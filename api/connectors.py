"""PostgreSQL SELECT-only logical extraction. Never runs user SQL or server DDL."""

from contextlib import contextmanager
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from .connector_common import source_config, require_password, ConnectorError


def safe_error(error):
    code = getattr(error, "sqlstate", None)
    if code and code.startswith("28"):
        return "认证失败，请检查数据库账号和密码"
    return {
        "3D000": "数据库不存在，请检查数据库名称",
        "42501": "账号缺少读取所选表的权限，本次未生成原始库",
        "57014": "读取已取消或查询超时，本次未生成原始库",
        "55P03": "目标表正在变更，读取锁等待超时，请稍后重新采集",
    }.get(code, "数据库读取失败，请检查地址、端口、网络、权限或目标表是否变更")


class PostgresReader:
    def __init__(self, source, password):
        values = source_config(source)
        self.config = {
            k: v
            for k, v in values.items()
            if k in ("host", "database", "user", "port", "sslmode")
        }
        if values.get("caFile") or values["sslmode"] == "require":
            import certifi

            self.config["sslrootcert"] = values.get("caFile") or certifi.where()
            self.config["sslmode"] = "verify-full"
        require_password(source, password)
        self.password = password
        self.connection = None

    def __enter__(self):
        params = {**self.config, "dbname": self.config["database"]}
        params.pop("database")
        self.connection = psycopg.connect(
            **params,
            password=self.password,
            connect_timeout=8,
            application_name="governance_readonly_snapshot",
            options="-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=120000 -c DateStyle=ISO",
            keepalives=1,
            keepalives_idle=15,
            keepalives_interval=5,
            keepalives_count=2,
            row_factory=dict_row,
        )
        self.password = None
        self.connection.read_only = True
        self.connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        return self

    def __exit__(self, *_):
        if self.connection:
            try:
                self.connection.rollback()
            finally:
                self.connection.close()
        self.password = None

    def cancel(self):
        if self.connection:
            self.connection.cancel_safe(timeout=3)

    def info(self):
        return self.connection.execute(
            "SELECT current_database() AS database,current_setting('server_version') AS version,current_setting('transaction_read_only') AS read_only,current_setting('transaction_isolation') AS isolation"
        ).fetchone()

    def tables(self):
        return self.connection.execute("""
            SELECT c.oid::bigint AS oid,n.nspname AS schema,c.relname AS name,
                   greatest(c.reltuples,0)::bigint AS estimated_rows,obj_description(c.oid,'pg_class') AS comment
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND NOT c.relispartition
              AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
              AND has_table_privilege(c.oid,'SELECT') ORDER BY n.nspname,c.relname
        """).fetchall()

    def describe(self, table):
        columns = self.connection.execute(
            """
            SELECT a.attname AS name,pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,
                   t.typname AS native_type,NOT a.attnotnull AS nullable,
                   col_description(a.attrelid,a.attnum) AS comment,
                   EXISTS(SELECT 1 FROM pg_catalog.pg_index i WHERE i.indrelid=a.attrelid AND i.indisprimary AND a.attnum=ANY(i.indkey)) AS primary_key
            FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_type t ON t.oid=a.atttypid
            WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
        """,
            (table["oid"],),
        ).fetchall()
        if not columns:
            raise ValueError("所选表没有可采集字段，请刷新表清单")
        return {**table, "columns": columns}

    def batches(self, table, batch_size=500):
        query = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(",").join(
                sql.SQL("{}::text AS {}").format(
                    sql.Identifier(c["name"]), sql.Identifier(c["name"])
                )
                for c in table["columns"]
            ),
            sql.Identifier(table["schema"]),
            sql.Identifier(table["name"]),
        )
        with self.connection.cursor(name="snapshot_rows") as cursor:
            cursor.execute(query)
            while rows := cursor.fetchmany(batch_size):
                yield rows


@contextmanager
def open_reader(source, password):
    reader = None
    entered = False
    try:
        if source.get("type") == "postgresql":
            reader_class = PostgresReader
        else:
            from .db_readers import READERS

            reader_class = READERS.get(source.get("type"))
            if not reader_class:
                raise ConnectorError("数据库类型尚未支持")
        reader = reader_class(source, password)
        with reader:
            entered = True
            yield reader
    except ConnectorError:
        raise
    except psycopg.Error as error:
        raise ValueError(safe_error(error)) from None
    except ValueError as error:
        if password and password in str(error):
            raise ConnectorError("连接参数或读取配置无效，请检查后重试") from None
        raise
    except ImportError:
        raise ConnectorError(
            "连接器依赖缺失，请安装requirements.lock.txt中的依赖"
        ) from None
    except Exception as error:
        from .db_readers import safe_driver_error

        raise ConnectorError(safe_driver_error(source.get("type"), error)) from None
    finally:
        if reader:
            reader.password = None
            if not entered and reader.connection:
                try:
                    reader.connection.close()
                except Exception:
                    pass
