# -*- coding: utf-8 -*-
"""
记忆 Service 层 — 封装 t_memory / t_interaction_record / t_retrieval_* 的 CRUD 业务逻辑。
所有函数接受 db: AsyncSession 作为第一参数。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, MemoryWriteError
from app.core.logger import get_logger
from app.models.base import (
    Memory,
    InteractionRecord,
    RetrievalRequest,
    RetrievalResult,
    MemoryRelation,
    User,
    Agent,
    Session,
)

logger = get_logger("memory_service")


# ============================================================
# ID 生成
# ============================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def gen_memory_id() -> str:
    return "mem_" + uuid.uuid4().hex[:28]


def gen_record_id() -> str:
    return "rec_" + uuid.uuid4().hex[:28]


def gen_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:28]


# ============================================================
# 核心 CRUD
# ============================================================

async def get_memory_by_id(db: AsyncSession, memory_id: str) -> Optional[Memory]:
    result = await db.execute(
        select(Memory).where(Memory.memory_id == memory_id)
    )
    return result.scalar_one_or_none()


async def create_memory(db: AsyncSession, data: dict) -> Memory:
    """类型感知的记忆创建 — 根据 memory_type 走不同的预处理规则。"""
    memory_type = data.get("memory_type", "fact")
    # 统一 task/task_state 为一个路由
    if memory_type == "task":
        memory_type = "task_state"
        data["memory_type"] = "task_state"

    if memory_type == "preference":
        return await _create_preference(db, data)
    elif memory_type == "task_state":
        return await _create_task_memory(db, data)
    else:
        return await _create_fact(db, data)


async def _create_preference(db: AsyncSession, data: dict) -> Memory:
    """偏好管理：基于 Embedding 语义相似度判断是否同一方面，替换旧偏好。"""
    user_id = data.get("user_id")
    new_id = data.get("memory_id", "")
    new_content = data.get("content", "")
    replaced = 0
    if user_id:
        old = await search_local(db, {
            "user_id": user_id, "memory_types": ["preference"], "status": "active",
        })
        if old:
            try:
                from app.services.embedding_client import embedding_client as _emb
                old_texts = [m.content or "" for m in old]
                new_vec = await _emb.embed_single(new_content)
                old_vecs = await _emb.embed_batch(old_texts)
                for m, old_vec in zip(old, old_vecs):
                    if not old_vec:
                        continue
                    similarity = _cosine_sim(new_vec, old_vec)
                    if similarity > 0.98:
                        m.use_count = (m.use_count or 0) + 1
                        return m
                    elif similarity > 0.75:
                        is_same = await _llm_same_topic_judge(new_content, m.content or "")
                        if is_same:
                            m.status = "pending_update"
                            m.replaced_by = new_id
                            m.updated_at = _now()
                            replaced += 1
                if replaced:
                    logger.info(f"用户 {user_id} LLM判定替换 {replaced}/{len(old)} 条旧偏好")
                else:
                    logger.info(f"用户 {user_id} 无同方面旧偏好，新偏好直接追加")
            except Exception as e:
                logger.warning(f"Embedding/LLM 不可用: {e}")
        else:
            return await _insert_memory(db, data)

    return await _insert_memory(db, data)


async def _llm_same_topic_judge(new_content: str, old_content: str) -> bool:
    """让 LLM 判断两条偏好是否属于同一方面（应替换旧偏好）。"""
    try:
        from app.services.llm_client import llm_client as _llm
        prompt = f"""判断以下两条用户偏好是否属于同一方面（比如都是关于编程工具/代码风格/饮食偏好等），如果是同一方面，新的会替换旧的。

旧偏好: {old_content[:300]}
新偏好: {new_content[:300]}

只回答 YES 或 NO。YES=同一方面应替换，NO=不同方面各自保留。
回答:"""
        resp = await _llm.chat_completion([{"role": "user", "content": prompt}], max_tokens=5)
        return "YES" in resp.upper()
    except Exception:
        return False


async def _create_preference_keyword(db: AsyncSession, data: dict) -> Memory:
    """关键词去重（Embedding 不可用时的降级方案）。"""
    import re as _re
    user_id = data.get("user_id")
    new_id = data.get("memory_id", "")
    new_content = data.get("content", "")
    new_words = set(_re.findall(r'[一-鿿]+|[a-zA-Z]+', new_content.lower()))
    replaced = 0
    if user_id:
        old = await search_local(db, {
            "user_id": user_id, "memory_types": ["preference"], "status": "active",
        })
        for m in old:
            old_words = set(_re.findall(r'[一-鿿]+|[a-zA-Z]+', (m.content or "").lower()))
            shared = new_words & old_words
            if len(shared) >= 2:
                m.status = "pending_update"
                m.replaced_by = new_id
                m.updated_at = _now()
                replaced += 1
    return await _insert_memory(db, data)


async def _create_fact(db: AsyncSession, data: dict) -> Memory:
    """事实管理：Embedding 初筛 → LLM 判断是否冲突。"""
    content = data.get("content", "")
    user_id = data.get("user_id")

    if user_id and len(content) > 5:
        existing = await search_local(db, {
            "user_id": user_id, "memory_types": ["fact"], "status": "active",
        })
        if existing:
            try:
                from app.services.embedding_client import embedding_client as _emb
                old_texts = [m.content or "" for m in existing]
                new_vec = await _emb.embed_single(content)
                old_vecs = await _emb.embed_batch(old_texts)
                for m, old_vec in zip(existing, old_vecs):
                    if not old_vec:
                        continue
                    similarity = _cosine_sim(new_vec, old_vec)
                    if similarity > 0.98:
                        logger.info(f"事实去重：与 {m.memory_id} 相似度 {similarity:.2f}，跳过")
                        m.use_count = (m.use_count or 0) + 1
                        return m
                    elif similarity > 0.75:
                        is_conflict = await _llm_conflict_judge(content, m.content or "")
                        if is_conflict:
                            data["status"] = "conflict"
                            data["replaced_by"] = m.memory_id
                            logger.info(f"LLM判定冲突：与 {m.memory_id}")
                            break
            except Exception as e:
                logger.warning(f"Embedding/LLM 不可用: {e}")

    return await _insert_memory(db, data)


async def _llm_conflict_judge(new_content: str, old_content: str) -> bool:
    """让 LLM 判断两条事实是否真正冲突（而非相关但不矛盾）。"""
    try:
        from app.services.llm_client import llm_client as _llm
        prompt = f"""判断以下两条记忆是否真正冲突（即相互矛盾、不能同时成立），而非仅仅是话题相关。

记忆A: {old_content[:300]}
记忆B: {new_content[:300]}

只回答 YES 或 NO。YES=真正冲突/矛盾，NO=相关但不冲突/只是不同角度。
回答:"""
        resp = await _llm.chat_completion([{"role": "user", "content": prompt}], max_tokens=5)
        return "YES" in resp.upper()
    except Exception:
        return False


async def _create_fact_keyword(db: AsyncSession, data: dict) -> Memory:
    """关键词去重（Embedding 不可用时的降级方案）。"""
    content = data.get("content", "")
    user_id = data.get("user_id")
    if user_id and len(content) > 5:
        existing = await search_local(db, {
            "user_id": user_id, "memory_types": ["fact"], "status": "active",
        })
        for m in existing:
            overlap = _content_overlap(content, m.content or "")
            if overlap > 0.9:
                m.use_count = (m.use_count or 0) + 1
                return m
            elif overlap >= 0.5:
                data["status"] = "conflict"
                data["replaced_by"] = m.memory_id
    return await _insert_memory(db, data)


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


# 任务目标关键词 — 命中则视为"目标/诉求"类记忆，走新旧更替逻辑
_TASK_GOAL_KEYWORDS = {"目标", "目的", "诉求", "任务", "需求", "要做", "实现", "完成目标", "交付", "goal", "objective", "task"}


def _is_task_goal(content: str, key_points: list) -> bool:
    text = content + " " + " ".join(key_points or [])
    return any(kw in text for kw in _TASK_GOAL_KEYWORDS)


async def _create_task_memory(db: AsyncSession, data: dict) -> Memory:
    """任务记忆管理 — 区分目标与进展。"""
    task_id = data.get("task_id")
    content = data.get("content", "")
    key_points = data.get("key_points", [])

    if task_id and _is_task_goal(content, key_points):
        # 目标类：新目标替换旧目标，旧标记 pending_update
        existing = await search_local(db, {
            "task_id": task_id, "memory_types": ["task_state"], "status": "active",
        })
        old_goals = [m for m in existing if _is_task_goal(m.content or "", m.key_points or [])]
        for m in old_goals:
            m.status = "pending_update"
            m.updated_at = _now()
        if old_goals:
            logger.info(f"任务 {task_id} 旧目标 {len(old_goals)} 条标记为 pending_update")
    # 进展类：直接追加，保留历史链

    return await _insert_memory(db, data)


def _content_overlap(a: str, b: str) -> float:
    """词级相似度计算 — 基于关键词重合而非字符重合"""
    if not a or not b:
        return 0.0
    import re
    words_a = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', a.lower()))
    words_b = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


async def _insert_memory(db: AsyncSession, data: dict) -> Memory:
    """纯插入，不做任何类型逻辑。"""
    memory = Memory(
        id=uuid.uuid4().hex,
        memory_id=data.get("memory_id", gen_memory_id()),
        user_id=data.get("user_id"),
        agent_id=data.get("agent_id"),
        scene_id=data.get("scene_id"),
        session_id=data.get("session_id"),
        task_id=data.get("task_id"),
        content=data.get("content", ""),
        summary=data.get("summary"),
        key_points=data.get("key_points", []),
        memory_type=data.get("memory_type", "fact"),
        tags=data.get("tags", []),
        entities=data.get("entities", []),
        status=data.get("status", "active"),
        version=data.get("version", 1),
        replaced_by=data.get("replaced_by"),
        importance=data.get("importance", 0.5),
        confidence=data.get("confidence", 0.5),
        source_type=data.get("source_type", "extracted"),
        source_record_ids=data.get("source_record_ids", []),
        vector_id=data.get("vector_id"),
        created_at=data.get("created_at", _now()),
        updated_at=data.get("updated_at", _now()),
    )
    db.add(memory)
    await db.flush()
    return memory


async def update_memory_fields(db: AsyncSession, memory_id: str, updates: dict) -> Memory:
    memory = await get_memory_by_id(db, memory_id)
    if not memory:
        raise NotFoundError(f"记忆 {memory_id} 不存在")

    allowed_fields = {"content", "summary", "status", "importance", "confidence", "tags"}
    for field in allowed_fields:
        if field in updates and updates[field] is not None:
            setattr(memory, field, updates[field])

    memory.version += 1
    memory.updated_at = _now()
    await db.flush()
    return memory


async def soft_delete_memory(db: AsyncSession, memory_id: str) -> tuple[str, str]:
    memory = await get_memory_by_id(db, memory_id)
    if not memory:
        raise NotFoundError(f"记忆 {memory_id} 不存在")

    previous_status = memory.status
    memory.status = "deleted"
    memory.updated_at = _now()
    await db.flush()
    return memory_id, previous_status


# ============================================================
# 批量写入辅助
# ============================================================

async def save_interaction_records(
    db: AsyncSession,
    messages: list,
    metadata: dict,
) -> list[InteractionRecord]:
    records = []
    for i, msg in enumerate(messages):
        rec = InteractionRecord(
            record_id=gen_record_id(),
            user_id=metadata.get("user_id", ""),
            agent_id=metadata.get("agent_id"),
            scene_id=metadata.get("scene_id"),
            session_id=metadata.get("session_id"),
            task_id=metadata.get("task_id"),
            turn_index=msg.get("turn_index", i),
            role=msg.get("role", "user"),
            content=msg.get("content", ""),
            content_type=msg.get("content_type", "text"),
            processed=False,
            recorded_at=_now(),
            extra_meta=metadata.get("extra_meta", {}),
        )
        db.add(rec)
        records.append(rec)
    await db.flush()
    return records


# ============================================================
# 查询构建
# ============================================================

def _apply_memory_filters(stmt, filters: dict):
    """在 select(Memory) 上叠加 where 条件，返回修改后的 stmt。"""
    if filters.get("user_id"):
        stmt = stmt.where(Memory.user_id == filters["user_id"])

    for attr in ("agent_id", "scene_id", "session_id", "task_id"):
        if filters.get(attr) is not None:
            stmt = stmt.where(getattr(Memory, attr) == filters[attr])

    if filters.get("memory_types"):
        stmt = stmt.where(Memory.memory_type.in_(filters["memory_types"]))

    include_inactive = filters.get("include_inactive", False)
    specified_status = filters.get("status")
    if specified_status:
        stmt = stmt.where(Memory.status == specified_status)
    elif not include_inactive:
        stmt = stmt.where(Memory.status != "deleted")

    if filters.get("time_start"):
        stmt = stmt.where(Memory.created_at >= filters["time_start"])
    if filters.get("time_end"):
        stmt = stmt.where(Memory.created_at <= filters["time_end"])

    return stmt


async def search_local(db: AsyncSession, filters: dict) -> list[Memory]:
    stmt = select(Memory)
    stmt = _apply_memory_filters(stmt, filters)
    stmt = stmt.order_by(Memory.importance.desc(), Memory.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_memories_filtered(
    db: AsyncSession, filters: dict, page: int, page_size: int
) -> tuple[list[Memory], int]:
    base_stmt = select(Memory)
    base_stmt = _apply_memory_filters(base_stmt, filters)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    query_stmt = base_stmt.order_by(Memory.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(query_stmt)
    items = list(result.scalars().all())

    return items, total


async def build_context_query(db: AsyncSession, filters: dict) -> list[Memory]:
    stmt = select(Memory)
    stmt = stmt.where(Memory.status != "deleted")

    if filters.get("user_id"):
        stmt = stmt.where(Memory.user_id == filters["user_id"])
    for attr in ("agent_id", "scene_id", "session_id", "task_id"):
        if filters.get(attr) is not None:
            stmt = stmt.where(getattr(Memory, attr) == filters[attr])

    include_map = filters.get("include_map", {})
    if include_map:
        type_conditions = []
        if include_map.get("preferences"):
            type_conditions.append(Memory.memory_type == "preference")
        if include_map.get("facts"):
            type_conditions.append(Memory.memory_type == "fact")
        if include_map.get("task_state"):
            type_conditions.append(Memory.memory_type == "task_state")
        if type_conditions:
            from sqlalchemy import or_
            stmt = stmt.where(or_(*type_conditions))

    stmt = stmt.order_by(Memory.importance.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ============================================================
# 多层记忆聚合 — 用户/会话/任务三层结构化视图
# ============================================================


async def get_user_profile(db: AsyncSession, user_id: str) -> dict:
    """用户画像：聚合用户跨会话的偏好和事实，供 LLM 注入 prompt。"""
    all_memories = await search_local(db, {"user_id": user_id, "status": "active"})

    profile = {
        "user_id": user_id,
        "preferences": [],
        "facts": [],
    }
    for m in all_memories:
        if m.memory_type == "preference":
            profile["preferences"].append(m.content)
        elif m.memory_type == "fact":
            profile["facts"].append(m.content)
    return profile


async def get_session_context(db: AsyncSession, session_id: str) -> dict:
    """会话上下文：会话内所有记忆按类型分组 + 关键内容。"""
    all_memories = await search_local(db, {"session_id": session_id, "status": "active"})

    ctx: dict = {"session_id": session_id, "by_type": {}, "key_items": []}
    for m in all_memories:
        ctx["by_type"].setdefault(m.memory_type, []).append({
            "memory_id": m.memory_id, "content": m.content, "importance": m.importance,
        })
        if m.importance >= 0.7:
            ctx["key_items"].append({
                "memory_id": m.memory_id, "content": m.content, "memory_type": m.memory_type,
            })
    return ctx


async def get_task_view(db: AsyncSession, task_id: str) -> dict:
    """任务视图：当前目标 + 进展时间线。"""
    all_memories = await search_local(db, {
        "task_id": task_id, "memory_types": ["task_state"],
    })
    all_memories.sort(key=lambda m: m.created_at or datetime.min)

    view: dict = {
        "task_id": task_id,
        "current_goal": None,
        "progress_timeline": [],
    }
    for m in all_memories:
        if m.status == "active" and _is_task_goal(m.content or "", m.key_points or []):
            view["current_goal"] = {"memory_id": m.memory_id, "content": m.content}
        view["progress_timeline"].append({
            "memory_id": m.memory_id, "content": m.content,
            "status": m.status, "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return view


# ============================================================
# 检索日志
# ============================================================

async def log_retrieval_request(db: AsyncSession, data: dict) -> RetrievalRequest:
    req = RetrievalRequest(
        request_id=data.get("request_id", gen_request_id()),
        agent_id=data.get("agent_id"),
        user_id=data.get("user_id", ""),
        scene_id=data.get("scene_id"),
        session_id=data.get("session_id"),
        task_id=data.get("task_id"),
        query_text=data.get("query_text", ""),
        filter_conditions=data.get("filter_conditions", {}),
        top_k=data.get("top_k", 10),
        is_triggered=data.get("is_triggered", False),
        created_at=_now(),
    )
    db.add(req)
    await db.flush()
    return req


async def log_retrieval_results(
    db: AsyncSession, request_id: str, results: list[dict]
) -> None:
    for i, r in enumerate(results):
        entry = RetrievalResult(
            request_id=request_id,
            memory_id=r.get("memory_id", ""),
            rank=i + 1,
            relevance_score=r.get("relevance_score", 0.0),
            semantic_score=r.get("semantic_score"),
            keyword_score=r.get("keyword_score"),
            recency_score=r.get("recency_score"),
            created_at=_now(),
        )
        db.add(entry)
    await db.flush()


# ============================================================
# 统计 / 关系
# ============================================================

async def get_stats(db: AsyncSession) -> dict:
    total_memories = (
        await db.execute(
            select(func.count()).select_from(Memory).where(Memory.status != "deleted")
        )
    ).scalar() or 0

    total_users = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar() or 0

    total_agents = (
        await db.execute(
            select(func.count()).select_from(Agent).where(Agent.is_active == True)
        )
    ).scalar() or 0

    total_sessions = (
        await db.execute(
            select(func.count()).select_from(Session).where(Session.status == "active")
        )
    ).scalar() or 0

    return {
        "total_memories": total_memories,
        "total_users": total_users,
        "total_agents": total_agents,
        "total_sessions": total_sessions,
    }


async def get_memory_relations(db: AsyncSession, memory_id: str) -> list[dict]:
    result = await db.execute(
        select(MemoryRelation).where(
            (MemoryRelation.source_memory_id == memory_id)
            | (MemoryRelation.target_memory_id == memory_id)
        )
    )
    relations = result.scalars().all()
    return [
        {
            "source_memory_id": r.source_memory_id,
            "target_memory_id": r.target_memory_id,
            "relation_type": r.relation_type,
            "description": r.description,
            "confidence": r.confidence,
        }
        for r in relations
    ]
