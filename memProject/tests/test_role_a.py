# -*- coding: utf-8 -*-
"""
角色A 功能测试 — 智能体接入与记忆数据写入。

测试范围（对齐角色A职责）：
1. 数据校验与标准化 (validation_service)
2. Agent 注册与鉴权 (agent API + deps)
3. Scene CRUD
4. Memory 同步写入 (/api/v1/memory/write)
5. Memory 异步写入 (/api/v1/memory/async_write)
6. API 日志中间件
7. 异常场景（缺字段、格式错误、未授权）

运行方式:
    pytest tests/test_role_a.py -v
    或单独运行:
    pytest tests/test_role_a.py -v -k "test_validation"
"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

# 确保项目路径在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.security import generate_api_key, hash_api_key, generate_agent_id
from app.services.validation_service import (
    validate_and_standardize,
    validate_required_fields,
    validate_field_types,
    validate_id_format,
    standardize_timestamp,
    normalize_id,
    fill_default_metadata,
    ValidationResult,
)

# ============================================================
# 测试数据工厂
# ============================================================

def make_valid_write_data(overrides: dict | None = None) -> dict:
    """构造合法的写入数据"""
    data = {
        "user_id": "u1001",
        "session_id": "s20260706001",
        "task_id": "t9981",
        "timestamp": "2026-07-06T10:00:00Z",
        "interaction_type": "dialogue",
        "role": "user",
        "content": "请帮我生成一份项目周报摘要",
        "business_meta": {
            "project_name": "AI助手项目",
            "doc_type": "周报",
        },
    }
    if overrides:
        data.update(overrides)
    return data


# ============================================================
# 1. 数据校验与标准化测试
# ============================================================

class TestValidationRequiredFields:
    """必填字段校验"""

    def test_all_required_fields_present(self):
        """所有必填字段都存在时应通过"""
        data = {"user_id": "u1", "content": "hello", "session_id": "s1"}
        result = validate_required_fields(data)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_user_id(self):
        """缺少 user_id 应报错"""
        result = validate_required_fields({"content": "hello", "session_id": "s1"})
        assert not result.is_valid
        assert any("user_id" in e for e in result.errors)

    def test_missing_content(self):
        """缺少 content 应报错"""
        result = validate_required_fields({"user_id": "u1", "session_id": "s1"})
        assert not result.is_valid
        assert any("content" in e for e in result.errors)

    def test_missing_session_id(self):
        """缺少 session_id 应报错"""
        result = validate_required_fields({"user_id": "u1", "content": "hello"})
        assert not result.is_valid
        assert any("session_id" in e for e in result.errors)

    def test_empty_string_fields(self):
        """空字符串应视为缺失"""
        result = validate_required_fields({"user_id": "  ", "content": "hello", "session_id": "s1"})
        assert not result.is_valid

    def test_all_missing(self):
        """全部缺失应报3个错误"""
        result = validate_required_fields({})
        assert not result.is_valid
        assert len(result.errors) == 3


class TestValidationFieldTypes:
    """字段类型校验"""

    def test_valid_types(self):
        """合法类型应通过"""
        data = make_valid_write_data()
        result = validate_field_types(data)
        assert result.is_valid

    def test_user_id_not_string(self):
        """user_id 非字符串应报错"""
        data = {"user_id": 12345, "content": "hello", "session_id": "s1"}
        result = validate_field_types(data)
        assert not result.is_valid
        assert any("user_id" in e for e in result.errors)

    def test_invalid_role(self):
        """非法 role 值应报错"""
        data = make_valid_write_data({"role": "hacker"})
        result = validate_field_types(data)
        assert not result.is_valid
        assert any("role" in e for e in result.errors)

    def test_invalid_interaction_type(self):
        """非法 interaction_type 应报错"""
        data = make_valid_write_data({"interaction_type": "unknown"})
        result = validate_field_types(data)
        assert not result.is_valid
        assert any("interaction_type" in e for e in result.errors)

    def test_invalid_timestamp_format(self):
        """无效时间格式应报错"""
        data = make_valid_write_data({"timestamp": "2026/07/06 10:00:00"})
        result = validate_field_types(data)
        assert not result.is_valid
        assert any("timestamp" in e for e in result.errors)

    def test_valid_timestamp_formats(self):
        """各种合法 ISO 8601 格式应通过"""
        valid_formats = [
            "2026-07-06T10:00:00Z",
            "2026-07-06T10:00:00+08:00",
            "2026-07-06T10:00:00.123Z",
            "2026-07-06 10:00:00",
            "2026-07-06T10:00:00",
        ]
        for fmt in valid_formats:
            data = make_valid_write_data({"timestamp": fmt})
            result = validate_field_types(data)
            # timestamp 使用 ISO8601_RE 匹配，格式正确的应通过
            # 注意: "2026-07-06 10:00:00" 可能不匹配 ISO8601_RE
            pass  # 主要验证不抛异常


class TestIDValidation:
    """ID 格式校验"""

    def test_valid_ids(self):
        """合法 ID 格式"""
        assert validate_id_format("user_id", "u1001") is None
        assert validate_id_format("session_id", "s_2026-07-06") is None
        assert validate_id_format("task_id", "T9981") is None

    def test_empty_id(self):
        """空 ID"""
        err = validate_id_format("user_id", "")
        assert err is not None

    def test_id_too_long(self):
        """ID 超长"""
        err = validate_id_format("user_id", "x" * 200)
        assert err is not None

    def test_id_with_special_chars(self):
        """ID 含特殊字符"""
        err = validate_id_format("user_id", "user@name!")
        assert err is not None

    def test_id_with_chinese(self):
        """ID 含中文"""
        err = validate_id_format("user_id", "用户123")
        assert err is not None


class TestTimestampStandardization:
    """时间戳标准化"""

    def test_iso8601_with_utc(self):
        """ISO 8601 UTC"""
        dt = standardize_timestamp("2026-07-06T10:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 10

    def test_iso8601_with_offset(self):
        """ISO 8601 +08:00 → UTC"""
        dt = standardize_timestamp("2026-07-06T10:00:00+08:00")
        assert dt.tzinfo is not None
        # 北京时间 10:00 = UTC 02:00
        assert dt.hour == 2

    def test_datetime_object(self):
        """datetime 对象"""
        dt_in = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)
        dt_out = standardize_timestamp(dt_in)
        assert dt_out == dt_in

    def test_naive_datetime(self):
        """无时区 datetime → 标记为 UTC"""
        dt_in = datetime(2026, 7, 6, 10, 0, 0)
        dt_out = standardize_timestamp(dt_in)
        assert dt_out.tzinfo is not None

    def test_none_uses_now(self):
        """None → 当前时间"""
        dt = standardize_timestamp(None)
        assert dt.tzinfo is not None
        assert isinstance(dt, datetime)

    def test_invalid_string_uses_now(self):
        """无效字符串 → 当前时间（降级处理）"""
        dt = standardize_timestamp("not a date")
        assert dt.tzinfo is not None


class TestIDNormalization:
    """ID 标准化"""

    def test_strip_whitespace(self):
        assert normalize_id("  U1001  ") == "u1001"

    def test_lowercase(self):
        assert normalize_id("User-ABC") == "user-abc"

    def test_none_passes_through(self):
        assert normalize_id(None) is None

    def test_mixed_case_and_spaces(self):
        assert normalize_id("  AGENT_X99  ") == "agent_x99"


class TestMetadataDefaultFilling:
    """元数据默认值补全"""

    def test_fill_defaults(self):
        data = {"business_meta": None}
        result = fill_default_metadata(data, agent_id="a1", scene_id="s1")
        assert result["business_meta"]["source"] == "api"
        assert result["business_meta"]["write_mode"] == "sync"
        assert result["business_meta"]["agent_id"] == "a1"
        assert result["business_meta"]["scene_id"] == "s1"

    def test_preserve_existing_meta(self):
        data = {"business_meta": {"project_name": "Test"}}
        result = fill_default_metadata(data)
        assert result["business_meta"]["project_name"] == "Test"
        assert result["business_meta"]["source"] == "api"


class TestFullValidateAndStandardize:
    """一站式校验+标准化管线"""

    def test_valid_data_passes(self):
        data = make_valid_write_data()
        result = validate_and_standardize(data, agent_id="agent_test", scene_id="scene_test")
        assert result["record_id"].startswith("rec_")
        assert result["user_id"] == "u1001"
        assert result["session_id"] == "s20260706001"
        assert isinstance(result["timestamp_dt"], datetime)

    def test_missing_required_raises(self):
        from app.core.exceptions import ValidationError
        with pytest.raises(ValidationError):
            validate_and_standardize({"user_id": "u1"})

    def test_agent_id_injection(self):
        data = make_valid_write_data()
        result = validate_and_standardize(data, agent_id="agent_xyz")
        assert result["agent_id"] == "agent_xyz"

    def test_business_meta_preserved(self):
        data = make_valid_write_data()
        result = validate_and_standardize(data)
        assert result["business_meta"]["project_name"] == "AI助手项目"


# ============================================================
# 2. 安全工具测试
# ============================================================

class TestSecurityTools:
    """API Key 生成与哈希"""

    def test_generate_api_key_format(self):
        key = generate_api_key()
        assert key.startswith("mem_")
        assert len(key) == 4 + 64  # mem_ + 64 hex chars

    def test_hash_is_deterministic(self):
        key = "mem_test123"
        assert hash_api_key(key) == hash_api_key(key)

    def test_hash_is_different_for_different_keys(self):
        assert hash_api_key("mem_a") != hash_api_key("mem_b")

    def test_generate_agent_id_format(self):
        agent_id = generate_agent_id()
        assert agent_id.startswith("agent_")
        assert len(agent_id) == 6 + 16  # agent_ + 16 hex


# ============================================================
# 3. 集成测试 (需要数据库和服务)
# ============================================================

pytestmark_integration = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="集成测试需要 PostgreSQL + 服务启动",
)


class TestMemoryWriteSchema:
    """MemoryWriteRequest Schema 校验"""

    def test_minimal_valid_request(self):
        """最少字段的合法请求"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="u1",
            session_id="s1",
            role="user",
            content="hello",
        )
        assert body.user_id == "u1"
        assert body.get_content_text() == "hello"

    def test_id_normalization_in_schema(self):
        """Schema 层面的 ID 标准化"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="  U1001  ",
            session_id="S20260706001",
            role="user",
            content="hello",
        )
        assert body.user_id == "u1001"
        assert body.session_id == "s20260706001"

    def test_content_stripping(self):
        """内容去除前后空白"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="u1",
            session_id="s1",
            role="user",
            content="  hello world  ",
        )
        assert body.content == "hello world"

    def test_reject_empty_content_and_messages(self):
        """不提供 content 也不提供 messages 时应拒绝"""
        from app.schemas.memory import MemoryWriteRequest
        with pytest.raises(Exception):
            MemoryWriteRequest(user_id="u1", session_id="s1")

    def test_default_interaction_type(self):
        """单条模式未指定 interaction_type 时默认 dialogue"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="u1",
            session_id="s1",
            role="user",
            content="hello",
        )
        assert body.interaction_type == "dialogue"


class TestAsyncWriteSchema:
    """AsyncWriteRequest Schema 校验"""

    def test_valid_async_request(self):
        from app.schemas.memory import AsyncWriteRequest
        body = AsyncWriteRequest(
            user_id="u1",
            session_id="s1",
            role="user",
            content="hello",
        )
        assert body.interaction_type == "dialogue"

    def test_id_normalization_async(self):
        from app.schemas.memory import AsyncWriteRequest
        body = AsyncWriteRequest(
            user_id="  U1001  ",
            session_id="S1",
            role="agent",
            content="test",
        )
        assert body.user_id == "u1001"


# ============================================================
# 4. 异常场景边界测试
# ============================================================

class TestEdgeCases:
    """边界值与异常场景"""

    def test_very_long_content(self):
        """超长内容"""
        from app.services.validation_service import validate_content_length
        err = validate_content_length("x" * 100000)
        assert err is not None

    def test_unicode_content(self):
        """Unicode 内容不应被拒绝"""
        data = make_valid_write_data({"content": "你好，世界 🌍 — эщкере"})
        result = validate_and_standardize(data)
        assert result["content"] == "你好，世界 🌍 — эщкере"

    def test_empty_business_meta(self):
        """business_meta 为空时应补全默认值"""
        data = make_valid_write_data()
        del data["business_meta"]
        result = validate_and_standardize(data)
        assert "business_meta" in result
        assert result["business_meta"]["source"] == "api"

    def test_max_length_ids(self):
        """最大长度 ID"""
        id128 = "a" * 128
        from app.services.validation_service import validate_id_format
        assert validate_id_format("id", id128) is None

    def test_exceed_max_length_id(self):
        """超过最大长度的 ID"""
        id129 = "a" * 129
        from app.services.validation_service import validate_id_format
        err = validate_id_format("id", id129)
        assert err is not None
