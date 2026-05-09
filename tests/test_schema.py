"""
测试 API schema — 统一响应格式
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.schema import ApiResponse, PaginatedData


class TestApiResponse:
    """ApiResponse 工厂方法测试"""

    def test_ok(self):
        r = ApiResponse.ok(data={"id": 1}, message="成功")
        assert r.success is True
        assert r.code == 200
        assert r.data == {"id": 1}
        assert r.message == "成功"

    def test_ok_defaults(self):
        r = ApiResponse.ok()
        assert r.success is True
        assert r.code == 200
        assert r.data is None
        assert r.message == "ok"

    def test_created(self):
        r = ApiResponse.created(data={"id": "proj_001"})
        assert r.success is True
        assert r.code == 201
        assert r.message == "创建成功"

    def test_error(self):
        r = ApiResponse.error(code=400, message="参数错误")
        assert r.success is False
        assert r.code == 400
        assert r.message == "参数错误"

    def test_not_found(self):
        r = ApiResponse.not_found()
        assert r.success is False
        assert r.code == 404
        assert r.message == "资源不存在"

    def test_not_found_custom(self):
        r = ApiResponse.not_found(message="项目 proj_001 不存在")
        assert r.success is False
        assert r.code == 404

    def test_server_error(self):
        r = ApiResponse.server_error()
        assert r.success is False
        assert r.code == 500

    def test_serialization(self):
        r = ApiResponse.ok(data={"name": "test"}, message="ok")
        d = r.model_dump()
        assert d["success"] is True
        assert d["code"] == 200
        assert d["data"] == {"name": "test"}

    def test_request_id_optional(self):
        r = ApiResponse.ok(data="hello")
        assert r.request_id is None

    def test_with_request_id(self):
        r = ApiResponse.ok(data="hello")
        r.request_id = "req-abc-123"
        assert r.request_id == "req-abc-123"


class TestPaginatedData:
    """PaginatedData 测试"""

    def test_defaults(self):
        p = PaginatedData()
        assert p.items == []
        assert p.total == 0
        assert p.page == 1
        assert p.page_size == 20
        assert p.pages == 0

    def test_with_data(self):
        p = PaginatedData(
            items=[{"id": 1}, {"id": 2}],
            total=100,
            page=2,
            page_size=20,
            pages=5,
        )
        assert len(p.items) == 2
        assert p.total == 100
        assert p.pages == 5
