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


def _sanitize_errors(errors: list) -> list:
    """
    清洗 Pydantic ValidationError 中的非 JSON 可序列化对象。

    Pydantic v2 的 field_validator 抛出的 ValueError 会嵌入到
    RequestValidationError.errors() 的 ctx.error 中，导致 json.dumps 失败。
    这里将所有不可序列化的值转为字符串。
    """
    import json as _json

    safe_list = []
    for e in errors:
        safe_item = {}
        for k, v in e.items():
            if k == "ctx" and isinstance(v, dict):
                # ctx 中的 error 对象转为 repr
                safe_ctx = {}
                for ck, cv in v.items():
                    try:
                        _json.dumps(cv)  # 快速测试是否可序列化
                        safe_ctx[ck] = cv
                    except (TypeError, ValueError, _json.JSONDecodeError):
                        safe_ctx[ck] = repr(cv)
                safe_item[k] = safe_ctx
            else:
                try:
                    _json.dumps(v)
                    safe_item[k] = v
                except (TypeError, ValueError, _json.JSONDecodeError):
                    safe_item[k] = repr(v)
        safe_list.append(safe_item)
    return safe_list


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
        raw_errors = exc.errors() if hasattr(exc, "errors") else None

        # ── 清洗 errors 中的非 JSON 可序列化对象 ──
        safe_errors = _sanitize_errors(raw_errors) if raw_errors else None

        # 提取前 3 个错误的字段和原因，生成可读 message
        field_names = []
        if safe_errors:
            for e in safe_errors[:3]:
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
                "detail": {"errors": safe_errors},
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = _get_trace_id(request)
        logger.opt(exception=True).error(
            "[{}] Unhandled 500: {}: {}",
            trace_id, type(exc).__name__, exc,
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
