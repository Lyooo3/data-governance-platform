import copy
import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
import sqlite3
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

KINDS = (
    "sources",
    "workflows",
    "elements",
    "businessTypes",
    "qualifiers",
    "dictionaries",
    "catalogs",
    "assets",
    "rules",
    "qualityTasks",
    "services",
    "projects",
    "tables",
    "datasets",
    "alertPolicies",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    key = hashlib.scrypt(
        value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    return salt + ":" + key


def verify_password(value, hashed):
    return hmac.compare_digest(password_hash(value, hashed.split(":")[0]), hashed)


def public_user(user):
    return {k: v for k, v in user.items() if k != "passwordHash"}


TABLES = dict(
    zip(
        KINDS,
        (
            "data_sources",
            "governance_workflows",
            "data_elements",
            "business_types",
            "qualifiers",
            "dictionaries",
            "catalogs",
            "data_assets",
            "quality_rules",
            "quality_tasks",
            "data_services",
            "projects",
            "metadata_tables",
            "datasets",
            "alert_policies",
        ),
    )
)
FIELDS = {
    "sources": {
        "type": "source_type",
        "host": "host",
        "port": "port",
        "database": "database_name",
        "user": "user_name",
        "status": "status",
    },
    "workflows": {"description": "description"},
    "elements": {
        "code": "code",
        "field": "field_name",
        "dataType": "data_type",
        "version": "version",
    },
    "businessTypes": {"code": "code"},
    "qualifiers": {"code": "code", "version": "version"},
    "dictionaries": {"code": "code", "version": "version"},
    "catalogs": {"code": "code", "version": "version"},
    "assets": {
        "datasetId": "dataset_id",
        "catalogId": "catalog_id",
        "dataLevelName": "level_name",
        "sourceSystem": "source_system",
        "region": "region",
        "status": "status",
    },
    "rules": {"field": "field_name", "type": "rule_type"},
    "qualityTasks": {"datasetId": "dataset_id"},
    "services": {
        "datasetId": "dataset_id",
        "runId": "run_id",
        "viewId": "view_id",
        "published": "published",
        "apiKeyHash": "api_key_hash",
    },
    "projects": {"code": "code"},
    "tables": {"datasetId": "dataset_id"},
    "datasets": {"description": "description", "demo": "is_demo"},
    "alertPolicies": {"severity": "severity"},
}
CHILD_FIELDS = {
    "datasets": ("rows",),
    "workflows": ("nodes", "edges"),
    "dictionaries": ("dictionaryDetails",),
    "qualityTasks": ("ruleIds",),
    "tables": ("columns",),
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Store:
    """SQLite repository. Each write is transactional, with no in-memory state mirror."""

    def __init__(self, directory: Path, initialize=True):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / "platform.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            self.file, timeout=10, check_same_thread=False, isolation_level=None
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        try:
            schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
            if initialize:
                self.db.executescript(schema.read_text(encoding="utf-8"))
                from .local_store import upgrade

                upgrade(self)
                from .raw_store import upgrade as upgrade_raw

                upgrade_raw(self)
                with self.transaction():
                    self.db.execute(
                        "INSERT OR IGNORE INTO schema_migrations VALUES (1,?,?)",
                        ("initial governance schema", now()),
                    )
                    if not self.setting("initialization_complete"):
                        self._initialize()
                self.interrupt_running()
                with self.transaction():
                    self.db.execute(
                        "DELETE FROM platform_sessions WHERE expires_at <= ?",
                        (time.time(),),
                    )
        except Exception:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        with self.lock:
            nested = self.db.in_transaction
            if not nested:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if not nested:
                    self.db.execute("COMMIT")
            except BaseException:
                if not nested and self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def setting(self, key):
        with self.lock:
            row = self.db.execute(
                "SELECT value_json FROM platform_settings WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def set_setting(self, key, value):
        with self.transaction():
            self.db.execute(
                "INSERT INTO platform_settings VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, encoded(value), now()),
            )

    def _initialize(self):
        source = self.directory / "state.json"
        backup = None
        if source.exists():
            backup_dir = self.directory / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / (
                "state-before-sqlite-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                + "-"
                + secrets.token_hex(3)
                + ".json"
            )
            shutil.copy2(source, backup)
            state = json.loads(source.read_text(encoding="utf-8"))
        else:
            from .seed import initial_state

            state = initial_state()
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("entities"), dict)
            or not isinstance(state.get("users"), dict)
        ):
            raise ValueError("原JSON数据结构无效，未导入；原文件和备份已保留")
        for value in state["users"].values():
            self._save_user(value)
        order = [
            "datasets",
            "projects",
            "businessTypes",
            "elements",
            "qualifiers",
            "dictionaries",
            "catalogs",
            "rules",
            "sources",
            "workflows",
            "qualityTasks",
            "assets",
            "tables",
            "alertPolicies",
        ]
        for kind in order:
            for key, value in state["entities"].get(kind, {}).items():
                self.save(kind, value, key)
        for run in state.get("runs", {}).values():
            self.save_run(run)
        for key, value in state["entities"].get("services", {}).items():
            self.save("services", value, key)
        for alert in state.get("alerts", {}).values():
            self.save_alert(alert)
        for item in state.get("audit", []):
            self._save_audit(item)
        expected = {TABLES[k]: len(state["entities"].get(k, {})) for k in KINDS}
        expected.update(
            platform_users=len(state["users"]),
            job_runs=len(state.get("runs", {})),
            data_alerts=len(state.get("alerts", {})),
            audit_logs=len(state.get("audit", [])),
            dataset_rows=sum(
                len(d.get("rows", []))
                for d in state["entities"].get("datasets", {}).values()
            ),
            job_result_rows=sum(
                len(r.get("rows", [])) for r in state.get("runs", {}).values()
            ),
        )
        for table, count in expected.items():
            actual = self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if actual != count:
                raise ValueError(f"迁移数量校验失败：{table}")
        self.set_setting("initialization_complete", True)
        self.set_setting(
            "migration_info",
            {
                "source": "state.json" if source.exists() else "seed",
                "backup": backup.name if backup else None,
                "completedAt": now(),
                "counts": expected,
            },
        )

    def _insert(self, table, columns, values, conflict):
        names = ",".join(columns)
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c not in conflict)
        self.db.execute(
            f'INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT({",".join(conflict)}) DO UPDATE SET {updates}',
            values,
        )

    def _entity(self, kind, row):
        value = json.loads(row["payload_json"])
        value.update(
            id=row["id"],
            name=row["name"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )
        for field, column in FIELDS[kind].items():
            if field in value or row[column] is not None:
                value[field] = (
                    bool(row[column]) if field in ("demo", "published") else row[column]
                )
        key = row["id"]
        if kind == "datasets":
            value["rows"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT data_json FROM dataset_rows WHERE dataset_id=? ORDER BY row_index",
                    (key,),
                )
            ]
        elif kind == "dictionaries":
            value["dictionaryDetails"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM dictionary_items WHERE dictionary_id=? ORDER BY position",
                    (key,),
                )
            ]
        elif kind == "tables":
            value["columns"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM metadata_columns WHERE table_id=? ORDER BY position",
                    (key,),
                )
            ]
        elif kind == "qualityTasks":
            value["ruleIds"] = [
                r[0]
                for r in self.db.execute(
                    "SELECT rule_id FROM quality_task_rules WHERE task_id=? ORDER BY position",
                    (key,),
                )
            ]
        elif kind == "workflows":
            value["nodes"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM workflow_nodes WHERE workflow_id=? ORDER BY position",
                    (key,),
                )
            ]
            value["edges"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM workflow_edges WHERE workflow_id=? ORDER BY position",
                    (key,),
                )
            ]
        return value

    def all(self, kind):
        with self.lock:
            return [
                self._entity(kind, row)
                for row in self.db.execute(
                    f"SELECT * FROM {TABLES[kind]} ORDER BY created_at,id"
                ).fetchall()
            ]

    def get(self, kind, key):
        with self.lock:
            row = self.db.execute(
                f"SELECT * FROM {TABLES[kind]} WHERE id=?", (key,)
            ).fetchone()
            return self._entity(kind, row) if row else None

    def save(self, kind, value, key=None):
        with self.transaction():
            key = key or str(uuid.uuid4())
            old = self.get(kind, key) or {}
            record = {
                **old,
                **copy.deepcopy(value),
                "id": key,
                "createdAt": old.get("createdAt", value.get("createdAt") or now()),
                "updatedAt": value.get("updatedAt") if not old else now(),
            }
            record["updatedAt"] = record["updatedAt"] or now()
            encoded(record)
            body = {
                k: v for k, v in record.items() if k not in CHILD_FIELDS.get(kind, ())
            }
            columns = ["id", "name", "created_at", "updated_at", "payload_json"] + list(
                FIELDS[kind].values()
            )
            values = [
                key,
                record["name"],
                record["createdAt"],
                record["updatedAt"],
                encoded(body),
            ]
            for field in FIELDS[kind]:
                item = record.get(field)
                if field in ("demo", "published"):
                    item = int(bool(item))
                elif field.endswith("Id") and item == "":
                    item = None
                elif kind == "sources" and field == "status":
                    item = item or "draft"
                values.append(item)
            self._insert(TABLES[kind], columns, values, ("id",))
            self._save_children(kind, key, record)
            return self.get(kind, key)

    def _save_children(self, kind, key, value):
        if kind == "datasets":
            self.db.execute("DELETE FROM dataset_rows WHERE dataset_id=?", (key,))
            self.db.executemany(
                "INSERT INTO dataset_rows VALUES (?,?,?)",
                [(key, i, encoded(row)) for i, row in enumerate(value.get("rows", []))],
            )
        elif kind == "dictionaries":
            self.db.execute(
                "DELETE FROM dictionary_items WHERE dictionary_id=?", (key,)
            )
            self.db.executemany(
                "INSERT INTO dictionary_items VALUES (?,?,?,?,?)",
                [
                    (key, i, str(r["code"]), str(r["name"]), encoded(r))
                    for i, r in enumerate(value.get("dictionaryDetails", []))
                ],
            )
        elif kind == "tables":
            self.db.execute("DELETE FROM metadata_columns WHERE table_id=?", (key,))
            self.db.executemany(
                "INSERT INTO metadata_columns VALUES (?,?,?,?,?)",
                [
                    (key, i, r["name"], r.get("type"), encoded(r))
                    for i, r in enumerate(value.get("columns", []))
                ],
            )
        elif kind == "qualityTasks":
            self.db.execute("DELETE FROM quality_task_rules WHERE task_id=?", (key,))
            self.db.executemany(
                "INSERT INTO quality_task_rules VALUES (?,?,?)",
                [(key, i, rule) for i, rule in enumerate(value.get("ruleIds", []))],
            )
        elif kind == "workflows":
            self.db.execute("DELETE FROM workflow_nodes WHERE workflow_id=?", (key,))
            for i, node in enumerate(value.get("nodes", [])):
                cfg = node.get("config", {})
                self.db.execute(
                    "INSERT INTO workflow_nodes VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        node["id"],
                        i,
                        node["type"],
                        node.get("label"),
                        node.get("x", 0),
                        node.get("y", 0),
                        cfg.get("datasetId") or None,
                        encoded(cfg),
                        encoded(node),
                    ),
                )
                if node["type"] == "quality":
                    self.db.executemany(
                        "INSERT INTO workflow_node_rules VALUES (?,?,?,?)",
                        [
                            (key, node["id"], j, rule)
                            for j, rule in enumerate(cfg.get("ruleIds", []))
                        ],
                    )
            self.db.executemany(
                "INSERT INTO workflow_edges VALUES (?,?,?,?,?)",
                [
                    (key, i, edge["source"], edge["target"], encoded(edge))
                    for i, edge in enumerate(value.get("edges", []))
                ],
            )

    def remove(self, kind, key):
        with self.transaction():
            self.db.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (key,))

    def _save_user(self, value):
        body = {k: v for k, v in value.items() if k != "passwordHash"}
        self._insert(
            "platform_users",
            ["id", "name", "role", "password_hash", "created_at", "payload_json"],
            [
                value["id"],
                value["name"],
                value["role"],
                value["passwordHash"],
                value.get("createdAt") or now(),
                encoded(body),
            ],
            ("id",),
        )

    def users(self):
        with self.lock:
            return [
                dict(json.loads(r["payload_json"]), passwordHash=r["password_hash"])
                for r in self.db.execute(
                    "SELECT * FROM platform_users ORDER BY created_at,id"
                )
            ]

    def get_user(self, key):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM platform_users WHERE id=?", (key,)
            ).fetchone()
            return (
                dict(json.loads(row["payload_json"]), passwordHash=row["password_hash"])
                if row
                else None
            )

    def create_user(self, name, password, role, actor):
        with self.transaction():
            value = {
                "id": str(uuid.uuid4()),
                "name": name,
                "role": role,
                "passwordHash": password_hash(password),
                "createdAt": now(),
            }
            self._save_user(value)
            self.audit(actor, "user.create", value["id"])
            return value

    def create_session(self, user_id, token):
        with self.transaction():
            self.db.execute(
                "DELETE FROM platform_sessions WHERE expires_at<=?", (time.time(),)
            )
            self.db.execute(
                "INSERT INTO platform_sessions VALUES (?,?,?,?)",
                (digest(token), user_id, time.time() + 28800, now()),
            )

    def session(self, token):
        with self.lock:
            row = self.db.execute(
                "SELECT user_id,expires_at FROM platform_sessions WHERE token_hash=? AND expires_at>?",
                (digest(token), time.time()),
            ).fetchone()
            return (
                {"userId": row["user_id"], "expires": row["expires_at"]}
                if row
                else None
            )

    def revoke_session(self, token):
        with self.transaction():
            self.db.execute(
                "DELETE FROM platform_sessions WHERE token_hash=?", (digest(token),)
            )

    def _save_audit(self, value):
        self._insert(
            "audit_logs",
            ["id", "actor_name", "action", "target", "created_at", "payload_json"],
            [
                value["id"],
                value["actor"],
                value["action"],
                value.get("target", ""),
                value["createdAt"],
                encoded(value),
            ],
            ("id",),
        )

    def audit(self, user, action, target=""):
        with self.transaction():
            self._save_audit(
                {
                    "id": str(uuid.uuid4()),
                    "actor": user,
                    "action": action,
                    "target": target,
                    "createdAt": now(),
                }
            )

    def audits(self):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM audit_logs ORDER BY created_at DESC,id"
                )
            ]

    def save_run(self, run):
        with self.transaction():
            record = {
                k: v for k, v in run.items() if k not in ("rows", "steps", "reports")
            }
            self._insert(
                "job_runs",
                [
                    "id",
                    "name",
                    "workflow_id",
                    "task_id",
                    "actor_name",
                    "status",
                    "source_count",
                    "output_count",
                    "started_at",
                    "finished_at",
                    "error_message",
                    "payload_json",
                ],
                [
                    run["id"],
                    run["name"],
                    (
                        run.get("workflowId")
                        if self.get("workflows", run.get("workflowId"))
                        else None
                    ),
                    (
                        run.get("taskId")
                        if self.get("qualityTasks", run.get("taskId"))
                        else None
                    ),
                    run["actor"],
                    run["status"],
                    run.get("sourceCount"),
                    run.get("outputCount"),
                    run["startedAt"],
                    run.get("finishedAt"),
                    run.get("error"),
                    encoded(record),
                ],
                ("id",),
            )
            key = run["id"]
            self.db.execute("DELETE FROM job_steps WHERE run_id=?", (key,))
            self.db.execute("DELETE FROM quality_reports WHERE run_id=?", (key,))
            self.db.execute("DELETE FROM job_result_rows WHERE run_id=?", (key,))
            self.db.executemany(
                "INSERT INTO job_steps VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        key,
                        i,
                        s.get("nodeId"),
                        s.get("name"),
                        s.get("type"),
                        s.get("inputCount"),
                        s.get("outputCount"),
                        encoded(s),
                    )
                    for i, s in enumerate(run.get("steps", []))
                ],
            )
            for i, report in enumerate(run.get("reports", [])):
                summary = {k: v for k, v in report.items() if k != "rules"}
                self.db.execute(
                    "INSERT INTO quality_reports VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        i,
                        report.get("nodeId"),
                        report.get("nodeName"),
                        report["total"],
                        report["invalidRows"],
                        report["validRows"],
                        report.get("passRate"),
                        encoded(summary),
                    ),
                )
                self.db.executemany(
                    "INSERT INTO quality_rule_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            key,
                            i,
                            j,
                            r.get("id"),
                            r["name"],
                            r.get("field"),
                            r.get("type"),
                            r["total"],
                            r["failed"],
                            r["passed"],
                            encoded(r.get("failedIndexes", [])),
                            encoded(r),
                        )
                        for j, r in enumerate(report.get("rules", []))
                    ],
                )
            self.db.executemany(
                "INSERT INTO job_result_rows VALUES (?,?,?)",
                [(key, i, encoded(row)) for i, row in enumerate(run.get("rows", []))],
            )

    def _run(self, row, include_rows=True):
        run = json.loads(row["payload_json"])
        key = run["id"]
        run.update(status=row["status"], finishedAt=row["finished_at"])
        if row["error_message"]:
            run["error"] = row["error_message"]
        run["steps"] = [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload_json FROM job_steps WHERE run_id=? ORDER BY position",
                (key,),
            )
        ]
        run["reports"] = []
        for report in self.db.execute(
            "SELECT report_index,payload_json FROM quality_reports WHERE run_id=? ORDER BY report_index",
            (key,),
        ):
            value = json.loads(report["payload_json"])
            value["rules"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM quality_rule_results WHERE run_id=? AND report_index=? ORDER BY position",
                    (key, report["report_index"]),
                )
            ]
            run["reports"].append(value)
        if include_rows:
            run["rows"] = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT data_json FROM job_result_rows WHERE run_id=? ORDER BY row_index",
                    (key,),
                )
            ]
        return run

    def run(self, key):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM job_runs WHERE id=?", (key,)
            ).fetchone()
            return self._run(row) if row else None

    def runs(self):
        with self.lock:
            return [
                self._run(r, include_rows=False)
                for r in self.db.execute(
                    "SELECT * FROM job_runs ORDER BY started_at DESC,id"
                ).fetchall()
            ]

    def interrupt_running(self):
        with self.transaction():
            self.db.execute(
                "UPDATE job_runs SET status='INTERRUPTED',error_message='服务重启，上次任务已中断',finished_at=? WHERE status='RUNNING'",
                (now(),),
            )

    def save_alert(self, alert):
        with self.transaction():
            self._insert(
                "data_alerts",
                [
                    "id",
                    "run_id",
                    "name",
                    "field_name",
                    "failed_rows",
                    "status",
                    "created_at",
                    "resolved_at",
                    "resolved_by",
                    "note",
                    "failed_indexes_json",
                    "payload_json",
                ],
                [
                    alert["id"],
                    alert["runId"],
                    alert["name"],
                    alert.get("field"),
                    alert["failed"],
                    alert["status"],
                    alert["createdAt"],
                    alert.get("resolvedAt"),
                    alert.get("resolvedBy"),
                    alert.get("note"),
                    encoded(alert.get("failedIndexes", [])),
                    encoded(alert),
                ],
                ("id",),
            )
            return self.alert(alert["id"])

    def alert(self, key):
        with self.lock:
            row = self.db.execute(
                "SELECT payload_json FROM data_alerts WHERE id=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def alerts(self):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload_json FROM data_alerts ORDER BY created_at DESC,id"
                )
            ]

    def info(self):
        with self.lock:
            tables = [
                r[0]
                for r in self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            counts = {
                name: self.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                for name in tables
            }
            return {
                "engine": "sqlite",
                "file": str(self.file),
                "schemaVersion": self.db.execute(
                    "SELECT max(version) FROM schema_migrations"
                ).fetchone()[0],
                "tables": counts,
                "tableCount": len(tables),
                "migration": self.setting("migration_info"),
            }

    def check(self):
        with self.lock:
            return {
                "integrity": [r[0] for r in self.db.execute("PRAGMA integrity_check")],
                "foreignKeyViolations": [
                    tuple(r) for r in self.db.execute("PRAGMA foreign_key_check")
                ],
            }

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.file:
            raise ValueError("备份目标不能覆盖当前数据库")
        if destination.exists():
            raise ValueError("备份目标已存在，请使用新文件名")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            with sqlite3.connect(destination) as target:
                self.db.backup(target)
                integrity = target.execute("PRAGMA integrity_check").fetchall()
                foreign_keys = target.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != [("ok",)] or foreign_keys:
                    raise ValueError("备份数据库验证失败，请勿用其恢复")
        return str(destination)

    def close(self):
        with self.lock:
            self.db.close()
