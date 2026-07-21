# -*- coding: utf-8 -*-
"""130条测试 — 30精准+100随机"""
import requests, time, sys, io, json, os, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000/api/v1"
r = requests.post(BASE + "/agent/register", json={"agent_name":"t130","scene_id":"t","permissions":[]})
KEY = r.json()["data"]["api_key"]

def W(uid, sid, tid, txt):
    body = {"user_id":uid, "session_id":sid, "messages":[{"role":"user","content":txt}]}
    if tid: body["task_id"] = tid
    requests.post(BASE + "/memory/write", headers={"X-API-Key":KEY, "X-User-Id":uid, "Content-Type":"application/json"}, json=body, timeout=60)

def wait(n=12):
    for _ in range(n): time.sleep(1); print(".",end="",flush=True)
    print(f" ({n}s)")

# ====== 30条精准 ======
print("=== 精准场景 30条 ===")

# user_a: 偏好(跨会话) + 事实冲突 + 任务
W("user_a","s_a1",None,"我喜欢用函数式编程写代码"); wait()
W("user_a","s_a1",None,"我更喜欢面向对象编程了"); wait()
W("user_a","s_a2",None,"我用Vim编辑器"); wait()
W("user_a","s_a2",None,"我改用VS Code了"); wait()
W("user_a","s_a2",None,"我喜欢吃川菜"); wait()

W("user_a","s_a3",None,"公司数据库在pg.example.com:5432"); wait()
W("user_a","s_a3",None,"数据库地址是pg.internal.com:5432"); wait()
W("user_a","s_a3",None,"公司营收5000万"); wait()

W("user_a","s_a4","task_a","任务目标是开发记忆系统三层聚合"); wait()
W("user_a","s_a4","task_a","数据模型和API已搭建完成"); wait()
W("user_a","s_a4","task_a","三层聚合全部完成测试通过"); wait()
W("user_a","s_a4","task_a","新目标是做系统性能优化"); wait()

# user_b: 偏好 + 事实冲突 + 任务
W("user_b","s_b1",None,"我用TDD写代码"); wait()
W("user_b","s_b1",None,"我改用BDD了"); wait()

W("user_b","s_b2",None,"生产环境在AWS东京"); wait()
W("user_b","s_b2",None,"生产环境搬到AWS新加坡了"); wait()
W("user_b","s_b2",None,"前端用React"); wait()

W("user_b","s_b3","task_b","任务是系统性能优化和压测"); wait()
W("user_b","s_b3","task_b","完成数据库索引优化查询降40%"); wait()
W("user_b","s_b3","task_b","压测全部通过系统稳定"); wait()

# user_c: 偏好 + 任务
W("user_c","s_c1",None,"我用React做前端"); wait()
W("user_c","s_c1",None,"我改用Vue了"); wait()
W("user_c","s_c1",None,"我喜欢暗色主题"); wait()

W("user_c","s_c2","task_c","任务是重构认证模块"); wait()
W("user_c","s_c2","task_c","确定用JWT方案技术选型完成"); wait()
W("user_c","s_c2","task_c","认证模块重构完成单元测试通过"); wait()

# ====== 100条随机 ======
print("\n=== 随机数据集 100条 ===")
DATASET = os.path.expanduser("~/Desktop/continue_zh.jsonl")
with open(DATASET,"r",encoding="utf-8") as f:
    lines = f.readlines()

random.seed(42)
samples = random.sample(list(enumerate(lines)), 100)
samples.sort()

for idx,(li,line) in enumerate(samples):
    d = json.loads(line)
    uid = f"u_{d['conversation_id']}"
    sid = f"s_{d['id']}"
    msgs = [{"role":"user","content":t["human"][:500]} for t in d["conversation"][:3]]
    requests.post(BASE + "/memory/write", headers={"X-API-Key":KEY,"X-User-Id":uid,"Content-Type":"application/json"}, json={"user_id":uid,"session_id":sid,"messages":msgs}, timeout=60)
    if (idx+1)%20==0: print(f"  随机 {idx+1}/100")

print("\n=== DONE: 130条 ===")
import subprocess
subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-c","SELECT status,COUNT(*) FROM t_memory GROUP BY status;"])
subprocess.run(["docker","exec","mem-postgres","psql","-U","memuser","-d","agent_memory","-c","SELECT user_id,COUNT(*) as total FROM t_memory WHERE user_id IN('user_a','user_b','user_c') GROUP BY user_id ORDER BY total DESC;"])
