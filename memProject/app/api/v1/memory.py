# -*- coding: utf-8 -*-
"""
记忆核心 API — 对齐前端对接文档。

写入路径：
  - POST /write       → 同步写入：鉴权→校验→写原始记录→Mock抽取→返回 results
  - POST /async_write → 异步写入：鉴权→校验→投递MQ→返回 request_id
  - POST /search      → 检索记忆
  - POST /list        → 列出全部
  - POST /delete-all  → 清除全部
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
from app.services.validation_service import validate_id_format, normalize_id
from app.schemas.common import ok
from app.schemas.memory import (
    MemoryWriteRequest,
    MemoryWriteResponse,
    WriteResultItem,
    MemoryEvent,
    AsyncWriteRequest,
    AsyncWriteResponse,
    MemorySearchRequest,
    ContextRequest,
    MemoryUpdateRequest,
    MemoryUpdateResponse,
    MemoryDeleteRequest,
    MemoryDeleteResponse,
)
from app.services.validation_service import validate_and_standardize
from app.services.memory_service import (
    get_memory_by_id,
    update_memory_fields,
    soft_delete_memory,
    build_context_query,
    list_memories_filtered,
    get_stats,
    get_memory_relations,
)

logger = get_logger("memory_api")
router = APIRouter()


# ============================================================
# Mock 记忆抽取规则（联调期使用，正式期替换为下游模块调用）
# ============================================================

def _mock_extract_memories(messages: list, user_id: str) -> list[dict]:
    """
    Mock 记忆抽取规则。

    联调期：简单规则模拟，保证前端流程跑通。
    正式期：替换为等待下游"记忆生成+去重融合"模块的 RPC/MQ 回调结果。

    规则：
    - 检测到 "我叫xxx" / "我是xxx" → ADD（偏好/事实）
    - 检测到 "不喜欢" / "讨厌" → ADD（偏好）
    - 纯问候/确认消息 → SKIP
    - 其他有价值的消息 → ADD（标记为一般记忆）
    """
    import re

    results = []
    for msg in messages:
        content = msg.content.strip()
        role = msg.role.lower()

        # 跳过 system 消息
        if role == "system":
            results.append({"event": "SKIP", "memory": "", "id": ""})
            continue

        # 纯问候/短确认 → SKIP
        greetings = {"你好", "hi", "hello", "ok", "好的", "收到", "明白了", "谢谢", "thanks", "嗯", "是的", "对"}
        if content.lower() in greetings or len(content) <= 2:
            results.append({
                "id": "",
                "memory": content,
                "event": "SKIP",
            })
            continue

        # 检测 "我叫xxx" / "我是xxx"
        name_match = re.search(r"我(?:叫|是)([^，。,\.\s]+)", content)
        if name_match:
            name = name_match.group(1)
            memory_text = f"用户名为{name}"
            results.append({
                "id": f"mem_{uuid4().hex[:16]}",
                "memory": memory_text,
                "event": "ADD",
            })
            continue

        # 检测 "喜欢" / "偏好" / "擅长"
        if re.search(r"喜欢|偏好|擅长|常用|习惯", content):
            memory_text = f"用户偏好: {content[:80]}"
            results.append({
                "id": f"mem_{uuid4().hex[:16]}",
                "memory": memory_text,
                "event": "ADD",
            })
            continue

        # 检测 "不喜欢" / "讨厌"
        if re.search(r"不喜欢|讨厌|不想|拒绝", content):
            memory_text = f"用户排斥: {content[:80]}"
            results.append({
                "id": f"mem_{uuid4().hex[:16]}",
                "memory": memory_text,
                "event": "ADD",
            })
            continue

        # 检测 "做了xxx" / "完成了xxx" → 事实
        if re.search(r"做了|完成了|已经|之前|上次|昨天|今天", content):
            memory_text = f"相关事实: {content[:80]}"
            results.append({
                "id": f"mem_{uuid4().hex[:16]}",
                "memory": memory_text,
                "event": "ADD",
            })
            continue

        # 一般有价值的消息 → ADD
        results.append({
            "id": f"mem_{uuid4().hex[:16]}",
            "memory": content[:100],
            "event": "ADD",
        })

    return results


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
    同步写入对话记忆。

    处理管线：
    1. 鉴权（开发阶段跳过）
    2. Pydantic 校验（messages 数组格式）
    3. 逐条写入 t_interaction_record（原始记录）
    4. Mock 记忆抽取 → 生成 results
    5. 返回 {"code": 0, "data": {"results": [...]}}
    """
    start = time_module.perf_counter()

    # 合并 ID 来源（Header > Body）
    effective_user_id = normalize_id(user_id_header or body.user_id)
    effective_scene_id = scene_id or body.scene_id
    effective_session_id = body.session_id or f"sess_{uuid4().hex[:12]}"

    # --- 业务级校验（Pydantic 之上，补充 ID 格式等） ---
    if effective_user_id:
        err = validate_id_format("user_id", effective_user_id)
        if err:
            raise ValidationError(message=err)

    # --- 写入原始交互记录（逐条落库，标记 processed=False） ---
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

    # --- Mock 记忆抽取（联调期规则，正式期替换为下游 RPC 调用） ---
    mock_results = _mock_extract_memories(body.messages, effective_user_id)

    results = [
        WriteResultItem(
            id=r["id"],
            memory=r["memory"],
            event=MemoryEvent(r["event"]),
        )
        for r in mock_results
    ]

    elapsed = round((time_module.perf_counter() - start) * 1000, 2)
    logger.info(
        f"同步写入完成: user_id={effective_user_id}, "
        f"messages={len(body.messages)}, results={len(results)}, "
        f"elapsed={elapsed}ms"
    )

    return ok(MemoryWriteResponse(results=results).model_dump())


# ============================================================
# 异步写入 — 对齐前端对接文档
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

    前端文档要求：异步接口直接返回 request_id。
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
    """尝试投递到 MQ。TODO: 角色B 实现 Kafka Producer"""
    return False


async def _fallback_sync_write(
    request_id: str, user_id: str, agent_id: str, body: AsyncWriteRequest
) -> None:
    """MQ 不可用时降级为同步写入"""
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

@router.post("/search", summary="检索记忆（本地多维过滤）")
async def memory_search(
    body: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    """多维过滤检索 — 用户/场景/会话/任务/类型/时间/状态任意组合"""
    from app.services.memory_service import search_local as local_search
    filters = {
        "user_id": body.user_id,
        "agent_id": body.agent_id,
        "scene_id": body.scene_id,
        "session_id": body.session_id,
        "task_id": body.task_id,
        "memory_types": body.memory_types,
        "time_start": body.time_start,
        "time_end": body.time_end,
        "include_inactive": body.include_inactive,
    }
    results = await local_search(db, filters)
    items = [{
        "memory_id": m.memory_id, "content": m.content, "summary": m.summary,
        "memory_type": m.memory_type, "status": m.status,
        "importance": m.importance, "confidence": m.confidence,
        "tags": m.tags, "source_type": m.source_type,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    } for m in results[: body.top_k]]
    return ok({"query": body.query, "results": items, "total": len(items)})


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


@router.get("/list", summary="多维度过滤查询")
async def memory_list_filtered(
    user_id: str = Query(...),
    scene_id: str = Query(None),
    session_id: str = Query(None),
    task_id: str = Query(None),
    memory_type: str = Query(None),
    status: str = Query(None),
    time_start: str = Query(None),
    time_end: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _agent: str = Depends(get_current_agent),
):
    from datetime import datetime as dt
    filters = {"user_id": user_id}
    if scene_id: filters["scene_id"] = scene_id
    if session_id: filters["session_id"] = session_id
    if task_id: filters["task_id"] = task_id
    if memory_type: filters["memory_types"] = [memory_type]
    if status: filters["status"] = status
    if time_start: filters["time_start"] = dt.fromisoformat(time_start)
    if time_end: filters["time_end"] = dt.fromisoformat(time_end)
    items, total = await list_memories_filtered(db, filters, page, page_size)
    return ok({"items": [_memory_to_dict(m) for m in items], "total": total, "page": page, "page_size": page_size})


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


# ============================================================
# MCP 工具直通接口 — 测试用
# ============================================================

def _memory_to_dict(m) -> dict:
    return {"memory_id":m.memory_id,"content":m.content,"summary":m.summary,
            "key_points":m.key_points,"memory_type":m.memory_type,"status":m.status,
            "importance":m.importance,"confidence":m.confidence,"tags":m.tags,
            "user_id":m.user_id,"agent_id":m.agent_id,"scene_id":m.scene_id,
            "session_id":m.session_id,"task_id":m.task_id,"version":m.version,
            "created_at":m.created_at.isoformat() if m.created_at else None,
            "updated_at":m.updated_at.isoformat() if m.updated_at else None}


@router.post("/list", summary="列出全部记忆（MCP）")
async def memory_list(user_id: str = Query(...)):
    result = await mcp_client.list_memories(user_id=user_id)
    return ok(result)


@router.post("/delete-all", summary="清除全部记忆")
async def memory_delete_all(user_id: str = Query(...)):
    result = await mcp_client.delete_all_memories(user_id=user_id)
    return ok(result)
