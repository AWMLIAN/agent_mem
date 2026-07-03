# -*- coding: utf-8 -*-
"""
认证中间件 — API Key / JWT 双模式验证。
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.security import decode_access_token, hash_api_key

settings = get_settings()

# 无需认证的公开路径
PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# 动态校验由中间件交由依赖注入完成，此处提供基础方法
# 实际鉴权在 api/deps.py 的依赖注入中实现


class AuthMiddleware(BaseHTTPMiddleware):
    """
    请求级认证中间件：提取 API Key 或 JWT，存入 request.state。
    不在此处拒绝请求，将校验逻辑交给具体的依赖注入 — 便于管理接口有独立的鉴权规则。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)

        api_key = request.headers.get(settings.auth.api_key_header)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")

        request.state.api_key = api_key
        request.state.token = token
        request.state.agent_id = None

        if api_key:
            request.state.api_key_hash = hash_api_key(api_key)
        elif token:
            subject = decode_access_token(token)
            if subject:
                request.state.agent_id = subject

        return await call_next(request)
