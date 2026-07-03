"""测试 mem0 add + search"""
import sys
sys.path.insert(0, '.')
from app.services.mem0_client import mem0_client

mem0_client.initialize()

# 写入
r = mem0_client.add(
    [{"role": "user", "content": "我叫张三，是一名后端工程师，喜欢简洁的回复风格"}],
    user_id="test_u1",
)
print("=== add 结果 ===")
for item in r.get("results", []):
    print(f"  {item['event']}: {item['memory']}")

# 检索
r2 = mem0_client.search("用户叫什么名字", user_id="test_u1", limit=5)
print("\n=== search 结果 ===")
for item in r2.get("results", []):
    print(f"  [{item.get('memory','')[:80]}]")
