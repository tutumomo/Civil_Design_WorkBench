#!/usr/bin/env bash
# 規範查詢台 - 啟動 Web 服務並開啟規範查詢台 (Linux / macOS)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/web.sh" regs "$@"
