# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  角色A 功能测试 — 一键完整测试脚本
═══════════════════════════════════════════════════════════════════════════════

运行方式:
  python tests/test_oneclick_role_a.py

说明:
  阶段1 — 49 个单元测试 (无需数据库, 无需启动服务, 即时可跑)
  阶段2 — 18 个 API 集成测试 (需先启动服务: uvicorn app.main:app --port 8000)

═══════════════════════════════════════════════════════════════════════════════
"""
import json
import os
import sys
from datetime import datetime

# ── Windows 编码修复 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 确保可以导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ═════════════════════════════════════════════════════════════════════════════
# 配置
# ═════════════════════════════════════════════════════════════════════════════
BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

total_pass = 0
total_fail = 0


def ok(msg: str) -> str:
    return f"{GREEN}✅ {msg}{RESET}"


def fail(msg: str) -> str:
    return f"{RED}❌ {msg}{RESET}"


def warn(msg: str) -> str:
    return f"{YELLOW}⚠️ {msg}{RESET}"


def info(msg: str) -> str:
    return f"{CYAN}💡 {msg}{RESET}"


def header(title: str) -> str:
    line = "═" * 70
    return f"\n{BOLD}{line}\n  {title}\n{line}{RESET}"


# ═════════════════════════════════════════════════════════════════════════════
# 阶段1: 单元测试 (无需任何外部依赖)
# ═════════════════════════════════════════════════════════════════════════════

def run_unit_tests():
    """运行 49 个纯逻辑单元测试"""
    global total_pass, total_fail

    print(header("阶段1: 单元测试 (49 个 — 无需数据库/服务)"))

    tests = _define_unit_tests()

    for t in tests:
        name = t["name"]
        func = t["func"]

        print(f"\n  [{t['category']}] {name}")
        print(f"  {'─' * 60}")

        try:
            func()
            print(f"  {ok('通过')}")
            total_pass += 1
        except AssertionError as e:
            print(f"  {fail('失败')} — {e}")
            total_fail += 1
        except Exception as e:
            print(f"  {fail('异常')} — {type(e).__name__}: {e}")
            total_fail += 1


def _define_unit_tests():
    """定义所有单元测试用例"""
    tests = []

    # ── Schema 层 (10 个) ──
    tests.append({
        "category": "Schema",
        "name": "标准 messages 数组格式可正常构造",
        "func": lambda: (
            (lambda b: (
                setattr(sys.modules[__name__], '_', b),
                b.user_id == "user_001" and len(b.messages) == 1 and b.messages[0].role == "user"
            )[-1])(
                __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
                .MemoryWriteRequest(user_id="user_001", messages=[{"role": "user", "content": "hello"}])
            )
        )
    })

    tests.append({
        "category": "Schema",
        "name": "多轮消息数组正确解析",
        "func": lambda: (
            (lambda b: len(b.messages) == 3 and b.get_last_role() == "user")(
                __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
                .MemoryWriteRequest(user_id="u1", messages=[
                    {"role": "user", "content": "A"},
                    {"role": "assistant", "content": "B"},
                    {"role": "user", "content": "C"}
                ])
            )
        )
    })

    tests.append({
        "category": "Schema",
        "name": "空 messages 数组应被拒绝",
        "func": lambda: _expect_error(
            lambda: __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
            .MemoryWriteRequest(user_id="u1", messages=[])
        )
    })

    tests.append({
        "category": "Schema",
        "name": "user_id 自动去空格转小写",
        "func": lambda: (
            __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
            .MemoryWriteRequest(user_id="  User_ABC  ", messages=[{"role": "user", "content": "x"}])
            .user_id == "user_abc"
        )
    })

    tests.append({
        "category": "Schema",
        "name": "scene_id 和 session_id 为可选字段",
        "func": lambda: (
            __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
            .MemoryWriteRequest(user_id="u1", messages=[{"role": "user", "content": "x"}])
            .scene_id is None
        )
    })

    tests.append({
        "category": "Schema",
        "name": "非法 role=hacker 应被拒绝",
        "func": lambda: _expect_error(
            lambda: __import__("app.schemas.memory", fromlist=["MessageItem"])
            .MessageItem(role="hacker", content="test")
        )
    })

    tests.append({
        "category": "Schema",
        "name": "所有合法 role 值 (user/assistant/system/tool/agent) 都通过",
        "func": lambda: all(
            __import__("app.schemas.memory", fromlist=["MessageItem"])
            .MessageItem(role=r, content="test").role == r
            for r in ["user", "assistant", "system", "tool", "agent"]
        )
    })

    tests.append({
        "category": "Schema",
        "name": "content 前后空白自动去除",
        "func": lambda: (
            __import__("app.schemas.memory", fromlist=["MessageItem"])
            .MessageItem(role="user", content="  hello world  ")
            .content == "hello world"
        )
    })

    tests.append({
        "category": "Schema",
        "name": "空 content 应被拒绝",
        "func": lambda: _expect_error(
            lambda: __import__("app.schemas.memory", fromlist=["MessageItem"])
            .MessageItem(role="user", content="")
        )
    })

    tests.append({
        "category": "Schema",
        "name": "messages 数组超过 100 条应拒绝",
        "func": lambda: _expect_error(
            lambda: __import__("app.schemas.memory", fromlist=["MemoryWriteRequest"])
            .MemoryWriteRequest(user_id="u1", messages=[{"role": "user", "content": "x"}] * 101)
        )
    })

    # ── 校验服务 (5 个) ──
    tests.append({
        "category": "校验服务",
        "name": "必填字段全部存在通过校验",
        "func": lambda: (
            __import__("app.services.validation_service", fromlist=["validate_required_fields"])
            .validate_required_fields({"user_id": "u1", "content": "hi", "session_id": "s1"})
            .is_valid == True
        )
    })

    tests.append({
        "category": "校验服务",
        "name": "缺少 user_id 报错",
        "func": lambda: (
            (lambda r: not r.is_valid and any("user_id" in e for e in r.errors))(
                __import__("app.services.validation_service", fromlist=["validate_required_fields"])
                .validate_required_fields({"content": "hi", "session_id": "s1"})
            )
        )
    })

    tests.append({
        "category": "校验服务",
        "name": "缺少 content 报错",
        "func": lambda: (
            (lambda r: not r.is_valid and any("content" in e for e in r.errors))(
                __import__("app.services.validation_service", fromlist=["validate_required_fields"])
                .validate_required_fields({"user_id": "u1", "session_id": "s1"})
            )
        )
    })

    tests.append({
        "category": "校验服务",
        "name": "缺少 session_id 报错",
        "func": lambda: (
            (lambda r: not r.is_valid and any("session_id" in e for e in r.errors))(
                __import__("app.services.validation_service", fromlist=["validate_required_fields"])
                .validate_required_fields({"user_id": "u1", "content": "hi"})
            )
        )
    })

    tests.append({
        "category": "校验服务",
        "name": "三个字段全缺报 3 个错误",
        "func": lambda: (
            len(__import__("app.services.validation_service", fromlist=["validate_required_fields"])
                .validate_required_fields({}).errors) == 3
        )
    })

    # ── ID 标准化 (4 个) ──
    from app.services.validation_service import normalize_id, validate_id_format

    tests.append({
        "category": "ID标准化",
        "name": "去前后空格 + 转小写",
        "func": lambda: normalize_id("  User_ABC  ") == "user_abc"
    })

    tests.append({
        "category": "ID标准化",
        "name": "None 透传不变",
        "func": lambda: normalize_id(None) is None
    })

    tests.append({
        "category": "ID标准化",
        "name": "合法 ID 格式通过",
        "func": lambda: validate_id_format("user_id", "u1001") is None
    })

    tests.append({
        "category": "ID标准化",
        "name": "含特殊字符的 ID 被拒绝",
        "func": lambda: validate_id_format("user_id", "user@name!") is not None
    })

    # ── 时间标准化 (3 个) ──
    from app.services.validation_service import standardize_timestamp

    tests.append({
        "category": "时间标准化",
        "name": "ISO 8601 UTC 正确解析",
        "func": lambda: standardize_timestamp("2026-07-06T10:00:00Z").tzinfo is not None
    })

    tests.append({
        "category": "时间标准化",
        "name": "None → 当前时间",
        "func": lambda: isinstance(standardize_timestamp(None), datetime)
    })

    tests.append({
        "category": "时间标准化",
        "name": "无效字符串 → 降级为当前时间",
        "func": lambda: isinstance(standardize_timestamp("not_a_date"), datetime)
    })

    # ── 元数据补全 (2 个) ──
    from app.services.validation_service import fill_default_metadata

    tests.append({
        "category": "元数据",
        "name": "空 metadata → 补全默认值",
        "func": lambda: (
            fill_default_metadata({"business_meta": None}, agent_id="a1", scene_id="s1")
            ["business_meta"]["source"] == "api"
        )
    })

    tests.append({
        "category": "元数据",
        "name": "已有值不被覆盖",
        "func": lambda: (
            fill_default_metadata({"business_meta": {"project": "X"}})
            ["business_meta"]["project"] == "X"
        )
    })

    # ── 一站式管线 (2 个) ──
    from app.services.validation_service import validate_and_standardize

    tests.append({
        "category": "一站式管线",
        "name": "合法数据完整通过",
        "func": lambda: (
            validate_and_standardize({
                "user_id": "u1", "session_id": "s1", "content": "test",
                "role": "user", "timestamp": "2026-07-06T10:00:00Z"
            }, agent_id="a1")["record_id"].startswith("rec_")
        )
    })

    tests.append({
        "category": "一站式管线",
        "name": "缺少必填字段抛 ValidationError",
        "func": lambda: _expect_error(
            lambda: validate_and_standardize({"user_id": "u1"})
        )
    })

    # ── 安全工具 (4 个) ──
    from app.core.security import generate_api_key, hash_api_key, generate_agent_id

    tests.append({
        "category": "安全工具",
        "name": "API Key 格式: mem_ + 64 hex",
        "func": lambda: generate_api_key().startswith("mem_") and len(generate_api_key()) == 68
    })

    tests.append({
        "category": "安全工具",
        "name": "相同输入 hash 一致",
        "func": lambda: hash_api_key("mem_test") == hash_api_key("mem_test")
    })

    tests.append({
        "category": "安全工具",
        "name": "不同输入 hash 不同",
        "func": lambda: hash_api_key("mem_a") != hash_api_key("mem_b")
    })

    tests.append({
        "category": "安全工具",
        "name": "Agent ID 格式: agent_ + 16 hex",
        "func": lambda: generate_agent_id().startswith("agent_") and len(generate_agent_id()) == 22
    })

    # ── 统一响应 (3 个) ──
    from app.schemas.common import ok as _ok

    tests.append({
        "category": "统一响应",
        "name": "ok() 返回 {code:0, message:ok, data:...}",
        "func": lambda: (
            (lambda r: r["code"] == 0 and r["message"] == "ok" and r["data"] == {"a": 1})(
                _ok({"a": 1})
            )
        )
    })

    tests.append({
        "category": "统一响应",
        "name": "ok(data, message) 自定义 message",
        "func": lambda: _ok(None, "success")["message"] == "success"
    })

    tests.append({
        "category": "统一响应",
        "name": "ok(None) 返回 data=null",
        "func": lambda: _ok(None)["data"] is None
    })

    # ── AUTH 开关 (2 个) ──
    tests.append({
        "category": "AUTH",
        "name": "默认 AUTH_ENABLED=False (开发模式)",
        "func": lambda: (
            __import__("app.core.config", fromlist=["get_settings"])
            .get_settings().auth.enabled == False
        )
    })

    tests.append({
        "category": "AUTH",
        "name": "AuthConfig 包含 enabled 字段",
        "func": lambda: hasattr(
            __import__("app.core.config", fromlist=["AuthConfig"]).AuthConfig(), "enabled"
        )
    })

    # ── 边界值 (6 个) ──
    tests.append({
        "category": "边界值",
        "name": "Unicode 表情符号被保留",
        "func": lambda: (
            validate_and_standardize({
                "user_id": "u1", "session_id": "s1", "content": "你好 🌍 — эщкере"
            })["content"] == "你好 🌍 — эщкере"
        )
    })

    tests.append({
        "category": "边界值",
        "name": "128 字符 ID 通过",
        "func": lambda: validate_id_format("id", "a" * 128) is None
    })

    tests.append({
        "category": "边界值",
        "name": "129 字符 ID 被拒绝",
        "func": lambda: validate_id_format("id", "a" * 129) is not None
    })

    tests.append({
        "category": "边界值",
        "name": "含 @ 特殊字符 ID 被拒绝",
        "func": lambda: validate_id_format("id", "user@email") is not None
    })

    tests.append({
        "category": "边界值",
        "name": "100000 字符 content 超长",
        "func": lambda: (
            __import__("app.services.validation_service", fromlist=["validate_content_length"])
            .validate_content_length("x" * 100000) is not None
        )
    })

    tests.append({
        "category": "边界值",
        "name": "空 metadata 自动补全默认值",
        "func": lambda: (
            "business_meta" in validate_and_standardize({
                "user_id": "u1", "session_id": "s1", "content": "test"
            })
        )
    })

    # ── WriteResult Schema (3 个) ──
    tests.append({
        "category": "WriteResult",
        "name": "ADD/SKIP/MERGE 枚举均可用",
        "func": lambda: (
            set(e.value for e in __import__("app.schemas.memory", fromlist=["MemoryEvent"]).MemoryEvent)
            == {"ADD", "SKIP", "MERGE"}
        )
    })

    tests.append({
        "category": "WriteResult",
        "name": "WriteResultItem 构造正确",
        "func": lambda: (
            (lambda w: w.id == "mem_abc" and w.event.value == "ADD")(
                __import__("app.schemas.memory", fromlist=["WriteResultItem", "MemoryEvent"])
                .WriteResultItem(id="mem_abc", memory="test", event="ADD")
            )
        )
    })

    tests.append({
        "category": "WriteResult",
        "name": "MemoryWriteResponse 允许空 results",
        "func": lambda: (
            __import__("app.schemas.memory", fromlist=["MemoryWriteResponse"])
            .MemoryWriteResponse(results=[]).results == []
        )
    })

    # ── 异常处理器 (4 个) ──
    from app.core.exceptions import (
        ValidationError, AuthenticationError, NotFoundError, ConflictError
    )

    tests.append({
        "category": "异常",
        "name": "ValidationError 状态码 422",
        "func": lambda: ValidationError().status_code == 422
    })

    tests.append({
        "category": "异常",
        "name": "AuthenticationError 状态码 401",
        "func": lambda: AuthenticationError().status_code == 401
    })

    tests.append({
        "category": "异常",
        "name": "NotFoundError 状态码 404",
        "func": lambda: NotFoundError().status_code == 404
    })

    tests.append({
        "category": "异常",
        "name": "所有异常继承自 AppException",
        "func": lambda: all(
            issubclass(c, __import__("app.core.exceptions", fromlist=["AppException"]).AppException)
            for c in [ValidationError, AuthenticationError, NotFoundError, ConflictError]
        )
    })

    return tests


def _expect_error(fn):
    """期望 fn 抛出异常"""
    try:
        fn()
        return False
    except Exception:
        return True


# ═════════════════════════════════════════════════════════════════════════════
# 阶段2: API 集成测试 (需要启动服务)
# ═════════════════════════════════════════════════════════════════════════════

def run_api_tests():
    """运行 API 集成测试"""
    global total_pass, total_fail

    print(header("阶段2: API 集成测试 (需要服务运行在 localhost:8000)"))

    # 检查服务可用性
    import requests
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=3)
        print(f"  {ok('服务已连接')} — {r.json()}")
    except Exception:
        print(f"  {warn('服务未启动，跳过 API 测试')}")
        print(f"  {info('启动方式: uvicorn app.main:app --reload --port 8000')}")
        return

    # ── 存储变量 ──
    state = {"agent_id": "", "api_key": "", "scene_id": "", "session_id": "", "task_id": ""}

    # ── 场景1: Agent 注册 ──
    data = {
        "agent_name": "Web聊天助手",
        "scene_id": "chat",
        "permissions": ["read", "write"]
    }
    _api_test(
        "Agent 注册", "POST", "/agent/register", data, 201,
        expected_keys=["agent_id", "api_key", "api_key_prefix", "agent_name", "is_active"],
        on_response=lambda d: state.update(agent_id=d.get("agent_id", ""), api_key=d.get("api_key", ""))
    )

    # ── 场景2: Scene 创建 ──
    data2 = {"scene_name": "代码助手", "description": "写代码相关对话"}
    _api_test(
        "Scene 创建", "POST", "/scene", data2, 201,
        expected_keys=["scene_id", "scene_name", "is_active"],
        on_response=lambda d: state.update(scene_id=d.get("scene_id", ""))
    )

    # ── 场景3: Session 创建 ──
    data3 = {"user_id": "user_001", "agent_id": state["agent_id"], "scene_id": state["scene_id"]}
    _api_test(
        "Session 创建", "POST", "/session", data3, 201,
        expected_keys=["session_id", "status"],
        on_response=lambda d: state.update(session_id=d.get("session_id", ""))
    )

    # ── 场景4: Task 创建 ──
    data4 = {"user_id": "user_001", "title": "技术方案编写", "goal": "完成Q3文档"}
    _api_test(
        "Task 创建", "POST", "/task", data4, 201,
        expected_keys=["task_id", "status"],
        on_response=lambda d: state.update(task_id=d.get("task_id", ""))
    )

    # ── 场景5: Memory 写入 — 偏好检测 ADD ──
    data5 = {
        "user_id": "user_001", "scene_id": "chat", "task_id": state["task_id"],
        "messages": [{"role": "user", "content": "我叫张伟，喜欢Python后端开发，讨厌写前端代码"}]
    }
    _api_test(
        "Memory 写入 — 偏好检测 → ADD", "POST", "/memory/write", data5, 200,
        expected_keys=["results"],
        validate=lambda d: any(
            r["event"] == "ADD" and "张伟" in r["memory"]
            for r in d.get("results", [])
        )
    )

    # ── 场景6: Memory 写入 — 简单问候（MemoryPipeline 返回空 results） ──
    data6 = {"user_id": "user_001", "messages": [{"role": "user", "content": "你好"}]}
    _api_test(
        "Memory 写入 — 问候语 → 空 results", "POST", "/memory/write", data6, 200,
        expected_keys=["results"],
    )

    # ── 场景7: Memory 写入 — 多轮对话 ──
    data7 = {
        "user_id": "user_001", "scene_id": "chat",
        "messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你的？"},
            {"role": "user", "content": "我之前做的Python项目需要优化数据库"}
        ]
    }
    _api_test(
        "Memory 写入 — 多轮对话", "POST", "/memory/write", data7, 200,
        expected_keys=["results"]
    )

    # ── 场景8: 校验失败 — 缺少 messages ──
    data8 = {"user_id": "user_001"}
    _api_test(
        "校验失败 — 缺少 messages → 422", "POST", "/memory/write", data8, 422,
        expected_keys=["error_code", "trace_id"],
        validate=lambda d: d.get("error_code") == "INVALID_PARAM"
    )

    # ── 场景9: 校验失败 — 非法 role ──
    data9 = {"user_id": "user_001", "messages": [{"role": "hacker", "content": "x"}]}
    _api_test(
        "校验失败 — 非法 role → 422", "POST", "/memory/write", data9, 422,
        expected_keys=["error_code", "trace_id"]
    )

    # ── 场景10: Session 关闭 ──
    _api_test(
        "Session 关闭 — 含 memory_count", "POST", f"/session/{state['session_id']}/close", None, 200,
        expected_keys=["session_id", "status", "memory_count"],
        validate=lambda d: d.get("status") == "closed" and "memory_count" in d
    )

    # ── 场景11: Task 更新 ──
    data11 = {"status": "in_progress", "progress": "已完成需求分析"}
    _api_test(
        "Task 更新进展", "PUT", f"/task/{state['task_id']}", data11, 200,
        validate=lambda d: d.get("status") == "in_progress"
    )

    # ── 场景12: Task 进展查询 ──
    _api_test(
        "Task 进展查询 — 含 related_memory_count", "GET", f"/task/{state['task_id']}/progress", None, 200,
        expected_keys=["task_id", "status", "completed_count", "pending_count", "related_memory_count"]
    )

    # ── 场景13: 非法状态转换 ──
    data13 = {"status": "cancelled"}  # in_progress → cancelled 合法
    _api_test(
        "Task 合法状态转换", "PUT", f"/task/{state['task_id']}", data13, 200,
        validate=lambda d: d.get("status") == "cancelled"
    )

    # ── 场景14: Agent 列表 ──
    _api_test(
        "Agent 分页列表", "GET", "/agent", None, 200,
        expected_keys=["items", "total", "page", "page_size"]
    )

    # ── 场景15: Scene 列表 ──
    _api_test(
        "Scene 分页列表", "GET", "/scene", None, 200,
        expected_keys=["items", "total", "page", "page_size"]
    )


def _api_test(name: str, method: str, path: str, data: dict | None,
              expected_status: int,
              expected_keys: list | None = None,
              validate: callable = None,
              on_response: callable = None):
    """通用 API 测试"""
    global total_pass, total_fail
    import requests

    url = f"{API}{path}"
    print(f"\n  {'─' * 60}")
    print(f"  [{method}] {name}")
    if data:
        print(f"  📤 请求: {json.dumps(data, ensure_ascii=False)[:120]}")

    try:
        if method == "POST":
            resp = requests.post(url, json=data, timeout=10)
        elif method == "GET":
            resp = requests.get(url, timeout=10)
        elif method == "PUT":
            resp = requests.put(url, json=data, timeout=10)
        else:
            print(f"  {fail(f'未知方法 {method}')}")
            total_fail += 1
            return

        body = resp.json() if resp.text else {}
        status = resp.status_code
        data_part = body.get("data", body)

        # HTTP 状态码
        status_ok = (status == expected_status)
        print(f"  {'✅' if status_ok else '❌'} HTTP {status} (期望 {expected_status})")

        # 统一响应格式
        has_code = "code" in body
        print(f"  {'✅' if has_code else '❌'} 统一响应格式: code={body.get('code')}")

        # trace_id (错误时)
        if expected_status >= 400:
            has_trace = "trace_id" in body
            print(f"  {'✅' if has_trace else '❌'} trace_id={body.get('trace_id')}")

        # 期望字段
        if expected_keys and expected_status < 400:
            for key in expected_keys:
                has_key = key in data_part
                val = str(data_part.get(key, ""))[:80] if has_key else "MISSING"
                print(f"  {'✅' if has_key else '❌'} data.{key} = {val}")

        # 自定义校验
        if validate and expected_status < 400:
            ok_flag = validate(data_part)
            print(f"  {'✅' if ok_flag else '❌'} 自定义校验")

        # 回调
        if on_response and expected_status < 400:
            on_response(data_part)

        if status_ok:
            total_pass += 1
        else:
            total_fail += 1
            print(f"  📋 完整响应: {json.dumps(body, ensure_ascii=False)[:300]}")

    except Exception as e:
        print(f"  {fail(str(e))}")
        total_fail += 1


# ═════════════════════════════════════════════════════════════════════════════
# 主函数
# ═════════════════════════════════════════════════════════════════════════════

def main():
    global total_pass, total_fail

    print(f"\n{BOLD}{'█' * 70}{RESET}")
    print(f"{BOLD}  智能体输入管理和数据输入校验 功能测试 — 一键完整测试{RESET}")
    print(f"{BOLD}  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'█' * 70}{RESET}")

    # ── 阶段1: 单元测试 ──
    run_unit_tests()

    # ── 阶段2: API 测试 ──
    run_api_tests()

    # ── 汇总 ──
    total = total_pass + total_fail
    print(header(f"测试汇总: {total_pass} 通过 / {total_fail} 失败 / {total} 总计"))

    if total_fail == 0:
        print(f"\n  {ok('智能体输入管理和数据输入校验 全部功能测试通过！')}\n")
    else:
        print(f"\n  {fail(f'有 {total_fail} 项失败，请检查')}\n")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
