#!/usr/bin/env bash
# ==============================================================================
# web.sh - 跨平台 Web 服務啟動與管理工具 (Linux / macOS / WSL)
#
# 用法:
#   ./web.sh [regs|design|status|stop|restart] [--port PORT] [--host HOST]
#   ./規範查詢台.sh
#   ./設計工作台.sh
# ==============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
TEMP_DIR="$ROOT/_temp"
PID_FILE="$TEMP_DIR/regs_server.pid"
LOG_FILE="$TEMP_DIR/regs_server.log"

DEFAULT_HOST="${CIVIL_AI_HOST:-0.0.0.0}"
DEFAULT_PORT="8765"
HOST="$DEFAULT_HOST"
PORT="$DEFAULT_PORT"

# 尋找可用的 Python 3.10+
find_python() {
    # 1. 環境變數指定
    if [ -n "${CIVIL_AI_PYTHON:-}" ] && [ -x "$CIVIL_AI_PYTHON" ]; then
        echo "$CIVIL_AI_PYTHON"
        return 0
    fi

    # 2. 專案根目錄虛擬環境
    if [ -x "$ROOT/.venv/bin/python" ]; then
        echo "$ROOT/.venv/bin/python"
        return 0
    fi
    if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
        echo "$ROOT/.venv/Scripts/python.exe"
        return 0
    fi

    # 3. PATH 上的 python3 / python
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
                echo "$cmd"
                return 0
            fi
        fi
    done

    return 1
}

# 檢查指定 port 服務是否存活
is_server_running() {
    local target_port="${1:-$PORT}"
    curl -s --connect-timeout 1 -o /dev/null "http://127.0.0.1:${target_port}/api/topics" >/dev/null 2>&1
}

# 印出可用連線網址（本機、區域網路、Tailscale）
print_urls() {
    local p="${1:-$PORT}"
    local path="${2:-/}"
    echo "  - 本機網址：http://127.0.0.1:${p}${path}"
    local lan_ip
    lan_ip=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '^127\.' | grep -v '^172\.' | head -n 1 || true)
    if [ -n "$lan_ip" ]; then
        echo "  - 區網網址：http://${lan_ip}:${p}${path}"
    fi
    local ts_ip
    ts_ip=$(ip -4 addr show dev tailscale0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)
    if [ -n "$ts_ip" ]; then
        echo "  - Tailscale：http://${ts_ip}:${p}${path}"
    fi
}

# 開啟瀏覽器
open_browser() {
    local url="$1"

    # 若為 SSH 連線且無 DISPLAY（非 macOS），不嘗試彈窗
    if [ -n "${SSH_CLIENT:-}" ] || [ -n "${SSH_TTY:-}" ]; then
        if [ -z "${DISPLAY:-}" ] && [ "$(uname -s)" != "Darwin" ]; then
            return 0
        fi
    fi

    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1 &
    elif command -v wslview >/dev/null 2>&1; then
        wslview "$url" >/dev/null 2>&1 &
    elif [ -n "${PYEXE:-}" ]; then
        "$PYEXE" -m webbrowser "$url" >/dev/null 2>&1 &
    fi
}

# 啟動伺服器
start_server() {
    local page="${1:-regs}"
    local target_path="/"
    [ "$page" = "design" ] && target_path="/design"
    local target_url="http://127.0.0.1:${PORT}${target_path}"

    if is_server_running "$PORT"; then
        echo "[資訊] Web 服務已在執行中。"
        print_urls "$PORT" "$target_path"
        open_browser "$target_url"
        return 0
    fi

    PYEXE="$(find_python)"
    if [ $? -ne 0 ] || [ -z "$PYEXE" ]; then
        echo "[錯誤] 找不到 Python 3.10+。" >&2
        echo "       請先安裝 Python 3.10+ 或建立虛擬環境：" >&2
        echo "       python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
        return 1
    fi

    mkdir -p "$TEMP_DIR"

    echo "[啟動] 使用 Python: $PYEXE"
    echo "[啟動] 正在啟動 Web 服務於 port ${PORT} (host ${HOST}) ..."

    # 以背景方式執行，記錄日誌與 PID
    nohup "$PYEXE" -E -P -X utf8 "$ROOT/tools/regs/regs_server.py" --web --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    # 等候服務啟動 (最多等 5 秒)
    ready=0
    for i in $(seq 1 25); do
        if is_server_running "$PORT"; then
            ready=1
            break
        fi
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            echo "[錯誤] 服務啟動失敗，請檢視日誌：$LOG_FILE" >&2
            [ -f "$LOG_FILE" ] && tail -n 20 "$LOG_FILE" >&2
            rm -f "$PID_FILE"
            return 1
        fi
        sleep 0.2
    done

    if [ $ready -eq 1 ]; then
        echo "[成功] Web 服務已在背景啟動 (PID: $SERVER_PID)"
        print_urls "$PORT" "$target_path"
        echo "  - 服務日誌檔：$LOG_FILE"
        open_browser "$target_url"
    else
        echo "[警告] 服務已在背景啟動 (PID: $SERVER_PID)，但健康檢查等待逾時。" >&2
        echo "       請檢查日誌：$LOG_FILE" >&2
        print_urls "$PORT" "$target_path"
        open_browser "$target_url"
    fi
}

# 停止伺服器
stop_server() {
    local stopped=0

    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "[停止] 正在停止 Web 服務 (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            for i in $(seq 1 10); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 0.2
            done
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            stopped=1
        fi
        rm -f "$PID_FILE"
    fi

    # 清理所有殘留的 regs_server.py --web
    if pgrep -f "regs_server\.py.*--web" >/dev/null 2>&1; then
        echo "[停止] 清理殘留的 regs_server.py 行程..."
        pkill -f "regs_server\.py.*--web" 2>/dev/null || true
        stopped=1
    fi

    if [ $stopped -eq 1 ]; then
        echo "[成功] Web 服務已停止。"
    else
        echo "[資訊] 目前沒有執行中的 Web 服務。"
    fi
}

# 狀態查詢
status_server() {
    if is_server_running "$PORT"; then
        local pid=""
        if [ -f "$PID_FILE" ]; then
            pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        fi
        echo "[狀態] Web 服務【執行中】"
        [ -n "$pid" ] && echo "  - PID: $pid"
        print_urls "$PORT" "/"
        [ -f "$LOG_FILE" ] && echo "  - 日誌檔案：$LOG_FILE"
        return 0
    else
        echo "[狀態] Web 服務【未執行】"
        rm -f "$PID_FILE" 2>/dev/null || true
        return 0
    fi
}

# 參數解析
ACTION="${1:-regs}"
shift || true

while [ $# -gt 0 ]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

case "$ACTION" in
    regs|--regs|lookup)
        start_server "regs"
        ;;
    design|workbench|--design)
        start_server "design"
        ;;
    stop|--stop|down)
        stop_server
        ;;
    restart|--restart)
        stop_server
        sleep 0.5
        start_server "regs"
        ;;
    status|--status)
        status_server
        ;;
    help|-h|--help)
        echo "用法: $0 [regs|design|status|stop|restart] [--port PORT] [--host HOST]"
        echo ""
        echo "指令選項:"
        echo "  regs       啟動服務並開啟「規範查詢台」 (http://${HOST}:${PORT}/)"
        echo "  design     啟動服務並開啟「工程設計工作台」 (http://${HOST}:${PORT}/design)"
        echo "  status     檢查服務執行狀態"
        echo "  stop       停止背景 Web 服務"
        echo "  restart    重新啟動服務"
        echo ""
        echo "額外參數:"
        echo "  --port PORT  指定 Port (預設 8765)"
        echo "  --host HOST  指定 Host (預設 127.0.0.1，跨機填 0.0.0.0)"
        ;;
    *)
        start_server "regs"
        ;;
esac
