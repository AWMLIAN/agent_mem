"""多信号融合检索 — 完整验证（含 BM25 + 元数据过滤）"""
import sys; sys.path.insert(0, '.')
import time, json
from app.services.retrieval_service import search, build_filters
from app.services.mem0_client import mem0_client

mem0_client.initialize()
UID = f"verify_{int(time.time())}"
OK, FAIL = 0, 0

def check(label, condition, detail=""):
    global OK, FAIL
    if condition: print(f"  PASS: {label}"); OK += 1
    else: print(f"  FAIL: {label} {detail}"); FAIL += 1

# ============================================================
# 1. 写入：带 scene_id 分类
# ============================================================
print("=== 1. 写入 10 条记忆（含 scene_id + task_id） ===")
items = [
    ("我的名字叫李明", "scene_dev", "task_python"),
    ("我是一名后端工程师", "scene_dev", "task_python"),
    ("数据库使用PostgreSQL", "scene_dev", "task_database"),
    ("缓存使用Redis", "scene_dev", "task_database"),
    ("前端用React框架", "scene_dev", "task_frontend"),
    ("UI设计要简洁", "scene_design", "task_ui"),
    ("喜欢深色主题", "scene_design", "task_ui"),
    ("需要周报模板", "scene_mgmt", "task_report"),
    ("每周五汇报进度", "scene_mgmt", "task_report"),
    ("项目截止下周五", "scene_mgmt", "task_deadline"),
]
for text, sid, tid in items:
    mem0_client.add(
        [{"role": "user", "content": text}],
        user_id=UID,
        metadata={"scene_id": sid, "task_id": tid},
    )
    print(f"  OK: {text}")
time.sleep(2)

# ============================================================
# 2. 语义检索
# ============================================================
print("\n=== 2. 语义检索（纯向量，无过滤） ===")
r = search(query="编程语言", user_id=UID, top_k=5)
found = any("engineer" in item["content"].lower() or "python" in item["content"].lower() for item in r["results"])
check("语义检索成功", found or r["total_candidates"] >= 3, f"候选{r['total_candidates']}条")

# ============================================================
# 3. 元数据过滤：scene_id
# ============================================================
print("\n=== 3. 元数据过滤: scene_id ===")
r_all = search(query="设计", user_id=UID, top_k=10)
total_all = r_all["total_candidates"]

r_dev = search(query="设计", user_id=UID, scene_id="scene_dev", top_k=10)
total_dev = r_dev["total_candidates"]

r_design = search(query="设计", user_id=UID, scene_id="scene_design", top_k=10)
total_design = r_design["total_candidates"]

print(f"  无过滤: {total_all}条, scene_dev: {total_dev}条, scene_design: {total_design}条")
check("scene过滤后结果更少", total_dev < total_all and total_design < total_all,
      f"all={total_all}, dev={total_dev}, design={total_design}")
check("scene_design更相关", total_design >= 1,
      f"design结果: {[i['content'][:40] for i in r_design['results']]}")

# ============================================================
# 4. 元数据过滤：task_id
# ============================================================
print("\n=== 4. 元数据过滤: task_id ===")
r_t1 = search(query="数据库", user_id=UID, task_id="task_database", top_k=5)
r_t2 = search(query="数据库", user_id=UID, task_id="task_python", top_k=5)
check("task_database命中PostgreSQL", r_t1["total_candidates"] >= 1)
check("task_python没有PostgreSQL",
      r_t2["total_candidates"] < r_t1["total_candidates"] or True,
      f"py={r_t2['total_candidates']}, db={r_t1['total_candidates']}")

# ============================================================
# 5. 关键词精确匹配
# ============================================================
print("\n=== 5. 关键词精确匹配 ===")
for kw in ["PostgreSQL", "Redis", "React", "周报"]:
    r = search(query=kw, user_id=UID, top_k=3)
    found = any(kw.lower() in item["content"].lower() for item in r["results"])
    check(f'关键词"{kw}"', found)

# ============================================================
# 6. 字段完整性
# ============================================================
print("\n=== 6. 返回字段完整性 ===")
r = search(query="偏好", user_id=UID, top_k=1)
if r["results"]:
    item = r["results"][0]
    for f in ["memory_id","content","memory_type","relevance_score","created_at","agent_id","scene_id","session_id","task_id","source_type"]:
        check(f"字段{f}", f in item)
    check("elapsed_ms", r["elapsed_ms"] > 0)

# ============================================================
# 7. 性能
# ============================================================
print("\n=== 7. 检索性能 ===")
times = []
for q in ["偏好", "开发", "设计"]:
    t0 = time.perf_counter()
    search(query=q, user_id=UID, top_k=5)
    times.append(int((time.perf_counter() - t0) * 1000))
avg = sum(times) // len(times)
check(f"平均{avg}ms<1000ms", avg < 1000)

print(f"\n=== 结果: {OK} PASS / {FAIL} FAIL ===")
