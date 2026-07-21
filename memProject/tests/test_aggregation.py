# -*- coding: utf-8 -*-
"""测试三层聚合 — 用户画像/会话上下文/任务视图"""
import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(BASE + "/agent/register", json={"agent_name":"show","scene_id":"s","permissions":[]})
K = r.json()["data"]["api_key"]

def agg(uid, sid=None, tid=None):
    body = {"query":"", "user_id":uid, "include_preferences":True, "include_facts":True}
    if sid: body["session_id"] = sid
    if tid: body["task_id"] = tid
    r = requests.post(BASE + "/memory/context", json=body,
        headers={"X-API-Key":K, "X-User-Id":uid, "Content-Type":"application/json"})
    return r.json()["data"]

# === 任务 ===
print("========== 任务级聚合 ==========")
for uid,tid in [("user_a","task_a"),("user_b","task_b"),("user_c","task_c")]:
    d = agg(uid, tid=tid)
    print(f"\n【{uid} / {tid}】 {d['memory_count']}碎片")
    for f in d["fragments"]:
        print(f"  [{f['memory_type']}] {f['content'][:100]}")
    if d.get("formatted_text"):
        print(f"  >>> {d['formatted_text'][:200]}")

# === 会话(前10) ===
print("\n\n========== 会话级聚合(前10) ==========")
import subprocess
sessions = subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-t","-c",
    "SELECT session_id FROM t_memory WHERE status='active' GROUP BY session_id ORDER BY COUNT(*) DESC LIMIT 10;"],
    capture_output=True, text=True).stdout.strip().split()
for sid in sessions:
    uid = subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-t","-c",
        f"SELECT user_id FROM t_memory WHERE session_id='{sid}' LIMIT 1;"],
        capture_output=True, text=True).stdout.strip()
    d = agg(uid, sid=sid)
    keys = [f for f in d["fragments"] if f.get("key")]
    print(f"\n【{uid}/{sid}】 {d['memory_count']}碎片 KEY:{len(keys)}")
    for f in d["fragments"][:5]:
        k = " ★KEY" if f.get("key") else ""
        print(f"  [{f['memory_type']}]{k} {f['content'][:100]}")

# === 用户(前10) ===
print("\n\n========== 用户级聚合(前10) ==========")
users = subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-t","-c",
    "SELECT user_id FROM t_memory WHERE status='active' GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10;"],
    capture_output=True, text=True).stdout.strip().split()
for uid in users:
    d = agg(uid)
    print(f"\n【{uid}】 {d['memory_count']}碎片")
    if d.get("formatted_text"):
        print(f"  {d['formatted_text'][:300]}")
