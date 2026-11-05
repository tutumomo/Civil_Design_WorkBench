---
name: civil-site-basemap
description: 產製 TWD97 現況平面底圖 DXF 與 A3 圖框配置出圖（DWG/PDF/PNG），並執行 check_delivery.py 交件品管檢核。適用於案址經緯度描圖、道路/建物/河道萃取、A3 視口比例排版與驗收。
---

# 現況平面底圖與 A3 圖框出圖技能（`civil-site-basemap`）

> 本技能封裝 `<專案根目錄>/` 現況平面底圖產製與 A3 出圖的完整確定性工具鏈與領域規則（DOM + INV）。
> 詳細流程背景見 [`docs\現況平面底圖作業流程.md`](../../../docs/現況平面底圖作業流程.md)。

**職責一句話**：給定案址經緯度，產出一份 `check_delivery.py` 退出碼 0 的 A3 現況平面圖交付包，交給業主／技師簽核。

## 1. 標準三步確定性產線（優先呼叫現成腳本，勿重寫一次性腳本）

執行前務必設定 `set PYTHONIOENCODING=utf-8`。因抓圖磚與 Overpass 查詢約需 1.5～2 分鐘，請將輸出導向 `_log.txt` 避免 60 秒逾時中斷：

```bat
set PYTHONIOENCODING=utf-8

:: Step 1: 產製模型空間 TWD97 線稿 DXF（單位：公尺，EPSG:3826）
:: ⚠ --out 是「資料夾」，不是檔名；DXF 檔名由 --name 自動決定
:: ⚠ 模型線稿屬中間檔 → 放 _temp；交付物才放 out（AGENTS.md §1.1）
python <專案根目錄>/tools\site_basemap\site_basemap.py ^
  --lat <緯度> --lon <經度> --width 260 --height 180 --scale 600 ^
  --name <案名> --out <專案根目錄>/_temp/<案名>/basemap > _log_step1.txt 2>&1

:: Step 2: 套用 A3 圖框樣板、建立非矩形裁切視口、並透過 accoreconsole 輸出 DWG 與 PDF
:: 底圖影像由 make_sheet 自動複製到輸出資料夾，模型放 _temp 不影響 IMAGE 連結（已實測）
python <專案根目錄>/tools\a3_sheet\make_sheet.py ^
  --model <專案根目錄>/_temp/<案名>/basemap/<案名>_現況平面圖_TWD97.dxf --scale 600 ^
  --title 現況平面圖 --project <工程名稱> ^
  --out <專案根目錄>/out/<案名>/<案名>_現況平面圖_A3.dxf --publish > _log_step2.txt 2>&1

:: Step 3: 執行交件品管檢核器（退出碼必須為 0 方可交件）
python <專案根目錄>/tools\a3_sheet\check_delivery.py ^
  <專案根目錄>/out/<案名>/<案名>_現況平面圖_A3.dxf --scale 600 --require-dwg ^
  --require-layer 10_道路邊線_現況 --require-layer 20_建物 --require-layer 22_水道
```

**範圍換算（1/600）**：A3 圖框視口實需 **212.1 × 155.04 m**（`CX-X0=353.5`、`Y1-Y0=258.4`，乘比例分母／1000）。低於此值 `make_sheet.py` 會印「邊緣會留白」警告，`E8` 也可能不過。實測 `--width 260 --height 180` 通過且無警告；舊版本節寫的 `--height 175` 仍可用但只剩約 20 m 餘裕；寫 `155` 則差 0.04 m 不足，會出警告。

> **注意**：`tools\a3_sheet\make_sheet.py` 為首選標準工具（已內建非矩形 Viewport 挖空避開左下說明區、右上指北針區、右下技師執業圖記區）；勿優先使用舊版 `make_a3_sheet.py`。

---

## 2. 領域規則（DOM — Practitioner Model & Data Sources）

### 2.1 資料源優先序
| 圖元類型 | 第一選擇（權威源） | 備援方案 | 禁用／避坑 |
|---|---|---|---|
| **建物輪廓** | **臺中市建物圖 SHP**（113 年版，`.prj` 為 TWD97 TM2，逐戶且具真實方位角） | NLSC `EMAPX99` 向量化（`RGB(233,226,233)`，連棟透天會併成街廓） | 禁用 OSM 建物（台中市區覆蓋率極低） |
| **道路邊線** | NLSC `EMAPX99` 灰色路緣線萃取＋水密阻隔種子法＋平滑化 | — | 嚴禁只畫 OSM 道路中心線充當平面圖 |
| **道路中心線／路名** | OSM Overpass `way[highway][name]`（**必須以 bbox 執行 Liang–Barsky 裁切**，防止範圍暴增至公里級） | 多鏡像節點輪詢（`kumi.systems`, `osm.jp`） | 不可盲猜座標放路名，取視口內幾何中點 `interpolate(0.5)` 與切線角 |
| **河道與水體** | NLSC `EMAPX99` 水體（`RGB(149,213,251)`）或 OSM `waterway` 偏移雙岸線＋**標註河道名稱** | — | 不可只畫單線或漏標河名 |

### 2.2 幾何品質與視覺規範
1. **房屋正交化與剖面線**：
   * 依每棟建物邊長加權之 $4\theta$ 圓周平均角求得真實主軸方位角（Azimuth），旋轉對齊後將 $\pm 12^\circ\sim 15^\circ$ 內近正交邊拉直，轉回原方位角並以 `buffer(0)` 修復拓樸。
   * 預先對建物遮罩做 `cv2.MORPH_CLOSE` 閉合圖示小破洞，但保留 $\ge 6\text{ m}^2$ 的真實中庭天井。
   * 逐棟建立 `ANSI31` Hatch（`hatch_style=0` Normal，外框逆時針 `flags=1`、內洞順時針 `flags=16`），切勿將百棟建物塞入單一 Hatch 實體。
2. **道路與河道平滑化**：
   * 先以 `Douglas-Peucker`（`simplify(0.5~0.6m)`）消除像素階梯鋸齒，再對 $4^\circ\sim 70^\circ$ 轉折角執行 2 階 **Chaikin Corner-Cutting** 平滑化，兼顧直線筆直度與彎道順暢度。
   * 距建物或水道 $1.0\text{ m}$ 內的重複道路邊線予以剔除，濾除 $<5\text{ m}$ 碎線。
3. **色彩對比度**：
   * 房屋與圖框文字設為 `ACI 7`（白/黑自動反轉色），避免使用黃色（`ACI 2`）導致白底 PDF 對比不足。

---

## 3. 版面與工具機制（INV — Layout & Tool Mechanics）

### 3.1 A3 圖框座標契約與視口比例換算
* **圖紙尺寸**：配置名稱 `全區工程位置圖`，A3 橫式（$420 \times 297\text{ mm}$）。
* **關鍵分區邊界（紙空間 mm）**：
  * **圖框內框總範圍**：`(10.03, 10.45) - (410.27, 287.45)`
  * **可繪區**：`x: 10.03 ~ 410.27`, `y: 29.00 ~ 287.45`（寬 $400.24\text{ mm}$，高 $258.45\text{ mm}$）
  * **標題欄保護區**：`y: 10.40 ~ 29.03`（任何說明文字、比例尺不得跨越 `y=29.03`）
  * **技師執業圖記保護區**：`x: 363.5 ~ 410.3`, `y: 29.0 ~ 80.9`（必須以非矩形 Viewport 裁切挖空避讓；不可用 `WIPEOUT` 或白色 `SOLID`）
  * **標題欄填值起點**：欄位標籤位於 `x ≈ 84.7 / 155.9 / 231.5 / 282.5 / 384.4`，填入的值文字必須位於標籤**右側**（`BOTTOM_LEFT` 對齊），嚴禁與標籤同 `x` 起排造成 E10 疊字。
* **公尺模型 vs. 公釐圖紙之 `VIEWPORT` 比例公式**：
  * 當模型空間 `1 unit = 1 m`、圖紙空間 `1 unit = 1 mm` 時，比例尺 $1/N$（如 $1/600$）代表紙面 $1\text{ mm} = \text{實地 } N/1000\text{ m}$（即 $0.6\text{ m}$）。
  * `view_height = vp_height_mm * (N / 1000.0)`（於 $1/600$ 即 `vp_height_mm * 0.6`，切勿誤乘 `600`）。
  * `ezdxf` 寫入 `VIEWPORT` 必設：`status=2`、`view_center_point=(cx, cy, 0)`、`view_target_point=(0, 0, 0)`。

### 3.2 轉檔與出圖雙軌分工
* **DWG 產製**：一律透過 `tools\acad\acc.py publish` 呼叫無介面 `accoreconsole.exe` 轉出原生 AutoCAD 2018 `.dwg`（不干擾使用者開啟中的 AutoCAD GUI，且保留完整圖紙空間配置）。
* **PDF 出圖與 PNG 預覽**：首選 `acc.py publish`（`make_sheet.py --publish` 已是這條路，出圖型式固定 `monochrome.ctb`）。
  * **備援 `cadcraft-cli` 會掉字**：CADCraft 不讀 SHX，而本專案 `TOMO` 是 `gbenor.shx` + `CHINA1.SHX`，直接用會出方框。真要走路要先設 `CADCRAFT_FONTALT=msjh.ttc`（只認檔名），並自行確認灰階出圖。機制見 [`docs\字型設定_CADCraft與AutoCAD.md`](../../../docs/字型設定_CADCraft與AutoCAD.md)。
  * 出圖型式（線粗）不是可選項：`E17`／`E18` 會擋。舊圖補樣式用 `tools\acad\apply_plot_style.py`，比對用 `tools\acad\ctb.py verify`。
  * PDF 轉 PNG 目視檢查用 PyMuPDF（`fitz`），200 DPI。

---

## 4. 交付包與品管門檻（E1–E18）

交付前必須確認 `<案名>_現況平面圖_A3.dwg`、`.dxf`、`.pdf`、`.png`、`紀錄.log` 五檔齊全，且 `check_delivery.py` **退出碼為 0**。E1–E18 任一項不過都不可宣稱完稿。

> 舊版本節只列到 E14。漏掉的 E15~E18 正好是出圖規定四項，會造成字太小、非標準比例、線粗錯誤、彩色出圖，`check_delivery.py` 卻會擋。

`check_delivery.py` 的檢查項目：
* **E1–E4**：`doc.audit()` 0 錯誤、`$INSUNITS=6`、`$MEASUREMENT=1`、`TOMO` 字型（`gbenor.shx` + `CHINA1.SHX`），無 `Standard`/`Only1` 殘留。
* **E5–E8**：單一出圖視口、比例誤差 $<0.5$、視口在內框內、模型圖元覆蓋範圍 $\ge$ 視口視窗（無邊緣留白）。
* **E9–E10**：零壓線（不跨越 `y=29.03` 與技師圖記區）、紙空間文字 bbox 零重疊。
* **E11–E14**：建物 Hatch 數 $\ge$ 建物數（E11）、圖層命名符合 `數字前綴_中文說明`（E12）、`.dwg` 存在（E13）、必要圖層（`10_道路邊線_現況`、`20_建物`、`22_水道`）皆有圖元（E14）。
* **E15**【出圖規定】文字字高 本文 3／附註 4／標題 5 mm；圖紙空間直接比對，模型空間以「字高×1000／比例」換算。
* **E16**【出圖規定】比例須為標準比例尺（清單在 `tools\drawing_rules.py`）。
* **E17**【出圖規定】顏色 1~8 對應線粗（0.10／0.15~0.20／0.35~0.40 mm），且與圖層一致。
* **E18** DXF 標頭 `TOMO_PLOTSTYLE` 須為 `monochrome.ctb`（灰階）；舊圖用 `tools\acad\apply_plot_style.py --publish` 補寫。

**唯一可放寬的項目**：案址確實無河道時 `22_水道` 不會有圖元，E14 會擋。此時移除該 `--require-layer 22_水道` 參數並在 `紀錄.log` 註明「案址無河道」（實測臺中大雅六寶里 water 0）。其餘 17 項不得放寬。

---

## 5. Anti-jobs（我永遠不做的事）

| 不做 | 原因 |
|---|---|
| 不寫入 `D:\公司案件\`、`完整案例(參考用)\`、`標準圖圖庫\`、`data\`、NAS | 這些是輸入資產。覆寫就沒有第二份，也沒有版控 |
| 不改使用者既有圖面的幾何，只新增 | 改了幾何就得整條重跑 E1–E18，而別人的圖未必過得了 |
| 不拿 CADCraft 出的 PDF 當交付 | CADCraft 不讀 SHX，本專案 `TOMO` 的中文會變方框，容易被誤當成定稿 |
| 不在 `check_delivery.py` 跑出退出碼 0 之前說「完成」 | 沒驗過就宣稱完稿，是這條產線唯一真正危險的失敗模式 |
| 不自行放寬 E1–E18 | 品管門檻是踩過坑才長出來的。唯一例外見 §4 的 E14 無河道 |

## 6. 邊界三級

| 級別 | 這個技能範圍內的行為 |
|---|---|
| **do（直接做）** | 讀 `tools\` 與 `docs\`；跑 `site_basemap.py` → `make_sheet.py` → `check_delivery.py`；寫 `_temp\<案名>\` 與 `out\<案名>\` |
| **draft-first（先草擬）** | A3 圖、PDF、PNG 產出後先給人看，確認版面（說明文字、比例尺、標題欄）再算交付 |
| **ask-first（先問過）** | 覆寫 `out\<案名>\` 內既有交付檔；寫入 §5 列出的任何輸入目錄；修改 `tools\` 或 `tools\drawing_rules.py`；把新圖歸入 `標準圖圖庫\` |

不確定往嚴格一級靠。

## 7. First run

第一次被叫用時，只問三件缺一不可的事，問完直接跑到 Step 3：

1. 案名（決定 `out\<案名>\` 資料夾名）。
2. 案址經緯度（WGS84 十進位；不接受 TWD97 座標，先換算）。
3. 出圖比例尺與範圍（預設 1/600、260×180 m；範圍內有沒有河道，決定 E14 要不要帶 `22_水道`）。

## 8. 已驗證紀錄（2026-11-05 實跑）

案址 24.241858, 120.635993（臺中市大雅區六寶里），1/600，`--width 260 --height 180`：

| 步驟 | 結果 |
|---|---|
| Step 1 | 退出碼 0｜`audit errors 0`、`entities 105`、官方建物 SHP **30 棟**、`water 0` |
| Step 2 | 退出碼 0｜`1/600 鎖定`、`PUBLISH` 產出 `.dwg` + `.pdf`、PDF 預覽 420.2×297.0 mm |
| Step 3 | 退出碼 0（兩圖層）｜`text_height_violations 0`、`plot_style monochrome.ctb`、`buildings 30 / hatches 30`、`layers_violating_naming []` |

帶 `--require-layer 22_水道` 時退出碼 1，唯一錯誤 `E14`（該案址無河道），其餘 17 項全過。

同批實跑修掉兩個工具 bug（技能舊版指令照抄會直接失敗）：

- `tools\site_basemap\site_basemap.py` 缺 `from project_paths import ROOT` → 每個 `ROOT` 參照都 `NameError`，程式根本無法啟動。
- 舊版技能把 `--out` 當檔名傳（`..._TWD97.dxf`），實際它是**資料夾** → 會建出一個以 `.dxf` 結尾的目錄。
