# 七套 CAD 工具／技能能力邊界與重疊度評估

> 評估日期：2026-10-28（原六套）｜**2026-11-03 追加 IngeTrazo 0.6.0**
> 範圍：CADCraft CLI、SolidCraft、Blender 技能、AutoCAD MCP、text-to-cad（cadgen）、CadCraft Studio（8 apps）、**IngeTrazo**
> 方法：**以本機實測為準**（版本、指令數、工具數、實際出圖與轉檔）；IngeTrazo 為本機安裝＋官方文件＋原始碼查證，**建模尚未實跑**，已標示。
> 目的：回答「這七套各自能到哪裡、哪裡互相重疊、本專案該用哪一套」。

---

## 0. 一句話結論

| 問題 | 答案 |
|---|---|
| 誰能**產交付級 2D 圖紙**（A3／圖框／視口／DWG） | **CADCraft CLI**（相容 >80% AutoCAD 功能，支援跨平台產出 DWG 與出圖）、**AutoCAD MCP**、CADCraft Studio 的 CadCraft。本專案以 `make_sheet.py`＋`acc.py`（Windows）或 CADCraft CLI 產出標準交付 DWG |
| 誰能**做 3D 實體** | **SolidCraft**、**text-to-cad**（皆參數化精確實體）；Blender 只做網格／渲染，不算實體 CAD |
| 誰能**做 3D 建築／土木 BIM 並出 IFC4＋數量** | **IngeTrazo**（GUI＋MCP 橋；IFC4、數量 CSV、比例 PDF／公尺 DXF） |
| 誰是**唯一沒有替代品**的 | CadCraft Studio 的 **CivilCraft（地形／土方／LandXML）**、**TakeoffCraft（圖面數量）**；以及 **Blender 的渲染／動畫**（IngeTrazo 可出 3D 示意圖與剖面，但不取代渲染管線） |
| 最大誤用風險 | 拿 AutoCAD MCP 當「土木出圖機」（它講 mm／ISO 製造語彙）；拿 Blender 當 CAD；拿 SolidCraft 排 A3 |

**重疊的本質**：七套裡真正互相重疊的有三群——
① **2D 圖面生產群**（CADCraft CLI ≈ AutoCAD MCP ≈ Studio/CadCraft）；
② **3D 參數化實體群**（SolidCraft ≈ text-to-cad）；
③ **3D 幾何／視覺群**（IngeTrazo ≈ Blender 的網格與示意，部分 ≈ Studio/CivilCraft 的地形）。
其餘四處（地形土方、圖面數量、渲染、細節圖庫）**彼此不重疊，也沒有替代品**。

---

## 1. 七套到底是什麼（本質分類）

| # | 名稱 | 實際實體（本機路徑） | 版本（實測） | 執行模式 | 幾何核心 | 原生格式 |
|---|---|---|---|---|---|---|
| 1 | **CADCraft CLI** | `C:\Program\ArtCraft\CADCraft\cadcraft-cli.exe` | **0.13.0** | **headless CLI**（另有 GUI `cadcraft.exe`），自帶 `mcp` 子命令 | 自研 2D DXF/DWG 引擎 | DXF／DWG／PDF／SVG／PNG |
| 2 | **SolidCraft** | `C:\Program Files\SolidCraft\solidcraft-cli.exe` | **0.25.1** | **headless CLI** ＋ GUI ＋ `mcp` 子命令 | 參數驅動特徵樹（布林實體） | `.solidcraft`／STEP／STL／3MF |
| 3 | **Blender 技能** | `~\.agents\skills\blender\`（Store 5.2.3，經 `blender-launcher.exe`） | **5.2.3** | headless（`--background`）；另有 MCP 但**必須搭 GUI** | 多邊形網格（非精確實體） | `.blend`／STL／OBJ／PLY／GLB／GLTF |
| 4 | **AutoCAD MCP** | `~\.mcp\autocad-mcp-pro`（1.6.0，Claude Code 用）／`~\.agents\mcp\autocad-mcp-pro`（1.7.0，Codex 用） | **1.6.0／1.7.0** | MCP stdio（`ezdxf` 純 DXF 後端；`com` 後端已禁用） | `ezdxf`（Python）＋可選 ODA | DXF（DWG 需外部工具） |
| 5 | **text-to-cad 技能**（`cad`／`dxf`） | `~\.agents\skills\cad`｜引擎 `cadgen==0.7.26`（`uvx` 安裝） | cadgen **0.7.26** | `uvx` 執行的 Python 腳本 ＋ headless viewer | **build123d／OpenCASCADE**（B-rep） | STEP／STL／3MF／GLB／DXF |
| 6 | **CadCraft Studio** | `C:\Program\CadCraft Studio\`（shell 0.7，8 apps） | **0.7** | **只有本機 HTTP MCP**，需人開視窗＋每次換 token | 8 個 Web 技術 app 各自 | 依 app（DXF／DWG／LandXML／PDF／xlsx） |
| 7 | **IngeTrazo** | `C:\Program Files\IngeTrazo\`（`ingetrazo.exe`＋`ingetrazo-mcp.exe`） | **0.6.0** | **GUI 常駐＋stdio MCP 橋**（`127.0.0.1:4763`）；**無 headless** | 自研推拉實體／BIM（Z-up、公尺） | `.igz`／IFC4／DXF／PDF／DAE／glTF／OBJ／STL |

### 1.1 CadCraft Studio 的 8 個 app（實測目錄確認）

`cadcraft`／`civilcraft`／`takeoffcraft`／`detailcraft`／`partcraft`／`bimcraft`／`modelcraft`／`markupcraft`

**關鍵事實（推論，依據：同名產品線、指令語彙一致、CLI 亦有 `mcp` 子命令）**：
Studio 內的 **CadCraft app 與本機 `cadcraft-cli.exe` 是同一產品家族的同一引擎**，只是一個有 GUI 外殼、一個是 headless。
→ **Studio 不另計一套**（它是「CadCraft ＋ 7 個旁支 app」的套裝；其中只有 CivilCraft／TakeoffCraft 是別處沒有的能力）。
第 7 套是 **IngeTrazo**，與 Studio 無關。

---

## 2. 能力邊界（逐套，實測口徑）

### 2.1 CADCraft CLI（441 個指令）

選單分佈（實測統計）：`Tools 72／Draw 52／Modify 51／View 29／Format 29／Dimension 28／File 19／Edit 13／Insert 4／Window 1`

| 能做 | 實測證據 |
|---|---|
| 完整 2D 繪圖／編修（線、圓、弧、聚合線、文字、Hatch、標註、圖層、圖塊） | `commands` 441 筆，含 `mview`／`viewport.set`／`plot`／`dimension` 系列 |
| **圖紙空間＋視口＋鎖比例＋出 PDF／PNG／SVG** | 對既有交付 A3 DXF 執行 `run --cmd plot`：**PDF 86,510 B，墨量 4.45%**（AutoCAD 出圖 76.2 KB／4.17%） |
| **DXF ↔ DWG 轉檔** | `convert`：54,398 B，回讀 entity 數 **完全一致**（見 §6.2） |
| 當 MCP server 用 | `cadcraft-cli mcp [--connect HOST:PORT]` |
| 效能／樣本／腳本重放 | `perf`／`sample`／`run --script-file` |

| 不能做 | 說明 |
|---|---|
| 3D 實體 | 純 2D，無布林實體 |
| 地形、土方、LandXML | 無 |
| 圖面數量自動計算 | 只能靠自寫腳本 + `--cmd` 查詢 |
| 台灣土木語彙（TOMO／TWD97／A3 圖框契約） | **一律得自己寫**（本專案已寫在 `make_sheet.py`／`drawing_rules.py`） |
| `--cmd` 之外的批次自動化 | 需自行組 JSON 指令鏈（`{last}` 支援串接） |

> **對本專案最重要的一條**：`plot` 能完整重現既有 A3 交付圖（視口內容、圖框、標題欄、技師圖記區、中文全部正常），
> 所以**「出 PDF／PNG 預覽」這一段可以完全脫離 AutoCAD**。

### 2.2 SolidCraft（493 個指令）

| 能做 | 實測證據 |
|---|---|
| 參數驅動特徵樹建模（box／cylinder／extrude／revolve／sweep／fillet／chamfer／shell／hole／pattern／combine） | `commands` 493 筆 |
| 改參數整條時間軸重建 | `parameters.change`；回歸測過 H 3000→3500 mm 外框即變 |
| 幾何自檢（體積／面積／bbox／面數／水密／質量） | `eval --in` 回 JSON；本專案 3 個案例誤差 0.000% |
| STEP／STL／3MF 匯出、頭像／渲染（GPU） | `run --out`／`snapshot`／`render`（`--overwrite`） |
| 當 MCP server 用 | `solidcraft-cli mcp --headless`；`mcp setup --client claude-code` 可自動註冊 |
| 剖面／透視／工具體可視化 | `snapshot --section z=27`／`--tool`／`--body opacity` |

| 不能做 | 說明 |
|---|---|
| **2D 圖紙空間／A3 圖框／DWG** | 完全沒有。`file.export_view_dxf` 只是視圖線稿，不是圖紙 |
| 配筋圖、鋼筋實體自動生成 | 需手工以圓柱體堆（本專案擋土牆範例即如此） |
| 地形／土方／測量 | 無 |
| 中文標註與出圖規範 | 無（不是它的職責） |

### 2.3 Blender 技能（5.2.3）

| 能做 | 限制 |
|---|---|
| headless 批次：`bpy` 腳本、渲染 PNG、**STL/OBJ/PLY/GLB/GLTF 互轉** | **launcher 不回傳 stdout** → 結果一律寫 `--result` JSON |
| 材質／燈光／鏡頭／動畫／序列輸出（Cycles／EEVEE／Workbench） | EEVEE 在 headless 需 GPU context，失敗要退 Workbench |
| MCP（`mcp-for-blender`，9876） | **必須開 GUI**；`--background` 下 addon 只 accept 連線**不回命令** |

| 不能做 | 說明 |
|---|---|
| **精確實體 CAD（B-rep）** | 網格為主。沒有 STEP；不能做布林公差、配合、工程圖 |
| 2D 圖紙／DWG | 無 |
| 尺寸驅動的參數化（工程意義上） | 只有 Geometry Nodes／driver，不是工程特徵樹 |

> 定位：**「做出來的東西怎麼好看／怎麼動」**，不是「怎麼精確、怎麼交圖」。

### 2.4 AutoCAD MCP（242 個工具，1.6.0 實測）

工具分佈（`tools/list` 實測）：`entity_* 40／drawing_* 30／layer_* 16／system_* 12／arch_* 12／analysis_* 10／pid_* 9／block_* 8／view_* 7／dimension_* 6／layout_* 6／mech_* 6／viewport_* 5／hatch_* 4／…`

| 能做 | 備註 |
|---|---|
| 2D 圖元全覆蓋（line／circle／arc／polyline／hatch／spline／wipeout／revcloud／table／mleader） | `entity_create_*` ＋ `entity_batch_*` |
| **圖層狀態／圖塊／標註型式／UCS／版面視口／出圖（`plot_style_list`／`batch_plot`）** | 圖紙空間操作完整 |
| **圖面量測與盤點**（`analysis_measure_area`／`measure_entity`／`select_by_layer`／`layer_stats`／`bounding_box`） | 本專案驗證過：建物 120／64 m²、含中庭 146 m² 扣洞全正確 |
| 讀別人圖：`drawing_understand`／`drawing_diff`／`drawing_topology_check`／`drawing_scale_check` | ⚠️ `drawing_understand` 的**單位推論不可信**（把公尺圖判成英寸） |
| 建築／機械／管線專用工具 | `arch_*`（牆／開口／樓梯／房間／明細表）、`mech_*`／`gear_*`／`keyway_*`／`weld_*`／`surface_texture`、`pid_*`（P&ID）、`bom_*`、`balloon_add` |
| 出圖前檢核 | `drawing_preflight`／`drawing_deliver`／`drawing_critique`／`validation_check` |

| 不能做 | 說明 |
|---|---|
| **產交付 DWG** | `drawing_export_dwg` 需 ODA File Converter（未裝）→ 一律走 `acc.py` |
| **TOMO 中文字型** | `textstyle_create` 無 bigfont 參數 → 存檔後用 `ezdxf` 補 |
| 3D 實體建模 | 無（只有 `section_line`／`surface_texture` 這類 2D 表現） |
| 地形／土方 | 無（`pipe_takeoff`／`cable_takeoff` 只是長度統計） |
| **台灣土木語彙** | ❗這是它最大的邊界：**它的預設是 mm／ISO／製造與建築**（`drawing_apply_iso_layers`、`titleblock_apply_iso_a3`、`drawing_apply_standard`）。本專案要的 m／TWD97／TOMO／`數字_中文` 圖層，它**一樣都沒有** |

### 2.5 text-to-cad 技能（cadgen 0.7.26 ＋ build123d）

| 能做 | 備註 |
|---|---|
| **參數化 3D 實體**（Python 腳本 → `@step`／`@stl`／`@threemf`／`@glb`） | 模型＝一支純 Python 腳本＋裝飾器，**天然可版控／可 diff／可 CI** |
| 組裝（多模型呼叫＋`.moved()`／`Location`） | 有 `src/` 專案版型、model catalog |
| 幾何檢查／量測／快照審閱 | `read_scene`／`read_step`；`cadgen step snapshot`；內建 CAD Viewer（`cadgen viewer --detach`） |
| 對 prompt 引用做選取解析 | `#o1.2.f7` 形式的拓撲選取 |
| 2D DXF（`dxf` 技能） | 由 build123d 草圖擠出／投影出 2D，**是「零件輪廓」，不是「圖紙」** |
| 現成零件庫查詢 | `$step-parts`（step.parts 目錄） |

| 不能做 | 說明 |
|---|---|
| 圖紙空間／A3 圖框／視口／DWG | 無 |
| 地形／土方／數量表 | 無 |
| **離線可用** | ❗首次要 `uvx` 從網路下載 cadgen 0.7.26 ＋ headless browser；**斷網即不可用** |
| 中文出圖規範 | 無 |

### 2.6 CadCraft Studio（8 apps）

| app | 能力邊界 | 是否別處有替代 |
|---|---|---|
| **CivilCraft** | 地形面（測點→TIN）、高程查詢、挖填方、整地／土堤／草溝、縱斷取樣、LandXML 匯出、DWG 匯出 | ❗**無替代**（本專案土方唯一可自動化路徑） |
| **TakeoffCraft** | 圖塊／圖層盤點與計數、依圖層量長度面積、計價項目、PDF 描點、估價（含損耗） | △ 部分可用 AutoCAD MCP `analysis_*`＋自寫 ezdxf 替代，但沒有估價 |
| **CadCraft** | 同 CADCraft CLI（GUI 版） | ✅ CLI 完全替代 |
| **PartCraft** | 零件／機械件 3D | ≈ SolidCraft／text-to-cad（推論） |
| **DetailCraft** | 細部大樣／詳圖 | △ 本專案現用「Detail Manager 圖庫＋手繪 ezdxf」 |
| **BimCraft** | BIM 元件／建築模型 | ✗ 本專案用不到 |
| **ModelCraft** | 3D 模型呈現 | ≈ Blender（推論） |
| **MarkupCraft** | 圖面標註／紅線 | ≈ AutoCAD MCP `entity_create_revcloud`／`markup` 類（推論） |

**共同硬限制**：**沒有 headless CLI**。必須「人開視窗 → Settings › Assistants 開連線 → 把 token 給 AI → Folders 加 `<專案根目錄>`」，
且 **token 在 Studio 重啟後失效、要人手動換**。→ **不能進自動化產線**，只能當「需要時人工開的資料處理機」。

### 2.7 IngeTrazo 0.6.0（GUI＋MCP 橋）

> 依據：本機安裝實查（`C:\Program Files\IngeTrazo\`）＋官網＋官方手冊＋`ingetrazo_mcp.py` 原始碼。
> **建模端到端尚未實跑**（需 GUI 開文件＋AI Bridge）；下列能力為文件與程式碼口徑。

| 能做 | 備註 |
|---|---|
| **精確 3D 建模** | 推拉時直接輸入尺寸；**公尺制、Z-up**；布林／旋轉體／擠出；實體需過水密（hermeticity）檢查 |
| **BIM 與數量** | 牆／版／柱／門窗標記 → **IFC4** 匯出＋**數量 CSV** |
| **地形與測量** | 3D 衛星地形、縱斷面、專案北；WebODM 無人機網格；GPS／全測站 **UTM CSV** |
| **出圖** | 具比例的 **PDF 圖紙**（圖框、尺寸、標題欄、多張圖紙）；目前視圖匯出 **DXF（公尺）** 給 IngeCAD |
| **格式** | 匯入 DWG／DXF／SKP（OpenSKP）／OBJ／DAE／glTF／STL；匯出 DAE／glTF／OBJ／STL／IFC4／DXF／PDF |
| **AI 協作** | 內建助手（自備 key／Ollama）；**MCP 橋**讓外部智能體在開著的視窗即時建模：`run_python`／`query_model`／`screenshot`／`undo`／`redo` |
| **資產** | 1,510 個元件、427 種材質；Blender 外掛算圖 |

| 不能做 | 說明 |
|---|---|
| **headless／批次** | ❗無 CLI 建模模式；必須 GUI 常駐、文件已開、**Extensões ▸ AI Bridge (MCP)** 已啟動 |
| **本專案交付契約** | ❗無 TWD97／TOMO（`gbenor.shx`＋`CHINA1.SHX`）／`數字_中文` 圖層／`A3圖框.dwt`／**DWG 2018** |
| **座標系直接沿用** | ❗地形與 GPS 是 **UTM WGS84**，不是 `EPSG:3826`；未轉換就帶入 TWD97 圖面必錯 |
| **STEP** | 匯出清單沒有 STEP；要給廠商 CNC 仍用 SolidCraft／text-to-cad |
| **多客戶端** | 官方明講一次只接受一個 MCP 客戶端，且只聽 `127.0.0.1` |
| **圖紙空間可程式化排版** | PDF 有自己的版面邏輯，但沒有本專案 `make_sheet.py` 的三區挖空與 E1~E18 品管 |

**本專案定位**：`3D 構造建模 ＋ BIM 數量 ＋ 地形剖面 ＋ 示意出圖`。
交付檔案仍回 `make_sheet.py` → `acc.py` → `check_delivery.py`；IngeTrazo 的 PDF／DXF 只當「參考圖／中間幾何」。

---

## 3. 重疊度矩陣

> 3＝高度重疊（可互換）；2＝部分重疊（功能交集明顯）；1＝邊緣接觸；0＝無關
> CC＝CADCraft CLI｜SC＝SolidCraft｜BL＝Blender｜AM＝AutoCAD MCP｜TC＝text-to-cad｜CS＝CadCraft Studio｜IZ＝IngeTrazo

| | CC | SC | BL | AM | TC | CS | IZ |
|---|---|---|---|---|---|---|---|
| **CC** CADCraft CLI | — | 0 | 1 | **3** | 1 | **3** | 1 |
| **SC** SolidCraft | | — | 1 | 1 | **3** | 2 | 2 |
| **BL** Blender | | | — | 0 | 2 | 2 | 2 |
| **AM** AutoCAD MCP | | | | — | 1 | 2 | 1 |
| **TC** text-to-cad | | | | | — | 2 | 0 |
| **CS** Studio | | | | | | — | 2 |
| **IZ** IngeTrazo | | | | | | | — |

### 3.1 重疊解讀

**重疊群 A：2D 圖面生產（CC ↔ AM ↔ CS/CadCraft）＝可互換度約 80%**
三者的交集是「2D 圖元＋圖層＋圖紙空間＋出圖」。差異只在**執行模式與語彙**：

| | CADCraft CLI | AutoCAD MCP | Studio/CadCraft |
|---|---|---|---|
| 執行 | headless，最適合自動化 | MCP，最適合「AI 邊想邊改」 | GUI，人手操作 |
| 出 PDF | ✅ 實測可 | ✅（matplotlib 僅預覽，交件用 `acc.py`） | ✅ |
| 出 DWG | ✅ 實測無損 | ✗ 需 ODA | ✅ |
| 工具數 | 441 指令 | 242 tools | 同 CLI |
| 台灣土木語彙 | 無 | 無 | 無 |

**重疊群 B：3D 參數化實體（SC ↔ TC）＝可互換度約 70%**
同為「參數→精確實體→STEP」。差異是**表達方式**：

| | SolidCraft | text-to-cad |
|---|---|---|
| 模型定義 | JSON 命令腳本／GUI 特徵樹 | **純 Python 腳本**（build123d） |
| 版控友善度 | 中（`.solidcraft` 二進位容器＋腳本） | **高**（`.py`，可 git diff／code review） |
| 自檢 | `eval` 給體積／bbox／面數／水密 | 自己寫 build123d 檢查＋快照 |
| 現成土木範本 | **有**（U 型溝／擋土牆／沉頭孔平板，本專案已建） | 無（要自己寫） |
| 離線 | ✅ 完全離線 | ✗ 首次需 `uvx` 連網下載 |
| 3MF／GLB | 3MF ✅ | 4 種格式全支援 |

**重疊群 C：3D 幾何／視覺（IZ ↔ BL ↔ CS/CivilCraft；IZ ↔ SC 部分）＝可互換度約 40%**
交集是「立體幾何＋看得到」，但**產物與用途不同**：

| | IngeTrazo | Blender | Studio/CivilCraft | SolidCraft |
|---|---|---|---|---|
| 幾何 | 推拉實體＋BIM 標記 | 多邊形網格 | 地形 TIN／土方 | 參數特徵樹（B-rep） |
| 數量 | ✅ IFC4＋CSV | ✗ | ✅ 土方／挖填 | ✅ 體積自檢 |
| 座標 | UTM WGS84（需轉換） | 任意 | 可設 EPSG:3826（需人工） | 區域座標／mm |
| 交付 | 比例 PDF／公尺 DXF | 渲染圖／動畫 | LandXML／DWG | STEP／STL |
| 自動化 | MCP（GUI 需開） | headless `--background` | 無 headless、token 人工 | headless CLI |

**不重疊的部分（真正不可替代）**

| 能力 | 唯一提供者 | 對本專案的價值 |
|---|---|---|
| 地形／挖填方／LandXML | Studio/CivilCraft | 土方量、整地設計 |
| 圖面數量＋估價 | Studio/TakeoffCraft | 與 GridCraft 預算書接合 |
| 渲染／動畫／材質 | Blender | 給業主看的 3D 示意 |
| 2D 圖紙空間的**可程式化**排版 | CADCraft CLI／AutoCAD MCP | 本專案已用 `make_sheet.py` 做得更好 |

---

## 4. 本專案建議分工（決策表）

> 前提：交付契約是 **m／TWD97 TM2／TOMO／A3 1:600-1:700／DWG 2018 ＋ `check_delivery.py` 退出碼 0**。七套裡**沒有任何一套原生支援這套契約**，所以主線必須是自建工具鏈，其餘七套只補「它做不了的那一段」。

| 工作 | 用哪一套 | 理由（實測） |
|---|---|---|
| 現況底圖（NLSC／OSM／建物 SHP） | `tools\site_basemap`（自建） | 七套都沒有國土測繪圖資接取 |
| A3 圖紙排版＋視口裁切 | `tools\a3_sheet\make_sheet.py`（自建） | 已內建三區挖空；CADCraft／MCP 都要自己重寫 |
| **交件 DWG** | **`tools\acad\acc.py`（accoreconsole）** | 規範要求 AutoCAD 2018；`acc.py` 是既有驗收路徑 |
| **PDF／PNG 預覽** | **可改走 `cadcraft-cli run --cmd plot`** | 實測完整重現、免 AutoCAD、無 COM 衝突風險 |
| 交件品管 | `check_delivery.py`（自建） | E1~E18 是為本專案契約寫的；`drawing_critique` 只報 ISO 規則 |
| 圖面編修／補標註／盤點既有 DWG | **AutoCAD MCP**（242 tools） | 量測與圖層統計實測正確；適合「讀別人圖」 |
| 2D 幾何批次生成／換算 | `cadcraft-cli` 或 `ezdxf`（自寫） | CLI 適合指令鏈；複雜邏輯仍建議純 `ezdxf` |
| **3D 斷面／擋土牆／溝渠** | **SolidCraft** | 專案已完成 U 型溝／擋土牆範本＋體積自檢流程 |
| 需要 STEP 給外部廠商／要 git 版控模型 | text-to-cad（cadgen） | 純 Python 可 diff；但**要連網安裝**，離線案場不可用 |
| 3D 示意圖／動畫給業主 | Blender | 唯一渲染／動畫路徑 |
| **3D 建築／構造 BIM、IFC4、數量 CSV** | **IngeTrazo**（GUI＋MCP 橋） | 唯一能出 IFC4＋BIM 數量；需 GUI 開文件＋AI Bridge |
| 地形剖面／無人機地形／3D 透視 | IngeTrazo（土方仍用 CivilCraft） | 讀 WebODM 網格與 UTM CSV；**剖面可看，土方計算不取代 CivilCraft** |
| 土方／整地／LandXML | **Studio/CivilCraft**（人工開窗） | 無替代；但**先請使用者改公制＋EPSG:3826** |
| 圖面數量／估價 | **Studio/TakeoffCraft**（人工開窗） | 有估價與損耗，MCP 沒有 |
| 細部大樣 | `G:\...\Detail Manager` 圖庫 ＋ ezdxf | 圖庫比任何工具都重要 |

### 4.1 紅線（不要做的事）

1. **不要用 AutoCAD MCP 產交件 DWG** — `drawing_export_dwg` 需 ODA（未裝），且它不懂 TOMO。
2. **不要用 AutoCAD MCP 的 ISO／mm 預設值直接出圖** — `titleblock_apply_iso_a3`／`drawing_apply_iso_layers` 是 mm＋ISO 語彙，與本專案 m／自訂圖框衝突。
3. **不要拿 Blender 當 CAD** — 無 STEP、無 B-rep、無工程圖；它只負責好看。
4. **不要在 Studio 上做批次／自動化** — 無 headless、token 每次重啟失效，且屬於「需人配合」的環節。
5. **不要用 SolidCraft 排 A3** — 它沒有圖紙空間概念。
6. **不要用 text-to-cad 於離線案場** — 首次需 `uvx` 下載。
7. **不要相信 `drawing_understand` 的單位推論** — 已實測會把公尺圖判成英寸。
8. **不要把 IngeTrazo 的 UTM 座標直接當 TWD97** — 地形／GPS 是 WGS84 UTM，與 `EPSG:3826` 不同；未轉換就疊圖必偏移。
9. **不要拿 IngeTrazo 的 PDF／DXF 交件** — 沒有 TOMO、沒有本專案 A3 圖框、沒有 DWG 2018；交件仍走 `make_sheet.py`＋`acc.py`。
10. **不要排 IngeTrazo 無人批次** — 無 headless，且一次只接受一個 MCP 客戶端；關掉 GUI 就全斷。

---

## 5. 需要修正的舊紀錄（本次實測推翻）

### 5.1 「`cadcraft-cli convert` 產出的 DWG 缺圖紙空間」→ **不再成立**

舊紀錄（`docs\經驗索引_INDEX.md` EXP-B1、`docs\踩坑紀錄.md` §L）說
「`cadcraft-cli convert` 產出的 DWG 僅 53 KB 且缺圖紙空間，DWG 必用 `accoreconsole`」。

**2026-10-28 實測（CADCraft CLI 0.13.0）**：

| 測試 | 來源 | 產出 | 回讀結果 |
|---|---|---|---|
| A3 配置圖 | `大雅區六寶里…_A3.dxf`（model 68 ＋ layout 100） | `convert` → DWG **54,398 B** | `acc.py todxf` 回讀：**model 68／layout 100 entity 完全一致**、3 個 IMAGE 都在、23 圖層、TOMO、`$INSUNITS=6` |
| 純模型圖 | `AC刨鋪…_現況平面圖_TWD97.dxf` | `convert` → DWG **50,686 B** | 回讀：model 68 一致、`Layout1` 保留 |

→ **entity 完全無損，圖紙空間也保留**（54 KB 只是 DWG 壓縮／表示差異；AutoCAD 產的是 136,713 B）。
舊紀錄應屬**早年版本行為**或**當時把「檔案小」誤判為「缺圖紙空間」**。

**相容性與交付建議更新**：CADCraft 可相容 >80% 以上 AutoCAD 功能，且具備跨平台直接產出 DWG 格式設計圖能力。在具備原生 AutoCAD 的 Windows 環境下可由 `acc.py` 產出 2018 版 DWG；在未安裝 AutoCAD 或非 Windows 平台（如 Linux、macOS）時，可直接由 CADCraft CLI 產出標準 DWG 格式交付件，完整保留圖紙空間、視口內容與外部圖層配置。

### 5.2 版本漂移（文件與實機不一致，已於本檔更新）

| 工具 | 文件寫的 | 實測 |
|---|---|---|
| SolidCraft | 0.24.0 | **0.25.1**（指令 493，非 474） |
| AutoCAD MCP | 1.6.0（Claude Code）／1.7.0（Codex） | 一致（242／243 tools） |
| CADCraft CLI | 文件未標 | **0.13.0** |
| Blender | 5.2.3 | 一致 |
| IngeTrazo | 0.6.0 | **0.6.0**（GUI 與 `ingetrazo-mcp.exe` 同安裝；建模端到端待實跑） |

---

## 6. 實測證據附錄（可重跑）

### 6.1 指令／工具數

```
cadcraft-cli commands                          → 441 指令（Tools72/Draw52/Modify51/View29/Format29/Dimension28/File19/Edit13/Insert4/Window1）
solidcraft-cli commands | grep -c '"id"'        → 493
autocad-mcp tools/list（ezdxf，1.6.0）          → 242 tools
C:\Program\CadCraft Studio\app\apps\            → 8 個 app 目錄
python tools\ingetrazo\ingetrazo_check.py       → 安裝路徑＋橋＋5 tools（--call 需 GUI 開橋）
```

### 6.2 CADCraft 出圖與轉檔

```
:: A3 配置 → PDF
cadcraft-cli run "<A3.dxf>" --cmd 'plot {"path":"out.pdf","layout":"全區工程位置圖","landscape":true,"plotArea":"layout","fit":false,"scale":1.0}'
→ {"bytes":86510,"layout":"全區工程位置圖","pages":1}
   PyMuPDF 110 dpi 比對：cadcraft 墨量 4.45% ／ AutoCAD 4.17%

:: DXF → DWG
cadcraft-cli convert "<A3.dxf>" out.dwg        → 54,398 B
acc.py todxf out.dwg 回讀                       → model 68、layout 100、IMAGE 3、圖層 23、TOMO、$INSUNITS=6
```

### 6.3 證據檔案位置

`<專案根目錄>\_cad_assess\`（遷移前舊路徑的產物，現已不存在）：`cadcraft_plot.pdf`／`cadcraft_plot.png`／`acad_plot.png`／`cadcraft_conv.dwg`／`cadcraft_conv_回讀.dxf`／`model_only.dwg`／`model_only_回讀.dxf`

---

## 7. 一句話收束

> **七套裡有三套在做同一件事（2D 圖面）、兩套在做同一件事（3D 參數化實體）、IngeTrazo 另佔「3D BIM＋地形＋示意出圖」一段；只有四件事沒人替代（地形土方、圖面數量、渲染、圖庫）。**
> 本專案的正確姿勢不是「選一套全包」，而是：**自建工具鏈守住契約 → 缺哪一段補哪一套**。
