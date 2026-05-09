"""
quanquan API 中间件 — 请求追踪与可观测性

包含：
- RequestIDMiddleware：每个 HTTP 请求分配/继承 X-Request-ID，
  测量响应时间，绑定请求上下文到 structlog。
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件：为每个请求注入追踪 ID 并记录耗时。

    功能：
    1. 从请求头 X-Request-ID 继承请求 ID（缺省生成 UUID4）
    2. 使用 structlog.contextvars 将 request_id / path 绑定到日志上下文
    3. 在响应头中返回 X-Request-ID 和 X-Response-Time
    4. 请求完成后清理上下文，防止跨请求污染

    用法：在 FastAPI app 上注册即可：
        from api.middleware import RequestIDMiddleware
        app.add_middleware(RequestIDMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        # ── 1. 获取或生成请求 ID ──
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # ── 2. 绑定到 structlog 上下文（该请求期间所有日志自动携带） ──
        bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )

        # ── 3. 执行下游中间件 / 路由处理 ──
        start_time = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start_time

        # ── 4. 在响应头中注入追踪信息 ──
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = "{:.3f}s".format(elapsed)

        # ── 5. 清理上下文（防止泄漏到下一个请求） ──
        clear_contextvars()

        return response
