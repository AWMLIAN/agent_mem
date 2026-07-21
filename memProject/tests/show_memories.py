"""查看 Qdrant 中存储的记忆及元数据"""
import sys; sys.path.insert(0, '.')
from app.services.mem0_client import mem0_client
from app.services.retrieval_service import search

mem0_client.initialize()
UID = input("请输入 user_id: ").strip()

print(f"\n{'='*60}")
print(f"用户: {UID}")
print(f"{'='*60}")

r = mem0_client.search("test", user_id=UID, limit=20)
results = r.get("results", [])
print(f"\n>>> Qdrant 记忆 ({len(results)} 条) <<<\n")
for i, item in enumerate(results):
    meta = item.get("metadata", {}) or {}
    print(f"  [{i+1}] {item.get('memory','')[:80]}")
    print(f"       scene={meta.get('scene_id','?')}  task={meta.get('task_id','?')}")

if results:
    sample_scene = results[0].get("metadata",{}).get("scene_id")
    sample_task = results[0].get("metadata",{}).get("task_id")
    print(f"\n>>> 过滤对比 <<<")
    r = search(query="偏好", user_id=UID, top_k=20)
    print(f"  无过滤: {r['filtered_count']}条")
    if sample_scene:
        r = search(query="偏好", user_id=UID, scene_id=sample_scene, top_k=20)
        print(f"  scene={sample_scene}: {r['filtered_count']}条")
    if sample_task:
        r = search(query="偏好", user_id=UID, task_id=sample_task, top_k=20)
        print(f"  task={sample_task}: {r['filtered_count']}条")
