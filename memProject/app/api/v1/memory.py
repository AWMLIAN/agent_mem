# -*- coding: utf-8 -*-
"""记忆核心 API — 通过 MCP Client 调用 OpenMemory MCP Server。"""

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


@router.post("/write", summary="存储记忆（MCP add_memories）")
async def memory_write(body: MemoryWriteRequest, db: AsyncSession = Depends(get_db)):
    text = body.messages[0].content if body.messages else ""
    result = await mcp_client.add_memories(text=text, user_id=body.user_id)
    return ok(result)


@router.post("/async_write", summary="异步写入（Kafka）")
async def memory_async_write(body: MemoryWriteRequest):
    return ok({"request_id": "placeholder", "status": "accepted"})


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
