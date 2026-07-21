"""全量写入 — 3 用户，LLM分类，部分不带scene/task"""
import sys; sys.path.insert(0, '.')
import os; os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import json, time, random
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv(".env")
from app.services.mem0_client import mem0_client

ds = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/v1")
mem0_client.initialize()
JSONL = "../continue_zh.jsonl"

CLASSIFY_PROMPT = """分析以下对话内容，输出JSON包含三个字段：
- scene: 从 ["code","game","chat","biz","science","music"] 中选一个
- task: 从 ["create","qa","iterate"] 中选一个
- memory_type: 从 ["preference","fact","task","decision","constraint"] 中选一个
只输出JSON。对话内容："""

all_data = [json.loads(line) for line in open(JSONL, encoding='utf-8')]
random.seed(42)
random.shuffle(all_data)
train_data = all_data[:-20]

# 3 用户，各 300 条
USERS = {"u_code": 100, "u_chat": 100, "u_mix": 100}
user_start = 0
stats = {"scene": {}, "task": {}, "users": {}}

print(f"写入 {sum(USERS.values())} 条, 3 个用户\n")
start = time.time()

for uid, count in USERS.items():
    batch = train_data[user_start:user_start + count]
    user_start += count
    stats["users"][uid] = 0

    for i, data in enumerate(batch):
        cid = data["conversation_id"]
        first_msg = data["conversation"][0].get("human", "")[:200]

        sid, tid, mtype = None, None, None
        try:
            resp = ds.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role":"user","content": f"{CLASSIFY_PROMPT}{first_msg}"}],
                max_tokens=80, temperature=0,
            )
            result = json.loads(resp.choices[0].message.content.strip())
            sid = result.get("scene")
            tid = result.get("task")
            mtype = result.get("memory_type")
        except Exception:
            pass

        # u_mix 部分数据故意不带元数据
        if uid == "u_mix" and random.random() < 0.3:
            sid = None
        if uid == "u_mix" and random.random() < 0.3:
            tid = None
        if uid == "u_mix" and random.random() < 0.2:
            mtype = None

        stats["scene"][sid or "None"] = stats["scene"].get(sid or "None", 0) + 1
        stats["task"][tid or "None"] = stats["task"].get(tid or "None", 0) + 1

        meta = {"session_id": cid}
        if sid: meta["scene_id"] = f"scene_{sid}"
        if tid: meta["task_id"] = f"task_{tid}"
        if mtype: meta["memory_type"] = mtype

        messages = [{"role":"system","content":"请用中文提取和记录所有记忆内容"}]
        for turn in data["conversation"]:
            h = turn.get("human","").strip()
            a = turn.get("assistant","").strip()
            if len(h) >= 3: messages.append({"role":"user","content":h})
            if len(a) >= 3: messages.append({"role":"assistant","content":a[:500]})
        if len(messages) <= 1: continue
        try:
            mem0_client.add(messages, user_id=uid, metadata=meta)
            stats["users"][uid] += 1
        except Exception as e:
            print(f"  FAIL [{cid[:8]}]: {e}")
        if (i+1) % 50 == 0:
            e = int(time.time()-start)
            print(f"  {uid}: {i+1}/{count} ({e//60}m{e%60}s)")

elapsed = int(time.time()-start)
print(f"\n完成, {elapsed//60}m{elapsed%60}s")
print(f"用户: {stats['users']}")
print(f"scene: {dict(sorted(stats['scene'].items()))}")
print(f"task:  {dict(sorted(stats['task'].items()))}")

with open("tests/_last_uids.txt","w") as f:
    json.dump(list(USERS.keys()), f)
print("UIDs 已保存")
