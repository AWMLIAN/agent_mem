# -*- coding: utf-8 -*-
"""
场景相关 Schema。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SceneCreateRequest(BaseModel):
    """场景创建请求"""
    scene_name: str = Field(..., min_length=1, max_length=256, description="场景名称")
    description: Optional[str] = Field(None, description="场景描述")
    extra_meta: Optional[dict[str, Any]] = Field(None, description="扩展元数据")


class SceneUpdateRequest(BaseModel):
    """场景更新请求"""
    scene_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = Field(None)
    is_active: Optional[bool] = Field(None)
    extra_meta: Optional[dict[str, Any]] = Field(None)


class SceneInfo(BaseModel):
    """场景信息"""
    scene_id: str
    scene_name: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SceneListResponse(BaseModel):
    """场景列表"""
    items: list[SceneInfo]
    total: int
