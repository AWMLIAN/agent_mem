# -*- coding: utf-8 -*-
"""
API 依赖注入 — 数据库会话、当前用户/智能体/场景上下文。
"""

from typing import Optional

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token, hash_api_key
from app.models.base import Agent


async def get_current_agent(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    验证调用方身份，返回 agent_id。
    优先级：API Key > JWT
    """
    if x_api_key:
        key_hash = hash_api_key(x_api_key)
        result = await db.execute(
            select(Agent).where(Agent.api_key_hash == key_hash, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise AuthenticationError("无效的 API Key")
        return agent.agent_id

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        agent_id = decode_access_token(token)
        if not agent_id:
            raise AuthenticationError("无效的 Token")
        return agent_id

    raise AuthenticationError("缺少认证凭证 (X-API-Key 或 Authorization)")


async def get_current_user_id(request: Request) -> str:
    """从 Header 获取当前用户 ID"""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise AuthenticationError("缺少 X-User-Id 请求头")
    return user_id


async def get_current_scene_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Scene-Id")


async def get_current_session_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Session-Id")


async def get_current_task_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Task-Id")
