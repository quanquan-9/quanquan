"""
测试 Settings 配置 — pydantic-settings 环境变量管理
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.settings import Settings


class TestSettings:
    """Settings 配置测试"""

    def test_defaults(self):
        """默认值"""
        s = Settings()
        assert s.QUANQUAN_ENV == "development"
        assert s.QUANQUAN_DEBUG is False
        assert s.DATABASE_URL == "sqlite+aiosqlite:///./data/quanquan.db"
        assert s.LLM_PROVIDER == "gemini"
        assert s.PORT == 8000
        assert s.WORKERS == 1

    def test_is_development(self):
        s = Settings()
        assert s.is_development is True
        assert s.is_production is False

    def test_is_production(self):
        s = Settings(QUANQUAN_ENV="production", JWT_SECRET="prod-secret-key")
        assert s.is_production is True
        assert s.is_development is False

    def test_custom_database_url(self):
        s = Settings(DATABASE_URL="postgresql+asyncpg://localhost/quanquan")
        assert s.DATABASE_URL == "postgresql+asyncpg://localhost/quanquan"

    def test_custom_llm_provider(self):
        s = Settings(LLM_PROVIDER="openai")
        assert s.LLM_PROVIDER == "openai"

    def test_cors_origins_default(self):
        s = Settings()
        assert s.CORS_ORIGINS == ["http://localhost:3000"]

    def test_cors_origins_custom(self):
        s = Settings(CORS_ORIGINS=["https://example.com", "https://app.example.com"])
        assert len(s.CORS_ORIGINS) == 2

    def test_business_limits(self):
        s = Settings()
        assert s.MAX_VIDEO_DURATION_SEC == 7200
        assert s.MAX_PROJECTS_PER_USER == 500
        assert s.RATE_LIMIT_PER_MINUTE == 60

    def test_jwt_secret_validation_development(self):
        """开发环境下默认 JWT_SECRET 不报错"""
        s = Settings(JWT_SECRET="change-me-in-production")
        assert s.JWT_SECRET == "change-me-in-production"

    def test_jwt_secret_validation_production(self):
        """生产环境下默认 JWT_SECRET 报错"""
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings(QUANQUAN_ENV="production", JWT_SECRET="change-me-in-production")

    def test_jwt_secret_custom_production(self):
        """生产环境下自定义 JWT_SECRET 通过"""
        s = Settings(QUANQUAN_ENV="production", JWT_SECRET="my-secret-key-12345")
        assert s.JWT_SECRET == "my-secret-key-12345"
