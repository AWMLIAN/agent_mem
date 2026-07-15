# -*- coding: utf-8 -*-
"""
记忆生成流水线 — 单元测试（Mock 外部依赖）。

测试：LLM Client、Embedding Client、MemoryExtractor、MemoryGenerator、Dedup Service
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm_client import LLMClient
from app.services.embedding_client import EmbeddingClient
from app.services.memory_extractor import (
    MemoryExtractor, KeyFactExtractor, TaskStateExtractor, DecisionExtractor,
    PreferenceExtractor, ProcessExtractor, FeedbackExtractor,
    ExtractionResult, KeyFactsResult, TaskStateResult, DecisionResult,
    PreferenceResult, ProcessResult, FeedbackResult,
)
from app.services.memory_generator import MemoryGenerator, MemoryCandidate
from app.services.memory_dedup import (
    DedupService, DedupResult, DedupAction, SimilarMemory,
)
from app.services.memory_quality import (
    judge_extraction_value,
    verify_candidate_quality,
    verify_candidates_batch,
    QualityReport,
    ValueJudgment,
)


# ============================================================
# LLM Client Tests
# ============================================================

class TestLLMClient:
    """测试 DeepSeek LLM 客户端"""

    @pytest.fixture
    def llm(self):
        return LLMClient(api_key="test-key", base_url="https://test.api.com/v1", model="test-model")

    @pytest.mark.asyncio
    async def test_chat_completion_success(self, llm):
        """测试正常聊天请求"""
        mock_response = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"total_tokens": 10},
        }
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value=mock_response),
            raise_for_status=MagicMock(),
        ))
        llm._http = mock_http

        result = await llm.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_extract_structured(self, llm):
        """测试结构化 JSON 抽取"""
        llm.chat_completion = AsyncMock(return_value='{"name": "test", "value": 42}')
        result = await llm.extract_structured(
            system_prompt="Test prompt",
            user_content="Test content",
            output_schema={"type": "object"},
        )
        assert result == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_extract_structured_json_recovery(self, llm):
        """测试 JSON 解析失败的 regex 恢复"""
        llm.chat_completion = AsyncMock(return_value='Prefix text {"name": "recovered"} suffix')
        result = await llm.extract_structured(
            system_prompt="Test",
            user_content="Test",
            output_schema={"type": "object"},
        )
        assert result == {"name": "recovered"}

    @pytest.mark.asyncio
    async def test_extract_structured_complete_failure(self, llm):
        """测试无法解析时抛异常"""
        from app.core.exceptions import LLMServiceError
        llm.chat_completion = AsyncMock(return_value="No JSON here at all")
        with pytest.raises(LLMServiceError):
            await llm.extract_structured(
                system_prompt="Test",
                user_content="Test",
                output_schema={"type": "object"},
            )


# ============================================================
# Embedding Client Tests
# ============================================================

class TestEmbeddingClient:
    """测试 SiliconFlow Embedding 客户端"""

    @pytest.fixture
    def emb(self):
        return EmbeddingClient(api_key="test-key", base_url="https://test.api.com/v1", model="test-model")

    @pytest.mark.asyncio
    async def test_embed_single(self, emb):
        """测试单文本嵌入"""
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "data": [{"embedding": [0.1] * 1024, "index": 0}],
            }),
            raise_for_status=MagicMock(),
        ))
        emb._http = mock_http

        result = await emb.embed_single("test text")
        assert len(result) == 1024
        assert result[0] == 0.1

    @pytest.mark.asyncio
    async def test_embed_batch_splitting(self, emb):
        """测试大批次自动拆分"""
        call_count = 0

        async def mock_post(url, json=None):
            nonlocal call_count
            call_count += 1
            texts = json.get("input", [])
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={
                    "data": [{"embedding": [0.5] * 1024, "index": i} for i in range(len(texts))],
                }),
                raise_for_status=MagicMock(),
            )

        mock_http = AsyncMock()
        mock_http.post = mock_post
        emb._http = mock_http

        # 发送 40 条文本（应拆分为 32 + 8）
        texts = ["text"] * 40
        results = await emb.embed_batch(texts)

        assert len(results) == 40
        assert call_count == 2  # 两次 API 调用


# ============================================================
# Memory Extractor Tests
# ============================================================

class TestMemoryExtractor:
    """测试记忆抽取器"""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock(spec=LLMClient)
        return llm

    @pytest.mark.asyncio
    async def test_key_fact_extraction(self, mock_llm):
        """测试关键事实抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "business_objects": [{"name": "ProjectX", "type": "project", "description": "主要项目"}],
            "constraints": [{"type": "temporal", "description": "下周五 deadline", "severity": "high"}],
            "confirmations": [{"item": "使用 FastAPI", "parties": ["dev"], "context": "技术选型会议"}],
        })

        extractor = KeyFactExtractor(mock_llm)
        result = await extractor.extract("我们决定在 ProjectX 上使用 FastAPI，deadline 是下周五")

        assert len(result.business_objects) == 1
        assert result.business_objects[0]["name"] == "ProjectX"
        assert len(result.constraints) == 1
        assert result.constraints[0]["severity"] == "high"
        assert len(result.confirmations) == 1

    @pytest.mark.asyncio
    async def test_task_state_extraction(self, mock_llm):
        """测试任务状态抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "current_progress": "API 开发阶段",
            "completed_items": [{"item": "数据库设计", "evidence": "已完成 ER 图"}],
            "pending_items": [{"item": "单元测试", "priority": "high"}],
        })

        extractor = TaskStateExtractor(mock_llm)
        result = await extractor.extract("API 开发进行中，数据库设计已完成")

        assert "API 开发阶段" in result.current_progress
        assert len(result.completed_items) == 1
        assert len(result.pending_items) == 1
        assert result.pending_items[0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_decision_extraction(self, mock_llm):
        """测试历史决策抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "confirmed_plans": [{"plan": "微服务架构", "alternatives": ["单体"], "decision_context": "架构评审"}],
            "selection_rationale": [{"reason": "可扩展性更好", "criteria": ["扩展性", "维护性"]}],
            "execution_results": [{"result": "部署成功", "outcome_type": "success"}],
        })

        extractor = DecisionExtractor(mock_llm)
        result = await extractor.extract("我们选择了微服务架构，因为可扩展性更好")

        assert len(result.confirmed_plans) == 1
        assert result.confirmed_plans[0]["plan"] == "微服务架构"
        assert len(result.selection_rationale) == 1
        assert len(result.execution_results) == 1

    @pytest.mark.asyncio
    async def test_memory_extractor_facade(self, mock_llm):
        """测试 MemoryExtractor facade 调度"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "business_objects": [],
            "constraints": [],
            "confirmations": [],
        })

        extractor = MemoryExtractor(mock_llm)
        result = await extractor.extract(
            text="test text",
            types=["key_fact"],
        )

        assert result.key_facts is not None
        assert result.task_state is None
        assert result.decisions is None

    @pytest.mark.asyncio
    async def test_extraction_result_to_dict(self):
        """测试 ExtractionResult.to_dict()"""
        result = ExtractionResult(
            key_facts=KeyFactsResult(
                business_objects=[{"name": "Test"}],
                constraints=[],
                confirmations=[],
            ),
            source_text="test",
        )
        d = result.to_dict()
        assert len(d["business_objects"]) == 1
        assert d["constraints"] == []
        assert d["current_progress"] == ""


# ============================================================
# Memory Generator Tests
# ============================================================

class TestMemoryGenerator:
    """测试记忆生成器"""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    @pytest.mark.asyncio
    async def test_generate_memories(self, mock_llm):
        """测试从抽取结果生成记忆"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "memories": [
                {
                    "content": "用户偏好使用 Python 进行开发",
                    "summary": "用户偏好 Python",
                    "key_points": ["偏好 Python", "主要开发语言"],
                    "memory_type": "preference",
                    "tags": ["python", "preference", "dev"],
                    "entities": ["Python"],
                    "importance": 0.8,
                    "confidence": 0.9,
                },
                {
                    "content": "ProjectX 的 deadline 是下周五",
                    "summary": "ProjectX deadline",
                    "key_points": ["deadline: 下周五"],
                    "memory_type": "constraint",
                    "tags": ["deadline", "ProjectX"],
                    "entities": ["ProjectX"],
                    "importance": 0.9,
                    "confidence": 1.0,
                },
            ]
        })

        extraction = ExtractionResult(
            key_facts=KeyFactsResult(
                business_objects=[{"name": "ProjectX", "type": "project", "description": ""}],
                constraints=[],
                confirmations=[{"item": "使用 Python", "parties": ["user"], "context": ""}],
            ),
            source_text="用户喜欢用 Python，ProjectX deadline 下周五",
        )

        generator = MemoryGenerator(mock_llm)
        candidates = await generator.generate(extraction)

        assert len(candidates) == 2
        assert candidates[0].memory_type == "preference"
        assert candidates[0].importance == 0.8
        assert candidates[1].memory_type == "constraint"
        assert "Python" in candidates[0].entities

    @pytest.mark.asyncio
    async def test_generate_empty_extraction(self, mock_llm):
        """测试空抽取结果"""
        extraction = ExtractionResult(source_text="hello")
        generator = MemoryGenerator(mock_llm)
        candidates = await generator.generate(extraction)
        assert len(candidates) == 0

    def test_memory_candidate_validation(self):
        """测试 MemoryCandidate 验证"""
        # 有效候选
        c = MemoryCandidate(
            content="测试记忆",
            summary="摘要",
            memory_type="fact",
            importance=0.7,
            confidence=0.8,
        )
        c.validate()
        assert c.memory_type == "fact"

        # 无效类型应回退
        c2 = MemoryCandidate(
            content="test",
            summary="s",
            memory_type="invalid_type",
        )
        c2.validate()
        assert c2.memory_type == "fact"

        # 值域裁剪
        c3 = MemoryCandidate(
            content="test",
            summary="s",
            importance=1.5,
            confidence=-0.5,
        )
        c3.validate()
        assert c3.importance == 1.0
        assert c3.confidence == 0.0


# ============================================================
# Dedup Service Tests
# ============================================================

class TestDedupService:
    """测试去重服务"""

    @pytest.fixture
    def mock_embedding(self):
        emb = MagicMock(spec=EmbeddingClient)
        emb.embed_single = AsyncMock(return_value=[0.1] * 1024)
        return emb

    @pytest.fixture
    def mock_qdrant(self):
        qdrant = MagicMock()
        qdrant.is_available = True
        qdrant.collection_name = "agent_mem_generation"
        return qdrant

    def test_decide_action_discard(self, mock_embedding, mock_qdrant):
        """高相似度 → DISCARD"""
        service = DedupService(mock_embedding, mock_qdrant)
        action = service._decide_action(
            vector_score=0.95,
            keyword_overlap=0.85,
            identity_match=True,
        )
        assert action == DedupAction.DISCARD

    def test_decide_action_update_existing(self, mock_embedding, mock_qdrant):
        """中等相似度 + identity match → UPDATE_EXISTING"""
        service = DedupService(mock_embedding, mock_qdrant)
        action = service._decide_action(
            vector_score=0.90,
            keyword_overlap=0.70,
            identity_match=True,
        )
        # composite = 0.5*0.90 + 0.3*0.70 + 0.2*1.0 = 0.45 + 0.21 + 0.20 = 0.86 ≥ 0.80
        assert action == DedupAction.UPDATE_EXISTING

    def test_decide_action_merge(self, mock_embedding, mock_qdrant):
        """中等相似度 + no identity → MERGE"""
        service = DedupService(mock_embedding, mock_qdrant)
        action = service._decide_action(
            vector_score=0.88,
            keyword_overlap=0.76,
            identity_match=False,
        )
        # composite = 0.5*0.88 + 0.3*0.76 + 0.2*0 = 0.44 + 0.228 = 0.668 ≥ 0.65
        assert action == DedupAction.MERGE

    def test_decide_action_keep_new(self, mock_embedding, mock_qdrant):
        """低相似度 → KEEP_NEW"""
        service = DedupService(mock_embedding, mock_qdrant)
        action = service._decide_action(
            vector_score=0.6,
            keyword_overlap=0.2,
            identity_match=False,
        )
        assert action == DedupAction.KEEP_NEW

    def test_compute_keyword_overlap(self, mock_embedding, mock_qdrant):
        """测试关键词 Jaccard 计算"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="使用 Python 和 FastAPI 开发",
            tags=["python", "fastapi"],
            entities=["Python", "FastAPI"],
        )
        existing = Memory(
            content="Python 开发项目使用 Django",
            tags=["python", "django"],
            entities=["Python", "Django"],
        )

        overlap = service._compute_keyword_overlap(candidate, existing)
        # 共有: python(英文) + Python(实体) → keywords 统一用小写处理
        assert overlap > 0.0
        assert overlap <= 1.0

    def test_check_identity_same_task(self, mock_embedding, mock_qdrant):
        """相同 task_id → identity match"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(content="test", entities=[])
        existing = Memory(task_id="task_001", content="test", entities=[])

        assert service._check_identity(candidate, existing, task_id="task_001")
        assert not service._check_identity(candidate, existing, task_id="task_002")

    def test_check_identity_entity_overlap(self, mock_embedding, mock_qdrant):
        """entities 重叠 >= 2 → identity match"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="test",
            entities=["Python", "FastAPI", "Qdrant"],
        )
        existing = Memory(
            content="test",
            entities=["Python", "FastAPI", "Django"],
            task_id=None,
        )

        assert service._check_identity(candidate, existing)
        assert not service._check_identity(
            MemoryCandidate(content="t", entities=["X"]),
            Memory(content="t", entities=["Y"]),
        )

    def test_merge_content(self, mock_embedding, mock_qdrant):
        """测试记忆合并"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="新发现: 使用 FastAPI",
            summary="用户选择 FastAPI",
            key_points=["使用 FastAPI"],
            tags=["fastapi"],
            entities=["FastAPI"],
            importance=0.9,
            confidence=0.95,
        )
        existing = Memory(
            content="用户使用 Python",
            summary="Python 偏好",
            key_points=["Python 偏好"],
            tags=["python"],
            entities=["Python"],
            importance=0.7,
            confidence=0.8,
        )

        merged = service._merge_content(candidate, existing)
        assert "Python" in merged["content"]
        assert "FastAPI" in merged["content"]
        # entities are lowercased during merge
        assert "fastapi" in merged["entities"]
        assert "python" in merged["entities"]
        assert merged["importance"] == 0.9  # max
        assert merged["confidence"] == 0.95  # max

    @pytest.mark.asyncio
    async def test_process_candidates_qdrant_unavailable(self, mock_embedding, mock_qdrant):
        """Qdrant 不可用时全部 KEEP_NEW"""
        mock_qdrant.is_available = False
        service = DedupService(mock_embedding, mock_qdrant)

        candidates = [
            MemoryCandidate(content="test1", summary="s1"),
            MemoryCandidate(content="test2", summary="s2"),
        ]

        from unittest.mock import AsyncMock
        db = AsyncMock()
        results = await service.process_candidates(candidates, "user_001", db)

        assert len(results) == 2
        assert all(r.action == DedupAction.KEEP_NEW for r in results)

    def test_extract_nouns(self):
        """测试简单关键词提取"""
        text = "用户使用 Python 开发 Web 应用，偏好 FastAPI 框架"
        nouns = DedupService._extract_nouns(text)
        assert "Python" in nouns or "python" in [n.lower() for n in nouns]
        assert any("Web" in n or "web" in n.lower() for n in nouns) or any("应用" == n for n in nouns)


# ============================================================
# New Extractor Tests (Preference, Process, Feedback)
# ============================================================

class TestPreferenceExtractor:
    """测试用户偏好抽取器"""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    @pytest.mark.asyncio
    async def test_preference_extraction(self, mock_llm):
        """测试偏好抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "style_preferences": [
                {"preference_object": "表达风格", "preference_content": "正式严谨", "applicable_scenario": "技术方案", "confidence": 0.9},
            ],
            "habitual_preferences": [
                {"preference_object": "开发语言", "preference_content": "优先使用 Python", "applicable_scenario": "后端开发", "confidence": 0.85},
            ],
            "decision_tendencies": [
                {"tendency_type": "risk_attitude", "tendency_content": "偏好稳定成熟方案", "evidence": "用户多次拒绝实验性技术", "confidence": 0.8},
            ],
        })

        extractor = PreferenceExtractor(mock_llm)
        result = await extractor.extract("用户偏好正式严谨的表达风格，优先使用 Python 开发")

        assert len(result.style_preferences) == 1
        assert result.style_preferences[0]["preference_content"] == "正式严谨"
        assert len(result.habitual_preferences) == 1
        assert len(result.decision_tendencies) == 1
        assert result.decision_tendencies[0]["tendency_type"] == "risk_attitude"

    @pytest.mark.asyncio
    async def test_preference_empty_text(self, mock_llm):
        """空文本返回空结果"""
        extractor = PreferenceExtractor(mock_llm)
        result = await extractor.extract("")
        assert result.is_empty()


class TestProcessExtractor:
    """测试过程信息抽取器"""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    @pytest.mark.asyncio
    async def test_process_extraction(self, mock_llm):
        """测试过程信息抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "execution_actions": [
                {"action_name": "向量检索", "action_type": "search", "input_summary": "查询 Qdrant", "output_summary": "返回 5 条结果", "tool_name": "Qdrant"},
            ],
            "intermediate_conclusions": [
                {"conclusion": "相似度不足需扩大检索范围", "basis": "最高分仅 0.6", "confidence": 0.7, "is_final": False},
            ],
            "failure_records": [
                {"failure_point": "Qdrant 连接超时", "failure_reason": "网络不稳定", "attempted_recovery": "重试 3 次", "was_resolved": True, "lesson_learned": "增加超时时间和重试机制"},
            ],
        })

        extractor = ProcessExtractor(mock_llm)
        result = await extractor.extract("执行了向量检索，Qdrant 超时后重试成功")

        assert len(result.execution_actions) == 1
        assert result.execution_actions[0]["action_type"] == "search"
        assert len(result.intermediate_conclusions) == 1
        assert len(result.failure_records) == 1
        assert result.failure_records[0]["was_resolved"] is True


class TestFeedbackExtractor:
    """测试反馈修正抽取器"""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    @pytest.mark.asyncio
    async def test_feedback_extraction(self, mock_llm):
        """测试反馈修正抽取"""
        mock_llm.extract_structured = AsyncMock(return_value={
            "corrections": [
                {"corrected_content": "使用 Redis 缓存", "correction_instruction": "改用 Memcached", "original_context": "架构讨论", "correction_type": "revision"},
            ],
            "confirmation_statuses": [
                {"confirmed_item": "微服务方案", "status": "confirmed", "parties_involved": ["user", "agent"], "context": "最终确认"},
            ],
            "replacement_relationships": [
                {"replaced_content": "Redis 缓存方案", "replacement_content": "Memcached 缓存方案", "replacement_reason": "性能考虑", "scope": "global"},
            ],
        })

        extractor = FeedbackExtractor(mock_llm)
        result = await extractor.extract("不要把 Redis 用于缓存，改用 Memcached。微服务方案确认。")

        assert len(result.corrections) == 1
        assert result.corrections[0]["correction_type"] == "revision"
        assert len(result.confirmation_statuses) == 1
        assert result.confirmation_statuses[0]["status"] == "confirmed"
        assert len(result.replacement_relationships) == 1
        assert result.replacement_relationships[0]["scope"] == "global"


# ============================================================
# ExtractionResult with 6 types
# ============================================================

class TestExtractionResultV2:
    """测试六类型 ExtractionResult"""

    def test_to_dict_with_all_six_types(self):
        """测试包含全部六种类型的 to_dict"""
        result = ExtractionResult(
            key_facts=KeyFactsResult(
                business_objects=[{"name": "Test"}],
            ),
            task_state=TaskStateResult(
                current_progress="进行中",
            ),
            decisions=DecisionResult(
                confirmed_plans=[{"plan": "方案A"}],
            ),
            preferences=PreferenceResult(
                style_preferences=[{"preference_object": "风格", "preference_content": "正式", "confidence": 0.8}],
            ),
            process=ProcessResult(
                execution_actions=[{"action_name": "检索", "action_type": "search"}],
            ),
            feedback=FeedbackResult(
                corrections=[{"corrected_content": "旧方案", "correction_instruction": "新方案", "correction_type": "revision"}],
            ),
            source_text="test",
        )

        d = result.to_dict()
        assert len(d["business_objects"]) == 1
        assert d["current_progress"] == "进行中"
        assert len(d["style_preferences"]) == 1
        assert len(d["execution_actions"]) == 1
        assert len(d["corrections"]) == 1

    def test_is_empty_all_empty(self):
        """全部为空时 is_empty() = True"""
        result = ExtractionResult(source_text="empty")
        assert result.is_empty()

    def test_is_empty_with_new_types(self):
        """新类型有内容时 is_empty() = False"""
        result = ExtractionResult(
            preferences=PreferenceResult(
                style_preferences=[{"preference_object": "test", "preference_content": "test", "confidence": 0.5}],
            ),
        )
        assert not result.is_empty()


# ============================================================
# Quality Verification Tests
# ============================================================

class TestQualityVerification:
    """测试质量校验"""

    def test_judge_extraction_value_with_data(self):
        """有价值数据 → should_keep=True"""
        result = ExtractionResult(
            key_facts=KeyFactsResult(
                business_objects=[{"name": "Test"}],
                constraints=[{"type": "temporal", "description": "deadline", "severity": "high"}],
            ),
            task_state=TaskStateResult(current_progress="进行中"),
            decisions=DecisionResult(confirmed_plans=[{"plan": "方案A"}]),
        )
        judgment = judge_extraction_value(result)
        assert judgment.should_keep is True
        assert judgment.overall_value > 0.0

    def test_judge_extraction_value_empty(self):
        """空数据 → should_keep=False"""
        result = ExtractionResult(source_text="empty")
        judgment = judge_extraction_value(result)
        assert judgment.should_keep is False
        assert judgment.overall_value == 0.0

    def test_verify_candidate_quality_valid(self):
        """有效候选 → active"""
        candidate = MemoryCandidate(
            content="用户偏好使用 Python 进行后端开发",
            summary="用户偏好 Python",
            key_points=["Python 偏好"],
            memory_type="preference",
            tags=["python", "preference"],
            entities=["Python"],
            importance=0.8,
            confidence=0.9,
        )
        report = verify_candidate_quality(candidate)
        assert report.is_accurate is True
        assert report.is_usable is True
        assert report.suggested_status == "active"
        assert report.quality_score > 0.5

    def test_verify_candidate_quality_empty_content(self):
        """空内容 → pending"""
        candidate = MemoryCandidate(
            content="",
            summary="",
            memory_type="fact",
        )
        report = verify_candidate_quality(candidate)
        assert report.is_accurate is False
        assert report.suggested_status == "pending"

    def test_verify_candidate_quality_low_confidence(self):
        """低置信度 → pending"""
        candidate = MemoryCandidate(
            content="用户可能偏好某种开发方式，但不确定具体是什么",
            summary="不确定偏好",
            key_points=["不确定"],
            memory_type="preference",
            tags=["uncertain"],
            entities=[],
            importance=0.3,
            confidence=0.2,
        )
        report = verify_candidate_quality(candidate)
        assert report.suggested_status == "pending"

    def test_verify_candidate_quality_hallucination_detection(self):
        """幻觉标记检测"""
        candidate = MemoryCandidate(
            content="无法确定 用户的具体需求，可能是 需要 [TODO] 确认 N/A",
            summary="不确定",
            key_points=["k1"],
            memory_type="fact",
            tags=["t1"],
            entities=["e1"],
            importance=0.3,
            confidence=0.3,
        )
        report = verify_candidate_quality(candidate)
        assert report.is_accurate is False
        assert "too_many_uncertain_markers" in report.issues

    def test_verify_candidates_batch(self):
        """批量质量校验"""
        candidates = [
            MemoryCandidate(
                content="有效记忆内容，包含足够长的语义信息用于测试",
                summary="摘要",
                key_points=["k1"],
                memory_type="fact",
                tags=["t1"],
                entities=["e1"],
                importance=0.7,
                confidence=0.8,
            ),
            MemoryCandidate(
                content="",
                summary="",
                memory_type="fact",
            ),
        ]
        reports = verify_candidates_batch(candidates)
        assert len(reports) == 2
        assert reports[0].suggested_status == "active"
        assert reports[1].suggested_status == "pending"


# ============================================================
# Conflict Detection & Audit Trail Tests
# ============================================================

class TestConflictDetection:
    """测试冲突检测"""

    @pytest.fixture
    def mock_embedding(self):
        emb = MagicMock(spec=EmbeddingClient)
        emb.embed_single = AsyncMock(return_value=[0.1] * 1024)
        return emb

    @pytest.fixture
    def mock_qdrant(self):
        qdrant = MagicMock()
        qdrant.is_available = True
        return qdrant

    def test_detect_preference_change(self, mock_embedding, mock_qdrant):
        """检测偏好变化"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="用户不再偏好详细报告，改为简短摘要格式",
            memory_type="preference",
        )
        existing = Memory(
            content="用户偏好详细的报告格式，包含完整分析和多维度数据展示",
            memory_type="preference",
        )
        best = SimilarMemory(
            memory_id="mem_001",
            content=existing.content,
            vector_score=0.82,
            keyword_overlap=0.6,
            identity_match=True,
        )

        is_conflict, reason = service._detect_conflict(candidate, existing, best)
        assert is_conflict is True
        assert "偏好变化" in reason

    def test_detect_constraint_adjustment(self, mock_embedding, mock_qdrant):
        """检测约束调整"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="必须使用 PostgreSQL，不能使用 MySQL",
            memory_type="constraint",
        )
        existing = Memory(
            content="数据库必须使用 MySQL",
            memory_type="constraint",
        )
        best = SimilarMemory(
            memory_id="mem_002",
            content=existing.content,
            vector_score=0.85,
            keyword_overlap=0.7,
            identity_match=True,
        )

        is_conflict, reason = service._detect_conflict(candidate, existing, best)
        assert is_conflict is True

    def test_no_conflict_low_similarity(self, mock_embedding, mock_qdrant):
        """低相似度不触发冲突检测"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(content="无关内容", memory_type="fact")
        existing = Memory(content="另一段无关内容", memory_type="fact")
        best = SimilarMemory(
            memory_id="mem_003",
            content=existing.content,
            vector_score=0.6,
            keyword_overlap=0.2,
            identity_match=False,
        )

        is_conflict, reason = service._detect_conflict(candidate, existing, best)
        assert is_conflict is False

    def test_decide_action_conflict(self, mock_embedding, mock_qdrant):
        """高相似度 + 冲突 → CONFLICT"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(
            content="用户不再使用 Redis 作为缓存方案，改为使用 Memcached",
            memory_type="preference",
        )
        existing = Memory(
            memory_id="mem_004",
            content="用户使用 Redis 作为主要的缓存方案并已部署到生产环境",
            memory_type="preference",
        )
        best = SimilarMemory(
            memory_id="mem_004",
            content=existing.content,
            vector_score=0.85,
            keyword_overlap=0.7,
            identity_match=True,
        )

        action = service._decide_action(
            vector_score=best.vector_score,
            keyword_overlap=best.keyword_overlap,
            identity_match=best.identity_match,
            candidate=candidate,
            best_match=best,
            existing_memories=[existing],
        )
        assert action == DedupAction.CONFLICT

    def test_check_identity_with_session(self, mock_embedding, mock_qdrant):
        """session_id 校验"""
        from app.models.base import Memory

        service = DedupService(mock_embedding, mock_qdrant)
        candidate = MemoryCandidate(content="test", entities=["E1", "E2"])
        existing = Memory(
            content="test",
            entities=["E1", "E2"],
            session_id="sess_001",
            task_id=None,
        )

        # 相同 session → identity match
        assert service._check_identity(candidate, existing, session_id="sess_001") is True


# ============================================================
# DedupAction CONFLICT
# ============================================================

class TestDedupActionConflict:
    """测试 CONFLICT 动作"""

    def test_conflict_action_exists(self):
        """CONFLICT 是有效的 DedupAction"""
        assert hasattr(DedupAction, "CONFLICT")
        assert DedupAction.CONFLICT.value == "conflict"

    def test_conflict_result_structure(self):
        """CONFLICT 结果包含冲突信息"""
        result = DedupResult(
            action=DedupAction.CONFLICT,
            content="新偏好内容",
            memory_type="preference",
            confidence=0.3,
            conflict_with=["mem_old_001"],
            tags=["conflict", "preference"],
            message="检测到冲突",
        )
        assert result.action == DedupAction.CONFLICT
        assert result.confidence == 0.3
        assert "mem_old_001" in result.conflict_with
        assert "conflict" in result.tags


# ============================================================
# MemoryQuality integration
# ============================================================

class TestMemoryQuality:
    """测试记忆质量服务"""

    def test_value_judgment_all_types_active(self):
        """全部类型活跃 → 高分"""
        result = ExtractionResult(
            key_facts=KeyFactsResult(business_objects=[{"name": "X"}]),
            task_state=TaskStateResult(current_progress="P"),
            decisions=DecisionResult(confirmed_plans=[{"plan": "A"}]),
            preferences=PreferenceResult(style_preferences=[{"preference_object": "S", "preference_content": "C", "confidence": 0.5}]),
            process=ProcessResult(execution_actions=[{"action_name": "A", "action_type": "search"}]),
            feedback=FeedbackResult(corrections=[{"corrected_content": "X", "correction_instruction": "Y", "correction_type": "revision"}]),
        )
        judgment = judge_extraction_value(result)
        assert judgment.should_keep is True
        assert judgment.overall_value >= 0.5  # All types contribute

    def test_quality_report_fields(self):
        """QualityReport 各字段正确填充"""
        candidate = MemoryCandidate(
            content="测试记忆内容足够长，包含完整的语义信息",
            summary="测试摘要",
            key_points=["要点1"],
            memory_type="fact",
            tags=["测试"],
            entities=["实体1"],
            importance=0.7,
            confidence=0.8,
        )
        report = verify_candidate_quality(candidate, source_text="原始文本")
        assert report.is_accurate is True
        assert report.is_usable is True
        assert report.suggested_status == "active"
        assert 0.0 <= report.quality_score <= 1.0
        assert len(report.issues) == 0
