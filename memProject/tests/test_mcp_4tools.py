"""直接测试 OpenMemory MCP 4 个工具"""
import asyncio
import json
import sys
import uuid

from fastmcp import Client

# Windows GBK 环境下强制 stdout 使用 UTF-8，避免特殊字符编码报错
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 每次运行使用唯一 UID，避免历史记忆导致去重返回空结果
UID = f"test_mcp_{uuid.uuid4().hex[:8]}"


def _safe_call_result(r) -> dict:
    """安全解析 MCP tool 返回的 JSON 字符串为 dict。"""
    text = r.content[0].text
    if text.startswith("Error:"):
        return {"_error": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


async def main():
    print(f"UID: {UID}")
    print(f"MCP URL: http://localhost:8765/mcp/memproject/http/{UID}\n")

    async with Client(f"http://localhost:8765/mcp/memproject/http/{UID}") as c:

        # ── 1. add_memories ──────────────────────────────────────────
        print("=== 1. add_memories (x2) ===")
        for text in ["我叫李四，喜欢简短回复", "我是前端工程师，常用React"]:
            r = await c.call_tool("add_memories", {"text": text, "infer": True})
            data = _safe_call_result(r)
            if "_error" in data:
                print(f"  X {text[:20]}... -> ERROR: {data['_error']}")
                continue
            results = data.get("results", [])
            if results:
                for mem in results:
                    print(f"  OK [{mem.get('event','?')}] {mem.get('memory','')[:80]}")
            else:
                print(f"  (skip) '{text[:20]}...' 未提取出新记忆（可能已存在相似内容）")

        # ── 2. list_memories ────────────────────────────────────────
        print("\n=== 2. list_memories ===")
        r = await c.call_tool("list_memories", {})
        data = _safe_call_result(r)
        if isinstance(data, list):
            print(f"  共 {len(data)} 条记忆")
            for item in data[:5]:
                print(f"  - {item.get('memory','')[:80]}")
        elif "_error" in data:
            print(f"  ERROR: {data['_error']}")
        else:
            print(f"  {data}")

        # ── 3. search_memory ────────────────────────────────────────
        print("\n=== 3. search_memory ===")
        r = await c.call_tool("search_memory", {"query": "用户叫什么名字"})
        data = _safe_call_result(r)
        results = data.get("results", [])
        print(f"  找到 {len(results)} 条结果")
        for item in results[:3]:
            print(f"  - [{item.get('score',0):.3f}] {item.get('memory','')[:80]}")

        # ── 4. delete_all_memories ──────────────────────────────────
        print("\n=== 4. delete_all_memories ===")
        r = await c.call_tool("delete_all_memories", {})
        print(f"  {r.content[0].text}")

        # ── 5. 验证清空 ─────────────────────────────────────────────
        print("\n=== 5. 验证清空 ===")
        r = await c.call_tool("list_memories", {})
        data = _safe_call_result(r)
        count = len(data) if isinstance(data, list) else 0
        print(f"  剩余 {count} 条记忆")

asyncio.run(main())
