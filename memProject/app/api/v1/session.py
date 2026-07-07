# -*- coding: utf-8 -*-
"""
会话管理 API — 5 个接口，全部实现真实 DB 操作。

对齐前端对接文档 三 节：
- POST /session — 创建会话
- GET /session/{id} — 查询
- GET /session — 列表
- PUT /session/{id} — 更新
- POST /session/{id}/close — 关闭会话
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent, get_current_user_id
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.logger import get_logger
from app.core.security import generate_session_id
from app.models.base import Session
from app.schemas.common import ok
from app.schemas.session import SessionCreateRequest, SessionUpdateRequest

logger = get_logger("session_api")
router = APIRouter()


@router.post("", summary="创建会话", status_code=201)
async def session_create(
    body: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
):
    """创建新会话，状态 active"""
    session_id = generate_session_id()

    session = Session(
        session_id=session_id,
        user_id=body.user_id.strip().lower(),
        agent_id=body.agent_id or agent_id,
        scene_id=body.scene_id,
        task_id=body.task_id,
        status="active",
        started_at=datetime.now(timezone.utc),
        message_count=0,
        extra_meta=body.extra_meta or {},
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    logger.info(f"会话创建: session_id={session_id}, user_id={body.user_id}")

    return ok({
        "session_id": session_id,
        "user_id": session.user_id,
        "agent_id": session.agent_id,
        "scene_id": session.scene_id,
        "task_id": session.task_id,
        "status": "active",
        "started_at": session.started_at.isoformat() if session.started_at else None,
    }, "创建成功")


@router.get("/{session_id}", summary="查询会话")
async def session_get(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    """查询单个会话"""
    result = await db.execute(
        select(Session).where(Session.session_id == session_id.strip().lower())
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError(f"会话不存在: {session_id}")

    return ok({
        "session_id": session.session_id,
        "user_id": session.user_id,
        "agent_id": session.agent_id,
        "scene_id": session.scene_id,
        "task_id": session.task_id,
        "status": session.status,
        "message_count": session.message_count,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    })


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
    """分页查询会话列表"""
    query = select(Session)

    if user_id:
        query = query.where(Session.user_id == user_id.strip().lower())
    if status:
        query = query.where(Session.status == status)
    if scene_id:
        query = query.where(Session.scene_id == scene_id.strip().lower())

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Session.started_at.desc()).offset(offset).limit(page_size)
    sessions = (await db.execute(query)).scalars().all()

    items = []
    for s in sessions:
        items.append({
            "session_id": s.session_id,
            "user_id": s.user_id,
            "agent_id": s.agent_id,
            "scene_id": s.scene_id,
            "task_id": s.task_id,
            "status": s.status,
            "message_count": s.message_count,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        })

    return ok({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.put("/{session_id}", summary="更新会话")
async def session_update(
    session_id: str,
    body: SessionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    """更新会话状态/关联任务"""
    result = await db.execute(
        select(Session).where(Session.session_id == session_id.strip().lower())
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError(f"会话不存在: {session_id}")

    if body.status is not None:
        session.status = body.status
    if body.task_id is not None:
        session.task_id = body.task_id.strip().lower()
    if body.extra_meta is not None:
        session.extra_meta = body.extra_meta

    await db.commit()
    logger.info(f"会话更新: session_id={session_id}")

    return ok({"session_id": session_id, "updated": True}, "更新成功")


@router.post("/{session_id}/close", summary="关闭会话")
async def session_close(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    """
    关闭会话。

    触发动作：
    1. 更新 status → closed
    2. 记录 ended_at
    3. 触发长对话压缩任务（角色B实现）
    """
    result = await db.execute(
        select(Session).where(Session.session_id == session_id.strip().lower())
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError(f"会话不存在: {session_id}")

    session.status = "closed"
    session.ended_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(f"会话关闭: session_id={session_id}, messages={session.message_count}")

    return ok({
        "session_id": session_id,
        "status": "closed",
        "message_count": session.message_count or 0,
        "ended_at": session.ended_at.isoformat(),
        "summary": "会话已关闭",
    }, "关闭成功")
