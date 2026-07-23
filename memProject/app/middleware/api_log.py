# -*- coding: utf-8 -*-
"""
API 日志中间件 — 异步记录每次接口调用到 T_API_LOG 表。

对齐《核心业务逻辑拆解》第四节 T_API_LOG 设计：
- log_id, agent_id, api_path, request_body, response_code, cost_time_ms, error_msg
- 使用 fire-and-forget 模式，不阻塞主请求响应
"""

import asyncio
import json
import time as time_module
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logger import get_logger

settings = get_settings()
logger = get_logger("api_log_middleware")

# 不记录日志的路径
SKIP_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/health",
}

# 请求体最大记录长度（字符），超过则截断
MAX_BODY_LOG_LENGTH = 2000


def _truncate(value: str, max_len: int = MAX_BODY_LOG_LENGTH) -> str:
    """截断过长内容"""
    if len(value) <= max_len:
        return value
    return value[:max_len] + f"... [截断，原长度 {len(value)}]"


async def _write_api_log(
    trace_id: str,
    agent_id: str | None,
    api_path: str,
    method: str,
    request_params: dict | None,
    response_code: int,
    error_code: str | None,
    elapsed_ms: int,
) -> None:
    """
    异步写入 API 调用日志到 T_API_LOG。

    fire-and-forget 模式：写入失败仅记录 warning，不抛出异常。
    """
    try:
        from app.core.database import async_session_factory
        from app.models.base import ApiLog

        log_entry = ApiLog(
            log_id=f"apilog_{uuid4().hex[:24]}",
            trace_id=trace_id,
            agent_id=agent_id,
            api_path=api_path,
            method=method,
            request_params=request_params,
            response_code=response_code,
            error_code=error_code,
            elapsed_ms=elapsed_ms,
        )

        async with async_session_factory() as session:
            session.add(log_entry)
            await session.commit()

    except Exception as e:
        # fire-and-forget — 不阻塞主流程
        logger.warning(f"API 日志写入失败 (非致命): {e}")


class ApiLogMiddleware(BaseHTTPMiddleware):
    """
    记录每次 API 调用的请求/响应信息到 T_API_LOG。

    采集字段：
    - trace_id: 链路追踪ID（由 LoggingMiddleware 设置）
    - agent_id: 调用方智能体ID（由 AuthMiddleware 设置）
    - api_path: 请求路径
    - method: HTTP 方法
    - request_params: 请求参数摘要（query params + body 截断）
    - response_code: HTTP 状态码
    - error_code: 业务错误码（异常时从响应中提取）
    - elapsed_ms: 请求耗时（毫秒）
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # 跳过不需要记录的路径
        if path in SKIP_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)

        # 从 request.state 获取上下文信息
        trace_id = getattr(request.state, "trace_id", None) or uuid4().hex[:16]
        agent_id = getattr(request.state, "agent_id", None)

        # 收集请求参数摘要
        request_params = _collect_request_params(request)

        # 计时
        start = time_module.perf_counter()
        response_code = 500
        error_code: str | None = "INTERNAL_ERROR"
        response: Response | None = None

        try:
            response = await call_next(request)
            response_code = response.status_code
            error_code = None
            # 从响应中提取错误码（如果存在）
            if response_code >= 400:
                error_code = _extract_error_code(response)
            return response
        except Exception:
            # 记录异常并重新抛出
            response_code = 500
            error_code = "INTERNAL_ERROR"
            raise
        finally:
            elapsed_ms = round((time_module.perf_counter() - start) * 1000)

            # 合并 context_snapshot（由 /context 端点设置，仅成功响应时附加）
            if 200 <= response_code < 300:
                snapshot = getattr(request.state, "context_snapshot", None)
                if snapshot is not None:
                    request_params["context_snapshot"] = snapshot

            # fire-and-forget 写入日志
            asyncio.create_task(
                _write_api_log(
                    trace_id=trace_id,
                    agent_id=agent_id,
                    api_path=path,
                    method=request.method,
                    request_params=request_params,
                    response_code=response_code,
                    error_code=error_code,
                    elapsed_ms=elapsed_ms,
                )
            )


def _collect_request_params(request: Request) -> dict:
    """安全收集请求参数摘要（不读取 body 流，避免消费）"""
    params: dict = {}

    # query 参数
    if request.query_params:
        params["query"] = dict(request.query_params)

    # path 参数
    if request.path_params:
        params["path"] = dict(request.path_params)

    return params


def _extract_error_code(response: Response) -> str | None:
    """从响应中提取业务错误码"""
    try:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            # 注意：StreamingResponse 的 body 可能无法直接读取
            # 这里通过检查响应的原始 body 来获取
            if hasattr(response, "body") and response.body:
                body_data = json.loads(response.body)
                return body_data.get("error_code")
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        pass
    return None
