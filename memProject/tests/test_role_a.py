# -*- coding: utf-8 -*-
"""
角色A 功能测试 — 智能体接入与记忆数据写入。

对齐前端对接文档 + 核心改动文档。

测试覆盖：
1. Schema 校验（messages 数组格式）
2. 数据校验与标准化
3. Mock 记忆抽取规则
4. 安全工具（API Key 生成/哈希）
5. 统一响应格式
6. AUTH_ENABLED 开关
7. 边界值与异常场景

运行: pytest tests/test_role_a.py -v
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.security import generate_api_key, hash_api_key, generate_agent_id
from app.services.validation_service import (
    validate_required_fields,
    validate_field_types,
    validate_id_format,
    standardize_timestamp,
    normalize_id,
    fill_default_metadata,
    validate_and_standardize,
)

# ============================================================
# 1. Schema 校验 — messages 数组格式
# ============================================================

class TestMemoryWriteSchema:
    """MemoryWriteRequest — messages 数组为 Primary 格式"""

    def test_valid_messages_array(self):
        """标准 messages 数组格式应通过"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="user_001",
            scene_id="chat",
            task_id="task_001",
            messages=[
                {"role": "user", "content": "我叫张伟，喜欢Python后端开发"},
            ],
        )
        assert body.user_id == "user_001"
        assert len(body.messages) == 1
        assert body.messages[0].role == "user"
        assert body.get_content_text() != ""

    def test_multi_turn_messages(self):
        """多轮对话 messages 数组"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="user_001",
            messages=[
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！有什么可以帮你的？"},
                {"role": "user", "content": "我叫张伟"},
            ],
        )
        assert len(body.messages) == 3
        assert body.get_last_role() == "user"
        assert body.get_last_content() == "我叫张伟"

    def test_empty_messages_rejected(self):
        """空 messages 数组应拒绝"""
        from app.schemas.memory import MemoryWriteRequest
        with pytest.raises(Exception):
            MemoryWriteRequest(user_id="u1", messages=[])

    def test_user_id_normalized(self):
        """user_id 自动标准化（去空格/小写）"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="  User_001  ",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert body.user_id == "user_001"

    def test_scene_id_optional(self):
        """scene_id 可选"""
        from app.schemas.memory import MemoryWriteRequest
        body = MemoryWriteRequest(
            user_id="u1",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert body.scene_id is None

    def test_invalid_role_rejected(self):
        """非法的 role 值应拒绝"""
        from app.schemas.memory import MessageItem
        with pytest.raises(Exception):
            MessageItem(role="hacker", content="test")

    def test_known_roles_accepted(self):
        """所有合法 role 值应通过"""
        from app.schemas.memory import MessageItem
        for role in ["user", "assistant", "system", "tool", "agent"]:
            msg = MessageItem(role=role, content="test")
            assert msg.role == role

    def test_content_stripped(self):
        """content 自动去除前后空白"""
        from app.schemas.memory import MessageItem
        msg = MessageItem(role="user", content="  hello world  ")
        assert msg.content == "hello world"

    def test_empty_content_rejected(self):
        """空 content 应拒绝"""
        from app.schemas.memory import MessageItem
        with pytest.raises(Exception):
            MessageItem(role="user", content="")

    def test_max_messages_enforced(self):
        """messages 数组最大 100 条"""
        from app.schemas.memory import MemoryWriteRequest
        with pytest.raises(Exception):
            MemoryWriteRequest(
                user_id="u1",
                messages=[{"role": "user", "content": "x"}] * 101,
            )


# ============================================================
# 3. 数据校验服务
# ============================================================

class TestValidationRequiredFields:
    """必填字段校验"""

    def test_all_required_present(self):
        result = validate_required_fields({"user_id": "u1", "content": "hello", "session_id": "s1"})
        assert result.is_valid

    def test_missing_user_id(self):
        result = validate_required_fields({"content": "hello", "session_id": "s1"})
        assert not result.is_valid

    def test_missing_content(self):
        result = validate_required_fields({"user_id": "u1", "session_id": "s1"})
        assert not result.is_valid

    def test_empty_strings(self):
        result = validate_required_fields({"user_id": "  ", "content": "hello", "session_id": "s1"})
        assert not result.is_valid

    def test_all_missing(self):
        result = validate_required_fields({})
        assert not result.is_valid
        assert len(result.errors) == 3


class TestIDNormalization:
    """ID 标准化"""

    def test_strip_whitespace(self):
        assert normalize_id("  U1001  ") == "u1001"

    def test_lowercase(self):
        assert normalize_id("User-ABC") == "user-abc"

    def test_none_passes_through(self):
        assert normalize_id(None) is None


class TestTimestampStandardization:
    """时间标准化"""

    def test_iso8601_utc(self):
        from datetime import datetime
        dt = standardize_timestamp("2026-07-06T10:00:00Z")
        assert dt.tzinfo is not None
        assert isinstance(dt, datetime)

    def test_none_uses_now(self):
        from datetime import datetime
        dt = standardize_timestamp(None)
        assert isinstance(dt, datetime)

    def test_invalid_fallback(self):
        """无效字符串降级为当前时间"""
        from datetime import datetime
        dt = standardize_timestamp("not a date")
        assert isinstance(dt, datetime)


class TestMetadataDefaults:
    """元数据默认值补全"""

    def test_fill_defaults(self):
        data = {"business_meta": None}
        result = fill_default_metadata(data, agent_id="a1", scene_id="s1")
        assert result["business_meta"]["source"] == "api"
        assert result["business_meta"]["agent_id"] == "a1"

    def test_preserve_existing(self):
        data = {"business_meta": {"project_name": "Test"}}
        result = fill_default_metadata(data)
        assert result["business_meta"]["project_name"] == "Test"


class TestFullValidationPipeline:
    """一站式校验管线"""

    def test_valid_passes(self):
        from datetime import datetime
        data = {
            "user_id": "u1001",
            "session_id": "s1",
            "content": "test content",
            "role": "user",
            "timestamp": "2026-07-06T10:00:00Z",
        }
        result = validate_and_standardize(data, agent_id="agent_001")
        assert result["record_id"].startswith("rec_")
        assert isinstance(result["timestamp_dt"], datetime)

    def test_missing_required_raises(self):
        from app.core.exceptions import ValidationError
        with pytest.raises(ValidationError):
            validate_and_standardize({"user_id": "u1"})


# ============================================================
# 4. 安全工具
# ============================================================

class TestSecurityTools:
    """API Key 生成与哈希"""

    def test_api_key_format(self):
        key = generate_api_key()
        assert key.startswith("mem_")
        assert len(key) == 4 + 64

    def test_hash_deterministic(self):
        assert hash_api_key("mem_test") == hash_api_key("mem_test")

    def test_hash_different(self):
        assert hash_api_key("mem_a") != hash_api_key("mem_b")

    def test_agent_id_format(self):
        aid = generate_agent_id()
        assert aid.startswith("agent_")
        assert len(aid) == 6 + 16


# ============================================================
# 5. 统一响应格式
# ============================================================

class TestUnifiedResponse:
    """统一响应格式 ok()"""

    def test_ok_basic(self):
        from app.schemas.common import ok
        resp = ok({"name": "test"})
        assert resp["code"] == 0
        assert resp["message"] == "ok"
        assert resp["data"] == {"name": "test"}

    def test_ok_with_message(self):
        from app.schemas.common import ok
        resp = ok({"id": 1}, "创建成功")
        assert resp["code"] == 0
        assert resp["message"] == "创建成功"

    def test_ok_none_data(self):
        from app.schemas.common import ok
        resp = ok(None)
        assert resp["code"] == 0
        assert resp["data"] is None


# ============================================================
# 6. AUTH_ENABLED 开关
# ============================================================

class TestAuthConfig:
    """鉴权开关配置"""

    def test_auth_disabled_by_default(self):
        """默认 AUTH_ENABLED=false（开发阶段）"""
        from app.core.config import get_settings
        settings = get_settings()
        # 开发阶段默认不启用鉴权
        assert settings.auth.enabled == False

    def test_auth_config_exists(self):
        """AuthConfig 包含 enabled 字段"""
        from app.core.config import AuthConfig
        cfg = AuthConfig()
        assert hasattr(cfg, "enabled")


# ============================================================
# 7. 边界值与异常场景
# ============================================================

class TestEdgeCases:
    """边界值"""

    def test_unicode_content(self):
        data = {
            "user_id": "u1", "session_id": "s1", "content": "你好世界 🌍",
            "role": "user",
        }
        result = validate_and_standardize(data)
        assert result["content"] == "你好世界 🌍"

    def test_max_length_id(self):
        id128 = "a" * 128
        assert validate_id_format("id", id128) is None

    def test_exceed_max_length_id(self):
        err = validate_id_format("id", "a" * 129)
        assert err is not None

    def test_id_with_special_chars(self):
        err = validate_id_format("user_id", "user@name!")
        assert err is not None

    def test_very_long_content(self):
        from app.services.validation_service import validate_content_length
        err = validate_content_length("x" * 100000)
        assert err is not None

    def test_empty_business_meta_completion(self):
        data = {
            "user_id": "u1", "session_id": "s1", "content": "test",
        }
        result = validate_and_standardize(data)
        assert "business_meta" in result
        assert result["business_meta"]["source"] == "api"


# ============================================================
# 8. WriteResultItem Schema
# ============================================================

class TestWriteResultSchema:
    """写入结果 Schema"""

    def test_result_item(self):
        from app.schemas.memory import WriteResultItem, MemoryEvent
        item = WriteResultItem(id="mem_abc", memory="用户偏好Python", event=MemoryEvent.ADD)
        assert item.id == "mem_abc"
        assert item.event == MemoryEvent.ADD

    def test_all_events(self):
        from app.schemas.memory import MemoryEvent
        events = [e.value for e in MemoryEvent]
        assert "ADD" in events
        assert "SKIP" in events
        assert "MERGE" in events

    def test_response_empty_results(self):
        from app.schemas.memory import MemoryWriteResponse
        resp = MemoryWriteResponse(results=[])
        assert resp.results == []
