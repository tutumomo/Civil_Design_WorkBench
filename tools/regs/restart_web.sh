#!/usr/bin/env bash
# 重啟規範查詢台／工程設計工作台的本機服務 (Linux / macOS)
# 用法: bash tools/regs/restart_web.sh
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$DIR/web.sh" restart "$@"
