import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.alerts import Severity
from app.services.alerting import report_async

logger = logging.getLogger("zbridge.errors")


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    # 4xx is the caller's problem (bad input, no permission) and must not page
    # anyone; 5xx means our side failed and is worth an alert.
    if exc.status_code >= 500:
        await report_async(
            exc.code,
            exc.message,
            severity=Severity.ERROR,
            context={"method": request.method, "path": request.url.path},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Any exception reaching here is a bug, so it always alerts."""
    logger.exception("UNHANDLED_EXCEPTION path=%s", request.url.path)
    await report_async(
        "UNHANDLED_EXCEPTION",
        f"{type(exc).__name__}: {exc}",
        severity=Severity.CRITICAL,
        context={"method": request.method, "path": request.url.path},
        dedup_key=f"backend:UNHANDLED:{request.url.path}",
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Hệ thống gặp lỗi không mong muốn. Lỗi đã được báo cho quản trị viên.",
            }
        },
    )
