# -*- coding: utf-8 -*-
"""
记忆核心 API — 写入/检索/管理。
写入：鉴权→校验→标准化→T_INTERACTION_RECORD + mem0 抽取
检索：多信号融合（mem0 语义+BM25+实体+元数据过滤）
"""

import time as time_module
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_agent, get_current_user_id, get_current_scene_id,
    get_current_session_id, get_current_task_id,
)
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.core.logger import get_logger
from app.mcp_client import mcp_client
from app.models.base import InteractionRecord
from app.schemas.common import ok
from app.schemas.memory import (
    MemoryWriteRequest, MemoryWriteResponse,
    AsyncWriteRequest, AsyncWriteResponse,
    MemorySearchRequest,
    ContextRequest, MemoryUpdateRequest, MemoryDeleteRequest,
)
from app.services.validation_service import validate_and_standardize
from app.services.memory_service import (
    get_memory_by_id,
    update_memory_fields,
    soft_delete_memory,
    build_context_query,
    get_stats,
    get_memory_relations,
)

logger = get_logger("memory_api")
router = APIRouter()


# ============================================================
# 同步写入（Phase 1 写入管线 + mem0 抽取）
# ============================================================

@router.post("/write", summary="同步写入交互记录", status_code=200)
async def memory_write(
    request: Request,
    body: MemoryWriteRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
    user_id: str = Depends(get_current_user_id),
    scene_id: str | None = Depends(get_current_scene_id),
    session_id: str | None = Depends(get_current_session_id),
):
    start = time_module.perf_counter()

    effective_user_id = user_id or body.user_id
    effective_session_id = session_id or body.session_id
    effective_agent_id = agent_id or body.agent_id
    effective_scene_id = scene_id or body.scene_id

    raw_data = {
        "user_id": effective_user_id,
        "session_id": effective_session_id,
        "task_id": body.task_id,
        "timestamp": body.timestamp,
        "interaction_type": body.interaction_type,
        "role": body.role,
        "content": body.get_content_text(),
        "business_meta": body.business_meta or body.metadata,
    }

    validated = validate_and_standardize(
        raw_data, agent_id=effective_agent_id, scene_id=effective_scene_id,
    )

    record = InteractionRecord(
        record_id=validated["record_id"],
        user_id=validated["user_id"],
        agent_id=effective_agent_id,
        scene_id=effective_scene_id,
        session_id=validated["session_id"],
        task_id=validated.get("task_id"),
        role=body.get_role(),
        content=validated["content"],
        content_type="text",
        processed=False,
        recorded_at=validated["timestamp_dt"],
        extra_meta=validated["business_meta"],
    )

    db.add(record)
    await db.commit()

    # 同时通过 mem0 做记忆抽取（fire-and-forget，不阻塞返回）
    try:
        from app.services.mem0_client import mem0_client as mc
        meta = {}
        if effective_scene_id: meta["scene_id"] = effective_scene_id
        if effective_session_id: meta["session_id"] = effective_session_id
        if body.task_id: meta["task_id"] = body.task_id
        mc.add(
            [{"role": "system", "content": "请用中文提取和记录所有记忆内容。"},
             {"role": "user", "content": validated["content"]}],
            user_id=effective_user_id,
            metadata=meta or None,
        )
    except Exception as e:
        logger.warning(f"mem0 抽取失败（不影响写入）: {e}")

    elapsed = round((time_module.perf_counter() - start) * 1000, 2)
    logger.info(f"写入完成: record_id={validated['record_id']}, elapsed={elapsed}ms")

    return ok(MemoryWriteResponse(
        record_id=validated["record_id"],
        status="pending_extract",
        message=f"已写入 (耗时 {elapsed}ms)",
    ).model_dump())


# ============================================================
# 异步写入
# ============================================================

@router.post("/async_write", summary="异步写入（高并发场景）", status_code=202)
async def memory_async_write(
    body: AsyncWriteRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
    user_id: str = Depends(get_current_user_id),
):
    effective_user_id = user_id or body.user_id
    request_id = f"async_{uuid4().hex[:24]}"

    raw_data = {
        "user_id": effective_user_id,
        "session_id": body.session_id,
        "task_id": body.task_id,
        "timestamp": body.timestamp,
        "interaction_type": body.interaction_type,
        "role": body.role,
        "content": body.content,
        "business_meta": body.business_meta,
    }

    validated = validate_and_standardize(raw_data, agent_id=agent_id, scene_id=None)
    mq_delivered = await _try_deliver_to_mq(request_id, validated)

    if mq_delivered:
        return ok(AsyncWriteResponse(
            request_id=request_id, status="accepted",
            message="异步写入已提交",
        ).model_dump(), message="已接受")
    else:
        from app.core.database import async_session_factory
        record = InteractionRecord(
            record_id=validated["record_id"], user_id=validated["user_id"],
            agent_id=agent_id, session_id=validated["session_id"],
            task_id=validated.get("task_id"),
            role=body.role.value if hasattr(body.role, "value") else str(body.role),
            content=validated["content"], processed=False,
            recorded_at=validated["timestamp_dt"], extra_meta=validated["business_meta"],
        )
        async with async_session_factory() as session:
            session.add(record)
            await session.commit()
        return ok({"request_id": request_id, "record_id": validated["record_id"],
                   "status": "stored", "fallback": True, "message": "MQ 不可用，已降级同步写入"})


async def _try_deliver_to_mq(request_id: str, data: dict) -> bool:
    return False  # 占位，MQ 后续实现


# ============================================================
# 多信号融合检索（Phase 4）
# ============================================================

@router.post("/search", summary="多信号融合检索（语义+BM25+实体+元数据过滤）")
async def memory_search(
    body: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    from app.services.retrieval_service import search as retrieval_search
    result = retrieval_search(
        query=body.query, user_id=body.user_id, agent_id=body.agent_id,
        scene_id=body.scene_id, session_id=body.session_id, task_id=body.task_id,
        memory_types=body.memory_types,
        time_start=body.time_start.isoformat() if body.time_start else None,
        time_end=body.time_end.isoformat() if body.time_end else None,
        top_k=body.top_k, include_inactive=body.include_inactive,
        include_scores=body.include_scores, rerank=body.rerank,
    )
    return ok(result)


# ============================================================
# 其他记忆接口
# ============================================================

@router.post("/context", summary="Prompt 上下文片段")
async def memory_context(
    body: ContextRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    filters = {
        "user_id": body.user_id,
        "agent_id": body.agent_id,
        "scene_id": body.scene_id,
        "session_id": body.session_id,
        "task_id": body.task_id,
        "include_map": {
            "preferences": body.include_preferences,
            "facts": body.include_facts,
            "task_state": body.include_task_state,
        },
    }
    memories = await build_context_query(db, filters)
    fragments = []
    for m in memories:
        fragments.append({
            "memory_type": m.memory_type,
            "content": m.content,
            "memory_ids": [m.memory_id],
        })
    formatted = "\n\n".join(f"[{m.memory_type}] {m.content}" for m in memories)
    return ok({
        "fragments": fragments,
        "formatted_text": formatted,
        "memory_count": len(memories),
        "estimated_tokens": len(formatted) // 2,
    })

@router.put("/update", summary="更新记忆")
async def memory_update(
    body: MemoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    updates = {k: v for k, v in body.model_dump(exclude={"memory_id"}, exclude_none=True).items() if v is not None}
    memory = await update_memory_fields(db, body.memory_id, updates)
    return ok({"memory_id": memory.memory_id, "updated": True, "version": memory.version})

@router.delete("/delete", summary="删除记忆（软删除）")
async def memory_delete(
    body: MemoryDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    memory_id, previous_status = await soft_delete_memory(db, body.memory_id)
    return ok({"memory_id": memory_id, "deleted": True, "previous_status": previous_status})


@router.get("/stats", summary="记忆统计")
async def memory_stats(
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    stats = await get_stats(db)
    return ok(stats)


@router.get("/{memory_id}", summary="查询单条记忆")
async def memory_get(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    memory = await get_memory_by_id(db, memory_id)
    if not memory:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"记忆 {memory_id} 不存在")
    return ok({
        "memory_id": memory.memory_id,
        "content": memory.content,
        "summary": memory.summary,
        "key_points": memory.key_points,
        "memory_type": memory.memory_type,
        "status": memory.status,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "tags": memory.tags,
        "user_id": memory.user_id,
        "agent_id": memory.agent_id,
        "scene_id": memory.scene_id,
        "session_id": memory.session_id,
        "task_id": memory.task_id,
        "version": memory.version,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    })


@router.get("/{memory_id}/relations", summary="查询记忆关系")
async def memory_relations(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    relations = await get_memory_relations(db, memory_id)
    return ok({"memory_id": memory_id, "relations": relations})

@router.post("/list", summary="列出全部记忆")
async def memory_list(user_id: str = Query(...)):
    result = await mcp_client.list_memories(user_id=user_id)
    return ok(result)

@router.post("/delete-all", summary="清除全部记忆")
async def memory_delete_all(user_id: str = Query(...)):
    result = await mcp_client.delete_all_memories(user_id=user_id)
    return ok(result)
