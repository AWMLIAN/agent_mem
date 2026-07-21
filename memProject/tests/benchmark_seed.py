"""
造数脚本（简化版）— 2000 轮对话全部写入一个用户，摸底每轮 API 实际产出。

策略:
  1. 从 continue_zh.jsonl 读取 ~2000 轮对话
  2. 每轮 → POST /api/v1/memory/write (同一 user_id)
  3. API 内部: LLM抽取 → 生成 → 去重 → Embedding → PG + Qdrant 双写
  4. 跑完后统计实际记忆条数，再决定下一步

用法:
  python tests/benchmark_seed.py
  python tests/benchmark_seed.py --user-id test_user_001
  python tests/benchmark_seed.py --base-url http://120.27.207.238:8000
"""
import sys; sys.path.insert(0, '.')
import asyncio
import json
import os
import time
import argparse

import httpx

JSONL = os.path.join(os.path.dirname(__file__), "..", "..", "continue_zh.jsonl")


def load_conversations() -> list[dict]:
    convos = []
    with open(JSONL, encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            messages = []
            for turn in data.get("conversation", []):
                h = turn.get("human", "").strip()
                a = turn.get("assistant", "").strip()
                if len(h) >= 3:
                    messages.append({"role": "user", "content": h})
                if len(a) >= 3:
                    messages.append({"role": "assistant", "content": a[:500]})
            if len(messages) >= 2:
                # Schema 限制 messages 最多 100 条，超出的截断
                if len(messages) > 100:
                    messages = messages[:100]
                convos.append({
                    "conversation_id": data.get("conversation_id", ""),
                    "messages": messages,
                })
    return convos


async def seed(user_id: str, base_url: str, concurrency: int = 3) -> dict:
    convos = load_conversations()
    sem = asyncio.Semaphore(concurrency)

    print(f"对话总数: {len(convos)} 轮")
    print(f"用户: {user_id}")
    print(f"API: {base_url}/api/v1/memory/write")
    print(f"并发: {concurrency}")
    print()

    stats = {
        "api_calls": 0, "ok": 0, "fail": 0,
        "total_add": 0, "total_merge": 0, "total_skip": 0,
        "total_elapsed_ms": 0,
    }
    all_results: list[dict] = []
    start = time.perf_counter()

    async def write_one(convo: dict) -> dict:
        body = {
            "user_id": user_id,
            "session_id": convo.get("conversation_id", f"sess_{time.time()}"),
            "interaction_type": "dialogue",
            "messages": convo["messages"],
        }
        async with sem:
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{base_url}/api/v1/memory/write",
                        json=body,
                        timeout=httpx.Timeout(120.0),
                    )
                ms = round((time.perf_counter() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    results = data.get("results", [])
                    return {
                        "ok": True,
                        "elapsed_ms": ms,
                        "add": sum(1 for r in results if r.get("event") == "ADD"),
                        "merge": sum(1 for r in results if r.get("event") == "MERGE"),
                        "skip": sum(1 for r in results if r.get("event") == "SKIP"),
                        "total": len(results),
                    }
                body = resp.text[:300]
                return {"ok": False, "elapsed_ms": ms, "status": resp.status_code, "body": body}
            except Exception as e:
                ms = round((time.perf_counter() - t0) * 1000)
                return {"ok": False, "elapsed_ms": ms, "error": str(e)[:100]}

    # 分批并发执行
    BATCH = concurrency * 10
    for i in range(0, len(convos), BATCH):
        batch = convos[i:i+BATCH]
        tasks = [write_one(c) for c in batch]
        results = await asyncio.gather(*tasks)

        for r in results:
            stats["api_calls"] += 1
            stats["total_elapsed_ms"] += r["elapsed_ms"]
            if r["ok"]:
                stats["ok"] += 1
                stats["total_add"] += r["add"]
                stats["total_merge"] += r["merge"]
                stats["total_skip"] += r["skip"]
            else:
                stats["fail"] += 1
                # 打印前 3 个失败详情便于排查
                if stats["fail"] <= 3:
                    err_detail = r.get("status") or r.get("error", "?")
                    resp_body = r.get("body", "")
                    print(f"  ⚠ 失败 #{stats['fail']}: HTTP {err_detail} {resp_body}")
            all_results.append(r)

        done = stats["api_calls"]
        pct = done * 100 // len(convos)
        elapsed = int(time.perf_counter() - start)
        total_mem = stats["total_add"] + stats["total_merge"]
        avg_ms = stats["total_elapsed_ms"] // max(stats["api_calls"], 1)
        print(
            f"  [{done}/{len(convos)} {pct}%] "
            f"记忆={total_mem} (ADD={stats['total_add']} MERGE={stats['total_merge']} SKIP={stats['total_skip']}) "
            f"失败={stats['fail']} 平均{avg_ms}ms/次 "
            f"已用{elapsed//60}m{elapsed%60}s"
        )

    total_s = int(time.perf_counter() - start)
    total_mem = stats["total_add"] + stats["total_merge"]

    print(f"\n{'='*60}")
    print(f"完成!")
    print(f"  API 调用: {stats['api_calls']} (成功 {stats['ok']}, 失败 {stats['fail']})")
    print(f"  总记忆:   {total_mem} 条")
    print(f"    ADD:    {stats['total_add']}")
    print(f"    MERGE:  {stats['total_merge']}")
    print(f"    SKIP:   {stats['total_skip']}")
    print(f"  总耗时:   {total_s//3600}h{(total_s%3600)//60}m{total_s%60}s")
    avg_mem = total_mem / max(stats['ok'], 1)
    print(f"  平均产出: {avg_mem:.1f} 条/轮对话")
    print(f"{'='*60}")

    # 保存结果
    out = {
        "user_id": user_id,
        "conversations": len(convos),
        "api_calls": stats["api_calls"],
        "total_memories": total_mem,
        "add": stats["total_add"],
        "merge": stats["total_merge"],
        "skip": stats["total_skip"],
        "avg_per_call": round(avg_mem, 1),
        "total_seconds": total_s,
        "fail": stats["fail"],
    }
    out_file = os.path.join(os.path.dirname(__file__), "_seed_result.json")
    with open(out_file, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果 → {out_file}")

    # 保存 user_id
    users_file = os.path.join(os.path.dirname(__file__), "_bench_users.txt")
    with open(users_file, "w") as f:
        json.dump([user_id], f)

    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="通过 API 摸底记忆产出")
    parser.add_argument("--user-id", default="bench_user_000", help="写入的目标用户 ID")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API 地址")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数")
    args = parser.parse_args()

    asyncio.run(seed(user_id=args.user_id, base_url=args.base_url, concurrency=args.concurrency))
