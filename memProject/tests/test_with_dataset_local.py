# -*- coding: utf-8 -*-
"""全量 1907 条 continue_zh.jsonl 测试"""
import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from datetime import datetime, timezone

BASE = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json"}
DATASET = os.path.expanduser("~/Desktop/continue_zh.jsonl")

pass_count = 0
fail_count = 0


def check(name, condition, detail=""):
    global pass_count, fail_count
    if condition:
        pass_count += 1
    else:
        fail_count += 1
        print(f"  [FAIL] {name}  -- {detail}")


def api(method, path, data=None, timeout=120):
    url = BASE + path
    try:
        if method == "POST":
            r = requests.post(url, headers=H, json=data, timeout=timeout)
        elif method == "GET":
            r = requests.get(url, headers=H, timeout=timeout)
        else:
            return -1, {}
        return r.status_code, r.json()
    except Exception as e:
        return -1, {"code": -1, "message": str(e)}


def get_data(resp):
    return resp.get("data", resp)


# ── 加载数据集 ────────────────────────────────
t0 = time.perf_counter()
with open(DATASET, 'r', encoding='utf-8') as f:
    all_lines = f.readlines()

total = len(all_lines)
print(f"数据集总量: {total} 条")
print(f"开始时间: {datetime.now(timezone.utc).isoformat()}")
print()

# ── 注册 Agent ─────────────────────────────────
status, resp = api("POST", "/agent/register",
                   {"agent_name": "full-test", "scene_id": "full-scene", "permissions": []})
ad = get_data(resp)
H["X-API-Key"] = ad.get("api_key", "")
H["X-User-Id"] = "full_user"
H["X-Scene-Id"] = "full-scene"
print(f"Agent 注册: {ad.get('agent_id')}")

# ================================================================
# 测试1：Mock 写入 —— 全量 1907 条
# ================================================================
print(f"\n{'='*60}")
print(f"  测试1：Mock 写入 —— 全量 {total} 条")
print(f"{'='*60}")

total_msg = 0
total_add = 0
total_skip = 0
total_merge = 0
errors = []
t1 = time.perf_counter()

for i, line in enumerate(all_lines):
    d = json.loads(line)
    conv = d['conversation']
    messages = []
    for turn in conv:
        messages.append({"role": "user", "content": turn['human'][:5000]})
        if turn.get('assistant'):
            messages.append({"role": "assistant", "content": turn['assistant'][:5000]})

    total_msg += len(messages)

    try:
        status, r = api("POST", "/memory/write", {
            "user_id": f"u_{d['conversation_id']}",
            "session_id": f"sess_{d['id']}",
            "messages": messages[-6:],  # 一次最多6条
        }, timeout=10)
        if status == 200:
            results = get_data(r).get("results", [])
            total_add += sum(1 for x in results if x.get("event") == "ADD")
            total_skip += sum(1 for x in results if x.get("event") == "SKIP")
            total_merge += sum(1 for x in results if x.get("event") == "MERGE")
        else:
            errors.append(f"line={i} id={d['id']} HTTP={status}")
    except Exception as e:
        errors.append(f"line={i} id={d['id']} {str(e)[:80]}")

    if (i + 1) % 200 == 0:
        elapsed = time.perf_counter() - t1
        print(f"  {i+1}/{total} ({100*(i+1)/total:.0f}%)  "
              f"ADD={total_add} SKIP={total_skip} errors={len(errors)}  "
              f"{(i+1)/elapsed:.0f}条/秒")

t1_end = time.perf_counter() - t1

print(f"\n  全量结果:")
print(f"    总对话: {total} 条")
print(f"    总消息: {total_msg} 条")
print(f"    提取记忆: ADD={total_add}, SKIP={total_skip}, MERGE={total_merge}")
print(f"    错误: {len(errors)} 条")
print(f"    耗时: {t1_end:.0f}秒 ({total/t1_end:.1f}条/秒)")

check("全量写入零错误", len(errors) == 0, f"errors={errors[:5]}")
check("ADD率合理 (>30%)", total_add / max(total_msg, 1) > 0.3,
      f"ADD率={total_add/max(total_msg,1)*100:.1f}%")

# ================================================================
# 测试2：LLM 生成 —— 抽样 10 条
# ================================================================
print(f"\n{'='*60}")
print(f"  测试2：LLM 记忆生成 —— 抽样 10 条")
print(f"{'='*60}")

import random
random.seed(42)
gen_samples = random.sample(list(enumerate(all_lines)), min(10, total))
gen_samples.sort()

gen_total_mems = 0
gen_types = {}
gen_errors = 0
t2 = time.perf_counter()

for idx, (li, line) in enumerate(gen_samples):
    d = json.loads(line)
    conv = d['conversation']

    text_parts = []
    for turn in conv[:5]:
        text_parts.append(f"用户: {turn['human'][:200]}")
        if turn.get('assistant'):
            text_parts.append(f"助手: {turn['assistant'][:200]}")
    text = "\n".join(text_parts)

    start = time.perf_counter()
    status, r = api("POST", "/memory/generate", {
        "text": text,
        "user_id": f"u_{d['conversation_id']}",
        "session_id": f"sess_gen_{d['id']}",
    }, timeout=120)
    elapsed = time.perf_counter() - start

    if status == 200:
        gd = get_data(r)
        mems = gd.get("memory_ids", [])
        details = gd.get("details", [])
        gen_total_mems += len(mems)
        for det in details:
            mt = det.get("memory_type", "?")
            gen_types[mt] = gen_types.get(mt, 0) + 1

        types_in = {d.get("memory_type") for d in details}
        previews = [d.get("content_preview", "")[:60] for d in details[:3]]
        print(f"  [{idx+1}/10] id={d['id']}, turns={len(conv)}, "
              f"{elapsed:.0f}ms, {len(mems)}mems, types={types_in}")
        for p in previews:
            print(f"         {p}")
    else:
        gen_errors += 1
        print(f"  [{idx+1}/10] id={d['id']} FAILED: status={status}")

t2_end = time.perf_counter() - t2

print(f"\n  LLM生成结果:")
print(f"    抽样: 10 条")
print(f"    生成记忆总数: {gen_total_mems} 条")
print(f"    类型分布: {gen_types}")
print(f"    错误: {gen_errors} 条")
print(f"    耗时: {t2_end:.0f}秒 ({t2_end/10:.0f}秒/条)")

check("LLM生成全部成功", gen_errors == 0)
check("类型覆盖 > 3种", len(gen_types) >= 3, f"types={list(gen_types.keys())}")

# ================================================================
# 测试3：检索 + 上下文 + 列表 + 统计
# ================================================================
print(f"\n{'='*60}")
print(f"  测试3：检索 / 上下文 / 列表 / 统计")
print(f"{'='*60}")

_, srch = api("POST", "/memory/search", {
    "query": "用户偏好 任务 需求",
    "user_id": "full_user",
    "top_k": 20,
})
check("多维检索", get_data(srch).get("results") is not None)

_, ctx = api("POST", "/memory/context", {
    "query": "偏好 事实 任务",
    "user_id": "full_user",
    "include_preferences": True,
    "include_facts": True,
    "include_task_state": True,
})
check("上下文聚合", get_data(ctx).get("fragments") is not None)

_, lst = api("GET", "/memory/list?user_id=full_user&page=1&page_size=20")
check("列表分页查询", get_data(lst).get("items") is not None)

_, st = api("GET", "/admin/stats")
sd = get_data(st)
print(f"  系统统计: {sd.get('total_memories')}条记忆, "
      f"{sd.get('total_agents')}智能体")
check("系统统计正常", sd.get("total_memories", -1) >= 0)

# ================================================================
# 最终汇总
# ================================================================
total_time = time.perf_counter() - t0
print(f"\n{'='*60}")
print(f"  测试结果汇总")
print(f"{'='*60}")
print(f"\n  数据集: {total} 条对话")
print(f"  Mock写入: {total} 条全量, {total_msg} 条消息,  "
      f"ADD={total_add}, SKIP={total_skip}")
print(f"  LLM生成: 10 条抽样, {gen_total_mems} 条记忆,  "
      f"类型覆盖 {len(gen_types)} 种")
print(f"  错误总数: {len(errors) + gen_errors}")
print(f"  总耗时: {total_time:.0f}秒")
print(f"  PASS: {pass_count}/{pass_count+fail_count} "
      f"({pass_count/(pass_count+fail_count)*100:.1f}%)")
