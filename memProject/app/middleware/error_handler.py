# -*- coding: utf-8 -*-
"""
全局异常处理器 — 将所有异常转为标准 JSON 响应。

对齐前端对接文档统一响应格式：
  成功: {"code": 0, "message": "ok", "data": {...}}
  失败: {"code": -1, "message": "...", "error_code": "...", "trace_id": "..."}

对齐核心改动文档：
  - trace_id 从 Request State 提取，无则生成
  - 422 错误码统一为 INVALID_PARAM
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException
from app.core.logger import get_logger

logger = get_logger("error_handler")


def _get_trace_id(request: Request) -> str:
    """从 Request State 提取 trace_id，无则生成"""
    trace_id = getattr(request.state, "trace_id", None)
    if trace_id:
        return trace_id
    # fallback: 如果 LoggingMiddleware 还未设置（极少见）
    trace_id = uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    return trace_id


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        trace_id = _get_trace_id(request)
        logger.warning(
            f"[{trace_id}] AppException {exc.status_code}: {exc.code} — {exc.message}",
            extra={"trace_id": trace_id, "error_code": exc.code, "detail": exc.detail},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": -1,
                "message": exc.message,
                "error_code": exc.code,
                "detail": exc.detail or {},
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        trace_id = _get_trace_id(request)
        errors = exc.errors() if hasattr(exc, "errors") else None
        # 提取第一个错误的字段和原因，生成可读 message
        field_names = []
        if errors:
            for e in errors[:3]:  # 最多取前 3 个
                loc = " → ".join(str(l) for l in e.get("loc", []))
                msg = e.get("msg", "")
                field_names.append(f"{loc}: {msg}")

        logger.warning(
            f"[{trace_id}] ValidationError 422: {field_names}",
            extra={"trace_id": trace_id, "path": request.url.path},
        )
        return JSONResponse(
            status_code=422,
            content={
                "code": -1,
                "message": f"请求参数校验失败: {'; '.join(field_names)}" if field_names else "请求参数校验失败",
                "error_code": "INVALID_PARAM",
                "detail": {"errors": errors},
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = _get_trace_id(request)
        logger.exception(
            f"[{trace_id}] Unhandled 500: {type(exc).__name__}: {exc}",
            extra={"trace_id": trace_id, "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": -1,
                "message": "内部服务异常，请稍后重试" if not app.debug else f"{type(exc).__name__}: {exc}",
                "error_code": "INTERNAL_ERROR",
                "detail": {"error": str(exc)} if app.debug else {},
                "trace_id": trace_id,
            },
        )
