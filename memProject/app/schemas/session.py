# -*- coding: utf-8 -*-
"""
会话相关 Schema。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """会话创建请求"""
    user_id: str = Field(..., description="所属用户标识")
    agent_id: Optional[str] = Field(None, description="所属智能体")
    scene_id: Optional[str] = Field(None, description="所属场景")
    task_id: Optional[str] = Field(None, description="关联任务")
    extra_meta: Optional[dict[str, Any]] = Field(None)


class SessionUpdateRequest(BaseModel):
    """会话更新请求"""
    status: Optional[str] = Field(None, description="active / closed / archived")
    task_id: Optional[str] = Field(None)
    extra_meta: Optional[dict[str, Any]] = Field(None)


class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    user_id: str
    agent_id: Optional[str] = None
    scene_id: Optional[str] = None
    task_id: Optional[str] = None
    status: str = "active"
    message_count: int = 0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class SessionCloseResponse(BaseModel):
    """会话关闭响应"""
    session_id: str
    status: str = "closed"
    message_count: int
    memory_count: int = Field(default=0, description="本次会话产生的记忆数")
    summary: Optional[str] = Field(None, description="自动生成的会话摘要")


class SessionListResponse(BaseModel):
    """会话列表"""
    items: list[SessionInfo]
    total: int
