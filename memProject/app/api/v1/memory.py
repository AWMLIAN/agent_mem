# -*- coding: utf-8 -*-
"""记忆核心 API。写入走 MCP，检索走 mem0 多信号融合。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.mcp_client import mcp_client
from app.schemas.common import ok
from app.schemas.memory import (
    MemoryWriteRequest,
    MemorySearchRequest,
    ContextRequest,
    MemoryUpdateRequest,
    MemoryDeleteRequest,
)

router = APIRouter()


@router.post("/write", summary="存储记忆（直接调 mem0，支持 metadata）")
async def memory_write(body: MemoryWriteRequest, db: AsyncSession = Depends(get_db)):
    from app.services.mem0_client import mem0_client as mc
    # 构建 metadata：存入自定义字段，供检索时过滤
    meta = {}
    if body.scene_id: meta["scene_id"] = body.scene_id
    if body.session_id: meta["session_id"] = body.session_id
    if body.task_id: meta["task_id"] = body.task_id
    text = body.messages[0].content if body.messages else ""
    # 要求 LLM 用中文抽取记忆，确保中文关键词检索可用
    messages = [{"role": msg.role, "content": msg.content} for msg in body.messages]
    messages.insert(0, {"role": "system", "content": "请用中文提取和记录所有记忆内容。"})
    result = mc.add(
        messages,
        user_id=body.user_id,
        metadata=meta or None,
    )
    return ok(result)


@router.post("/async_write", summary="异步写入（Kafka）")
async def memory_async_write(body: MemoryWriteRequest):
    return ok({"request_id": "placeholder", "status": "accepted"})


@router.post("/search", summary="多信号融合检索（语义+BM25+实体+元数据过滤）")
async def memory_search(body: MemorySearchRequest, db: AsyncSession = Depends(get_db)):
    from app.services.retrieval_service import search as retrieval_search
    result = retrieval_search(
        query=body.query,
        user_id=body.user_id,
        agent_id=body.agent_id,
        scene_id=body.scene_id,
        session_id=body.session_id,
        task_id=body.task_id,
        memory_types=body.memory_types,
        time_start=body.time_start.isoformat() if body.time_start else None,
        time_end=body.time_end.isoformat() if body.time_end else None,
        top_k=body.top_k,
        include_inactive=body.include_inactive,
        include_scores=body.include_scores,
        rerank=body.rerank,
    )
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
