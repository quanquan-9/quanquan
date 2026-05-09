# quanquan Makefile
.PHONY: run dev test lint clean install setup docker-build

# 默认目标
help:
	@echo "quanquan v5.0 — 多Agent视频生产系统"
	@echo ""
	@echo "  make install    安装依赖"
	@echo "  make run        启动服务器 (生产模式)"
	@echo "  make dev        启动服务器 (热重载开发模式)"
	@echo "  make test       运行测试"
	@echo "  make lint       代码检查"
	@echo "  make clean      清理缓存"
	@echo "  make setup      完整初始化"
	@echo "  make docker     构建 Docker 镜像"

install:
	pip install -r requirements.txt 2>/dev/null || pip install fastapi uvicorn pydantic aiohttp pyyaml

run:
	uvicorn api.server:app --host 0.0.0.0 --port 8000

dev:
	uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload --log-level info

test:
	python3 -m pytest tests/ -v --tb=short 2>/dev/null || python3 tests/test_e2e.py

lint:
	python3 -c "
import sys, os
errors = 0
for root, dirs, files in os.walk('.'):
    if '__pycache__' in root or '.git' in root: continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path) as fh:
                    compile(fh.read(), path, 'exec')
            except SyntaxError as e:
                print(f'  ❌ {path}: {e}')
                errors += 1
print(f'Lint: {errors} errors' if errors else 'Lint: all clean ✅')
"

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .pytest_cache 2>/dev/null || true

setup: install
	@echo "✅ quanquan setup complete!"
	@echo "Run: make dev"

docker-build:
	docker build -t quanquan:latest .

docker-run:
	docker run -p 8000:8000 quanquan:latest

version:
	@python3 -c "from api.server import app; print('quanquan v5.0.0')"
