# -*- coding: utf-8 -*-
"""
记忆相关 Schema — 写入/检索/上下文/更新/删除。
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================
# 枚举定义
# ============================================================

class InteractionType(str, Enum):
    """交互类型枚举 — 对齐设计文档"""
    DIALOGUE = "dialogue"        # 对话记录
    SESSION = "session"          # 历史会话摘要
    TASK_PROCESS = "task_process"  # 任务过程


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    TOOL = "tool"


# ============================================================
# 写入 — 对齐设计文档《核心业务逻辑拆解》
# ============================================================

class MessageItem(BaseModel):
    """对话消息（批量messages格式，保留兼容MCP路径）"""
    role: str = Field(..., description="角色: user / assistant / system / tool")
    content: str = Field(..., description="消息内容")
    turn_index: Optional[int] = Field(None, description="对话轮次")


class MemoryWriteRequest(BaseModel):
    """
    同步写入请求 — 单条交互记录格式（对齐设计文档三.1节）。

    支持两种模式：
    1. 文档标准模式：使用 interaction_type + role + content
    2. 兼容MCP模式：使用 messages 数组
    """
    user_id: str = Field(..., min_length=1, max_length=128, description="用户唯一标识")
    session_id: str = Field(..., min_length=1, max_length=128, description="会话唯一标识")
    task_id: Optional[str] = Field(None, max_length=128, description="任务唯一标识")
    timestamp: Optional[datetime] = Field(None, description="交互发生时间（ISO 8601），默认服务端时间")

    # 单条模式（文档标准）
    interaction_type: Optional[InteractionType] = Field(None, description="交互类型: dialogue/session/task_process")
    role: Optional[MessageRole] = Field(None, description="角色: user/agent")
    content: Optional[str] = Field(None, max_length=50000, description="交互内容文本")
    business_meta: Optional[dict[str, Any]] = Field(None, description="业务元数据（如project_name, doc_type等）")

    # 批量模式（兼容MCP）
    messages: Optional[list[MessageItem]] = Field(None, description="对话消息列表（批量模式）")
    metadata: Optional[dict[str, Any]] = Field(None, description="业务元数据（批量模式的别名）")

    # Header中获取的字段（由中间件注入后填充）
    agent_id: Optional[str] = Field(None, description="智能体标识（由Header注入）")
    scene_id: Optional[str] = Field(None, description="场景标识（由Header注入）")

    @field_validator("user_id", "session_id")
    @classmethod
    def strip_and_normalize(cls, v: str) -> str:
        """去除前后空格，统一小写（ID标准化）"""
        if v:
            return v.strip().lower()
        return v

    @field_validator("task_id")
    @classmethod
    def normalize_optional_id(cls, v: Optional[str]) -> Optional[str]:
        """可选的ID字段标准化"""
        if v:
            return v.strip().lower()
        return v

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: Optional[str]) -> Optional[str]:
        """去除内容前后空白"""
        if v:
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_content_mode(self) -> "MemoryWriteRequest":
        """确保至少提供 content 或 messages 之一"""
        has_single = self.content is not None and self.role is not None
        has_batch = self.messages is not None and len(self.messages) > 0

        if not has_single and not has_batch:
            raise ValueError(
                "必须提供 (role + content) 或 messages 字段之一。"
                "标准模式: role='user', content='...'; "
                "批量模式: messages=[{role:'user', content:'...'}]"
            )

        # 如果提供了单条模式但缺少 interaction_type，设置默认值
        if has_single and self.interaction_type is None:
            self.interaction_type = InteractionType.DIALOGUE

        return self

    def get_content_text(self) -> str:
        """提取核心内容文本（兼容两种模式）"""
        if self.content:
            return self.content
        if self.messages:
            return " ".join(m.content for m in self.messages)
        return ""

    def get_role(self) -> str:
        """获取角色"""
        if self.role:
            return self.role.value
        if self.messages and len(self.messages) > 0:
            return self.messages[-1].role
        return "unknown"


class MemoryWriteResponse(BaseModel):
    """写入响应"""
    record_id: str = Field(..., description="写入的交互记录 ID")
    status: str = Field(default="stored", description="状态: stored / pending_extract")
    message: str = Field(default="数据已接收并写入原始记录表")


class AsyncWriteRequest(BaseModel):
    """异步写入请求 — 高并发场景"""
    user_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    task_id: Optional[str] = Field(None, max_length=128)
    timestamp: Optional[datetime] = Field(None)
    interaction_type: InteractionType = Field(default=InteractionType.DIALOGUE)
    role: MessageRole = Field(..., description="角色")
    content: str = Field(..., max_length=50000)
    business_meta: Optional[dict[str, Any]] = Field(None)

    @field_validator("user_id", "session_id")
    @classmethod
    def strip_and_normalize(cls, v: str) -> str:
        return v.strip().lower() if v else v


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
