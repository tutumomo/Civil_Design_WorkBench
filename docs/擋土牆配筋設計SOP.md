# 擋土牆配筋設計 SOP（六種 RC 牆型）

> 版本：1.0（2026-11-04）
>
> 適用：重力式、半重力式、懸臂式、扶壁式、錨定式、加勁式（MSE）；
> 疊砌式（蛇籠／格籠／漿砌石／乾砌石／三明治）只做穩定，不配 RC 鋼筋。
>
> 唯一入口：`tools\design\wall_system.py` 的 `analyse()` 與 `rebar_design()`。
> 不要在不同模組各自判斷 `wall_type`，否則會出現「報告說不用配筋、預算卻算懸臂鋼筋」。
> 疊砌式是例外：它走 `block_wall.py`（不經 `wall_system.analyse()`），
> 配筋由 `design_wall_rebar()` 明示回傳 0 kg/m。
>
> 相關文件：
> [`設計計算產線.md`](設計計算產線.md) §3.6、
> [`擋土牆斷面圖產線.md`](擋土牆斷面圖產線.md)、
> [`踩坑紀錄.md`](踩坑紀錄.md) §AB。

---

## 0. 一句話

**需求 → 規範 → 穩定 → 配筋 → 數量 → 預算 → 報告 → 出圖**，八步一線；
任何一步檢核不過就停下來改斷面，不可用「先出圖再說」跳過。

---

## 1. 前置資料（缺一項就先標假設）

| 類別 | 必要欄位 | 說明 |
|---|---|---|
| 幾何 | `wall_type`、`height_m`、`length_m`、各牆型斷面尺寸 | 斷面幾何必須與穩定分析、S-01／S-02 同一份 |
| 土工 | `gamma_kn_m3`、`phi_deg`、`cohesion_kpa`、`q_allow_kpa` | 無鑽探時用假設值，報告與預算都要標「假設，待鑽探替換」 |
| 地下水 | 水位比例或 `groundwater_depth_m` | 未調查時以無水計，並在報告寫明 |
| 地震 | `kh`、`kv` | 常時與地震兩工況都要跑 |
| 載重 | 超載 `surcharge_kpa`、其他集中載重 | 擋土牆不套用箱涵的車載重；道路載重換算成超載 |
| 材料 | `fc_mpa`、`fy_mpa`、保護層 | 牆體保護層 75 mm；MSE 面版 50 mm |

---

## 2. 牆型分流（先選對引擎）

| `wall_type` | 穩定分析 | 配筋設計 | 主要構材 | 高度限制 |
|---|---|---|---|---|
| `gravity` | `retaining_wall.py` | `design_mass_wall_steel()` | 牆身名目構造筋＋底部縱筋 | 水保 §118 |
| `semigravity` | `retaining_wall.py` | `design_mass_wall_steel()` | 同上 | 水保 §118 |
| `cantilever` | `retaining_wall.py` | `design_cantilever_stem()`＋`design_base_slab()` | 牆身懸臂、趾板、踵板 | 水保 §118 |
| `counterfort` | `counterfort_wall.py` | `design_counterfort_wall_steel()` | 牆板三帶、踵板連續版、趾板懸臂、扶壁 T 梁、箍筋、繫筋 | 有效高 ≤ 10 m |
| `anchored` | `anchored_wall.py` | `design_anchored_wall_steel()` | 牆面四向筋、基腳、地錨五項檢核 | 未訂上限，依地錨設計 |
| `mse` | `mse_wall.py` | `design_mse_face_steel()` | RC 面版單向版；加勁材逐層拉斷／拉出 | 有效高 ≤ 8 m |
| `gabion`／`crib`／`masonry_wet`／`masonry_dry`／`sandwich` | `block_wall.py` | `design_block_wall_steel()` 回傳 0 | 無 RC 鋼筋 | 水保 §118 |

呼叫方式（唯一入口）：

```python
import wall_system as WS
result = WS.analyse(q, case)          # 穩定＋尺寸檢核
design = WS.rebar_design(q, result)   # 依牆型分流的配筋設計
kg_per_m = design["total_kg_per_m"]
```

---

## 3. 穩定分析（先過，再談配筋）

`WS.analyse()` 回傳的 `checks` 至少要有：

- 滑動 FS（常時 ≥ 1.5、地震 ≥ 1.1）
- 傾倒 FS（常時 ≥ 2.0、地震 ≥ 1.2）
- 合力作用點（常時落在 1/3 中段）
- 基礎承載 FS（常時 ≥ 3.0、地震 ≥ 2.0）或基底最大應力 ≤ 容許承載力

規範依據：水土保持技術規範 §119～§120；疊砌式另依 §118。

> **不通過就改斷面**：先用 `--size` 反推通過的斷面，或加地錨／加勁材；
> 不要直接把鋼筋加粗，穩定不足不是配筋能解決的。

---

## 4. 配筋設計（逐構材，不是一個公式套全部）

### 4.1 共通檢核

| 項目 | 公式／門檻 | 規範 |
|---|---|---|
| 撓曲 | `φMn ≥ Mu`；`φ=0.90`（拉力控制），`εt` 不足時依 §3.4.4 內插 | 混凝土結構設計規範 §3.4.4 |
| 剪力 | `φVc ≥ Vu`；`φ=0.75`、`Vc=0.53√fc′·bw·d`（SI） | §4.4.1.1 |
| 最小鋼筋 | `As,min = 1.4/fy·b·d`（SI，對應 kgf 版 `14/fy`） | §3.6.1 |
| 裂縫 | 服務載重下 `w ≤ 0.30 mm` | §3.4.4／常用耐久性要求 |
| 間距 | 依構材類型與鋼筋號數檢核 | §3.7.2 只管梁與單向版 |

### 4.2 各牆型構材

**懸臂式**
- 牆身：牆底為控制斷面，三角形土壓 `M = Pa·H/3`。
- 底板：趾板與踵板各以牆身為固定端之懸臂板，踵板常控制。

**扶壁式**
- 牆板：上／中／下三帶水平彎矩（扶壁處負彎、跨中正彎）＋ Huntington 鉛直彎矩。
- 踵板：以扶壁為支承之連續版，取扶壁處與跨中兩控制斷面。
- 趾板：懸臂板。
- 扶壁：豎向懸臂 T 梁；**有效深度 `d` 是水平深度 `ts + heel`，不是乘斜背傾角的斜長**。
- 箍筋：`Vu > 0.5φVc` 時依 ACI 318 配置最少剪力筋（H=8 m 案為 D13 兩肢 @600）。
- 繫筋：扶壁－牆板、扶壁－踵板各一組。

**錨定式**
- 牆面：以各排地錨與基底為支承之連續梁，四向筋依正負彎矩分開配置。
- 基腳：上下層橫向筋＋縱向分布筋；**圖上有畫的鋼筋，數量表就要有那一列**。
- 地錨：抗張材、錨碇段長、自由段長、鎖定荷重、承壓鈑下壓應力、錨頭沖剪，共五項。

**加勁式（MSE）**
- RC 面版：以加勁材層距與面版寬度較大者作單向版設計。
- 外部穩定：滑動、傾倒、偏心、承載（常時＋地震）。
- 內部穩定：逐層拉斷、拉出、錨定長度；`L ≥ 0.7H` 且 `≥ 2.4 m`、層距 ≤ 1.0 m。
- 面版只有水平筋與豎向筋，**沒有底板筋**。

---

## 5. 鋼筋量與模板（每延米）

### 5.1 損耗率

| 構造物 | 損耗率 | 說明 |
|---|---|---|
| 擋土牆（本 SOP） | **6%** | 含搭接、錨定與損耗；使用者 2026-11-04 指示 |
| 箱涵 | **6%** | 使用者指定；與擋土牆、排水溝一致（全專案 RC 鋼筋同一損耗率） |

### 5.2 已驗證數量（2026-11-04；損耗率改 6% 後重測）

| 牆型 | 案例 | 鋼筋量 kg/m | 20 m 總量 kg | 斷面積（圖／模型） | 比例 |
|---|---|---|---|---|---|
| 扶壁 H=8 m | `擋土牆8m扶壁式` | **588.18** | **11,764** | 6.36／8.824 m²/m | 1:50 |
| 錨定 H=7 m | `擋土牆7m錨定式` | **308.94** | **6,179** | 3.20／3.20 m²/m | 1:40 |
| 加勁 H=6 m | `擋土牆6m加勁式` | **48.77** | **976** | 1.20／1.20 m²/m | 1:50 |
| 懸臂 H=3 m | `擋土牆3m懸臂式` | 131.04 | 2,621 | 1.752／1.752 m²/m | 1:25 |
| 半重力 H=4 m | `擋土牆4m半重力式` | 55.34 | 1,107 | 4.484／4.484 m²/m | 1:25 |
| 重力 H=3 m | `擋土牆3m重力式` | 41.51 | 830 | 3.375／3.375 m²/m | 1:25 |

> 扶壁式的「模型斷面積 8.824」含扶壁分攤；S-01／S-02 畫的是兩扶壁間標準斷面 6.36，
> 兩者本來就不同，對帳要用 `DRAWN_SECTION_AREA_KEY`，不可拿總量比典型斷面。

### 5.3 模板

- 一般牆：正面（露出面）＋兩端端模；牆背貼土不計。
- 扶壁式：另加扶壁兩側模板。
- MSE：預鑄面版不計場鑄模板；場鑄面版才計。
- 數量鍵：`qty_models` 的 `formwork_m2`。

---

## 6. 數量 → 預算 → 報告（同一份 case.json）

1. `cases\<案名>\case.json` 的 `quantities.model` 設 `wall`。
2. 配筋量由 `case_core` 呼叫 `WS.rebar_design()` 派生：
   - `rebar_kg_per_m_design`（kg/m）
   - `rebar_kg_design`（kg，已乘牆長）
3. 預算書工項用 `qty_from: "rebar_kg_design"`、`qty_from: "formwork_m2"`，**不要在 BOQ 再打一次數量**。
4. 報告第 6／7／11 章由 `case_core._design_sections()` 派生；跑完必看
   `out\<案名>\_case\report_case.json` 的 `_derived.design_sections_error` 是否為 `None`。
5. 三軸一次跑：

```powershell
$env:PYTHONIOENCODING='utf-8'
C:\Python312\python.exe tools\case_package\case_package.py `
    "cases\擋土牆8m扶壁式\case.json" --allow-placeholder
```

> `--allow-placeholder` 只供示範案；正式案必須先填 `project.full_name` 與
> `project.agency`，否則報告軸會以 exit 4 中止（這是刻意設計）。

---

## 7. 出圖 S-01／S-02

```powershell
# S-01 標準斷面圖
C:\Python312\python.exe tools\wall_section\make_wall_section.py `
    "cases\<案名>\case.json" --scale auto --out "out\<案名>\S-01_擋土牆標準斷面圖.dxf" --publish

# S-02 配筋圖（同一份配筋設計）
C:\Python312\python.exe tools\wall_section\make_wall_section.py `
    "cases\<案名>\case.json" --scale auto --rebar `
    --out "out\<案名>\S-02_擋土牆配筋圖.dxf" --publish
```

出圖必查：

- 比例採 `drawing_rules.STANDARD_SCALES` 最小可容納者；auto 會把背填、尺寸線、
  地錨前 2 m、加勁材長 L 全部算進外廓。
- 右欄 `RY_TOP=271 mm`；再往上會讓「鋼筋圖例／配筋表」穿出圖框。
- 保護層：牆體 75 mm、MSE 面版 50 mm、排水溝 50 mm。
- 部位圖例編號要對得上：扶壁式的 6 是扶壁、錨定式的 6 是地錨、
  MSE 的 4 是基礎埋入段；7（或 MSE 的 6）是基礎開挖線。
- MSE 沒有底板，圖例不可出現「底板筋」。
- 出圖後跑 `check_delivery.py`（E1～E18），再跑 `dxf_takeoff.py` 對面積與配筋間距。

---

## 8. 六道閘門（缺一不可）

| # | 閘門 | 指令／檢查 | 通過條件 |
|---|---|---|---|
| 1 | 設計檢核 | `case_core.py check` | 0 error |
| 2 | 圖面品管 | `check_delivery.py` | E1～E18 全過 |
| 3 | 圖／數對帳 | `dxf_takeoff.py` | 斷面積差異 0.0000% |
| 4 | 配筋間距對帳 | `dxf_takeoff.py --rebar` | 圖面量到的間距與配筋表一致 |
| 5 | 報告段落注入 | `report_case.json` | `_derived.design_sections_error` 為 `None` |
| 6 | 全案回歸 | `regression.py` | 基準全部相符 |

---

## 9. 常見錯誤（都實際發生過）

| 症狀 | 根因 | 修正 |
|---|---|---|
| 扶壁主筋偏少、`d` 只有 4,023 mm | 把 `d` 當成斜背的斜長 `(ts+heel)×sinθ` | 改水平深度 `ts+heel`；H=8 m 案 d=4,515、8-D32 |
| 扶壁式圖數對帳差 27.9% | 拿含扶壁分攤的 8.824 去比兩扶壁間的 6.36 | `qty_models` 新增 `DRAWN_SECTION_AREA_KEY` |
| 錨定式圖上畫基腳筋、數量卻沒有 | 只算牆面四向筋 | 基腳 `0.0018bh` 上下層＋縱向分布筋，同步配筋表與 `spacing_candidates()` |
| 3 m 重力式 auto 選 1:20 卻出圖失敗 | 只估混凝土多邊形，沒算背填與尺寸線 | 右側餘裕 0.50→0.95 m；加勁式納入 L、錨定式納入前 2 m 地錨 |
| S-01／S-02 右欄標題被切掉 | `RY_TOP=278` 超過圖框內頂 | 改 271 mm |
| S-01 寫 D16@200、S-02 寫 D16@260 | S-01 走示意值 | S-01 也先跑同一套配筋設計，圖例取實際值 |
| MSE 圖例出現「底板筋」、保護層 75 mm | 共用一般牆型圖例 | MSE 專屬圖例；保護層 50 mm |
| 報告圖說寫「1:auto（自動）」 | `section.scale` 是 `"auto"` | 從 DXF 標題欄讀回實際 `1:N` |
| 回歸對扶壁／錨定／加勁只記 `design_error` | 只呼叫 `retaining_wall`，未走 `wall_system` | 改用 `WS.analyse`／`WS.rebar_design`，以 `unit=="FS"` 辨識安全係數 |

---

## 9B. 工作台入口（2026-11-04 補）

| 牆型 | 計算器 | 配筋顯示 |
|---|---|---|
| 重力／半重力／懸臂 | `wall_stability`「擋土牆穩定與配筋」 | 穩定與配筋**同一頁**；可設 fc′、fy、保護層、牆身／底板主筋、牆面／底部構造筋，結果含每延米鋼筋量與撓曲／剪力／裂縫檢核 |
| 扶壁／錨定／加勁 | `counterfort_wall`／`anchored_wall`／`mse_wall` | 各計算器 summary 已含配筋明細與檢核 |
| 疊砌／砌石 | `block_wall` | 明示不適用 RC 鋼筋（量為 0） |

> 自動選配（`size: true`）已把配筋納入關卡：只通過穩定但有裂縫 NG 的斷面會被淘汰，
> 回傳的是「穩定＋配筋都過」的最小斷面。

---

## 10. 快速指令

```powershell
$env:PYTHONIOENCODING='utf-8'
$py = "C:\Python312\python.exe"

# 1. 看某牆型的輸入範例
& $py tools\design\design_cli.py show counterfort_wall

# 2. 跑設計
& $py tools\design\design_cli.py run counterfort_wall _temp\cc8.json
& $py tools\design\design_cli.py show wall_stability   # 重力／半重力／懸臂（含配筋）

# 3. 三軸交付
& $py tools\case_package\case_package.py "cases\擋土牆8m扶壁式\case.json" --allow-placeholder

# 4. 測試
& $py tools\selftest\design_core_selftest.py
& $py tools\selftest\design_workbench_selftest.py
& $py tools\selftest\design_launch_check.py --all
& $py tools\selftest\regression.py
```

---

## 11. 已知限制（正式設計前必讀）

1. 土工參數多為假設值；沒有鑽探報告就不是正式設計。
2. 扶壁式牆板／踵板採連續版係數與 Huntington 簡化，非雙向版精算。
3. 錨定式的整體深層穩定不在引擎內，須另跑 `slope_stability.py`。
4. 加勁式的複合滑動與整體圓弧滑動不在引擎內，須另案檢核。
5. 疊砌式只做穩定，不配 RC 鋼筋；石材與施工品質另由規範控制。
6. 程式仍引用《混凝土結構設計規範》100.06.09 版條號；112.08.10 版條號對照待建立。
7. 地錨握裹強度須以現場試驗確認，不能只靠計算值。
