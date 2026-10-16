"""Persistent local workflows for review, scheduling, grants and event delivery."""

import asyncio
import copy
import secrets
import time
from collections import Counter
from .engine import require, validate, fields_exist
from .storage import now, digest
from .local_store import LocalStore, public
from .local_engine import LocalEngine, view_rows, text_list, comparison, fingerprints

EDITABLE = {"schedules", "views", "apps", "adapters", "channels", "subscriptions"}
APPROVABLE = {
    "elements",
    "dictionaries",
    "qualifiers",
    "businessTypes",
    "assets",
    "services",
    "views",
}


class LocalGovernance:
    def __init__(self, store, jobs):
        self.store, self.jobs = store, jobs
        self.repo = LocalStore(store)
        self.engine = LocalEngine(store)
        self.worker = None

    def checked(self, kind, key):
        value = self.repo.get(kind, key)
        require(value is not None, "记录不存在或已删除")
        return value

    def target(self, kind, key):
        require(kind in APPROVABLE, "该类型不支持审核")
        value = (
            self.repo.get("views", key)
            if kind == "views"
            else self.store.get(kind, key)
        )
        require(value is not None, "审核对象不存在")
        return value

    def save(self, kind, body, actor, key=None):
        require(kind in EDITABLE, "该记录需通过业务操作创建")
        old = self.checked(kind, key) if key else {}
        value = {**old, **body}
        value.pop("apiKey", None)
        name = value.get("name")
        require(
            isinstance(name, str) and 0 < len(name.strip()) <= 120,
            "名称需要1至120个字符",
        )
        value["name"] = name.strip()
        require(isinstance(value.get("enabled", False), bool), "启用状态必须为布尔值")
        value["enabled"] = value.get("enabled", False)
        if old.get("approvalStatus") == "approved":
            value["approvalStatus"] = "draft"
            value.pop("approvedAt", None)
            value.pop("approvedBy", None)
        if kind in ("schedules", "subscriptions"):
            interval = float(value.get("intervalSeconds", 300))
            require(60 <= interval <= 31536000, "间隔需为60至31536000秒")
            value["intervalSeconds"] = interval
            value["nextRunAt"] = time.time() + interval
        if kind == "schedules":
            workflow = self.store.get("workflows", value.get("workflowId"))
            require(workflow is not None, "请选择有效治理流程")
            validate(workflow)
            value["maxRetries"] = int(value.get("maxRetries", 0))
            require(0 <= value["maxRetries"] <= 3, "重试次数应为0至3")
        if kind in ("views", "adapters", "subscriptions"):
            dataset = self.engine.dataset(value.get("datasetId"))
        if kind == "views":
            value["fields"] = text_list(value.get("fields", []))
            view_rows(self.store, value)
        if kind == "adapters":
            mappings = value.get("mappings", [])
            require(
                isinstance(mappings, list)
                and 0 < len(mappings) <= 100
                and all(
                    isinstance(m, dict)
                    and isinstance(m.get("from"), str)
                    and isinstance(m.get("to"), str)
                    for m in mappings
                ),
                "请配置字段映射对象数组，填写from和to",
            )
            transform_rows = self.map_adapter(value, dataset["rows"])
            value["fieldCount"] = (
                len(transform_rows[0]) if transform_rows else len(mappings)
            )
        if kind == "apps":
            owner = value.get("ownerId") or actor["id"]
            require(self.store.get_user(owner) is not None, "应用归属账号不存在")
            value["ownerId"] = owner
            value["apiKeyHash"] = old.get("apiKeyHash")
        if kind == "channels":
            value["recipient"] = str(value.get("recipient") or "本地工作空间")[:200]
        if kind == "subscriptions":
            value["keys"] = text_list(value.get("keys", []))
            fields_exist(dataset["rows"], value["keys"])
            comparison(dataset["rows"], dataset["rows"], value["keys"])
            if value.get("channelId"):
                self.checked("channels", value["channelId"])
        with self.store.transaction():
            saved = self.repo.save(kind, value, key)
            if kind == "subscriptions" and (
                not old
                or old.get("datasetId") != saved["datasetId"]
                or old.get("keys") != saved["keys"]
            ):
                self.repo.save_snapshot(saved["id"], dataset["rows"])
            secret = None
            if kind == "apps" and not key:
                secret = secrets.token_urlsafe(32)
                saved = self.repo.save(
                    kind, {"apiKeyHash": digest(secret)}, saved["id"]
                )
            self.store.audit(
                actor["name"], kind + (".update" if key else ".create"), saved["id"]
            )
        return {**public(saved), **({"apiKey": secret} if secret else {})}

    def map_adapter(self, adapter, rows):
        require(
            isinstance(rows, list)
            and len(rows) <= 10000
            and all(isinstance(r, dict) for r in rows),
            "接收数据需为不超过10000条的对象数组",
        )
        if rows:
            require(
                all(set(r) == set(rows[0]) for r in rows), "每条接收记录的字段必须一致"
            )
        require(
            all(
                isinstance(v, (str, int, float, bool, type(None)))
                for r in rows
                for v in r.values()
            ),
            "接收字段值仅支持基本类型",
        )
        from .local_engine import transform

        return transform(rows, "select", {"mappings": adapter["mappings"]})

    def receive(self, key, rows, actor):
        adapter = self.checked("adapters", key)
        mapped = self.map_adapter(adapter, rows)
        with self.store.transaction():
            dataset = self.store.save(
                "datasets",
                {
                    "name": adapter["name"] + "-接收结果",
                    "rows": mapped,
                    "description": "本地接口适配接收，未访问外部服务器",
                },
            )
            report = self.repo.save(
                "reports",
                {
                    "name": adapter["name"] + "-接收记录",
                    "operation": "adapter",
                    "datasetId": adapter["datasetId"],
                    "outputDatasetId": dataset["id"],
                    "metrics": {"received": len(rows), "saved": len(mapped)},
                    "rows": mapped,
                    "actor": actor,
                },
            )
            self.store.audit(actor, "adapter.receive", report["id"])
        return report

    def request_approval(self, body, actor):
        kind, key = body.get("targetKind"), body.get("targetId")
        with self.store.transaction():
            target = self.target(kind, key)
            require(
                not any(
                    a["targetKind"] == kind
                    and a["targetId"] == key
                    and a["status"] == "pending"
                    for a in self.repo.all("approvals")
                ),
                "该对象已有待审核申请",
            )
            record = self.repo.save(
                "approvals",
                {
                    "name": target["name"],
                    "targetKind": kind,
                    "targetId": key,
                    "status": "pending",
                    "submittedBy": actor["name"],
                    "submittedUserId": actor["id"],
                    "reason": str(body.get("reason", ""))[:2000],
                    "fingerprint": fingerprints(target),
                    "snapshot": public(target),
                },
            )
            self.store.audit(actor["name"], "approval.submit", record["id"])
            return record

    def decide_approval(self, key, action, body, actor):
        with self.store.transaction():
            record = self.checked("approvals", key)
            require(record["status"] == "pending", "该申请已处理")
            if action == "withdraw":
                require(
                    record["submittedUserId"] == actor["id"]
                    or actor["role"] == "admin",
                    "只能撤回自己的申请",
                )
            else:
                require(actor["role"] == "admin", "审核需要管理员权限")
            if action == "approve":
                target = self.target(record["targetKind"], record["targetId"])
                require(
                    fingerprints(target) == record["fingerprint"],
                    "对象已变更，请撤回后重新提交当前版本",
                )
                approved = {
                    **target,
                    "approvalStatus": "approved",
                    "approvedBy": actor["name"],
                    "approvedAt": now(),
                }
                if record["targetKind"] == "views":
                    self.repo.save("views", approved, target["id"])
                else:
                    self.store.save(record["targetKind"], approved, target["id"])
            status = {
                "approve": "approved",
                "reject": "rejected",
                "withdraw": "withdrawn",
            }[action]
            saved = self.repo.save(
                "approvals",
                {
                    **record,
                    "status": status,
                    "reviewedBy": actor["name"],
                    "reviewedAt": now(),
                    "reviewNote": str(body.get("note", ""))[:2000],
                },
                key,
            )
            self.store.audit(actor["name"], "approval." + action, key)
            return saved

    def grant_request(self, body, actor):
        app = self.checked("apps", body.get("appId"))
        service = self.store.get("services", body.get("serviceId"))
        require(
            actor["role"] == "admin" or app["ownerId"] == actor["id"],
            "只能为自己归属的应用申请服务",
        )
        require(service is not None and service.get("published"), "请选择已发布服务")
        with self.store.transaction():
            require(
                not any(
                    g["appId"] == app["id"]
                    and g["serviceId"] == service["id"]
                    and g["status"] in ("pending", "approved")
                    for g in self.repo.all("grants")
                ),
                "该应用已申请或已获授权",
            )
            record = self.repo.save(
                "grants",
                {
                    "name": app["name"] + " → " + service["name"],
                    "appId": app["id"],
                    "serviceId": service["id"],
                    "status": "pending",
                    "reason": str(body.get("reason", ""))[:2000],
                    "submittedBy": actor["name"],
                },
            )
            self.store.audit(actor["name"], "grant.request", record["id"])
            return record

    def grant_decide(self, key, action, body, actor):
        require(actor["role"] == "admin", "授权审核需要管理员权限")
        with self.store.transaction():
            record = self.checked("grants", key)
            require(
                (record["status"] == "pending" and action in ("approve", "reject"))
                or (record["status"] == "approved" and action == "revoke"),
                "当前授权状态不支持此操作",
            )
            saved = self.repo.save(
                "grants",
                {
                    **record,
                    "status": {
                        "approve": "approved",
                        "reject": "rejected",
                        "revoke": "revoked",
                    }[action],
                    "reviewedBy": actor["name"],
                    "reviewedAt": now(),
                    "note": str(body.get("note", ""))[:2000],
                },
                key,
            )
            self.store.audit(actor["name"], "grant." + action, key)
            return saved

    def authorized_app(self, service_id, secret):
        if not secret or len(secret) > 200:
            return None
        app = next(
            (
                a
                for a in self.repo.all("apps")
                if a["enabled"]
                and a.get("apiKeyHash")
                and secrets.compare_digest(a["apiKeyHash"], digest(secret))
            ),
            None,
        )
        if app and any(
            g["appId"] == app["id"]
            and g["serviceId"] == service_id
            and g["status"] == "approved"
            for g in self.repo.all("grants")
        ):
            return app
        return None

    def start_schedule(self, key, actor, current=None):
        record = self.checked("schedules", key)
        current = current or time.time()
        if record.get("lastRunId"):
            last = self.store.run(record["lastRunId"])
            require(
                last is None or last["status"] != "RUNNING",
                "上次任务仍在运行，请稍后重试",
            )
        workflow = self.store.get("workflows", record["workflowId"])
        require(workflow is not None, "计划关联流程不存在")
        run = self.jobs.start(workflow, actor)
        saved = self.repo.save(
            "schedules",
            {
                "lastRunId": run["id"],
                "lastError": "",
                "nextRunAt": current + record["intervalSeconds"],
            },
            key,
        )
        self.store.audit(actor, "schedule.run", key)
        return {**saved, "runId": run["id"]}

    def compare(self, key, actor):
        with self.store.transaction():
            subscription = self.checked("subscriptions", key)
            rows = self.engine.dataset(subscription["datasetId"])["rows"]
            previous = self.repo.snapshot(key)
            require(previous is not None, "订阅快照不存在，请重新建立基线")
            changes = comparison(previous, rows, subscription["keys"])
            counts = Counter(c["changeType"] for c in changes)
            for kind in ("insert", "update", "delete"):
                values = [c for c in changes if c["changeType"] == kind]
                if not values:
                    continue
                event = self.repo.save(
                    "events",
                    {
                        "name": subscription["name"]
                        + " / "
                        + {"insert": "新增", "update": "修改", "delete": "删除"}[kind],
                        "subscriptionId": key,
                        "changeType": kind,
                        "count": len(values),
                        "changes": values,
                    },
                )
                if subscription.get("channelId"):
                    self.enqueue(event["id"], subscription["channelId"], actor)
            self.repo.save_snapshot(key, rows)
            self.repo.save(
                "subscriptions",
                {
                    "lastComparedAt": now(),
                    "lastError": "",
                    "nextRunAt": time.time() + subscription["intervalSeconds"],
                    "lastChanges": len(changes),
                },
                key,
            )
            report = self.repo.save(
                "reports",
                {
                    "name": subscription["name"] + "-比对记录",
                    "operation": "compare",
                    "datasetId": subscription["datasetId"],
                    "metrics": {
                        "insert": counts["insert"],
                        "update": counts["update"],
                        "delete": counts["delete"],
                    },
                    "rows": changes,
                    "actor": actor,
                },
            )
            self.store.audit(actor, "subscription.compare", key)
            return report

    def enqueue(self, event_id, channel_id, actor):
        event = self.checked("events", event_id)
        self.checked("channels", channel_id)
        with self.store.transaction():
            existing = next(
                (
                    d
                    for d in self.repo.all("deliveries")
                    if d["eventId"] == event_id and d["channelId"] == channel_id
                ),
                None,
            )
            if existing:
                return existing
            saved = self.repo.save(
                "deliveries",
                {
                    "name": event["name"],
                    "eventId": event_id,
                    "channelId": channel_id,
                    "status": "pending",
                    "attempts": 0,
                },
            )
            self.store.audit(actor, "delivery.enqueue", saved["id"])
            return saved

    def deliver(self, key, actor):
        with self.store.transaction():
            delivery = self.checked("deliveries", key)
            if delivery["status"] == "delivered":
                return delivery
            channel = self.checked("channels", delivery["channelId"])
            if not channel["enabled"]:
                saved = self.repo.save(
                    "deliveries",
                    {
                        "status": "failed",
                        "error": "本地收件通道已停用",
                        "attempts": delivery.get("attempts", 0) + 1,
                    },
                    key,
                )
                self.store.audit(actor, "delivery.failed", key)
                return saved
            event = self.checked("events", delivery["eventId"])
            self.repo.save(
                "inbox",
                {
                    "name": delivery["name"],
                    "deliveryId": key,
                    "recipient": channel["recipient"],
                    "channelName": channel["name"],
                    "message": event,
                    "receivedAt": now(),
                },
            )
            saved = self.repo.save(
                "deliveries",
                {
                    "status": "delivered",
                    "error": "",
                    "deliveredAt": now(),
                    "attempts": delivery.get("attempts", 0) + 1,
                },
                key,
            )
            self.store.audit(actor, "delivery.delivered", key)
            return saved

    def toggle(self, kind, key, enabled, actor):
        record = self.checked(kind, key)
        saved = self.repo.save(
            kind,
            {
                "enabled": enabled,
                "nextRunAt": time.time() + record.get("intervalSeconds", 300),
            },
            key,
        )
        self.store.audit(actor, kind + (".enable" if enabled else ".disable"), key)
        return public(saved)

    def tick(self, current=None):
        current = current or time.time()
        for kind in ("schedules", "subscriptions"):
            for record in self.repo.all(kind):
                if kind == "schedules" and record.get("lastRunId"):
                    last = self.store.run(record["lastRunId"])
                    if (
                        last
                        and last["status"] != "RUNNING"
                        and record.get("checkedRunId") != last["id"]
                    ):
                        patch = {"checkedRunId": last["id"]}
                        if last["status"] in (
                            "FAILED",
                            "TIMED_OUT",
                            "INTERRUPTED",
                        ) and record.get("retryCount", 0) < record.get("maxRetries", 0):
                            patch.update(
                                nextRunAt=current + 60,
                                retryCount=record.get("retryCount", 0) + 1,
                                lastError=last.get("error", "执行失败"),
                            )
                        else:
                            patch.update(
                                retryCount=0,
                                lastError=(
                                    last.get("error", "")
                                    if last["status"] != "SUCCESS"
                                    else ""
                                ),
                            )
                        record = self.repo.save(kind, patch, record["id"])
                if not record["enabled"] or (record.get("nextRunAt") or 0) > current:
                    continue
                try:
                    if kind == "schedules":
                        self.start_schedule(record["id"], "scheduler", current)
                    else:
                        self.compare(record["id"], "scheduler")
                except Exception as error:
                    retries = int(record.get("retryCount", 0)) + 1
                    self.repo.save(
                        kind,
                        {
                            "lastError": str(error)[:500],
                            "retryCount": retries,
                            "nextRunAt": current + record["intervalSeconds"],
                        },
                        record["id"],
                    )
                    self.store.audit("scheduler", kind + ".failed", record["id"])
        for record in self.repo.all("deliveries"):
            if record["status"] == "pending":
                self.deliver(record["id"], "local-delivery")

    async def start(self):
        async def loop():
            while True:
                await asyncio.sleep(1)
                try:
                    self.tick()
                except Exception:
                    self.store.audit(
                        "scheduler",
                        "scheduler.error",
                        "本地调度循环失败，将在下一周期重试",
                    )

        self.worker = asyncio.create_task(loop())

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
