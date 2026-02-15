#!/bin/bash
# TrendPulse 一键启动脚本
# 同时启动后端 FastAPI 服务和前端 Flutter Web 应用

set -e

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  TrendPulse 舆情脉冲 - 启动脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查后端虚拟环境
if [ ! -f "$PROJECT_ROOT/backend/.venv/bin/python" ]; then
    echo -e "${RED}[错误] 未找到后端虚拟环境，请先执行:${NC}"
    echo "  cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 检查 .env 文件
if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
    echo -e "${YELLOW}[警告] 未找到 backend/.env 文件，从模板复制...${NC}"
    cp "$PROJECT_ROOT/backend/.env.example" "$PROJECT_ROOT/backend/.env"
    echo -e "${YELLOW}请编辑 backend/.env 填入你的 LLM API 密钥${NC}"
    exit 1
fi

# 加载环境变量
set -a
source "$PROJECT_ROOT/backend/.env"
set +a

# 清理函数：退出时杀掉所有子进程
cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    kill $(jobs -p) 2>/dev/null
    wait 2>/dev/null
    echo -e "${GREEN}所有服务已停止${NC}"
}
trap cleanup EXIT INT TERM

# ===== 启动后端 =====
echo -e "${GREEN}[1/3] 启动后端服务 (FastAPI)...${NC}"
cd "$PROJECT_ROOT"
backend/.venv/bin/python -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload &
BACKEND_PID=$!
sleep 2

if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}[错误] 后端启动失败，请检查日志${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ 后端已启动: http://localhost:8000${NC}"
echo -e "${GREEN}    API文档: http://localhost:8000/docs${NC}"

# ===== 构建前端 =====
if command -v flutter &> /dev/null; then
    echo -e "${GREEN}[2/3] 构建前端 (Flutter Web)...${NC}"
    cd "$PROJECT_ROOT/frontend"
    flutter pub get --no-example > /dev/null 2>&1
    flutter build web --no-tree-shake-icons 2>&1 | tail -3
    echo -e "${GREEN}  ✓ 前端构建完成${NC}"

    # ===== 启动前端静态服务 =====
    echo -e "${GREEN}[3/3] 启动前端服务...${NC}"
    cd "$PROJECT_ROOT/frontend/build/web"
    python3 -m http.server 3000 &
    FRONTEND_PID=$!
    echo -e "${GREEN}  ✓ 前端已启动: http://localhost:3000${NC}"
else
    echo -e "${YELLOW}[跳过] Flutter 未安装，仅启动后端${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  所有服务已启动${NC}"
echo -e "${GREEN}  后端 API:  http://localhost:8000${NC}"
echo -e "${GREEN}  API 文档:  http://localhost:8000/docs${NC}"
echo -e "${GREEN}  前端页面:  http://localhost:3000${NC}"
echo -e "${GREEN}  按 Ctrl+C 停止所有服务${NC}"
echo -e "${GREEN}========================================${NC}"

wait
