"""
v7.0 Repository 集成测试 — Preference/Social/Audit
"""
import pytest
from datetime import datetime, timezone, timedelta

from core.repository import PreferenceRepository, SocialRepository, AuditRepository


@pytest.mark.asyncio
class TestPreferenceRepository:
    """偏好锚点 CRUD 测试"""

    async def test_upsert_new_anchor(self, db_session):
        repo = PreferenceRepository(db_session)
        anchor = await repo.upsert_anchor(
            user_id="test_u1", category="voice",
            key="deep_male_03", weight=0.8, source="explicit",
        )
        assert anchor.key == "deep_male_03"
        assert anchor.weight == 0.8
        assert anchor.user_id == "test_u1"

    async def test_upsert_updates_existing(self, db_session):
        repo = PreferenceRepository(db_session)
        # 第一次插入
        await repo.upsert_anchor("test_u2", "bgm", "synthwave", 0.6)
        # 第二次更新
        updated = await repo.upsert_anchor("test_u2", "bgm", "synthwave", 0.9)
        assert updated.weight == 0.9

    async def test_get_all_for_user(self, db_session):
        repo = PreferenceRepository(db_session)
        await repo.upsert_anchor("test_u3", "voice", "a", 0.8)
        await repo.upsert_anchor("test_u3", "bgm", "b", 0.6)
        await repo.upsert_anchor("test_u3", "filter", "c", 0.4)

        all_prefs = await repo.get_all_for_user("test_u3")
        assert len(all_prefs) == 3
        # 按权重降序
        assert all_prefs[0].key == "a"

    async def test_delete_anchor(self, db_session):
        repo = PreferenceRepository(db_session)
        await repo.upsert_anchor("test_u4", "voice", "tmp", 0.3)
        deleted = await repo.delete_anchor("test_u4", "voice", "tmp")
        assert deleted
        all_prefs = await repo.get_all_for_user("test_u4")
        assert len(all_prefs) == 0

    async def test_delete_nonexistent(self, db_session):
        repo = PreferenceRepository(db_session)
        deleted = await repo.delete_anchor("no_user", "voice", "nope")
        assert not deleted

    async def test_record_evolution(self, db_session):
        repo = PreferenceRepository(db_session)
        event = await repo.record_evolution(
            "test_u5", "voice",
            old_key="old_voice", new_key="new_voice",
            trigger="correct", old_weight=0.5, new_weight=0.8,
        )
        assert event.trigger == "correct"
        assert event.new_key == "new_voice"

    async def test_get_evolution_history(self, db_session):
        repo = PreferenceRepository(db_session)
        await repo.record_evolution("test_u6", "bgm", "old", "new", "like")
        history = await repo.get_evolution_history("test_u6", days=1)
        assert len(history) >= 1


@pytest.mark.asyncio
class TestSocialRepository:
    """社媒排期 CRUD 测试"""

    async def test_create_post(self, db_session):
        repo = SocialRepository(db_session)
        post = await repo.create_post(
            post_id="post_001", user_id="u1", platform="bilibili",
            content={"title": "测试视频"},
        )
        assert post.post_id == "post_001"
        assert post.status == "pending"

    async def test_get_pending(self, db_session):
        repo = SocialRepository(db_session)
        await repo.create_post("p1", "u1", "douyin", {"t": "a"})
        await repo.create_post("p2", "u1", "bilibili", {"t": "b"})
        pending = await repo.get_pending()
        assert len(pending) >= 2

    async def test_update_status(self, db_session):
        repo = SocialRepository(db_session)
        await repo.create_post("p3", "u2", "youtube", {"t": "c"})
        ok = await repo.update_status("p3", "published", {"ok": True})
        assert ok
        history = await repo.get_history("u2", limit=10)
        assert len(history) >= 1

    async def test_cancel(self, db_session):
        repo = SocialRepository(db_session)
        await repo.create_post("p4", "u3", "bilibili", {})
        ok = await repo.cancel_post("p4")
        assert ok


@pytest.mark.asyncio
class TestAuditRepository:
    """审计日志测试"""

    async def test_log(self, db_session):
        repo = AuditRepository(db_session)
        entry = await repo.log(
            action="project_create", resource_type="project",
            resource_id="proj_001", user_id="u1",
            detail={"duration": 180},
        )
        assert entry.action == "project_create"
        assert entry.resource_id == "proj_001"

    async def test_query_by_user(self, db_session):
        repo = AuditRepository(db_session)
        await repo.log("login", "auth", "sess_1", "u_a")
        await repo.log("logout", "auth", "sess_2", "u_a")
        await repo.log("login", "auth", "sess_3", "u_b")

        logs_a = await repo.query(user_id="u_a")
        assert len(logs_a) == 2

    async def test_query_by_action(self, db_session):
        repo = AuditRepository(db_session)
        await repo.log("login", "auth", "s1", "u1")
        await repo.log("logout", "auth", "s2", "u1")

        logins = await repo.query(action="login")
        assert len(logins) >= 1
