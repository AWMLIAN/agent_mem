"""Step 2: 验证 retrieval_service（过滤条件 + 结果格式化）"""
import sys; sys.path.insert(0, '.')
from app.services.retrieval_service import search, build_filters
import json

print("=== Step 2.1: build_filters ===")
f = build_filters(
    user_id="u1",
    scene_id="s1",
    task_id="t1",
    memory_types=["preference", "fact"],
    time_start="2026-01-01T00:00:00",
)
print(json.dumps(f, indent=2, ensure_ascii=False))

print("\n=== Step 2.2: 完整检索 ===")
r = search(
    query="偏好",
    user_id="test_retrieval_1783300877",
    top_k=5,
)
print(f"total_candidates: {r['total_candidates']}")
print(f"elapsed_ms: {r['elapsed_ms']}")
for item in r.get("results", []):
    print(f"  [{item.get('relevance_score',0):.3f}] {item.get('memory_type','?')}: {item.get('content','')[:80]}")
if r["total_candidates"] > 0:
    print("PASS")
else:
    print("FAIL: 无结果")
