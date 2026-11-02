# 口語操作手冊：ArtCraft 13 套＋SolidCraft／Blender／text-to-cad／AutoCAD MCP

> 建立：2026-10-29｜全部本機實測（冒煙測試腳本 `_sandbox\artcraft_smoke\smoke.py`，產物在同層 `out\`）。
> 用途：使用者用口語下令 → 智能體查本表決定用哪套、怎麼下指令，**一律走無視窗 CLI（headless）**，不搶使用者正在用的視窗。
> 完整指令清單：`docs\artcraft_commands\<App>.txt`（SolidCraft 為 `.json`）。查單一指令參數：`<cli> describe <id>`（Deck／Design／Sound／SolidCraft）或在清單檔中搜尋。
> CAD 類能力邊界的深入評估見 `docs\六套CAD工具能力邊界與重疊度.md`，本檔不重複。

## 0. 口語 → 工具 對照（先查這張）

| 使用者說的話（例） | 用哪套 | 一句話做法 |
|---|---|---|
| 「出圖／轉 DWG／DXF 轉 PDF、PNG」 | **CADCraft**（土木交件仍走 `make_sheet.py`＋`acc.py`） | `cadcraft-cli convert IN.dxf OUT.pdf` |
| 「畫一條線／改圖層／量面積」（2D 編修） | **CADCraft** `run --cmd`；或 AutoCAD MCP（見 §3 警告） | `run in.dxf --cmd 'line {...}' --save out.dxf` |
| 「做一個 3D 實體／擋土牆模型／出 STEP、STL」 | **SolidCraft**（參數特徵樹）或 **text-to-cad**（Python build123d） | `solidcraft-cli run script.json --out x.step` |
| 「把模型渲染成漂亮圖／做旋轉動畫／STL 轉 GLB」 | **Blender** 技能 | `blender_run.py recipe_render.py --input x.stl --out x.png` |
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

## 1. ArtCraft 13 套總表（實測 2026-10-29）

路徑一律 `C:\Program\ArtCraft\<App>\<app>-cli.exe`（GUI 為同目錄 `<app>.exe`）。全部支援 `mcp` 子命令（stdio MCP server），也可 `--connect/--bridge` 操作使用者已開的視窗（**需使用者同意才連視窗**）。

| App | 版本 | 指令數 | 讀寫格式（重點） | 冒煙測試 |
|---|---|---|---|---|
| CADCraft | 0.13.0 | 441 | DXF／DWG／SVG／PNG／PDF | 產範例 DXF→PNG ✔ |
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
