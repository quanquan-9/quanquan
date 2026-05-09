"""
统一错误处理框架 (Error Handling Framework)

功能：
- 自定义异常层次结构
- 全局异常捕获
- 结构化错误响应
- 错误码体系
- 链路追踪 (Trace ID)
"""

import uuid
import traceback
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class ErrorCode(IntEnum):
    """错误码体系"""
    # 通用
    UNKNOWN = 1000
    INTERNAL_ERROR = 1001
    NOT_IMPLEMENTED = 1002
    SERVICE_UNAVAILABLE = 1003

    # 认证
    UNAUTHORIZED = 2001
    FORBIDDEN = 2002
    TOKEN_EXPIRED = 2003
    INVALID_API_KEY = 2004
    INSUFFICIENT_PERMISSION = 2005

    # 请求
    BAD_REQUEST = 3001
    VALIDATION_ERROR = 3002
    MISSING_PARAMETER = 3003
    INVALID_PARAMETER = 3004
    RATE_LIMIT_EXCEEDED = 3005

    # 资源
    NOT_FOUND = 4001
    ALREADY_EXISTS = 4002
    CONFLICT = 4003
    RESOURCE_EXHAUSTED = 4004

    # 视频处理
    VIDEO_NOT_FOUND = 5001
    VIDEO_ENCODE_FAILED = 5002
    VIDEO_FORMAT_UNSUPPORTED = 5003
    VIDEO_TOO_LARGE = 5004
    GPU_NOT_AVAILABLE = 5005

    # AI 服务
    LLM_SERVICE_ERROR = 6001
    LLM_TIMEOUT = 6002
    TTS_SERVICE_ERROR = 6003
    MODEL_NOT_FOUND = 6004
    EMBEDDING_FAILED = 6005

    # 存储
    STORAGE_ERROR = 7001
    FILE_TOO_LARGE = 7002
    UPLOAD_FAILED = 7003

    # 项目
    PROJECT_NOT_FOUND = 8001
    PROJECT_ALREADY_RUNNING = 8002
    PROJECT_FAILED = 8003
    QC_FAILED = 8004


HTTP_STATUS_MAP = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


class QuanquanError(Exception):
    """quanquan 基础异常"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN,
        details: Optional[Dict] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        self.trace_id = str(uuid.uuid4())[:12]
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.error_code.value,
                "name": self.error_code.name,
                "message": self.message,
                "trace_id": self.trace_id,
                "details": self.details,
            }
        }

    @property
    def http_status(self) -> int:
        return HTTP_STATUS_MAP.get(self.error_code, 500)


# ---- 具体异常类 ----

class AuthError(QuanquanError):
    """认证错误"""
    def __init__(self, message: str = "Authentication failed", *args, **kwargs):
        super().__init__(message, ErrorCode.UNAUTHORIZED, *args, **kwargs)


class ForbiddenError(QuanquanError):
    """权限不足"""
    def __init__(self, message: str = "Permission denied", *args, **kwargs):
        super().__init__(message, ErrorCode.FORBIDDEN, *args, **kwargs)


class NotFoundError(QuanquanError):
    """资源不存在"""
    def __init__(self, resource: str = "Resource", *args, **kwargs):
        super().__init__(f"{resource} not found", ErrorCode.NOT_FOUND, *args, **kwargs)


class ValidationError(QuanquanError):
    """参数验证错误"""
    def __init__(self, message: str = "Validation failed", *args, **kwargs):
        super().__init__(message, ErrorCode.VALIDATION_ERROR, *args, **kwargs)


class RateLimitError(QuanquanError):
    """速率限制"""
    def __init__(self, *args, **kwargs):
        super().__init__("Rate limit exceeded", ErrorCode.RATE_LIMIT_EXCEEDED, *args, **kwargs)


class VideoProcessError(QuanquanError):
    """视频处理错误"""
    def __init__(self, message: str, *args, **kwargs):
        super().__init__(message, ErrorCode.VIDEO_ENCODE_FAILED, *args, **kwargs)


class LLMServiceError(QuanquanError):
    """LLM 服务错误"""
    def __init__(self, message: str = "LLM service error", *args, **kwargs):
        super().__init__(message, ErrorCode.LLM_SERVICE_ERROR, *args, **kwargs)


class StorageError(QuanquanError):
    """存储错误"""
    def __init__(self, message: str = "Storage error", *args, **kwargs):
        super().__init__(message, ErrorCode.STORAGE_ERROR, *args, **kwargs)


# ---- 错误处理器 ----

class ErrorHandler:
    """统一错误处理器"""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._handlers: Dict[ErrorCode, callable] = {}

    def register(self, error_code: ErrorCode, handler: callable):
        self._handlers[error_code] = handler

    async def handle(self, error: Exception) -> dict:
        """处理异常 → 结构化响应"""
        if isinstance(error, QuanquanError):
            # 自定义处理
            if error.error_code in self._handlers:
                return await self._handlers[error.error_code](error)

            logger.error(
                f"[{error.trace_id}] {error.error_code.name}: {error.message}",
                exc_info=error.cause if self.debug else False,
            )
            return error.to_dict()

        # 未知异常
        trace_id = str(uuid.uuid4())[:12]
        logger.error(f"[{trace_id}] Unhandled exception: {error}", exc_info=True)
        return {
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "name": "INTERNAL_ERROR",
                "message": str(error) if self.debug else "Internal server error",
                "trace_id": trace_id,
            }
        }


# 全局实例
error_handler = ErrorHandler()


# ============================================================
# FastAPI 异常注册
# ============================================================

def register_fastapi_exception_handlers(app):
    """为 FastAPI 注册全局异常处理器"""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(QuanquanError)
    async def quanquan_exception_handler(request: Request, exc: QuanquanError):
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        result = await error_handler.handle(exc)
        status_map = {
            1001: 500, 4001: 404, 3001: 400,
        }
        status = status_map.get(result["error"]["code"], 500)
        return JSONResponse(status_code=status, content=result)
