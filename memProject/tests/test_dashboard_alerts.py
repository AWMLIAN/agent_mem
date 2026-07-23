# -*- coding: utf-8 -*-
"""
告警状态逻辑单元测试 — 确定时间线，不依赖数据库。

通过 mock db.execute 的返回数据，测试 _compute_recent_alerts 在
固定时间轴下的 active / resolved / historical 判定是否准确。
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.dashboard import RecentAlertItem
from app.services.dashboard_service import _compute_latest_context, _compute_recent_alerts


def _make_row(**kwargs):
    """创建一个属性可读的 mock 行对象。"""
    row = Mock(spec=[])
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _make_result(rows: list):
    """db.execute 返回的 Result-like mock。"""
    result = Mock()
    result.all.return_value = rows
    return result


class TestAlertTimeline:
    """固定时间线场景，验证告警状态派发逻辑。"""

    T = datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc)  # 基准时间

    def _ts(self, minute: int) -> datetime:
        """生成基准时间 + minute 偏移的时间戳。"""
        return self.T + timedelta(minutes=minute)

    def _build_db(self, error_rows: list, history_rows: list) -> AsyncMock:
        """构造 AsyncSession mock，两次 execute 分别返回错误行和历史行。"""
        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock()
        # 第 1 次调用返回 error rows，第 2 次返回 history rows
        db.execute.side_effect = [
            _make_result(error_rows),
            _make_result(history_rows),
        ]
        return db

    @pytest.mark.asyncio
    async def test_single_error_resolved_by_subsequent_success(self):
        """单条错误 + 后续同路径 2xx → resolved"""
        err_t = self._ts(1)  # 10:01 500
        ok_t = self._ts(5)   # 10:05 200

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=err_t, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=err_t, response_code=500),
                _make_row(api_path="/test", created_at=ok_t, response_code=200),
            ],
        )
        alerts = await _compute_recent_alerts(db, as_of=self._ts(60))
        assert len(alerts) == 1
        assert alerts[0].status == "resolved"
        assert alerts[0].resolved_at == ok_t
        assert alerts[0].api_path == "/test"

    @pytest.mark.asyncio
    async def test_recent_unresolved_is_active(self):
        """错误后无成功，30 分钟内 → active"""
        err_t = self._ts(3)   # 10:03 500
        as_of = self._ts(15)  # 10:15 (< 30 min)

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=err_t, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=err_t, response_code=500),
            ],
        )
        alerts = await _compute_recent_alerts(db, as_of=as_of)
        assert len(alerts) == 1
        assert alerts[0].status == "active"
        assert alerts[0].resolved_at is None

    @pytest.mark.asyncio
    async def test_old_unresolved_is_historical(self):
        """错误后无成功，超过 30 分钟 → historical"""
        err_t = self._ts(3)   # 10:03 500
        as_of = self._ts(50)  # 10:50 (> 30 min, but as_of here doesn't affect the `now` check)
        # The function uses datetime.now() for the "recent" check, not as_of
        # So I need to patch datetime.now instead

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=err_t, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=err_t, response_code=500),
            ],
        )

        # Patch datetime.now to return a time >30 min after the error
        far_time = self._ts(45)  # 10:45, 42 min after error
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("app.services.dashboard_service.datetime", _FixedDatetime(far_time))
            alerts = await _compute_recent_alerts(db, as_of=as_of)

        assert len(alerts) == 1
        assert alerts[0].status == "historical"
        assert alerts[0].resolved_at is None

    @pytest.mark.asyncio
    async def test_consecutive_failures_only_latest_active(self):
        """同路径连续 3 次失败, 无后续成功, 仅最新一条为 active"""
        t1 = self._ts(1)   # 10:01 500
        t2 = self._ts(2)   # 10:02 500
        t3 = self._ts(3)   # 10:03 500 (latest)
        as_of = self._ts(20)  # 10:20 (within 30 min of t3)

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e3", api_path="/test", error_code="ERR",
                          trace_id="t3", created_at=t3, response_code=500),
                _make_row(log_id="e2", api_path="/test", error_code="ERR",
                          trace_id="t2", created_at=t2, response_code=500),
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=t1, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=t1, response_code=500),
                _make_row(api_path="/test", created_at=t2, response_code=500),
                _make_row(api_path="/test", created_at=t3, response_code=500),
            ],
        )

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("app.services.dashboard_service.datetime", _FixedDatetime(as_of))
            alerts = await _compute_recent_alerts(db, as_of=self._ts(60))

        assert len(alerts) == 3
        statuses = {a.trace_id: a.status for a in alerts}
        assert statuses["t3"] == "active", "最新错误应为 active"
        assert statuses["t2"] == "historical", "中间错误应为 historical"
        assert statuses["t1"] == "historical", "最早错误应为 historical"

    @pytest.mark.asyncio
    async def test_consecutive_failures_then_success_only_latest_resolved(self):
        """同路径 3 次失败后出现成功, 仅最新一条 resolved, 其余 historical"""
        t1 = self._ts(1)  # 10:01 500
        t2 = self._ts(2)  # 10:02 500
        t3 = self._ts(3)  # 10:03 500 (latest)
        ok = self._ts(5)  # 10:05 200

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e3", api_path="/test", error_code="ERR",
                          trace_id="t3", created_at=t3, response_code=500),
                _make_row(log_id="e2", api_path="/test", error_code="ERR",
                          trace_id="t2", created_at=t2, response_code=500),
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=t1, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=t1, response_code=500),
                _make_row(api_path="/test", created_at=t2, response_code=500),
                _make_row(api_path="/test", created_at=t3, response_code=500),
                _make_row(api_path="/test", created_at=ok, response_code=200),
            ],
        )

        alerts = await _compute_recent_alerts(db, as_of=self._ts(60))

        assert len(alerts) == 3
        statuses = {a.trace_id: (a.status, a.resolved_at) for a in alerts}
        # After post-processing: only latest (t3) keeps resolved
        assert statuses["t3"] == ("resolved", ok), "最新错误应为 resolved"
        assert statuses["t2"][0] == "historical", "中间错误降为 historical"
        assert statuses["t1"][0] == "historical", "最早错误降为 historical"

    @pytest.mark.asyncio
    async def test_success_on_other_path_does_not_resolve(self):
        """A 路径的成功不影响 B 路径的告警状态"""
        err_t = self._ts(1)  # 10:01 /test 500
        ok_other = self._ts(5)  # 10:05 /other 200

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=err_t, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=err_t, response_code=500),
                _make_row(api_path="/other", created_at=ok_other, response_code=200),
            ],
        )

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("app.services.dashboard_service.datetime", _FixedDatetime(self._ts(60)))
            alerts = await _compute_recent_alerts(db, as_of=self._ts(60))

        assert len(alerts) == 1
        # /test has no 2xx, >30 min ago → historical
        assert alerts[0].status == "historical"
        assert alerts[0].resolved_at is None

    @pytest.mark.asyncio
    async def test_mixed_paths_independent_status(self):
        """不同路径的告警状态互不影响"""
        err_a = self._ts(1)  # 10:01 /a 500
        err_b = self._ts(2)  # 10:02 /b 500
        ok_a = self._ts(4)   # 10:04 /a 200

        db = self._build_db(
            error_rows=[
                _make_row(log_id="ea", api_path="/a", error_code="ERR_A",
                          trace_id="ta", created_at=err_a, response_code=500),
                _make_row(log_id="eb", api_path="/b", error_code="ERR_B",
                          trace_id="tb", created_at=err_b, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/a", created_at=err_a, response_code=500),
                _make_row(api_path="/a", created_at=ok_a, response_code=200),
                _make_row(api_path="/b", created_at=err_b, response_code=500),
            ],
        )

        alerts = await _compute_recent_alerts(db, as_of=self._ts(60))
        assert len(alerts) == 2
        by_path = {a.api_path: a for a in alerts}
        assert by_path["/a"].status == "resolved"
        assert by_path["/a"].resolved_at == ok_a
        assert by_path["/b"].status in ("historical", "active"), \
            "/b 无后续成功, 由时间决定 active 或 historical"

    @pytest.mark.asyncio
    async def test_no_errors_returns_empty(self):
        """无错误记录时返回空列表"""
        db = self._build_db(error_rows=[], history_rows=[])
        alerts = await _compute_recent_alerts(db, as_of=self._ts(10))
        assert alerts == []

    @pytest.mark.asyncio
    async def test_resolved_alert_resolved_at_is_first_success(self):
        """resolved_at 取第一条后续成功的时间，非最新成功时间"""
        err_t = self._ts(1)  # 10:01 500
        ok1 = self._ts(3)    # 10:03 200 (first success)
        ok2 = self._ts(5)    # 10:05 200 (later success)

        db = self._build_db(
            error_rows=[
                _make_row(log_id="e1", api_path="/test", error_code="ERR",
                          trace_id="t1", created_at=err_t, response_code=500),
            ],
            history_rows=[
                _make_row(api_path="/test", created_at=err_t, response_code=500),
                _make_row(api_path="/test", created_at=ok1, response_code=200),
                _make_row(api_path="/test", created_at=ok2, response_code=200),
            ],
        )

        alerts = await _compute_recent_alerts(db, as_of=self._ts(60))
        assert len(alerts) == 1
        assert alerts[0].status == "resolved"
        assert alerts[0].resolved_at == ok1, \
            f"应为第一条成功时间 {ok1}, 实际 {alerts[0].resolved_at}"


class _FixedDatetime:
    """替换 datetime.now() 返回固定时间，用于测试时间敏感逻辑。"""

    def __init__(self, fixed_now: datetime):
        self._fixed = fixed_now
        # 保留原始 datetime 的类方法引用
        import datetime as dt_mod
        self._real_module = dt_mod

    def now(self, tz=None):
        return self._fixed.astimezone(tz) if tz else self._fixed.replace(tzinfo=None)

    def __getattr__(self, name):
        return getattr(self._real_module, name)

    # 显式代理需要 datetime 模块暴露的方法
    timezone = timezone
    timedelta = timedelta
    datetime = datetime


# ============================================================
# _compute_latest_context 单元测试
# ============================================================

def _make_api_log(request_params: dict | None, **kwargs) -> Mock:
    """构造 ApiLog ORM 行 mock（用于 scalars().all()）。"""
    row = Mock(spec=["request_params", "trace_id", "created_at"])
    row.request_params = request_params
    row.trace_id = kwargs.pop("trace_id", "trace_default")
    row.created_at = kwargs.pop("created_at", datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc))
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


class TestLatestContext:
    """_compute_latest_context 在不同数据状态下的行为验证。"""

    T = datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc)

    def _build_db(self, logs: list[Mock]) -> AsyncMock:
        """构造 AsyncSession mock，execute + scalars + all 返回 logs。"""
        db = AsyncMock(spec=["execute"])
        result = Mock()
        scalars_chain = Mock()
        scalars_chain.all.return_value = logs
        result.scalars.return_value = scalars_chain
        db.execute = AsyncMock(return_value=result)
        return db

    @pytest.mark.asyncio
    async def test_latest_row_has_valid_snapshot(self):
        """最新一条日志有合法快照 → 直接返回该快照"""
        db = self._build_db([
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "valid context",
                        "memory_count": 3,
                        "generated_at": "2026-07-23T10:05:00+00:00",
                        "trace_id": "trace_001",
                    }
                },
                trace_id="trace_001",
                created_at=self.T,
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.formatted_text == "valid context"
        assert ctx.memory_count == 3
        assert ctx.trace_id == "trace_001"

    @pytest.mark.asyncio
    async def test_latest_no_snapshot_fallback_to_older(self):
        """最新日志无 context_snapshot，更早日志有 → 返回更早的有效快照"""
        db = self._build_db([
            # 最新：无快照
            _make_api_log(
                request_params={},
                trace_id="trace_latest",
                created_at=self.T,
            ),
            # 更早：有快照
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "older valid context",
                        "memory_count": 5,
                        "generated_at": "2026-07-23T09:30:00+00:00",
                        "trace_id": "trace_older",
                    }
                },
                trace_id="trace_older",
                created_at=self.T - timedelta(hours=1),
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.formatted_text == "older valid context"
        assert ctx.memory_count == 5
        assert ctx.trace_id == "trace_older"

    @pytest.mark.asyncio
    async def test_no_valid_snapshot_returns_none(self):
        """没有任何有效快照时返回 None"""
        db = self._build_db([
            _make_api_log(request_params={}, trace_id="t1", created_at=self.T),
            _make_api_log(
                request_params={"context_snapshot": {"version": 2, "formatted_text": "x"}},
                trace_id="t2", created_at=self.T - timedelta(hours=1),
            ),
            _make_api_log(
                request_params=None,
                trace_id="t3", created_at=self.T - timedelta(hours=2),
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is None

    @pytest.mark.asyncio
    async def test_empty_formatted_text_skipped(self):
        """formatted_text 为空字符串时跳过该记录"""
        db = self._build_db([
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "",
                        "memory_count": 0,
                        "generated_at": "2026-07-23T10:00:00+00:00",
                    }
                },
                trace_id="t_empty",
                created_at=self.T,
            ),
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "real content",
                        "memory_count": 2,
                        "generated_at": "2026-07-23T09:00:00+00:00",
                    }
                },
                trace_id="t_real",
                created_at=self.T - timedelta(hours=1),
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.formatted_text == "real content"
        assert ctx.trace_id == "t_real"

    @pytest.mark.asyncio
    async def test_version_is_string_one(self):
        """version 为字符串 "1" 也应该通过"""
        db = self._build_db([
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": "1",
                        "formatted_text": "string version",
                        "memory_count": 1,
                        "generated_at": "2026-07-23T10:00:00+00:00",
                    }
                },
                trace_id="t_str",
                created_at=self.T,
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.formatted_text == "string version"

    @pytest.mark.asyncio
    async def test_no_logs_returns_none(self):
        """没有日志记录时返回 None"""
        db = self._build_db([])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is None

    @pytest.mark.asyncio
    async def test_trace_id_fallback_to_row(self):
        """快照无 trace_id 时回退到 ApiLog.trace_id"""
        db = self._build_db([
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "no trace in snapshot",
                        "memory_count": 1,
                        "generated_at": "2026-07-23T10:00:00+00:00",
                        # 没有 trace_id
                    }
                },
                trace_id="row_trace",
                created_at=self.T,
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.trace_id == "row_trace"

    @pytest.mark.asyncio
    async def test_malformed_generated_at_fallback_to_created_at(self):
        """generated_at 不是合法 ISO 8601 时回退到 row.created_at"""
        db = self._build_db([
            _make_api_log(
                request_params={
                    "context_snapshot": {
                        "version": 1,
                        "formatted_text": "bad date",
                        "memory_count": 1,
                        "generated_at": "not-a-date",
                    }
                },
                trace_id="t_bad_date",
                created_at=self.T,
            ),
        ])
        ctx = await _compute_latest_context(db, as_of=self.T)
        assert ctx is not None
        assert ctx.formatted_text == "bad date"
        # 应该回退到 row.created_at
        assert ctx.generated_at == self.T
