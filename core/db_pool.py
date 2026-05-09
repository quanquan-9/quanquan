"""
quanquan 数据库连接池管理 — SQLAlchemy 2.0 Async

提供连接池健康检查、统计和优雅关闭。
"""
from sqlalchemy import text
from core.database import engine
from core.settings import settings


async def check_db_health() -> dict:
    """检查数据库连接健康状态。

    返回:
        {"status": "connected"/"disconnected", "latency_ms": float}
    """
    import time
    try:
        start = time.monotonic()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000
        return {"status": "connected", "latency_ms": round(latency, 2)}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


async def get_pool_stats() -> dict:
    """获取连接池统计信息。

    返回:
        {"size": int, "checked_in": int, "overflow": int, "total": int}
    """
    pool = engine.pool
    return {
        "size": pool.size(),
        "checked_in": pool.checkedin(),
        "overflow": pool.overflow(),
        "total": pool.size() + pool.overflow(),
    }


async def close_db() -> None:
    """优雅关闭数据库连接池。"""
    await engine.dispose()
