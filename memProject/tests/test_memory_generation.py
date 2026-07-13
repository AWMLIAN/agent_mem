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
    ExtractionResult, KeyFactsResult, TaskStateResult, DecisionResult,
)
from app.services.memory_generator import MemoryGenerator, MemoryCandidate
from app.services.memory_dedup import (
    DedupService, DedupResult, DedupAction, SimilarMemory,
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
