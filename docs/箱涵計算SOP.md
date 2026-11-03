# 箱涵計算 SOP（單孔／雙孔／三孔）

> 版本：1.0（2026-11-03）
>
> 適用：現場澆置 RC 箱涵，單孔、雙孔、三孔，矩形斷面，覆土完成後承受
> H-20／H-20 S-16／40T 拖車或自訂均佈車載。
>
> 不適用：預鑄箱涵、拱形／圓形涵洞、四孔以上（引擎未建構架拓樸）、
> 斜交箱涵、分期施工與三維角隅補強。上述型式須另案建模。
>
> 本 SOP 是計算流程與檢核清單，不取代技師簽認。正式設計須由依法登記之
> 土木／結構技師覆核。

---

## 0. 工具現況（2026-11-03）

| 項目 | 內容 |
|---|---|
| 引擎 | `tools\design\box_culvert.py`（版本 0.5） |
| 構架分析 | `tools\design\frame_analysis.py`（支援頂版局部均佈載重） |
| RC 配筋 | `tools\design\rc_design.py` |
| 水力 | `tools\design\culvert_hydraulics.py`＋引擎內建 Manning |
| 工作台 id | `box_culvert`（群組「箱涵」） |
| 工作台網址 | `http://127.0.0.1:8765/design`（`regs_server.py --web`） |
| CLI 自測 | `C:\Python312\python.exe tools\design\box_culvert.py --selftest`（16 項） |
| 上架檢核 | `C:\Python312\python.exe tools\selftest\design_launch_check.py box_culvert` |
| MCP | `design_show("box_culvert")` → `design_run("box_culvert", {...})` |
| 主題卡 | `tools\regs\topics.json`「箱涵」 |

檢核數（未含進口控制）：

| 孔數 | 檢核數 | 說明 |
|---|---:|---|
| 單孔 | 29 | 6 個受拉面、3 組分佈筋／軸彎、5 根桿件 |
| 雙孔 | 38 | 8 個受拉面、4 組分佈筋／軸彎、7 根桿件 |
| 三孔 | 41 | 8 個受拉面、4 組分佈筋／軸彎、9 根桿件 |

> 檢核數會隨 `inlet_type`（進口／出口控制）與地下水（抗浮）增加。
> 車載重**不列入檢核列**（沒有通過／不通過判準），由 `loads.traffic`
> 與報告摘要呈現。

---

## 1. 流程總覽

```text
Step 0 輸入幾何／材料／土工／車載／水力
  ↓
Step 1 載重（土壓、水壓、自重、車載、組合）
  ↓
Step 2 水力（滿管容量、正常水深＋出水高、進口／出口控制）
  ↓
Step 3 平面剛架（每延米、逐孔局部輪壓包絡）
  ↓
Step 4 逐面配筋（內側／外側、撓曲、裂縫、剪力、軸彎、分佈筋）
  ↓
Step 5 數量（鋼筋 6% 損耗、模板、混凝土）
  ↓
Step 6 工作台／案件／預算串接
  ↓
Step 7 驗證（引擎自測、核心、工作台、上架、全案回歸）
```

---

## 2. Step 0：輸入資料

### 2.1 幾何

| 參數 | 單位 | 說明 |
|---|---|---|
| `cell_count` | 孔 | 1～3 |
| `clear_width_m` | m | 每孔淨寬 |
| `clear_height_m` | m | 淨高 |
| `wall_thickness_m` | m | 外側牆厚 |
| `interior_wall_thickness_m` | m | 中間牆厚（單孔不使用） |
| `top_slab_thickness_m` | m | 頂版厚 |
| `bottom_slab_thickness_m` | m | 底版厚 |
| `cover_depth_m` | m | 頂版以上覆土深 `Hc` |
| `length_m` | m | 涵長 |

衍生：

- 外寬 `B_o = 2·t_w + n·B + (n−1)·t_i`
- 外高 `H_o = t_b + H + t_t`
- 混凝土斷面積 `A = B_o·H_o − n·B·H`

### 2.2 材料

| 參數 | 預設 | 說明 |
|---|---:|---|
| `fc_mpa` | 28 | 混凝土強度 |
| `fy_mpa` | 420 | 鋼筋降伏強度 |
| `concrete_unit_weight_kn_m3` | 24 | RC 單位重 |
| `cover_mm` | 50 | 主筋保護層；底版貼地澆置宜 75 mm |
| `crack_limit_mm` | 0.30 | 裂縫上限；腐蝕環境可加嚴至 0.20 |

### 2.3 土工與地下水

| 參數 | 預設 | 說明 |
|---|---:|---|
| `soil_unit_weight_kn_m3` | 18 | 覆土單位重 |
| `soil_phi_deg` | 30 | 內摩擦角（Rankine `Ka`） |
| `surcharge_kpa` | 0 | 地面均佈上載 |
| `groundwater_depth_m` | 無 | 地表下深度；有值才做抗浮 |
| `internal_water_depth_m` | 0 | 涵內水深（由底板頂起算） |

> `γ`、`φ` 是預設值，正式設計必須用鑽探報告替換。

### 2.4 車載

| `traffic_type` | 公式 | 施加方式 |
|---|---|---|
| `none` | 0 | 僅土壓／上載；會警告 |
| `h20` | `7.25(1+0.30)/[(1.065+0.707Hc)×3.30]` t/m² | 頂版均佈 |
| `h20_s16` | `n×4P/(L×W)`；`P=7.3 t`、`L=1.75Hc`（>2.43 加 4.25）、`W=(1.75+Hc)+1.8n+1.2(n−1)`；三／四車道乘 0.9／0.75 | `Hc>0.6` 均佈；`Hc≤0.6` 局部 `E=1.2+0.06s` |
| `trailer_40t` | `p=8 t`、`E=1.2+0.06s`（上限 2.1）、`Pwh=p(1+0.30)/E` | 頂版局部輪壓，逐孔移動 |
| `custom` | 使用者指定 `traffic_load_kpa` | 頂版均佈 |

| 參數 | 預設 | 說明 |
|---|---:|---|
| `traffic_lanes` | 4 | 僅 `h20_s16`，1～4 |
| `traffic_impact_factor` | 自動 | 可覆寫 0～0.5 |
| `traffic_load_kpa` | 0 | 僅 `custom` |

> **不要用 `none` 假裝已檢核。** 道路箱涵至少 H-20；市區道路常見
> H-20 S-16；重車路線用 40T 拖車。車型由道路等級與業主指定，不是由程式猜。

### 2.5 水力

| 參數 | 預設 | 說明 |
|---|---:|---|
| `design_flow_m3s` | 0 | 設計流量；0 只做容量，不做正常水深檢核 |
| `slope` | 0.005 | 涵底坡度 |
| `manning_n` | 0.014 | 混凝土糙度 |
| `freeboard_min_m` | 0.20 | 正常水深以外的最小出水高 |
| `inlet_type` | 無 | 有值才做附錄 N／O 進口／出口控制 |
| `tailwater_depth_m` | 0 | 下游水深（涵底起算） |
| `allowable_headwater_m` | 無 | 最高容許上游水深 |

---

## 3. Step 1：載重

### 3.1 側向土壓

採 Rankine 主動土壓：

```text
Ka = (1 − sinφ) / (1 + sinφ)
p(z) = Ka·γ·z
```

覆土側由地表起算；涵內側另有內水壓。地下水位以下採有效單位重
`γ' = γ − 9.81`，並加水壓。

### 3.2 自重與底版反力

- 頂版、底版、牆自重由 `γc × 斷面積` 逐桿件積分。
- 底版反力由整體垂直力平衡求得，不是平均分攤假設。

### 3.3 車載重

依第 2.4 節選型。兩個關鍵限制：

1. **局部輪壓只作用於頂版**，不另加側向土壓。
2. **H-20 S-16 低覆土（`Hc≤0.6 m`）與 40T 拖車**採局部輪壓，逐孔移動取
   彎矩／剪力包絡；不是把輪載整片均佈到整個頂版。

> `tools.excel\箱涵(單孔、雙孔).xls` 的 40T 工作表把 `Pwh` 直接當頂版
> 整片均佈（總載重約為輪載的 span/E 倍，偏保守）。本引擎改以同強度
> `7.2222 t/m²` 作用於寬度 `E`，總輪載與實際相符。若要完全復刻工作簿，
> 把 `traffic_type` 設 `custom` 並直接輸入該 kPa。

### 3.4 載重組合

目前所有載重共用 `load_factor`（預設 1.7），**尚未拆分**
`1.2D + 1.6L` 或 AASHTO `1.25DC + 1.75LL`。正式設計須依採用規範重算
組合；本工具的檢核是「同一放大係數下的構架內力包絡」。

---

## 4. Step 2：水力

### 4.1 滿管容量（上限）

```text
A  = n · B · H
Pw = n · (B + 2H)
R  = A / Pw
Qcap = (1/n) · A · R^(2/3) · S^(1/2)
```

满管容量只是上限，不代表設計流量下不會溢流。

### 4.2 正常水深與出水高

由設計流量反算正常水深 `y_n`，檢核：

```text
y_n + freeboard_min_m ≤ clear_height_m
```

### 4.3 進口／出口控制

有 `inlet_type` 時，依公路排水設計規範附錄 N／O：

- 進口控制（HDS-5 迴歸式）與出口控制取較大上游水深。
- 檢核 `HW/D` 與 `HW ≤ allowable_headwater_m`。
- `HW/D` 原文「宜儘量控制在 1.5 以上」依水理意義判讀為「以下」，
  程式會警告；可用 `hw_d_limit` 調整。

---

## 5. Step 3：平面剛架分析

- 每延米涵長一個二維剛架；節點在牆中心線與版中心線交點。
- 每孔一個頂版桿件、一個底版桿件；每道牆一個垂直桿件。
- 只约束一個節點的三個自由度，移除剛體模態；其餘由平衡求解。
- 局部輪壓以 `wy_patch`／`wy_patch_start`／`wy_patch_end` 施加，
  一致性節點載重與彎矩圖都會在載重邊界切段。
- 多孔時逐一將輪壓放在各孔頂版，取各桿件內力包絡。

輸出：`frame`（節點、桿件、變位）、`members`（各桿件彎矩／剪力／軸力）。

---

## 6. Step 4：逐面配筋

### 6.1 分面規則

| 構材 | 面 | 取用彎矩 |
|---|---|---|
| 頂版 | 外側（覆土側） | 負彎矩（支承處） |
| 頂版 | 內側（涵內側） | 正彎矩（跨中） |
| 底版 | 外側（基礎土側） | 正彎矩（支承處） |
| 底版 | 內側（涵內側） | 負彎矩（跨中） |
| 外側牆 | 外側（背土側） | 支承處彎矩 |
| 外側牆 | 內側（涵內側） | 牆中彎矩 |
| 中間牆 | 左面 | 負彎矩面 |
| 中間牆 | 右面 | 正彎矩面 |

> 不可用「兩個方向取較小容量」偷懶；上下配筋不同時，會把受拉面在
> 配筋較多側的工況誤判為 NG。

### 6.2 撓曲、裂縫與最小鋼筋

每個受拉面依 `rc_design`：

1. 撓曲 `φMn ≥ Mu`。
2. 裂縫寬度 `w ≤ crack_limit_mm`（預設 0.30 mm）。
3. 最小鋼筋 `As,min`。
4. 選筋（`bar_preference`：`auto`／`fine`／`coarse`）與間距。

### 6.3 剪力

每根桿件檢核 `φVn ≥ Vu`；`Vc = 0.53√fc′·bw·d`（100 年版 §4.4.1.1，
程式用 MPa）。

### 6.4 軸彎互制

以彎矩最大面為受拉面、另一面為壓力面建 `layer_areas`，用
`column_interaction_capacity()` 檢核 `Pu`／`Mu`。這是單軸、兩層鋼筋的
初步檢核，雙向彎矩與二階效應未納入。

### 6.5 縱向分佈筋

- 版：`0.0018·b·h`，分置兩面。
- 牆：`0.0020·b·h`，分置兩面。

> 這裡是「總量分置兩面」，不是每面都配一份總量。舊 Excel 常每面同量
> 配置，照抄會多一倍。

---

## 7. Step 5：數量

### 7.1 鋼筋

依理想化排筋計數：

- 橫向主筋：`ceil(L / spacing)` 支，長度取構材外寬／外高。
- 縱向分佈筋：`ceil(外寬或外高 / spacing)` 支，長度取涵長。
- 中間牆依孔數乘 `(n−1)`；外側牆乘 2（兩側）。

```text
淨鋼筋量 = Σ(支數 × 長度 × 單位重)
總鋼筋量 = 淨鋼筋量 × (1 + 6%)
```

`6%` 含搭接、錨定與裁剪損耗，可用 `rebar_loss_rate` 覆寫（0～0.5）。

> `rc_design.LAP_ALLOWANCE = 12%` 仍供擋土牆／排水溝使用，**箱涵不共用**。

### 7.2 模板

只計涵內側：

```text
每延米 m²/m = n·B（頂版底面）
            + n·B（底板頂面）
            + 2n·H（外牆內面＋中牆兩面）
            = 2n(B + H)

總量 m² = 每延米 × L + 2A（兩端端模）
```

外側貼土面、施工縫、開口、翼牆不計。若外側需雙面模板或免拆模板，須另加。

### 7.3 混凝土

```text
每延米 m³/m = A = B_o·H_o − n·B·H
總量 m³     = A × L
```

### 7.4 輸出欄位

| 欄位 | 單位 | 說明 |
|---|---|---|
| `quantities.rebar_kg_per_m_net` | kg/m | 淨鋼筋量（未含損耗） |
| `quantities.rebar_kg_per_m` | kg/m | 含 6% 損耗 |
| `quantities.rebar_kg_total` | kg | 全長 |
| `quantities.rebar_ton` | t | 全長 |
| `quantities.rebar_loss_rate` | – | 損耗率 |
| `quantities.rebar_kg_per_m3` | kg/m³ | 含鋼量 |
| `quantities.formwork_m2_per_m` | m²/m | 每延米模板 |
| `quantities.formwork_m2` | m² | 含兩端端模 |
| `quantities.formwork_end_faces_m2` | m² | 兩端端模 |
| `quantities.formwork_breakdown` | – | 頂版底面／底板頂面／牆內面 |

---

## 8. Step 6：工作台與案件串接

### 8.1 工作台

`design_api._example_box_culvert()` 提供範例；`_box_culvert_field_rules()`
提供下拉與中文標籤。新增欄位時：

1. `field_rules` 一定要有 `label`（G8）。
2. 列舉值一律 `type:"select"`（G6）。
3. `example` 要能直接跑過（G3）。
4. 純資訊不要放進 `checks`；放 `summary`／`result`，或至少
   `severity:"advisory"` 且有 `unit`。

### 8.2 案件數量模型

`tools\case_package\qty_models.py` 的 `box_culvert` 模型提供：

- `rebar_kg`：`rebar_ratio_kg_m3 × 混凝土體積`（假設值，預設 90 kg/m³）。
- `formwork_m2`：與引擎相同的 `2n(B+H)·L + 2A`。
- `rebar_kg_design`／`formwork_m2_design`：由 `case_core.quantity_context()`
  呼叫引擎後寫入，供預算選用。

案件可在 `boq.items` 用 `qty_from` 指向設計值：

```json
{"name": "鋼筋及加工組立", "qty_from": "rebar_kg_design", "unit": "kg"}
```

> 設計值與假設值差超過 25% 時，`case_core.consistency()` 會警告。
> 不要為了讓預算好看而默默改回假設值。

---

## 9. Step 7：驗證清單

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = 'C:\Python312\python.exe'

& $PY tools\design\box_culvert.py --selftest                      # 16/16
& $PY tools\selftest\design_core_selftest.py                      # 142 tests OK
& $PY tools\selftest\design_workbench_selftest.py                 # 0 failure
& $PY tools\selftest\design_launch_check.py box_culvert           # 0 FAIL
& $PY tools\selftest\regression.py                                # 基準相符
```

驗收門檻：

- 引擎自測 16/16。
- 核心 142 tests OK。
- 工作台 0 failure。
- 上架檢核 0 FAIL（WARN 需逐項說明）。
- 回歸基準全部相符；`--update` 只用在**刻意**改變設計值時，且回報要寫
  明前後差異與原因。

---

## 10. 常見錯誤

| 症狀 | 原因 | 修法 |
|---|---|---|
| 以為「沒算車載」 | 舊版固定內建 10 kPa，工作台看不到 | 改用 `traffic_type`；預設 H-20 |
| 車載加了兩次 | `custom` 與 H-20 同時給 | `traffic_load_kpa` 只在 `custom` 使用 |
| 低覆土卻用整片均佈 | 沒走局部輪壓分支 | `Hc≤0.6` 會自動走 `E=1.2+0.06s` |
| 中間牆只配一面 | 把中間牆當外牆 | 中間牆左／右面各一組，另加兩面分佈筋 |
| 分佈筋多一倍 | 把 `0.0018bh` 當「每面」 | 那是總量，分置兩面 |
| 鋼筋量突然少 5% | 有人把損耗從 12% 改成 6% | 確認是刻意變更；回歸 baseline 要同步 |
| 模板少算頂版底面 | 只算 `n(2H+B)` | 正確是 `2n(B+H)` |
| 上架 G4 WARN「缺 limit」 | 把資訊列放進 `checks` | 移到 `summary`／`result`，或標 `advisory` |
| 回歸基準不符就按 `--update` | 沒確認是否為刻意變更 | 先列差異、問清楚，再更新 |
| 工作台表單還是舊的 | `design_api` 被 server 快取 | 重啟 `regs_server.py --web` |

---

## 11. 限制與待辦

1. 未含三維角隅補強、施工縫、開口補強、錨定／搭接長度細節與正式配筋詳圖。
2. 鋼筋量是排筋概估，不是裁剪表；正式數量須依配筋圖重算。
3. 土工參數須以鑽探報告替換；`none` 不等於已檢核。
4. 軸彎互制為單軸、兩層鋼筋；雙向彎矩、剪力牆行為、地震組合、二階效應未納入。
5. 保護層採單一 `cover_mm`；底版貼地澆置宜 75 mm。
6. 車載與其他載重共用 `load_factor`，未拆分靜／活載因數。
7. 模板只計涵內側與兩端端模；外側貼土面、施工縫、翼牆不計。
8. 進口控制採 HDS-5 迴歸式，與附錄 N 線解圖約有 5～8% 差異；沖刷深度未檢核。
9. 多孔假設各孔同尺寸、流量平均分配。

---

## 附錄 A：Excel 對照

| 車型 | 工作簿 | 公式 | 對帳值 |
|---|---|---|---|
| H-20 | `箱涵(單孔、雙孔、四孔).xls` | `7.25(1+0.30)/[(1.065+0.707Hc)×3.30]` | `Hc=0` → 2.6817 t/m²＝26.30 kPa |
| H-20 S-16 | `箱涵(雙孔、三孔).xls` | `n×4P/(L×W)`；`L=1.75Hc`、`W=(1.75+Hc)+1.8n+1.2(n−1)` | `Hc=2.0`、四車道 → 16×7.3/(3.5×10.9125)＝3.0581 t/m²＝29.99 kPa |
| 40T 拖車 | `箱涵(單孔、雙孔).xls` | `p=40×0.4/2=8 t`；`E=1.2+0.06s`；`Pwh=p(1+0.30)/E` | `s=4.0` → `E=1.44`、7.2222 t/m²＝70.82 kPa |

驗證方式：用 `xlrd` 逐格 dump `B74～B94`（雙孔、三孔）與 `B74～B79`、
`B86`（單孔修2），確認**數值**而不是只看文字標籤。工作簿的文字標籤曾
寫 `P*(1+0.3)/E`，但實際儲存格用 `1.2`（衝擊 0.2）；以數值為準。

---

## 附錄 B：輸出欄位字典

| 路徑 | 說明 |
|---|---|
| `loads.traffic_type` | `none`／`h20`／`h20_s16`／`trailer_40t`／`custom` |
| `loads.traffic_label` | 中文車型名稱 |
| `loads.traffic_equivalent_kpa` | 換算均佈（含局部輪壓分攤） |
| `loads.traffic_patch_total_kn_m` | 局部輪壓每延米合力 |
| `loads.traffic` | 完整車載細節（`details` 含公式與依據） |
| `reinforcement.elements` | 每個受拉面的筋號、間距、As、φMn、裂縫 |
| `reinforcement.distribution` | 縱向分佈筋 |
| `reinforcement.axial_flexure` | 軸彎互制 |
| `reinforcement.quantity` | 鋼筋排筋明細、淨量、總量、損耗率 |
| `quantities.formwork_breakdown` | 模板分項 |

---

## 附錄 C：與工作區工具鏈的接法

```powershell
# 1. 取輸入範例
C:\Python312\python.exe tools\design\design_cli.py show box_culvert

# 2. 單次計算（JSON）
C:\Python312\python.exe tools\design\design_cli.py run box_culvert payload.json --format text

# 3. 案件三軸（設計圖＋預算書＋報告）
C:\Python312\python.exe tools\case_package\case_package.py cases\箱涵三孔測試\case.json
```

案件主檔的 `culvert` 段可放 `traffic_type`、`traffic_lanes`、
`rebar_loss_rate`、`groundwater_depth_m`、`allowable_bearing_kpa`；
`quantities.model` 用 `box_culvert`。
