# -*- coding: utf-8 -*-
"""
记忆核心 API — 对齐前端对接文档。

所有端点使用 MemoryPipeline（生成+去重）和 MemoryStore（检索/列表/删除）。
替换原来的 MCP 中转 + Mock 提取器方案。

端点:
  POST /write       — 同步写入记忆（支持 Mock / MQ_Wait / Direct Pipeline 三种模式）
  POST /async_write — 异步写入（即刻返回 request_id）
  POST /search      — 语义检索记忆（Qdrant + PostgreSQL）
  POST /list        — 分页列出记忆
  POST /delete-all  — 清除全部记忆
  POST /context     — 检索并格式化为 Prompt 上下文
  PUT  /update      — 更新单条记忆
  DELETE /delete    — 软删除单条记忆

支持三种数据类型（通过 interaction_type 区分）：
  - dialogue:     当前对话记录，messages 逐条落库
  - session:      历史会话数据，含会话时间/来源/摘要
  - task_process: 任务过程数据，含目标/进展/执行结果

同步写入三种模式:
  - Mock (use_mock_extraction=True):   中文正则提取，闪电返回，开发期使用
  - MQ_Wait (use_mq_wait=True):       投递 Kafka → Redis 等待结果 → 返回（伪同步）
  - Direct Pipeline (default):        直接调用 LLM Pipeline，5-15s 延迟
"""

import asyncio
import re as re_module
import time as time_module
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DEFAULT_DEV_SCENE_ID,
    get_current_agent,
    get_current_user_id,
    get_current_scene_id,
    get_current_session_id,
    get_current_task_id,
)
from app.core.config import get_settings
from app.core.database import async_session_factory, get_db
from app.models.base import InteractionRecord, RetrievalRequest, RetrievalResult
from app.core.exceptions import ValidationError
from app.core.logger import get_logger
from app.schemas.common import error, ok
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
from app.services.memory_service import (
    get_user_profile,
    get_session_context,
    get_task_view,
)
from app.services.mq_producer import mq_producer
from app.services.validation_service import (
    validate_id_format,
    normalize_id,
    validate_write_request_by_type,
)

logger = get_logger("memory_api")
router = APIRouter()


# ============================================================
# Fire-and-Forget 检索日志（写 t_retrieval_request + t_retrieval_result）
# ============================================================

async def _log_retrieval(
    request_id: str,
    agent_id: Optional[str],
    user_id: str,
    scene_id: Optional[str],
    session_id: Optional[str],
    task_id: Optional[str],
    query_text: str,
    filter_conditions: dict,
    top_k: int,
    results: list[dict],
    elapsed_ms: int,
):
    """异步写检索日志，失败不阻塞主流程。"""
    try:
        async with async_session_factory() as log_db:
            log_db.add(RetrievalRequest(
                request_id=request_id,
                agent_id=agent_id,
                user_id=user_id,
                scene_id=scene_id,
                session_id=session_id,
                task_id=task_id,
                query_text=query_text,
                filter_conditions=filter_conditions,
                top_k=top_k,
            ))
            await log_db.flush()

            for rank, mem in enumerate(results):
                log_db.add(RetrievalResult(
                    request_id=request_id,
                    memory_id=mem.get("memory_id", ""),
                    rank=rank,
                    relevance_score=mem.get("relevance_score"),
                ))

            await log_db.commit()
    except Exception as e:
        logger.warning(f"Retrieval log write failed (non-fatal): {e}")


# Mock 提取器（从共享模块导入，供 memory.py 和 mq_consumer.py 共用）
from app.services.mock_extractor import mock_extract_results as _mock_extract_results


# ============================================================
# 同步写入 — 对齐前端对接文档 一.1 节
# ============================================================

@router.post("/write", summary="写入记忆（同步）", status_code=200)
async def memory_write(
    request: Request,
    body: MemoryWriteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
    user_id_header: str = Depends(get_current_user_id),
    scene_id: str | None = Depends(get_current_scene_id),
    session_id_header: str | None = Depends(get_current_session_id),
    task_id_header: str | None = Depends(get_current_task_id),
):
    """
    同步写入记忆数据，支持三种数据类型：

    - dialogue (对话记录): messages 数组逐条落库，每轮标记 turn_index
    - session (历史会话): 导入历史会话内容、时间、来源信息
    - task_process (任务过程): 写入任务目标、进展、执行结果

    同步写入模式（由 settings.generation 控制）：
    1. Mock 模式 (use_mock_extraction=True): 中文正则提取，<100ms 返回
    2. MQ_Wait 模式 (use_mq_wait=True): 投递 Kafka → Redis 等待结果 → 伪同步返回
    3. Direct Pipeline 模式: 直接调用 LLM Pipeline（5-15s）

    延迟: Mock <100ms, MQ_Wait ~1-5s, Direct ~5-15s。
    """
    start = time_module.perf_counter()
    itype = body.interaction_type
    settings = get_settings()

    # 合并 ID 来源（Header > Body，开发模式自动补默认值）
    effective_user_id = normalize_id(user_id_header or body.user_id)
    effective_scene_id = scene_id or body.scene_id or DEFAULT_DEV_SCENE_ID
    effective_session_id = session_id_header or body.session_id or f"sess_{uuid4().hex[:12]}"
    effective_task_id = task_id_header or body.task_id

    # 业务级校验（ID 格式 + 类型感知校验）
    if effective_user_id:
        err = validate_id_format("user_id", effective_user_id)
        if err:
            raise ValidationError(message=err)

    # 类型感知校验：确保每种 interaction_type 有足够的输入数据
    type_validation = validate_write_request_by_type(
        interaction_type=itype,
        messages=body.messages,
        session_summary=body.session_summary,
        session_time=body.session_time,
        task_goal=body.task_goal,
        task_progress=body.task_progress,
        task_result=body.task_result,
    )
    type_validation.raise_if_invalid()

    # --- 写入原始交互记录（批量 insert）---
    await _batch_write_records(body, db, effective_user_id, agent_id,
                                effective_scene_id, effective_session_id,
                                effective_task_id)
    await db.commit()

    # ============================================================
    # 根据配置选择处理模式
    # ============================================================

    # 模式 1: Mock 提取（开发期，秒级返回）
    if settings.generation.use_mock_extraction:
        raw_results = _mock_extract_results(body.messages)
        results = [
            WriteResultItem(
                id=r["id"],
                memory=r["memory"],
                event=MemoryEvent(r["event"]),
            )
            for r in raw_results
        ]
        elapsed = round((time_module.perf_counter() - start) * 1000, 2)
        logger.info(
            f"[Mock] 同步写入完成: type={itype}, user_id={effective_user_id}, "
            f"messages={len(body.messages)}, "
            f"results={len([r for r in raw_results if r['event'] == 'ADD'])}, "
            f"elapsed={elapsed}ms"
        )
        return ok(MemoryWriteResponse(results=results).model_dump())

    # 模式 2: MQ 等待（正式期伪同步，方案二）
    if settings.generation.use_mq_wait:
        request_id = f"mq_{uuid4().hex[:24]}"
        body_dict = body.model_dump()

        # 投递到 MQ
        mq_ok = await _try_deliver_to_mq(
            request_id, effective_user_id, agent_id, body_dict
        )

        if mq_ok:
            # 等待 Consumer 处理结果（带超时降级）
            from app.services.result_waiter import wait_for_result_with_timeout
            raw_results = await wait_for_result_with_timeout(request_id)

            results = [
                WriteResultItem(
                    id=r.get("id", ""),
                    memory=r.get("memory", ""),
                    event=MemoryEvent(r.get("event", "SKIP")),
                )
                for r in raw_results
            ]
            elapsed = round((time_module.perf_counter() - start) * 1000, 2)
            logger.info(
                f"[MQ_Wait] 同步写入完成: request_id={request_id}, "
                f"elapsed={elapsed}ms"
            )
            return ok(MemoryWriteResponse(results=results).model_dump())
        else:
            logger.warning("MQ 不可用，降级到 Direct Pipeline")

    # 模式 3: Direct Pipeline（默认，直接调用 LLM）
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
        return ok(MemoryWriteResponse(
            results=[
                WriteResultItem(
                    id="",
                    memory=m.content[:80] if hasattr(m, 'content') else "",
                    event=MemoryEvent.SKIP,
                )
                for m in body.messages
            ]
        ).model_dump())

    # --- 将 PipelineResult 映射为前端 results 格式 ---
    results = _pipeline_to_write_results(pipeline_result)

    elapsed = round((time_module.perf_counter() - start) * 1000, 2)
    logger.info(
        f"[Pipeline] 同步写入完成: type={itype}, user_id={effective_user_id}, "
        f"messages={len(body.messages)}, "
        f"memories={pipeline_result.new_count + pipeline_result.merged_count}, "
        f"discarded={pipeline_result.discarded_count}, elapsed={elapsed}ms"
    )

    return ok(MemoryWriteResponse(results=results).model_dump())


# ============================================================
# 写入辅助函数 — 批量 insert
# ============================================================

async def _batch_write_records(
    body: MemoryWriteRequest, db, user_id: str, agent_id: str,
    scene_id: str | None, session_id: str, task_id: str | None = None
) -> None:
    """批量写入交互记录（使用单条 INSERT ... VALUES 多条）"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    itype = body.interaction_type
    records = []

    base = {
        "user_id": user_id,
        "agent_id": agent_id,
        "scene_id": scene_id,
        "session_id": session_id,
        "task_id": task_id,
        "interaction_type": itype,
        "content_type": "text",
        "processed": False,
        "status": "pending_extract",
        "recorded_at": now,
        "extra_meta": body.metadata or {},
    }

    extra = dict(body.metadata or {})

    if itype == "dialogue":
        for i, msg in enumerate(body.messages):
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": i,
                "role": msg.role,
                "content": msg.content,
            })

    elif itype == "session":
        if body.session_time:
            extra["session_time"] = body.session_time
        if body.session_source:
            extra["session_source"] = body.session_source
        base["extra_meta"] = extra

        for i, msg in enumerate(body.messages):
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": i,
                "role": msg.role,
                "content": msg.content,
            })

        if body.session_summary:
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": len(body.messages),
                "role": "session_summary",
                "content": body.session_summary,
                "content_type": "session_summary",
            })

    elif itype == "task_process":
        base["extra_meta"] = extra
        for i, msg in enumerate(body.messages):
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": i,
                "role": msg.role,
                "content": msg.content,
            })

        turn_offset = len(body.messages)
        task_fields = [
            ("task_goal", body.task_goal),
            ("task_progress", body.task_progress),
            ("task_result", body.task_result),
        ]
        for j, (role_name, content) in enumerate(task_fields):
            if content:
                records.append({
                    **base,
                    "record_id": f"rec_{uuid4().hex[:24]}",
                    "turn_index": turn_offset + j,
                    "role": role_name,
                    "content": content,
                    "content_type": "task_process",
                })

    if records:
        await db.execute(insert(InteractionRecord), records)


# ============================================================
# Pipeline 结果映射
# ============================================================

def _pipeline_to_write_results(pipeline_result) -> list[WriteResultItem]:
    """
    将 PipelineResult.details 转换为前端 WriteResultItem 格式。

    映射规则:
      keep_new        → ADD      (新记忆创建)
      merge           → MERGE    (合并到已有)
      update_existing → ADD      (更新视为新增信息)
      discard         → SKIP     (重复或不包含新信息)
      conflict        → CONFLICT (冲突需人工确认)
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
        elif action == "conflict":
            # 冲突：返回给前端标记为冲突，等待人工处理
            results.append(WriteResultItem(
                id=memory_id,
                memory=f"[冲突] {content}",
                event=MemoryEvent.ADD,  # 仍写入但标记为 pending
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

    处理管线:
      1. 鉴权（开发阶段跳过）
      2. 投递到 Kafka MQ
      3. Consumer 异步处理 → 落库
      4. 失败时降级为同步写入（status=pending_extract）
    """
    request_id = f"async_{uuid4().hex[:24]}"
    effective_user_id = normalize_id(user_id_header or body.user_id)
    body_dict = body.model_dump()

    mq_ok = await _try_deliver_to_mq(request_id, effective_user_id, agent_id, body_dict)

    if mq_ok:
        logger.info(f"异步写入已投递 MQ: request_id={request_id}")
    else:
        logger.warning(f"MQ 不可用，降级同步写入: request_id={request_id}")
        await _fallback_sync_write(request_id, effective_user_id, agent_id, body)

    return ok(AsyncWriteResponse(
        request_id=request_id,
        status="accepted",
    ).model_dump())


async def _try_deliver_to_mq(
    request_id: str, user_id: str, agent_id: str, body_dict: dict
) -> bool:
    """尝试投递到 Kafka MQ。返回 True 投递成功，False 失败。"""
    if not mq_producer.is_available:
        logger.debug("MQ Producer 未初始化，跳过投递")
        return False

    return await mq_producer.publish_memory_write(
        request_id=request_id,
        user_id=user_id,
        agent_id=agent_id,
        body_dict=body_dict,
    )


async def _fallback_sync_write(
    request_id: str, user_id: str, agent_id: str, body: AsyncWriteRequest
) -> None:
    """MQ 不可用时降级为同步写入原始记录（status=pending_extract，后续可补处理）"""
    from app.core.database import async_session_factory
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    itype = body.interaction_type
    extra_meta = dict(body.metadata or {})

    if itype == "session":
        if body.session_time:
            extra_meta["session_time"] = body.session_time
        if body.session_source:
            extra_meta["session_source"] = body.session_source

    records = []
    base = {
        "user_id": user_id,
        "agent_id": agent_id,
        "scene_id": body.scene_id,
        "session_id": body.session_id or f"sess_{uuid4().hex[:12]}",
        "task_id": body.task_id,
        "interaction_type": itype,
        "content_type": "text",
        "processed": False,
        "status": "pending_extract",
        "recorded_at": now,
        "extra_meta": extra_meta,
    }

    async with async_session_factory() as session:
        for i, msg in enumerate(body.messages):
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": i,
                "role": msg.role,
                "content": msg.content,
            })

        if itype == "session" and body.session_summary:
            records.append({
                **base,
                "record_id": f"rec_{uuid4().hex[:24]}",
                "turn_index": len(body.messages),
                "role": "session_summary",
                "content": body.session_summary,
                "content_type": "session_summary",
            })

        if itype == "task_process":
            turn_offset = len(body.messages)
            task_fields = [
                ("task_goal", body.task_goal),
                ("task_progress", body.task_progress),
                ("task_result", body.task_result),
            ]
            for j, (role_name, content) in enumerate(task_fields):
                if content:
                    records.append({
                        **base,
                        "record_id": f"rec_{uuid4().hex[:24]}",
                        "turn_index": turn_offset + j,
                        "role": role_name,
                        "content": content,
                        "content_type": "task_process",
                    })

        if records:
            await session.execute(insert(InteractionRecord), records)
        await session.commit()

    logger.info(
        f"降级同步写入完成: request_id={request_id}, "
        f"records={len(records)}, status=pending_extract"
    )


# ============================================================
# 检索 — 对齐前端对接文档 一.2 节
# ============================================================

@router.post("/search", summary="检索记忆")
async def memory_search(
    body: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
):
    """
    语义检索历史记忆 — Qdrant 向量检索 + PostgreSQL 元数据过滤。

    返回与 query 最相关的记忆列表，包含 relevance_score。
    当 Qdrant 不可用时，降级为数据库关键词匹配。
    """
    from app.services.retrieval_service import search as legacy_search

    try:
        result = await memory_store.search(
                query=body.query,
                user_id=body.user_id,
                db=db,
                agent_id=agent_id,
                scene_id=body.scene_id,
                task_id=body.task_id,
                session_id=body.session_id,
                memory_types=body.memory_types,
                status=body.status,
                max_content_length=body.max_content_length,
                time_start=body.time_start,
                time_end=body.time_end,
                top_k=body.top_k,
                rerank=body.rerank,
            )
        logger.info(
            f"Search: user={body.user_id}, query='{body.query[:50]}...', "
            f"found={len(result['results'])}, elapsed={result['elapsed_ms']}ms"
        )

        # Fire-and-forget 检索日志
        req_id = str(uuid4())
        asyncio.create_task(_log_retrieval(
            request_id=req_id,
            agent_id=agent_id,
            user_id=body.user_id,
            scene_id=body.scene_id,
            session_id=body.session_id,
            task_id=body.task_id,
            query_text=body.query,
            filter_conditions={
                "memory_types": body.memory_types,
                "status": body.status,
                "time_start": str(body.time_start) if body.time_start else None,
                "time_end": str(body.time_end) if body.time_end else None,
            },
            top_k=body.top_k,
            results=result.get("results", []),
            elapsed_ms=result.get("elapsed_ms", 0),
        ))

        return ok(result)
    except Exception as e:
        logger.warning(f"MemoryStore search failed, falling back to legacy: {e}")
        try:
            result = legacy_search(
                query=body.query,
                user_id=body.user_id,
                scene_id=body.scene_id,
                task_id=body.task_id,
                session_id=body.session_id,
                memory_types=body.memory_types,
                status=body.status,
                max_content_length=body.max_content_length,
                top_k=body.top_k,
                rerank=body.rerank,
            )
            return ok(result)
        except Exception as e2:
            logger.error(f"Search failed (both paths): {e2}")
            return error(
                message="检索服务暂时不可用",
                code=-1,
                data={
                    "query": body.query,
                    "results": [],
                    "total_candidates": 0,
                    "elapsed_ms": 0,
                },
                error_code="SEARCH_FAILED",
            )


# ============================================================
# 上下文 — 对齐前端对接文档 二.1 节
# ============================================================

@router.post("/context", summary="Prompt 上下文片段")
async def memory_context(
    body: ContextRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
):
    """
    Prompt 上下文。

    三层聚合 — 不混入原始记忆碎片，仅返回结构化聚合结果 + LLM 总结。
    """
    try:
        aggregation = {}

        if body.task_id:
            task_view = await get_task_view(db, body.task_id)
            aggregation = {
                "type": "task_view",
                "task_id": body.task_id,
                "goal": task_view["current_goal"]["content"] if task_view.get("current_goal") else "",
                "timeline": [
                    {"stage": item.get("sub_type", "progress"), "content": item["content"]}
                    for item in task_view.get("progress_timeline", [])
                ],
            }

        elif body.session_id:
            sess_ctx = await get_session_context(db, body.session_id)
            by_type_clean = {
                k: [item["content"] for item in v]
                for k, v in sess_ctx.get("by_type", {}).items()
            }
            aggregation = {
                "type": "session_context",
                "session_id": body.session_id,
                "by_type": by_type_clean,
                "key_items": [
                    {"type": item["memory_type"], "content": item["content"]}
                    for item in sess_ctx.get("key_items", [])
                ],
            }

        elif body.include_preferences or body.include_facts:
            profile = await get_user_profile(db, body.user_id)
            aggregation = {
                "type": "user_profile",
                "user_id": body.user_id,
                "preferences": profile.get("preferences", []),
                "facts": profile.get("facts", []),
            }

        # LLM 总结
        formatted_text = ""
        contents = []
        for key, val in aggregation.items():
            if key in ("preferences", "facts") and isinstance(val, list):
                contents.extend(val)
            elif key == "goal" and val:
                contents.append(val)
            elif key == "timeline" and isinstance(val, list):
                contents.extend(item["content"] for item in val)
            elif key == "by_type" and isinstance(val, dict):
                for items in val.values():
                    contents.extend(items)
            elif key == "key_items" and isinstance(val, list):
                contents.extend(item["content"] for item in val)

        if contents:
            try:
                from app.services.llm_client import llm_client as _llm
                lines = "\n".join(f"- {c[:200]}" for c in contents[:20])
                formatted_text = await _llm.chat_completion([{
                    "role": "user",
                    "content": f"将以下记忆碎片总结为一段通顺的摘要，注入AI对话上下文。保留关键信息，去除冗余：\n{lines}"
                }], max_tokens=body.max_tokens or 500)
            except Exception:
                pass

        return ok({
            "aggregation": aggregation,
            "formatted_text": formatted_text,
            "estimated_tokens": len(formatted_text) // 2 if formatted_text else 0,
        })
    except Exception as e:
        logger.error(f"Context generation failed: {e}")
        return error(
            message="上下文生成失败",
            code=-2,
            data={
                "aggregation": {},
                "formatted_text": "",
                "estimated_tokens": 0,
            },
            error_code="CONTEXT_FAILED",
        )


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
    store_result = await memory_store.delete_all_memories(
        user_id=user_id,
        db=db,
        scene_id=scene_id,
    )

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
