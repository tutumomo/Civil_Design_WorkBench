---
name: solidcraft-param
description: 以 SolidCraft CLI 建立參數化 3D CAD 模型並交付（STEP/STL/3MF/原生設計檔/成果圖/數量表）。適用於使用者口述 3D 模型需求（土木構造物、零件、管線、斷面）要參數化建模、修改尺寸重建、或匯出模型檔與成果附圖時使用。
---

# SolidCraft 參數化 3D CAD 設計技能（`solidcraft-param`）

> 本技能封裝 SolidCraft CLI 的參數化建模工作法。
> 詳細操作手冊見 [`<專案根目錄>/docs\SolidCraft操作指引.md`](file:///D:/公司案件.AI/docs/SolidCraft操作指引.md)。
> 執行檔：`C:\Program Files\SolidCraft\solidcraft-cli.exe`（v0.24.0）

## 1. 核心原則

1. **先參數、後幾何**：所有會變的尺寸建成 `parameters.add`（名稱／值／單位／中文註解），建模特徵一律引用參數運算式，不寫死數字。需求變更時只改參數（`parameters.change`），模型自動重建。
2. **數量型參數用 `unit: ""`**：帶了 `mm` 會變成長度×長度 → `expected a length, got a value in length^2`。
3. **`name` 是特徵名、`body_name` 才是實體名**：`solid.combine` 的 `target`/`tools` 要用 `body_name`。
4. **幾何量測必做**：跑完必須 `document.inspect {measure:true}`，體積與手算理論值誤差 >1% 即判定建模有誤（常見是 `corner` 偏移）。**不驗證不交件。**

## 2. 一鍵交付（主工具）

```bat
set PYTHONIOENCODING=utf-8
python <專案根目錄>/tools\solidcraft\sc_build.py ^
  <建模腳本.json> --out-dir "<專案根目錄>/<案名>\<模型名>" --name <模型名> ^
  --param "B=400 mm" --param "H=350 mm" ^
  --formats step,stl,3mf --views iso,top,front ^
  --expect-volume 1978527378.44 --tol 0.01 --expect-bbox 2000x600x3400
```

**退出碼 0 = 建構成功且驗證通過；1 = 失敗。退出碼非 0 不可交件。**

產出：`模型名.solidcraft`（原生設計檔，保留參數與時間軸）、`.step` / `.stl` / `.3mf`、
`_iso.png`/`_top.png`/`_front.png`（GPU 視圖）、`_render.png`（產品渲染）、`_參數表.csv`、`_measure.json`、`_紀錄.log`

## 3. 腳本骨架

```json
{
 "commands": [
  { "command": "parameters.add", "params": { "name": "B", "expression": "300 mm", "comment": "溝內寬" } },
  { "command": "solid.box", "params": {
      "length": "B + 2*t", "width": "Lg", "height": "H + tb",
      "center": [0, 0, "(H + tb)/2"],
      "operation": "new", "body_name": "U型溝", "name": "外形" } },
  { "command": "solid.box", "params": {
      "length": "B", "width": "Lg + 20 mm", "height": "H + 10 mm",
      "center": [0, 0, "tb + (H + 10 mm)/2"],
      "operation": "cut", "targets": ["U型溝"], "name": "溝槽" } }
 ]
}
```

**布林兩種寫法**：A. 同命令 `operation: new|cut|join` + `targets:[實體名]`（推薦）；B. 分離建體 + `solid.combine {target, tools, operation}`。

## 4. 交付清單（缺一不可）

- `.step` — B-rep 實體（AutoCAD / Revit / Rhino）
- `.stl` / `.3mf` — 三角網格（3D 列印、量測軟體）
- `.solidcraft` — 原生設計檔（保留參數與時間軸，可回溯、可改參數重建）
- 等軸視／正視／俯視 PNG + 產品渲染 PNG
- `_參數表.csv`（參數一覽）+ `_measure.json`（體積／面積／bbox／面數／質量）
- 交件回報：模型說明、參數清單、數量、檔案清單、資料來源、可信度（1–10）、已知風險

## 5. 高頻踩坑

| 現象 | 解法 |
|---|---|
| `unknown body 'X'` | 用 `body_name` 不用 `name` |
| `expected value at line N` | 腳本 JSON 語法錯，運算式字串要加引號 |
| `expected a length, got a value in length^2` | 數量參數改 `unit: ""` |
| 當檔案已存在時，無法建立該檔案 | render 加 `--overwrite`（`sc.render` 已自動處理） |
| `no image host is installed` | 不要用 `render.*` 命令；改 CLI `render` / `snapshot` 子命令 |
| 體積與理論值不符 | `corner` 是**最小角點**，挖長向時 x 給 0 |
| 排水孔只貫穿半厚 | `solid.cylinder` 的 `base` 是**底面中心**；要貫穿牆厚就 `base` 給牆外、方向軸對齊 |
| 輸出目錄不存在 | 先建目錄 |
| 落盤 JSON 讀不到 | 禁用 shell `>`；用 Python `subprocess` + UTF-8 |

## 6. 已驗證案例

- `SolidCraft範例\U型溝渠\` — 內寬600/壁厚120/10單元，體積誤差 0.000%
- `SolidCraft範例\擋土牆\` — RC 擋土牆（牆身＋趾板＋3 排排水孔），體積誤差 0.00004%
- `SolidCraft範例\U型溝渠_變體\` — 三種規格變體，證明改參數即重建
- 範本：`tools\solidcraft\examples\{U型溝,擋土牆,沉頭孔平板}.json`
