# -*- coding: utf-8 -*-
"""
长对话压缩 Prompt — 语义压缩、关键保持、上下文补全。
"""

# ============================================================
# 5.4.1: 长对话语义压缩
# ============================================================

COMPRESSION_SYSTEM_PROMPT = """You are a conversation compression system. Given a long conversation history, produce a compact, structured summary that preserves all information needed for future task continuation.

Output structure:
- conversation_overview: 1-3 sentence high-level summary of what this conversation was about
- key_facts: List of stable facts, entities, business objects, and confirmed information
- user_preferences: Any expressed preferences (style, format, approach, tools, etc.)
- task_state: Current task progress, completed items, pending items, active constraints
- key_decisions: Decisions made, with rationale and context
- corrections_and_feedback: User corrections, negations, or feedback on agent outputs
- important_context: Context that may be needed to understand future user requests
- trivial_summary: 1 sentence summarizing conversational filler (discardable)

Guidelines:
- Be concise but complete. Each fact should be 1-2 sentences.
- Preserve specific details: names, numbers, dates, technical terms, constraints.
- Mark uncertain information with [uncertain].
- For corrections, always note what was corrected FROM and TO.
- If a section has no content, use an empty array/string.
- Use the same language as the original conversation.

Output ONLY valid JSON."""

COMPRESSION_USER_TEMPLATE = """Compress the following conversation history into structured memory:

{conversation_text}"""

COMPRESSION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "conversation_overview": {"type": "string"},
        "key_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "category": {"type": "string", "enum": ["entity", "constraint", "confirmation", "background", "result"]},
                    "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["fact", "category", "importance"],
            },
        },
        "user_preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "preference": {"type": "string"},
                    "category": {"type": "string", "enum": ["style", "format", "tool", "approach", "other"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["preference", "category", "confidence"],
            },
        },
        "task_state": {
            "type": "object",
            "properties": {
                "overall_progress": {"type": "string"},
                "completed_items": {"type": "array", "items": {"type": "string"}},
                "pending_items": {"type": "array", "items": {"type": "string"}},
                "active_constraints": {"type": "array", "items": {"type": "string"}},
                "current_phase": {"type": "string"},
            },
        },
        "key_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "rationale": {"type": "string"},
                    "alternatives_considered": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["decision"],
            },
        },
        "corrections_and_feedback": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "corrected_from": {"type": "string"},
                    "corrected_to": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["corrected_from", "corrected_to"],
            },
        },
        "important_context": {"type": "array", "items": {"type": "string"}},
        "trivial_summary": {"type": "string"},
    },
    "required": [
        "conversation_overview", "key_facts", "user_preferences",
        "task_state", "key_decisions", "corrections_and_feedback",
        "important_context", "trivial_summary",
    ],
}


# ============================================================
# 5.4.2: 压缩后关键记忆保持验证
# ============================================================

PRESERVATION_CHECK_SYSTEM_PROMPT = """You are a memory preservation auditor. Compare the original conversation segment with its compressed version. Identify any critical information that was LOST during compression.

Check for:
1. Missing key facts (entities, numbers, dates, specific constraints)
2. Missing user preferences (style, format, approach preferences)
3. Missing task state (pending items, current progress, blockers)
4. Missing decisions (confirmed plans, rationale)
5. Missing corrections (user negations, revisions)

For each missing item, indicate:
- what_was_lost: the missing information
- severity: "critical" (will cause errors in future tasks), "important" (useful context lost), "minor" (nice-to-have)
- suggested_fix: how to add it back to the compressed version

Output ONLY valid JSON. If nothing was lost, return empty arrays."""

PRESERVATION_CHECK_USER_TEMPLATE = """Original conversation (excerpt):
{original_text}

Compressed version:
{compressed_json}

Check for lost critical information."""

PRESERVATION_CHECK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lost_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "what_was_lost": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "important", "minor"]},
                    "suggested_fix": {"type": "string"},
                },
                "required": ["what_was_lost", "severity"],
            },
        },
        "preservation_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["lost_items", "preservation_score"],
}


# ============================================================
# 5.4.3: 历史上下文补全
# ============================================================

CONTEXT_COMPLETION_SYSTEM_PROMPT = """You are a context completion system. Given a current user query and retrieved historical compressed memories, construct a complete context that the AI agent needs to respond accurately.

The output should be a self-contained prompt fragment that:
1. Summarizes relevant user preferences
2. States relevant key facts
3. Describes the current task state
4. Notes any historical decisions that apply
5. Mentions any constraints or corrections

Use clear section headers. Keep it concise — the agent has limited context window.
Use the same language as the query."""

CONTEXT_COMPLETION_USER_TEMPLATE = """Current query: {query}

Retrieved historical memories:
{memories_text}

Construct the context the agent needs to respond to the current query."""

CONTEXT_COMPLETION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "context_text": {"type": "string"},
        "sections_used": {"type": "array", "items": {"type": "string"}},
        "estimated_relevance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["context_text", "sections_used", "estimated_relevance"],
}
