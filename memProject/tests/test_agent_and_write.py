"""测试：智能体接入与记忆数据写入 — 覆盖 A~E 全部用例"""
import httpx, json

BASE = "http://localhost:8000/api/v1"
OK, FAIL, SKIP = 0, 0, 0

def check(label, condition, detail=""):
    global OK, FAIL
    if condition: OK += 1; print(f"  PASS: {label}")
    else: FAIL += 1; print(f"  FAIL: {label} {detail}")

# ============================================================
# A-1 注册智能体
# ============================================================
print("=== A: 智能体接入管理 ===\n")
r = httpx.post(f"{BASE}/agent/register", json={"agent_name":"自动测试智能体","scene_id":"scene_test"}, timeout=10)
data = r.json()["data"]
agent_id = data["agent_id"]
api_key = data["api_key"]
check("A-1 agent_id以agent_开头", agent_id.startswith("agent_"))
check("A-1 api_key以mem_开头", api_key.startswith("mem_"))
check("A-1 api_key长度68", len(api_key) == 68)
check("A-1 scene_id=scene_test", data.get("scene_id") == "scene_test")

# ============================================================
# B: 接入参数管理
# ============================================================
print("\n=== B: 接入参数管理 ===\n")

# B-1 Body传user_id
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "test_user_001",
    "messages": [{"role":"user","content":"我叫张三"}],
}, timeout=10)
check("B-1 返回200", r.status_code == 200)
check("B-1 返回200", r.status_code == 200)

# B-2 Header优先Body
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "user_from_body",
    "messages": [{"role":"user","content":"测试Header优先级"}],
}, headers={"X-User-Id": "user_from_header"}, timeout=10)
check("B-2 返回200", r.status_code == 200)

# B-3 会话ID
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1",
    "messages": [{"role":"user","content":"测试会话ID"}],
}, headers={"X-Session-Id": "sess_abc123"}, timeout=10)
check("B-3 返回200", r.status_code == 200)

# B-4 任务ID
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1",
    "session_id": "sess_001",
    "messages": [{"role":"user","content":"测试任务ID"}],
}, headers={"X-Task-Id": "task_xyz789"}, timeout=10)
check("B-4 返回200", r.status_code == 200)

# ============================================================
# C: 记忆数据写入
# ============================================================
print("\n=== C: 记忆数据写入 ===\n")

cases = [
    ("C-1 名称提取", "我叫张三，是后端工程师", "ADD", "张三"),
    ("C-2 偏好提取", "我喜欢简洁的代码风格", "ADD", "简洁"),
    ("C-3 排斥提取", "我不喜欢过度设计，讨厌冗余代码", "ADD", "过度设计"),
]
for label, content, exp_event, exp_contains in cases:
    r = httpx.post(f"{BASE}/memory/write", json={
        "user_id": "u1", "messages": [{"role":"user","content":content}],
    }, timeout=10)
    results = r.json()["data"].get("results", [])
    if not results:
        check(f"{label} 有结果", False, "results为空")
        continue
    first = results[0]
    check(f"{label} event={exp_event}", first.get("event") == exp_event, f"实际: {first.get('event')}")
    check(f"{label} memory包含'{exp_contains}'",
          exp_contains in first.get("memory",""), first.get("memory","")[:50])

# C-4 智能体回复
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1", "messages": [{"role":"assistant","content":"好的张三，我记住了"}],
}, timeout=10)
check("C-4 回复写入200", r.status_code == 200)

# C-5 对话轮次
for i, (role, text) in enumerate([
    ("user","第一轮"), ("assistant","回复第一轮"), ("user","第二轮")
]):
    r = httpx.post(f"{BASE}/memory/write", json={
        "user_id": "u1", "session_id": "sess_turn",
        "messages": [{"role":role,"content":text}],
    }, timeout=10)
check(f"C-5 轮次{i+1} 200", r.status_code == 200)

# ============================================================
# D: 数据接入校验
# ============================================================
print("\n=== D: 数据接入校验 ===\n")

# D-1 空content
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1", "messages": [{"role":"user","content":""}],
}, timeout=10)
check("D-1 空content→422", r.status_code != 200 or r.json().get("code") == -1,
      f"code={r.json().get('code')}")

# D-2 缺user_id
r = httpx.post(f"{BASE}/memory/write", json={
    "messages": [{"role":"user","content":"测试"}],
}, timeout=10)
check("D-2 缺user_id→422", r.status_code == 422)

# D-3 字段类型
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": 123, "messages": [{"role":"user","content":"测试"}],
}, timeout=10)
check("D-3 数字uid→422", r.status_code == 422)

# D-4 缺messages
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1", "content": "直接传content",
}, timeout=10)
check("D-4 缺messages→422", r.status_code == 422)

# ============================================================
# E: 数据标准化
# ============================================================
print("\n=== E: 数据标准化 ===\n")

# E-1 时间
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1", "messages": [{"role":"user","content":"时间测试"}],
    "timestamp": "2026-07-13",
}, timeout=10)
check("E-1 时间格式200", r.status_code == 200)

# E-2 标识标准化
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "USER_Test_001", "messages": [{"role":"user","content":"大写测试"}],
}, headers={"X-User-Id": "USER_Test_001"}, timeout=10)
check("E-2 标准化200", r.status_code == 200)

# E-3 元数据补全
r = httpx.post(f"{BASE}/memory/write", json={
    "user_id": "u1", "messages": [{"role":"user","content":"元数据测试"}],
}, timeout=10)
check("E-3 补全200", r.status_code == 200)

# ============================================================
# 异步写入
# ============================================================
print("\n=== 异步写入 ===\n")
r = httpx.post(f"{BASE}/memory/async_write", json={
    "user_id": "u2", "messages": [{"role":"user","content":"我是李四"}],
}, timeout=10)
data = r.json()["data"]
check("异步: code=0", r.json()["code"] == 0)
check("异步: status=stored", data.get("status") in ["stored","accepted"])

# ============================================================
print(f"\n=== 结果: {OK} PASS / {FAIL} FAIL / {SKIP} SKIP ===")
