# -*- coding: utf-8 -*-
"""
记忆相关 Schema — 写入/检索/上下文/更新/删除。

对齐前端对接文档 API 契约：
- 写入请求：messages 数组为 Primary 格式
- 写入响应：results[{id, memory, event}]
- 统一响应：{code, message, data}
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 写入
# ============================================================

class MessageItem(BaseModel):
    """单条对话消息（对齐前端文档 messages 数组元素）"""
    role: str = Field(..., description="角色: user / assistant / system")
    content: str = Field(..., min_length=1, max_length=50000, description="消息内容")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"user", "assistant", "system", "tool", "agent"}
        if v.lower() not in allowed:
            raise ValueError(f"非法 role 值: '{v}'，允许: {', '.join(sorted(allowed))}")
        return v.lower()

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str) -> str:
        return v.strip()


class MemoryWriteRequest(BaseModel):
    """
    同步写入请求 — 对齐前端对接文档 一.1 节。

    messages 数组为 Primary 格式，支持多轮对话批量写入。
    """
    user_id: str = Field(..., min_length=1, max_length=128, description="用户唯一标识")
    scene_id: Optional[str] = Field(None, max_length=128, description="场景标识")
    session_id: Optional[str] = Field(None, max_length=128, description="会话ID")
    task_id: Optional[str] = Field(None, max_length=128, description="任务标识")
    messages: list[MessageItem] = Field(..., min_length=1, max_length=100, description="对话消息数组")
    metadata: Optional[dict[str, Any]] = Field(None, description="扩展元数据")

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("scene_id", "session_id", "task_id")
    @classmethod
    def normalize_optional_id(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip().lower()
        return v

    def get_content_text(self) -> str:
        """将 messages 数组拼接为单个文本（用于 mem0 LLM 抽取）"""
        lines = []
        for i, m in enumerate(self.messages):
            lines.append(f"[{m.role}](轮次{i + 1}): {m.content}")
        return "\n".join(lines)

    def get_last_role(self) -> str:
        """获取最后一条消息的角色"""
        return self.messages[-1].role if self.messages else "user"

    def get_last_content(self) -> str:
        """获取最后一条消息的内容"""
        return self.messages[-1].content if self.messages else ""


# ============================================================
# 写入响应 — 对齐前端文档 results 格式
# ============================================================

class MemoryEvent(str, Enum):
    """记忆事件类型"""
    ADD = "ADD"       # 新增记忆
    SKIP = "SKIP"     # 跳过（无价值信息）
    MERGE = "MERGE"   # 合并到已有记忆


class WriteResultItem(BaseModel):
    """单条写入结果（对齐前端文档 results 数组元素）"""
    id: str = Field(..., description="记忆 ID")
    memory: str = Field(..., description="记忆内容摘要")
    event: MemoryEvent = Field(..., description="事件: ADD / SKIP / MERGE")


class MemoryWriteResponse(BaseModel):
    """写入响应"""
    results: list[WriteResultItem] = Field(default_factory=list, description="每条消息的处理结果")


# ============================================================
# 异步写入
# ============================================================

class AsyncWriteRequest(BaseModel):
    """异步写入请求 — 同 write 格式"""
    user_id: str = Field(..., min_length=1, max_length=128)
    scene_id: Optional[str] = Field(None, max_length=128)
    session_id: Optional[str] = Field(None, max_length=128)
    task_id: Optional[str] = Field(None, max_length=128)
    messages: list[MessageItem] = Field(..., min_length=1, max_length=100)
    metadata: Optional[dict[str, Any]] = Field(None)

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, v: str) -> str:
        return v.strip().lower()


class AsyncWriteResponse(BaseModel):
    """异步写入响应"""
    request_id: str = Field(..., description="异步请求 ID")
    status: str = Field(default="accepted")
    message: str = Field(default="异步写入已提交")


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
    memory_types: Optional[list[str]] = Field(None, description="筛选类型: preference/fact/task/decision/constraint")
    top_k: int = Field(default=10, ge=1, le=50)
    time_start: Optional[datetime] = Field(None)
    time_end: Optional[datetime] = Field(None)
    include_inactive: bool = Field(default=False)
    include_scores: bool = Field(default=True)
    rerank: bool = Field(default=False, description="是否启用二次排序")


class MemoryResultItem(BaseModel):
    """检索结果单条"""
    memory_id: str
    content: str
    summary: Optional[str] = None
    relevance_score: Optional[float] = None
    memory_type: str = "unknown"
    scene_id: Optional[str] = None
    task_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MemorySearchResponse(BaseModel):
    """检索响应"""
    query: str
    results: list[MemoryResultItem] = Field(default_factory=list)
    total_candidates: int = Field(default=0)
    elapsed_ms: Optional[int] = Field(None)


# ============================================================
# 上下文
# ============================================================

class ContextRequest(BaseModel):
    """上下文返回请求"""
    query: str = Field(..., description="当前用户问题")
    user_id: str = Field(..., description="用户标识")
    agent_id: Optional[str] = Field(None)
    scene_id: Optional[str] = Field(None)
    session_id: Optional[str] = Field(None)
    task_id: Optional[str] = Field(None)
    max_tokens: int = Field(default=3000)
    group_by_type: bool = Field(default=True)
    include_preferences: bool = Field(default=True)
    include_facts: bool = Field(default=True)
    include_task_state: bool = Field(default=True)


class ContextFragment(BaseModel):
    """上下文片段"""
    memory_type: str
    content: str
    memory_ids: list[str] = Field(default_factory=list)


class ContextResponse(BaseModel):
    """上下文响应"""
    fragments: list[ContextFragment] = Field(default_factory=list)
    formatted_text: str = Field(default="")
    memory_count: int = Field(default=0)
    estimated_tokens: int = Field(default=0)


# ============================================================
# 更新 / 删除
# ============================================================

class MemoryUpdateRequest(BaseModel):
    """更新记忆请求"""
    memory_id: str = Field(..., description="记忆唯一标识")
    content: Optional[str] = Field(None)
    summary: Optional[str] = Field(None)
    status: Optional[str] = Field(None, description="状态: active/deleted/pending_update/conflict")
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
    reason: Optional[str] = Field(None)


class MemoryDeleteResponse(BaseModel):
    """删除响应"""
    memory_id: str
    deleted: bool = True
    previous_status: str = "active"
