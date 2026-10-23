#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
# RAG 服务管理脚本
#
# 依赖关系:
#   API/MCP → Qdrant + Embedding + Rerank
#
# 用法: ./scripts/run.sh help
# ──────────────────────────────────────────────────────

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

LOG_DIR="$ROOT_DIR/logs"
CONF="conf/conf.yaml"
QDRANT_NAME="rag-qdrant"

mkdir -p "$LOG_DIR"

# ── 服务定义 ──────────────────────────────────────────

SERVICES=(qdrant embedding rerank api mcp)

service_label() {
    case "$1" in
        qdrant)    echo "Qdrant" ;;
        embedding) echo "Embedding" ;;
        rerank)    echo "Rerank" ;;
        api)       echo "API" ;;
        mcp)       echo "MCP" ;;
    esac
}

service_module() {
    case "$1" in
        embedding) echo "rag.embedding.server" ;;
        rerank)    echo "rag.rerank.server" ;;
        api)       echo "rag.main" ;;
        mcp)       echo "rag.mcp_server" ;;
    esac
}

service_port() {
    case "$1" in
        qdrant)    echo 6333 ;;
        embedding) echo 8002 ;;
        rerank)    echo 8003 ;;
        api)       echo 8001 ;;
        mcp)       echo 9000 ;;
    esac
}

service_timeout() {
    case "$1" in
        qdrant)           echo 30 ;;
        embedding|rerank) echo 180 ;;
        *)                echo 60 ;;
    esac
}

is_service() {
    local target=$1 svc
    for svc in "${SERVICES[@]}"; do
        if [ "$svc" = "$target" ]; then
            return 0
        fi
    done
    return 1
}

require_target() {
    local target=$1
    if [ "$target" != all ] && ! is_service "$target"; then
        log_error "未知服务: $target"
        echo "可用服务: all ${SERVICES[*]}" >&2
        exit 1
    fi
}

# ── 进程探测 ──────────────────────────────────────────

# 锚定到 python 进程本身，避免误匹配命令行里包含同样字符串的 shell
process_pattern() {
    local module
    module=$(service_module "$1")
    echo "^([^ ]*/)?python[0-9.]* -m ${module//./\\.}( |$)"
}

is_running() {
    local svc=$1
    if [ "$svc" = qdrant ]; then
        command -v docker >/dev/null 2>&1 &&
            docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$QDRANT_NAME"
        return
    fi
    pgrep -f "$(process_pattern "$svc")" >/dev/null 2>&1
}

service_pid() {
    local svc=$1
    if [ "$svc" = qdrant ]; then
        docker inspect -f '{{.State.Pid}}' "$QDRANT_NAME" 2>/dev/null || true
        return
    fi
    pgrep -f "$(process_pattern "$svc")" | head -n1
}

health_url() {
    if [ "$1" = qdrant ]; then
        echo "http://localhost:6333/healthz"
    else
        echo "http://localhost:$(service_port "$1")/health"
    fi
}

# 返回 0=就绪，1=进程已退出，2=超时
wait_ready() {
    local svc=$1 timeout=$2
    local url elapsed=0
    url=$(health_url "$svc")

    printf "  等待 %s 就绪" "$(service_label "$svc")"
    while [ "$elapsed" -lt "$timeout" ]; do
        if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
            printf " ✓ (%ss)\n" "$elapsed"
            return 0
        fi
        if ! is_running "$svc"; then
            printf " ✗\n"
            log_error "$(service_label "$svc") 进程已退出，最近日志："
            if [ "$svc" = qdrant ]; then
                docker logs --tail 20 "$QDRANT_NAME" 2>&1 || true
            else
                tail -n 20 "$LOG_DIR/$svc.log" 2>/dev/null || true
            fi
            return 1
        fi
        printf "."
        sleep 1
        elapsed=$((elapsed + 1))
    done

    printf " ✗\n"
    log_warn "$(service_label "$svc") 在 ${timeout}s 内未就绪，请查看 logs/$svc.log"
    return 2
}

# ── 启停实现 ──────────────────────────────────────────

start_service() {
    local svc=$1
    if is_running "$svc"; then
        log_info "$(service_label "$svc") 已在运行 (PID $(service_pid "$svc"))"
        return 0
    fi

    local module log_file
    module=$(service_module "$svc")
    log_file="$LOG_DIR/$svc.log"

    case "$svc" in
        qdrant)
            if ! command -v docker >/dev/null 2>&1; then
                log_error "需要 Docker 来启动 Qdrant"
                return 1
            fi
            log_info "启动 Qdrant ..."
            docker run -d --rm --name "$QDRANT_NAME" \
                -p 6333:6333 -p 6334:6334 \
                -v rag_qdrant:/qdrant/storage \
                qdrant/qdrant:latest >/dev/null
            ;;
        embedding|rerank)
            log_info "启动 $(service_label "$svc") 服务（--conf $CONF）..."
            nohup python -m "$module" --conf "$CONF" \
                >"$log_file" 2>&1 &
            ;;
        api)
            log_info "启动 RAG API 服务 (端口 8001) ..."
            nohup python -m "$module" >"$log_file" 2>&1 &
            ;;
        mcp)
            log_info "启动 MCP Server (端口 9000) ..."
            nohup python -m "$module" >"$log_file" 2>&1 &
            ;;
    esac
}

start_group() {
    local svc

    # 先全部拉起，模型服务可以并行加载
    for svc in "$@"; do
        start_service "$svc" || exit 1
    done

    for svc in "$@"; do
        local rc=0
        wait_ready "$svc" "$(service_timeout "$svc")" || rc=$?
        if [ "$rc" -eq 1 ]; then
            log_error "启动中止"
            exit 1
        fi
    done
}

stop_service() {
    local svc=$1
    if ! is_running "$svc"; then
        log_warn "$(service_label "$svc") 未运行"
        return 0
    fi

    if [ "$svc" = qdrant ]; then
        log_info "停止 Qdrant ..."
        docker stop "$QDRANT_NAME" >/dev/null 2>&1 || true
        return 0
    fi

    local pattern
    pattern=$(process_pattern "$svc")
    log_info "停止 $(service_label "$svc") ..."
    pkill -f "$pattern" 2>/dev/null || true

    local i=0
    while [ "$i" -lt 20 ] && is_running "$svc"; do
        sleep 0.5
        i=$((i + 1))
    done
    if is_running "$svc"; then
        log_warn "$(service_label "$svc") 未响应 TERM，强制结束"
        pkill -9 -f "$pattern" 2>/dev/null || true
    fi
    log_info "$(service_label "$svc") 已停止"
}

# ── 命令实现 ──────────────────────────────────────────

cmd_start() {
    local target=${1:-all}
    require_target "$target"

    case "$target" in
        all)
            start_group qdrant
            start_group embedding rerank
            start_group api mcp
            log_info "启动流程完成，当前状态："
            cmd_status
            ;;
        qdrant)
            start_group qdrant
            ;;
        embedding|rerank)
            start_group qdrant "$target"
            ;;
        api|mcp)
            start_group qdrant embedding rerank
            start_group "$target"
            ;;
    esac
}

cmd_stop() {
    local target=${1:-all}
    require_target "$target"

    if [ "$target" = all ]; then
        local svc
        for svc in mcp api rerank embedding qdrant; do
            stop_service "$svc"
        done
        log_info "全部服务已停止"
    else
        stop_service "$target"
    fi
}

cmd_restart() {
    local target=${1:-all}
    require_target "$target"
    cmd_stop "$target"
    cmd_start "$target"
}

cmd_status() {
    echo -e "\n  ${GREEN}服务${NC}         ${GREEN}PID${NC}       ${GREEN}端口${NC}    ${GREEN}状态${NC}"
    echo "  ──────────────────────────────────────"

    local svc pid port state
    for svc in "${SERVICES[@]}"; do
        port=$(service_port "$svc")
        pid="-"
        if ! is_running "$svc"; then
            state="❌ 未运行"
        else
            pid=$(service_pid "$svc" 2>/dev/null || true)
            [ -n "$pid" ] || pid="-"
            if curl -sf --max-time 2 "$(health_url "$svc")" >/dev/null 2>&1; then
                state="✅ 就绪"
            else
                state="⏳ 未就绪"
            fi
        fi
        printf "  %-12s %-8s %-6s %s\n" "$(service_label "$svc")" "$pid" "$port" "$state"
    done
    echo ""
}

cmd_logs() {
    local svc=${1:-}
    if [ -z "$svc" ] || ! is_service "$svc"; then
        log_error "用法: $0 logs <${SERVICES[*]}>"
        exit 1
    fi

    if [ "$svc" = qdrant ]; then
        if ! is_running qdrant; then
            log_error "Qdrant 未运行"
            exit 1
        fi
        exec docker logs -f --tail 100 "$QDRANT_NAME"
    fi

    local file="$LOG_DIR/$svc.log"
    if [ ! -f "$file" ]; then
        log_error "日志不存在: $file"
        exit 1
    fi
    exec tail -n 100 -f "$file"
}

usage() {
    cat <<EOF
RAG 服务管理脚本

用法: $0 <命令> [服务]

命令:
  start [服务]     启动服务（默认 all）
  stop [服务]      停止服务（默认 all）
  restart [服务]   重启服务（默认 all）
  status           查看服务状态
  logs <服务>      跟踪服务日志
  help             显示本帮助

服务:
  all              ${SERVICES[*]}
  qdrant           仅启动/停止 Qdrant
  embedding        启动时自动拉起 Qdrant
  rerank           启动时自动拉起 Qdrant
  api              启动时自动拉起 Qdrant/Embedding/Rerank
  mcp              启动时自动拉起 Qdrant/Embedding/Rerank

示例:
  $0 start                 # 启动全部服务
  $0 start api             # 只启动 API 及其依赖
  $0 restart rerank        # 重启 Rerank
  $0 stop embedding        # 只停止 Embedding
  $0 logs api              # 跟踪 API 日志
EOF
}

# ── 入口 ──────────────────────────────────────────────

COMMAND=${1:-help}
if [ $# -gt 0 ]; then
    shift
fi

case "$COMMAND" in
    start)   cmd_start "${1:-all}" ;;
    stop)    cmd_stop "${1:-all}" ;;
    restart) cmd_restart "${1:-all}" ;;
    status)  cmd_status ;;
    logs)    cmd_logs "${1:-}" ;;
    help|-h|--help) usage ;;
    *)
        log_error "未知命令: $COMMAND"
        echo ""
        usage
        exit 1
        ;;
esac
