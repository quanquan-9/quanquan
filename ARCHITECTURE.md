# quanquan 架构文档 v7.0

> 多 Agent 视频自动生产系统 · UniVA 范式 · DAG 并行执行

## 1. 系统概览

quanquan 是一个基于 UniVA（规划-执行）范式的多智能体视频自动生产系统。
用户通过多模态输入表达创意，系统在"导演 Agent"的编排下，由多个专业 Agent
协同完成脚本、分镜、配音、BGM、调色、审核与交付。

```
用户输入 → Director(Planner) → DAG Executor → [Scriptwriter, Storyboard, Voiceover, BGM, QC, Styling] → 交付
                  ↕                      ↕
            Context Bus ←──────── Artifact Store
```

## 2. 分层架构

```
┌─────────────────────────────────────────────────┐
│                   API 层 (FastAPI)               │
│  45+ REST 端点 · WebSocket · 认证/限流 · Swagger │
├─────────────────────────────────────────────────┤
│               Director Agent (调度器)            │
│  11状态机 · DAG编排 · 全局质量管控 · 动态重规划   │
├─────────────────────────────────────────────────┤
│              多 Agent 执行层                     │
│  Scriptwriter · Storyboard · Voiceover           │
│  BGM · QualityControl · Stylization · Delivery   │
├─────────────────────────────────────────────────┤
│          核心基础设施 (v7.0 新增)                 │
│  ContextBus · ArtifactStore · DAGExecutor        │
├─────────────────────────────────────────────────┤
│          业务核心模块                             │
│  LLM Client · TTS Engine · VFX Engine            │
│  Video Renderer · Analytics · Memory Engine      │
├─────────────────────────────────────────────────┤
│          存储 & 基础设施                          │
│  SQLAlchemy 2.0+ · SQLite/PostgreSQL · structlog │
└─────────────────────────────────────────────────┘
```

## 3. 核心基础设施 (v7.0 新增)

### 3.1 ContextBus — 上下文总线

**文件**: `core/context_bus.py` · **行数**: ~170

异步事件驱动的 Agent 通信总线。所有 Agent 不直接点对点通信，
通过 ContextBus 发布/订阅标准化事件。

**事件类型**:
- `TASK_DISPATCH` — 任务分发
- `RESULT_PUBLISH` — 结果发布
- `QC_FAILED` — 质检失败
- `REPLAN_REQUEST` — 重规划请求
- `NODE_COMPLETE` — 节点完成
- `PIPELINE_COMPLETE` — 管线完成
- `HEARTBEAT` — 心跳

**后端**: 内存 (asyncio.Queue) · 生产可切 Redis Streams

### 3.2 ArtifactStore — 版本化制品库

**文件**: `core/artifact_store.py` · **行数**: ~253

所有 Agent 产出物（脚本/分镜/配音/BGM/QC报告）的版本化存储。

**特性**:
- 自动版本递增 (v1 → v2 → v3)
- 内存缓存 (TTL 300s, LRU 淘汰)
- JSON 文件后端 · 生产可切 MinIO/S3
- 元数据追踪 (hash, size, timestamps)

### 3.3 DAGExecutor — DAG 并行执行引擎

**文件**: `core/dag_executor.py` · **行数**: ~290

读取导演生成的 DAG 定义，拓扑排序后并行执行独立节点。

**特性**:
- Kahn 算法拓扑排序 → 分层并行执行
- 节点超时 + 自动重试 (最多3次)
- Agent 注册机制 (可插拔执行器)
- 降级: Agent 未注册时自动 mock
- 与 ContextBus + ArtifactStore 集成

**节点状态机**: `PENDING → RUNNING → COMPLETED / FAILED / TIMEOUT / SKIPPED`

## 4. Agent 体系

| Agent | 文件 | 版本 | 行数 | 能力 |
|-------|------|------|------|------|
| Director | `core/director.py` | v3.0 | 451 | 11状态机, DAG编排, 动态重规划 |
| Scriptwriter | `agents/scriptwriter.py` | v3.0 | 870 | CoT推理, 多模型投票, 自我批判 |
| Storyboard | `agents/storyboard.py` | - | - | 视觉规划, 素材语义匹配 |
| Voiceover | `agents/all_agents.py` | - | 219 | 智能配音, 音效增强 |
| BGM | `agents/all_agents.py` | - | 219 | 情绪匹配, 节奏对齐 |
| QC | `agents/qc.py` | v3.0 | 254 | 6检测器插件, 缺陷分级 |
| Stylization | `agents/all_agents.py` | - | 219 | AI风格迁移, LUT调色 |
| Delivery | `agents/all_agents.py` | - | 219 | 剪映草稿组装, 导演笔记 |
| Memory | `agents/memory.py` | - | - | 分层记忆, 衰减演化 |

## 5. API 路由表 (v7.0)

### 页面路由 (HTML Dashboard)
```
GET  /api/v1/health              → 健康监控面板
GET  /api/v1/vfx/presets         → VFX 特效引擎 (22种滤镜)
GET  /api/v1/platforms            → 多平台发布 (3平台)
GET  /api/v1/analytics/dashboard  → 分析面板
GET  /api/v1/batch                → 批量处理中心
GET  /api/v1/thumbnail            → AI 缩略图生成器
```

### 数据端点 (JSON)
```
GET  /api/v1/health/status           → 健康状态
GET  /api/v1/vfx/presets-data        → VFX预设数据
GET  /api/v1/vfx/transitions         → 转场效果列表
GET  /api/v1/vfx/particles           → 粒子特效列表
GET  /api/v1/analytics/dashboard-data → 分析数据
GET  /api/v1/analytics/cost          → 成本估算
GET  /api/v1/system/info             → 系统信息
GET  /api/v1/director/status         → 导演状态
GET  /api/v1/director/projects       → 项目列表
GET  /api/v1/batch/status            → 批量状态
```

### 操作端点 (POST)
```
POST /api/v1/create              → 创建项目
POST /api/v1/batch/submit        → 批量提交
POST /api/v1/publish             → 发布到平台
POST /api/v1/projects/{id}/feedback → 用户反馈
```

## 6. 测试覆盖

**文件**: `tests/test_core_infrastructure.py` · 6 个集成测试

| 测试 | 验证内容 |
|------|---------|
| `test_context_bus_pubsub` | 发布/订阅 + 事件分发 |
| `test_artifact_store_crud` | CRUD + 版本化 + 缓存 |
| `test_heartbeat` | 心跳 + 过期检测 |
| `test_dag_executor_basic` | 并行DAG + 制品存储 |
| `test_dag_executor_sequential` | 顺序依赖DAG |
| `test_dag_executor_mixed_parallel` | 混合并行+顺序 |

运行: `python3 tests/test_core_infrastructure.py`

## 7. 启动指南

```bash
# 安装依赖
pip install fastapi uvicorn sqlalchemy aiosqlite

# 启动服务
cd /data/quanquan
python3 -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# API 文档
open http://localhost:8000/docs      # Swagger
open http://localhost:8000/redoc     # ReDoc
open http://localhost:8000/          # Landing Page
```

## 8. 技术栈

- **后端**: Python 3.8+ / FastAPI / asyncio
- **数据库**: SQLAlchemy 2.0+ / SQLite (开发) / PostgreSQL (生产)
- **AI/LLM**: Gemini 2.5 Flash / Groq / DeepSeek
- **视频**: FFmpeg / VFX Engine / LUT Library
- **日志**: structlog / 标准 logging
- **测试**: pytest + asyncio

---

*最后更新: 2026-05-09 · v7.0*
