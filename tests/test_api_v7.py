"""v7.0 API integration tests - memory / social / audit / metrics / version"""
import pytest
from httpx import AsyncClient, ASGITransport
from api.server import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
class TestMemoryAPI:

    async def test_memory_profile_empty(self, client):
        resp = await client.get("/api/v1/memory/profile?user_id=nobody")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["data"]["cold_start"] is True

    async def test_cold_start(self, client):
        resp = await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_cold", "keywords": ["keji", "zhuanye"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert "voice" in data["data"]

    async def test_like(self, client):
        await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_like", "keywords": ["game"],
        })
        resp = await client.post("/api/v1/memory/like", json={
            "user_id": "test_like", "category": "bgm",
            "preferences": ["electronic_hype"],
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

    async def test_correct(self, client):
        await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_cc", "keywords": ["edu"],
        })
        resp = await client.post("/api/v1/memory/correct", json={
            "user_id": "test_cc", "category": "voice",
            "from": "clear_male_01", "to": "deep_male_03",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert not data["data"]["migrated"]

    async def test_dislike(self, client):
        await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_no", "keywords": ["keji"],
        })
        resp = await client.post("/api/v1/memory/dislike", json={
            "user_id": "test_no", "category": "voice",
            "preference": "professional_male_01",
        })
        assert resp.status_code == 200

    async def test_evolution(self, client):
        await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_evo", "keywords": ["game"],
        })
        await client.post("/api/v1/memory/like", json={
            "user_id": "test_evo", "category": "bgm",
            "preferences": ["electronic_hype"],
        })
        resp = await client.get("/api/v1/memory/evolution?user_id=test_evo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["count"] >= 1

    async def test_profile_after_activity(self, client):
        await client.post("/api/v1/memory/cold-start", json={
            "user_id": "test_full", "keywords": ["keji"],
        })
        await client.post("/api/v1/memory/like", json={
            "user_id": "test_full", "category": "voice",
            "preferences": ["professional_male_01"],
        })
        resp = await client.get("/api/v1/memory/profile?user_id=test_full")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["cold_start"] is False
        assert data["data"]["total_anchors"] > 0


@pytest.mark.asyncio
class TestV7InfraAPI:

    async def test_version(self, client):
        resp = await client.get("/api/v1/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["version"] == "7.0.0"

    async def test_metrics(self, client):
        resp = await client.get("/api/v1/metrics")
        assert resp.status_code == 200
        assert "quanquan_uptime_seconds" in resp.text

    @pytest.mark.skip(reason="Needs real PostgreSQL — audit tables not in test SQLite")
    async def test_audit_empty(self, client):
        resp = await client.get("/api/v1/audit/logs")
        assert resp.status_code == 200
        assert resp.json()["success"]

    async def test_health_dashboard(self, client):
        resp = await client.get("/health-dashboard")
        assert resp.status_code == 200

    async def test_ping(self, client):
        resp = await client.get("/api/v1/ping")
        assert resp.status_code == 200
        assert resp.json()["data"]["pong"] is True

    async def test_status(self, client):
        resp = await client.get("/api/v1/status")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestSocialModerationAPI:

    async def test_queue_empty(self, client):
        resp = await client.get("/api/v1/social/queue")
        assert resp.status_code == 200

    async def test_moderation_text(self, client):
        resp = await client.post("/api/v1/moderation/check/text", json={
            "text": "normal video description",
        })
        assert resp.status_code == 200

    async def test_moderation_missing(self, client):
        resp = await client.post("/api/v1/moderation/check/text", json={})
        assert resp.status_code == 200
        assert not resp.json()["success"]

    async def test_moderation_video(self, client):
        resp = await client.post("/api/v1/moderation/check/video", json={
            "video_path": "/tmp/test.mp4",
        })
        assert resp.status_code == 200
