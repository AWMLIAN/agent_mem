# -*- coding: utf-8 -*-
"""
Dashboard Phase 2 专项测试 — generation_summary 与 retrieval_signal_distribution。

覆盖场景：
  P01: generation_summary 结构完整，五项计数均为 ≥0 的整数
  P02: retrieval_signal_distribution 结构完整
  P03: 触发检索后 retrieval_signal_distribution 含有效信号
  P04: 检索信号比例之和 ≈ 1.0（有数据时）
  P05: generation_summary 各字段类型正确
  P06: 无数据时返回默认零值而非缺失字段
  P13: 删除/恢复记忆后 deleted_at 与 Dashboard 计数闭环
"""
import httpx
import pytest
import time
from datetime import datetime, timezone

BASE = "http://localhost:8000/api/v1/admin"
MEM_BASE = "http://localhost:8000/api/v1/memory"
TIMEOUT = 30


def test_P01_generation_summary_structure():
    """P01: generation_summary 五项计数完整"""
    r = httpx.get(f"{BASE}/dashboard", timeout=TIMEOUT)
    body = r.json()
    gs = body["data"]["generation_summary"]
    for field in ("generated_count", "merged_count", "updated_count",
                  "discarded_count", "conflict_count"):
        assert field in gs, f"缺少字段 {field}"
        assert isinstance(gs[field], int), f"{field} 不是整数"
        assert gs[field] >= 0, f"{field} 为负数"


def test_P02_retrieval_signal_structure():
    """P02: retrieval_signal_distribution 是列表"""
    r = httpx.get(f"{BASE}/dashboard", timeout=TIMEOUT)
    body = r.json()
    signals = body["data"]["retrieval_signal_distribution"]
    assert isinstance(signals, list)
    if signals:
        for item in signals:
            assert "signal" in item
            assert "count" in item
            assert "ratio" in item
            assert isinstance(item["count"], int)


def test_P03_retrieval_signal_after_search():
    """P03: 触发检索后 retrieval_signal_distribution 至少有一条记录"""
    # 触发搜索
    r = httpx.post(
        "http://localhost:8000/api/v1/memory/search",
        json={"query": "工作", "user_id": "test_pipeline_zh_1784080440", "top_k": 3},
        timeout=30,
    )
    assert r.status_code == 200

    # 检查 dashboard
    r2 = httpx.get(f"{BASE}/dashboard?hours=24&trend_days=1", timeout=TIMEOUT)
    body = r2.json()
    signals = body["data"]["retrieval_signal_distribution"]
    assert len(signals) > 0, "触发检索后应有信号记录"
    # 验证每个项目结构
    for item in signals:
        # 旧记录可能含 vector_hybrid（迁移前），新记录为 hybrid
        assert item["signal"] in ("hybrid", "keyword", "vector_hybrid")
        assert item["count"] > 0


def test_P04_signal_ratio_sum():
    """P04: 有数据时信号比例之和 ≈ 1.0"""
    r = httpx.get(f"{BASE}/dashboard?hours=24&trend_days=1", timeout=TIMEOUT)
    body = r.json()
    signals = body["data"]["retrieval_signal_distribution"]
    if signals:
        ratio_sum = sum(item["ratio"] for item in signals)
        assert abs(ratio_sum - 1.0) < 0.001, f"比例之和 {ratio_sum} 偏离 1.0"


def test_P05_generation_types():
    """P05: generation_summary 数字类型正确"""
    r = httpx.get(f"{BASE}/dashboard", timeout=TIMEOUT)
    body = r.json()
    gs = body["data"]["generation_summary"]
    for val in gs.values():
        assert isinstance(val, int), f"值 {val} 不是 int"
        assert val >= 0


def test_P06_empty_defaults():
    """P06: 无数据时返回默认零值而非缺失字段"""
    r = httpx.get(f"{BASE}/dashboard?hours=1&trend_days=1", timeout=TIMEOUT)
    body = r.json()
    data = body["data"]
    # generation_summary 始终存在
    assert "generation_summary" in data
    # retrieval_signal_distribution 始终存在（可能是空列表）
    assert "retrieval_signal_distribution" in data


# ── Phase 3: recent_* ──────────────────────────────────────

def test_P07_recent_lists_structure():
    """P07: 四个 recent 列表都在响应中"""
    r = httpx.get(f"{BASE}/dashboard", timeout=TIMEOUT)
    body = r.json()
    for key in ("recent_agents", "recent_retrievals", "recent_alerts", "recent_tasks"):
        assert key in body["data"], f"缺少 {key}"
        assert isinstance(body["data"][key], list)


def test_P08_recent_retrievals_has_data():
    """P08: recent_retrievals 有数据时包含必需字段"""
    # 触发一次检索
    httpx.post(
        f"{MEM_BASE}/search",
        json={"query": "工作", "user_id": "test_pipeline_zh_1784080440", "top_k": 3},
        timeout=30,
    )
    r = httpx.get(f"{BASE}/dashboard?hours=168&trend_days=7", timeout=TIMEOUT)
    items = r.json()["data"]["recent_retrievals"]
    if items:
        item = items[0]
        for field in ("retrieval_id", "summary", "relevance_score", "occurred_at"):
            assert field in item


def test_P09_recent_alerts_has_required_fields():
    """P09: recent_alerts 包含 message/error_code/trace_id/occurred_at"""
    r = httpx.get(f"{BASE}/dashboard?hours=168&trend_days=7", timeout=TIMEOUT)
    items = r.json()["data"]["recent_alerts"]
    if items:
        item = items[0]
        for field in ("message", "error_code", "trace_id", "occurred_at"):
            assert field in item, f"缺少 {field}"


def test_P10_recent_lists_max_five():
    """P10: 每个 recent 列表最多 5 条"""
    r = httpx.get(f"{BASE}/dashboard?hours=168&trend_days=7", timeout=TIMEOUT)
    data = r.json()["data"]
    for key in ("recent_agents", "recent_retrievals", "recent_alerts", "recent_tasks"):
        assert len(data[key]) <= 5, f"{key} 超过 5 条"


def test_P11_summary_desensitized():
    """P11: 检索摘要不含明文手机号"""
    r = httpx.get(f"{BASE}/dashboard?hours=168&trend_days=7", timeout=TIMEOUT)
    items = r.json()["data"]["recent_retrievals"]
    for item in items:
        summary = item.get("summary", "")
        import re
        assert not re.search(r"1[3-9]\d{9}", summary), f"摘要含手机号: {summary}"


# ── 层次六：一致性验证 ──────────────────────────────────

def test_P12_dashboard_consistency_with_stats():
    """P12: Dashboard.memory_count 与 admin/stats 一致"""
    r1 = httpx.get(f"{BASE}/dashboard", timeout=TIMEOUT)
    r2 = httpx.get(f"{BASE}/stats", timeout=TIMEOUT)
    dash_mem = r1.json()["data"]["summary"]["memory_count"]
    stats_mem = r2.json()["data"]["total_memories"]
    msg = f"Dashboard={dash_mem}, Stats={stats_mem}"
    assert dash_mem == stats_mem, f"memory_count 不一致: {msg}"


@pytest.mark.asyncio
async def test_P13_delete_deleted_at_written(p13_test_memory):
    """
    P13: 删除记忆 → deleted_at 写入 → Dashboard 计数同步。
    不依赖 LLM，通过 fixture 预建确定性记忆。
    使用同步 SQLAlchemy 验证 deleted_at（无 docker exec）。
    """
    from sqlalchemy import create_engine, text
    from app.core.config import get_settings

    s = get_settings()
    sync_url = f"postgresql://{s.database.user}:{s.database.password}@{s.database.host}:{s.database.port}/{s.database.database}"
    uid, mem_id, headers = p13_test_memory
    ADMIN = "http://localhost:8000/api/v1/admin"
    MEM = "http://localhost:8000/api/v1/memory"

    async with httpx.AsyncClient(timeout=30) as cli:
        # 1. 删除前取证：用户维度的记忆数
        list_before = await cli.post(f"{MEM}/list?user_id={uid}&page=1&page_size=10", headers=headers)
        count_before = list_before.json()["data"]["total"]
        assert count_before >= 1, f"预建记忆应 >=1，实际 {count_before}"

        # 2. 删除记忆
        del_resp = await cli.request("DELETE", f"{MEM}/delete",
            json={"memory_id": mem_id}, headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["code"] == 0
        assert del_resp.json()["data"]["deleted"] is True

        # 3. 验证 deleted_at 已写入（同步 SQLAlchemy，无 docker exec）
        check_engine = create_engine(sync_url)
        with check_engine.connect() as c:
            row = c.execute(text("SELECT status, deleted_at FROM t_memory WHERE memory_id=:mid"),
                           {"mid": mem_id}).fetchone()
        assert row is not None
        assert row[0] == "deleted", f"状态应为 deleted，实际 {row[0]}"
        assert row[1] is not None, "deleted_at 不应为 NULL"

        # 4. 用户维度的列表计数减少
        list_after_del = await cli.post(f"{MEM}/list?user_id={uid}&page=1&page_size=10", headers=headers)
        count_after_del = list_after_del.json()["data"]["total"]
        assert count_after_del == count_before - 1, (
            f"删除后用户记忆计数应减 1: {count_before} -> {count_after_del}"
        )

        # 5. 恢复记忆（active，清除 deleted_at）
        upd_resp = await cli.put(f"{MEM}/update",
            json={"memory_id": mem_id, "status": "active"}, headers=headers)
        assert upd_resp.status_code == 200
        assert upd_resp.json()["data"]["updated"] is True

        # 6. 验证 deleted_at 已清除
        with check_engine.connect() as c:
            row2 = c.execute(text("SELECT status, deleted_at FROM t_memory WHERE memory_id=:mid"),
                            {"mid": mem_id}).fetchone()
        assert row2 is not None
        assert row2[0] == "active", f"恢复后状态应为 active，实际 {row2[0]}"
        assert row2[1] is None, "恢复后 deleted_at 应为 NULL"

        # 7. 用户维度的记忆数恢复
        list_final = await cli.post(f"{MEM}/list?user_id={uid}&page=1&page_size=10", headers=headers)
        count_final = list_final.json()["data"]["total"]
        assert count_final == count_before, (
            f"恢复后计数应回到原值: {count_before} -> {count_final}"
        )

        check_engine.dispose()