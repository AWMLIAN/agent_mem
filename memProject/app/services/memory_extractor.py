# -*- coding: utf-8 -*-
"""
Memory Extractor — 关键记忆抽取服务。

从对话文本中抽取三类结构化信息：
  - 关键事实（业务对象、约束条件、确认事项）
  - 任务状态（当前进展、已完成内容、待处理事项）
  - 历史决策（已确认方案、选择依据、执行结果）

使用 LLM + 自定义 Prompt 进行精确的结构化 JSON 抽取。
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from app.core.exceptions import MemoryGenerationError
from app.core.logger import get_logger
from app.prompts.key_fact_extraction import (
    KEY_FACT_SYSTEM_PROMPT,
    KEY_FACT_USER_TEMPLATE,
    KEY_FACT_OUTPUT_SCHEMA,
)
from app.prompts.task_state_extraction import (
    TASK_STATE_SYSTEM_PROMPT,
    TASK_STATE_USER_TEMPLATE,
    TASK_STATE_OUTPUT_SCHEMA,
)
from app.prompts.decision_extraction import (
    DECISION_SYSTEM_PROMPT,
    DECISION_USER_TEMPLATE,
    DECISION_OUTPUT_SCHEMA,
)
from app.services.llm_client import LLMClient

logger = get_logger("memory_extractor")

EXTRACTION_VALID_TYPES = {"key_fact", "task_state", "decision"}


# ============================================================
# 抽取结果数据类
# ============================================================

@dataclass
class KeyFactsResult:
    """关键事实抽取结果"""
    business_objects: list[dict] = field(default_factory=list)
    constraints: list[dict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.business_objects or self.constraints or self.confirmations)


@dataclass
class TaskStateResult:
    """任务状态抽取结果"""
    current_progress: str = ""
    completed_items: list[dict] = field(default_factory=list)
    pending_items: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.current_progress or self.completed_items or self.pending_items)


@dataclass
class DecisionResult:
    """历史决策抽取结果"""
    confirmed_plans: list[dict] = field(default_factory=list)
    selection_rationale: list[dict] = field(default_factory=list)
    execution_results: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.confirmed_plans or self.selection_rationale or self.execution_results)


@dataclass
class ExtractionResult:
    """统一抽取结果，包含所有三类信息的汇总"""
    key_facts: Optional[KeyFactsResult] = None
    task_state: Optional[TaskStateResult] = None
    decisions: Optional[DecisionResult] = None
    source_text: str = ""

    def is_empty(self) -> bool:
        has_facts = self.key_facts is not None and not self.key_facts.is_empty()
        has_state = self.task_state is not None and not self.task_state.is_empty()
        has_decision = self.decisions is not None and not self.decisions.is_empty()
        return not (has_facts or has_state or has_decision)

    def to_dict(self) -> dict:
        """转为 JSON 兼容的 dict，用于传给 MemoryGenerator。"""
        result: dict = {"source_text": self.source_text}

        if self.key_facts:
            result["business_objects"] = self.key_facts.business_objects
            result["constraints"] = self.key_facts.constraints
            result["confirmations"] = self.key_facts.confirmations
        else:
            result["business_objects"] = []
            result["constraints"] = []
            result["confirmations"] = []

        if self.task_state:
            result["current_progress"] = self.task_state.current_progress
            result["completed_items"] = self.task_state.completed_items
            result["pending_items"] = self.task_state.pending_items
        else:
            result["current_progress"] = ""
            result["completed_items"] = []
            result["pending_items"] = []

        if self.decisions:
            result["confirmed_plans"] = self.decisions.confirmed_plans
            result["selection_rationale"] = self.decisions.selection_rationale
            result["execution_results"] = self.decisions.execution_results
        else:
            result["confirmed_plans"] = []
            result["selection_rationale"] = []
            result["execution_results"] = []

        return result


# ============================================================
# 子提取器
# ============================================================

class KeyFactExtractor:
    """从文本中提取关键事实（业务对象、约束条件、确认事项）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str) -> KeyFactsResult:
        """执行关键事实抽取。"""
        if not text.strip():
            return KeyFactsResult()

        try:
            user_content = KEY_FACT_USER_TEMPLATE.format(text=text)
            data = await self._llm.extract_structured(
                system_prompt=KEY_FACT_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=KEY_FACT_OUTPUT_SCHEMA,
            )
            return KeyFactsResult(
                business_objects=data.get("business_objects", []),
                constraints=data.get("constraints", []),
                confirmations=data.get("confirmations", []),
            )
        except Exception as e:
            logger.warning(f"Key fact extraction failed: {e}")
            return KeyFactsResult()


class TaskStateExtractor:
    """从文本中提取任务状态（进展、已完成、待处理）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str, task_context: Optional[dict] = None) -> TaskStateResult:
        """执行任务状态抽取。"""
        if not text.strip():
            return TaskStateResult()

        ctx_str = json.dumps(task_context, ensure_ascii=False) if task_context else "无"

        try:
            user_content = TASK_STATE_USER_TEMPLATE.format(
                text=text, task_context=ctx_str
            )
            data = await self._llm.extract_structured(
                system_prompt=TASK_STATE_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=TASK_STATE_OUTPUT_SCHEMA,
            )
            return TaskStateResult(
                current_progress=data.get("current_progress", ""),
                completed_items=data.get("completed_items", []),
                pending_items=data.get("pending_items", []),
            )
        except Exception as e:
            logger.warning(f"Task state extraction failed: {e}")
            return TaskStateResult()


class DecisionExtractor:
    """从文本中提取历史决策（方案、依据、结果）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str) -> DecisionResult:
        """执行历史决策抽取。"""
        if not text.strip():
            return DecisionResult()

        try:
            user_content = DECISION_USER_TEMPLATE.format(text=text)
            data = await self._llm.extract_structured(
                system_prompt=DECISION_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=DECISION_OUTPUT_SCHEMA,
            )
            return DecisionResult(
                confirmed_plans=data.get("confirmed_plans", []),
                selection_rationale=data.get("selection_rationale", []),
                execution_results=data.get("execution_results", []),
            )
        except Exception as e:
            logger.warning(f"Decision extraction failed: {e}")
            return DecisionResult()


# ============================================================
# Facade
# ============================================================

class MemoryExtractor:
    """
    记忆抽取 Facade。

    根据指定的 types 参数并行调度子提取器，聚合结果到 ExtractionResult。
    """

    def __init__(self, llm: LLMClient) -> None:
        self._fact_extractor = KeyFactExtractor(llm)
        self._state_extractor = TaskStateExtractor(llm)
        self._decision_extractor = DecisionExtractor(llm)

    async def extract(
        self,
        text: str,
        types: Optional[list[str]] = None,
        task_context: Optional[dict] = None,
    ) -> ExtractionResult:
        """
        执行多类型记忆抽取。

        Args:
            text: 待抽取的对话文本
            types: 抽取类型列表，默认全部。可选: "key_fact", "task_state", "decision"
            task_context: 额外任务上下文（用于 task_state 抽取）

        Returns:
            ExtractionResult 包含所有指定类型的抽取结果

        Raises:
            MemoryGenerationError: 如果指定的 types 无效
        """
        if types is None:
            types = ["key_fact", "task_state", "decision"]

        # 验证类型
        invalid = [t for t in types if t not in EXTRACTION_VALID_TYPES]
        if invalid:
            raise MemoryGenerationError(
                f"无效的抽取类型: {invalid}，有效类型: {EXTRACTION_VALID_TYPES}"
            )

        result = ExtractionResult(source_text=text)

        # 并行执行所有需要的抽取器
        import asyncio

        tasks = {}

        if "key_fact" in types:
            tasks["key_fact"] = self._fact_extractor.extract(text)
        if "task_state" in types:
            tasks["task_state"] = self._state_extractor.extract(text, task_context)
        if "decision" in types:
            tasks["decision"] = self._decision_extractor.extract(text)

        if not tasks:
            return result

        completed = await asyncio.gather(*tasks.values(), return_exceptions=True)

        keys = list(tasks.keys())
        for key, r in zip(keys, completed):
            if isinstance(r, Exception):
                logger.error(f"Extractor '{key}' failed with exception: {r}")
                continue
            if key == "key_fact":
                result.key_facts = r
            elif key == "task_state":
                result.task_state = r
            elif key == "decision":
                result.decisions = r

        # 统计
        extracted_types = []
        if result.key_facts and not result.key_facts.is_empty():
            extracted_types.append("key_fact")
        if result.task_state and not result.task_state.is_empty():
            extracted_types.append("task_state")
        if result.decisions and not result.decisions.is_empty():
            extracted_types.append("decision")

        logger.info(
            f"Extraction complete: text_len={len(text)}, types={extracted_types}"
        )
        return result
