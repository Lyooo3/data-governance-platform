import json
import sqlite3
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.storage import Store
from api.local_store import LocalStore


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        assert (
            c.post(
                "/api/auth/local-session", headers={"Origin": "http://testserver"}
            ).status_code
            == 200
        )
        yield c


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def fixture_data(client):
    return data(
        client.post(
            "/api/governance/datasets",
            json={
                "name": "测试输入",
                "rows": [
                    {
                        "id": 1,
                        "from": "A",
                        "to": "B",
                        "amount": 0.1,
                        "category": "A",
                        "updated": "2026-10-14T22:00:00+08:00",
                    },
                    {
                        "id": 2,
                        "from": "B",
                        "to": "C",
                        "amount": 0.2,
                        "category": "X",
                        "updated": "2026-10-10T00:00:00+08:00",
                    },
                    {
                        "id": 3,
                        "from": "A",
                        "to": "B",
                        "amount": 0.3,
                        "category": "B",
                        "updated": "bad",
                    },
                ],
            },
        )
    )


def test_version_two_preserves_existing_version_one_records(tmp_path):
    connection = sqlite3.connect(tmp_path / "platform.sqlite3")
    connection.executescript(
        (Path(__file__).resolve().parents[2] / "db/schema.sql").read_text(
            encoding="utf8"
        )
    )
    connection.execute(
        "INSERT INTO platform_settings VALUES (?,?,?)",
        ("initialization_complete", "true", "2026-01-01"),
    )
    connection.execute(
        "INSERT INTO projects VALUES (?,?,?,?,?,?)",
        ("legacy", "原有项目", "OLD", "2026", "2026", json.dumps({"name": "原有项目"})),
    )
    connection.commit()
    connection.close()
    store = Store(tmp_path)
    try:
        assert store.get("projects", "legacy")["name"] == "原有项目"
        assert store.info()["schemaVersion"] == 3 and store.info()["tableCount"] == 49
        assert "view_id" in {
            r[1] for r in store.db.execute("PRAGMA table_info(data_services)")
        }
        assert store.check()["foreignKeyViolations"] == []
    finally:
        store.close()


def test_real_local_analysis_and_copy_outputs(client):
    dataset = fixture_data(client)
    element = data(
        client.post(
            "/api/governance/elements",
            json={"name": "金额", "field": "amount", "dataType": "number"},
        )
    )
    dictionary = data(
        client.post(
            "/api/governance/dictionaries",
            json={
                "name": "类型代码",
                "dictionaryDetails": [
                    {"code": "A", "name": "甲"},
                    {"code": "B", "name": "乙"},
                ],
            },
        )
    )
    common = {"datasetId": dataset["id"], "name": "测试报告"}
    standard = data(
        client.post(
            "/api/local/analyze/standard",
            json={**common, "elementIds": [element["id"]]},
        )
    )
    assert standard["metrics"] == {"standards": 1, "passed": 1, "failed": 0}
    codes = data(
        client.post(
            "/api/local/analyze/code",
            json={
                **common,
                "dictionaryId": dictionary["id"],
                "field": "category",
                "apply": True,
            },
        )
    )
    assert codes["metrics"] == {"total": 3, "matched": 2, "unmatched": 1}
    copied = data(client.get("/api/governance/datasets/" + codes["outputDatasetId"]))
    assert [r["category_name"] for r in copied["rows"]] == ["甲", None, "乙"]
    assert (
        "category_name"
        not in data(client.get("/api/governance/datasets/" + dataset["id"]))["rows"][0]
    )
    timely = data(
        client.post(
            "/api/local/analyze/timeliness",
            json={
                **common,
                "field": "updated",
                "maxAgeHours": 24,
                "referenceTime": "2026-10-15T00:00:00+08:00",
            },
        )
    )
    assert timely["metrics"] == {
        "total": 3,
        "timely": 1,
        "stale": 1,
        "invalid": 1,
        "future": 0,
    }
    relations = data(
        client.post(
            "/api/local/analyze/relations",
            json={**common, "fromField": "from", "toField": "to"},
        )
    )
    assert relations["metrics"]["nodes"] == 3 and relations["metrics"]["edges"] == 2
    funds = data(
        client.post(
            "/api/local/analyze/funds",
            json={
                **common,
                "fromField": "from",
                "toField": "to",
                "amountField": "amount",
            },
        )
    )
    assert funds["metrics"]["totalAmount"] == 0.6
    assert next(r for r in funds["rows"] if r["entity"] == "A")["net"] == -0.4
    operated = data(
        client.post(
            "/api/local/analyze/operate",
            json={
                **common,
                "action": "filter",
                "config": {"field": "amount", "operator": "gt", "value": 0.1},
            },
        )
    )
    assert operated["metrics"]["output"] == 2


def test_approval_changes_version_and_rejects_stale_review(client):
    element = data(
        client.post(
            "/api/governance/elements",
            json={"name": "审核对象", "field": "id", "dataType": "integer"},
        )
    )
    request = data(
        client.post(
            "/api/local/approvals",
            json={
                "targetKind": "elements",
                "targetId": element["id"],
                "reason": "检查",
            },
        )
    )
    assert (
        client.post(
            "/api/local/approvals",
            json={"targetKind": "elements", "targetId": element["id"]},
        ).status_code
        == 422
    )
    data(
        client.put(
            "/api/governance/elements/" + element["id"], json={"name": "对象已变更"}
        )
    )
    assert (
        client.post(
            "/api/local/action/approvals/" + request["id"] + "/approve", json={}
        ).status_code
        == 422
    )
    data(
        client.post(
            "/api/local/action/approvals/" + request["id"] + "/withdraw", json={}
        )
    )
    current = data(
        client.post(
            "/api/local/approvals",
            json={"targetKind": "elements", "targetId": element["id"]},
        )
    )
    approved = data(
        client.post(
            "/api/local/action/approvals/" + current["id"] + "/approve",
            json={"note": "通过"},
        )
    )
    assert approved["status"] == "approved"
    assert (
        data(client.get("/api/governance/elements/" + element["id"]))["approvalStatus"]
        == "approved"
    )
    changed = data(
        client.put(
            "/api/governance/elements/" + element["id"], json={"description": "新版本"}
        )
    )
    assert changed["approvalStatus"] == "draft"


def test_view_service_contract_app_grants_and_revocation(client):
    dataset = fixture_data(client)
    view = data(
        client.post(
            "/api/local/records/views",
            json={
                "name": "金额视图",
                "datasetId": dataset["id"],
                "fields": ["id", "amount"],
                "filters": [{"field": "amount", "operator": "gt", "value": 0.1}],
            },
        )
    )
    preview = data(
        client.post("/api/local/action/views/" + view["id"] + "/preview", json={})
    )
    assert len(preview["rows"]) == 2 and set(preview["rows"][0]) == {"id", "amount"}
    service = data(
        client.post(
            "/api/governance/services",
            json={"name": "视图服务", "viewId": view["id"], "fields": ["amount"]},
        )
    )
    published = data(
        client.post("/api/governance/services/" + service["id"] + "/publish", json={})
    )
    assert (
        len(
            data(
                client.get(
                    published["endpoint"], headers={"X-API-Key": published["apiKey"]}
                )
            )["list"]
        )
        == 2
    )
    contract = data(client.get("/api/local/contracts/" + service["id"]))
    assert (
        contract["x-fields"] == ["amount"]
        and "AppKey" in contract["components"]["securitySchemes"]
    )
    app = data(
        client.post(
            "/api/local/records/apps", json={"name": "测试应用", "enabled": True}
        )
    )
    assert "apiKey" in app and "apiKeyHash" not in app
    assert "apiKeyHash" not in json.dumps(data(client.get("/api/local/records/apps")))
    assert (
        client.get(
            published["endpoint"], headers={"X-App-Key": app["apiKey"]}
        ).status_code
        == 403
    )
    grant = data(
        client.post(
            "/api/local/grants", json={"appId": app["id"], "serviceId": service["id"]}
        )
    )
    data(client.post("/api/local/action/grants/" + grant["id"] + "/approve", json={}))
    assert set(
        data(client.get(published["endpoint"], headers={"X-App-Key": app["apiKey"]}))[
            "list"
        ][0]
    ) == {"amount"}
    data(client.post("/api/local/action/apps/" + app["id"] + "/disable", json={}))
    assert (
        client.get(
            published["endpoint"], headers={"X-App-Key": app["apiKey"]}
        ).status_code
        == 403
    )
    data(client.post("/api/local/action/apps/" + app["id"] + "/enable", json={}))
    data(client.post("/api/local/action/grants/" + grant["id"] + "/revoke", json={}))
    assert (
        client.get(
            published["endpoint"], headers={"X-App-Key": app["apiKey"]}
        ).status_code
        == 403
    )
    assert client.delete("/api/local/records/views/" + view["id"]).status_code == 409


def test_adapter_accepts_actual_payload_and_rejects_missing_fields(client):
    dataset = fixture_data(client)
    adapter = data(
        client.post(
            "/api/local/records/adapters",
            json={
                "name": "接口适配",
                "datasetId": dataset["id"],
                "mappings": [
                    {"from": "id", "to": "record_id"},
                    {"from": "amount", "to": "value"},
                ],
            },
        )
    )
    replay = data(
        client.post("/api/local/action/adapters/" + adapter["id"] + "/replay", json={})
    )
    assert replay["metrics"] == {"received": 3, "saved": 3}
    received = data(
        client.post(
            "/api/local/adapters/" + adapter["id"] + "/receive",
            json={"rows": [{"id": 99, "amount": 12.5}]},
        )
    )
    assert received["rows"] == [{"record_id": 99, "value": 12.5}]
    assert (
        client.post(
            "/api/local/adapters/" + adapter["id"] + "/receive",
            json={"rows": [{"other": 1}]},
        ).status_code
        == 422
    )


def test_subscription_diff_delivery_retry_and_idempotence(client):
    dataset = fixture_data(client)
    channel = data(
        client.post(
            "/api/local/records/channels",
            json={"name": "测试通道", "recipient": "本地验收", "enabled": False},
        )
    )
    subscription = data(
        client.post(
            "/api/local/records/subscriptions",
            json={
                "name": "测试订阅",
                "datasetId": dataset["id"],
                "keys": ["id"],
                "channelId": channel["id"],
                "enabled": False,
                "intervalSeconds": 60,
            },
        )
    )
    altered = data(client.get("/api/governance/datasets/" + dataset["id"]))["rows"]
    altered[0]["amount"] = 9
    altered.pop(1)
    altered.append({**altered[0], "id": 4})
    data(
        client.put("/api/governance/datasets/" + dataset["id"], json={"rows": altered})
    )
    report = data(
        client.post(
            "/api/local/action/subscriptions/" + subscription["id"] + "/compare",
            json={},
        )
    )
    assert report["metrics"] == {"insert": 1, "update": 1, "delete": 1}
    unchanged = data(
        client.post(
            "/api/local/action/subscriptions/" + subscription["id"] + "/compare",
            json={},
        )
    )
    assert unchanged["metrics"] == {"insert": 0, "update": 0, "delete": 0}
    deliveries = data(client.get("/api/local/records/deliveries"))["list"]
    assert len(deliveries) == 3
    assert (
        data(
            client.post(
                "/api/local/action/deliveries/" + deliveries[0]["id"] + "/deliver",
                json={},
            )
        )["status"]
        == "failed"
    )
    data(
        client.post("/api/local/action/channels/" + channel["id"] + "/enable", json={})
    )
    for delivery in deliveries:
        assert (
            data(
                client.post(
                    "/api/local/action/deliveries/" + delivery["id"] + "/deliver",
                    json={},
                )
            )["status"]
            == "delivered"
        )
        assert (
            data(
                client.post(
                    "/api/local/action/deliveries/" + delivery["id"] + "/deliver",
                    json={},
                )
            )["status"]
            == "delivered"
        )
    assert len(data(client.get("/api/local/records/inbox"))["list"]) == 3
    assert client.delete("/api/governance/datasets/" + dataset["id"]).status_code == 409


def test_scheduler_automatically_executes_due_job_and_pause_persists(client):
    schedule = data(
        client.post(
            "/api/local/records/schedules",
            json={
                "name": "后台计划",
                "workflowId": "demo-workflow",
                "intervalSeconds": 60,
                "enabled": True,
            },
        )
    )
    local = client.app.state.local
    local.repo.save("schedules", {"nextRunAt": time.time() - 1}, schedule["id"])
    for _ in range(100):
        current = data(client.get("/api/local/records/schedules/" + schedule["id"]))
        if current.get("lastRunId"):
            break
        time.sleep(0.03)
    assert current.get("lastRunId")
    paused = data(
        client.post(
            "/api/local/action/schedules/" + schedule["id"] + "/disable", json={}
        )
    )
    assert paused["enabled"] is False
    for _ in range(100):
        run = data(client.get("/api/governance/runs/" + current["lastRunId"]))
        if run["status"] != "RUNNING":
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCESS"
    assert data(client.get("/api/local/chain"))["total"] >= 1
    lineage = data(client.get("/api/local/lineage"))
    assert len(lineage["nodes"]) >= 7 and lineage["edges"]


def test_reader_cannot_modify_extensions_or_read_other_app_secrets(client):
    user = data(
        client.post(
            "/api/auth/users",
            json={"name": "reader", "password": "reader-acceptance", "role": "reader"},
        )
    )
    data(
        client.post(
            "/api/local/records/apps", json={"name": "管理员应用", "enabled": True}
        )
    )
    data(client.post("/api/auth/logout"))
    data(
        client.post(
            "/api/auth/login", json={"name": "reader", "password": "reader-acceptance"}
        )
    )
    assert data(client.get("/api/local/records/apps"))["total"] == 0
    assert (
        client.post("/api/local/records/views", json={"name": "禁止写入"}).status_code
        == 403
    )
    assert client.post("/api/local/analyze/code", json={}).status_code == 403
    assert client.get("/api/local/records/inbox").status_code == 403
    assert (
        client.post("/api/local/action/approvals/missing/approve", json={}).status_code
        == 403
    )
