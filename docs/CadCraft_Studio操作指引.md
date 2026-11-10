# CadCraft Studio 操作指引（CivilCraft／TakeoffCraft 實測版）

> 實測日期：2026-10-28｜版本：CadCraft Studio 0.7（`C:\Program\CadCraft Studio\`）
> 測試成果：`<專案根目錄>\_cadcraft_studio測試\`（遷移前舊路徑的產物，現已不存在）｜客戶端：`tools\cadcraft_studio\ccs.py`

## 1. 定位與能力邊界

- Studio 內含 8 個網頁技術 app（CadCraft、CivilCraft、TakeoffCraft、DetailCraft、PartCraft、BimCraft、ModelCraft、MarkupCraft）。
- **沒有 headless CLI**：AI 只能透過 Studio 本機 MCP 伺服器操作「使用者已開啟、且已在該 app 的 Settings › Assistants 打開助理連線」的視窗。
- 本工作區採用：**CivilCraft**（地形面、土方、縱斷、LandXML）、**TakeoffCraft**（DWG/DXF/PDF 數量計算）。
  其餘與既有工具重疊：2D 交件仍用 AutoCAD `accoreconsole`（`tools\acad\acc.py`）；3D 參數化用 SolidCraft（`docs\SolidCraft操作指引.md`）。

## 2. 連線（每次 Studio 重啟都要重新取得 token）

1. 使用者開啟 app → Settings › Assistants 打開連線 → Folders 加入 `<專案根目錄>`（實際磁碟路徑以當下專案根目錄為準）。
2. 使用者於 Studio Hub「Assistants」卡片複製 **Token** 給 AI。**token 不得寫入任何檔案**，只放環境變數：
   ```bash
   export PYTHONIOENCODING=utf-8 CCS_TOKEN='<token>'
   python tools/cadcraft_studio/ccs.py call windows_list
   ```
3. 端點 `http://127.0.0.1:<埠>/mcp`（Bearer token；埠號 `ccs.py` 自動偵測 Studio 監聽埠）。
4. 每個工具都帶 `"window": "civilcraft"` 或 `"takeoffcraft"` 指定視窗；`tools/list` 只列「最後使用視窗」的工具。
5. 檔案路徑只能在 Folders 允許的資料夾內；目標資料夾需先存在。

## 3. CivilCraft（26 個工具）

| 能做（AI 可自動） | 只能使用者在視窗手動做 |
|---|---|
| `points_add` 匯入測點（加點即自動建原地面 TIN）、`surface_elevation` 查高程、`surface_volume` 挖填方（全區／指定範圍／基準高）、`landscape_grade` 整地平台・土堤・草溝（含邊坡）、`profile_sample`／`alignment_station`（需已有線形）、`landxml_export`、`dwg_export`、`project_save` | **專案單位（預設英尺）**、**座標系統**、建立平面線形／縱斷設計／道路斷面／管網、開啟既有專案 |

**實測（121 點平面 z=100+0.02dx+0.01dy）**：高程查詢與理論值完全一致；挖填方 0% 誤差。

**陷阱**
- 單位為英尺時，`surface_volume` 以**立方碼**輸出（數值 ÷27）、`landscape_grade` 以立方英尺輸出，LandXML 標記 US Survey Foot → **作業前必請使用者把專案改公制、座標系設 TWD97 TM2 (EPSG:3826)**，並以 `site_describe` 確認 `units`。
- `dwg_export`：**只有 version `"2000"` 能被 AutoCAD 開啟**；2007／2013／2018 皆「圖檔無效」。匯出後一律以 `acc.py to_dxf` 重開驗證；交件 DWG 仍由 AutoCAD 另存。
- 匯出 DWG 的 `$INSUNITS` 隨專案單位（英尺專案為 2）。

## 4. TakeoffCraft（15 個工具）

| 能做（AI 可自動） | 只能使用者在視窗手動做 |
|---|---|
| `cad_catalog` 列圖塊／圖層／圖元、`cad_count`・`cad_count_add` 依圖塊名／圖層計數、`cad_measure` 依圖層・圖元類型・handle 量長度與面積、`items_add` 建計價項目（單價、損耗%）、`marks_add` 在 PDF 頁面座標描點、`takeoff_quantities`、`takeoff_estimate` | **開啟檔案**、**PDF 比例校正**、`takeoff_export`（會跳另存新檔對話框，AI 勿呼叫；改用 `takeoff_estimate` JSON 自行產表交 GridCraft） |

**實測（`takeoff測試圖.dxf`，答案已知）**：道路邊線 340 m、排水溝 81.4159 m（含圓弧）、建物 330 m²（hatch 中庭正確扣除）、人孔圖塊 5 個，**全部與理論值一致**；估價含 5% 損耗計算正確（四捨五入差 < 0.1 元）。

**陷阱**
- DXF/DWG 模型空間依 `$INSUNITS` 自動得比例（公尺圖檔免校正）；沒有視口的 Layout 無比例，量長度／面積會被拒（計數可）。
- 金額一律顯示 `$`、欄位名 `materialCents/laborCents`（分），自行換算新台幣顯示即可；面積項 `perimeterFt` 為英尺。
- 量測只算「圖面看得到」的圖元；關閉／凍結圖層預設略過（`hidden: include` 可納入）。
- 本工作區產出的 DXF 圖層已標準化（`10_道路邊線`、`20_建物`、`22_水道`…），可直接以圖層名量測。

## 5. 標準作業（使用者口述 → AI 交付）

1. 請使用者開啟對應 app、打開助理連線、提供 token；CivilCraft 另請確認公制與座標系。
2. `windows_list`／`app_info` 確認視窗與已開檔案。
3. 執行工具；**每個數量都要和獨立計算（ezdxf 量測或手算）比對**，差異 > 0.1% 不得交付。
4. 匯出成果放案件資料夾；DWG 以 AutoCAD 重開驗證。
5. 回報時列出：數據來源、單位、驗證方式、限制與可信度。
6. 完成後提醒使用者在 Hub › Assistants 按 New token 讓舊 token 失效。
