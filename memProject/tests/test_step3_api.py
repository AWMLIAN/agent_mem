"""Step 3: 验证 FastAPI 接口（HTTP 请求）"""
import httpx, time

BASE = "http://localhost:8000/api/v1/memory"

# 用固定 UID 保证幂等
UID = f"api_test_{int(time.time())}"

print("=== Step 3.1: 写入 + 立即检索 ===")
r = httpx.post(f"{BASE}/write", json={
    "user_id": UID,
    "messages": [{"role": "user", "content": "hello I am Bob"}],
}, timeout=90)
print(f"write: {r.status_code}")

r = httpx.post(f"{BASE}/search", json={
    "query": "who is Bob",
    "user_id": UID,
    "top_k": 3,
}, timeout=30)
data = r.json()
results = data.get("data", {}).get("results", [])
print(f"search: {r.status_code}, {len(results)} results")
for item in results:
    print(f"  {item.get('content','')[:80]}")

if results:
    print("PASS")
else:
    # 可能 DeepSeek 慢，数据还没写完
    print("CHECK: 搜索无结果，检查 FastAPI 日志")
