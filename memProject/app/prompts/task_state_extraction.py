# -*- coding: utf-8 -*-
"""
任务状态抽取 Prompt — 从对话中提取当前进展、已完成内容、待处理事项。
"""

TASK_STATE_SYSTEM_PROMPT = """You are a task tracking analyst. Analyze the conversation to extract task execution state:

1. CURRENT_PROGRESS (当前进展): A concise description of where the task stands right now. Summarize what phase or step is currently in progress.

2. COMPLETED_ITEMS (已完成内容): Deliverables, milestones, subtasks, or work items that have been finished.
   For each: item (已完成的事项描述), evidence (文本中的证据), completion_note (完成备注).

3. PENDING_ITEMS (待处理事项): Work still to be done, blockers, next steps, or upcoming tasks.
   For each: item (待处理事项描述), priority (优先级: high/medium/low), dependencies (依赖项, if mentioned).

Output ONLY valid JSON. If a category has no content, use empty string for current_progress and empty arrays for items.
"""

TASK_STATE_USER_TEMPLATE = """Extract task state information (current progress, completed items, pending items) from the following text:

{text}

Additional task context (if available):
{task_context}"""

TASK_STATE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "current_progress": {"type": "string"},
        "completed_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "evidence": {"type": "string"},
                    "completion_note": {"type": "string"},
                },
                "required": ["item"],
            },
        },
        "pending_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "dependencies": {"type": "string"},
                },
                "required": ["item", "priority"],
            },
        },
    },
    "required": ["current_progress", "completed_items", "pending_items"],
}
