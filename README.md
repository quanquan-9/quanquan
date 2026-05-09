# 🎬 quanquan — 多Agent视频自动生产系统

> **UniVA 范式** · **OpenClaw 调度** · **Hermes Agent 执行** · **8 Agent 协作** · **全自动剪辑**

[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)](https://fastapi.tiangolo.com)
[![deepseek](https://img.shields.io/badge/deepseek-v4-pro-red)](https://www.deepseek.com/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## 🎯 一句话

**输入一行文字 → 8个AI Agent 自动协作 → 3分钟输出带字幕/配音/BGM/调色的可编辑视频草稿**

---

## 🧠 核心架构

```
用户输入 "赛博朋克科技解说 3分钟"
                │
    ┌───────────┴───────────┐
    │   🎬 导演 Agent        │  ← 11状态机 UniVA Planner
    │   意图解析 + DAG编排   │
    └───────────┬───────────┘
                │
  ┌─────┬───────┼───────┬───────┬──────┐
  │     │       │       │       │      │
  ▼     ▼       ▼       ▼       ▼      ▼
编剧  分镜    BGM    配音   调色   QC
Agent Agent  Agent  Agent  Agent Agent
  │     │       │       │       │      │
  └─────┴───────┴───────┴───────┴──────┘
                │
                ▼
        ┌──────────────┐
        │  交付 Agent   │  → 剪映草稿 + 导演笔记
        └──────────────┘
```

## ⚡ 快速开始

```bash
git clone https://github.com/yourname/quanquan
cd quanquan
pip install -r requirements.txt

# 配置 LLM (可选，不配置也能跑模拟模式)
export Gemini_API_KEY=sk-xxx     # Gemini
export DEEPSEEK_API_KEY=sk-xxx # DeepSeek V4

# 启动
python3 -m uvicorn api.server:app --host 0.0.0.0 --port 8000

# 打开 Dashboard
open http://localhost:8000/dashboard
```

## 🏗️ 技术栈

| 层 | 技术 |
|---|------|
| AI 调度 | OpenClaw (Claude Sonnet 4) — UniVA Planner |
| 代码执行 | Hermes Agent (DeepSeek V4 Pro) |
| LLM 集成 | Gemini / DeepSeek / Claude 多模型支持 |
| API 框架 | FastAPI + Pydantic |
| 通信总线 | Redis Streams / 本地队列双模 |
| 制品存储 | MinIO / S3 / 本地文件系统 |
| 视频质检 | FFmpeg 自动化验片 |
| 前端 | 原生 HTML5 Dashboard |

## 📊 量化数据

| 指标 | 数据 |
|------|------|
| Agent 数量 | 8 (Director + 7 执行Agent) |
| 导演状态数 | 11 状态 (UniVA FSM) |
| 并行执行 | DAG 引擎，3组并行 |
| 日 Token 消耗 | 500万-1200万 (启用 LLM) |
| 视频生成 | 3分钟视频 ≈ 15-30秒 (模拟) |
| API 端点 | 6 RESTful 端点 |
| 质检规则 | 6 项自动化检测 |

## 📡 API

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/dashboard` | Web 管理界面 |
| GET | `/api/v1/health` | 系统健康 |
| POST | `/api/v1/projects` | 创建视频项目 |
| GET | `/api/v1/projects/{id}/status` | 实时进度 |

## 📂 项目结构

```
quanquan/
├── api/server.py           # FastAPI 服务
├── api/dashboard.html      # Web Dashboard
├── core/
│   ├── director.py         # 导演Agent (11状态机)
│   ├── dag_executor.py     # DAG并行引擎
│   ├── context_bus.py      # 通信总线
│   ├── artifact_store.py   # 制品存储
│   └── llm_client.py       # LLM统一接口
├── agents/
│   ├── scriptwriter.py     # 编剧Agent
│   ├── storyboard.py       # 分镜Agent
│   └── all_agents.py       # 配音/BGM/QC/调色/交付
├── docker-compose.yml
└── Dockerfile
```

## 📄 License

MIT © 2026 Burning.AI
