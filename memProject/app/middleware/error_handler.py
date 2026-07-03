# -*- coding: utf-8 -*-
"""
全局异常处理器 — 将所有异常转为标准 JSON 响应。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException
from app.core.logger import get_logger

logger = get_logger("error_handler")


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        trace_id = getattr(request.state, "trace_id", None)
        logger.warning(
            f"app exception: {exc.code} - {exc.message}",
            extra={"trace_id": trace_id, "error_code": exc.code, "detail": exc.detail},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": -1,
                "message": exc.message,
                "error_code": exc.code,
                "detail": exc.detail,
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None)
        logger.exception(
            f"unhandled exception: {exc}",
            extra={"trace_id": trace_id},
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": -1,
                "message": "内部服务异常，请稍后重试",
                "error_code": "INTERNAL_ERROR",
                "detail": {"error": str(exc)} if app.debug else None,
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(422)
    async def validation_exception_handler(request: Request, exc):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=422,
            content={
                "code": -1,
                "message": "请求参数校验失败",
                "error_code": "VALIDATION_ERROR",
                "detail": exc.errors() if hasattr(exc, "errors") else None,
                "trace_id": trace_id,
            },
        )
