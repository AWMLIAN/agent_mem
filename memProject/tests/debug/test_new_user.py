"""测试全新用户"""
import httpx

# 新用户，超时设 60 秒（LLM 调用慢）
print("=== Write: new user u99 ===")
r = httpx.post("http://localhost:8000/api/v1/memory/write", json={
    "user_id": "u99",
    "messages": [{"role": "user", "content": "my name is Bob, I work at Google"}]
}, timeout=60)
print(r.status_code, r.text[:300])
