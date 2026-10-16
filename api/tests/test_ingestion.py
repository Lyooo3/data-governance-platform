import copy
import json
import threading
from contextlib import contextmanager
import psycopg
import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api import connectors, raw_store

SOURCE = {
    "name": "隔离采集",
    "type": "postgresql",
    "host": "127.0.0.1",
    "port": 5432,
    "database": "training",
    "user": "reader",
}
PASSWORD = "only-in-request-not-saved"
COLS = [
    {
        "name": name,
        "native_type": kind,
        "type": kind,
        "nullable": True,
        "primary_key": name == "id",
    }
    for name, kind in [
        ("id", "int8"),
        ("score", "numeric"),
        ("active", "bool"),
        ("details", "jsonb"),
    ]
]


class Reader:
    connection = None

    def info(self):
        return {
            "database": "training",
            "version": "16",
            "read_only": "on",
            "isolation": "repeatable read",
        }

    def tables(self):
        return [
            {
                "oid": 1,
                "schema": "public",
                "name": "exam",
                "estimated_rows": 0,
                "comment": "考试",
            },
            {
                "oid": 2,
                "schema": "public",
                "name": "empty",
                "estimated_rows": 0,
                "comment": None,
            },
        ]

    def describe(self, table):
        return {**table, "columns": copy.deepcopy(COLS)}

    def batches(self, table):
        if table["oid"] == 1:
            for start in range(0, 10005, 500):
                yield [
                    {
                        "id": str(i),
                        "score": "0.10",
                        "active": "true",
                        "details": '{"kind":"exam"}',
                    }
                    for i in range(start, min(10005, start + 500))
                ]


@pytest.fixture
def client(tmp_path, monkeypatch):
    @contextmanager
    def fake(source, password):
        assert password == PASSWORD
        yield Reader()

    monkeypatch.setattr(raw_store, "open_reader", fake)
    import api.ingestion_api as api

    monkeypatch.setattr(api, "open_reader", fake)
    with TestClient(create_app(tmp_path)) as c:
        c.post("/api/auth/local-session", headers={"Origin": "http://testserver"})
        yield c


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def source(client):
    return data(client.post("/api/governance/sources", json=SOURCE))


def capture(client, src, tables=None):
    snap = data(
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/snapshots",
            json={"password": PASSWORD, "tables": tables},
        )
    )
    client.app.state.raw.thread.join(timeout=5)
    return data(client.get("/api/ingestion/snapshots/" + snap["id"]))


def test_readonly_catalog_cursor_quoting_and_rollback(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, query):
            self.query = query.as_string(None)

        def fetchmany(self, n):
            return []

    class Connection:
        read_only = False
        isolation_level = None
        rolled = False
        closed = False
        cursor_args = None

        def cursor(self, **kw):
            self.cursor_args = kw
            return cursor

        def rollback(self):
            self.rolled = True

        def close(self):
            self.closed = True

    conn, cursor = Connection(), Cursor()
    args = {}

    def connect(**kw):
        args.update(kw)
        return conn

    monkeypatch.setattr(connectors.psycopg, "connect", connect)
    with connectors.PostgresReader(SOURCE, PASSWORD) as reader:
        assert (
            conn.read_only is True
            and conn.isolation_level == psycopg.IsolationLevel.REPEATABLE_READ
        )
        assert (
            list(
                reader.batches(
                    {
                        "schema": 'p"x',
                        "name": "exam; DROP TABLE x",
                        "columns": [{"name": 'i"d'}],
                    }
                )
            )
            == []
        )
        assert '"p""x"."exam; DROP TABLE x"' in cursor.query
        assert '"i""d"::text AS "i""d"' in cursor.query
    assert (
        args["dbname"] == "training"
        and "default_transaction_read_only=on" in args["options"]
    )
    assert (
        conn.rolled
        and conn.closed
        and args["password"] == PASSWORD
        and conn.cursor_args["name"] == "snapshot_rows"
    )
    with pytest.raises(ValueError):
        connectors.source_config({**SOURCE, "host": "http://127.0.0.1"})


def test_full_snapshot_over_10000_rows_offline_immutable_and_provenance(
    client, monkeypatch
):
    src = source(client)
    info = data(
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/test", json={"password": PASSWORD}
        )
    )
    assert info["read_only"] == "on"
    assert data(client.get("/api/health"))["databaseConfigured"] is True
    assert (
        data(
            client.post(
                "/api/ingestion/sources/" + src["id"] + "/tables",
                json={"password": PASSWORD},
            )
        )["total"]
        == 2
    )
    snap = capture(client, src)
    assert (
        snap["status"] == "SUCCESS"
        and snap["rowCount"] == 10005
        and snap["tableCount"] == 2
    )
    manager = client.app.state.raw
    target = snap["tables"][0]
    exam = next(t for t in snap["tables"] if t["name"] == "exam")

    @contextmanager
    def offline(*_):
        raise AssertionError("Local reads must not connect")
        yield

    monkeypatch.setattr(raw_store, "open_reader", offline)
    raw = data(
        client.get(
            f'/api/ingestion/snapshots/{snap["id"]}/tables/{exam["id"]}/rows?pageNum=501&pageSize=20'
        )
    )
    assert len(raw["list"]) == 5 and raw["list"][0]["id"] == "10000"
    assert raw["list"][0]["score"] == "0.10" and raw["list"][0]["active"] == "true"
    copy_result = data(
        client.post(
            f'/api/ingestion/snapshots/{snap["id"]}/tables/{exam["id"]}/datasets',
            json={"fields": ["id", "score", "active"], "offset": 10000, "limit": 10000},
        )
    )
    assert copy_result["rowCount"] == 5
    local = data(client.get("/api/governance/datasets/" + copy_result["id"]))
    assert local["rows"][0] == {"id": 10000, "score": 0.1, "active": True}
    assert local["rawOrigin"]["sourceRowCount"] == 10005
    lineage = data(client.get("/api/local/lineage"))
    assert any(n["kind"] == "raw-table" for n in lineage["nodes"])
    assert (
        client.put("/api/ingestion/snapshots/" + snap["id"], json={}).status_code == 404
    )
    assert client.delete("/api/governance/sources/" + src["id"]).status_code == 409
    assert (
        client.get("/api/ingestion/snapshots/" + snap["id"] + "/download").status_code
        == 200
    )
    all_response = json.dumps(
        [snap, data(client.get("/api/governance/sources")), lineage]
    )
    assert PASSWORD not in all_response
    assert PASSWORD.encode() not in manager.path(snap["id"]).read_bytes()


def test_failure_does_not_publish_partial_data(client, monkeypatch):
    monkeypatch.setattr(raw_store, "MAX_RAW_BYTES", 80)
    snap = capture(client, source(client))
    assert snap["status"] == "FAILED" and snap["tables"] == []
    assert not client.app.state.raw.path(snap["id"]).exists()
    assert not client.app.state.raw.path(snap["id"], True).exists()
    assert (
        client.get("/api/ingestion/snapshots/" + snap["id"] + "/download").status_code
        == 422
    )


def test_cancel_and_single_capture_lock(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Slow(Reader):
        def batches(self, table):
            entered.set()
            release.wait(3)
            yield [{"id": "1", "score": "1", "active": "true", "details": "{}"}]

    @contextmanager
    def slow(*_):
        yield Slow()

    monkeypatch.setattr(raw_store, "open_reader", slow)
    src = source(client)
    snap = data(
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/snapshots",
            json={"password": PASSWORD},
        )
    )
    assert entered.wait(2)
    assert (
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/snapshots",
            json={"password": PASSWORD},
        ).status_code
        == 422
    )
    data(client.post("/api/ingestion/snapshots/" + snap["id"] + "/cancel", json={}))
    release.set()
    client.app.state.raw.thread.join(3)
    done = data(client.get("/api/ingestion/snapshots/" + snap["id"]))
    assert done["status"] == "CANCELLED" and not done["tables"]


def test_materialization_validation_and_preserving_large_values(client):
    snap = capture(client, source(client), [1])
    table = snap["tables"][0]
    path = f'/api/ingestion/snapshots/{snap["id"]}/tables/{table["id"]}/datasets'
    for body in [
        {"limit": 10001},
        {"offset": -1},
        {"offset": 20000},
        {"fields": ["unknown"]},
        {"fields": [{}]},
        {"fields": ["id", "id"]},
    ]:
        assert client.post(path, json=body).status_code == 422
    assert (
        raw_store.normalized("9223372036854775807", {"native_type": "int8"})
        == "9223372036854775807"
    )
    assert (
        raw_store.normalized("1234567890.123456789", {"native_type": "numeric"})
        == "1234567890.123456789"
    )
    assert raw_store.normalized("NaN", {"native_type": "float8"}) == "NaN"


def test_restart_preserves_completed_and_marks_active_interrupted(client):
    src = source(client)
    snap = capture(client, src)
    manager = client.app.state.raw
    assert (
        raw_store.RawManager(client.app.state.store).get(snap["id"])["status"]
        == "SUCCESS"
    )
    manager.patch(snap["id"], status="RUNNING")
    restarted = raw_store.RawManager(client.app.state.store)
    assert restarted.get(snap["id"])["status"] == "INTERRUPTED"
    assert restarted.get(snap["id"])["error"]


def test_platform_backup_includes_immutable_raw_files(client, tmp_path):
    from api.database_cli import backup_raw_files

    snap = capture(client, source(client))
    store = client.app.state.store
    target = store.backup(tmp_path / "backup.sqlite3")
    result = backup_raw_files(store, target)
    assert result["rawSnapshots"] == 1
    from pathlib import Path

    raw_file = Path(result["rawDirectory"]) / (snap["id"] + ".sqlite3")
    assert raw_file.read_bytes() == client.app.state.raw.path(snap["id"]).read_bytes()


def test_selected_table_stale_or_invalid_credentials_never_publishes(client):
    src = source(client)
    snap = capture(client, src, [9999])
    assert snap["status"] == "FAILED" and not snap["tables"]
    assert (
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/snapshots",
            json={"password": PASSWORD, "tables": []},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/test", json={}
        ).status_code
        == 422
    )


def test_reader_cannot_access_remote_or_raw_data(client):
    src = source(client)
    snap = capture(client, src)
    data(
        client.post(
            "/api/auth/users",
            json={"name": "reader", "password": "Reader!123456", "role": "reader"},
        )
    )
    data(
        client.post(
            "/api/auth/login", json={"name": "reader", "password": "Reader!123456"}
        )
    )
    assert client.get("/api/ingestion/snapshots").status_code == 403
    assert (
        client.get("/api/ingestion/snapshots/" + snap["id"] + "/download").status_code
        == 403
    )
    assert (
        client.post(
            "/api/ingestion/sources/" + src["id"] + "/test", json={"password": PASSWORD}
        ).status_code
        == 403
    )
