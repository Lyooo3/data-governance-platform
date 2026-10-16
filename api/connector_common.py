"""Connector capabilities, validated public settings, and lossless text values."""

import base64
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import uuid


class ConnectorError(ValueError):
    """A fixed, user-safe message, never a raw driver exception."""


SPECS = {
    "postgresql": dict(
        label="PostgreSQL",
        port=5432,
        module="psycopg",
        note="一致只读事务",
        consistency="strict",
    ),
    "mysql": dict(
        label="MySQL",
        port=3306,
        module="pymysql",
        note="严格模式要求InnoDB表",
        consistency="strict",
    ),
    "mariadb": dict(
        label="MariaDB",
        port=3306,
        module="pymysql",
        note="严格模式要求InnoDB表",
        consistency="strict",
    ),
    "sqlserver": dict(
        label="SQL Server",
        port=1433,
        module="pytds",
        note="严格模式要求数据库已启用SNAPSHOT；不自动更改服务器设置",
        consistency="strict",
    ),
    "oracle": dict(
        label="Oracle",
        port=1521,
        module="oracledb",
        note="Thin模式，Oracle 12.1+；支持Service Name或SID",
        consistency="strict",
    ),
    "sqlite": dict(
        label="SQLite",
        port=None,
        module="sqlite3",
        note="读取后端机器已有数据库文件，mode=ro",
        consistency="strict",
        passwordOptional=True,
    ),
    "mongodb": dict(
        label="MongoDB",
        port=27017,
        module="pymongo",
        note="严格模式要求5.0+副本集/分片；文档保存为完整Extended JSON",
        consistency="strict",
        passwordOptional=True,
    ),
    "clickhouse": dict(
        label="ClickHouse",
        port=8123,
        module="clickhouse_connect",
        note="HTTP接口；不提供跨表一致事务，采集需选择尽力读取",
        consistency="best_effort",
        passwordOptional=True,
    ),
}
PUBLIC_FIELDS = (
    "name",
    "type",
    "host",
    "port",
    "database",
    "user",
    "sslmode",
    "caFile",
    "serviceMode",
    "authDatabase",
    "filePath",
    "consistencyMode",
    "description",
)


def catalog():
    return [
        {
            "type": key,
            **value,
            "available": importlib.util.find_spec(value["module"]) is not None,
        }
        for key, value in SPECS.items()
    ]


def source_config(value):
    kind = value.get("type")
    if kind not in SPECS:
        raise ConnectorError("请选择受支持的数据库类型")
    mode = value.get("consistencyMode", "strict")
    if mode not in ("strict", "best_effort"):
        raise ConnectorError("请选择有效的一致性模式")
    if kind == "sqlite":
        path = str(value.get("filePath") or "").strip()
        if (
            not path
            or "\x00" in path
            or not Path(path).is_absolute()
            or path.startswith(("\\\\", "//"))
            or path.startswith("file:")
        ):
            raise ConnectorError(
                "SQLite请填写后端机器上的本地绝对文件路径，不使用URI或网络共享路径"
            )
        return {"filePath": str(Path(path).resolve()), "consistencyMode": mode}
    result = {k: str(value.get(k) or "").strip() for k in ("host", "database", "user")}
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", result["host"]):
        raise ConnectorError("主机只填写IP或域名，不含http://、路径或连接参数")
    if not result["database"] or len(result["database"]) > 120:
        raise ConnectorError("请填写数据库名称；Oracle填写Service Name或SID")
    if kind not in ("mongodb", "clickhouse") and not result["user"]:
        raise ConnectorError("请填写数据库账号")
    if len(result["user"]) > 120:
        raise ConnectorError("数据库账号过长")
    try:
        result["port"] = int(value.get("port") or SPECS[kind]["port"])
    except (TypeError, ValueError):
        raise ConnectorError("端口必须为1至65535") from None
    if not 1 <= result["port"] <= 65535:
        raise ConnectorError("端口必须为1至65535")
    result["sslmode"] = value.get("sslmode", "prefer")
    if result["sslmode"] not in ("prefer", "require"):
        raise ConnectorError("请选择有效的传输加密方式")
    ca = str(value.get("caFile") or "").strip()
    if ca and (not Path(ca).is_absolute() or not Path(ca).is_file()):
        raise ConnectorError("CA证书需为后端机器上已有文件的绝对路径")
    result.update(caFile=ca, consistencyMode=mode)
    if kind == "oracle":
        result["serviceMode"] = value.get("serviceMode", "service")
        if result["serviceMode"] not in ("service", "sid"):
            raise ConnectorError("请选择Service Name或SID")
    if kind == "mongodb":
        result["authDatabase"] = str(value.get("authDatabase") or "admin").strip()
        if len(result["authDatabase"]) > 120:
            raise ConnectorError("认证数据库名称过长")
    return result


def require_password(source, password):
    if (
        not isinstance(password, str)
        or len(password) > 1024
        or (not password and not SPECS[source["type"]].get("passwordOptional"))
    ):
        raise ConnectorError("请输入本次连接密码，密码不会保存")


def table_id(schema, name):
    # 13 hex digits fit exactly in JS numeric identifiers; stable across scans.
    return (
        int(
            hashlib.sha256(
                json.dumps([schema, name], ensure_ascii=False).encode()
            ).hexdigest()[:13],
            16,
        )
        or 1
    )


def text_value(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "base64:" + base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, timedelta)):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=lambda v: {"type": type(v).__name__, "value": text_value(v)},
            allow_nan=False,
            separators=(",", ":"),
        )
    if hasattr(value, "read"):
        return text_value(value.read())  # Oracle LOBs while cursor is alive.
    return str(value)


def value_kind(type_name):
    t = type_name.lower().strip()
    if any(x in t for x in ("int", "serial")) and not any(
        x in t for x in ("interval", "point")
    ):
        return "integer"
    if any(
        x in t
        for x in ("number", "numeric", "decimal", "float", "double", "real", "money")
    ):
        return "number"
    if t in ("bool", "boolean", "bit"):
        return "boolean"
    return "text"


class SQLReader:
    connection = None
    isolation = "repeatable read"
    consistent = True
    enforcement = "database transaction"

    def __init__(self, source, password):
        self.source = source
        self.config = source_config(source)
        require_password(source, password)
        self.password = password

    def __exit__(self, *_):
        self.password = None
        if self.connection:
            try:
                self.connection.rollback()
            finally:
                self.connection.close()

    def query(self, sql, args=None):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, args) if args is not None else cursor.execute(sql)
            names = [str(c[0]).lower() for c in cursor.description]
            return [dict(zip(names, r)) for r in cursor.fetchall()]
        finally:
            cursor.close()

    def batch_cursor(self):
        return self.connection.cursor()

    def execute_select(self, cursor, query):
        cursor.execute(query)

    def batches(self, table, batch_size=500):
        cursor = self.batch_cursor()
        try:
            self.execute_select(cursor, self.select_sql(table))
            names = [c["name"] for c in table["columns"]]
            while batch := cursor.fetchmany(batch_size):
                yield [
                    {name: text_value(v) for name, v in zip(names, row)}
                    for row in batch
                ]
        finally:
            cursor.close()

    def cancel(self):
        if self.connection and hasattr(self.connection, "cancel"):
            self.connection.cancel()

    def info(self):
        return {
            "database": self.config.get("database", self.config.get("filePath")),
            "version": self.version,
            "read_only": "on",
            "isolation": self.isolation,
            "consistent_snapshot": self.consistent,
            "read_only_enforcement": self.enforcement,
        }
