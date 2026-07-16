# -*- coding: utf-8 -*-
"""200条对话批量测试 —— 验证去重性能与准确性。"""
import json, sys, asyncio, time
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, func
from app.services.memory_pipeline import memory_pipeline
from app.core.qdrant_client import qdrant_client
from app.models.base import Memory, DedupAudit, MemoryRelation
from app.core.database import Base

DATASET = "E:/AI Memory/continue_zh.jsonl"
DB = "postgresql+asyncpg://memuser:mempassword@localhost:5432/agent_memory"
N = 200   # 目标样本量
USERS = 5
REPORT_PATH = "E:/AI Memory/agent_mem/memProject/tests/batch_200_report.json"
PROGRESS_PATH = "E:/AI Memory/agent_mem/memProject/tests/batch_200_progress.txt"

def load_n(path, n):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if len(recs) >= n: break
            try: recs.append(json.loads(line))
            except: pass
    return recs

def build(conv):
    parts = []
    for t in conv[:3]:
        h, a = t.get("human",""), t.get("assistant","")
        if h: parts.append(f"[用户]: {h}")
        if a: parts.append(f"[助手]: {a}")
    return "\n".join(parts)[:2500]

async def main():
    t0 = time.time()
    qdrant_client.initialize()
    engine = create_async_engine(DB, echo=False)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 清空旧数据
    async with sf() as db:
        for tbl in [Memory, DedupAudit, MemoryRelation]:
            await db.execute(tbl.__table__.delete())
        await db.commit()

    recs = load_n(DATASET, N)
    total = len(recs)
    print(f"Loaded {total} conversations", flush=True)

    st = {"ok":0, "err":0, "new":0, "merge":0, "discard":0, "update":0, "conflict":0,
          "mems":0, "actions":defaultdict(int), "types":defaultdict(int), "lats":[]}
    batch_start = time.time()

    # 写入进度头
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(f"Batch test: {total} conversations\n")

    for idx, rec in enumerate(recs):
        text = build(rec.get("conversation", []))
        uid = f"user_{(idx % USERS) + 1}"
        cid = rec.get("conversation_id", f"c{idx}")

        t1 = time.time()
        try:
            async with sf() as db:
                r = await memory_pipeline.run(
                    text=text, user_id=uid, agent_id="batch",
                    scene_id="test", session_id=cid,
                    task_id=f"t_{(idx % 25) + 1}", db=db)
            st["lats"].append(time.time() - t1)
            st["ok"] += 1
            st["new"] += r.new_count; st["merge"] += r.merged_count
            st["discard"] += r.discarded_count; st["update"] += r.updated_count
            st["conflict"] += r.conflict_count
            st["mems"] += len(r.memory_ids)
            for d in r.details:
                st["actions"][d.get("action","?")] += 1
                st["types"][d.get("memory_type","?")] += 1
        except Exception as e:
            st["err"] += 1

        # 每 20 条写进度
        if (idx + 1) % 20 == 0:
            elapsed = time.time() - batch_start
            rate = 20 / elapsed
            avg_lat = sum(st["lats"][-20:]) / len(st["lats"][-20:])
            msg = (f"[{idx+1}/{total}] rate={rate:.2f}/s avg={avg_lat:.1f}s "
                   f"mems={st['mems']} err={st['err']} "
                   f"new={st['new']} merge={st['merge']} discard={st['discard']} "
                   f"update={st['update']} conflict={st['conflict']}")
            print(msg, flush=True)
            with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            batch_start = time.time()

    dur = time.time() - t0

    # 收集 DB 统计
    async with sf() as db:
        db_total = (await db.execute(select(func.count()).select_from(Memory))).scalar()
        r = await db.execute(select(Memory.status, func.count()).group_by(Memory.status))
        status_dist = dict(r.all())
        r = await db.execute(select(Memory.memory_type, func.count()).group_by(Memory.memory_type))
        type_dist = dict(r.all())
        r = await db.execute(select(Memory.user_id, func.count()).group_by(Memory.user_id))
        user_dist = dict(r.all())
        audit = (await db.execute(select(func.count()).select_from(DedupAudit))).scalar()
        rels = (await db.execute(select(func.count()).select_from(MemoryRelation))).scalar()

    # 计算去重率
    ta = sum(st["actions"].values())
    dedup_hit = (st["merge"] + st["discard"] + st["update"] + st["conflict"]) / max(ta, 1)

    lats = sorted(st["lats"])
    p50 = lats[len(lats)//2] if lats else 0
    p95 = lats[int(len(lats)*0.95)] if lats else 0

    # 输出最终报告
    report = f"""
{'='*60}
  批量测试报告 ({total} 条对话)
{'='*60}

── 总体 ──
处理: {st['ok']}/{total} 成功, {st['err']} 异常
耗时: {dur:.0f}s ({dur/60:.1f}min)
DB 记忆: {db_total}
吞吐: {st['ok']/dur:.2f} 条/秒

── 性能 ──
平均延迟: {sum(st['lats'])/max(len(st['lats']),1):.1f}s
P50: {p50:.1f}s  P95: {p95:.1f}s

── 去重效果 ──
总动作: {ta}  去重命中率: {dedup_hit:.1%}
新增: {st['new']}  合并: {st['merge']}  丢弃: {st['discard']}
更新: {st['update']}  冲突: {st['conflict']}

── 记忆分布 ──
状态: {status_dist}
类型: {dict(sorted(type_dist.items(), key=lambda x:-x[1]))}
用户: {user_dist}

── 数据完整性 ──
审计: {audit}  关系: {rels}
"""
    print(report, flush=True)
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(report)

    # JSON 报告
    jr = {
        "total_processed": st["ok"], "errors": st["err"],
        "duration_s": round(dur, 1), "throughput": round(st["ok"]/dur, 2),
        "avg_latency_s": round(sum(st["lats"])/max(len(st["lats"]),1), 1),
        "p50_s": round(p50, 1), "p95_s": round(p95, 1),
        "dedup_hit_rate": round(dedup_hit, 3),
        "actions": dict(st["actions"]),
        "status": status_dist, "types": type_dist,
        "users": user_dist, "audit": audit, "relations": rels,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(jr, f, ensure_ascii=False, indent=2)
    print(f"\nReports saved: {REPORT_PATH}, {PROGRESS_PATH}", flush=True)

    await engine.dispose()

asyncio.run(main())
