"""排查 OpenMemory Server 配置和 mem0 初始化状态"""
import httpx
BASE = "http://localhost:8765"

# 1. 查看当前配置
r = httpx.get(f"{BASE}/api/v1/config/")
print("=== 当前配置 ===")
print(r.text[:800])

# 2. 直接调用 add_memories 看报错
r = httpx.post(f"{BASE}/api/v1/memories/", json={
    "user_id": "u1",
    "text": "test memory",
})
print("\n=== 记忆写入 ===")
print(r.status_code, r.text[:300])
