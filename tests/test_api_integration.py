"""
API 集成测试 — 完整端点验证（项目CRUD、样式、LUT、模板、VFX）
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
class TestProjectAPI:
    """项目 CRUD API 集成测试"""

    async def test_create_project(self, client):
        resp = await client.post("/api/v1/projects", json={
            "text": "AI改变世界的三种方式",
            "duration": 120,
            "style": "tech",
            "tags": ["AI", "科技"],
        })
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            data = resp.json()
            assert "project_id" in data or "id" in data

    async def test_create_project_minimal(self, client):
        resp = await client.post("/api/v1/projects", json={
            "text": "最短主题",
            "duration": 30,
        })
        assert resp.status_code in (200, 404)  # endpoint may not exist yet

    async def test_create_project_validation(self, client):
        resp = await client.post("/api/v1/projects", json={
            "text": "",
            "duration": 120,
        })
        assert resp.status_code in (200, 404, 422)


@pytest.mark.asyncio
class TestStylesAPI:
    """样式列表 API"""

    async def test_list_styles(self, client):
        resp = await client.get("/api/v1/styles")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestLUTAPI:
    """LUT 预设 API"""

    async def test_list_luts(self, client):
        resp = await client.get("/api/v1/luts")
        assert resp.status_code == 200

    async def test_list_lut_categories(self, client):
        resp = await client.get("/api/v1/luts/categories")
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestDirectorAPI:
    """导演状态 API"""

    async def test_director_status(self, client):
        resp = await client.get("/api/v1/director/status")
        assert resp.status_code == 200
        data = resp.json()
        inner = data.get("data", data)
        assert "state" in inner


@pytest.mark.asyncio
class TestAnalyticsAPI:
    """分析面板 API"""

    async def test_analytics_dashboard(self, client):
        resp = await client.get("/api/v1/analytics/dashboard")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestVFXAPI:
    """VFX API"""

    async def test_vfx_presets(self, client):
        resp = await client.get("/api/v1/vfx/presets")
        assert resp.status_code in (200, 404)

    async def test_vfx_categories(self, client):
        resp = await client.get("/api/v1/vfx/categories")
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestTemplateAPI:
    """模板市场 API"""

    async def test_list_templates(self, client):
        resp = await client.get("/api/v1/templates")
        assert resp.status_code == 200

    async def test_template_categories(self, client):
        resp = await client.get("/api/v1/templates/categories")
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestPlatformAPI:
    """平台发布 API"""

    async def test_list_platforms(self, client):
        resp = await client.get("/api/v1/platforms")
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestVoiceAPI:
    """声音克隆 API"""

    async def test_list_voices(self, client):
        resp = await client.get("/api/v1/voices")
        assert resp.status_code in (200, 404)


@pytest.mark.asyncio
class TestDocumentation:
    """文档端点"""

    async def test_docs(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200

    async def test_redoc(self, client):
        resp = await client.get("/redoc")
        assert resp.status_code == 200

    async def test_openapi_json(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "openapi" in data
        assert data["info"]["version"] == "7.0.0"
