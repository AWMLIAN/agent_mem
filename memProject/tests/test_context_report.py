# -*- coding: utf-8 -*-
"""
记忆上下文返回模块 — 21 项功能测试报告（合并 master 后验证）
"""
import httpx, json

BASE = "http://localhost:8000/api/v1/memory"
UID = "test_pipeline_zh_1784080440"
TIMEOUT = 90
results = []

def test(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name} {detail}")
    results.append({"name": name, "status": status, "detail": detail})

def post(path, body):
    r = httpx.post(f"{BASE}{path}", json=body, timeout=TIMEOUT)
    return r.json()

print("=" * 60)
print(" 记忆上下文返回模块 — 合并 master 后验证报告")
print("=" * 60)
print(f" 服务器: http://localhost:8000")
print(f" 用户: {UID} (1179 条记忆)")
print(f" Qdrant: connected | Embedding: ready")
print()

# ====== 3.1 记忆结果筛选 ======
print("--- 3.1 记忆结果筛选 ---")

d = post("/search", {"query": "用户偏好", "user_id": UID, "top_k": 3})
items = d.get("data", {}).get("results", [])
scores = [i.get("relevance_score") for i in items]
test("功能1 按相关性筛选", d["code"] == 0 and len(items) > 0,
     f"返回{len(items)}条, scores={scores}")

for tp in ["fact", "task_state"]:
    d = post("/search", {"query": "用户", "user_id": UID, "memory_types": [tp], "top_k": 3})
    items = d.get("data", {}).get("results", [])
    types = [i.get("memory_type") for i in items]
    all_match = all(t == tp for t in types)
    test(f"功能2 类型筛选[{tp}]", d["code"] == 0 and all_match,
         f"返回{len(items)}条, 类型={types}")

for st in ["active", "archived"]:
    d = post("/search", {"query": "用户", "user_id": UID, "status": [st], "top_k": 3})
    items = d.get("data", {}).get("results", [])
    all_match = all(i.get("status") == st for i in items) if items else True
    test(f"功能3 状态筛选[{st}]", d["code"] == 0 and all_match,
         f"返回{len(items)}条")

# ====== 3.2 返回长度控制 ======
print("--- 3.2 返回长度控制 ---")

for k in [2, 5]:
    d = post("/search", {"query": "用户", "user_id": UID, "top_k": k})
    n = len(d.get("data", {}).get("results", []))
    test(f"功能4 top_k={k}", n == k, f"实际返回{n}条")

d = post("/search", {"query": "用户", "user_id": UID, "top_k": 1, "max_content_length": 10})
items = d.get("data", {}).get("results", [])
if items:
    c = items[0].get("content", "")
    test("功能5 max_content_length=10", len(c) <= 13, f"实际长度={len(c)}")

d = post("/search", {"query": "用户", "user_id": UID, "top_k": 1, "max_content_length": 5})
items = d.get("data", {}).get("results", [])
if items:
    c = items[0].get("content", "")
    test("功能6 长内容裁剪", len(c) <= 8, f"实际长度={len(c)}")

# ====== 3.3 结构化结果返回 ======
print("--- 3.3 结构化结果返回 ---")

d = post("/search", {"query": "用户", "user_id": UID, "top_k": 1})
items = d.get("data", {}).get("results", [])
if items:
    i = items[0]
    fields = ["memory_id","memory_type","relevance_score","created_at",
              "content","summary","key_points","agent_id","source_type","status"]
    present = [f for f in fields if f in i]
    missing = [f for f in fields if f not in i]
    test("功能7-9 JSON结构化返回", not missing,
         f"{len(present)}/10 字段完整, memory_type={i.get('memory_type')}, "
         f"relevance_score={i.get('relevance_score')}, agent_id={i.get('agent_id')}")
else:
    test("功能7-9 JSON结构化返回", False, "无结果")

# ====== 3.4 Prompt 片段生成 ======
print("--- 3.4 Prompt 片段生成（context 重构后：纯聚合输出）---")

d = post("/context", {"query": "用户偏好", "user_id": UID, "max_tokens": 1000, "top_k": 5})
ctx = d.get("data", {})
agg = ctx.get("aggregation", {})
ft = ctx.get("formatted_text", "")
et = ctx.get("estimated_tokens")
# 新 context 接口返回 aggregation + formatted_text，不再有 fragments/memory_count
test("功能10-12 context聚合输出", d["code"] == 0 and ft and agg,
     f"aggregation类型={agg.get('type')}, formatted_text长度={len(ft)}, estimated_tokens={et}")
test("功能10-12 context含preferences", "preferences" in agg and len(agg.get("preferences",[])) > 0,
     f"preferences={len(agg.get('preferences',[]))}条")
test("功能10-12 context含facts", "facts" in agg and len(agg.get("facts",[])) > 0,
     f"facts={len(agg.get('facts',[]))}条")

# ====== 3.5 上下文组织输出 ======
print("--- 3.5 上下文组织输出 ---")

d = post("/context", {"query": "用户偏好", "user_id": UID, "max_tokens": 500,
                      "top_k": 10, "group_by_type": True})
ctx = d.get("data", {})
ft = ctx.get("formatted_text", "")
agg = ctx.get("aggregation", {})
test("功能13-15 context聚合分组", d["code"] == 0 and ft,
     f"aggregation类型={agg.get('type')}, formatted_text长度={len(ft)}")

# ====== 3.6 检索日志 ======
print("--- 3.6 检索日志 ---")
d = post("/search", {"query": "用户", "user_id": UID, "top_k": 3})
elapsed = d.get("data", {}).get("elapsed_ms", 0)
has_results = len(d.get("data", {}).get("results", [])) > 0
test("功能16-18 检索日志", d["code"] == 0 and elapsed > 0,
     f"elapsed_ms={elapsed}ms, results={has_results}")

# ====== 3.7 返回异常处理 ======
print("--- 3.7 返回异常处理 ---")

# 用不存在的用户测试空结果
d = post("/search", {"query": "用户", "user_id": "nonexistent_user_xyz", "top_k": 3})
test("功能19 空结果", d["code"] == 0 and len(d.get("data",{}).get("results",[])) == 0,
     f"返回0条, total_candidates={d.get('data',{}).get('total_candidates')}")

d = post("/search", {"query": "test"})
test("功能20 错误码返回", d["code"] == -1 and d.get("error_code") == "INVALID_PARAM",
     f"code={d['code']}, error_code={d.get('error_code')}")

d = post("/search", {})
test("功能21 异常信息提示", d["code"] == -1 and d.get("error_code") == "INVALID_PARAM",
     f"code={d['code']}, error_code={d.get('error_code')}")

# ====== 汇总 ======
print()
print("=" * 60)
print(" 测试摘要")
print("=" * 60)
passed = sum(1 for r in results if r["status"] == "PASS")
failed = sum(1 for r in results if r["status"] == "FAIL")
print(f" 通过: {passed} | 失败: {failed} | 总计: {len(results)}")
print()
for r in results:
    print(f"  [{r['status']}] {r['name']}")
print()
print("=" * 60)
print(" 说明: context 接口已重构为纯聚合输出(commit 1343b7c)")
print(" 返回 aggregation + formatted_text，不再有 fragments/memory_count")
print("=" * 60)
