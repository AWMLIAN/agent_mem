# -*- coding: utf-8 -*-
"""
使用 continue_zh.jsonl 数据集进行完整集成测试（含 DB + Qdrant 持久化）。

运行方式：
  python tests/test_integration_full.py
"""

import json
import sys
import asyncio
import time
import os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.services.memory_pipeline import memory_pipeline
from app.services.memory_store import memory_store
from app.core.qdrant_client import qdrant_client
from app.services.llm_client import llm_client
from app.services.embedding_client import embedding_client
from app.models.base import Memory

DATASET_PATH = "E:/AI Memory/continue_zh.jsonl"
DB_URL = "postgresql+asyncpg://memuser:mempassword@localhost:5432/agent_memory"


def load_and_build_texts(path: str, sample_size: int = 8, max_turns: int = 4) -> list[dict]:
    """加载对话并构建测试文本。"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if len(records) >= sample_size:
                break
            try:
                data = json.loads(line)
                conv = data.get("conversation", [])
                parts = []
                for turn in conv[:max_turns]:
                    h = turn.get("human", "")
                    a = turn.get("assistant", "")
                    if h: parts.append(f"[用户]: {h}")
                    if a: parts.append(f"[助手]: {a}")
                text = "\n".join(parts)[:3000]
                data["_text"] = text
                records.append(data)
            except Exception:
                pass
    return records


async def main():
    print("=" * 60)
    print("  完整集成测试 (DB + Qdrant + LLM)")
    print("=" * 60)

    # 1. 初始化 Qdrant
    print("\n[1] 初始化 Qdrant...")
    qdrant_ok = qdrant_client.initialize()
    print(f"    Qdrant: {'[OK]' if qdrant_ok else '[XX] 初始化失败'}")

    # 2. 初始化 DB
    print("[2] 初始化 PostgreSQL...")
    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 确保表存在
    from app.core.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("    DB: [OK] 连接成功，表已就绪")

    # 3. 加载数据
    print(f"[3] 加载数据集...")
    records = load_and_build_texts(DATASET_PATH, sample_size=8, max_turns=4)
    print(f"    已加载 {len(records)} 条对话")

    # 4. 流水线端到端测试
    print(f"\n[4] 运行 MemoryPipeline (extract -> value -> generate -> quality -> dedup -> store)...")
    total_new = 0
    total_merged = 0
    total_discarded = 0
    total_updated = 0
    total_conflict = 0
    total_memories = 0
    errors = 0
    all_actions = {}

    t0 = time.time()

    # 第一轮：建立初始记忆
    first_rec = records[0]
    async with session_factory() as db:
        result = await memory_pipeline.run(
            text=first_rec["_text"],
            user_id="test_user_001",
            agent_id="test_agent",
            scene_id="integration_test",
            session_id=first_rec.get("conversation_id", "sess_001"),
            task_id="task_integration_001",
            db=db,
        )
        total_new += result.new_count
        total_merged += result.merged_count
        total_discarded += result.discarded_count
        total_updated += result.updated_count
        total_conflict += result.conflict_count
        total_memories += len(result.memory_ids)
        for d in result.details:
            all_actions[d.get("action", "?")] = all_actions.get(d.get("action", "?"), 0) + 1

        print(f"    Round 1 (首轮): new={result.new_count}, merge={result.merged_count}, "
              f"discard={result.discarded_count}, update={result.updated_count}, "
              f"conflict={result.conflict_count} -> total_memories={len(result.memory_ids)}")

        # 同时搜索验证
        if result.memory_ids:
            search_result = await memory_store.search(
                query=first_rec["_text"][:200],
                user_id="test_user_001",
                db=db,
                top_k=3,
            )
            print(f"    搜索验证: 找到 {search_result.get('total_candidates', 0)} 条相关记忆")
            for item in search_result.get("results", [])[:3]:
                preview = item.get("content", "")[:80]
                score = item.get("score", 0)
                print(f"      [{score:.3f}] {preview}...")

    # 第二轮：同一用户、同一任务，发送额外对话（测试去重）
    print()
    second_rec = records[1]
    async with session_factory() as db:
        result2 = await memory_pipeline.run(
            text=second_rec["_text"],
            user_id="test_user_001",  # 同一用户
            agent_id="test_agent",
            scene_id="integration_test",
            session_id=second_rec.get("conversation_id", "sess_002"),
            task_id="task_integration_001",  # 同一任务
            db=db,
        )
        total_new += result2.new_count
        total_merged += result2.merged_count
        total_discarded += result2.discarded_count
        total_updated += result2.updated_count
        total_conflict += result2.conflict_count
        total_memories += len(result2.memory_ids)
        for d in result2.details:
            all_actions[d.get("action", "?")] = all_actions.get(d.get("action", "?"), 0) + 1

        print(f"    Round 2 (同用户/同任务): new={result2.new_count}, merge={result2.merged_count}, "
              f"discard={result2.discarded_count}, update={result2.updated_count}, "
              f"conflict={result2.conflict_count} -> total_memories={len(result2.memory_ids)}")

    # 第三轮：不同用户（测试隔离）
    print()
    async with session_factory() as db:
        result3 = await memory_pipeline.run(
            text=first_rec["_text"],  # 与第一轮相同的文本
            user_id="test_user_002",   # 不同用户
            agent_id="test_agent",
            scene_id="integration_test",
            session_id="sess_003",
            task_id="task_integration_002",
            db=db,
        )
        total_new += result3.new_count
        total_merged += result3.merged_count
        total_discarded += result3.discarded_count
        total_updated += result3.updated_count
        total_conflict += result3.conflict_count
        total_memories += len(result3.memory_ids)
        for d in result3.details:
            all_actions[d.get("action", "?")] = all_actions.get(d.get("action", "?"), 0) + 1

        print(f"    Round 3 (不同用户): new={result3.new_count}, merge={result3.merged_count}, "
              f"discard={result3.discarded_count}, update={result3.updated_count}, "
              f"conflict={result3.conflict_count} -> total_memories={len(result3.memory_ids)}")

    t1 = time.time()

    # 5. 验证持久化
    print(f"\n[5] 验证持久化...")
    async with session_factory() as db:
        from sqlalchemy import select, func
        # 按用户统计
        for uid in ["test_user_001", "test_user_002"]:
            result = await db.execute(
                select(func.count()).select_from(Memory).where(Memory.user_id == uid)
            )
            count = result.scalar()
            result2 = await db.execute(
                select(Memory.status, func.count())
                .where(Memory.user_id == uid)
                .group_by(Memory.status)
            )
            statuses = {row[0]: row[1] for row in result2.all()}
            print(f"    {uid}: {count} 条记忆, 状态分布: {statuses}")

        # 按类型统计
        result = await db.execute(
            select(Memory.memory_type, func.count())
            .group_by(Memory.memory_type)
        )
        type_counts = {row[0]: row[1] for row in result.all()}
        print(f"    类型分布: {type_counts}")

        # 检查审计记录
        from app.models.base import DedupAudit
        result = await db.execute(
            select(func.count()).select_from(DedupAudit)
        )
        audit_count = result.scalar()
        print(f"    审计记录: {audit_count} 条")

    # 6. 上下文返回测试
    print(f"\n[6] 测试 get_context...")
    async with session_factory() as db:
        ctx = await memory_store.get_context(
            query="编程偏好和技术选型",
            user_id="test_user_001",
            db=db,
            max_tokens=2000,
        )
        print(f"    记忆数: {ctx.get('memory_count', 0)}")
        print(f"    估算 Token: {ctx.get('estimated_tokens', 0)}")
        formatted = ctx.get("formatted_text", "")
        print(f"    格式化文本前 200 字符:\n{formatted[:200]}...")

    # 总结
    print(f"\n{'='*60}")
    print(f"  总结")
    print(f"{'='*60}")
    print(f"  总耗时: {t1 - t0:.1f}s")
    print(f"  总记忆数: {total_memories}")
    print(f"  动作分布: {all_actions}")
    print(f"  新增={total_new}, 合并={total_merged}, 丢弃={total_discarded}, "
          f"更新={total_updated}, 冲突={total_conflict}")
    print(f"  异常数: {errors}")

    # 清理资源
    await engine.dispose()

    if errors == 0:
        print(f"\n  [OK] 全部集成测试通过！")
    else:
        print(f"\n  [!!] 存在 {errors} 个异常")


if __name__ == "__main__":
    asyncio.run(main())
