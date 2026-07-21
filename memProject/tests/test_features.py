# -*- coding: utf-8 -*-
"""功能验证脚本 — 类型写入 + 多层聚合 + 软删除清理"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8001/api/v1"

def api(m, p, d=None, h=None):
    r = requests.request(m, BASE + p, json=d, headers=h, timeout=30)
    return r.json().get("data", {})

# 1. 注册
print("=== 注册 Agent ===")
r = requests.post(BASE + "/agent/register", json={"agent_name":"verify","scene_id":"v","permissions":[]})
KEY = r.json()["data"]["api_key"]
H = {"X-API-Key": KEY, "X-User-Id": "verify_u", "Content-Type": "application/json"}
print(f"OK: {KEY[:24]}...\n")

# 2. 类型感知写入
print("=== 类型感知写入 ===")
# 偏好
api("POST","/memory/write",{"user_id":"verify_u","session_id":"v1","interaction_type":"dialogue","messages":[{"role":"user","content":"我喜欢用Vim编辑器"}]}, H)
api("POST","/memory/write",{"user_id":"verify_u","session_id":"v1","interaction_type":"dialogue","messages":[{"role":"user","content":"我现在改用VS Code了"}]}, H)
# 事实
api("POST","/memory/write",{"user_id":"verify_u","session_id":"v2","interaction_type":"dialogue","messages":[{"role":"user","content":"公司数据库地址是 pg.example.com:5432"}]}, H)
api("POST","/memory/write",{"user_id":"verify_u","session_id":"v2","interaction_type":"dialogue","messages":[{"role":"user","content":"数据库连接地址 pg.example.com:5432"}]}, H)
# 任务
api("POST","/memory/write",{"user_id":"verify_u","task_id":"vt1","interaction_type":"dialogue","messages":[{"role":"user","content":"任务目标是完成功能验证"}]}, H)
print("写入完成\n")

# 3. 查库验证
import subprocess
print("=== 偏好验证(新active + 旧pending_update) ===")
subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-c",
    "SELECT status, LEFT(content,50) FROM t_memory WHERE user_id='verify_u' AND memory_type='preference' ORDER BY updated_at DESC LIMIT 3;"])

print("\n=== 事实冲突验证 ===")
subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-c",
    "SELECT status, LEFT(content,50) FROM t_memory WHERE user_id='verify_u' AND memory_type='fact';"])

print("\n=== 任务路由验证 ===")
subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-c",
    "SELECT memory_type, status, LEFT(content,60) FROM t_memory WHERE user_id='verify_u' AND memory_type='task_state';"])

# 4. 三层聚合
print("\n=== 多层聚合 ===")
u = api("POST","/context",{"query":"","user_id":"verify_u","include_preferences":True,"include_facts":True}, H)
print(f"用户画像: {len(u.get('fragments',[]))} fragments")

s = api("POST","/context",{"query":"","user_id":"verify_u","session_id":"v1"}, H)
print(f"会话上下文: {len(s.get('fragments',[]))} fragments")

t = api("POST","/context",{"query":"","user_id":"verify_u","task_id":"vt1"}, H)
print(f"任务视图: {len(t.get('fragments',[]))} fragments")

d = api("DELETE","/memory/delete",{"memory_id":"mem_test","reason":"test"}, H)
print(f"软删除: auto_purged={d.get('auto_purged','N/A')}")
