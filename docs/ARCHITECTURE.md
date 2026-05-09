# quanquan 系统架构

> v6.0 — 多Agent视频自动生产系统 · 企业级

## 分层架构

```
┌─────────────────────────────────┐
│   API Layer (FastAPI)           │  ← api/server.py, api/v1/, api/middleware.py
│   REST + WebSocket + 静态页面     │
├─────────────────────────────────┤
│   Service Layer                 │  ← core/director.py, core/vfx_engine.py, ...
│   业务流程 + DAG编排              │
├─────────────────────────────────┤
│   Agent Layer                   │  ← agents/scriptwriter, voiceover, bgm, ...
│   9个专业化AI智能体               │
├─────────────────────────────────┤
│   Domain Layer                  │  ← core/models.py, core/types.py, core/repository.py
│   ORM模型 + TypedDict + Repository│
├─────────────────────────────────┤
│   Infrastructure                │  ← core/database.py, core/logging.py, core/settings.py
│   DB引擎 + 日志 + 配置            │
└─────────────────────────────────┘
```

## 数据流

```
User → API → DirectorAgent (11状态机)
                ↓
            DAG Executor (并行调度)
                ↓
    ┌───────────┼───────────┐
    ↓           ↓           ↓
ScriptWriter  Voiceover    BGM
    ↓           ↓           ↓
Storyboard   Styling      QC
    ↓
Delivery → 制品文件系统 + 数据库
```

## 技术栈

| 层 | 技术 |
|----|------|
| Web框架 | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.0 (Async) |
| 迁移 | Alembic |
| 配置 | pydantic-settings |
| 日志 | structlog |
| 测试 | pytest + pytest-asyncio + pytest-cov |
| 类型 | TypedDict + mypy |
| 质量 | ruff + pre-commit |
| 容器 | Docker + docker-compose |
| CI/CD | GitHub Actions |

## 关键设计决策

1. **Async SQLAlchemy** — 全链路异步IO，FastAPI原生支持
2. **Repository Pattern** — 数据访问抽象，上层不直接操作ORM
3. **TypedDict** — 轻量级类型合约，无运行时开销
4. **structlog** — 结构化日志，开发彩色/生产JSON
5. **DAG Executor** — 并行Agent调度，支持依赖图
6. **11状态机 Director** — 完整的视频生产生命周期管理

## 目录结构

```
quanquan/
├── api/            # FastAPI应用 + 静态页面
│   ├── server.py   # 主应用 (79+端点)
│   ├── middleware.py
│   └── pages/      # 8个独立管理页面
├── core/           # 核心业务逻辑
│   ├── database.py # SQLAlchemy引擎
│   ├── models.py   # ORM模型
│   ├── repository.py # 数据访问层
│   ├── types.py    # TypedDict定义
│   ├── settings.py # 配置管理
│   ├── logging.py  # 结构化日志
│   └── ...         # 30+功能模块
├── agents/         # AI智能体
│   ├── scriptwriter.py
│   ├── voiceover.py
│   └── ...
├── adapters/       # 外部适配器
├── tests/          # 测试套件
├── alembic/        # 数据库迁移
├── pyproject.toml  # 项目元数据
├── docker-compose.yml
└── .github/workflows/ci.yml
```
