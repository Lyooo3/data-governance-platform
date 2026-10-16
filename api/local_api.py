from typing import Any
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from .storage import public_user
from .local_store import TABLES, public
from .local_engine import view_rows
from .engine import require
from .local_governance import EDITABLE


def install(app, user, admin):
    router = APIRouter(
        prefix="/api/local", tags=["本地治理扩展"], dependencies=[Depends(user)]
    )

    def module(request):
        return request.app.state.local

    def fail(code, text):
        raise HTTPException(code, text)

    def listed(local, kind, actor):
        if kind not in TABLES:
            fail(404, "配置类型不存在")
        records = local.repo.all(kind)
        if actor["role"] != "admin":
            if kind in ("channels", "deliveries", "inbox", "subscriptions", "events"):
                fail(403, "此功能需要管理员权限")
            if kind == "apps":
                records = [r for r in records if r["ownerId"] == actor["id"]]
            if kind == "grants":
                owned = {
                    a["id"]
                    for a in local.repo.all("apps")
                    if a["ownerId"] == actor["id"]
                }
                records = [r for r in records if r["appId"] in owned]
        return records

    @router.get("/bootstrap")
    def bootstrap(request: Request, actor=Depends(user)):
        local = module(request)
        store = local.store
        return {
            "success": True,
            "code": 200,
            "data": {
                "datasets": [
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "fields": list(d["rows"][0]) if d["rows"] else [],
                        "rowCount": len(d["rows"]),
                    }
                    for d in store.all("datasets")
                ],
                "elements": store.all("elements"),
                "dictionaries": store.all("dictionaries"),
                "workflows": [
                    {"id": w["id"], "name": w["name"]} for w in store.all("workflows")
                ],
                "services": [public(s) for s in store.all("services")],
                "views": local.repo.all("views"),
                "apps": [public(a) for a in listed(local, "apps", actor)],
                "channels": (
                    local.repo.all("channels") if actor["role"] == "admin" else []
                ),
                "users": (
                    [public_user(u) for u in store.users()]
                    if actor["role"] == "admin"
                    else []
                ),
                "targets": {
                    kind: [
                        {"id": r["id"], "name": r["name"]}
                        for r in (
                            local.repo.all("views")
                            if kind == "views"
                            else store.all(kind)
                        )
                    ]
                    for kind in (
                        "elements",
                        "dictionaries",
                        "qualifiers",
                        "businessTypes",
                        "assets",
                        "services",
                        "views",
                    )
                },
            },
        }

    @router.get("/records/{kind}")
    def records(kind: str, request: Request, actor=Depends(user)):
        values = listed(module(request), kind, actor)
        for field in ("operation", "status", "targetKind", "subscriptionId"):
            if request.query_params.get(field):
                values = [
                    v for v in values if v.get(field) == request.query_params[field]
                ]
        return {
            "success": True,
            "code": 200,
            "data": {
                "list": [
                    {
                        k: v
                        for k, v in public(r).items()
                        if k not in ("rows", "snapshot", "changes", "message")
                    }
                    for r in values
                ],
                "total": len(values),
            },
        }

    @router.get("/records/{kind}/{key}")
    def record(kind: str, key: str, request: Request, actor=Depends(user)):
        local = module(request)
        if not any(r["id"] == key for r in listed(local, kind, actor)):
            fail(404, "记录不存在")
        return {"success": True, "code": 200, "data": public(local.checked(kind, key))}

    @router.post("/records/{kind}")
    def create(
        kind: str,
        request: Request,
        body: dict[str, Any] = Body(...),
        actor=Depends(admin),
    ):
        return {
            "success": True,
            "code": 200,
            "data": module(request).save(kind, body, actor),
        }

    @router.put("/records/{kind}/{key}")
    def update(
        kind: str,
        key: str,
        request: Request,
        body: dict[str, Any] = Body(...),
        actor=Depends(admin),
    ):
        return {
            "success": True,
            "code": 200,
            "data": module(request).save(kind, body, actor, key),
        }

    @router.delete("/records/{kind}/{key}")
    def remove(kind: str, key: str, request: Request, actor=Depends(admin)):
        local = module(request)
        if kind not in EDITABLE | {"reports"}:
            fail(422, "历史业务记录不支持直接删除")
        local.checked(kind, key)
        local.repo.remove(kind, key)
        local.store.audit(actor["name"], kind + ".delete", key)
        return {"success": True, "code": 200, "data": None}

    @router.post("/analyze/{operation}")
    def analyze(
        operation: str,
        request: Request,
        body: dict[str, Any] = Body(...),
        actor=Depends(admin),
    ):
        return {
            "success": True,
            "code": 200,
            "data": module(request).engine.analyze(operation, body, actor["name"]),
        }

    @router.post("/approvals")
    def approval(
        request: Request, body: dict[str, Any] = Body(...), actor=Depends(user)
    ):
        return {
            "success": True,
            "code": 200,
            "data": module(request).request_approval(body, actor),
        }

    @router.post("/grants")
    def grant(request: Request, body: dict[str, Any] = Body(...), actor=Depends(user)):
        local = module(request)
        app_record = local.checked("apps", body.get("appId"))
        if actor["role"] != "admin" and app_record["ownerId"] != actor["id"]:
            fail(403, "只能为自己的应用申请授权")
        return {"success": True, "code": 200, "data": local.grant_request(body, actor)}

    @router.post("/action/{kind}/{key}/{action}")
    async def action(
        kind: str,
        key: str,
        action: str,
        request: Request,
        body: dict[str, Any] = Body(default={}),
        actor=Depends(user),
    ):
        local = module(request)
        value = None
        if kind == "approvals" and action in ("approve", "reject", "withdraw"):
            if action != "withdraw" and actor["role"] != "admin":
                fail(403, "审核需要管理员权限")
            value = local.decide_approval(key, action, body, actor)
        else:
            if actor["role"] != "admin":
                fail(403, "此操作需要管理员权限")
            if kind == "grants" and action in ("approve", "reject", "revoke"):
                value = local.grant_decide(key, action, body, actor)
            elif kind in (
                "schedules",
                "subscriptions",
                "apps",
                "channels",
            ) and action in ("enable", "disable"):
                value = local.toggle(kind, key, action == "enable", actor["name"])
            elif kind == "schedules" and action == "run":
                value = local.start_schedule(key, actor["name"])
            elif kind == "subscriptions" and action == "compare":
                value = local.compare(key, actor["name"])
            elif kind == "subscriptions" and action == "reset":
                record = local.checked(kind, key)
                rows = local.engine.dataset(record["datasetId"])["rows"]
                from .local_engine import comparison

                comparison(rows, rows, record["keys"])
                local.repo.save_snapshot(key, rows)
                local.store.audit(actor["name"], "subscription.reset", key)
                value = {"name": "基线已重新建立"}
            elif kind == "views" and action == "preview":
                record = local.checked(kind, key)
                rows = view_rows(local.store, record)
                value = {
                    "name": record["name"],
                    "rows": rows,
                    "metrics": {"rowCount": len(rows)},
                }
            elif kind == "adapters" and action == "replay":
                record = local.checked(kind, key)
                value = local.receive(
                    key,
                    local.engine.dataset(record["datasetId"])["rows"],
                    actor["name"],
                )
            elif kind == "events" and action == "enqueue":
                value = local.enqueue(key, body.get("channelId"), actor["name"])
            elif kind == "deliveries" and action == "deliver":
                value = local.deliver(key, actor["name"])
            else:
                fail(404, "此业务操作不存在")
        return {"success": True, "code": 200, "data": public(value)}

    @router.post("/adapters/{key}/receive")
    def receive(
        key: str,
        request: Request,
        body: dict[str, Any] = Body(...),
        actor=Depends(admin),
    ):
        return {
            "success": True,
            "code": 200,
            "data": module(request).receive(key, body.get("rows"), actor["name"]),
        }

    @router.get("/lineage")
    def lineage(request: Request):
        return {
            "success": True,
            "code": 200,
            "data": module(request).engine.lineage(
                request.query_params.get("workflowId")
            ),
        }

    @router.get("/chain")
    def chain(request: Request):
        store = module(request).store
        rows = []
        for run in store.runs():
            for report in run.get("reports", []):
                rows.append(
                    {
                        "id": run["id"] + ":" + report["nodeId"],
                        "name": run["name"],
                        "runId": run["id"],
                        "nodeName": report["nodeName"],
                        "total": report["total"],
                        "invalid": report["invalidRows"],
                        "passRate": report["passRate"],
                        "finishedAt": run.get("finishedAt"),
                    }
                )
        return {
            "success": True,
            "code": 200,
            "data": {"list": rows, "total": len(rows)},
        }

    @router.get("/contracts/{key}")
    def contract(key: str, request: Request):
        local = module(request)
        service = local.store.get("services", key)
        require(service is not None, "服务不存在")
        if service.get("viewId"):
            rows = view_rows(local.store, local.checked("views", service["viewId"]))
        elif service.get("runId"):
            run = local.store.run(service["runId"])
            require(run is not None and run["status"] == "SUCCESS", "运行结果不可用")
            rows = run["rows"]
        else:
            rows = local.engine.dataset(service.get("datasetId"))["rows"]
        fields = service.get("fields") or (list(rows[0]) if rows else [])
        definition = {
            "openapi": "3.1.0",
            "info": {"title": service["name"], "version": "1.0"},
            "paths": {
                f"/api/published/{key}/query": {
                    "get": {
                        "summary": service["name"],
                        "parameters": [
                            {
                                "name": "pageNum",
                                "in": "query",
                                "schema": {"type": "integer", "minimum": 1},
                            },
                            {
                                "name": "pageSize",
                                "in": "query",
                                "schema": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 500,
                                },
                            },
                        ],
                        "security": [{"ServiceKey": []}, {"AppKey": []}],
                        "responses": {
                            "200": {"description": "分页结果，字段受白名单限制"},
                            "403": {"description": "凭据无效或应用未获授权"},
                            "404": {"description": "服务未发布"},
                            "429": {"description": "每分钟超过60次查询"},
                        },
                    }
                }
            },
            "components": {
                "securitySchemes": {
                    "ServiceKey": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-API-Key",
                    },
                    "AppKey": {"type": "apiKey", "in": "header", "name": "X-App-Key"},
                }
            },
            "x-fields": fields,
            "x-rate-limit-per-minute": 60,
            "x-published": bool(service.get("published")),
        }
        return {"success": True, "code": 200, "data": definition}

    app.include_router(router)
