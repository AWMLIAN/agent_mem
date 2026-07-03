# -*- coding: utf-8 -*-
"""管理后台 API — 5 个接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.schemas.common import ok

router = APIRouter()


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
    return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


@router.get("/memories/{memory_id}", summary="记忆详情（含关系链路）")
async def admin_memory_detail(memory_id: str, db: AsyncSession = Depends(get_db), _admin: str = Depends(get_current_agent)):
    return ok({"memory_id": memory_id, "content": "", "relations": []})


@router.get("/retrieval-logs", summary="检索请求日志")
async def admin_retrieval_logs(
    agent_id: str | None = Query(None),
    hours: int = Query(24, ge=1, le=720),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(get_current_agent),
):
    return ok({"items": [], "total": 0})


@router.get("/stats", summary="系统统计概览")
async def admin_stats(db: AsyncSession = Depends(get_db), _admin: str = Depends(get_current_agent)):
    return ok({"total_memories": 0, "total_users": 0, "total_agents": 0, "total_sessions": 0})


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
    return ok({"items": [], "total": 0})
