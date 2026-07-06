# -*- coding: utf-8 -*-
"""
Memory Dedup Service — 多阶段记忆去重与融合引擎。

去重算法流程：
  1. 向量相似度检索（Qdrant 语义搜索）
  2. 数据库加载完整候选记忆
  3. 关键词重合计算（Jaccard 系数）
  4. 标识一致性判断（task_id + entities 重叠）
  5. 综合评分决策（DISCARD / MERGE / UPDATE_EXISTING / KEEP_NEW）
  6. 融合执行（合并内容、要点、实体）
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.qdrant_client import QdrantClientSingleton
from app.models.base import Memory
from app.services.embedding_client import EmbeddingClient
from app.services.memory_generator import MemoryCandidate

logger = get_logger("memory_dedup")


class DedupAction(str, Enum):
    KEEP_NEW = "keep_new"
    MERGE = "merge"
    DISCARD = "discard"
    UPDATE_EXISTING = "update_existing"


@dataclass
class SimilarMemory:
    """与候选记忆相似的已有记忆"""
    memory_id: str
    content: str
    vector_score: float           # 余弦相似度 (0-1)
    keyword_overlap: float        # Jaccard 系数 (0-1)
    identity_match: bool          # 是否同一实体/任务


@dataclass
class DedupResult:
    """去重决策结果"""
    action: DedupAction
    memory_id: Optional[str] = None       # 分配或已有的 memory_id
    content: str = ""                     # 最终内容（合并后）
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    memory_type: str = "fact"
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.5
    merged_from: list[str] = field(default_factory=list)  # 合并来源的 memory_ids
    message: str = ""


class DedupService:
    """
    多阶段记忆去重引擎。

    对每个候选记忆执行：向量检索 → 关键词对比 → 标识检查 → 综合决策。
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        qdrant: QdrantClientSingleton,
    ) -> None:
        self._embedding = embedding_client
        self._qdrant = qdrant

    async def process_candidates(
        self,
        candidates: list[MemoryCandidate],
        user_id: str,
        db: AsyncSession,
        task_id: Optional[str] = None,
        similarity_threshold: float = 0.85,
        keyword_threshold: float = 0.5,
    ) -> list[DedupResult]:
        """
        对候选记忆列表逐一执行去重决策。

        Args:
            candidates: 待处理的记忆候选
            user_id: 用户标识
            db: 数据库会话
            task_id: 当前任务 ID
            similarity_threshold: 向量相似度阈值
            keyword_threshold: 关键词重合阈值

        Returns:
            DedupResult 列表，顺序与 candidates 一致
        """
        if not self._qdrant.is_available:
            logger.warning("Qdrant unavailable, skipping dedup — all candidates KEEP_NEW")
            return [
                DedupResult(
                    action=DedupAction.KEEP_NEW,
                    content=c.content,
                    summary=c.summary,
                    key_points=c.key_points,
                    memory_type=c.memory_type,
                    tags=c.tags,
                    entities=c.entities,
                    importance=c.importance,
                    confidence=c.confidence,
                    message="Qdrant 不可用，跳过去重",
                )
                for c in candidates
            ]

        results: list[DedupResult] = []

        for candidate in candidates:
            result = await self._process_single(
                candidate=candidate,
                user_id=user_id,
                db=db,
                task_id=task_id,
                similarity_threshold=similarity_threshold,
                keyword_threshold=keyword_threshold,
            )
            results.append(result)

        actions = {
            a: sum(1 for r in results if r.action == a)
            for a in DedupAction
        }
        logger.info(f"Dedup complete: {len(candidates)} candidates → {actions}")
        return results

    async def _process_single(
        self,
        candidate: MemoryCandidate,
        user_id: str,
        db: AsyncSession,
        task_id: Optional[str],
        similarity_threshold: float,
        keyword_threshold: float,
    ) -> DedupResult:
        """对单个候选记忆执行完整去重流程。"""

        # Stage 1: 向量相似度检索
        try:
            query_vector = await self._embedding.embed_single(candidate.content)
            hits = self._qdrant.search_similar(
                query_vector=query_vector,
                user_id=user_id,
                top_k=5,
                score_threshold=0.70,  # 宽松阈值，捕捉更多候选
            )
        except Exception as e:
            logger.warning(f"Vector search failed for dedup: {e}")
            return self._make_keep_new(candidate, "向量检索失败，默认保留")

        if not hits:
            return self._make_keep_new(candidate, "无相似向量匹配")

        # Stage 2: 从 PostgreSQL 加载完整记忆
        hit_ids = [h["id"] for h in hits]
        existing_memories: list[Memory] = []
        try:
            result = await db.execute(
                select(Memory).where(Memory.memory_id.in_(hit_ids))
            )
            existing_memories = list(result.scalars().all())
        except Exception as e:
            logger.warning(f"DB load failed for dedup: {e}")
            return self._make_keep_new(candidate, "数据库加载失败，保留新记忆")

        if not existing_memories:
            return self._make_keep_new(candidate, "无匹配数据库记录")

        # 为每个已有记忆计算相似度
        similar_memories: list[SimilarMemory] = []
        hit_score_map = {h["id"]: h["score"] for h in hits}

        for existing in existing_memories:
            vector_score = hit_score_map.get(existing.memory_id, 0.0)
            keyword_overlap = self._compute_keyword_overlap(candidate, existing)
            identity_match = self._check_identity(candidate, existing, task_id)

            similar_memories.append(
                SimilarMemory(
                    memory_id=existing.memory_id,
                    content=existing.content or "",
                    vector_score=vector_score,
                    keyword_overlap=keyword_overlap,
                    identity_match=identity_match,
                )
            )

        # 找最佳匹配
        best = max(similar_memories, key=lambda s: s.vector_score)

        # Stage 3-5: 综合决策
        action = self._decide_action(
            vector_score=best.vector_score,
            keyword_overlap=best.keyword_overlap,
            identity_match=best.identity_match,
            similarity_threshold=similarity_threshold,
            keyword_threshold=keyword_threshold,
        )

        # Stage 6: 执行对应的处理
        if action == DedupAction.DISCARD:
            return DedupResult(
                action=DedupAction.DISCARD,
                memory_id=best.memory_id,
                content=candidate.content,
                summary=candidate.summary,
                key_points=candidate.key_points,
                memory_type=candidate.memory_type,
                tags=candidate.tags,
                entities=candidate.entities,
                importance=candidate.importance,
                confidence=candidate.confidence,
                message=f"与现有记忆 {best.memory_id} 高度重复 (vec={best.vector_score:.3f}, kw={best.keyword_overlap:.3f})",
            )

        elif action == DedupAction.UPDATE_EXISTING:
            return DedupResult(
                action=DedupAction.UPDATE_EXISTING,
                memory_id=best.memory_id,
                content=candidate.content,
                summary=candidate.summary,
                key_points=candidate.key_points,
                memory_type=candidate.memory_type,
                tags=list(set(candidate.tags)),
                entities=list(set(candidate.entities)),
                importance=max(candidate.importance, 0.5),
                confidence=max(candidate.confidence, 0.5),
                message=f"更新现有记忆 {best.memory_id} (identity match)",
            )

        elif action == DedupAction.MERGE:
            # 获取完整 existing memory 用于合并
            existing = next((e for e in existing_memories if e.memory_id == best.memory_id), None)
            if existing:
                merged = self._merge_content(candidate, existing)
                return DedupResult(
                    action=DedupAction.MERGE,
                    memory_id=best.memory_id,
                    content=merged["content"],
                    summary=merged["summary"],
                    key_points=merged["key_points"],
                    memory_type=candidate.memory_type,
                    tags=merged["tags"],
                    entities=merged["entities"],
                    importance=merged["importance"],
                    confidence=merged["confidence"],
                    merged_from=[best.memory_id],
                    message=f"合并到现有记忆 {best.memory_id} (vec={best.vector_score:.3f})",
                )
            else:
                return self._make_keep_new(candidate, "合并目标不可用，保留新记忆")

        else:  # KEEP_NEW
            return self._make_keep_new(candidate, "无匹配，保留新记忆")

    # ---------- 辅助方法 ----------

    def _compute_keyword_overlap(
        self,
        candidate: MemoryCandidate,
        existing: Memory,
    ) -> float:
        """计算关键词 Jaccard 系数。"""
        candidate_keywords = set(
            [t.lower() for t in candidate.tags]
            + [e.lower() for e in candidate.entities]
            + self._extract_nouns(candidate.content)
        )
        existing_keywords = set(
            [t.lower() for t in (existing.tags or [])]
            + [e.lower() for e in (existing.entities or [])]
            + self._extract_nouns(existing.content or "")
        )

        if not candidate_keywords or not existing_keywords:
            return 0.0

        intersection = candidate_keywords & existing_keywords
        union = candidate_keywords | existing_keywords
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _extract_nouns(text: str) -> list[str]:
        """
        简单关键词提取：提取中英文词语（2+ 字符）。
        这不是精确的 NLP 分词，但足以用于关键词重合判断。
        """
        # 提取英文单词 (3+ chars)
        english = re.findall(r"[a-zA-Z]{3,}", text)
        # 提取中文词组 (2-4 chars)
        chinese = re.findall(r"[一-鿿]{2,4}", text)
        # 组合
        keywords = english + chinese
        # 去重并限制数量
        seen = set()
        unique = []
        for kw in keywords:
            low = kw.lower()
            if low not in seen:
                seen.add(low)
                unique.append(low)
        return unique[:20]  # 最多 20 个关键词

    def _check_identity(
        self,
        candidate: MemoryCandidate,
        existing: Memory,
        task_id: Optional[str] = None,
    ) -> bool:
        """判断候选记忆与已有记忆是否指向同一实体/任务。"""
        # 条件 1: 相同 task_id
        if task_id and existing.task_id == task_id:
            return True

        # 条件 2: entities 重叠 >= 2
        candidate_entities = set(e.lower() for e in candidate.entities)
        existing_entities = set(e.lower() for e in (existing.entities or []))
        overlap = candidate_entities & existing_entities
        if len(overlap) >= 2:
            return True

        return False

    def _decide_action(
        self,
        vector_score: float,
        keyword_overlap: float,
        identity_match: bool,
        similarity_threshold: float = 0.85,
        keyword_threshold: float = 0.5,
    ) -> DedupAction:
        """
        基于综合评分决定去重动作。

        决策矩阵：
          composite = 0.5 * vector_score + 0.3 * keyword_overlap + 0.2 * identity_bonus
          composite >= 0.90               → DISCARD (近乎重复)
          0.80 <= composite < 0.90 + identity → UPDATE_EXISTING
          0.65 <= composite < 0.80 + !identity → MERGE
          composite < 0.65                → KEEP_NEW
        """
        identity_bonus = 1.0 if identity_match else 0.0
        composite = 0.5 * vector_score + 0.3 * keyword_overlap + 0.2 * identity_bonus

        logger.debug(
            f"Dedup decision: vector={vector_score:.3f}, keyword={keyword_overlap:.3f}, "
            f"identity={identity_match}, composite={composite:.3f}"
        )

        if composite >= 0.90:
            return DedupAction.DISCARD
        elif composite >= 0.80 and identity_match:
            return DedupAction.UPDATE_EXISTING
        elif composite >= 0.65 and not identity_match:
            return DedupAction.MERGE
        else:
            return DedupAction.KEEP_NEW

    def _merge_content(
        self,
        candidate: MemoryCandidate,
        existing: Memory,
    ) -> dict:
        """
        合并候选记忆与已有记忆。

        策略：
        - content: 追加新信息到已有内容
        - key_points: 合并去重
        - entities: 取并集
        - tags: 取并集
        - importance/confidence: 取最大值
        """
        # 合并 key_points（去重）
        existing_kps = existing.key_points or []
        all_kps = existing_kps + [kp for kp in candidate.key_points if kp not in existing_kps]

        # 合并 entities（去重）
        existing_entities = existing.entities or []
        all_entities = list(set(
            [e.lower() for e in existing_entities]
            + [e.lower() for e in candidate.entities]
        ))

        # 合并 tags（去重）
        existing_tags = existing.tags or []
        all_tags = list(set(existing_tags + candidate.tags))

        # 合并内容：已有 + 新发现
        merged_content = existing.content or ""
        if candidate.content not in merged_content:
            merged_content = f"{merged_content}\n[更新: {candidate.summary}]"

        # 取更高评分
        existing_importance = float(existing.importance or 0.5)
        existing_confidence = float(existing.confidence or 0.5)

        return {
            "content": merged_content.strip(),
            "summary": (existing.summary or "") + f" | 更新: {candidate.summary}",
            "key_points": all_kps,
            "tags": all_tags,
            "entities": all_entities,
            "importance": max(candidate.importance, existing_importance),
            "confidence": max(candidate.confidence, existing_confidence),
        }

    def _make_keep_new(self, candidate: MemoryCandidate, message: str) -> DedupResult:
        """构造 KEEP_NEW 结果。"""
        return DedupResult(
            action=DedupAction.KEEP_NEW,
            content=candidate.content,
            summary=candidate.summary,
            key_points=candidate.key_points,
            memory_type=candidate.memory_type,
            tags=candidate.tags,
            entities=candidate.entities,
            importance=candidate.importance,
            confidence=candidate.confidence,
            message=message,
        )
