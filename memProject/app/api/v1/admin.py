# -*- coding: utf-8 -*-
"""管理后台 API — 5 个接口。"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.schemas.common import ok
from app.models.base import RetrievalRequest, ApiLog
from app.services.memory_service import (
    get_memory_by_id,
    get_memory_relations,
    get_stats,
    list_memories_filtered,
)

router = APIRouter()


def _memory_item(m) -> dict:
    return {
        "memory_id": m.memory_id, "content": m.content, "memory_type": m.memory_type,
        "status": m.status, "importance": m.importance, "user_id": m.user_id,
        "agent_id": m.agent_id, "session_id": m.session_id, "task_id": m.task_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/memories", summary="分页查询全部记忆")
async def admin_memories(
    user_id: str | None = Query(None),
    memory_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(get_current_agent),
):
    filters = {}
    if user_id: filters["user_id"] = user_id
    if memory_type: filters["memory_types"] = [memory_type]
    if status: filters["status"] = status
    items, total = await list_memories_filtered(db, filters, page, page_size)
    return ok({"items": [_memory_item(m) for m in items], "total": total, "page": page, "page_size": page_size})


@router.get("/memories/{memory_id}", summary="记忆详情（含关系链路）")
async def admin_memory_detail(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(get_current_agent),
):
    memory = await get_memory_by_id(db, memory_id)
    if not memory:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"记忆 {memory_id} 不存在")
    relations = await get_memory_relations(db, memory_id)
    return ok({**_memory_item(memory), "relations": relations})


@router.get("/retrieval-logs", summary="检索请求日志")
async def admin_retrieval_logs(
    agent_id: str | None = Query(None),
    hours: int = Query(24, ge=1, le=720),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(get_current_agent),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = select(RetrievalRequest).where(RetrievalRequest.created_at >= since)
    if agent_id:
        stmt = stmt.where(RetrievalRequest.agent_id == agent_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(RetrievalRequest.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = [
        {"request_id": r.request_id, "agent_id": r.agent_id, "user_id": r.user_id,
         "query_text": r.query_text, "top_k": r.top_k,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in result.scalars().all()
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/stats", summary="系统统计概览")
async def admin_stats(db: AsyncSession = Depends(get_db), _admin: str = Depends(get_current_agent)):
    return ok(await get_stats(db))


@router.get("/api-logs", summary="接口调用日志")
async def admin_api_logs(
    api_path: str | None = Query(None),
    error_code: str | None = Query(None),
    hours: int = Query(24, ge=1, le=720),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(get_current_agent),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = select(ApiLog).where(ApiLog.created_at >= since)
    if api_path:
        stmt = stmt.where(ApiLog.api_path == api_path)
    if error_code:
        stmt = stmt.where(ApiLog.error_code == error_code)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(ApiLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = [
        {"log_id": r.log_id, "agent_id": r.agent_id, "api_path": r.api_path,
         "method": r.method, "response_code": r.response_code, "error_code": r.error_code,
         "elapsed_ms": r.elapsed_ms, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in result.scalars().all()
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})
