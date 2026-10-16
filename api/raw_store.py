"""Immutable raw snapshot files, separate from editable governance datasets."""

import asyncio
import hashlib
import json
import math
import sqlite3
import threading
import uuid
from pathlib import Path
from .connectors import open_reader
from .storage import now, encoded
from .connector_common import PUBLIC_FIELDS, require_password

MAX_RAW_BYTES = 2 * 1024**3


def upgrade(store):
    store.db.executescript(
        (Path(__file__).resolve().parents[1] / "db/schema-v3.sql").read_text(
            encoding="utf8"
        )
    )
    store.db.execute(
        "INSERT OR IGNORE INTO schema_migrations VALUES (3,?,?)",
        ("readonly raw database snapshots", now()),
    )


def normalized(value, column):
    if value is None:
        return None
    kind = column.get("value_kind") or column["native_type"]
    try:
        if kind in ("int2", "int4", "int8", "oid", "integer"):
            number = int(value)
            return number if abs(number) <= 2**53 - 1 else value
        if kind in ("float4", "float8", "numeric", "number"):
            number = float(value)
            return (
                number
                if math.isfinite(number)
                and len(str(value).replace(".", "").replace("-", "")) <= 15
                else value
            )
        if kind in ("bool", "boolean"):
            return value in ("t", "true", "1")
    except (ValueError, TypeError, OverflowError):
        pass
    return value


class RawManager:
    def __init__(self, store):
        self.store = store
        self.directory = (store.directory / "raw").resolve()
        self.directory.mkdir(exist_ok=True)
        self.gate = threading.RLock()
        self.thread = None
        self.stop = threading.Event()
        self.reader = None
        self.active = None
        with store.transaction():
            for snap in self.list():
                if snap["status"] == "RUNNING":
                    self.patch(
                        snap["id"],
                        status="INTERRUPTED",
                        error="平台重启中断采集，请重新创建原始库",
                        finishedAt=now(),
                    )
                    self.path(snap["id"], True).unlink(missing_ok=True)

    def path(self, key, partial=False):
        if str(uuid.UUID(key)) != key:
            raise ValueError("原始库标识无效")
        return self.directory / (key + (".partial" if partial else ".sqlite3"))

    def get(self, key):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT payload_json FROM raw_snapshots WHERE id=?", (key,)
            ).fetchone()
        if not row:
            raise ValueError("原始库不存在")
        return json.loads(row[0])

    def list(self, source_id=None):
        with self.store.lock:
            query = "SELECT payload_json FROM raw_snapshots"
            args = ()
            if source_id:
                query += " WHERE source_id=?"
                args = (source_id,)
            return [
                json.loads(r[0])
                for r in self.store.db.execute(
                    query + " ORDER BY created_at DESC,id", args
                )
            ]

    def patch(self, key, **changes):
        with self.store.transaction():
            value = {**self.get(key), **changes, "updatedAt": now()}
            self.store.db.execute(
                "UPDATE raw_snapshots SET status=?,updated_at=?,payload_json=? WHERE id=?",
                (value["status"], value["updatedAt"], encoded(value), key),
            )
            return value

    def tables(self, key):
        self.get(key)
        with self.store.lock:
            return [
                json.loads(r[0])
                for r in self.store.db.execute(
                    "SELECT payload_json FROM raw_snapshot_tables WHERE snapshot_id=? ORDER BY schema_name,table_name",
                    (key,),
                )
            ]

    def table(self, key, table_id):
        table = next((t for t in self.tables(key) if t["id"] == table_id), None)
        if not table:
            raise ValueError("原始表不存在")
        return table

    def start(self, source, password, selected, name, actor):
        require_password(source, password)
        if selected is not None and (
            not isinstance(selected, list)
            or not selected
            or len(selected) > 2000
            or any(
                not isinstance(x, int) or isinstance(x, bool) or x <= 0
                for x in selected
            )
        ):
            raise ValueError("请勾选有效的业务表，或选择采集全部业务表")
        name = str(name or source["name"] + "-原始库").strip()
        if not name or len(name) > 120:
            raise ValueError("原始库名称需要1至120个字符")
        from .connectors import source_config

        source_config(source)
        with self.gate:
            if self.thread and self.thread.is_alive():
                raise ValueError("已有原始库正在采集，请等待完成或取消")
            key = str(uuid.uuid4())
            value = dict(
                id=key,
                sourceId=source["id"],
                name=name,
                status="RUNNING",
                createdAt=now(),
                updatedAt=now(),
                source={k: source.get(k) for k in PUBLIC_FIELDS},
                scope="all" if selected is None else "selected",
                selectedTableCount=len(selected) if selected else None,
                tableCount=0,
                completedTables=0,
                rowCount=0,
                bytes=0,
                currentTable="",
                error="",
                actor=actor,
            )
            with self.store.transaction():
                self.store.db.execute(
                    "INSERT INTO raw_snapshots VALUES (?,?,?,?,?,?,?)",
                    (
                        key,
                        source["id"],
                        name,
                        "RUNNING",
                        value["createdAt"],
                        value["updatedAt"],
                        encoded(value),
                    ),
                )
                self.store.audit(actor, "raw.snapshot.start", key)
            self.stop = threading.Event()
            self.active = key
            self.thread = threading.Thread(
                target=self.capture,
                args=(key, source, password, selected, actor),
                daemon=True,
            )
            self.thread.start()
            return value

    def capture(self, key, source, password, selected, actor):
        db = None
        total = size = completed = 0
        try:
            partial = self.path(key, True)
            db = sqlite3.connect(partial)
            db.executescript(
                "CREATE TABLE raw_tables(id TEXT PRIMARY KEY,metadata_json TEXT NOT NULL); CREATE TABLE raw_rows(table_id TEXT NOT NULL,row_index INTEGER NOT NULL,data_json TEXT NOT NULL,PRIMARY KEY(table_id,row_index)); CREATE TABLE manifest(value_json TEXT NOT NULL);"
            )
            with open_reader(source, password) as reader:
                self.reader = reader
                password = None
                info = reader.info()
                if info["read_only"] != "on":
                    raise ValueError("目标连接未处于只读采集模式，已停止")
                consistent = info.get(
                    "consistent_snapshot", info.get("isolation") == "repeatable read"
                )
                if (
                    source.get("consistencyMode", "strict") == "strict"
                    and not consistent
                ):
                    raise ValueError(
                        "当前数据库模式不支持整批一致快照；如接受采集期间数据变化，请在数据源明确选择尽力读取"
                    )
                available = reader.tables()
                selected_set = set(selected) if selected is not None else None
                tables = [
                    t
                    for t in available
                    if selected_set is None or t["oid"] in selected_set
                ]
                if not tables or (
                    selected_set is not None
                    and {t["oid"] for t in tables} != selected_set
                ):
                    raise ValueError("业务表不存在或读取权限已变更，请重新扫描")
                if len(tables) > 2000:
                    raise ValueError("单次最多2000张表，请分批选择")
                if len({t["oid"] for t in tables}) != len(tables):
                    raise ValueError("表标识发生冲突，请减少范围或联系维护人员")
                self.patch(
                    key, tableCount=len(tables), transaction=info, snapshotAt=now()
                )
                for target in tables:
                    if self.stop.is_set():
                        raise InterruptedError()
                    table = {
                        **reader.describe(target),
                        "id": str(uuid.uuid4()),
                        "rowCount": 0,
                    }
                    self.patch(
                        key,
                        currentTable=table["schema"] + "." + table["name"],
                        currentTableRows=0,
                    )
                    digest = hashlib.sha256()
                    for batch in reader.batches(table):
                        if self.stop.is_set():
                            raise InterruptedError()
                        values = []
                        for row in batch:
                            text = encoded(row)
                            size += len(text.encode("utf8"))
                            if size > MAX_RAW_BYTES:
                                raise ValueError(
                                    "原始记录超过单次2GiB限制，本批未完成；请减少所选表后重新采集"
                                )
                            digest.update(text.encode("utf8"))
                            values.append((table["id"], table["rowCount"], text))
                            table["rowCount"] += 1
                        db.executemany("INSERT INTO raw_rows VALUES (?,?,?)", values)
                        db.commit()
                        total += len(batch)
                        self.patch(
                            key,
                            rowCount=total,
                            bytes=size,
                            currentTableRows=table["rowCount"],
                        )
                    table["sha256"] = digest.hexdigest()
                    db.execute(
                        "INSERT INTO raw_tables VALUES (?,?)",
                        (table["id"], encoded(table)),
                    )
                    db.commit()
                    with self.store.transaction():
                        self.store.db.execute(
                            "INSERT INTO raw_snapshot_tables VALUES (?,?,?,?,?,?)",
                            (
                                table["id"],
                                key,
                                table["schema"],
                                table["name"],
                                table["rowCount"],
                                encoded(table),
                            ),
                        )
                    completed += 1
                    self.patch(key, completedTables=completed)
            self.reader = None
            with self.gate:
                if self.stop.is_set():
                    raise InterruptedError()
                manifest = {**self.get(key), "status": "SUCCESS", "finishedAt": now()}
                db.execute("INSERT INTO manifest VALUES (?)", (encoded(manifest),))
                db.commit()
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("本地原始库完整性检查失败")
                db.close()
                db = None
                partial.replace(self.path(key))
                self.patch(
                    key,
                    status="SUCCESS",
                    finishedAt=manifest["finishedAt"],
                    fileBytes=self.path(key).stat().st_size,
                    currentTable="",
                )
                self.store.audit(actor, "raw.snapshot.success", key)
        except Exception as error:
            cancelled = self.stop.is_set() or isinstance(error, InterruptedError)
            message = (
                "采集已取消，未发布不完整原始库"
                if cancelled
                else (
                    str(error)
                    if isinstance(error, ValueError)
                    else "本地采集失败，请检查磁盘空间或重新采集"
                )
            )
            self.patch(
                key,
                status="CANCELLED" if cancelled else "FAILED",
                error=message,
                finishedAt=now(),
            )
            with self.store.transaction():
                self.store.db.execute(
                    "DELETE FROM raw_snapshot_tables WHERE snapshot_id=?", (key,)
                )
            self.store.audit(
                actor,
                "raw.snapshot.cancelled" if cancelled else "raw.snapshot.failed",
                key,
            )
        finally:
            password = None
            self.reader = None
            if db:
                db.close()
            self.path(key, True).unlink(missing_ok=True)

    def cancel(self, key):
        with self.gate:
            if self.get(key)["status"] != "RUNNING" or key != self.active:
                raise ValueError("只有正在采集的原始库可以取消")
            self.stop.set()
            result = self.patch(key, cancelRequested=True)
        reader = self.reader
        if reader and getattr(reader, "cancel", None):
            try:
                reader.cancel()
            except Exception:
                pass
        return result

    async def close(self):
        self.stop.set()
        if self.reader and getattr(self.reader, "cancel", None):
            try:
                await asyncio.to_thread(self.reader.cancel)
            except Exception:
                pass
        if self.thread:
            await asyncio.to_thread(self.thread.join)

    def rows(self, key, table_id, offset=0, limit=20, fields=None, raw=False):
        if self.get(key)["status"] != "SUCCESS":
            raise ValueError("原始库尚未成功完成，不能读取或治理")
        table = self.table(key, table_id)
        columns = table["columns"]
        if fields is not None:
            if (
                not isinstance(fields, list)
                or not fields
                or any(not isinstance(f, str) for f in fields)
                or len(set(fields)) != len(fields)
                or any(f not in {c["name"] for c in columns} for f in fields)
            ):
                raise ValueError("请选择有效且不重复的字段")
            columns = [next(c for c in columns if c["name"] == f) for f in fields]
        with sqlite3.connect(self.path(key).as_uri() + "?mode=ro", uri=True) as db:
            records = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT data_json FROM raw_rows WHERE table_id=? AND row_index>=? ORDER BY row_index LIMIT ?",
                    (table_id, offset, limit),
                )
            ]
        return [
            {
                c["name"]: r[c["name"]] if raw else normalized(r[c["name"]], c)
                for c in columns
            }
            for r in records
        ]

    def materialize(self, key, table_id, body, actor):
        table = self.table(key, table_id)
        fields = body.get("fields") or [c["name"] for c in table["columns"]]
        offset = int(body.get("offset", 0))
        limit = int(body.get("limit", 10000))
        if (
            offset < 0
            or not 1 <= limit <= 10000
            or not isinstance(fields, list)
            or len(fields) > 100
        ):
            raise ValueError("每次治理副本最多10000行、100字段，起始行不能为负数")
        if table["rowCount"] and offset >= table["rowCount"]:
            raise ValueError("起始行超过原始表记录数")
        rows = self.rows(key, table_id, offset, limit, fields)
        name = str(
            body.get("name") or table["schema"] + "." + table["name"] + "-治理副本"
        ).strip()
        if not name or len(name) > 120:
            raise ValueError("副本名称需要1至120个字符")
        provenance = dict(
            snapshotId=key,
            tableId=table_id,
            schema=table["schema"],
            table=table["name"],
            offset=offset,
            limit=limit,
            rowCount=len(rows),
            sourceRowCount=table["rowCount"],
            fields=fields,
        )
        with self.store.transaction():
            dataset = self.store.save(
                "datasets",
                dict(
                    name=name,
                    rows=rows,
                    description="从本地原始库创建，原始快照保持不变",
                    rawOrigin=provenance,
                ),
            )
            self.store.db.execute(
                "INSERT INTO raw_dataset_links VALUES (?,?,?,?,?)",
                (dataset["id"], key, table_id, now(), encoded(provenance)),
            )
            self.store.audit(actor, "raw.dataset.create", dataset["id"])
        return {
            **{k: v for k, v in dataset.items() if k != "rows"},
            "rowCount": len(rows),
        }
