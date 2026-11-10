# `cases\` —— 案件資料夾規範

每個案件一個資料夾，**一份 `case.json` 是唯一數字來源**，三軸（設計圖／預算書／設計報告）都從它派生。

```
cases\<案名>\
  case.json                        統一案件檔（civil-case/1）— 唯一數字來源
  model\                           site_basemap.py 產的模型線稿＋底圖影像
  <案名>_現況平面圖_A3.dxf/.dwg/.pdf   make_sheet.py --publish 產的 A3 成果
  out\                             case_package.py 的產出（三軸成品＋交付清單）
    _case\                         當次實際送進兩軸的派生輸入（可追溯）
    _log_<軸>.txt                  各軸完整執行記錄
    預算書\ 設計報告\
    <案名>_案件交付清單.md          逐軸狀態＋交件前人工必檢清單
  _derived\                        （可選）case_core.py derive 的單獨輸出
```

## 為什麼要統一案件檔

上一版三軸各吃自己的 JSON，同一個「面積 850.6 m²」要在三個地方各打一次；打錯一次就是三份交付互相矛盾，
而且**沒有任何工具會報錯**。現在：

| 機制 | 效果 |
|---|---|
| `quantities` 是唯一可寫數量的地方 | 預算書與報告都由此派生 |
| 預算書工項用 `"qty_from": "area_m2"`（可乘 `qty_factor`） | 數量算出來，不是打出來的 |
| 報告數量表用 `row_bind` 綁回主檔 | 改主檔，表格數字跟著變 |
| `case_core.consistency()` | 驗 L×W=A、A×t=V 等幾何關係，不符即 **error 並中止** |
| `case_core.check` 的 unbound 警告 | 提示「這列表格的數字沒綁主檔，將來會走鐘」 |

## 用法

```bat
set PYTHONIOENCODING=utf-8

:: 1) 只驗一致性（不產檔，秒級）
python tools/case_package/case_core.py check cases/<案名>/case.json

:: 2) 只看摘要
... case_core.py show cases\<案名>\case.json

:: 3) 只派生兩軸輸入（除錯／人工檢視用）
... case_core.py derive cases\<案名>\case.json --out-dir cases\<案名>\_derived

:: 4) 三軸一起跑（正式用法）
python tools/case_package/case_package.py cases/<案名>/case.json
```

退出碼：`0` = 一致性無 error **且**啟用的每一軸都通過自己的驗證。

## 數量模型（`quantities.model`）

不同工程類別的數量結構不同，**不能共用一套公式**（擋土牆套道路公式會「看起來合格但完全錯」）。
`tools\case_package\qty_models.py` 定義三個模型，各自的必要輸入與衍生量：

| model | 類別 | 必要輸入 | 主要衍生量 |
|---|---|---|---|
| `road` | 道路／路面 | length, width_avg, area, thickness, volume | （採驗算：A=L×W、V=A×t） |
| `wall` | 擋土牆 | length, height, stem_thickness, base_width, base_thickness, **wall_type** | 斷面積、混凝土淨體積、排水孔數、伸縮縫數、模板、開挖、背填、鋼筋 |
| `channel` | 排水溝（U 型／矩型） | length, inner_width, depth, wall_thickness, base_thickness | 斷面積、混凝土體積、模板、開挖、伸縮縫、鋼筋 |

寫法：

```jsonc
"quantities": {
  "model": "wall",
  "values": { "length_m": 20, "height_m": 3.0, "stem_thickness_m": 0.25,
              "base_width_m": 0.6, "base_thickness_m": 0.4 }
}
```

之後 `boq.items` 就能 `"qty_from": "concrete_volume_m3"`、`"qty_from": "weep_hole_count"` 等；
**報告的數量表也會自動生成**（不需要手寫表格，數字直接取衍生值）。

排水孔與伸縮縫直接依**水土保持技術規範第121條**計算（每 2 m² 牆面 1 孔、伸縮縫每 20~40 m 一處取 25 m）。

**擋土牆必須指定 `wall_type`**（斷面積公式不同，漏填預設 cantilever）：

| wall_type | 斷面 | 斷面積 | 3 m 高的量 |
|---|---|---|---|
| `gravity` | 梯形（正面鉛直、背面斜） | `(T+BL)/2 × H` | 2.85 m³/m |
| `cantilever` | 薄牆身 + 底板 | `T×H + BL×BT` | 0.99 m³/m |

> 名稱要與幾何相符。曾把「薄牆身 250 + 底板 600×400」誤標重力式 —— 那其實是懸臂式。

## 已驗證案件

| 案件 | model | 狀態 | 證據 |
|---|---|---|---|
| `AC刨鋪5cm工程` | road | **三軸全過** | 設計圖 E1~E18 exit 0（26 棟逐戶建物、0 字高違規）、預算書總計 777,364 元回讀一致、設計報告 22 頁 R1~R16 零錯誤 |
| `擋土牆3m重力式` | wall / gravity | **三軸全過**（含斷面圖） | 斷面**依穩定分析選配** T=0.30／BL=1.95（3.375 m²/m）；滑動 FS 1.50、傾倒 3.86、合力 0.953 m（1/3 中段內）；S-01／S-02 皆 E1~E18 零錯誤 |
| `擋土牆3m懸臂式` | wall / cantilever | **三軸全過**（含斷面圖） | 斷面依穩定分析＋**配筋裂縫控制**選配：T=**0.35**／BL=1.95／BT=0.36；滑動 FS 2.35、傾倒 3.26；配筋：莖板 D16@220（裂縫 0.243）、**踵板 D16@210（M=34.07 kN·m/m 控制）**、趾板 D16@210 |

> 配筋：`tools\design\rc_design.py`（公式採 ACI 318 常用式，混凝土結構設計規範尚未取得）。

> 道路案的刨鋪範圍由 `tools\takeoff\paving_extent.py` 產生（實測 851.1 vs 850.6 m²，差 0.06%）。

> 交件前建議跑 `tools\takeoff\dxf_takeoff.py <圖> --case <case.json>` 做圖／數對帳（五張斷面圖實測差異皆 0.0000%）。

> 排水溝斷面同理：先跑 `tools\design\channel_hydraulics.py --Q <流量> --S <縱坡> --size` 選出斷面。
> 設計流量若無水文分析，須在報告標明「假設值」。

> 擋土牆斷面不可再用「慣例值」。先跑 `tools\design\retaining_wall.py <case.json>`，
> 用 `size_section()` 選出通過第 120 條檢核的斷面，再填進 `quantities.values`。
> 實測：前一版的假設斷面（重力式 BL=1.50、懸臂式 BL=0.60）**皆不通過**。
| `排水溝U型` | channel | **三軸全過**（含 D-01 斷面圖） | 斷面**依水力計算選配** b=0.50／h=0.90（Q_cap 0.766、h_n 0.625、V 1.60 m/s）；溝壁配筋 D16@300、裂縫 0.022 mm；S-01／S-02 皆 E1~E18 零錯誤 |

## 新增案件的做法

1. 複製 `tools/boq/examples/` 與 `tools/report/examples/` 的思路，但**不要再各寫一份** —— 直接寫 `case.json`。
2. `quantities` 先填 L／W／A／t／V（**A 必須等於 L×W、V 必須等於 A×t**，差 >1% 會被擋）。
3. `boq.items` 逐項填，面積類用 `qty_from: "area_m2"`、體積換噸用 `qty_from: "volume_m3", qty_factor: 2.3`。
4. `report` 段填章節素材；數量表記得加 `row_bind`。
5. `drawing.scale` 必須是標準比例尺（`tools\drawing_rules.py`），否則 E16 會擋。
6. 跑 `case_core.py check` → 修到 0 error → 跑 `case_package.py`。
