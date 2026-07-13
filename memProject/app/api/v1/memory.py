# -*- coding: utf-8 -*-
"""
记忆核心 API — 对齐前端对接文档。

所有端点使用 MemoryPipeline（生成+去重）和 MemoryStore（检索/列表/删除）。
替换原来的 MCP 中转 + Mock 提取器方案。

端点:
  POST /write       — 同步写入记忆（extract→generate→dedup→store）
  POST /async_write — 异步写入（即刻返回 request_id）
  POST /search      — 语义检索记忆（Qdrant + PostgreSQL）
  POST /list        — 分页列出记忆
  POST /delete-all  — 清除全部记忆
  POST /context     — 检索并格式化为 Prompt 上下文
  PUT  /update      — 更新单条记忆
  DELETE /delete    — 软删除单条记忆
"""

import time as time_module
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_agent,
    get_current_user_id,
    get_current_scene_id,
    get_current_session_id,
    get_current_task_id,
)
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.core.logger import get_logger
from app.models.base import InteractionRecord
from app.schemas.common import ok
from app.schemas.memory import (
    AsyncWriteRequest,
    AsyncWriteResponse,
    ContextRequest,
    MemoryDeleteRequest,
    MemoryDeleteResponse,
    MemoryEvent,
    MemorySearchRequest,
    MemoryUpdateRequest,
    MemoryUpdateResponse,
    MemoryWriteRequest,
    MemoryWriteResponse,
    WriteResultItem,
)
from app.services.memory_pipeline import memory_pipeline
from app.services.memory_store import memory_store
from app.services.validation_service import validate_id_format, normalize_id

logger = get_logger("memory_api")
router = APIRouter()


# ============================================================
# 同步写入 — 对齐前端对接文档 一.1 节
# ============================================================

@router.post("/write", summary="写入记忆（同步）", status_code=200)
async def memory_write(
    request: Request,
    body: MemoryWriteRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
    user_id_header: str = Depends(get_current_user_id),
    scene_id: str | None = Depends(get_current_scene_id),
):
    """
    同步写入对话记忆 — 使用真实记忆生成流水线。

    处理管线:
    1. 鉴权（开发阶段跳过）
    2. messages → 拼接为对话文本
    3. 逐条写入 t_interaction_record（原始记录）
    4. 调用 MemoryPipeline: extract → generate → dedup → store
    5. 将 PipelineResult 映射为前端 results 格式
    6. 返回 {"code": 0, "data": {"results": [...]}}

    延迟: 约 5-15 秒（取决于 LLM 响应速度）。
    对于延迟敏感的场景，请使用 /async_write。
    """
    start = time_module.perf_counter()

    # 合并 ID 来源（Header > Body）
    effective_user_id = normalize_id(user_id_header or body.user_id)
    effective_scene_id = scene_id or body.scene_id
    effective_session_id = body.session_id or f"sess_{uuid4().hex[:12]}"

    # 业务级校验
    if effective_user_id:
        err = validate_id_format("user_id", effective_user_id)
        if err:
            raise ValidationError(message=err)

    # --- 写入原始交互记录 ---
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    for i, msg in enumerate(body.messages):
        record = InteractionRecord(
            record_id=f"rec_{uuid4().hex[:24]}",
            user_id=effective_user_id,
            agent_id=agent_id,
            scene_id=effective_scene_id,
            session_id=effective_session_id,
            task_id=body.task_id,
            turn_index=i,
            role=msg.role,
            content=msg.content,
            content_type="text",
            processed=False,
            recorded_at=now,
            extra_meta=body.metadata or {},
        )
        db.add(record)

    await db.commit()

    # --- 调用真实记忆生成流水线 ---
    # 将 messages 数组转换为对话文本
    conversation_text = body.get_content_text()

    try:
        pipeline_result = await memory_pipeline.run(
            text=conversation_text,
            user_id=effective_user_id,
            agent_id=agent_id,
            scene_id=effective_scene_id,
            session_id=effective_session_id,
            task_id=body.task_id,
            source_record_ids=None,
            extraction_types=["key_fact", "task_state", "decision"],
            task_context=body.metadata,
            db=db,
        )
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        # Pipeline 失败时回退：标记 messages 为已处理但返回 SKIP
        return ok(MemoryWriteResponse(
            results=[
                WriteResultItem(
                    id="",
                    memory=m.content[:80],
                    event=MemoryEvent.SKIP,
                )
                for m in body.messages
            ]
        ).model_dump())

    # --- 将 PipelineResult 映射为前端 results 格式 ---
    results = _pipeline_to_write_results(pipeline_result)

    elapsed = round((time_module.perf_counter() - start) * 1000, 2)
    logger.info(
        f"同步写入完成: user_id={effective_user_id}, "
        f"messages={len(body.messages)}, memories={pipeline_result.new_count + pipeline_result.merged_count}, "
        f"discarded={pipeline_result.discarded_count}, elapsed={elapsed}ms"
    )

    return ok(MemoryWriteResponse(results=results).model_dump())


def _pipeline_to_write_results(pipeline_result) -> list[WriteResultItem]:
    """
    将 PipelineResult.details 转换为前端 WriteResultItem 格式。

    映射规则:
      keep_new        → ADD     (新记忆创建)
      merge           → MERGE   (合并到已有)
      update_existing → ADD     (更新视为新增信息)
      discard         → SKIP    (重复或不包含新信息)
    """
    results = []
    for d in pipeline_result.details:
        action = d.get("action", "keep_new")
        memory_id = d.get("memory_id", "") or ""
        content = d.get("content_preview", "") or ""

        if action == "discard":
            results.append(WriteResultItem(
                id="",
                memory=content,
                event=MemoryEvent.SKIP,
            ))
        elif action == "merge":
            results.append(WriteResultItem(
                id=memory_id,
                memory=content,
                event=MemoryEvent.MERGE,
            ))
        else:  # keep_new / update_existing
            results.append(WriteResultItem(
                id=memory_id,
                memory=content,
                event=MemoryEvent.ADD,
            ))

    return results


# ============================================================
# 异步写入 — 对齐前端对接文档 一.1 附节
# ============================================================

@router.post("/async_write", summary="异步写入记忆", status_code=202)
async def memory_async_write(
    body: AsyncWriteRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
    user_id_header: str = Depends(get_current_user_id),
):
    """
    异步写入 — 即刻返回 request_id，后台处理。

    当前版本：投递失败时降级为同步写入。
    未来：对接 Celery/Kafka 实现真异步。
    """
    request_id = f"async_{uuid4().hex[:24]}"
    effective_user_id = user_id_header or body.user_id

    # 尝试投递 MQ
    mq_ok = await _try_deliver_to_mq(request_id, effective_user_id, body)

    if mq_ok:
        logger.info(f"异步写入已投递 MQ: request_id={request_id}")
    else:
        # 降级：同步写入
        logger.warning(f"MQ 不可用，降级同步写入: request_id={request_id}")
        await _fallback_sync_write(request_id, effective_user_id, agent_id, body)

    return ok(AsyncWriteResponse(
        request_id=request_id,
        status="accepted",
    ).model_dump())


async def _try_deliver_to_mq(request_id: str, user_id: str, body: AsyncWriteRequest) -> bool:
    """尝试投递到 MQ。TODO: 实现 Kafka/RabbitMQ Producer"""
    return False


async def _fallback_sync_write(
    request_id: str, user_id: str, agent_id: str, body: AsyncWriteRequest
) -> None:
    """MQ 不可用时降级为同步写入原始记录（不含 Pipeline 处理）"""
    from app.core.database import async_session_factory
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        for i, msg in enumerate(body.messages):
            record = InteractionRecord(
                record_id=f"rec_{uuid4().hex[:24]}",
                user_id=user_id.strip().lower(),
                agent_id=agent_id,
                scene_id=body.scene_id,
                session_id=body.session_id or f"sess_{uuid4().hex[:12]}",
                task_id=body.task_id,
                turn_index=i,
                role=msg.role,
                content=msg.content,
                processed=False,
                recorded_at=now,
                extra_meta=body.metadata or {},
            )
            session.add(record)
        await session.commit()


# ============================================================
# 检索 — 对齐前端对接文档 一.2 节
# ============================================================

@router.post("/search", summary="检索记忆")
async def memory_search(
    body: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    语义检索历史记忆 — Qdrant 向量检索 + PostgreSQL 元数据过滤。

    返回与 query 最相关的记忆列表，包含 relevance_score。
    当 Qdrant 不可用时，降级为数据库关键词匹配。
    """
    from app.services.retrieval_service import search as legacy_search

    # 优先使用新的 MemoryStore 直查路径
    try:
        result = await memory_store.search(
            query=body.query,
            user_id=body.user_id,
            db=db,
            scene_id=body.scene_id,
            task_id=body.task_id,
            session_id=body.session_id,
            memory_types=body.memory_types,
            time_start=body.time_start,
            time_end=body.time_end,
            top_k=body.top_k,
            rerank=body.rerank,
        )
        logger.info(
            f"Search: user={body.user_id}, query='{body.query[:50]}...', "
            f"found={len(result['results'])}, elapsed={result['elapsed_ms']}ms"
        )
        return ok(result)
    except Exception as e:
        logger.warning(f"MemoryStore search failed, falling back to legacy: {e}")
        # 降级到旧版 MCP 路径
        try:
            result = legacy_search(
                query=body.query,
                user_id=body.user_id,
                scene_id=body.scene_id,
                task_id=body.task_id,
                session_id=body.session_id,
                memory_types=body.memory_types,
                top_k=body.top_k,
                rerank=body.rerank,
            )
            return ok(result)
        except Exception:
            return ok({
                "query": body.query,
                "results": [],
                "total_candidates": 0,
                "elapsed_ms": 0,
            })


# ============================================================
# 上下文 — 对齐前端对接文档 二.1 节
# ============================================================

@router.post("/context", summary="Prompt 上下文片段")
async def memory_context(
    body: ContextRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    检索记忆并格式化为可直接注入 AI Prompt 的文本。

    按类型分组，带 emoji 标记，便于 LLM 理解。
    """
    try:
        result = await memory_store.get_context(
            query=body.query,
            user_id=body.user_id,
            db=db,
            scene_id=body.scene_id,
            task_id=body.task_id,
            session_id=body.session_id,
            max_tokens=body.max_tokens,
            group_by_type=body.group_by_type,
            include_preferences=body.include_preferences,
            include_facts=body.include_facts,
            include_task_state=body.include_task_state,
        )
        return ok(result)
    except Exception as e:
        logger.error(f"Context generation failed: {e}")
        return ok({
            "formatted_text": "",
            "fragments": [],
            "memory_count": 0,
            "estimated_tokens": 0,
        })


# ============================================================
# 更新 — 对齐前端对接文档 二.2 节
# ============================================================

@router.put("/update", summary="更新记忆")
async def memory_update(
    body: MemoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新单条记忆的内容、重要性、标签等字段。"""
    result = await memory_store.update_memory(
        memory_id=body.memory_id,
        db=db,
        content=body.content,
        summary=body.summary,
        status=body.status,
        importance=body.importance,
        confidence=body.confidence,
        tags=body.tags,
    )
    if result["updated"]:
        return ok(MemoryUpdateResponse(
            memory_id=body.memory_id,
            updated=True,
            version=result.get("version", 1),
        ).model_dump())
    else:
        return ok(MemoryUpdateResponse(
            memory_id=body.memory_id,
            updated=False,
            version=0,
        ).model_dump())


# ============================================================
# 删除（软删除） — 对齐前端对接文档 二.3 节
# ============================================================

@router.delete("/delete", summary="删除记忆（软删除）")
async def memory_delete(
    body: MemoryDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """软删除单条记忆（状态置为 deleted，从 Qdrant 移除向量）。"""
    result = await memory_store.soft_delete(
        memory_id=body.memory_id,
        db=db,
        reason=body.reason,
    )
    return ok(MemoryDeleteResponse(
        memory_id=body.memory_id,
        deleted=result["deleted"],
        previous_status=result.get("previous_status", "active"),
    ).model_dump())


# ============================================================
# 列出全部 — 对齐前端对接文档 一.3 节
# ============================================================

@router.post("/list", summary="列出全部记忆")
async def memory_list(
    user_id: str = Query(...),
    scene_id: str | None = Query(None),
    task_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    分页列出用户全部记忆。

    优先使用 MemoryStore 直查 PostgreSQL；
    MemoryStore 查询为空时降级到 MCP 路径。
    """
    try:
        result = await memory_store.list_memories(
            user_id=user_id,
            db=db,
            scene_id=scene_id,
            task_id=task_id,
            page=page,
            page_size=page_size,
        )

        if result["total"] > 0:
            return ok(result)

        # MemoryStore 为空，降级到 MCP
        logger.info(f"MemoryStore empty for user={user_id}, falling back to MCP")
        from app.mcp_client import mcp_client
        mcp_result = await mcp_client.list_memories(user_id=user_id)
        return ok(mcp_result)

    except Exception as e:
        logger.error(f"List failed: {e}")
        from app.mcp_client import mcp_client
        try:
            mcp_result = await mcp_client.list_memories(user_id=user_id)
            return ok(mcp_result)
        except Exception:
            return ok({"items": [], "total": 0, "page": page, "page_size": page_size})


# ============================================================
# 清除全部 — 对齐前端对接文档 一.4 节
# ============================================================

@router.post("/delete-all", summary="清除全部记忆")
async def memory_delete_all(
    user_id: str = Query(...),
    scene_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    清除用户全部记忆 — PostgreSQL + Qdrant 双清。
    同时清理 MCP/mem0 中的记忆（如果可用）。
    """
    # 1. 清理 MemoryStore（PostgreSQL + Qdrant generation collection）
    store_result = await memory_store.delete_all_memories(
        user_id=user_id,
        db=db,
        scene_id=scene_id,
    )

    # 2. 尝试清理 MCP/mem0 中的记忆（非致命）
    try:
        from app.mcp_client import mcp_client
        await mcp_client.delete_all_memories(user_id=user_id)
        logger.info(f"MCP memories also cleared for user={user_id}")
    except Exception as e:
        logger.warning(f"MCP delete-all failed (non-fatal): {e}")

    return ok({
        "message": store_result["message"],
        "deleted_count": store_result["deleted_count"],
    })
