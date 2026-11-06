# 土木工程設計 AI 工作區：共用作業規範（Harness² 架構主規範）

> 本檔為所有智能體（Claude、Gemini / Antigravity、Codex、OpenCode、WorkBuddy）之**唯一常駐主規範（Always-On Core）**。
> `CLAUDE.md`、`GEMINI.md` 皆以本檔為準。為保護推理與輸出 Context 預算，本檔僅保留通用常駐規則與按需載入觸發器（Triggers）。

## 1. 業務範疇與目錄讀寫護欄（Guardrails）
從事**道路、排水溝、擋土牆、邊坡、箱涵、滯洪池、建築樑柱與基礎**等土木／結構小型工程設計與預算編列（小型案件通常不另行測量）。

| 目錄路徑 | 角色定位 | AI 讀寫權限 |
|---|---|---|
| `<專案根目錄>` | AI 本機作業區（根目錄只放共用設定、入口文件與既有案例） | 讀寫；但**不得在根目錄新增產出檔**（見 §1.1） |
| `<專案根目錄>/out/` | **交付物唯一落點**（`out\<案名>\`） | 讀寫；交付清單只列這裡的檔案 |
| `<專案根目錄>/_temp/` | **暫存唯一落點**（探測腳本、日誌、測試圖、下載物、實驗輸出） | 讀寫；**可整批刪除**，不得放交付物 |
| `<專案根目錄>/完整案例(參考用)/` | 使用者存放的**參考案例資料**（完整設計圖、預算書等，依案件分子資料夾） | **唯讀**：不得改寫、刪除、搬移（放檔規範見該夾內 `_放置規範與處理計畫.md`） |
| `<專案根目錄>/標準圖圖庫/` | **標準圖存放位置**（依類別分資料夾，如擋土牆／排水溝／箱涵／路面） | 可新增與歸類；不得與案件交付物混放 |
| `<專案根目錄>/cases/` | 統一案件檔（`cases\<案名>\case.json`，數量的唯一來源） | 讀寫 |
| `<專案根目錄>/data/` | 圖資與法規庫（建物 SHP、法規全文） | 以唯讀為主；新增須註明來源 |
| `<專案根目錄>/_ref/` | 機讀參考目錄（元件目錄、`components_dxf`、重建腳本） | 可寫（由 `_ref\*.py` 重建） |
| `<專案根目錄>/docs/` / `tools\` / `templates\` | 知識文件 / 程式 / 樣板 | `docs\` 只放長期知識；三者皆**不得放產出物或暫存檔** |
| `D:\公司案件\` | 人工本機作業區 | **唯讀參考**（未獲使用者明確授權，嚴禁寫入或覆寫） |
| `\\Guushan-nas\320G外接共用\` | 公司區網交付區 | 唯讀參考；**僅在使用者明確指示「交付」時**才複製成果至此 |
| `g:\我的雲端硬碟\Detail Manager\` | 歷年案例設計圖與預算書庫 | 唯讀參考（標準元件位於 `00-圖面相關\公司土木工程常用元件\`） |

### 1.1 檔案落地硬規定（HARD — 所有智能體、所有任務、不得例外）

1. **暫存檔一律進 `_temp\`**：探測腳本、一次性腳本、`_log*.txt`／`*.log`、測試 PNG、中間 DXF、下載中檔案、實驗輸出 → `_temp\<主題或案名>\`。**根目錄、`docs\`、`tools\`、`cases\` 不得出現暫存檔。**
2. **交付物一律進 `out\`**：DWG／PDF／XLSX／DOCX、PDF 轉 PNG 預覽、`<案名>_案件交付清單.md` → `out\<案名>\`。跑工具時 `--out`／`--out-dir`／`out_dir` 一律填 `out\<案名>`（`case_package.py` 已以此為預設）。
3. **`_temp\` 的定義就是「可無條件整批刪除」**：任務結束前確認裡面沒有唯一副本；`out\` 之外的成果都不算交付。
4. **不得覆寫輸入資產**：`完整案例(參考用)\`、`標準圖圖庫\`、`data\`、`D:\公司案件\`、`g:\...\Detail Manager\`、NAS 均為輸入；工具若會寫到相同路徑，一律改寫到 `out\`。
5. **交付清單只列 `out\`**：回報「交了什麼」只列 `out\<案名>\` 內檔案；`_temp\` 內容不得列入交付說明。
6. **舊案就地不動**：2026-10-30 前已散落在根目錄或 `cases\<案名>\out\` 的舊產出，不強制搬移；**新案一律照本節**，要整併舊案須先取得使用者同意。
7. **歸檔優先於新建**：需要標準圖時先找 `標準圖圖庫\` 與 `_ref\components_dxf\`，再考慮重畫；新產出的可重用標準圖，經使用者同意後歸入 `標準圖圖庫\<類別>\`。

- **高風險動作攔截**：使用者口語下令時直接執行；但**刪除檔案、寫入 `D:\公司案件\`、修改 MCP 設定檔、對外交付至 NAS** 必須先取得明確點名同意。
- **機密保護**：`claude_desktop_config.json` 含明文金鑰，嚴禁於對話或文件中輸出其內容。

## 2. DOM — 土木設計領域常數與交付契約（Durable Domain Facts）
- **輸出格式**：交件預設必須包含 **`.dwg`**（AutoCAD 2018 格式，由 `accoreconsole` 或 `CADCraft CLI` 產出；CADCraft 相容 >80% 以上 AutoCAD 功能，支援跨平台產出 DWG 與出圖），`.dxf` 為工作檔。
- **單位與座標系**：公制公尺（DXF 必設 `$INSUNITS=6`、`$MEASUREMENT=1`）；平面座標採 **TWD97 TM2 二度分帶（`EPSG:3826`）**，圖面即真實座標（台中一帶 `E≈215,000, N≈2,669,000` 屬正常假東移 `250,000`），嚴禁任意平移縮放。
- **文字樣式（`TOMO`）**：字體庫 `c:\CadFont[S]\`，英文 `gbenor.shx` ＋ 中文大字體 `CHINA1.SHX`。
  - `ezdxf` 寫法：`st = doc.styles.add("TOMO", font="gbenor.shx"); st.dxf.bigfont = "CHINA1.SHX"`（禁留 `Standard`/`Only1`）。
  - **SHX 只有 AutoCAD／`accoreconsole` 認得；CADCraft 不讀 SHX**（只吃**已安裝**的 TTF/OTF/TTC）。用 CADCraft 校對本專案圖面時設 `CADCRAFT_FONTALT=msjh.ttc`（**只認檔名**，家族名稱與完整路徑實測無效）；**沒有任何環境變數可以指定字型資料夾**。機制、實測雜湊與 `C:\CadFont[S]` 的 `-LiteralPath` 陷阱見 [`docs\字型設定_CADCraft與AutoCAD.md`](docs/字型設定_CADCraft與AutoCAD.md)。
- **圖層與色彩**：命名採 `數字前綴_中文說明`（底圖影像 `00_`、道路 `10_`、建物 `20_`、水道 `22_`、圖框說明 `90_`）；房屋與圖框文字設為 `ACI 7`（白/黑自動反轉色），禁用黃色 `ACI 2`。內嵌影像（IMAGE）須與 DXF 放同資料夾。**出圖型式一律 `monochrome.ctb`，顏色 1~8 對應固定線粗**（不重要 0.10／一般 0.15~0.20／重要 0.35~0.40 mm）；新圖層一律用 `drawing_rules.add_plot_layer()` 建，說明見 `docs\出圖樣式與線粗.md`。
- **現況平面圖必備要素**：平滑化道路邊線與中心線、依實際方位角正交化之建物輪廓＋逐棟 `ANSI31` Hatch、標註名稱之河道雙岸線、指北針、比例尺。

## 3. INV — 智能體作業與工具迴圈紀律（Invariant Execution Mechanics）

- **路徑一律由 `tools/project_paths.py` 解析（跨平台、禁止寫死絕對路徑）**：本專案要能上 GitHub，任何新增程式都不得寫死磁碟絕對路徑（例如 Windows 的 `D:\某資料夾`、`C:\Python312\python.exe`，或 macOS 的 `/Users/<名稱>/...`）。用法 `from project_paths import ROOT, regs_db, artcraft_cli, python_exe, accoreconsole, temp_dir, out_dir`；環境變數可覆寫（`CIVIL_AI_ROOT`、`CIVIL_AI_REGS_DB`、`ARTCRAFT_HOME`、`AUTOCAD_HOME`、`SOLIDCRAFT_CLI`、`CAD_FONTS`、`INGETRAZO_HOME`、`INGETRAZO_MCP`）。環境自我檢查跑 `python tools/project_paths.py`；完整需求與自動配置見 [`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)，對外說明見 [`README.md`](README.md)。
- **工具不得住在 `_temp`**：`_temp` 依 §1.1 可整批刪除，凡文件會引用的工具一律放 `tools\`（2026-11-02 已把 `page_crop.py`、`locate_pages.py`、`dump_tables.py`、`audit_qualitative.py`、`audit_skip_reasons.py`、`reconcile_progress.py` 提升到 `tools
egs\`）。
- **優先呼叫確定性腳本**：嚴禁略過 `tools\` 現成工具而重寫一次性腳本。
- **Windows 與 Python 執行鐵則**：
  1. 執行 Python（`C:\Python312\python.exe`）前必設 `set PYTHONIOENCODING=utf-8`；讀寫中文檔一律指定 `encoding="utf-8"`（**嚴禁用 PowerShell `Get-Content/Set-Content` 修改中文檔**）。
  2. 結合影像與地理幾何套件時，**第一行必寫 `import matplotlib; matplotlib.use('Agg')`**，接著依序 `import shapely`、`import pyproj`，最後才 `import cv2` 與 `import ezdxf`（防止 OpenMP `libiomp5md.dll` 衝突閃退）。
  3. 超過 60 秒之長工作（抓圖磚、Overpass、`accoreconsole`）輸出導向 `> _log.txt 2>&1` 輪詢，逾時後先檢查檔案時間戳確認冪等才重跑。
  4. 紀錄時間一律取本機系統時間：`C:\Python312\python.exe -c "import datetime;print(datetime.datetime.now())"`。
  5. **暫存與輸出位置**：批次作業前先把 `$env:TEMP`／`$env:TMP` 指向 `<專案根目錄>/_temp`（或直接用 `tools/project_paths.py` 的 `temp_dir()`），並 `os.makedirs` 出 `out\<案名>` 與 `_temp\<主題>`；中間檔（DXF／PNG／log）寫 `_temp`，交付檔寫 `out`（§1.1）。

- **不碰共用 GUI AutoCAD，並嚴格區隔兩套同名 CadCraft**：
  - **AI 後台自動化代工（轉檔、出圖、無人值守運算）**：走無介面 `accoreconsole.exe`（經 `tools\acad\acc.py`）或 `CADCraft CLI`（`tools/project_paths.py` 之 `artcraft_cli("CADCraft")` 即 `C:\Program\ArtCraft\CADCraft\cadcraft-cli.exe`，相容 >80% 以上 AutoCAD 功能，支援跨平台產出 DWG 與出圖）。
  - **人類視覺化驗收與特定互動模組**：`CadCraft Studio`（`C:\Program\CadCraft Studio\CadCraft Studio.exe`，內含 8 套網頁技術 App 如 CadCraft/CivilCraft/TakeoffCraft）為 **GUI 視窗看板**，無 headless CLI，嚴禁 AI 嘗試用腳本操控其介面做背景轉檔；僅供人類開圖檢視或依 `docs/CadCraft_Studio操作指引.md` 在已開視窗時協助。詳見 `docs/CadCraft與CadCraft_Studio分工規範.md`。
- **完稿重開驗證（Reopen & Check）**：寫檔成功 ≠ 圖面可用。每次產出 CAD 檔必須重讀驗證並將實際出圖之 PDF 轉為 PNG 目視檢查；回報時須列出風險限制、數據來源與自評可信度（1–10）。

## 4. 確定性工具鏈（Deterministic Scripts）
- `tools\site_basemap\site_basemap.py`：輸入案址經緯度 → 產出 TWD97 現況平面線稿 DXF。
- `tools\site_basemap\render_dxf.py`：將模型空間 DXF 渲染為 PNG 供快速檢核。
- `tools\a3_sheet\make_sheet.py`：**A3 出圖首選標準工具**。套用 `A3圖框.dwt`、建立非矩形裁切視口（自動避開左下說明、右上指北針、右下技師圖記區）、鎖定比例，`--publish` 呼叫 `acc.py` 產出 DWG 與 PDF（優先於舊版 `make_a3_sheet.py`）。
- `tools\a3_sheet\check_delivery.py`：**交件強制品管檢核器**（檢查 E1~E18，含幾何 bbox 壓字、疊字碰撞、顏色→線粗與出圖型式）。
- `tools\acad\acc.py`：封裝 `accoreconsole.exe` 執行 `todxf`（DWT/DWG→DXF）與 `publish`（DXF→DWG＋PDF）。出圖型式預設用專案自帶的 `tools\acad\plot\monochrome.ctb`（顏色→線粗符合規定；安裝版 monochrome.ctb 實測不符）。
- `tools\acad\ctb.py`：**出圖型式表（CTB）讀取／比對／產生**。`report` 列出顏色→線粗、`verify` 與規定表比對（不符退出碼 1）、`build` 由安裝版重產專案 CTB（只改線粗）。
- `tools\acad\apply_plot_style.py`：**舊圖套新出圖樣式**。規定上線前的 DXF 不必重跑整條產線，只換圖層顏色／線粗、把圖元自帶顏色改回 BYLAYER、補寫 `TOMO_PLOTSTYLE`，幾何與圖紙空間完全不動；`--publish` 另出 DWG＋PDF＋PNG。顏色來源是 `drawing_rules.PLAN_LAYER_COLORS`（與 `site_basemap.py` 共用同一份表）。
- `tools\cadastral\make_cadastral_map.py`：**地籍套繪圖首選工具**。輸入 WGS84 經緯度＋半徑（預設 50 m）→ 抓臺中市開放 TCLandType 坵塊／段籍（免 token、已做 `resultOffset` 分頁）＋臺中市建物 SHP，產 A3 地籍套繪圖 DXF／DWG（`--publish` 另出 PDF、`--check` 跑 E1~E18）。地號標註先找內接點、放不下改環狀外移＋引線（估寬法與 check_delivery 同一套）；段界自動裁到圖面外 30 m。**界址仍以地籍圖謄本為準，不得作為產權、鑑界或建築線依據。** 說明見 `docs\地籍套繪圖產線.md`。
- **報告章節是「派生」出來的**：`case_core._design_sections()` 拋錯時 `derive_report` 會吞掉，導致第 6/7/8/9/11 章整批消失而報告工具仍 exit 0 → `case_package.run_report` 已加檢查。**改動 `_design_sections` 內任何格式化字串後，務必看 `out\_case\report_case.json` 的 `_derived` 有沒有 `design_sections_error`。**
- **過往完整案例（參考用）**：`完整案例(參考用)\` —— 使用者會放入不同業主／地點的完整設計圖與預算書。**用途是學「格式與慣例」（圖框、圖號編法、字高、說明寫法、費率層百分比、工項命名），不是學單價也不是學設計結論。** 放置規範與處理四步見 `完整案例(參考用)\_放置規範與處理計畫.md`。收到「放好了」通知後：建索引 → 抽慣例 → 寫 `docs\完整案例_慣例對照.md`（案例怎麼做 vs 本工具怎麼做）→ 只提建議不動既有設定。**只讀不改原檔；不把案例單價寫進 `tools\boq\prices\`；不記錄業主名稱。**
- **常用元件標準圖盤點（2026-10-28）**：`docs\常用元件標準圖盤點.md` —— 把 `G:\我的雲端硬碟\Detail Manager\00-圖面相關\公司土木工程常用元件\` 的 **166 張 DWG** 分類成 12 類（擋土牆 38、排水溝渠 30、集水井 20、箱涵 11、護欄 11、路面 12、標誌標線 10、植生護坡 6、邊坡防護 4、圖框樣板 16、附屬詳圖 3、其他 5），含系列圖對照與工具鏈對應。**本地鏡像** `標準圖圖庫\`（12 類、166 張 DWG，索引見 `標準圖圖庫\_索引.md`）；**機讀目錄** `_ref\components_catalog.json`、**已轉好的 DXF** `_ref\components_dxf\C001~C166.dxf`（對照 `_ref\manifest.json`）。**重建**：`python _ref\convert_batch.py` → `_ref\parse_components.py` → `_ref\build_inventory.py`。**⚠ 圖面單位不可信**：INSUNITS 表頭多為樣板殘留（同一構造物 m 版與 cm 版都寫 mm），以檔名標註為準、範圍量級初篩後須目視確認。
- **給人看的入口**：[`怎麼用.md`](怎麼用.md)（三步驟、四類案件、五道閘門、六個常用指令、五件必須人看的事）。回報使用者「怎麼開始」時指向這份，不要叫他自己翻 `docs\`。
- **交付六道閘門**（總表見 [`docs\交付閘門總表.md`](docs/交付閘門總表.md)）：①設計檢核全過（`case_core.check`，不過即 error 中止）②E1~E18 品管 ③圖／數對帳 ④配筋圖間距對帳 ⑤**設計段落注入**（`report_case.json` 的 `_derived.design_sections_error` 有值即失敗）⑥全案回歸。各閘門防的是不同的錯，互不重疊。
- `tools\selftest\regression.py`：**全案回歸測試**。一條指令跑完所有案件的三大軸並與 `tools\selftest\baseline.json` 比對（預算總計、斷面淨面積、通水容量、滑動/傾倒/承載 FS、配筋間距）；任一項不符即退出碼 1。負面測試已驗（改壞基準 → 列出差異、exit 1）。**改過 `tools\design\*`、`qty_models`、`case_core`、繪圖模組或 `chapters.json` 後必跑**；只有改了設計才用 `--update` 重寫基準。說明見 `docs\回歸測試.md`。
- **本案最貼近的單價來源（首選）**：`tools\boq\prices\大雅區公所115年度小型工程開口契約_臺中市大雅區.json`（**176 項**，同行政區、同類小型工程、**實際契約單價**）。擋土牆覆蓋率 55.6%、排水溝 62.5%。**不同來源／年度／規模的單價可差 2~3 倍**（模板 480→1,230、挖方 350→70 是方向相反的誤差）。說明見 `docs\單價庫_大雅區115年度開口契約.md`。
- **政府公開單價**：`tools\boq\prices\公路總局單價分析表_表2_全台.json`（混凝土 210 含澆置 2,599 元/m³、鋼筋連工帶料 26 元/kg、普通模板 435 元/m²、免拆模板 206 元/m²），來源為公路總局第二區養護工程處單價分析表（`data\物價\`）。**用單價前先看工料分解，確認含不含澆置／組立**。說明見 `docs\單價庫_公路總局參考單價.md`。
- `tools\boq\price_audit.py`：**單價來源稽核首選工具**。逐項比對 `tools\boq\prices\`，標出「物價庫」或「假設值」，算出**查證覆蓋率**。`case_package` 跑完預算軸會自動產 `<案名>_單價來源稽核.md` 並在交付清單加一節。實測 AC 案 42.9%（3/7）、擋土牆與排水溝 0%（工作區無該兩類單價資料）。說明見 `docs\單價庫與查證覆蓋率.md`。
- `tools\boq\boq_build.py`：**工程預算書首選工具**。案件 JSON → 5 工作表（封面／總表／詳細表／單價分析表／數量計算）`.xlsx` ＋ `.pdf`，費率層全部活公式，內建「回讀總計 = 計算值」與 `gridcraft-cli check` 雙重驗證。費率核心 `tools\boq\boq_rules.py` 已與真實預算書對帳（回歸 `selftest\selftest_rules.py`，退出碼 0）。
- `tools\report\make_report.py`：**設計報告首選工具**。案件 JSON → A4 `.docx` ＋ `.pdf`（14 章骨架、表號圖號、頁首頁尾）；`tools\report\verify_report.py` 做 R1~R16 回讀驗證。
- `tools\case_package\case_core.py`：**統一案件檔（`civil-case/1`）**。一份 `cases\<案名>\case.json` 是數量的唯一來源；`qty_from`／`row_bind` 讓預算書數量與報告數量表都由主檔派生；`consistency()` 驗模型算式，不符即 error 並中止。
- `tools\case_package\qty_models.py`：**類別化數量模型**（`road` 道路／`wall` 擋土牆／`channel` 排水溝／`slope` 邊坡）。邊坡＝坡面斜長（H/sinβ）、水平投影（H/tanβ）、整地／植生／坡面排水／平台／表層整地；`safe_eval` 已補 `sin/cos/tan/radians`。各類別的必要輸入與衍生量不同（牆＝每米斷面×牆長＋排水孔＋伸縮縫＋模板＋開挖＋背填），**不可用道路公式硬套牆／溝**。排水孔與伸縮縫依水土保持技術規範第121條計算。
- `tools\takeoff\paving_extent.py`：**道路刨鋪範圍首選工具**。由 `road_edges_meta.json` 的實測邊線（`edge_a`/`edge_b`）沿設計中心線**裁到樁號 s1~s2** 圍成多邊形（不裁切會多算 7.6%），輸出 `15_刨鋪範圍` 圖層並對帳 `area_m2`。**只比面積，長度不可用「周長÷2」**（含兩端蓋）。
- `tools\takeoff\dxf_takeoff.py`：**圖／數對帳首選工具**。把 DXF 讀回來量（圖層面積／長度／圖元數），與案件檔 `section_area_m2` 對帳；**面積須扣 `34_溝內腔` 內腔**（不扣會多算 96%）。五張斷面圖實測差異皆 0.0000%。**已接進 `case_package.py` 的 section 軸作第三道閘門**（出圖→E1~E18→圖數對帳，任一不過即 exit 1）。道路案則在 drawing 軸自動產生刨鋪範圍並對帳 `area_m2`。`--rebar` 另量配筋圖的**鋼筋圓點間距**對配筋表（**須以 `radius<=0.02` 濾掉半徑 0.055 的筋號圓標**），已成為 section 軸第四道閘門。
- `tools\design\hydrology.py`：**集水區水文分析首選工具**（水保第 16~19 條）。降雨強度公式（第16條）、合理化公式 Qp=(1/360)CIA（第17條）、逕流係數查表（第18條）、集流時間 tc=t1+t2 與芮哈公式（第19條）。排水溝的設計流量由此求得，**不要再用假設值**。
- `tools\design\channel_hydraulics.py`：**排水溝水力計算首選工具**（曼寧等速流）。`analyse()` 檢核容量／出水高／流速上下限／福祿數；`size_channel()` 由設計流量反推最小斷面。水力參數已依《水土保持技術規範》第 78、83~86 條條文值（最小流速 0.8 m/s、混凝土常流水最大 4.57 m/s、出水高 25% 且 ≥20 cm）。
- `tools\design\rc_design.py`：**RC 構材配筋設計首選工具**（擋土牆莖板／排水溝溝壁）。撓曲 φMn≥Mu、剪力 φVc≥Vu、最小鋼筋、裂縫寬度 ≤0.3 mm。含**底板（趾板／踵板）**以牆身為固定端之懸臂板積分求彎矩（實測踵板常控制）。`rebar_kg_per_m()`／`rebar_kg_per_m_channel()` 由配筋設計推算鋼筋量（**注意：As×7850 只是「每米鋼筋長」的 kg，必須再乘鋼筋實際長度**）。實測數量表的假設值 40 kg/m³ 比設計值 61.5／64.7 低 54~62%，`consistency()` 已加交叉警告。**條文已對帳**：《混凝土結構設計規範》（內政部 100.06.09 版，全文 `data\法規\混凝土結構設計規範_1000609_全文.txt`）§2.3.2 φ（撓曲 0.90／剪力 0.75）、§3.6.1 As,min、§4.4.1.1 Vc=0.53√fc′bw·d —— 與程式一致；並已依 **§3.4.4** 用實際鋼筋量反算淨拉應變 εt 判定斷面類型（εt≥0.005 → φ=0.90；εt≤εty → 0.65；之間內插），不再一律取 0.90；規範用 kgf/cm²，程式用 MPa（1.4/fy ↔ 14/fy、0.17√fc′ ↔ 0.53√fc′）。**已依 §7.2.2／§7.4.2~7.4.4 修正牆的水平鋼筋量**（ρt=0.0025，擋土牆 t=350 → 875 mm²/m；原 D13@300 僅 423，**差 2.1 倍**；已改 D13@140=907，鋼筋量 107.84→131.04 kg/m（2026-11-04 損耗率改 6%））。**§3.7.2 的最大鋼筋間距只管梁與單向版，不適用牆**。⚠ 現行為 **112.08.10 版**《建築物混凝土結構設計規範》（已取得：`data\法規\建築物混凝土結構設計規範_1120810_全文.txt`，依 ACI 318-19 重編，條號與 100 年版不同），程式目前仍引用 100 年版條號，新舊條號對照待建立。說明見 `docs\混凝土結構設計規範_取得與條文庫.md`。
- `tools\design\sediment_basin.py`：**沉砂設施容量與初步結構／水理首選工具**（水保第 35、92、93 條）。`analyse()`：USLE（1 m³ = 1.4 公噸）→ 第 92 條臨時打 1/2 與下限（開挖 250 m³/ha、其他 30 m³/ha）→ 第 93 條臨時×1.5、深度 1.5~3.5 m；附下水道標準第 12 條快速複核。`--structure` 加做池壁／底板 RC 配筋與空池浮力；`--design-q`＋`--outlet-head`／`--overflow-head` 做孔口與矩形溢流堰。`--selftest` 25 項手算對帳。Rm／Km／LS 必須用當地參數；第 92 條未定年期，`--years` 要在報告寫明；結構未計土壓、地震、施工載重與錨定，正式設計須技師覆核。
- `tools\design\slope_stability.py`：**邊坡穩定分析首選工具**（水保第 72、73 條）。`analyse()` 同時算**無限邊坡法**與**圓弧滑動（Fellenius 坡趾圓）**，並查第 73 條最小安全係數（永久性 1.5／1.1／1.2、臨時性 1.2／1.0／1.1）；`max_stable_angle()` 反算容許坡角（回傳 `None` = 坡角非控制因素）。無凝聚性封閉解 FS=tanφ/tanβ 已對帳（1.2128 vs 1.213）。⚠ 土工參數為假設值，須以鑽探報告替換；採 Fellenius 略保守、只搜坡趾圓。
- `tools\design\retaining_wall.py`：**擋土牆穩定分析首選工具**（水土保持技術規範第 119～120 條）。`analyse()` 算主動土壓力、滑動 FS、傾倒 FS、合力作用點、基礎承載（常時與地震兩工況）；`size_section()` 依穩定需求**反推通過檢核的斷面**。斷面幾何必須與斷面圖一致（背面靠土側鉛直）。
- `tools\design\block_wall.py`：**疊砌式擋土牆首選工具**（蛇籠／格籠／漿砌石／乾砌石／三明治式，第 118～120 條）。每層界面＋基底各取自由體檢核滑動、傾倒、合力位置、承載（Coulomb＋M-O）；第 118 條高度限制（蛇籠 ≤4 m、格籠每層 ≤3 m 總高 ≤6 m、砌石 ≤4 m 且 n≥0.3、≤5／6.5 倍石材長徑）以**有效高＝總高－埋入深度**判定，超限直接拒算；三明治式須給 `site_condition`（開挖 ≤4 m／填方 ≤2 m）。工作台 id `block_wall`。
- `tools\design\counterfort_wall.py`：**扶壁式擋土牆**（§118 五，有效高 ≤10 m）。常時／地震穩定＋牆板（三帶連續版）、踵板、趾板、扶壁（T 梁＋箍筋）配筋，`--size` 反推斷面。工作台 id `counterfort_wall`。
- `tools\design\mse_wall.py`：**加勁擋土牆**（§118 六(三)，有效高 ≤8 m，FHWA 簡化法）。外部滑動／傾倒／偏心／承載＋逐層拉斷與拉出（含地震）；L ≥0.7H 且 ≥2.4 m、層距 ≤1.0 m。工作台 id `mse_wall`。
- `tools\design\anchored_wall.py`：**錨定擋土牆**（§118 八未訂高度上限；地錨依《公路邊坡工程設計規範》第六章）。視土壓包絡（0.65KaγH²）或三角形土壓 → 牆面連續梁求各排地錨反力 → 每排抗張材（表 C6.4-1 FS 1.6/2.0）、錨碇段長（地層-漿體／抗張材-漿體 FS 2.0/3.0、≥3 m）、自由段（穿過破壞面＋緩衝、≥4 m）、鎖定荷重、承壓鈑 ≤0.3fc'、沖剪；基底滑動承載；牆面雙向配筋。**整體深層穩定不在內**，須另跑 `slope_stability.py`；握裹強度須證明試驗。工作台 id `anchored_wall`。
- `tools\design\design_api.py`／`design_cli.py`：**所有設計計算的統一 JSON 入口**（`civil-design-run/1`）。21 個計算器涵蓋擋土牆（含疊砌式、扶壁式、加勁式、錨定式）、箱涵、渠道、渠道水面線、排水網路、滯洪池、建築剛架、三類基礎、沉陷與角變量、水文、沉砂池、邊坡、RC 梁與柱、鋼構柱腳（柱＋柱腳基板＋基礎螺栓，`tools\design\steel_column.py`）；每筆回傳 `summary`／`checks`／`warnings`／`codes`／`result`，並保存紀錄到 `out\design_workbench\runs\`。口語案件先用 `design_cli.py show <id>` 取得輸入範例，再 `run <id> <json>`。
- `tools\design\channel_profile.py`：**明渠水面線（迴水）首選工具**。矩形／梯形標準步法，由指定下游控制水深或自由出流（取臨界水深）向上游演算，輸出各測站水深、流速、福祿數、剖面型態（M1/M2/M3、S1/S2/S3），並檢核出水高與 §85 容許流速。均勻流會保持正常水深（回歸已驗）。**限制**：一維緩變流，不處理水躍、橋涵束縮、側流入流與彎道二次流；超臨界段無解時會截斷並回報，不會硬湊數字。
- `tools\design\workbench_web.html`：**工程設計工作台**，網址 `http://127.0.0.1:8765/design`（由 `regs_server.py --web` 同時提供）；表單由計算器 JSON 範例自動產生，可執行、檢核、下載 JSON 並跳回規範查詢。
- `tools\wall_section\make_wall_section.py`：**標準斷面圖首選工具**（擋土牆 S-01／排水溝 D-01）。`quantities.model` 為 `wall`（另需 `wall_type`：gravity 梯形／cantilever 薄牆＋底板）或 `channel`（U 型）→ A3／1:20 斷面圖 DXF＋DWG＋PDF；畫剖面線、鋼筋、排水孔／溝內腔、背填反濾層、尺寸與圖例。`--rebar` 另產**配筋圖**：擋土牆 **S-02**／排水溝 **D-02**（鋼筋依配筋設計配置、右欄為配筋表）。出圖後自動接 `check_delivery.py`（E1~E18）。
- `tools\box_section\make_box_section.py`：**箱涵標準斷面圖／配筋圖首選工具**（單孔／雙孔／三孔箱涵 S-01／S-02）。案件 JSON（`quantities.model=box_culvert`）→ A3 斷面圖 DXF＋DWG＋PDF；內角 45° 加腋（倒角，`inner_chamfer_m`，預設 0.20 m）與**角隅補強筋（X 形交叉斜筋，`corner_rebar`／`corner_rebar_spacing_mm`，預設 D13@200 mm）**一併出圖；`--rebar` 另產配筋圖 S-02（右欄為配筋表＋每延米數量表）。數量由 `box_culvert.py` 引擎同一份結果推算，出圖後接 `check_delivery.py`（E1~E18）與 `dxf_takeoff.py` 圖／數對帳。
- `tools\case_package\case_package.py`：**三軸一鍵交付**（設計圖＋預算書＋設計報告）。讀 `cases\<案名>\case.json` → 先一致性檢查 → 派生兩軸輸入 → 跑三軸 → 產 `<案名>_案件交付清單.md`。任一種不合格即退出碼 1。
- `C:\Program\ArtCraft\GridCraft\gridcraft-cli.exe`：工程預算書與 `.xlsx` 試算表處理工具（353 個指令；`boq_build.py` 底下就是呼叫它）。

- **擋土牆配筋牆型分流（2026-11-04）**：一律走 `rc_design.design_wall_rebar(q, wall_res)`。`gravity`／`semigravity`＝名目構造鋼筋（D13@250 雙向＋D16@200 底部縱筋、ρ≥0.002；3 m 重力式 41.51 kg/m）；`cantilever`＝莖板＋底板撓曲配筋；`counterfort`／`anchored`／`mse`＝由各引擎的構材設計彙總 `kg/m`；`gabion`／`crib`／`masonry_wet`／`masonry_dry`／`sandwich`＝明示不適用 RC 鋼筋、量為 0。**不可再對所有 `wall_type` 直接呼叫 `design_cantilever_stem()`**——曾使 3 m 重力式多算 61%（66.8→41.51 kg/m）。加勁式面版配筋目前為單向版初步設計，面版－加勁材連接與局部承壓仍須另核。
- **RC 鋼筋損耗率（2026-11-04 使用者指示）**：**全專案一律 6%（含搭接）**——擋土牆、排水溝、箱涵共用 `rc_design.LAP_ALLOWANCE`＝0.06；不得再把牆／溝另切 12%。

## 4B. 預算書編列原則：可微調項與方向（2026-10-28 使用者指定，必須遵守）

編列預算書時**有兩項會刻意偏離標稱費率，用來把總計調到目標金額**。這是正常作業，**不是錯誤**：

| 項目 | 標稱費率 | 可微調方向 | 原因 |
|---|---|---|---|
| **包商利潤及管理費** | 小計A × 7%（或 8%） | **一律用扣的**（實際 ≤ 標稱值） | 怕被質疑圖利廠商，所以只能往下調 |
| **空氣污染防制費** | 發包工程費 × 0.3% | **只加不減**（實際 ≥ 標稱值） | 空污費屬規費性質，多編不構成圖利 |

**因此：**
- 看到「利潤 ≠ 小計A×7%」→ **先確認是不是向下微調，不要直接判定計算錯誤**。
- 看到「空污費 ≠ 發包工程費×0.3%」→ **先確認是不是向上微調，不要直接判定計算錯誤**。
- 看到「總計剛好是整數（3,000,000／4,760,000）」→ **這是上述兩項微調的結果，不是回填造假**。

**實測驗證（兩案四項全部符合此規則）**：

| 案件 | 利潤 實際 vs 7% | 空污 實際 vs 0.3% |
|---|---|---|
| 崙背中厝 | 257,085 vs 257,087（**−2，扣**）| 13,617 vs 12,899（**+718，加**）|
| 崙背羅厝 | 160,528 vs 161,534（**−1,006，扣**）| 8,402 vs 8,016（**+386，加**）|

其他費率層（品質管制費、職安費、保險、營業稅、工程管理費、設計監造費）**沒有**這種微調慣例，
若與標稱費率不符才需要問依據。

## 5. 按需載入觸發器（On-Demand Skill & Library Triggers）
- **When the user asks in plain words to operate any ArtCraft app (CAD/Grid/Word/Deck/Pdf/Photo/Light/Vector/Design/Fig/Film/Effect/Sound/Texture Craft or Craft Anything), SolidCraft, Blender or text-to-cad (口語操作 App)**, read [`docs/口語操作手冊_ArtCraft與CAD工具.md`](docs/口語操作手冊_ArtCraft與CAD工具.md) first（口語→工具對照、參數坑、全部走 headless CLI；完整指令清單在 `docs\artcraft_commands\`）。
- **When text shows as boxes/wrong glyphs, or you need to add or verify CAD fonts (字型／字體顯示異常、要新增字型)**, read [`docs\字型設定_CADCraft與AutoCAD.md`](docs/字型設定_CADCraft與AutoCAD.md)（SHX 只有 AutoCAD 讀、CADCraft 只吃已安裝 TTF/TTC、`CADCRAFT_FONTALT`／`CADCRAFT_FONTFALLBACK` 只認檔名且不能指資料夾；附雜湊驗收法）。
- **Before using the `autocad` MCP tools (`mcp__autocad__*`)**, read [`docs/AutoCAD_MCP操作指引.md`](docs/AutoCAD_MCP操作指引.md)（僅限 `ezdxf` 後端；DWG 一律經 `acc.py`；`drawing_understand` 單位推論不可信；文字須補 TOMO）。
- **When doing terrain / cut-fill / LandXML work (CivilCraft) or quantity takeoff from DWG/DXF/PDF (TakeoffCraft)**, read [`docs/CadCraft_Studio操作指引.md`](docs/CadCraft_Studio操作指引.md) first（需使用者開視窗並提供 token；token 不落地；CivilCraft 須先改公制；DWG 只能匯出 2000 版）。
- **When choosing between CADCraft (ArtCraft CLI) and CadCraft Studio, or automating CAD operations vs opening GUI for review (兩套同名 CadCraft 分工與自動化邊界)**, read [`docs/CadCraft與CadCraft_Studio分工規範.md`](docs/CadCraft與CadCraft_Studio分工規範.md)（AI 後台代工一律用 `cadcraft-cli.exe`，Studio 僅作為人類開圖看板與特種互動模組）。
- **Before producing or modifying any drawing (basemap, A3 sheet, detail)**, read [`本項目的出圖規定(不定期新增).md`](<本項目的出圖規定(不定期新增).md>)（使用者不定期新增）並遵守；已工具化的條文集中於 `tools\drawing_rules.py`（字高 本文 3／附註 4／標題 5 mm、模型空間依比例換算、標準比例尺清單、顏色 1~8 → 線粗），出圖樣式的實作與 CTB 說明見 `docs\出圖樣式與線粗.md`，規定新增時須同步該檔。；**既有舊圖要改成新樣式時用 `tools\acad\apply_plot_style.py`**，不要重跑整條產線
- **After changing any tool under `tools\` (改過工具後)**, run `tools\selftest\regression.py`；它會跑完所有既有案件的全軸並比對基準（FS、斷面積、通水容量、配筋間距、預算）。若改到 `tools\design\`，另必跑 `tools\selftest\design_core_selftest.py` 與 `tools\selftest\design_workbench_selftest.py`；若改到查詢台，再跑 `tools\regs\regq_selftest.py`。說明見 [`docs\回歸測試.md`](docs/回歸測試.md)。
- **When checking whether a budget's unit prices are sourced or assumed (單價可信度)**, run `tools\boq\price_audit.py <case.json>`；價格庫在 `tools\boq\prices\`，案件工項要有 `code` 才比對得到（沒有 key 就等於沒有連結）。說明見 [`docs\單價庫與查證覆蓋率.md`](docs/單價庫與查證覆蓋率.md)。
- **Before producing or modifying a budget (預算書)**, read [`docs/預算書產線.md`](docs/預算書產線.md)（案件 JSON schema、費率公式與 `adj_*`／`basis` 兩個必知陷阱、單價資料庫 `tools\boq\prices\`）並用 `tools\boq\boq_build.py`，勿自建新的預算書腳本。
- **Before producing or modifying a design report (設計報告)**, read [`docs/設計報告產線.md`](docs/設計報告產線.md)（14 章骨架、`applies_to` 類別切換、需人工補項規則）並用 `tools\report\make_report.py`。
- **Before estimating a design flow (設計流量／集水區水文分析)**, read [`docs/設計計算產線.md`](docs/設計計算產線.md) §3.4 並用 `tools\design\hydrology.py`（第 16~19 條；第16條推估值為下限）。
- **Before sizing or checking a drainage channel (排水溝斷面選配／水力檢核)**, read [`docs/設計計算產線.md`](docs/設計計算產線.md)（曼寧、流速上下限、出水高、福祿數；參數已依水保規範第78、83~86條條文值）並用 `tools\design\channel_hydraulics.py`，**不要用猜的斷面**。
- **Before drawing a water-surface profile or backwater (水面線／迴水／沿線出水高檢核)**, use `tools\design\channel_profile.py` or `design_run("channel_profile", ...)`：標準步法由下游控制水深往上游算，**不要拿單一斷面的正常水深當整條溝的水深**。
- **Before designing rebar for a wall stem or channel wall (配筋設計)**, read [`docs/設計計算產線.md`](docs/設計計算產線.md) §3.6（三個坑：fs 不可一律取 0.6fy、重力式／半重力式走名目構造鋼筋而非撓曲配筋、牆型一律走 `design_wall_rebar()` 分流）並用 `tools\design\rc_design.py`。
- **Before designing or drawing rebar for any retaining wall type (擋土牆配筋／S-01 與 S-02 配筋圖)**, read [`docs/擋土牆配筋設計SOP.md`](docs/擋土牆配筋設計SOP.md)：六型分流、每延米鋼筋／模板（**RC 鋼筋損耗率全專案 6%（含搭接），牆／溝／涵一致**）、S-01 與 S-02 圖例同源、回歸與驗收數據。工作台 `wall_stability`（擋土牆穩定與配筋）已含重力／半重力／懸臂三型的配筋設定與結果；扶壁／錨定／加勁用各自計算器。**不可對所有牆型直接呼叫 `design_cantilever_stem()`**。
- **Before sizing a sediment basin or checking its wall/outlet/overflow (沉砂池容量、結構配筋、出水口、溢流)**, read [`docs\設計計算產線.md`](docs/設計計算產線.md) §3.9 並用 `tools\design\sediment_basin.py`；容量用 USLE 與第 92／93 條，結構用 `--structure`，水理用 `--design-q`，**不要再用「每公頃 30 m³」直接當設計值**（那是下水道標準的複核值）。
- **Before checking a slope (邊坡穩定分析／容許坡角)**, read [`docs/設計計算產線.md`](docs/設計計算產線.md) §3.7 並用 `tools\design\slope_stability.py`（第 72、73 條；例外要往保守倒、圓弧採坡趾圓族）。
- **Before sizing or checking a retaining wall (擋土牆斷面選配／穩定檢核)**, read [`docs/設計計算產線.md`](docs/設計計算產線.md)（三個會算錯的關鍵：梯形方向、踵板覆土、承載 FS 重複計算）並用 `tools\design\retaining_wall.py`，**不要用慣例值直接出圖**。
- **Before any numerical civil/structural design (任何數值設計／檢核)**, use `tools\design\design_api.py` through `design_cli.py`, the `/design` workbench, or MCP `design_list` → `design_show` → `design_run`. Do not replace calculations with chat arithmetic. Read [`docs\設計工作台.md`](docs/設計工作台.md) for the 22-calculator map（2026-11-03 實列） and output contract.
- **Before checking or designing a box culvert (單孔／雙孔／三孔箱涵)**, use `tools\design\box_culvert.py` or `design_run("box_culvert", ...)`. 填 `inlet_type`／`tailwater_depth_m`／`allowable_headwater_m` 時會另跑 `tools\design\culvert_hydraulics.py`：公路排水設計規範 §6.2 進口控制（附錄 N／HDS-5 迴歸式）、出口控制（附錄 O 式 O-1／O-2、表 O-1 Ke），**取兩者較大值**當設計上游水深，並比對最高容許上游水深與表 6-1 最小斷面；端牆／翼牆只檢核有輸入的幾何值（§6.5）。沖刷深度、低水頭迴水曲線與施工階段仍未做；內角 45° 加腋（`inner_chamfer_m`）與角隅補強筋（X 形交叉斜筋，構造筋）已納入引擎與出圖。
- **When using the workbench「設計圖」button or re-running a section/rebar drawing (工作台設計圖、斷面圖＋配筋圖、圖面單位 m／cm、比例 1:10～1:250)**, read [`docs\工作台設計圖產線.md`](docs/工作台設計圖產線.md) and use `tools\design\design_section.py`（`POST /api/design/section`）。模型空間一律公尺，`--unit` 只改標註與右欄尺寸表；計算結果未通過時前端按鈕必須停用。雲端靜態版沒有 Python／AutoCAD 出圖後端，只會顯示改用本機工作台的說明。
- **Before sizing beams/columns/foundations or a detention basin (建築樑柱、基礎、滯洪池)**, use `design_run("building_frame"／"foundation_*"／"settlement_assessment"／"detention_basin", ...)`. Beam design includes closed-stirrup shear and crack-driven reinforcement selection. Isolated/combined footings can include layered immediate, primary consolidation and secondary compression; `settlement_assessment` adds total settlement, differential settlement and rigid-body-adjusted angular distortion. Soil-structure interaction, lateral piles, liquefaction and raft/pile FEM remain preliminary or absent.
- **When adding or changing a design calculator (新增／修改設計計算器、要上架工作台)**, read [`docs\設計計算器上架SOP.md`](docs/設計計算器上架SOP.md)：先問清設計法與版本、適用上限、模型選擇、單位制、預設值與驗收標準（**不確定就先問使用者，不得自行假設後上架**），再依 G1~G8 落地；完成前必跑 `tools\selftest\design_launch_check.py <id>`（0 FAIL 才算上架）＋四道既有測試。漏了 `topics.json` 主題卡會讓口語查詢查不到（`steel_column` 就是漏這關後補的）。
- **Before producing a retaining-wall section drawing (擋土牆斷面圖)**, read [`docs/擋土牆斷面圖產線.md`](docs/擋土牆斷面圖產線.md)（`wall_type` 兩種斷面的差異、10 條踩坑、已知限制）並用 `tools\wall_section\make_wall_section.py`，勿自繪。
- **Before producing a box-culvert section or rebar drawing (箱涵斷面圖／配筋圖)**，read [`docs/箱涵斷面圖產線.md`](docs/箱涵斷面圖產線.md)（內角加腋、角隅補強筋、配筋表欄位、已知限制）並用 `tools\box_section\make_box_section.py`，勿自繪；**內角 45° 加腋不可省**（過往標準圖 C105~C112 內角皆有倒角），**角隅補強筋必列**（每內角 X 形交叉斜筋，標準圖 C110／C111）。
- **When starting a new case (新案件／要三件交付)**, read [`cases/README.md`](cases/README.md) and [`docs/案件交付包.md`](docs/案件交付包.md)：建立 `cases\<案名>\case.json`（`civil-case/1`，數量只寫一次），先跑 `tools\case_package\case_core.py check` 到 0 error，再跑 `tools\case_package\case_package.py` 產三軸。**不要**再為三軸各寫一份 JSON。
- **When generating a site basemap, tracing roads/buildings, or laying out an A3 sheet**, load the `civil-site-basemap` skill (at `.agents/skills/civil-site-basemap/SKILL.md`) or read [`docs/現況平面底圖作業流程.md`](docs/現況平面底圖作業流程.md) and follow it.
- **When asked to draw a cadastral map (地籍套繪圖／地籍圖套繪／查地號／地籍套繪),** use `tools\cadastral\make_cadastral_map.py --lat --lon --radius --out --publish --check`; it already handles TWD97 conversion, parcel/section/building layers, A3 frame and E1~E18. Do not build a one-off script. Limits and pitfalls: `docs\地籍套繪圖產線.md`.
- **When troubleshooting a tool error, modifying scripts under `tools/`, or handling edge cases in `accoreconsole` / `CADCraft` / `ezdxf` / `NLSC` / `Overpass`**, read [`docs/經驗索引_INDEX.md`](docs/經驗索引_INDEX.md) first and open only the matching section in [`docs/踩坑紀錄.md`](docs/踩坑紀錄.md) (do NOT read the entire `踩坑紀錄.md` up front).
- **Before trusting a quantity table, or after changing any section dimension (數量與圖是否一致／改斷面後)**, run `tools\takeoff\dxf_takeoff.py <圖.dxf> --case <case.json>`；並掃一遍 `docs\` 與報告裡引用舊值的地方。說明見 [`docs/數量量測與對帳.md`](docs/數量量測與對帳.md)。
- **中文 PDF 抽文字後要先 `unicodedata.normalize("NFKC", t)` 再搜尋**：規範 PDF 用相容表意字（如 `U+F9A0 　` 而非標準 `裂`），不正規化會 grep 到 0 次而誤判「缺字」。已備 `data\法規\混凝土結構設計規範_1000609_全文_NFKC.txt`。
- **Before citing any design code or regulation (引用任何規範／法規條文前)**, read [`docs\法規庫總目錄.md`](docs/法規庫總目錄.md) to confirm the edition is 「現行」（目前 34 份：水保、道路、排水、邊坡、鋪面、交通、施工、橋梁、建築結構、建築技術規則、農路、營建空污等），全文搜尋用 `data\法規\*_全文_NFKC.txt`；更新用 `tools\regs\fetch_regs.py` → `tools\regs\build_catalog.py`。
- **Before designing any structure or answering 「某設施要依什麼規範」 (設計前查規範)**, call the MCP tool `regs_ask`（口語句即可，例「設計一個沉砂池」；另有 `regs_search`／`regs_clause`／`regs_list`），或跑 `C:\Python312\python.exe -E -P -X utf8 tools\regs\regq.py <主題或口語句>`（`--search` 關鍵字、`--clause <代號> <條號>` 全文）。主題卡列核心條文／前置計算／注意數值（28 個主題）；PDF 表格會亂須回原 PDF 頁碼看。改過 `tools\regs\` 任何檔或重建索引後必跑 `tools\regs\regq_selftest.py`（exit 0）。人用的網頁：雙擊 `規範查詢台.bat`，工程設計工作台為 `http://127.0.0.1:8765/design`。說明見 [`docs\規範查詢台.md`](docs/規範查詢台.md)。
- **Before citing any 混凝土結構設計規範 clause**, use [`data\法規\混凝土結構設計規範_1000609_全文.txt`](data/法規/混凝土結構設計規範_1000609_全文.txt)（100.06.09 版，161 頁）與 `regulations.json` 的 `RC-*` 條目；**注意規範用 kgf/cm²、程式用 MPa**。說明見 [`docs\混凝土結構設計規範_取得與條文庫.md`](docs/混凝土結構設計規範_取得與條文庫.md)。
- **Before citing any 水土保持技術規範 clause**, use [`data/法規/水土保持技術規範_1140507_全文.txt`](data/法規/水土保持技術規範_1140507_全文.txt)（全文，114.05.07 修正）與 `templates\report\regulations.json`（條文庫，report 會自動附查證狀態）。取得法與踩坑見 [`docs/水土保持技術規範_取得與條文庫.md`](docs/水土保持技術規範_取得與條文庫.md)。
- **When drafting retaining walls, drainage channels, or standard civil details**, search and reuse standard blocks from `g:\我的雲端硬碟\Detail Manager\00-圖面相關\公司土木工程常用元件\`.

- **When using any 規範公式或表格數值做設計計算（引用規範公式／表值）**，一律用 MCP `regs_formula`／`regs_table`（已驗證庫，帶單位、適用範圍、條文頁碼）；`regs_clause` 純文字開頭標「【可信度：低】」者不得直接取數。`design_run` 回傳的 `references` 要寫進報告的依據欄。**新增或補強規範公式／圖表**（現有規範補庫、新增規範、修訂版）必須照 [`docs/規範公式圖表入庫SOP.md`](docs/規範公式圖表入庫SOP.md)：先 `tools/regs/regs_vtool.py coverage` 盤點，預設用 `tools/regs/page_table.py <src> --page N` 讀**座標化文字層**逐格轉錄（不看圖；真要對圖才 `regs_vtool.py page` 產 PNG，**同一對話的圖片總數上限 200 張，撞線後連 `/compact` 都會 400，只能開新對話**，見 `docs/踩坑紀錄.md` §U），不確定就不收，`lint`＋`verified_selftest.py`＋`regq_selftest.py` 全過才算入庫；原書疑誤者標 `pending` 並登錄 `tools/regs/design_conformance.py` 的 KNOWN，每輪跑 `design_conformance.py` 做「引擎↔已驗證庫」雙向比對（SOP §5 三道閘門、§6 雙向比對原則）。

### 5.1 MCP 工具鏈接線（2026-11-03 實測；細節見 [`docs\AI工具鏈_MCP整合_2026-11-03.md`](docs/AI工具鏈_MCP整合_2026-11-03.md)）

- **六條 MCP 通道已接線**：`regs`（9 支工具，實測）、`blender`（5，實測）、`autocad`（`full` 242／`lean` 65，實測）、`artcraft`（5 支工具／16 apps，實測）、`ingetrazo`（原始碼確認 5 支；**待 app 開橋後**跑 `python tools\ingetrazo\ingetrazo_check.py --call` 完成端到端實測）、`cadgen`（2，實測）。設定由 `tools\mcp\register_all.py` 產生；改過 MCP 設定後必跑 `python tools\mcp\register_all.py`（dry-run）→ `--apply` → `python tools\mcp\mcp_probe.py`。
- **IngeTrazo 是「GUI＋橋」型 MCP，不是 headless**：`ingetrazo-mcp.exe` 只是 stdio → `127.0.0.1:4763` 的橋；**app 開著、文件已開、擴充功能 ▸ AI Bridge (MCP) 已啟動**，`run_python`／`query_model` 才會成功（只跑 `tools/list` 會過，容易誤判）。它出的是 IFC4／數量 CSV／比例 PDF／公尺 DXF，**不是本專案 TWD97／TOMO／A3／DWG 2018 契約**；地形用 UTM WGS84，**不得當成 `EPSG:3826`**。用法見 [`docs\IngeTrazo操作指引.md`](docs/IngeTrazo操作指引.md)。
- **Blender 是 MSIX（Microsoft Store）版 5.2.3**，exe 在 `C:\Program Files\WindowsApps\BlenderFoundation.Blender_5.2.3.0_x64__pw...\Blender\blender.exe`。自檢若只掃 `C:\Program Files\Blender Foundation` 會**誤報「未安裝」**；`project_paths.blender_exe()` 已改為優先呼叫 `tools\blender\blender_runner.find_blender()`（`Get-AppxPackage` 解析）。
- **從 MCP 呼叫 ArtCraft 時，相對路徑一律落在 `out\`**（閘道 `WORK_DIR` 綁 `out`，可用 `ARTCRAFT_WORK_DIR` 覆寫）；`autocad` MCP 的 `ALLOWED_PATHS` 限本專案根，寫到外面會被拒。
- **`regs_server.py` 必須帶 `--mcp`**，否則會以一次性 CLI 結束，看起來像握手失敗。
- `cadgen`（text-to-cad）的 MCP 只給 CAD Viewer 連結與遙測；建模走 CLI `%APPDATA%\Python\Python312\Scripts\cadgen.exe`（0.6.5）＋`cad`／`dxf`／`step-parts` 技能腳本的 build123d 腳本。

- **When the user asks to turn a hand-drawn / schematic landscape image into a 3D 景觀模擬圖 or 實景意象圖（手繪圖轉 3D）**, read [`docs\3D景觀模擬_作業經驗與踩坑.md`](docs/3D景觀模擬_作業經驗與踩坑.md) first：①**建模前先送 5~7 列「判讀確認表」**並問「我這樣讀對不對」，不要問「你要選哪個方案」——2026-11-06 避車彎案三次返工全是構造物定名看錯（避車彎→誤判停車格、路緣石→誤判擋土牆），不是算圖失敗；②Blender 一律經 `tools\blender\blender_runner.py`（MSIX 版，只掃 `C:\Program Files\Blender Foundation` 會誤判未安裝），`--timeout 1200`，存檔前設 `save_version=0`；③可重用腳本在 `tools\landscape3d\`（`bay_scene.py` 參數集中在檔尾版面常數區，用 `grep -n "BAY_DEPTH =" tools\landscape3d\bay_scene.py` 定位、別抄行號；參數覆寫一律用 `blender_runner.py --arg KEY=VALUE`，MSIX 版收不到呼叫端的 `$env:`；`plan_view.py` 產正交俯視作第二幾何證據——只有透視圖不能證明緣石與坡趾對齊）；④交付清單必含性質聲明／尺寸對照／判讀假設與待確認項／重跑指令／限制／自評可信度。踩坑濃縮版見 `docs\踩坑紀錄.md` §AG。

- **When the user says「收工」、「關帳」or closeout**, read [`docs\專案收工SOP.md`](docs/專案收工SOP.md) and run all 16 steps. 版本採 CalVer `vYYYY.MM.DD-N`；「收工」一律授權 commit、tag 與 push `main`（使用者另說「先不推」才跳過）；只 stage 本次白名單，不得掃入其他 dirty 檔。

## 6. 交件強制品管門檻（Mandatory Delivery Gate）
凡交付 A3 圖面，必須備齊 `<案名>_現況平面圖_A3.dwg`、`.dxf`、`.pdf`、`.png`、`紀錄.log`，且**交件前必跑下列指令並取得退出碼 `0`（E1~E18 零錯誤，含 E15 字高／E16 標準比例／E17 顏色線粗／E18 出圖型式，含 E9 標題欄 `y=29.03`／技師圖記區 `x363.5~410.3, y29~80.9` 零跨越、E10 紙空間文字 bbox 零重疊）**，未通過不得宣稱完稿：

```bat
python tools/a3_sheet/check_delivery.py <成果.dxf> ^
  --scale 600 --require-dwg ^
  --require-layer 10_道路邊線_現況 --require-layer 20_建物 --require-layer 22_水道
```
