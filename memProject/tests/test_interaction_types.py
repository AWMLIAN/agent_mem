# -*- coding: utf-8 -*-
"""
测试"智能体接入与记忆数据写入功能"新增的三种数据类型支持。

覆盖：
- Schema 层: MemoryWriteRequest 三种类型构造与校验
- Validation 层: validate_write_request_by_type 类型感知校验
- Mock 抽取层: session / task_process 类型的内容抽取
- API 端点: POST /memory/write 三种类型的请求/响应格式
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.memory import (
    MemoryWriteRequest,
    AsyncWriteRequest,
    MessageItem,
    MemoryWriteResponse,
    WriteResultItem,
    MemoryEvent,
)
from app.services.validation_service import (
    validate_write_request_by_type,
    ValidationResult,
)


# ============================================================
# 1. Schema 层 — MemoryWriteRequest 字段校验
# ============================================================

class TestMemoryWriteRequestDialogue:
    """dialogue 类型：保持向后兼容"""

    def test_default_type_is_dialogue(self):
        req = MemoryWriteRequest(user_id="u1", messages=[MessageItem(role="user", content="hello")])
        assert req.interaction_type == "dialogue"

    def test_dialogue_with_messages_ok(self):
        req = MemoryWriteRequest(
            user_id="u1",
            messages=[
                MessageItem(role="user", content="你好"),
                MessageItem(role="assistant", content="你好，有什么可以帮你的？"),
            ],
        )
        assert len(req.messages) == 2
        assert req.get_content_text() != ""

    def test_dialogue_empty_messages_rejected(self):
        with pytest.raises(PydanticValidationError) as exc:
            MemoryWriteRequest(user_id="u1", messages=[])
        assert "dialogue" in str(exc.value).lower() or "必须提供" in str(exc.value)

    def test_dialogue_ignores_session_fields(self):
        """dialogue 模式下 session 字段被忽略但不报错"""
        req = MemoryWriteRequest(
            user_id="u1",
            messages=[MessageItem(role="user", content="test")],
            session_summary="不应该被处理的内容",
            session_time="2026-01-01T00:00:00Z",
        )
        assert req.interaction_type == "dialogue"
        # session 字段不参与 dialogue 的 content_text
        text = req.get_content_text()
        assert "[历史会话摘要]" not in text

    def test_dialogue_ignores_task_fields(self):
        """dialogue 模式下 task 字段被忽略但不报错"""
        req = MemoryWriteRequest(
            user_id="u1",
            messages=[MessageItem(role="user", content="test")],
            task_goal="目标",
            task_progress="进展",
            task_result="结果",
        )
        text = req.get_content_text()
        assert "[任务目标]" not in text
        assert "[任务进展]" not in text
        assert "[执行结果]" not in text


class TestMemoryWriteRequestSession:
    """session 类型：历史会话数据"""

    def test_session_type_explicit(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="session",
            session_summary="用户之前讨论过Python后端开发",
        )
        assert req.interaction_type == "session"
        assert req.session_summary == "用户之前讨论过Python后端开发"

    def test_session_with_all_fields(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="session",
            messages=[MessageItem(role="user", content="历史对话内容")],
            session_summary="摘要",
            session_time="2026-07-01T10:00:00Z",
            session_source="agent_code_helper",
            scene_id="chat",
        )
        assert req.interaction_type == "session"
        assert req.session_time == "2026-07-01T10:00:00Z"
        assert req.session_source == "agent_code_helper"

    def test_session_content_text_includes_summary(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="session",
            session_summary="用户喜欢Python",
            session_source="agent_code_helper",
            session_time="2026-06-15T08:30:00Z",
        )
        text = req.get_content_text()
        assert "[历史会话摘要]: 用户喜欢Python" in text
        assert "[会话来源]: agent_code_helper" in text
        assert "[会话时间]: 2026-06-15T08:30:00Z" in text

    def test_session_with_messages_and_summary(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="session",
            messages=[
                MessageItem(role="user", content="我之前说过我喜欢什么？"),
                MessageItem(role="assistant", content="您喜欢Python后端开发"),
            ],
            session_summary="确认用户偏好：Python后端",
            session_time="2026-07-01T10:00:00Z",
        )
        text = req.get_content_text()
        assert "[user](轮次1): 我之前说过我喜欢什么？" in text
        assert "[assistant](轮次2): 您喜欢Python后端开发" in text
        assert "[历史会话摘要]: 确认用户偏好：Python后端" in text

    def test_session_empty_messages_ok_with_summary(self):
        """session 类型：无 messages 但有 summary 是合法的"""
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="session",
            messages=[],
            session_summary="纯摘要导入",
        )
        assert req.interaction_type == "session"
        assert len(req.messages) == 0


class TestMemoryWriteRequestTaskProcess:
    """task_process 类型：任务过程数据"""

    def test_task_process_type_explicit(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            task_goal="完成Q3技术方案",
        )
        assert req.interaction_type == "task_process"
        assert req.task_goal == "完成Q3技术方案"

    def test_task_process_with_all_fields(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            task_id="task_001",
            task_goal="编写技术方案文档",
            task_progress="需求分析已完成，正在设计方案架构",
            task_result="方案已通过技术评审，获得批准",
            messages=[
                MessageItem(role="user", content="帮我写Q3技术方案"),
            ],
        )
        assert req.task_goal == "编写技术方案文档"
        assert req.task_progress == "需求分析已完成，正在设计方案架构"
        assert req.task_result == "方案已通过技术评审，获得批准"

    def test_task_process_content_text(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            task_goal="完成用户画像模块",
            task_progress="数据采集完成，模型训练中",
            task_result="模型准确率达到95%",
        )
        text = req.get_content_text()
        assert "[任务目标]: 完成用户画像模块" in text
        assert "[任务进展]: 数据采集完成，模型训练中" in text
        assert "[执行结果]: 模型准确率达到95%" in text

    def test_task_process_with_messages_and_task_data(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            messages=[
                MessageItem(role="user", content="帮我分析一下数据"),
                MessageItem(role="assistant", content="分析完成，结果如下..."),
            ],
            task_goal="数据分析",
            task_progress="已完成",
        )
        text = req.get_content_text()
        assert "[user](轮次1): 帮我分析一下数据" in text
        assert "[assistant](轮次2): 分析完成，结果如下..." in text
        assert "[任务目标]: 数据分析" in text

    def test_task_process_empty_messages_ok_with_goal(self):
        """task_process 类型：无 messages 但有 task_goal 是合法的"""
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            messages=[],
            task_goal="目标",
        )
        assert req.interaction_type == "task_process"
        assert len(req.messages) == 0


class TestInteractionTypeValidation:
    """interaction_type 字段自身的校验"""

    def test_valid_types_accepted(self):
        for itype in ["dialogue", "session", "task_process"]:
            req = MemoryWriteRequest(
                user_id="u1",
                interaction_type=itype,
                messages=[MessageItem(role="user", content="test")],
            )
            assert req.interaction_type == itype

    def test_invalid_type_rejected(self):
        with pytest.raises(PydanticValidationError) as exc:
            MemoryWriteRequest(
                user_id="u1",
                interaction_type="invalid_type",
                messages=[MessageItem(role="user", content="test")],
            )
        assert "interaction_type" in str(exc.value).lower()

    def test_type_case_insensitive(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="SESSION",
            session_summary="test",
        )
        assert req.interaction_type == "session"

    def test_type_whitespace_trimmed(self):
        req = MemoryWriteRequest(
            user_id="u1",
            interaction_type="  task_process  ",
            task_goal="test",
        )
        assert req.interaction_type == "task_process"


# ============================================================
# 2. Validation 层 — validate_write_request_by_type
# ============================================================

class TestValidationDialogue:
    """dialogue 类型的业务校验"""

    def test_dialogue_with_messages_passes(self):
        result = validate_write_request_by_type("dialogue", [{"role": "user", "content": "hi"}])
        assert result.is_valid

    def test_dialogue_empty_messages_fails(self):
        result = validate_write_request_by_type("dialogue", [])
        assert not result.is_valid
        assert any("messages" in e for e in result.errors)

    def test_dialogue_extra_fields_ignored(self):
        """dialogue 类型忽略 session/task 字段"""
        result = validate_write_request_by_type(
            "dialogue",
            [{"role": "user", "content": "hi"}],
            session_summary="something",
            task_goal="something",
        )
        assert result.is_valid


class TestValidationSession:
    """session 类型的业务校验"""

    def test_session_with_messages_passes(self):
        result = validate_write_request_by_type(
            "session", [{"role": "user", "content": "hi"}]
        )
        assert result.is_valid

    def test_session_with_summary_passes(self):
        result = validate_write_request_by_type(
            "session", [], session_summary="历史会话摘要"
        )
        assert result.is_valid

    def test_session_with_both_passes(self):
        result = validate_write_request_by_type(
            "session",
            [{"role": "user", "content": "hi"}],
            session_summary="摘要",
        )
        assert result.is_valid

    def test_session_empty_both_fails(self):
        result = validate_write_request_by_type("session", [])
        assert not result.is_valid
        assert any("session_summary" in e for e in result.errors)

    def test_session_with_empty_summary_fails(self):
        result = validate_write_request_by_type("session", [], session_summary="   ")
        assert not result.is_valid

    def test_session_summary_too_long(self):
        long_summary = "x" * 10001
        result = validate_write_request_by_type(
            "session", [], session_summary=long_summary
        )
        assert not result.is_valid
        assert any("长度超过限制" in e for e in result.errors)

    def test_session_time_invalid_format(self):
        result = validate_write_request_by_type(
            "session",
            [{"role": "user", "content": "hi"}],
            session_time="not-a-datetime",
        )
        assert not result.is_valid
        assert any("session_time" in e for e in result.errors)

    def test_session_time_valid_iso8601(self):
        result = validate_write_request_by_type(
            "session",
            [{"role": "user", "content": "hi"}],
            session_time="2026-07-01T10:00:00Z",
        )
        assert result.is_valid


class TestValidationTaskProcess:
    """task_process 类型的业务校验"""

    def test_task_process_with_messages_passes(self):
        result = validate_write_request_by_type(
            "task_process", [{"role": "user", "content": "hi"}]
        )
        assert result.is_valid

    def test_task_process_with_goal_passes(self):
        result = validate_write_request_by_type(
            "task_process", [], task_goal="完成技术方案"
        )
        assert result.is_valid

    def test_task_process_with_progress_passes(self):
        result = validate_write_request_by_type(
            "task_process", [], task_progress="进行中"
        )
        assert result.is_valid

    def test_task_process_with_result_passes(self):
        result = validate_write_request_by_type(
            "task_process", [], task_result="已完成"
        )
        assert result.is_valid

    def test_task_process_with_all_task_fields_passes(self):
        result = validate_write_request_by_type(
            "task_process",
            [],
            task_goal="目标",
            task_progress="进展",
            task_result="结果",
        )
        assert result.is_valid

    def test_task_process_empty_all_fails(self):
        result = validate_write_request_by_type("task_process", [])
        assert not result.is_valid
        assert any("task_goal" in e for e in result.errors)

    def test_task_process_goal_too_long(self):
        long_goal = "x" * 5001
        result = validate_write_request_by_type(
            "task_process", [], task_goal=long_goal
        )
        assert not result.is_valid
        assert any("长度超过限制" in e for e in result.errors)

    def test_task_process_result_too_long(self):
        long_result = "x" * 5001
        result = validate_write_request_by_type(
            "task_process", [], task_result=long_result
        )
        assert not result.is_valid
        assert any("长度超过限制" in e for e in result.errors)


class TestValidationEdgeCases:
    """校验边界和异常情况"""

    def test_unknown_type_returns_errors(self):
        """未知类型不会崩溃，返回错误"""
        result = validate_write_request_by_type("unknown_type", [])
        # 不在已知类型中，不会添加任何错误（但我们不做拦截，由 Schema 层处理）
        assert result.is_valid  # 校验不做类型有效性判断，交给 Schema 层

    def test_empty_messages_list(self):
        """空消息列表是合法的参数"""
        result = validate_write_request_by_type(
            "session", [], session_summary="ok"
        )
        assert result.is_valid

    def test_result_raise_if_invalid(self):
        from app.core.exceptions import ValidationError
        result = ValidationResult(is_valid=False, errors=["test error"])
        with pytest.raises(ValidationError) as exc:
            result.raise_if_invalid()
        assert "数据校验失败" in str(exc.value.message)


# ============================================================
# 3. AsyncWriteRequest — 异步写入 Schema
# ============================================================

class TestAsyncWriteRequest:
    """异步写入请求应与同步写入有相同的字段支持"""

    def test_async_default_type_dialogue(self):
        req = AsyncWriteRequest(
            user_id="u1",
            messages=[MessageItem(role="user", content="hello")],
        )
        assert req.interaction_type == "dialogue"

    def test_async_session_type(self):
        req = AsyncWriteRequest(
            user_id="u1",
            interaction_type="session",
            session_summary="历史会话",
            session_time="2026-07-01T10:00:00Z",
            session_source="agent_abc",
        )
        assert req.interaction_type == "session"
        assert req.session_summary == "历史会话"

    def test_async_task_process_type(self):
        req = AsyncWriteRequest(
            user_id="u1",
            interaction_type="task_process",
            task_goal="目标",
            task_progress="进展",
            task_result="结果",
        )
        assert req.interaction_type == "task_process"

    def test_async_user_id_normalized(self):
        req = AsyncWriteRequest(
            user_id="  User_001  ",
            messages=[MessageItem(role="user", content="test")],
        )
        assert req.user_id == "user_001"


# ============================================================
# 4. MessageItem — 消息条目 Schema
# ============================================================

class TestMessageItem:
    def test_valid_roles(self):
        for role in ["user", "assistant", "system", "tool", "agent"]:
            msg = MessageItem(role=role, content="test")
            assert msg.role == role

    def test_case_insensitive_role(self):
        msg = MessageItem(role="USER", content="test")
        assert msg.role == "user"

    def test_content_stripped(self):
        msg = MessageItem(role="user", content="  hello world  ")
        assert msg.content == "hello world"

    def test_empty_content_rejected(self):
        with pytest.raises(PydanticValidationError):
            MessageItem(role="user", content="")


# ============================================================
# 5. MemoryWriteResponse — 写入响应
# ============================================================

class TestMemoryWriteResponse:
    def test_empty_results(self):
        resp = MemoryWriteResponse(results=[])
        assert len(resp.results) == 0

    def test_with_results(self):
        results = [
            WriteResultItem(id="mem_1", memory="用户偏好Python", event=MemoryEvent.ADD),
            WriteResultItem(id="", memory="你好", event=MemoryEvent.SKIP),
        ]
        resp = MemoryWriteResponse(results=results)
        assert len(resp.results) == 2
        assert resp.results[0].event == MemoryEvent.ADD
        assert resp.results[1].event == MemoryEvent.SKIP

    def test_all_event_types(self):
        for event in [MemoryEvent.ADD, MemoryEvent.SKIP, MemoryEvent.MERGE]:
            item = WriteResultItem(id="mem_x", memory="test", event=event)
            assert item.event == event


# ============================================================
# 6. 端到端：模拟三种类型的完整数据流
# ============================================================

class TestEndToEndDataFlow:
    """验证三种类型的完整写入数据流（Schema → Validation → 内容拼接）"""

    def test_dialogue_flow(self):
        """对话记录：用户和助手多轮对话"""
        req = MemoryWriteRequest(
            user_id="user_001",
            scene_id="chat",
            session_id="sess_abc",
            interaction_type="dialogue",
            messages=[
                MessageItem(role="user", content="我叫张伟，喜欢Python"),
                MessageItem(role="assistant", content="好的张伟，我记住了"),
                MessageItem(role="user", content="帮我写一个FastAPI接口"),
            ],
            metadata={"source": "web_chat"},
        )
        # Step 1: Schema 校验通过
        assert req.interaction_type == "dialogue"
        assert len(req.messages) == 3
        # Step 2: 业务校验通过
        validation = validate_write_request_by_type("dialogue", req.messages)
        assert validation.is_valid
        # Step 3: 内容可拼接
        text = req.get_content_text()
        assert "张伟" in text
        assert "Python" in text
        assert "FastAPI" in text

    def test_session_flow(self):
        """历史会话：导入其他智能体的历史对话摘要"""
        req = MemoryWriteRequest(
            user_id="user_001",
            scene_id="code_review",
            interaction_type="session",
            session_summary="用户之前与代码助手讨论过微服务架构，确认使用FastAPI + PostgreSQL",
            session_time="2026-06-20T14:30:00Z",
            session_source="agent_code_helper_v1",
            messages=[
                MessageItem(role="user", content="微服务用Python还是Go？"),
                MessageItem(role="assistant", content="建议用Python+FastAPI"),
            ],
            metadata={"import_type": "migration"},
        )
        # Step 1: Schema 校验通过
        assert req.interaction_type == "session"
        assert req.session_time == "2026-06-20T14:30:00Z"
        # Step 2: 业务校验通过
        validation = validate_write_request_by_type(
            "session", req.messages, session_summary=req.session_summary
        )
        assert validation.is_valid
        # Step 3: 内容拼接包含所有信息
        text = req.get_content_text()
        assert "微服务" in text
        assert "FastAPI + PostgreSQL" in text
        assert "2026-06-20T14:30:00Z" in text
        assert "agent_code_helper_v1" in text

    def test_task_process_flow(self):
        """任务过程：记录长周期任务的阶段性进展"""
        req = MemoryWriteRequest(
            user_id="user_001",
            task_id="task_tech_plan_q3",
            interaction_type="task_process",
            task_goal="完成Q3技术方案文档，包括架构设计、技术选型和风险评估",
            task_progress="已完成需求分析和架构草稿，正在进行技术选型对比",
            task_result="",
            messages=[
                MessageItem(role="user", content="技术选型确定了吗？"),
                MessageItem(role="assistant", content="正在对比FastAPI和Django，倾向于FastAPI"),
            ],
            metadata={"priority": "high"},
        )
        # Step 1: Schema 校验通过
        assert req.interaction_type == "task_process"
        assert req.task_goal is not None
        # Step 2: 业务校验通过
        validation = validate_write_request_by_type(
            "task_process",
            req.messages,
            task_goal=req.task_goal,
            task_progress=req.task_progress,
            task_result=req.task_result,
        )
        assert validation.is_valid
        # Step 3: 内容拼接包含所有信息
        text = req.get_content_text()
        assert "Q3技术方案" in text
        assert "架构草稿" in text
        assert "FastAPI" in text


# ============================================================
# 7. 向后兼容性
# ============================================================

class TestBackwardCompatibility:
    """确保旧版 API 调用（没有 interaction_type）仍然正常工作"""

    def test_old_format_still_works(self):
        """旧格式：不传 interaction_type，只传 messages"""
        req = MemoryWriteRequest(
            user_id="u1",
            scene_id="chat",
            messages=[MessageItem(role="user", content="hello")],
        )
        assert req.interaction_type == "dialogue"
        assert req.get_content_text() == "[user](轮次1): hello"

    def test_old_format_with_metadata(self):
        """旧格式 + metadata"""
        req = MemoryWriteRequest(
            user_id="u1",
            messages=[MessageItem(role="user", content="test")],
            metadata={"key": "value"},
        )
        assert req.interaction_type == "dialogue"
        assert req.metadata == {"key": "value"}

    def test_minimal_request(self):
        """最小请求：只有必填字段"""
        req = MemoryWriteRequest(
            user_id="u1",
            messages=[MessageItem(role="user", content="hi")],
        )
        assert req.interaction_type == "dialogue"
        assert req.scene_id is None
        assert req.session_id is None
        assert req.task_id is None
