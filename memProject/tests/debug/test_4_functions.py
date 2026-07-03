"""测试 OpenMemory MCP 4 个核心工具"""
import httpx, asyncio, json

BASE = "http://localhost:8000/api/v1/memory"
UID = "test_user_001"
TIMEOUT = 60

def post(path, json_data=None, params=None):
    r = httpx.post(f"{BASE}{path}", json=json_data, params=params, timeout=TIMEOUT)
    return r.status_code, r.json()

# 1. add_memories
print("=== 1. add_memories: 写入 2 条记忆 ===")
for text in ["我叫张三，喜欢简洁回复", "我是后端工程师，常用Python"]:
    code, resp = post("/write", {"user_id": UID, "messages": [{"role": "user", "content": text}]})
    print(f"  写入 '{text[:20]}...': {code}")

# 2. list_memories
print("\n=== 2. list_memories: 查看全部记忆 ===")
code, resp = post("/list", params={"user_id": UID})
print(f"  {code}: {json.dumps(resp.get('data',''), ensure_ascii=False)[:500]}")

# 3. search_memory
print("\n=== 3. search_memory: 检索记忆 ===")
code, resp = post("/search", {"query": "用户叫什么名字", "user_id": UID, "top_k": 5})
print(f"  {code}: {json.dumps(resp.get('data',''), ensure_ascii=False)[:500]}")

# 4. delete_all_memories
print("\n=== 4. delete_all_memories: 清除全部记忆 ===")
code, resp = post("/delete-all", params={"user_id": UID})
print(f"  {code}: {json.dumps(resp.get('data',''), ensure_ascii=False)[:200]}")

# 5. verify deleted
print("\n=== 5. 验证已清空 ===")
code, resp = post("/list", params={"user_id": UID})
print(f"  {code}: {json.dumps(resp.get('data',''), ensure_ascii=False)[:200]}")
