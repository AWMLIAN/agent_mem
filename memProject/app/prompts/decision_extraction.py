# -*- coding: utf-8 -*-
"""
历史决策抽取 Prompt — 从对话中提取已确认方案、选择依据、执行结果。
"""

DECISION_SYSTEM_PROMPT = """You are a decision analysis system. Extract historical decision records from the conversation:

1. CONFIRMED_PLANS (已确认方案): Approaches, architectures, strategies, or solutions that were chosen or agreed upon.
   For each: plan (方案描述), alternatives (备选方案, if mentioned), decision_context (决策背景).

2. SELECTION_RATIONALE (选择依据): Why a particular option was chosen over others. The reasoning, criteria, or constraints that drove the decision.
   For each: reason (选择原因), criteria (评判标准, list), trade_offs (权衡取舍, if mentioned).

3. EXECUTION_RESULTS (执行结果): Outcomes, consequences, or results of previously executed decisions or actions.
   For each: result (结果描述), outcome_type (结果类型: success/partial/failure/unknown), lessons (经验教训, if mentioned).

Output ONLY valid JSON. If a category has no findings, return an empty array [].
"""

DECISION_USER_TEMPLATE = """Extract decision records (confirmed plans, selection rationale, execution results) from the following text:

{text}"""

DECISION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed_plans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "plan": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                    "decision_context": {"type": "string"},
                },
                "required": ["plan"],
            },
        },
        "selection_rationale": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "criteria": {"type": "array", "items": {"type": "string"}},
                    "trade_offs": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
        "execution_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                    "outcome_type": {
                        "type": "string",
                        "enum": ["success", "partial", "failure", "unknown"],
                    },
                    "lessons": {"type": "string"},
                },
                "required": ["result", "outcome_type"],
            },
        },
    },
    "required": ["confirmed_plans", "selection_rationale", "execution_results"],
}
