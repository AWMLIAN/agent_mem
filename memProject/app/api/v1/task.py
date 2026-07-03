# -*- coding: utf-8 -*-
"""任务管理 API — 6 个接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.core.security import generate_task_id
from app.schemas.common import ok
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest

router = APIRouter()


@router.post("", summary="创建任务", status_code=201)
async def task_create(body: TaskCreateRequest, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"task_id": generate_task_id(), "user_id": body.user_id, "status": "pending"}, "创建成功")


@router.get("/{task_id}", summary="查询任务")
async def task_get(task_id: str, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"task_id": task_id, "status": "pending", "progress": None})


@router.get("", summary="任务列表")
async def task_list(
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    session_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


@router.put("/{task_id}", summary="更新任务")
async def task_update(task_id: str, body: TaskUpdateRequest, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"task_id": task_id, "updated": True}, "更新成功")


@router.get("/{task_id}/progress", summary="任务进展摘要")
async def task_progress(task_id: str, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"task_id": task_id, "status": "pending", "completed_count": 0, "pending_count": 0})


@router.post("/{task_id}/complete", summary="完成任务")
async def task_complete(task_id: str, db: AsyncSession = Depends(get_db), _agent: str = Depends(get_current_agent)):
    return ok({"task_id": task_id, "status": "completed"}, "任务已完成")
