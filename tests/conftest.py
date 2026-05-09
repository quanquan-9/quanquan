"""
quanquan 测试 fixtures — 数据库会话共享资源
"""
import os, sys, asyncio
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from core.database import Base
from core.models import Project, Artifact, PreferenceAnchorOrm, PreferenceEvolutionOrm, ScheduledPostOrm, AuditLog  # ensure all models registered

TEST_DB_URL = "sqlite+aiosqlite:///./data/test.db"


@pytest.fixture
async def test_engine():
    """测试用异步 SQLAlchemy 引擎"""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """每个测试独享的数据库会话"""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()
