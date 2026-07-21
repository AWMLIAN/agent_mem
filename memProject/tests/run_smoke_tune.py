# -*- coding: utf-8 -*-
"""冒烟测试 — 快速验证 UPDATE 事件 + 双遍去重效果。"""
import json, sys, time
import requests

SERVER = "http://localhost:8000"
DATASET = "tests/test_dataset_smoke.jsonl"
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

def run_pass(records, pass_no):
    total = len(records)
    events = {"ADD": 0, "UPDATE": 0, "MERGE": 0, "SKIP": 0, "CONFLICT": 0}
    lats = []
    session = requests.Session()
    session.headers["Content-Type"] = "application/json"

    for idx, rec in enumerate(records):
        uid = rec["user_id"]
        cid = rec.get("conversation_id", f"c{idx}")
        sid = cid if pass_no == 1 else f"{cid}_p{pass_no}"

        body = {
            "user_id": uid, "scene_id": "smoke_tune",
            "session_id": sid, "interaction_type": "dialogue",
            "messages": rec["messages"],
        }

        t1 = time.time()
        resp = session.post(f"{SERVER}/api/v1/memory/write", json=body, timeout=TIMEOUT)
        lat = time.time() - t1
        lats.append(lat)

        data = resp.json().get("data", {})
        mode = data.get("mode", "legacy")
        results = data.get("results", [])

        for item in results:
            ev = item.get("event", "?")
            mem = item.get("memory", "")
            if mem.startswith("[冲突]"):
                ev = "CONFLICT"
            events[ev] = events.get(ev, 0) + 1

        print(f"  P{pass_no}[{idx+1}/{total}] {uid}/{cid} mode={mode} evts={[item.get('event') for item in results]} lat={lat:.1f}s", flush=True)

        if idx < total - 1:
            time.sleep(DELAY)

    session.close()
    return events, lats

def main():
    records = load(DATASET)
    print(f"Loaded {len(records)} smoke dialogues\n")

    for p in [1, 2]:
        print(f"=== Pass {p} ===")
        events, lats = run_pass(records, p)
        total_ev = sum(events.values())
        print(f"  Events: {events}")
        print(f"  Total: {total_ev}, Avg lat: {sum(lats)/len(lats):.1f}s")
        if total_ev > 1:
            hit = (events["MERGE"] + events["SKIP"] + events["UPDATE"] + events["CONFLICT"]) / total_ev
            print(f"  Dedup hit rate: {hit:.1%}")
        print()

if __name__ == "__main__":
    main()
