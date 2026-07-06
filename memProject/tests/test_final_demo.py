"""多信号融合检索演示 — 每条结果完整输出"""
import sys; sys.path.insert(0, '.')
import os; os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import time, json
from app.services.retrieval_service import search
from app.services.mem0_client import mem0_client

mem0_client.initialize()
UID = f"demo_{int(time.time())}"

# ============================================================
# 写入 25 条
# ============================================================
data = [
    ("我叫张伟，是后端组长", "scene_dev", "task_backend"),
    ("主语言是Python，框架用FastAPI", "scene_dev", "task_backend"),
    ("数据库用PostgreSQL，缓存用Redis", "scene_dev", "task_backend"),
    ("代码风格偏好简洁，不喜欢过度设计", "scene_dev", "task_coding"),
    ("需要单元测试覆盖率达到80%", "scene_dev", "task_coding"),
    ("API文档用Swagger自动生成", "scene_dev", "task_coding"),
    ("部署用Docker和K8s", "scene_dev", "task_devops"),
    ("日志用ELK收集", "scene_dev", "task_devops"),
    ("监控用Prometheus和Grafana", "scene_dev", "task_devops"),
    ("代码仓库用GitLab", "scene_dev", "task_devops"),
    ("我叫李婷，是UI设计师", "scene_design", "task_ui"),
    ("设计工具用Figma", "scene_design", "task_ui"),
    ("偏好深色主题界面", "scene_design", "task_theme"),
    ("按钮圆角用8px", "scene_design", "task_theme"),
    ("字体用苹方，字号14px", "scene_design", "task_theme"),
    ("间距统一用8的倍数", "scene_design", "task_layout"),
    ("响应式布局支持移动端", "scene_design", "task_layout"),
    ("交互动效不超过300ms", "scene_design", "task_anim"),
    ("我叫王强，是项目经理", "scene_mgmt", "task_report"),
    ("每周五下午3点开周会", "scene_mgmt", "task_report"),
    ("周报模板包含进度、风险和下周计划", "scene_mgmt", "task_report"),
    ("项目截止日期是7月30日", "scene_mgmt", "task_deadline"),
    ("本季度OKR：用户增长30%", "scene_mgmt", "task_okr"),
    ("团队共8人，3前端4后端1设计", "scene_mgmt", "task_team"),
    ("每天站会9:30，不超过15分钟", "scene_mgmt", "task_team"),
]

print("写入 25 条知识...")
for text, sid, tid in data:
    mem0_client.add(
        [{"role":"system","content":"请用中文提取和记录所有记忆内容。"},
         {"role":"user","content":text}],
        user_id=UID, metadata={"scene_id": sid, "task_id": tid}
    )
time.sleep(3)
print(f"写入完成 (UID: {UID})\n")


def show_results(results):
    """格式化输出检索结果"""
    if not results:
        print("    (无结果)")
        return
    for i, item in enumerate(results):
        score = item.get('relevance_score', 0)
        sid = item.get('scene_id', '')[:10]
        tid = item.get('task_id', '')[:12]
        content = item.get('content', '')[:70]
        print(f"    [{i+1}] [分数:{score:.3f}] {content}")
        print(f"         scene={sid}  task={tid}")


# ============================================================
# 1. 语义向量检索
# ============================================================
print("=" * 70)
print("1. 语义向量检索")
print("=" * 70)
queries = [
    ("后端技术栈", "语义相近的 'Python' 'FastAPI' '后端' 应排前"),
    ("设计规范", "语义相近的 '圆角' '间距' '字体' 应排前"),
    ("团队管理", "语义相近的 '站会' 'OKR' '周报' 应排前"),
]
for q, explain in queries:
    print(f"\n  查询: '{q}' — ({explain})")
    r = search(query=q, user_id=UID, top_k=5)
    show_results(r["results"])
    print(f"  候选: {r['total_candidates']}条, 耗时: {r['elapsed_ms']}ms")

# ============================================================
# 2. 关键词精确检索
# ============================================================
print("\n" + "=" * 70)
print("2. 关键词精确检索 (BM25)")
print("=" * 70)
for kw in ["周报", "Redis", "Figma", "K8s", "OKR"]:
    print(f"\n  关键词: '{kw}'")
    r = search(query=kw, user_id=UID, top_k=3)
    show_results(r["results"])
    print(f"  候选: {r['total_candidates']}条")

# ============================================================
# 3. 元数据过滤：按场景
# ============================================================
print("\n" + "=" * 70)
print("3. 元数据过滤: 按 scene_id")
print("=" * 70)
print(f"\n  查询: '设计规范'")
for label, sid in [("无过滤", None), ("只查 scene_dev", "scene_dev"),
                    ("只查 scene_design", "scene_design"), ("只查 scene_mgmt", "scene_mgmt")]:
    print(f"\n  [{label}]")
    r = search(query="设计规范", user_id=UID, scene_id=sid, top_k=3)
    show_results(r["results"])
    print(f"  mem0召回{r['total_candidates']}条 → 过滤后{r['filtered_count']}条 → Top-{len(r['results'])}显示")

# ============================================================
# 4. 元数据过滤：按任务
# ============================================================
print("\n" + "=" * 70)
print("4. 元数据过滤: 按 task_id")
print("=" * 70)
print(f"\n  查询: '技术工具'")
for label, tid in [("无过滤", None), ("只查 task_devops", "task_devops"),
                    ("只查 task_backend", "task_backend"), ("只查 task_theme", "task_theme")]:
    print(f"\n  [{label}]")
    r = search(query="技术工具", user_id=UID, task_id=tid, top_k=3)
    show_results(r["results"])
    print(f"  mem0召回{r['total_candidates']}条 → 过滤后{r['filtered_count']}条 → Top-{len(r['results'])}显示")

# ============================================================
# 5. 分数排序验证
# ============================================================
print("\n" + "=" * 70)
print("5. 分数排序验证")
print("=" * 70)
for q in ["代码规范", "项目进度", "设计方案"]:
    r = search(query=q, user_id=UID, top_k=5)
    scores = [item["relevance_score"] for item in r["results"]]
    desc = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    print(f"\n  查询 '{q}' 分数: {[round(s,3) for s in scores]}")
    print(f"  降序: {'PASS' if desc else 'FAIL'}")
    show_results(r["results"])
