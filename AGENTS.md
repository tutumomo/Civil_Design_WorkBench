# 土木工程設計 AI 工作區：共用作業規範（Harness² 架構主規範）

> 本檔為所有智能體（Claude、Gemini / Antigravity、Codex、OpenCode、WorkBuddy）之**唯一常駐主規範（Always-On Core）**。
> `CLAUDE.md`、`GEMINI.md` 皆以本檔為準。為保護推理與輸出 Context 預算，本檔僅保留通用常駐規則與按需載入觸發器（Triggers），葉節點細部推導與歷史案例一律下放至 `docs/`。

## 1. 業務範疇、目錄讀寫護欄與 Anti-Jobs（Scope, Boundaries & Anti-Jobs）
從事**道路、排水溝、擋土牆、邊坡、箱涵、滯洪池、建築樑柱與基礎**等土木／結構小型工程設計與預算編列（小型案件通常不另行測量）。

| 目錄路徑 | 角色定位 | AI 讀寫權限 |
|---|---|---|
| `<專案根目錄>` | AI 本機作業區（根目錄只放共用設定、入口文件與既有案例） | 讀寫；但**不得在根目錄新增產出檔**（見 §1.1） |
| `<專案根目錄>/out/` | **交付物唯一落點**（`out/<案名>/`） | 讀寫；交付清單只列這裡的檔案 |
| `<專案根目錄>/_temp/` | **暫存唯一落點**（探測腳本、日誌、測試圖、下載物、實驗輸出） | 讀寫；**可整批刪除**，不得放交付物 |
| `<專案根目錄>/完整案例(參考用)/` | 使用者存放的**參考案例資料**（完整設計圖、預算書等，依案件分子資料夾） | **唯讀**：不得改寫、刪除、搬移（放檔規範見該夾內 `_放置規範與處理計畫.md`） |
| `<專案根目錄>/標準圖圖庫/` | **標準圖存放位置**（依類別分資料夾，如擋土牆／排水溝／箱涵／路面） | 可新增與歸類；不得與案件交付物混放 |
| `<專案根目錄>/cases/` | 統一案件檔（`cases/<案名>/case.json`，數量的唯一來源） | 讀寫 |
| `<專案根目錄>/data/` | 圖資與法規庫（建物 SHP、法規全文） | 以唯讀為主；新增須註明來源 |
| `<專案根目錄>/_ref/` | 機讀參考目錄（元件目錄、`components_dxf`、重建腳本） | 可寫（由 `_ref/*.py` 重建） |
| `<專案根目錄>/docs/` / `tools/` / `templates/` | 知識文件 / 程式 / 樣板 | `docs/` 只放長期知識；三者皆**不得放產出物或暫存檔** |
| `<人工本機作業區>`（例 `D:/公司案件/`） | 人工本機作業區 | **唯讀參考**（未獲使用者明確授權，嚴禁寫入或覆寫） |
| `<公司交付區/NAS>`（例 `//Guushan-nas/320G外接共用/`） | 公司區網交付區 | 唯讀參考；**僅在使用者明確指示「交付」時**才複製成果至此 |
| `<雲端硬碟/Detail Manager>` | 歷年案例設計圖與預算書庫 | 唯讀參考（標準元件位於 `00-圖面相關/公司土木工程常用元件/`） |

### 1.1 檔案落地硬規定（HARD — 所有智能體、所有任務、不得例外）

1. **暫存檔一律進 `_temp/`**：探測腳本、一次性腳本、`_log*.txt`／`*.log`、測試 PNG、中間 DXF、下載中檔案、實驗輸出 → `_temp/<主題或案名>/`。**根目錄、`docs/`、`tools/`、`cases/` 不得出現暫存檔。**
2. **交付物一律進 `out/`**：DWG／PDF／XLSX／DOCX、PDF 轉 PNG 預覽、`<案名>_案件交付清單.md` → `out/<案名>/`。跑工具時 `--out`／`--out-dir`／`out_dir` 一律填 `out/<案名>`（`case_package.py` 已以此為預設）。
3. **`_temp/` 的定義就是「可無條件整批刪除」**：任務結束前確認裡面沒有唯一副本；`out/` 之外的成果都不算交付。
4. **不得覆寫輸入資產**：`完整案例(參考用)/`、`標準圖圖庫/`、`data/`、本機作業區、雲端硬碟、NAS 均為輸入；工具若會寫到相同路徑，一律改寫到 `out/`。
5. **交付清單只列 `out/`**：回報「交了什麼」只列 `out/<案名>/` 內檔案；`_temp/` 內容不得列入交付說明。
6. **舊案就地不動**：2026-10-30 前已散落在根目錄或 `cases/<案名>/out/` 的舊產出，不強制搬移；**新案一律照本節**，要整併舊案須先取得使用者同意。
7. **歸檔優先於新建**：需要標準圖時先找 `標準圖圖庫/` 與 `_ref/components_dxf/`，再考慮重畫；新產出的可重用標準圖，經使用者同意後歸入 `標準圖圖庫/<類別>/`。

### 1.2 邊界分級與 Anti-Jobs（Boundaries & Anti-Jobs）

- **三級行為邊界**：
  - `do`（直接執行）：純本機計算、`_temp/` 讀寫、執行回歸測試與檢查腳本、查詢法規庫。
  - `draft-first`（先草擬確認）：產出或修改 `out/<案名>/` 成果、建立或調整 `cases/<案名>/case.json`、產出設計報告。
  - `ask-first`（先取得明確點名同意）：刪除既有檔案、寫入外部人工作業區、修改 MCP 設定檔、對外交付複製至 NAS、執行 `git push`、更新回歸測試基準（`regression.py --update`）。
- **五大 Anti-Jobs（絕不執行的任務與禁令）**：
  1. **嚴禁未經授權覆寫測試基準**：`regression.py --update` 必須在確認為刻意設計變更並經許可後才可執行，不可為求通過而隨意覆寫。
  2. **嚴禁非 `out/` 目錄交付**：任何交付物未落地於 `out/<案名>/` 者，不得列入交付清單或宣告完成。
  3. **嚴禁自動化覆寫輸入資產**：包含參考案例、法規庫、標準圖庫等輸入資料夾，一律視為唯讀。
  4. **嚴禁臆測未核實單價**：工項單價未在價格庫查證者，必須明確標註為「假設值」，不可假造物價庫來源。
  5. **嚴禁以腳本操控 CadCraft Studio GUI 介面**：背景轉檔與批次代工一律走 headless 介面（OpenCADStudio `--http`／`accoreconsole`／`cadcraft-cli`，統一經 `tools/acad/acc.py`），嚴禁操控 Studio 視窗。
- **機密保護**：`claude_desktop_config.json` 含明文金鑰，嚴禁於對話或文件中輸出其內容。

## 2. DOM — 土木設計領域常數與交付契約（Durable Domain Facts）
- **輸出格式**：交件預設必須包含 **`.dwg`**（AutoCAD 2018 格式，**預設由 OpenCADStudio 經 `tools/acad/acc.py` 產出**，退路為 `accoreconsole`／`CADCraft CLI`），`.dxf` 為工作檔。
- **單位與座標系**：公制公尺（DXF 必設 `$INSUNITS=6`、`$MEASUREMENT=1`）；平面座標採 **TWD97 TM2 二度分帶（`EPSG:3826`）**，圖面即真實座標（台中一帶 `E≈215,000, N≈2,669,000` 屬正常假東移 `250,000`），嚴禁任意平移縮放。
- **文字樣式（`TOMO`）**：字體庫、英文 `gbenor.shx` ＋ 中文大字體 `CHINA1.SHX`。
  - `ezdxf` 寫法：`st = doc.styles.add("TOMO", font="gbenor.shx"); st.dxf.bigfont = "CHINA1.SHX"`（禁留 `Standard`/`Only1`）。
  - **SHX 只有 AutoCAD／`accoreconsole`／OpenCADStudio 認得（`--install`／`--configure` 會把 `CAD_FONTS/*.shx` **複製進 OCS 自己的 `fonts/`** 並把 `settings.fonts_folder` 指過去）；CADCraft 不讀 SHX**（只吃**已安裝**的 TTF/OTF/TTC）。用 CADCraft 校對本專案圖面時設 `CADCRAFT_FONTALT=msjh.ttc`（**只認檔名**，家族名稱與完整路徑實測無效）；**沒有任何環境變數可以指定字型資料夾**。機制、實測雜湊見 [`docs/字型設定_CADCraft與AutoCAD.md`](docs/字型設定_CADCraft與AutoCAD.md)。
- **圖層與色彩**：命名採 `數字前綴_中文說明`（底圖影像 `00_`、道路 `10_`、建物 `20_`、水道 `22_`、圖框說明 `90_`）；房屋與圖框文字設為 `ACI 7`（白/黑自動反轉色），禁用黃色 `ACI 2`。內嵌影像（IMAGE）須與 DXF 放同資料夾。**出圖型式一律 `monochrome.ctb`，顏色 1~8 對應固定線粗**（不重要 0.10／一般 0.15~0.20／重要 0.35~0.40 mm）；新圖層一律用 `drawing_rules.add_plot_layer()` 建，說明見 `docs/出圖樣式與線粗.md`。
- **現況平面圖必備要素**：平滑化道路邊線與中心線、依實際方位角正交化之建物輪廓＋逐棟 `ANSI31` Hatch、標註名稱之河道雙岸線、指北針、比例尺。
- **設計與預算核心不變量（關鍵防錯）**：
  - **擋土牆配筋牆型分流**：一律走 `rc_design.design_wall_rebar(q, wall_res)`。`gravity`/`semigravity`＝名目構造鋼筋；`cantilever`＝莖板＋底板撓曲配筋；`counterfort`/`anchored`/`mse`＝構材彙總；砌石與蛇籠鋼筋為 0。**嚴禁對所有牆型直接呼叫 `design_cantilever_stem()`**。詳見 `docs/擋土牆配筋設計SOP.md`。
  - **RC 鋼筋損耗率**：**全專案一律 6%（含搭接）**——擋土牆、排水溝、箱涵共用 `rc_design.LAP_ALLOWANCE = 0.06`；不得再把牆／溝另切 12%。
  - **預算書湊整微調慣例**：包商利潤及管理費**一律用扣的**（實際 ≤ 標稱值 7% 或 8%，防圖利廠商）；空氣污染防制費**只加不減**（實際 ≥ 標稱值 0.3%，規費多編不圖利）。看到非標稱值或整數總額時先檢核此規則，勿逕判錯誤；詳見 `docs/預算書產線.md`。

## 3. INV — 執行環境與跨平台運作紀律（Invariant Execution Mechanics）

- **開工前多端同步檢查（SessionStart 紀律與多機作業）**：
  本專案常態在多台電腦（公司／家裡／筆電）輪流作業。智能體開工前或接手新任務時必須依循：
  1. 執行 `python tools/git/sync_check.py`（macOS/Linux 用 `.venv/bin/python tools/git/sync_check.py`）。
  2. **遠端有新提交（`behind > 0`）**：開工前務必先 `git pull --ff-only origin <branch>`。若工作區有已追蹤改動，先 `git stash push -u -m "pre-pull-$(hostname)-$(date +%H%M)"` 再 pull，最後以 `git stash apply` 復原。
  3. **殘留鎖定檔（`.git/*.lock`）**：若有殘留，確認無執行中的 git 程序後清理，避免所有 git 指令卡死。
  4. **本地未推送（`ahead > 0`）**：換地點或收工前務必落實 `docs/專案收工SOP.md` 執行 push，確保遠端為最新。
- **路徑一律由 `tools/project_paths.py` 解析（跨平台、禁止寫死絕對路徑）**：本專案程式不得寫死磁碟絕對路徑。用法 `from project_paths import ROOT, regs_db, artcraft_cli, python_exe, accoreconsole, opencadstudio_exe, temp_dir, out_dir`；環境變數可覆寫。環境自我檢查跑 `python tools/project_paths.py`；說明見 [`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)。
- **外部工具版本不寫死**：ArtCraft 13 套、SolidCraft 與 Blender 更新頻繁，文件與程式**不得把版本號當規格或檢核條件**（否則每次 app 更新就產生假警報，卻抓不到真正的 API 變更）。要查目前版本跑 `python tools/project_paths.py --versions`；要留紀錄時只新增到 [`docs/已驗證環境快照.md`](docs/已驗證環境快照.md)（標日期、註明僅供追溯）。相容性以實際冒煙測試為準。
- **【硬性】新機器／換機器／使用者說「更新必備工具」「裝好環境」時，必須執行安裝而非只做檢查**：
  ```bash
  python tools/project_paths.py --install            # 偵測並補裝缺漏的第三方工具
  python tools/project_paths.py --install --dry-run  # 先看計畫
  ```
  **只跑 `python tools/project_paths.py` 是唯讀回報，不會安裝任何東西**——它印出 OK／— 清單後就結束，缺的工具仍然缺。要宣稱「環境已備妥」之前，必須先跑過 `--install` 且其退出碼為 0，並在回報中貼出該指令的總結段。
  **`--install` 會一併寫好 OpenCADStudio 的 TOMO 字型夾與 CTB 樣式夾**（字型：複製 `CAD_FONTS/*.shx` 進 OCS 設定夾的 `fonts/` 並設 `settings.fonts_folder`；`settings.plot_styles_folder` → `tools/acad/plot/`，只指向不複製）；已安裝的機器也會補寫。只想重寫設定、不下載時用 `python tools/project_paths.py --configure`。驗證方式是開一張 TOMO 圖後看 REST 回應的 `state.missing_fonts` 是否為 `[]`，不要只憑「沒有警告」判斷。詳見 `docs/環境需求與自動配置.md` §8.8。
  安裝規範：免 root、成品落 `~/.local/opt/<name>-<ver>/`、`~/.local/bin/` 建 symlink、來源為官方 GitHub Releases；symlink 衝突時改建 `<name>-new` 並印出 `mv` 指令交使用者確認，不直接覆蓋。
  **必備工具共四項（2026-11-10 起）：OpenCADStudio TW、Open CalcSheet Studio TW、ArtCraft Launcher（`storytold/craft-launcher`，Craft App Suite 啟動器，十幾套開源軟體可平替 Adobe／Office／CAD）、Blender。** 後兩者為 GUI／官方發行版，`--install` 只偵測（`project_paths.artcraft_launcher_exe()`／`blender_exe()`）並在缺少時印取得指引、退出碼非 0；**不得對 Launcher 跑 `--version`／`--help`**（GUI 程式）。Launcher 裝好後，各 App（至少 GridCraft、WordCraft）要在它的視窗內安裝。
  **前兩個必備工具由 `--install` 自動安裝，來源是使用者自己的 fork，且只綁「本地化 TW 版」應用程式（2026-11-10 定案，不得改回上游）**。使用者本機會**同時安裝上游版與 TW 版**（識別碼與安裝資料夾不同），解析器只認 TW 版、**絕不退回上游版**：

  | 工具 | TW 版（本專案綁定） | 上游版（並存，不採用） |
  |---|---|---|
  | OpenCADStudio | 資料夾「Open CAD Studio.TW」、`OpenCADStudio.TW.exe`；設定檔夾與上游共用 `%APPDATA%/OpenCADStudio` | 「Open CAD Studio」、`OpenCADStudio.exe` |
  | Open CalcSheet Studio | 資料夾「Open CalcSheet Studio TW」、識別碼 `tw.opencalcsheet.studio`（token 在其 `preferences.json`） | 「Open CalcSheet Studio」、`studio.openstructuralcalculation.app` |

  兩版執行檔可能同名，**只能靠資料夾／.app／desktop 檔名分辨**；路徑一律由 `project_paths.opencadstudio_exe()`／`opencalcsheet_exe()`／`ocss_settings_dir()` 解析，不得寫死。兩版 OCSS 預設都用埠 3879，同時開啟時以先開者佔埠；`probe` 回 401 多半是連到了上游版，請關掉上游版。
  - **OpenCADStudio**（[`tutumomo/OpenCADStudio`](https://github.com/tutumomo/OpenCADStudio)）：fork 版含 Big5 SHX 大字體修正，中文才不會亂碼。Windows 取 `*-installer.msi`，以 `msiexec /passive` 安裝到「Open CAD Studio.TW」（可能跳 UAC）；Linux 取 AppImage，命令為 `~/.local/bin/opencadstudio-tw`；macOS fork 目前未發行 dmg，印手動指引。
  - **Open CalcSheet Studio**（[`tutumomo/Open-CalcSheet-Studio`](https://github.com/tutumomo/Open-CalcSheet-Studio)，鍵名 `OpenCalcSheet`）：開放計算環境／第二套獨立算法。Windows 下載檔名含 `.TW_` 的 `x64-setup.exe`、**先以 `SHA256SUMS.txt` 校驗**再 `/S` 靜默安裝（可能跳 UAC，請使用者核准）；Linux 下載 `.deb` 後試 `sudo -n apt-get install`（只在免密碼 sudo 時成功，絕不代填密碼），不行才印出 `sudo apt install` 指令；裝好後 `--install` 會補防黑屏啟動腳本 `~/.local/bin/open-calcsheet-studio-tw` 與選單項目（OpenCADStudio AppImage 同樣補「Open CAD Studio TW」選單項目）；macOS 走 dmg 流程（尚未實測）。已安裝則略過，不自動升級。單獨補裝：`python tools/project_paths.py --install --only OpenCalcSheet`。
  **OCSS 裝好後還有兩件事，`--install` 不會代做**：① 開啟程式一次並在設定啟用 MCP／API（token 才會產生）；② 跑 `python tools/crosscheck/ocss_crosscheck.py register-mcp --apply` 把 MCP 連線寫進本機 `.mcp.json`（token 不印出、不進版控），最後用 `ocss_crosscheck.py probe` 驗證。**嚴禁對 OCSS 執行檔跑 `--version`／`--help`（會卡死）**，偵測一律走 `project_paths.opencalcsheet_exe()`。
- **工具不得住在 `_temp/`**：`_temp/` 依 §1.1 可整批刪除，凡會長期引用的工具一律放 `tools/`。
- **優先呼叫確定性腳本**：嚴禁略過 `tools/` 現成工具而重寫一次性腳本。
- **跨平台 Python 執行鐵則**：
  1. Windows 執行 Python 前必設 `set PYTHONIOENCODING=utf-8`；讀寫中文檔一律指定 `encoding="utf-8"`（**嚴禁用 PowerShell `Get-Content/Set-Content` 修改中文檔**）。
  2. macOS/Linux 一律用專案內的 `.venv`（`.venv/bin/python`）。
  3. 結合影像與地理幾何套件時，**第一行必寫 `import matplotlib; matplotlib.use('Agg')`**，接著依序 `import shapely`、`import pyproj`，最後才 `import cv2` 與 `import ezdxf`（防止 OpenMP 衝突閃退）。
  4. 超過 60 秒之長工作輸出導向至 `_temp/<主題>/_log.txt` 輪詢（**嚴禁直接導向根目錄**，例：`> _temp/basemap/_log.txt 2>&1`）。
  5. 紀錄時間一律取本機系統時間。
  6. **暫存與輸出位置**：中間檔寫 `_temp/`，交付檔寫 `out/`（§1.1）。
- **不碰共用 GUI AutoCAD，並嚴格區隔兩套同名 CadCraft**：
  - **AI 後台自動化代工（轉檔、出圖、無人值守運算）**：一律經 `tools/acad/acc.py`，**預設後端為 OpenCADStudio**（按需起 `--http` 服務，執行檔由 `project_paths.opencadstudio_exe()` 解析，**嚴禁寫死安裝路徑**）；退路為無介面 `accoreconsole.exe` 或 `CADCraft CLI`（`artcraft_cli("CADCraft")`），以 `CIVIL_AI_CAD_BACKEND=cadcraft` 切換。
  - **macOS CLI 替代層**：使用 `tools/artcraft_cli/` 封裝之 JSON-lines 殼層，維持 CLI 子指令介面。
  - **人類視覺化驗收看板**：`CadCraft Studio` 為 GUI 視窗看板，無 headless CLI，嚴禁 AI 嘗試用腳本操控其介面做背景轉檔；僅供人類開圖檢視。詳見 `docs/CadCraft與CadCraft_Studio分工規範.md`。
- **改動留痕與驗證閉環（Git Commit & Test-Before-Delivery）**：
  1. 每次實質改動（修改工具、新增功能、修復 bug、重構或升級規範）完成後，都必須建立對應的 Git commit，確保異動具備語意化說明，以便後續追蹤、審計與快速回滾。
  2. 每次改動後，都必須編寫、補充或同步更新相關測試與檢核腳本；在交付給使用者前，必須執行測試與全案回歸，確保所有測試與品管驗證全部通過（退出碼為 0），嚴禁未經驗證即宣稱完成。
- **完稿重開驗證（Reopen & Check）**：寫檔成功 ≠ 圖面可用。每次產出 CAD 檔必須重讀驗證並將實際出圖之 PDF 轉為 PNG 目視檢查；回報時須列出風險限制、數據來源與自評可信度（1–10）。

## 4. 確定性工具註冊表（Deterministic Tool Registry）

| 工具路徑 | 功能說明 | 產出與主要規範文件 |
|---|---|---|
| `tools/site_basemap/site_basemap.py` | 輸入案址經緯度 → 產出 TWD97 現況平面線稿 DXF | `render_dxf.py` 產 PNG 檢核；`docs/現況平面底圖作業流程.md` |
| `tools/a3_sheet/make_sheet.py` | **A3 出圖標準工具**：套用 DWT 圖框、非矩形視口、出 DWG/PDF | 優先於舊版；搭配 `tools/a3_sheet/check_delivery.py` |
| `tools/a3_sheet/check_delivery.py` | **交件強制品管檢核器**：檢查 E1~E18（bbox 壓字、疊字碰撞、顏色線粗、出圖型式） | 退出碼必須為 0 方可交件；見 §6 |
| `tools/acad/acc.py` | CAD 轉檔／出圖統一入口：DWT/DWG→DXF（`todxf`）、DXF→DWG（`to_dwg`）、DXF→DWG+PDF（`publish`）；後端由 `CIVIL_AI_CAD_BACKEND` 選 `ocs`（**預設**，OpenCADStudio，含 SHX 中文與 CTB 絕對路徑出圖）／`cadcraft`（退路：`accoreconsole` 或 `cadcraft-cli`）。OCS 回報 `missing_fonts` 會在 stderr 警告；出圖後仍須目視 PDF 中文 | 專案出圖型式預設使用 `tools/acad/plot/monochrome.ctb`；後端差異見 `docs/環境需求與自動配置.md` §8.7、切換紀錄見 `docs/CAD引擎選型_OpenCADStudio與CADCraft.md` §13 |
| `tools/acad/ctb.py` | CTB 讀取、比對與產生工具（`report`/`verify`/`build`） | `docs/出圖樣式與線粗.md` |
| `tools/acad/apply_plot_style.py` | 舊圖套用新出圖樣式（換顏色線粗、補寫 `TOMO_PLOTSTYLE`，幾何不動） | 來源為 `drawing_rules.PLAN_LAYER_COLORS` |
| `tools/cadastral/make_cadastral_map.py` | **地籍套繪圖首選工具**：抓台中開放坵塊/段籍＋建物 SHP 產 A3 地籍套繪圖 | `docs/地籍套繪圖產線.md`（僅供參考，不得作產權鑑界依據） |
| `tools/boq/boq_build.py` | **工程預算書首選工具**：案件 JSON → 5 工作表 XLSX ＋ PDF，活公式雙重驗證 | 費率核心 `tools/boq/boq_rules.py`；`docs/預算書產線.md` |
| `tools/boq/price_audit.py` | **單價來源稽核工具**：逐項比對 `tools/boq/prices/`，標註物價庫/假設值並算覆蓋率 | `docs/單價庫與查證覆蓋率.md` |
| `tools/report/make_report.py` | **設計報告首選工具**：案件 JSON → A4 DOCX ＋ PDF（14 章骨架、表號圖號、頁首尾） | 回讀驗證 `verify_report.py`；`docs/設計報告產線.md` |
| `tools/case_package/case_core.py` | **統一案件檔核心（`civil-case/1`）**：`cases/<案名>/case.json` 為數量唯一來源 | 數量派生與模型算式一致性檢查（`consistency()`） |
| `tools/case_package/qty_models.py` | 類別化數量模型（`road` 道路、`wall` 擋土牆、`channel` 排水溝、`slope` 邊坡） | 水保第 121 條伸縮縫/排水孔；不可跨類別硬套公式 |
| `tools/case_package/case_package.py` | **三軸一鍵交付**：讀案件主檔 → 一致性檢查 → 派生輸入 → 跑三軸產交付清單 | 任何一軸未過即退出碼 1；`docs/案件交付包.md` |
| `tools/takeoff/dxf_takeoff.py` | **圖／數對帳首選工具**：回讀 DXF 實測面積/長度，對帳斷面面積（扣內腔）與鋼筋間距 | 接進 `case_package.py` 為第三與第四道交付閘門 |
| `tools/takeoff/paving_extent.py` | 道路刨鋪範圍計算：由邊線沿設計中心線裁到樁號圍成多邊形，產 15 圖層對帳面積 | 避免超出樁號範圍多算面積 |
| `tools/design/design_api.py` / `design_cli.py` | **設計計算統一 JSON 入口（`civil-design-run/1`）**：涵蓋 22+ 項土木結構計算器 | 網頁工作台 `tools/design/workbench_web.html`；`docs/設計工作台.md` |
| `tools/crosscheck/ocss_crosscheck.py` | **OCSS 交叉驗算**：同一題目分別用本專案引擎與 Open CalcSheet Studio 開放計算環境各算一次，比對數值與單位（`probe`／`eval`／`checks`／`register-mcp`） | 需 OCSS 桌面程式開啟，因此**不進**回歸預設流程；`docs/OpenCalcSheetStudio_整合與開放計算環境.md` |
| `tools/design/hydrology.py` | 集水區水文分析（水保第 16~19 條）：降雨強度、合理化公式 Qp、逕流係數、集流時間 | 排水溝設計流量計算首選；`docs/設計計算產線.md` |
| `tools/design/channel_hydraulics.py` | 排水溝水力計算（曼寧公式、容量、出水高、流速上下限、福祿數、斷面反推） | 水保第 78、83~86 條；`docs/設計計算產線.md` |
| `tools/design/channel_profile.py` | 明渠水面線（迴水）計算：標準步法由下游往上游演算水深與剖面型態 | 檢核沿線出水高；`docs/設計計算產線.md` |
| `tools/design/rc_design.py` | RC 構材配筋設計（擋土牆莖板/底板、排水溝壁、水土保持與混凝土規範檢核） | 裂縫寬度、最小鋼筋、水平鋼筋量；`docs/設計計算產線.md` |
| `tools/design/sediment_basin.py` | 沉砂設施容量（USLE 公式、水保第 35/92/93 條）、結構配筋與水理檢核 | 臨時設施折減與下限；`docs/設計計算產線.md` |
| `tools/design/slope_stability.py` | 邊坡穩定分析（水保第 72/73 條）：無限邊坡法與 Fellenius 圓弧滑動安全係數 | 容許坡角反算；`docs/設計計算產線.md` |
| `tools/design/retaining_wall.py` | 懸臂式/重力式擋土牆穩定分析（水保第 119~120 條：滑動、傾倒、偏心、承載力） | 斷面反推尺寸；`docs/設計計算產線.md` |
| `tools/design/box_culvert.py` | 單/雙/三孔箱涵結構分析、車載、進出口水理、逐面配筋與每延米數量計算 | `docs/箱涵計算SOP.md` 與 `docs/箱涵斷面圖產線.md` |
| `tools/wall_section/make_wall_section.py` | 擋土牆（S-01/S-02）與排水溝（D-01/D-02）標準斷面圖與配筋圖產出 | 1:20 出圖＋自動接 `check_delivery.py`；`docs/擋土牆斷面圖產線.md` |
| `tools/box_section/make_box_section.py` | 箱涵標準斷面圖與配筋圖（S-01/S-02）：含 45° 倒角加腋與角隅補強斜筋 | 自動接 `check_delivery.py` 與 `dxf_takeoff.py` |
| `tools/selftest/regression.py` | **全案回歸測試**：一鍵驗證全案件預算、斷面積、通水容量、FS、配筋間距 | 比對 `tools/selftest/baseline.json`；`docs/回歸測試.md` |

- **交付六道閘門**（總表見 [`docs/交付閘門總表.md`](docs/交付閘門總表.md)）：
  ①設計檢核全過（`case_core.check`）
  ②E1~E18 品管檢核
  ③圖／數對帳
  ④配筋圖間距對帳
  ⑤設計段落注入（`report_case.json` 的 `_derived.design_sections_error` 必須為空）
  ⑥全案回歸測試全過。

## 5. 按需載入觸發器（On-Demand Skill & Library Triggers）

- **When the user asks in plain words to operate any ArtCraft app, SolidCraft, Blender or text-to-cad (口語操作 App)**: Read [`docs/口語操作手冊_ArtCraft與CAD工具.md`](docs/口語操作手冊_ArtCraft與CAD工具.md) first（指令對照、參數注意、一律走 CLI）。
- **When text shows as boxes/wrong glyphs, or you need to add or verify CAD fonts (字型／字體異常)**: Read [`docs/字型設定_CADCraft與AutoCAD.md`](docs/字型設定_CADCraft與AutoCAD.md)（SHX 僅 AutoCAD 讀、CADCraft 僅吃已安裝 TTF/TTC、環境變數只認檔名）。
- **Before using the `autocad` MCP tools (`mcp__autocad__*`)**: Read [`docs/AutoCAD_MCP操作指引.md`](docs/AutoCAD_MCP操作指引.md)（僅限 ezdxf 後端、DWG 一律經 `acc.py`、文字補 TOMO）。
- **When doing terrain / cut-fill / LandXML work (CivilCraft) or quantity takeoff (TakeoffCraft)**: Read [`docs/CadCraft_Studio操作指引.md`](docs/CadCraft_Studio操作指引.md) first（需使用者開啟視窗並提供 token，token 不落地）。
- **When choosing between CADCraft CLI and CadCraft Studio (分工邊界)**: Read [`docs/CadCraft與CadCraft_Studio分工規範.md`](docs/CadCraft與CadCraft_Studio分工規範.md)（後台代工一律用 CLI，Studio 僅為人類視覺化看板）。
- **Before producing or modifying any drawing (basemap, A3 sheet, detail)**: Read [`本項目的出圖規定(不定期新增).md`](<本項目的出圖規定(不定期新增).md>) 並遵守；出圖樣式與線粗見 `docs/出圖樣式與線粗.md`，舊圖改樣式用 `tools/acad/apply_plot_style.py`。
- **After changing any tool under `tools/` (改過工具後)**: 必跑 `tools/selftest/regression.py`（可加 `--only <案名>` 只跑相關案件）；若改到 `tools/design/` 另跑 `tools/selftest/design_core_selftest.py` 與 `tools/selftest/design_workbench_selftest.py`；改查詢台跑 `tools/regs/regq_selftest.py`。詳見 [`docs/回歸測試.md`](docs/回歸測試.md)。
- **Before producing or modifying a budget (預算書與單價稽核)**: Read [`docs/預算書產線.md`](docs/預算書產線.md)（費率公式、可微調項與方向、單價庫）並跑 `tools/boq/price_audit.py`；產出使用 `tools/boq/boq_build.py`。
- **Before producing or modifying a design report (設計報告)**: Read [`docs/設計報告產線.md`](docs/設計報告產線.md)（14 章骨架、章節派生防錯）並用 `tools/report/make_report.py`。
- **Before estimating design flow, sizing channel, profile, slope, or basin (水文/水力/邊坡/沉砂池計算)**: Read [`docs/設計計算產線.md`](docs/設計計算產線.md) 並呼叫對應確定性腳本，嚴禁在對話中口算或臆測。
- **Before designing rebar for walls, channels, or box culverts (RC 配筋設計)**: Read [`docs/擋土牆配筋設計SOP.md`](docs/擋土牆配筋設計SOP.md) 與 [`docs/箱涵計算SOP.md`](docs/箱涵計算SOP.md)（落實牆型分流與 6% 損耗率）。
- **Before any numerical civil/structural design (結構數值計算)**: 使用 `tools/design/design_api.py`、`design_cli.py` 或網頁工作台；計算器地圖詳見 [`docs/設計工作台.md`](docs/設計工作台.md)。
- **When adding or changing a design calculator (新增／修改計算器上架)**: Read [`docs/設計計算器上架SOP.md`](docs/設計計算器上架SOP.md) 並落實 G1~G8 規範；完成前必跑 `tools/selftest/design_launch_check.py <id>`。
- **Before producing a retaining-wall or box-culvert drawing (擋土牆／箱涵出圖)**: Read [`docs/擋土牆斷面圖產線.md`](docs/擋土牆斷面圖產線.md) 或 [`docs/箱涵斷面圖產線.md`](docs/箱涵斷面圖產線.md)（箱涵 45° 加腋與角隅斜筋不可省）。
- **When starting a new case (新案件建立與三軸交付)**: Read [`cases/README.md`](cases/README.md) 與 [`docs/案件交付包.md`](docs/案件交付包.md)；建立 `cases/<案名>/case.json`，執行 `case_core.py check` 與 `case_package.py`。
- **When generating a site basemap or laying out an A3 sheet**: 載入 `civil-site-basemap` skill 或閱讀 [`docs/現況平面底圖作業流程.md`](docs/現況平面底圖作業流程.md)。
- **When asked to draw a cadastral map (地籍套繪圖)**: 使用 `tools/cadastral/make_cadastral_map.py`；踩坑與限制詳見 [`docs/地籍套繪圖產線.md`](docs/地籍套繪圖產線.md)。
- **When troubleshooting tool errors or modifying scripts**: 先查 [`docs/經驗索引_INDEX.md`](docs/經驗索引_INDEX.md) 並僅開啟符合的 [`docs/踩坑紀錄.md`](docs/踩坑紀錄.md) 小節（嚴禁通讀全檔）。
- **Before citing design codes or regulations (引用法規規範條文)**: 查閱 [`docs/法規庫總目錄.md`](docs/法規庫總目錄.md)；使用 MCP `regs_ask`/`regs_search` 或 `tools/regs/regq.py`；公式與表值引用依據 [`docs/規範公式圖表入庫SOP.md`](docs/規範公式圖表入庫SOP.md)。
- **When turning hand-drawn images into 3D landscape renderings (手繪圖轉 3D 景觀意象圖)**: Read [`docs/3D景觀模擬_作業經驗與踩坑.md`](docs/3D景觀模擬_作業經驗與踩坑.md) first（建模前必先送 5~7 列判讀確認表；Blender 經 `blender_runner.py` 執行；可重用腳本在 `tools/landscape3d/`）。
- **When the user says「收工」、「關帳」or closeout**: Read [`docs/專案收工SOP.md`](docs/專案收工SOP.md) 並嚴格執行 16 個步驟。版本採 CalVer `vYYYY.MM.DD-N`；只 stage 本次白名單。

### 5.1 MCP 工具鏈接線（細節見 [`docs/AI工具鏈_MCP整合_2026-11-03.md`](docs/AI工具鏈_MCP整合_2026-11-03.md)）

- **六條 MCP 通道配置**：`regs`（規範查詢台）、`blender`（3D 景觀/模型）、`autocad`（CAD 讀圖）、`artcraft`（Office/CAD 工具鏈）、`ingetrazo`（道路橋樑專案）、`cadgen`（text-to-cad 遙測）。設定由 `tools/mcp/register_all.py` 管理；修改後跑 dry-run → `--apply` → `mcp_probe.py`。
- **第七條通道 `open-calcsheet-studio`（2026-11-10 新增）**：OCSS 的 MCP（`http://127.0.0.1:3879/mcp`）與 REST 是同一個橋接器、同一份 43 工具 registry，但**必須 OCSS 桌面程式開著**才存在，且 token 為機密（只存本機 `.mcp.json`，不進版控、不寫文件）。腳本端一律走 REST（`tools/crosscheck/ocss_client.py`），不必處理 JSON-RPC 握手。**它是必備工具**：clone 後 `--install` 會自動安裝，`.mcp.json` 條目用 `ocss_crosscheck.py register-mcp --apply` 產生（見 §3 硬性安裝規定）。細節見 [`docs/OpenCalcSheetStudio_整合與開放計算環境.md`](docs/OpenCalcSheetStudio_整合與開放計算環境.md)。 **43 個工具逐一清單**（用途／參數／REST 路由）見 [`docs/OpenCalcSheetStudio_工具清單.md`](docs/OpenCalcSheetStudio_工具清單.md)，由 `tools/crosscheck/ocss_tools_doc.py` 生成（OCSS 升版後重跑，`--check` 驗是否過期）。
- **第八條通道 `opencadstudio-tw`（2026-11-10 新增）**：Open CAD Studio TW 的 stdio MCP（`<執行檔> --mcp`），連到**執行中的 TW 版 GUI**，不需 token，20 個 `ocs_*` 工具（先用 `ocs_inspect`；交付前 `ocs_save_verified`）。執行檔由 `project_paths.opencadstudio_exe()` 解析（只認 TW 版），以 `python tools/mcp/register_all.py --only opencadstudio-tw --apply` 註冊；範本見 `.mcp.json.example`。批次出圖仍走 `tools/acad/acc.py`，不經此通道。**注意**：使用者在 GUI 開著某張 DXF 時會持有編輯鎖，`acc.py`／回歸出同一張圖會回 400「Drawing edit lock is held」——請使用者先關圖。
- **IngeTrazo 為 GUI+橋接型**：需桌面 App 開啟並啟動 AI Bridge；輸出為 IFC4/CSV/DXF，座標為 UTM WGS84，**不得直接視為 TWD97 `EPSG:3826`**。詳見 [`docs/IngeTrazo操作指引.md`](docs/IngeTrazo操作指引.md)。
- **IngeTrazo 在 macOS arm64 已有官方 DMG**（`IngeTrazo-0.6.0-macos-arm64.dmg`），裝在 `/Applications/IngeTrazo.app`；`project_paths` 已內建該路徑，**不必設 `INGETRAZO_HOME`／`INGETRAZO_MCP`**。
- **橋已改為自動開啟**（2026-11-08）：使用者外掛 `~/.local/share/ingetrazo/plugins/auto_ai_bridge.py` 在 app 啟動時自動拉起橋（停用＝檔名加 `.disabled`）。**橋只收一個客戶端**——第二個 MCP 客戶端會「逾時」而非拒絕；用 `lsof -nP -iTCP:4763` 找出佔用者並 `kill` 才能釋放名額。
- **Blender MCP 能力與使用情境**：五個工具（`blender_info`／`blender_run_python`／`blender_render`／`blender_convert`／`blender_selftest`）、情境、路徑與限制見 [`docs/Blender_MCP_能力與使用情境.md`](docs/Blender_MCP_能力與使用情境.md)。腳本內的輸出路徑一律用絕對路徑（相對路徑會落在 `_temp/blender/<job>/`）。
- **Blender 執行環境**：MSIX 版路徑由 `project_paths.blender_exe()` 解析；腳本一律經 `tools/blender/blender_runner.py` 啟動。
- **MCP 相對路徑約束**：ArtCraft 相對路徑落於 `out/`；AutoCAD MCP 限制於本專案根目錄。
- **`regs_server.py` 啟動旗標**：提供 MCP 時必須帶 `--mcp` 參數。

## 6. 交件強制品管門檻（Mandatory Delivery Gate）
凡交付 A3 圖面，必須備齊 `<案名>_現況平面圖_A3.dwg`、`.dxf`、`.pdf`、`.png`、`紀錄.log`，且**交件前必跑下列指令並取得退出碼 `0`（E1~E18 零錯誤，含 E15 字高／E16 標準比例／E17 顏色線粗／E18 出圖型式，含 E9 標題欄 `y=29.03`／技師圖記區 `x363.5~410.3, y29~80.9` 零跨越、E10 紙空間文字 bbox 零重疊）**，未通過不得宣稱完稿：

```bash
python tools/a3_sheet/check_delivery.py <成果.dxf> \
  --scale 600 --require-dwg \
  --require-layer 10_道路邊線_現況 --require-layer 20_建物 --require-layer 22_水道
```

> macOS／Linux 用 `.venv/bin/python tools/a3_sheet/check_delivery.py …`。

> **版面類錯誤的三個高頻來源**（詳見 `docs/踩坑紀錄.md` §AI.4）：
> ① **右欄圖例／說明過寬** → E9／E10（寬度估算要比 `est_width()` 再保守一成，SHX 中文寬度會被低估兩成）；
> ② **匯入的底圖圖層沒有線粗**（DXF 370 = -3） → E17（`make_sheet.py` 已內建 `apply_plot_style()`，勿手動補圖）；
> ③ **右側欄圖例超出圖框內框 410.27** → E9（圖例文字起點不得晚於 `CX+12`）。
