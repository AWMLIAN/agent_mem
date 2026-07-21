"""
异步压测脚本 — 对 /api/v1/memory/search 做并发梯度压测。

用法:
  # 单轮快速验证
  python tests/benchmark_search.py --concurrency 5 --duration 30

  # 完整梯度压测（1 → 5 → 10 → 20 → 50 并发）
  python tests/benchmark_search.py --gradient --duration 60

  # 自定义参数
  python tests/benchmark_search.py --gradient --duration 60 --base-url http://120.27.207.238:8000

输出:
  - 控制台实时打印每轮 P50/P90/P99/QPS
  - tests/_bench_results.json 保存详细结果
"""
import sys; sys.path.insert(0, '.')
import os
import asyncio
import json
import random
import time
import argparse
from typing import Optional

import httpx

JSONL = os.path.join(os.path.dirname(__file__), "..", "..", "continue_zh.jsonl")
USERS_FILE = os.path.join(os.path.dirname(__file__), "_bench_users.txt")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "_bench_results.json")

# 请求体模板（对照 /api/v1/memory/search 的 MemorySearchRequest）
SEARCH_BODY_TEMPLATE = {
    "query": "",
    "user_id": "",
    "top_k": 10,
    "rerank": True,
    "include_scores": True,
}

# 过滤条件变体（覆盖场景/任务/类型/组合过滤）
FILTER_VARIANTS = [
    {},  # 纯语义（无过滤）
    {"scene_id": "scene_code"},
    {"scene_id": "scene_chat"},
    {"task_id": "task_create"},
    {"task_id": "task_qa"},
    {"memory_types": ["preference"]},
    {"memory_types": ["fact"]},
    {"memory_types": ["decision"]},
    {"scene_id": "scene_code", "task_id": "task_create"},
    {"scene_id": "scene_game", "memory_types": ["preference"]},
]


def load_query_pool() -> list[str]:
    """从 continue_zh.jsonl 提取查询池（50-200 条真实用户消息）。"""
    queries = []
    with open(JSONL, encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            for turn in data.get("conversation", []):
                msg = turn.get("human", "").strip()
                if 10 <= len(msg) <= 200:
                    queries.append(msg)
                    if len(queries) >= 200:
                        break
            if len(queries) >= 200:
                break
    return queries


def load_users() -> list[str]:
    """从造数脚本输出的用户列表加载。"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    # fallback
    return [f"bench_user_{i:03d}" for i in range(100)]


def percentile(sorted_vals: list[float], p: float) -> float:
    """计算百分位数（线性插值）。"""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_vals):
        return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
    return sorted_vals[f]


def compute_stats(latencies: list[float], errors: int, duration_s: float) -> dict:
    """从延迟列表计算统计指标。"""
    if not latencies:
        return {"p50": 0, "p90": 0, "p99": 0, "avg": 0, "min": 0, "max": 0,
                "qps": 0, "errors": errors, "total_requests": 0}
    s = sorted(latencies)
    return {
        "p50": round(percentile(s, 50), 1),
        "p90": round(percentile(s, 90), 1),
        "p95": round(percentile(s, 95), 1),
        "p99": round(percentile(s, 99), 1),
        "avg": round(sum(s) / len(s), 1),
        "min": round(s[0], 1),
        "max": round(s[-1], 1),
        "qps": round(len(s) / max(duration_s, 0.1), 1),
        "errors": errors,
        "total_requests": len(s) + errors,
    }


async def run_benchmark(
    base_url: str,
    concurrency: int,
    duration_s: int,
    query_pool: list[str],
    user_ids: list[str],
) -> dict:
    """单轮压测：固定并发数，持续 duration_s 秒。"""
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    stop = False

    async def worker(client: httpx.AsyncClient, worker_id: int):
        nonlocal errors, stop
        while not stop:
            query = random.choice(query_pool)
            uid = random.choice(user_ids)
            variant = random.choice(FILTER_VARIANTS)
            body = {**SEARCH_BODY_TEMPLATE, "query": query, "user_id": uid, **variant}

            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/memory/search",
                    json=body,
                    timeout=httpx.Timeout(30.0),
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    latencies.append(elapsed_ms)
                else:
                    errors += 1
            except Exception:
                errors += 1

            # 释放 semaphore 后让其他 worker 有机会执行
            await asyncio.sleep(0)

    print(f"\n{'─'*50}")
    print(f"并发={concurrency}, 持续={duration_s}s, 查询池={len(query_pool)}条")
    print(f"{'─'*50}")

    async with httpx.AsyncClient() as client:
        tasks = [worker(client, i) for i in range(concurrency)]
        start = time.perf_counter()

        # 启动 worker + 定时停止
        async def timer():
            nonlocal stop
            await asyncio.sleep(duration_s)
            stop = True

        await asyncio.gather(timer(), *tasks)

    actual_duration = time.perf_counter() - start
    stats = compute_stats(latencies, errors, actual_duration)
    stats["concurrency"] = concurrency
    stats["duration_s"] = round(actual_duration, 1)

    # 实时输出
    print(f"  请求: {stats['total_requests']}  |  "
          f"P50={stats['p50']}ms  P90={stats['p90']}ms  P99={stats['p99']}ms  "
          f"avg={stats['avg']}ms  QPS={stats['qps']}")
    if errors:
        print(f"  ⚠ 错误: {errors}")

    return stats


async def gradient_benchmark(
    base_url: str,
    duration_s: int,
    concurrency_levels: list[int],
) -> list[dict]:
    """并发梯度压测。"""
    query_pool = load_query_pool()
    user_ids = load_users()
    print(f"查询池: {len(query_pool)} 条")
    print(f"用户: {len(user_ids)} 个")
    print(f"过滤变体: {len(FILTER_VARIANTS)} 种")
    print(f"梯度: {concurrency_levels}")

    all_results = []
    for c in concurrency_levels:
        stats = await run_benchmark(base_url, c, duration_s, query_pool, user_ids)
        all_results.append(stats)

    return all_results


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="记忆检索压测")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API 地址")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--duration", type=int, default=60, help="每轮持续时间(秒)")
    parser.add_argument("--gradient", action="store_true", help="梯度压测: 1→5→10→20→50")
    parser.add_argument("--levels", default="1,5,10,20,50", help="自定义梯度 (逗号分隔)")
    parser.add_argument("--output", default=RESULTS_FILE, help="结果输出文件")
    args = parser.parse_args()

    if args.gradient:
        levels = [int(x.strip()) for x in args.levels.split(",")]
        results = asyncio.run(gradient_benchmark(args.base_url, args.duration, levels))
    else:
        results = asyncio.run(
            gradient_benchmark(args.base_url, args.duration, [args.concurrency])
        )

    # ── 汇总输出 ──
    print(f"\n{'='*70}")
    print(f"压测汇总")
    print(f"{'='*70}")
    print(f"{'并发':>5} | {'请求数':>7} | {'P50':>8} | {'P90':>8} | {'P99':>8} | {'avg':>8} | {'QPS':>8} | {'错误':>5}")
    print(f"{'─'*5}─┼─{'─'*7}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*5}")
    for r in results:
        print(f"{r['concurrency']:>5} | {r['total_requests']:>7} | "
              f"{r['p50']:>7}ms | {r['p90']:>7}ms | {r['p99']:>7}ms | "
              f"{r['avg']:>7}ms | {r['qps']:>7.1f} | {r['errors']:>5}")

    # ── 判断达标 ──
    print(f"\n{'='*70}")
    print(f"P90 ≤ 500ms 验收:")
    for r in results:
        status = "✅ PASS" if r['p90'] <= 500 else "❌ FAIL"
        print(f"  并发{r['concurrency']:>2}: P90={r['p90']}ms  {status}")
    print(f"{'='*70}")

    # ── 写入文件 ──
    with open(args.output, "w") as f:
        json.dump({
            "base_url": args.base_url,
            "concurrency_levels": [r["concurrency"] for r in results],
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存 → {args.output}")
