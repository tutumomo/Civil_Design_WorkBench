# 擋土牆安定分析 Excel 消化與整併建議

> 對象：`tools.excel\擋土牆安定分析.mod.xls`
> 日期：2026-10-29
> 性質：唯讀逆向分析、整併設計；本文完成前未修改原工作表與既有設計工具
> 參考案例：`data\reference\擋土牆\legacy_semigravity_H4.5.json`

---

## 1. 結論先行

這份檔案不是「一份擋土牆公式」，而是**三套舊版擋土牆計算範本＋VBA 操作介面**：

1. 重力式：`GInput` → `重力式擋土牆` → `GFS`
2. 懸臂式：`RTInput` → `懸臂式擋土牆` → `RTFS`
3. 半重力式：`SGInput` → `半重力式擋土牆` → `SGFS`

其中真正有完整計算鏈的是三個「擋土牆」計算頁；`*Input` 是舊介面，`*FS` 是結果摘要，VBA 巨集負責把儲存格數值反覆改小，直到檢核不過為止。這種「最佳化」只是固定比例試誤，不是嚴謹的最佳化演算法。

**建議的整併方式不是解析 Excel 公式，而是把計算核心重寫成 Python，Excel 只留作歷史對帳基準。**

建議優先順序：

1. 先建立共用的牆體幾何模組，避免半重力式幾何散落在穩定、數量、鋼筋、畫圖四處。
2. 先把主動土壓力、被動土壓力、水壓、超載、地震增量做成獨立的 `earth_pressure.py`。
3. 擴充 `retaining_wall.py`，加入 `semigravity` 與可選的水壓、超載、斜背填、止滑榫、被動土壓。
4. 以本文附的 `H=4.5 m` 半重力式舊案例做第一個數值回歸測試。
5. 數值核心對上後，才接 `qty_models.py`、`case_new.py`、`make_wall_section.py`、報告與配筋圖。

---

## 2. 工作簿盤點

### 2.1 工作表結構

| 群組 | 輸入頁 | 計算頁 | 結果頁 | 用途 |
|---|---|---|---|---|
| 重力式 | `GInput` | `重力式擋土牆` | `GFS` | 重力式梯形牆 |
| 懸臂式 | `RTInput` | `懸臂式擋土牆` | `RTFS` | 薄牆＋底板 |
| 半重力式 | `SGInput` | `半重力式擋土牆` | `SGFS` | 厚牆身＋基礎＋可選止滑榫 |

工作簿另含 `upwall` 封面、VBA 表單與數個隱藏／介面工作表。檔案大小約 1.29 MB，含 VBA 專案。

### 2.2 VBA 模組

| 模組 | 功能 |
|---|---|
| `按鈕控制` | 介面按鈕與表單控制 |
| `重力式建議模組` | 重力式尺寸試誤 |
| `懸臂式建議模組` | 懸臂式尺寸試誤 |
| `半重力式建議模組` | 半重力式尺寸試誤 |
| `確定取消按鈕` | 表單確認／取消 |

巨集不是數值核心。它只反覆修改 `f`、`S1`、`S2`、`B3`、止滑榫寬度等儲存格，再讀取 `*FS` 頁的 `O.K. / N.G.` 文字。這種做法有兩個限制：

- 只會以固定 5% 步長往一個方向縮小，可能停在局部邊界，不能宣稱全域最佳。
- 巨集依賴 Excel、表單與儲存格位址，不適合當成可重複呼叫的工程 API。

---

## 3. 三套計算頁實際處理的內容

三個計算頁的核心邏輯相近，但幾何與構材設計不同。

### 3.1 共同輸入

| 類別 | 舊符號 | 意義 |
|---|---|---|
| 幾何 | `H` | 牆身高度 |
| 幾何 | `H0` | 牆頂額外高度／背填斜面高度 |
| 幾何 | `Hw` | 牆背後地下水位高 |
| 幾何 | `n` | 牆頂填土坡度 `n:1` |
| 幾何 | `D` | 牆趾處覆土深 |
| 幾何 | `d` | 基腳厚度 |
| 幾何 | `b` | 止滑榫厚度 |
| 幾何 | `B` | 牆身底面寬度 |
| 幾何 | `f` | 牆趾突出長度 |
| 幾何 | `a` | 止滑榫寬度 |
| 幾何 | `S1` | 牆面坡度 `1:S1` |
| 幾何 | `S2` | 牆背坡度 `1:S2` |
| 幾何 | `S3` | 牆頂寬 |
| 載重 | `q` | 牆頂超載 |
| 土壤 | `c, f, g` | 基礎土壤凝聚力、摩擦角、單位重 |
| 背填 | `cb, fb, gb` | 背填土凝聚力、摩擦角、單位重 |
| 地震 | `Kh, Kv` | 水平／垂直地震係數 |
| 材料 | `f'c, fy` | 混凝土與鋼筋強度，舊單位 `kg/cm²` |

### 3.2 主動土壓力

舊計算頁不是只用一個 Rankine 公式，而是用**土楔試誤法**：

- 以每 1 度或 2 度為間隔搜尋可能破裂面。
- 對每個土楔計算土重、超載、水壓、地震慣性力與牆背摩擦。
- 取最大主動土壓力作為 `Pa`。
- 再依牆背摩擦角與填土坡度分解成水平 `Pah` 與垂直 `Pav`。

牆背摩擦角在舊公式中採 `δ = 2φ/3`。這比現行 `retaining_wall.py` 的單純 Rankine 水平壓力完整，但也更難驗證；重寫時應保留中間值與搜尋範圍，不能只回傳最後一個 `FS`。

### 3.3 被動土壓力

舊計算頁在前趾覆土深度 `D` 與止滑榫厚度 `b` 的範圍內，採 Rankine 被動土壓力：

```text
Kp = (1 + sin φ) / (1 - sin φ)
Pp = 0.5 γ (D + b)^2 Kp + 2 c sqrt(Kp) (D + b)
```

若止滑榫為零，`b=0`，被動土壓力仍會由前趾覆土提供。這一點是現行工具沒有的。

### 3.4 水壓力、上浮力與超載

舊頁面包含：

- 牆背水壓力
- 牆面水壓力
- 基礎上浮力
- 牆頂超載造成的側向壓力
- 地震時的水壓力與額外主動土壓力增量

本次工作簿內建的半重力式計算案例剛好 `Hw=0、q=0`，所以這些分支在該案例中為零；但欄位與公式確實存在，不能因為這個案例為零就省略。

### 3.5 穩定檢核

舊頁面執行：

- 傾倒：抵抗力矩／傾倒力矩
- 滑動：

```text
Fs = ((2/3) c B + ΣV tan(2φ/3) + Pp) / ΣH
```

- 合力作用點：由淨彎矩／總垂直力求 `d`
- 基礎承載：Meyerhof 公式，含 `Nc、Nq、Nr` 及形狀、深度、傾斜修正
- 常時與地震兩種工況

舊頁面的安全係數設定（計算頁）為：

| 檢核 | 常時 | 地震 |
|---|---:|---:|
| 傾倒 | 2.0 | 1.5 |
| 滑動 | 1.5 | 1.2 |
| 支承力 | 3.0 | 2.0 |

這些數值與《水土保持技術規範》第 120 條的常時／地震要求一致；但 `*Input` 頁仍寫著舊值 `1.5/1.2、1.3/1.1`，**不可把 Input 頁當成規範來源**。

### 3.6 構材設計

舊計算頁另含：

- 牆身十等分撓曲與剪力檢核
- 趾板五等分撓曲與剪力檢核
- 踵板五等分撓曲與剪力檢核
- 止滑榫剪力與鋼筋檢核
- 舊式 ACI 邏輯：
  - `Vc = 0.53 sqrt(f'c) b d`（kgf/cm²）
  - `ρmin = 14 / fy`
  - 最大鋼筋比 `0.75 × 0.85 × β1 × f'c / fy × 6120/(6120+fy)`

這些公式的「概念」可參考，但不應直接搬進新版 `rc_design.py`。本專案已改用 SI 單位、`φ` 依淨拉應變判定、最大鋼筋間距與新版混凝土規範對帳；直接移植舊公式會讓專案退回舊版邏輯。

---

## 4. 最重要的資料品質問題

### 4.1 Input 頁與計算頁不同步

這是本工作簿最危險的地方。實際儲存格值如下：

| 牆型 | Input 頁 | 計算頁 | 判定 |
|---|---|---|---|
| 重力式 | `H=2.7 m`、`B=2.7 m` | `H=3.5 m`、`B=2.14 m` | **不同步** |
| 懸臂式 | `H=2.8 m`、`B=1.7 m` | `H=2.8 m`、`B=1.7 m` | 同步 |
| 半重力式 | `H=3.5 m`、`B=2.14 m`、`Hw=1.6 m`、`q=0.5 T/m²` | `H=4.5 m`、`B=2.5 m`、`Hw=0`、`q=0` | **不同步** |

此外，`GInput` 與 `SGInput` 的土壤參數、`f'c` 也可能和計算頁不同。**任何未來要匯入的案例，都必須先讀「計算頁」的 `C30:C43、D12:D23`，不能讀 Input 頁。**

### 4.2 半重力式參考案例超過規範原則上限

計算頁的半重力式案例是 `H=4.5 m`。依《水土保持技術規範》第 118 條，半重力式擋土牆有效高在 **4 m 以下為原則**；超過 4 m 者，須由專業技師分析安全無虞。

因此：

- 這個案例可以當「數值引擎回歸基準」。
- 不能當成「4.5 m 半重力式標準圖可直接複製」的依據。
- 若未來案件真的要用 4.5 m 半重力式，報告必須明確標示第 118 條但書與技師覆核。

### 4.3 `#DIV/0!` 的 COM 值

舊工作簿的錯誤值經 Excel COM 讀取時可能出現 `-2146826281`，不是有效數字。匯入器或回歸測試必須把它視為錯誤／缺值，不能參與比較。

### 4.4 單位不一致

舊工作簿使用：

- `T`、`T/m`、`T/m²`
- `kg/cm²`
- `cm` 與 `m` 混用

本專案使用：

- `kN`、`kN/m`、`kN/m²`
- `MPa`
- `m`

換算基準：

| 舊單位 | SI |
|---|---:|
| `1 T` | `9.80665 kN` |
| `1 T/m` | `9.80665 kN/m` |
| `1 T/m²` | `9.80665 kN/m²` |
| `1 T/m³` | `9.80665 kN/m³` |
| `1 kgf/cm²` | `0.0980665 MPa` |

---

## 5. 可用的舊案例基準

半重力式計算頁內建案例（不是 `SGInput` 頁）：

### 5.1 幾何與材料

| 項目 | 舊值 | SI 換算 |
|---|---:|---:|
| `H` | 4.5 m | 4.5 m |
| `S3` | 0.3 m | 0.3 m |
| `D` | 1.5 m | 1.5 m |
| `d` | 0.8 m | 0.8 m |
| `B` | 2.5 m | 2.5 m |
| `f` | 0.5 m | 0.5 m |
| `S1` | 0.3 | 0.3 |
| `S2` | 0 | 0 |
| `Hw` | 0 | 0 |
| `q` | 0 | 0 |
| 基礎土壤 `c` | 0 | 0 |
| 基礎土壤 `φ` | 32° | 32° |
| 基礎土壤 `γ` | 1.8 T/m³ | 17.652 kN/m³ |
| 背填土 `c` | 0 | 0 |
| 背填土 `φ` | 38° | 38° |
| 背填土 `γ` | 1.7 T/m³ | 16.672 kN/m³ |
| `Kh` | 0.15 | 0.15 |
| `Kv` | 0 | 0 |
| `f'c` | 280 kg/cm² | 27.459 MPa |
| `fy` | 2800 kg/cm² | 274.586 MPa |

> 數值換算採用 `1 T = 9.80665 kN`；文件中的四捨五入值與 JSON fixture 可能差在小數末位。

### 5.2 舊計算結果

| 項目 | 常時 | 地震 |
|---|---:|---:|
| 傾倒 FS | 4.141326 | 1.903262 |
| 滑動 FS | 3.647391 | 1.857732 |
| 承載 FS | 9.513847 | 5.015422 |
| 牆趾最大基底應力 | 8.135678 T/m² | 14.517141 T/m² |
| 牆跟最小基底應力 | 3.559416 T/m² | 0 T/m² |
| 合力距牆趾 | 1.086959 m | 0.702612 m |
| 極限承載力 | 77.401595 T/m² | 72.809589 T/m² |
| 混凝土重量 | 12.3924 T/m | 同左 |

其他中間值：

| 項目 | 值 |
|---|---:|
| 主動土壓力 `Pa` | 3.731077 T/m |
| 水平分量 `Pah` | 3.372273 T/m |
| 垂直分量 `Pav` | 1.596467 T/m |
| 地震主動土壓增量 | 1.591566 T/m |
| 被動土壓力 `Pp` | 6.590541 T/m |

這個案例的完整可機讀版本見：

`data\reference\擋土牆\legacy_semigravity_H4.5.json`

---

## 6. 舊符號 → 新架構的建議映射

### 6.1 幾何

不建議把半重力式硬套成現有的：

```text
wall_type = "gravity"
stem_thickness_m
base_width_m
base_thickness_m
```

因為半重力式至少需要以下獨立參數：

| 新鍵名（建議） | 舊符號 | 說明 |
|---|---|---|
| `height_m` | `H` | 牆高 |
| `top_width_m` | `S3` | 牆頂寬 |
| `front_batter_ratio` | `S1` | 牆面坡度 `1:S1` |
| `back_batter_ratio` | `S2` | 牆背坡度 `1:S2` |
| `base_width_m` | `B` | 基腳總寬 |
| `base_thickness_m` | `d` | 基腳厚 |
| `toe_projection_m` | `f` | 牆趾突出 |
| `toe_soil_depth_m` | `D` | 牆趾覆土深 |
| `extra_height_m` | `H0` | 牆頂額外高度 |
| `backfill_slope_n` | `n` | 牆頂填土坡度 |
| `shear_key_width_m` | `a` | 止滑榫寬 |
| `shear_key_depth_m` | `b` | 止滑榫厚／深 |
| `groundwater_back_m` | `Hw` | 牆背水位 |

`heel_width`、`stem_bottom_width`、`section_area_m2_per_m` 應由幾何模組推導，不建議再由使用者手填，避免和 `B、f、S1、S2、S3` 衝突。

### 6.2 土壤與載重

建議把單一 `soil` 拆成：

```json
{
  "foundation_soil": {
    "c_kpa": 0,
    "phi_deg": 32,
    "gamma_kn_m3": 17.652
  },
  "backfill": {
    "c_kpa": 0,
    "phi_deg": 38,
    "gamma_kn_m3": 16.672
  },
  "surcharge_kpa": 0,
  "water": {
    "back_head_m": 0,
    "front_head_m": 0
  },
  "seismic": {
    "kh": 0.15,
    "kv": 0
  }
}
```

保留舊 `soil` 欄位作相容層，讓既有案件不用立刻改寫；新案件才使用 `foundation_soil`／`backfill`。

---

## 7. 與現行工具的差距

| 模組 | 現況 | 半重力式／舊 Excel 缺口 |
|---|---|---|
| `tools\design\retaining_wall.py` | 支援 `gravity`、`cantilever`；簡化 Rankine；地震只加 `W×Kh` | 無 `semigravity`、無水壓、超載、斜背填、垂直土壓分量、被動土壓、止滑榫、試誤土楔 |
| `tools\design\rc_design.py` | 已有牆身、底板、渠道配筋與新版規範對帳 | 尚未吃半重力式完整幾何與趾／踵板彎矩 |
| `tools\case_package\qty_models.py` | 只有 `gravity`／`cantilever` 斷面積公式 | 無法表達 `S1/S2/S3/D/d/f` 的半重力式斷面 |
| `tools\case_package\case_new.py` | `--wall-type` 只有 `gravity`／`cantilever` | 不能直接建立半重力式案件 |
| `tools\wall_section\make_wall_section.py` | 有重力式、懸臂式、排水溝 | 無半重力式斷面與止滑榫 |
| `tools\selftest\regression.py` | 現有五案回歸 | 無舊 Excel 的數值金標準 |

**重要：不能把半重力式直接改名成 `gravity` 就交給現有工具。**

`gravity` 的梯形断面與半重力式的「牆身＋基腳＋趾板＋踵板＋可選止滑榫」不是同一個幾何，會同時算錯混凝土量、自重、形心、穩定與鋼筋。

---

## 8. 建議的整併架構

### 8.1 新增 `tools\design\wall_geometry.py`

目的：**所有牆型幾何只在一個地方定義。**

建議 API：

```python
geom = wall_geometry.parse(q)
geom.polygon()              # 斷面多邊形
geom.area_m2_per_m()
geom.centroid()
geom.key_points()           # 牆趾、牆跟、牆頂、基腳、止滑榫
geom.validate()             # 幾何衝突與負尺寸檢查
```

支援：

- `gravity`
- `cantilever`
- `semigravity`

下游共用：

- `retaining_wall.py`：自重、形心、力臂
- `qty_models.py`／`case_core.py`：斷面積與數量
- `rc_design.py`：牆身、趾板、踵板控制斷面
- `make_wall_section.py`：圖面幾何
- `dxf_takeoff.py`：圖／數對帳

這樣做的好處是：以後新增「扶壁式」或「三明治式」時，只需要新增一種幾何與其構材規則，不必在五個檔案各改一次。

### 8.2 新增 `tools\design\earth_pressure.py`

建議將土壓力從穩定分析中拆出：

```python
active = earth_pressure.active_wedge(
    height_m=...,
    backfill=...,
    surcharge_kpa=...,
    groundwater_m=...,
    wall_batter=...,
    delta_ratio=2.0/3.0,
    kh=...,
    kv=...,
)
passive = earth_pressure.rankine_passive(...)
water = earth_pressure.hydrostatic(...)
```

回傳值至少包含：

- 水平力、垂直力
- 作用高度
- 對牆趾的力矩
- 搜尋到的破裂面角度
- 使用的 `Ka` 或等值土壓係數
- 是否受超載、水壓、地震控制

### 8.3 擴充 `retaining_wall.py`

保留既有 `analyse(q, soil=None, seismic=None)` 介面，新增：

- `wall_type="semigravity"`
- `q["wall_geometry"]` 或新幾何鍵
- `q["foundation_soil"]`、`q["backfill"]`
- `q["water"]`
- `q["surcharge_kpa"]`
- `q["shear_key"]`
- `q["passive_resistance"]`

輸出不要只給 `pass`，還要給每個檢核的 `value / limit / ok / basis`，以及 `legacy_comparison` 區塊，讓回歸測試可以逐項比對。

### 8.4 接入數量和案件 JSON

建議 `case.json` 新增：

```json
{
  "quantities": {
    "model": "wall",
    "values": {
      "wall_type": "semigravity",
      "length_m": 40,
      "height_m": 4.5,
      "top_width_m": 0.3,
      "front_batter_ratio": 0.3,
      "back_batter_ratio": 0.0,
      "base_width_m": 2.5,
      "base_thickness_m": 0.8,
      "toe_projection_m": 0.5,
      "toe_soil_depth_m": 1.5
    }
  }
}
```

`qty_models.py` 不應再用單一 `if wall_type == 'gravity' else ...` 猜公式。建議由 `wall_geometry.py` 先算出：

- `section_area_m2_per_m`
- `stem_bottom_width_m`
- `heel_width_m`
- `perimeter_m`
- `toe_area_m2`
- `heel_area_m2`

再把結果寫回 `quantities.values`，由既有 `qty_models` 的 `verify_tol_pct=0` 欄位驗算。

### 8.5 接入圖面與配筋

順序應在數值核心之後：

1. `make_wall_section.py` 加半重力式斷面。
2. `rc_design.py` 加半重力式牆身、趾板、踵板控制斷面。
3. `case_core.py` 加半重力式設計段落。
4. `case_package.py` 跑完整三軸。
5. `check_delivery.py` 加對應圖層與尺寸檢查。

---

## 9. 回歸驗證策略

### 9.1 第一階段：只比數值核心

用 `legacy_semigravity_H4.5.json` 比對：

| 類別 | 比對項目 | 初期容差 |
|---|---|---|
| 主動土壓 | `Pa、Pah、Pav、y_a` | 0.1%～1% |
| 被動土壓 | `Pp` | 0.1%～1% |
| 穩定 | 傾倒 FS、滑動 FS、承載 FS | 0.1%～1% |
| 基底 | `q_max、q_min、e、x_R` | 0.1%～1% |
| 重量 | 混凝土重量、總垂直力 | 0.1%～1% |

若差異超過容差，先檢查：

1. 是否誤讀 `SGInput` 而非 `半重力式擋土牆`。
2. `T/m²`、`kgf/cm²` 是否正確轉 SI。
3. 牆背摩擦角是否為 `δ=2φ/3`。
4. 被動土壓是否計入 `D + b`。
5. 地震工況是否把 `Kv` 與 `Kh` 分開處理。
6. 承載公式是否使用 `B' = B - 2|e|` 與 Meyerhof 修正因子。

### 9.2 第二階段：數量對帳

以舊頁面的幾何重算混凝土斷面積，和 `qty_models.py` 的 `section_area_m2` 對帳。這一步不做，會出現「穩定過了，但數量多算 20%」的典型錯誤。

### 9.3 第三階段：全案回歸

完成 `tools\design\*`、`qty_models.py`、`case_core.py`、圖面模組後，必須跑：

```bat
python tools/selftest/regression.py
```

在半重力式新案例尚未正式加入 baseline 前，不可用 `--update` 覆蓋既有回歸基準。

---

## 10. 建議實作順序

### Phase 0：凍結基準

- 保持 `.xls` 唯讀。
- 將有效案例轉成 `data\reference\擋土牆\*.json`。
- 不執行含 `MsgBox`／Dialog 的 VBA。

### Phase 1：數值引擎

- 建 `wall_geometry.py`。
- 建 `earth_pressure.py`。
- 擴充 `retaining_wall.py` 支援 `semigravity`。
- 用 `H=4.5` 舊案例對帳。

### Phase 2：案件與數量

- 擴充 `case_new.py` 的 wall schema。
- 擴充 `qty_models.py` 的半重力式斷面積。
- 加 `case.json` 範例與一致性檢查。

### Phase 3：圖面與配筋

- `make_wall_section.py` 加半重力式。
- `rc_design.py` 加牆身／趾板／踵板。
- 報告與交付包接入。

### Phase 4：介面

- `retaining_wall.py --wall-type semigravity`。
- `case_package.py` 支援半重力式案件。
- 規範查詢台或 CLI 增加「擋土牆設計助手」入口。

---

## 11. 需要先決定的設計問題

這些問題會影響實作，不建議直接猜：

1. **半重力式的「有效高」是否包含基腳？**  
   第 118 條說「露出地面之高度」；舊 Excel 的 `H` 是否等於有效高，必須逐案確認。

2. **半重力式是否一律做牆身鋼筋設計？**  
   舊頁面有牆身十等分 RC 檢核，但半重力式在實務上可能以構造筋為主。應依牆厚、受力與規範判定，不可直接把重力式「免結構配筋」套上去。

3. **地震承載 FS 要用 2.0 還是 3.0？**  
   舊 Excel 用常時 3、地震 2；現行 `retaining_wall.py` 目前以一個 `bearing=3.0` 套用兩個工況。整併時應先確認適用規範與專案既有規則，避免把舊值或新值誤套。

4. **舊 Excel 的主動土楔法是否要完全復刻？**  
   建議復刻「概念與中間輸出」，但用可測試的 Python 實作；不要復刻 Excel 的固定格線與巨集流程。

5. **是否接受 `q`、`Hw`、`S1/S2` 為新案件必要欄位？**  
   若不接受，應提供明確預設值與「未提供即採保守值」的報告註記。

---

## 12. 最後建議

這份 Excel 最有價值的不是 VBA，而是：

- 三種牆型的參數化欄位
- 半重力式的試誤土楔與完整穩定流程
- 一組可以直接當回歸基準的 `H=4.5 m` 案例

最不應該做的是：

- 在 Python 裡直接呼叫 Excel 計算。
- 把 `.xls` 當成正式資料來源。
- 把 `SGInput` 的數值當成計算頁數值。
- 把半重力式硬改名成 `gravity`。
- 把舊 ACI 公式直接覆蓋新版 `rc_design.py`。

正確路線是「**Excel 當歷史金標準，Python 當正式計算核心，幾何與土壓力模組共用，最後才接數量、圖面與報告**」。

