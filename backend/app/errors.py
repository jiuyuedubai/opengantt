"""类型化错误体系 + 全局异常处理：客户端只看到规范化错误结构。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务错误基类：可安全返回给客户端的错误。"""

    status_code = 400
    code = "app_error"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class DependencyCycleError(AppError):
    status_code = 422
    code = "dependency_cycle"


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = (exc.errors() or [{}])[0]
        loc = ".".join(str(p) for p in first.get("loc", []) if p not in ("body",))
        message = first.get("msg", "输入参数不合法")
        detail = f"{loc}: {message}" if loc else message
        return _error_response(422, "validation_error", detail)
