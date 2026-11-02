
## Q. SolidCraft 參數化 3D CAD（2026-10-27，MiniMax Code，CLI 落地）
- **安裝位置不在 ArtCraft 套件內**：`C:\Program Files\SolidCraft\`（`solidcraft-cli.exe` 102 MB、
  `solidcraft.exe` 142 MB、`solvecraft-cli.exe`）；`artcraft-gateway` 的 apps 清單**沒有** solidcraft。
  → 必須直接呼叫 `solidcraft-cli.exe`，不要去 artcraft-gateway 找。
- **`name` 是特徵名、`body_name` 才是實體名**：首個腳本 `solid.combine` 報
  `unknown body 'Cutter'` → `solid.box/cylinder` 的 `name` 只在時間軸上留名，
  要被 combine 引用必須給 `body_name`。
- **`corner` 是最小角點，不是中心**：挖內腔時若 `corner` 的 x 給了壁厚偏移，
  內腔會整條往內縮，體積與理論值差 2.015%（模型量測 2,491,200,000 vs 理論 2,448,000,000 mm³）。
  → 挖通長向時 `corner` 的 x 給 0，內腔寬高用 `width`/`height` 控制。
  **這個坑靠「模型量測 vs 手算理論值」才抓到，一定要做幾何自檢。**
- **數量型參數必須 `unit: ""`**：`N_UNITS` 給 `mm` 會使 `UNIT_LEN * N_UNITS` 變成長度×長度，
  報 `expected a length, got a value in length^2`。
- **腳本 JSON 的運算式字串要加引號**：`"corner": [0, WALL_T, "BASE_T"]` 是 JSON 語法錯，
  必須寫成 `[0, "WALL_T", "BASE_T"]`。
- **`render.*` 命令在 headless CLI 會失敗**：`render.start` 報 `no image host is installed`
  （需要 GUI 主程式當 host）；`render.settings.set` 另要求 `method` 欄位。
  → **改用 CLI 子命令**：`solidcraft-cli render <src> --out x.png`（需 `--overwrite` 才能覆寫）
  與 `solidcraft-cli snapshot <src> --out x.png --view iso`（GPU，快）。
- **`commands` 輸出不能用 shell 重導向落盤**：PowerShell `>` 產生 UTF-16 BOM，
  後續 `json.loads` 報 `UnicodeDecodeError: 0xff`。→ 用 Python `subprocess` + `encoding="utf-8"`。
- **`file.export` 目標目錄必須先存在**：報 `系統找不到指定的路徑`（不是中文編碼問題）；
  SolidCraft 本身支援中文路徑。
- **已驗證可重現案例**：`tools\solidcraft\example_run.py`（U 型溝渠，體積誤差 0.000%）與
  `example_variants.py`（三種規格變體，誤差皆 0.000%，證明改參數即重建成立）。
