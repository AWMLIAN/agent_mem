"""直接测试 OpenMemory MCP 4 个工具"""
import asyncio, json
from fastmcp import Client

UID = "test_mcp_001"

async def main():
    async with Client(f"http://localhost:8765/mcp/memproject/http/{UID}") as c:

        # 1. add_memories
        print("=== 1. add_memories (x2) ===")
        for text in ["我叫李四，喜欢简短回复", "我是前端工程师，常用React"]:
            r = await c.call_tool("add_memories", {"text": text, "infer": True})
            data = json.loads(r.content[0].text)
            print(f"  写入 '{text[:15]}...': {data.get('results', [{}])[0].get('event','?')} - {data.get('results', [{}])[0].get('memory','')[:60]}")

        # 2. list_memories
        print("\n=== 2. list_memories ===")
        r = await c.call_tool("list_memories", {})
        data = json.loads(r.content[0].text)
        if isinstance(data, list):
            print(f"  共 {len(data)} 条记忆")
            for item in data[:5]:
                print(f"  - {item.get('memory','')[:80]}")
        else:
            print(f"  {data}")

        # 3. search_memory
        print("\n=== 3. search_memory ===")
        r = await c.call_tool("search_memory", {"query": "用户叫什么名字"})
        data = json.loads(r.content[0].text)
        results = data.get("results", [])
        print(f"  找到 {len(results)} 条结果")
        for item in results[:3]:
            print(f"  - [{item.get('score',0):.3f}] {item.get('memory','')[:80]}")

        # 4. delete_all_memories
        print("\n=== 4. delete_all_memories ===")
        r = await c.call_tool("delete_all_memories", {})
        print(f"  {r.content[0].text}")

        # 5. 验证清空
        print("\n=== 5. 验证清空 ===")
        r = await c.call_tool("list_memories", {})
        data = json.loads(r.content[0].text)
        count = len(data) if isinstance(data, list) else 0
        print(f"  剩余 {count} 条记忆")

asyncio.run(main())
