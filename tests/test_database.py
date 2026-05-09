"""
测试数据库引擎 + 连接池 + Alembic 迁移
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text


class TestDatabaseEngine:
    """core.database 引擎测试"""

    @pytest.mark.asyncio
    async def test_engine_creation(self):
        from core.database import engine
        assert engine is not None

    @pytest.mark.asyncio
    async def test_connection(self):
        from core.database import engine
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_session_factory(self):
        from core.database import async_session
        async with async_session() as session:
            assert session is not None

    @pytest.mark.asyncio
    async def test_get_db_dependency(self):
        from core.database import get_db
        gen = get_db()
        session = await gen.__anext__()
        assert session is not None
        await gen.aclose()


class TestDBPool:
    """core.db_pool 连接池测试"""

    @pytest.mark.asyncio
    async def test_health_check(self):
        from core.db_pool import check_db_health
        result = await check_db_health()
        assert result["status"] == "connected"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_pool_stats(self):
        from core.db_pool import get_pool_stats
        stats = await get_pool_stats()
        assert "size" in stats
        assert "checked_in" in stats


class TestAlembic:
    """Alembic 迁移测试"""

    def test_alembic_config_exists(self):
        assert os.path.exists("/data/quanquan/alembic.ini")

    def test_alembic_env_exists(self):
        assert os.path.exists("/data/quanquan/alembic/env.py")

    def test_migration_versions_exist(self):
        versions_dir = "/data/quanquan/alembic/versions"
        assert os.path.isdir(versions_dir)
        py_files = [f for f in os.listdir(versions_dir) if f.endswith('.py')]
        assert len(py_files) >= 1


class TestContainer:
    """core.container IoC 容器测试"""

    def test_container_exists(self):
        from core.container import container
        assert container is not None

    @pytest.mark.asyncio
    async def test_get_session(self):
        from core.container import container
        session = await container.get_session()
        assert session is not None
        await session.close()

    def test_repo_creation(self):
        from core.container import container
        from unittest.mock import MagicMock
        mock = MagicMock()
        pr = container.project_repo(mock)
        assert pr is not None
        ar = container.artifact_repo(mock)
        assert ar is not None
