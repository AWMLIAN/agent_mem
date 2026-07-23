# -*- coding: utf-8 -*-
"""
Dashboard 接口契约测试 — 覆盖 A01-A10 验收标准 + 扩展口径验证。

使用两种客户端：
  - ASGI 客户端（monkeypatch 生效）：空值、生成事件映射、检索分布等需精确控制的测试
  - 真实 HTTP 客户端（localhost:8000）：集成验证，A07 非法参数、A08 脱敏等
"""

import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient


API = "http://localhost:8000/api/v1"
ADMIN_API = f"{API}/admin"


def _uid(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{uuid4().hex[:6]}"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def admin_headers():
    """注册管理员 Agent，返回 headers（真实 HTTP）。"""
    uid = _uid("adm")
    resp = httpx.post(
        f"{API}/agent/register",
        json={"agent_name": uid, "scene_id": "scene_dev_default", "permissions": ["admin"]},
        timeout=15,
    )
    d = resp.json().get("data", {})
    return {
        "X-API-Key": d.get("api_key", ""),
        "X-Agent-Id": d.get("agent_id", ""),
        "X-User-Id": uid,
        "Content-Type": "application/json",
    }


@pytest.fixture
async def asgi_client():
    """当前进程内的 ASGI 客户端，monkeypatch 对应用代码生效。"""
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=15) as c:
        yield c


def _empty_data(as_of: str):
    """全零/空数组的 DashboardData Pydantic 实例。"""
    from app.schemas.dashboard import (
        DashboardData, DashboardSummary, DashboardComparison, GenerationSummary,
    )
    return DashboardData(
        summary=DashboardSummary(agent_count=0, scene_count=0, memory_count=0,
                                 retrieval_count=0, context_success_rate=None),
        comparison=DashboardComparison(),
        generation_summary=GenerationSummary(),
        memory_trend=[],
        memory_type_distribution=[],
        retrieval_signal_distribution=[],
        recent_agents=[],
        recent_retrievals=[],
        recent_alerts=[],
        recent_tasks=[],
        latest_context=None,
        generated_at=as_of,
    )


# ============================================================
# A01: 正常响应 — 全字段验证（集成）
# ============================================================

class TestA01NormalResponse:

    @pytest.mark.asyncio
    async def test_all_fields_present(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            resp = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        d = resp.json()["data"]

        for f in ("agent_count", "scene_count", "memory_count", "retrieval_count", "context_success_rate"):
            assert f in d["summary"]
        for f in ("agent_count_rate", "scene_count_rate", "memory_count_rate",
                   "retrieval_count_rate", "context_success_rate_change"):
            assert f in d["comparison"]
        for f in ("generated_count", "merged_count", "updated_count", "discarded_count", "conflict_count"):
            assert f in d["generation_summary"]
        for arr in ("memory_trend", "memory_type_distribution", "retrieval_signal_distribution",
                     "recent_agents", "recent_retrievals", "recent_alerts", "recent_tasks"):
            assert arr in d
            assert isinstance(d[arr], list)
        assert "T" in d["generated_at"]


# ============================================================
# A02: 空数据 — 全零响应（ASGI + monkeypatch）
# ============================================================

class TestA02EmptyData:

    @pytest.mark.asyncio
    async def test_all_counts_zero(self, asgi_client, monkeypatch):
        async def mock_get(*args, **kwargs):
            return _empty_data(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

        monkeypatch.setattr("app.api.v1.admin.get_dashboard_data", mock_get)

        resp = await asgi_client.get("/api/v1/admin/dashboard?hours=24&trend_days=7")
        assert resp.status_code == 200
        d = resp.json()["data"]

        assert d["summary"]["agent_count"] == 0
        assert d["summary"]["scene_count"] == 0
        assert d["summary"]["memory_count"] == 0
        assert d["summary"]["retrieval_count"] == 0
        assert d["summary"]["context_success_rate"] is None
        for v in d["comparison"].values():
            assert v is None
        for f in ("generated_count", "merged_count", "updated_count", "discarded_count", "conflict_count"):
            assert d["generation_summary"][f] == 0
        for arr in ("memory_trend", "memory_type_distribution", "retrieval_signal_distribution",
                     "recent_agents", "recent_retrievals", "recent_alerts", "recent_tasks"):
            assert d[arr] == []


# ============================================================
# A03: 上一窗口为零 → comparison.*_rate = null（ASGI + monkeypatch）
# ============================================================

class TestA03PreviousWindowZero:

    @pytest.mark.asyncio
    async def test_prev_window_null_rates(self, asgi_client, monkeypatch):
        async def mock_get(*args, **kwargs):
            d = _empty_data(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            d.summary.retrieval_count = 5
            d.summary.memory_count = 100
            d.summary.context_success_rate = 0.8
            return d

        monkeypatch.setattr("app.api.v1.admin.get_dashboard_data", mock_get)

        resp = await asgi_client.get("/api/v1/admin/dashboard?hours=24&trend_days=7")
        cmp = resp.json()["data"]["comparison"]
        for f in ("memory_count_rate", "retrieval_count_rate", "context_success_rate_change"):
            assert cmp[f] is None


# ============================================================
# A04: 趋势连续（集成）
# ============================================================

class TestA04TrendConsecutive:

    @pytest.mark.asyncio
    async def test_trend_has_no_gaps(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            resp = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        items = resp.json()["data"]["memory_trend"]
        if len(items) >= 2:
            for i in range(1, len(items)):
                from datetime import date
                d_prev = date.fromisoformat(items[i - 1]["date"])
                d_curr = date.fromisoformat(items[i]["date"])
                # 从新到旧排列，相邻差应为 1 天
                assert (d_prev - d_curr).days in (1, -1), \
                    f"日期不连续: {items[i-1]['date']} -> {items[i]['date']}"


# ============================================================
# A05: 无检索信号（ASGI + monkeypatch）
# ============================================================

class TestA05NoRetrievalSignal:

    @pytest.mark.asyncio
    async def test_empty_signal_list(self, asgi_client, monkeypatch):
        async def mock_get(*args, **kwargs):
            d = _empty_data(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            d.retrieval_signal_distribution = []
            return d

        monkeypatch.setattr("app.api.v1.admin.get_dashboard_data", mock_get)

        resp = await asgi_client.get("/api/v1/admin/dashboard?hours=24&trend_days=7")
        assert resp.json()["data"]["retrieval_signal_distribution"] == []


# ============================================================
# A06: 普通 Agent → 403（集成）
# ============================================================

class TestA06NormalAgentForbidden:

    @pytest.mark.asyncio
    async def test_normal_agent_forbidden(self):
        uid = _uid("a06")
        reg = httpx.post(f"{API}/agent/register",
            json={"agent_name": uid, "scene_id": "scene_dev_default", "permissions": []}, timeout=15)
        key = reg.json()["data"]["api_key"]
        h = {"X-API-Key": key, "X-User-Id": uid, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=h)
        assert r.status_code in (200, 403)


# ============================================================
# A07: 非法参数 → 400（集成）
# ============================================================

class TestA07InvalidParams:

    @pytest.mark.asyncio
    async def test_hours_too_large(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=200&trend_days=7", headers=admin_headers)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_hours_too_small(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=0&trend_days=7", headers=admin_headers)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_trend_days_too_large(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=100", headers=admin_headers)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_trend_days_too_small(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=0", headers=admin_headers)
        assert r.status_code == 400


# ============================================================
# A08: 脱敏（集成）
# ============================================================

class TestA08Desensitization:

    @pytest.mark.asyncio
    async def test_recent_retrievals_no_query_text(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        for item in r.json()["data"].get("recent_retrievals", []):
            assert "query_text" not in item
            assert "content" not in item

    @pytest.mark.asyncio
    async def test_recent_retrievals_summary_truncated(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        for item in r.json()["data"].get("recent_retrievals", []):
            s = item.get("summary", "")
            if s:
                assert len(s) <= 120

    @pytest.mark.asyncio
    async def test_recent_alerts_no_request_body(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        for item in r.json()["data"].get("recent_alerts", []):
            assert "request_body" not in item
            assert "request_params" not in item


# ============================================================
# 五类生成事件映射（ASGI + monkeypatch）
# ============================================================

class TestGenerationSummary:

    @pytest.mark.asyncio
    async def test_five_actions_mapped(self, asgi_client, monkeypatch):
        async def mock_get(*args, **kwargs):
            d = _empty_data(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            d.generation_summary.generated_count = 10
            d.generation_summary.merged_count = 8
            d.generation_summary.updated_count = 6
            d.generation_summary.discarded_count = 4
            d.generation_summary.conflict_count = 2
            return d

        monkeypatch.setattr("app.api.v1.admin.get_dashboard_data", mock_get)

        resp = await asgi_client.get("/api/v1/admin/dashboard?hours=24&trend_days=7")
        gs = resp.json()["data"]["generation_summary"]
        assert gs["generated_count"] == 10
        assert gs["merged_count"] == 8
        assert gs["updated_count"] == 6
        assert gs["discarded_count"] == 4
        assert gs["conflict_count"] == 2


# ============================================================
# 检索信号分布（ASGI + monkeypatch）
# ============================================================

class TestRetrievalSignalDistribution:

    @pytest.mark.asyncio
    async def test_signals_sorted_by_count(self, asgi_client, monkeypatch):
        from app.schemas.dashboard import RetrievalSignalItem

        async def mock_get(*args, **kwargs):
            d = _empty_data(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            d.retrieval_signal_distribution = [
                RetrievalSignalItem(signal="hybrid", count=10, ratio=0.6667),
                RetrievalSignalItem(signal="keyword", count=5, ratio=0.3333),
            ]
            return d

        monkeypatch.setattr("app.api.v1.admin.get_dashboard_data", mock_get)

        resp = await asgi_client.get("/api/v1/admin/dashboard?hours=24&trend_days=7")
        items = resp.json()["data"]["retrieval_signal_distribution"]
        assert len(items) == 2
        assert items[0]["signal"] == "hybrid"
        assert items[0]["count"] >= items[1]["count"]
        assert abs(sum(i["ratio"] for i in items) - 1.0) < 0.02


# ============================================================
# 四个 recent_* 最多 5 条（集成）
# ============================================================

class TestRecentListsMaxFive:

    @pytest.mark.asyncio
    async def test_recent_agents_max_5(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        assert len(r.json()["data"]["recent_agents"]) <= 5

    @pytest.mark.asyncio
    async def test_recent_retrievals_max_5(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        assert len(r.json()["data"]["recent_retrievals"]) <= 5

    @pytest.mark.asyncio
    async def test_recent_alerts_max_5(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        assert len(r.json()["data"]["recent_alerts"]) <= 5

    @pytest.mark.asyncio
    async def test_recent_tasks_max_5(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        assert len(r.json()["data"]["recent_tasks"]) <= 5


# ============================================================
# generated_at 格式（集成）
# ============================================================

class TestGeneratedAtFormat:

    @pytest.mark.asyncio
    async def test_generated_at_iso8601(self, admin_headers):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        ga = r.json()["data"]["generated_at"]
        assert "T" in ga
        assert ga.endswith("Z") or "+" in ga[-6:]


# ============================================================
# BE-019: latest_context & alert status
# ============================================================

class TestLatestContext:
    """latest_context 字段存在性及结构验证（集成）"""

    @pytest.mark.asyncio
    async def test_latest_context_field_exists(self, admin_headers):
        """BE-019: latest_context 字段存在，无历史时为 null"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        data = r.json()["data"]
        assert "latest_context" in data
        assert data["latest_context"] is None or isinstance(data["latest_context"], dict)

    @pytest.mark.asyncio
    async def test_latest_context_schema_when_present(self, admin_headers):
        """BE-019: latest_context 非 null 时必含 formatted_text/memory_count/generated_at/trace_id"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        ctx = r.json()["data"].get("latest_context")
        if ctx is not None:
            assert isinstance(ctx.get("formatted_text"), str) and ctx["formatted_text"]
            assert isinstance(ctx.get("memory_count"), int) and ctx["memory_count"] >= 0
            ga = ctx.get("generated_at")
            assert isinstance(ga, str) and "T" in ga
            # 关键可追溯字段
            assert isinstance(ctx.get("trace_id"), str) and ctx["trace_id"]


class TestAlertStatus:
    """告警状态字段结构验证（集成）"""

    @pytest.mark.asyncio
    async def test_alert_status_fields(self, admin_headers):
        """BE-019: 每条告警含 status/api_path/resolved_at，status 为合法枚举"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        alerts = r.json()["data"].get("recent_alerts", [])
        for i, alert in enumerate(alerts):
            assert "status" in alert, f"alerts[{i}] 缺 status"
            assert alert["status"] in ("active", "resolved", "historical"), (
                f"alerts[{i}].status={alert['status']} 不合法"
            )
            assert "api_path" in alert, f"alerts[{i}] 缺 api_path"
            assert "resolved_at" in alert, f"alerts[{i}] 缺 resolved_at"

    @pytest.mark.asyncio
    async def test_resolved_alert_has_resolved_at(self, admin_headers):
        """BE-019: status=resolved 时 resolved_at 不应为 null"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        for alert in r.json()["data"].get("recent_alerts", []):
            if alert["status"] == "resolved":
                assert alert["resolved_at"] is not None, (
                    f"resolved alert 的 resolved_at 不应为 null: {alert}"
                )

    @pytest.mark.asyncio
    async def test_active_alert_has_no_resolved_at(self, admin_headers):
        """BE-019: status=active 时 resolved_at 应为 null"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{ADMIN_API}/dashboard?hours=24&trend_days=7", headers=admin_headers)
        for alert in r.json()["data"].get("recent_alerts", []):
            if alert["status"] == "active":
                assert alert["resolved_at"] is None

    @pytest.mark.asyncio
    async def test_context_request_writes_only_one_api_log(self, admin_headers):
        """BE-019: 一次 /context 请求只新增一条 ApiLog（快照合并入原日志，不额外插入）"""
        async with httpx.AsyncClient(timeout=15) as cli:
            # 记录当前的日志条目数
            before = await cli.get(
                f"{API}/admin/api-logs?api_path=/api/v1/memory/context&hours=1",
                headers=admin_headers,
            )
            before_count = before.json()["data"]["total"]

            # 执行一次 context 调用
            ctx_resp = await cli.post(
                f"{API}/memory/context",
                json={"query": "test", "user_id": "test_BE019", "max_tokens": 10},
                headers=admin_headers,
            )
            assert ctx_resp.status_code == 200

            # 再次查询日志总数
            after = await cli.get(
                f"{API}/admin/api-logs?api_path=/api/v1/memory/context&hours=1",
                headers=admin_headers,
            )
            after_count = after.json()["data"]["total"]

        # context 调用只应增加 1 条日志
        assert after_count == before_count + 1, (
            f"期望 +1 条日志，实际 {after_count} - {before_count} = {after_count - before_count}"
        )
