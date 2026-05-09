"""
quanquan 全局异常处理器 — 所有未捕获异常统一转为 ApiResponse 格式
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from api.schema import ApiResponse


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕获所有未处理的异常，返回统一 ApiResponse 格式。"""
    status_code = getattr(exc, "status_code", 500)
    detail = str(exc) if str(exc) else type(exc).__name__

    response = ApiResponse.error(
        code=status_code,
        message=detail,
    )
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(),
    )


def register_exception_handlers(app):
    """注册全局异常处理器到 FastAPI 应用。"""
    app.add_exception_handler(Exception, global_exception_handler)
