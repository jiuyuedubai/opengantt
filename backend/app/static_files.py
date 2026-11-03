"""生产模式：托管前端构建产物（SPA），并为刷新路由提供回退。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import NotFoundError


def mount_frontend(app: FastAPI) -> None:
    dist = settings.FRONTEND_DIST
    if not (dist / "index.html").is_file():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(dist / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str) -> FileResponse:
        candidate = (dist / path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            raise NotFoundError("资源不存在")
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
