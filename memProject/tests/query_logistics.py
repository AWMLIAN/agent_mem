"""
物流场景检索测试 — 多维度可观测版。
覆盖: 语义检索 / 关键词检索 / 实体匹配 / 场景过滤 / 任务过滤 / 会话过滤 /
      记忆类型过滤 / 状态过滤 / 时间范围 / TopK / Reranker

用法:
  python tests/query_logistics.py
  python tests/query_logistics.py --verbose
"""
import sys; sys.path.insert(0, '.')
import json, os, time, argparse

import httpx

INFO_FILE = os.path.join(os.path.dirname(__file__), "_logistics_info.json")
try:
    with open(INFO_FILE) as f: SEED_INFO = json.load(f)
except FileNotFoundError:
    SEED_INFO = {"user_id": "logistics_test_user"}
USER_ID = SEED_INFO.get("user_id", "logistics_test_user")


def show_results(label, results, ms, kw=None):
    """格式化打印检索结果"""
    print(f"{'='*70}")
    print(f"{label}  —  {len(results)} 条 / {ms}ms")
    print(f"{'─'*70}")
    for i, item in enumerate(results):
        c = item.get("content", "")
        print(f"  [{i+1}] type={item.get('memory_type','?')} score={item.get('relevance_score',0):.3f} "
              f"scene={item.get('scene_id','?')} task={item.get('task_id','?')}")
        print(f"      {c[:120]}")
    if kw and results:
        all_text = " ".join(r.get("content", "") for r in results)
        hit = [k for k in kw if k in all_text]
        miss = [k for k in kw if k not in all_text]
        print(f"  关键词: 命中 {hit}  缺失 {miss}")
    print()


def search(query, **filters):
    """调 /api/v1/memory/search，返回 (results, elapsed_ms)"""
    body = {"query": query, "user_id": USER_ID, "top_k": 5, "rerank": True}
    body.update(filters)
    t0 = time.perf_counter()
    r = httpx.post("http://localhost:8000/api/v1/memory/search", json=body, timeout=120)
    ms = round((time.perf_counter() - t0) * 1000)
    if r.status_code == 200:
        return r.json()["data"]["results"], ms
    else:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return [], ms


def test():
    print(f"用户: {USER_ID}  |  场景: logistics-large-test")
    print(f"4 个任务: log_route_001 / log_warehouse_002 / log_delivery_003 / log_compliance_004\n")

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("一、语义向量检索（Qdrant cosine，无任何过滤）")
    print("="*70)
    for q in ["路线优化技术栈", "安全库存补货", "车辆检查", "温控合规"]:
        results, ms = search(q)
        show_results(f"语义: '{q}'", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("二、关键词精确检索（mem0 BM25 + 语义融合）")
    print("="*70)
    for kw in ["Python", "摄氏度", "油量", "730", "告警"]:
        results, ms = search(kw, keyword=kw)
        show_results(f"关键词: '{kw}'", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("三、实体匹配检索（mem0 entity boost 自动生效）")
    print("="*70)
    for entity_q in ["冷链", "配送", "库存", "合规"]:
        results, ms = search(entity_q)
        show_results(f"实体: '{entity_q}'", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("四、场景过滤 (scene_id)")
    print("="*70)
    results, ms = search("路线 库存 配送 合规")
    show_results("无过滤", results, ms)

    for sid in [None, "logistics-large-test", "scene_code"]:
        label = sid or "无过滤"
        results, ms = search("路线 库存 配送 合规", scene_id=sid)
        show_results(f"scene_id={label}", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("五、任务过滤 (task_id)")
    print("="*70)
    task_queries = [
        ("log_route_001", "路线优化 Python OR-Tools"),
        ("log_warehouse_002", "库存 仓库 安全库存"),
        ("log_delivery_003", "配送 车辆 司机"),
        ("log_compliance_004", "温控 合规 监管"),
    ]
    for tid, q in task_queries:
        results, ms = search(q, task_id=tid)
        show_results(f"task_id={tid}", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("六、记忆类型过滤 (memory_type)")
    print("="*70)
    for mtype in ["preference", "fact", "decision", "constraint", "task"]:
        results, ms = search("路线", memory_types=[mtype])
        show_results(f"memory_type={mtype}", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("七、状态过滤 (status)")
    print("="*70)
    for st in [None, "active", "deleted", "archived"]:
        label = st or "不传(默认active)"
        kwargs = {}
        if st:
            kwargs["status"] = [st]
        results, ms = search("路线", **kwargs)
        show_results(f"status={label}", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("八、时间范围过滤 (created_at)")
    print("="*70)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    results, ms = search("路线", time_start=(now - timedelta(hours=1)).isoformat())
    show_results("最近1小时", results, ms)
    results, ms = search("路线", time_end=(now - timedelta(days=1)).isoformat())
    show_results("1天前", results, ms)
    results, ms = search("路线",
        time_start=(now - timedelta(days=7)).isoformat(),
        time_end=now.isoformat())
    show_results("最近7天", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("九、TopK 控制")
    print("="*70)
    for k in [1, 3, 5, 10]:
        results, ms = search("路线", top_k=k)
        show_results(f"top_k={k}", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("十、Reranker 对比")
    print("="*70)
    results_on, ms_on = search("路线优化项目", rerank=True)
    results_off, ms_off = search("路线优化项目", rerank=False)
    show_results(f"rerank=True ({ms_on}ms)", results_on, ms_on)
    show_results(f"rerank=False ({ms_off}ms)", results_off, ms_off)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("十一、组合过滤")
    print("="*70)
    results, ms = search("库存 安全",
        task_id="log_warehouse_002",
        memory_types=["fact", "decision"])
    show_results("task=log_warehouse_002 + type=[fact,decision]", results, ms)

    # ═══════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("十二、8 条标准 query 验证（含关键词检查）")
    print("="*70)

    STD_QUERIES = [
        ("Q001", "路线优化项目使用什么技术栈？","log_route_001",
         ["Python 3.12","FastAPI","PostgreSQL 16","OR-Tools"]),
        ("Q002", "济南冷链路线优化目前完成到哪个阶段，下一步是什么，高峰与普通时段分别优化什么目标，最终验收指标有哪些？","log_route_001",
         ["车辆路径算法","接口联调","准时率","运输成本","90 秒"]),
        ("Q003", "A 类商品的安全库存是多少？","log_warehouse_002",
         ["300 件","800 件"]),
        ("Q004", "仓库如何管理不同温区、入库异常、盘点差异和出库复核，分别有哪些温度、时间或错误率要求？","log_warehouse_002",
         ["2 至 8 摄氏度","零下 18 摄氏度","30 天","0.5%","0.2%"]),
        ("Q005", "车辆出发前检查哪四项？","log_delivery_003",
         ["油量","制冷机","车门密封","定位设备"]),
        ("Q006", "配送途中出现车辆一级故障或预计迟到时应怎样处理，司机工时和客户拒收又有哪些规则？","log_delivery_003",
         ["5 分钟","15 分钟","提前 15 分钟","连续驾驶 4 小时","现场照片"]),
        ("Q007", "冷链轨迹数据保存多久？","log_compliance_004",
         ["730 天"]),
        ("Q008", "发生三级温控告警后谁需要处理，监管抽查要导出哪些证据，传感器校准周期和误差限制是什么？","log_compliance_004",
         ["质量负责人","30 分钟","温度曲线","12 个月","0.5 摄氏度"]),
    ]

    passed = 0
    for qid, query, tid, kws in STD_QUERIES:
        results, ms = search(query, task_id=tid)
        show_results(f"{qid} task={tid}", results, ms, kw=kws)

        all_text = " ".join(r.get("content", "") for r in results)
        # 忽略空格差异匹配（实际内容中"90秒" vs 关键词"90 秒"）
        all_text_nospace = all_text.replace(" ", "")
        def kw_match(kw: str) -> bool:
            return kw in all_text or kw.replace(" ", "") in all_text_nospace
        hit = [k for k in kws if kw_match(k)]
        ok = len(hit) >= max(1, len(kws)//2) and len(results) >= 1
        if ok:
            passed += 1
        print(f"  {'PASS' if ok else 'FAIL'}: {len(hit)}/{len(kws)} 关键词命中\n")

    print(f"\n{'='*70}")
    print(f"标准 query: {passed}/{len(STD_QUERIES)} PASS")
    print(f"{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    test()
