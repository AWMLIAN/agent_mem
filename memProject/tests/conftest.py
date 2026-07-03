# -*- coding: utf-8 -*-
"""
pytest 配置 — 异步测试支持。
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def async_client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
