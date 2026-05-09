"""
quanquan 统一 API 响应模型 — 所有端点必须使用此类格式

用法:
    from api.schema import ApiResponse
    return ApiResponse.ok(data=project, message="创建成功")
    return ApiResponse.error(code=404, message="项目不存在")
"""
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    success: bool = Field(..., description="是否成功")
    code: int = Field(default=200, description="业务状态码")
    message: str = Field(default="ok", description="响应消息")
    data: Optional[T] = Field(default=None, description="响应数据")
    request_id: Optional[str] = Field(default=None, description="请求追踪ID")

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(success=True, code=200, message=message, data=data)

    @classmethod
    def created(cls, data: Any = None, message: str = "创建成功") -> "ApiResponse":
        return cls(success=True, code=201, message=message, data=data)

    @classmethod
    def error(cls, code: int = 400, message: str = "请求错误", data: Any = None) -> "ApiResponse":
        return cls(success=False, code=code, message=message, data=data)

    @classmethod
    def not_found(cls, message: str = "资源不存在") -> "ApiResponse":
        return cls(success=False, code=404, message=message)

    @classmethod
    def server_error(cls, message: str = "服务器内部错误") -> "ApiResponse":
        return cls(success=False, code=500, message=message)


class PaginatedData(BaseModel):
    """分页数据"""
    items: list = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    pages: int = 0
