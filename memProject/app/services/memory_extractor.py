# -*- coding: utf-8 -*-
"""
Memory Extractor — 关键记忆抽取服务。

从对话文本中抽取六类结构化信息：
  - 关键事实（业务对象、约束条件、确认事项）
  - 任务状态（当前进展、已完成内容、待处理事项）
  - 历史决策（已确认方案、选择依据、执行结果）
  - 用户偏好（表达风格、使用习惯、决策倾向）
  - 过程信息（执行动作、中间结论、失败记录）
  - 反馈修正（修正记录、确认状态、替代关系）

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
from app.prompts.preference_extraction import (
    PREFERENCE_SYSTEM_PROMPT,
    PREFERENCE_USER_TEMPLATE,
    PREFERENCE_OUTPUT_SCHEMA,
)
from app.prompts.process_extraction import (
    PROCESS_SYSTEM_PROMPT,
    PROCESS_USER_TEMPLATE,
    PROCESS_OUTPUT_SCHEMA,
)
from app.prompts.feedback_extraction import (
    FEEDBACK_SYSTEM_PROMPT,
    FEEDBACK_USER_TEMPLATE,
    FEEDBACK_OUTPUT_SCHEMA,
)
from app.services.llm_client import LLMClient

logger = get_logger("memory_extractor")

EXTRACTION_VALID_TYPES = {
    "key_fact", "task_state", "decision",
    "preference", "process", "feedback",
}


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
class PreferenceResult:
    """用户偏好抽取结果"""
    style_preferences: list[dict] = field(default_factory=list)
    habitual_preferences: list[dict] = field(default_factory=list)
    decision_tendencies: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.style_preferences or self.habitual_preferences or self.decision_tendencies)


@dataclass
class ProcessResult:
    """过程信息抽取结果"""
    execution_actions: list[dict] = field(default_factory=list)
    intermediate_conclusions: list[dict] = field(default_factory=list)
    failure_records: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.execution_actions or self.intermediate_conclusions or self.failure_records)


@dataclass
class FeedbackResult:
    """反馈修正抽取结果"""
    corrections: list[dict] = field(default_factory=list)
    confirmation_statuses: list[dict] = field(default_factory=list)
    replacement_relationships: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.corrections or self.confirmation_statuses or self.replacement_relationships)


@dataclass
class ExtractionResult:
    """统一抽取结果，包含所有六类信息的汇总"""
    key_facts: Optional[KeyFactsResult] = None
    task_state: Optional[TaskStateResult] = None
    decisions: Optional[DecisionResult] = None
    preferences: Optional[PreferenceResult] = None
    process: Optional[ProcessResult] = None
    feedback: Optional[FeedbackResult] = None
    source_text: str = ""

    def is_empty(self) -> bool:
        has_facts = self.key_facts is not None and not self.key_facts.is_empty()
        has_state = self.task_state is not None and not self.task_state.is_empty()
        has_decision = self.decisions is not None and not self.decisions.is_empty()
        has_pref = self.preferences is not None and not self.preferences.is_empty()
        has_proc = self.process is not None and not self.process.is_empty()
        has_fb = self.feedback is not None and not self.feedback.is_empty()
        return not (has_facts or has_state or has_decision or has_pref or has_proc or has_fb)

    def to_dict(self) -> dict:
        """转为 JSON 兼容的 dict，用于传给 MemoryGenerator。"""
        result: dict = {"source_text": self.source_text}

        # Key facts
        if self.key_facts:
            result["business_objects"] = self.key_facts.business_objects
            result["constraints"] = self.key_facts.constraints
            result["confirmations"] = self.key_facts.confirmations
        else:
            result["business_objects"] = []
            result["constraints"] = []
            result["confirmations"] = []

        # Task state
        if self.task_state:
            result["current_progress"] = self.task_state.current_progress
            result["completed_items"] = self.task_state.completed_items
            result["pending_items"] = self.task_state.pending_items
        else:
            result["current_progress"] = ""
            result["completed_items"] = []
            result["pending_items"] = []

        # Decisions
        if self.decisions:
            result["confirmed_plans"] = self.decisions.confirmed_plans
            result["selection_rationale"] = self.decisions.selection_rationale
            result["execution_results"] = self.decisions.execution_results
        else:
            result["confirmed_plans"] = []
            result["selection_rationale"] = []
            result["execution_results"] = []

        # Preferences (new)
        if self.preferences:
            result["style_preferences"] = self.preferences.style_preferences
            result["habitual_preferences"] = self.preferences.habitual_preferences
            result["decision_tendencies"] = self.preferences.decision_tendencies
        else:
            result["style_preferences"] = []
            result["habitual_preferences"] = []
            result["decision_tendencies"] = []

        # Process (new)
        if self.process:
            result["execution_actions"] = self.process.execution_actions
            result["intermediate_conclusions"] = self.process.intermediate_conclusions
            result["failure_records"] = self.process.failure_records
        else:
            result["execution_actions"] = []
            result["intermediate_conclusions"] = []
            result["failure_records"] = []

        # Feedback (new)
        if self.feedback:
            result["corrections"] = self.feedback.corrections
            result["confirmation_statuses"] = self.feedback.confirmation_statuses
            result["replacement_relationships"] = self.feedback.replacement_relationships
        else:
            result["corrections"] = []
            result["confirmation_statuses"] = []
            result["replacement_relationships"] = []

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


class PreferenceExtractor:
    """从文本中提取用户偏好（表达风格、使用习惯、决策倾向）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str) -> PreferenceResult:
        """执行用户偏好抽取。"""
        if not text.strip():
            return PreferenceResult()

        try:
            user_content = PREFERENCE_USER_TEMPLATE.format(text=text)
            data = await self._llm.extract_structured(
                system_prompt=PREFERENCE_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=PREFERENCE_OUTPUT_SCHEMA,
            )
            return PreferenceResult(
                style_preferences=data.get("style_preferences", []),
                habitual_preferences=data.get("habitual_preferences", []),
                decision_tendencies=data.get("decision_tendencies", []),
            )
        except Exception as e:
            logger.warning(f"Preference extraction failed: {e}")
            return PreferenceResult()


class ProcessExtractor:
    """从文本中提取过程信息（执行动作、中间结论、失败记录）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str) -> ProcessResult:
        """执行过程信息抽取。"""
        if not text.strip():
            return ProcessResult()

        try:
            user_content = PROCESS_USER_TEMPLATE.format(text=text)
            data = await self._llm.extract_structured(
                system_prompt=PROCESS_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=PROCESS_OUTPUT_SCHEMA,
            )
            return ProcessResult(
                execution_actions=data.get("execution_actions", []),
                intermediate_conclusions=data.get("intermediate_conclusions", []),
                failure_records=data.get("failure_records", []),
            )
        except Exception as e:
            logger.warning(f"Process extraction failed: {e}")
            return ProcessResult()


class FeedbackExtractor:
    """从文本中提取反馈修正（修正记录、确认状态、替代关系）。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def extract(self, text: str) -> FeedbackResult:
        """执行反馈修正抽取。"""
        if not text.strip():
            return FeedbackResult()

        try:
            user_content = FEEDBACK_USER_TEMPLATE.format(text=text)
            data = await self._llm.extract_structured(
                system_prompt=FEEDBACK_SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=FEEDBACK_OUTPUT_SCHEMA,
            )
            return FeedbackResult(
                corrections=data.get("corrections", []),
                confirmation_statuses=data.get("confirmation_statuses", []),
                replacement_relationships=data.get("replacement_relationships", []),
            )
        except Exception as e:
            logger.warning(f"Feedback extraction failed: {e}")
            return FeedbackResult()


# ============================================================
# Facade
# ============================================================

class MemoryExtractor:
    """
    记忆抽取 Facade。

    根据指定的 types 参数并行调度子提取器，聚合结果到 ExtractionResult。
    支持六种抽取类型：key_fact, task_state, decision, preference, process, feedback
    """

    def __init__(self, llm: LLMClient) -> None:
        self._fact_extractor = KeyFactExtractor(llm)
        self._state_extractor = TaskStateExtractor(llm)
        self._decision_extractor = DecisionExtractor(llm)
        self._preference_extractor = PreferenceExtractor(llm)
        self._process_extractor = ProcessExtractor(llm)
        self._feedback_extractor = FeedbackExtractor(llm)

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
            types: 抽取类型列表，默认全部六种。
                   可选: "key_fact", "task_state", "decision",
                         "preference", "process", "feedback"
            task_context: 额外任务上下文（用于 task_state 抽取）

        Returns:
            ExtractionResult 包含所有指定类型的抽取结果

        Raises:
            MemoryGenerationError: 如果指定的 types 无效
        """
        if types is None:
            types = ["key_fact", "task_state", "decision",
                     "preference", "process", "feedback"]

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
        if "preference" in types:
            tasks["preference"] = self._preference_extractor.extract(text)
        if "process" in types:
            tasks["process"] = self._process_extractor.extract(text)
        if "feedback" in types:
            tasks["feedback"] = self._feedback_extractor.extract(text)

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
            elif key == "preference":
                result.preferences = r
            elif key == "process":
                result.process = r
            elif key == "feedback":
                result.feedback = r

        # 统计
        extracted_types = []
        if result.key_facts and not result.key_facts.is_empty():
            extracted_types.append("key_fact")
        if result.task_state and not result.task_state.is_empty():
            extracted_types.append("task_state")
        if result.decisions and not result.decisions.is_empty():
            extracted_types.append("decision")
        if result.preferences and not result.preferences.is_empty():
            extracted_types.append("preference")
        if result.process and not result.process.is_empty():
            extracted_types.append("process")
        if result.feedback and not result.feedback.is_empty():
            extracted_types.append("feedback")

        logger.info(
            f"Extraction complete: text_len={len(text)}, types={extracted_types}"
        )
        return result
