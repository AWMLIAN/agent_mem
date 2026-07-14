# -*- coding: utf-8 -*-
"""
角色B 功能测试 — MQ全链路 + 伪同步 + Mock模式 + 降级 + 批量写入 + 压缩触发。

对齐三份设计文档：
  - 核心改动.docx（方案一 Mock + 方案二 MQ/RPC等待）
  - 核心业务逻辑拆解.docx
  - 任务分工文档（角色B部分）

测试覆盖（8 模块 单元测试 + 7 模块 HTTP 集成测试）:
  B1  Model — interaction_type + status 列 + 索引
  B2  Config — KafkaConfig + RedisConfig + GenerationConfig
  B3  Mock Extraction — 中文正则规则匹配
  B4  Batch Insert — insert() 批量写入 + status=pending_extract
  B5  MQ Producer — 消息格式 + topic + 超时降级
  B6  MQ Consumer — 按类型分发逻辑
  B7  Degradation — MQ不可用降级同步(status=pending_extract)
  B8  Compression — 会话关闭压缩触发器
  B9  HTTP /write dialogue — Mock模式完整链路
  B10 HTTP /write session — 历史会话数据类型
  B11 HTTP /write task_process — 任务过程数据类型
  B12 HTTP /async_write — 异步写入 202
  B13 HTTP /search — 检索记忆
  B14 HTTP Session lifecycle — 创建到关闭+压缩
  B15 HTTP Error codes — 数字错误码 + 校验

运行:
  python tests/test_role_b.py                  # 纯单元测试 (B1-B8)
  python tests/test_role_b.py --with-server    # 含 HTTP 集成测试 (B1-B15)
  python tests/test_role_b.py --json           # JSON 输出格式
"""

import json as json_module
import re
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 确保 UTF-8 输出（Windows 兼容）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


# ============================================================
# 测试工具
# ============================================================

_tests_run = 0
_tests_passed = 0
_tests_failed = 0
_tests_skipped = 0
_failures: list[str] = []


def _run_test(name: str, fn):
    global _tests_run, _tests_passed, _tests_failed, _tests_skipped
    _tests_run += 1
    try:
        fn()
        _tests_passed += 1
        print(f"  [PASS] {name}")
        return True
    except unittest.SkipTest as e:
        _tests_skipped += 1
        print(f"  [SKIP] {name} — {e}")
        return None
    except Exception as e:
        _tests_failed += 1
        msg = f"{name}: {e}"
        _failures.append(msg)
        print(f"  [FAIL] {name} — {e}")
        return False


class _assert:
    @staticmethod
    def equal(a, b, msg=""):
        if a != b:
            raise AssertionError(f"{msg}: {a!r} != {b!r}" if msg else f"{a!r} != {b!r}")

    @staticmethod
    def true(cond, msg=""):
        if not cond:
            raise AssertionError(msg or "Expected True, got False")

    @staticmethod
    def false(cond, msg=""):
        if cond:
            raise AssertionError(msg or "Expected False, got True")

    @staticmethod
    def in_(item, container, msg=""):
        if item not in container:
            raise AssertionError(msg or f"{item!r} not in {container!r}")

    @staticmethod
    def not_in(item, container, msg=""):
        if item in container:
            raise AssertionError(msg or f"{item!r} should not be in {container!r}")

    @staticmethod
    def is_none(val, msg=""):
        if val is not None:
            raise AssertionError(msg or f"Expected None, got {val!r}")

    @staticmethod
    def is_not_none(val, msg=""):
        if val is None:
            raise AssertionError(msg or "Expected not None, got None")

    @staticmethod
    def greater(a, b, msg=""):
        if not a > b:
            raise AssertionError(msg or f"{a!r} <= {b!r}")

    @staticmethod
    def greater_equal(a, b, msg=""):
        if not a >= b:
            raise AssertionError(msg or f"{a!r} < {b!r}")


try:
    import unittest
except ImportError:
    pass


# ============================================================
# B1: Model Tests — interaction_type + status 列 + 索引
# ============================================================

def test_b1_model_columns():
    """B1.1: InteractionRecord 包含 interaction_type 和 status 列"""
    from app.models.base import InteractionRecord
    columns = {c.name: c for c in InteractionRecord.__table__.columns}

    _assert.in_("interaction_type", columns, "缺少 interaction_type 列")
    _assert.in_("status", columns, "缺少 status 列")

    it_col = columns["interaction_type"]
    _assert.equal(str(it_col.type).lower(), "varchar(32)", f"interaction_type 类型错误: {it_col.type}")

    st_col = columns["status"]
    _assert.in_("varchar", str(st_col.type).lower(), f"status 类型错误: {st_col.type}")


def test_b1_model_status_default():
    """B1.2: status 默认值为 pending_extract"""
    from app.models.base import InteractionRecord
    columns = {c.name: c for c in InteractionRecord.__table__.columns}

    st_col = columns["status"]
    _assert.is_not_none(st_col.default, "status 缺少默认值")
    default_val = st_col.default.arg if hasattr(st_col.default, 'arg') else str(st_col.default)
    _assert.equal(default_val, "pending_extract", f"status 默认值错误: {default_val}")


def test_b1_model_indexes():
    """B1.3: InteractionRecord 包含所需联合索引"""
    from app.models.base import InteractionRecord
    idx_names = {idx.name for idx in InteractionRecord.__table__.indexes}

    expected_indexes = [
        "idx_interaction_session_turn",
        "idx_interaction_processed",
        "idx_interaction_user_time",
        "idx_interaction_type_user",
        "idx_interaction_user_session_time",
        "idx_interaction_status",
    ]
    for idx_name in expected_indexes:
        _assert.in_(idx_name, idx_names, f"缺少索引: {idx_name}")


def test_b1_model_interaction_type_default():
    """B1.4: interaction_type 默认值为 dialogue"""
    from app.models.base import InteractionRecord
    columns = {c.name: c for c in InteractionRecord.__table__.columns}

    it_col = columns["interaction_type"]
    _assert.is_not_none(it_col.default, "interaction_type 缺少默认值")
    default_val = it_col.default.arg if hasattr(it_col.default, 'arg') else str(it_col.default)
    _assert.equal(default_val, "dialogue", f"interaction_type 默认值错误: {default_val}")


# ============================================================
# B2: Config Tests — KafkaConfig + RedisConfig + GenerationConfig
# ============================================================

def test_b2_kafka_config():
    """B2.1: KafkaConfig 包含所有必要字段"""
    from app.core.config import KafkaConfig
    cfg = KafkaConfig()

    _assert.true(hasattr(cfg, "bootstrap_servers"), "缺少 bootstrap_servers")
    _assert.true(hasattr(cfg, "topic_memory_write"), "缺少 topic_memory_write")
    _assert.true(hasattr(cfg, "topic_memory_result"), "缺少 topic_memory_result")
    _assert.true(hasattr(cfg, "topic_memory_dlq"), "缺少 topic_memory_dlq")
    _assert.true(hasattr(cfg, "consumer_group"), "缺少 consumer_group")
    _assert.true(hasattr(cfg, "max_retries"), "缺少 max_retries")
    _assert.true(hasattr(cfg, "retry_backoff_ms"), "缺少 retry_backoff_ms")

    _assert.equal(cfg.max_retries, 3, "max_retries 默认值错误")
    _assert.equal(cfg.retry_backoff_ms, 1000, "retry_backoff_ms 默认值错误")


def test_b2_redis_config():
    """B2.2: RedisConfig 包含所有必要字段"""
    from app.core.config import RedisConfig
    cfg = RedisConfig()

    _assert.true(hasattr(cfg, "url"), "缺少 url")
    _assert.true(hasattr(cfg, "result_ttl"), "缺少 result_ttl")
    _assert.true(hasattr(cfg, "result_poll_timeout"), "缺少 result_poll_timeout")

    _assert.greater(cfg.result_ttl, 0, "result_ttl 应 > 0")
    _assert.greater(cfg.result_poll_timeout, 0, "result_poll_timeout 应 > 0")


def test_b2_generation_config():
    """B2.3: GenerationConfig 包含 Mock 和 MQ_Wait 开关"""
    from app.core.config import GenerationConfig
    cfg = GenerationConfig()

    _assert.true(hasattr(cfg, "use_mock_extraction"), "缺少 use_mock_extraction")
    _assert.true(hasattr(cfg, "use_mq_wait"), "缺少 use_mq_wait")

    _assert.true(cfg.use_mock_extraction, "use_mock_extraction 默认应为 True")
    _assert.false(cfg.use_mq_wait, "use_mq_wait 默认应为 False")


def test_b2_settings_includes_all():
    """B2.4: Settings 包含 kafka + redis 配置"""
    from app.core.config import Settings
    s = Settings()

    _assert.true(hasattr(s, "kafka"), "Settings 缺少 kafka")
    _assert.true(hasattr(s, "redis"), "Settings 缺少 redis")
    _assert.true(hasattr(s.kafka, "topic_memory_dlq"), "kafka 缺少 topic_memory_dlq")
    _assert.true(hasattr(s.redis, "result_ttl"), "redis 缺少 result_ttl")


# ============================================================
# B3: Mock Extraction — 中文正则规则匹配
# ============================================================

def test_b3_mock_identity():
    """B3.1: '我是...' 应被提取为 identity"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "我是张三，来自北京"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("张三", results[0]["memory"])


def test_b3_mock_reminder():
    """B3.2: '记住...' 应被提取为 reminder"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "记住我喜欢喝咖啡不加糖"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("咖啡", results[0]["memory"])


def test_b3_mock_task_goal():
    """B3.3: '我的任务是...' 应被提取为 task"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "我的任务是完成周报撰写"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("周报", results[0]["memory"])


def test_b3_mock_preference_like():
    """B3.4: '我喜欢...' 应被提取为 preference"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "我喜欢听古典音乐"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("古典音乐", results[0]["memory"])


def test_b3_mock_preference_dislike():
    """B3.5: '我不喜欢...' 应被提取为 preference"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "我不喜欢排队等待"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("排队", results[0]["memory"])


def test_b3_mock_decision():
    """B3.6: '我决定...' 应被提取为 decision"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "我决定下个月去旅行"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("旅行", results[0]["memory"])


def test_b3_mock_no_match():
    """B3.7: 无匹配消息应返回 SKIP"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "今天天气真不错啊"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "SKIP")


def test_b3_mock_english_no_match():
    """B3.8: 纯英文消息应返回 SKIP（正则只匹配中文）"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "I am John from New York"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "SKIP")


def test_b3_mock_multiple_messages():
    """B3.9: 多条消息混合匹配"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [
        {"role": "user", "content": "我是李明"},
        {"role": "user", "content": "今天天气不错"},
        {"role": "assistant", "content": "记住我明天有会议"},
        {"role": "user", "content": "我决定下午去健身"},
    ]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 4)

    events = [r["event"] for r in results]
    _assert.equal(events[0], "ADD")   # 我是李明 → identity
    _assert.equal(events[1], "SKIP")  # 今天天气不错 → 无匹配
    _assert.equal(events[2], "ADD")   # 记住我明天有会议 → reminder
    _assert.equal(events[3], "ADD")   # 我决定下午去健身 → decision


def test_b3_mock_progress():
    """B3.10: '完成了/已经完成' 应被提取为 progress"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "完成了用户模块的单元测试"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("单元测试", results[0]["memory"])


def test_b3_mock_need_to_do():
    """B3.11: '需要完成/要做' 应被提取为 task"""
    from app.services.mock_extractor import mock_extract_results
    msgs = [{"role": "user", "content": "需要完成数据库迁移脚本"}]
    results = mock_extract_results(msgs)
    _assert.equal(len(results), 1)
    _assert.equal(results[0]["event"], "ADD")
    _assert.in_("数据库", results[0]["memory"])


# ============================================================
# B4: Batch Insert — insert() 批量写入
# ============================================================

def test_b4_insert_imported():
    """B4.1: memory.py 导入了 insert"""
    from app.api.v1.memory import insert
    _assert.is_not_none(insert)


def test_b4_records_use_insert():
    """B4.2: _batch_write_records 使用 insert() 而非逐条 db.add()"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._batch_write_records)
    _assert.in_("insert(InteractionRecord)", source, "_batch_write_records 未使用 insert()")
    _assert.not_in("db.add(", source, "_batch_write_records 不应使用 db.add()")


def test_b4_fallback_uses_insert():
    """B4.3: _fallback_sync_write 使用 insert()"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._fallback_sync_write)
    _assert.in_("insert(InteractionRecord)", source, "_fallback_sync_write 未使用 insert()")
    _assert.not_in("session.add(", source, "_fallback_sync_write 不应使用 session.add()")


def test_b4_records_have_status():
    """B4.4: 批量写入的记录包含 status 字段"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._batch_write_records)
    _assert.in_('"status"', source, "记录字典缺少 status 字段")
    _assert.in_('"pending_extract"', source, "status 默认值应为 pending_extract")


# ============================================================
# B5: MQ Producer — 消息格式 + topic + 超时降级
# ============================================================

def test_b5_producer_exists():
    """B5.1: mq_producer 模块存在且包含必要方法"""
    from app.services.mq_producer import mq_producer as prod
    _assert.true(hasattr(prod, "publish_memory_write"), "缺少 publish_memory_write")
    _assert.true(hasattr(prod, "publish_memory_result"), "缺少 publish_memory_result")
    _assert.true(hasattr(prod, "publish_to_dlq"), "缺少 publish_to_dlq")
    _assert.true(hasattr(prod, "is_available"), "缺少 is_available")


def test_b5_producer_not_available_initially():
    """B5.2: Producer 初始化后不可用（未调用 start()）"""
    from app.services.mq_producer import MQProducer
    # 创建一个新的 producer 实例（不调用 start）
    prod = MQProducer()
    _assert.false(prod.is_available, "未启动的 producer 应不可用")


async def _test_b5_producer_start_stop():
    """B5.3: Producer start/stop 生命周期（需要 Kafka 运行）"""
    from app.services.mq_producer import MQProducer
    prod = MQProducer()
    try:
        await prod.start()
        # 即使 Kafka 不可用，start() 也不应抛异常
    except Exception as e:
        raise AssertionError(f"Producer start 不应抛异常: {e}")
    finally:
        await prod.stop()


def test_b5_message_format():
    """B5.4: 验证消息格式包含必要字段"""
    expected_fields = ["request_id", "user_id", "agent_id", "body", "timestamp"]
    # 这些字段在 publish_memory_write 中定义
    import inspect
    from app.services.mq_producer import MQProducer
    source = inspect.getsource(MQProducer.publish_memory_write)
    for field in expected_fields:
        _assert.in_(f'"{field}"', source, f"消息格式缺少字段: {field}")


# ============================================================
# B6: MQ Consumer — 按类型分发逻辑
# ============================================================

def test_b6_consumer_dispatch_functions():
    """B6.1: Consumer 包含三种类型的处理函数"""
    import inspect
    from app.services import mq_consumer
    source = inspect.getsource(mq_consumer._dispatch_and_store)

    _assert.in_("dialogue", source, "缺少 dialogue 处理分支")
    _assert.in_("session", source, "缺少 session 处理分支")
    _assert.in_("task_process", source, "缺少 task_process 处理分支")


def test_b6_consumer_retry_logic():
    """B6.2: Consumer 包含指数退避重试逻辑"""
    import inspect
    from app.services import mq_consumer as mod
    source = inspect.getsource(mod._process_one_message)

    _assert.in_("MAX_RETRIES", source, "缺少 MAX_RETRIES 重试次数")
    _assert.in_("attempt", source, "缺少重试循环")
    source_lower = source.lower()
    has_dlq = "dlq" in source_lower or "publish_to_dlq" in source
    _assert.true(has_dlq, "缺少 DLQ 投递")


def test_b6_consumer_batch_insert():
    """B6.3: Consumer 使用批量 insert 写入"""
    import inspect
    from app.services import mq_consumer as mod
    source = inspect.getsource(mod._dispatch_and_store)

    _assert.in_("insert(InteractionRecord)", source, "Consumer 未使用批量 insert")


def test_b6_consumer_offset_commit():
    """B6.4: Consumer 处理完成后手动提交 offset"""
    import inspect
    from app.services import mq_consumer as mod
    source = inspect.getsource(mod._process_one_message)

    _assert.in_("commit()", source, "Consumer 未手动提交 offset")


# ============================================================
# B7: Degradation — MQ不可用降级同步
# ============================================================

def test_b7_try_deliver_checks_availability():
    """B7.1: _try_deliver_to_mq 检查 producer.is_available"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._try_deliver_to_mq)

    _assert.in_("is_available", source, "_try_deliver_to_mq 未检查 is_available")


def test_b7_fallback_status_pending():
    """B7.2: 降级写入使用 status=pending_extract"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._fallback_sync_write)

    _assert.in_('"pending_extract"', source, "降级写入未设置 status=pending_extract")


def test_b7_fallback_uses_insert():
    """B7.3: 降级写入使用批量 insert"""
    import inspect
    from app.api.v1 import memory as mem_mod
    source = inspect.getsource(mem_mod._fallback_sync_write)
    _assert.in_("insert(InteractionRecord)", source, "降级写入未使用 insert()")


def test_b7_try_deliver_returns_bool():
    """B7.4: _try_deliver_to_mq 返回 bool 类型"""
    from app.api.v1.memory import _try_deliver_to_mq
    import asyncio

    async def _check():
        result = await _try_deliver_to_mq("test_id", "user1", "agent1", {})
        _assert.true(isinstance(result, bool), f"返回值应为 bool，实际: {type(result)}")

    try:
        asyncio.new_event_loop().run_until_complete(_check())
    except RuntimeError:
        asyncio.run(_check())


# ============================================================
# B8: Compression — 会话关闭压缩触发器
# ============================================================

def test_b8_session_close_has_background_tasks():
    """B8.1: session_close 接受 BackgroundTasks 参数"""
    import inspect
    from app.api.v1 import session as sess_mod
    source = inspect.getsource(sess_mod.session_close)

    _assert.in_("background_tasks", source, "session_close 缺少 background_tasks 参数")


def test_b8_compression_function_exists():
    """B8.2: _trigger_compression 函数存在"""
    from app.api.v1.session import _trigger_compression
    _assert.true(callable(_trigger_compression))


def test_b8_compression_threshold():
    """B8.3: 压缩阈值来自配置文件"""
    from app.core.config import get_settings
    settings = get_settings()

    _assert.greater(settings.compression.trigger_session_length, 0,
                    "trigger_session_length 应 > 0")
    _assert.true(hasattr(settings.compression, "compressed_context_length"),
                 "缺少 compressed_context_length")


def test_b8_close_response_has_compression_flag():
    """B8.4: 会话关闭响应包含 compression_triggered 字段"""
    import inspect
    from app.api.v1 import session as sess_mod
    source = inspect.getsource(sess_mod.session_close)

    _assert.in_("compression_triggered", source, "响应未包含 compression_triggered")


# ============================================================
# HTTP Integration Tests (需要服务器运行)
# ============================================================

# 全局标记：是否已尝试 HTTP 测试
_http_tests_attempted = False
_http_tests_available = False


async def _ensure_server(http_client=None):
    """检查服务器是否可达"""
    global _http_tests_attempted, _http_tests_available

    if _http_tests_attempted:
        return _http_tests_available

    _http_tests_attempted = True

    try:
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/docs")
            _http_tests_available = resp.status_code < 500
    except Exception:
        _http_tests_available = False

    return _http_tests_available


async def _http_post(path: str, json_data: dict, headers: dict | None = None):
    """发送 POST 请求到测试服务器"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _headers = {
        "X-User-ID": json_data.get("user_id", "test_user_http"),
        "X-Agent-Id": "test_agent_role_b",
    }
    if headers:
        _headers.update(headers)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(path, json=json_data, headers=_headers)
        return resp


# ---- B9: HTTP /write dialogue (Mock模式) ----

async def _test_b9_write_dialogue_mock():
    """B9.1: POST /write dialogue 类型 Mock 模式完整链路"""
    payload = {
        "user_id": "test_roleb_http",
        "interaction_type": "dialogue",
        "messages": [
            {"role": "user", "content": "我是王小明"},
            {"role": "assistant", "content": "你好王小明！"},
            {"role": "user", "content": "今天我完成了需求文档"},
            {"role": "user", "content": "今天天气好"},
        ],
    }
    resp = await _http_post("/api/v1/memory/write", payload)
    _assert.equal(resp.status_code, 200, f"状态码应为 200: {resp.status_code}")
    data = resp.json()
    _assert.equal(data["code"], 0, f"业务码应为 0: {data}")
    _assert.is_not_none(data.get("data"), "data 不应为空")
    results = data["data"]["results"]
    _assert.greater_equal(len(results), 4, f"results 应至少有 4 条: {len(results)}")


async def _test_b10_write_session():
    """B10.1: POST /write session 类型历史会话"""
    payload = {
        "user_id": "test_roleb_session",
        "interaction_type": "session",
        "session_id": "sess_b10_test",
        "messages": [
            {"role": "user", "content": "上次你帮我查过天气"},
            {"role": "assistant", "content": "是的，那天是晴天"},
        ],
        "session_time": "2026-07-10T14:00:00Z",
        "session_source": "chatgpt",
        "session_summary": "用户与ChatGPT的天气查询对话",
    }
    resp = await _http_post("/api/v1/memory/write", payload)
    _assert.equal(resp.status_code, 200, f"状态码应为 200: {resp.status_code}")
    data = resp.json()
    _assert.equal(data["code"], 0, f"业务码应为 0: {data}")


async def _test_b11_write_task_process():
    """B11.1: POST /write task_process 类型任务过程"""
    payload = {
        "user_id": "test_roleb_task",
        "interaction_type": "task_process",
        "task_id": "task_b11_test",
        "messages": [
            {"role": "user", "content": "我开始处理报税"},
            {"role": "assistant", "content": "好的，我来帮你"},
        ],
        "task_goal": "完成2026年个人所得税申报",
        "task_progress": "已收集收入证明，正在填写表格",
        "task_result": "",
    }
    resp = await _http_post("/api/v1/memory/write", payload)
    _assert.equal(resp.status_code, 200, f"状态码应为 200: {resp.status_code}")
    data = resp.json()
    _assert.equal(data["code"], 0, f"业务码应为 0: {data}")


async def _test_b12_async_write():
    """B12.1: POST /async_write 返回 202 + request_id"""
    payload = {
        "user_id": "test_roleb_async",
        "interaction_type": "dialogue",
        "messages": [
            {"role": "user", "content": "我是异步测试用户"},
        ],
    }
    resp = await _http_post("/api/v1/memory/async_write", payload)
    _assert.equal(resp.status_code, 202, f"状态码应为 202: {resp.status_code}")
    data = resp.json()
    _assert.equal(data["code"], 0)
    _assert.is_not_none(data["data"].get("request_id"), "缺少 request_id")
    _assert.equal(data["data"]["status"], "accepted")


async def _test_b13_search():
    """B13.1: POST /search 检索记忆"""
    # 先写入一些数据
    write_payload = {
        "user_id": "test_roleb_search",
        "interaction_type": "dialogue",
        "messages": [
            {"role": "user", "content": "我是搜索测试用户，我喜欢喝咖啡"},
        ],
    }
    await _http_post("/api/v1/memory/write", write_payload)

    # 再检索
    search_payload = {
        "query": "咖啡",
        "user_id": "test_roleb_search",
        "top_k": 5,
    }
    resp = await _http_post("/api/v1/memory/search", search_payload)
    _assert.equal(resp.status_code, 200, f"状态码应为 200: {resp.status_code}")
    data = resp.json()
    _assert.equal(data["code"], 0)

    # 搜索可能返回结果也可能为空（取决于 LLM 是否可用）
    _assert.is_not_none(data.get("data"), "data 不应为空")


async def _test_b14_session_lifecycle():
    """B14.1: Session 完整生命周期 — 创建 → 查询 → 关闭+压缩"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "X-User-ID": "test_roleb_sess",
            "X-Agent-Id": "test_agent_role_b",
        }

        # 1. 创建会话
        create_resp = await client.post(
            "/api/v1/session",
            json={"user_id": "test_roleb_sess"},
            headers=headers,
        )
        _assert.equal(create_resp.status_code, 201, f"创建会话失败: {create_resp.status_code}")
        session_id = create_resp.json()["data"]["session_id"]
        _assert.is_not_none(session_id)

        # 2. 查询会话
        get_resp = await client.get(
            f"/api/v1/session/{session_id}",
            headers=headers,
        )
        _assert.equal(get_resp.status_code, 200)
        _assert.equal(get_resp.json()["data"]["status"], "active")

        # 3. 关闭会话（含压缩检查）
        close_resp = await client.post(
            f"/api/v1/session/{session_id}/close",
            headers=headers,
        )
        _assert.equal(close_resp.status_code, 200)
        close_data = close_resp.json()["data"]
        _assert.equal(close_data["status"], "closed")
        _assert.in_("compression_triggered", close_data, "响应缺少 compression_triggered")
        _assert.true(isinstance(close_data["compression_triggered"], bool))


async def _test_b15_error_codes():
    """B15.1: 数字错误码 — 校验失败返回数字码"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "X-User-ID": "test_roleb_err",
            "X-Agent-Id": "test_agent_role_b",
        }

        # 1. 非法 interaction_type
        resp = await client.post(
            "/api/v1/memory/write",
            json={
                "user_id": "test_roleb_err",
                "interaction_type": "invalid_type",
                "messages": [{"role": "user", "content": "test"}],
            },
            headers=headers,
        )
        _assert.equal(resp.status_code, 422, f"422 预期: {resp.status_code}")

        # 2. dialogue 类型缺少 messages
        resp2 = await client.post(
            "/api/v1/memory/write",
            json={
                "user_id": "test_roleb_err2",
                "interaction_type": "dialogue",
            },
            headers=headers,
        )
        _assert.equal(resp2.status_code, 422, f"422 预期: {resp2.status_code}")

        # 3. 资源不存在
        resp3 = await client.get(
            "/api/v1/session/nonexistent_session_id_xyz",
            headers=headers,
        )
        _assert.equal(resp3.status_code, 404, f"404 预期: {resp3.status_code}")


# ============================================================
# 测试运行器
# ============================================================

def _print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _print_summary() -> None:
    print(f"\n{'=' * 60}")
    print(f"  测试汇总")
    print(f"{'=' * 60}")
    total = _tests_run
    passed = _tests_passed
    failed = _tests_failed
    skipped = _tests_skipped
    rate = (passed / (total - skipped) * 100) if (total - skipped) > 0 else 0
    print(f"  总计: {total}  |  通过: {passed}  |  失败: {failed}  |  跳过: {skipped}")
    print(f"  通过率: {rate:.1f}% (排除跳过)")

    if _failures:
        print(f"\n  失败明细:")
        for f in _failures:
            print(f"    - {f}")

    if _http_tests_attempted and not _http_tests_available:
        print(f"\n  [INFO] HTTP 集成测试未运行（服务器未启动）")
        print(f"         使用 --with-server 参数运行完整测试")


# ---- 单元测试注册 ----
_UNIT_TESTS = [
    # B1: Model
    ("B1.1 InteractionRecord columns", test_b1_model_columns),
    ("B1.2 status default pending_extract", test_b1_model_status_default),
    ("B1.3 indexes", test_b1_model_indexes),
    ("B1.4 interaction_type default dialogue", test_b1_model_interaction_type_default),
    # B2: Config
    ("B2.1 KafkaConfig", test_b2_kafka_config),
    ("B2.2 RedisConfig", test_b2_redis_config),
    ("B2.3 GenerationConfig mock/mq_wait", test_b2_generation_config),
    ("B2.4 Settings includes kafka+redis", test_b2_settings_includes_all),
    # B3: Mock Extraction
    ("B3.1 Mock identity", test_b3_mock_identity),
    ("B3.2 Mock reminder", test_b3_mock_reminder),
    ("B3.3 Mock task goal", test_b3_mock_task_goal),
    ("B3.4 Mock preference (like)", test_b3_mock_preference_like),
    ("B3.5 Mock preference (dislike)", test_b3_mock_preference_dislike),
    ("B3.6 Mock decision", test_b3_mock_decision),
    ("B3.7 Mock no match SKIP", test_b3_mock_no_match),
    ("B3.8 Mock English SKIP", test_b3_mock_english_no_match),
    ("B3.9 Mock multiple messages", test_b3_mock_multiple_messages),
    ("B3.10 Mock progress", test_b3_mock_progress),
    ("B3.11 Mock need-to-do task", test_b3_mock_need_to_do),
    # B4: Batch Insert
    ("B4.1 insert imported", test_b4_insert_imported),
    ("B4.2 _batch_write_records uses insert()", test_b4_records_use_insert),
    ("B4.3 _fallback_sync_write uses insert()", test_b4_fallback_uses_insert),
    ("B4.4 records have status field", test_b4_records_have_status),
    # B5: MQ Producer
    ("B5.1 Producer methods exist", test_b5_producer_exists),
    ("B5.2 Producer not available initially", test_b5_producer_not_available_initially),
    ("B5.3 Message format fields", test_b5_message_format),
    # B6: MQ Consumer
    ("B6.1 Consumer dispatch functions", test_b6_consumer_dispatch_functions),
    ("B6.2 Consumer retry logic", test_b6_consumer_retry_logic),
    ("B6.3 Consumer batch insert", test_b6_consumer_batch_insert),
    ("B6.4 Consumer offset commit", test_b6_consumer_offset_commit),
    # B7: Degradation
    ("B7.1 _try_deliver checks is_available", test_b7_try_deliver_checks_availability),
    ("B7.2 Fallback status pending_extract", test_b7_fallback_status_pending),
    ("B7.3 Fallback uses insert()", test_b7_fallback_uses_insert),
    ("B7.4 _try_deliver returns bool", test_b7_try_deliver_returns_bool),
    # B8: Compression
    ("B8.1 Session close has BackgroundTasks", test_b8_session_close_has_background_tasks),
    ("B8.2 _trigger_compression exists", test_b8_compression_function_exists),
    ("B8.3 Compression threshold config", test_b8_compression_threshold),
    ("B8.4 Close response has compression_triggered", test_b8_close_response_has_compression_flag),
]

# ---- HTTP 集成测试注册 ----
_HTTP_TESTS = [
    ("B9.1  HTTP /write dialogue (Mock)", _test_b9_write_dialogue_mock),
    ("B10.1 HTTP /write session", _test_b10_write_session),
    ("B11.1 HTTP /write task_process", _test_b11_write_task_process),
    ("B12.1 HTTP /async_write 202", _test_b12_async_write),
    ("B13.1 HTTP /search", _test_b13_search),
    ("B14.1 HTTP Session lifecycle + compression", _test_b14_session_lifecycle),
    ("B15.1 HTTP Error codes numeric", _test_b15_error_codes),
]


def run_unit_tests() -> None:
    """运行所有单元测试"""
    _print_header("B1: Model Tests")
    for name, fn in _UNIT_TESTS[:4]:
        _run_test(name, fn)

    _print_header("B2: Config Tests")
    for name, fn in _UNIT_TESTS[4:8]:
        _run_test(name, fn)

    _print_header("B3: Mock Extraction Tests")
    for name, fn in _UNIT_TESTS[8:19]:
        _run_test(name, fn)

    _print_header("B4: Batch Insert Tests")
    for name, fn in _UNIT_TESTS[19:23]:
        _run_test(name, fn)

    _print_header("B5: MQ Producer Tests")
    for name, fn in _UNIT_TESTS[23:26]:
        _run_test(name, fn)

    _print_header("B6: MQ Consumer Tests")
    for name, fn in _UNIT_TESTS[26:30]:
        _run_test(name, fn)

    _print_header("B7: Degradation Tests")
    for name, fn in _UNIT_TESTS[30:34]:
        _run_test(name, fn)

    _print_header("B8: Compression Tests")
    for name, fn in _UNIT_TESTS[34:38]:
        _run_test(name, fn)


async def run_http_tests_async() -> None:
    """运行所有 HTTP 集成测试"""
    import asyncio

    available = await _ensure_server()
    if not available:
        print("  [SKIP] 服务器不可达，跳过 HTTP 集成测试")
        return

    _print_header("B9-B15: HTTP Integration Tests")
    for name, fn in _HTTP_TESTS:
        try:
            await fn()
            print(f"  [PASS] {name}")
            global _tests_passed, _tests_run
            _tests_passed += 1
            _tests_run += 1
        except Exception as e:
            global _tests_failed
            _tests_failed += 1
            _tests_run += 1
            msg = f"{name}: {e}"
            _failures.append(msg)
            print(f"  [FAIL] {name} — {e}")


def run_http_tests() -> None:
    """同步包装器"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
    except RuntimeError:
        pass

    asyncio.run(run_http_tests_async())


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="角色B 功能测试套件")
    parser.add_argument("--with-server", action="store_true",
                        help="包含 HTTP 集成测试（需要应用可运行）")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 格式输出测试结果")
    parser.add_argument("--only", type=str,
                        help="仅运行指定模块（如 B3, B5）")
    args = parser.parse_args()

    if args.only:
        _print_header(f"仅运行: {args.only}")
        for name, fn in _UNIT_TESTS:
            if name.startswith(args.only):
                _run_test(name, fn)
            elif args.with_server:
                for hname, hfn in _HTTP_TESTS:
                    if hname.startswith(args.only):
                        _run_test(hname, lambda: asyncio.run(hfn()))
    else:
        run_unit_tests()

        if args.with_server:
            _print_header("B9-B15: HTTP Integration Tests")
            run_http_tests()

    _print_summary()

    if args.json:
        print("\n[JSON]")
        print(json_module.dumps({
            "total": _tests_run,
            "passed": _tests_passed,
            "failed": _tests_failed,
            "skipped": _tests_skipped,
            "failures": _failures,
        }, ensure_ascii=False, indent=2))

    # 退出码：有失败则非零
    if _tests_failed > 0:
        sys.exit(1)
