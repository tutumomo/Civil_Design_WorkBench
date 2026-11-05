# SolidCraft 操作指引（3D CAD 參數化設計落地）

> 適用：使用者以口述方式提出 3D CAD 參數化設計需求，由 MiniMax Code 產出參數化模型、匯出檔與成果圖。
> 執行檔：`C:\Program Files\SolidCraft\solidcraft-cli.exe`（v0.24.0）
> 工具鏈：`<專案根目錄>\tools\solidcraft\`

---

## 1. 工具鏈地圖

| 檔案 | 角色 | 說明 |
|---|---|---|
| `sc_build.py` | **主工具（一鍵交付）** | 腳本 → 建構 → 匯出 → 量測 → 驗證 → 截圖 → 渲染 → 紀錄。退出碼 0 = 通過。 |
| `sc.py` | Python API 封裝 | `exec_command` / `run_script` / `snapshot` / `render` / `commands`，供程式化呼叫。 |
| `example_run.py` | 端到端範例（含幾何自檢） | U 型溝渠，自動算理論體積並比對。 |
| `example_variants.py` | 參數化變體驗證 | 同一腳本三種規格，證明「改參數即重建」。 |
| `examples\*.json` | 建模腳本範本 | `U型溝.json`、`沉頭孔平板.json`、`擋土牆.json` |
| `templates\rc_u_channel.script.json` | 範本（模板版） | 內建參數註解的 U 型溝渠 |

---

## 2. 核心概念：什麼是「參數化」

SolidCraft 的模型是**參數驅動的特徵樹**，不是一堆固定幾何。因此：

1. 所有可變尺寸先建成 `parameters`（具名參數，帶單位與中文說明）。
2. 建模特徵的尺寸欄位寫**參數運算式**（如 `"INNER_W + 2 * WALL_T"`），不寫死數字。
3. 需求變更時只改參數（`parameters.change`），模型自動重建，不需要重畫。
4. 交付時同時給出：`.solidcraft`（保留參數與時間軸，可回溯）、`.step`/`.stl`/`.3mf`（下游工具用）、數量表、成果圖。

這就是「我用說的，你作並交付成果」的技術基礎：口述需求 → 參數表 → 模型 → 匯出。

---

## 3. 一鍵交付（標準流程）

在專案根目錄執行（先 `cd` 到專案根目錄，以下路徑皆為相對路徑；產出依 AGENTS.md §1.1 落 `out\`）：

```bat
set PYTHONIOENCODING=utf-8
python tools\solidcraft\sc_build.py ^
  <建模腳本.json> --out-dir "out\<案名>\<模型名>" --name <模型名> ^
  --param "B=400 mm" --param "H=350 mm" ^
  --formats step,stl,3mf --views iso,top,front ^
  --expect-volume 1978527378.44 --tol 0.01 --expect-bbox 2000x600x3400
```

| 選項 | 用途 |
|---|---|
| `--param 名稱=運算式` | **覆寫參數**（可重複），會在腳本最後追加 `parameters.change` 觸發整條時間軸重建 |
| `--formats` | 匯出格式，預設 `step,stl,3mf` |
| `--views` | 截圖視角，預設 `iso,top,front` |
| `--expect-volume` / `--tol` | 體積驗證（mm³ 與容許誤差 %），**強烈建議必填** |
| `--expect-bbox` | 外框驗證（`LxWxH` mm，容許 0.01 mm） |
| `--no-render` | 跳過產品渲染（省時） |

**產出檔**：`模型名.solidcraft`（原生設計檔）、`.step`、`.stl`、`.3mf`、`_iso.png`/`_top.png`/`_front.png`、`_render.png`、`_參數表.csv`、`_measure.json`、`_紀錄.log`

**退出碼**：0 = 建構成功且驗證通過；1 = 失敗或數量不符。**退出碼非 0 不可交件。**

---

## 4. 腳本格式與核心命令

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

### 兩種布林寫法（擇一）

| 方式 | 寫法 | 說明 |
|---|---|---|
| **A. 同命令 operation**（推薦，範例採用） | `solid.box` 帶 `operation: "new" \| "cut" \| "join"` 與 `targets: ["實體名"]` | 一次成型，不用事後 combine |
| B. 分離建體再 combine | `solid.box` 各給 `body_name`，再 `solid.combine {target, tools:[...], operation:"cut"\|"join"\|"intersect"}` | 需注意 `name`≠`body_name`（見 §6） |

### 核心命令
`parameters.add` `parameters.change` `parameters.list` `parameters.graph` `parameters.export`
`solid.box` `solid.cylinder` `solid.combine` `solid.extrude` `solid.revolve` `solid.sweep`
`solid.fillet` `solid.chamfer` `solid.shell` `solid.hole` `solid.thread` `solid.pipe` `solid.pattern`
`sketch.create` `sketch.draw.dimensioned` `sketch.finish` `sketch.rectangle.center` `sketch.circle.center`
`component.create` `body.rename` `appearance.assign` `document.inspect` `view.save`
`file.export` `file.save` `file.insert_step` `file.insert_mesh` `file.export_view_dxf`

完整命令目錄（474 筆，每筆含 id/label/params）：
`docs\solidcraft_commands.txt`
分組摘要：`docs\solidcraft_commands_summary.txt`

---

## 5. 幾何自檢（強制）

`document.inspect {measure:true}` 會給出每個實體的 `volume_mm3`、`area_mm2`、`bbox`、`faces`、`closed`、`mass_g`。

**必須把模型量測與自己手算的理論值比對，誤差 >1% 即判定建模有誤。** 實測兩次都靠這個抓到瑕疵：

| 案例 | 模型量測 | 理論值 | 差異 | 真因 |
|---|---|---|---|---|
| U 型溝渠 | 2,491,200,000 | 2,448,000,000 mm³ | 2.015% | `corner` 是**最小角點**，挖內腔時 x 給了壁厚偏移 → 內腔整條內縮 |
| RC 擋土牆 | 1,978,528,112 | 1,978,527,378 mm³ | 0.00004% | ✓ 通過 |

自檢公式範例：
```
U型溝   體積 = L×(B+2t)×(H+tb) − L×B×H
擋土牆  體積 = L×T×H + L×BL×BT − NZ×π×(HD/2)²×T
```
> 擋土牆的趾板在牆身**下方**（Z 從 −BT 到 0），與牆身不重疊 → 不要扣重疊體積。

---

## 6. 踩坑紀錄（實測）

| # | 現象 | 原因 | 解法 |
|---|---|---|---|
| 1 | `unknown body 'Cutter'` | `name` 是**特徵名**（時間軸一步），`body_name` 才是**實體名**（可被 combine 引用） | 用 `body_name`；或改用 §4 的 operation/targets 寫法 |
| 2 | `expected value at line N column M` | 腳本 JSON 語法錯，運算式沒加引號 | `"corner": [0, "WALL_T", "BASE_T"]` |
| 3 | `expected a length, got a value in length^2` | 數量型參數帶了長度單位 | 數量用 `unit: ""` |
| 4 | `系統找不到指定的路徑` | 輸出目錄不存在 | 先建目錄 |
| 5 | `當檔案已存在時，無法建立該檔案` | render 不覆寫既有檔 | 加 `--overwrite`（`sc.render` 已自動處理） |
| 6 | `no image host is installed`（`render.start`） | `render.*` 命令需要 GUI 主程式當 host | 改用 CLI 子命令 `render` / `snapshot`（headless 可用） |
| 7 | `render.settings.set` 報 `missing field 'method'` | 該命令 set 結構另有必填欄位 | 用 CLI `render` 子命令 |
| 8 | 體積與理論值差 2% | `corner` 是最小角點，挖內腔時 x 給了偏移 | 挖通長向時 `corner` 的 x 給 0 |
| 9 | `commands` 輸出用 `>` 落盤後讀不到 | PowerShell `>` 寫 UTF-16 BOM | 一律用 Python `subprocess` + `encoding="utf-8"` |
| 10 | 排水孔只貫穿半厚 | `solid.cylinder` 的 `base` 是**底面中心**、`axis` 決定方向，`base` 落在牆身中線會只挖到一側 | `base` 的 y 給 `-T/2`（牆外），`axis:[0,1,0]`，`height:"T*3"` |
| 11 | `--expect-volume 0` 造成 ZeroDivisionError | 除零 | `sc_build.py` 已修（`> 0` 才檢查） |

---

## 7. 常見模型套路

### 7.1 溝渠 / U 型槽（外框減內腔）
1. `solid.box` 外框：`length=B+2t, width=Lg, height=H+tb`，`body_name` = 成品名
2. `solid.box` 內腔：`length=B, width=Lg+20mm, height=H+10mm`（**必須超出**待挖面）
3. `solid.combine {target:成品名, tools:[暫存名], operation:"cut"}`

### 7.2 擋土牆（牆身＋趾板＋排水孔）
1. 牆身 `solid.box`（`operation:"new"`）→ 趾板 `solid.box`（`operation:"join", targets:["擋土牆"]`）
2. 排水孔 `solid.cylinder`（`operation:"cut", targets:["擋土牆"]`），逐孔一個命令
3. 孔位以參數算：`base z = H/(NZ+1)*n`

### 7.3 沉頭孔平板（草圖流程）
1. `sketch.create {plane:"XY"}` → `sketch.draw.dimensioned {command:"sketch.rectangle.center", dimensions:{width:"L",height:"W"}}` → `sketch.finish`
2. `solid.extrude {distance:"T"}` → `solid.fillet` → `solid.hole`

### 7.4 改參數重建
`{"command":"parameters.change","params":{"name":"W","expression":"200"}}`
重建後 `document.inspect` 顯示新 bbox/體積。`sc_build.py --param` 即自動走這條路。

### 7.5 顏色
`appearance.assign {bodies:["實體名"], color:"#BFB9AE"}` → 之後 `snapshot` / `render` 才會套用。

---

## 8. 已驗證案例

| 案例 | 位置 | 驗證結果 |
|---|---|---|
| U 型溝渠（內寬 600／壁厚 120／10 單元） | `SolidCraft範例\U型溝渠\` | 體積誤差 0.000%，10 面，水密 |
| RC 擋土牆（H3000／L2000／T250／趾板 600×400／3 排 ⌀50 排水孔） | `SolidCraft範例\擋土牆\` | 體積誤差 0.00004%，外框 2000×600×3400，11 面，水密 |
| U 型溝渠三規格變體（600/800/400 內寬） | `SolidCraft範例\U型溝渠_變體\` | 三者誤差皆 0.000% |
| U 型溝 1 m 單元（B=400） | `tools\solidcraft\_selftest\v3\` | 體積與外框皆通過 |

---

## 9. MCP 註冊（尚未執行，待使用者同意）

若要讓後續工作階段直接呼叫 SolidCraft 原生工具，需註冊 MCP server（會寫入 `<使用者家目錄>\.minimax\mcp.json`）：

```
command: C:\Program Files\SolidCraft\solidcraft-cli.exe
args:    ["mcp", "--headless"]
```

另有 `solidcraft-cli mcp setup --client opencode|claude-desktop|claude-code|cursor` 可自動寫入該客戶端設定檔。
**目前一律走 CLI 封裝**，已可完成全部交付需求，不依賴 MCP。
