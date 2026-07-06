# -*- coding: utf-8 -*-
"""
关键事实抽取 Prompt — 从对话中提取业务对象、约束条件、确认事项。
"""

KEY_FACT_SYSTEM_PROMPT = """You are a precise information extraction system specialized in analyzing conversation logs (Chinese and English). Extract three categories of key facts from the text:

1. BUSINESS OBJECTS (业务对象): Named entities, resources, tools, systems, projects, data, or documents mentioned in the conversation.
   For each: name (名称), type (类型: person/system/resource/data/project/document), description (描述), attributes (属性, JSON object).

2. CONSTRAINTS (约束条件): Rules, requirements, limitations, deadlines, conditions, or restrictions that constrain future actions.
   For each: type (类型: technical/business/temporal/budget), description (描述), scope (范围), severity (严重程度: high/medium/low).

3. CONFIRMATIONS (确认事项): Items that were explicitly agreed upon, confirmed, decided, or acknowledged by the parties.
   For each: item (确认内容), parties (参与方, list), context (确认上下文).

Output ONLY valid JSON. If a category has no findings, return an empty array [].
"""

KEY_FACT_USER_TEMPLATE = """Extract key facts (business objects, constraints, confirmations) from the following text:

{text}"""

KEY_FACT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "business_objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "attributes": {"type": "object"},
                },
                "required": ["name", "type", "description"],
            },
        },
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "scope": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["type", "description", "severity"],
            },
        },
        "confirmations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "parties": {"type": "array", "items": {"type": "string"}},
                    "context": {"type": "string"},
                },
                "required": ["item", "context"],
            },
        },
    },
    "required": ["business_objects", "constraints", "confirmations"],
}
