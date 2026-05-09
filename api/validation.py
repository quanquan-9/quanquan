"""
请求验证中间件 — 请求体大小限制、Content-Type 校验
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """请求验证：体大小限制、Content-Type 校验。"""

    async def dispatch(self, request: Request, call_next):
        # 仅对 POST/PUT/PATCH 校验
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > MAX_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"success": False, "code": 413, "message": f"请求体超过 {MAX_BODY_SIZE // 1024 // 1024}MB 限制"},
                )
        response = await call_next(request)
        return response
