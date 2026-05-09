"""
quanquan 结构化日志系统 — 基于 structlog（v7.0 增强）

功能：
- dev: 彩色 ConsoleRenderer
- prod: JSON → 文件轮转 + stdout
- 请求上下文集成 (request_id)
- 优雅关闭时 flush
"""
import logging
import logging.handlers
import os
import sys

import structlog

from core.settings import settings

_LOG_DIR = "/data/quanquan/logs"
_FILE_HANDLER = None


def setup_logging() -> None:
    """初始化结构化日志系统。

    生产环境：JSON 格式输出到文件和 stdout 双通道。
    文件路径：/data/quanquan/logs/quanquan.log，每日轮转保留 30 天。
    """
    global _FILE_HANDLER

    # ── 生产环境：文件轮转 ──
    if not settings.QUANQUAN_DEBUG:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _FILE_HANDLER = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(_LOG_DIR, "quanquan.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        _FILE_HANDLER.setLevel(logging.INFO)
        _FILE_HANDLER.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("quanquan").addHandler(_FILE_HANDLER)
        logging.getLogger("quanquan").setLevel(logging.INFO)

    # ── 渲染器 ──
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.QUANQUAN_DEBUG
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__):
    """获取 structlog logger"""
    return structlog.get_logger(name)


def flush_logs():
    """优雅关闭：flush 文件日志"""
    if _FILE_HANDLER:
        _FILE_HANDLER.flush()
        _FILE_HANDLER.close()
