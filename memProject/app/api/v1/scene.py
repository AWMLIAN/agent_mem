# -*- coding: utf-8 -*-
"""场景管理 API — 5 个接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.core.database import get_db
from app.core.security import generate_scene_id
from app.schemas.common import ok
from app.schemas.scene import SceneCreateRequest, SceneUpdateRequest

router = APIRouter()


@router.post("", summary="创建场景", status_code=201)
async def scene_create(body: SceneCreateRequest, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"scene_id": generate_scene_id(), "scene_name": body.scene_name}, "创建成功")


@router.get("/{scene_id}", summary="查询场景")
async def scene_get(scene_id: str, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"scene_id": scene_id, "scene_name": "示例场景", "is_active": True})


@router.get("", summary="场景列表")
async def scene_list(
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current: str = Depends(get_current_agent),
):
    return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


@router.put("/{scene_id}", summary="更新场景")
async def scene_update(scene_id: str, body: SceneUpdateRequest, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"scene_id": scene_id, "updated": True}, "更新成功")


@router.delete("/{scene_id}", summary="停用场景")
async def scene_disable(scene_id: str, db: AsyncSession = Depends(get_db), _current: str = Depends(get_current_agent)):
    return ok({"scene_id": scene_id, "is_active": False}, "已停用")
