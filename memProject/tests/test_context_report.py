# -*- coding: utf-8 -*-
"""
验收测试 — POST /memory/context + /memory/search 上下文与检索接口。

使用 context_test_data fixture 提供 20 条确定性记忆。
"""

import httpx
import pytest

API = "http://localhost:8000/api/v1"


class TestMemoryContext:
    """记忆上下文与检索接口验收测试"""

    async def test_01_relevance_filter(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户偏好编程", "user_id": uid, "top_k": 3},
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"].get("results", [])) > 0

    async def test_02_type_filter_preference(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "memory_types": ["preference"], "top_k": 10},
                headers=headers,
            )
        data = resp.json()
        results = data["data"].get("results", [])
        assert len(results) >= 3
        assert all(r["memory_type"] == "preference" for r in results)

    async def test_02_type_filter_fact(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "memory_types": ["fact"], "top_k": 10},
                headers=headers,
            )
        data = resp.json()
        results = data["data"].get("results", [])
        assert len(results) >= 3
        assert all(r["memory_type"] == "fact" for r in results)

    async def test_04_top_k_2(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "top_k": 2},
                headers=headers,
            )
        assert len(resp.json()["data"].get("results", [])) == 2

    async def test_04_top_k_5(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "top_k": 5},
                headers=headers,
            )
        assert len(resp.json()["data"].get("results", [])) == 5

    async def test_07_json_structure(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "top_k": 1},
                headers=headers,
            )
        data = resp.json()
        results = data["data"].get("results", [])
        assert len(results) > 0
        required = ["memory_id", "memory_type", "relevance_score", "created_at",
                     "content", "summary", "key_points", "agent_id", "source_type", "status"]
        missing = [f for f in required if f not in results[0]]
        assert not missing, f"缺少字段: {missing}"

    async def test_10_context_aggregation(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/context",
                json={
                    "query": "用户偏好编程",
                    "user_id": uid, "max_tokens": 500, "top_k": 5,
                    "include_preferences": True, "include_facts": True,
                },
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        ctx = data["data"]
        assert ctx.get("aggregation", {}).get("type") == "user_profile"
        assert len(ctx.get("formatted_text", "")) > 0

    async def test_10_context_preferences(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/context",
                json={
                    "query": "用户偏好", "user_id": uid, "max_tokens": 500,
                    "include_preferences": True,
                },
                headers=headers,
            )
        agg = resp.json()["data"].get("aggregation", {})
        assert len(agg.get("preferences", [])) >= 3

    async def test_10_context_facts(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/context",
                json={
                    "query": "用户信息", "user_id": uid, "max_tokens": 500,
                    "include_facts": True,
                },
                headers=headers,
            )
        agg = resp.json()["data"].get("aggregation", {})
        assert len(agg.get("facts", [])) >= 3

    async def test_16_retrieval_log(self, context_test_data):
        uid, headers, memories = context_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": uid, "top_k": 3},
                headers=headers,
            )
        data = resp.json()
        assert data["code"] == 0
        assert data["data"].get("elapsed_ms", 0) > 0

    async def test_19_empty_result(self):
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "用户", "user_id": "nonexistent_user_xyz", "top_k": 3},
                headers={"X-Agent-Id": "agent_test_fixture", "Content-Type": "application/json"},
            )
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"].get("results", [])) == 0

    async def test_20_error_code_missing_param(self):
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={"query": "test"},
                headers={"X-Agent-Id": "agent_test_fixture", "Content-Type": "application/json"},
            )
        data = resp.json()
        assert data["code"] == -1
        assert data.get("error_code") == "INVALID_PARAM"

    async def test_21_error_empty_body(self):
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/search",
                json={},
                headers={"X-Agent-Id": "agent_test_fixture", "Content-Type": "application/json"},
            )
        data = resp.json()
        assert data["code"] == -1
        assert data.get("error_code") == "INVALID_PARAM"
