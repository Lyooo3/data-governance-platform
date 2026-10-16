import copy
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.connector_common import (
    SPECS,
    catalog,
    source_config,
    table_id,
    text_value,
    ConnectorError,
)
from api.connectors import open_reader
from api import db_readers

SECRET = "private-test-credential"


def config(kind, **extra):
    return dict(
        name="隔离数据库-" + kind,
        type=kind,
        host="127.0.0.1",
        port=SPECS[kind]["port"],
        database="training",
        user="reader",
        **extra,
    )


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "platform")) as c:
        data(c.post("/api/auth/local-session", headers={"Origin": "http://testserver"}))
        yield c


def capture(client, source):
    value = data(
        client.post("/api/ingestion/sources/" + source["id"] + "/snapshots", json={})
    )
    client.app.state.raw.thread.join(5)
    value = data(client.get("/api/ingestion/snapshots/" + value["id"]))
    assert value["status"] != "RUNNING"
    return value


def test_catalog_and_stable_ids():
    assert len(catalog()) == 8 and all(c["available"] for c in catalog())
    assert all(
        isinstance(table_id("业务", "x"), int) and 0 < table_id("业务", "x") < 2**53
        for _ in range(3)
    )
    assert table_id("业务", "x") != table_id("其他", "x")
    assert text_value(Decimal("12345678901234567890.123")) == "12345678901234567890.123"
    assert text_value(b"\x00\xff") == "base64:AP8="
    assert json.loads(text_value({"n": Decimal("0.10")}))["n"]["value"] == "0.10"


def test_postgres_required_tls_validates_ca_and_hostname():
    from api.connectors import PostgresReader
    reader = PostgresReader(config("postgresql", sslmode="require"), SECRET)
    assert reader.config["sslmode"] == "verify-full"
    assert Path(reader.config["sslrootcert"]).is_file()


@pytest.mark.parametrize("kind", list(SPECS))
def test_all_types_save_and_validation(client, tmp_path, kind):
    body = config(kind)
    if kind == "sqlite":
        body["filePath"] = str(tmp_path / "source.sqlite3")
    source = data(client.post("/api/governance/sources", json=body))
    assert source["connectionStatus"] == "untested" and source["type"] == kind
    assert "password" not in source
    assert len(data(client.get("/api/ingestion/connectors"))["list"]) == 8
    if kind != "sqlite":
        bad = {**body, "host": "127.0.0.1; DROP TABLE x"}
        assert client.post("/api/governance/sources", json=bad).status_code == 422
    else:
        for path in ("relative.sqlite3", "file:/tmp/x", "//server/share/x"):
            assert (
                client.post(
                    "/api/governance/sources", json={**body, "filePath": path}
                ).status_code
                == 422
            )


def test_sqlite_actual_source_unchanged_full_snapshot_and_governance(client, tmp_path):
    source_file = tmp_path / "business.sqlite3"
    with sqlite3.connect(source_file) as db:
        db.execute(
            'CREATE TABLE "exam" (id INTEGER PRIMARY KEY, score REAL, note TEXT, data BLOB)'
        )
        db.executemany(
            "INSERT INTO exam VALUES (?,?,?,?)",
            [(i, 50.25, " 中文 ", b"\x00\xff") for i in range(10021)],
        )
        db.execute('CREATE TABLE "含""引号" (code TEXT)')
    # Deliberate quoting case in the catalog, without interpolating input values.
    before = source_file.read_bytes()
    cfg = config("sqlite", filePath=str(source_file))
    with open_reader(cfg, "") as reader:
        assert reader.info()["consistent_snapshot"]
        with pytest.raises(sqlite3.OperationalError):
            reader.connection.execute("DELETE FROM exam")
    source = data(client.post("/api/governance/sources", json=cfg))
    info = data(
        client.post("/api/ingestion/sources/" + source["id"] + "/test", json={})
    )
    assert info["read_only"] == "on"
    snap = capture(client, source)
    assert (
        snap["status"] == "SUCCESS"
        and snap["rowCount"] == 10021
        and snap["tableCount"] == 2
    )
    target = next(t for t in snap["tables"] if t["name"] == "exam")
    copy = data(
        client.post(
            f'/api/ingestion/snapshots/{snap["id"]}/tables/{target["id"]}/datasets',
            json={
                "offset": 10000,
                "limit": 10000,
                "fields": ["id", "score", "note", "data"],
            },
        )
    )
    assert copy["rowCount"] == 21
    row = data(client.get("/api/governance/datasets/" + copy["id"]))["rows"][0]
    assert row == {"id": 10000, "score": 50.25, "note": " 中文 ", "data": "base64:AP8="}
    rule = data(
        client.post(
            "/api/governance/rules",
            json={"name": "编号唯一", "type": "unique", "field": "id"},
        )
    )
    flow = data(
        client.post(
            "/api/governance/workflows",
            json={
                "name": "真实SQLite治理",
                "nodes": [
                    {"id": "s", "type": "source", "config": {"datasetId": copy["id"]}},
                    {"id": "q", "type": "quality", "config": {"ruleIds": [rule["id"]]}},
                    {"id": "o", "type": "output", "config": {}},
                ],
                "edges": [
                    {"source": "s", "target": "q"},
                    {"source": "q", "target": "o"},
                ],
            },
        )
    )
    run = data(client.post("/api/governance/workflows/" + flow["id"] + "/run", json={}))
    for _ in range(100):
        result = data(client.get("/api/governance/runs/" + run["id"]))
        if result["status"] != "RUNNING":
            break
        time.sleep(0.05)
    assert result["status"] == "SUCCESS" and result["outputCount"] == 21
    assert result["reports"][0]["invalidRows"] == 0
    assert source_file.read_bytes() == before


def test_sqlite_missing_file_never_created(client, tmp_path):
    f = tmp_path / "absent.sqlite3"
    source = data(
        client.post("/api/governance/sources", json=config("sqlite", filePath=str(f)))
    )
    assert (
        client.post(
            "/api/ingestion/sources/" + source["id"] + "/test", json={}
        ).status_code
        == 422
    )
    assert not f.exists()


class Cursor:
    description = [("id",), ("amount",)]

    def __init__(self, conn):
        self.conn = conn
        self.done = False

    def execute(self, query, args=None, **kwargs):
        self.conn.calls.append((query, args, kwargs))
        return self

    def fetchone(self):
        return ("8.0.40",)

    def fetchmany(self, size):
        if self.done:
            return []
        self.done = True
        return [(1, Decimal("1234567890.123456789"))]

    def close(self):
        pass


class Connection:
    version = "19.20"
    open = True
    _secure = True
    closed = False
    rolled = False

    def __init__(self):
        self.calls = []

    def cursor(self, *_):
        return Cursor(self)

    def rollback(self):
        self.rolled = True

    def close(self):
        self.closed = True
        self.open = False

    def cancel(self):
        pass


@pytest.mark.parametrize("kind", ["mysql", "mariadb", "sqlserver", "oracle"])
def test_network_sql_readers_driver_contracts(monkeypatch, kind):
    conn = Connection()
    kwargs = {}
    module = {
        "mysql": "pymysql",
        "mariadb": "pymysql",
        "sqlserver": "pytds",
        "oracle": "oracledb",
    }[kind]
    driver = __import__(module)

    def connect(**kw):
        kwargs.update(kw)
        return conn

    monkeypatch.setattr(driver, "connect", connect)
    cls = db_readers.READERS[kind]
    reader = cls(config(kind), SECRET)
    query_log = []

    def query(sql, args=None):
        query_log.append((sql, args))
        if "snapshot_isolation_state" in sql:
            return [{"state": 1}]
        if "ProductVersion" in sql:
            return [{"version": "16"}]
        if "information_schema.TABLES" in sql:
            return [
                {
                    "schema_name": "training",
                    "name": "x`];drop",
                    "estimated_rows": 1,
                    "comment": None,
                    "engine": "InnoDB",
                }
            ]
        if "FROM sys.tables" in sql:
            return [{"oid": 1, "schema": "dbo", "name": "x];drop"}]
        if "FROM all_tables" in sql:
            return [
                {
                    "oid": 1,
                    "schema": "READER",
                    "name": 'x";drop',
                    "estimated_rows": 1,
                    "comment": None,
                }
            ]
        return [
            {
                "name": "id",
                "type": "INTEGER",
                "nullable": 0,
                "primary_key": 1,
                "comment": None,
            },
            {
                "name": "amount",
                "type": "DECIMAL",
                "nullable": 1,
                "primary_key": 0,
                "comment": None,
            },
        ]

    reader.query = query
    with reader:
        assert (
            reader.info()["read_only"] == "on" and reader.info()["consistent_snapshot"]
        )
        target = reader.describe(reader.tables()[0])
        values = list(reader.batches(target))
        assert values[0][0]["amount"] == "1234567890.123456789"
        sql = conn.calls[-1][0]
        assert sql.startswith("SELECT ") and "drop" in sql
        assert target["columns"][0]["value_kind"] == "integer"
    assert conn.closed and conn.rolled
    assert all(
        not q.lstrip()
        .upper()
        .startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "GRANT"))
        for q, _, _ in conn.calls
    )
    if kind in ("mysql", "mariadb"):
        assert kwargs["local_infile"] is False and kwargs["read_timeout"] == 60
        assert any(
            q == "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            for q, _, _ in conn.calls
        )
        assert "`x``];drop`" in sql
    if kind == "sqlserver":
        assert (
            kwargs["readonly"] is True
            and kwargs["isolation_level"] == 5
            and "[x]];drop]" in sql
        )
    if kind == "oracle":
        assert (
            kwargs["params"].service_name == "training" and conn.call_timeout == 60000
        )
        assert conn.calls[-1][2]["fetch_decimals"] is True
        assert '"x"";drop"' in sql


def test_mysql_nontransactional_guard_and_mssql_failure_cleanup(monkeypatch):
    reader = db_readers.MySQLReader(config("mysql"), SECRET)
    with pytest.raises(ConnectorError):
        reader.describe({"engine": "MyISAM"})
    import pytds

    conn = Connection()
    monkeypatch.setattr(pytds, "connect", lambda **_: conn)
    monkeypatch.setattr(db_readers.SQLServerReader, "query", lambda *_: [{"state": 0}])
    with pytest.raises(ConnectorError, match="SNAPSHOT"):
        with open_reader(config("sqlserver"), SECRET):
            pass
    assert conn.closed


def test_driver_errors_never_echo_credentials(monkeypatch):
    import pymysql

    def error(**_):
        raise RuntimeError("dsn user:private-test-credential@server")

    monkeypatch.setattr(pymysql, "connect", error)
    with pytest.raises(ConnectorError) as exc:
        with open_reader(config("mysql"), SECRET):
            pass
    assert SECRET not in str(exc.value)


def test_mongodb_snapshot_and_full_document(monkeypatch):
    import pymongo
    from bson import ObjectId, Decimal128, Binary, json_util

    doc = {
        "_id": ObjectId(),
        "amount": Decimal128("1.234567890123456789"),
        "blob": Binary(b"\x00\xff"),
        "nested": {"when": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    }
    calls = {}

    class Session:
        def end_session(self):
            calls["session_closed"] = True

    class Find:
        def max_time_ms(self, value):
            calls["timeout"] = value
            return self

        def __iter__(self):
            return iter([doc])

        def close(self):
            pass

    class Collection:
        def find(self, *args, **kw):
            calls["find"] = kw
            return Find()

    class Database:
        def list_collections(self, **kw):
            return [{"name": "records"}, {"name": "system.views"}]

        def __getitem__(self, key):
            return Collection()

    class Client:
        @property
        def admin(self):
            return self

        def command(self, name):
            return {"setName": "rs0"}

        def server_info(self):
            return {"version": "7.0"}

        def start_session(self, **kw):
            calls["session"] = kw
            return Session()

        def __getitem__(self, key):
            return Database()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(pymongo, "MongoClient", lambda **kw: Client())
    with open_reader(config("mongodb"), SECRET) as reader:
        assert reader.info()["consistent_snapshot"]
        table = reader.describe(reader.tables()[0])
        row = list(reader.batches(table))[0][0]
        restored = json_util.loads(row["document"])
        assert (
            restored["amount"] == doc["amount"]
            and bytes(restored["blob"]) == bytes(doc["blob"])
            and restored["_id"] == doc["_id"]
        )
    assert (
        calls["session"] == {"snapshot": True}
        and calls["closed"]
        and calls["session_closed"]
    )


def test_clickhouse_readonly_streaming_and_consistency_guard(client, monkeypatch):
    import clickhouse_connect

    calls = {}

    class Result:
        def __init__(self, cols, rows):
            self.column_names = cols
            self.result_rows = rows

    class Client:
        def query(self, query, parameters=None):
            if query.startswith("SELECT version()"):
                return Result(["v", "r"], [("24.8", 1)])
            if query.startswith("SELECT getSetting"):
                return Result(["r"], [(1,)])
            if "system.tables" in query:
                return Result(
                    ["schema", "name", "estimated_rows", "comment", "engine"],
                    [("training", "a`b", 1, None, "MergeTree")],
                )
            return Result(
                ["name", "type", "nullable", "primary_key", "comment"],
                [("id", "Int64", 0, 1, None)],
            )

        @contextmanager
        def query_row_block_stream(self, query):
            calls["select"] = query
            yield [[(42,)]]

        def close(self):
            calls["closed"] = True

    def connect(**kw):
        calls["connect"] = kw
        return Client()

    monkeypatch.setattr(clickhouse_connect, "get_client", connect)
    with open_reader(config("clickhouse", consistencyMode="best_effort"), "") as reader:
        assert reader.info()["consistent_snapshot"] is False
        table = reader.describe(reader.tables()[0])
        assert list(reader.batches(table))[0][0]["id"] == "42"
    assert (
        calls["connect"]["settings"]["readonly"] == 1 and "`a\\`b`" in calls["select"]
    )
    source = data(client.post("/api/governance/sources", json=config("clickhouse")))
    snap = capture(client, source)
    assert snap["status"] == "FAILED" and not snap["tables"]
    source = data(
        client.put(
            "/api/governance/sources/" + source["id"],
            json={"consistencyMode": "best_effort"},
        )
    )
    snap = capture(client, source)
    assert (
        snap["status"] == "SUCCESS"
        and snap["rowCount"] == 1
        and snap["transaction"]["consistent_snapshot"] is False
    )
