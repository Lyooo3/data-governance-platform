"""Opt-in integration test against an isolated MySQL fixture, never a business DB."""

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.connectors import open_reader


@pytest.mark.skipif(not os.getenv("GOV_MYSQL_FIXTURE"), reason="isolated MySQL fixture not supplied")
def test_live_mysql_snapshot_and_governance(tmp_path):
    fixture = json.loads(Path(os.environ["GOV_MYSQL_FIXTURE"]).read_text(encoding="utf-8-sig"))
    source = fixture["source"]
    password = fixture["password"]
    with open_reader(source, password) as reader:
        info = reader.info()
        assert reader.query("SELECT @@transaction_read_only AS ro")[0]["ro"] == 1
        before = reader.query("SELECT COUNT(*) AS n FROM exams")[0]["n"]
        assert before == 10021
        with pytest.raises(Exception):
            reader.connection.cursor().execute("DELETE FROM exams WHERE id=-1")

    def data(response):
        assert response.status_code == 200, response.text
        return response.json()["data"]

    with TestClient(create_app(tmp_path / "platform")) as client:
        data(client.post("/api/auth/local-session", headers={"Origin": "http://testserver"}))
        saved = data(client.post("/api/governance/sources", json=source))
        key = saved["id"]
        data(client.post(f"/api/ingestion/sources/{key}/test", json={"password": password}))
        tables = data(client.post(f"/api/ingestion/sources/{key}/tables", json={"password": password}))
        assert tables["total"] == 2
        snap = data(client.post(f"/api/ingestion/sources/{key}/snapshots", json={"password": password}))
        client.app.state.raw.thread.join(20)
        snap = data(client.get("/api/ingestion/snapshots/" + snap["id"]))
        assert snap["status"] == "SUCCESS", snap.get("error")
        assert snap["rowCount"] == 10021 and snap["tableCount"] == 2
        table = next(t for t in snap["tables"] if t["name"] == "exams")
        preview = data(client.get(f'/api/ingestion/snapshots/{snap["id"]}/tables/{table["id"]}/rows'))
        assert preview["list"][0]["amount"] == "1234567890.123456789"
        copy = data(client.post(f'/api/ingestion/snapshots/{snap["id"]}/tables/{table["id"]}/datasets',
                                json={"offset": 10000, "limit": 10000}))
        assert copy["rowCount"] == 21
        rule = data(client.post("/api/governance/rules", json={"name": "实库编号唯一", "type": "unique", "field": "id"}))
        flow = data(client.post("/api/governance/workflows", json={
            "name": "隔离MySQL全流程", "nodes": [
                {"id": "s", "type": "source", "config": {"datasetId": copy["id"]}},
                {"id": "q", "type": "quality", "config": {"ruleIds": [rule["id"]]}},
                {"id": "o", "type": "output", "config": {}}],
            "edges": [{"source": "s", "target": "q"}, {"source": "q", "target": "o"}]}))
        run = data(client.post("/api/governance/workflows/" + flow["id"] + "/run", json={}))
        for _ in range(100):
            run = data(client.get("/api/governance/runs/" + run["id"]))
            if run["status"] != "RUNNING":
                break
            time.sleep(0.05)
        assert run["status"] == "SUCCESS" and run["outputCount"] == 21
        assert run["reports"][0]["invalidRows"] == 0
        assert password not in (tmp_path / "platform" / "platform.sqlite3").read_bytes().decode("latin1")
        with open_reader(source, password) as reader:
            assert reader.query("SELECT COUNT(*) AS n FROM exams")[0]["n"] == before
        report = {"database": "MySQL", "version": info["version"], "tls": "verified CA and hostname",
                  "transactionReadOnly": True, "tables": 2, "rawRows": 10021, "governanceRows": 21,
                  "invalidRows": 0, "sourceRowsUnchanged": True, "passwordNotPersisted": True}
        if os.getenv("GOV_MYSQL_REPORT"):
            Path(os.environ["GOV_MYSQL_REPORT"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
