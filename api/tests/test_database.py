import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.seed import initial_state
from api.storage import Store, digest, now


def test_schema_and_every_resource_uses_independent_table(tmp_path):
    store = Store(tmp_path)
    try:
        assert store.info()["tableCount"] == 49
        assert store.info()["schemaVersion"] == 3
        assert store.check() == {"integrity": ["ok"], "foreignKeyViolations": []}
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        counts = store.info()["tables"]
        assert counts["dataset_rows"] == 8
        assert counts["workflow_nodes"] == 5 and counts["workflow_edges"] == 4
        assert counts["workflow_node_rules"] == 2 and counts["quality_task_rules"] == 2
        assert counts["dictionary_items"] == 2 and counts["metadata_columns"] == 5
        assert not (tmp_path / "state.json").exists()
    finally:
        store.close()


def test_json_migration_is_backed_up_complete_and_idempotent(tmp_path):
    state = initial_state()
    state["users"]["local-admin"]["passwordHash"] = "original-password-hash"
    state["entities"]["services"]["service-1"] = {
        "id": "service-1",
        "name": "原服务",
        "datasetId": "demo-dataset",
        "published": True,
        "apiKeyHash": "original-key-hash",
    }
    run = {
        "id": "run-1",
        "name": "历史运行",
        "workflowId": "demo-workflow",
        "status": "SUCCESS",
        "actor": "admin",
        "startedAt": now(),
        "finishedAt": now(),
        "sourceCount": 8,
        "outputCount": 1,
        "rows": [{"code": "a"}],
        "steps": [
            {
                "nodeId": "n1",
                "name": "读取",
                "type": "source",
                "inputCount": 0,
                "outputCount": 8,
            }
        ],
        "reports": [
            {
                "nodeId": "n4",
                "nodeName": "检测",
                "total": 1,
                "invalidRows": 1,
                "validRows": 0,
                "passRate": 0,
                "rules": [
                    {
                        "id": "rule-required",
                        "name": "空值",
                        "type": "required",
                        "field": "org_name",
                        "total": 1,
                        "failed": 1,
                        "passed": 0,
                        "failedIndexes": [0],
                    }
                ],
            }
        ],
    }
    state["runs"]["run-1"] = run
    state["alerts"]["alert-1"] = {
        "id": "alert-1",
        "runId": "run-1",
        "name": "空值",
        "field": "org_name",
        "failed": 1,
        "status": "open",
        "createdAt": now(),
        "failedIndexes": [0],
    }
    state["audit"] = [
        {
            "id": "audit-1",
            "actor": "admin",
            "action": "test",
            "target": "run-1",
            "createdAt": now(),
        }
    ]
    source = tmp_path / "state.json"
    raw = json.dumps(state, ensure_ascii=False)
    source.write_text(raw, encoding="utf-8")
    store = Store(tmp_path)
    try:
        assert store.get_user("local-admin")["passwordHash"] == "original-password-hash"
        assert store.get("services", "service-1")["apiKeyHash"] == "original-key-hash"
        assert store.run("run-1")["rows"] == run["rows"]
        assert store.run("run-1")["reports"] == run["reports"]
        assert store.alert("alert-1")["failedIndexes"] == [0]
        assert len(store.audits()) == 1
        assert (
            list((tmp_path / "backups").glob("state-before-sqlite-*.json"))[
                0
            ].read_text(encoding="utf-8")
            == raw
        )
        store.save("elements", {"name": "后来修改"}, "demo-element")
    finally:
        store.close()
    # The old file becomes an archive and must not overwrite database changes.
    state["entities"]["elements"]["demo-element"]["name"] = "旧文件回写"
    source.write_text(json.dumps(state), encoding="utf-8")
    store = Store(tmp_path)
    try:
        assert store.get("elements", "demo-element")["name"] == "后来修改"
        assert store.info()["tables"]["job_result_rows"] == 1
        assert len(list((tmp_path / "backups").glob("state-before-sqlite-*.json"))) == 1
        assert store.check()["integrity"] == ["ok"]
    finally:
        store.close()


def test_failed_migration_rolls_back_all_records_and_can_retry(tmp_path):
    state = initial_state()
    state["entities"]["qualityTasks"]["demo-task"]["ruleIds"] = ["missing-rule"]
    source = tmp_path / "state.json"
    source.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(sqlite3.IntegrityError):
        Store(tmp_path)
    with sqlite3.connect(tmp_path / "platform.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM platform_users").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM datasets").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM platform_settings").fetchone()[0] == 0
    state["entities"]["qualityTasks"]["demo-task"]["ruleIds"] = ["rule-required"]
    source.write_text(json.dumps(state), encoding="utf-8")
    store = Store(tmp_path)
    assert store.get("qualityTasks", "demo-task")["ruleIds"] == ["rule-required"]
    store.close()


def test_update_children_and_constraints_are_transactional(tmp_path):
    store = Store(tmp_path)
    try:
        original = store.get("workflows", "demo-workflow")
        broken = copy.deepcopy(original)
        broken["name"] = "不能部分保存"
        broken["nodes"][-1]["type"] = "unknown"
        with pytest.raises(sqlite3.IntegrityError):
            store.save("workflows", broken, "demo-workflow")
        assert store.get("workflows", "demo-workflow") == original
        with pytest.raises(sqlite3.IntegrityError):
            store.remove("datasets", "demo-dataset")
        with pytest.raises(sqlite3.IntegrityError):
            store.remove("rules", "rule-required")
        assert store.get("datasets", "demo-dataset")["rows"]
        dictionary = store.get("dictionaries", "demo-dictionary")
        dictionary["dictionaryDetails"] = [{"code": "C", "name": "新代码"}]
        store.save("dictionaries", dictionary, dictionary["id"])
        assert (
            store.db.execute("SELECT count(*) FROM dictionary_items").fetchone()[0] == 1
        )
        assert store.check()["foreignKeyViolations"] == []
    finally:
        store.close()


def test_session_persistence_expiry_and_hash_only(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/local-session", headers={"Origin": "http://testserver"})
        token = client.cookies.get("gov_v3_session")
        with sqlite3.connect(tmp_path / "platform.sqlite3") as db:
            stored = db.execute("SELECT token_hash FROM platform_sessions").fetchone()[
                0
            ]
            assert stored == digest(token) and stored != token
    with TestClient(create_app(tmp_path)) as client:
        client.cookies.set("gov_v3_session", token)
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401
    store = Store(tmp_path)
    try:
        store.create_session("local-admin", "expired-token")
        store.db.execute("UPDATE platform_sessions SET expires_at=0")
        assert store.session("expired-token") is None
    finally:
        store.close()


def test_backup_and_readonly_management_do_not_interrupt_runs(tmp_path):
    store = Store(tmp_path)
    try:
        store.save_run(
            {
                "id": "active",
                "name": "任务",
                "status": "RUNNING",
                "actor": "admin",
                "startedAt": now(),
                "rows": [],
                "steps": [],
                "reports": [],
            }
        )
        manager = Store(tmp_path, initialize=False)
        try:
            destination = tmp_path / "backups" / "copy.sqlite3"
            manager.backup(destination)
            assert manager.run("active")["status"] == "RUNNING"
            with sqlite3.connect(destination) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert (
                    db.execute(
                        "SELECT status FROM job_runs WHERE id=?", ("active",)
                    ).fetchone()[0]
                    == "RUNNING"
                )
            with pytest.raises(ValueError):
                manager.backup(destination)
        finally:
            manager.close()
    finally:
        store.close()
    restarted = Store(tmp_path)
    try:
        assert restarted.run("active")["status"] == "INTERRUPTED"
    finally:
        restarted.close()


def test_concurrent_writes_and_sql_injection_values(tmp_path):
    store = Store(tmp_path)
    try:

        def write(index):
            return store.save(
                "projects",
                {
                    "name": (
                        "项目'); DROP TABLE projects; --"
                        if index == 0
                        else f"项目{index}"
                    )
                },
            )

        with ThreadPoolExecutor(max_workers=6) as executor:
            records = list(executor.map(write, range(20)))
        assert len(store.all("projects")) == 21
        assert store.get("projects", records[0]["id"])["name"].startswith("项目')")
        assert store.check()["integrity"] == ["ok"]
    finally:
        store.close()
