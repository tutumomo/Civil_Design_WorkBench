#!/usr/bin/env bash
# 設計工作台 - 啟動 Web 服務並開啟工程設計工作台 (Linux / macOS)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/web.sh" design "$@"
