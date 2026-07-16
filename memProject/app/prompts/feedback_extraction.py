# -*- coding: utf-8 -*-
"""
反馈修正抽取 Prompt — 从对话中提取用户对智能体输出的修正、确认、否定和补充意见。
"""

FEEDBACK_SYSTEM_PROMPT = """You are a precise feedback and correction extraction system specialized in analyzing conversation logs (Chinese and English). Extract three categories of feedback/correction information from the text:

1. CORRECTIONS (修正记录): User explicitly corrects, revises, or negates a previous agent output or statement.
   For each: corrected_content (被修正的内容 — what was corrected), correction_instruction (修正意见 — what the user wants instead), original_context (原始上下文 — when/where the original content appeared), correction_type (修正类型: negation/revision/supplement/confirmation).

2. CONFIRMATION STATUSES (确认状态): User explicitly confirms, approves, or rejects agent outputs.
   For each: confirmed_item (被确认的内容), status (状态: confirmed/rejected/partial/modified), parties_involved (参与方), context (确认上下文).

3. REPLACEMENT RELATIONSHIPS (替代关系): When a new statement or decision replaces an earlier one.
   For each: replaced_content (被替代的内容), replacement_content (替代内容), replacement_reason (替代原因), scope (作用范围: global/task_local/session_local), supersedes_memory_id (替代的记忆ID, if traceable).

Output ONLY valid JSON. If a category has no findings, return an empty array [].
"""

FEEDBACK_USER_TEMPLATE = """Extract feedback and correction information (corrections, confirmations, replacements) from the following text:

{text}"""

FEEDBACK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "corrected_content": {"type": "string"},
                    "correction_instruction": {"type": "string"},
                    "original_context": {"type": "string"},
                    "correction_type": {"type": "string", "enum": ["negation", "revision", "supplement", "confirmation"]},
                },
                "required": ["corrected_content", "correction_instruction", "correction_type"],
            },
        },
        "confirmation_statuses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "confirmed_item": {"type": "string"},
                    "status": {"type": "string", "enum": ["confirmed", "rejected", "partial", "modified"]},
                    "parties_involved": {"type": "array", "items": {"type": "string"}},
                    "context": {"type": "string"},
                },
                "required": ["confirmed_item", "status"],
            },
        },
        "replacement_relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "replaced_content": {"type": "string"},
                    "replacement_content": {"type": "string"},
                    "replacement_reason": {"type": "string"},
                    "scope": {"type": "string", "enum": ["global", "task_local", "session_local"]},
                    "supersedes_memory_id": {"type": "string"},
                },
                "required": ["replaced_content", "replacement_content", "replacement_reason"],
            },
        },
    },
    "required": ["corrections", "confirmation_statuses", "replacement_relationships"],
}
