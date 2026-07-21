# -*- coding: utf-8 -*-
"""
验收测试 — GET /memory/stats 层级统计接口。

使用 stats_test_data fixture 提供确定性测试数据，不依赖外部环境。
7 项测试覆盖：正常响应、缺失参数、ratio、与 list 一致、scene_id 过滤、
memory_scope 过滤、响应包含 memory_scope 字段。
"""

import httpx
import pytest

API = "http://localhost:8000/api/v1"


class TestMemoryStats:
    """记忆层级统计接口验收测试"""

    async def test_01_normal_response(self, stats_test_data):
        """A01: 正常响应 — 全部字段存在且结构正确"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.get(f"{API}/memory/stats?user_id={uid}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        dist = data["level_distribution"]

        assert data["total"] >= 0
        assert data["total"] == sum(lv["count"] for lv in dist)
        assert len(dist) == 4
        assert [lv["level"] for lv in dist] == ["user", "session", "task", "agent"]
        assert data["classification_version"] == "memory_scope_v1"
        assert "generated_at" in data

    async def test_02_missing_user_id(self):
        """A02: 缺少 user_id → HTTP 400/422"""
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.get(f"{API}/memory/stats")
        assert resp.status_code in (400, 422)

    async def test_03_ratio_sum(self, stats_test_data):
        """A03: ratio 总和 ≈ 1（有数据时）"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.get(f"{API}/memory/stats?user_id={uid}", headers=headers)
        dist = resp.json()["data"]["level_distribution"]
        total_ratio = sum(lv["ratio"] for lv in dist)
        assert abs(total_ratio - 1.0) < 0.001

    async def test_04_stats_total_equals_list_total(self, stats_test_data):
        """A04: stats.total == list.total（口径一致）"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            stats_resp = await cli.get(f"{API}/memory/stats?user_id={uid}", headers=headers)
            list_resp = await cli.post(
                f"{API}/memory/list?user_id={uid}&page=1&page_size=1",
                headers=headers,
            )
        stats_total = stats_resp.json()["data"]["total"]
        list_total = list_resp.json()["data"]["total"]
        assert stats_total == list_total, f"stats={stats_total} != list={list_total}"

    async def test_05_scene_id_filter(self, stats_test_data):
        """A05: scene_id 过滤后正常"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.get(
                f"{API}/memory/stats?user_id={uid}&scene_id={headers['X-Scene-Id']}",
                headers=headers,
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_06_list_memory_scope_filter(self, stats_test_data):
        """A06: list 接口 memory_scope 过滤"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/list?user_id={uid}&memory_scope=task&page=1&page_size=10",
                headers=headers,
            )
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["total"] >= 3

    async def test_07_list_item_contains_memory_scope(self, stats_test_data):
        """A07: 列表项包含 memory_scope 字段"""
        uid, headers, memories, total_active = stats_test_data
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{API}/memory/list?user_id={uid}&page=1&page_size=5",
                headers=headers,
            )
        body = resp.json()
        assert body["code"] == 0
        items = body["data"]["items"]
        assert len(items) > 0, "应有记忆数据"
        for item in items[:3]:
            assert "memory_scope" in item, f"缺少 memory_scope: keys={list(item.keys())}"
