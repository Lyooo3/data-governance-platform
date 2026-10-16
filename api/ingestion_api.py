from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, SecretStr, Field, StrictInt
from .connectors import open_reader
from .storage import now
from .connector_common import catalog, require_password


class Credential(BaseModel):
    password: SecretStr = Field(default_factory=lambda: SecretStr(""), max_length=1024)


class Capture(Credential):
    name: str = Field(default="", max_length=120)
    tables: list[StrictInt] | None = Field(default=None, max_length=2000)


def install(app, admin):
    router = APIRouter(
        prefix="/api/ingestion",
        tags=["数据库只读采集与原始库"],
        dependencies=[Depends(admin)],
    )

    def source(request, key):
        record = request.app.state.store.get("sources", key)
        if not record:
            raise HTTPException(404, "数据源不存在")
        return record

    def ok(data):
        return {"code": 200, "success": True, "data": data}

    @router.get("/connectors")
    def connectors():
        return ok({"list": catalog()})

    @router.post("/sources/{key}/test")
    def test(key: str, request: Request, body: Credential, actor=Depends(admin)):
        record = source(request, key)
        require_password(record, body.password.get_secret_value())
        with open_reader(record, body.password.get_secret_value()) as reader:
            info = reader.info()
        if info["read_only"] != "on":
            raise ValueError("只读连接校验失败")
        request.app.state.store.save(
            "sources",
            {
                **record,
                "status": "connected",
                "connectionStatus": "tested",
                "lastTestAt": now(),
            },
            key,
        )
        request.app.state.store.audit(actor["name"], "source.test", key)
        return ok(info)

    @router.post("/sources/{key}/tables")
    def tables(key: str, request: Request, body: Credential, actor=Depends(admin)):
        require_password(source(request, key), body.password.get_secret_value())
        with open_reader(
            source(request, key), body.password.get_secret_value()
        ) as reader:
            values = reader.tables()
        request.app.state.store.audit(actor["name"], "source.scan", key)
        return ok({"list": values, "total": len(values)})

    @router.post("/sources/{key}/snapshots")
    def capture(key: str, request: Request, body: Capture, actor=Depends(admin)):
        return ok(
            request.app.state.raw.start(
                source(request, key),
                body.password.get_secret_value(),
                body.tables,
                body.name,
                actor["name"],
            )
        )

    @router.get("/snapshots")
    def snapshots(request: Request, sourceId: str | None = None):
        values = request.app.state.raw.list(sourceId)
        return ok({"list": values, "total": len(values)})

    @router.get("/snapshots/{key}")
    def snapshot(key: str, request: Request):
        manager = request.app.state.raw
        return ok({**manager.get(key), "tables": manager.tables(key)})

    @router.post("/snapshots/{key}/cancel")
    def cancel(key: str, request: Request, actor=Depends(admin)):
        value = request.app.state.raw.cancel(key)
        request.app.state.store.audit(actor["name"], "raw.snapshot.cancel", key)
        return ok(value)

    @router.get("/snapshots/{key}/tables/{table_id}/rows")
    def rows(
        key: str, table_id: str, request: Request, pageNum: int = 1, pageSize: int = 20
    ):
        pageNum = max(1, pageNum)
        pageSize = min(100, max(1, pageSize))
        manager = request.app.state.raw
        table = manager.table(key, table_id)
        return ok(
            {
                "list": manager.rows(
                    key, table_id, (pageNum - 1) * pageSize, pageSize, raw=True
                ),
                "total": table["rowCount"],
                "pageNum": pageNum,
                "pageSize": pageSize,
            }
        )

    @router.post("/snapshots/{key}/tables/{table_id}/datasets")
    def dataset(
        key: str,
        table_id: str,
        request: Request,
        body: dict = Body(default={}),
        actor=Depends(admin),
    ):
        return ok(request.app.state.raw.materialize(key, table_id, body, actor["name"]))

    @router.get("/snapshots/{key}/download")
    def download(key: str, request: Request, actor=Depends(admin)):
        value = request.app.state.raw.get(key)
        if value["status"] != "SUCCESS":
            raise ValueError("原始库未完成，无法下载")
        request.app.state.store.audit(actor["name"], "raw.snapshot.download", key)
        return FileResponse(
            request.app.state.raw.path(key),
            filename=value["name"] + ".sqlite3",
            media_type="application/vnd.sqlite3",
        )

    app.include_router(router)
