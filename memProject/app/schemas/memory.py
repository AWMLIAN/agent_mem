# -*- coding: utf-8 -*-
"""
记忆相关 Schema — 写入/检索/上下文/更新/删除。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 写入
# ============================================================

class MessageItem(BaseModel):
    """对话消息"""
    role: str = Field(..., description="角色: user / assistant / system / tool")
    content: str = Field(..., description="消息内容")
    turn_index: Optional[int] = Field(None, description="对话轮次")


class MemoryWriteRequest(BaseModel):
    """同步写入请求"""
    user_id: str = Field(..., description="用户唯一标识")
    agent_id: Optional[str] = Field(None, description="智能体唯一标识")
    scene_id: Optional[str] = Field(None, description="场景标识")
    session_id: Optional[str] = Field(None, description="会话标识")
    task_id: Optional[str] = Field(None, description="任务标识")
    messages: list[MessageItem] = Field(..., min_length=1, description="对话消息列表")
    metadata: Optional[dict[str, Any]] = Field(None, description="业务元数据")


class MemoryWriteResponse(BaseModel):
    """写入响应"""
    memory_ids: list[str] = Field(default_factory=list, description="生成的记忆 ID 列表")
    count: int = Field(default=0, description="写入数量")


class AsyncWriteResponse(BaseModel):
    """异步写入响应"""
    request_id: str = Field(..., description="异步请求 ID，用于回调/轮询")
    status: str = Field(default="accepted", description="状态: accepted")
    message: str = Field(default="异步写入已提交，处理完成后通过回调通知")


# ============================================================
# 检索
# ============================================================

class MemorySearchRequest(BaseModel):
    """混合检索请求"""
    query: str = Field(..., description="检索查询文本")
    user_id: str = Field(..., description="用户标识")
    agent_id: Optional[str] = Field(None)
    scene_id: Optional[str] = Field(None)
    session_id: Optional[str] = Field(None)
    task_id: Optional[str] = Field(None)
    memory_types: Optional[list[str]] = Field(None, description="筛选记忆类型: preference/fact/task/process/feedback/constraint/decision")
    top_k: int = Field(default=10, ge=1, le=50, description="返回 Top-K 条数")
    time_start: Optional[datetime] = Field(None, description="时间范围-起始")
    time_end: Optional[datetime] = Field(None, description="时间范围-结束")
    include_inactive: bool = Field(default=False, description="是否包含失效记忆")
    include_scores: bool = Field(default=True, description="是否返回评分明细")
    rerank: bool = Field(default=False, description="是否启用 Reranker 二次排序（增加 150-200ms 延迟）")


class MemoryItem(BaseModel):
    """检索结果中的单条记忆"""
    memory_id: str
    content: str
    summary: Optional[str] = None
    memory_type: str
    status: str
    relevance_score: Optional[float] = None
    importance: float = 0.5
    confidence: float = 0.5
    tags: list[str] = Field(default_factory=list)
    source_type: str = "extracted"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MemorySearchResponse(BaseModel):
    """检索响应"""
    query: str
    results: list[MemoryItem] = Field(default_factory=list)
    total_candidates: int = Field(default=0, description="融合前的候选数量")
    elapsed_ms: Optional[int] = Field(None, description="检索耗时(ms)")


# ============================================================
# 上下文返回
# ============================================================

class ContextRequest(BaseModel):
    """上下文返回请求"""
    query: str = Field(..., description="当前用户问题")
    user_id: str = Field(..., description="用户标识")
    agent_id: Optional[str] = Field(None)
    scene_id: Optional[str] = Field(None)
    session_id: Optional[str] = Field(None)
    task_id: Optional[str] = Field(None)
    max_tokens: int = Field(default=3000, description="最大文本长度(token近似)")
    group_by_type: bool = Field(default=True, description="是否按记忆类型分组")
    include_preferences: bool = Field(default=True)
    include_facts: bool = Field(default=True)
    include_task_state: bool = Field(default=True)


class ContextFragment(BaseModel):
    """一段上下文片段"""
    memory_type: str
    content: str
    memory_ids: list[str] = Field(default_factory=list)


class ContextResponse(BaseModel):
    """上下文响应"""
    fragments: list[ContextFragment] = Field(default_factory=list)
    formatted_text: str = Field(default="", description="可直接注入 Prompt 的格式化文本")
    memory_count: int = Field(default=0)
    estimated_tokens: int = Field(default=0)


# ============================================================
# 更新 / 删除
# ============================================================

class MemoryUpdateRequest(BaseModel):
    """更新记忆请求"""
    memory_id: str = Field(..., description="记忆唯一标识")
    content: Optional[str] = Field(None, description="更新后的记忆内容")
    summary: Optional[str] = Field(None)
    status: Optional[str] = Field(None, description="状态: active/inactive/pending_update/conflict/deleted")
    importance: Optional[float] = Field(None, ge=0, le=1)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    tags: Optional[list[str]] = Field(None)


class MemoryUpdateResponse(BaseModel):
    """更新响应"""
    memory_id: str
    updated: bool = True
    version: int = 1


class MemoryDeleteRequest(BaseModel):
    """删除记忆请求（软删除）"""
    memory_id: str = Field(..., description="记忆唯一标识")
    reason: Optional[str] = Field(None, description="删除原因")


class MemoryDeleteResponse(BaseModel):
    """删除响应"""
    memory_id: str
    deleted: bool = True
    previous_status: str
