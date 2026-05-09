# 贡献指南

## 快速开始

```bash
# 1. 克隆项目
git clone <repo-url> && cd quanquan

# 2. 创建虚拟环境并安装
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 等

# 4. 初始化数据库
alembic upgrade head

# 5. 运行开发服务器
make dev
# 访问 http://localhost:8000
# API文档 http://localhost:8000/docs
```

## 开发工作流 (TDD)

1. **写测试** — `pytest tests/test_xxx.py -v`
2. **看失败** — 确认测试因功能缺失而失败
3. **写代码** — 最小实现使测试通过
4. **看通过** — `pytest tests/ -v`
5. **重构** — 消除重复，保持测试通过

## 代码规范

```bash
# 格式化 + 检查
ruff check . --fix
ruff format .

# 类型检查
mypy core/ agents/ api/ --ignore-missing-imports

# 跑全部测试
pytest tests/ -v --cov=core --cov=agents --cov=api
```

## 提交规范

```
feat: 添加新功能
fix: 修复bug
docs: 文档变更
test: 测试相关
refactor: 重构
chore: 构建/工具变更
```

## 分支策略

- `main` — 生产就绪
- `develop` — 集成测试
- `feature/*` — 功能开发
- `fix/*` — 紧急修复

## PR 流程

1. 从 `develop` 创建分支
2. 遵循TDD开发
3. 确保 `pytest tests/` 全部通过
4. 确保 `ruff check .` 无报错
5. 提交PR到 `develop`
6. 等待CI通过 + 代码审查
