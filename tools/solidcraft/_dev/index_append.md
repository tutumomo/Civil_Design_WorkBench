
---

## 5. SolidCraft 參數化 3D CAD（INV — Parametric 3D Modeling）

| ID | Cue（觸發情境／錯誤特徵） | Lesson（標準可執行操作） | Evidence / 確定性元件 | Ref |
|---|---|---|---|---|
| **EXP-E1** | 使用者口述 3D CAD 需求，要求「我用說的、你作並交付成果」 | **不要去 `artcraft-gateway` 找 SolidCraft**（apps 清單無此項）；直接呼叫 `C:\Program Files\SolidCraft\solidcraft-cli.exe`。標準流程：口述需求 → 參數表（`parameters.add`，數量型用 `unit:""`）→ 特徵腳本（尺寸只寫參數運算式）→ `document.inspect{measure:true}` 做幾何自檢 → `file.export`(step/stl)＋`file.save`(container)＋CLI `snapshot`/`render` 出圖 → 回報數量與風險。 | [`tools/solidcraft/sc.py`](file:///D:/公司案件.AI/tools/solidcraft/sc.py)、[`example_run.py`](file:///D:/公司案件.AI/tools/solidcraft/example_run.py)、[操作指引](file:///D:/公司案件.AI/docs/SolidCraft操作指引.md) | `§Q` |
| **EXP-E2** | `solid.combine` 報 `unknown body 'X'`；或 `expected a length, got a value in length^2`；或腳本 JSON 報 `expected value at line N` | 1. `name` 是**特徵名**、**`body_name` 才是實體名**，combine 的 target/tools 要用 `body_name`。<br>2. 數量型參數（單元數、孔數）必須 `unit:""`，否則相乘變長度²。<br>3. JSON 裡的運算式字串一律加引號：`[0,"WALL_T","BASE_T"]`。 | 首個端到端腳本連踩三坑，逐條修正後 RC=0 | `§Q` |
| **EXP-E3** | `render.start` 報 `no image host is installed`；`render` 報「當檔案已存在時，無法建立該檔案」；`file.export` 報「系統找不到指定的路徑」 | headless CLI **不可用 `render.*` 命令**（需 GUI 主程式當 host）→ 改用 CLI 子命令 `solidcraft-cli render <src> --out x.png --overwrite` 與 `solidcraft-cli snapshot <src> --out x.png --view iso`（GPU，快）。`file.export` 目標目錄必須先 `os.makedirs`。 | 渲染／截圖皆成功出圖 | `§Q` |
| **EXP-E4** | 模型量測體積與手算理論值差 2%（U 型溝渠案例：2,491,200,000 vs 2,448,000,000 mm³） | `corner` 是**最小角點不是中心**：挖內腔時 `corner` 的 x 給了壁厚偏移 → 內腔整條內縮。挖通長向時 `corner` 的 x 給 0，內腔用 `width`/`height` 控制。**務必做「模型量測 vs 理論值」自檢（誤差 >1% 即判定建模錯）**。 | 修正後三個規格變體誤差皆 0.000% | `§Q` |
| **EXP-E5** | `commands` 輸出用 PowerShell `>` 落盤後 `json.loads` 報 `UnicodeDecodeError: 0xff` | PowerShell `>` 寫 UTF-16 BOM。SolidCraft 輸出落盤一律用 Python `subprocess` + `encoding="utf-8"`；本專案 `sc.py` 已封裝此事。 | `tools/solidcraft/sc.py` | `§Q` |
