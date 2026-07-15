"""测试：通用记忆建模与多层记忆管理"""
import httpx, time
BASE = "http://localhost:8000/api/v1"
OK, FAIL = 0, 0
SEP = "=" * 55

def check(label, condition, detail=""):
    global OK, FAIL
    if condition: OK += 1; print(f"  PASS: {label}")
    else: FAIL += 1; print(f"  FAIL: {label} {detail}")

# ────────────────────────────────────────────────────────────
UID   = f"u_model_{int(time.time())}"
SID   = "sess_model_001"
TID   = "task_model_001"
SCENE = "scene_model_test"

# ────────────────────────────────────────────────────────────
# M: 记忆单元 + 元数据建模
# ────────────────────────────────────────────────────────────
print(f"{SEP}\nM: 记忆建模 — 验证 t_interaction_record + t_memory 表字段\n{SEP}\n")

r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": UID, "scene_id": SCENE, "session_id": SID, "task_id": TID,
    "messages": [{"role": "user", "content": "我叫张三，是后端工程师"}],
}, timeout=10)
check("写入200", r.status_code == 200)
results = r.json()["data"].get("results", [])
has_mem = len(results) > 0
check("提取出记忆", has_mem)
if has_mem:
    mem = results[0]
    check("M-1 content有值", len(mem.get("memory", "")) > 0,
          f"memory={mem.get('memory','')[:50]}")
    check("M-2 event=ADD", mem.get("event") == "ADD",
          f"event={mem.get('event')}")
    check("M-3 id生成", len(mem.get("id", "")) > 10,
          f"id={mem.get('id','')[:20]}")

# M-4: 验证 5 个标识字段都传到了（查 t_interaction_record）
print(f"\n  >> 检查 t_interaction_record 最新记录：")
print(f"  >> user_id={UID}")
print(f"  >> session_id={SID}")
print(f"  >> task_id={TID}")
print(f"  >> scene_id={SCENE}")
print(f"  >> role=user, content=我叫张三..., processed=false")

# ────────────────────────────────────────────────────────────
# M-5: 任务状态机
# ────────────────────────────────────────────────────────────
print(f"\n{SEP}\nM-5: 任务状态机 — 验证 t_task 表\n{SEP}\n")

UID_TASK = f"u_task_{int(time.time())}"
r = httpx.post(f"{BASE}/task", json={
    "user_id": UID_TASK, "title": "编写技术方案", "goal": "完成Q3技术方案",
    "scene_id": SCENE,
}, timeout=10)
tid = r.json()["data"]["task_id"]
check("task_id以task_开头", tid.startswith("task_"))
check("初始pending", r.json()["data"]["status"] == "pending")
print(f"  >> Navicat t_task: task_id={tid}, status=pending")

# in_progress
r = httpx.put(f"{BASE}/task/{tid}", json={
    "status": "in_progress", "progress": "已完成需求分析",
    "completed_items": ["需求文档"], "pending_items": ["技术方案", "代码实现"],
}, timeout=10)
check("→in_progress", r.json()["data"]["status"] == "in_progress")
print(f"  >> status=in_progress, progress=已完成需求分析")

# 完成
r = httpx.post(f"{BASE}/task/{tid}/complete", timeout=10)
check("→completed", r.json()["data"]["status"] == "completed")

# 非法: completed → pending (不允许)
r = httpx.put(f"{BASE}/task/{tid}", json={"status": "pending"}, timeout=10)
check("completed→pending被拒", r.json().get("code") == -1)
print(f"  >> code=-1, error_code=CONFLICT_ERROR")

# 进展
r = httpx.get(f"{BASE}/task/{tid}/progress", timeout=10)
check("进展摘要200", r.status_code == 200)
print(f"  >> completed_count={r.json()['data']['completed_count']},"
      f" related_memory_count={r.json()['data']['related_memory_count']}")

print(f"\n  >> 状态变化: pending → in_progress → completed")
print(f"  >> ended_at 应有值（标记完成时间）")

# ────────────────────────────────────────────────────────────
# L-2: 会话级记忆
# ────────────────────────────────────────────────────────────
print(f"\n{SEP}\nL-2: 会话级记忆 — 验证 t_interaction_record\n{SEP}\n")

SESS = "sess_layer_test"
for i, text in enumerate(["第一轮：见面问候", "第二轮：讨论方案"]):
    r = httpx.post(f"{BASE}/memory/write", json={
        "user_id": UID, "session_id": SESS,
        "messages": [{"role": "user", "content": text}],
    }, timeout=10)
    check(f"轮次{i+1}写入200", r.status_code == 200)

print(f"\n  >> Navicat: SELECT * FROM t_interaction_record WHERE session_id='{SESS}'")
print(f"  >> 预期: 2条记录, session_id相同, recorded_at递增")

# ────────────────────────────────────────────────────────────
# L-1: 用户级检索
# ────────────────────────────────────────────────────────────
print(f"\n{SEP}\nL-1: 用户级检索 — 通过 /search 验证记忆可被召回\n{SEP}\n")

r = httpx.post(f"{BASE}/memory/search", json={
    "query": "偏好", "user_id": UID, "top_k": 10,
}, timeout=10)
results = r.json()["data"].get("results", [])
check("检索200", r.status_code == 200)
check("返回结果≥1", len(results) >= 1, f"实际{len(results)}条。"
     "注：当前写入用mock抽取(写t_interaction_record)，"
     "检索用mem0(查Qdrant)，两条路径不同，需mem0抽取启用后才有结果。"
     "暂时预期为0条，Phase 3打通后应有结果。")

# ────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  结果: {OK} PASS / {FAIL} FAIL")
print(f"{SEP}")
print(f"\n  需检查的4张表：")
print(f"  1. t_interaction_record — user_id={UID}, 多条会话记录")
print(f"  2. t_task — task_id={tid}, pending→in_progress→completed")
print(f"  3. t_memory — user_id={UID} 的记忆记录")
print(f"  4. t_session — 会话记录（如有创建）")
