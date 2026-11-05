---
name: civil-site-basemap
description: 產製 TWD97 現況平面底圖 DXF 與 A3 圖框配置出圖（DWG/PDF/PNG），並執行 check_delivery.py 交件品管檢核。適用於案址經緯度描圖、道路/建物/河道萃取、A3 視口比例排版與驗收。
---

# 現況平面底圖與 A3 圖框出圖技能（`civil-site-basemap`）

> 本技能封裝 `<專案根目錄>/` 現況平面底圖產製與 A3 出圖的完整確定性工具鏈與領域規則（DOM + INV）。
> 詳細流程背景見 [`docs\現況平面底圖作業流程.md`](../../../docs/現況平面底圖作業流程.md)。

## 1. 標準三步確定性產線（優先呼叫現成腳本，勿重寫一次性腳本）

執行前務必設定 `set PYTHONIOENCODING=utf-8`。因抓圖磚與 Overpass 查詢約需 1.5～2 分鐘，請將輸出導向 `_log.txt` 避免 60 秒逾時中斷：

```bat
set PYTHONIOENCODING=utf-8

:: Step 1: 產製模型空間 TWD97 線稿 DXF（單位：公尺，EPSG:3826）
:: 視口覆蓋換算：1/600 建議給 --width 260 --height 175（或緊貼視口 240 x 155）
python <專案根目錄>/tools\site_basemap\site_basemap.py ^
  --lat <緯度> --lon <經度> --width 260 --height 175 --scale 600 ^
  --name <案名> --out <專案根目錄>/<案名>\model\<案名>_現況平面圖_TWD97.dxf > _log_step1.txt 2>&1

:: Step 2: 套用 A3 圖框樣板、建立非矩形裁切視口、並透過 accoreconsole 輸出 DWG 與 PDF
python <專案根目錄>/tools\a3_sheet\make_sheet.py ^
  --model <專案根目錄>/<案名>\model\<案名>_現況平面圖_TWD97.dxf --scale 600 ^
  --title 現況平面圖 --project <工程名稱> ^
  --out <專案根目錄>/<案名>\<案名>_現況平面圖_A3.dxf --publish > _log_step2.txt 2>&1

:: Step 3: 執行交件品管檢核器（退出碼必須為 0 方可交件）
python <專案根目錄>/tools\a3_sheet\check_delivery.py ^
  <專案根目錄>/<案名>\<案名>_現況平面圖_A3.dxf --scale 600 --require-dwg ^
  --require-layer 10_道路邊線_現況 --require-layer 20_建物 --require-layer 22_水道
```

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
* **PDF 出圖與 PNG 預覽**：可使用 `acc.py publish` 或透過 Python `subprocess.run` 呼叫 `cadcraft-cli.exe run <file.dxf> --cmd 'plot {"path":"out.pdf","layout":"全區工程位置圖","landscape":true,"plotArea":"layout","fit":false,"scale":1.0}'`，再以 PyMuPDF（`fitz`）轉出 200 DPI PNG 目視檢查。

---

## 4. 交付包與品管門檻（E1–E14）

交付前必須確認 `<案名>_現況平面圖_A3.dwg`、`.dxf`、`.pdf`、`.png`、`紀錄.log` 五檔齊全，且 `check_delivery.py` 通過以下全部檢查：
* **E1–E4**：`doc.audit()` 0 錯誤、`$INSUNITS=6`、`$MEASUREMENT=1`、`TOMO` 字型（`gbenor.shx` + `CHINA1.SHX`），無 `Standard`/`Only1` 殘留。
* **E5–E8**：單一出圖視口、比例誤差 $<0.5$、視口在內框內、模型圖元覆蓋範圍 $\ge$ 視口視窗（無邊緣留白）。
* **E9–E10**：零壓線（不跨越 `y=29.03` 與技師圖記區）、紙空間文字 bbox 零重疊。
* **E11–E14**：建物 Hatch 數 $\ge$ 建物數、`.dwg` 存在、必要圖層（`10_道路邊線_現況`、`20_建物`、`22_水道`）皆有圖元。
