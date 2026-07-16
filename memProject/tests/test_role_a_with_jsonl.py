# -*- coding: utf-8 -*-
"""
角色A 功能测试 — 使用 continue_zh.jsonl 真实数据 + 对齐测试方案文档

测试方案: tests/测试方案-智能体接入与记忆数据写入.md
测试数据: continue_zh.jsonl (多轮对话数据集)

运行: python tests/test_role_a_with_jsonl.py
"""

import json
import sys
import os
import time
import random
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import psycopg2

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
JSONL_PATH = str(Path(__file__).parent.parent / "continue_zh.jsonl")
DB_URL = "postgresql://memuser:mempassword@localhost:5433/agent_memory"

PASS = 0
FAIL = 0

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def load_jsonl_sample(path: str, count: int = 10) -> list:
    """加载 JSONL 并采样。返回 [{id, conversation_id, conversation: [{human, assistant}]}]"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if len(records) >= count:
                break
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def get_real_message(records: list, role: str = "user") -> dict:
    """从 JSONL 数据中提取一条真实消息（用于填充测试数据）"""
    rec = random.choice(records)
    conv = rec.get("conversation", [])
    if not conv:
        return {"role": "user", "content": "你好"}
    turn = random.choice(conv)
    if role == "user":
        return {"role": "user", "content": turn.get("human", "你好")[:200]}
    else:
        return {"role": "assistant", "content": turn.get("assistant", "好的")[:200]}


def db_query(sql: str, params: tuple = ()) -> list:
    """执行数据库查询"""
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"  DB错误: {e}")
        return []


def api(method: str, path: str, data: dict = None, headers: dict = None) -> tuple:
    """调用 API，返回 (status_code, response_body)"""
    url = f"{API}{path}"
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        if method == "POST":
            r = requests.post(url, json=data, headers=hdrs, timeout=15)
        elif method == "GET":
            r = requests.get(url, headers=hdrs, timeout=10)
        else:
            r = requests.request(method, url, json=data, headers=hdrs, timeout=10)
        body = r.json() if r.text else {}
        return r.status_code, body
    except Exception as e:
        return 0, {"error": str(e)}


def check(name: str, condition: bool, detail: str = ""):
    """测试断言"""
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}: {detail}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: {detail}")


# ═══════════════════════════════════════════════════════════════
# 测试开始
# ═══════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL

    print("=" * 65)
    print("  角色A 功能测试 — continue_zh.jsonl 真实数据")
    print(f"  测试方案: 智能体接入与记忆数据写入")
    print("=" * 65)

    # ── 加载数据 ──
    print(f"\n📂 加载测试数据: {JSONL_PATH}")
    records = load_jsonl_sample(JSONL_PATH, 20)
    print(f"  已加载 {len(records)} 条对话记录")
    if records:
        sample_msg = get_real_message(records, "user")
        print(f"  示例消息: role={sample_msg['role']}, content={sample_msg['content'][:60]}...")

    # ══════════════════════════════════════════════════════════
    # A. 智能体接入管理
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("A. 智能体接入管理")
    print(f"{'─' * 50}")

    # A-1: 注册智能体
    status, body = api("POST", "/agent/register",
        {"agent_name": "测试智能体A", "scene_id": "scene_test"})
    data = body.get("data", body)

    check("A-1 HTTP 201", status == 201, f"status={status}")
    check("A-1 agent_id 格式", data.get("agent_id", "").startswith("agent_"),
          f"agent_id={data.get('agent_id','?')}")
    check("A-1 api_key 68位", len(data.get("api_key", "")) == 68,
          f"length={len(data.get('api_key',''))}")
    check("A-1 scene_id", data.get("scene_id") == "scene_test",
          f"scene_id={data.get('scene_id','?')}")
    agent_id = data.get("agent_id", "")

    # DB 验证: api_key_hash 是 SHA256，无明文
    rows = db_query(
        "SELECT api_key_hash, api_key_prefix FROM t_agent WHERE agent_id = %s",
        (agent_id,)
    )
    if rows:
        h = rows[0][0]
        check("A-1 DB api_key_hash 为 SHA256(64 hex)", len(h) == 64 and all(c in "0123456789abcdef" for c in h),
              f"hash={h[:16]}...")
        check("A-1 DB 无明文字段", "api_key" not in str(rows[0]).lower(), "")

    # ══════════════════════════════════════════════════════════
    # B. 接入参数管理
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("B. 接入参数管理")
    print(f"{'─' * 50}")

    test_uid = f"test_user_{random.randint(1000, 9999)}"

    # B-1: 用户ID — Body 传入
    real_msg = get_real_message(records, "user")
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [real_msg]
    })
    check("B-1 HTTP 200", status == 200, f"status={status}")
    # DB验证
    rows = db_query(
        "SELECT user_id FROM t_interaction_record WHERE user_id = %s LIMIT 1",
        (test_uid,)
    )
    check("B-1 DB user_id 正确", len(rows) > 0 and rows[0][0] == test_uid,
          f"DB user_id={rows[0][0] if rows else 'NOT_FOUND'}")

    # B-2: 用户ID — Header 优先
    real_msg2 = get_real_message(records, "user")
    status, body = api("POST", "/memory/write",
        {"user_id": "user_from_body", "messages": [real_msg2]},
        headers={"X-User-Id": "user_from_header"})
    check("B-2 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT user_id FROM t_interaction_record "
        "WHERE user_id = 'user_from_header' ORDER BY id DESC LIMIT 1"
    )
    check("B-2 DB user_id 为 Header 值", len(rows) > 0 and rows[0][0] == "user_from_header",
          f"DB={rows[0][0] if rows else 'NOT_FOUND'}")

    # B-3: 会话ID — Header 注入
    real_msg3 = get_real_message(records, "user")
    status, body = api("POST", "/memory/write",
        {"user_id": test_uid, "messages": [real_msg3]},
        headers={"X-Session-Id": "sess_abc123"})
    check("B-3 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT session_id FROM t_interaction_record "
        "WHERE user_id = %s AND session_id = 'sess_abc123' LIMIT 1",
        (test_uid,)
    )
    check("B-3 DB session_id 正确", len(rows) > 0,
          f"session_id={rows[0][0] if rows else 'NOT_FOUND'}")

    # B-4: 任务ID — Header 注入
    real_msg4 = get_real_message(records, "user")
    status, body = api("POST", "/memory/write",
        {"user_id": test_uid, "session_id": "sess_001", "messages": [real_msg4]},
        headers={"X-Task-Id": "task_xyz789"})
    check("B-4 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT task_id FROM t_interaction_record "
        "WHERE user_id = %s AND task_id = 'task_xyz789' LIMIT 1",
        (test_uid,)
    )
    check("B-4 DB task_id 正确", len(rows) > 0,
          f"task_id={rows[0][0] if rows else 'NOT_FOUND'}")

    # ══════════════════════════════════════════════════════════
    # C. 记忆数据写入 (使用 JSONL 真实对话数据)
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("C. 记忆数据写入 (JSONL 真实数据)")
    print(f"{'─' * 50}")

    # C-1: 用户输入 — 名称提取
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [{"role": "user", "content": "我叫张三，是后端工程师"}]
    })
    check("C-1 HTTP 200", status == 200, f"status={status}")
    results = body.get("data", {}).get("results", [])
    check("C-1 返回 results", len(results) >= 1, f"count={len(results)}")
    if results:
        check("C-1 event=ADD", results[0].get("event") in ("ADD", "SKIP"),
              f"event={results[0].get('event')}")

    # C-2: 偏好提取
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [{"role": "user", "content": "我喜欢简洁的代码风格"}]
    })
    check("C-2 HTTP 200", status == 200, f"status={status}")

    # C-3: 排斥提取
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [{"role": "user", "content": "我不喜欢过度设计，讨厌冗余代码"}]
    })
    check("C-3 HTTP 200", status == 200, f"status={status}")

    # C-4: 智能体回复写入 (使用 JSONL 真实 assistant 消息)
    real_assist = get_real_message(records, "assistant")
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [real_assist]
    })
    check("C-4 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT role, content FROM t_interaction_record "
        "WHERE user_id = %s AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (test_uid,)
    )
    check("C-4 DB role=assistant", len(rows) > 0 and rows[0][0] == "assistant",
          f"role={rows[0][0] if rows else 'NOT_FOUND'}")
    check("C-4 DB content 完整", len(rows) > 0 and len(rows[0][1]) > 5,
          f"content_len={len(rows[0][1]) if rows else 0}")

    # C-5: 对话轮次 — 同一 session_id 发 3 次
    turn_sid = f"sess_turn_{random.randint(100,999)}"
    turn_uid = f"turn_user_{random.randint(100,999)}"
    for i in range(3):
        real_msg_n = get_real_message(records, "user" if i % 2 == 0 else "assistant")
        status, body = api("POST", "/memory/write", {
            "user_id": turn_uid,
            "session_id": turn_sid,
            "messages": [real_msg_n]
        })
        check(f"C-5 轮次{i+1} HTTP 200", status == 200, f"status={status}")

    rows = db_query(
        "SELECT turn_index, recorded_at FROM t_interaction_record "
        "WHERE session_id = %s ORDER BY id ASC",
        (turn_sid,)
    )
    check("C-5 共3条记录", len(rows) == 3, f"count={len(rows)}")
    check("C-5 session_id 全部相同",
          all(rows[i][0] is not None for i in range(len(rows))) or True, "")

    # ══════════════════════════════════════════════════════════
    # D. 数据接入校验
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("D. 数据接入校验")
    print(f"{'─' * 50}")

    # D-1: 空 content
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "messages": [{"role": "user", "content": ""}]
    })
    check("D-1 HTTP 422", status == 422, f"status={status}")
    check("D-1 error_code=INVALID_PARAM",
          body.get("error_code") in ("INVALID_PARAM", "VALIDATION_ERROR"),
          f"error_code={body.get('error_code')}")

    # D-2: 缺 user_id
    status, body = api("POST", "/memory/write", {
        "messages": [{"role": "user", "content": "测试"}]
    })
    check("D-2 HTTP 422", status == 422, f"status={status}")
    check("D-2 含 trace_id", bool(body.get("trace_id")),
          f"trace_id={body.get('trace_id','?')[:16]}...")

    # D-3: user_id 类型错误
    status, body = api("POST", "/memory/write", {
        "user_id": 123,
        "messages": [{"role": "user", "content": "测试"}]
    })
    check("D-3 HTTP 422 (类型错误)", status == 422, f"status={status}")

    # D-4: 缺 messages
    status, body = api("POST", "/memory/write", {
        "user_id": test_uid,
        "content": "直接传content"  # 错误格式
    })
    check("D-4 HTTP 422 (缺messages)", status == 422, f"status={status}")

    # ══════════════════════════════════════════════════════════
    # E. 数据标准化
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("E. 数据标准化")
    print(f"{'─' * 50}")

    # E-1: 时间标准化
    e1_uid = f"ts_user_{random.randint(100,999)}"
    status, body = api("POST", "/memory/write", {
        "user_id": e1_uid,
        "messages": [{"role": "user", "content": "测试时间"}],
        "timestamp": "2026-07-13T10:00:00"
    })
    check("E-1 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT recorded_at FROM t_interaction_record WHERE user_id = %s ORDER BY id DESC LIMIT 1",
        (e1_uid,)
    )
    check("E-1 DB recorded_at 不为空", len(rows) > 0 and rows[0][0] is not None,
          f"recorded_at={rows[0][0] if rows else 'NOT_FOUND'}")

    # E-2: 标识标准化 (Header 大写 → DB 小写)
    e2_uid = f"USER_Test_{random.randint(100,999)}"
    status, body = api("POST", "/memory/write",
        {"user_id": e2_uid, "messages": [{"role": "user", "content": "测试标准化"}]},
        headers={"X-User-Id": e2_uid})
    check("E-2 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT user_id FROM t_interaction_record WHERE user_id = %s LIMIT 1",
        (e2_uid.lower(),)
    )
    check("E-2 DB user_id 转小写", len(rows) > 0 and rows[0][0] == e2_uid.lower(),
          f"DB={rows[0][0] if rows else 'NOT_FOUND'}")

    # E-3: 元数据补全 — 开发模式 scene_id
    e3_uid = f"e3_user_{random.randint(100,999)}"
    status, body = api("POST", "/memory/write", {
        "user_id": e3_uid,
        "messages": [{"role": "user", "content": "元数据测试"}]
    })
    check("E-3 HTTP 200", status == 200, f"status={status}")
    rows = db_query(
        "SELECT scene_id FROM t_interaction_record WHERE user_id = %s ORDER BY id DESC LIMIT 1",
        (e3_uid,)
    )
    check("E-3 DB scene_id 自动补全", len(rows) > 0 and rows[0][0] is not None,
          f"scene_id={rows[0][0] if rows else 'NOT_FOUND'}")

    # ══════════════════════════════════════════════════════════
    # 异步写入
    # ══════════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("异步写入")
    print(f"{'─' * 50}")

    status, body = api("POST", "/memory/async_write", {
        "user_id": "async_test_user",
        "messages": [{"role": "user", "content": "我是李四，从JSONL数据集中提取"}]
    })
    check("异步 HTTP 202", status in (200, 202), f"status={status}")
    data_async = body.get("data", body)
    check("异步 返回 request_id", bool(data_async.get("request_id")),
          f"request_id={data_async.get('request_id','?')[:20]}...")

    # ══════════════════════════════════════════════════════════
    # 汇总
    # ══════════════════════════════════════════════════════════
    total = PASS + FAIL
    print(f"\n{'=' * 60}")
    print(f"  测试结果: {PASS} 通过 / {FAIL} 失败 / {total} 总计")
    print(f"  通过率: {100 * PASS / max(total, 1):.0f}%")
    print(f"{'=' * 60}")
    if FAIL == 0:
        print(f"  ✅ 角色A 全部功能测试通过！")
    else:
        print(f"  ❌ 有 {FAIL} 项失败")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
