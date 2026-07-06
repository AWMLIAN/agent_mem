"""Step 1: 验证 mem0_client 初始化和基本搜索"""
import sys; sys.path.insert(0, '.')
from app.services.mem0_client import mem0_client

print("=== Step 1.1: 初始化 ===")
ok = mem0_client.initialize()
print(f"初始化: {'OK' if ok else 'FAIL'}")

print("\n=== Step 1.2: 搜索测试 ===")
# 用之前测试留下的 UID
r = mem0_client.search("偏好", user_id="test_retrieval_1783300877")
results = r.get("results", [])
print(f"找到 {len(results)} 条结果")
for item in results[:3]:
    print(f"  [{item.get('score',0):.3f}] {item.get('memory','')[:80]}")
if results:
    print("PASS")
else:
    print("FAIL: 无结果")
