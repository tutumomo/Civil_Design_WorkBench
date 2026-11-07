# IngeTrazo 操作指引（MCP 橋接）

> 適用版本：**IngeTrazo 0.6.0**（GPL-3.0，Windows／macOS／Linux）｜本機路徑：`C:\Program Files\IngeTrazo\`
> 官網：<https://ingetrazo.com/en/>｜手冊（西班牙文）：<https://docs.ingetrazo.com/ia/>
> 本專案接線日期：2026-11-03。**本文只寫官方文件與本機檔案查得到的事；沒實跑過的會標「未實測」。**

---

## 0. 一句話

IngeTrazo 是一套**開源的 3D 建築／土木模型器**（推拉建模、BIM 標記、IFC4、地形與剖面、出圖排版），
它內建 **MCP 橋接**，可以讓 Claude Code／Claude Desktop／Codex／VS Code 等智能體**在你開著的視窗裡即時建模**。

它**不是**本專案的交件 CAD：沒有 TWD97/TWD97 圖框契約、沒有 TOMO 字型、沒有 DWG 2018 輸出、也沒有 headless 模式。
定位是「**3D 概念／構造建模 ＋ BIM 數量 ＋ 示意出圖**」，交件仍走 `make_sheet.py`＋`acc.py`＋`check_delivery.py`。

---

## 1. 本機安裝內容（2026-11-03 實查）

| 項目 | 內容 |
|---|---|
| 安裝目錄 | `C:\Program Files\IngeTrazo\` |
| 主程式 | `ingetrazo.exe`（約 13.8 MB） |
| MCP 伺服器 | `ingetrazo-mcp.exe`（約 2.0 MB，PyInstaller 打包，**不需要另裝 Python**） |
| 原始碼版伺服器 | `_internal\scripts\ingetrazo_mcp.py`（只用標準庫，可讀可稽核） |
| 內建外掛 | `plugins\ai_bridge.py`（MCP 橋）、`ai_assistant.py`（app 內建 AI 助手）、`render_blender.py`（Blender 渲染） |
| 版本／授權 | 0.6.0／GPL-3.0（`LEEME.txt`） |
| 說明語言 | 手冊為西班牙文；app 介面可切換語言（`_internal\i18n\*.json`） |

`tools\project_paths.py` 會依序找 `INGETRAZO_MCP` → `INGETRAZO_HOME` → `C:\Program Files\IngeTrazo`、
`D:\Program Files\IngeTrazo`、`~/IngeTrazo`、`/opt/IngeTrazo`、`/Applications/IngeTrazo.app/Contents/MacOS` → `PATH`。
**不要在程式裡寫死安裝路徑。**

---

## 1.5 Linux（aarch64）：原始碼建置版（2026-11-07 實測）

官方只出 **x86_64** 的 AppImage／tarball／flatpak／snap（0.6.0 發行檔全是 x86_64 或 macOS／Windows），
**沒有 aarch64 資產**。aarch64 機器要走原始碼建置；PySide6 6.11.3 有 `manylinux_2_39_aarch64` wheel，
`manifold3d` 亦有 aarch64 wheel，所以不需要模擬層。

```bash
git clone --depth 1 https://github.com/ingelibre/ingetrazo.git ~/IngeTrazo
cd ~/IngeTrazo && python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt     # PySide6 6.11.3 / numpy / openskp / ezdxf / manifold3d
./venv/bin/python main.py --check                        # 應以 OK 結尾
```

安裝目錄另外放兩個啟動器（未追蹤檔，更新不會被覆蓋）：

| 檔案 | 用途 |
|---|---|
| `~/IngeTrazo/ingetrazo` | GUI 啟動器 → `venv/bin/python main.py` |
| `~/IngeTrazo/ingetrazo-mcp` | MCP 橋（stdio ↔ `127.0.0.1:4763`）→ `venv/bin/python scripts/ingetrazo_mcp.py` |

`project_paths.ingetrazo_home()` 的候選清單本來就有 `~/IngeTrazo`，所以**不需要設 `INGETRAZO_HOME`／`INGETRAZO_MCP`**。
原始碼版**沒有** `ingetrazo-mcp.exe`，走的是 `scripts/ingetrazo_mcp.py`（只用標準庫，可稽核）。

三個啟動器都可以 symlink 到 PATH 目錄直接用（`ingetrazo`／`ingetrazo-mcp`／`ingetrazo_update`）：

```bash
ln -sfn ~/IngeTrazo/ingetrazo        ~/.local/bin/ingetrazo
ln -sfn ~/IngeTrazo/ingetrazo-mcp    ~/.local/bin/ingetrazo-mcp
ln -sfn ~/IngeTrazo/ingetrazo_update ~/.local/bin/ingetrazo_update
```

**啟動器必須以 `readlink -f "${BASH_SOURCE[0]}"` 解出真實路徑再找 `venv/`**，不能只用 `dirname`：
走 symlink 呼叫時 `dirname` 拿到的是 `~/.local/bin`，會去找 `~/.local/bin/venv/bin/python` 而報
「沒有此一檔案或目錄」（2026-11-07 實例）。

### 1.5.1 自動更新

```bash
python tools/ingetrazo/ingetrazo_update.py --check   # 只看有沒有新版（有新版 → 退出碼 2）
python tools/ingetrazo/ingetrazo_update.py           # 更新（git fetch → reset --hard FETCH_HEAD → 必要時 pip → 自檢）
~/IngeTrazo/ingetrazo_update                         # 同一支的方便入口
```

- **依賴只在 `requirements.txt` 有變時才重裝**（省掉每次幾分鐘的 pip）。
- **GUI 開著時拒絕更新**（改到一半的原始碼會讓 Qt 載入半套模組）；要硬更新加 `--force`。
- 安裝目錄有**已納入版控**的改動時拒絕更新；`--force` 會先把 `git diff` 存到 `_temp/ingetrazo/local_*.patch`。
- 不是 git 工作區（官方 tarball／AppImage 版）→ 明確報錯，不做猜測式更新。
- 更新後自動跑 `main.py --check`，非 OK 即退出碼 1。

> 未實測：BIM／IFC4 匯出、地形 DEM、Sheet composer 在 aarch64 的表現；本輪只驗到「GUI 起得來、MCP 伺服器 tools/list 回 5 支工具、`--check` OK」。

---

## 2. 能力邊界

### 2.1 可以做

| 能力 | 說明 |
|---|---|
| 精確 3D 建模 | 推拉（push/pull）時直接輸入尺寸；公尺制、**Z 軸向上** |
| BIM 與數量 | 牆、版、柱、門窗等 BIM 標記 → **IFC4** 匯出、**數量 CSV** |
| 地形與測量 | 3D 衛星地形、縱斷面、專案北；讀 WebODM 無人機網格；GPS／全測站 **UTM CSV** |
| 出圖 | 具比例的 PDF 圖紙（圖框、尺寸標註、標題欄、多張圖紙）；目前視圖匯出 **DXF（公尺）** 給 IngeCAD |
| 匯入 | DWG／DXF、SketchUp（OpenSKP）、OBJ、COLLADA、glTF、STL |
| 匯出 | DAE／glTF／OBJ／STL／IFC4（另有 DXF、PDF） |
| 資產 | 1,510 個元件、427 種材質；Blender 外掛可算圖 |
| AI | app 內建助手（自備 API key 或 Ollama）；**MCP 橋接**給外部智能體 |

### 2.2 不可以做（本專案的紅線）

1. **不能當交件 CAD**：PDF 圖紙是 IngeTrazo 自己的圖框，不是本專案 `A3圖框.dwt`；
   DXF 是公尺、無 TOMO（`gbenor.shx`＋`CHINA1.SHX`）、無 `數字_中文` 圖層規範、**沒有 DWG 2018**。
2. **不能假設座標系相同**：IngeTrazo 的地形／GPS 走 **UTM WGS84**；本專案契約是 **TWD97 TM2 `EPSG:3826`**。
   兩者原點、假東移、尺度都不同，**必須先轉換並在圖說註明**，不得直接把 UTM 值當 TWD97 用。
3. **不能無人顧批次跑**：沒有 headless／CLI 建模模式；MCP 一定要 **GUI 開著、文件已開、橋已啟動**。
4. **不能同時多客戶端**：官方明講「一次只接受一個客戶端」，且只聽 `127.0.0.1`。

---

## 3. 啟動順序（少一步就连不上）

1. 開 **IngeTrazo**（`ingetrazo.exe`）。
2. **開一份文件**（新檔或 `.igz`）。沒有文件時工具呼叫會失敗。
3. 功能表 **Extensões／Extensiones ▸ AI Bridge (MCP)**（側盤 AI 分頁也可）→ 啟動。
   視窗會顯示本機連線字串，預設 **`127.0.0.1:4763`**，可按「複製」。
4. 再啟動你的 MCP 客戶端（Claude Code／Desktop／Codex／VS Code）。
5. 收工：同一選單可關閉橋；關 app 也會斷。

> 官方手冊的對應頁：<https://docs.ingetrazo.com/ia/>（「El puente MCP, paso a paso」）。

---

## 4. MCP 接線

| 項目 | 值 |
|---|---|
| 伺服器名稱 | `ingetrazo` |
| 啟動命令 | `C:\Program Files\IngeTrazo\ingetrazo-mcp.exe`，參數空 |
| 傳輸 | **stdio**（客戶端 ↔ exe）→ 本機 **TCP**（exe ↔ app），JSON-RPC，protocol `2024-11-05` |
| 位址 | `INGETRAZO_AI_HOST`（預設 `127.0.0.1`）／`INGETRAZO_AI_PORT`（預設 `4763`） |
| 認證 | **無**（僅 loopback；這也是為什麼不要把它暴露到區網） |
| 逾時 | 單次橋接呼叫 180 秒；斷線會重連一次 |

本專案的設定由 `tools\mcp\register_all.py` 產生，已納入 `build_servers()`：

```powershell
python tools\mcp\register_all.py              # dry-run，先看會改哪些檔
python tools\mcp\register_all.py --apply      # 寫入（每個檔先備份）
python tools\mcp\mcp_probe.py ingetrazo 30 "C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"
python tools\ingetrazo\ingetrazo_check.py     # 橋有沒有開、五支工具在不在
```

> `mcp_probe.py` 只證明「握手＋工具清單」；**橋沒開也會過**。要證明真的能建模，跑 `ingetrazo_check.py --call`（會實際呼叫 `query_model`）。

### 4.1 五支工具

| 工具 | 做什麼 | 注意 |
|---|---|---|
| `run_python` | 在**活的文件**上執行 Python（`scene`、`mesh`、`selection`、`groups`、`layers`、`viewport`、`QVector3D`、`Mesh`、`Group`、`Edge`、`Face`、`bim`；建構子 `revolve(profile)`、`extrude(contour, z0, z1)`） | **每次呼叫＝一個 undo 步驟**；失敗會自動 rollback，文件不留半成品。回傳 `stdout`／`stderr`／`error`／`changed` |
| `query_model` | 群組／元件／材質／圖層／包圍盒／數量 | 建模後先用它自檢，不要只看截圖 |
| `screenshot` | 即時 viewport 截圖（PNG base64＋檔案路徑） | 智能體「看」模型的主要手段；回報前至少看一次 |
| `undo`／`redo` | 歷史操作 | 與 GUI 的 Ctrl+Z 同一條歷史 |

座標與單位：**Z-up、公尺**。餵 UTM 或 TWD97 絕對座標前，先確認你要的是「專案局部座標」還是「真實座標」；
混用會讓模型跑到數十萬公尺外，viewport 看起來像空白。

### 4.2 建議的呼叫節奏

1. `query_model` 先看目前文件有什麼（避免重複建模、確認群組命名）。
2. 一個 `run_python` **只做一個構件**（牆、版、基礎），用尺寸參數組字串，不要一次塞整棟。
3. `query_model` 驗數量／包圍盒 → `screenshot` 目視 → 有錯 `undo`，不要疊補丁。
4. 確認後才匯出 IFC／CSV／PDF／DXF 到 `out\<案名>\`（**不要寫進 `D:\公司案件\`**）。

---

## 5. 和本專案協作的標準流程

| 步驟 | 做什麼 | 用哪支 |
|---|---|---|
| 1 | 場址底圖、TWD97 線稿 | `tools\site_basemap\site_basemap.py`（**不要**用 IngeTrazo 取代） |
| 2 | 3D 構造建模／BIM 標記／數量 | IngeTrazo（GUI＋MCP） |
| 3 | 數量核對 | `query_model` → 數量 CSV → 與 `case.json`／`boq` 對帳 |
| 4 | 示意圖／斷面 | IngeTrazo 截圖或 PDF；要 render 再交 Blender |
| 5 | 交件圖 | **回本專案產線**：`make_sheet.py` → `acc.py` → `check_delivery.py` |
| 6 | 座標 | 若要把 IngeTrazo 幾何帶進 TWD97 圖面，先做 UTM→TWD97 轉換並記錄參數 |

**可以帶走的東西**：IFC4（給 BIM／數量）、OBJ／glTF／STL（給 Blender／TextureCraft）、數量 CSV（給預算）。
**不要帶走的東西**：IngeTrazo 的 PDF 圖框、DXF 圖層與字型（不合本專案契約）。

---

## 6. 疑難排解

| 症狀 | 原因 | 解法 |
|---|---|---|
| `tools/list` 正常，但每個工具都回「請先啟動 AI Bridge」 | 只開了 exe，app 沒開或橋沒啟動 | 開 IngeTrazo → 開文件 → Extensões ▸ AI Bridge (MCP) |
| `initialize` 就失敗、程序立刻結束 | 命令路徑錯，或指到 `ingetrazo.exe` 卻沒加 `--mcp` | Windows 用 `ingetrazo-mcp.exe`；Linux 原始碼版用 `ingetrazo --mcp` |
| 連線被拒 / `Connection refused` | app 的橋沒開、port 被改、或防火牆擋 loopback | 看 app 顯示的 port；必要時設 `INGETRAZO_AI_PORT` 給**伺服器**（兩邊要一致） |
| 第一個客戶端可用，第二個不行 | 官方設計：一次一個客戶端 | 關掉前一個客戶端，或改用同一個客戶端 |
| 模型畫在很遠的地方／viewport 空白 | 把 UTM／TWD97 絕對座標當區域座標餵進去 | 用專案局部原點建模，或先轉到一致的座標系 |
| `run_python` 回 `ROLLED BACK` | 腳本丟錯，交易已回滾 | 讀 `error`／`stderr` 修腳本；文件沒被改壞，直接重跑 |

---

## 7. 安全

- 橋只綁 **`127.0.0.1`**、**無認證**。不要用連接埠轉發、反向代理或 `0.0.0.0` 把它露出區網。
- `run_python` 等於在 app 內執行任意 Python（可讀寫檔案）。**只在自己開的文件上使用**；
  不要把不明來源的「配方」貼進去。
- IngeTrazo 內建 AI 助手的 API key 存在使用者偏好設定，**不會寫進 `.igz`**；但仍不要把 key 貼進對話或文件。

---

## 8. 驗證清單（改完設定照跑）

```powershell
python tools\project_paths.py                  # 應顯示 IngeTrazo 根目錄與 MCP 橋路徑
python tools\mcp\register_all.py --only ingetrazo          # dry-run
python tools\mcp\register_all.py --only ingetrazo --apply  # 寫入（會備份）
python tools\mcp\mcp_probe.py ingetrazo 30 "C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"
python tools\ingetrazo\ingetrazo_check.py --call           # 需 app 開著＋橋啟動
```

預期：`tools` 回 **5** 支（`run_python`、`query_model`、`screenshot`、`undo`、`redo`）；
`--call` 回文件摘要（群組數、包圍盒）與 `bridge: listening`。

---

## 9. 檔案

| 路徑 | 用途 |
|---|---|
| `tools\project_paths.py` | `ingetrazo_home()`／`ingetrazo_mcp()` 路徑解析（環境變數優先） |
| `tools\mcp\register_all.py` | 把 `ingetrazo` 寫進各客戶端設定 |
| `tools\ingetrazo\ingetrazo_check.py` | 橋接／工具／實際呼叫檢查 |
| `docs\AI工具鏈_MCP整合_2026-11-03.md` | 六條通道的接線與實測總表 |
| `docs\七套CAD工具能力邊界與重疊度.md` | IngeTrazo 與其他七套的能力邊界 |

---

## 10. 一句話收束

**IngeTrazo 補的是「3D＋BIM＋地形＋示意出圖」這一段，不是交件那一段。**
智慧體可以透過 MCP 在開著的視窗裡即時建模，但交付前一定要回本專案的 TWD97／TOMO／A3／DWG 2018 產線複核。
