# 計算器 → 設計圖 SOP（出圖上架產線）

> 2026-11-11 建立。對象：要讓設計工作台某個計算器按得出「產生設計圖」的人或智能體。
> 姊妹文件：`docs/設計計算器上架SOP.md`（計算器本身上架，G0～G8）。本檔管**出圖**這一段，閘門編號 DG0～DG9。
> 使用者操作說明與 API 見 `docs/工作台設計圖產線.md`；待補清單見 `docs/設計圖產線補齊_工作計劃書_2026-11-11.md`。

**本檔有兩種內容，請分清楚：**
標「現行」者是程式今天就這樣運作；標「待 D0」者是本 SOP 定下的規則，自動檢核要等工作計劃書 D0 落地後才有，在那之前靠人照表檢查。

## 0. 完成定義（Definition of Done）

一個計算器算「可出圖」，DG0～DG8 全過才算；DG9 依下表適用範圍：

| 關 | 內容 | 怎麼驗 | 沒過會怎樣 | 自動化 |
|---|---|---|---|---|
| DG0 | 已表態：`supported`／`not_applicable`（附理由），不可留白 | `design_section.capability(id)` | 使用者看到誤導訊息 | 待 D0 |
| DG1 | 圖說規格已與使用者確認（圖名、圖號、張數、內容、比例範圍） | §1 規格表有紀錄 | 畫完才發現不是要的圖 | 人工 |
| DG2 | 圖上每個數字都指得回計算結果欄位；預設值有明示 | §2 欄位對照表 | 圖與計算書不一致 | 待 D0（部分） |
| DG3 | 以 `CATALOG` 範例出得了 DXF，張數與檔名符合 `sheets` | `design_section.py <id> <payload> --no-publish` | 按鈕一按就報錯 | 待 D0 |
| DG4 | DXF 合乎製圖規定：`$INSUNITS=6`、`TOMO` 字型、`add_plot_layer()` 圖層、A3 圖框 | `check_delivery.py` E1～E18 exit 0 | 交不出去 | 現行 |
| DG5 | 圖／數對帳：斷面積、鋼筋間距與計算結果相符（適用者） | `dxf_takeoff.py`（`--rebar`） | 圖畫的跟算的不同 | 現行（wall／channel／box） |
| DG6 | DWG／PDF 轉得出來，`missing_fonts` 為空 | `publish=True` 實跑 | 中文變方框 | 現行 |
| DG7 | PDF 轉 PNG 目視；**每種新圖至少交使用者確認一次** | 人看 | 自動檢核抓不到「讀不懂」 | 人工 |
| DG8 | 邊界測過（§6）；文件、能力表、自測同步；回歸不變 | `run_all.py`、`regression.py` | 改壞別人 | 現行＋待 D0 |
| DG9 | 圖上關鍵數值經第二套獨立算法核過（Open CalcSheet Studio） | `ocss_crosscheck.py checks`，差異皆已處置 | 引擎算錯，圖照著錯 | 需 OCSS 桌面程式開啟；人在場 |

計算未通過（`ok=false`）不出圖——這是前端現行閘門，新圖不得繞過。

**DG9 的適用範圍**：有 `tw-*` 模板或可手寫公式鏈的計算器都要做；植筋、基腳、柱腳錨栓這類「圖會被照著施工」的詳圖為必做，沒過不得上架。需要求解器、OCSS 做不了的（剛架、圓弧滑動、網路演算）免做，改以 `design_core_selftest.py` 的手算對照為準，並在能力表註明。DG9 是**上架時做一次**，不是每次出圖都跑（OCSS 沒有 headless 模式）。

## 1. 階段一：定圖說規格（先問清楚，不要急著畫）

動手前填這張表，交使用者確認（屬 `draft-first`）。**不確定的欄位用問的，不要猜。**

| 欄位 | 說明 | 例（`rc_beam`） |
|---|---|---|
| 圖名／圖號 | 依公司慣例；未定者先問 | B-01 梁斷面配筋圖 |
| 張數 | 斷面圖與配筋圖是否分張 | 1 張 |
| 視圖 | 平面／剖面／立面／詳圖／表 | 斷面 1、配筋表 1 |
| 必標尺寸 | 列舉 | b、h、保護層、主筋間距、箍筋間距 |
| 必列表格 | 配筋表、尺寸表、數量表 | 配筋表 |
| 比例範圍 | 常用比例；是否縱橫異比例 | 1:10～1:20 |
| 不畫的東西 | 明寫限制，會印在圖面說明 | 不含搭接、錨定長度 |
| 標準圖來源 | `標準圖圖庫/`、`_ref/components_dxf/` 有無可引用 | 無 |

**判斷「該不該出圖」**：計算器的輸入與輸出裡沒有任何幾何（如 `hydrology`）→ 登錄 `not_applicable` 並寫理由，不硬湊。成果是曲線或拓撲（水面線、網路）→ 可以出，但圖名要寫明是「圖表」或「示意圖」，非比例圖須註明。

## 2. 階段二：資料契約（圖上的數字從哪來）

### 2.1 鐵則

1. **繪圖端不計算**。號數、間距、尺寸一律讀計算結果；結果裡沒有的，回去擴充引擎（走 `docs/設計計算器上架SOP.md`，另立 commit），不可在繪圖端自己挑鋼筋或補尺寸。
2. **預設值要現形**。出圖需要、但計算器沒有的尺寸，進 `defaults_used`，且**印在圖面說明欄並標「假設值」**。影響結構安全的尺寸（壁厚、版厚、埋深）不得用預設值——改成計算器輸入欄。
3. **模型空間永遠是公尺**；`--unit` 只改標註顯示（現行）。

### 2.2 欄位對照表（每個計算器一張，寫進繪圖工具的 docstring）

| 圖上元素 | 來源欄位 | 單位換算 |
|---|---|---|
| 梁寬 b | `result.flexure.b_mm` | mm → m |
| 箍筋間距 | `result.shear.spacing_mm` | 標註原值 |
| … | … | … |

對照表列不出來源的元素，就是 DG2 沒過。

### 2.3 兩條資料路線

| 路線 | 適用 | 資料流 | 現況 |
|---|---|---|---|
| **甲：案件模型** | 計算器對應得到 `qty_models` 的類別（`wall`／`channel`／`slope`／`box_culvert`） | payload → `build_case()` 組 `civil-case/1` → 繪圖工具讀案件、經 `case_core` 取數量與設計結果 | 現行，7 個計算器都走這條 |
| **乙：結果直繪** | 沒有案件模型的計算器（RC 構材、基礎、鋼柱、滯洪池、圖表類） | payload → `run_calculation()` 得 `civil-design-run/1` → 繪圖工具直接讀 `payload`＋`result` | **待 D0**：`build_case()` 目前寫死四種模型，遇到其他模型直接報錯 |

選路線的規則：會進三軸交付（預算、報告）的構造物走甲，圖與數量同源；只在工作台試算的構材走乙，不為了出圖硬造一個數量模型。

走乙時，`generate()` 把完整的 run 信封寫到 `_temp/design_sections/<id>/<時間>/run.json` 交給繪圖工具；繪圖工具**不得**自己再跑一次引擎（避免兩次結果不一致）。

## 3. 階段三：繪圖工具

### 3.1 放哪裡

| 情況 | 位置 |
|---|---|
| 擋土牆、排水溝、邊坡的變體 | `tools/wall_section/make_wall_section.py` 加分支 |
| 箱涵變體 | `tools/box_section/make_box_section.py` |
| 新圖種 | `tools/<圖種>_section/make_<圖種>_section.py`（工具不得放 `_temp/`） |

### 3.2 命令列契約（`design_section.generate()` 依此呼叫，現行）

```bash
.venv/bin/python tools/<x>_section/make_<x>_section.py <輸入.json> \
  --scale auto|<N> --unit m|cm --out <輸出.dxf> [--rebar] [--project <名稱>] [--drafter <姓名>]
```

- 成功：退出碼 0 且 `--out` 檔存在。失敗：非 0，stderr 末段說得出原因。
- `--scale auto` 挑放得進 A3 可用區的最小標準比例；手選比例放不下要**明確失敗**並回報可用比例，不得偷改。
- 實際採用的比例要印在輸出裡（`generate()` 以 `_resolve_scale()` 從 log 擷取）。
- 產出後自行呼叫 `check_delivery.py`；沒過就退出非 0。
- 新工具一律提供 `--drafter`（`box_section` 目前缺，見工作計劃書 D13）。

### 3.3 製圖規定（全部現行，不得自創）

- 圖層用 `drawing_rules.add_plot_layer()` 建；顏色 1～8 對固定線粗；出圖型式 `monochrome.ctb`。
- 文字樣式 `TOMO`（`gbenor.shx`＋`CHINA1.SHX`），不留 `Standard`。
- `$INSUNITS=6`、`$MEASUREMENT=1`；A3 圖框與標題欄沿用樣板。
- 右欄文字寬度比 `est_width()` 再保守一成；圖例起點不晚於 `CX+12`（`AGENTS.md` §6）。
- 動手前讀 `本項目的出圖規定(不定期新增).md` 與 `docs/出圖樣式與線粗.md`。

## 4. 階段四：登錄能力

在 `tools/design/design_section.py` 的 `CAPABILITIES` 加一筆（現行）：

```python
"rc_beam": {
    "title": "梁斷面配筋圖（B-01）",
    "tool": "rc_section",          # → tools/rc_section/make_rc_section.py
    "model": "rc_beam",
    "sheets": [{"suffix": "B-01_梁斷面配筋圖", "rebar": True}],
},
```

- 前端由 `/api/design/section/capabilities` 自動取得，**不必改 HTML**。
- 走路線甲者，另在 `build_case()` 補該模型的取值函式（`_<model>_values()` 回 `(values, missing)`）。
- 不出圖者登錄 `not_applicable`＋理由（待 D0 提供欄位）。

## 5. 階段五：驗證（依序，前一步沒過不往下）

```bash
# 1. 只出 DXF（DG3、DG4）
.venv/bin/python tools/design/design_section.py <id> _temp/<主題>/payload.json --scale auto --no-publish

# 2. 圖／數對帳（DG5，適用者）
.venv/bin/python tools/takeoff/dxf_takeoff.py <圖.dxf> --case <case.json> [--rebar]

# 3. 完整出圖 DWG＋PDF（DG6）
.venv/bin/python tools/design/design_section.py <id> _temp/<主題>/payload.json --scale auto

# 4. PDF 轉 PNG 目視（DG7），再交使用者看

# 5. 全體自測與回歸（DG8）
.venv/bin/python tools/selftest/run_all.py
```

出圖失敗先看 `_temp/design_sections/<id>/<時間>/<圖名>_log.txt`。

## 5.1 獨立驗算（DG9）

```bash
.venv/bin/python tools/crosscheck/ocss_crosscheck.py probe     # 先確認連得上；401 多半是連到上游版
.venv/bin/python tools/crosscheck/ocss_crosscheck.py checks    # 跑對照案例
```

- 對照案例放 `tools/crosscheck/checks/`；比對的是**會畫到圖上的數值**（尺寸檢核的 FS、需求鋼筋量、選配間距的依據）。
- 兩個不報錯的單位陷阱必查：分數次方污染單位、單位不自動收斂（`ocss_client.unit_warnings()` 已偵測）。
- **差異要查到原因**：修引擎、回報模板問題、或登錄為可解釋差異並寫理由，三選一。不得為了通過而放寬容差。
- 不動使用者開著的 OCSS 專案：批次驗算用無狀態的 `calc_evaluate`；要套模板（`sheet_add`）先請使用者開空白專案。
- 模板對照（非手寫公式）的工具支援待工作計劃書 X1。

## 6. 邊界測試（DG8 的一部分）

範例過了不算數，至少再測：

| 情境 | 期望 |
|---|---|
| 計算未通過的 payload | 前端按鈕停用；直接打 API 也不該拿到看似正常的圖 |
| 最小與最大合理尺寸 | `auto` 比例都放得進 A3，文字不重疊（E10） |
| 手選過小比例 | 明確失敗並回報可用比例 |
| `--unit cm` | 幾何不變，只有標註與尺寸表換單位 |
| 所有下拉選項（牆型、孔數、支承型式…） | 每個選項都出得了圖，或明確拒絕 |
| 鋼筋最密與最疏的組合 | 配筋表不溢出右欄 |

## 7. 收尾

1. `docs/工作台設計圖產線.md` §3 能力表與 §7 限制同步。
2. 工作計劃書進度欄更新。
3. 測試檔留在 `_temp/`；`out/design_sections/` 內的試跑產物不是交付物，不列入交付說明。
4. 建立語意化 commit（一個計算器或一組同類計算器一個）。
5. 回報時列：出了哪幾張、採用比例、用了哪些預設值、沒畫什麼、自評可信度（1～10）。

## 8. 常見錯誤

| 錯誤 | 後果 | 對策 |
|---|---|---|
| 繪圖端自己重算或挑鋼筋 | 圖與計算書對不上 | §2.1 鐵則 1 |
| 預設值默默畫上去 | 壁厚是假設值卻被當設計值施工 | §2.1 鐵則 2 |
| 只測範例 | 換個牆型就報錯 | §6 |
| 只看 `check_delivery` 通過 | 圖合規但讀不懂 | DG7 目視 |
| 交叉驗算有差異就調容差 | 把真錯誤蓋掉 | DG9：查到原因再處置 |
| 手選比例放不下時自動改比例 | 圖面比例與標題欄不符 | §3.2 明確失敗 |
| 對未知模型退回預設畫法 | 畫出錯的構造 | 未知型別一律報錯（同 `wall_system`） |
| 使用者在 GUI 開著同一張 DXF | 轉檔回 400「Drawing edit lock is held」 | 請使用者先關圖（`AGENTS.md` §5.1） |
