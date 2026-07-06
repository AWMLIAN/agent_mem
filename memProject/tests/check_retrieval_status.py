"""检查多信号融合检索的完整状态"""
import sys; sys.path.insert(0, '.')
import json

print("=" * 50)
print("1. BM25 关键词检索 — 检查 fastembed 是否可用")
print("=" * 50)
try:
    import os; os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    from fastembed import SparseTextEmbedding
    bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")
    print("  BM25: OK (fastembed loaded)")
except Exception as e:
    print(f"  BM25: FAIL - {str(e)[:100]}")

print()
print("=" * 50)
print("2. 向量检索 — 检查 mem0 搜索是否返回结果")
print("=" * 50)
from app.services.mem0_client import mem0_client
mem0_client.initialize()
r = mem0_client.search("test", user_id="verify_1783305997")
results = r.get("results", [])
print(f"  向量检索: {len(results)} 条结果")
if results:
    print(f"  示例: {results[0].get('memory','')[:80]}")

print()
print("=" * 50)
print("3. 元数据过滤 — 检查 metadata 是否写入且可过滤")
print("=" * 50)
if results:
    item = results[0]
    meta = item.get("metadata", {})
    print(f"  metadata 存在: {bool(meta)}")
    print(f"  metadata 内容: {json.dumps(meta, ensure_ascii=False)}")
    print(f"  scene_id: {meta.get('scene_id', 'N/A')}")
    print(f"  task_id: {meta.get('task_id', 'N/A')}")

    # 模拟过滤
    from app.services.retrieval_service import _post_filter
    filtered = _post_filter(results, scene_id=meta.get("scene_id"))
    print(f"  按 scene_id={meta.get('scene_id')} 过滤: {len(results)} -> {len(filtered)} 条")
    if len(filtered) == 0:
        print("  FAIL: 后过滤不生效!")
    elif len(filtered) < len(results):
        print("  PASS: 过滤后结果减少")
    else:
        print("  CHECK: 过滤前后数量相同（可能该 scene 就是全部数据）")
else:
    print("  跳过（无检索结果）")

print()
print("=" * 50)
print("4. 融合排序 — 检查分数是否降序")
print("=" * 50)
if len(results) >= 2:
    scores = [item.get("score", 0) for item in results]
    ordered = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    print(f"  分数降序: {'PASS' if ordered else 'FAIL'}")
    print(f"  分数序列: {[round(s,3) for s in scores[:5]]}")
else:
    print("  跳过（不足2条）")

print()
print("=" * 50)
print("5. 后过滤修复 — 新写入带 metadata，验证过滤")
print("=" * 50)
import time
uid = f"filter_test_{int(time.time())}"
# 写3条不同scene的数据
for text, sid, tid in [
    ("我是后端", "scene_a", "task_x"),
    ("我是前端", "scene_b", "task_y"),
    ("我是测试", "scene_a", "task_z"),
]:
    mem0_client.add([{"role":"system","content":"请用中文记录"},{"role":"user","content":text}], user_id=uid,
                    metadata={"scene_id": sid, "task_id": tid})
time.sleep(2)
r = mem0_client.search("开发", user_id=uid)
all_items = r.get("results", [])
print(f"  写入3条, 检索到{len(all_items)}条")
filtered_a = _post_filter(all_items, scene_id="scene_a")
filtered_b = _post_filter(all_items, scene_id="scene_b")
print(f"  scene_a过滤: {len(filtered_a)}条, scene_b过滤: {len(filtered_b)}条")
if len(filtered_a) == 2 and len(filtered_b) == 1:
    print("  PASS: 后过滤正确")
else:
    print("  FAIL: 后过滤不正确")
    for item in all_items:
        m = item.get("metadata", {})
        print(f"    scene={m.get('scene_id')} task={m.get('task_id')} mem={item.get('memory','')[:50]}")
