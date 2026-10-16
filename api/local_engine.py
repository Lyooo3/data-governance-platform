"""Local, bounded data analysis and declarative views. No network or user SQL."""

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from .engine import execute, require, fields_exist
from .storage import encoded, now
from .local_store import LocalStore


def text_list(value):
    if isinstance(value, str):
        value = [v.strip() for v in value.replace("，", ",").split(",") if v.strip()]
    require(
        isinstance(value, list)
        and all(isinstance(v, str) and v.strip() for v in value),
        "字段列表必须为非空字符串数组",
    )
    return value


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.astimezone(timezone.utc)


def transform(rows, kind, cfg):
    return execute(
        {
            "datasets": {"input": {"rows": rows}},
            "rules": {},
            "workflow": {
                "nodes": [
                    {"id": "a", "type": "source", "config": {"datasetId": "input"}},
                    {"id": "b", "type": kind, "config": cfg},
                    {"id": "c", "type": "output", "config": {}},
                ],
                "edges": [
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "c"},
                ],
            },
        }
    )["rows"]


def view_rows(store, view):
    source = store.get("datasets", view.get("datasetId"))
    require(source is not None, "视图关联的数据集不存在")
    rows = copy.deepcopy(source["rows"])
    fields = text_list(view.get("fields", []))
    if fields:
        fields_exist(rows, fields)
    filters = view.get("filters", [])
    require(
        isinstance(filters, list)
        and len(filters) <= 20
        and all(isinstance(f, dict) for f in filters),
        "最多配置20个过滤条件对象",
    )
    for condition in filters:
        rows = transform(rows, "filter", condition)
    return [{f: r[f] for f in fields} for r in rows] if fields else rows


def fingerprints(record):
    body = {
        k: v
        for k, v in record.items()
        if k not in ("approvalStatus", "approvedAt", "approvedBy")
    }
    return hashlib.sha256(encoded(body).encode()).hexdigest()


def comparison(before, after, keys):
    def index(rows):
        result = {}
        for row in rows:
            require(
                all(
                    k in row and row[k] is not None and str(row[k]).strip()
                    for k in keys
                ),
                "订阅业务键不能为空",
            )
            key = encoded([row[k] for k in keys])
            require(key not in result, "订阅业务键存在重复，请先去重或选择复合键")
            result[key] = row
        return result

    old, new = index(before), index(after)
    return (
        [
            {"key": k, "changeType": "insert", "before": None, "after": new[k]}
            for k in sorted(new.keys() - old.keys())
        ]
        + [
            {"key": k, "changeType": "delete", "before": old[k], "after": None}
            for k in sorted(old.keys() - new.keys())
        ]
        + [
            {"key": k, "changeType": "update", "before": old[k], "after": new[k]}
            for k in sorted(old.keys() & new.keys())
            if old[k] != new[k]
        ]
    )


class LocalEngine:
    def __init__(self, store):
        self.store = store
        self.repo = LocalStore(store)

    def dataset(self, key):
        dataset = self.store.get("datasets", key)
        require(dataset is not None, "请选择有效本地数据集")
        require(len(dataset["rows"]) <= 10000, "本地处理最多10000行")
        return dataset

    def analyze(self, operation, body, actor):
        require(
            operation
            in ("standard", "code", "timeliness", "relations", "funds", "operate"),
            "分析类型不支持",
        )
        dataset = self.dataset(body.get("datasetId"))
        rows = dataset["rows"]
        result = []
        metrics = {}
        output = None
        if operation == "standard":
            definitions = self.store.all("elements")
            if body.get("elementIds"):
                definitions = [e for e in definitions if e["id"] in body["elementIds"]]
            require(definitions, "请先定义数据元标准")
            mapping = body.get("mapping", {})
            require(
                isinstance(mapping, dict)
                and all(isinstance(v, str) for v in mapping.values()),
                "字段映射需为对象",
            )
            for element in definitions:
                field = mapping.get(element.get("field"), element.get("field"))
                kind = str(element.get("dataType") or "string").lower()
                missing = not field or (bool(rows) and field not in rows[0])

                def matches(value):
                    if value is None:
                        return True
                    if kind in ("string", "text", "varchar", "字符", "字符串"):
                        return isinstance(value, str)
                    if kind in ("int", "integer", "整数"):
                        return isinstance(value, int) and not isinstance(value, bool)
                    if kind in ("number", "float", "decimal", "numeric", "数值"):
                        return (
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(value)
                        )
                    if kind in ("boolean", "bool", "布尔"):
                        return isinstance(value, bool)
                    if kind in ("date", "datetime", "日期", "时间"):
                        try:
                            timestamp(value)
                            return True
                        except (ValueError, TypeError):
                            return False
                    return False

                invalid = (
                    list(range(len(rows)))
                    if missing
                    else [i for i, row in enumerate(rows) if not matches(row[field])]
                )
                result.append(
                    {
                        "standard": element["name"],
                        "field": field or "未配置",
                        "expectedType": kind,
                        "total": len(rows),
                        "invalid": len(invalid),
                        "status": (
                            "缺少字段"
                            if missing
                            else "符合标准" if not invalid else "类型不匹配"
                        ),
                        "indexes": invalid[:100],
                    }
                )
            metrics = {
                "standards": len(result),
                "passed": sum(r["status"] == "符合标准" for r in result),
                "failed": sum(r["status"] != "符合标准" for r in result),
            }
        elif operation == "code":
            field = body.get("field")
            fields_exist(rows, [field])
            dictionary = self.store.get("dictionaries", body.get("dictionaryId"))
            require(dictionary is not None, "请选择有效代码集")
            codes = {
                str(item["code"]): item["name"]
                for item in dictionary.get("dictionaryDetails", [])
            }
            result = [
                {
                    "index": i + 1,
                    "code": row[field],
                    "label": codes.get(str(row[field])),
                    "status": "已匹配" if str(row[field]) in codes else "未匹配",
                }
                for i, row in enumerate(rows)
            ]
            metrics = {
                "total": len(rows),
                "matched": sum(r["status"] == "已匹配" for r in result),
                "unmatched": sum(r["status"] == "未匹配" for r in result),
            }
            if body.get("apply"):
                target = body.get("outputField") or field + "_name"
                require(
                    isinstance(target, str) and target.strip() and len(target) <= 100,
                    "输出字段无效",
                )
                output = [{**r, target: codes.get(str(r[field]))} for r in rows]
        elif operation == "timeliness":
            field = body.get("field")
            fields_exist(rows, [field])
            hours = float(body.get("maxAgeHours", 24))
            require(math.isfinite(hours) and hours > 0, "时效阈值必须为正数")
            reference = timestamp(body.get("referenceTime") or now())
            for i, row in enumerate(rows):
                age = None
                try:
                    age = (reference - timestamp(row[field])).total_seconds() / 3600
                    status = (
                        "未来时间"
                        if age < -1 / 12
                        else "超期" if age > hours else "及时"
                    )
                except (ValueError, TypeError):
                    status = "时间无效"
                result.append(
                    {
                        "index": i + 1,
                        "timestamp": row[field],
                        "ageHours": round(age, 2) if age is not None else None,
                        "status": status,
                    }
                )
            counts = Counter(r["status"] for r in result)
            metrics = {
                "total": len(rows),
                "timely": counts["及时"],
                "stale": counts["超期"],
                "invalid": counts["时间无效"],
                "future": counts["未来时间"],
            }
        elif operation in ("relations", "funds"):
            source, target = body.get("fromField"), body.get("toField")
            fields_exist(rows, [source, target])
            amount_field = body.get("amountField") if operation == "funds" else None
            if amount_field:
                fields_exist(rows, [amount_field])
            require(operation != "funds" or amount_field, "请选择金额字段")
            edges = Counter()
            totals = defaultdict(
                lambda: {"in": Decimal(0), "out": Decimal(0), "count": 0}
            )
            invalid = 0
            for row in rows:
                if (
                    row[source] is None
                    or row[target] is None
                    or not str(row[source]).strip()
                    or not str(row[target]).strip()
                ):
                    invalid += 1
                    continue
                a, b = str(row[source]), str(row[target])
                amount = Decimal(0)
                if amount_field:
                    try:
                        amount = Decimal(str(row[amount_field]))
                        require(
                            amount.is_finite() and abs(amount) < Decimal("1e15"),
                            "金额无效",
                        )
                    except (InvalidOperation, ValueError):
                        invalid += 1
                        continue
                edges[(a, b)] += 1
                totals[a]["out"] += amount
                totals[b]["in"] += amount
                totals[a]["count"] += 1
                totals[b]["count"] += 1
            require(len(totals) <= 10000, "关联对象过多")
            graph_edges = [
                {"source": a, "target": b, "count": n} for (a, b), n in edges.items()
            ]
            if operation == "relations":
                result = graph_edges
                metrics = {
                    "nodes": len(totals),
                    "edges": len(edges),
                    "records": sum(edges.values()),
                    "invalid": invalid,
                }
            else:
                result = [
                    {
                        "entity": name,
                        "incoming": float(v["in"]),
                        "outgoing": float(v["out"]),
                        "net": float(v["in"] - v["out"]),
                        "count": v["count"],
                    }
                    for name, v in sorted(totals.items())
                ]
                metrics = {
                    "entities": len(totals),
                    "transactions": sum(edges.values()),
                    "totalAmount": float(sum(v["out"] for v in totals.values())),
                    "invalid": invalid,
                }
        else:
            action = body.get("action", "clean")
            require(
                action in ("clean", "filter", "dedupe", "select"),
                "请选择支持的数据操作",
            )
            cfg = body.get("config", {})
            require(isinstance(cfg, dict), "操作参数需为JSON对象")
            output = transform(rows, action, cfg)
            result = output
            metrics = {"input": len(rows), "output": len(output), "operation": action}
        with self.store.transaction():
            output_dataset = None
            if output is not None:
                output_dataset = self.store.save(
                    "datasets",
                    {
                        "name": str(body.get("name") or dataset["name"] + "-治理结果")[
                            :120
                        ],
                        "rows": output,
                        "description": "本地治理生成，原数据未修改",
                        "sourceDatasetId": dataset["id"],
                    },
                )
            report = self.repo.save(
                "reports",
                {
                    "name": str(body.get("name") or dataset["name"] + "-分析报告")[
                        :120
                    ],
                    "operation": operation,
                    "datasetId": dataset["id"],
                    "config": body,
                    "metrics": metrics,
                    "rows": result,
                    "outputDatasetId": output_dataset["id"] if output_dataset else None,
                    "actor": actor,
                },
            )
            self.store.audit(actor, "local." + operation, report["id"])
            return report

    def lineage(self, workflow_id=None):
        workflows = (
            [self.store.get("workflows", workflow_id)]
            if workflow_id
            else self.store.all("workflows")
        )
        nodes = {}
        edges = []
        field_mappings = []

        def add(key, label, kind, path=""):
            nodes[key] = {"id": key, "label": label, "kind": kind, "path": path}

        if not workflow_id:
            for dataset in self.store.all("datasets"):
                add(
                    dataset["id"],
                    dataset["name"],
                    "dataset",
                    "/access/preview?dataset=" + dataset["id"],
                )
                if dataset.get("sourceDatasetId"):
                    edges.append(
                        {"source": dataset["sourceDatasetId"], "target": dataset["id"]}
                    )
        for flow in filter(None, workflows):
            for node in flow["nodes"]:
                key = flow["id"] + ":" + node["id"]
                add(
                    key,
                    flow["name"] + " / " + node.get("label", node["type"]),
                    node["type"],
                    "/develop/flows",
                )
                if node["type"] == "source":
                    dataset = self.store.get(
                        "datasets", node.get("config", {}).get("datasetId")
                    )
                    if dataset:
                        add(
                            dataset["id"],
                            dataset["name"],
                            "dataset",
                            "/access/preview?dataset=" + dataset["id"],
                        )
                        edges.append({"source": dataset["id"], "target": key})
                if node["type"] == "select":
                    field_mappings += [
                        {"workflow": flow["name"], "from": m["from"], "to": m["to"]}
                        for m in node.get("config", {}).get("mappings", [])
                    ]
            edges += [
                {
                    "source": flow["id"] + ":" + e["source"],
                    "target": flow["id"] + ":" + e["target"],
                }
                for e in flow["edges"]
            ]
            for run in self.store.runs():
                if run.get("workflowId") == flow["id"] and run["status"] == "SUCCESS":
                    add(
                        run["id"],
                        run["name"] + " / 运行结果",
                        "run",
                        "/develop/runs?run=" + run["id"],
                    )
                    output = next(n for n in flow["nodes"] if n["type"] == "output")
                    edges.append(
                        {"source": flow["id"] + ":" + output["id"], "target": run["id"]}
                    )
        with self.store.lock:
            origins = list(
                self.store.db.execute(
                    "SELECT dataset_id,snapshot_id,table_id,payload_json FROM raw_dataset_links"
                )
            )
        for origin in origins:
            if origin["dataset_id"] in nodes:
                detail = json.loads(origin["payload_json"])
                raw_key = "raw:" + origin["table_id"]
                snap_key = "snapshot:" + origin["snapshot_id"]
                add(
                    snap_key,
                    "本地原始库",
                    "snapshot",
                    "/access/raw?snapshot=" + origin["snapshot_id"],
                )
                add(
                    raw_key,
                    detail["schema"] + "." + detail["table"],
                    "raw-table",
                    "/access/raw?snapshot=" + origin["snapshot_id"],
                )
                edges.extend(
                    [
                        {"source": snap_key, "target": raw_key},
                        {"source": raw_key, "target": origin["dataset_id"]},
                    ]
                )
        for view in self.repo.all("views"):
            if view["datasetId"] in nodes:
                add(view["id"], view["name"], "view", "/service/views")
                edges.append({"source": view["datasetId"], "target": view["id"]})
                field_mappings += [
                    {"workflow": view["name"], "from": f, "to": f}
                    for f in view.get("fields", [])
                ]
        for service in self.store.all("services"):
            source = (
                service.get("viewId")
                or service.get("runId")
                or service.get("datasetId")
            )
            if source in nodes:
                add(service["id"], service["name"], "service", "/service/manage")
                edges.append({"source": source, "target": service["id"]})
        return {
            "nodes": list(nodes.values()),
            "edges": [
                dict(source=a, target=b)
                for a, b in dict.fromkeys(
                    (e["source"], e["target"])
                    for e in edges
                    if e["source"] in nodes and e["target"] in nodes
                )
            ],
            "mappings": field_mappings,
        }
