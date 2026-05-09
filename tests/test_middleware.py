"""
测试中间件 — RequestID / SecurityHeaders / ResponseTime
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from api.server import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
class TestRequestID:
    """RequestID 中间件"""

    async def test_request_id_present(self, client):
        resp = await client.get("/health")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    async def test_request_id_is_uuid(self, client):
        resp = await client.get("/health")
        rid = resp.headers["X-Request-ID"]
        parts = rid.split("-")
        assert len(parts) == 5, f"expected UUID4, got: {rid}"

    async def test_request_id_passed_through(self, client):
        custom_id = "my-custom-req-id-12345"
        resp = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.headers["X-Request-ID"] == custom_id


@pytest.mark.asyncio
class TestSecurityHeaders:
    """SecurityHeaders 中间件"""

    async def test_x_content_type_options(self, client):
        resp = await client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    async def test_x_frame_options(self, client):
        resp = await client.get("/health")
        assert resp.headers["X-Frame-Options"] == "DENY"

    async def test_x_xss_protection(self, client):
        resp = await client.get("/health")
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"

    async def test_referrer_policy(self, client):
        resp = await client.get("/health")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
class TestResponseTime:
    """ResponseTime 中间件"""

    async def test_response_time_header(self, client):
        resp = await client.get("/health")
        assert "X-Response-Time-Ms" in resp.headers
        ms = float(resp.headers["X-Response-Time-Ms"])
        assert ms >= 0

    async def test_response_time_on_error(self, client):
        resp = await client.get("/api/v1/nonexistent-endpoint-12345")
        assert "X-Response-Time-Ms" in resp.headers


@pytest.mark.asyncio
class TestExceptionHandling:
    """全局异常处理"""

    async def test_404_returns_json(self, client):
        resp = await client.get("/api/v1/definitely-does-not-exist-99999")
        assert resp.headers["content-type"] == "application/json"
        data = resp.json()
        assert "success" in data or "detail" in data

    async def test_invalid_method_has_security_headers(self, client):
        resp = await client.post("/health")
        assert "X-Content-Type-Options" in resp.headers
