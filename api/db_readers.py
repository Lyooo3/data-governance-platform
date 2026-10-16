"""Fixed read-only queries for common database protocols. No user SQL."""

import sqlite3
import ssl
from pathlib import Path
from .connector_common import (
    SQLReader,
    ConnectorError,
    source_config,
    require_password,
    table_id,
    text_value,
    value_kind,
)


def quoted(name, style='"'):
    if style == "[":
        return "[" + str(name).replace("]", "]]") + "]"
    return style + str(name).replace(style, style * 2) + style


def columns(values):
    return [
        {
            **v,
            "nullable": bool(v["nullable"]),
            "primary_key": bool(v["primary_key"]),
            "native_type": v["type"],
            "value_kind": value_kind(v["type"]),
        }
        for v in values
    ]


class MySQLReader(SQLReader):
    def __enter__(self):
        import pymysql

        cfg = self.config
        tls = ssl.create_default_context(cafile=cfg.get("caFile") or None)
        self.connection = pymysql.connect(
            host=cfg["host"],
            port=cfg["port"],
            database=cfg["database"],
            user=cfg["user"],
            password=self.password,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=8,
            read_timeout=60,
            write_timeout=8,
            local_infile=False,
            ssl=tls,
        )
        if cfg["sslmode"] == "require" and not getattr(
            self.connection, "_secure", False
        ):
            raise ConnectorError("服务器未建立TLS连接，已停止；请检查数据库加密配置")
        cur = self.connection.cursor()
        try:
            cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cur.execute("SELECT VERSION()")
            self.version = cur.fetchone()[0]
        finally:
            cur.close()
        self.consistent = cfg["consistencyMode"] == "strict"
        if not self.consistent:
            self.isolation = "best effort; nontransactional tables may change"
        self.password = None
        return self

    def tables(self):
        rows = self.query(
            "SELECT TABLE_SCHEMA AS schema_name,TABLE_NAME AS name,TABLE_ROWS AS estimated_rows,TABLE_COMMENT AS comment,ENGINE AS engine FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
            (self.config["database"],),
        )
        return [
            {
                **r,
                "schema": r["schema_name"],
                "oid": table_id(r["schema_name"], r["name"]),
                "estimated_rows": int(r["estimated_rows"] or 0),
            }
            for r in rows
        ]

    def describe(self, table):
        if (
            self.config["consistencyMode"] == "strict"
            and str(table.get("engine")).lower() != "innodb"
        ):
            raise ConnectorError(
                "严格一致采集仅支持InnoDB表；当前选择包含非事务表，可明确选择尽力读取后重新采集"
            )
        rows = self.query(
            "SELECT COLUMN_NAME AS name,COLUMN_TYPE AS type,IS_NULLABLE='YES' AS nullable,COLUMN_KEY='PRI' AS primary_key,COLUMN_COMMENT AS comment FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
            (table["schema"], table["name"]),
        )
        return {**table, "columns": columns(rows)}

    def select_sql(self, table):
        return (
            "SELECT "
            + ",".join(quoted(c["name"], "`") for c in table["columns"])
            + " FROM "
            + quoted(table["schema"], "`")
            + "."
            + quoted(table["name"], "`")
        )

    def batch_cursor(self):
        from pymysql.cursors import SSCursor

        return self.connection.cursor(SSCursor)

    def cancel(self):
        # Interrupt this client's socket; never issue KILL on the server.
        if self.connection:
            self.connection.close()

    def __exit__(self, *_):
        if self.connection and self.connection.open:
            super().__exit__()


class SQLServerReader(SQLReader):
    enforcement = "read-only intent and fixed SELECT statements"

    def __enter__(self):
        import pytds
        from pytds import extensions
        import certifi

        cfg = self.config
        strict = cfg["consistencyMode"] == "strict"
        self.isolation = "snapshot" if strict else "read committed (best effort)"
        self.consistent = strict
        args = dict(
            server=cfg["host"],
            port=cfg["port"],
            database=cfg["database"],
            user=cfg["user"],
            password=self.password,
            login_timeout=8,
            timeout=60,
            readonly=True,
            autocommit=False,
            appname="governance_readonly_snapshot",
            isolation_level=(
                extensions.ISOLATION_LEVEL_SNAPSHOT
                if strict
                else extensions.ISOLATION_LEVEL_READ_COMMITTED
            ),
        )
        if cfg["sslmode"] == "require":
            args.update(
                cafile=cfg.get("caFile") or certifi.where(),
                validate_host=True,
                enc_login_only=False,
            )
        self.connection = pytds.connect(**args)
        if strict:
            state = self.query(
                "SELECT snapshot_isolation_state AS state FROM sys.databases WHERE database_id=DB_ID()"
            )[0]["state"]
            if state != 1:
                raise ConnectorError(
                    "SQL Server数据库未启用SNAPSHOT，严格采集已停止；本系统不会更改服务器设置，可选择尽力读取"
                )
        self.version = str(
            self.query(
                "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(100)) AS version"
            )[0]["version"]
        )
        self.password = None
        return self

    def tables(self):
        return [
            {**r, "estimated_rows": 0}
            for r in self.query(
                "SELECT t.object_id AS oid,s.name AS [schema],t.name AS name FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE t.is_ms_shipped=0 ORDER BY s.name,t.name"
            )
        ]

    def describe(self, table):
        rows = self.query(
            """SELECT c.name AS name,ty.name AS type,c.is_nullable AS nullable,
            CASE WHEN EXISTS(SELECT 1 FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id WHERE i.object_id=c.object_id AND i.is_primary_key=1 AND ic.column_id=c.column_id) THEN 1 ELSE 0 END AS primary_key,
            CAST(ep.value AS nvarchar(4000)) AS comment
            FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id
            LEFT JOIN sys.extended_properties ep ON ep.major_id=c.object_id AND ep.minor_id=c.column_id AND ep.class=1 AND ep.name='MS_Description'
            WHERE c.object_id=%s ORDER BY c.column_id""",
            (table["oid"],),
        )
        return {**table, "columns": columns(rows)}

    def select_sql(self, table):
        return (
            "SELECT "
            + ",".join(quoted(c["name"], "[") for c in table["columns"])
            + " FROM "
            + quoted(table["schema"], "[")
            + "."
            + quoted(table["name"], "[")
        )


class OracleReader(SQLReader):
    isolation = "read only transaction"

    def execute_select(self, cursor, query):
        cursor.execute(query, fetch_decimals=True)

    def __enter__(self):
        import oracledb

        cfg = self.config
        args = dict(
            host=cfg["host"],
            port=cfg["port"],
            tcp_connect_timeout=8,
            retry_count=0,
            protocol="tcps" if cfg["sslmode"] == "require" else "tcp",
        )
        args["sid" if cfg["serviceMode"] == "sid" else "service_name"] = cfg["database"]
        if cfg["sslmode"] == "require":
            args.update(
                ssl_context=ssl.create_default_context(
                    cafile=cfg.get("caFile") or None
                ),
                ssl_server_dn_match=True,
            )
        params = oracledb.ConnectParams(**args)
        self.connection = oracledb.connect(
            user=cfg["user"], password=self.password, params=params
        )
        self.connection.call_timeout = 60000
        cur = self.connection.cursor()
        try:
            cur.execute("SET TRANSACTION READ ONLY")
        finally:
            cur.close()
        self.version = self.connection.version
        self.password = None
        return self

    def tables(self):
        return self.query(
            """SELECT o.object_id AS oid,t.owner AS "schema",t.table_name AS name,NVL(t.num_rows,0) AS estimated_rows,c.comments AS "comment"
            FROM all_tables t JOIN all_objects o ON o.owner=t.owner AND o.object_name=t.table_name AND o.object_type='TABLE'
            LEFT JOIN all_tab_comments c ON c.owner=t.owner AND c.table_name=t.table_name
            WHERE t.owner=SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AND t.nested='NO' AND t.secondary='N'
            AND NOT EXISTS(SELECT 1 FROM all_external_tables e WHERE e.owner=t.owner AND e.table_name=t.table_name)
            ORDER BY t.table_name"""
        )

    def describe(self, table):
        rows = self.query(
            """SELECT col.column_name AS name,col.data_type AS type,
            CASE col.nullable WHEN 'Y' THEN 1 ELSE 0 END AS nullable,
            CASE WHEN EXISTS(SELECT 1 FROM all_constraints ac JOIN all_cons_columns cc ON cc.owner=ac.owner AND cc.constraint_name=ac.constraint_name WHERE ac.owner=col.owner AND ac.table_name=col.table_name AND ac.constraint_type='P' AND cc.column_name=col.column_name) THEN 1 ELSE 0 END AS primary_key,
            comments.comments AS "comment"
            FROM all_tab_columns col LEFT JOIN all_col_comments comments ON comments.owner=col.owner AND comments.table_name=col.table_name AND comments.column_name=col.column_name
            WHERE col.owner=:owner AND col.table_name=:name ORDER BY col.column_id""",
            {"owner": table["schema"], "name": table["name"]},
        )
        return {**table, "columns": columns(rows)}

    def select_sql(self, table):
        return (
            "SELECT "
            + ",".join(quoted(c["name"]) for c in table["columns"])
            + " FROM "
            + quoted(table["schema"])
            + "."
            + quoted(table["name"])
        )


class SQLiteReader(SQLReader):
    isolation = "sqlite read snapshot"

    def __enter__(self):
        path = Path(self.config["filePath"])
        if not path.is_file():
            raise ConnectorError("SQLite文件不存在；请填写后端机器已有文件路径")
        self.connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=8, check_same_thread=False
        )
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("PRAGMA trusted_schema=OFF")
        self.connection.enable_load_extension(False)
        self.connection.execute("BEGIN")
        self.version = sqlite3.sqlite_version
        return self

    def tables(self):
        return [
            {
                "oid": table_id("main", r["name"]),
                "schema": "main",
                "name": r["name"],
                "estimated_rows": 0,
                "comment": None,
            }
            for r in self.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND upper(sql) NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name"
            )
        ]

    def describe(self, table):
        rows = self.query("PRAGMA table_xinfo(" + quoted(table["name"]) + ")")
        values = [
            {
                "name": r["name"],
                "type": r["type"] or "dynamic",
                "nullable": not bool(r["notnull"] or r["pk"]),
                "primary_key": bool(r["pk"]),
                "comment": None,
            }
            for r in rows
            if r.get("hidden", 0) != 1
        ]
        return {**table, "columns": columns(values)}

    def select_sql(self, table):
        return (
            "SELECT "
            + ",".join(quoted(c["name"]) for c in table["columns"])
            + " FROM "
            + quoted(table["name"])
        )

    def cancel(self):
        if self.connection:
            self.connection.interrupt()


class MongoReader(SQLReader):
    enforcement = "fixed catalog and find commands only"
    session = None

    def __enter__(self):
        import pymongo
        from pymongo.read_concern import ReadConcern

        cfg = self.config
        args = dict(
            host=cfg["host"],
            port=cfg["port"],
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            socketTimeoutMS=60000,
            retryWrites=False,
        )
        if cfg["user"]:
            args.update(
                username=cfg["user"],
                password=self.password,
                authSource=cfg["authDatabase"],
            )
        if cfg["sslmode"] == "require":
            args.update(tls=True, tlsAllowInvalidCertificates=False)
            if cfg.get("caFile"):
                args["tlsCAFile"] = cfg["caFile"]
        self.connection = pymongo.MongoClient(**args)
        self.version = self.connection.server_info()["version"]
        self.consistent = cfg["consistencyMode"] == "strict"
        self.isolation = (
            "mongodb snapshot session"
            if self.consistent
            else "best effort document cursor"
        )
        hello = self.connection.admin.command("hello")
        if self.consistent:
            if int(str(self.version).split(".")[0]) < 5 or not (
                hello.get("setName") or hello.get("msg") == "isdbgrid"
            ):
                raise ConnectorError(
                    "MongoDB严格快照需要5.0+副本集或分片；单机可选择尽力读取，不能保证整库时点一致"
                )
            self.session = self.connection.start_session(snapshot=True)
        self.database = self.connection[cfg["database"]]
        self.password = None
        return self

    def tables(self):
        rows = self.database.list_collections(
            filter={"type": "collection"}, maxTimeMS=60000
        )
        return sorted(
            [
                {
                    "oid": table_id(self.config["database"], r["name"]),
                    "schema": self.config["database"],
                    "name": r["name"],
                    "estimated_rows": 0,
                    "comment": "完整BSON文档的Canonical Extended JSON",
                }
                for r in rows
                if not r["name"].startswith("system.")
            ],
            key=lambda t: t["name"],
        )

    def describe(self, table):
        return {
            **table,
            "columns": [
                {
                    "name": "_id",
                    "type": "BSON identity",
                    "native_type": "text",
                    "nullable": False,
                    "primary_key": True,
                    "comment": "Extended JSON标识",
                },
                {
                    "name": "document",
                    "type": "Canonical Extended JSON",
                    "native_type": "text",
                    "nullable": False,
                    "primary_key": False,
                    "comment": "完整文档，包含嵌套对象、数组、日期和二进制类型",
                },
            ],
        }

    def batches(self, table, batch_size=500):
        from bson import json_util

        cursor = (
            self.database[table["name"]]
            .find({}, session=self.session, batch_size=batch_size)
            .max_time_ms(60000)
        )
        batch = []
        try:
            for doc in cursor:
                batch.append(
                    {
                        "_id": json_util.dumps(
                            doc.get("_id"),
                            json_options=json_util.CANONICAL_JSON_OPTIONS,
                        ),
                        "document": json_util.dumps(
                            doc, json_options=json_util.CANONICAL_JSON_OPTIONS
                        ),
                    }
                )
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch
        finally:
            cursor.close()

    def __exit__(self, *_):
        if self.session:
            self.session.end_session()
        if self.connection:
            self.connection.close()

    def cancel(self):
        if self.connection:
            self.connection.close()


class ClickHouseReader(SQLReader):
    consistent = False
    isolation = "per-query snapshots; no cross-table consistency"
    enforcement = "ClickHouse readonly=1"

    def __enter__(self):
        import clickhouse_connect

        cfg = self.config
        args = dict(
            host=cfg["host"],
            port=cfg["port"],
            database=cfg["database"],
            username=cfg["user"] or "default",
            password=self.password,
            connect_timeout=8,
            send_receive_timeout=60,
            secure=cfg["sslmode"] == "require",
            verify=True,
            autogenerate_session_id=False,
            settings={"readonly": 1, "max_execution_time": 60},
        )
        if cfg.get("caFile"):
            args["ca_cert"] = cfg["caFile"]
        self.connection = clickhouse_connect.get_client(**args)
        self.version = str(
            self.connection.query(
                "SELECT version(),getSetting('readonly')"
            ).result_rows[0][0]
        )
        if (
            int(
                self.connection.query("SELECT getSetting('readonly')").result_rows[0][0]
            )
            != 1
        ):
            raise ConnectorError("ClickHouse未处于readonly=1，已停止采集")
        self.password = None
        return self

    def ch_query(self, query, parameters=None):
        result = self.connection.query(query, parameters=parameters)
        return [dict(zip(result.column_names, r)) for r in result.result_rows]

    def tables(self):
        rows = self.ch_query(
            "SELECT database AS schema,name,total_rows AS estimated_rows,comment,engine FROM system.tables WHERE database={db:String} AND (endsWith(engine,'MergeTree') OR engine IN ('Memory','Log','TinyLog','StripeLog')) ORDER BY name",
            {"db": self.config["database"]},
        )
        return [
            {
                **r,
                "oid": table_id(r["schema"], r["name"]),
                "estimated_rows": int(r["estimated_rows"] or 0),
            }
            for r in rows
        ]

    def describe(self, table):
        rows = self.ch_query(
            "SELECT name,type,startsWith(type,'Nullable(') AS nullable,is_in_primary_key AS primary_key,comment FROM system.columns WHERE database={db:String} AND table={tbl:String} ORDER BY position",
            {"db": table["schema"], "tbl": table["name"]},
        )
        return {**table, "columns": columns(rows)}

    def batches(self, table, batch_size=500):
        from clickhouse_connect.driver.binding import quote_identifier

        query = (
            "SELECT "
            + ",".join(quote_identifier(c["name"]) for c in table["columns"])
            + " FROM "
            + quote_identifier(table["schema"])
            + "."
            + quote_identifier(table["name"])
        )
        with self.connection.query_row_block_stream(query) as stream:
            names = [c["name"] for c in table["columns"]]
            for block in stream:
                for i in range(0, len(block), batch_size):
                    yield [
                        {k: text_value(v) for k, v in zip(names, row)}
                        for row in block[i : i + batch_size]
                    ]

    def __exit__(self, *_):
        if self.connection:
            self.connection.close()

    def cancel(self):
        if self.connection:
            self.connection.close()


READERS = {
    "mysql": MySQLReader,
    "mariadb": MySQLReader,
    "sqlserver": SQLServerReader,
    "oracle": OracleReader,
    "sqlite": SQLiteReader,
    "mongodb": MongoReader,
    "clickhouse": ClickHouseReader,
}


def safe_driver_error(kind, error):
    # Never return driver text: it may contain DSNs, credentials, or query values.
    code = getattr(error, "code", None)
    if kind in ("mysql", "mariadb"):
        code = error.args[0] if error.args else code
        if code in (1044, 1045, 1698):
            return "数据库认证或读取权限不足，请检查账号和本次密码"
        if code == 1049:
            return "数据库不存在，请检查名称"
    if kind == "oracle" and error.args:
        code = getattr(error.args[0], "code", None)
        if code in (1017, 28000):
            return "Oracle账号、密码无效或账号已锁定"
        if code == 1555:
            return "Oracle一致快照已过期，本批未完成，请减少表数后重试"
    if kind == "sqlserver":
        return "SQL Server连接或读取失败，请检查网络、凭据、TLS证书和SNAPSHOT模式；未修改服务器配置"
    if kind == "sqlite":
        return "SQLite只读打开或读取失败，请检查文件格式、权限及是否被锁定"
    return "数据库连接或读取失败，请检查地址、端口、凭据、版本、证书及当前账号读取权限"
