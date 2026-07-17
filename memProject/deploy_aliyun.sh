#!/bin/bash
# 阿里云 ECS 一键部署脚本 — 智能体记忆系统
set -e

echo "=== 1. 检查 Python ==="
python3 --version || { echo "需要安装 Python 3.12+"; exit 1; }

echo "=== 2. 检查 Docker ==="
docker --version || { 
    echo "安装 Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
}

echo "=== 3. 检查 Docker Compose ==="
docker compose version || { echo "需要 Docker Compose v2"; exit 1; }

echo "=== 4. 安装 Python 依赖 ==="
pip install -r requirements.txt -q 2>&1 | tail -3

echo "=== 5. 配置环境变量 ==="
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
    echo "请编辑 .env 填入 API Key: vim .env"
fi
source .env 2>/dev/null || true

echo "=== 6. 启动 Docker 服务 ==="
docker compose up -d
sleep 5
docker ps --filter "name=mem-"

echo "=== 7. 创建数据库表 ==="
python3 -m alembic upgrade head

echo "=== 8. 启动 FastAPI ==="
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
sleep 3
echo "服务 PID: $!"

echo "=== 9. 验证 ==="
curl -s http://localhost:8000/health

echo ""
echo "✅ 部署完成!"
echo "   健康检查: http://120.27.207.238:8000/health"
echo "   API 文档: http://120.27.207.238:8000/docs"
