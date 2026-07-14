# -*- coding: utf-8 -*-
"""
数据库物理模型 — PostgreSQL 12 张表。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean,
    DateTime, BigInteger, JSON, Index,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> str:
    return uuid.uuid4().hex


# ============================================================
# 1. T_USER
# ============================================================
class User(Base):
    __tablename__ = "t_user"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    user_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=True)
    extra_meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ============================================================
# 2. T_AGENT
# ============================================================
class Agent(Base):
    __tablename__ = "t_agent"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    agent_id = Column(String(128), unique=True, nullable=False, index=True)
    agent_name = Column(String(256))
    scene_id = Column(String(128), nullable=True, index=True)
    api_key_hash = Column(String(256))
    api_key_prefix = Column(String(16))
    is_active = Column(Boolean, default=True)
    permissions = Column(JSON, default=list)
    extra_meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ============================================================
# 3. T_SCENE
# ============================================================
class Scene(Base):
    __tablename__ = "t_scene"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    scene_id = Column(String(128), unique=True, nullable=False, index=True)
    scene_name = Column(String(256))
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    extra_meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ============================================================
# 4. T_SESSION
# ============================================================
class Session(Base):
    __tablename__ = "t_session"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    session_id = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    scene_id = Column(String(128), nullable=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), default="active")
    started_at = Column(DateTime(timezone=True), default=_now)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, default=0)
    extra_meta = Column(JSON, default=dict)


# ============================================================
# 5. T_TASK
# ============================================================
class Task(Base):
    __tablename__ = "t_task"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    task_id = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    scene_id = Column(String(128), nullable=True, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    title = Column(String(512))
    goal = Column(Text)
    status = Column(String(32), default="pending")
    progress = Column(Text)
    completed_items = Column(JSON, default=list)
    pending_items = Column(JSON, default=list)
    started_at = Column(DateTime(timezone=True), default=_now)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    extra_meta = Column(JSON, default=dict)


# ============================================================
# 6. T_INTERACTION_RECORD
# ============================================================
class InteractionRecord(Base):
    __tablename__ = "t_interaction_record"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    record_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    scene_id = Column(String(128), nullable=True, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    interaction_type = Column(String(32), default="dialogue", index=True)
    turn_index = Column(Integer, default=0)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(32), default="text")
    processed = Column(Boolean, default=False)
    status = Column(String(32), default="pending_extract", index=True,
                    comment="记录状态: pending_extract / processed / failed")
    recorded_at = Column(DateTime(timezone=True), default=_now)
    extra_meta = Column(JSON, default=dict)

    __table_args__ = (
        Index("idx_interaction_session_turn", "session_id", "turn_index"),
        Index("idx_interaction_processed", "processed", "recorded_at"),
        Index("idx_interaction_user_time", "user_id", "recorded_at"),
        Index("idx_interaction_type_user", "interaction_type", "user_id"),
        Index("idx_interaction_user_session_time", "user_id", "session_id", "recorded_at"),
        Index("idx_interaction_status", "status", "recorded_at"),
    )


# ============================================================
# 7. T_MEMORY
# ============================================================
class Memory(Base):
    __tablename__ = "t_memory"

    id = Column(String(32), primary_key=True, default=_gen_uuid)
    memory_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    scene_id = Column(String(128), nullable=True, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)

    content = Column(Text, nullable=False)
    summary = Column(Text)
    key_points = Column(JSON, default=list)

    memory_type = Column(String(64), nullable=False, index=True)
    tags = Column(JSON, default=list)
    entities = Column(JSON, default=list)

    status = Column(String(32), default="active", index=True)
    version = Column(Integer, default=1)
    replaced_by = Column(String(64), nullable=True)

    importance = Column(Float, default=0.5)
    confidence = Column(Float, default=0.5)
    use_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    decay_factor = Column(Float, default=1.0)

    source_type = Column(String(32), default="extracted")
    source_record_ids = Column(JSON, default=list)

    vector_id = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("idx_memory_user_type_status", "user_id", "memory_type", "status"),
        Index("idx_memory_task", "task_id", "status"),
        Index("idx_memory_session", "session_id", "status"),
        Index("idx_memory_status_time", "status", "created_at"),
    )


# ============================================================
# 8. T_MEMORY_VECTOR
# ============================================================
class MemoryVector(Base):
    __tablename__ = "t_memory_vector"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    memory_id = Column(String(64), nullable=False, index=True)
    vector_store_id = Column(String(128), unique=True, nullable=False)
    dimension = Column(Integer, default=1024)
    model_name = Column(String(128))
    created_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("idx_memory_vector_memory", "memory_id"),
    )


# ============================================================
# 9. T_MEMORY_RELATION
# ============================================================
class MemoryRelation(Base):
    __tablename__ = "t_memory_relation"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_memory_id = Column(String(64), nullable=False, index=True)
    target_memory_id = Column(String(64), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False)
    description = Column(Text)
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("idx_mem_rel_source", "source_memory_id", "relation_type"),
        Index("idx_mem_rel_target", "target_memory_id", "relation_type"),
    )


# ============================================================
# 10. T_RETRIEVAL_REQUEST
# ============================================================
class RetrievalRequest(Base):
    __tablename__ = "t_retrieval_request"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    scene_id = Column(String(128), nullable=True, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    query_text = Column(Text)
    filter_conditions = Column(JSON)
    top_k = Column(Integer, default=10)
    is_triggered = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)


# ============================================================
# 11. T_RETRIEVAL_RESULT
# ============================================================
class RetrievalResult(Base):
    __tablename__ = "t_retrieval_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(64), nullable=False, index=True)
    memory_id = Column(String(64), nullable=False, index=True)
    rank = Column(Integer)
    relevance_score = Column(Float)
    semantic_score = Column(Float, nullable=True)
    keyword_score = Column(Float, nullable=True)
    recency_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("idx_result_request", "request_id", "rank"),
    )


# ============================================================
# 12. T_API_LOG
# ============================================================
class ApiLog(Base):
    __tablename__ = "t_api_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    log_id = Column(String(64), unique=True, nullable=False, index=True)
    trace_id = Column(String(64), index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    api_path = Column(String(256))
    method = Column(String(16))
    request_params = Column(JSON)
    response_code = Column(Integer)
    error_code = Column(String(64), nullable=True)
    elapsed_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (
        Index("idx_api_log_time", "created_at"),
        Index("idx_api_log_agent_path", "agent_id", "api_path"),
    )
