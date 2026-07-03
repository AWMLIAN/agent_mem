# -*- coding: utf-8 -*-
"""智能体管理 API — 6 个接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.core.security import generate_agent_id, generate_api_key
from app.schemas.common import ok
from app.schemas.agent import AgentRegisterRequest, AgentUpdateRequest

router = APIRouter()


@router.post("/register", summary="注册智能体", status_code=201)
async def agent_register(body: AgentRegisterRequest, db: AsyncSession = Depends(get_db)):
    return ok({
        "agent_id": generate_agent_id(),
        "agent_name": body.agent_name,
        "api_key": generate_api_key(),
        "api_key_prefix": "mem_****",
    }, "注册成功")


@router.get("/{agent_id}", summary="查询智能体")
async def agent_get(agent_id: str, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"agent_id": agent_id, "agent_name": "示例智能体", "is_active": True})


@router.get("", summary="智能体列表")
async def agent_list(
    scene_id: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current: str = Depends(get_current_agent),
):
    return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


@router.put("/{agent_id}", summary="更新智能体")
async def agent_update(agent_id: str, body: AgentUpdateRequest, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"agent_id": agent_id, "updated": True}, "更新成功")


@router.delete("/{agent_id}", summary="停用智能体")
async def agent_disable(agent_id: str, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"agent_id": agent_id, "is_active": False}, "已停用")


@router.post("/{agent_id}/rotate-key", summary="轮换 API Key")
async def agent_rotate_key(agent_id: str, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"agent_id": agent_id, "api_key": generate_api_key()}, "轮换成功")
