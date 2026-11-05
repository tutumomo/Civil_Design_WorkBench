---
name: solidcraft-param
description: 以 SolidCraft CLI 建立參數化 3D CAD 模型並交付（STEP/STL/3MF/原生設計檔/成果圖/數量表）。適用於使用者口述 3D 模型需求（土木構造物、零件、管線、斷面）要參數化建模、修改尺寸重建、或匯出模型檔與成果附圖時使用。
---

# SolidCraft 參數化 3D CAD 設計技能（`solidcraft-param`）

> 本技能封裝 SolidCraft CLI 的參數化建模工作法。
> 詳細操作手冊見 [`docs\SolidCraft操作指引.md`](../../../docs/SolidCraft操作指引.md)。
> 執行檔由 `tools\project_paths.py` 的 `solidcraft_cli()` 解析（實測 0.30.1）。**不寫死路徑、不寫死版本**，版本會更新，寫死就遲早誤導。

**職責一句話**：給定使用者口述的構造物需求，產出體積與外框都對過手算值的參數化 3D 模型檔，交給需要 STEP／STL 的下游（3D 列印、量測、Revit）。

## 1. 核心原則

1. **先參數、後幾何**：所有會變的尺寸建成 `parameters.add`（名稱／值／單位／中文註解），建模特徵一律引用參數運算式，不寫死數字。需求變更時只改參數（`parameters.change`），模型自動重建。
2. **數量型參數用 `unit: ""`**：帶了 `mm` 會變成長度×長度 → `expected a length, got a value in length^2`。
3. **`name` 是特徵名、`body_name` 才是實體名**：`solid.combine` 的 `target`/`tools` 要用 `body_name`。
4. **幾何量測必做**：跑完必須看 `_measure.json`／`_紀錄.log` 的體積與外框。驗收線分兩段：與手算值差 **> 0.01% 就要查**（多為 `corner` 或布林裁切偏移），**> 1% 直接判定建模錯**。**不驗證不交件。**

## 2. 一鍵交付（主工具）

```bat
set PYTHONIOENCODING=utf-8
python <專案根目錄>/tools\solidcraft\sc_build.py ^
  <建模腳本.json> --out-dir "<專案根目錄>/out/<案名>/<模型名>" --name <模型名> ^
  --param "B=400 mm" --param "H=350 mm" ^
  --formats step,stl,3mf --views iso,top,front ^
  --expect-volume 1978527378.44 --tol 0.01 --expect-bbox 2000x600x3400
```

**退出碼 0 = 建構成功且驗證通過；1 = 失敗。退出碼非 0 不可交件。**

⚠ `--expect-volume` 與 `--expect-bbox` 要自己算，不能省。`--tol` 預設 0.10% 太鬆，建議 0.01。沒給預期值時腳本只會印「（未指定預期值）」卻可能退出碼 0，那就等於沒驗。
⚠ 交付物一律落 `out\<案名>\`（AGENTS.md §1.1），不要寫到 `<專案根目錄>/<案名>/`。

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

範本：`tools\solidcraft\examples\{U型溝,擋土牆,沉頭孔平板}.json`。下列兩案於 **2026-11-05 以 solidcraft-cli 0.30.1 重跑**，指令可直接照抄。

| 案例 | 期望值怎麼來 | 實測結果 |
|---|---|---|
| 擋土牆（牆高3000／牆長2000／牆厚250／趾400／踵600／洩水孔3排） | 手算 B-rep 體積 1978527378.44 mm³ | 退出碼 0；體積 1978528112.286 mm³，**差 0.0000%**；外框 2000.000×600.000×3400.000；面 11、封閉 True |
| U型溝（內寬600／內高600／壁厚120／底板120／單節1000，**1 個單元**） | 斷面 0.84×0.72 − 0.60×0.60 = 0.2448 m² × 1 m = 0.2448 m³ | 退出碼 0；體積 244800000.000 mm³，**差 0.0000%**；外框 840.000×1000.000×720.000 |

重跑指令（擋土牆）：

```bat
python <專案根目錄>/tools\solidcraft\sc_build.py "tools\solidcraft\examples\擋土牆.json" ^
  --out-dir "<專案根目錄>/out/<案名>/RC擋土牆" --name RC擋土牆 ^
  --expect-volume 1978527378.44 --tol 0.01 --expect-bbox 2000x600x3400
```

重跑指令（U型溝單元）：

```bat
python <專案根目錄>/tools\solidcraft\sc_build.py "tools\solidcraft\examples\U型溝.json" ^
  --out-dir "<專案根目錄>/out/<案名>/U型溝" --name U型溝 ^
  --param "B=600 mm" --param "H=600 mm" --param "t=120 mm" --param "tb=120 mm" --param "Lg=1000 mm" ^
  --expect-volume 244800000 --tol 0.01 --expect-bbox 840x1000x720
```

> ⚠ `SolidCraft範例\` 底下是 **2026-10-27 舊版產物**（`執行紀錄.log`、`_數量表.json`、`_等軸視.png` 是舊命名，缺 `_measure.json`），且紀錄裡的腳本路徑還指向已遷移的 `D:\公司案件.AI\`。要引用數據一律看本節，不要引用那批資料夾。
> ⚠ 舊版技能寫的「內寬600／壁厚120／**10單元**，誤差 0.000%」在 `examples\U型溝.json` 上重跑不出來：那支範本是 **1 個單元**（體積 0.2448 m³）。10 單元是另一份設計（`SolidCraft範例\U型溝渠_變體\`），以 `N_UNITS` 數量參數建模，腳本未隨範本保留。

## 7. Anti-jobs（我永遠不做的事）

| 不做 | 原因 |
|---|---|
| 不寫死 CLI 路徑或版本 | 版本會更新（本次實測就從文件寫的 0.24.0 變成 0.30.1），寫死會讓下一個人以為工具壞了 |
| 不用猜的體積當驗證 | 沒給 `--expect-volume` 的「通過」等於什麼都沒驗，比不驗更危險 |
| 不把建構失敗的模型交出去 | STEP 檔有大小不代表是水密實體，要看 `_紀錄.log` 的「結論：通過」 |
| 不寫入 `D:\公司案件\`、`SolidCraft範例\`、`完整案例(參考用)\` | 那是輸入資產與歷史證據，覆寫就沒有第二份 |
| 不在 `--tol` 仍為 0.10% 時宣稱精度 | 0.10% 對 3.4 m 高的牆等於容許 3.4 mm，太鬆 |

## 8. 邊界三級

| 級別 | 這個技能範圍內的行為 |
|---|---|
| **do（直接做）** | 寫 JSON 腳本；跑 `sc_build.py`；量測、截圖、產參數表；寫 `out\<案名>\<模型名>\` 與 `_temp\` |
| **draft-first（先草擬）** | 模型出來先給人看 PNG 與參數表，確認尺寸與構造合理，再說「可交付」 |
| **ask-first（先問過）** | 覆寫 `out\` 內既有模型；改動 `tools\solidcraft\` 底下的範本或腳本；把新模型歸入共用範例 |

## 9. First run

第一次被叫用時，缺的才問，最多問三件：

1. 構造物類型與關鍵尺寸（有沒有可照的標準圖或舊模型）。
2. 手算體積或斷面積（拿不到就先自己算，再回頭跟使用者對）。
3. 要哪些格式（預設 `step,stl,3mf`）與輸出案名。

問完直接跑。跑完貼 `_紀錄.log` 的「檢核」與「結論」兩行，不要只說「好了」。
