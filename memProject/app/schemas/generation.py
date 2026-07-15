# -*- coding: utf-8 -*-
"""
记忆生成与去重融合 — Pydantic 请求/响应模型。
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

EXTRACTION_VALID_TYPES = {"key_fact", "task_state", "decision", "preference", "process", "feedback"}


# ============================================================
# 请求
# ============================================================

class GenerationRequest(BaseModel):
    """同步记忆生成请求"""
    text: str = Field(
        ..., min_length=1, max_length=10000,
        description="输入文本（对话记录、任务描述等）"
    )
    user_id: str = Field(..., description="用户唯一标识")
    agent_id: Optional[str] = Field(None, description="智能体标识")
    scene_id: Optional[str] = Field(None, description="场景标识")
    session_id: Optional[str] = Field(None, description="会话标识")
    task_id: Optional[str] = Field(None, description="任务标识")
    extraction_types: list[str] = Field(
        default=["key_fact", "task_state", "decision", "preference", "process", "feedback"],
        description="抽取类型: key_fact, task_state, decision, preference, process, feedback"
    )
    source_record_ids: Optional[list[str]] = Field(None, description="来源记录 ID")
    metadata: Optional[dict] = Field(None, description="业务元数据")

    @field_validator("extraction_types")
    @classmethod
    def validate_extraction_types(cls, v: list[str]) -> list[str]:
        invalid = [t for t in v if t not in EXTRACTION_VALID_TYPES]
        if invalid:
            raise ValueError(
                f"无效的抽取类型: {invalid}，有效类型: {EXTRACTION_VALID_TYPES}"
            )
        return v


class BatchGenerationRequest(BaseModel):
    """批量记忆生成请求"""
    texts: list[str] = Field(
        ..., min_length=1, max_length=50,
        description="输入文本列表"
    )
    user_id: str = Field(..., description="用户唯一标识")
    agent_id: Optional[str] = Field(None)
    scene_id: Optional[str] = Field(None)
    session_id: Optional[str] = Field(None)
    task_id: Optional[str] = Field(None)
    extraction_types: list[str] = Field(
        default=["key_fact", "task_state", "decision"]
    )

    @field_validator("extraction_types")
    @classmethod
    def validate_extraction_types(cls, v: list[str]) -> list[str]:
        invalid = [t for t in v if t not in EXTRACTION_VALID_TYPES]
        if invalid:
            raise ValueError(
                f"无效的抽取类型: {invalid}，有效类型: {EXTRACTION_VALID_TYPES}"
            )
        return v


# ============================================================
# 响应
# ============================================================

class MemoryGenerationDetail(BaseModel):
    """单条记忆生成详情"""
    action: str = Field(..., description="处理动作: keep_new/merge/discard/update_existing/conflict")
    memory_id: Optional[str] = Field(None, description="记忆 ID")
    content_preview: str = Field("", description="记忆内容预览（前 100 字）")
    memory_type: str = Field("fact", description="记忆类型")
    importance: float = Field(0.5, description="重要性评分")
    confidence: float = Field(0.5, description="置信度评分")
    message: str = Field("", description="处理说明")


class GenerationResponse(BaseModel):
    """同步生成响应"""
    memory_ids: list[str] = Field(default_factory=list, description="生成的记忆 ID 列表")
    new_count: int = Field(0, description="新增数量")
    merged_count: int = Field(0, description="合并数量")
    discarded_count: int = Field(0, description="丢弃数量")
    updated_count: int = Field(0, description="更新数量")
    conflict_count: int = Field(0, description="冲突数量")
    details: list[MemoryGenerationDetail] = Field(default_factory=list, description="详情列表")
    new_count: int = Field(default=0, description="新创建数量")
    merged_count: int = Field(default=0, description="合并数量")
    discarded_count: int = Field(default=0, description="丢弃（重复）数量")
    updated_count: int = Field(default=0, description="更新已有数量")
    details: list[MemoryGenerationDetail] = Field(default_factory=list, description="处理详情")


class BatchGenerationResponse(BaseModel):
    """批量生成响应"""
    results: list[GenerationResponse] = Field(default_factory=list, description="每条文本的结果")
    total_memories: int = Field(default=0, description="总记忆数")
    total_new: int = Field(default=0)
    total_merged: int = Field(default=0)
    total_discarded: int = Field(default=0)


class AsyncGenerationResponse(BaseModel):
    """异步生成响应"""
    request_id: str = Field(..., description="异步请求 ID")
    status: str = Field(default="accepted", description="状态")
    message: str = Field(default="异步记忆生成已提交", description="说明")


class GenerationStatusResponse(BaseModel):
    """异步生成状态查询响应"""
    request_id: str = Field(..., description="请求 ID")
    status: str = Field(default="pending", description="pending/processing/completed/failed")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="进度 0.0-1.0")
    result: Optional[GenerationResponse] = Field(None, description="完成后的结果")
    error: Optional[str] = Field(None, description="失败时的错误信息")
