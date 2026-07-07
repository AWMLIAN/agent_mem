# -*- coding: utf-8 -*-
"""
认证中间件 — API Key / JWT 双模式验证。

对齐核心改动文档：
- 开发阶段 AUTH_ENABLED=False：跳过鉴权，请求自由通过
- 生产阶段 AUTH_ENABLED=True：强制校验 API Key 或 JWT
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

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


class AuthMiddleware(BaseHTTPMiddleware):
    """
    请求级认证中间件：提取 API Key 或 JWT，存入 request.state。

    开发阶段 (AUTH_ENABLED=False)：
      - 完全跳过鉴权，所有请求自由通过
      - 设置 request.state.auth_bypassed = True

    生产阶段 (AUTH_ENABLED=True)：
      - 提取 API Key 或 JWT，存入 request.state
      - 不在此处拒绝请求，实际鉴权由 deps.py 依赖注入完成
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径始终跳过
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
            request.state.auth_bypassed = True
            return await call_next(request)

        # ================================================================
        # 开发阶段：跳过鉴权
        # ================================================================
        if not settings.auth.enabled:
            request.state.api_key = None
            request.state.token = None
            request.state.agent_id = None
            request.state.auth_bypassed = True
            # 尝试从 Header 提取 agent_id（即使不校验也保留上下文）
            request.state.agent_id = request.headers.get("X-Agent-Id")
            request.state.scene_id = request.headers.get("X-Scene-Id")
            return await call_next(request)

        # ================================================================
        # 生产阶段：提取凭证
        # ================================================================
        api_key = request.headers.get(settings.auth.api_key_header)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")

        request.state.api_key = api_key
        request.state.token = token
        request.state.agent_id = None
        request.state.auth_bypassed = False

        if api_key:
            request.state.api_key_hash = hash_api_key(api_key)
        elif token:
            subject = decode_access_token(token)
            if subject:
                request.state.agent_id = subject

        return await call_next(request)
