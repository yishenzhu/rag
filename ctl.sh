#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
# RAG Service 管理脚本
#
# 依赖关系:
#   API/MCP → Qdrant + Embedding + Rerank

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PARENT_DIR="$(dirname "$ROOT_DIR")"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PARENT_DIR"

# 离线模式 —— 避免 HuggingFace Hub 联网挂起
export HF_HUB_OFFLINE=1

if [ -d .venv ]; then
    source .venv/bin/activate
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

mkdir -p "$ROOT_DIR/logs"

# ── 底层服务 ──────────────────────────────────────────

start_qdrant() {
    if ! command -v docker &>/dev/null; then
        log_error "需要 Docker 来启动 Qdrant"
        return 1
    fi
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^rag-qdrant$'; then
        log_info "Qdrant 已在运行"
    else
        log_info "启动 Qdrant ..."
        docker run -d --rm --name rag-qdrant \
            -p 6333:6333 -p 6334:6334 \
            -v rag_qdrant:/qdrant/storage \
            qdrant/qdrant:latest >/dev/null

        for i in $(seq 1 15); do
            if curl -sf http://localhost:6333/healthz >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        log_info "Qdrant 就绪"
    fi
}

start_embedding() {
    if pgrep -f "rag.embedding.server" >/dev/null 2>&1; then
        log_info "Embedding 服务已在运行"
        return
    fi
    log_info "启动 Embedding 服务 (端口 8002) ..."
    nohup python -m rag.embedding.server --model models/bge-m3 \
        > "$ROOT_DIR/logs/embedding.log" 2>&1 &
    log_info "Embedding 启动中，请稍候（模型加载约需 10-30 秒）"
}

start_rerank() {
    if pgrep -f "rag.rerank.server" >/dev/null 2>&1; then
        log_info "Rerank 服务已在运行"
        return
    fi
    log_info "启动 Rerank 服务 (端口 8003) ..."
    nohup python -m rag.rerank.server --model models/ms-marco-MiniLM-L6-v2 \
        > "$ROOT_DIR/logs/rerank.log" 2>&1 &
    log_info "Rerank 启动中，请稍候（模型加载约需 10-30 秒）"
}

# ── 应用服务 ──────────────────────────────────────────

start_api() {
    log_info "启动 RAG API 服务 (端口 8001) ..."
    nohup python -m rag.main > "$ROOT_DIR/logs/api.log" 2>&1 &
}

start_mcp() {
    log_info "启动 MCP Server (端口 9000) ..."
    nohup python -m rag.mcp_svr > "$ROOT_DIR/logs/mcp.log" 2>&1 &
}

# ── 命令实现 ──────────────────────────────────────────

cmd_start() {
    local target="${1:-all}"

    case "$target" in
        all)
            start_qdrant
            start_embedding
            start_rerank
            echo -n "等待模型加载"
            for i in $(seq 1 30); do
                if curl -sf http://localhost:8002/health >/dev/null 2>&1 &&
                   curl -sf http://localhost:8003/health >/dev/null 2>&1; then
                    echo ""
                    break
                fi
                echo -n "."
                sleep 1
            done
            echo ""
            start_api
            start_mcp
            log_info "所有服务已启动"
            log_info "  API:   http://localhost:8001"
            log_info "  MCP:   http://localhost:9000"
            log_info "  日志:  logs/{api,mcp,embedding,rerank}.log"
            ;;
        api)
            start_qdrant
            start_embedding
            start_rerank
            start_api
            ;;
        mcp)
            start_qdrant
            start_embedding
            start_rerank
            echo -n "等待模型加载"
            for i in $(seq 1 30); do
                if curl -sf http://localhost:8002/health >/dev/null 2>&1 &&
                   curl -sf http://localhost:8003/health >/dev/null 2>&1; then
                    echo ""
                    break
                fi
                echo -n "."
                sleep 1
            done
            echo ""
            start_mcp
            ;;
        *)
            log_error "未知服务: $target"
            exit 1
            ;;
    esac
}

cmd_stop() {
    log_info "停止服务 ..."
    pkill -f "rag.mcp_svr"  2>/dev/null && log_info "MCP Server 已停止" || true
    pkill -f "rag.main"               2>/dev/null && log_info "RAG API 已停止"    || true
    pkill -f "rag.rerank.server" 2>/dev/null && log_info "Rerank 已停止"  || true
    pkill -f "rag.embedding.server" 2>/dev/null && log_info "Embedding 已停止" || true

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^rag-qdrant$'; then
        log_info "停止 Qdrant ..."
        docker stop rag-qdrant >/dev/null
    fi
    log_info "全部已停止"
}

cmd_status() {
    echo -e "\n  ${GREEN}服务${NC}        ${GREEN}状态${NC}"
    echo "  ─────────────────────"

    # Qdrant (Docker 容器)
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^rag-qdrant$'; then
        printf "  %-12s ✅\n" "Qdrant"
    else
        printf "  %-12s ❌\n" "Qdrant"
    fi

    # 其余服务
    for s in "Embedding|embedding|8002" \
             "Rerank|rerank|8003" \
             "API|rag.main|8001" \
             "MCP|rag.mcp_svr|9000"; do
        IFS='|' read -r name cmd port <<< "$s"
        if ! pgrep -f "$cmd" >/dev/null 2>&1; then
            printf "  %-12s ❌\n" "$name"
        elif curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
            printf "  %-12s ✅\n" "$name"
        else
            printf "  %-12s ⏳\n" "$name"
        fi
    done
    echo ""
}

# ── 入口 ──────────────────────────────────────────────

usage() {
    echo "用法: ./ctl.sh <command> [service]"
    echo ""
    echo "命令:"
    echo "  start          启动所有服务"
    echo "  start api|mcp  启动单个应用服务（依赖的底层服务也会启动）"
    echo "  stop           停止所有服务"
    echo "  status         查看各服务运行状态"
    exit 0
}

case "${1:-help}" in
    start)  shift; cmd_start "${1:-all}" ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    *)      usage ;;
esac
