# -*- coding: utf-8 -*-
"""
使用 continue_zh.jsonl 数据集端到端测试"智能体接入与记忆数据写入"API。

覆盖功能清单中"二级功能：智能体接入与记忆数据写入功能"：
  - 智能体接入管理
  - 三种数据类型写入（dialogue / session / task_process）
  - 数据接入校验

用法:
  # 冒烟测试（默认 5 条，三种类型各测一次）
  python tests/test_with_dataset.py

  # 指定测试条数
  python tests/test_with_dataset.py --count 50

  # 指定测试类型
  python tests/test_with_dataset.py --type dialogue
  python tests/test_with_dataset.py --type session
  python tests/test_with_dataset.py --type task_process
  python tests/test_with_dataset.py --type all

  # 全量测试
  python tests/test_with_dataset.py --count 0 --type all

  # 仅校验数据转换（不发请求）
  python tests/test_with_dataset.py --count 3 --dry-run
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# 自动定位项目根目录和数据集
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = PROJECT_ROOT.parent.parent / "continue_zh.jsonl"
BASE_URL = "http://localhost:8000"
API_ENDPOINT = f"{BASE_URL}/api/v1/memory/write"


def load_dataset(limit: int = 0) -> list[dict]:
    """加载 JSONL 数据集。limit=0 表示全量。"""
    if not DATASET_PATH.exists():
        print(f"[ERROR] 数据集不存在: {DATASET_PATH}")
        sys.exit(1)

    items = []
    with open(DATASET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
            if limit > 0 and len(items) >= limit:
                break
    return items


def conversation_to_messages(conv: list[dict], max_turns: int = 20) -> list[dict]:
    """将 {human, assistant} 转为 messages[{role, content}]。"""
    messages = []
    for turn in conv[:max_turns]:
        if turn.get("human"):
            messages.append({"role": "user", "content": turn["human"][:2000]})
        if turn.get("assistant"):
            messages.append({"role": "assistant", "content": turn["assistant"][:2000]})
    return messages


def build_request(item: dict, interaction_type: str) -> dict:
    """构建指定类型的 MemoryWriteRequest。"""
    conv = item.get("conversation", [])
    base = {
        "user_id": f"dataset_{item['id']}",
        "scene_id": "dataset_test",
        "session_id": f"sess_{item.get('conversation_id', 'unknown')}",
        "interaction_type": interaction_type,
        "metadata": {
            "source": "continue_zh.jsonl",
            "conversation_id": item.get("conversation_id"),
            "original_id": item["id"],
        },
    }

    if interaction_type == "dialogue":
        base["messages"] = conversation_to_messages(conv)

    elif interaction_type == "session":
        base["messages"] = conversation_to_messages(conv, max_turns=10)
        # 用第一轮用户问题作为摘要
        first_human = ""
        for t in conv:
            if t.get("human"):
                first_human = t["human"][:500]
                break
        base["session_summary"] = first_human or "历史会话记录"
        base["session_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        base["session_source"] = "continue_zh_dataset"

    elif interaction_type == "task_process":
        base["task_id"] = f"task_{item.get('conversation_id', item['id'])}"
        base["messages"] = conversation_to_messages(conv, max_turns=10)
        # 推断任务目标和进展
        first_human = ""
        for t in conv:
            if t.get("human"):
                first_human = t["human"][:300]
                break
        base["task_goal"] = first_human or "未指定目标"
        mid = len(conv) // 2
        mid_text = ""
        for key in ("human", "assistant"):
            if mid < len(conv) and conv[mid].get(key):
                mid_text = conv[mid][key][:300]
                break
        base["task_progress"] = mid_text or "进行中"

    return base


def send_request(client: httpx.Client, body: dict, timeout: int = 120) -> dict:
    """发送请求，返回结果摘要。"""
    start = time.perf_counter()
    try:
        resp = client.post(API_ENDPOINT, json=body, timeout=timeout)
        elapsed = round((time.perf_counter() - start) * 1000)
        data = resp.json()

        results = data.get("data", {}).get("results", [])
        events = {"ADD": 0, "SKIP": 0, "MERGE": 0}
        for r in results:
            e = r.get("event", "SKIP")
            events[e] = events.get(e, 0) + 1

        return {
            "success": data.get("code") == 0,
            "code": data.get("code"),
            "message": data.get("message", ""),
            "elapsed_ms": elapsed,
            "results_count": len(results),
            "events": events,
        }
    except httpx.TimeoutException:
        return {"success": False, "code": -1, "message": "timeout", "elapsed_ms": round((time.perf_counter() - start) * 1000)}
    except Exception as e:
        return {"success": False, "code": -1, "message": str(e)[:100], "elapsed_ms": round((time.perf_counter() - start) * 1000)}


def run_tests(items: list[dict], interaction_type: str, dry_run: bool = False) -> dict:
    """运行一批测试。"""
    labels = {"dialogue": "对话记录", "session": "历史会话", "task_process": "任务过程"}
    label = labels.get(interaction_type, interaction_type)

    print(f"\n{'='*60}")
    print(f"  测试类型: {label} ({interaction_type})")
    print(f"  测试条数: {len(items)}")
    if dry_run:
        print(f"  模式: DRY RUN (仅构造请求)")
    print(f"{'='*60}")

    stats = {"total": 0, "success": 0, "fail": 0, "total_ms": 0, "results": []}

    with httpx.Client() as client:
        for i, item in enumerate(items):
            body = build_request(item, interaction_type)
            stats["total"] += 1

            if dry_run:
                print(f"  [{i+1}/{len(items)}] id={item['id']} | "
                      f"turns={len(item.get('conversation',[]))} | "
                      f"messages={len(body.get('messages',[]))} | DRY RUN")
                stats["success"] += 1
                continue

            print(f"  [{i+1}/{len(items)}] id={item['id']} | "
                  f"turns={len(item.get('conversation',[]))} | ", end="", flush=True)

            result = send_request(client, body)
            stats["total_ms"] += result["elapsed_ms"]
            stats["results"].append({**result, "id": item["id"]})

            if result["success"]:
                stats["success"] += 1
                e = result["events"]
                print(f"OK ({result['elapsed_ms']}ms) [ADD={e['ADD']}, SKIP={e['SKIP']}, MERGE={e['MERGE']}]")
            else:
                stats["fail"] += 1
                print(f"FAIL ({result['elapsed_ms']}ms) [{result['message']}]")

    return stats


def print_summary(all_stats: dict) -> None:
    """打印汇总报告。"""
    print(f"\n{'='*60}")
    print(f"  测试汇总")
    print(f"{'='*60}")

    labels = {"dialogue": "对话记录", "session": "历史会话", "task_process": "任务过程"}
    grand = {"total": 0, "success": 0, "fail": 0, "total_ms": 0}

    for itype, stats in all_stats.items():
        if stats["total"] == 0:
            continue
        rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        avg_ms = stats["total_ms"] / stats["total"] if stats["total"] > 0 else 0
        print(f"\n  [{labels.get(itype, itype)}] "
              f"{stats['total']} 条 | 成功 {stats['success']} | 失败 {stats['fail']} | "
              f"成功率 {rate:.1f}% | 平均 {avg_ms:.0f} ms/条")

        failures = [r for r in stats["results"] if not r["success"]]
        if failures:
            print(f"    失败详情:")
            for f in failures[:5]:
                print(f"      id={f['id']}: {f['message']}")
            if len(failures) > 5:
                print(f"      ... 还有 {len(failures) - 5} 条")

        grand["total"] += stats["total"]
        grand["success"] += stats["success"]
        grand["fail"] += stats["fail"]
        grand["total_ms"] += stats["total_ms"]

    if grand["total"] > 0:
        rate = grand["success"] / grand["total"] * 100
        avg_ms = grand["total_ms"] / grand["total"]
        print(f"\n  [总计] {grand['total']} 条 | 成功 {grand['success']} | "
              f"失败 {grand['fail']} | 成功率 {rate:.1f}% | 平均 {avg_ms:.0f} ms/条")


def run_validation_tests() -> None:
    """校验拦截测试：故意发送非法请求。"""
    print(f"\n{'='*60}")
    print(f"  校验测试: 非法请求拦截")
    print(f"{'='*60}")

    tests = [
        ("session 无 messages 无 summary", {
            "user_id": "test", "interaction_type": "session", "messages": []
        }),
        ("task_process 无数据", {
            "user_id": "test", "interaction_type": "task_process", "messages": []
        }),
        ("dialogue 空 messages", {
            "user_id": "test", "interaction_type": "dialogue", "messages": []
        }),
    ]

    with httpx.Client() as client:
        for label, body in tests:
            try:
                resp = client.post(API_ENDPOINT, json=body, timeout=10)
                data = resp.json()
                ok_result = data.get("code") != 0
                print(f"  [{'PASS' if ok_result else 'FAIL'}] {label}: "
                      f"code={data.get('code')}, {data.get('message', '')}")
            except Exception as e:
                print(f"  [ERROR] {label}: {e}")


def main():
    parser = argparse.ArgumentParser(description="使用 continue_zh.jsonl 端到端测试记忆写入 API")
    parser.add_argument("--count", type=int, default=5,
                        help="测试条数，0 表示全量 (默认 5)")
    parser.add_argument("--type", choices=["dialogue", "session", "task_process", "all"],
                        default="all")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅构造请求不发送")
    args = parser.parse_args()

    # 加载数据
    items = load_dataset(limit=args.count if args.count > 0 else 0)
    print(f"{'='*60}")
    print(f"  智能体接入与记忆数据写入 — 数据集端到端测试")
    print(f"{'='*60}")
    print(f"  数据集: {DATASET_PATH}")
    print(f"  加载: {len(items)} 条 (共 1907 条)")
    print(f"  API: {API_ENDPOINT}")

    # 确定测试类型
    types = ["dialogue", "session", "task_process"] if args.type == "all" else [args.type]

    # 运行测试
    all_stats = {}
    for itype in types:
        stats = run_tests(items, itype, dry_run=args.dry_run)
        all_stats[itype] = stats

    # 汇总
    print_summary(all_stats)

    # 校验测试
    if not args.dry_run:
        run_validation_tests()


if __name__ == "__main__":
    main()
