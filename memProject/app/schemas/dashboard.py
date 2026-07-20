# -*- coding: utf-8 -*-
"""
Dashboard 聚合接口 — 响应 Schema。

对齐前端协作文档 `系统总览Dashboard接口协作文档.docx`。
"""
import datetime
from datetime import datetime as _datetime

from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    """总览指标卡 — 当前快照值"""
    agent_count: int = Field(default=0, description="当前可用智能体总数")
    scene_count: int = Field(default=0, description="当前可用业务场景总数")
    memory_count: int = Field(default=0, description="有效记忆总数")
    retrieval_count: int = Field(default=0, description="统计窗口内检索请求数")
    context_success_rate: float | None = Field(default=None, description="上下文接口成功率（窗口内），分母为 0 时返回 null")


class DashboardComparison(BaseModel):
    """环比变化率（当前窗口 vs 上一等长窗口）"""
    agent_count_rate: float | None = Field(default=None, description="智能体数量变化率")
    scene_count_rate: float | None = Field(default=None, description="场景数量变化率")
    memory_count_rate: float | None = Field(default=None, description="记忆数量变化率")
    retrieval_count_rate: float | None = Field(default=None, description="检索请求数变化率")
    context_success_rate_change: float | None = Field(default=None, description="成功率差值（非增长率）")


class TrendItem(BaseModel):
    """按日趋势项"""
    date: datetime.date = Field(..., description="业务日期 (Asia/Shanghai)")
    total: int = Field(default=0, description="日末有效记忆总量（需 deleted_at 支持，当前返回 0）")
    added: int = Field(default=0, description="当日新增记忆数")


class TypeDistributionItem(BaseModel):
    """记忆类型分布项"""
    memory_type: str = Field(..., description="记忆类型")
    count: int = Field(default=0, ge=0, description="该类型有效记忆数")
    ratio: float = Field(default=0.0, ge=0, le=1, description="占比")


class RetrievalSignalItem(BaseModel):
    """检索信号分布项"""
    signal: str = Field(..., description="检索模式 (vector_hybrid / db_fallback)")
    count: int = Field(default=0, ge=0, description="该模式的请求数")
    ratio: float = Field(default=0.0, ge=0, le=1, description="占比")


class RecentAgentItem(BaseModel):
    """近期活跃智能体"""
    agent_id: str = Field(..., description="智能体标识")
    scene_id: str | None = Field(None)
    scene_name: str | None = Field(None)
    status: str = Field(default="unknown")
    last_write_at: str | None = Field(None, description="最近写入时间 (ISO 8601)")
    latest_result: str | None = Field(None, description="最近写入结果，无可信来源时返回 null")


class RecentRetrievalItem(BaseModel):
    """近期检索记录"""
    retrieval_id: str = Field(..., description="检索请求 ID")
    memory_type: str | None = Field(None)
    summary: str = Field(default="", description="脱敏并截断的检索摘要，最长 120 字")
    relevance_score: float | None = Field(None)
    occurred_at: str | None = Field(None)


class RecentAlertItem(BaseModel):
    """近期告警"""
    message: str = Field(..., description="告警信息（已脱敏）")
    error_code: str | None = Field(None)
    trace_id: str | None = Field(None)
    occurred_at: str | None = Field(None)


class RecentTaskItem(BaseModel):
    """近期任务"""
    task_id: str = Field(..., description="任务标识")
    title: str | None = Field(None)
    status: str = Field(default="pending")
    updated_at: str | None = Field(None)


class DashboardData(BaseModel):
    """Dashboard 聚合响应"""
    summary: DashboardSummary = Field(default_factory=DashboardSummary)
    comparison: DashboardComparison = Field(default_factory=DashboardComparison)
    memory_trend: list[TrendItem] = Field(default_factory=list)
    memory_type_distribution: list[TypeDistributionItem] = Field(default_factory=list)
    generation_summary: "GenerationSummary" = Field(default_factory="GenerationSummary")
    retrieval_signal_distribution: list[RetrievalSignalItem] = Field(default_factory=list)
    recent_agents: list[RecentAgentItem] = Field(default_factory=list)
    recent_retrievals: list[RecentRetrievalItem] = Field(default_factory=list)
    recent_alerts: list[RecentAlertItem] = Field(default_factory=list)
    recent_tasks: list[RecentTaskItem] = Field(default_factory=list)
    generated_at: _datetime = Field(..., description="统计快照时间 (UTC, ISO 8601)")


class GenerationSummary(BaseModel):
    """生成与去重摘要 — 统计窗口内所有去重操作"""
    generated_count: int = Field(default=0, description="新增记忆数 (keep_new)")
    merged_count: int = Field(default=0, description="融合数 (merge)")
    updated_count: int = Field(default=0, description="更新数 (update_existing)")
    discarded_count: int = Field(default=0, description="丢弃数 (discard)")
    conflict_count: int = Field(default=0, description="冲突数 (conflict)")
