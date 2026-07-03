# -*- coding: utf-8 -*-
"""
任务相关 Schema。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    """任务创建请求"""
    user_id: str = Field(..., description="所属用户标识")
    agent_id: Optional[str] = Field(None)
    scene_id: Optional[str] = Field(None)
    session_id: Optional[str] = Field(None)
    title: Optional[str] = Field(None, max_length=512, description="任务标题")
    goal: Optional[str] = Field(None, description="任务目标")
    extra_meta: Optional[dict[str, Any]] = Field(None)


class TaskUpdateRequest(BaseModel):
    """任务更新请求"""
    title: Optional[str] = Field(None, max_length=512)
    goal: Optional[str] = Field(None)
    status: Optional[str] = Field(None, description="pending / in_progress / completed / cancelled")
    progress: Optional[str] = Field(None, description="当前进展描述")
    completed_items: Optional[list[str]] = Field(None, description="已完成事项")
    pending_items: Optional[list[str]] = Field(None, description="待处理事项")
    extra_meta: Optional[dict[str, Any]] = Field(None)


class TaskInfo(BaseModel):
    """任务信息"""
    task_id: str
    user_id: str
    agent_id: Optional[str] = None
    scene_id: Optional[str] = None
    session_id: Optional[str] = None
    title: Optional[str] = None
    goal: Optional[str] = None
    status: str = "pending"
    progress: Optional[str] = None
    completed_items: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class TaskListResponse(BaseModel):
    """任务列表"""
    items: list[TaskInfo]
    total: int


class TaskProgressResponse(BaseModel):
    """任务进展摘要"""
    task_id: str
    status: str
    progress: Optional[str] = None
    completed_count: int = 0
    pending_count: int = 0
    related_memory_count: int = Field(default=0, description="关联的记忆数")
    last_activity: Optional[datetime] = None
