# -*- coding: utf-8 -*-
"""
记忆生成与去重融合 — API 端点。

提供记忆生成的同步/异步/批量接口，所有端点返回标准 ok(data) 格式。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import MemoryGenerationError
from app.core.logger import get_logger
from app.schemas.common import ok
from app.schemas.generation import (
    AsyncGenerationResponse,
    BatchGenerationRequest,
    BatchGenerationResponse,
    GenerationRequest,
    GenerationResponse,
    GenerationStatusResponse,
    MemoryGenerationDetail,
)
from app.services.memory_pipeline import memory_pipeline

logger = get_logger("generation_api")

router = APIRouter()

from app.services.async_task_manager import async_task_manager
from app.models.base import Memory


# ============================================================
# POST /memory/generate — 同步生成
# ============================================================

@router.post("/generate", summary="从文本生成结构化记忆（同步）")
async def memory_generate(
    body: GenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    输入一段对话/任务文本，执行完整流水线：
    关键记忆抽取 → 结构化记忆生成 → 去重融合 → 存储。

    返回生成的记忆 ID 列表和处理统计。

    示例请求:
    ```json
    {
        "text": "用户说他喜欢用 Python 开发，项目 deadline 是下周五，我们决定用 FastAPI 框架",
        "user_id": "user_001",
        "extraction_types": ["key_fact", "task_state", "decision"]
    }
    ```
    """
    try:
        result = await memory_pipeline.run(
            text=body.text,
            user_id=body.user_id,
            agent_id=body.agent_id,
            scene_id=body.scene_id,
            session_id=body.session_id,
            task_id=body.task_id,
            source_record_ids=body.source_record_ids,
            extraction_types=body.extraction_types,
            task_context=body.metadata,
            db=db,
        )

        details = [
            MemoryGenerationDetail(
                action=d.get("action", "keep_new"),
                memory_id=d.get("memory_id"),
                content_preview=d.get("content_preview", ""),
                memory_type=d.get("memory_type", "fact"),
                importance=d.get("importance", 0.5),
                confidence=d.get("confidence", 0.5),
                message=d.get("message", ""),
            )
            for d in result.details
        ]

        response = GenerationResponse(
            memory_ids=result.memory_ids,
            new_count=result.new_count,
            merged_count=result.merged_count,
            discarded_count=result.discarded_count,
            updated_count=result.updated_count,
            conflict_count=result.conflict_count,
            details=details,
        )
        return ok(response.model_dump())

    except MemoryGenerationError as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail={"code": e.code, "message": e.message})
    except Exception as e:
        logger.error(f"Unexpected error in memory generation: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


# ============================================================
# POST /memory/generate/batch — 批量生成
# ============================================================

@router.post("/generate/batch", summary="批量生成记忆")
async def memory_generate_batch(
    body: BatchGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    批量生成记忆，最多 50 条文本。
    每条文本独立执行完整流水线。
    """
    if len(body.texts) > 50:
        raise HTTPException(status_code=422, detail="批量生成最多支持 50 条文本")

    try:
        pipeline_results = await memory_pipeline.run_batch(
            texts=body.texts,
            user_id=body.user_id,
            agent_id=body.agent_id,
            scene_id=body.scene_id,
            session_id=body.session_id,
            task_id=body.task_id,
            extraction_types=body.extraction_types,
            db=db,
        )

        results = []
        for pr in pipeline_results:
            details = [
                MemoryGenerationDetail(
                    action=d.get("action", "keep_new"),
                    memory_id=d.get("memory_id"),
                    content_preview=d.get("content_preview", ""),
                    memory_type=d.get("memory_type", "fact"),
                    importance=d.get("importance", 0.5),
                    confidence=d.get("confidence", 0.5),
                    message=d.get("message", ""),
                )
                for d in pr.details
            ]
            results.append(GenerationResponse(
                memory_ids=pr.memory_ids,
                new_count=pr.new_count,
                merged_count=pr.merged_count,
                discarded_count=pr.discarded_count,
                updated_count=pr.updated_count,
                details=details,
            ))

        batch_response = BatchGenerationResponse(
            results=[r.model_dump() for r in results],
            total_memories=sum(r.new_count + r.merged_count + r.updated_count for r in results),
            total_new=sum(r.new_count for r in results),
            total_merged=sum(r.merged_count for r in results),
            total_discarded=sum(r.discarded_count for r in results),
        )
        return ok(batch_response.model_dump())

    except MemoryGenerationError as e:
        raise HTTPException(status_code=500, detail={"code": e.code, "message": e.message})
    except Exception as e:
        logger.error(f"Batch generation failed: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


# ============================================================
# POST /memory/generate/async — 异步提交
# ============================================================

@router.post("/generate/async", summary="异步生成记忆")
async def memory_generate_async(
    body: GenerationRequest,
    background_tasks: BackgroundTasks,
):
    """
    提交异步记忆生成任务，立即返回 request_id。
    后台执行完整 Pipeline，通过 GET /memory/generate/{request_id}/status 查询进度。

    支持最多 5 个并发任务，超额排队等待。
    """
    # 捕获所需参数（FastAPI DI 在后台任务中不可用）
    text = body.text
    user_id = body.user_id
    agent_id = body.agent_id
    scene_id = body.scene_id
    session_id = body.session_id
    task_id = body.task_id
    source_record_ids = body.source_record_ids
    extraction_types = body.extraction_types
    metadata = body.metadata

    async def run_pipeline() -> dict:
        """后台执行 Pipeline（独立 DB 会话）。"""
        from app.core.database import async_session_factory

        async with async_session_factory() as db:
            result = await memory_pipeline.run(
                text=text,
                user_id=user_id,
                agent_id=agent_id,
                scene_id=scene_id,
                session_id=session_id,
                task_id=task_id,
                source_record_ids=source_record_ids,
                extraction_types=extraction_types,
                task_context=metadata,
                db=db,
            )

            return {
                "memory_ids": result.memory_ids,
                "new_count": result.new_count,
                "merged_count": result.merged_count,
                "discarded_count": result.discarded_count,
                "updated_count": result.updated_count,
                "conflict_count": result.conflict_count,
                "details": result.details,
            }

    request_id = await async_task_manager.submit(
        coroutine_factory=run_pipeline,
    )

    return ok(AsyncGenerationResponse(
        request_id=request_id,
        status="accepted",
        message=f"任务已提交 (当前队列: {async_task_manager.active_count - 1 if async_task_manager.active_count > 0 else 0})",
    ).model_dump())


# ============================================================
# GET /memory/generate/{request_id}/status — 查询异步状态
# ============================================================

@router.get("/generate/{request_id}/status", summary="查询异步生成状态")
async def memory_generate_status(request_id: str):
    """
    查询异步记忆生成任务的状态。
    返回 progress (0.0-1.0)、status、完成后的 result、失败时的 error。
    """
    task = async_task_manager.get_status(request_id)
    if task is None:
        return ok(GenerationStatusResponse(
            request_id=request_id,
            status="not_found",
            error="任务不存在或已过期",
        ).model_dump())

    result = None
    if task.get("result"):
        result = GenerationResponse(**task["result"])

    return ok(GenerationStatusResponse(
        request_id=request_id,
        status=task.get("status", "unknown"),
        progress=task.get("progress", 0.0),
        result=result,
        error=task.get("error"),
    ).model_dump())


# ============================================================
# POST /memory/compress — 长对话压缩 (Section 5.4.1)
# ============================================================

from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField


class CompressRequest(PydanticBaseModel):
    text: str = PydanticField(..., description="长对话文本")
    validate_preservation: bool = PydanticField(True, description="是否验证关键信息保留")


class CompressResponse(PydanticBaseModel):
    conversation_overview: str
    key_facts_count: int
    preferences_count: int
    decisions_count: int
    corrections_count: int
    original_length: int
    compressed_length: int
    compression_ratio: float
    preservation_score: float
    compact_text: str


@router.post("/compress", summary="压缩长对话为结构化记忆 (Section 5.4)")
async def memory_compress(body: CompressRequest):
    """压缩长对话历史，保留关键事实/偏好/任务状态/决策/修正记录。"""
    from app.services.memory_compressor import get_compressor

    compressor = get_compressor()
    compressed = await compressor.compress_and_validate(
        body.text,
        validate_preservation=body.validate_preservation,
    )

    return ok(CompressResponse(
        conversation_overview=compressed.conversation_overview,
        key_facts_count=len(compressed.key_facts),
        preferences_count=len(compressed.user_preferences),
        decisions_count=len(compressed.key_decisions),
        corrections_count=len(compressed.corrections_and_feedback),
        original_length=compressed.original_length,
        compressed_length=compressed.compressed_length,
        compression_ratio=compressed.compression_ratio,
        preservation_score=compressed.preservation_score,
        compact_text=compressed.to_compact_text(),
    ).model_dump())


# ============================================================
# POST /memory/context/complete — 历史上下文补全 (Section 5.4.3)
# ============================================================

class ContextCompleteRequest(PydanticBaseModel):
    query: str = PydanticField(..., description="当前用户查询")
    memory_ids: list[str] = PydanticField(..., description="相关历史记忆 ID 列表")
    max_context_tokens: int = PydanticField(3000, description="最大上下文 token 数")


class ContextCompleteResponse(PydanticBaseModel):
    context_text: str
    sections_used: list[str]
    estimated_relevance: float


@router.post("/context/complete", summary="基于历史压缩记忆补全上下文 (Section 5.4.3)")
async def memory_context_complete(
    body: ContextCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """从已存储的压缩记忆中检索并补全当前查询所需的历史上下文。"""
    from app.services.memory_compressor import get_compressor
    from app.services.memory_store import memory_store
    from sqlalchemy import select as _select

    # 从 DB 加载记忆
    memories_data = []
    for mid in body.memory_ids:
        result = await db.execute(_select(Memory).where(Memory.memory_id == mid))
        mem = result.scalar_one_or_none()
        if mem:
            memories_data.append({
                "id": mem.memory_id,
                "content": mem.content,
                "summary": mem.summary or "",
                "memory_type": mem.memory_type,
            })

    if not memories_data:
        return ok(ContextCompleteResponse(
            context_text="",
            sections_used=[],
            estimated_relevance=0.0,
        ).model_dump())

    # 构建压缩记忆对象
    from app.services.memory_compressor import CompressedMemory
    compressed_list = []
    for md in memories_data:
        cm = CompressedMemory(
            conversation_overview=md["summary"],
            key_facts=[{"fact": md["content"], "category": "background", "importance": 0.5}],
            important_context=[md["content"]],
        )
        compressed_list.append(cm)

    compressor = get_compressor()
    result = await compressor.complete_context(
        query=body.query,
        compressed_memories=compressed_list,
        max_context_tokens=body.max_context_tokens,
    )

    return ok(ContextCompleteResponse(
        context_text=result["context_text"],
        sections_used=result["sections_used"],
        estimated_relevance=result["estimated_relevance"],
    ).model_dump())
