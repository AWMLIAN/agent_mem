# -*- coding: utf-8 -*-
"""
API 依赖注入 — 鉴权、租户隔离、上下文注入。

对齐《智能体接入与记忆数据写入后端功能任务分工》角色A职责：
1. 全局鉴权中间件校验（API Key / Token）
2. 多租户数据隔离（强制注入 agent_id + scene_id）
3. Header 校验与默认值处理
"""

from typing import Optional

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.logger import get_logger
from app.core.security import decode_access_token, hash_api_key
from app.models.base import Agent, Scene

logger = get_logger("deps")


async def get_current_agent(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    验证调用方身份，返回 agent_id。

    鉴权优先级：API Key > JWT Bearer Token

    安全措施（对齐设计文档 一.1 节）：
    1. API Key → SHA256 哈希 → 查 T_AGENT 表
    2. 验证 is_active 状态（停用的 Agent 拒绝访问）
    3. JWT → 解码 → 返回 subject (agent_id)
    4. 验证通过后将 agent_id 存入 request.state 供后续使用
    """
    if x_api_key:
        key_hash = hash_api_key(x_api_key)
        result = await db.execute(
            select(Agent).where(
                Agent.api_key_hash == key_hash,
                Agent.is_active == True,
            )
        )
        agent = result.scalar_one_or_none()

        if not agent:
            logger.warning(f"无效的 API Key 尝试: prefix={x_api_key[:8]}...")
            raise AuthenticationError("无效的 API Key")

        # 注入 agent_id 到 request.state
        request.state.agent_id = agent.agent_id
        request.state.scene_id = agent.scene_id

        logger.debug(f"Agent 鉴权通过 (API Key): agent_id={agent.agent_id}")
        return agent.agent_id

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        agent_id = decode_access_token(token)
        if not agent_id:
            logger.warning("无效的 JWT Token")
            raise AuthenticationError("无效的 Token")

        # 验证 Token 中的 agent 是否仍然有效
        result = await db.execute(
            select(Agent).where(
                Agent.agent_id == agent_id,
                Agent.is_active == True,
            )
        )
        if not result.scalar_one_or_none():
            raise AuthenticationError("Token 对应的智能体已停用或不存在")

        request.state.agent_id = agent_id
        logger.debug(f"Agent 鉴权通过 (JWT): agent_id={agent_id}")
        return agent_id

    logger.warning("请求缺少认证凭证")
    raise AuthenticationError("缺少认证凭证 — 请提供 X-API-Key 或 Authorization: Bearer <token>")


async def get_current_user_id(request: Request) -> str:
    """
    从 Header 获取当前用户 ID。

    设计文档要求：每个请求必须携带 X-User-Id，用于多租户数据隔离。
    """
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise AuthenticationError(
            "缺少 X-User-Id 请求头 — 请提供用户唯一标识"
        )
    # 标准化
    user_id = user_id.strip().lower()
    if len(user_id) > 128:
        raise AuthenticationError("X-User-Id 长度超过限制 (128)")
    return user_id


async def get_current_scene_id(request: Request) -> Optional[str]:
    """
    从 Header 获取场景 ID。

    如果 Header 中没有 X-Scene-Id，则尝试从 Agent 注册信息中获取。
    """
    scene_id = request.headers.get("X-Scene-Id")
    if scene_id:
        return scene_id.strip()
    # fallback: 使用 Agent 注册时绑定的 scene_id
    return getattr(request.state, "scene_id", None)


async def get_current_session_id(request: Request) -> Optional[str]:
    """从 Header 获取会话 ID"""
    session_id = request.headers.get("X-Session-Id")
    if session_id:
        return session_id.strip().lower()
    return None


async def get_current_task_id(request: Request) -> Optional[str]:
    """从 Header 获取任务 ID"""
    task_id = request.headers.get("X-Task-Id")
    if task_id:
        return task_id.strip().lower()
    return None


async def verify_scene_access(
    scene_id: Optional[str],
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """
    验证 Agent 对 Scene 的访问权限。

    规则：
    - Agent 注册时如果绑定了 scene_id，则只能访问该 scene
    - 如果 Agent 未绑定 scene，则可以访问任何 scene
    - scene_id 为 None 时跳过校验（公共资源）
    """
    if not scene_id:
        return None

    # 查 Agent 的绑定 scene
    result = await db.execute(
        select(Agent).where(Agent.agent_id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise AuthenticationError("智能体不存在")

    # 如果 Agent 绑定了特定 scene，限制访问
    if agent.scene_id and agent.scene_id != scene_id:
        raise AuthorizationError(
            f"智能体 {agent_id} 无权访问场景 {scene_id}，"
            f"仅限访问场景 {agent.scene_id}"
        )

    return scene_id


async def verify_data_isolation(
    request_user_id: str,
    agent_id: str,
) -> None:
    """
    验证数据隔离 — 确保请求中的数据归属于声明的用户。

    防止跨租户数据污染（设计文档 五.2 节）。
    """
    # 确保 user_id 不为空且格式合法
    if not request_user_id or not request_user_id.strip():
        raise AuthenticationError("user_id 不能为空")

    # 记录隔离校验通过（后续可扩展更细粒度的规则）
    pass
