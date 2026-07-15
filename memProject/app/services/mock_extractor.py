# -*- coding: utf-8 -*-
"""
Mock 提取器 — 基于中文正则规则的记忆提取（开发期使用）。

供 memory.py 和 mq_consumer.py 共用，避免循环导入。
"""

import re as re_module
from uuid import uuid4


# Mock 提取规则：匹配中文自我描述、目标、提醒等
_MOCK_PATTERNS: list[tuple[str, str]] = [
    # (正则模式, 记忆类别标签)
    (r"(?:我是|我叫|我的名字是)\s*(.+?)(?:，|。|$)", "identity"),
    (r"(?:记住|别忘了|请记住)\s*(.+?)(?:，|。|$)", "reminder"),
    (r"(?:提醒我|下次提醒我)\s*(.+?)(?:，|。|$)", "reminder"),
    (r"(?:我的任务是|任务[：:]\s*|目标是|目标[：:]\s*)(.+?)(?:，|。|$)", "task"),
    (r"(?:需要完成|需要做|要做)\s*(.+?)(?:，|。|$)", "task"),
    (r"(?:完成了|已经完成|做完了)\s*(.+?)(?:，|。|$)", "progress"),
    (r"(?:我喜欢|我喜欢吃|我爱好|我的爱好是)\s*(.+?)(?:，|。|$)", "preference"),
    (r"(?:我不喜欢|我讨厌|我不爱吃)\s*(.+?)(?:，|。|$)", "preference"),
    (r"(?:我决定|我选择|我打算|我计划)\s*(.+?)(?:，|。|$)", "decision"),
    (r"(?:我的|我的地址是|我的电话是|我在)\s*(.+?)(?:，|。|$)", "fact"),
]


def mock_extract_results(messages: list) -> list[dict]:
    """
    使用正则规则从消息中提取记忆片段（Mock 模式）。

    每条消息尝试匹配所有规则，匹配成功则添加 ADD 事件，
    未匹配到任何规则则添加 SKIP 事件。

    Args:
        messages: MemoryWriteRequest.messages 或纯 dict 列表 [{role, content}, ...]

    Returns:
        [{id, memory, event}, ...]
    """
    results = []
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")

        # 只处理 user 和 agent/assistant 角色的消息
        if role.lower() not in ("user", "agent", "assistant"):
            results.append({"id": "", "memory": "", "event": "SKIP"})
            continue

        matched = False
        for pattern, category in _MOCK_PATTERNS:
            m = re_module.search(pattern, content)
            if m:
                extracted = m.group(1).strip()
                if extracted:
                    mem_id = f"mock_{uuid4().hex[:16]}"
                    results.append({
                        "id": mem_id,
                        "memory": f"[{category}] {extracted}",
                        "event": "ADD",
                    })
                    matched = True
                    break  # 每条消息只匹配第一条规则

        if not matched:
            results.append({"id": "", "memory": "", "event": "SKIP"})

    return results
