# -*- coding: utf-8 -*-
"""
过程信息抽取 Prompt — 从对话中提取智能体执行动作、工具调用、中间结论。
"""

PROCESS_SYSTEM_PROMPT = """You are a precise process information extraction system specialized in analyzing agent execution traces from conversation logs (Chinese and English). Extract three categories of process information from the text:

1. EXECUTION ACTIONS (执行动作): Actions the agent performed — searching, analyzing, computing, calling tools, querying databases, generating content, etc.
   For each: action_name (动作名称), action_type (类型: search/analyze/compute/tool_call/generate/query), input_summary (输入摘要), output_summary (输出摘要), tool_name (工具名称, if applicable).

2. INTERMEDIATE CONCLUSIONS (中间结论): Interim findings, partial results, or阶段性判断 made during task execution.
   For each: conclusion (结论内容), basis (依据 — what evidence led to this conclusion), confidence (置信度 0.0-1.0), is_final (是否为最终结论: true/false).

3. FAILURE RECORDS (失败记录): Errors, failures, retries, or unexpected results encountered during execution.
   For each: failure_point (失败点 — what failed), failure_reason (失败原因), attempted_recovery (尝试的恢复措施), was_resolved (是否已解决: true/false), lesson_learned (经验教训).

Output ONLY valid JSON. If a category has no findings, return an empty array [].
"""

PROCESS_USER_TEMPLATE = """Extract process information (execution actions, intermediate conclusions, failure records) from the following text:

{text}"""

PROCESS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "execution_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_name": {"type": "string"},
                    "action_type": {"type": "string", "enum": ["search", "analyze", "compute", "tool_call", "generate", "query"]},
                    "input_summary": {"type": "string"},
                    "output_summary": {"type": "string"},
                    "tool_name": {"type": "string"},
                },
                "required": ["action_name", "action_type"],
            },
        },
        "intermediate_conclusions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "conclusion": {"type": "string"},
                    "basis": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "is_final": {"type": "boolean"},
                },
                "required": ["conclusion", "confidence", "is_final"],
            },
        },
        "failure_records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "failure_point": {"type": "string"},
                    "failure_reason": {"type": "string"},
                    "attempted_recovery": {"type": "string"},
                    "was_resolved": {"type": "boolean"},
                    "lesson_learned": {"type": "string"},
                },
                "required": ["failure_point", "failure_reason", "was_resolved"],
            },
        },
    },
    "required": ["execution_actions", "intermediate_conclusions", "failure_records"],
}
