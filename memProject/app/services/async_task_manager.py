# -*- coding: utf-8 -*-
"""
Async Task Manager — 异步任务提交与管理。

为 /memory/generate/async 提供后台任务执行能力：
  - submit(): 提交任务，返回 request_id
  - get_status(): 查询任务状态和进度
  - 使用 asyncio 后台协程执行 Pipeline
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable, Awaitable

from app.core.logger import get_logger

logger = get_logger("async_task_manager")


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncTask:
    """异步任务记录"""
    request_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0          # 0.0 - 1.0
    progress_message: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # 内部使用
    _task: Optional[asyncio.Task] = field(default=None, repr=False)


class AsyncTaskManager:
    """
    异步任务管理器（内存存储）。

    用法:
        manager = AsyncTaskManager()
        request_id = await manager.submit(
            coroutine_factory=lambda: run_pipeline(text, user_id, db),
        )
        status = manager.get_status(request_id)
    """

    # 任务过期时间（秒）
    TASK_TTL = 3600 * 24  # 24 hours

    def __init__(self, max_concurrent: int = 5) -> None:
        self._tasks: dict[str, AsyncTask] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent

    async def submit(
        self,
        coroutine_factory: Callable[[], Awaitable[dict]],
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        提交异步任务。

        Args:
            coroutine_factory: 返回可等待对象的工厂函数（在后台执行）
            progress_callback: 进度回调 (progress: float, message: str)

        Returns:
            request_id: 任务标识
        """
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        task = AsyncTask(request_id=request_id)
        self._tasks[request_id] = task

        # 创建后台任务
        async def _runner():
            await self._semaphore.acquire()
            try:
                task.status = TaskStatus.PROCESSING
                task.started_at = datetime.now(timezone.utc)
                task.progress = 0.1
                task.progress_message = "开始执行..."

                if progress_callback:
                    progress_callback(0.1, "开始执行...")

                try:
                    result = await coroutine_factory()
                    task.status = TaskStatus.COMPLETED
                    task.progress = 1.0
                    task.progress_message = "完成"
                    task.result = result
                    task.completed_at = datetime.now(timezone.utc)

                    if progress_callback:
                        progress_callback(1.0, "完成")

                    logger.info(f"Async task {request_id} completed")
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    task.progress_message = f"失败: {e}"
                    task.completed_at = datetime.now(timezone.utc)
                    logger.error(f"Async task {request_id} failed: {e}")
            finally:
                self._semaphore.release()

        task._task = asyncio.create_task(_runner())
        logger.info(f"Async task {request_id} submitted")
        return request_id

    def get_status(self, request_id: str) -> Optional[dict]:
        """
        查询任务状态。

        Returns:
            None 如果任务不存在，否则返回状态 dict
        """
        task = self._tasks.get(request_id)
        if task is None:
            return None

        result = {
            "request_id": task.request_id,
            "status": task.status.value,
            "progress": task.progress,
            "progress_message": task.progress_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }

        if task.status == TaskStatus.COMPLETED and task.result:
            result["result"] = task.result
        if task.status == TaskStatus.FAILED:
            result["error"] = task.error

        return result

    def cancel(self, request_id: str) -> bool:
        """取消任务（如果仍在执行）。"""
        task = self._tasks.get(request_id)
        if task is None:
            return False

        if task._task and not task._task.done():
            task._task.cancel()
            task.status = TaskStatus.FAILED
            task.error = "任务已取消"
            task.completed_at = datetime.now(timezone.utc)
            logger.info(f"Async task {request_id} cancelled")
            return True

        return False

    async def cleanup_expired(self) -> int:
        """清理过期任务。"""
        now = datetime.now(timezone.utc)
        expired = []
        for rid, task in self._tasks.items():
            if task.completed_at:
                age = (now - task.completed_at).total_seconds()
                if age > self.TASK_TTL:
                    expired.append(rid)
            elif task.created_at:
                age = (now - task.created_at).total_seconds()
                if age > self.TASK_TTL * 2:
                    expired.append(rid)

        for rid in expired:
            task = self._tasks.pop(rid, None)
            if task and task._task and not task._task.done():
                task._task.cancel()

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired async tasks")
        return len(expired)

    @property
    def active_count(self) -> int:
        """当前活跃（执行中）的任务数。"""
        return sum(
            1 for t in self._tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.PROCESSING)
        )

    @property
    def total_count(self) -> int:
        """任务总数。"""
        return len(self._tasks)


# 模块级单例
async_task_manager = AsyncTaskManager(max_concurrent=5)
