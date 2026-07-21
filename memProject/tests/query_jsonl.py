"""多路检索综合测试 — LLM评分选query, 6维度 × 短/中/长"""
import sys; sys.path.insert(0, '.')
import os; os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import json, time, random
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv(".env")
from app.services.retrieval_service import search

ds = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/v1")
JSONL = "../continue_zh.jsonl"
try: UIDS = json.load(open("tests/_last_uids.txt"))
except: print("请先运行 write_jsonl.py"); exit(1)

# ── 1. 选取 query (DeepSeek 评分) ──
all_data = [json.loads(line) for line in open(JSONL, encoding='utf-8')]
random.seed(42); random.shuffle(all_data)
query_pool = all_data[-50:]

candidates = []
for data in query_pool:
    for turn in data["conversation"]:
        m = turn.get("human","").strip()
        if len(m) >= 10:
            candidates.append(m)
        break

print(f"候选: {len(candidates)} 条, 调用 DeepSeek 评分...")
score_prompt = f"""对以下消息作为搜索查询的质量打分(1-5分)，只返回JSON数组，每个元素包含index和score两个字段。
[
{chr(10).join(f'  {{"index":{i},"text":"{c[:80]}"}}' for i, c in enumerate(candidates))}
]"""

resp = ds.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role":"user","content": score_prompt}],
    max_tokens=2000, temperature=0,
)
raw = resp.choices[0].message.content.strip()
scores = None
try:
    scores = json.loads(raw)
except json.JSONDecodeError:
    import re
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        scores = json.loads(match.group(0))

if scores is None or not isinstance(scores, list):
    print(f"DeepSeek 返回非JSON, 降级随机选\n原始: {raw[:200]}")
    scores = [{"index": i, "score": 3} for i in range(len(candidates))]

ranked = sorted(scores, key=lambda x: x["score"], reverse=True)

# 按长度分类: 短<50, 中50-100, 长>100
def pick(length_range, count):
    result = []
    for s in ranked:
        idx = s["index"]
        if idx < len(candidates) and length_range(candidates[idx]) and candidates[idx] not in result:
            result.append(candidates[idx])
        if len(result) >= count: break
    return result

short  = pick(lambda m: len(m) < 50, 6)
medium = pick(lambda m: 50 <= len(m) <= 100, 5)
long_q = pick(lambda m: len(m) > 100, 5)

print(f"短{len(short)} 中{len(medium)} 长{len(long_q)}\n")

queries = []
for q in short: queries.append((q, "短"))
for q in medium: queries.append((q, "中"))
for q in long_q: queries.append((q, "长"))

scene_vals = ["scene_code", "scene_chat", "scene_game", "scene_biz"]
task_vals  = ["task_create", "task_qa", "task_iterate"]

def show(r):
    if not r["results"]: print("    (无结果)"); return
    for i, item in enumerate(r["results"]):
        print(f"    [{i+1}] [s:{item.get('relevance_score',0):.3f}] "
              f"{item.get('scene_id','?')}/{item.get('task_id','?')} "
              f"{item.get('content','')[:70]}")

# ═══════════════════════════════════
print("=" * 70)
print("1. 语义向量检索")
print("=" * 70)
for q, label in (queries[:3] +
    [(q,l) for q,l in queries if l=="中"][:2] +
    [(q,l) for q,l in queries if l=="长"][:2]):
    t0 = time.perf_counter()
    r = search(query=q, user_id=UIDS[0], top_k=5)
    ms = int((time.perf_counter()-t0)*1000)
    print(f"\n  [{label} {len(q)}字] '{q[:70]}' → {r['total_candidates']}条 {ms}ms")
    show(r)

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("2. 关键词精确检索")
print("=" * 70)
for kw in ["Python","CRISPR","游戏","AI","OKR","PHP","SQL","React"]:
    r = search(query=kw, user_id=UIDS[0], top_k=3, keyword=kw)
    print(f"\n  '{kw}' → 命中{r['filtered_count']}")
    show(r)

# 取短/中/长各 1 个有代表性的 query
q_short  = short[0] if short else queries[0][0]
q_medium = medium[0] if medium else queries[0][0]
q_long   = long_q[0] if long_q else queries[-1][0]

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("3. 场景过滤 (短/中/长 × 5种过滤)")
print("=" * 70)
for q, label_q in [(q_short,"短"), (q_medium,"中"), (q_long,"长")]:
    print(f"\n  [{label_q}字] '{q[:50]}...'")
    for label, sid in [("无过滤", None)] + [(s.split("_")[1], s) for s in scene_vals]:
        r = search(query=q, user_id=UIDS[0], scene_id=sid, top_k=5)
        print(f"  [{label}] 过滤后{r['filtered_count']}条 → Top-{len(r['results'])}返回")
        show(r)

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("4. 任务过滤 (短/中/长 × 4种过滤)")
print("=" * 70)
for q, label_q in [(q_short,"短"), (q_medium,"中"), (q_long,"长")]:
    print(f"\n  [{label_q}字] '{q[:50]}...'")
    for label, tid in [("无过滤", None)] + [(t.split("_")[1], t) for t in task_vals]:
        r = search(query=q, user_id=UIDS[0], task_id=tid, top_k=5)
        print(f"  [{label}] 过滤后{r['filtered_count']}条 → Top-{len(r['results'])}返回")
        show(r)

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("5. 组合过滤 + 时间范围 (短/中/长)")
print("=" * 70)
combos = [
    ("sc+tk", scene_vals[0], task_vals[0], None, None),
    ("时间<2020", None, None, None, "2020-01-01"),
    ("时间>2026", None, None, "2026-01-01", None),
]
for q, label_q in [(q_short,"短"), (q_medium,"中"), (q_long,"长")]:
    print(f"\n  [{label_q}字] '{q[:50]}...'")
    for label, sid, tid, ts, te in combos:
        r = search(query=q, user_id=UIDS[0], scene_id=sid, task_id=tid,
                   time_start=ts, time_end=te, top_k=5)
        print(f"  [{label}] 过滤后{r['filtered_count']}条 → Top-{len(r['results'])}返回")
        show(r)

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("6. 记忆类型过滤 (短/中/长)")
print("=" * 70)
mt_vals = ["preference", "fact", "task", "decision", "constraint"]
for q, label_q in [(q_short,"短"), (q_medium,"中"), (q_long,"长")]:
    print(f"\n  [{label_q}字] '{q[:50]}...'")
    for mt in mt_vals:
        r = search(query=q, user_id=UIDS[0], memory_types=[mt], top_k=5)
        print(f"  [{mt}] 过滤后{r['filtered_count']}条")
        show(r)

# ═══════════════════════════════════
print("\n" + "=" * 70)
print("7. 用户隔离 + 降序 (3 UID, 短/中/长)")
print("=" * 70)
for uid in UIDS:
    for q in [q_short, q_medium, q_long]:
        r = search(query=q, user_id=uid, top_k=5)
        scores = [it["relevance_score"] for it in r["results"]]
        desc = all(scores[i] >= scores[i+1] for i in range(len(scores)-1)) if len(scores)>=2 else True
        print(f"\n  [{uid}] '{q[:40]}' → {r['total_candidates']}条")
        print(f"  降序:{'OK' if desc else 'FAIL'} 分数:{[round(s,3) for s in scores[:3]]}")

print("\n" + "=" * 70)
print("完成")
print("=" * 70)
