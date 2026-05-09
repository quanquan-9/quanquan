"""
测试 ORM 模型 — Project 和 Artifact 的 CRUD 行为
"""
import pytest
from datetime import datetime, timezone

from core.models import Project, Artifact, ProjectStatus


class TestProjectModel:
    """Project 模型单元测试"""

    def test_create_with_defaults(self):
        """构造时只有显式赋值字段有值，SQL 级 default 只在 INSERT 时生效"""
        p = Project(title="测试项目", text="这是测试文本")
        assert p.title == "测试项目"
        assert p.text == "这是测试文本"
        # 以下字段是 SQL 级 default，构造后为 None：
        # duration_sec=180, user_id="anonymous", progress=0.0, meta={}
        assert p.id is None  # server_default lambda
        assert p.user_id is None
        assert p.duration_sec is None
        assert p.progress is None

    def test_create_with_all_fields(self):
        """全字段创建"""
        p = Project(
            id="proj_custom001",
            user_id="user_001",
            title="完整项目",
            text="完整文本",
            style="cyberpunk",
            duration_sec=300,
            status=ProjectStatus.PLANNING,
            progress=0.5,
            meta={"tags": ["AI", "tech"]},
        )
        assert p.id == "proj_custom001"
        assert p.user_id == "user_001"
        assert p.style == "cyberpunk"
        assert p.status == ProjectStatus.PLANNING
        assert p.progress == 0.5

    def test_repr(self):
        """__repr__ 可读性"""
        p = Project(id="proj_test", title="Hello World")
        r = repr(p)
        assert "proj_test" in r
        assert "Hello World" in r

    def test_timestamps_are_none_until_persisted(self):
        """SQLAlchemy default lambda 只在 INSERT 时触发，构造后 created_at 为 None"""
        p = Project(title="时间戳测试")
        # 正确行为：SQLAlchemy mapped_column(default=...) 是数据库级默认值
        assert p.created_at is None
        assert p.updated_at is None


class TestArtifactModel:
    """Artifact 模型单元测试"""

    def test_create_artifact(self):
        """创建制品"""
        a = Artifact(
            project_id="proj_001",
            key="script_v1",
            stage="script_gen",
            content={"title": "AI改变世界", "scenes": 5},
        )
        assert a.project_id == "proj_001"
        assert a.key == "script_v1"
        assert a.stage == "script_gen"
        assert a.content["scenes"] == 5
        assert a.file_path is None
        # created_at 也是 SQL 级默认值，persist 后才有值
        assert a.created_at is None

    def test_artifact_with_file(self):
        """带文件路径的制品"""
        a = Artifact(
            project_id="proj_001",
            key="voiceover_v2",
            stage="voiceover",
            content={},
            file_path="/artifacts/proj_001/voice.mp3",
        )
        assert a.file_path == "/artifacts/proj_001/voice.mp3"

    def test_repr(self):
        """__repr__ 可读性"""
        a = Artifact(project_id="proj_001", key="bgm_v1", stage="bgm", content={})
        r = repr(a)
        assert "bgm_v1" in r
        assert "bgm" in r


class TestProjectStatus:
    """ProjectStatus 枚举"""

    def test_all_statuses(self):
        assert ProjectStatus.CREATED.value == "created"
        assert ProjectStatus.ANALYZING.value == "analyzing"
        assert ProjectStatus.PLANNING.value == "planning"
        assert ProjectStatus.RENDERING.value == "rendering"
        assert ProjectStatus.COMPLETED.value == "completed"
        assert ProjectStatus.FAILED.value == "failed"
        assert ProjectStatus.CANCELLED.value == "cancelled"
