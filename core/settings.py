"""
quanquan 全局配置 — 基于 pydantic-settings 的类型安全环境变量管理
用法: from core.settings import settings
"""

from typing import Optional, Literal, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """quanquan 全局配置。自动从 .env 文件和系统环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 运行环境 ──
    QUANQUAN_ENV: Literal["development", "staging", "production"] = "development"
    QUANQUAN_DEBUG: bool = False

    # ── 数据库 ──
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/quanquan.db"

    # ── LLM ──
    GEMINI_API_KEY: Optional[str] = None
    LLM_PROVIDER: Literal["gemini", "deepseek", "openai", "groq"] = "gemini"
    HTTPS_PROXY: Optional[str] = None

    # ── 认证 ──
    JWT_SECRET: str = "change-me-in-production"
    API_KEY_SALT: str = "change-me-too"

    # ── 存储路径 ──
    ARTIFACT_ROOT: str = "./artifacts"
    OUTPUT_ROOT: str = "./output"

    # ── 服务器 ──
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # ── CORS ──
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ── 业务限制 ──
    MAX_VIDEO_DURATION_SEC: int = 7200  # 2小时
    MAX_PROJECTS_PER_USER: int = 500
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── 验证器 ──
    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_must_be_set(cls, v: str, info) -> str:
        if v == "change-me-in-production":
            env = info.data.get("QUANQUAN_ENV", "development") if info.data else "development"
            if env == "production":
                raise ValueError("JWT_SECRET 必须在生产环境中设置！请修改 .env 文件。")
        return v

    @property
    def is_production(self) -> bool:
        return self.QUANQUAN_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.QUANQUAN_ENV == "development"


# 全局单例
settings = Settings()
