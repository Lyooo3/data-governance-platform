import copy
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.engine import execute, quality, validate
from api import config


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


def wait_run(client, key):
    for _ in range(200):
        run = data(client.get("/api/governance/runs/" + key))
        if run["status"] != "RUNNING":
            return run
        time.sleep(0.03)
    raise AssertionError("run did not finish")


def test_health_platform_database_auth_and_origin(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        health = data(c.get("/api/health"))
        assert health["backend"] == "fastapi" and health["databaseConfigured"] is False
        assert health["storage"] == "sqlite"
        assert health["platformDatabase"]["configured"] is True
        assert (tmp_path / "platform.sqlite3").is_file()
        assert c.get("/api/governance/rules").status_code == 401
        assert c.post("/api/auth/local-session").status_code == 403
        assert (
            c.post(
                "/api/auth/local-session",
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert c.get("/api/not-a-route").status_code == 404
        assert c.get("/openapi.json").status_code == 200


def test_crud_search_pagination_and_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        c.post("/api/auth/local-session", headers={"Origin": "http://testserver"})
        record = data(
            c.post(
                "/api/governance/elements",
                json={"name": "新数据元", "field": "unit", "code": "T-1"},
            )
        )
        assert data(c.get("/api/governance/elements?search=T-1"))["total"] == 1
        assert len(data(c.get("/api/governance/elements?pageSize=1"))["list"]) == 1
        assert (
            data(
                c.put(
                    "/api/governance/elements/" + record["id"],
                    json={"name": "修改数据元"},
                )
            )["name"]
            == "修改数据元"
        )
    with TestClient(create_app(tmp_path)) as c:
        c.post("/api/auth/local-session", headers={"Origin": "http://testserver"})
        assert (
            data(c.get("/api/governance/elements/" + record["id"]))["name"]
            == "修改数据元"
        )
        assert c.delete("/api/governance/elements/" + record["id"]).status_code == 200
        assert c.get("/api/governance/elements/" + record["id"]).status_code == 404


def test_database_draft_never_connects(client):
    assert data(client.get("/api/governance/sources"))["total"] == 0
    source = data(
        client.post(
            "/api/governance/sources",
            json={
                "name": "未来MySQL",
                "type": "mysql",
                "host": "127.0.0.1",
                "port": 3306,
                "database": "training",
                "user": "reader",
            },
        )
    )
    assert source["connectionStatus"] == "untested"
    assert (
        client.post(f'/api/governance/sources/{source["id"]}/test', json={}).status_code
        == 501
    )
    assert (
        client.post(
            "/api/governance/sources",
            json={"name": "禁止密码", "type": "mysql", "password": "not-stored"},
        ).status_code
        == 422
    )


def test_real_sample_workflow_reports_alerts_and_export(client):
    run = data(client.post("/api/governance/workflows/demo-workflow/run", json={}))
    done = wait_run(client, run["id"])
    assert done["status"] == "SUCCESS"
    assert (
        done["sourceCount"],
        done["outputCount"],
        done["reports"][0]["invalidRows"],
    ) == (8, 7, 2)
    assert done["reports"][0]["passRate"] == 71.43
    assert len(done["steps"]) == 5
    assert (
        data(client.get(f'/api/governance/runs/{run["id"]}/rows?pageSize=2'))["total"]
        == 7
    )
    csv = client.get(f'/api/governance/runs/{run["id"]}/export')
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    alerts = data(client.get("/api/governance/alerts"))["list"]
    assert len(alerts) == 2
    detail = data(client.get("/api/governance/alerts/" + alerts[0]["id"]))
    assert detail["runId"] == run["id"]
    assert (
        data(
            client.post(
                f'/api/governance/alerts/{detail["id"]}/resolve',
                json={"note": "完成核查"},
            )
        )["status"]
        == "resolved"
    )
    summary = data(client.get("/api/governance/summary"))
    assert summary["today"]["success"] == 1 and summary["openAlerts"] == 1


def test_quality_task_checks_original_rows(client):
    run = data(client.post("/api/governance/qualityTasks/demo-task/run", json={}))
    done = wait_run(client, run["id"])
    assert done["status"] == "SUCCESS" and done["outputCount"] == 8
    assert done["reports"][0]["invalidRows"] == 2


def test_rules_validation_and_reference_integrity(client):
    assert (
        client.post(
            "/api/governance/rules",
            json={
                "name": "错误规则",
                "type": "regex",
                "field": "score",
                "pattern": "[",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/governance/rules",
            json={
                "name": "错误范围",
                "type": "range",
                "field": "score",
                "min": 10,
                "max": 1,
            },
        ).status_code
        == 422
    )
    assert client.delete("/api/governance/rules/rule-required").status_code == 409
    assert client.delete("/api/governance/datasets/demo-dataset").status_code == 409
    workflow = data(client.get("/api/governance/workflows/demo-workflow"))
    workflow["edges"].append({"source": "n3", "target": "n1"})
    assert (
        client.put("/api/governance/workflows/demo-workflow", json=workflow).status_code
        == 422
    )
    assert (
        client.get("/api/governance/workflows/getUnsupportedAction").status_code == 404
    )


def test_reader_permissions_and_logout(client):
    user = data(
        client.post(
            "/api/auth/users",
            json={"name": "reader", "password": "reader-password", "role": "reader"},
        )
    )
    assert "passwordHash" not in user
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"name": "reader", "password": "incorrect"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"name": "reader", "password": "reader-password"}
        ).status_code
        == 200
    )
    assert client.get("/api/governance/rules").status_code == 200
    assert (
        client.post("/api/governance/elements", json={"name": "禁止新增"}).status_code
        == 403
    )
    assert (
        client.post("/api/governance/workflows/demo-workflow/run", json={}).status_code
        == 403
    )
    assert client.get("/api/governance/audit").status_code == 403


def test_service_secret_field_whitelist_rotation_and_unpublish(client):
    service = data(
        client.post(
            "/api/governance/services",
            json={
                "name": "样例查询",
                "datasetId": "demo-dataset",
                "fields": ["org_name"],
            },
        )
    )
    published = data(
        client.post(f'/api/governance/services/{service["id"]}/publish', json={})
    )
    assert client.get(published["endpoint"]).status_code == 403
    result = data(
        client.get(published["endpoint"], headers={"X-API-Key": published["apiKey"]})
    )
    assert result["total"] == 8 and set(result["list"][0]) == {"org_name"}
    assert "apiKeyHash" not in data(
        client.get("/api/governance/services/" + service["id"])
    )
    newer = data(
        client.post(f'/api/governance/services/{service["id"]}/publish', json={})
    )
    assert (
        client.get(
            published["endpoint"], headers={"X-API-Key": published["apiKey"]}
        ).status_code
        == 403
    )
    assert (
        client.get(
            newer["endpoint"], headers={"X-API-Key": newer["apiKey"]}
        ).status_code
        == 200
    )
    client.put("/api/governance/services/" + service["id"], json={"name": "已修改"})
    assert (
        client.get(
            newer["endpoint"], headers={"X-API-Key": newer["apiKey"]}
        ).status_code
        == 404
    )


def test_worker_timeout_cancellation_and_responsive_api(client, monkeypatch):
    dataset = data(
        client.post(
            "/api/governance/datasets",
            json={"name": "超时样例", "rows": [{"text": "a" * 200 + "!"}]},
        )
    )
    rule = data(
        client.post(
            "/api/governance/rules",
            json={
                "name": "耗时表达式",
                "type": "regex",
                "field": "text",
                "pattern": "^(a+)+$",
            },
        )
    )
    workflow = {
        "name": "超时流程",
        "nodes": [
            {"id": "a", "type": "source", "config": {"datasetId": dataset["id"]}},
            {"id": "b", "type": "quality", "config": {"ruleIds": [rule["id"]]}},
            {"id": "c", "type": "output", "config": {}},
        ],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
    }
    saved = data(client.post("/api/governance/workflows", json=workflow))
    monkeypatch.setattr(config, "JOB_TIMEOUT", 0.3)
    run = data(client.post(f'/api/governance/workflows/{saved["id"]}/run', json={}))
    assert client.get("/api/governance/summary").status_code == 200
    assert wait_run(client, run["id"])["status"] == "TIMED_OUT"
    monkeypatch.setattr(config, "JOB_TIMEOUT", 5)
    second = data(client.post(f'/api/governance/workflows/{saved["id"]}/run', json={}))
    assert (
        client.post(f'/api/governance/runs/{second["id"]}/cancel', json={}).status_code
        == 200
    )
    assert wait_run(client, second["id"])["status"] == "CANCELLED"


def test_dataset_validation_csv_injection_and_empty_report(client):
    assert (
        client.post(
            "/api/governance/datasets",
            json={"name": "不一致", "rows": [{"a": 1}, {"b": 2}]},
        ).status_code
        == 422
    )
    dataset = data(
        client.post(
            "/api/governance/datasets",
            json={"name": "CSV示例", "rows": [{"text": "=1+1"}]},
        )
    )
    workflow = data(
        client.post(
            "/api/governance/workflows",
            json={
                "name": "CSV流程",
                "nodes": [
                    {
                        "id": "a",
                        "type": "source",
                        "config": {"datasetId": dataset["id"]},
                    },
                    {"id": "b", "type": "output", "config": {}},
                ],
                "edges": [{"source": "a", "target": "b"}],
            },
        )
    )
    run = data(client.post(f'/api/governance/workflows/{workflow["id"]}/run', json={}))
    assert wait_run(client, run["id"])["status"] == "SUCCESS"
    assert "'=1+1" in client.get(f'/api/governance/runs/{run["id"]}/export').text
    report, invalid = quality(
        [], [{"name": "非空", "type": "required", "field": "text"}]
    )
    assert report["passRate"] is None and not invalid


def test_spa_routes_only_serve_new_frontend(client):
    for path in ("/home", "/quality/overview", "/develop/flows", "/workbench"):
        response = client.get(path)
        assert response.status_code == 200 and 'id="app"' in response.text
        assert "/dist/js/" not in response.text and "iframe" not in response.text
    assert client.get("/.data-v3/state.json").status_code == 404
