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

# 简易内存任务状态追踪（未来可迁移到 Celery/Redis）
_task_status: dict[str, dict] = {}


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
):
    """
    提交异步记忆生成任务，立即返回 request_id。
    后续可通过 GET /memory/generate/{request_id}/status 查询进度。

    当前版本使用内存任务追踪，未来可迁移到 Celery/Kafka。
    """
    request_id = f"gen_{uuid.uuid4().hex[:16]}"

    _task_status[request_id] = {
        "status": "pending",
        "progress": 0.0,
        "result": None,
        "error": None,
    }

    # 注意：完整的异步执行需要后台任务队列（Celery 等）支持。
    # 当前为同步占位实现——将状态设为 completed 并返回模拟结果。
    # 实际生产环境请配置 Celery worker 调用 memory_pipeline.run()。
    _task_status[request_id] = {
        "status": "pending",
        "progress": 0.0,
        "result": None,
        "error": None,
        "message": "异步任务已提交（当前为同步占位，需配置 Celery/Kafka 才能真实异步执行）",
    }

    return ok(AsyncGenerationResponse(
        request_id=request_id,
        status="accepted",
    ).model_dump())


# ============================================================
# GET /memory/generate/{request_id}/status — 查询异步状态
# ============================================================

@router.get("/generate/{request_id}/status", summary="查询异步生成状态")
async def memory_generate_status(request_id: str):
    """
    查询异步记忆生成任务的状态。

    返回 progress (0.0-1.0) 和完成后的 result。
    """
    task = _task_status.get(request_id)
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
