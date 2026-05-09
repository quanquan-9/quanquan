# quanquan v6.0 — 企业级生产系统重构路线图

> **For Hermes:** 采用 subagent-driven-development 逐阶段实现。每个 Phase 独立可交付。

**目标：** 将 quanquan 从快速原型（v5.3, ~27K 行, 78 模块, 无持久化, 脆弱测试）重构为可测试、可维护、可扩展的企业级生产系统。

**架构转型：** 内存字典 → SQLAlchemy ORM；裸 dict → TypedDict/Pydantic；print → structlog；散装脚本 → 分层架构。

**技术栈：** Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, structlog, pytest, ruff, mypy, Docker Compose。

---

## 现状审计

| 维度 | 现状 | 目标 |
|------|------|------|
| 项目元数据 | ❌ 无 pyproject.toml | ✅ PEP 621 标准 |
| 依赖管理 | ❌ 7 行 requirements.txt | ✅ pyproject.toml + lock |
| 类型安全 | ❌ 几乎所有地方用 `dict`/`Any` | ✅ TypedDict + mypy strict |
| 数据持久化 | ❌ 纯内存 dict | ✅ SQLAlchemy + Alembic |
| 日志 | ❌ print + basic logger | ✅ structlog JSON |
| 测试覆盖率 | ❌ ~1.5% (400行/27000行) | ✅ ≥70% |
| 环境配置 | ❌ 无校验 | ✅ pydantic-settings |
| API 版本 | ❌ 无版本前缀 | ✅ /api/v1/ |
| 容器编排 | ❌ 单 Dockerfile | ✅ docker-compose 多服务 |
| CI/CD | 🟡 有但路径硬编码 | ✅ 修复 + matrix + coverage badge |
| 健康检查 | ❌ 无标准端点 | ✅ /health + /ready |
| 中间件 | ❌ 无 request-id/timing | ✅ 全链路追踪 |
| 文档 | ❌ 无架构文档 | ✅ ARCHITECTURE.md + ADR |

---

## Phase 0：基础设施 — 项目骨架标准化

**目标：** 建立可复现、可验证的开发环境。

### Task 0.1：创建 pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "quanquan"
version = "6.0.0"
description = "多Agent视频自动生产系统 · 工业级"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "redis>=5.0.0",
    "httpx>=0.27.0",
    "aiofiles>=24.0.0",
    "structlog>=24.0.0",
    "celery>=5.4.0",
    "python-multipart>=0.0.9",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "pytest-timeout>=2.3.0",
    "ruff>=0.5.0",
    "mypy>=1.11.0",
    "pre-commit>=3.8.0",
    "httpx>=0.27.0",  # for TestClient
    "locust>=2.30.0",
]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = false
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
timeout = 60

[tool.coverage.run]
source = ["core", "agents", "adapters", "api"]
omit = ["*/__pycache__/*", "*/test_*", "*/tests/*"]
```

### Task 0.2：创建 .env.example

```bash
# quanquan 环境变量模板 — 复制为 .env 并填入真实值
QUANQUAN_ENV=development
QUANQUAN_DEBUG=true

# 数据库
DATABASE_URL=sqlite+aiosqlite:///./data/quanquan.db

# LLM
GEMINI_API_KEY=your_key_here
LLM_PROVIDER=gemini
HTTPS_PROXY=http://127.0.0.1:7890

# 认证
JWT_SECRET=change-me-in-production
API_KEY_SALT=change-me-too

# 存储
ARTIFACT_ROOT=./artifacts
OUTPUT_ROOT=./output
```

### Task 0.3：创建 .env 校验模块

路径：`core/settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional, Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 环境
    QUANQUAN_ENV: Literal["development", "staging", "production"] = "development"
    QUANQUAN_DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/quanquan.db"

    # LLM
    GEMINI_API_KEY: Optional[str] = None
    LLM_PROVIDER: Literal["gemini", "deepseek", "openai"] = "gemini"
    HTTPS_PROXY: Optional[str] = None

    # 认证
    JWT_SECRET: str = "change-me-in-production"
    API_KEY_SALT: str = "change-me-too"

    # 存储
    ARTIFACT_ROOT: str = "./artifacts"
    OUTPUT_ROOT: str = "./output"

    # 服务
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_must_be_set(cls, v: str) -> str:
        if v == "change-me-in-production" and cls.QUANQUAN_ENV == "production":
            raise ValueError("JWT_SECRET must be set in production!")
        return v

settings = Settings()
```

### Task 0.4：创建 .gitignore 补充

补充现有 .gitignore：
```
.env
*.db
*.db-journal
*.db-wal
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
coverage.xml
dist/
```

### Phase 0 验证

```bash
python -c "from core.settings import settings; print(settings.model_dump())"
pip install -e ".[dev]"
ruff check . --select=E,F
```

---

## Phase 1：数据层 — SQLAlchemy + Alembic

**目标：** 淘汰内存 dict，建立持久化 ORM 层。

### Task 1.1：创建数据库引擎

路径：`core/database.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.settings import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.QUANQUAN_DEBUG)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### Task 1.2：定义核心 ORM 模型

路径：`core/models.py`

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, Text, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from core.database import Base
import enum

class ProjectStatus(str, enum.Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: f"proj_{uuid.uuid4().hex[:12]}")
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text)
    style: Mapped[str] = mapped_column(String(64), default="auto")
    duration_sec: Mapped[int] = mapped_column(Integer, default=180)
    status: Mapped[ProjectStatus] = mapped_column(SAEnum(ProjectStatus), default=ProjectStatus.CREATED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    artifacts: Mapped[List["Artifact"]] = relationship(back_populates="project", cascade="all, delete-orphan")

class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(256))
    stage: Mapped[str] = mapped_column(String(64))  # script_gen, voiceover, bgm, etc.
    content: Mapped[dict] = mapped_column(JSON)
    file_path: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    project: Mapped["Project"] = relationship(back_populates="artifacts")
```

### Task 1.3：初始化 Alembic

```bash
cd /data/quanquan
pip install alembic
alembic init alembic
```

修改 `alembic/env.py`：
```python
from core.database import Base, engine
from core.models import *  # noqa: F401,F403 — 导入所有模型以供 Alembic 检测
target_metadata = Base.metadata
```

### Task 1.4：创建 Repository 层

路径：`core/repository.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from core.models import Project, ProjectStatus

class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get(self, project_id: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Project]:
        result = await self.session.execute(
            select(Project).where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
            .offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(self, project_id: str, status: ProjectStatus, progress: float = None):
        project = await self.get(project_id)
        if project:
            project.status = status
            if progress is not None:
                project.progress = progress
            await self.session.commit()
        return project
```

### Task 1.5：迁移 DirectorAgent 使用 Repository

修改 `core/director.py`：
- 构造函数接受 `ProjectRepository` 而非 `_projects_store: dict`
- `_update_project` 改为调用 `repo.update_status()`
- 移除 `_projects_store` 引用

### Task 1.6：API 层注入 repository

在 `api/server.py` 中：
```python
from core.database import get_db, init_db
from core.repository import ProjectRepository

@app.on_event("startup")
async def startup():
    await init_db()
    # ... 其他启动逻辑

# 依赖注入
async def get_repo(db: AsyncSession = Depends(get_db)):
    return ProjectRepository(db)
```

### Phase 1 验证

```bash
pytest tests/ -x -v --tb=short
curl http://localhost:8000/api/v1/health
python -c "from core.database import init_db; import asyncio; asyncio.run(init_db()); print('DB OK')"
```

---

## Phase 2：类型安全 — TypedDict + mypy

**目标：** 消灭 `dict[str, Any]`，建立强类型合约。

### Task 2.1：定义核心 TypedDict

路径：`core/types.py`

```python
from typing import TypedDict, NotRequired, List, Optional, Literal

class Scene(TypedDict):
    id: str
    title: str
    duration_sec: int
    narration: str
    visual_description: str
    emotion: str
    transition: NotRequired[str]

class Script(TypedDict):
    title: str
    total_duration_sec: int
    scenes: List[Scene]
    keywords: List[str]
    style_tags: List[str]

class Shot(TypedDict):
    id: str
    scene_id: str
    type: Literal["wide", "medium", "close_up", "aerial", "tracking"]
    duration_sec: float
    description: str
    camera_movement: NotRequired[str]

class Storyboard(TypedDict):
    project_id: str
    total_shots: int
    shots: List[Shot]
    transitions: List[dict]

class VoiceSegment(TypedDict):
    scene_id: str
    text: str
    duration_sec: float
    pitch: NotRequired[float]
    speed: NotRequired[float]

class Voiceover(TypedDict):
    project_id: str
    voice_profile: str
    segments: List[VoiceSegment]
    audio_duration_sec: float
    audio_path: NotRequired[str]

# ... 其他 TypedDict: BGMTrack, StylizationResult, QCReport, DeliveryPackage
```

### Task 2.2：逐个模块添加类型注解

**优先级顺序：**
1. `core/types.py` — 所有 TypedDict 定义
2. `agents/scriptwriter.py` — ScriptwriterAgent.generate() 返回 `Script`
3. `agents/storyboard.py` — plan() 返回 `Storyboard`
4. `agents/voiceover.py` — generate() 返回 `Voiceover`
5. `core/director.py` — 内部方法签名
6. `core/llm_client.py` — LLM 客户端接口
7. `api/server.py` — API 端点返回类型

每个文件改动后运行：
```bash
mypy <文件路径> --strict 2>&1 | head -20
```

### Task 2.3：配置 mypy 渐进式严格

`.mypy.ini` 不存在则创建，逐步收紧：
```ini
[mypy]
python_version = 3.11
strict = false
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # 渐进开启

# 逐步对模块开启严格模式
[mypy-core.types]
disallow_untyped_defs = true

[mypy-core.models]
disallow_untyped_defs = true
```

### Phase 2 验证

```bash
mypy core/types.py core/models.py agents/scriptwriter.py --strict
pytest tests/ -x -q
```

---

## Phase 3：可观测性 — 结构化日志 + 健康检查

**目标：** 每行日志可查询，每个服务可监控。

### Task 3.1：集成 structlog

路径：`core/logging.py`

```python
import structlog
import logging
from core.settings import settings

def setup_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.QUANQUAN_DEBUG else structlog.processors.JSONRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置标准库日志转发到 structlog
    logging.basicConfig(format="%(message)s", level=logging.DEBUG if settings.QUANQUAN_DEBUG else logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer() if settings.QUANQUAN_DEBUG else structlog.processors.JSONRenderer()
    ))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]

def get_logger(name: str = __name__):
    return structlog.get_logger(name)
```

### Task 3.2：添加请求 ID 中间件

路径：`api/middleware.py`

```python
import uuid, time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from structlog.contextvars import bind_contextvars, clear_contextvars

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        bind_contextvars(request_id=request_id, path=request.url.path)
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        elapsed = time.monotonic() - start
        response.headers["X-Response-Time"] = f"{elapsed:.3f}s"
        clear_contextvars()
        return response
```

在 `server.py` 中：
```python
from api.middleware import RequestIDMiddleware
app.add_middleware(RequestIDMiddleware)
```

### Task 3.3：添加健康检查端点

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "6.0.0", "uptime": time.time() - START_TIME}

@app.get("/ready")
async def readiness_check():
    try:
        from core.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        raise HTTPException(503, detail=f"Database not ready: {e}")
```

### Task 3.4：全模块日志迁移

用 `from core.logging import get_logger; logger = get_logger(__name__)` 替换所有 `import logging; logger = logging.getLogger(...)`。

### Phase 3 验证

```bash
curl http://localhost:8000/health | python -m json.tool
curl http://localhost:8000/ready
# 检查日志输出格式（development 模式应为彩色结构化输出）
```

---

## Phase 4：测试体系 — 覆盖率 ≥70%

**目标：** 每个核心模块有独立的单元测试和集成测试。

### Task 4.1：创建测试 fixtures

路径：`tests/conftest.py`

```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from core.database import Base

TEST_DB_URL = "sqlite+aiosqlite:///./data/test.db"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def setup_db():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()
```

### Task 4.2：按模块补充单元测试

测试文件规划：

| 测试文件 | 覆盖模块 | 最低覆盖率 |
|----------|----------|-----------|
| `tests/test_models.py` | `core/models.py` | 90% |
| `tests/test_repository.py` | `core/repository.py` | 90% |
| `tests/test_types.py` | `core/types.py` | 100% |
| `tests/test_config.py` | `core/config_manager.py`, `core/settings.py` | 85% |
| `tests/test_director.py` | `core/director.py` | 80% |
| `tests/test_llm_client.py` | `core/llm_client.py` | 70% |
| `tests/test_scriptwriter.py` | `agents/scriptwriter.py` | 75% |
| `tests/test_storyboard.py` | `agents/storyboard.py` | 75% |
| `tests/test_voiceover.py` | `agents/voiceover.py` | 75% |
| `tests/test_bgm.py` | `agents/bgm.py` | 75% |
| `tests/test_stylization.py` | `agents/stylization.py` | 75% |
| `tests/test_qc.py` | `agents/qc.py` | 75% |
| `tests/test_delivery.py` | `agents/delivery.py` | 75% |
| `tests/test_vfx_engine.py` | `core/vfx_engine.py` | 70% |
| `tests/test_batch_export.py` | `core/batch_export.py` | 70% |
| `tests/test_api.py` | `api/server.py` | 80% |

### Task 4.3：API 集成测试

路径：`tests/test_api.py`

```python
from httpx import AsyncClient, ASGITransport
from api.server import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

async def test_create_project(client):
    resp = await client.post("/api/v1/projects", json={
        "text": "AI改变世界", "duration": 120, "style": "tech"
    })
    assert resp.status_code == 200
    assert "project_id" in resp.json()
```

### Phase 4 验证

```bash
pytest tests/ -v --cov=. --cov-report=term --cov-report=html
# 确认覆盖率 ≥70%
open htmlcov/index.html
```

---

## Phase 5：CI/CD 加固 — 可复现构建

**目标：** CI 真正可用，多服务编排就绪。

### Task 5.1：修复 GitHub Actions

修改 `.github/workflows/ci.yml`:
- `cd /data/quanquan` → `${{ github.workspace }}`
- 添加 `cache: pip` 到 `setup-python`
- 添加 coverage XML 上传
- 添加 test matrix 结果汇总

### Task 5.2：创建 docker-compose.yml

```yaml
version: "3.9"
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["./artifacts:/app/artifacts", "./output:/app/output"]
    depends_on: [redis]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    env_file: .env
    depends_on: [redis, api]
    command: celery -A worker.celery_app worker -Q video_long,video_short --concurrency=2 -l info
```

### Task 5.3：创建 .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.0
    hooks:
      - id: mypy
        files: ^(core|agents|adapters|api)/
        args: [--ignore-missing-imports]
```

### Phase 5 验证

```bash
pre-commit run --all-files
docker compose up -d
docker compose ps  # 所有服务 healthy
curl http://localhost:8000/health
docker compose down
```

---

## Phase 6：API 加固 — 版本化 + 分页 + 限流强化

**目标：** API 设计达到生产级标准。

### Task 6.1：API 版本路由

创建 `api/v1/__init__.py`，将现有 79 个端点迁移到 `/api/v1/` 下。

```python
from fastapi import APIRouter

v1_router = APIRouter(prefix="/api/v1")

# 在 server.py 中：
app.include_router(v1_router)
```

现有 `/api/v1/director/status` 等端点移到 `v1_router` 中。

### Task 6.2：通用分页模型

```python
class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int

# 分页依赖
async def pagination(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return {"page": page, "page_size": page_size, "offset": (page - 1) * page_size}
```

### Task 6.3：CORS 加固

生产环境不允许 `allow_origins=["*"]`：
```python
app.add_middleware(CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if not settings.QUANQUAN_DEBUG else ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
)
```

### Task 6.4：输入校验强化

- 所有 `BaseModel` request 添加 `max_length` 等约束
- 视频时长上限从 36000s (10h) 降到 7200s (2h)
- 添加 `@field_validator` 防止 XSS/注入

### Phase 6 验证

```bash
curl http://localhost:8000/api/v1/projects?page=1&page_size=10
curl http://localhost:8000/health  # 应保持 200
pytest tests/test_api.py -v
```

---

## Phase 7：文档 — 架构文档 + ADR

**目标：** 新开发者 30 分钟内可上手。

### Task 7.1：创建 ARCHITECTURE.md

```
# quanquan 系统架构

## 分层架构
┌─────────────────────────┐
│   API Layer (FastAPI)   │  ← api/server.py, api/v1/, api/middleware.py
├─────────────────────────┤
│   Service Layer         │  ← core/director.py, core/vfx_engine.py, ...
├─────────────────────────┤
│   Agent Layer           │  ← agents/scriptwriter.py, agents/voiceover.py, ...
├─────────────────────────┤
│   Domain Layer          │  ← core/models.py, core/types.py, core/repository.py
├─────────────────────────┤
│   Infrastructure         │  ← core/database.py, core/logging.py, core/settings.py
└─────────────────────────┘

## 数据流
User → API → DirectorAgent (11-state FSM) → DAG Executor → Agents → Artifacts → Delivery

## 关键设计决策
1. SQLAlchemy Async — 全链路异步 IO
2. Repository Pattern — 数据访问抽象
3. TypedDict — 轻量级类型合约
4. structlog — 结构化日志
5. DAG Executor — 并行 Agent 调度
```

### Task 7.2：创建 CONTRIBUTING.md

- 开发环境搭建（`pip install -e ".[dev]"`）
- TDD 工作流（写测试 → 失败 → 实现 → 通过 → 重构）
- 代码规范（ruff + mypy）
- PR 流程

### Task 7.3：创建 ADR 目录

```
docs/adr/
├── 001-use-sqlalchemy-async.md
├── 002-use-typeddict-over-pydantic-for-internal.md
├── 003-use-structlog-for-observability.md
├── 004-repository-pattern-for-data-access.md
```

### Phase 7 验证

```bash
cat docs/ARCHITECTURE.md
ls docs/adr/
```

---

## 执行顺序与时间估计

| Phase | 预估时间 | 可并行 | 依赖 |
|-------|---------|--------|------|
| 0 — 基础设施 | 30 min | — | — |
| 1 — 数据层 | 2-3 h | — | Phase 0 |
| 2 — 类型安全 | 3-4 h | Phase 1 后 | Phase 1 |
| 3 — 可观测性 | 1-2 h | Phase 1 后 | Phase 0 |
| 4 — 测试体系 | 4-6 h | 任何 Phase 后 | Phase 1+2 |
| 5 — CI/CD 加固 | 1 h | — | Phase 1+3 |
| 6 — API 加固 | 2-3 h | — | Phase 1+2+3 |
| 7 — 文档 | 1-2 h | — | 所有 Phase 后 |

**可优化：** Phase 2 和 Phase 3 可并行执行（不同关注点，文件不冲突）。

---

## 风险与回退

| 风险 | 缓解措施 |
|------|---------|
| SQLAlchemy 迁移破坏现有逻辑 | 保留旧 `_projects_store` 作为 fallback，渐进迁移 |
| TypedDict 导致循环导入 | 统一从 `core/types.py` 导入，避免模块间类型依赖 |
| 测试补充耗时过长 | 优先覆盖核心路径（director, scriptwriter, api） |
| mypy 报错过多 | 分模块渐进开启，先 `warn_return_any` 再 `disallow_untyped_defs` |

---

**签名：** 魔女虾 (Hermes Agent) · 2026-05-09
**下一动作：** 大魔王审阅路线图 → 确认后从 Phase 0 开始执行
