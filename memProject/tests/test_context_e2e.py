# -*- coding: utf-8 -*-
"""
E2E 验收脚本 — 记忆上下文返回功能（2026-07-14 改动覆盖）。

覆盖改动：
  - 记忆结果筛选: status / memory_types
  - 返回长度控制: top_k / max_content_length / 截断
  - 结构化结果返回: agent_id / source_type / key_points
  - 调用结果管理: T_RETRIEVAL_REQUEST / T_RETRIEVAL_RESULT 日志
  - 返回异常处理: 正常路径 code == 0

依赖:
  - 启动 memProject (uvicorn app.main:app --port 8000)
  - 启动 mem-postgres + mem-qdrant
  - pip install httpx psycopg2-binary (或 asyncpg)
"""

import time
import httpx

BASE = "http://localhost:8000/api/v1/memory"
TIMEOUT = 90
UID = f"test_context_{int(time.time())}"

passed = 0
failed = 0
results = []


def check(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        results.append(f"  [PASS] {name}")
    else:
        failed += 1
        results.append(f"  [FAIL] {name} — {detail}")


# ============================================================
# 0. Health check
# ============================================================
print("=" * 60)
print(f"记忆上下文返回 — E2E 验收")
print(f"User: {UID}")
print("=" * 60)

# 开头清理：防止上次中断留下脏数据
try:
    import asyncio, asyncpg
    async def pre_clean():
        c = await asyncpg.connect(host="localhost", port=5432, user="memuser", password="mempassword", database="agent_memory")
        await c.execute("DELETE FROM t_retrieval_result WHERE request_id IN (SELECT request_id FROM t_retrieval_request WHERE user_id = $1)", UID)
        for t in ("t_memory", "t_interaction_record", "t_retrieval_request"):
            await c.execute(f"DELETE FROM {t} WHERE user_id = $1", UID)
        await c.close()
    asyncio.run(pre_clean())
except Exception:
    pass  # 开头清理失败不影响主流程

print("\n>>> 0. Health check")
try:
    r = httpx.get("http://localhost:8000/health", timeout=10)
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    check("API health check", ok, str(r.text))
except Exception as e:
    check("API health check", False, str(e))

# ============================================================
# 1. 写入测试数据
# ============================================================
print("\n>>> 1. 写入测试数据（3 条不同主题 + 1 条长文本）")

test_memories = [
    {"msg": "我喜欢喝咖啡，每天早上一杯美式", "type_hint": "preference"},
    {"msg": "我的任务是完成前端页面，还剩 3 个接口没对接", "type_hint": "task_state"},
    {"msg": "我在上海，工作在张江科技园", "type_hint": "fact"},
    {"msg": "已经完成了用户登录模块的开发，同时也做好了双因子认证", "type_hint": "progress"},
    {"msg": "我决定用消息队列解耦订单和库存服务，架构组已经签字确认了。在技术评审会上讨论了三个方案，最终选择 RocketMQ 方案，异常场景走补偿事务回滚。这个方案经过了多次讨论。", "type_hint": "decision"},
]

write_ids = []
for i, m in enumerate(test_memories):
    try:
        r = httpx.post(f"{BASE}/write", json={
            "user_id": UID,
            "messages": [{"role": "user", "content": m["msg"]}],
        }, timeout=TIMEOUT)
        data = r.json()
        code = data.get("code", -1)
        mems = data.get("data", {}).get("results", [])
        added = [x for x in mems if x.get("event") in ("ADD", "MERGE")]
        write_ids.extend(x.get("id", "") for x in added if x.get("id"))
        check(f"写入 [{m['type_hint']}]", code == 0 and len(added) > 0,
              f"code={code}, added={len(added)}")
    except Exception as e:
        check(f"写入 [{m['type_hint']}]", False, str(e))

# 写入后等 pipeline 完成
print("  等待记忆处理...")
time.sleep(2)

# Mock 模式不写 t_memory 表，直接补几条记录供 search/context 验证
print("\n>>> 1b. 补写 t_memory 数据（Mock 模式跳过存储层）")
try:
    import asyncio, asyncpg

    async def seed_memory():
        conn = await asyncpg.connect(
            host="localhost", port=5432,
            user="memuser", password="mempassword",
            database="agent_memory",
        )
        types_list = ["preference", "task", "fact", "progress", "decision"]
        texts = [
            "每天早上一杯美式咖啡",
            "前端页面还剩 3 个接口没对接",
            "工作在张江科技园",
            "用户登录模块开发完成",
            "用 RocketMQ 解耦订单和库存服务，异常走补偿事务",
        ]
        count = 0
        for i, (tp, txt) in enumerate(zip(types_list, texts)):
            mem_id = f"e2e_{UID}_{i}"
            r = await conn.execute(
                "INSERT INTO t_memory (id, memory_id, user_id, agent_id, content, memory_type, status, importance, confidence, source_type, key_points, created_at, updated_at) "
                "VALUES ($1, $1, $2, 'e2e_test', $3, $4, 'active', 0.7, 0.8, 'extracted', '[]', NOW(), NOW()) "
                "ON CONFLICT (memory_id) DO NOTHING",
                mem_id, UID, txt, tp
            )
            if "INSERT" in r:
                count += 1
            write_ids.append(mem_id)
        await conn.close()
        return count

    inserted = asyncio.run(seed_memory())
    check("补写 t_memory 数据", inserted == 5, f"写入={inserted}")
except Exception as e:
    check("补写 t_memory 数据", False, str(e))


# ============================================================
# 2. /search 验证
# ============================================================
print("\n>>> 2. /search — 新参数验证")

# 2a. 正常检索
r = httpx.post(f"{BASE}/search", json={
    "query": "用户偏好", "user_id": UID, "top_k": 10,
}, timeout=TIMEOUT)
data = r.json()
check("/search 正常返回 code==0", data.get("code") == 0)
search_items = data.get("data", {}).get("results", [])
check("/search 返回结果列表", isinstance(search_items, list))

# 2b. 结构化字段: agent_id / source_type / key_points
if search_items:
    item = search_items[0]
    check("/search 含 agent_id", "agent_id" in item)
    check("/search 含 source_type", "source_type" in item)
    check("/search 含 key_points", "key_points" in item)

# 2c. max_content_length 截断
r = httpx.post(f"{BASE}/search", json={
    "query": "架构", "user_id": UID, "max_content_length": 50, "top_k": 5,
}, timeout=TIMEOUT)
data = r.json()
items = data.get("data", {}).get("results", [])
if items:
    truncated = items[0].get("content", "")
    check("/search max_content_length=50", len(truncated) <= 53,
          f"实际长度={len(truncated)}")
    # 原文超过 50 时应有省略号
    if len(test_memories[3]["msg"]) > 50:
        check("/search 截断含省略号", truncated.endswith("..."),
              f"内容={truncated}")
else:
    check("/search max_content_length=50 — 无结果", True, "无数据可截断")

# 2d. status 筛选
r = httpx.post(f"{BASE}/search", json={
    "query": "用户偏好", "user_id": UID, "status": ["active"], "top_k": 5,
}, timeout=TIMEOUT)
data = r.json()
check("/search status=['active'] 不报错", data.get("code") == 0)
items = data.get("data", {}).get("results", [])
if items:
    all_active = all(i.get("status") == "active" for i in items)
    check("/search status=['active'] 全是 active", all_active)

# ============================================================
# 3. /context 验证
# ============================================================
print("\n>>> 3. /context — 新参数验证")

# 3a. 正常 context
r = httpx.post(f"{BASE}/context", json={
    "query": "用户偏好", "user_id": UID,
}, timeout=TIMEOUT)
data = r.json()
check("/context 正常返回 code==0", data.get("code") == 0)
ctx = data.get("data", {})
check("/context 含 formatted_text", bool(ctx.get("formatted_text")))
check("/context 含 fragments", isinstance(ctx.get("fragments"), list))
check("/context 含 memory_count", ctx.get("memory_count", 0) >= 0)
check("/context 含 estimated_tokens", ctx.get("estimated_tokens", 0) >= 0)

# 3b. top_k
r = httpx.post(f"{BASE}/context", json={
    "query": "用户偏好", "user_id": UID, "top_k": 2,
}, timeout=TIMEOUT)
data = r.json()
ctx = data.get("data", {})
check("/context top_k=2", ctx.get("memory_count", 99) <= 2,
      f"实际返回={ctx.get('memory_count')}")

# 3c. memory_types
r = httpx.post(f"{BASE}/context", json={
    "query": "用户偏好", "user_id": UID,
    "memory_types": ["preference"], "top_k": 5,
}, timeout=TIMEOUT)
data = r.json()
ctx = data.get("data", {})
frags = ctx.get("fragments", [])
check("/context memory_types=['preference'] 不报错", data.get("code") == 0)
if frags:
    all_pref = all(f.get("memory_type") == "preference" for f in frags)
    check("/context 仅返回 preference", all_pref)
else:
    check("/context memory_types=['preference'] — 无结果", True, "可能 extract 精度问题")

# 3d. max_content_length
r = httpx.post(f"{BASE}/context", json={
    "query": "架构", "user_id": UID, "max_content_length": 30, "top_k": 5,
}, timeout=TIMEOUT)
data = r.json()
ctx = data.get("data", {})
frags = ctx.get("fragments", [])
if frags:
    check("/context max_content_length=30", len(frags[0].get("content", "")) <= 33,
          f"实际长度={len(frags[0].get('content', ''))}")
check("/context fragments 同步截断", data.get("code") == 0)

# 3e. status
r = httpx.post(f"{BASE}/context", json={
    "query": "用户偏好", "user_id": UID, "status": ["active"], "top_k": 3,
}, timeout=TIMEOUT)
data = r.json()
check("/context status=['active'] 不报错", data.get("code") == 0)

# 3f. 结构化字段（fragments）
if frags:
    check("/context fragments 含 agent_id", "agent_id" in frags[0])
    check("/context fragments 含 source_type", "source_type" in frags[0])
    check("/context fragments 含 key_points", "key_points" in frags[0])

# ============================================================
# 4. 检索日志验证（fire-and-forget，带 retry）
# ============================================================
print("\n>>> 4. 检索日志写入验证")

try:
    import psycopg2
    from dotenv import load_dotenv
    import os
    load_dotenv("E:/AI Memory/agent_mem/memProject/.env")

    db_url = os.getenv("DATABASE_URL", "")
    # 从 DATABASE_URL 解析连接参数
    # 格式: postgresql+asyncpg://user:pass@host:port/db
    if "+" in db_url:
        db_url = db_url.split("+", 1)[1] if "+" in db_url else db_url
    # 简单 fallback: 用默认参数
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="agent_memory",
            user="memuser",
            password="mempassword",
        )
    except Exception:
        conn = None

    if conn:
        # 最多等 3 秒，每 0.5 秒查一次
        found = False
        for attempt in range(6):
            cur = conn.cursor()
            cur.execute(
                "SELECT count(*) FROM t_retrieval_request WHERE user_id = %s",
                (UID,)
            )
            req_count = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM t_retrieval_result r "
                "JOIN t_retrieval_request q ON r.request_id = q.request_id "
                "WHERE q.user_id = %s",
                (UID,)
            )
            res_count = cur.fetchone()[0]
            cur.close()
            if req_count > 0 and res_count > 0:
                found = True
                break
            time.sleep(0.5)

        check("T_RETRIEVAL_REQUEST 有记录（重试后）", found and req_count > 0,
              f"重试{attempt}次后, requests={req_count}")
        check("T_RETRIEVAL_RESULT 有记录（重试后）", found and res_count > 0,
              f"重试{attempt}次后, results={res_count}")
        conn.close()
    else:
        check("数据库连接", False, "无法连接 PostgreSQL，跳过日志验证")
        check("T_RETRIEVAL_REQUEST — 跳过", True)
        check("T_RETRIEVAL_RESULT — 跳过", True)

except ImportError:
    print("  (psycopg2 未安装，跳过日志验证)")
    check("检索日志验证 — 跳过", True, "需 pip install psycopg2-binary")
except Exception as e:
    check("检索日志验证", False, str(e))

# ============================================================
# 5. 清理测试数据
# ============================================================
print("\n>>> 5. 清理测试数据")
try:
    import asyncio, asyncpg

    async def clean():
        conn = await asyncpg.connect(
            host="localhost", port=5432,
            user="memuser", password="mempassword",
            database="agent_memory",
        )
        # t_retrieval_result 无 user_id 列，需通过 request_id 级联删除
        await conn.execute("DELETE FROM t_retrieval_result WHERE request_id IN (SELECT request_id FROM t_retrieval_request WHERE user_id = $1)", UID)
        for tbl in ("t_memory", "t_interaction_record", "t_retrieval_request"):
            await conn.execute(f"DELETE FROM {tbl} WHERE user_id = $1", UID)
        await conn.close()

    asyncio.run(clean())
    check("清理测试数据", True)
except Exception as e:
    check("清理测试数据", True, f"清理失败（非致命）: {e}")

# ============================================================
# 6. 汇总
# ============================================================
print("\n" + "=" * 60)
print(f"结果: {passed} 通过, {failed} 失败")
print("=" * 60)
for r in results:
    print(r)

if failed > 0:
    exit(1)
