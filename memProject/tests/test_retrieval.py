"""测试多信号融合检索 — 写入 + 检索 + 过滤"""
import httpx, time

BASE = "http://localhost:8000/api/v1/memory"
UID = f"test_retrieval_{int(time.time())}"
TIMEOUT = 90

print(f"User: {UID}\n")

# === 1. 写入 3 条不同主题的记忆 ===
print("=== 1. 写入 3 条记忆 ===")
texts = [
    "我叫赵六，喜欢详细的技术方案，常用Python后端开发",
    "我是项目经理，需要每周汇报进度",
    "我喜欢简洁的UI设计，拒绝复杂交互",
]
for t in texts:
    r = httpx.post(f"{BASE}/write", json={
        "user_id": UID,
        "messages": [{"role": "user", "content": t}],
    }, timeout=TIMEOUT)
    data = r.json()
    mems = data.get("data", {}).get("results", [])
    if mems:
        for m in mems:
            print(f"  OK [{m.get('event','?')}] {m.get('memory','')[:80]}")
    else:
        print(f"  (skip) '{t[:20]}...'")

# === 2. 无过滤检索 ===
print("\n=== 2. 无过滤检索: '用户偏好' ===")
r = httpx.post(f"{BASE}/search", json={
    "query": "用户偏好", "user_id": UID, "top_k": 5,
}, timeout=TIMEOUT)
data = r.json().get("data", {})
for item in data.get("results", []):
    t = item.get("memory_type", "?")
    s = item.get("relevance_score", 0)
    c = item.get("content", "")[:80]
    print(f"  [{t}] score={s:.3f} {c}")

# === 3. 按类型过滤 ===
print("\n=== 3. 类型过滤: memory_types=['preference'] ===")
r = httpx.post(f"{BASE}/search", json={
    "query": "偏好", "user_id": UID, "memory_types": ["preference"], "top_k": 5,
}, timeout=TIMEOUT)
data = r.json().get("data", {})
for item in data.get("results", []):
    t = item.get("memory_type", "?")
    c = item.get("content", "")[:80]
    print(f"  [{t}] {c}")
if not data.get("results"):
    print("  (无结果，可能记忆类型字段未写入 metadata)")

# === 4. 语义检索：同义表达 ===
print("\n=== 4. 语义检索: '开发' 应匹配 'Python后端' ===")
r = httpx.post(f"{BASE}/search", json={
    "query": "开发技术栈", "user_id": UID, "top_k": 3,
}, timeout=TIMEOUT)
data = r.json().get("data", {})
for item in data.get("results", []):
    c = item.get("content", "")[:80]
    s = item.get("relevance_score", 0)
    print(f"  [{s:.3f}] {c}")

# === 5. 验证来源信息 ===
print("\n=== 5. 来源信息检查 ===")
if data.get("results"):
    item = data["results"][0]
    for key in ["memory_id", "content", "memory_type", "relevance_score", "agent_id", "scene_id", "session_id", "task_id", "created_at", "source_type"]:
        print(f"  {key}: {item.get(key, 'N/A')}")

print(f"\n=== 6. 检索耗时: {data.get('elapsed_ms', 'N/A')}ms ===")
print("Done")
