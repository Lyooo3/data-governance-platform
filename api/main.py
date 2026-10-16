import sqlite3
import asyncio
import copy
import csv
import io
import json
import os
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from . import config
from .engine import validate, validate_rule
from .jobs import Jobs
from .storage import (
    KINDS,
    Store,
    digest,
    now,
    password_hash,
    public_user,
    verify_password,
)


def ok(data=None, message="成功"):
    return {"code": 200, "success": True, "message": message, "data": data}


def fail(status, message):
    raise HTTPException(status, message)


def page(values, request):
    query = request.query_params
    number = max(1, int(query.get("pageNum", query.get("pageNumber", "1"))))
    size = min(500, max(1, int(query.get("pageSize", "20"))))
    search = query.get("search", query.get("searchContent", "")).strip().lower()
    if search:
        values = [
            v for v in values if search in json.dumps(v, ensure_ascii=False).lower()
        ]
    for field in ("status", "type", "catalogId"):
        if query.get(field):
            values = [v for v in values if str(v.get(field, "")) == query[field]]
    selected = values[(number - 1) * size : number * size]
    return {"list": selected, "total": len(values), "pageNum": number, "pageSize": size}


def visible(kind, record):
    if record is None:
        fail(404, "记录不存在")
    record = copy.deepcopy(record)
    if kind == "services":
        record.pop("apiKeyHash", None)
    if kind == "datasets":
        record["rowCount"] = len(record.pop("rows", []))
    return record


class Login(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(max_length=200)


class NewUser(Login):
    password: str = Field(min_length=10, max_length=200)
    role: str = "reader"


def create_app(data_dir: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(Path(data_dir or config.DATA_DIR))
        app.state.jobs = Jobs(app.state.store)
        from .local_governance import LocalGovernance

        app.state.local = LocalGovernance(app.state.store, app.state.jobs)
        from .raw_store import RawManager

        app.state.raw = RawManager(app.state.store)
        await app.state.local.start()
        app.state.login_attempts = defaultdict(list)
        app.state.usage = defaultdict(list)
        yield
        await app.state.raw.close()
        await app.state.local.close()
        await app.state.jobs.close()
        app.state.store.close()

    app = FastAPI(
        title="数据治理平台 API",
        version="3.4.0",
        description="Vue 3门户。SQLite平台存储与本地原始库，支持常见关系数据库、MongoDB及ClickHouse只读采集。",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-App-Key"],
    )

    @app.middleware("http")
    async def boundary(request, call_next):
        origin = request.headers.get("origin")
        own_origin = str(request.base_url).rstrip("/")
        if origin and origin not in {
            own_origin,
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }:
            return JSONResponse(
                {"code": 403, "success": False, "message": "不允许跨站请求"},
                status_code=403,
            )
        if int(request.headers.get("content-length", "0")) > 2_000_000:
            return JSONResponse(
                {"code": 413, "success": False, "message": "请求正文过大"},
                status_code=413,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def constraint_error(_, error):
        return JSONResponse(
            {
                "code": 409,
                "success": False,
                "message": "记录被引用或违反唯一性约束，请检查关联配置",
            },
            status_code=409,
        )

    @app.exception_handler(HTTPException)
    async def http_error(_, error):
        return JSONResponse(
            {"code": error.status_code, "success": False, "message": str(error.detail)},
            status_code=error.status_code,
        )

    @app.exception_handler(ValueError)
    async def value_error(_, error):
        return JSONResponse(
            {"code": 422, "success": False, "message": str(error)}, status_code=422
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, error):
        details = [
            {"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
            for e in error.errors()
        ]
        return JSONResponse(
            {
                "code": 422,
                "success": False,
                "message": "请求参数格式不正确",
                "details": details,
            },
            status_code=422,
        )

    def user(request: Request):
        token = request.cookies.get("gov_v3_session") or request.headers.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        session = request.app.state.store.session(token) if token else None
        if not session or session["expires"] < time.time():
            fail(401, "请登录后操作")
        account = request.app.state.store.get_user(session["userId"])
        if not account:
            fail(401, "账号不存在")
        return public_user(account)

    def admin(account=Depends(user)):
        if account["role"] != "admin":
            fail(403, "此操作需要管理员权限")
        return account

    def issue(request, response, account):
        token = secrets.token_urlsafe(32)
        request.app.state.store.create_session(account["id"], token)
        response.set_cookie(
            "gov_v3_session", token, httponly=True, samesite="strict", max_age=28800
        )
        return ok(public_user(account))

    auth = APIRouter(prefix="/api/auth", tags=["身份与账号"])

    @auth.post("/local-session")
    def local_session(request: Request, response: Response):
        if not config.LOCAL_AUTO_LOGIN:
            fail(403, "本机自动登录已关闭")
        if request.headers.get("origin") != str(request.base_url).rstrip(
            "/"
        ) and request.headers.get("origin") not in (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ):
            fail(403, "本机会话需要同源请求")
        account = next(
            u for u in request.app.state.store.users() if u["role"] == "admin"
        )
        return issue(request, response, account)

    @auth.post("/login")
    def login(body: Login, request: Request, response: Response):
        key = request.client.host if request.client else "local"
        attempts = request.app.state.login_attempts[key]
        attempts[:] = [t for t in attempts if t > time.time() - 60]
        if len(attempts) >= 10:
            fail(429, "登录尝试过多，请一分钟后重试")
        attempts.append(time.time())
        account = next(
            (
                u
                for u in request.app.state.store.users()
                if u["name"] == body.name.strip()
            ),
            None,
        )
        if not account or not verify_password(body.password, account["passwordHash"]):
            fail(401, "账号或密码错误")
        attempts.clear()
        return issue(request, response, account)

    @auth.get("/me")
    def me(account=Depends(user)):
        return ok(account)

    @auth.post("/logout")
    def logout(request: Request, response: Response, account=Depends(user)):
        token = request.cookies.get("gov_v3_session") or request.headers.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        request.app.state.store.revoke_session(token)
        response.delete_cookie("gov_v3_session")
        return ok()

    @auth.get("/users")
    def users(request: Request, account=Depends(admin)):
        return ok([public_user(u) for u in request.app.state.store.users()])

    @auth.post("/users")
    def add_user(body: NewUser, request: Request, account=Depends(admin)):
        store = request.app.state.store
        name = body.name.strip()
        if not name:
            fail(422, "账号名称不能为空或仅包含空格")
        if body.role not in ("reader", "admin"):
            fail(422, "角色必须是admin或reader")
        if any(u["name"] == name for u in store.users()):
            fail(409, "账号已存在")
        value = store.create_user(name, body.password, body.role, account["name"])
        return ok(public_user(value))

    app.include_router(auth)
    gov = APIRouter(
        prefix="/api/governance", tags=["治理业务"], dependencies=[Depends(user)]
    )

    @app.get("/api/health", tags=["运行状态"])
    def health(request: Request):
        from .connector_common import catalog

        drivers = catalog()
        return ok(
            {
                "backend": "fastapi",
                "frontend": "vue3",
                "version": "3.4.0",
                "mode": "local",
                "storage": "sqlite",
                "databaseConfigured": any(
                    s.get("connectionStatus") == "tested"
                    for s in request.app.state.store.all("sources")
                ),
                "platformDatabase": {
                    "configured": True,
                    "engine": "sqlite",
                    "file": "platform.sqlite3",
                    "schemaVersion": 3,
                },
                "externalConnectors": [
                    c["type"] + "-readonly" for c in drivers if c["available"]
                ],
                "connectorCatalog": drivers,
                "rawSnapshots": len(request.app.state.raw.list()),
                "capabilities": [
                    "sample-data",
                    "workflow",
                    "quality",
                    "catalog",
                    "service",
                    "audit",
                    "raw-snapshots",
                ],
            }
        )

    @gov.get("/summary")
    def summary(request: Request):
        store = request.app.state.store
        runs = store.runs()
        local_day = datetime.now(timezone(timedelta(hours=8))).date()
        today = [
            r
            for r in runs
            if datetime.fromisoformat(r["startedAt"])
            .astimezone(timezone(timedelta(hours=8)))
            .date()
            == local_day
        ]
        successful = [r for r in runs if r["status"] == "SUCCESS"]
        latest = successful[0] if successful else None
        return ok(
            {
                "counts": {k: len(store.all(k)) for k in KINDS},
                "runs": {
                    "total": len(runs),
                    "success": sum(r["status"] == "SUCCESS" for r in runs),
                    "running": sum(r["status"] == "RUNNING" for r in runs),
                    "failed": sum(
                        r["status"] in ("FAILED", "TIMED_OUT", "INTERRUPTED")
                        for r in runs
                    ),
                },
                "today": {
                    "total": len(today),
                    "success": sum(r["status"] == "SUCCESS" for r in today),
                    "running": sum(r["status"] == "RUNNING" for r in today),
                    "failed": sum(
                        r["status"] in ("FAILED", "TIMED_OUT", "INTERRUPTED")
                        for r in today
                    ),
                },
                "latestRun": (
                    {k: v for k, v in latest.items() if k != "rows"} if latest else None
                ),
                "openAlerts": sum(a["status"] == "open" for a in store.alerts()),
                "databaseConfigured": any(
                    s.get("connectionStatus") == "tested" for s in store.all("sources")
                ),
            }
        )

    @gov.get("/audit")
    def audit(request: Request, account=Depends(admin)):
        return ok(page(request.app.state.store.audits(), request))

    @gov.post("/shutdown")
    async def shutdown(request: Request, account=Depends(admin)):
        callback = getattr(request.app.state, "request_shutdown", None)
        if callback is None:
            fail(409, "开发服务请在启动终端按Ctrl+C停止")

        async def later():
            await asyncio.sleep(0.2)
            callback()

        asyncio.create_task(later())
        return ok(None, "服务正在停止")

    @gov.get("/runs")
    def runs(request: Request):
        return ok(
            page(
                [
                    {k: v for k, v in r.items() if k != "rows"}
                    for r in request.app.state.store.runs()
                ],
                request,
            )
        )

    @gov.get("/runs/{run_id}")
    def run_detail(run_id: str, request: Request):
        run = request.app.state.store.run(run_id)
        if not run:
            fail(404, "运行记录不存在")
        run.pop("rows", None)
        return ok(run)

    @gov.get("/runs/{run_id}/rows")
    def run_rows(run_id: str, request: Request):
        run = request.app.state.store.run(run_id)
        if not run:
            fail(404, "运行记录不存在")
        return ok(page(run.get("rows", []), request))

    @gov.get("/runs/{run_id}/export")
    def export(run_id: str, request: Request):
        run = request.app.state.store.run(run_id)
        if not run:
            fail(404, "运行记录不存在")
        rows = run.get("rows", [])
        output = io.StringIO()
        fields = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: (
                        "'" + v
                        if isinstance(v, str)
                        and v.lstrip().startswith(("=", "+", "-", "@"))
                        else v
                    )
                    for k, v in row.items()
                }
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="run-{run_id}.csv"'},
        )

    @gov.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request, account=Depends(admin)):
        run = request.app.state.store.run(run_id)
        if not run:
            fail(404, "运行记录不存在")
        if run["status"] != "RUNNING":
            fail(409, "任务已结束")
        request.app.state.jobs.cancel(run_id)
        run.update(status="CANCELLED", error="执行已取消", finishedAt=now())
        request.app.state.store.save_run(run)
        request.app.state.store.audit(account["name"], "run.cancel", run_id)
        return ok(run)

    @gov.post("/workflows/{key}/run")
    async def execute_flow(key: str, request: Request, account=Depends(admin)):
        workflow = request.app.state.store.get("workflows", key)
        if not workflow:
            fail(404, "流程不存在")
        return ok(request.app.state.jobs.start(workflow, account["name"]))

    @gov.post("/qualityTasks/{key}/run")
    async def execute_quality(key: str, request: Request, account=Depends(admin)):
        task = request.app.state.store.get("qualityTasks", key)
        if not task:
            fail(404, "质量任务不存在")
        nodes = [
            {
                "id": "a",
                "type": "source",
                "config": {"datasetId": task.get("datasetId")},
            },
            {
                "id": "b",
                "type": "quality",
                "config": {"ruleIds": task.get("ruleIds", [])},
            },
            {"id": "c", "type": "output", "config": {}},
        ]
        return ok(
            request.app.state.jobs.start(
                {
                    "name": task["name"],
                    "nodes": nodes,
                    "edges": [
                        {"source": "a", "target": "b"},
                        {"source": "b", "target": "c"},
                    ],
                },
                account["name"],
                key,
            )
        )

    @gov.get("/alerts")
    def alerts(request: Request):
        return ok(
            page(
                sorted(
                    copy.deepcopy(list(request.app.state.store.alerts())),
                    key=lambda r: r["createdAt"],
                    reverse=True,
                ),
                request,
            )
        )

    @gov.get("/alerts/{key}")
    def alert_detail(key: str, request: Request):
        alert = request.app.state.store.alert(key)
        if not alert:
            fail(404, "预警不存在")
        return ok(copy.deepcopy(alert))

    @gov.post("/alerts/{key}/resolve")
    def resolve_alert(
        key: str,
        request: Request,
        body: Annotated[dict, Body()],
        account=Depends(admin),
    ):
        store = request.app.state.store
        with store.transaction():
            alert = store.alert(key)
            if not alert:
                fail(404, "预警不存在")
            alert.update(
                status="resolved",
                resolvedAt=now(),
                resolvedBy=account["name"],
                note=str(body.get("note", ""))[:500],
            )
            store.save_alert(alert)
            store.audit(account["name"], "alert.resolve", key)
        return ok(copy.deepcopy(alert))

    @gov.get("/datasets/{key}/rows")
    def dataset_rows(key: str, request: Request):
        record = request.app.state.store.get("datasets", key)
        if not record:
            fail(404, "数据集不存在")
        return ok(page(record["rows"], request))

    @gov.get("/sources/{key}/{action}")
    @gov.post("/sources/{key}/{action}")
    def source_action(key: str, action: str):
        fail(501, "此旧接口已停用；请使用/api/ingestion中的认证只读采集接口")

    @gov.post("/services/{key}/publish")
    def publish(key: str, request: Request, account=Depends(admin)):
        store = request.app.state.store
        service = store.get("services", key)
        if not service:
            fail(404, "服务不存在")
        rows = service_rows(store, service)
        if (
            service.get("fields")
            and rows
            and any(f not in rows[0] for f in service["fields"])
        ):
            fail(422, "发布字段不在数据中")
        secret = secrets.token_urlsafe(32)
        saved = store.save(
            "services",
            {**service, "published": True, "apiKeyHash": digest(secret)},
            key,
        )
        store.audit(account["name"], "service.publish", key)
        return ok(
            {
                "id": saved["id"],
                "endpoint": f"/api/published/{key}/query",
                "apiKey": secret,
            }
        )

    def service_rows(store, service):
        if service.get("viewId"):
            from .local_store import LocalStore
            from .local_engine import view_rows

            view = LocalStore(store).get("views", service["viewId"])
            if not view:
                fail(422, "关联视图不存在")
            return view_rows(store, view)
        if service.get("runId"):
            run = store.run(service["runId"])
            if not run or run["status"] != "SUCCESS":
                fail(422, "请关联成功的运行结果")
            return run["rows"]
        dataset = store.get("datasets", service.get("datasetId"))
        if not dataset:
            fail(422, "请关联有效样例数据集")
        return dataset["rows"]

    @app.get("/api/published/{key}/query", tags=["已发布数据查询"])
    def query_service(key: str, request: Request):
        store = request.app.state.store
        service = store.get("services", key)
        if not service or not service.get("published"):
            fail(404, "服务未发布")
        secret = request.headers.get("x-api-key", "")
        app_client = request.app.state.local.authorized_app(
            key, request.headers.get("x-app-key", "")
        )
        if not app_client and not secrets.compare_digest(
            digest(secret), service["apiKeyHash"]
        ):
            fail(
                403,
                (
                    "应用凭据无效、应用已停用或尚未获授权"
                    if request.headers.get("x-app-key")
                    else "服务密钥无效"
                ),
            )
        usage = request.app.state.usage[key]
        usage[:] = [t for t in usage if t > time.time() - 60]
        if len(usage) >= 60:
            fail(429, "每分钟最多60次查询")
        usage.append(time.time())
        rows = service_rows(store, service)
        if service.get("fields"):
            rows = [{f: r.get(f) for f in service["fields"]} for r in rows]
        store.audit(
            "app:" + app_client["name"] if app_client else "api-key",
            "service.query",
            key,
        )
        return ok(page(rows, request))

    def check_kind(kind):
        if kind not in KINDS:
            fail(404, "未知资源类型")

    def save_entity(store, kind, body, key=None):
        check_kind(kind)
        json.dumps(body, allow_nan=False)
        old = store.get(kind, key) if key else {}
        if key and not old:
            fail(404, "记录不存在")
        record = {**old, **body}
        if (
            not isinstance(record.get("name"), str)
            or not record["name"].strip()
            or len(record["name"]) > 120
        ):
            fail(422, "名称需要1至120个字符")
        record["name"] = record["name"].strip()
        if key and old.get("approvalStatus") == "approved":
            record["approvalStatus"] = "draft"
            record.pop("approvedAt", None)
            record.pop("approvedBy", None)
        if kind == "workflows":
            validate(record)
        if kind == "rules":
            validate_rule(record)
        if kind == "sources":
            if any(body.get(k) for k in ("password", "passwordSecret", "passwd")):
                fail(422, "密码请在连接或采集时提供，不保存在数据源配置中")
            from .connector_common import PUBLIC_FIELDS, source_config

            record = {k: record[k] for k in PUBLIC_FIELDS if k in record}
            source_config(record)
            record.update(
                status="draft",
                connectionStatus="untested",
            )
        if kind == "datasets":
            rows = record.get("rows")
            if (
                not isinstance(rows, list)
                or len(rows) > 10000
                or any(not isinstance(r, dict) for r in rows)
            ):
                fail(422, "请提供不超过10,000行的JSON对象数组")
            if rows:
                if len(rows[0]) > 100 or any(set(row) != set(rows[0]) for row in rows):
                    fail(422, "数据集每行字段必须相同，最多100个字段")
                if any(
                    not isinstance(v, (str, int, float, bool, type(None)))
                    for row in rows
                    for v in row.values()
                ):
                    fail(422, "字段值仅支持基础类型")
        if kind == "tables":
            columns = record.get("columns", [])
            if (
                not isinstance(columns, list)
                or len(columns) > 100
                or any(
                    not isinstance(c, dict)
                    or not isinstance(c.get("name"), str)
                    or not c["name"].strip()
                    or len(c["name"]) > 200
                    or (c.get("type") is not None and not isinstance(c["type"], str))
                    for c in columns
                )
            ):
                fail(
                    422,
                    "字段结构需为不超过100个对象的数组，每项填写非空name和可选字符串type",
                )
            names = [c["name"].strip() for c in columns]
            if len(set(names)) != len(names):
                fail(422, "字段名称不能重复")
            record["columns"] = [{**c, "name": name} for c, name in zip(columns, names)]
            if record.get("datasetId") and not store.get(
                "datasets", record["datasetId"]
            ):
                fail(422, "样例数据集不存在")
        if kind == "dictionaries":
            items = record.get("dictionaryDetails", [])
            if (
                not isinstance(items, list)
                or len(items) > 10000
                or any(
                    not isinstance(item, dict)
                    or any(
                        not isinstance(item.get(f), str)
                        or not item[f].strip()
                        or len(item[f]) > 200
                        for f in ("code", "name")
                    )
                    for item in items
                )
            ):
                fail(
                    422, "代码项需为对象数组，每项填写非空code和name，单项最多200个字符"
                )
            codes = [item["code"].strip() for item in items]
            if len(set(codes)) != len(codes):
                fail(422, "代码集中的代码不能重复")
            record["dictionaryDetails"] = [
                {**item, "code": code, "name": item["name"].strip()}
                for item, code in zip(items, codes)
            ]
        if kind in ("qualityTasks", "services", "assets"):
            if record.get("datasetId") and not store.get(
                "datasets", record["datasetId"]
            ):
                fail(422, "样例数据集不存在")
        if kind == "qualityTasks":
            if (
                not record.get("datasetId")
                or not record.get("ruleIds")
                or any(not store.get("rules", r) for r in record["ruleIds"])
            ):
                fail(422, "请选择数据集和有效质量规则")
        if kind == "services":
            service_rows(store, record)
            if not isinstance(record.get("fields", []), list):
                fail(422, "发布字段必须是数组")
            if any(
                not isinstance(f, str) or not f.strip()
                for f in record.get("fields", [])
            ):
                fail(422, "发布字段必须是非空字符串")
            record.pop("apiKey", None)
            record.pop("apiKeyHash", None)
            record["published"] = False
        return store.save(kind, record, key)

    @gov.get("/{kind}")
    def list_entities(kind: str, request: Request):
        check_kind(kind)
        return ok(
            page([visible(kind, r) for r in request.app.state.store.all(kind)], request)
        )

    @gov.get("/{kind}/{key}")
    def get_entity(kind: str, key: str, request: Request):
        check_kind(kind)
        record = request.app.state.store.get(kind, key)
        if not record:
            fail(404, "记录不存在")
        return ok(record if kind == "datasets" else visible(kind, record))

    @gov.post("/{kind}")
    def create_entity(
        kind: str,
        request: Request,
        body: Annotated[dict[str, Any], Body()],
        account=Depends(admin),
    ):
        store = request.app.state.store
        record = save_entity(store, kind, body)
        store.audit(account["name"], kind + ".create", record["id"])
        return ok(visible(kind, record))

    @gov.put("/{kind}/{key}")
    @gov.patch("/{kind}/{key}")
    def update_entity(
        kind: str,
        key: str,
        request: Request,
        body: Annotated[dict[str, Any], Body()],
        account=Depends(admin),
    ):
        store = request.app.state.store
        record = save_entity(store, kind, body, key)
        store.audit(account["name"], kind + ".update", key)
        return ok(visible(kind, record))

    @gov.delete("/{kind}/{key}")
    def delete_entity(kind: str, key: str, request: Request, account=Depends(admin)):
        check_kind(kind)
        store = request.app.state.store
        if not store.get(kind, key):
            fail(404, "记录不存在")
        if kind == "datasets":
            referenced_by_flow = any(
                n.get("config", {}).get("datasetId") == key
                for w in store.all("workflows")
                for n in w.get("nodes", [])
            )
            referenced_by_entity = any(
                r.get("datasetId") == key
                for k in ("qualityTasks", "services", "assets", "tables")
                for r in store.all(k)
            )
            if referenced_by_flow or referenced_by_entity:
                fail(409, "数据集仍被流程、任务、服务或资产引用")
        if kind == "rules" and (
            any(key in t.get("ruleIds", []) for t in store.all("qualityTasks"))
            or any(
                key in n.get("config", {}).get("ruleIds", [])
                for w in store.all("workflows")
                for n in w.get("nodes", [])
            )
        ):
            fail(409, "规则仍被流程或质量任务引用")
        store.remove(kind, key)
        store.audit(account["name"], kind + ".delete", key)
        return ok()

    app.include_router(gov)
    from .local_api import install

    install(app, user, admin)
    from .ingestion_api import install as install_ingestion

    install_ingestion(app, admin)

    @app.api_route(
        "/api/{unknown:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_api(unknown: str):
        fail(404, "该接口不存在，请查看/docs中的新API")

    dist = config.ROOT / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{route:path}", include_in_schema=False)
    def frontend(route: str):
        if route.startswith((".data", "api/", "src/")):
            fail(404, "页面不存在")
        if not (dist / "index.html").exists():
            fail(503, "请先执行npm run build，或使用npm run dev启动前端开发服务")
        return FileResponse(dist / "index.html")

    return app


app = create_app()
