# -*- coding: utf-8 -*-
"""会话管理 API — 5 个接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.core.security import generate_session_id
from app.schemas.common import ok
from app.schemas.session import SessionCreateRequest, SessionUpdateRequest

router = APIRouter()


@router.post("", summary="创建会话", status_code=201)
async def session_create(body: SessionCreateRequest, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"session_id": generate_session_id(), "user_id": body.user_id, "status": "active"}, "创建成功")


@router.get("/{session_id}", summary="查询会话")
async def session_get(session_id: str, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"session_id": session_id, "status": "active", "message_count": 0})


@router.get("", summary="会话列表")
async def session_list(
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    scene_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


@router.put("/{session_id}", summary="更新会话")
async def session_update(session_id: str, body: SessionUpdateRequest, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"session_id": session_id, "updated": True}, "更新成功")


@router.post("/{session_id}/close", summary="关闭会话")
async def session_close(session_id: str, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"session_id": session_id, "status": "closed", "message_count": 0, "summary": "会话已关闭"}, "关闭成功")
