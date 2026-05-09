"""
中间件集合 — 响应计时、请求体大小限制、安全头
"""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class ResponseTimeMiddleware(BaseHTTPMiddleware):
    """在每个响应中添加 X-Response-Time-Ms 头（毫秒精度）。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加基本安全响应头。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
