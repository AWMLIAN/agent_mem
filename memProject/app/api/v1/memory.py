# -*- coding: utf-8 -*-
"""
记忆核心 API — 记忆写入/检索/管理。

写入路径：
  - POST /write       → 同步写入：鉴权→校验→标准化→写T_INTERACTION_RECORD→返回
  - POST /async_write → 异步写入：鉴权→快速校验→投递MQ→返回202（高并发场景）
  - MCP 路径保留在 /mcp/* 子路由，用于通过 OpenMemory Server 做 LLM 抽取
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
from app.mcp_client import mcp_client
from app.models.base import InteractionRecord
from app.schemas.common import ok
from app.schemas.memory import (
    MemoryWriteRequest,
    MemoryWriteResponse,
    AsyncWriteRequest,
    AsyncWriteResponse,
    MemorySearchRequest,
    ContextRequest,
    MemoryUpdateRequest,
    MemoryDeleteRequest,
)
from app.services.validation_service import validate_and_standardize

logger = get_logger("memory_api")
router = APIRouter()


# ============================================================
# 同步写入 — 对齐《核心业务逻辑拆解》三.1节
# ============================================================

@router.post("/write", summary="同步写入交互记录（标准路径）", status_code=200)
async def memory_write(
    request: Request,
    body: MemoryWriteRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent),
    user_id: str = Depends(get_current_user_id),
    scene_id: str | None = Depends(get_current_scene_id),
    session_id: str | None = Depends(get_current_session_id),
):
    """
    同步写入单条交互记录。

    处理管线（对齐设计文档）：
    1. 鉴权 — Depends(get_current_agent) 已完成
    2. 校验 — Pydantic + validation_service 双层校验
    3. 标准化 — 时间格式统一、ID规范化、元数据补全
    4. 写库 — INSERT INTO t_interaction_record
    5. 返回 — 200 + record_id
    """
    start = time_module.perf_counter()

    # --- 合并 Header 中的 ID（Header > Body） ---
    effective_user_id = user_id or body.user_id
    effective_session_id = session_id or body.session_id
    effective_agent_id = agent_id or body.agent_id
    effective_scene_id = scene_id or body.scene_id

    # --- 校验与标准化 ---
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
        raw_data,
        agent_id=effective_agent_id,
        scene_id=effective_scene_id,
    )

    # --- 写入 T_INTERACTION_RECORD ---
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
        processed=False,  # 标记为待LLM抽取
        recorded_at=validated["timestamp_dt"],
        extra_meta=validated["business_meta"],
    )

    db.add(record)
    await db.commit()

    elapsed = round((time_module.perf_counter() - start) * 1000, 2)
    logger.info(
        f"同步写入完成: record_id={validated['record_id']}, "
        f"user_id={validated['user_id']}, elapsed={elapsed}ms"
    )

    return ok(MemoryWriteResponse(
        record_id=validated["record_id"],
        status="pending_extract",
        message=f"数据已接收并写入原始记录表 (耗时 {elapsed}ms)",
    ).model_dump())


# ============================================================
# 异步写入 — 对齐《核心业务逻辑拆解》三.2节
# ============================================================

@router.post("/async_write", summary="异步写入（高并发场景）", status_code=202)
async def memory_async_write(
    body: AsyncWriteRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
    user_id: str = Depends(get_current_user_id),
):
    """
    异步写入接口 — 高并发/历史数据导入场景。

    处理管线：
    1. 鉴权
    2. 快速校验
    3. 生成 request_id + 投递到消息队列（Kafka/Redis Stream）
    4. 立即返回 202 Accepted

    注：当前 MQ 消费者由角色B实现，此处投递占位。
       当 MQ 不可用时，降级为直接同步写入。
    """
    effective_user_id = user_id or body.user_id
    request_id = f"async_{uuid4().hex[:24]}"

    # --- 快速校验 ---
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

    # 仅做必填字段校验，不做完整标准化（标准化由消费者完成）
    validated = validate_and_standardize(
        raw_data,
        agent_id=agent_id,
        scene_id=None,
    )

    # --- 尝试投递 MQ，失败则降级同步写入 ---
    mq_delivered = await _try_deliver_to_mq(request_id, validated)

    if mq_delivered:
        logger.info(f"异步写入已投递: request_id={request_id}")
        return ok(AsyncWriteResponse(
            request_id=request_id,
            status="accepted",
            message="异步写入已提交，处理完成后通过回调通知",
        ).model_dump(), message="已接受")
    else:
        # 降级：MQ 不可用时直接同步写入
        logger.warning(f"MQ 不可用，降级为同步写入: request_id={request_id}")
        from app.core.database import async_session_factory

        record = InteractionRecord(
            record_id=validated["record_id"],
            user_id=validated["user_id"],
            agent_id=agent_id,
            session_id=validated["session_id"],
            task_id=validated.get("task_id"),
            role=body.role.value if hasattr(body.role, "value") else str(body.role),
            content=validated["content"],
            processed=False,
            recorded_at=validated["timestamp_dt"],
            extra_meta=validated["business_meta"],
        )

        async with async_session_factory() as session:
            session.add(record)
            await session.commit()

        return ok({
            "request_id": request_id,
            "record_id": validated["record_id"],
            "status": "stored",
            "fallback": True,
            "message": "MQ 不可用，已降级为同步写入",
        })


async def _try_deliver_to_mq(request_id: str, data: dict) -> bool:
    """
    尝试将数据投递到消息队列。

    当前占位实现：总是返回 False（降级到同步写入）。
    角色B实现 MQ Producer 后替换此函数。
    """
    # TODO: 角色B — 接入 Kafka/Redis Stream Producer
    # from app.services.mq_producer import mq_producer
    # return await mq_producer.send("memory.async.write", message)
    return False


@router.post("/search", summary="检索记忆（MCP search_memory）")
async def memory_search(body: MemorySearchRequest, db: AsyncSession = Depends(get_db)):
    result = await mcp_client.search_memory(query=body.query, user_id=body.user_id)
    return ok(result)


@router.post("/context", summary="Prompt 上下文片段")
async def memory_context(body: ContextRequest, db: AsyncSession = Depends(get_db)):
    return ok({"fragments": [], "formatted_text": "", "memory_count": 0})


@router.put("/update", summary="更新记忆")
async def memory_update(body: MemoryUpdateRequest, db: AsyncSession = Depends(get_db)):
    return ok({"memory_id": body.memory_id, "updated": True})


@router.delete("/delete", summary="删除记忆（软删除）")
async def memory_delete(body: MemoryDeleteRequest, db: AsyncSession = Depends(get_db)):
    return ok({"memory_id": body.memory_id, "deleted": True})


# ============================================================
# MCP 工具直通接口 — 测试用
# ============================================================

@router.post("/list", summary="列出全部记忆（MCP list_memories）")
async def memory_list(user_id: str = Query(...)):
    result = await mcp_client.list_memories(user_id=user_id)
    return ok(result)


@router.post("/delete-all", summary="清除全部记忆（MCP delete_all_memories）")
async def memory_delete_all(user_id: str = Query(...)):
    result = await mcp_client.delete_all_memories(user_id=user_id)
    return ok(result)
