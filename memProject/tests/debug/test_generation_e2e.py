# -*- coding: utf-8 -*-
"""
记忆生成流水线 — E2E 演示脚本。

用法:
  # 基础测试（仅 LLM + Embedding，不需要数据库）
  python tests/debug/test_generation_e2e.py basic

  # 完整测试（需要 Docker + PostgreSQL + Qdrant 运行）
  python tests/debug/test_generation_e2e.py full

  # 去重测试（发送相同内容两次，验证去重效果）
  python tests/debug/test_generation_e2e.py dedup
"""

import asyncio
import json
import sys
import os
import time

# 设置 SSL 证书（Windows 环境必须）
os.environ["SSL_CERT_FILE"] = "E:/anaconda3/envs/agent_mem/Lib/site-packages/certifi/cacert.pem"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")

from app.services.llm_client import llm_client
from app.services.embedding_client import embedding_client
from app.services.memory_extractor import MemoryExtractor
from app.services.memory_generator import MemoryGenerator, MemoryCandidate
from app.services.memory_dedup import DedupService, DedupAction
from app.core.qdrant_client import qdrant_client
from app.prompts.key_fact_extraction import KEY_FACT_SYSTEM_PROMPT


# ============================================================
# 测试数据
# ============================================================

SAMPLE_TEXT = """
用户: 我们正在开发一个叫 ProjectX 的电商平台，主要用 Python 和 FastAPI。
智能体: 好的，Python + FastAPI 技术栈已经记录。
用户: 项目的 deadline 是下周五，目前数据库设计已经完成，API 接口开发正在进行中。
智能体: 了解。数据库设计已完成，API 开发进行中。
用户: 我们之前讨论了技术选型，最终决定用 PostgreSQL 而不是 MySQL，因为需要 pgvector 支持。
智能体: 确认，已选择 PostgreSQL 作为数据库。
用户: 用户画像服务需要在下周三之前完成，QA 团队已经确认了这个时间点。
智能体: 记录：用户画像服务 deadline 为下周三，QA 已确认。
"""

SAMPLE_TEXT_2 = """
用户: ProjectX 的 API 开发进度怎么样了？
智能体: API 基本框架已搭建完成，正在实现用户认证模块。
用户: 好的。另外我们决定把缓存层从 Redis 换成 Dragonfly，性能更好。
智能体: 确认切换到 Dragonfly。Dragonfly 兼容 Redis 协议，迁移成本低。
用户: 之前说的用户画像服务已经完成了，QA 测试通过了。
智能体: 好的，用户画像服务已标记为完成。
"""


def divider(title: str = "") -> None:
    """打印分隔线"""
    width = 60
    if title:
        print(f"\n{'=' * width}")
        print(f"  {title}")
        print(f"{'=' * width}")
    else:
        print(f"{'─' * width}")


async def test_llm_connection() -> bool:
    """测试 DeepSeek LLM 连接"""
    divider("1. DeepSeek LLM 连接测试")
    try:
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": "Say 'OK' if you can read this."}],
            max_tokens=20,
        )
        print(f"   响应: {response.strip()}")
        print(f"   ✅ LLM 连接正常")
        return True
    except Exception as e:
        print(f"   ❌ LLM 连接失败: {e}")
        return False


async def test_embedding_connection() -> bool:
    """测试 SiliconFlow Embedding 连接"""
    divider("2. Embedding 连接测试")
    try:
        vec = await embedding_client.embed_single("Hello, world!")
        print(f"   向量维度: {len(vec)}")
        print(f"   前 5 维: {[round(v, 4) for v in vec[:5]]}")
        print(f"   ✅ Embedding 正常 (dim={len(vec)})")
        return len(vec) == 1024
    except Exception as e:
        print(f"   ❌ Embedding 失败: {e}")
        return False


async def test_extraction() -> None:
    """测试关键记忆抽取"""
    divider("3. 关键记忆抽取")
    extractor = MemoryExtractor(llm_client)

    print(f"   输入文本: {len(SAMPLE_TEXT)} 字符")
    print(f"   抽取类型: key_fact, task_state, decision")

    start = time.time()
    result = await extractor.extract(
        text=SAMPLE_TEXT,
        types=["key_fact", "task_state", "decision"],
    )
    elapsed = time.time() - start

    print(f"   耗时: {elapsed:.2f}s")
    print()

    if result.key_facts:
        kf = result.key_facts
        print(f"   📋 关键事实:")
        if kf.business_objects:
            print(f"      业务对象 ({len(kf.business_objects)}):")
            for obj in kf.business_objects[:3]:
                print(f"        - {obj.get('name', '?')} ({obj.get('type', '?')})")
        if kf.constraints:
            print(f"      约束条件 ({len(kf.constraints)}):")
            for c in kf.constraints[:3]:
                print(f"        - {c.get('description', '?')} [严重: {c.get('severity', '?')}]")
        if kf.confirmations:
            print(f"      确认事项 ({len(kf.confirmations)}):")
            for cf in kf.confirmations[:3]:
                print(f"        - {cf.get('item', '?')}")

    if result.task_state:
        ts = result.task_state
        print(f"   📊 任务状态:")
        if ts.current_progress:
            print(f"      当前进展: {ts.current_progress[:100]}")
        if ts.completed_items:
            print(f"      已完成 ({len(ts.completed_items)}):")
            for item in ts.completed_items[:3]:
                print(f"        - {item.get('item', '?')}")
        if ts.pending_items:
            print(f"      待处理 ({len(ts.pending_items)}):")
            for item in ts.pending_items[:3]:
                print(f"        - [{item.get('priority', '?')}] {item.get('item', '?')}")

    if result.decisions:
        dc = result.decisions
        print(f"   🎯 历史决策:")
        if dc.confirmed_plans:
            print(f"      已确认方案 ({len(dc.confirmed_plans)}):")
            for plan in dc.confirmed_plans[:3]:
                print(f"        - {plan.get('plan', '?')}")
        if dc.selection_rationale:
            print(f"      选择依据 ({len(dc.selection_rationale)}):")
            for r in dc.selection_rationale[:3]:
                print(f"        - {r.get('reason', '?')}")

    if result.is_empty():
        print(f"   ⚠️ 未抽取到任何内容")


async def test_generation() -> None:
    """测试结构化记忆生成"""
    divider("4. 结构化记忆生成")
    extractor = MemoryExtractor(llm_client)
    generator = MemoryGenerator(llm_client)

    print("   执行抽取...")
    extraction = await extractor.extract(SAMPLE_TEXT)
    print(f"   执行生成...")

    start = time.time()
    candidates = await generator.generate(extraction)
    elapsed = time.time() - start
    print(f"   耗时: {elapsed:.2f}s")
    print(f"   生成候选记忆: {len(candidates)} 条")

    for i, c in enumerate(candidates):
        print(f"\n   --- 候选 #{i+1} ---")
        print(f"   类型: {c.memory_type}")
        print(f"   内容: {c.content[:150]}")
        print(f"   摘要: {c.summary[:120]}")
        print(f"   要点: {c.key_points}")
        print(f"   标签: {c.tags}")
        print(f"   实体: {c.entities}")
        print(f"   重要性: {c.importance:.2f}  置信度: {c.confidence:.2f}")


async def test_dedup_logic() -> None:
    """演示去重逻辑（不需要数据库，仅演示决策矩阵）"""
    divider("5. 去重决策矩阵演示")

    service = DedupService(embedding_client, qdrant_client)

    test_cases = [
        # (vector_score, keyword_overlap, identity_match, expected)
        (0.95, 0.90, True, DedupAction.DISCARD),
        (0.90, 0.70, True, DedupAction.UPDATE_EXISTING),
        (0.88, 0.76, False, DedupAction.MERGE),
        (0.60, 0.30, False, DedupAction.KEEP_NEW),
    ]

    all_pass = True
    for vec, kw, identity, expected in test_cases:
        action = service._decide_action(vec, kw, identity)
        status = "✅" if action == expected else "❌"
        if action != expected:
            all_pass = False
        print(f"   vec={vec:.2f} kw={kw:.2f} id={identity} → {action.value} {status} (expected: {expected.value})")

    if all_pass:
        print(f"   ✅ 决策矩阵全部正确")
    else:
        print(f"   ❌ 部分决策不正确")


async def test_full_pipeline() -> None:
    """完整流水线测试（需要数据库和 Qdrant）"""
    divider("6. 完整流水线（需要数据库）")

    from app.core.database import get_db, check_db_connection
    from app.services.memory_pipeline import memory_pipeline

    # 检查数据库连接
    db_ok = await check_db_connection()
    if not db_ok:
        print("   ❌ 数据库不可用，请先启动 Docker 容器:")
        print("      docker start mem-postgres mem-qdrant")
        return

    # 初始化 Qdrant
    if not qdrant_client.is_available:
        print("   初始化 Qdrant...")
        ok = qdrant_client.initialize()
        if not ok:
            print("   ❌ Qdrant 初始化失败")
            return
        print("   ✅ Qdrant 连接成功")

    # 获取数据库会话
    async for db in get_db():
        print(f"\n   发送文本: {len(SAMPLE_TEXT)} 字符")
        print(f"   用户: test_e2e_user")

        start = time.time()
        result = await memory_pipeline.run(
            text=SAMPLE_TEXT,
            user_id="test_e2e_user",
            db=db,
        )
        elapsed = time.time() - start

        print(f"\n   ✅ 流水线完成 ({elapsed:.2f}s)")
        print(f"   新创建: {result.new_count}")
        print(f"   已合并: {result.merged_count}")
        print(f"   已丢弃: {result.discarded_count}")
        print(f"   已更新: {result.updated_count}")
        print(f"   记忆 ID: {result.memory_ids}")

        for d in result.details[:5]:
            print(f"\n   [{d['action']}] {d.get('memory_id', 'N/A')}")
            print(f"   内容: {d.get('content_preview', '')[:100]}")
            print(f"   类型: {d.get('memory_type', '?')}  重要性: {d.get('importance', 0):.2f}")
        break  # 只执行一次


async def test_dedup_with_db() -> None:
    """去重测试（发送相同内容两次）"""
    divider("7. 去重测试（发送相同内容两次）")

    from app.core.database import get_db, check_db_connection
    from app.services.memory_pipeline import memory_pipeline

    db_ok = await check_db_connection()
    if not db_ok:
        print("   ❌ 数据库不可用，跳过")
        return

    if not qdrant_client.is_available:
        qdrant_client.initialize()

    async for db in get_db():
        user_id = f"test_dedup_{int(time.time())}"

        # 第一次提交
        print(f"\n   第一次提交（用户: {user_id}）...")
        result1 = await memory_pipeline.run(
            text=SAMPLE_TEXT,
            user_id=user_id,
            db=db,
        )
        print(f"   新创建: {result1.new_count}  丢弃: {result1.discarded_count}")

        # 第二次提交相同内容
        print(f"\n   第二次提交（相同内容）...")
        result2 = await memory_pipeline.run(
            text=SAMPLE_TEXT,
            user_id=user_id,
            db=db,
        )
        print(f"   新创建: {result2.new_count}  丢弃: {result2.discarded_count}")

        if result2.discarded_count > 0:
            print(f"\n   ✅ 去重生效！第二次提交检测到重复并丢弃了 {result2.discarded_count} 条记忆")
        elif result2.new_count == 0:
            print(f"\n   ✅ 去重生效！第二次提交没有创建新记忆")
        else:
            print(f"\n   ⚠️ 去重未完全生效（可能相似度未达阈值），新创建 {result2.new_count} 条")
        break


# ============================================================
# 主入口
# ============================================================

async def main(mode: str = "basic"):
    """运行测试"""
    print("=" * 60)
    print("  记忆生成与去重融合 — E2E 测试")
    print("=" * 60)
    print(f"  模式: {mode}")

    if mode == "basic":
        # 基础测试：仅 LLM + Embedding 连接 + 抽取 + 生成 + 去重逻辑
        llm_ok = await test_llm_connection()
        if not llm_ok:
            print("\n❌ LLM 不可用，终止测试")
            return

        emb_ok = await test_embedding_connection()
        if not emb_ok:
            print("\n⚠️ Embedding 不可用，跳过去重相关测试")

        await test_extraction()
        await test_generation()
        await test_dedup_logic()

    elif mode == "full":
        # 完整测试：包括数据库写入
        await test_llm_connection()
        await test_extraction()
        await test_generation()
        await test_full_pipeline()
        await test_dedup_logic()

    elif mode == "dedup":
        # 去重专用测试
        await test_llm_connection()
        await test_extraction()
        await test_dedup_with_db()

    else:
        print(f"未知模式: {mode}")
        print("用法: python tests/debug/test_generation_e2e.py [basic|full|dedup]")

    # 关闭连接
    await llm_client.close()
    await embedding_client.close()

    print(f"\n{'=' * 60}")
    print(f"  测试完成")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "basic"
    asyncio.run(main(mode))
