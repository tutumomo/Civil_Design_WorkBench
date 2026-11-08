# DeepSeek Harness Web（dsh web）能力串接

> 用途：把「本專案預期 AI 會有的能力」與「dsh web 實際有的能力」逐項對帳，補掉缺口並留下可重做的步驟。
> 建立：2026-11-04。適用：本機 Linux 工作區 `/home/altos/Civil_Design_WorkBench`（GUI 位址 `http://127.0.0.1:3080`）。
> 相關：[`環境需求與自動配置.md`](環境需求與自動配置.md) §4、[`規範查詢台.md`](規範查詢台.md)、[`設計工作台.md`](設計工作台.md)。

## 1. 結論（先看這段）

1. **最大的缺口是 `regs` MCP 沒接**：規範查詢 6 個工具與設計計算 3 個工具（共 9 個）在 dsh web 原本完全不存在，
   智能體只能改走 shell 呼叫 `regq.py`／`design_cli.py`，與 AGENTS.md「一律用 MCP `regs_formula`／`regs_table`／`design_run`」
   的規定不一致。**本輪已用 stdio 接上並以真實呼叫驗證**（見 §5）。
2. **其餘能力本機都已具備**：ArtCraft 13 支 CLI（含 `cadcraft-cli` 可產 DWG）、CAD 字體、SolidCraft／Blender、
   專案技能（`civil-site-basemap`、`solidcraft-param`）在 dsh web 的技能目錄裡都載得到。
3. **`autocad` MCP 是全機都沒接的選用項**（Windows 專用 `autocad-mcp-pro`，本機不存在）；
   本機 DWG 由 CADCraft 產出，不需要它。
4. **dsh web 反而多出專案原本沒有的能力**：`cad_show`（CAD Viewer 直接開 DXF／STEP／STL／GLB／3MF）、
   內建瀏覽器、排程、任務板、跨工作區記憶——作圖後可直接在對話裡看圖，不必另開程式。

## 2. 能力對照表

| 能力 | 專案預期（AGENTS.md／docs） | 接線前 dsh web | 現在 |
|---|---|---|---|
| 規範查詢 `regs_ask`／`regs_search`／`regs_clause`／`regs_formula`／`regs_table`／`regs_list` | MCP `regs` | ❌ 無 | ✅ 已接（`mcp__regs__*`） |
| 設計計算 `design_list`／`design_show`／`design_run`（22 個計算器） | 同一個 MCP | ❌ 無 | ✅ 已接 |
| 規範／設計網頁（8765 `/`、`/design`） | `./web.sh` | 未啟動（連線 000） | 未啟動，需要時再起 |
| ArtCraft 13 支 CLI（CADCraft／GridCraft／WordCraft／PdfCraft…） | `tools/project_paths.py` 應全 OK | ✅ 全 OK | ✅ |
| CAD 字體 `gbenor.shx`／`CHINA1.SHX` | `CAD_FONTS/` | ✅ | ✅ |
| DWG 產出 | AutoCAD 或 CADCraft | ✅ CADCraft（版本查 `--versions`） | ✅ |
| 技能 `civil-site-basemap`、`solidcraft-param` | `.agents/skills/` | ✅ 在技能目錄 | ✅ |
| `autocad` MCP（ezdxf 後端） | 選用 | ❌ | ❌（本機無此套件；Windows 專用，判定不需要） |
| `cindy_memory` | 選用 | — | 由 dsh 內建記憶系統取代 |
| CAD 檔即時預覽 | （專案原本沒有） | — | ✅ `cad_show` 支援 DXF／STEP／STL／GLB／3MF |

## 3. 怎麼重做（dsh 重裝或換機時）

dsh web 的 MCP 連線存在它的連接器倉庫，**不在本 repo 內**，重裝後要重加一次。兩種做法：

**A. 介面**：設定 → MCP 連接器 → 新增自訂（stdio），填

| 欄位 | 值 |
|---|---|
| 名稱 | `規範查詢台 regs（土木設計）` |
| serverName | `regs` |
| command | `<專案根>/.venv/bin/python` |
| args | `-X utf8 <專案根>/tools/regs/regs_server.py --mcp` |
| env | `CIVIL_AI_ROOT=<專案根>`、`PYTHONIOENCODING=utf-8` |

**B. 智慧體**：呼叫連接器工具 `mcp_connector_configure`，參數同上（`transport: "stdio"`、`scope: "global"`）。

> 不要用 `tools/regs/register_mcp.py` 處理 dsh——那支只認 Claude Code／Claude Desktop／Codex／
> Gemini CLI／Antigravity／OpenCode 的設定檔格式。

註冊後驗證（不必開對話）：

```bash
.venv/bin/python tools/regs/mcp_smoke.py          # 9 個工具＋3 個實際呼叫，全過 exit 0
.venv/bin/python tools/regs/regq_selftest.py      # 39 題考題＋22 題口語分派＋11 項 MCP 檢查
```

## 4. 工具名稱對照（文件寫法 → dsh web 實際名稱）

| 文件／AGENTS.md 寫法 | dsh web 工具名 |
|---|---|
| `regs_ask` | `mcp__regs__regs_ask` |
| `regs_search` | `mcp__regs__regs_search` |
| `regs_clause` | `mcp__regs__regs_clause` |
| `regs_formula` | `mcp__regs__regs_formula` |
| `regs_table` | `mcp__regs__regs_table` |
| `regs_list` | `mcp__regs__regs_list` |
| `design_list` | `mcp__regs__design_list` |
| `design_show` | `mcp__regs__design_show` |
| `design_run` | `mcp__regs__design_run` |

## 5. 驗證紀錄（2026-11-04 實測）

| 檢查 | 指令／呼叫 | 結果 |
|---|---|---|
| 傳輸層煙測 | `.venv/bin/python tools/regs/mcp_smoke.py` | 6/6 PASS，exit 0：`regs 1.1`、protocol `2024-11-05`、9 個工具 |
| 查詢自我測試 | `.venv/bin/python tools/regs/regq_selftest.py` | 39 題考題＋22 題口語分派，0 failure，exit 0（含 11 項 MCP 檢查） |
| 主題卡 | `mcp__regs__regs_ask("設計一個沉砂池")` | 回水保 §91／§93／§165／§166 與下水道標準 §12，附原文與工具指引 |
| 計算器清單 | `mcp__regs__design_list` | 22 個（擋土牆 5、排水 4、基礎 4、RC 2、水文／沉砂／邊坡／箱涵／滯洪／剛架／鋼構各 1） |
| 真的算一題 | `mcp__regs__design_run("sediment_basin", 範例負載)` | `ok: true`，設計容量 477.0 m³、深度 2 m 檢核 OK，紀錄落 `out/design_workbench/runs/20261104_001829_599343_sediment_basin.json` |
| CAD 預覽 | `cad_show(out/地籍套繪_豐原區西湳里/豐原區西湳段地籍套繪圖.dxf)` | CAD Viewer 開啟成功 |
| 環境自檢 | `.venv/bin/python tools/project_paths.py` | 規範索引、已驗證庫、建物 SHP、13 支 CLI 全 OK；`accoreconsole` 未裝（CADCraft 可替代） |

## 6. 仍然沒補的（明列，不是漏寫）

| 項目 | 狀態 | 說明 |
|---|---|---|
| `autocad` MCP | 未接 | 需 `autocad-mcp-pro`（Windows／AutoCAD COM）；本機 Linux 無此套件，DWG 由 `cadcraft-cli` 產出。真要接時照 `.mcp.json.example` |
| `cindy_memory` | 不接 | dsh web 自帶跨會話記憶（`memory_*`），再接一套會分裂記憶來源 |
| 規範查詢台／設計工作台（8765） | 未啟動 | `./web.sh regs`／`./web.sh design` 隨開隨用；不影響 MCP 與 CLI |
| Windows 路徑文件 | 文件仍寫 `C:\Python312\python.exe` | 本機為 Linux，一律用 `.venv/bin/python`；`tools/project_paths.py` 已處理跨平台 |
| `mcp__cad__cad_show` 版本提示 | text-to-cad 0.7.26 → 0.8.4 有新版 | 非本專案元件，升級與否不影響 DXF 預覽 |
