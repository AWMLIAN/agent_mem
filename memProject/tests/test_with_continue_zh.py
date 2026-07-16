# -*- coding: utf-8 -*-
"""
使用 continue_zh.jsonl 数据集进行端到端功能测试。

测试流程：
  1. 加载数据集
  2. 对采样对话完整运行 Pipeline（extract → value_judge → generate → quality → dedup）
  3. 统计各阶段结果
  4. 报告所有错误和警告

运行方式：
  python tests/test_with_continue_zh.py
"""

import json
import sys
import asyncio
import time
import os
from pathlib import Path

# Windows GBK 终端 Unicode 修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.memory_pipeline import memory_pipeline, MemoryPipeline, PipelineResult
from app.services.memory_extractor import MemoryExtractor, ExtractionResult
from app.services.memory_generator import MemoryGenerator, MemoryCandidate
from app.services.memory_dedup import DedupService, DedupAction
from app.services.memory_quality import (
    judge_extraction_value, verify_candidate_quality, verify_candidates_batch,
)
from app.services.llm_client import llm_client
from app.services.embedding_client import embedding_client
from app.core.qdrant_client import qdrant_client

# ============================================================
# 配置
# ============================================================

DATASET_PATH = str(Path(__file__).resolve().parent.parent.parent.parent / "continue_zh.jsonl")
SAMPLE_SIZE = 10          # 测试采样数量
MAX_CONV_TURNS = 6        # 每条对话最多取前 N 轮
MAX_TEXT_LENGTH = 3000    # 单次输入最大字符数


def load_dataset(path: str, sample_size: int) -> list[dict]:
    """加载 JSONL 数据集并采样。"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if len(records) >= sample_size:
                break
            try:
                data = json.loads(line)
                records.append(data)
            except json.JSONDecodeError as e:
                print(f"  [WARN] 跳过无效 JSON 行 {i}: {e}")
    return records


def build_text_from_conversation(conv: list[dict], max_turns: int) -> str:
    """将对话轮次拼接为单个文本。"""
    parts = []
    for turn in conv[:max_turns]:
        human = turn.get("human", "")
        assistant = turn.get("assistant", "")
        if human:
            parts.append(f"[用户]: {human}")
        if assistant:
            parts.append(f"[助手]: {assistant}")
    text = "\n".join(parts)
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "...[截断]"
    return text


# ============================================================
# 逐阶段详细测试
# ============================================================

async def test_phase_extraction(texts: list[str]) -> dict:
    """测试阶段 1+1.5：抽取 + 价值判断（逐条调用 LLM）。"""
    extractor = MemoryExtractor(llm_client)
    stats = {
        "total": len(texts),
        "success": 0,
        "empty": 0,
        "errors": 0,
        "value_kept": 0,
        "value_discarded": 0,
        "type_counts": {},
        "details": [],
    }

    for i, text in enumerate(texts):
        detail = {"index": i, "text_len": len(text)}
        try:
            result = await extractor.extract(text)
            if result.is_empty():
                stats["empty"] += 1
                detail["result"] = "empty"
            else:
                stats["success"] += 1
                # 统计活跃类型
                types = []
                if result.key_facts and not result.key_facts.is_empty():
                    types.append("key_fact")
                    n_bo = len(result.key_facts.business_objects)
                    n_co = len(result.key_facts.constraints)
                    n_cf = len(result.key_facts.confirmations)
                    detail["key_fact"] = f"bo={n_bo}, constraints={n_co}, confirmations={n_cf}"
                if result.task_state and not result.task_state.is_empty():
                    types.append("task_state")
                    detail["task_state"] = f"progress={bool(result.task_state.current_progress)}, done={len(result.task_state.completed_items)}, pending={len(result.task_state.pending_items)}"
                if result.decisions and not result.decisions.is_empty():
                    types.append("decision")
                    detail["decision"] = f"plans={len(result.decisions.confirmed_plans)}, rationale={len(result.decisions.selection_rationale)}, results={len(result.decisions.execution_results)}"
                if result.preferences and not result.preferences.is_empty():
                    types.append("preference")
                    detail["preference"] = f"style={len(result.preferences.style_preferences)}, habits={len(result.preferences.habitual_preferences)}, tendencies={len(result.preferences.decision_tendencies)}"
                if result.process and not result.process.is_empty():
                    types.append("process")
                    detail["process"] = f"actions={len(result.process.execution_actions)}, conclusions={len(result.process.intermediate_conclusions)}, failures={len(result.process.failure_records)}"
                if result.feedback and not result.feedback.is_empty():
                    types.append("feedback")
                    detail["feedback"] = f"corrections={len(result.feedback.corrections)}, confirmations={len(result.feedback.confirmation_statuses)}, replacements={len(result.feedback.replacement_relationships)}"

                detail["types"] = types
                for t in types:
                    stats["type_counts"][t] = stats["type_counts"].get(t, 0) + 1

                # 价值判断
                vj = judge_extraction_value(result)
                if vj.should_keep:
                    stats["value_kept"] += 1
                else:
                    stats["value_discarded"] += 1
                detail["value"] = f"{vj.overall_value:.2f} keep={vj.should_keep}"
                detail["result"] = "ok"

        except Exception as e:
            stats["errors"] += 1
            detail["result"] = f"error: {e}"
            print(f"  [ERROR] Extraction #{i}: {e}")

        stats["details"].append(detail)

    return stats


async def test_phase_generation(texts: list[str]) -> dict:
    """测试阶段 2+2.5：生成 + 质量校验（逐条调用 LLM）。"""
    extractor = MemoryExtractor(llm_client)
    generator = MemoryGenerator(llm_client)

    stats = {
        "total": len(texts),
        "candidates_generated": 0,
        "memories_total": 0,
        "quality_active": 0,
        "quality_pending": 0,
        "type_counts": {},
        "avg_quality_score": 0.0,
        "errors": 0,
        "details": [],
    }

    all_scores = []

    for i, text in enumerate(texts):
        detail = {"index": i, "text_len": len(text)}
        try:
            extraction = await extractor.extract(text)
            if extraction.is_empty():
                detail["result"] = "extraction_empty"
                stats["details"].append(detail)
                continue

            candidates = await generator.generate(extraction)
            stats["candidates_generated"] += 1
            stats["memories_total"] += len(candidates)
            detail["memories"] = len(candidates)

            # 质量校验
            reports = verify_candidates_batch(candidates, source_text=text)
            active = sum(1 for r in reports if r.suggested_status == "active")
            pending = sum(1 for r in reports if r.suggested_status == "pending")
            stats["quality_active"] += active
            stats["quality_pending"] += pending

            for r in reports:
                all_scores.append(r.quality_score)
                t = r.candidate.memory_type
                stats["type_counts"][t] = stats["type_counts"].get(t, 0) + 1

            detail["active"] = active
            detail["pending"] = pending
            detail["types"] = [r.candidate.memory_type for r in reports]
            detail["result"] = "ok"

        except Exception as e:
            stats["errors"] += 1
            detail["result"] = f"error: {e}"
            print(f"  [ERROR] Generation #{i}: {e}")

        stats["details"].append(detail)

    if all_scores:
        stats["avg_quality_score"] = sum(all_scores) / len(all_scores)
    return stats


async def test_phase_dedup_simulation(texts: list[str]) -> dict:
    """
    测试阶段 3：去重模拟。
    对同一 conversation 的多条 text 依次运行 Pipeline，
    观察第二条及之后的去重行为。
    """
    stats = {
        "total_convos": 0,
        "total_memories": 0,
        "actions": {},
        "errors": 0,
        "details": [],
    }

    # 加载完整数据集，按 conversation_id 分组
    records = load_dataset(DATASET_PATH, 50)
    conv_groups: dict[str, list[str]] = {}
    for rec in records:
        cid = rec.get("conversation_id", f"unknown_{rec.get('id')}")
        if cid not in conv_groups:
            conv_groups[cid] = []
        conv_groups[cid].append(build_text_from_conversation(
            rec.get("conversation", []), MAX_CONV_TURNS
        ))

    # 对每个 conversation 运行多轮 Pipeline
    for cid, texts in list(conv_groups.items())[:5]:  # 只测 5 个 conversation
        stats["total_convos"] += 1
        detail = {"conversation_id": cid, "rounds": []}

        previous_memory_ids = []
        for rnd, text in enumerate(texts[:3]):  # 每个 conversation 最多 3 轮
            round_detail = {"round": rnd, "text_len": len(text)}
            try:
                result = await memory_pipeline.run(
                    text=text,
                    user_id=f"test_user_{cid}",
                    agent_id="test_agent",
                    task_id=f"task_{cid}",
                    db=None,  # 不持久化，只测试逻辑
                )
                round_detail["new"] = result.new_count
                round_detail["merged"] = result.merged_count
                round_detail["discarded"] = result.discarded_count
                round_detail["updated"] = result.updated_count
                round_detail["conflict"] = result.conflict_count
                round_detail["total"] = len(result.memory_ids)

                for d in result.details:
                    action = d.get("action", "unknown")
                    stats["actions"][action] = stats["actions"].get(action, 0) + 1

                stats["total_memories"] += len(result.memory_ids)
                previous_memory_ids = result.memory_ids
                round_detail["result"] = "ok"

            except Exception as e:
                stats["errors"] += 1
                round_detail["result"] = f"error: {e}"
                print(f"  [ERROR] Pipeline {cid} round {rnd}: {e}")

            detail["rounds"].append(round_detail)

        stats["details"].append(detail)

    return stats


# ============================================================
# 主函数
# ============================================================

def print_separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_phase1_stats(stats: dict) -> None:
    """打印抽取阶段统计。"""
    print(f"  总样本: {stats['total']}")
    print(f"  抽取成功: {stats['success']} | 空结果: {stats['empty']} | 异常: {stats['errors']}")
    print(f"  价值判断: 保留={stats['value_kept']}, 丢弃={stats['value_discarded']}")
    print(f"  类型分布: {stats['type_counts']}")
    print(f"\n  逐条详情:")
    for d in stats["details"]:
        status = "[OK]" if d.get("result") == "ok" else "[XX]" if d.get("result") == "empty" else "[!!]"
        types_str = ", ".join(d.get("types", [])) or "无"
        value_str = d.get("value", "N/A")
        extra = ""
        if "key_fact" in d: extra += f" | facts: {d['key_fact']}"
        if "task_state" in d: extra += f" | task: {d['task_state']}"
        if "preference" in d: extra += f" | pref: {d['preference']}"
        if "process" in d: extra += f" | proc: {d['process']}"
        if "feedback" in d: extra += f" | fb: {d['feedback']}"
        print(f"    [{status}] #{d['index']}: {types_str} | {value_str}{extra}")


def print_phase2_stats(stats: dict) -> None:
    """打印生成阶段统计。"""
    print(f"  总样本: {stats['total']}")
    print(f"  生成记忆总数: {stats['memories_total']} (来自 {stats['candidates_generated']} 次生成)")
    print(f"  质量分布: active={stats['quality_active']}, pending={stats['quality_pending']}")
    print(f"  平均质量分: {stats['avg_quality_score']:.2f}")
    print(f"  异常: {stats['errors']}")
    print(f"  类型分布: {stats['type_counts']}")
    print(f"\n  逐条详情:")
    for d in stats["details"]:
        result = d.get("result", "?")
        if result == "extraction_empty":
            print(f"    [[--]] #{d['index']}: 抽取为空，跳过生成")
        elif result == "ok":
            types = ", ".join(d.get("types", []))
            print(f"    [[OK]] #{d['index']}: {d.get('memories',0)}条记忆, active={d.get('active',0)}, pending={d.get('pending',0)} | {types}")
        else:
            print(f"    [[!!]] #{d['index']}: {result}")


def print_phase3_stats(stats: dict) -> None:
    """打印去重模拟统计。"""
    print(f"  测试对话数: {stats['total_convos']}")
    print(f"  总记忆数: {stats['total_memories']}")
    print(f"  动作分布: {stats['actions']}")
    print(f"  异常: {stats['errors']}")
    print(f"\n  逐对话详情:")
    for detail in stats["details"]:
        cid = detail["conversation_id"][:12]
        for rd in detail["rounds"]:
            result = rd.get("result", "?")
            if result == "ok":
                print(f"    [{cid}] Round {rd['round']}: "
                      f"new={rd.get('new',0)}, merge={rd.get('merged',0)}, "
                      f"discard={rd.get('discarded',0)}, update={rd.get('updated',0)}, "
                      f"conflict={rd.get('conflict',0)} → total={rd.get('total',0)}")
            else:
                print(f"    [{cid}] Round {rd['round']}: [!!] {result}")


async def main():
    print("=" * 60)
    print("  记忆生成系统 — continue_zh.jsonl 数据集测试")
    print("=" * 60)

    # 加载数据
    print(f"\n加载数据集: {DATASET_PATH}")
    records = load_dataset(DATASET_PATH, SAMPLE_SIZE)
    texts = [
        build_text_from_conversation(r.get("conversation", []), MAX_CONV_TURNS)
        for r in records
    ]
    print(f"  已加载 {len(texts)} 条对话文本")
    print(f"  平均长度: {sum(len(t) for t in texts) / max(len(texts), 1):.0f} 字符")

    # 检查 LLM/Embedding 可用性
    print(f"\n服务状态:")
    print(f"  LLM: {'[OK] 可用' if llm_client else '[XX] 不可用'}")
    print(f"  Embedding: {'[OK] 可用' if embedding_client else '[XX] 不可用'}")
    print(f"  Qdrant: {'[OK] 可用' if qdrant_client.is_available else '[XX] 不可用 (无 Docker)'}")

    # ---- Phase 1: 抽取测试 ----
    print_separator("Phase 1: 抽取 + 价值判断 (前 5 条)")
    t0 = time.time()
    extraction_stats = await test_phase_extraction(texts[:5])
    t1 = time.time()
    print_phase1_stats(extraction_stats)
    print(f"  耗时: {t1 - t0:.1f}s")

    # ---- Phase 2: 生成测试 ----
    print_separator("Phase 2: 生成 + 质量校验 (前 3 条)")
    t0 = time.time()
    generation_stats = await test_phase_generation(texts[:3])
    t1 = time.time()
    print_phase2_stats(generation_stats)
    print(f"  耗时: {t1 - t0:.1f}s")

    # ---- Phase 3: 去重模拟 ----
    print_separator("Phase 3: 去重模拟 (5 个对话，每对话多轮)")
    t0 = time.time()
    dedup_stats = await test_phase_dedup_simulation(texts)
    t1 = time.time()
    print_phase3_stats(dedup_stats)
    print(f"  耗时: {t1 - t0:.1f}s")

    # ---- 总结 ----
    print_separator("总结")
    total_errors = extraction_stats["errors"] + generation_stats["errors"] + dedup_stats["errors"]
    total_extracted = extraction_stats["success"]
    total_generated = generation_stats["memories_total"]
    total_quality = generation_stats["quality_active"] + generation_stats["quality_pending"]

    print(f"  抽取成功率: {extraction_stats['success']}/{extraction_stats['total']} "
          f"({100*extraction_stats['success']/max(extraction_stats['total'],1):.0f}%)")
    print(f"  价值保留率: {extraction_stats['value_kept']}/{extraction_stats['success']} "
          f"({100*extraction_stats['value_kept']/max(extraction_stats['success'],1):.0f}%)" if extraction_stats['success'] > 0 else "  价值保留率: N/A")
    print(f"  生成记忆数: {total_generated}")
    print(f"  质量通过率: {generation_stats['quality_active']}/{total_quality} "
          f"({100*generation_stats['quality_active']/max(total_quality,1):.0f}%)" if total_quality > 0 else "  质量通过率: N/A")
    print(f"  平均质量分: {generation_stats['avg_quality_score']:.2f}")
    print(f"  去重动作分布: {dedup_stats['actions']}")
    print(f"  总异常数: {total_errors}")
    print(f"  新提取类型覆盖: preference={extraction_stats['type_counts'].get('preference', 0)}, "
          f"process={extraction_stats['type_counts'].get('process', 0)}, "
          f"feedback={extraction_stats['type_counts'].get('feedback', 0)}")

    if total_errors > 0:
        print(f"\n  [!!] 存在 {total_errors} 个异常，需要排查。")
    else:
        print(f"\n  [OK] 所有阶段无异常！")


if __name__ == "__main__":
    asyncio.run(main())
