# -*- coding: utf-8 -*-
"""
请求日志中间件 — Trace ID 注入 + 请求耗时记录。
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logger import get_logger

settings = get_settings()
logger = get_logger("middleware")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id", uuid.uuid4().hex[:16])
        request.state.trace_id = trace_id

        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Response-Time"] = str(elapsed_ms)

        if request.url.path not in ("/metrics", "/health"):
            logger.info(
                "request completed",
                extra={
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
        return response
