# -*- coding: utf-8 -*-
"""
服务器端去重融合全量测试 — test_dataset_full.jsonl (126 条对话)

测试目标：
  1. 对全部 126 条对话调用服务器 POST /api/v1/memory/write
  2. 追踪每条的去重行为：ADD / MERGE / SKIP / CONFLICT
  3. 统计各 user_id 的去重命中率
  4. 生成 JSON 报告

运行方式：
  python tests/test_server_dedup.py
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# 配置
# ============================================================

SERVER = "http://localhost:8000"
DATASET = Path(__file__).parent / "test_dataset_full.jsonl"
REPORT_PATH = Path(__file__).parent / "server_dedup_report.json"
PROGRESS_PATH = Path(__file__).parent / "server_dedup_progress.txt"

SCENE_ID = "test_dedup"


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


def call_write(server: str, record: dict) -> dict:
    """调用 POST /api/v1/memory/write，返回解析后的 JSON 或错误信息。"""
    url = f"{server}/api/v1/memory/write"

    body = {
        "user_id": record.get("user_id", "unknown"),
        "scene_id": SCENE_ID,
        "session_id": record.get("conversation_id", ""),
        "interaction_type": "dialogue",
        "messages": record.get("messages", []),
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:500]
        except Exception:
            pass
        return {"_error": f"HTTP {e.code}", "_detail": err_body}
    except Exception as e:
        return {"_error": str(e)}


def classify_event(item: dict) -> str:
    """根据 results 条目判断实际去重动作。"""
    event = item.get("event", "?")
    memory = item.get("memory", "")
    if memory.startswith("[冲突]"):
        return "CONFLICT"
    return event  # ADD / SKIP / MERGE


def main():
    print("=" * 60)
    print("  服务器去重融合全量测试")
    print(f"  服务器: {SERVER}")
    print(f"  数据集: {DATASET}")
    print("=" * 60)

    records = load_dataset(DATASET)
    total = len(records)
    print(f"\n已加载 {total} 条对话记录")

    # 统计
    stats = {
        "ok": 0, "err": 0,
        "ADD": 0, "SKIP": 0, "MERGE": 0, "CONFLICT": 0,
        "event_counts": defaultdict(int),
        "user_stats": defaultdict(lambda: {"total": 0, "ADD": 0, "SKIP": 0, "MERGE": 0, "CONFLICT": 0}),
        "lats": [],
        "details": [],
    }

    batch_start = time.time()
    t0 = batch_start

    # 写入进度头
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(f"Server Dedup Test: {total} conversations\n")

    for idx, rec in enumerate(records):
        uid = rec.get("user_id", "unknown")
        cid = rec.get("conversation_id", f"c{idx}")
        n_msgs = len(rec.get("messages", []))

        t1 = time.time()
        result = call_write(SERVER, rec)
        lat = time.time() - t1
        stats["lats"].append(lat)

        detail = {
            "index": idx,
            "user_id": uid,
            "conversation_id": cid,
            "messages": n_msgs,
            "latency_s": round(lat, 2),
        }

        if "_error" in result:
            stats["err"] += 1
            detail["status"] = "ERROR"
            detail["error"] = result["_error"]
            detail["detail"] = result.get("_detail", "")
            print(f"  [{idx+1}/{total}] ERROR: {uid}/{cid} -> {result['_error']}", flush=True)
        else:
            stats["ok"] += 1
            results = result.get("data", {}).get("results", [])
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

        # 每 20 条输出进度
        if (idx + 1) % 20 == 0:
            elapsed = time.time() - batch_start
            rate = 20 / max(elapsed, 0.01)
            avg_lat = sum(stats["lats"][-20:]) / max(len(stats["lats"][-20:]), 1)
            msg = (
                f"[{idx+1}/{total}] rate={rate:.2f}/s avg={avg_lat:.1f}s "
                f"ok={stats['ok']} err={stats['err']} "
                f"ADD={stats['ADD']} MERGE={stats['MERGE']} "
                f"SKIP={stats['SKIP']} CONFLICT={stats['CONFLICT']}"
            )
            print(f"  {msg}", flush=True)
            with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            batch_start = time.time()

    dur = time.time() - t0

    # ============================================================
    # 报告
    # ============================================================
    lats_sorted = sorted(stats["lats"])
    p50 = lats_sorted[len(lats_sorted) // 2] if lats_sorted else 0
    p95 = lats_sorted[int(len(lats_sorted) * 0.95)] if lats_sorted else 0
    total_events = sum(stats["event_counts"].values())
    dedup_hit = (stats["MERGE"] + stats["SKIP"] + stats["CONFLICT"]) / max(total_events, 1)

    report_text = f"""
{'='*60}
  服务器去重融合测试报告 ({total} 条对话)
{'='*60}

── 总体 ──
处理: {stats['ok']}/{total} 成功, {stats['err']} 异常
耗时: {dur:.0f}s ({dur/60:.1f}min)
吞吐: {stats['ok']/max(dur,0.01):.2f} 条/秒

── 性能 ──
平均延迟: {sum(stats['lats'])/max(len(stats['lats']),1):.1f}s
P50: {p50:.1f}s  P95: {p95:.1f}s

── 去重效果 ──
总动作: {total_events}
去重命中率: {dedup_hit:.1%} (非 ADD 占比)
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
        "duration_s": round(dur, 1),
        "throughput": round(stats["ok"] / max(dur, 0.01), 2),
        "avg_latency_s": round(sum(stats["lats"]) / max(len(stats["lats"]), 1), 1),
        "p50_s": round(p50, 1),
        "p95_s": round(p95, 1),
        "dedup_hit_rate": round(dedup_hit, 3),
        "events": dict(stats["event_counts"]),
        "user_stats": {
            uid: dict(us) for uid, us in stats["user_stats"].items()
        },
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(json_report, f, ensure_ascii=False, indent=2)

    # 尾部
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(f"\nDone. OK={stats['ok']} ERR={stats['err']} DUR={dur:.0f}s\n")

    print(f"\n报告已保存: {REPORT_PATH}")
    print(f"进度日志: {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
