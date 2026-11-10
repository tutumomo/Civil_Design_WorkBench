# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Always-On Core**: Complete project operational rules, boundaries, and engineering invariants are unified in [`AGENTS.md`](AGENTS.md) (imported below, so it is loaded every session). This file adds commands and architectural context for Claude Code; where the two differ, `AGENTS.md` wins.

@AGENTS.md

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
# Unified entry: runs every selftest and summarizes (CI uses `--no-cad --skip regs-verified`)
.venv/bin/python tools/selftest/run_all.py
.venv/bin/python tools/selftest/run_all.py --changed        # only tests tied to git changes
.venv/bin/python tools/selftest/run_all.py --no-cad         # skip regression (no CAD backend)
.venv/bin/python tools/selftest/run_all.py --list

# Full regression test suite across all case types (compares numbers against tools/selftest/baseline.json).
# `--update` rewrites the baseline: ask-first, only for an intentional design change; with --only it
# rewrites just those cases. `--only` accepts repeats or comma lists; `--list` prints scanned cases.
.venv/bin/python tools/selftest/regression.py
.venv/bin/python tools/selftest/regression.py --only 排水溝U型
.venv/bin/python tools/selftest/regression.py --list

# Single-module self-tests
.venv/bin/python tools/selftest/design_core_selftest.py       # Design engines, hand-calc comparisons
.venv/bin/python tools/selftest/design_workbench_selftest.py  # Design workbench API / catalog rules
.venv/bin/python tools/regs/regq_selftest.py                  # Regulations query engine

# Single test class / single test (design_core_selftest is plain unittest; the workbench selftest
# is a custom check runner with no per-test filter)
.venv/bin/python tools/selftest/design_core_selftest.py WallRebarTests
.venv/bin/python tools/selftest/design_core_selftest.py WallRebarTests.<test_name>
.venv/bin/python tools/selftest/design_core_selftest.py -k rebar

# Calculator launch check G0~G8 (one calculator, or all)
.venv/bin/python tools/selftest/design_launch_check.py <id>
.venv/bin/python tools/selftest/design_launch_check.py --all

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

### Design Calculators & Local Web Workbench
```bash
# Unified calculator entry (same registry the web workbench and the `regs` MCP design_* tools use)
.venv/bin/python tools/design/design_cli.py list
.venv/bin/python tools/design/design_cli.py show <id>     # input example + limitations
.venv/bin/python tools/design/design_cli.py run ...       # see `run --help`

# Regulations query (CLI) and the web UI (one server, default port 8765: regs at /, workbench at /design)
.venv/bin/python tools/regs/regq.py <question>            # --search / --clause ID CLAUSE / --topics / --json
./web.sh regs|design|status|stop|restart [--port PORT] [--host HOST]
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

### How the pieces connect

- **`cases/<案名>/case.json` (`civil-case/1`) drives everything.** `case_core.py` loads it, calls the category model in `qty_models.py` (`road`/`wall`/`channel`/`slope`) and the matching `tools/design/` engines to build `quantity_context()`, then *derives* the downstream inputs: `derive_boq()` for the budget and `derive_report()` (including the injected design sections) for the report. Quantities are never typed twice; `consistency()` fails the case when a derived number and a model formula disagree.
- **`case_package.py` only orchestrates.** It writes the derived inputs to `out/<案名>/_case/`, runs each axis tool as a subprocess (`boq_build.py`, `make_report.py`, section drawing + `check_delivery.py` + `dxf_takeoff.py`), collects exit codes into `<案名>_案件交付清單.md` / `_交付狀態.json`, and leaves per-axis `_log_<軸>.txt`. When an axis fails, read that log first. `--only boq,report,drawing` reruns a subset.
- **Design calculators have one registry.** `tools/design/design_api.py` holds `CATALOG` (metadata, example, field rules) and `RUNNERS` (id → engine function); `run_calculation()` returns the `civil-design-run/1` envelope. `design_cli.py`, the web workbench (`tools/regs/regs_server.py` serving `/design`) and the `regs` MCP `design_*` tools are all thin fronts over it. Adding a calculator means engine file + `CATALOG` entry + `RUNNERS` entry + tests, enforced by `design_launch_check.py`.
- **Retaining walls dispatch by type** through `tools/design/wall_system.py` (`analyse()` / `rebar_design()`); `case_core` and the drawing tools go through it rather than calling a specific wall engine. An unknown `wall_type` is an error, never a fallback to cantilever.
- **Drawing tools share `tools/drawing_rules.py`** (layer colours, lineweights, standard scales, `add_plot_layer()`) and hand DXF to `tools/acad/acc.py` for DWG/PDF. `check_delivery.py` re-reads the DXF as the gate.
- **Regression is number-based.** `regression.py` reruns every case under `cases/` and compares tracked numbers with `tools/selftest/baseline.json`. Cases already failing in the baseline are reported as known-bad and do not fail the run (currently `擋土牆3m重力式_北屯民政里`, which lacks case data).
- **No package install.** There is no `pyproject.toml`; each script inserts `tools/` (and sibling tool folders) into `sys.path` and imports modules by bare name (`import case_core`, `import rc_design`). Run scripts by path from the repo root, and resolve every external path through `tools/project_paths.py`.

## 3. Claude-Specific Notes (rules themselves live in AGENTS.md)

- **Open CalcSheet Studio (OCSS)**: 必備工具；開放計算環境，用於逐式可稽核的計算書與第二套獨立算法（`tools/crosscheck/`）。
  - 必須桌面程式開著才有 API（`127.0.0.1:3879`），無 headless 模式；勿執行它的 `--version`／`--help`（會卡住）。
  - API 產不出 PDF：`export_pdf` 在一般安裝版回 501；PDF 只能 App 內按「Rapport」。
  - 開放環境的結果一律要交叉驗算才可進交付；模板有檢查腳本把關，自由書寫沒有。
  - 兩個不報錯的單位陷阱必查：分數次方污染單位（`R^(2/3)` → `m^0.667`，須先無因次化）、單位不自動收斂（`kN/mm²` ≠ `MPa`，須顯式 `to MPa`）。`ocss_client.unit_warnings()` 已自動偵測。
- **Docs still show Windows-style commands** (`python -E -P -X utf8 tools/selftest/...`). On this Linux/macOS checkout use `.venv/bin/python` with forward slashes.
- **Troubleshooting**: consult `docs/經驗索引_INDEX.md` first; open only the matching section in `docs/踩坑紀錄.md` (never read the entire file).
