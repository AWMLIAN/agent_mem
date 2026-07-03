"""测试完整链路: FastAPI → MCP Client → OpenMemory Server"""
import httpx

# 确保两个 server 都在运行
# Terminal 1: memProject FastAPI :8000
# Terminal 2: OpenMemory :8765

# 测试 memory/write
print("=== 测试 memory/write ===")
r = httpx.post("http://localhost:8000/api/v1/memory/write", json={
    "user_id": "u1",
    "messages": [{"role": "user", "content": "我叫张三，喜欢简洁回复"}]
})
print(r.status_code, r.text[:300])

# 测试 memory/search
print("\n=== 测试 memory/search ===")
r = httpx.post("http://localhost:8000/api/v1/memory/search", json={
    "query": "用户叫什么名字",
    "user_id": "u1",
    "top_k": 5,
})
print(r.status_code, r.text[:300])
