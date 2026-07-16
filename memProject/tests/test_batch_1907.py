# -*- coding: utf-8 -*-
"""
全量 1,907 条对话批量测试 —— 验证 Qdrant 去重性能与准确性。

运行方式：python tests/test_batch_1907.py
"""

import json
import sys
import asyncio
import time
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, func

from app.services.memory_pipeline import memory_pipeline, MemoryPipeline
from app.services.memory_store import memory_store
from app.core.qdrant_client import qdrant_client
from app.services.llm_client import llm_client
from app.services.embedding_client import embedding_client
from app.models.base import Memory, DedupAudit, MemoryRelation
from app.core.database import Base


# ==================== 配置 ====================
DATASET_PATH = "E:/AI Memory/continue_zh.jsonl"
DB_URL = "postgresql+asyncpg://memuser:mempassword@localhost:5432/agent_memory"
BATCH_SIZE = 20          # 每批处理条数（控制 LLM 并发）
MAX_TURNS = 3            # 每条对话取前 N 轮
MAX_TEXT_LEN = 2500      # 单次输入最大字符数
CHECKPOINT_EVERY = 50    # 每 N 条打印进度
TEST_USERS = 5           # 将对话分散到 N 个用户


def load_all(path: str) -> list[dict]:
    """加载全部对话。"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


# 进度日志文件（实时写入，不受 stdout 缓冲影响）
PROGRESS_LOG = Path("E:/AI Memory/agent_mem/memProject/tests/batch_progress.log")

def log(msg: str):
    """同时打印到 stdout 和写入进度日志。"""
    print(msg, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def build_text(conv: list[dict]) -> str:
    parts = []
    for turn in conv[:MAX_TURNS]:
        h = turn.get("human", "")
        a = turn.get("assistant", "")
        if h: parts.append(f"[用户]: {h}")
        if a: parts.append(f"[助手]: {a}")
    text = "\n".join(parts)
    return text[:MAX_TEXT_LEN]


async def main():
    log("=" * 60)
    log("  全量 1,907 条对话批量测试")
    log("=" * 60)

    # ---- 初始化 ----
    log("\n[1/5] 初始化服务...")
    t0 = time.time()

    qdrant_client.initialize()
    log(f"  Qdrant: {'OK' if qdrant_client.is_available else 'FAIL'}")

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log("  PostgreSQL: OK")

    # 清空旧测试数据
    async with session_factory() as db:
        await db.execute(Memory.__table__.delete())
        await db.execute(DedupAudit.__table__.delete())
        await db.execute(MemoryRelation.__table__.delete())
        await db.commit()
    log("  已清空旧测试数据")

    # ---- 加载数据 ----
    log(f"\n[2/5] 加载数据集...")
    records = load_all(DATASET_PATH)
    log(f"  已加载 {len(records)} 条对话")

    # ---- 批量执行 ----
    log(f"\n[3/5] 开始批量执行 Pipeline...")
    log(f"  批次大小: {BATCH_SIZE}, 预计总批次: {len(records)//BATCH_SIZE + 1}")

    stats = {
        "total": 0, "errors": 0,
        "new": 0, "merged": 0, "discarded": 0, "updated": 0, "conflict": 0,
        "total_memories": 0,
        "actions": defaultdict(int),
        "types": defaultdict(int),
        "latencies": [],
        "text_lens": [],
    }
    per_user_stats = defaultdict(lambda: {"count": 0, "memories": 0})

    batch_start = time.time()
    pipeline_start = time.time()

    for batch_idx in range(0, len(records), BATCH_SIZE):
        batch = records[batch_idx:batch_idx + BATCH_SIZE]

        for i, rec in enumerate(batch):
            global_idx = batch_idx + i
            text = build_text(rec.get("conversation", []))
            stats["text_lens"].append(len(text))

            # 分散到不同用户
            user_id = f"batch_user_{(global_idx % TEST_USERS) + 1}"
            conv_id = rec.get("conversation_id", f"conv_{global_idx}")

            per_user_stats[user_id]["count"] += 1

            t_start = time.time()
            try:
                async with session_factory() as db:
                    result = await memory_pipeline.run(
                        text=text,
                        user_id=user_id,
                        agent_id="batch_test_agent",
                        scene_id="batch_test",
                        session_id=conv_id,
                        task_id=f"task_{(global_idx % 50) + 1}",
                        db=db,
                    )

                elapsed = time.time() - t_start
                stats["latencies"].append(elapsed)
                stats["total"] += 1
                stats["new"] += result.new_count
                stats["merged"] += result.merged_count
                stats["discarded"] += result.discarded_count
                stats["updated"] += result.updated_count
                stats["conflict"] += result.conflict_count
                stats["total_memories"] += len(result.memory_ids)
                per_user_stats[user_id]["memories"] += len(result.memory_ids)

                for d in result.details:
                    action = d.get("action", "?")
                    stats["actions"][action] += 1
                    mtype = d.get("memory_type", "?")
                    stats["types"][mtype] += 1

            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    log(f"  [ERROR] #{global_idx}: {str(e)[:100]}")

            # 进度检查点
            if (global_idx + 1) % CHECKPOINT_EVERY == 0:
                elapsed = time.time() - batch_start
                rate = CHECKPOINT_EVERY / elapsed if elapsed > 0 else 0
                total_elapsed = time.time() - pipeline_start
                avg_latency = sum(stats["latencies"][-100:]) / min(len(stats["latencies"][-100:]), 1)

                log(f"  [{global_idx + 1}/{len(records)}] "
                      f"rate={rate:.2f}/s, avg={avg_latency:.1f}s/item, "
                      f"total_elapsed={total_elapsed:.0f}s, "
                      f"mem={stats['total_memories']}, "
                      f"err={stats['errors']}, "
                      f"new={stats['new']} merge={stats['merged']} "
                      f"discard={stats['discarded']} update={stats['updated']} "
                      f"conflict={stats['conflict']}")
                batch_start = time.time()

    pipeline_duration = time.time() - pipeline_start

    # ---- 结果统计 ----
    log(f"\n[4/5] 收集统计数据...")

    async with session_factory() as db:
        # 总记忆数
        total_result = await db.execute(select(func.count()).select_from(Memory))
        db_total = total_result.scalar()

        # 按状态
        status_result = await db.execute(
            select(Memory.status, func.count()).group_by(Memory.status)
        )
        status_dist = {row[0]: row[1] for row in status_result.all()}

        # 按类型
        type_result = await db.execute(
            select(Memory.memory_type, func.count()).group_by(Memory.memory_type)
        )
        type_dist = {row[0]: row[1] for row in type_result.all()}

        # 审计记录
        audit_result = await db.execute(select(func.count()).select_from(DedupAudit))
        audit_count = audit_result.scalar()

        # 关系记录
        rel_result = await db.execute(select(func.count()).select_from(MemoryRelation))
        rel_count = rel_result.scalar()

        # 按用户统计
        user_dist = {}
        for uid in [f"batch_user_{i}" for i in range(1, TEST_USERS + 1)]:
            result = await db.execute(
                select(func.count()).select_from(Memory).where(Memory.user_id == uid)
            )
            user_dist[uid] = result.scalar()

    # ---- 输出去重准确性报告 ----
    log(f"\n[5/5] 生成报告...")

    total_processed = stats["total"]
    total_actions = sum(stats["actions"].values())
    dedup_rate = (
        (stats["merged"] + stats["discarded"] + stats["updated"] + stats["conflict"])
        / max(total_actions, 1)
    ) if total_actions > 0 else 0

    avg_latency = sum(stats["latencies"]) / max(len(stats["latencies"]), 1)
    latencies_sorted = sorted(stats["latencies"])
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0
    p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else 0

    total_duration = time.time() - t0

    log(f"\n{'='*60}")
    log(f"  全量批量测试报告")
    log(f"{'='*60}")

    log(f"\n  ── 总体指标 ──")
    log(f"  处理条数: {total_processed}/{len(records)}")
    log(f"  总耗时: {total_duration:.0f}s ({total_duration/60:.1f}min)")
    log(f"  流水线耗时: {pipeline_duration:.0f}s ({pipeline_duration/60:.1f}min)")
    log(f"  DB 记忆总数: {db_total}")
    log(f"  异常数: {stats['errors']}")

    log(f"\n  ── 性能指标 ──")
    log(f"  平均延迟: {avg_latency:.1f}s/条")
    log(f"  P50 延迟: {p50:.1f}s")
    log(f"  P95 延迟: {p95:.1f}s")
    log(f"  P99 延迟: {p99:.1f}s")
    log(f"  吞吐量: {total_processed/pipeline_duration:.2f} 条/秒" if pipeline_duration > 0 else "")

    log(f"\n  ── 去重效果 ──")
    log(f"  总动作数: {total_actions}")
    log(f"  去重命中率: {dedup_rate:.1%}")
    log(f"  新增: {stats['new']} ({stats['new']/max(total_actions,1):.1%})")
    log(f"  合并: {stats['merged']} ({stats['merged']/max(total_actions,1):.1%})")
    log(f"  丢弃: {stats['discarded']} ({stats['discarded']/max(total_actions,1):.1%})")
    log(f"  更新: {stats['updated']} ({stats['updated']/max(total_actions,1):.1%})")
    log(f"  冲突: {stats['conflict']} ({stats['conflict']/max(total_actions,1):.1%})")

    log(f"\n  ── 记忆分布 ──")
    log(f"  状态: {status_dist}")
    log(f"  类型: {type_dist}")
    log(f"  用户: {user_dist}")

    log(f"\n  ── 数据完整性 ──")
    log(f"  审计记录: {audit_count}")
    log(f"  关系图谱: {rel_count} 条边")

    log(f"\n  ── 动作详情 ──")
    for action in ["keep_new", "merge", "discard", "update_existing", "conflict"]:
        count = stats["actions"].get(action, 0)
        bar = "█" * int(count / max(total_actions, 1) * 30)
        log(f"  {action:20s}: {count:5d} {bar}")

    # 保存详细报告到 JSON
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_processed": total_processed,
            "total_duration_s": round(total_duration, 1),
            "pipeline_duration_s": round(pipeline_duration, 1),
            "avg_latency_s": round(avg_latency, 1),
            "p50_latency_s": round(p50, 1),
            "p95_latency_s": round(p95, 1),
            "p99_latency_s": round(p99, 1),
            "throughput_per_s": round(total_processed / pipeline_duration, 2) if pipeline_duration > 0 else 0,
            "db_total_memories": db_total,
            "errors": stats["errors"],
            "dedup_hit_rate": round(dedup_rate, 3),
        },
        "dedup": {
            "new": stats["new"],
            "merged": stats["merged"],
            "discarded": stats["discarded"],
            "updated": stats["updated"],
            "conflict": stats["conflict"],
            "total_actions": total_actions,
        },
        "distribution": {
            "status": status_dist,
            "types": type_dist,
            "users": user_dist,
        },
        "integrity": {
            "audit_records": audit_count,
            "relation_edges": rel_count,
        },
    }

    report_path = "E:/AI Memory/agent_mem/memProject/tests/batch_1907_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n  详细报告已保存至: {report_path}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
