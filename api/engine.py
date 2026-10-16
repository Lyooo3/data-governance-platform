import copy
import json
import math
import re
from collections import Counter

NODE_TYPES = ("source", "select", "clean", "filter", "dedupe", "quality", "output")
RULE_TYPES = ("required", "unique", "regex", "range", "enum")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(workflow):
    nodes, edges = workflow.get("nodes", []), workflow.get("edges", [])
    require(isinstance(nodes, list) and 2 <= len(nodes) <= 50, "流程需要2至50个节点")
    require(isinstance(edges, list), "连线格式错误")
    require(
        all(
            isinstance(n, dict) and isinstance(n.get("config", {}), dict) for n in nodes
        ),
        "节点配置格式错误",
    )
    require(
        all(isinstance(n.get("id"), str) and 0 < len(n["id"]) <= 100 for n in nodes),
        "节点ID格式错误",
    )
    lookup = {n.get("id"): n for n in nodes}
    require(
        len(lookup) == len(nodes)
        and all(n.get("id") and n.get("type") in NODE_TYPES for n in nodes),
        "节点ID重复或类型不支持",
    )
    require(
        sum(n["type"] == "source" for n in nodes) == 1
        and sum(n["type"] == "output" for n in nodes) == 1,
        "需要一个读取节点和一个输出节点",
    )
    incoming, outgoing = {k: [] for k in lookup}, {k: [] for k in lookup}
    for edge in edges:
        require(isinstance(edge, dict), "连线格式错误")
        a, b = edge.get("source"), edge.get("target")
        require(a in lookup and b in lookup and a != b, "连线节点无效")
        incoming[b].append(a)
        outgoing[a].append(b)
    for n in nodes:
        require(
            len(incoming[n["id"]]) == (0 if n["type"] == "source" else 1),
            "请连接所有节点，暂不支持多表合并",
        )
        require(
            len(outgoing[n["id"]]) == (0 if n["type"] == "output" else 1),
            "请按线性顺序连接节点，暂不支持分支",
        )
    order, seen = [], set()
    current = next(n["id"] for n in nodes if n["type"] == "source")
    while current:
        require(current not in seen, "流程存在循环")
        seen.add(current)
        order.append(lookup[current])
        current = outgoing[current][0] if outgoing[current] else None
    require(len(order) == len(nodes), "存在未连接节点或循环")
    return order


def validate_rule(rule):
    require(
        rule.get("type") in RULE_TYPES
        and isinstance(rule.get("field"), str)
        and rule["field"].strip(),
        "请选择有效规则类型和检查字段",
    )
    if rule["type"] == "regex":
        require(
            isinstance(rule.get("pattern"), str) and 0 < len(rule["pattern"]) <= 200,
            "正则表达式需要1至200个字符",
        )
        try:
            re.compile(rule["pattern"])
        except re.error as error:
            raise ValueError("正则表达式格式错误") from error
    if rule["type"] == "enum":
        require(
            isinstance(rule.get("values"), list) and len(rule["values"]) > 0,
            "请填写允许值集合",
        )
    if rule["type"] == "range":
        require(
            rule.get("min") is not None or rule.get("max") is not None,
            "请填写范围上下限",
        )
        for key in ("min", "max"):
            if rule.get(key) is not None:
                require(math.isfinite(float(rule[key])), "范围必须是有限数字")
        require(
            rule.get("min") is None
            or rule.get("max") is None
            or float(rule["min"]) <= float(rule["max"]),
            "最小值不能大于最大值",
        )


def fields_exist(rows, fields):
    require(
        isinstance(fields, list)
        and fields
        and all(isinstance(f, str) and f for f in fields),
        "请配置有效字段",
    )
    if rows:
        require(all(f in rows[0] for f in fields), "配置字段不在输入数据中")


def empty(value):
    return value is None or str(value).strip() == ""


def quality(rows, rules):
    require(
        isinstance(rules, list) and 1 <= len(rules) <= 100, "质量节点需要1至100条规则"
    )
    details, invalid = [], set()
    for rule in rules:
        require(rule is not None, "质量规则不存在或已删除")
        validate_rule(rule)
        fields_exist(rows, [rule["field"]])
        freq = Counter(
            json.dumps(r[rule["field"]], sort_keys=True, ensure_ascii=False)
            for r in rows
        )
        failed = []
        for index, row in enumerate(rows):
            value = row[rule["field"]]
            passed = not empty(value)
            if rule["type"] == "unique":
                passed = (
                    passed
                    and freq[json.dumps(value, sort_keys=True, ensure_ascii=False)] == 1
                )
            elif rule["type"] == "regex":
                passed = passed and re.search(rule["pattern"], str(value)) is not None
            elif rule["type"] == "enum":
                passed = passed and str(value) in [str(v) for v in rule["values"]]
            elif rule["type"] == "range":
                try:
                    n = float(value)
                    passed = (
                        passed
                        and math.isfinite(n)
                        and (rule.get("min") is None or n >= float(rule["min"]))
                        and (rule.get("max") is None or n <= float(rule["max"]))
                    )
                except (ValueError, TypeError):
                    passed = False
            if not passed:
                failed.append(index)
                invalid.add(index)
        details.append(
            {
                "id": rule.get("id"),
                "name": rule["name"],
                "type": rule["type"],
                "field": rule["field"],
                "total": len(rows),
                "failed": len(failed),
                "passed": len(rows) - len(failed),
                "failedIndexes": failed[:100],
            }
        )
    return {
        "total": len(rows),
        "invalidRows": len(invalid),
        "validRows": len(rows) - len(invalid),
        "passRate": (
            round((len(rows) - len(invalid)) / len(rows) * 100, 2) if rows else None
        ),
        "rules": details,
    }, invalid


def execute(payload):
    order = validate(payload["workflow"])
    rows, steps, reports = [], [], []
    source_count = 0
    for node in order:
        config, kind, before = node.get("config", {}), node["type"], len(rows)
        if kind == "source":
            require(
                not config.get("sourceId") and not config.get("sql"),
                "外部数据库尚未配置，请选择内置或导入样例",
            )
            dataset = payload["datasets"].get(config.get("datasetId"))
            require(dataset is not None, "请选择有效样例数据集")
            rows = copy.deepcopy(dataset["rows"])
            require(len(rows) <= 10000, "当前执行最多10,000条记录")
            source_count = len(rows)
        elif kind == "select":
            mappings = config.get("mappings", [])
            require(
                mappings and all(m.get("from") and m.get("to") for m in mappings),
                "请填写字段映射",
            )
            require(
                len({m["to"] for m in mappings}) == len(mappings),
                "映射目标字段不能重复",
            )
            fields_exist(rows, [m["from"] for m in mappings])
            rows = [{m["to"]: r[m["from"]] for m in mappings} for r in rows]
        elif kind == "clean":
            fields_exist(rows, config.get("fields"))
            operation = config.get("operation", "trim")
            require(
                operation in ("trim", "upper", "lower", "number", "fill"),
                "清洗方式不支持",
            )
            for row in rows:
                for field in config["fields"]:
                    value = row[field]
                    if operation == "fill":
                        row[field] = config.get("value", "") if empty(value) else value
                    elif operation == "number":
                        try:
                            n = float(value) if not empty(value) else None
                            row[field] = (
                                n if n is not None and math.isfinite(n) else None
                            )
                        except (TypeError, ValueError):
                            row[field] = None
                    elif value is not None:
                        row[field] = {
                            "trim": str.strip,
                            "upper": str.upper,
                            "lower": str.lower,
                        }[operation](str(value))
        elif kind == "dedupe":
            fields_exist(rows, config.get("fields"))
            seen, result = set(), []
            for row in rows:
                key = json.dumps(
                    [row[f] for f in config["fields"]],
                    sort_keys=True,
                    ensure_ascii=False,
                )
                if key not in seen:
                    seen.add(key)
                    result.append(row)
            rows = result
        elif kind == "filter":
            fields_exist(rows, [config.get("field")])
            operator = config.get("operator", "eq")
            require(
                operator in ("eq", "ne", "contains", "notEmpty", "gt", "lt"),
                "过滤条件不支持",
            )

            def keep(row):
                a, b = row[config["field"]], config.get("value", "")
                if operator == "notEmpty":
                    return not empty(a)
                if operator == "contains":
                    return str(b) in str(a or "")
                if operator == "eq":
                    return str(a) == str(b)
                if operator == "ne":
                    return str(a) != str(b)
                try:
                    return (
                        float(a) > float(b) if operator == "gt" else float(a) < float(b)
                    )
                except (TypeError, ValueError):
                    return False

            rows = [r for r in rows if keep(r)]
        elif kind == "quality":
            rules = config.get("rules") or [
                payload["rules"].get(key) for key in config.get("ruleIds", [])
            ]
            report, invalid = quality(rows, rules)
            reports.append(
                {
                    **report,
                    "nodeId": node["id"],
                    "nodeName": node.get("label", "质量检查"),
                }
            )
            if config.get("dropInvalid"):
                rows = [r for i, r in enumerate(rows) if i not in invalid]
        elif kind == "output":
            require(
                not config.get("sourceId"), "外部数据库尚未配置，结果保存为本地文件数据"
            )
        steps.append(
            {
                "nodeId": node["id"],
                "name": node.get("label", kind),
                "type": kind,
                "inputCount": before,
                "outputCount": len(rows),
            }
        )
    return {
        "sourceCount": source_count,
        "outputCount": len(rows),
        "steps": steps,
        "reports": reports,
        "rows": rows,
    }
