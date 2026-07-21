# -*- coding: utf-8 -*-
"""Pass 2 only — re-run full dataset against existing Pass 1 data, with encoding fix."""
import json, sys, time
import requests

# Fix Windows GBK encoding
sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
DATASET = "tests/test_dataset_full.jsonl"
SCENE_ID = "test_dedup"
DELAY = 0.5
TIMEOUT = 300

def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs

records = load(DATASET)
total = len(records)
print(f"Loaded {total} dialogues for Pass 2\n")

events = {"ADD": 0, "UPDATE": 0, "MERGE": 0, "SKIP": 0, "CONFLICT": 0}
modes = {}
lats = []
session = requests.Session()
session.headers["Content-Type"] = "application/json"

t0 = time.time()
for idx, rec in enumerate(records):
    uid = rec["user_id"]
    cid = rec.get("conversation_id", f"c{idx}")
    sid = f"{cid}_p2"  # Pass 2 suffix

    body = {
        "user_id": uid, "scene_id": SCENE_ID,
        "session_id": sid, "interaction_type": "dialogue",
        "messages": rec["messages"],
    }

    t1 = time.time()
    resp = session.post(f"{SERVER}/api/v1/memory/write", json=body, timeout=TIMEOUT)
    lat = time.time() - t1
    lats.append(lat)

    data = resp.json().get("data", {})
    mode = data.get("mode", "legacy")
    modes[mode] = modes.get(mode, 0) + 1
    results = data.get("results", [])

    for item in results:
        ev = item.get("event", "?")
        mem = item.get("memory", "")
        if mem.startswith("[冲突]"):
            ev = "CONFLICT"
        events[ev] = events.get(ev, 0) + 1

    if (idx + 1) % 10 == 0 or idx == total - 1:
        elapsed = time.time() - t0
        avg_lat = sum(lats[-10:]) / min(len(lats[-10:]), 1)
        total_ev = sum(events.values())
        hit = (events["MERGE"] + events["SKIP"] + events["UPDATE"] + events["CONFLICT"]) / max(total_ev, 1)
        print(f"P2[{idx+1}/{total}] elapsed={elapsed:.0f}s avg_lat={avg_lat:.1f}s "
              f"| ADD={events['ADD']} UPDATE={events['UPDATE']} MERGE={events['MERGE']} "
              f"SKIP={events['SKIP']} CONFLICT={events['CONFLICT']} "
              f"| hit={hit:.1%} | modes={modes}", flush=True)

    if idx < total - 1:
        time.sleep(DELAY)

session.close()
dur = time.time() - t0
total_ev = sum(events.values())
hit = (events["MERGE"] + events["SKIP"] + events["UPDATE"] + events["CONFLICT"]) / max(total_ev, 1)
lats_sorted = sorted(lats)
p50 = lats_sorted[len(lats_sorted)//2] if lats_sorted else 0
p95 = lats_sorted[int(len(lats_sorted)*0.95)] if lats_sorted else 0

print(f"""
{'='*60}
  Pass 2 完成 ({total} dialogues)
{'='*60}
模式: {modes}
耗时: {dur:.0f}s ({dur/60:.1f}min)
平均延迟: {sum(lats)/len(lats):.1f}s  P50: {p50:.1f}s  P95: {p95:.1f}s
总事件: {total_ev}
事件分布: {events}
去重命中率: {hit:.1%}
""")
