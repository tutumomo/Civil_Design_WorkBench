# Open CalcSheet Studio 工具清單（MCP／REST）

> 本檔由 `python tools/crosscheck/ocss_tools_doc.py` 從**執行中的 OCSS 即時抓取**後生成，**請勿手改**；OCSS 升版後重跑即可更新。整合脈絡、單位陷阱與能力邊界見 [`OpenCalcSheetStudio_整合與開放計算環境.md`](OpenCalcSheetStudio_整合與開放計算環境.md)。

- **OCSS 版本**：2026.46.2　**工具總數**：60
- **分類（kind）**：檔案 I/O 4、改動專案 31、讀取 22、介面操作 3
- **同一份 registry、三種進入點**：MCP `http://127.0.0.1:3879/mcp`、REST 通用 `POST /api/v1/tools/<name>`、以及部分工具的語意化 REST 路由（下表『REST 路由』）。三者行為一致，token 相同。
- **認證**：`Authorization: Bearer <token>`；token 在 `preferences.json` 的 `mcpToken`（機密，不入文件／版控）。
- **Linux 設定檔位置**：`~/.local/share/tw.opencalcsheet.studio/preferences.json`（TW 版；上游為 `studio.openstructuralcalculation.app`）（Tauri `app_data_dir`；非 `~/.config`）。

## 本專案使用建議

1. **交叉驗算首選 `calc_evaluate`**：無狀態、不動專案、不會讓專案變『未儲存』。腳本端走 `tools/crosscheck/ocss_client.py`。
2. **要改專案才用 `sheet_*`／`project_*`**：`sheet_add`／`sheet_remove` 一旦做了，專案即標未儲存，刪回原狀也不復原；`project_new`／`project_open` 遇未儲存會 CONFLICT。
3. **台灣模組** `modules_list` 中以 `tw-` 開頭（RC 梁柱板、基腳、樁帽、鋼梁柱、擋土牆、排水溝、滯洪池、箱涵、沉砂池、重力式擋土牆、水面線、地震力、風力、載重彙整），專案資料欄位 `tw_*`（用途別、地況、V10、SDS、SD1）要先用 `project_set_data` 設好。
4. **不要用的**：`export_pdf`（一般版 501）、`print`（開系統對話框）。IFC 匯出（`export_ifc`／`ifc_get`）正常。
5. **連外工具**（`openWorldHint`）：`library_list`、`library_install`，會連 OpenAEC Foundation 模組庫；離線環境勿用。
6. **嚴禁對 OCSS 執行檔跑 `--version`／`--help`**：它們不會印說明，而是直接啟動 GUI 並卡住（本機 Linux 實測亦同）。查版本用 `ocss_crosscheck.py probe` 或 `app_info`。

## 總覽

### 應用與專案檔

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `app_info` | 讀取 | 唯讀、冪等 | App 名稱／版本、MCP 與 REST 位址、OpenAPI 文件位置、是否唯讀。連線冒煙測試用 |
| `project_get` | 讀取 | 唯讀、冪等 | 讀目前專案：名稱、檔案路徑、是否未儲存、專案資料欄位（可加 evaluate） |
| `project_new` | 改動專案 | 會改動、破壞性、非冪等 | 開新空白專案。有未儲存變更時回 CONFLICT，除非 force=true |
| `project_open` | 改動專案 | 會改動、破壞性、非冪等 | 由路徑開啟 .ifccalculation（或舊 .ifc-calculation／.cpd）。同樣受未儲存保護 |
| `project_save` | 檔案 I/O | 會改動、冪等 | 覆存專案檔；專案還沒有檔案時需給 path |
| `project_save_as` | 檔案 I/O | 會改動、冪等 | 另存新檔（自動補 .ifccalculation），專案改指向新檔 |
| `recent_files` | 讀取 | 唯讀、冪等 | 最近開啟／儲存的專案清單（File > Recent） |
| `project_set_name` | 改動專案 | 會改動、冪等 | 設定專案名稱（檔名與列印標題） |
| `project_set_data` | 改動專案 | 會改動、冪等 | 設定專案資料欄位，套用到所有工作表：tw_klasse 用途別 1-4、tw_terrein 地況 A/B/C、tw_V10 基本風速、tw_SDS／tw_SD1 設計譜加速度、tw_DesignLife、project_nummer 等；只能改既有欄位，任一值無效則全部不寫 |
| `project_set_visibility` | 改動專案 | 會改動、冪等 | 顯示／隱藏專案樹中的『專案資料表單』或『報告』 |

### 結構報告書

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `report_get` | 讀取 | 唯讀、冪等 | 讀結構報告書（封面、語言、修訂、章節、假設、荷重、版面），可用 dot path 只讀一部分 |
| `report_set` | 改動專案 | 會改動、冪等 | 以 dot path 設報告欄位，例如 belastingen.wind.gebouwhoogte |

### 編輯歷史

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `undo` | 改動專案 | 會改動、非冪等 | 復原上一個變更（同 Ctrl+Z，不分是誰改的） |
| `redo` | 改動專案 | 會改動、非冪等 | 重做被復原的變更（同 Ctrl+Y） |

### 模組與工作表

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `modules_list` | 讀取 | 唯讀、冪等 | 列出可用 sheet_add 加入的計算模組與資料庫工作表（templateId、name）。台灣模組以 tw- 開頭 |
| `sheets_list` | 讀取 | 唯讀、冪等 | 依序列出專案所有工作表（id、name、種類 calculation/pdf/spreadsheet/markdown/graph/drawing/jupyter…），可加 evaluate |
| `sheet_add` | 改動專案 | 會改動、非冪等 | 新增計算工作表：用 templateId 套模板，或直接給 source 計算文字。⚠ 會讓專案變『未儲存』且刪回去也不復原 |
| `sheet_add_pdf` | 改動專案 | 會改動、非冪等 | 新增 PDF 工作表（供應商計算書、FEM 報告等），給 path 或 base64 |
| `sheet_get` | 讀取 | 唯讀、冪等 | 讀單一工作表：計算文字 source、輸入欄位（含選單與目前值），可加 evaluate |
| `sheet_set_source` | 改動專案 | 會改動、破壞性、冪等 | 取代工作表的計算文字；已填輸入值保留。可 undo |
| `sheet_set_input` | 改動專案 | 會改動、冪等 | 設工作表輸入欄位或選單值，單一 name/value 或多個 values |
| `sheet_set_pdf` | 改動專案 | 會改動、破壞性、冪等 | 替換 PDF 工作表的 PDF 檔（名稱與位置不變） |
| `sheet_rename` | 改動專案 | 會改動、冪等 | 改工作表名稱（專案樹、報告、列印都會顯示） |
| `sheet_duplicate` | 改動專案 | 會改動、非冪等 | 複製工作表（含文字與輸入），插在原表後並開啟 |
| `sheet_move` | 改動專案 | 會改動、非冪等 | 上移／下移工作表（影響報告與列印順序） |
| `sheet_remove` | 改動專案 | 會改動、破壞性、冪等 | 刪除工作表，可 undo |
| `sheet_select` | 介面操作 | 會改動、冪等 | 讓 App 開啟指定工作表（id 可為 'project'＝專案資料、'report'＝報告），給使用者看 |

### 工作表內容取代（2026.45.2-tw.5 新增）

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `sheet_set_markdown` | 改動專案 | 會改動、冪等 | 取代 Markdown 工作表的文字（text）；省略的欄位保持原值 |
| `sheet_set_graph` | 改動專案 | 會改動、冪等 | 取代工作表整張圖（graph：{versie, nodes, verbindingen}），計算會重跑 |
| `sheet_set_drawing` | 改動專案 | 會改動、冪等 | 改繪圖工作表：drawing 取代整張，或只給 paper／orientation |
| `sheet_set_spreadsheet` | 改動專案 | 會改動、破壞性、冪等 | 以本機檔（path）或 base64 取代試算表工作表的 XLSX 活頁簿 |
| `sheet_set_jupyter` | 改動專案 | 會改動、破壞性、冪等 | 以本機檔（path）或 base64 取代 Jupyter 工作表的工作資料夾（ZIP，含 .ipynb） |
| `sheet_set_marimo` | 改動專案 | 會改動、冪等 | 取代 Marimo 筆記本工作表的程式碼（code，.py 含 @app.cell）；輸出屬於舊程式碼 |

### 計算

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `sheet_evaluate` | 讀取 | 唯讀、冪等 | 以該表自己的輸入與專案資料計算，回傳標題、規範、控制 UC 值、結果與檢核 |
| `calc_evaluate` | 讀取 | 唯讀、冪等 | 無狀態試算一段計算文字，不動專案、逐行回結果。批次驗算首選（不污染專案） |
| `sheet_insert_formula` | 改動專案 | 會改動、非冪等 | 把公式庫的公式（含輸入與範例值）插入工作表計算文字 |

### 批次與背景工作（不動專案，2026.46.2 新增）

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `calc_evaluate_batch` | 讀取 | 唯讀、冪等 | 一次試算多段計算文字（每項同 calc_evaluate），不動專案；上限 200 項，逐項回結果或該項錯誤。超過 120 秒的工作改用 job_start |
| `job_start` | 讀取 | 會改動、非冪等 | 在背景開始多段試算（同 calc_evaluate_batch 的項目），立即回 jobId；不動專案，工作只存在記憶體（保留最近 20 筆已結束工作） |
| `job_status` | 讀取 | 唯讀、冪等 | 查背景工作狀態（running／done／cancelled）與已完成項數；results=true（預設）回目前已算出的結果 |
| `job_cancel` | 讀取 | 會改動、冪等 | 停止背景工作（在目前這項算完後停）；已算出的結果仍可由 job_status 取得 |

### 拋棄式工作階段（不動使用者專案，2026.46.2 新增）

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `session_new` | 改動專案 | 會改動、非冪等 | 開拋棄式工作表：先把目前專案（名稱、路徑、工作表、報告、undo、未儲存旗標）收起，換成空專案；之後的操作都不進使用者專案與最近檔案 |
| `session_close` | 改動專案 | 會改動、非冪等 | 關閉 session_new 開的拋棄式工作表，把原專案完整放回（含未儲存旗標與 undo 歷史）；沒有開 session 時回 CONFLICT |

### 工作表讀取、執行與繪圖（2026.46.2 新增）

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `sheet_read` | 讀取 | 唯讀、冪等 | 以資料形式讀任一工作表：試算表逐格（值、公式、顯示文字）、圖形節點輸出與錯誤、Jupyter 逐 cell（source、execution count、輸出）、Marimo 等 |
| `sheet_run` | 改動專案 | 會改動、冪等 | 執行工作表並回傳新內容（同 sheet_read）。Jupyter：依序執行所有 code cell，遇錯停止，輸出存入專案；Marimo：重新載入並執行所有 cell。⚠ 會改動專案 |
| `sheet_reset_input` | 改動專案 | 會改動、冪等 | 把工作表輸入值還原為交付設計值（由 sheet_set_input 設的值，未設過的回計算文字預設）；可指定 names，省略則全部已改欄位還原；一步 undo |
| `sheet_drawing` | 讀取 | 唯讀、冪等 | 匯出繪圖工作表為 SVG 或 DXF（標註與 {{…}} 文字已代入計算結果，例如標註 'L/2' 隨 L 變）。座標為實際毫米（SVG 寫 data-eenheid="mm"；DXF 依 $INSUNITS：4＝mm、6＝m）；回應另列出所有綁定的變數 |
| `module_schema` | 讀取 | 唯讀、冪等 | 由 modules_list 的模組描述輸入欄位（name、label、kind、unit、default、choices）與計算文字引用的規範條號，供客戶端組 case.json；欄位範圍不在文字中宣告，回傳與該欄位相關的比較式作為防護條件 |

### 模組庫與公式庫

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `library_list` | 讀取 | 唯讀、冪等、連外 | 線上模組庫（OpenAEC Foundation 公開倉庫）全部模組：id、版本、是否已安裝；refresh 強制重抓。⚠ 連外 |
| `library_install` | 改動專案 | 會改動、非冪等、連外 | 由模組庫安裝／更新模組（用 id）。⚠ 連外 |
| `library_remove` | 改動專案 | 會改動、破壞性、冪等 | 移除由模組庫裝的模組；同 id 內建模組會回復 |
| `formulas_list` | 讀取 | 唯讀、冪等 | 搜尋公式庫（力學與 Eurocode EN 1990~1999 標準公式），可依 query／group 篩選 |
| `formula_get` | 讀取 | 唯讀、冪等 | 讀單一公式與其計算文字 |

### 匯出與列印

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `ifc_get` | 讀取 | 唯讀、冪等 | 取整個專案或單一工作表的 IFC 文字：format=ifcx（IFCX JSON）或 ifc（STEP） |
| `export_ifc` | 檔案 I/O | 會改動、冪等 | 把 IFCX（.ifcx）或 IFC（STEP .ifc）寫到檔案 |
| `export_pdf` | 檔案 I/O | 會改動、冪等 | 經 report engine 寫計算書 PDF（封面＋工作表）。⚠ 一般安裝版回 501 NOT_AVAILABLE，含圖 PDF 只能 App 內按『Rapport』 |
| `print` | 介面操作 | 會改動、非冪等 | 觸發 App 的列印（what='report' 報告 或單表）。⚠ 會開系統對話框，需人在場 |

### 檢視與設定

| 工具 | 類別 | 特性 | 用途 |
|---|---|---|---|
| `view_get` | 讀取 | 唯讀、冪等 | 讀目前工作表的檢視模式（code-visual／code-output／visual-output／print-preview／ifc） |
| `view_set` | 介面操作 | 會改動、冪等 | 切換目前工作表的檢視模式 |
| `settings_get` | 讀取 | 唯讀、冪等 | 讀 App 設定：主題、語言、文字大小、單位（角度模式、預設顯示單位） |
| `settings_set` | 改動專案 | 會改動、冪等 | 改 App 設定（theme、language、textSize、units） |

## 逐一規格

每個工具列：特性、REST 路由、參數表與 OCSS 原文說明（英文，原樣保留以免失真）。

### 應用與專案檔

#### `app_info`

- **用途**：App 名稱／版本、MCP 與 REST 位址、OpenAPI 文件位置、是否唯讀。連線冒煙測試用
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/info`、`POST /api/v1/tools/app_info`
- **參數**：無

> Name and version of the app, which edition this build is (tw or upstream) together with the full release tag, commit and build date, the MCP and REST addresses, the OpenAPI document, and whether the API is read-only or paused. Use edition and tag to tell the Taiwan build from the upstream build: they share the version number.

#### `project_get`

- **用途**：讀目前專案：名稱、檔案路徑、是否未儲存、專案資料欄位（可加 evaluate）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/project`、`POST /api/v1/tools/project_get`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `evaluate` | boolean |  | Compute every sheet now (a large sheet can take a second or more). Default false. |

> Read the open project: its name, file path, whether it has unsaved changes, the project data (fields that apply to every sheet, such as consequence class CC and wind region, with their options), the sheets (id, name, module, UC and verdict when known), which parts are hidden from the project tree, and the undo/redo steps. UC is the governing unity check (UC_max); a sheet passes when UC <= 1.0 and the sheet's own verdict agrees. By default UC is only reported for sheets evaluated through this API with their current input; pass evaluate=true to compute every sheet now.

#### `project_new`

- **用途**：開新空白專案。有未儲存變更時回 CONFLICT，除非 force=true
- **類別／特性**：改動專案；會改動、破壞性、非冪等
- **REST 路由**：`POST /api/v1/project/new`、`POST /api/v1/tools/project_new`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `force` | boolean |  | Discard unsaved changes. |
| `scratch` | boolean |  | Open a throwaway sheet instead: same as session_new (the open project comes back with session_close). |

> Start a new, empty project. Refused with CONFLICT when the open project has unsaved changes, unless force=true (then those changes are lost).

#### `project_open`

- **用途**：由路徑開啟 .ifccalculation（或舊 .ifc-calculation／.cpd）。同樣受未儲存保護
- **類別／特性**：改動專案；會改動、破壞性、非冪等
- **REST 路由**：`POST /api/v1/project/open`、`POST /api/v1/tools/project_open`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string | 是 | Absolute path of the project file. |
| `force` | boolean |  | Discard unsaved changes of the open project. |

> Open a project file (.ifccalculation, or an older .ifc-calculation/.cpd) from a path on this computer, as File > Open does; it is added to the recent files. Refused with CONFLICT when the open project has unsaved changes, unless force=true. Desktop app only.

#### `project_save`

- **用途**：覆存專案檔；專案還沒有檔案時需給 path
- **類別／特性**：檔案 I/O；會改動、冪等
- **REST 路由**：`POST /api/v1/project/save`、`POST /api/v1/tools/project_save`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string |  | Save to this path instead (as project_save_as). |

> Save the project over its own file, as File > Save does. When the project has no file yet (or was opened from an older format), pass path, or use project_save_as. Desktop app only.

#### `project_save_as`

- **用途**：另存新檔（自動補 .ifccalculation），專案改指向新檔
- **類別／特性**：檔案 I/O；會改動、冪等
- **REST 路由**：`POST /api/v1/project/save-as`、`POST /api/v1/tools/project_save_as`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string | 是 | Absolute path of the new file. |

> Save the project to a new path, as File > Save as does (.ifccalculation is added when missing). The project then continues in that file. Desktop app only.

#### `recent_files`

- **用途**：最近開啟／儲存的專案清單（File > Recent）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/project/recent`、`POST /api/v1/tools/recent_files`
- **參數**：無

> The recently opened and saved project files (File > Recent).

#### `project_set_name`

- **用途**：設定專案名稱（檔名與列印標題）
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/project/name`、`POST /api/v1/tools/project_set_name`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | string | 是 | New project name. |

> Set the project name (the name of the project file and the heading of the printout). The project data field project_naam is separate (project_set_data).

#### `project_set_data`

- **用途**：設定專案資料欄位，套用到所有工作表：tw_klasse 用途別 1-4、tw_terrein 地況 A/B/C、tw_V10 基本風速、tw_SDS／tw_SD1 設計譜加速度、tw_DesignLife、project_nummer 等；只能改既有欄位，任一值無效則全部不寫
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PATCH /api/v1/project/data`、`PATCH /api/v1/project/gegevens`、`POST /api/v1/tools/project_set_data`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | string：19 個選項（見 `tools/list`） |  | Field name. |
| `value` | string｜number |  | New value. |
| `values` | object |  | Several fields at once: {name: value}. |

> Set project data fields (see projectData in project_get). Project data applies to every sheet, e.g. tw_klasse (Taiwan building use category 1-4), tw_terrein (terrain A/B/C = 1/2/3), tw_V10, tw_SDS, tw_SD1, project_nummer; and for the Eurocode sheets CC (consequence class), windgebied (wind region), terreincategorie (terrain category), DesignLife. Pass name and value, or values {name: value} for several. For a choice field pass one of its option values (a label or the part of the label before ' — ' is also accepted). Only existing fields can be set; nothing is written if one value is invalid.

#### `project_set_visibility`

- **用途**：顯示／隱藏專案樹中的『專案資料表單』或『報告』
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/project/visibility`、`POST /api/v1/tools/project_set_visibility`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `part` | string：`projectData`／`report` | 是 | Which part. |
| `visible` | boolean | 是 | true = show in the project tree, false = hide. |

> Hide or show the project data form or the report in the project tree (as removing/adding them in the app does). Hiding keeps their content; showing brings it back.

### 結構報告書

#### `report_get`

- **用途**：讀結構報告書（封面、語言、修訂、章節、假設、荷重、版面），可用 dot path 只讀一部分
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/report`、`POST /api/v1/tools/report_get`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string |  | Dot path into the report. Default: the whole report. |

> Read the structural report (cover, language, revisions, chapters, assumptions, loads, layout) or one part of it by path, e.g. 'taal', 'belastingen.wind', 'revisies' or 'revisies.0.omschrijving' (numbers are list indexes).

#### `report_set`

- **用途**：以 dot path 設報告欄位，例如 belastingen.wind.gebouwhoogte
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PATCH /api/v1/report`、`POST /api/v1/tools/report_set`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string |  | Dot path into the report. |
| `value` | any |  | New value: string, boolean, number, list or object. |
| `values` | object |  | Several fields at once: {path: value}. |

> Set report fields by dot path (see report_get), e.g. {path: 'belastingen.wind.gebouwhoogte', value: '12'}. Text and checkbox fields take a string or boolean. Setting 'taal' ('en', 'nl') switches the report language: built-in texts switch along, text typed by the user stays. A list or object value replaces that part (e.g. append a revision with path 'revisies.2'); the app then completes it to a valid report. Pass values {path: value} for several. The parent of each path must exist.

### 編輯歷史

#### `undo`

- **用途**：復原上一個變更（同 Ctrl+Z，不分是誰改的）
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/undo`、`POST /api/v1/tools/undo`
- **參數**：無

> Undo the last change to the project (as Ctrl+Z in the app), whoever made it.

#### `redo`

- **用途**：重做被復原的變更（同 Ctrl+Y）
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/redo`、`POST /api/v1/tools/redo`
- **參數**：無

> Redo the last undone change (as Ctrl+Y in the app).

### 模組與工作表

#### `modules_list`

- **用途**：列出可用 sheet_add 加入的計算模組與資料庫工作表（templateId、name）。台灣模組以 tw- 開頭
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/modules`、`POST /api/v1/tools/modules_list`
- **參數**：無

> List the calculation modules and library sheets that can be added with sheet_add (templateId and name), including modules installed from the online module library. status: 'gereed' = checked against reference sheets, 'controleren' = verification present but not yet checked, 'raming' = quantity estimate only, 'concept' = input and drawing only. To start an empty sheet with your own calculation text, call sheet_add without templateId.

#### `sheets_list`

- **用途**：依序列出專案所有工作表（id、name、種類 calculation/pdf/spreadsheet/markdown/graph/drawing/jupyter…），可加 evaluate
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/sheets`、`POST /api/v1/tools/sheets_list`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `evaluate` | boolean |  | Compute every calculation sheet now (a large sheet can take a second or more). Default false. |

> List the sheets of the project in order (id, name, kind calculation/pdf/spreadsheet/markdown/graph/drawing/jupyter/marimo, module, active, UC and verdict when known). UC is reported for sheets evaluated through this API with their current input; pass evaluate=true to compute every sheet now.

#### `sheet_add`

- **用途**：新增計算工作表：用 templateId 套模板，或直接給 source 計算文字。⚠ 會讓專案變『未儲存』且刪回去也不復原
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/sheets`、`POST /api/v1/tools/sheet_add`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `kind` | string：`calculation`／`markdown`／`graph`／`drawing`／`spreadsheet`／`jupyter`／`marimo` |  | Sort of sheet. Default 'calculation'. |
| `templateId` | string |  | Module to insert (calculation only; see modules_list). Omit for an empty sheet. |
| `name` | string |  | Name of the new sheet. |
| `source` | string |  | Calculation text of an empty calculation sheet. Not allowed together with templateId. |
| `text` | string |  | Markdown text (kind=markdown). |
| `code` | string |  | Marimo notebook code, a .py file (kind=marimo). Default: a start notebook. |
| `graph` | object |  | Graph {versie, nodes, verbindingen} (kind=graph). Default: an empty graph. |
| `drawing` | object |  | Drawing sheet {paper, orientation, views} (kind=drawing). Default: A3 landscape with one empty view. |
| `paper` | string：`A4`／`A3`／`A2` |  | Paper size of a drawing sheet. Default A3. |
| `orientation` | string：`staand`／`liggend` |  | Orientation of a drawing sheet: staand (portrait) or liggend (landscape). Default liggend. |
| `path` | string |  | Path of the file on this computer (desktop app only). |
| `base64` | string |  | The file as base64 (a data: prefix is allowed). |
| `fileName` | string |  | File name to store with the sheet. |
| `withCode` | boolean |  | jupyter/marimo: print the code in the report. Default true. |
| `automatic` | boolean |  | jupyter: run every cell again after a change. Default false. |

> Add a sheet to the project and open it. kind picks the sort: 'calculation' (default), 'markdown', 'graph', 'drawing', 'spreadsheet', 'jupyter' or 'marimo'; a PDF has its own tool (sheet_add_pdf). For a calculation sheet pass templateId (from modules_list), or omit it to add an empty sheet with your own calculation text in source. For the other sorts pass their content: text (markdown), code (marimo), graph (graph), drawing/paper/orientation (drawing), path or base64 (spreadsheet XLSX, jupyter work folder ZIP). Without content a sensible empty sheet is made (an empty Markdown text, a start notebook, an empty graph or A3 drawing, an empty workbook). name sets the sheet name.

#### `sheet_add_pdf`

- **用途**：新增 PDF 工作表（供應商計算書、FEM 報告等），給 path 或 base64
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/sheets/pdf`、`POST /api/v1/tools/sheet_add_pdf`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string |  | Path of a PDF file on this computer (desktop app only). |
| `base64` | string |  | The PDF file as base64 (a data: prefix is allowed). |
| `fileName` | string |  | File name to store with the PDF. Default: the name in path, or document.pdf. |
| `force` | boolean |  | Allow a PDF above 20 MB. |
| `name` | string |  | Name of the new sheet. |

> Add a PDF sheet: a PDF file (e.g. a supplier calculation or a FEM report) that sits between the calculation sheets and goes into the structural report. Pass path (a PDF on this computer) or base64. name defaults to the file name without .pdf.

#### `sheet_get`

- **用途**：讀單一工作表：計算文字 source、輸入欄位（含選單與目前值），可加 evaluate
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/sheets/{id}`、`POST /api/v1/tools/sheet_get`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string |  | Sheet id. Default: the sheet that is open in the app. |
| `evaluate` | boolean |  | Compute the sheet to report the outcome (a large sheet can take a second). Default true. |
| `full` | boolean |  | Drawing and Marimo: return the whole sheet (views with shapes, stored output) instead of a summary. Default false. |

> Read one sheet. A calculation sheet gives its text (source), its input fields and, unless evaluate=false, the outcome (title, norm, governing UC, verdict, UC values). A PDF or spreadsheet gives the file name and size; Markdown gives its text; a graph its nodes and connections; a drawing a summary (pass full=true for the whole sheet); Jupyter its file name, size and files; Marimo its code, cell count and stored output.

#### `sheet_set_source`

- **用途**：取代工作表的計算文字；已填輸入值保留。可 undo
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/source`、`POST /api/v1/tools/sheet_set_source`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `source` | string | 是 | The new calculation text. |

> Replace the calculation text of a sheet. Input values already entered stay as they are. Undoable (undo). Returns the input fields of the new text.

#### `sheet_set_input`

- **用途**：設工作表輸入欄位或選單值，單一 name/value 或多個 values
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PATCH /api/v1/sheets/{id}/inputs`、`POST /api/v1/tools/sheet_set_input`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `name` | string |  | Input name. |
| `value` | string｜number |  | New value. |
| `values` | object |  | Several values at once: {name: value}. |
| `design` | boolean |  | Record the values as the delivered design values. Default true; false leaves the delivered values and so marks the fields as modified. |

> Set input values of a sheet: an input field or a choice list (see inputs in sheet_get). Pass name and value for one value, or values as an object {name: value} for several. For a choice list pass the option value (the option text is also accepted). Numbers may be given as number or text ('4.2' or '4,2'), in the unit of the field. Nothing is written if one value is invalid. The values you set are recorded as the delivered design values: when the user later changes a field in the app, sheet_get and sheet_evaluate report it as modified with its original value. Pass design=false to change a value the way a user does, leaving the delivered value as it was.

#### `sheet_set_pdf`

- **用途**：替換 PDF 工作表的 PDF 檔（名稱與位置不變）
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/pdf`、`POST /api/v1/tools/sheet_set_pdf`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `path` | string |  | Path of a PDF file on this computer (desktop app only). |
| `base64` | string |  | The PDF file as base64 (a data: prefix is allowed). |
| `fileName` | string |  | File name to store with the PDF. Default: the name in path, or document.pdf. |
| `force` | boolean |  | Allow a PDF above 20 MB. |

> Replace the PDF file of a PDF sheet (path or base64); name and position stay.

#### `sheet_rename`

- **用途**：改工作表名稱（專案樹、報告、列印都會顯示）
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PATCH /api/v1/sheets/{id}`、`POST /api/v1/tools/sheet_rename`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `name` | string | 是 | New name. |

> Rename a sheet. The name shows in the project tree, the report and on the printout.

#### `sheet_duplicate`

- **用途**：複製工作表（含文字與輸入），插在原表後並開啟
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/duplicate`、`POST /api/v1/tools/sheet_duplicate`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `name` | string |  | Name of the copy. |

> Duplicate a sheet with its own copy of text and inputs, directly after the original, and open the copy. name sets the name of the copy.

#### `sheet_move`

- **用途**：上移／下移工作表（影響報告與列印順序）
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/move`、`POST /api/v1/tools/sheet_move`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `direction` | string：`up`／`down` | 是 | up = towards the start of the project. |
| `steps` | integer |  | Number of places. Default 1. |

> Move a sheet up or down in the project (and thus in the report and the printout). steps defaults to 1; the sheet stops at the top or bottom.

#### `sheet_remove`

- **用途**：刪除工作表，可 undo
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`DELETE /api/v1/sheets/{id}`、`POST /api/v1/tools/sheet_remove`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |

> Remove a sheet from the project. Undoable (undo).

#### `sheet_select`

- **用途**：讓 App 開啟指定工作表（id 可為 'project'＝專案資料、'report'＝報告），給使用者看
- **類別／特性**：介面操作；會改動、冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/select`、`POST /api/v1/tools/sheet_select`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id, 'project' or 'report'. |

> Open a sheet in the app so the user sees it. id is a sheet id, or 'project' for the project data form, or 'report' for the structural report. Does not change the project.

### 工作表內容取代（2026.45.2-tw.5 新增）

#### `sheet_set_markdown`

- **用途**：取代 Markdown 工作表的文字（text）；省略的欄位保持原值
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/markdown`、`POST /api/v1/tools/sheet_set_markdown`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `text` | string | 是 | The new Markdown text. |
| `fileName` | string |  | Source file name to store with the sheet. |
| `headingsInToc` | boolean |  | Keep the headings of this sheet in the table of contents of the report. |

> Replace the text of a Markdown sheet. fileName and headingsInToc are optional; what you leave out stays as it is. Undoable (undo).

#### `sheet_set_graph`

- **用途**：取代工作表整張圖（graph：{versie, nodes, verbindingen}），計算會重跑
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/graph`、`POST /api/v1/tools/sheet_set_graph`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `graph` | object | 是 | The graph: {versie, nodes, verbindingen}. |

> Replace the whole graph of a graph sheet: nodes and connections as JSON ({versie, nodes, verbindingen}). The sheet recomputes its values from the graph. Undoable (undo).

#### `sheet_set_drawing`

- **用途**：改繪圖工作表：drawing 取代整張，或只給 paper／orientation
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/drawing`、`POST /api/v1/tools/sheet_set_drawing`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `drawing` | object |  | The whole drawing sheet {paper, orientation, views}. |
| `paper` | string：`A4`／`A3`／`A2` |  | New paper size. |
| `orientation` | string：`staand`／`liggend` |  | New orientation: staand or liggend. |

> Change a drawing sheet: pass drawing to replace the whole sheet ({paper, orientation, views}), or paper and/or orientation to change only the sheet size. A view holds shapes in mm; see sheet_get with full=true for the current sheet. Undoable (undo).

#### `sheet_set_spreadsheet`

- **用途**：以本機檔（path）或 base64 取代試算表工作表的 XLSX 活頁簿
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/spreadsheet`、`POST /api/v1/tools/sheet_set_spreadsheet`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `path` | string |  | Path of the file on this computer (desktop app only). |
| `base64` | string |  | The file as base64 (a data: prefix is allowed). |
| `fileName` | string |  | File name to store with the sheet. |

> Replace the workbook (XLSX) of a spreadsheet sheet with a file from this computer (path) or base64. Name and position stay. Undoable (undo).

#### `sheet_set_jupyter`

- **用途**：以本機檔（path）或 base64 取代 Jupyter 工作表的工作資料夾（ZIP，含 .ipynb）
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/jupyter`、`POST /api/v1/tools/sheet_set_jupyter`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `path` | string |  | Path of the file on this computer (desktop app only). |
| `base64` | string |  | The file as base64 (a data: prefix is allowed). |
| `fileName` | string |  | File name to store with the sheet. |
| `withCode` | boolean |  | Print the code in the report. |
| `automatic` | boolean |  | Run every cell again after a change. |

> Replace the work folder (ZIP with .ipynb files) of a Jupyter sheet with a file from this computer (path) or base64. withCode and automatic are optional; what you leave out stays as it is. Undoable (undo).

#### `sheet_set_marimo`

- **用途**：取代 Marimo 筆記本工作表的程式碼（code，.py 含 @app.cell）；輸出屬於舊程式碼
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PUT /api/v1/sheets/{id}/marimo`、`POST /api/v1/tools/sheet_set_marimo`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `code` | string | 是 | The Marimo notebook as Python code. |
| `fileName` | string |  | Source file name to store with the sheet. |
| `withCode` | boolean |  | Print the code in the report. Default: keep the current setting. |
| `clearOutput` | boolean |  | Drop the stored output of the old code. Default true. |

> Replace the code of a Marimo notebook sheet (a .py file with @app.cell blocks). The stored output belongs to the old code, so it is cleared unless clearOutput=false; the app computes new output when the user runs the notebook. Undoable (undo).

### 計算

#### `sheet_evaluate`

- **用途**：以該表自己的輸入與專案資料計算，回傳標題、規範、控制 UC 值、結果與檢核
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/evaluate`、`POST /api/v1/tools/sheet_evaluate`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string |  | Sheet id. Default: the sheet that is open in the app. |
| `numbers` | boolean |  | Include the numbers of the sheet. Default true. |
| `names` | array<string> |  | Only these numbers (variable names). |
| `lines` | boolean |  | Also return the calculation line by line, as calc_evaluate does. Default false. |
| `conventionalUnits` | boolean |  | Also give each value in the conventional unit where there is one (kN/mm^2 → MPa, tf/m^2 → kPa). Default false. |
| `strict` | boolean |  | Refuse the calculation when a unit warning is raised. Default false. |

> Compute a sheet with its own inputs and the project data, and return the outcome: title, norm, governing UC (UC_max), verdict (passes), every UC value and the numbers the sheet shows (name → value in the sheet's unit). Pass names to return only those numbers, or numbers=false to leave them out.

#### `calc_evaluate`

- **用途**：無狀態試算一段計算文字，不動專案、逐行回結果。批次驗算首選（不污染專案）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`POST /api/v1/evaluate`、`POST /api/v1/tools/calc_evaluate`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `source` | string | 是 | Calculation text. |
| `values` | object |  | Input values {name: value}. |
| `useProjectData` | boolean |  | Make the project data available as variables. Default true. |
| `maxLines` | integer |  | At most this many lines. Default 400. |
| `conventionalUnits` | boolean |  | Also give each value in the conventional unit where there is one (kN/mm^2 → MPa, tf/m^2 → kPa). Default false. |
| `strict` | boolean |  | Refuse the calculation when a unit warning is raised (warnings[] would not be empty). Default false. |

> Compute a piece of calculation text without changing the project, and return the result line by line (headings, text, assignments with expression, result and unit, inputs, choices) plus the governing UC and verdict if the text has them. The project data (CC, K_FI, windgebied, …) are available as variables unless useProjectData=false. values sets input fields and choice lists by name.

#### `sheet_insert_formula`

- **用途**：把公式庫的公式（含輸入與範例值）插入工作表計算文字
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/formulas`、`POST /api/v1/tools/sheet_insert_formula`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `formulaId` | string | 是 | Formula id (from formulas_list). |
| `position` | string｜integer |  | 'end', 'start' or a line number after which to insert. |
| `language` | string：`en`／`nl` |  | Language of the text lines of a worked example. Default: the language of the app. |

> Insert a formula from the formula library (formulas_list) into a sheet's calculation text: its inputs with example values and the formula lines. position: 'end' (default), 'start', or a line number to insert after (0 = before the first line). Returns the lines that were inserted.

### 批次與背景工作（不動專案，2026.46.2 新增）

#### `calc_evaluate_batch`

- **用途**：一次試算多段計算文字（每項同 calc_evaluate），不動專案；上限 200 項，逐項回結果或該項錯誤。超過 120 秒的工作改用 job_start
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`POST /api/v1/evaluate/batch`、`POST /api/v1/tools/calc_evaluate_batch`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `items` | array<object> | 是 | The texts to compute, each with the arguments of calc_evaluate (source, values, useProjectData, maxLines, conventionalUnits, strict). At most 200. |

> Compute several calculation texts in one request without changing the project. Each item takes the arguments of calc_evaluate and gets the same answer calc_evaluate would give, or its error ({index, ok:false, error:{code, message, data}}), in the order of the items. At most 200 items. For work that may take longer than the bridge timeout (120 s), use job_start.

#### `job_start`

- **用途**：在背景開始多段試算（同 calc_evaluate_batch 的項目），立即回 jobId；不動專案，工作只存在記憶體（保留最近 20 筆已結束工作）
- **類別／特性**：讀取；會改動、非冪等
- **REST 路由**：`POST /api/v1/jobs`、`POST /api/v1/tools/job_start`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `items` | array<object> | 是 | The texts to compute, each with the arguments of calc_evaluate (source, values, useProjectData, maxLines, conventionalUnits, strict). At most 200. |

> Start computing several calculation texts in the background (the items of calc_evaluate_batch) and return a jobId at once. Poll job_status for progress and results; job_cancel stops it. Does not change the project. Jobs live in memory only (the last 20 finished jobs are kept).

#### `job_status`

- **用途**：查背景工作狀態（running／done／cancelled）與已完成項數；results=true（預設）回目前已算出的結果
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/jobs/{jobId}`、`POST /api/v1/tools/job_status`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `jobId` | string | 是 | The job id from job_start. |
| `results` | boolean |  | Include the answers so far. Default true. |

> The state of a background job: running, done or cancelled; how many items are done; and with results=true (default) the answers so far, each as in calc_evaluate_batch.

#### `job_cancel`

- **用途**：停止背景工作（在目前這項算完後停）；已算出的結果仍可由 job_status 取得
- **類別／特性**：讀取；會改動、冪等
- **REST 路由**：`DELETE /api/v1/jobs/{jobId}`、`POST /api/v1/tools/job_cancel`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `jobId` | string | 是 | The job id from job_start. |

> Stop a background job after the item it is computing now. The answers so far stay available through job_status. A job that has finished is left as it is.

### 拋棄式工作階段（不動使用者專案，2026.46.2 新增）

#### `session_new`

- **用途**：開拋棄式工作表：先把目前專案（名稱、路徑、工作表、報告、undo、未儲存旗標）收起，換成空專案；之後的操作都不進使用者專案與最近檔案
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/session/new`、`POST /api/v1/tools/session_new`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `force` | boolean |  | Set the open project aside even when it has unsaved changes; those changes are not lost. |

> Open a throwaway sheet: the open project is set aside (name, path, sheets, report, undo history and the unsaved flag) and an empty project takes its place. Everything the tools do from then on stays out of the real project and out of the recent files. Close it with session_close, which puts the project back exactly as it was. Useful for a computation that should not touch the user's project. Refused with CONFLICT when a session is already open, or when the open project has unsaved changes and force is not true.

#### `session_close`

- **用途**：關閉 session_new 開的拋棄式工作表，把原專案完整放回（含未儲存旗標與 undo 歷史）；沒有開 session 時回 CONFLICT
- **類別／特性**：改動專案；會改動、非冪等
- **REST 路由**：`POST /api/v1/session/close`、`POST /api/v1/tools/session_close`
- **參數**：無

> Close the throwaway sheet opened with session_new (or project_new with scratch=true) and put the project back exactly as it was, including the unsaved flag and the undo history. The answers from Open FEM Studio that were fetched during the session are dropped. Refused with CONFLICT when no session is open.

### 工作表讀取、執行與繪圖（2026.46.2 新增）

#### `sheet_read`

- **用途**：以資料形式讀任一工作表：試算表逐格（值、公式、顯示文字）、圖形節點輸出與錯誤、Jupyter 逐 cell（source、execution count、輸出）、Marimo 等
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/sheets/{id}/content`、`POST /api/v1/tools/sheet_read`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string |  | Sheet id. Default: the sheet that is open in the app. |
| `maxCells` | integer |  | Spreadsheet: at most this many filled cells in total. Default 2000. |

> Read the content of any sheet as data. Spreadsheet: every filled cell per worksheet (a1, kind, value, formula, displayed text; formulas give the result the spreadsheet engine computed). Graph: the graph is computed and each node gives its output values (text, value or si_value), errors and warnings, plus the table of view nodes. Jupyter: each notebook with its cells, source, execution count and stored outputs (stream text, results, errors; images only as their MIME type); cells never run have executionCount null. Marimo: each cell's code and stored output as plain text. Calculation sheet: the outcome and the structured lines (as sheet_evaluate with lines=true). Stored notebook output is what the notebook showed when it was last run in the app; call sheet_run to run it again first.

#### `sheet_run`

- **用途**：執行工作表並回傳新內容（同 sheet_read）。Jupyter：依序執行所有 code cell，遇錯停止，輸出存入專案；Marimo：重新載入並執行所有 cell。⚠ 會改動專案
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/run`、`POST /api/v1/tools/sheet_run`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `timeoutSeconds` | integer |  | Notebook: wait at most this long. Default 90. |
| `maxCells` | integer |  | Spreadsheet: at most this many filled cells. Default 2000. |

> Run a sheet and return its new content (the same data as sheet_read). Jupyter: the sheet opens in the app, every code cell of the open notebook runs top to bottom (stopping after an error), and the new output is stored in the project. Marimo: the notebook reloads, which runs every cell, and the output is stored once it stops changing. Graph, spreadsheet and calculation sheets compute when read, so this equals sheet_read. Notebooks run only in the desktop app, and need its Python environment. completed=false means the run did not finish in time and the output may be stale or partial: do not rely on it.

#### `sheet_reset_input`

- **用途**：把工作表輸入值還原為交付設計值（由 sheet_set_input 設的值，未設過的回計算文字預設）；可指定 names，省略則全部已改欄位還原；一步 undo
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`POST /api/v1/sheets/{id}/inputs/reset`、`POST /api/v1/tools/sheet_reset_input`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `names` | array<string> |  | Only these inputs. Default: every modified input. |

> Put input values of a sheet back to the delivered design values (the values set with sheet_set_input, or the defaults of the calculation text for fields never set). Pass names for some fields; without names every modified field goes back. One undo step. A sheet that was never filled in through the API tracks no design values: then nothing is reset and tracked is false.

#### `sheet_drawing`

- **用途**：匯出繪圖工作表為 SVG 或 DXF（標註與 {{…}} 文字已代入計算結果，例如標註 'L/2' 隨 L 變）。座標為實際毫米（SVG 寫 data-eenheid="mm"；DXF 依 $INSUNITS：4＝mm、6＝m）；回應另列出所有綁定的變數
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/sheets/{id}/drawing`、`POST /api/v1/tools/sheet_drawing`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Sheet id (from project_get or sheets_list). |
| `format` | string：`svg`／`dxf` |  | Default svg. |
| `view` | string |  | Id or title of one view. Default: every view of the sheet. |
| `unit` | string：`mm`／`m` |  | DXF only: the unit of the coordinates. Default mm. |

> Export a drawing sheet as SVG or DXF, with the dimensions and {{…}} texts that hang on the calculation sheet filled in (a dimension 'L/2' follows the value of L). Coordinates are millimetres in reality; SVG says so in the file (data-eenheid="mm", width/height in mm) and DXF in $INSUNITS (4 = mm, 6 = m; unit sets which). In DXF the y-axis points up, as DXF expects. The answer also lists every binding (expression, value, unit, error) and each view with its bounds in mm; bindings the calculation sheet cannot resolve are in unbound. Symbols and arcs cannot become plain DXF entities without drawing them wrong: they are counted in skipped and left out of the DXF.

#### `module_schema`

- **用途**：由 modules_list 的模組描述輸入欄位（name、label、kind、unit、default、choices）與計算文字引用的規範條號，供客戶端組 case.json；欄位範圍不在文字中宣告，回傳與該欄位相關的比較式作為防護條件
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/modules/{templateId}/schema`、`POST /api/v1/tools/module_schema`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `templateId` | string | 是 | Module (templateId from modules_list). |

> Describe a module from modules_list: its input fields (name, label, kind, unit, default, choices) and the norm clauses its calculation text cites, so a client can build a case.json for it. The bounds a field has to satisfy are not declared in the text: the sheet checks them itself and refuses outside them, so the comparing lines of the text that mention the field are returned as guards.

### 模組庫與公式庫

#### `library_list`

- **用途**：線上模組庫（OpenAEC Foundation 公開倉庫）全部模組：id、版本、是否已安裝；refresh 強制重抓。⚠ 連外
- **類別／特性**：讀取；唯讀、冪等、連外
- **REST 路由**：`GET /api/v1/library`、`POST /api/v1/tools/library_list`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `refresh` | boolean |  | Fetch the catalog again. Default: only the first time. |

> The online module library (the public module repository of the OpenAEC Foundation): every module with id, version, name, category, status and norms, and whether it is installed (and an update is available). refresh=true fetches the catalog again. Needs internet.

#### `library_install`

- **用途**：由模組庫安裝／更新模組（用 id）。⚠ 連外
- **類別／特性**：改動專案；會改動、非冪等、連外
- **REST 路由**：`POST /api/v1/library/{id}/install`、`POST /api/v1/tools/library_install`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Module id from library_list. |

> Install (or update) a module from the online module library by id (see library_list). It then appears in modules_list and can be added with sheet_add; existing sheets keep their own copy of the text. Needs internet.

#### `library_remove`

- **用途**：移除由模組庫裝的模組；同 id 內建模組會回復
- **類別／特性**：改動專案；會改動、破壞性、冪等
- **REST 路由**：`DELETE /api/v1/library/{id}`、`POST /api/v1/tools/library_remove`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Module id. |

> Remove a module installed from the online module library. A built-in module with the same id comes back; sheets already in the project keep their text.

#### `formulas_list`

- **用途**：搜尋公式庫（力學與 Eurocode EN 1990~1999 標準公式），可依 query／group 篩選
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/formulas`、`POST /api/v1/tools/formulas_list`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `query` | string |  | Search text. |
| `group` | string：10 個選項（見 `tools/list`） |  | Group id. |
| `includeCode` | boolean |  | Include the calculation text. Default false. |

> Search the formula library: standard formulas from mechanics and the Eurocodes (EN 1990, 1991, 1992, 1993, 1995) as ready-to-run calculation text. query searches names, explanations, sources and code; group limits to one group. includeCode=true adds the calculation text. Insert one with sheet_insert_formula. Formulas with library are the worked examples of the app's Library panel; these and the beams and sections, whose drawing follows the input, have their text lines in Dutch in code and in English in codeEn.

#### `formula_get`

- **用途**：讀單一公式與其計算文字
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/formulas/{id}`、`POST /api/v1/tools/formula_get`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 | Formula id. |

> One formula from the formula library, with its calculation text.

### 匯出與列印

#### `ifc_get`

- **用途**：取整個專案或單一工作表的 IFC 文字：format=ifcx（IFCX JSON）或 ifc（STEP）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/export/ifc`、`POST /api/v1/tools/ifc_get`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `format` | string：`ifc`／`ifcx` | 是 | ifc = STEP, ifcx = JSON. |
| `id` | string |  | Sheet id. Default: the whole project. |

> The IFC of the whole project or one sheet, as text: format 'ifcx' (IFCX JSON, the same document as the project file: every sheet with its text, input and results, and the report) or 'ifc' (IFC4X3 STEP with the same content: every sheet as a document and property sets). Without id the whole project. To write it to a file, use export_ifc.

#### `export_ifc`

- **用途**：把 IFCX（.ifcx）或 IFC（STEP .ifc）寫到檔案
- **類別／特性**：檔案 I/O；會改動、冪等
- **REST 路由**：`POST /api/v1/export/ifc`、`POST /api/v1/tools/export_ifc`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `format` | string：`ifc`／`ifcx` | 是 | ifc = STEP, ifcx = JSON. |
| `path` | string | 是 | Absolute path of the file to write. |
| `id` | string |  | Sheet id. Default: the whole project. |

> Write the IFCX (.ifcx, the same document as the project file) or IFC (STEP, .ifc) of the whole project or one sheet to a file. Desktop app only.

#### `export_pdf`

- **用途**：經 report engine 寫計算書 PDF（封面＋工作表）。⚠ 一般安裝版回 501 NOT_AVAILABLE，含圖 PDF 只能 App 內按『Rapport』
- **類別／特性**：檔案 I/O；會改動、冪等
- **REST 路由**：`POST /api/v1/export/pdf`、`POST /api/v1/tools/export_pdf`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string | 是 | Absolute path of the PDF (.pdf is added when missing). |
| `ids` | array<string> |  | Sheet ids. Default: every calculation sheet. |

> Write calculation sheets to a PDF file through the report engine (a cover page plus the sheets; without drawings). Only available in an app build that includes the report engine; otherwise NOT_AVAILABLE. The full structural report with drawings is printed through the app's print dialog: use print and choose a PDF printer there.

#### `print`

- **用途**：觸發 App 的列印（what='report' 報告 或單表）。⚠ 會開系統對話框，需人在場
- **類別／特性**：介面操作；會改動、非冪等
- **REST 路由**：`POST /api/v1/print`、`POST /api/v1/tools/print`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `what` | string：`report`／`sheets` | 是 | The structural report or calculation sheets. |
| `ids` | array<string> |  | Only for sheets: these sheet ids. Default: all. |

> Print from the app, as the Print buttons do: what='report' for the structural report (cover, chapters, sheets in appendix A), what='sheets' for calculation sheets (ids, default all). The system print dialog opens in the app; the user picks the printer there, or a PDF printer to save a PDF. The app waits until the dialog is closed.

### 檢視與設定

#### `view_get`

- **用途**：讀目前工作表的檢視模式（code-visual／code-output／visual-output／print-preview／ifc）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/view`、`POST /api/v1/tools/view_get`
- **參數**：無

> The view of the open sheet in the app: code-visual, code-output, visual-output, print-preview or ifc.

#### `view_set`

- **用途**：切換目前工作表的檢視模式
- **類別／特性**：介面操作；會改動、冪等
- **REST 路由**：`PUT /api/v1/view`、`POST /api/v1/tools/view_set`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `view` | string：`code-visual`／`code-output`／`visual-output`／`print-preview`／`ifc` | 是 | The view. |

> Choose the view of the open sheet in the app: 'code-visual' (code and drawing), 'code-output' (code and worked-out calculation), 'visual-output' (drawing and calculation), 'print-preview' (the printout of the open sheet, or of the report when the report is open), or 'ifc' (the IFC of the whole project). A sheet without a drawing shows code and calculation.

#### `settings_get`

- **用途**：讀 App 設定：主題、語言、文字大小、單位（角度模式、預設顯示單位）
- **類別／特性**：讀取；唯讀、冪等
- **REST 路由**：`GET /api/v1/settings`、`POST /api/v1/tools/settings_get`
- **參數**：無

> The app settings: theme, language, text size and units (angle mode, default display units).

#### `settings_set`

- **用途**：改 App 設定（theme、language、textSize、units）
- **類別／特性**：改動專案；會改動、冪等
- **REST 路由**：`PATCH /api/v1/settings`、`POST /api/v1/tools/settings_set`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `theme` | string：`light`／`dark`／`blueprint`／`high-contrast-dark`／`high-contrast-light` |  |  |
| `language` | string：`auto`／`en`／`nl` |  |  |
| `textSize` | string：`compact`／`standard`／`large` |  |  |
| `units` | object |  |  |

> Change app settings, as Settings does: theme, language ('auto' follows the system), textSize, and units (any subset of angleMode, defaultLength, defaultForce, defaultStress, returnAngleUnits, stelsel). Takes effect immediately and is saved.
