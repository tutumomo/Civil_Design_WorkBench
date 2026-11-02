# 口語操作手冊：ArtCraft 15 套＋SolidCraft／Blender／text-to-cad／AutoCAD MCP

> 建立：2026-10-29（2026-11-02 新增 `TextureCraft` 與 `Craft Anything`）｜全部本機實測。
> 用途：使用者用口語下令 → 智能體查本表決定用哪套、怎麼下指令，**一律走無視窗 CLI（headless）**，不搶使用者正在用的視窗。
> 完整指令清單：`docs\artcraft_commands\<App>.txt`（SolidCraft 與 CraftAnything 為 `.json`）。查單一指令參數：`<cli> describe <id>`（Deck／Design／Sound／SolidCraft）或 `craft-anything-cli <tool> --help`，或在清單檔中搜尋。
> CAD 類能力邊界的深入評估見 `docs\六套CAD工具能力邊界與重疊度.md`，本檔不重複。

## 0. 口語 → 工具 對照（先查這張）

| 使用者說的話（例） | 用哪套 | 一句話做法 |
|---|---|---|
| 「出圖／轉 DWG／DXF 轉 PDF、PNG」 | **CADCraft**（相容 >80% 以上 AutoCAD 功能，支援直接產出 DWG 與出圖；土木交件亦可走 `make_sheet.py`＋`acc.py`） | `cadcraft-cli convert IN.dxf OUT.dwg`（或 `OUT.pdf`） |
| 「畫一條線／改圖層／量面積」（2D 編修） | **CADCraft** `run --cmd`；或 AutoCAD MCP（見 §3 警告） | `run in.dxf --cmd 'line {...}' --save out.dxf` |
| 「做一個 3D 實體／擋土牆模型／出 STEP、STL」 | **SolidCraft**（參數特徵樹）或 **text-to-cad**（Python build123d） | `solidcraft-cli run script.json --out x.step` |
| 「給 3D 模型上混凝土／砌石材質、烘焙 AO／Normal 貼圖、渲染 PBR 圖」 | **TextureCraft**（3D PBR 材質貼圖與烘焙，類 Substance Painter） | `texturecraft-cli new in.glb out.tcraft --sample`；`bake`；`export`；`render out.tcraft out.png --samples 64` |
| 「把模型渲染成漂亮圖／做旋轉動畫／STL 轉 GLB」 | **Blender** 技能（或 **TextureCraft** `render`） | `blender_run.py recipe_render.py --input x.stl --out x.png` |
| 「分析這個舊程式（.exe/.dll/.apk/.asar/SQLite）怎麼算的／擷取某網站並重建」 | **Craft Anything**（全能逆向剖析與潔淨室重建平台） | `craft-anything-cli triage <target>`；`rebuild <url_or_path>`；`db-sqlite-show` |
| 「做預算表／Excel／算公式／xlsx 轉 PDF」 | **GridCraft**（預算書請走 `boq_build.py`） | `gridcraft-cli run --cmd 'cell.set={...}' --out x.xlsx` |
| 「寫報告／Word／docx 轉 PDF」 | **WordCraft**（設計報告請走 `make_report.py`） | `wordcraft-cli run --cmd ... --save x.docx`；`convert x.docx x.pdf` |
| 「做簡報／PPT」 | **DeckCraft** | `deckcraft-cli run --cmd 'slide.new={...}' --save x.pptx` |
| 「PDF 合併／拆頁／抽頁／旋轉／抽文字／OCR／轉圖」 | **PdfCraft** | `combine`／`split`／`extract`／`edit`／`text`／`render`／`batch --steps ocr` |
| 「修照片／裁切／調色／批次縮圖／PSD」 | **PhotoCraft**（像素編修） | `photocraft-cli run in.jpg --cmd ... --out out.png`；`batch` |
| 「現場照片調亮／RAW 顯影／批次匯出」 | **LightCraft**（相片庫＋顯影） | `lightcraft-cli render in.jpg -o out.jpg --set light.exposure=0.5 --size 1600` |
| 「向量圖／Logo／SVG／AI／EPS 轉檔」 | **VectorCraft**（類 Illustrator） | `vectorcraft-cli convert IN OUT.svg` |
| 「排版海報／DM／多頁印刷 PDF（PDF/X）」 | **DesignCraft**（類 InDesign） | `designcraft-cli run --in x --export out.pdf`；`validate-pdf` |
| 「UI／介面稿／Figma 檔／匯出切圖」 | **FigCraft**（類 Figma） | `figcraft-cli export x.fig -o outdir --format png` |
| 「剪影片／接片段／加音軌／匯出 MP4」 | **FilmCraft**（類 Premiere） | `filmcraft-cli import ...`；`export out.mp4 --format h264` |
| 「片頭動畫／動態字卡／特效合成」 | **EffectCraft**（類 After Effects） | `effectcraft-cli render --project x.ecproj --out out.mp4 --format h264` |
| 「錄音剪輯／轉檔／正規化音量／混音」 | **SoundCraft**（類 DAW） | `soundcraft-cli convert in out.wav --normalize` |

## 1. ArtCraft 15 套總表（實測 2026-11-02）

路徑一律由 `from project_paths import artcraft_cli` 解析（預設 `C:\Program\ArtCraft\<App>\<app>-cli.exe`，其中 `Craft Anything` 為 `C:\Program\ArtCraft\Craft Anything\craft-anything-cli.exe`）。全部支援 `mcp` 子命令（stdio MCP server），也可 `--connect/--bridge` 操作使用者已開的視窗（**需使用者同意才連視窗**）。

| App | 版本 | 指令數 | 讀寫格式（重點） | 冒煙測試 |
|---|---|---|---|---|
| CADCraft | 0.12.0~0.13.0 | 441 | DXF／DWG／SVG／PNG／PDF | 相容 >80% AutoCAD 功能，產範例 DXF→DWG/PNG ✔ |
| GridCraft | 0.12.1 | 353 | xlsx／xls／csv／tsv／json／html／pdf | A3=`=A2*2` 回讀 25 ✔ |
| WordCraft | 0.11.0 | 643 | docx／doc(讀)／pdf／odt／rtf／html／md／tex／txt／png | 中文 docx→pdf，PdfCraft 回讀文字一致 ✔ |
| DeckCraft | 0.11.1 | 327 | .deckcraft／pptx／pdf／png／jpeg／gif／md | 中文標題投影片 pptx＋png ✔（目視） |
| PdfCraft | — | 179 工具 | pdf（另 OCR、PDF/A、偽遮蔽稽核） | info／render／text ✔ |
| PhotoCraft | 0.16.0 | 940 | pcraft／psd／png／jpg／tif／webp／exr／tga／dds／dpx | 新建 400×300 輸出 png ✔ |
| LightCraft | 0.14.0 | 376 | jpg／png／tif／webp／avif／jxl／psd／dng（RAW 讀） | 曝光 +0.5 顯影輸出 ✔ |
| VectorCraft | — | 811 | ai／ait／eps／pdf／svg／psd／png… | png→svg ✔ |
| DesignCraft | 0.13.0 | 537 | 原生＋pdf（PDF/X-4 檢核） | 範例 4 頁 pdf ✔ |
| FigCraft | 0.11.2 | 597 | figcraft／fig／json／svg／png／jpg／webp／pdf | svg→png 2400×1600 ✔ |
| FilmCraft | 0.13.0 | 710 | h264／hevc／prores／dnxhr／mxf／gif／wav／aac… | 專案 inspect ✔（未實際匯出影片） |
| EffectCraft | — | 734 | ecproj；h264／hevc／av1／prores／webm／gif／png 序列 | 範例合成渲染一格 640×360 ✔（目視） |
| SoundCraft | — | 482 | wav／aiff…；.scraft 工程檔 | 範例混音 2 秒 wav，-37.8 LUFS ✔ |
| **TextureCraft** | 0.2.0 | 135 | `.tcraft`；輸入 3D 網格 `.glb/.gltf/.fbx/.dae/.usd/.abc/.obj/.ply/.stl`；匯出 PBR 貼圖與光追渲染 `.png` | `new builtin:sphere`＋`info` ✔ |
| **Craft Anything** | 0.2.0 | 314（15 toolsets） | `.cany` 調查／重建專案；讀取 `.exe/.dll/.apk/.ipa/.jar/.asar/.wasm/.pyc/.sqlite/.har` 與網站 URL；輸出 Markdown/HTML 報告與重建專案 | `commands` 314 工具盤點 ✔ |

### 1.1 新增工具詳解：`TextureCraft` 與 `Craft Anything`（2026-11-02）

#### (A) `TextureCraft`（3D PBR 材質貼圖、烘焙與光追渲染，類 Substance 3D Painter）
- **執行檔**：`C:\Program\ArtCraft\TextureCraft\texturecraft-cli.exe`（`artcraft_cli("TextureCraft")`）
- **指令清單**：[`docs/artcraft_commands/TextureCraft.txt`](artcraft_commands/TextureCraft.txt)（共 135 個引擎指令）
- **核心用途**：
  1. **直接讀取 3D 模型上材質**：支援 `.stl`、`.obj`、`.glb`、`.gltf`、`.fbx`、`.usd` 等格式（完美銜接 **SolidCraft** 匯出的土木構造物 3D 模型）。
  2. **Mesh Maps 烘焙（`bake`）**：自動烘焙 Ambient Occlusion (AO)、Curvature、World Space Normal、Position、Thickness 等貼圖。
  3. **圖層與程序化智慧材質（`layer.*` / `--sample`）**：支援 Paint Layer、Fill Layer、Procedural 雜訊（Perlin/Worley/Concrete/Rust）、Triplanar 三平面無縫投影（適合無 UV 的 CAD/STL 模型）、智慧遮罩（Edge wear / Cavity dirt）。
  4. **PBR 貼圖匯出與光追渲染（`export` / `render`）**：可將 BaseColor / Roughness / Metallic / Normal / AO 貼圖整批匯出，或直接用內建 GPU/CPU Path Tracer 渲染高畫質成果圖（`texturecraft-cli render in.tcraft out.png --size 1920x1080 --samples 64`）。

#### (B) `Craft Anything`（軟體／網站／資料庫逆向剖析與潔淨室 1:1 重建平台）
- **執行檔**：`C:\Program\ArtCraft\Craft Anything\craft-anything-cli.exe`（`artcraft_cli("Craft Anything")` 或 `artcraft_cli("CraftAnything")`）
- **指令清單**：[`docs/artcraft_commands/CraftAnything.json`](artcraft_commands/CraftAnything.json)（共 314 個工具，分屬 15 個 Toolset）
- **核心用途**：
  1. **舊有工程軟體／試算程式演算法剖析（`native` 55 / `managed` .NET 8 / `java` 6 / `formats` 36）**：
     - 針對沒有原始碼的舊版土木結構計算程式（Windows `.exe`/`.dll`、.NET 組件、Java `.jar`、Python `.pyc`、Android `.apk`），免安裝外部反編譯器即可直接抽出字串、函式呼叫圖與 **Clean-room Pseudo-C / C# / Java 反編譯碼**（`native-function-pseudocode`、`managed-ilspy-decompile`、`java-vineflower-decompile`），幫我們把舊軟體裡的經驗公式與係數表還原並改寫成工作區的標準 Python 引擎。
  2. **網站與 Web App 擷取與 1:1 重建（`browser` 22 / `javascript` 11 / `projects` 26 / `build` 6）**：
     - 輸入任何網站網址或 Electron 桌面程式（`app.asar`），自動擷取多寬度全頁截圖、DOM 結構、選單／彈窗互動狀態與 `.har` 網路封包（還能用 `web-standin-build` 自動建立離線模擬後端），並驅動 AI 完整重建前端與後端、用 `rebuild-check` 做像素級比對。
  3. **SQLite 資料庫免 SQL 結構與內容勘查（`database`）**：
     - `craft-anything-cli db-sqlite-show` 可直接檢視任何 `.sqlite` 檔案的表頭、Schema 與資料列。
  4. **AI 圖片與 3D 低面數模型生成（`assets-image-generate` / `assets-model-generate`）**：
     - 連接 `fal.ai` 生成配圖或遊戲／簡報級 `.glb` 3D 模型。

## 2. 下指令的共通規則（踩過的坑）

1. **JSON 參數一律由 Python `subprocess` 傳（list 形式）**，不要在 PowerShell 直接寫 `--cmd '{"a":1}'`：PowerShell 會吃掉雙引號。範本見 `_sandbox\artcraft_smoke\smoke.py`。
2. **參數名稱先查清單再寫**，猜錯會「靜默套用預設值」而非報錯。實例：GridCraft `cell.set` 參數是 `{cell, input}`，寫成 `{ref, value}` 時三筆全寫進 A1、退出碼仍為 0；SolidCraft `solid.box` 是 `length/width/height` 不是 `width/depth/height`。→ **每次都回讀驗證產物**。
3. **WordCraft `run` 只認一個 `--save`**：要 docx＋pdf 時先存 docx，再 `convert x.docx x.pdf`。
4. 位置單位：DeckCraft 為 pt（投影片 960×540，左上原點、y 向下）；CADCraft 為圖面單位（本專案 m）；SolidCraft 預設 mm。
5. CADCraft `run` 的 `--cmd` 可用 `"{last}"` 串接上一指令回傳的 handle。
6. 產物寫在 `D:\公司案件.AI\` 底下；MCP 模式可加 `--automation-read-root/--automation-write-root D:\公司案件.AI` 限縮檔案存取。

## 3. 非 ArtCraft 工具（狀態 2026-10-29）

| 工具 | 狀態 | 怎麼叫 |
|---|---|---|
| **SolidCraft 0.25.1** | ✔ 實測：box 2000×500×1500 mm → STEP＋STL，體積 1.5×10⁹ mm³ 正確 | `C:\Program Files\SolidCraft\solidcraft-cli.exe run script.json --out x.step --out x.stl`；細節 `docs\SolidCraft操作指引.md` |
| **Blender 5.2.3**（Store 版） | ✔ 實測：上述 STL → 渲染 PNG | `C:\Python312\python.exe %USERPROFILE%\.agents\skills\blender\scripts\blender_run.py <recipe> ... --result x.json`（stdout 拿不到，結果看 `--result`） |
| **text-to-cad（cadgen）** | ⚠ 版本不一致：PATH 上是 **0.6.5**（pip --user），技能要求 `cadgen +0.8.2` 啟動器（`~\.local\bin\cadgen` 不存在），舊文件記 0.7.26（uvx）。`step snapshot` 可用 | 建模前先 `cadgen doctor`；需新版時另議安裝 |
| **AutoCAD MCP Pro** | ⚠ **目前接的是 GUI AutoCAD（`com` 後端）**：`~\.codex\config.toml` 的 `AUTOCAD_MCP_BACKEND="com"`，與 `docs\AutoCAD_MCP操作指引.md` 記載「已改 ezdxf」不符。實測 `drawing_new` 會在使用者的 AutoCAD 開新圖；AutoCAD 忙碌時畫線回「接收者已拒絕這個呼叫」 | 改回 `ezdxf` 屬「修改 MCP 設定檔」，**須使用者點名同意**。未改前：除非使用者明說要操作他開著的 AutoCAD，否則不用此 MCP，改用 CADCraft／ezdxf |
| **CadCraft Studio**（8 apps） | 未重測（需使用者開視窗並給 token） | 見 `docs\CadCraft_Studio操作指引.md` |

## 4. 什麼時候「不」直接用這些 App

土木三軸交付已有確定性工具鏈，口語提到下列事項時**走既有工具，不要用 App 從零做**：
預算書 → `tools\boq\boq_build.py`（底層即 GridCraft）；設計報告 → `tools\report\make_report.py`；
A3 出圖 → `tools\a3_sheet\make_sheet.py`＋`check_delivery.py`；擋土牆／排水溝斷面 → `tools\wall_section\make_wall_section.py`；整案 → `tools\case_package\case_package.py`。
