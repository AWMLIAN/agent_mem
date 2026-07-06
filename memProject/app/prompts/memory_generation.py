# -*- coding: utf-8 -*-
"""
记忆生成 Prompt — 将抽取结果转化为结构化记忆对象。
"""

MEMORY_GENERATION_SYSTEM_PROMPT = """You are a memory structuring system. Given extracted facts, task states, and decisions from a conversation, generate structured memory entries. Each memory should be a self-contained, useful piece of information for future retrieval.

For each distinct piece of information, produce:
- content: A natural, standalone memory sentence in the appropriate language (Chinese for Chinese content, English for English content). This is the primary retrievable text.
- summary: A concise 1-2 sentence summary of this memory.
- key_points: 2-5 bullet points capturing the essence (as a list of strings).
- memory_type: One of:
  - "fact": Objective facts, business objects, entities
  - "preference": User preferences, habits, likes/dislikes
  - "task_state": Task progress, status, pending items
  - "decision": Confirmed plans, choices, rationales
  - "constraint": Rules, limitations, requirements, deadlines
  - "process": Workflows, procedures, methodologies
- tags: 2-5 relevant tags for categorization and filtering.
- entities: Named entities (people, systems, projects, tools) referenced in this memory.
- importance: 0.0-1.0 float — how critical this information is for future decisions and context.
- confidence: 0.0-1.0 float — how certain/confirmed the information is based on the source text.

Guidelines:
- Group closely related facts into a single memory. Separate unrelated facts into different memories.
- Do NOT generate memories for trivial, conversational filler (greetings, small talk, etc.).
- For task state, create at most ONE memory summarizing the overall task status.
- If the extracted data is empty or contains only noise, return an empty memories array.
- Prioritize information that would be useful in future conversations.

Output ONLY valid JSON: {"memories": [...]}
"""

MEMORY_GENERATION_USER_TEMPLATE = """Generate structured memories from the following extraction results:

## Key Facts Extracted
Business Objects: {business_objects}
Constraints: {constraints}
Confirmations: {confirmations}

## Task State Extracted
Current Progress: {current_progress}
Completed Items: {completed_items}
Pending Items: {pending_items}

## Decisions Extracted
Confirmed Plans: {confirmed_plans}
Selection Rationale: {selection_rationale}
Execution Results: {execution_results}

Generate a list of structured memory entries from this data."""

MEMORY_GENERATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "memory_type": {
                        "type": "string",
                        "enum": [
                            "fact",
                            "preference",
                            "task_state",
                            "decision",
                            "constraint",
                            "process",
                        ],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": [
                    "content",
                    "summary",
                    "key_points",
                    "memory_type",
                    "tags",
                    "entities",
                    "importance",
                    "confidence",
                ],
            },
        }
    },
    "required": ["memories"],
}
