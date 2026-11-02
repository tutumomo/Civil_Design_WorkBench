# 土木小型工程設計工作區（Civil AI Workspace）

把「道路、排水溝、擋土牆、邊坡、箱涵、滯洪池、建築樑柱與基礎」這類**小型土木／結構工程設計**，
從現況底圖、結構計算、預算編列到設計報告，整理成一條可重跑、可驗證的工具鏈，
並把**規範條文轉成機器可讀的公式與表格庫**（目前已驗證 1,011 條），讓 AI 智能體算得出數字、也說得出依據。

- 單位與座標：公制公尺；平面採 **TWD97 TM2（EPSG:3826）**，圖面即真實座標
- 交付格式：原生 **DWG**（AutoCAD 2018）＋ PDF ＋ XLSX ＋ DOCX
- 只用**相對路徑**，資料夾搬到任何磁碟／作業系統都能跑（見 `tools/project_paths.py`）

## 目錄

- [這個專案能做什麼](#這個專案能做什麼)
- [五分鐘上手](#五分鐘上手)
- [環境需求](#環境需求)
- [核心概念：案件主檔是唯一數據來源](#核心概念案件主檔是唯一數據來源)
- [工具鏈地圖](#工具鏈地圖)
- [規範公式圖表庫](#規範公式圖表庫)
- [交付前的六道閘門](#交付前的六道閘門)
- [目錄結構](#目錄結構)
- [給 AI 智能體：自動配置環境](#給-ai-智能體自動配置環境)
- [資料來源與授權](#資料來源與授權)

## 這個專案能做什麼

| 能力 | 指令 | 產出 |
|---|---|---|
| 現況平面底圖 | `tools/site_basemap/site_basemap.py` | TWD97 線稿 DXF（道路邊線、建物、河道） |
| A3 出圖 | `tools/a3_sheet/make_sheet.py` | DXF／**DWG**／PDF／PNG（含圖框、視口、比例尺） |
| 地籍套繪圖 | `tools/cadastral/make_cadastral_map.py` | A3 地籍圖（坵塊、段籍、建物） |
| 斷面圖／配筋圖 | `tools/wall_section/make_wall_section.py` | 擋土牆 S-01／S-02、排水溝 D-01／D-02 |
| 結構與水理設計 | `tools/design/design_cli.py`（20 個計算器） | 擋土牆、箱涵、渠道、邊坡、基礎、RC 樑柱… |
| 工程預算書 | `tools/boq/boq_build.py` | 5 工作表 `.xlsx` ＋ PDF（費率層活公式） |
| 設計報告書 | `tools/report/make_report.py` | 14 章 `.docx` ＋ PDF |
| 規範查詢 | `tools/regs/regq.py` | 主題卡／條文全文／**公式**／**表格** |
| 三軸一鍵交付 | `tools/case_package/case_package.py` | 設計圖＋預算書＋報告書＋交付清單 |

## 五分鐘上手

**支援 Windows、macOS、Linux**。核心功能（設計計算、預算書、報告書、規範查詢、公式庫）三個平台都能跑；
出圖與 DWG 格式設計圖可由 AutoCAD（Windows）或 **CADCraft**（跨平台，相容 >80% 以上 AutoCAD 功能）產出。

### 步驟 1：安裝 Python 3.10+（建議 3.12）

| 平台 | 指令 |
|---|---|
| **Windows** | 從 [python.org](https://www.python.org/downloads/) 下載安裝，**勾選「Add python.exe to PATH」**。或 `winget install Python.Python.3.12` |
| **macOS** | `brew install python@3.12`（或從 python.org 下載） |
| **Linux（Debian/Ubuntu）** | `sudo apt update && sudo apt install python3.12 python3.12-venv python3-pip` |
| **Linux（Fedora/RHEL）** | `sudo dnf install python3.12 python3-pip` |

確認：`python --version`（Windows 若只裝了 py launcher，用 `py -3 --version`）。

### 步驟 2：取得程式並建虛擬環境

```bash
git clone <this-repo>
cd <this-repo>
```

**Windows（PowerShell 或 cmd）**

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**macOS / Linux（bash、zsh）**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> 之後每次開新終端機都要先啟用虛擬環境（Windows `.venv\Scripts\activate`；macOS/Linux `source .venv/bin/activate`）。
> 不想用虛擬環境也可以，但系統 Python 可能不允許 `pip install`（PEP 668），此時加 `--break-system-packages` 或改用 venv。

### 步驟 3：檢查環境（會逐項列出還缺什麼）

```bash
python tools/project_paths.py
```

它會印出：專案根目錄、Python 版本與平台、規範索引在不在、**13 套 ArtCraft 找到幾套**、
AutoCAD `accoreconsole`、SolidCraft、Blender、CAD 字體庫。加 `--json` 可給安裝腳本吃。

### 步驟 3.5：安裝 CAD 字型（有 AutoCAD 才需要）

TOMO 文字樣式用 `gbenor.shx`（英數）＋ `CHINA1.SHX`（中文）。**這兩個字型已隨 repo 附在 `CAD_FONTS/`**，
但 DXF 裡只記字型**檔名**，AutoCAD 開圖時是到自己的字型目錄找檔，所以仍要裝一次：

```bash
# 先看會裝到哪（不改動）
python tools/install_cad_fonts.py

# 實際安裝（Program Files 受保護，需以系統管理員身分執行）
python tools/install_cad_fonts.py --apply
```

不想用系統管理員權限也可以：AutoCAD → OPTIONS → 檔案 → 字型檔名，把專案的 `CAD_FONTS` 資料夾
加入字型搜尋路徑即可（**不影響 DXF 產生**，只影響 AutoCAD 開圖與列印時的字型呈現）。

> 沒有 AutoCAD（macOS／Linux）時這段可略過：DXF 仍會帶正確的字型名稱，
> 只是用其他軟體開圖時字型由該軟體自行取代。

### 步驟 3.6：解壓縮臺中市建物圖資（隨 repo 附壓縮檔，需自行解壓）

本專案已隨 repo 附上 **`data/臺中市建物/臺中市建物_114.7z`**（74.5 MB，解壓後為 `data/臺中市建物/01-SHP/114中_B0001_1216n.shp` 共約 495 MB，供「現況平面底圖 `site_basemap.py`」與「地籍套繪圖 `make_cadastral_map.py`」繪製建物輪廓與樓層數使用）。Clone 或 Fork 後請先**就地解壓縮**至 `data/臺中市建物/` 目錄下：

```bash
# 使用 7-Zip 命令列（或直接在檔案總管對 data/臺中市建物/臺中市建物_114.7z 按右鍵「解壓縮至此」）
7z x "data/臺中市建物/臺中市建物_114.7z" -o"data/臺中市建物"
```

解壓後確認 `python tools/project_paths.py` 的 `臺中建物SHP` 一欄顯示 `[OK]` 即可。

### 步驟 4：下載規範並建索引（第一次需要，之後可略）

```bash
python tools/regs/fetch_regs.py      # 從政府網站下載 34 份現行規範（需網路）
python tools/regs/build_index.py     # 建 data/法規/_regs_index.sqlite
```

> `data/法規/` 不隨 repo 附（法規 PDF 屬原發布機關著作）。沒下載也能跑設計與出圖，
> 只有「規範查詢」與「公式庫的條文原文對照」會缺資料；`tools/regs/verified/` 的
> 1,011 條公式與表格**已隨 repo 附**，不需要下載即可計算。

### 步驟 5：驗證安裝

```bash
python tools/regs/verified_selftest.py          # 公式庫：612 式／399 表每條測試重算
python tools/selftest/regression.py --ignore-new # 全案回歸：7 個案件的預算／斷面／FS／配筋間距
python tools/regs/regq.py "設計一個沉砂池"        # 查一條規範看看
```

### 步驟 6：啟動 Web 服務（規範查詢台與設計工作台）

- **Windows**：雙擊根目錄 `規範查詢台.bat`（查詢台）或 `設計工作台.bat`（設計工作台）
- **Linux / macOS**：
  ```bash
  ./規範查詢台.sh     # 啟動並開啟規範查詢台 (http://127.0.0.1:8765/)
  ./設計工作台.sh     # 啟動並開啟工程設計工作台 (http://127.0.0.1:8765/design)
  # 或使用通用管理指令：
  ./web.sh status    # 檢查服務執行狀態
  ./web.sh stop      # 停止背景服務
  ./web.sh restart   # 重新啟動服務
  ```

三軸交付（需要 `cases/<案名>/case.json`）：

```bash
python tools/case_package/case_core.py check cases/<案名>/case.json
python tools/case_package/case_package.py cases/<案名>/case.json
```

## 環境需求

### 必要（沒有就跑不動核心功能）

| 項目 | 版本 | 用途 |
|---|---|---|
| Python | **3.10+（建議 3.12）** | 全部工具 |
| numpy | ≥1.26 | 設計計算 |
| ezdxf | ≥1.3 | 產生／讀取 DXF |
| matplotlib | ≥3.8 | 圖表、斷面預覽 |
| shapely | ≥2.0 | 幾何運算（範圍、緩衝） |
| pyproj | ≥3.6 | TWD97 ↔ WGS84 座標轉換 |
| PyMuPDF | ≥1.24 | 讀規範 PDF、`find_tables()` |

一行裝完：`python -m pip install -r requirements.txt`。
**不需要**編譯器、GDAL 或任何系統級服務（`pyshp` 取代 GDAL 讀 SHP）。

### 選用但影響交付品質

| 項目 | 用途 | 沒有會怎樣 | 平台 |
|---|---|---|---|
| **AutoCAD 2020+** 或 **CADCraft** | DXF → **DWG**、PDF 出圖（CADCraft 可相容 >80% AutoCAD 功能） | 兩者皆無時只能交 DXF | AutoCAD 僅 Windows；CADCraft 支援跨平台 |
| **CAD 字體**（`gbenor.shx`、`CHINA1.SHX`） | TOMO 中文文字樣式 | 圖面中文變替代字體 | **已隨 repo 附於 `CAD_FONTS/`**；安裝見步驟 3.5 |
| **ArtCraft**（CADCraft／GridCraft／WordCraft 為交付必要，其餘選用） | 預算書 xlsx、報告 docx、轉檔 | 對應產出需改用其他方式 | 依該套是否有該平台版本 |
| SolidCraft／Blender | 3D 模型與渲染 | 3D 軸停用 | Blender 有 macOS／Linux 版 |

### 跨平台差異

| 功能 | Windows | macOS | Linux |
|---|---|---|---|
| 設計計算、預算書、報告書、規範查詢、公式庫 | ✅ | ✅ | ✅ |
| 出 DXF／PNG／SVG | ✅ | ✅ | ✅ |
| 出 **DWG 格式設計圖** | ✅（AutoCAD 或 CADCraft） | ✅（CADCraft） | ✅（CADCraft） |
| 出 PDF（配置出圖） | ✅（AutoCAD 或 CADCraft） | ✅（CADCraft） | ✅（CADCraft） |

> 本機安裝 **CADCraft** 後，可相容 >80% 以上 AutoCAD 功能，各平台皆可直接產出 DWG 與出圖。
> 若環境兩者皆無，macOS／Linux 亦可先用 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) 將 DXF 轉為 DWG。

### 環境變數（想改路徑時才需要，程式不必改）

```bash
CIVIL_AI_ROOT      # 專案根目錄（預設＝repo 位置）
CIVIL_AI_REGS_DB   # 規範索引 sqlite（預設 data/法規/_regs_index.sqlite）
ARTCRAFT_HOME      # ArtCraft 安裝根目錄（Windows 預設 C:\Program\ArtCraft）
AUTOCAD_HOME       # AutoCAD 安裝目錄（含 accoreconsole.exe）
SOLIDCRAFT_CLI     # SolidCraft CLI 完整路徑
BLENDER            # Blender 執行檔
CAD_FONTS          # CAD 字體庫目錄（預設＝專案內 CAD_FONTS/，已隨 repo 附）
CIVIL_AI_STD_BLOCKS # 公司標準元件 DWG 資料夾（_ref 重建腳本用）
```

Windows 設定方式（ PowerShell，永久）：`setx ARTCRAFT_HOME "C:\Program\ArtCraft"`；
macOS／Linux：寫進 `~/.bashrc` 或 `~/.zshrc` 的 `export ARTCRAFT_HOME=...`。

### 常見問題

| 症狀 | 原因與解法 |
|---|---|
| `python: command not found` | Windows 只裝了 py launcher → 用 `py -3`；macOS/Linux 用 `python3` |
| `pip install` 被拒（externally-managed-environment） | 先建 venv（步驟 2），或加 `--break-system-packages` |
| 中文變問號／方框 | AutoCAD 找不到 SHX 字型。字型已隨 repo 附於 `CAD_FONTS/`，執行 `python tools/install_cad_fonts.py --apply`（需系統管理員權限），或在 AutoCAD 的 OPTIONS → 字型檔名把該資料夾加入搜尋路徑 |
| `規範索引 missing` | 還沒跑 `python tools/regs/build_index.py`（需先 `fetch_regs.py`） |
| `找不到 ArtCraft` | 未安裝或路徑非預設，設 `ARTCRAFT_HOME` |
| 產不出 DWG | 平台未安裝 AutoCAD 或 CADCraft，或 `accoreconsole` 不在預設路徑。可設 `AUTOCAD_HOME` 或安裝/指定 `CADCraft` |

完整清單（13 套 ArtCraft 對照、MCP 伺服器、Skills、資料取得方式、給智能體的自動配置指令範本）見
**[`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)**。

## 核心概念：案件主檔是唯一數據來源

一份 `cases/<案名>/case.json`（schema `civil-case/1`）寫一次數量，**設計圖、預算書、報告書都由它派生**，
不再維護三份 JSON。`case_core.check` 會驗算模型算式，不符直接 error 中止。

```jsonc
{
  "schema": "civil-case/1",
  "case_name": "示範案",
  "type": "wall",                 // road / wall / channel / slope
  "quantities": {
    "model": "wall",
    "wall_type": "cantilever",    // gravity / cantilever
    "H": 4.0, "L": 50.0, ...      // 幾何參數
  }
}
```

## 工具鏈地圖

```
                         ┌─ site_basemap ─→ a3_sheet ──→ DWG/PDF/PNG
  case.json ──check──┬───┤
  (唯一數量來源)       │   ├─ wall_section ─→ 斷面圖/配筋圖 ─→ dwg
                     │   ├─ boq_build ───→ 預算書 xlsx/PDF
                     │   └─ make_report ─→ 設計報告 docx/PDF
                     └─ design/*（20 個計算器）← 規範公式庫 regs/verified
```

| 層 | 目錄 | 說明 |
|---|---|---|
| 設計計算 | `tools/design/` | 20 個計算器，統一 JSON 入口 `design_api.py`；每個都有 selftest |
| 數量模型 | `tools/case_package/qty_models.py` | 依類別（road／wall／channel／slope）算數量，**不可用道路公式硬套牆／溝** |
| 出圖 | `tools/a3_sheet/`、`tools/wall_section/`、`tools/regs` 以外 | ezdxf 建模 → `acc.py`（accoreconsole）轉 DWG／PDF |
| 預算 | `tools/boq/` | `boq_rules.py` 費率層已與真實預算書對帳；`price_audit.py` 稽核單價來源 |
| 報告 | `tools/report/` | 14 章骨架；`verify_report.py` 做 R1~R16 回讀驗證 |
| 規範 | `tools/regs/` | 下載、索引、查詢、**已驗證公式／表格庫** |
| 品管 | `tools/a3_sheet/check_delivery.py`、`tools/selftest/` | E1~E18 出圖品管、圖數對帳、全案回歸 |

## 規範公式圖表庫

`tools/regs/verified/` 是本專案最花時間的部分：把 34 份現行台灣土木規範的**公式與表格**逐條轉成
機器可讀、可算、可回查的結構化資料。

| 指標 | 數量 |
|---|---|
| 已驗證條目 | **1,011**（612 公式／399 表格） |
| 覆蓋規範 | 34 份（水保、道路、排水、邊坡、鋪面、交通、施工、橋梁、建築結構…） |
| flagged 條文已轉換／已涵蓋 | **959 / 1,384（69.3%）** |
| 待核（原文疑誤／來源缺漏） | 0 |

每條都有：LaTeX、變數與單位、可執行程式碼、適用條件、**測試案例**、以及與原書頁碼的對照。
取用方式：

```bash
python tools/regs/regq.py --clause swc_tech 119         # 條文全文
python -c "import sys; sys.path.insert(0,'tools/regs'); import verified as V; \
f,t=V.load(); e=f['swc_tech:119'] if 'swc_tech:119' in f else None; print(e and e['latex'])"  # 公式
```

品質保證（每次改動都跑）：

```bash
python tools/regs/payload_check.py --library   # 結構與數值檢查
python tools/regs/verified_selftest.py         # 每條測試案例重算
python tools/regs/regq_selftest.py             # 查詢台問答
python tools/regs/design_conformance.py        # 引擎 ↔ 已驗證庫 雙向比對
```

方法論寫在 [`docs/規範公式圖表入庫SOP.md`](docs/規範公式圖表入庫SOP.md)，
踩過的坑在 [`docs/踩坑紀錄.md`](docs/踩坑紀錄.md)（含索引 `docs/經驗索引_INDEX.md`）。

## 交付前的六道閘門

| # | 閘門 | 指令 |
|---|---|---|
| 1 | 設計檢核全過 | `case_core.py check` |
| 2 | E1~E18 出圖品管 | `check_delivery.py` |
| 3 | 圖／數對帳（DXF 量回與 case.json 比對） | `dxf_takeoff.py`（已內建於 section 軸） |
| 4 | 配筋圖間距對帳 | `dxf_takeoff.py --rebar` |
| 5 | 設計段落注入（報告的 `_derived` 無 error） | `case_package` 內建 |
| 6 | 全案回歸 | `tools/selftest/regression.py` |

總表見 [`docs/交付閘門總表.md`](docs/交付閘門總表.md)。

## 目錄結構

```
├── AGENTS.md                 共用作業規範（智能體常駐主規範）
├── README.md
├── requirements.txt
├── CAD_FONTS/               TOMO 用 SHX 字型（gbenor.shx、CHINA1.SHX）
├── 怎麼用.md                 給人看的入口（三步驟、四類案件、六道閘門）
├── tools/
│   ├── project_paths.py      ★ 路徑與外部程式的唯一解析入口（跨平台、無絕對路徑）
│   ├── design/               20 個設計計算器 + 統一 JSON 入口
│   ├── case_package/         案件主檔、數量模型、三軸編排
│   ├── a3_sheet/             A3 出圖與 E1~E18 品管
│   ├── wall_section/         斷面圖／配筋圖
│   ├── site_basemap/         現況底圖（NLSC／OSM → TWD97 DXF）
│   ├── cadastral/            地籍套繪圖
│   ├── boq/                  預算書（boq_rules 費率、prices 單價庫）
│   ├── report/               設計報告書
│   ├── regs/                 規範下載／索引／查詢／已驗證公式庫
│   │   ├── verified/         ★ 1,011 條已驗證公式與表格
│   │   ├── page_crop.py      PDF 裁圖（讀原頁公式）
│   │   ├── page_index.py     印刷頁碼 → PDF 頁
│   │   ├── locate_pages.py   關鍵字定位頁碼
│   │   ├── dump_tables.py    find_tables 表格骨架
│   │   ├── audit_qualitative.py / audit_skip_reasons.py / reconcile_progress.py
│   │   └── payload_check.py / verified_selftest.py / design_conformance.py
│   ├── selftest/             全案回歸
│   ├── acad/                 accoreconsole 封裝、出圖型式 CTB
│   └── clean_project.py      清理暫存（--dry-run / --apply）
├── data/                     法規全文／索引、臺中市建物_114.7z（隨 repo 附，Clone/Fork 後需就地解壓）
├── cases/                    案件主檔
├── docs/                     知識文件（產線說明、法規庫、踩坑紀錄）
├── templates/                報告與規範條文模板
├── 標準圖圖庫/                公司標準圖（自有資料，不入版控）
└── out/                      交付物唯一落點（不入版控）
```

## 給 AI 智能體：自動配置環境

把下面這段貼給任何支援 shell 的智能體（Claude Code／Codex／Cindy／Gemini CLI…）：

```
這個 repo 是土木小型工程設計工作區。請幫我把環境配置好：
1. 跑 `python tools/project_paths.py`，看目前缺什麼（它會列出 Python 依賴、規範索引、
   13 套 ArtCraft、AutoCAD、SolidCraft、Blender、CAD 字體）。
2. 缺 Python 套件：在虛擬環境內 `python -m pip install -r requirements.txt`。
3. 缺規範資料：`python tools/regs/fetch_regs.py` 然後 `python tools/regs/build_index.py`。
   若 `data/臺中市建物/臺中市建物_114.7z` 尚未解壓，請將其就地解壓縮至 `data/臺中市建物/`（產生 `01-SHP/`）。
4. ArtCraft／AutoCAD／SolidCraft 是外部桌面程式，無法自動安裝。請列出我還缺哪幾套，
   以及該設哪個環境變數（ARTCRAFT_HOME／AUTOCAD_HOME／SOLIDCRAFT_CLI／CAD_FONTS）。
5. 完成後跑 `python tools/regs/verified_selftest.py` 與
   `python tools/selftest/regression.py --ignore-new` 確認可用。
限制：不要改 tools/ 內的程式；不要上傳 data/、out/、_temp/ 內任何檔案。
```

環境變數與各平台的差異（例如 AutoCAD 與 CADCraft 的出圖配置）
一律記在 [`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)。

## 資料來源與授權

- **法規全文**：各級政府機關公開資料（交通部、內政部國土管理署、農業部、臺中市…），
  由 `tools/regs/fetch_regs.py` 下載並記錄來源 URL 與版本於 `data/法規/_regs_manifest.json`。
- **地圖與地籍**：內政部國土測繪中心（NLSC）、臺中市開放資料、OpenStreetMap。
- **規範公式庫**：由本專案逐條轉錄並加註出處（規範名稱、版次、頁碼、條號）。
  **引用前請回原規範確認**；本庫不是法規的替代品，正式設計須經技師覆核。
- 本 repo 的程式碼可自由使用與修改；但**規範本文的著作權屬原發布機關**，
  `data/法規/` 內的 PDF 與全文不隨 repo 散布，請用 `fetch_regs.py` 自行下載。

> 本專案輸出之設計圖、預算書與報告書，**設計責任仍由簽證技師承擔**。
