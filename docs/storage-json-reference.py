import copy
import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
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


class Store:
    """Single-process file repository; replace this boundary when a DB is configured."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = directory / "state.json"
        self.lock = threading.RLock()
        if self.file.exists():
            self.state = json.loads(self.file.read_text(encoding="utf-8"))
        else:
            self.state = {
                "entities": {k: {} for k in KINDS},
                "users": {},
                "runs": {},
                "audit": [],
                "alerts": {},
            }
            self.seed()
        for kind in KINDS:
            self.state["entities"].setdefault(kind, {})
        for run in self.state["runs"].values():
            if run["status"] == "RUNNING":
                run.update(
                    status="INTERRUPTED", error="服务重启，任务已中断", finishedAt=now()
                )
        self.flush()

    def flush(self):
        with self.lock:
            temporary = self.file.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(self.state, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.file)

    def all(self, kind):
        with self.lock:
            return copy.deepcopy(list(self.state["entities"][kind].values()))

    def get(self, kind, key):
        with self.lock:
            return copy.deepcopy(self.state["entities"][kind].get(key))

    def save(self, kind, value, key=None):
        with self.lock:
            key = key or str(uuid.uuid4())
            old = self.state["entities"][kind].get(key, {})
            record = {
                **old,
                **copy.deepcopy(value),
                "id": key,
                "createdAt": old.get("createdAt", now()),
                "updatedAt": now(),
            }
            self.state["entities"][kind][key] = record
            self.flush()
            return copy.deepcopy(record)

    def remove(self, kind, key):
        with self.lock:
            self.state["entities"][kind].pop(key)
            self.flush()

    def audit(self, user, action, target=""):
        with self.lock:
            self.state["audit"].insert(
                0,
                {
                    "id": str(uuid.uuid4()),
                    "actor": user,
                    "action": action,
                    "target": target,
                    "createdAt": now(),
                },
            )
            self.state["audit"] = self.state["audit"][:10000]
            self.flush()

    def save_run(self, run):
        with self.lock:
            self.state["runs"][run["id"]] = copy.deepcopy(run)
            self.flush()

    def run(self, key):
        with self.lock:
            return copy.deepcopy(self.state["runs"].get(key))

    def runs(self):
        with self.lock:
            return sorted(
                copy.deepcopy(list(self.state["runs"].values())),
                key=lambda r: r["startedAt"],
                reverse=True,
            )

    def seed(self):
        admin_id = "local-admin"
        self.state["users"][admin_id] = {
            "id": admin_id,
            "name": "admin",
            "role": "admin",
            "passwordHash": password_hash(
                os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(32)
            ),
            "createdAt": now(),
        }
        rows = [
            {
                "id": r[0],
                "record_code": r[1],
                "org_name": r[2],
                "score": r[3],
                "category": r[4],
            }
            for r in [
                [1, "R001", " 示例单位甲 ", 90, "A"],
                [2, "R002", "示例单位乙", 80, "B"],
                [3, "R002", "示例单位乙", 80, "B"],
                [4, "R003", "", 70, "A"],
                [5, "R004", "示例单位丙", 120, "B"],
                [6, "R005", "示例单位丁", 60, "A"],
                [7, "R006", " 示例单位戊 ", 85, "B"],
                [8, "R007", "示例单位己", 75, "A"],
            ]
        ]
        examples = {
            "datasets": [
                {
                    "id": "demo-dataset",
                    "name": "治理演示样例",
                    "description": "内置JSON样例，不连接任何数据库",
                    "rows": rows,
                    "demo": True,
                }
            ],
            "projects": [
                {"id": "local-project", "name": "本地数据治理", "code": "LOCAL"}
            ],
            "businessTypes": [
                {"id": "demo-business", "name": "示例业务", "code": "DEMO"}
            ],
            "elements": [
                {
                    "id": "demo-element",
                    "name": "单位名称",
                    "field": "org_name",
                    "code": "DE0001",
                    "dataType": "字符串",
                    "version": "1.0",
                }
            ],
            "qualifiers": [
                {
                    "id": "demo-qualifier",
                    "name": "名称",
                    "code": "Q0001",
                    "version": "1.0",
                }
            ],
            "dictionaries": [
                {
                    "id": "demo-dictionary",
                    "name": "类别代码",
                    "code": "CATEGORY",
                    "version": "1.0",
                    "dictionaryDetails": [
                        {"code": "A", "name": "类别A"},
                        {"code": "B", "name": "类别B"},
                    ],
                }
            ],
            "catalogs": [
                {
                    "id": "demo-catalog",
                    "name": "演示数据目录",
                    "code": "LOCAL-001",
                    "version": "1.0",
                }
            ],
            "assets": [
                {
                    "id": "demo-asset",
                    "name": "治理样例资源",
                    "datasetId": "demo-dataset",
                    "catalogId": "demo-catalog",
                    "dataLevelName": "内部",
                    "sourceSystem": "内置样例",
                    "region": "本地",
                    "status": "registered",
                }
            ],
            "rules": [
                {
                    "id": "rule-required",
                    "name": "单位名称不能为空",
                    "field": "org_name",
                    "type": "required",
                },
                {
                    "id": "rule-score",
                    "name": "分值应在0至100之间",
                    "field": "score",
                    "type": "range",
                    "min": 0,
                    "max": 100,
                },
            ],
            "qualityTasks": [
                {
                    "id": "demo-task",
                    "name": "样例数据质量检测",
                    "datasetId": "demo-dataset",
                    "ruleIds": ["rule-required", "rule-score"],
                }
            ],
            "tables": [
                {
                    "id": "demo-table",
                    "name": "demo_records",
                    "datasetId": "demo-dataset",
                    "description": "样例字段结构",
                    "columns": [
                        {
                            "name": k,
                            "type": (
                                "number" if isinstance(v, (int, float)) else "string"
                            ),
                        }
                        for k, v in rows[0].items()
                    ],
                }
            ],
        }
        for kind, values in examples.items():
            for value in values:
                self.state["entities"][kind][value["id"]] = {
                    **value,
                    "createdAt": now(),
                    "updatedAt": now(),
                }
        nodes = [
            {
                "id": "n1",
                "type": "source",
                "label": "读取演示样例",
                "x": 30,
                "y": 140,
                "config": {"datasetId": "demo-dataset"},
            },
            {
                "id": "n2",
                "type": "clean",
                "label": "清理单位名称空格",
                "x": 245,
                "y": 140,
                "config": {"fields": ["org_name"], "operation": "trim"},
            },
            {
                "id": "n3",
                "type": "dedupe",
                "label": "按记录编号去重",
                "x": 460,
                "y": 140,
                "config": {"fields": ["record_code"]},
            },
            {
                "id": "n4",
                "type": "quality",
                "label": "完整性与范围检查",
                "x": 675,
                "y": 140,
                "config": {"ruleIds": ["rule-required", "rule-score"]},
            },
            {
                "id": "n5",
                "type": "output",
                "label": "保存治理结果",
                "x": 890,
                "y": 140,
                "config": {},
            },
        ]
        self.state["entities"]["workflows"]["demo-workflow"] = {
            "id": "demo-workflow",
            "name": "示例：清洗、去重与质量检查",
            "nodes": nodes,
            "edges": [
                {"source": nodes[i]["id"], "target": nodes[i + 1]["id"]}
                for i in range(4)
            ],
            "createdAt": now(),
            "updatedAt": now(),
        }
