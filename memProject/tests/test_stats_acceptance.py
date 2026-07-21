# -*- coding: utf-8 -*-
"""11. 验收测试 — GET /memory/stats 层级统计接口"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000/api/v1"

r = requests.post(BASE + "/agent/register", json={"agent_name":"acc","scene_id":"s","permissions":[]})
KEY = r.json()["data"]["api_key"]
H = {"X-API-Key": KEY, "X-User-Id": "user_a", "Content-Type": "application/json"}


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if not condition else ""))
    return condition

passed = failed = 0

# 1. 正常响应
print("=== 1. 正常响应 ===")
r = requests.get(BASE + "/memory/stats?user_id=user_a", headers=H)
d = r.json()
assert d["code"] == 0
data = d["data"]
dist = data["level_distribution"]

ok = True
ok &= check("total >= 0", data["total"] >= 0)
ok &= check("total == sum(counts)", data["total"] == sum(lv["count"] for lv in dist))
ok &= check("level_distribution 有4项", len(dist) == 4)
ok &= check("levels: user,session,task,agent", [lv["level"] for lv in dist] == ["user","session","task","agent"])
ok &= check("classification_version = memory_scope_v1", data["classification_version"] == "memory_scope_v1")
ok &= check("有 generated_at", "generated_at" in data)
if ok: passed += 1
else: failed += 1

# 2. 缺少 user_id
print("\n=== 2. 缺少 user_id ===")
r = requests.get(BASE + "/memory/stats", headers=H)
ok = r.status_code in (400, 422)
check("返回 400/422", ok, f"status={r.status_code}")
if ok: passed += 1
else: failed += 1

# 3. ratio 总和 ≈ 1 (total > 0)
print("\n=== 3. ratio 总和 ≈ 1 ===")
r = requests.get(BASE + "/memory/stats?user_id=user_a", headers=H)
dist = r.json()["data"]["level_distribution"]
total_ratio = sum(lv["ratio"] for lv in dist)
ok = abs(total_ratio - 1.0) < 0.001 if r.json()["data"]["total"] > 0 else total_ratio == 0
check("ratio 总和 ≈ 1", ok, f"sum={total_ratio}")
if ok: passed += 1
else: failed += 1

# 4. stats.total == list.total
print("\n=== 4. stats.total == list.total ===")
stats = requests.get(BASE + "/memory/stats?user_id=user_a", headers=H).json()["data"]
rl = requests.post(BASE + "/memory/list?user_id=user_a&page=1&page_size=1", headers=H).json()["data"]
ok = stats["total"] == rl["total"]
check(f"stats={stats['total']} == list={rl['total']}", ok)
if ok: passed += 1
else: failed += 1

# 5. scene_id 过滤
print("\n=== 5. scene_id 过滤 ===")
r = requests.get(BASE + "/memory/stats?user_id=user_a&scene_id=scene_dev_default", headers=H)
ok = r.json()["code"] == 0
check("scene_id 过滤后正常", ok)
if ok: passed += 1
else: failed += 1

# 6. memory_scope 过滤列表
print("\n=== 6. 列表 memory_scope 过滤 ===")
r = requests.post(BASE + "/memory/list?user_id=user_a&memory_scope=task&page=1&page_size=3", headers=H)
ok = r.json()["code"] == 0
check("list?memory_scope=task", ok, f"total={r.json().get('data',{}).get('total',0)}")
if ok: passed += 1
else: failed += 1

# 7. 响应中包含 memory_scope
print("\n=== 7. 列表项包含 memory_scope ===")
r = requests.post(BASE + "/memory/list?user_id=user_a&page=1&page_size=1", headers=H)
item = r.json()["data"]["items"][0] if r.json()["data"]["items"] else {}
ok = "memory_scope" in item
check("包含 memory_scope 字段", ok, f"keys={list(item.keys())[:8]}")
if ok: passed += 1
else: failed += 1

print(f"\n{'='*40}")
print(f"  通过: {passed}/{passed+failed}")
print(f"{'='*40}")
