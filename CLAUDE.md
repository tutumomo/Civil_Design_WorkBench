# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Always-On Core**: Complete project operational rules, boundaries, and engineering invariants are unified in [`AGENTS.md`](AGENTS.md). This file provides operational guidance, commands, and architectural context for Claude Code.

## 1. Common Commands

### Environment & Multi-Device Sync
```bash
# Check git sync status across devices (run before starting work / switching machines)
python tools/git/sync_check.py      # macOS/Linux: .venv/bin/python tools/git/sync_check.py

# Resolve paths & inspect environment tools
python tools/project_paths.py

# Install missing third-party tools after `git clone` (REQUIRED; plain project_paths.py only reports)
# Mandatory tools auto-installed from the user's forks on GitHub Releases:
#   OpenCADStudio       (tutumomo/OpenCADStudio, Big5 SHX fix)  -> "Open CAD Studio.TW" (headless CAD, fonts, CTB)
#   Open CalcSheet Studio (tutumomo/Open-CalcSheet-Studio)      -> "Open CalcSheet Studio TW" (key: OpenCalcSheet)
#   Only the localized TW builds are bound; upstream installs side by side are ignored.
# Also mandatory but detect-only (install by hand; --install prints the hint and exits non-zero if missing):
#   ArtCraft Launcher (storytold/craft-launcher; installs the Craft App Suite: open-source substitutes for Adobe/Office/CAD)
#   Blender           (blender.org; 3D landscape simulation)
python tools/project_paths.py --install
python tools/project_paths.py --install --dry-run
python tools/project_paths.py --install --only OpenCalcSheet   # single tool
python tools/project_paths.py --configure  # Re-configure CADCraft/OpenCADStudio font & plot folders
```

### Testing & Verification
```bash
# Full regression test suite across all case types (compares numbers against tools/selftest/baseline.json)
.venv/bin/python tools/selftest/regression.py

# Single-module self-tests
.venv/bin/python tools/design/design_core_selftest.py       # Civil/structural design engines
.venv/bin/python tools/design/design_workbench_selftest.py  # Design workbench API
.venv/bin/python tools/regs/regq_selftest.py                # Regulations query engine
.venv/bin/python tools/selftest/design_launch_check.py <id> # Launch check for specific calculator (G1~G8)

# Mandatory Delivery Quality Control Gate E1~E18 (must exit with code 0)
.venv/bin/python tools/a3_sheet/check_delivery.py <drawing.dxf> \
  --scale <scale> --layout 斷面圖 \
  --building-layer 30_擋土牆混凝土 --hatch-layer 31_擋土牆剖面線 \
  --require-layer 30_擋土牆混凝土 --require-layer 40_鋼筋 --require-layer 42_尺寸

# Quantity Takeoff & Rebar Spacing Verification
.venv/bin/python tools/takeoff/dxf_takeoff.py <drawing.dxf> --case cases/<case>/case.json
.venv/bin/python tools/takeoff/dxf_takeoff.py <drawing.dxf> --rebar --case cases/<case>/case.json
```

### Open CalcSheet Studio 交叉驗算（需桌面程式開啟）
```bash
# 連線檢查、版本、22 個模組（台灣 17 個 tw-*）
python tools/crosscheck/ocss_crosscheck.py probe

# 無狀態試算一段計算書（不碰專案），並自動檢查單位陷阱
python tools/crosscheck/ocss_crosscheck.py eval --expr "M = 20 kN*m\nW = 500 mm^3\nsigma = M/W to MPa"

# 跑內建對照案例（本專案引擎 vs OCSS 開放計算環境）
python tools/crosscheck/ocss_crosscheck.py checks

# 安裝後一次性設定：先開啟程式並啟用 MCP/API，再把 MCP 連線寫入本機 .mcp.json（預設僅預覽；token 不印出）
python tools/crosscheck/ocss_crosscheck.py register-mcp --apply
```

### Three-Axis Case Delivery Pipeline
```bash
# Verify case consistency (single source of truth in case.json)
.venv/bin/python tools/case_package/case_core.py check cases/<case>/case.json

# Execute three axes (Drawings + Budget + Report) into out/<case>/
.venv/bin/python tools/case_package/case_package.py cases/<case>/case.json --out-dir out/<case> --allow-placeholder

# Single-axis execution
.venv/bin/python tools/wall_section/make_wall_section.py cases/<case>/case.json --scale auto --out out/<case>/S-01.dxf
.venv/bin/python tools/wall_section/make_wall_section.py cases/<case>/case.json --scale auto --rebar --out out/<case>/S-02.dxf
.venv/bin/python tools/box_section/make_box_section.py cases/<case>/case.json --scale auto --rebar --out out/<case>/S-02.dxf
.venv/bin/python tools/boq/price_audit.py cases/<case>/case.json
.venv/bin/python tools/boq/boq_build.py cases/<case>/case.json --out out/<case>/<case>_工程預算書.xlsx
.venv/bin/python tools/report/make_report.py cases/<case>/case.json --out out/<case>/<case>_設計報告.docx
```

## 2. High-Level Architecture & Structure

```
Civil_Design_WorkBench/
├── AGENTS.md               # ALWAYS-ON CORE: Central operational discipline & boundaries
├── CLAUDE.md / GEMINI.md   # Assistant entry files (reference AGENTS.md)
├── cases/<案名>/case.json  # Single source of truth for each engineering case
├── out/<案名>/             # ONLY allowed landing zone for deliverables
├── _temp/<主題>/           # ONLY allowed landing zone for temp files, logs & probes (auto-disposable)
├── 完整案例(參考用)/       # Read-only reference cases
├── 標準圖圖庫/             # Read-only standard CAD details (retaining wall, channel, box culvert)
├── data/                   # Read-only reference data (cadastral, SHP, regulation texts)
├── docs/                   # Durable engineering knowledge, SOPs, and pitfall index (docs/經驗索引_INDEX.md)
└── tools/                  # Deterministic Python scripts & engines
    ├── a3_sheet/           # A3 drawing layout (make_sheet.py) & gate QC (check_delivery.py E1~E18)
    ├── acad/               # Unified headless CAD entry (acc.py: OpenCADStudio default, accoreconsole/CADCraft fallback) + ctb.py
    ├── boq/                # Budget sheet generator (boq_build.py) & price audit (price_audit.py)
    ├── box_section/        # Box culvert cross section & rebar generator (make_box_section.py)
    ├── case_package/       # Unified case model (case_core.py, qty_models.py, case_package.py)
    ├── crosscheck/         # OCSS cross-check (ocss_client.py REST client, ocss_crosscheck.py CLI, checks/)
    ├── design/             # 22+ civil/structural calculation engines & design workbench
    ├── report/             # 14-chapter design report generator (make_report.py)
    ├── selftest/           # Regression test suite (regression.py, baseline.json)
    ├── site_basemap/       # Existing site basemap DXF generator (site_basemap.py)
    ├── takeoff/            # Drawing vs budget takeoff & rebar checker (dxf_takeoff.py)
    └── wall_section/       # Retaining wall, channel & slope drawing generator (make_wall_section.py)
```

## 3. Core Invariants & Boundaries

- **File System Guardrails**:
  - Deliverables: Must land in `out/<案名>/` exclusively. Never output deliverables to root or tool directories.
  - Temporary files: Must land in `_temp/<主題>/`. `_temp/` can be unconditionally deleted anytime.
  - Read-Only Directories: `完整案例(參考用)/`, `標準圖圖庫/`, `data/`, and external drives/NAS are read-only.
- **Domain Constants**:
  - Unit: Metric meter (`$INSUNITS=6`, `$MEASUREMENT=1`).
  - Coordinates: Real TWD97 TM2 (`EPSG:3826`), never arbitrary origin.
  - CAD Text Style: `TOMO` style with `gbenor.shx` + `CHINA1.SHX`.
  - Plot Style: `monochrome.ctb` (colors 1~8 map to standard lineweights).
  - RC Design: Uniform 6% lap and loss allowance across project (`rc_design.LAP_ALLOWANCE = 0.06`).
  - Retaining Wall Rebar: Strict wall-type dispatch (`gravity`/`semigravity` nominal rebar; `cantilever` flexural; `counterfort`/`anchored`/`mse` structural components).
- **Mandatory tools (auto-installed by `--install`, from the user's forks)**: `tutumomo/OpenCADStudio`（Big5 SHX 修正版，不得改回上游）與 `tutumomo/Open-CalcSheet-Studio`。**只綁本地化 TW 版應用程式**（「Open CAD Studio.TW」／`OpenCADStudio.TW.exe`；「Open CalcSheet Studio TW」／識別碼 `tw.opencalcsheet.studio`），本機並存的上游版一律不採用；路徑只經 `project_paths` 解析。clone 後必須跑 `python tools/project_paths.py --install`，且退出碼為 0 才算環境備妥；OCSS 另需開程式一次並跑 `register-mcp --apply`。**必備工具共四項**：另兩項 **ArtCraft Launcher**（`storytold/craft-launcher`，十幾套開源軟體可平替 Adobe／Office／CAD）與 **Blender** 為手動安裝，`--install` 只偵測、缺少時印指引並以非 0 退出；Launcher 內要裝好 GridCraft、WordCraft。
- **Open CalcSheet Studio (OCSS)**: 必備工具；開放計算環境，用於逐式可稽核的計算書與第二套獨立算法（`tools/crosscheck/`）。
  - 必須桌面程式開著才有 API（`127.0.0.1:3879`），無 headless 模式；勿執行它的 `--version`／`--help`（會卡住）。
  - API 產不出 PDF：`export_pdf` 在一般安裝版回 501；PDF 只能 App 內按「Rapport」。
  - 開放環境的結果一律要交叉驗算才可進交付；模板有檢查腳本把關，自由書寫沒有。
  - 兩個不報錯的單位陷阱必查：分數次方污染單位（`R^(2/3)` → `m^0.667`，須先無因次化）、單位不自動收斂（`kN/mm²` ≠ `MPa`，須顯式 `to MPa`）。`ocss_client.unit_warnings()` 已自動偵測。
- **Headless CAD Execution**:
  - Background CAD tasks (DWG publishing, conversion) go through `tools/acad/acc.py`; default backend is OpenCADStudio (`--http` on demand; exe resolved by `project_paths.opencadstudio_exe()`, never hardcode its path), fallback `accoreconsole`/`CADCraft CLI` via `CIVIL_AI_CAD_BACKEND=cadcraft`. Always eyeball the PDF's Chinese text after publishing.
  - Do NOT automate or script CadCraft Studio GUI.
- **Import Priority**:
  - In scripts combining geometry and imagery, follow import order:
    1. `import matplotlib; matplotlib.use('Agg')`
    2. `import shapely`
    3. `import pyproj`
    4. `import cv2`, `import ezdxf`
- **Reopen & Check Verification**:
  - Always re-read output DXF/DWG, convert rendered PDF to PNG, and verify visually. All A3 sheets must pass `check_delivery.py` (exit code 0).
- **Troubleshooting**:
  - Consult `docs/經驗索引_INDEX.md` first; open only the matching section in `docs/踩坑紀錄.md` (never read the entire file).
