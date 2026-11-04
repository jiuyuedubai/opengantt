"""应用包初始化：集中创建 FastAPI 实例（CORS、路由、静态托管）。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenGantt API",
        description="免费开源甘特图项目进度管理平台 API",
        version="1.0.0",
    )

    register_exception_handlers(app)

    from app.api.admin import router as admin_router
    from app.api.audit import router as audit_router
    from app.api.auth import router as auth_router
    from app.api.daily_tasks import router as daily_tasks_router
    from app.api.departments import router as departments_router
    from app.api.doc_access import router as doc_access_router
    from app.api.documents import router as documents_router
    from app.api.performance import router as performance_router
    from app.api.projects import router as projects_router
    from app.api.reports import router as reports_router
    from app.api.search import router as search_router
    from app.api.stats import router as stats_router
    from app.api.tasks import router as tasks_router
    from app.api.users import router as users_router

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    app.include_router(auth_router, tags=["auth"])
    app.include_router(admin_router, tags=["admin"])
    app.include_router(departments_router, tags=["departments"])
    app.include_router(users_router, tags=["users"])
    app.include_router(daily_tasks_router, tags=["daily-tasks"])
    app.include_router(projects_router, tags=["projects"])
    app.include_router(tasks_router, tags=["tasks"])
    app.include_router(documents_router, tags=["documents"])
    app.include_router(reports_router, tags=["reports"])
    app.include_router(stats_router, tags=["stats"])
    app.include_router(search_router, tags=["search"])
    app.include_router(audit_router, tags=["audit"])
    app.include_router(doc_access_router, tags=["doc-access"])
    app.include_router(performance_router, tags=["performance"])

    @app.get("/api/health", tags=["system"], summary="健康检查")
    def health() -> dict:
        return {"status": "ok", "app": "opengantt", "version": "1.0.0"}

    if settings.serve_frontend:
        from app.static_files import mount_frontend

        mount_frontend(app)

    return app


app = create_app()
