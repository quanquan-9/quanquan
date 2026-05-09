"""
quanquan 数据库引擎 — SQLAlchemy 2.0 Async

提供异步数据库会话管理、引擎生命周期和表初始化。
用法:
    from core.database import engine, async_session, get_db, init_db
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.settings import settings

logger = logging.getLogger("quanquan.database")

# ── 异步引擎 ──
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.QUANQUAN_DEBUG,  # SQL 调试输出
    future=True,
)

# ── 会话工厂 ──
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后不使对象过期，便于跨函数使用
)


# ── ORM 基类 ──
class Base(DeclarativeBase):
    """所有 ORM 模型必须继承此类"""
    pass


# ── FastAPI 依赖注入 ──
async def get_db() -> AsyncSession:
    """获取数据库会话（用于 FastAPI Depends）。"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# ── 初始化 ──
async def init_db() -> None:
    """在应用启动时创建所有缺失的表（幂等操作）。"""
    import core.models  # ensure all models are registered with Base.metadata  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库表初始化完成")
