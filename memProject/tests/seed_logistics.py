"""
物流场景测试数据写入 — 24 条记忆通过 /api/v1/memory/write 接口写入。

数据来源: ../../大规模测试数据-物流场景-24条.json
每条消息独立写入，走 Pipeline → mem0 双写路径。

用法:
  python tests/seed_logistics.py
  python tests/seed_logistics.py --base-url http://120.27.207.238:8000
"""
import sys; sys.path.insert(0, '.')
import asyncio, json, os, time, argparse

import httpx

JSONL = os.path.join(os.path.dirname(__file__), "..", "..", "大规模测试数据-物流场景-24条.json")
USER_ID = "logistics_test_user"


def load_records() -> list[dict]:
    with open(JSONL, encoding='utf-8') as f:
        return json.load(f)


async def seed(base_url: str, concurrency: int = 3):
    records = load_records()
    sem = asyncio.Semaphore(concurrency)

    print(f"数据: {len(records)} 条")
    print(f"用户: {USER_ID}")
    print(f"API: {base_url}/api/v1/memory/write")
    print()

    async def write_one(idx: int, rec: dict) -> dict:
        body = {
            "user_id": USER_ID,
            "scene_id": rec["scene_id"],
            "task_id": rec["task_id"],
            "messages": [{"role": rec["role"], "content": rec["content"]}],
        }
        t0 = time.perf_counter()
        async with sem:
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
                    add = sum(1 for r in results if r.get("event") == "ADD")
                    merge = sum(1 for r in results if r.get("event") == "MERGE")
                    skip = sum(1 for r in results if r.get("event") == "SKIP")
                    mode = data.get("mode", "?")
                    return {"idx": idx, "ok": True, "elapsed_ms": ms, "add": add, "merge": merge, "skip": skip, "mode": mode}
                return {"idx": idx, "ok": False, "elapsed_ms": ms, "status": resp.status_code, "body": resp.text[:200]}
            except Exception as e:
                ms = round((time.perf_counter() - t0) * 1000)
                return {"idx": idx, "ok": False, "elapsed_ms": ms, "error": str(e)[:100]}

    BATCH = concurrency * 5
    all_results = []
    start = time.perf_counter()

    for i in range(0, len(records), BATCH):
        batch = [(j, records[j]) for j in range(i, min(i + BATCH, len(records)))]
        tasks = [write_one(idx, rec) for idx, rec in batch]
        results = await asyncio.gather(*tasks)
        all_results.extend(results)

        done = len(all_results)
        ok_count = sum(1 for r in results if r["ok"])
        total_add = sum(r.get("add", 0) for r in results if r["ok"])
        total_merge = sum(r.get("merge", 0) for r in results if r["ok"])
        elapsed = int(time.perf_counter() - start)
        print(f"  [{done}/{len(records)}] 成功={ok_count} 记忆={total_add+total_merge} (ADD={total_add} MERGE={total_merge}) 耗时={elapsed}s")

    total_s = int(time.perf_counter() - start)
    ok_count = sum(1 for r in all_results if r["ok"])
    fail_count = sum(1 for r in all_results if not r["ok"])
    total_add = sum(r.get("add", 0) for r in all_results if r["ok"])
    total_merge = sum(r.get("merge", 0) for r in all_results if r["ok"])
    total_mem = total_add + total_merge

    print(f"\n{'='*50}")
    print(f"完成: {ok_count}/{len(records)} 成功, {fail_count} 失败")
    print(f"产出记忆: {total_mem} (ADD={total_add} MERGE={total_merge})")
    print(f"总耗时: {total_s}s")
    print(f"用户: {USER_ID}")
    print(f"场景: logistics-large-test")
    print(f"任务: log_route_001 / log_warehouse_002 / log_delivery_003 / log_compliance_004")
    print(f"{'='*50}")

    if fail_count:
        for r in all_results:
            if not r["ok"]:
                print(f"  FAIL #{r['idx']+1}: {r.get('status','?')} {r.get('body','')} {r.get('error','')}")

    # 保存用户信息供查询脚本使用
    info_file = os.path.join(os.path.dirname(__file__), "_logistics_info.json")
    with open(info_file, "w") as f:
        json.dump({"user_id": USER_ID, "scene_id": "logistics-large-test", "total_memories": total_mem}, f)
    print(f"信息已保存 → {info_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="物流场景数据写入")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API 地址")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(seed(base_url=args.base_url, concurrency=args.concurrency))
