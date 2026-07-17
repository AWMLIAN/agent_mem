# -*- coding: utf-8 -*-
"""
服务器端去重融合全量测试 — test_dataset_full.jsonl (126 条对话)

特性：
  - 严格串行：一次只发送一个请求，绝不并发
  - 请求间延迟 0.5s 保护服务器
  - 失败自动重试（最多 3 次，指数退避）
  - 使用 requests.Session() 复用 TCP 连接

运行方式：
  python tests/test_server_dedup.py
"""

import json
import sys
import time
from pathlib import Path
from collections import defaultdict

import requests

# ============================================================
# 配置
# ============================================================

SERVER = "http://localhost:8000"
DATASET = Path(__file__).parent / "test_dataset_full.jsonl"
REPORT_PATH = Path(__file__).parent / "server_dedup_report.json"
PROGRESS_PATH = Path(__file__).parent / "server_dedup_progress.txt"
SCENE_ID = "test_dedup"

REQUEST_DELAY = 0.5       # 请求间延迟（秒），保护服务器
MAX_RETRIES = 3           # 连接失败最大重试次数
RETRY_BACKOFF = 2.0       # 重试退避基数（秒）
TIMEOUT = 300             # 单次请求超时（秒），Pipeline 可能很慢


def load_dataset(path: Path) -> list[dict]:
    """加载全部 JSONL 记录。"""
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def classify_event(item: dict) -> str:
    """根据 results 条目判断实际去重动作。"""
    event = item.get("event", "?")
    memory = item.get("memory", "")
    if memory.startswith("[冲突]"):
        return "CONFLICT"
    return event


def main():
    print("=" * 60)
    print("  服务器去重融合全量测试")
    print(f"  服务器: {SERVER}")
    print(f"  数据集: {DATASET}")
    print(f"  模式: 严格串行 | 延迟={REQUEST_DELAY}s | 重试={MAX_RETRIES}次")
    print("=" * 60)

    records = load_dataset(DATASET)
    total = len(records)
    print(f"\n已加载 {total} 条对话记录\n")

    # 统计
    stats = {
        "ok": 0, "err": 0,
        "ADD": 0, "SKIP": 0, "MERGE": 0, "CONFLICT": 0,
        "event_counts": defaultdict(int),
        "user_stats": defaultdict(lambda: {"total": 0, "ADD": 0, "SKIP": 0, "MERGE": 0, "CONFLICT": 0}),
        "lats": [],
        "retries": 0,
        "details": [],
        "modes": defaultdict(int),       # 服务端处理路径统计（pipeline/mock/mq/degraded...）
        "degraded_count": 0,             # 非 pipeline/mq 的降级响应数
    }

    t0 = time.time()
    batch_start = t0

    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(f"Server Dedup Test: {total} conversations\n")

    # 使用 Session 复用 TCP 连接
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    for idx, rec in enumerate(records):
        uid = rec.get("user_id", "unknown")
        cid = rec.get("conversation_id", f"c{idx}")
        n_msgs = len(rec.get("messages", []))

        body = {
            "user_id": uid,
            "scene_id": SCENE_ID,
            "session_id": cid,
            "interaction_type": "dialogue",
            "messages": rec.get("messages", []),
        }

        # --- 发送请求（带重试） ---
        result = None
        t1 = time.time()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = session.post(
                    f"{SERVER}/api/v1/memory/write",
                    json=body,
                    timeout=TIMEOUT,
                )
                result = resp.json()
                break  # 成功
            except requests.exceptions.ConnectionError as e:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF ** attempt
                    print(f"  [{idx+1}/{total}] 连接失败 (尝试 {attempt}/{MAX_RETRIES}), {wait:.0f}s 后重试...", flush=True)
                    time.sleep(wait)
                    stats["retries"] += 1
                else:
                    result = {"_error": f"ConnectionError after {MAX_RETRIES} retries: {e}"}
            except requests.exceptions.Timeout:
                result = {"_error": "Timeout (>5min)"}
                break
            except Exception as e:
                result = {"_error": str(e)}
                break

        lat = time.time() - t1
        stats["lats"].append(lat)

        # --- 处理结果 ---
        detail = {
            "index": idx, "user_id": uid, "conversation_id": cid,
            "messages": n_msgs, "latency_s": round(lat, 1),
        }

        if result is None or "_error" in (result or {}):
            stats["err"] += 1
            detail["status"] = "ERROR"
            detail["error"] = (result or {}).get("_error", "unknown")
            print(f"  [{idx+1}/{total}] ERROR: {uid}/{cid} -> {detail['error']}", flush=True)
        else:
            stats["ok"] += 1
            data = result.get("data", {})
            results = data.get("results", [])
            # mode 校验：非真实 Pipeline 的响应立即告警（旧版服务端无此字段 → "legacy"）
            mode = data.get("mode", "legacy")
            stats["modes"][mode] += 1
            detail["mode"] = mode
            if mode not in ("pipeline", "mq"):
                stats["degraded_count"] += 1
                print(
                    f"  [{idx+1}/{total}] ⚠ 降级响应: {uid}/{cid} mode={mode} "
                    f"— 该条事件不代表真实去重结果!", flush=True
                )
            detail["status"] = "OK"
            detail["n_results"] = len(results)
            detail["events"] = []

            for item in results:
                event = classify_event(item)
                detail["events"].append(event)
                stats["event_counts"][event] += 1
                stats[event] = stats.get(event, 0) + 1
                us = stats["user_stats"][uid]
                us["total"] += 1
                us[event] = us.get(event, 0) + 1

        stats["details"].append(detail)

        # --- 进度报告 ---
        if (idx + 1) % 10 == 0 or idx == total - 1:
            elapsed_total = time.time() - t0
            elapsed_batch = time.time() - batch_start
            n_batch = min(10, (idx + 1) % 10 or 10)
            rate = n_batch / max(elapsed_batch, 0.01)
            avg_lat = sum(stats["lats"][-10:]) / max(len(stats["lats"][-10:]), 1)
            msg = (
                f"[{idx+1}/{total}] elapsed={elapsed_total:.0f}s batch_rate={rate:.1f}/s "
                f"avg_lat={avg_lat:.1f}s ok={stats['ok']} err={stats['err']} "
                f"retries={stats['retries']} | "
                f"ADD={stats['ADD']} MERGE={stats['MERGE']} "
                f"SKIP={stats['SKIP']} CONFLICT={stats['CONFLICT']} "
                f"| modes={dict(stats['modes'])}"
            )
            print(f"  {msg}", flush=True)
            with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            batch_start = time.time()

        # --- 请求间延迟（保护服务器） ---
        if idx < total - 1:
            time.sleep(REQUEST_DELAY)

    session.close()
    dur = time.time() - t0

    # ============================================================
    # 报告
    # ============================================================
    lats_sorted = sorted(stats["lats"])
    p50 = lats_sorted[len(lats_sorted) // 2] if lats_sorted else 0
    p95 = lats_sorted[int(len(lats_sorted) * 0.95)] if lats_sorted else 0
    total_events = sum(stats["event_counts"].values())
    dedup_hit = (stats["MERGE"] + stats["SKIP"] + stats["CONFLICT"]) / max(total_events, 1)

    # 有效性判定：只要有降级响应，本报告的去重统计不可信
    if stats["degraded_count"] > 0:
        validity = (
            f"⚠⚠ 报告无效: {stats['degraded_count']}/{stats['ok']} 条响应为降级模式 "
            f"{dict(stats['modes'])}，事件统计不代表真实去重能力!"
        )
    elif stats["modes"].get("legacy", 0) > 0:
        validity = "⚠ 服务端未返回 mode 字段（旧版），无法验证处理路径，结果存疑"
    else:
        validity = f"✔ 全部响应来自真实处理路径 {dict(stats['modes'])}"

    report_text = f"""
{'='*60}
  服务器去重融合测试报告 ({total} 条对话)
{'='*60}

── 有效性 ──
{validity}

── 总体 ──
处理: {stats['ok']}/{total} 成功, {stats['err']} 异常, {stats['retries']} 次重试
耗时: {dur:.0f}s ({dur/60:.1f}min)
吞吐: {stats['ok']/max(dur,0.01):.2f} 条/秒

── 性能 ──
平均延迟: {sum(stats['lats'])/max(len(stats['lats']),1):.1f}s
P50: {p50:.1f}s  P95: {p95:.1f}s

── 去重效果 ──
总动作: {total_events}
去重命中率: {dedup_hit:.1%}
ADD (新增):   {stats['ADD']}
MERGE (合并): {stats['MERGE']}
SKIP (跳过):  {stats['SKIP']}
CONFLICT:     {stats['CONFLICT']}

── 事件分布 ──
{json.dumps(dict(stats['event_counts']), ensure_ascii=False, indent=2)}

── 用户去重统计 (Top 20) ──"""

    print(report_text, flush=True)

    sorted_users = sorted(
        stats["user_stats"].items(),
        key=lambda x: x[1]["total"], reverse=True,
    )[:20]
    for uid, us in sorted_users:
        hit = (us["MERGE"] + us["SKIP"] + us["CONFLICT"]) / max(us["total"], 1)
        print(f"  {uid}: total={us['total']} hit={hit:.1%} "
              f"ADD={us['ADD']} MERGE={us['MERGE']} SKIP={us['SKIP']} CONFLICT={us['CONFLICT']}")

    print(f"\n── 异常列表 ──")
    err_count = 0
    for d in stats["details"]:
        if d["status"] == "ERROR":
            print(f"  [{d['index']}] {d['user_id']}/{d['conversation_id']}: {d.get('error','?')}")
            err_count += 1
    if err_count == 0:
        print("  (无异常)")

    # JSON 报告
    json_report = {
        "server": SERVER,
        "dataset": str(DATASET),
        "total": total,
        "ok": stats["ok"],
        "errors": stats["err"],
        "retries": stats["retries"],
        "duration_s": round(dur, 1),
        "throughput": round(stats["ok"] / max(dur, 0.01), 2),
        "avg_latency_s": round(sum(stats["lats"]) / max(len(stats["lats"]), 1), 1),
        "p50_s": round(p50, 1),
        "p95_s": round(p95, 1),
        "dedup_hit_rate": round(dedup_hit, 3),
        "modes": dict(stats["modes"]),
        "degraded_count": stats["degraded_count"],
        "events": dict(stats["event_counts"]),
        "user_stats": {uid: dict(us) for uid, us in stats["user_stats"].items()},
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(json_report, f, ensure_ascii=False, indent=2)

    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(f"\nDone. OK={stats['ok']} ERR={stats['err']} DUR={dur:.0f}s\n")

    print(f"\n报告已保存: {REPORT_PATH}")
    print(f"进度日志: {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
