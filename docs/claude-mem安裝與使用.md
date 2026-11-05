# claude-mem：持久記憶（Claude Code 端）

> 安裝日期：2026-11-04｜對象：本機 Claude Code（Code 分頁）｜上游：<https://github.com/thedotmack/claude-mem>（Apache-2.0）
> 官方文件：<https://docs.claude-mem.ai/>｜本文件只寫**本機實際做的事**。

---

## 0. 一句話

claude-mem 會在每個 Claude Code session 結束時，把「做了什麼、為什麼這樣做」壓縮成記憶存進本機 SQLite，
下次開新 session 自動注入，於是跨 session 不必重新解釋專案背景。

**它與這個 App 內建的記憶系統是兩套東西，互不衝突**：
這個 App（Cowork／桌面版）用的是檔案式記憶（`MEMORY.md`＋各主題檔）；claude-mem 管的是 **Claude Code** 那邊。
兩邊都可以留著。

---

## 1. 組成（先知道再裝，免得搞混）

| 元件 | 說明 |
|---|---|
| 6 個 lifecycle hooks | `SessionStart`／`UserPromptSubmit`／`PostToolUse`／`Stop`／`SessionEnd`／`Setup`，由 plugin 內的 `hooks/hooks.json` 定義，**不會寫進** `settings.json` |
| worker service | 本機 HTTP 服務（預設 port 37777）＋網頁檢視 UI，Bun 執行 |
| SQLite＋向量庫 | 觀測（observations）、摘要、會話；本機儲存 |
| MCP 搜尋工具 | `search` → `timeline` → `get_observations` 三段式，約省 10 倍 token |
| `mem-search` skill | 用自然語言查歷史 |
| hook launcher | `%LOCALAPPDATA%\claude-mem\bin\claude-mem.exe`，安裝器會加入使用者 PATH |

---

## 2. 安裝

### 2.1 一鍵腳本（建議）

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Civil_Design_WorkBench\.agents\setup\claude-mem-install.ps1"
```

腳本會依序做：前置檢查 → `npx claude-mem install --ide claude-code --provider claude` → 關閉匿名遙測 →
掛 marketplace 與 plugin → 跑 `claude-mem doctor` 與 `claude plugin list` 驗證。

選項：

| 參數 | 用途 |
|---|---|
| `-Provider claude`（預設） | 記憶摘要用**你自己的 Anthropic 方案**，不需要 cmem.ai 帳號、不外傳第三方 |
| `-Provider host` | 本機 loopback 觀察器，不用 API key |
| `-SkipPlugin` | 只做 npx 安裝，不碰 marketplace／plugin |
| `-KeepTelemetry` | 保留匿名遙測（預設是**關閉**） |
| `-NoPause` | 結束時不按 Enter |

### 2.2 手動（若腳本卡在互動選單）

```powershell
npx -y claude-mem install --ide claude-code --provider claude
npx -y claude-mem telemetry disable
claude plugin marketplace add thedotmack/claude-mem
claude plugin marketplace list          # 確認實際名稱（thedotmack 或 thedotmack-claude-mem）
claude plugin install claude-mem@thedotmack
npx -y claude-mem doctor
```

app 內等價的斜線指令：`/plugin marketplace add thedotmack/claude-mem`、`/plugin install claude-mem@thedotmack`。
`claude plugin install` **不能在執行中的 session 生效**，裝完要重開或 `/reload-plugins`。

---

## 3. 前置條件與 Windows 陷阱

| 項目 | 要求 | 沒有的症狀 |
|---|---|---|
| Node.js | **≥ 20**（v20+） | 安裝器直接退場 |
| Claude Code | **≥ 2.1.139** | 舊版會忽略 hook 的 `args`，**不報錯但擷取不到任何資料** |
| Git for Windows | 建議裝 | `Setup` hook 用 `shell: "bash"`，缺 Git Bash 會報錯 |
| Bun／uv | 安裝器自動裝 | `Failed to start Bun: spawn bun ENOENT` |
| PATH | 含 `%LOCALAPPDATA%\claude-mem\bin` | hook 報 `Executable not found in $PATH: "claude-mem"` |

已知坑：Windows 上 hook 預設走 Git Bash；若裝了 WSL，`bash` 可能被解析到 `C:\Windows\System32\bash.exe`（WSL stub）而失敗，
此時設 `CLAUDE_CODE_GIT_BASH_PATH` 指向 Git Bash 的 `bash.exe`。

---

## 4. 驗收

```powershell
npx claude-mem status                      # worker 是否活著
npx claude-mem doctor                      # bun / uv / launcher / worker 診斷
npx claude-mem search "擋土牆"              # 查本專案歷史
claude plugin list                          # 應看到 claude-mem
```

網頁檢視：<http://localhost:37777>（可看到即時記憶串流、My Work 佇列）。

驗收通過的判準：**開一個新的 Claude Code session，它講得出你上次做到哪裡**。

---

## 5. 隱私與資料流

| 項目 | 說明 |
|---|---|
| 觀測資料 | 存在本機 `%APPDATA%\claude-mem`（SQLite）＋向量庫 |
| 摘要模型 | `--provider claude` 時走你自己的 Anthropic 方案（等同一般 Claude Code 用量），**不需 cmem.ai 帳號** |
| 匿名遙測 | 官方預設開啟；本專案腳本已預設**關閉**（`npx claude-mem telemetry disable`） |
| 雲端同步 | 未啟用。要開才有 `cmem.ai` 帳號與付費方案 |
| `<private>` 標記 | 排除敏感內容不被收錄 |
| **桌面版 `claude-mem-cowork` plugin** | 會把**工具使用串流到 cmem.ai 雲端**。本專案有案件機密（`D:\公司案件`），**請不要安裝那個** |

> 提醒：claude-mem 會擷取工具呼叫內容。若某個 session 內含敏感檔案，請先開 `<private>` 或事後清理該筆觀測。

---

## 6. 常用維護指令

```powershell
npx claude-mem status | start | stop | restart
npx claude-mem repair          # 重跑 Bun／uv／bun install，hook launcher 壞掉時用
npx claude-mem update          # 更新到最新版（含 launcher）
npx claude-mem prune           # 清掉舊版 plugin cache（保留最新兩版）
npx claude-mem backup run      # 本機 DB 快照
npx claude-mem uninstall       # 移除 plugin、設定與 launcher
```

模式（摘要語言）：`~/.claude-mem/settings.json` 設 `"CLAUDE_MEM_MODE": "code--zh"` → 簡體中文；
內建模式只有 `code`（英文）、`code--zh` 等，**沒有繁體中文模式**。

---

## 7. 與本專案的關係

- claude-mem 是**機器層級**工具，不是本專案的 `tools/` 產線工具；它不會改變任何出圖、計算、交付行為。
- 本專案既有記憶（`MEMORY.md` 那套檔案式記憶）與 claude-mem 各自為政；claude-mem 服務 Claude Code session，
  檔案式記憶服務這個 App 的對話。
- 若日後想讓本專案的跨 session 脈絡更好，可讓智能體把關鍵決策寫進本專案文件與 `MEMORY.md`，
  而不是依賴 claude-mem 的自動摘要——後者是「工具呼叫觀測」，不是「決策理由」。
