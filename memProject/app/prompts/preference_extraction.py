# -*- coding: utf-8 -*-
"""
偏好抽取 Prompt — 从对话中提取用户偏好、使用习惯、决策倾向。
"""

PREFERENCE_SYSTEM_PROMPT = """You are a precise user preference extraction system specialized in analyzing conversation logs (Chinese and English). Extract three categories of user preferences from the text:

1. STYLE PREFERENCES (表达风格偏好): User's preferred communication style, tone, formality level, output format, or language preferences.
   For each: preference_object (偏好对象, e.g. "表达风格"/"输出格式"/"语言"), preference_content (具体偏好内容), applicable_scenario (适用场景), confidence (置信度 0.0-1.0).

2. HABITUAL PREFERENCES (使用习惯偏好): User's habits, workflow patterns, tool preferences, interaction frequency preferences, or process preferences.
   For each: preference_object (偏好对象), preference_content (具体偏好内容), applicable_scenario (适用场景), confidence (置信度 0.0-1.0).

3. DECISION TENDENCIES (决策倾向): User's tendencies in making choices — risk attitude, priority criteria, trade-off patterns, or evaluation preferences.
   For each: tendency_type (倾向类型: risk_attitude/priority_criteria/trade_off/evaluation), tendency_content (具体倾向内容), evidence (支撑证据 — what the user said or did that reveals this tendency), confidence (置信度 0.0-1.0).

Output ONLY valid JSON. If a category has no findings, return an empty array [].
"""

PREFERENCE_USER_TEMPLATE = """Extract user preferences (style, habits, decision tendencies) from the following text:

{text}"""

PREFERENCE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "style_preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "preference_object": {"type": "string"},
                    "preference_content": {"type": "string"},
                    "applicable_scenario": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["preference_object", "preference_content", "confidence"],
            },
        },
        "habitual_preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "preference_object": {"type": "string"},
                    "preference_content": {"type": "string"},
                    "applicable_scenario": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["preference_object", "preference_content", "confidence"],
            },
        },
        "decision_tendencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tendency_type": {"type": "string", "enum": ["risk_attitude", "priority_criteria", "trade_off", "evaluation"]},
                    "tendency_content": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["tendency_type", "tendency_content", "confidence"],
            },
        },
    },
    "required": ["style_preferences", "habitual_preferences", "decision_tendencies"],
}
