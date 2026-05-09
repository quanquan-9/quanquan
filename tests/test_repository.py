"""测试 Repository 层"""
import pytest
from datetime import datetime, timezone

from core.models import Project, Artifact, ProjectStatus
from core.repository import ProjectRepository, ArtifactRepository


@pytest.mark.asyncio
class TestProjectRepository:
    """ProjectRepository 数据库操作测试"""

    async def test_create_and_get(self, db_session):
        """创建项目并读取"""
        repo = ProjectRepository(db_session)
        p = Project(user_id="user_1", title="我的第一个项目")
        created = await repo.create(p)

        assert created.id is not None
        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.title == "我的第一个项目"
        assert fetched.user_id == "user_1"

    async def test_get_nonexistent(self, db_session):
        """读取不存在的项目返回 None"""
        repo = ProjectRepository(db_session)
        result = await repo.get("proj_nonexistent")
        assert result is None

    async def test_list_by_user(self, db_session):
        """按用户查询项目列表"""
        repo = ProjectRepository(db_session)
        # 创建 3 个项目
        for i in range(3):
            await repo.create(Project(user_id="user_A", title=f"项目{i}"))
        # 另一个用户的项目不应出现
        await repo.create(Project(user_id="user_B", title="别人的项目"))

        results = await repo.list_by_user("user_A")
        assert len(results) == 3
        assert all(p.user_id == "user_A" for p in results)

    async def test_list_by_user_empty(self, db_session):
        """不存在的用户返回空列表"""
        repo = ProjectRepository(db_session)
        results = await repo.list_by_user("no_such_user")
        assert results == []

    async def test_update_status(self, db_session):
        """更新项目状态和进度"""
        repo = ProjectRepository(db_session)
        p = await repo.create(Project(user_id="u1", title="待更新"))

        updated = await repo.update_status(p.id, ProjectStatus.RENDERING, 0.75)
        assert updated.status == ProjectStatus.RENDERING
        assert updated.progress == 0.75

    async def test_update_status_nonexistent(self, db_session):
        """更新不存在的项目返回 None"""
        repo = ProjectRepository(db_session)
        result = await repo.update_status("fake_id", ProjectStatus.COMPLETED)
        assert result is None

    async def test_update_fields(self, db_session):
        """通用字段更新"""
        repo = ProjectRepository(db_session)
        p = await repo.create(Project(user_id="u1", title="旧标题"))

        updated = await repo.update(p.id, title="新标题", style="cyberpunk")
        assert updated.title == "新标题"
        assert updated.style == "cyberpunk"

    async def test_soft_delete(self, db_session):
        """软删除将状态设为 CANCELLED"""
        repo = ProjectRepository(db_session)
        p = await repo.create(Project(user_id="u1", title="待删除"))

        result = await repo.delete(p.id)
        assert result is True

        # 重新获取验证
        p2 = await repo.get(p.id)
        assert p2.status == ProjectStatus.CANCELLED

    async def test_hard_delete(self, db_session):
        """硬删除彻底移除"""
        repo = ProjectRepository(db_session)
        p = await repo.create(Project(user_id="u1", title="彻底消失"))

        result = await repo.delete_hard(p.id)
        assert result is True

        p2 = await repo.get(p.id)
        assert p2 is None

    async def test_count_by_status(self, db_session):
        """按状态统计"""
        repo = ProjectRepository(db_session)
        await repo.create(Project(user_id="u1", title="已完成", status=ProjectStatus.COMPLETED))
        await repo.create(Project(user_id="u1", title="进行中", status=ProjectStatus.RENDERING))
        await repo.create(Project(user_id="u1", title="已完成2", status=ProjectStatus.COMPLETED))

        counts = await repo.count_by_status()
        assert counts.get("completed") == 2
        assert counts.get("rendering") == 1

    async def test_total_count(self, db_session):
        """总项目数"""
        repo = ProjectRepository(db_session)
        assert await repo.total_count() == 0
        await repo.create(Project(user_id="u1", title="A"))
        await repo.create(Project(user_id="u1", title="B"))
        assert await repo.total_count() == 2


@pytest.mark.asyncio
class TestArtifactRepository:
    """ArtifactRepository 数据库操作测试"""

    async def test_create_artifact(self, db_session):
        """创建制品"""
        repo = ProjectRepository(db_session)
        art_repo = ArtifactRepository(db_session)

        p = await repo.create(Project(user_id="u1", title="测试"))
        a = Artifact(project_id=p.id, key="script_v1", stage="script_gen", content={"scenes": 3})

        created = await art_repo.create(a)
        assert created.id is not None
        assert created.key == "script_v1"

    async def test_get_by_key(self, db_session):
        """按键获取制品"""
        repo = ProjectRepository(db_session)
        art_repo = ArtifactRepository(db_session)

        p = await repo.create(Project(user_id="u1", title="测试"))
        await art_repo.create(Artifact(project_id=p.id, key="bgm_v1", stage="bgm", content={}))

        result = await art_repo.get_by_key(p.id, "bgm_v1")
        assert result is not None
        assert result.stage == "bgm"

        # 不存在的键
        missing = await art_repo.get_by_key(p.id, "nonexistent")
        assert missing is None

    async def test_list_by_project(self, db_session):
        """获取项目的所有制品"""
        repo = ProjectRepository(db_session)
        art_repo = ArtifactRepository(db_session)

        p = await repo.create(Project(user_id="u1", title="多制品项目"))
        await art_repo.create(Artifact(project_id=p.id, key="script", stage="script_gen", content={}))
        await art_repo.create(Artifact(project_id=p.id, key="voice", stage="voiceover", content={}))
        await art_repo.create(Artifact(project_id=p.id, key="bgm", stage="bgm", content={}))

        results = await art_repo.list_by_project(p.id)
        assert len(results) == 3
        stages = {a.stage for a in results}
        assert stages == {"script_gen", "voiceover", "bgm"}
