"""直接测试 OpenMemory MCP 连接"""
import asyncio, json
from fastmcp import Client

async def test():
    url = "http://localhost:8765/mcp/memproject/http/u1"
    print("Connect:", url)
    async with Client(url) as c:
        # add
        r = await c.call_tool("add_memories", {"text": "my name is Alice", "infer": True})
        print("add:", r.content[0].text[:200])

        # search
        r = await c.call_tool("search_memory", {"query": "what is my name"})
        print("search:", r.content[0].text[:200])

asyncio.run(test())
