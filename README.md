# 土木小型工程設計工作區（Civil AI Workspace）

把「道路、排水溝、擋土牆、邊坡、箱涵、滯洪池、建築樑柱與基礎」這類**小型土木／結構工程設計**，
從現況底圖、結構計算、預算編列到設計報告，整理成一條可重跑、可驗證的工具鏈，
並把**規範條文轉成機器可讀的公式與表格庫**（目前已驗證 1,011 條），讓 AI 智能體算得出數字、也說得出依據。

- 單位與座標：公制公尺；平面採 **TWD97 TM2（EPSG:3826）**，圖面即真實座標
- 交付格式：原生 **DWG**（AutoCAD 2018）＋ PDF ＋ XLSX ＋ DOCX
- 只用**相對路徑**，資料夾搬到任何磁碟／作業系統都能跑（見 `tools/project_paths.py`）

> **先看這裡**
> 1. **本 repo 需要接上 AI 智能體，才能發揮 100% 功能。** 沒有 AI 智能體時，只能使用兩個網頁介面：
>    **規範查詢台**與**設計工作台**。
> 2. **這份 README 是給人看的。** 環境與工具由 AI 智能體替你配置，你不必自己照著做完所有步驟；
>    直接照〈[初級上手三步驟](#初級上手三步驟)〉走：裝智能體、取得專案、把〈[配置提示詞](#配置提示詞上手步驟-3-貼這段)〉貼給它就好。
> 3. **擔心 token 用量？** 建議同時安裝 **magpie ＋ magpie-our-free-model 外掛**（提示詞裡已含安裝步驟，AI 會替你裝），
>    詳見〈[避免 token 焦慮](#避免-token-焦慮magpie--免費模型外掛建議)〉。

## 初級上手三步驟

第一次用，照這三步走就好；其餘細節都可以之後再看。

| 步驟 | 要做什麼 | 完成的標準 |
|---|---|---|
| **1. 安裝 AI 智能體** | 安裝任一個支援 shell 與 MCP 的 AI 智能體（Claude Code、Codex、Gemini CLI、OpenCode、Antigravity…），**先確認它能正常運行**：開起來、能對話、能回應。還沒有額度的話，可先裝 [magpie](https://usemagpie.ai) 並搭配免費模型外掛（見〈[避免 token 焦慮](#避免-token-焦慮magpie--免費模型外掛建議)〉） | 對智能體說一句話，它有回應 |
| **2. 取得專案，並把智能體的專案資料夾設為它** | 把專案複製到本機：<br>`git clone https://github.com/tutumomo/Civil_Design_WorkBench.git`<br>沒有 git 時，改到 GitHub 頁面按 **Code → Download ZIP**，解壓縮到你找得到的位置。<br>然後用 AI 智能體**開啟（或 `cd` 進）這個資料夾**，讓它的工作目錄就是專案根目錄 | 智能體能列出專案裡的 `README.md`、`tools/`、`cases/` |
| **3. 貼「配置提示詞」給智能體** | 複製〈[配置提示詞](#配置提示詞上手步驟-3-貼這段)〉那一整段，貼給智能體。它會替你裝好依賴與工具、註冊 MCP、跑驗證；遇到非你不可的事（管理員密碼、開軟體一次、重開客戶端）才會停下來問你 | 智能體回報 `--install` 總結段，且退出碼為 0 |

> 配好之後，直接用白話提需求即可，例如「幫我做一個 3 公尺高的重力式擋土牆案」。
> 想知道背後發生什麼、或出問題要查，再往下讀；**不必**自己照後面的「五分鐘上手」一步步做完。

## 目錄

- [初級上手三步驟](#初級上手三步驟)
- [給 AI 智能體：自動配置環境](#給-ai-智能體自動配置環境)
- [這個專案能做什麼](#這個專案能做什麼)
- [五分鐘上手](#五分鐘上手)
- [環境需求](#環境需求)
- [核心概念：案件主檔是唯一數據來源](#核心概念案件主檔是唯一數據來源)
- [工具鏈地圖](#工具鏈地圖)
- [規範公式圖表庫](#規範公式圖表庫)
- [交付前的六道閘門](#交付前的六道閘門)
- [目錄結構](#目錄結構)
- [資料來源與授權](#資料來源與授權)

## 給 AI 智能體：自動配置環境

> **這份 README 是給人看的；環境與工具，交給 AI 智能體替你配置。**
> 後面「五分鐘上手」把每一步都攤開，是為了讓你知道發生了什麼、出問題時查得到，
> **不是要你自己一步步做完**。環境項目看起來很多，不用怕：把下面的提示詞貼給 AI 智能體，
> 它會替你裝好、設定好、驗證好，遇到非你不可的事（管理員密碼、開軟體一次、重開客戶端）才會停下來請你處理。

### 為什麼一定要接 AI 智能體

本專案的設計是「**你提需求，AI 智能體呼叫整條工具鏈**」：規範庫、設計計算器、OpenCADStudio TW（CAD）、
Open CalcSheet Studio TW（交叉驗算）、品管閘門，都是透過 MCP 與指令讓 AI 串起來用。

| | 有接 AI 智能體 | 沒有 AI 智能體 |
|---|---|---|
| 可用範圍 | **100%**：[下一節](#這個專案能做什麼)列的全部功能 | 只剩兩個網頁介面：**規範查詢台**、**設計工作台**（見步驟 6） |
| 環境配置 | AI 代做、代驗證 | 要自己照「五分鐘上手」逐項做 |

> 指令列工具（斷面圖、預算書、報告書…）不靠 AI 也能手動跑，但需要自己組 `case.json`、串 CAD 工具、過六道閘門，
> 不建議初學者這樣用。

### 避免 token 焦慮：magpie ＋ 免費模型外掛（建議）

AI 智能體跑一輪設計、審查、出圖會用掉不少 token。**magpie** 讓你不必綁死單一廠商的額度，
再搭配**免費模型外掛**，初學者可以放心先用起來：

| 工具 | 是什麼 | 對你的好處 |
|---|---|---|
| **[magpie](https://github.com/yetone/magpie)**（MIT，支援 Windows／macOS／Linux） | 本機的模型閘道（`127.0.0.1:3425`）。Claude Code、Codex、Gemini CLI、OpenCode 等 AI 智能體都能從**同一個選單**挑任何模型；某個額度用完時自動換下一個帳號或模型 | 一處管理所有智能體的模型與額度；額度用完不會中斷工作 |
| **[magpie-our-free-model](https://github.com/mu-zi-lee/magpie-our-free-model)**（magpie 外掛） | 在 magpie 裡新增一個「**Our Free Model**」供應商，提供匿名 Zen／Kilo 免費模型池，以及 EAC 與多個帳號渠道 | 不用先買 API 額度就能讓 AI 智能體跑起來 |

這兩個都**由 AI 智能體替你安裝**（見下方提示詞的第 0 步），你只需要在它請你確認時點頭，並在 magpie 的網頁管理頁完成一次登入／授權。

> **使用前請知道**
> - 外掛是第三方的 magpie 適配版（原專案為 [Ebony-Vinyl/dsh-our-free-model](https://github.com/Ebony-Vinyl/dsh-our-free-model)），**不是 magpie 或本專案官方發布**。免費模型的種類、額度與穩定度由第三方渠道決定，**隨時可能變動，不保證**。
> - 請求會經過第三方渠道：**含機敏資料的案件（業主資料、未公開圖面）請自行評估**後再用，或改用你信任的供應商。
> - 外掛安裝目錄要**固定**，所以放在本 repo 之外（例如家目錄下的 `magpie-plugins/`）；使用時 magpie 要保持開著（完全退出才會停止服務）。
> - 首次使用要下載 Node 等元件；EAC 還需在網頁完成 GitHub 授權與 Star 校驗，帳號渠道則要各自登入廠商帳號。詳細操作見外掛自己的 README。

### 配置提示詞（上手步驟 3 貼這段）

前置：已完成〈[初級上手三步驟](#初級上手三步驟)〉的步驟 1、2（智能體可運行，且工作目錄是本專案資料夾）。
還沒有任何智能體時，可先裝 magpie（官網下載：[usemagpie.ai](https://usemagpie.ai)），再裝一個智能體並在 magpie 裡選免費模型。

把下面整段貼給智能體。它會請你做的事通常只有：確認安裝清單、需要管理員權限的指令、開 Open CalcSheet Studio TW 一次並啟用 MCP／API、最後**重開 AI 客戶端**載入新工具。

```
這個 repo 是土木小型工程設計工作區。請幫我把環境配置好：
0. （建議先做，讓我不用擔心 token）安裝 magpie 與免費模型外掛：
   a. 先告訴我要安裝什麼，取得我同意後再裝。magpie 官方安裝：`curl -fsSL https://usemagpie.ai/install.sh | sh`
      （Windows 請到 https://usemagpie.ai 下載安裝）。裝完確認 `magpie` 指令可用。
   b. 在一個固定、不在本 repo 內的資料夾安裝外掛（家目錄下的 magpie-plugins/ 即可，安裝後不可搬動）：
      git clone https://github.com/mu-zi-lee/magpie-our-free-model.git ~/magpie-plugins/magpie-our-free-model
      magpie plugin add ~/magpie-plugins/magpie-our-free-model
   c. 引導我在 Magpie 的「插件」確認外掛已啟用，再到「供應商 → Our Free Model」打開管理頁完成登入／授權，
      然後替我的 AI 智能體選 `our-free-model` 下的模型。操作細節以該外掛的 README 為準。
1. 跑 `python tools/project_paths.py`，看目前缺什麼（它會列出 Python 依賴、規範索引、
   OpenCADStudio TW、Open CalcSheet Studio TW、CAD 字體庫、SolidCraft、Blender，
   以及建議安裝的 15 套 ArtCraft、僅備援用的 AutoCAD）。
2. 缺 Python 套件：在虛擬環境內 `python -m pip install -r requirements.txt`（已含 `mcp`，MCP 註冊與 Blender 橋需要）。
2.5 **要真的安裝**：`python tools/project_paths.py --install`（退出碼 0 才算備妥）。它會從我的 fork
   安裝 OpenCADStudio TW（tutumomo/OpenCADStudio）與 Open CalcSheet Studio TW（tutumomo/Open-CalcSheet-Studio），
   不要改回上游版；並自動把 TOMO 字型（CAD_FONTS/ 的 *.shx，推薦 gbenor.shx＋CHINA1.SHX）複製進 OpenCADStudio TW 的字型夾，並設好 CTB 出圖樣式夾。
   若印出需要我執行的 sudo／mv 指令，列給我確認。
   必備工具共四項：另外 **ArtCraft Launcher**（https://github.com/storytold/craft-launcher ，十幾套開源軟體，可平替 Adobe／Office／CAD）
   與 **Blender**（blender.org）`--install` 只偵測；缺少時依它印出的指引幫我裝好（Launcher 裝好後在它的視窗內安裝 GridCraft、WordCraft），
   再重跑 `--install` 直到退出碼為 0。
   裝好 OCSS 後提醒我「開 TW 版一次並在設定啟用 MCP/API」，再跑
   `python tools/crosscheck/ocss_crosscheck.py register-mcp --apply` 與 `probe`。嚴禁對 OCSS 跑 --version／--help。
3. 缺規範資料：`python tools/regs/fetch_regs.py` 然後 `python tools/regs/build_index.py`。
   若 `data/臺中市建物/臺中市建物_114.7z` 尚未解壓，請將其就地解壓縮至 `data/臺中市建物/`（產生 `01-SHP/`）。
4. 註冊 MCP 通道：`python tools/mcp/register_all.py --dry-run` 看會改哪些檔，我同意後再 `--apply`，然後提醒我重開 AI 客戶端。
5. ArtCraft 各 App（經 ArtCraft Launcher 安裝）與 SolidCraft 無法由 `--install` 自動安裝：GridCraft、WordCraft 為交付必要，
   其餘建議裝（CAD 主力是 OpenCADStudio TW，CADCraft 只是備援），AutoCAD 不需要裝。請列出我還缺哪幾套，
   以及該設哪個環境變數（ARTCRAFT_LAUNCHER_EXE／BLENDER／ARTCRAFT_HOME／SOLIDCRAFT_CLI／CAD_FONTS）。
6. 完成後跑 `python tools/regs/verified_selftest.py` 與
   `python tools/selftest/regression.py --ignore-new` 確認可用。
限制：不要改 tools/ 內的程式；不要上傳 data/、out/、_temp/ 內任何檔案。
```

環境變數與各平台的差異（例如備援 CAD 後端 AutoCAD／CADCraft 的出圖配置）
一律記在 [`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)。

## 這個專案能做什麼

功能依工作類型分成六類（絕大多數透過 AI 智能體呼叫，見上一節）。「狀態」欄的意思：

- **現成**：有專用指令，可重跑、有自測或回歸把關。
- **AI 協作**：沒有單一指令，由 AI 組合現有工具（規範庫、設計引擎、OpenCADStudio MCP、品管閘門）完成，依對應文件的 SOP 操作，成果須人工複核。
- **規劃中**：構想已確認可行，尚無專用產線。

### 一、規範查詢與彙整

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 規範查詢 | 關鍵字或條號 → 主題卡、條文全文、**已驗證公式**、**表格** | `tools/regs/regq.py`、MCP `regs`（`regs_ask`／`regs_clause`／`regs_formula`／`regs_table`） | 現成 |
| 依需求彙整設計規範 | 一句設計需求（例：「公路邊的護欄有什麼設計規範？」、「交叉路口改成圓環要考慮哪些？」）→ 適用規範清單、關鍵條文、設計檢核項目與引用出處 | `regs_ask` 依據卡 → `regs_clause` 讀全文確認；34 份規範、1,011 條已驗證公式表格 | 現成（查詢）＋ AI 協作（彙整成清單） |
| 設計規範維護（新增／改版更新） | 一句話（例：「把 114 年版建築物無障礙設施設計規範加進來」、「水保技術規範改版了，幫我更新」）→ 登錄來源與版次、下載原文、重建條文索引與法規目錄、抽查切條與缺號、驗收查得到且條號頁碼正確 | **直接跟 AI 說，照 SOP 做**：[`docs/規範查詢台.md`](docs/規範查詢台.md) §5B／§6 與 [`docs/規範公式圖表入庫SOP.md`](docs/規範公式圖表入庫SOP.md) §9。流程：`fetch_regs.py`（`SOURCES` 登錄來源）→ `build_index.py`（切條、建 sqlite）→ `index_stats.py`／`regq_selftest.py`（缺號、超長條文、驗收）→ `build_catalog.py`（重建目錄）；公式與表格另走 `verified.py` 入已驗證庫 | AI 協作（SOP 已文件化） |
| 規範改版影響分析 | 新舊版規範 → 條文差異清單，以及受影響的已驗證公式、設計引擎與案件；再自動跑回歸確認數字有沒有變 | `fetch_regs.py`／`build_index.py` 的條文索引、`verified.py` 條目、`tools/selftest/regression.py`；條文 diff 與影響對照待建 | 規劃中 |
| 跨規範衝突比對 | 一個設計參數（保護層、載重組合、最小厚度…）→ 各規範數值併排表，標出較嚴者與條文出處 | `verified` 公式／表格庫＋`regs_formula`／`regs_table`＋`regs_clause` 讀全文 | AI 協作（材料現成） |

### 二、設計計算與交叉驗算

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 結構與水理設計 | 構造物參數 → 檢核結果與計算書數據（擋土牆、箱涵、渠道、邊坡、基礎、RC 樑柱…） | `tools/design/design_cli.py`（20 個計算器，統一入口 `design_api.py`） | 現成 |
| 第二套獨立算法交叉驗算 | 同一題目 → 本專案引擎與 Open CalcSheet Studio TW 各算一次並比對數值與單位 | `tools/crosscheck/ocss_crosscheck.py`（需 OCSS 桌面程式開著） | 現成 |
| 參數掃描與最經濟斷面 | 參數範圍（例：牆高 3～8 m、φ 28～36°）→ 掃描表格、趨勢圖，指出最經濟／最省地的斷面 | `tools/design/design_api.py`＋matplotlib／GridCraft；掃描包裝待建 | 規劃中 |
| 多方案比較 | 同一案的多種型式（懸臂式／重力式／扶壁式…）→ 數量、經費、占地、施工難度比較表 | `tools/design/`＋`case_package/qty_models.py`＋`tools/boq/`；整合入口待建 | 規劃中 |
| 改版後批次重算舊案 | 規範或單價更新 → `cases/` 全部重跑，列出數量／經費／檢核結果有變動的案件 | `tools/case_package/case_package.py`＋`tools/selftest/regression.py`；差異報告待建 | 規劃中 |

### 三、製圖、重繪與轉繪

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 現況平面底圖 | 座標或範圍 → TWD97 線稿 DXF（道路邊線、建物、河道） | `tools/site_basemap/site_basemap.py`、`docs/現況平面底圖作業流程.md` | 現成 |
| 地籍套繪圖 | 座標或地號範圍 → A3 地籍圖（坵塊、段籍、建物） | `tools/cadastral/make_cadastral_map.py`、`docs/地籍套繪圖產線.md` | 現成 |
| 斷面圖／配筋圖 | `case.json` → 擋土牆 S-01／S-02、排水溝 D-01／D-02、箱涵斷面 | `tools/wall_section/make_wall_section.py`、`tools/box_section/make_box_section.py` | 現成 |
| A3 出圖 | DXF → DXF／**DWG**／PDF／PNG（圖框、視口、比例尺、monochrome.ctb） | `tools/a3_sheet/make_sheet.py` → `tools/acad/acc.py`（OpenCADStudio TW） | 現成 |
| 依圖面按實尺重繪 | 一張圖面（PDF／影像／他人 DWG）→ 模型空間以**公尺**為單位、真實尺寸的 DXF／DWG，再套本專案圖層、TOMO 字型與圖框 | ezdxf ＋ OpenCADStudio TW MCP（`ocs_measure`／`ocs_audit`）；`tools/drawing_rules.py`；出圖後過 E1~E18 | AI 協作 |
| 他人設計圖收編進標準圖庫 | 他人圖面 → 本專案格式 DWG，分類登錄進元件目錄 | `_ref/build_inventory.py`、`_ref/components_catalog.json`、`docs/常用元件標準圖盤點.md`。`標準圖圖庫/` 為唯讀，實際寫入須你核可 | AI 協作 |
| 既有圖逆向成 `case.json` | 他人設計圖（PDF／DWG）→ 量測與辨識後產生 `case.json`，之後改參數就能重出標準圖、預算與報告 | OpenCADStudio TW MCP（`ocs_measure`／`ocs_query`）＋`tools/case_package/case_core.py`；尺寸與構造判定需人工複核 | AI 協作 |
| 參數化可變尺寸結構體 | 構造物型式與可變參數 → 改尺寸即自動更新的圖塊／模型 | 2D：OpenCADStudio 動態圖塊（block editor 參數與動作）；3D：SolidCraft 參數化（skill `solidcraft-param`） | 2D 規劃中；3D 現成 |

### 四、圖面與預算審查、除錯

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 設計圖合規審查 | 一張設計圖（PDF／DWG）→ 審查意見：尺寸、材料、構造是否符合相關規範，逐條附出處 | DWG → DXF 抽圖元與文字、OpenCADStudio TW MCP 量測、`regs` 查條文、設計引擎重算；本專案自產圖另有 `check_delivery.py`（E1~E18）。前例：`docs/審查_*.md` | AI 協作 |
| 修改 DWG 元件規格／尺寸並同步檢核 | DWG ＋ 要改的元件與新規格 → 修改後 DWG（`ocs_save_verified`）＋ 改後合規檢核 | OpenCADStudio TW MCP（`ocs_query`／`ocs_run`／`ocs_save_verified`）＋ 設計引擎 ＋ `regs` | AI 協作 |
| 預算書除錯 | 預算書 `.xlsx`／`.xlsm` → 錯誤清單：公式斷鏈、數量與單價分析不符、單價無來源、費率與合計錯誤 | `tools/boq/price_audit.py`（單價來源稽核）＋ 逐表解析重算；前例：`docs/審查_崙背羅厝路面改善.md`（路工表 40 段逐段重算） | 現成（單價稽核）＋ AI 協作（全表除錯） |
| 圖／數對帳 | DXF ＋ `case.json` → 圖面量回數量與預算數量比對、配筋間距對帳 | `tools/takeoff/dxf_takeoff.py`（`--rebar`） | 現成 |
| 圖說一致性三方對帳 | 平面圖＋斷面圖＋預算書 → 尺寸與數量對不起來的清單（同一工項三邊核對） | `tools/takeoff/dxf_takeoff.py`（單圖對帳已現成）；跨圖比對待擴充 | 規劃中 |
| 交付前自我審查一頁表 | 一個案件 → 一頁「可以交了嗎」：六道閘門、規範符合性、圖數對帳、單價稽核逐項結果 | `check_delivery.py`＋`price_audit.py`＋`dxf_takeoff.py`＋`design_conformance.py`；彙整入口待建 | 規劃中 |

### 五、文件產製（預算書、報告書、施工／監造計畫）

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 工程預算書 | `case.json` → 5 工作表 `.xlsx` ＋ PDF（費率層活公式） | `tools/boq/boq_build.py`、`docs/預算書產線.md` | 現成 |
| 設計報告書 | `case.json` → 14 章 `.docx` ＋ PDF（R1~R16 回讀驗證） | `tools/report/make_report.py`、`docs/設計報告產線.md` | 現成 |
| 三軸一鍵交付 | `case.json` → 設計圖＋預算書＋報告書＋交付清單 | `tools/case_package/case_package.py` | 現成 |
| 優質報告書格式內化為範本 | 一份參考報告書 → 章節架構、版面、用語整理成本專案報告範本，之後 `make_report.py` 套用 | `tools/report/`（`chapters.py`／`report_model.py`／`docx_build.py`）、`templates/report/` | AI 協作 |
| 施工計畫／監造計畫草擬 | 預算書＋圖說＋規範（可附既有範例）→ 依主辦機關、經費、施作工項、施工順序、檢查停留點與抽查頻率改寫的施工計畫或監造計畫 `.docx` | 預算書逐表解析＋`regs` 查條文＋docx 編輯；尚無專用產線 | 規劃中 |

### 六、3D 與景觀模擬

| 功能 | 你給什麼 → 得到什麼 | 工具／依據 | 狀態 |
|---|---|---|---|
| 景觀平面圖轉 3D 景觀模擬 | 景觀平面圖或手繪示意 → 3D 意象模擬圖（**意象，不是施工圖**）＋正交俯視補圖 | `tools/landscape3d/`（`bay_scene.py`、`park_scene.py`、`plan_view.py`）、Blender；`docs/3D景觀模擬_作業經驗與踩坑.md` | AI 協作（有參考實作） |
| 參數化 3D 構造物 | 口述需求 → 參數化模型、STEP／STL／3MF、成果圖與數量表 | SolidCraft（`tools/solidcraft/`、skill `solidcraft-param`） | 現成 |
| 3D 現況建模與 BIM（**SketchUp 開源平替**） | 基地或構造物 3D 模型 → 推拉式編輯、量測、IFC4／數量 CSV、地形剖面 | **IngeTrazo**（<https://ingetrazo.com/en/>）＋ MCP 橋（`run_python`／`query_model`／`screenshot`）；見 [`docs/IngeTrazo操作指引.md`](docs/IngeTrazo操作指引.md) | 現成（選用，意象與溝通用，**不進交件**） |
| 土方平衡與整地 | 現況地形（DEM／測量點）＋設計高程 → 挖填方數量、最佳整地高程、土方運距初估 | `tools/site_basemap/`＋IngeTrazo／Blender 地形；土方計算模組待建 | 規劃中 |
| 改一個數字重出圖 | 「路寬改 6 m、再出一次」 → 只重建重出，不必重做（參考實測：載入既有 .blend 補 1 張約 40 秒） | `blender` MCP：`blender_run_python`＋`blender_render` | 現成 |
| 程式量測（不靠目視） | 「這個坡面實際多長、車道淨寬夠不夠」 → 從模型讀尺寸、座標，回傳數字與設計值對帳 | `blender_run_python`（腳本設 `RESULT`） | 現成 |
| 3D 模型格式轉換與對帳 | SolidCraft／CAD 的 STL、OBJ、FBX → glb、usd 等，並回報物件數與三角面數 | `blender_convert` | 現成 |
| 簡報、報告用擬真示意圖 | 「這個擋土牆做一張帶光影的示意圖」 → PNG（可去背），放進 GridCraft／WordCraft／DeckCraft 文件 | `blender_render` | 現成 |

> **Blender MCP 很好用**：AI 在背景寫 `bpy` 腳本就能建模、量測、匯出、渲染，不開視窗、不干擾你開著的 Blender。
> 五個工具（`blender_info`／`blender_run_python`／`blender_render`／`blender_convert`／`blender_selftest`）、
> 使用情境、路徑與限制見 [`docs/Blender_MCP_能力與使用情境.md`](docs/Blender_MCP_能力與使用情境.md)。
> 與 SolidCraft 分工：SolidCraft 做精確的參數化構造物，Blender 做場景、光影與意象圖，兩者可接力。

所有交付物一律落在 `out/<案名>/`，並須通過[交付前的六道閘門](#交付前的六道閘門)。

## 五分鐘上手

> **初學者請注意**：本節把每個步驟攤開，是給想看懂細節、手動操作或除錯的人。
> 一般使用請直接用上一節的提示詞，讓 AI 智能體代做。

**支援 Windows、macOS、Linux**。核心功能（設計計算、預算書、報告書、規範查詢、公式庫）三個平台都能跑；
出圖與 DWG 格式設計圖由 **OpenCADStudio TW**（開源、台灣在地化、跨平台）產出，這是 CAD 主力；
AutoCAD（僅 Windows）與 CADCraft 退居**備援**。

### 步驟 1：安裝 Python 3.10+（建議 3.12）

| 平台 | 指令 |
|---|---|
| **Windows** | 從 [python.org](https://www.python.org/downloads/) 下載安裝，**勾選「Add python.exe to PATH」**。或 `winget install Python.Python.3.12` |
| **macOS** | `brew install python@3.12`（或從 python.org 下載） |
| **Linux（Debian/Ubuntu）** | `sudo apt update && sudo apt install python3.12 python3.12-venv python3-pip` |
| **Linux（Fedora/RHEL）** | `sudo dnf install python3.12 python3-pip` |

確認：`python --version`（Windows 若只裝了 py launcher，用 `py -3 --version`）。

### 步驟 2：取得程式並建虛擬環境

```bash
git clone <this-repo>
cd <this-repo>
```

**Windows（PowerShell 或 cmd）**

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**macOS / Linux（bash、zsh）**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> 之後每次開新終端機都要先啟用虛擬環境（Windows `.venv\Scripts\activate`；macOS/Linux `source .venv/bin/activate`）。
> 不想用虛擬環境也可以，但系統 Python 可能不允許 `pip install`（PEP 668），此時加 `--break-system-packages` 或改用 venv。

### 步驟 3：檢查環境（會逐項列出還缺什麼）

```bash
python tools/project_paths.py
```

它會印出：專案根目錄、Python 版本與平台、規範索引在不在、**OpenCADStudio TW**、**Open CalcSheet Studio TW**、
CAD 字體庫、SolidCraft、Blender，以及選用／備援的 15 套 ArtCraft（建議安裝）與 AutoCAD `accoreconsole`（備援）。
加 `--json` 可給安裝腳本吃。**這一步只回報，不安裝。**

### 步驟 3.1：自動安裝必備外部工具（clone 後必做）

```bash
python tools/project_paths.py --install --dry-run   # 先看會裝什麼
python tools/project_paths.py --install             # 實際安裝；退出碼 0 才算環境備妥
python tools/project_paths.py --install --only OpenCalcSheet   # 只補單一工具
```

**必備工具共四項**。其中 OpenCADStudio、Open CalcSheet Studio 一律從使用者 fork 的 GitHub Releases 取「本地化 TW 版」，
**不得改回上游**，由 `--install` 自動安裝；本機若同時裝著上游版，專案一律不採用（路徑只經 `project_paths` 解析）。
ArtCraft Launcher 與 Blender 是 GUI／官方發行版，`--install` **只偵測、缺了就印取得指引並讓退出碼非 0**，不會替你下載：

| 工具 | 用途 |
|---|---|
| **OpenCADStudio TW**<br>來源：[`tutumomo/OpenCADStudio`](https://github.com/tutumomo/OpenCADStudio) | **CAD 主力**（開源、台灣在地化，Big5 SHX 修正，中文不亂碼）：DXF → DWG／PDF、CTB 出圖、MCP 控制。安裝後自動設好 TOMO 字型夾與 CTB 樣式夾（見步驟 3.5） |
| **Open CalcSheet Studio TW**<br>來源：[`tutumomo/Open-CalcSheet-Studio`](https://github.com/tutumomo/Open-CalcSheet-Studio) | 開放計算環境、逐式可稽核計算書、第二套獨立算法（交叉驗算） |
| **ArtCraft Launcher**<br>來源：[`storytold/craft-launcher`](https://github.com/storytold/craft-launcher) | Craft App Suite 的安裝／更新／開啟入口。內含十幾套開源軟體，可平替 Adobe、Office、CAD（PhotoCraft、VectorCraft、PdfCraft、WordCraft、GridCraft、DeckCraft、CADCraft 等）；交付流程必要的 GridCraft（預算書 xlsx）、WordCraft（報告 docx）由它安裝 |
| **Blender**<br>來源：[blender.org](https://www.blender.org/download/) | 3D 景觀模擬、量測、格式轉換與擬真渲染（`blender` MCP 五個工具，見〈[3D 與景觀模擬](#六3d-與景觀模擬)〉） |

各平台安裝方式（`--install` 自動處理）：

| 平台 | OpenCADStudio TW | Open CalcSheet Studio TW |
|---|---|---|
| **Windows** | <sub>`*-installer.msi` → 「Open CAD Studio.TW」</sub> | <sub>檔名含 `.TW_` 的 `setup.exe`，SHA256 校驗後 `/S` 靜默安裝</sub> |
| **macOS** | <sub>dmg → `Open CAD Studio TW.app`</sub> | <sub>dmg</sub> |
| **Linux** | <sub>AppImage → `~/.local/bin/opencadstudio-tw`，自動補選單項目</sub> | <sub>`.deb`：先試 `sudo -n apt-get install`；需密碼時印出 `sudo apt install` 指令請你執行，裝好後再跑一次 `--install` 補防黑屏啟動腳本與選單項目</sub> |

**ArtCraft Launcher 與 Blender 的取得方式**（裝好後再跑一次 `--install` 確認；裝在非標準位置時以 `ARTCRAFT_LAUNCHER_EXE`／`BLENDER` 指定）：

| 平台 | ArtCraft Launcher（[Releases](https://github.com/storytold/craft-launcher/releases/latest)） | Blender |
|---|---|---|
| **Windows** | <sub>`*-windows-x64.msi`（ARM 取 `-arm64`）；裝好後開啟，在視窗內安裝各 App</sub> | <sub>`winget install BlenderFoundation.Blender` 或 blender.org 安裝檔</sub> |
| **macOS** | <sub>`*-macos-universal.dmg` → `/Applications`</sub> | <sub>`brew install --cask blender`</sub> |
| **Linux** | <sub>`*-linux-x86_64`／`-aarch64` 的 `.AppImage`（或 `.deb`／`.rpm`）；AppImage 放 `~/.local/bin/artcraft-launcher`</sub> | <sub>套件管理器、snap／flatpak，或 blender.org 壓縮檔</sub> |

> Launcher 只是入口，**各 App 要在它的視窗裡按 Install**（至少 GridCraft、WordCraft）。CADCraft 隨套件一起裝，但已退居 CAD 備援，CAD 工作不依賴它。

### 步驟 3.2：Open CalcSheet Studio 一次性設定（裝好後做一次）

OCSS 的 API／MCP（`127.0.0.1:3879`）**只在桌面程式開著時存在**，沒有 headless 模式；
**勿對它的執行檔跑 `--version`／`--help`（會卡住）**。

1. 開啟 **Open CalcSheet Studio TW**（上游版請先關掉，兩版搶同一個埠 3879）。
2. 在「設定 › API 與 AI 助理」啟用 MCP／API（token 才會產生）。
3. 註冊並驗證：

```bash
python tools/crosscheck/ocss_crosscheck.py register-mcp --apply   # 寫入本機 .mcp.json（token 不印出、不進版控）
python tools/crosscheck/ocss_crosscheck.py probe                  # 版本、22 個模組（台灣 17 個 tw-*）
python tools/crosscheck/ocss_crosscheck.py checks                 # 本專案引擎 vs OCSS 對照案例
```

43 個 OCSS 工具的用途／參數／路由見 [`docs/OpenCalcSheetStudio_工具清單.md`](docs/OpenCalcSheetStudio_工具清單.md)。

### 步驟 3.3：MCP 通道（讓 AI 直接呼叫工具，選用但建議）

本機 `.mcp.json` 不進版控（含 token 與各機器路徑），由範本 [`.mcp.json.example`](.mcp.json.example) 產生：

```bash
cp .mcp.json.example .mcp.json                                     # Windows：copy
python tools/mcp/register_all.py --apply                           # regs／blender／ingetrazo／opencadstudio-tw（autocad／artcraft 為備援，路徑寫死 Windows，僅 Windows 適用）
python tools/crosscheck/ocss_crosscheck.py register-mcp --apply    # open-calcsheet-studio（讀 TW 版 token）
```

- `opencadstudio-tw`：stdio 橋（`<執行檔> --mcp`），連到**執行中的** Open CAD Studio TW 視窗，不需 token，20 個 `ocs_*` 工具。
- `open-calcsheet-studio`：HTTP（`http://127.0.0.1:3879/mcp`，Bearer token），OCSS 開著才可用。
- 只想更新其中一條：`register_all.py --only opencadstudio-tw --apply`；先看會改哪些檔用 `--dry-run`。
  `register_all.py` 會寫入本機所有 AI 客戶端（Claude Code、Gemini CLI、Codex、OpenCode…），寫檔前先備份。
- 改完重開 AI 客戶端才會載入新工具。

### 步驟 3.5：CAD 字型（自動複製，通常不用動手）

TOMO 文字樣式的**推薦組合是 `gbenor.shx`（英數）＋ `CHINA1.SHX`（中文）**；裝好 OpenCADStudio TW 後中文不會亂碼。
字型已隨 repo 附在 `CAD_FONTS/`，但 DXF 裡只記字型**檔名**，開圖的 CAD 軟體要自己找得到檔案，中文才不會變問號或方框。

本專案的 CAD 主力是 **OpenCADStudio TW**，所以字型**一律替你複製到 OpenCADStudio 自己的字型夾**，
與有沒有 AutoCAD 無關、三個平台都一樣：

```bash
python tools/project_paths.py --install     # 裝 OpenCADStudio TW 時自動做；已裝過的機器也會補做
python tools/project_paths.py --configure   # 只想重做這一步（不下載）
```

- 做了什麼：把 `CAD_FONTS/` 的 `*.shx`（含 `gbenor.shx`、`CHINA1.SHX`）**複製**到 OpenCADStudio 設定夾下的 `fonts/`，
  並把設定檔的 `fonts_folder` 指向該夾。複製進去之後，搬動或刪除專案資料夾也不影響 OpenCADStudio。
  同名檔內容不同時，舊檔先另存 `.bak` 再覆蓋；可重複執行。
- 另外把 `plot_styles_folder` 指向專案的 `tools/acad/plot`（`monochrome.ctb` 出圖樣式，只指向、不複製）。
  設定檔寫入前先備份成 `settings.json.bak`，其餘設定不動。
- 設定夾位置：Linux `~/.config/OpenCADStudio/`、Windows `%APPDATA%\OpenCADStudio\`、macOS `~/Library/Application Support/OpenCADStudio/`。
- 驗證：用 OpenCADStudio 開 TOMO 圖面不再出現 `Missing fonts: CHINA1.SHX, gbenor.shx` 警告；
  `python tools/project_paths.py` 的「CAD 字體庫」一欄有路徑。出圖後仍要目視 PDF 中文。

**備援：AutoCAD 才需要的手動步驟**（只有改用 AutoCAD 當備援後端時才做）：AutoCAD 開圖是到自己的字型目錄找檔，
需另外安裝一次：

```bash
python tools/install_cad_fonts.py           # 先看會裝到哪（不改動）
python tools/install_cad_fonts.py --apply   # 實際安裝（Program Files 受保護，需以系統管理員身分執行）
```

不想用系統管理員權限：AutoCAD → OPTIONS → 檔案 → 字型檔名，把專案的 `CAD_FONTS` 資料夾加入字型搜尋路徑即可
（不影響 DXF 產生，只影響 AutoCAD 開圖與列印時的字型呈現）。

### 步驟 3.6：解壓縮臺中市建物圖資（隨 repo 附壓縮檔，需自行解壓）

本專案已隨 repo 附上 **`data/臺中市建物/臺中市建物_114.7z`**（74.5 MB，解壓後為 `data/臺中市建物/01-SHP/114中_B0001_1216n.shp` 共約 495 MB，供「現況平面底圖 `site_basemap.py`」與「地籍套繪圖 `make_cadastral_map.py`」繪製建物輪廓與樓層數使用）。Clone 或 Fork 後請先**就地解壓縮**至 `data/臺中市建物/` 目錄下：

```bash
# 使用 7-Zip 命令列（或直接在檔案總管對 data/臺中市建物/臺中市建物_114.7z 按右鍵「解壓縮至此」）
7z x "data/臺中市建物/臺中市建物_114.7z" -o"data/臺中市建物"
```

解壓後確認 `python tools/project_paths.py` 的 `臺中建物SHP` 一欄顯示 `[OK]` 即可。

### 步驟 4：下載規範並建索引（第一次需要，之後可略）

```bash
python tools/regs/fetch_regs.py      # 從政府網站下載 34 份現行規範（需網路）
python tools/regs/build_index.py     # 建 data/法規/_regs_index.sqlite
```

> `data/法規/` 不隨 repo 附（法規 PDF 屬原發布機關著作）。沒下載也能跑設計與出圖，
> 只有「規範查詢」與「公式庫的條文原文對照」會缺資料；`tools/regs/verified/` 的
> 1,011 條公式與表格**已隨 repo 附**，不需要下載即可計算。

### 步驟 5：驗證安裝

```bash
python tools/regs/verified_selftest.py          # 公式庫：612 式／399 表每條測試重算
python tools/selftest/regression.py --ignore-new # 全案回歸：11 個案件的預算／斷面／FS／配筋間距
python tools/regs/regq.py "設計一個沉砂池"        # 查一條規範看看
```

### 步驟 6：啟動 Web 服務（規範查詢台與設計工作台）

- **Windows**：雙擊根目錄 `規範查詢台.bat`（查詢台）或 `設計工作台.bat`（設計工作台）
- **Linux / macOS**：
  ```bash
  ./規範查詢台.sh     # 啟動並開啟規範查詢台 (http://127.0.0.1:8765/)
  ./設計工作台.sh     # 啟動並開啟工程設計工作台 (http://127.0.0.1:8765/design)
  # 或使用通用管理指令：
  ./web.sh status    # 檢查服務執行狀態
  ./web.sh stop      # 停止背景服務
  ./web.sh restart   # 重新啟動服務
  ```

三軸交付（需要 `cases/<案名>/case.json`）：

```bash
python tools/case_package/case_core.py check cases/<案名>/case.json
python tools/case_package/case_package.py cases/<案名>/case.json
```

## 環境需求

### 必要（沒有就跑不動核心功能）

| 項目 | 版本 | 用途 |
|---|---|---|
| Python | **3.10+（建議 3.12）** | 全部工具 |
| numpy | ≥1.26 | 設計計算 |
| ezdxf | ≥1.3 | 產生／讀取 DXF |
| matplotlib | ≥3.8 | 圖表、斷面預覽 |
| shapely | ≥2.0 | 幾何運算（範圍、緩衝） |
| pyproj | ≥3.6 | TWD97 ↔ WGS84 座標轉換 |
| PyMuPDF | ≥1.24 | 讀規範 PDF、`find_tables()` |

一行裝完：`python -m pip install -r requirements.txt`。
**不需要**編譯器、GDAL 或任何系統級服務（`pyshp` 取代 GDAL 讀 SHP）。

**必備外部工具（共四項，見步驟 3.1，`python tools/project_paths.py --install` 檢查）**：
**OpenCADStudio TW**（CAD 主力、預設出圖後端，TOMO 字型自動複製進它的字型夾、CTB 樣式夾自動設定）與 **Open CalcSheet Studio TW**（交叉驗算／開放計算環境）由它自動安裝，只綁 TW 版、上游版不採用；
**ArtCraft Launcher**（[`storytold/craft-launcher`](https://github.com/storytold/craft-launcher/releases/latest)，Craft App Suite 啟動器，十幾套開源軟體，可平替 Adobe／Office／CAD）與 **Blender**（[blender.org](https://www.blender.org/download/)，3D）為手動安裝，`--install` 只偵測並印取得指引。

### 選用但影響交付品質

| 項目 | 用途 | 沒有會怎樣 | 平台 |
|---|---|---|---|
| **AutoCAD 2020+**、**CADCraft**（皆為備援） | CAD 主力已是必備的 OpenCADStudio TW；只有 OpenCADStudio 異常或要跨後端比對時，設 `CIVIL_AI_CAD_BACKEND=cadcraft` 才改走 accoreconsole／CADCraft | 不影響（OpenCADStudio TW 已可出 DWG／PDF） | AutoCAD 僅 Windows；CADCraft 支援跨平台 |
| **CAD 字體**（`gbenor.shx`、`CHINA1.SHX`，推薦組合） | TOMO 中文文字樣式 | 圖面中文變替代字體 | **已隨 repo 附於 `CAD_FONTS/`**，`--install`／`--configure` 自動複製進 OpenCADStudio TW 的字型夾；AutoCAD 備援另需手動，見步驟 3.5 |
| **ArtCraft 各 App**（經必備的 ArtCraft Launcher 安裝；GridCraft／WordCraft 為交付必要，其餘選用。內含的 CADCraft 僅備援） | 預算書 xlsx、報告 docx、轉檔 | 對應產出需改用其他方式 | 依該套是否有該平台版本 |
| SolidCraft | 3D 參數化建模 | 對應功能停用 | 依平台而定 |

### 開源平替軟體（選用；不裝也能交付，裝了少訂一堆軟體）

本專案的主力工具都是開源或免費版；下面這幾套是「商業軟體的開源平替」，用得到再裝：

| 平替對象 | 開源軟體 | 取得方式 | 在本專案的角色 |
|---|---|---|---|
| **SketchUp**（推拉式 3D 建模） | **IngeTrazo** | 官網 <https://ingetrazo.com/en/>；原始碼／Releases <https://github.com/ingelibre/ingetrazo> | 選用。3D 構造建模、匯入 DWG／SketchUp（OpenSKP）、輸出 IFC4 與數量 CSV、地形剖面；GUI＋MCP 橋，AI 可直接建模。**只補能力、不進交件**，見 [`docs/IngeTrazo操作指引.md`](docs/IngeTrazo操作指引.md) |
| **Adobe 套裝** | ArtCraft 的 **PhotoCraft**（≈Photoshop）、**VectorCraft**（≈Illustrator）、**PdfCraft**（≈Acrobat）、**DesignCraft**（≈InDesign）、**FigCraft**、**LightCraft**、**EffectCraft**、**FilmCraft**、**SoundCraft** | 先裝 **ArtCraft Launcher**（必備）<https://github.com/storytold/craft-launcher/releases/latest>，再從它的視窗安裝各 App | 現場／竣工照片整理、向量圖與標準圖、PDF 合併抽頁 OCR、成果簡報與影片 |
| **Microsoft Office 套裝** | ArtCraft 的 **WordCraft**（≈Word）、**GridCraft**（≈Excel）、**DeckCraft**（≈PowerPoint） | 同上（經 ArtCraft Launcher 安裝） | **GridCraft、WordCraft 是交付必要**：工程預算書 `.xlsx`、設計報告 `.docx` 都由 `tools/boq/boq_build.py`、`tools/report/make_report.py` 產出後用它們開啟／轉 PDF；DeckCraft 用於成果簡報 |

> ArtCraft 不必整套安裝，但 **GridCraft 與 WordCraft 缺了會影響交付**；CADCraft 僅在 OpenCADStudio TW 異常時當備援。完整 15 套對照見 [`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)。

### 跨平台差異

| 功能 | Windows | macOS | Linux |
|---|---|---|---|
| 設計計算、預算書、報告書、規範查詢、公式庫 | ✅ | ✅ | ✅ |
| 出 DXF／PNG／SVG | ✅ | ✅ | ✅ |
| 出 **DWG 格式設計圖** | ✅（OpenCADStudio TW；備援 AutoCAD／CADCraft） | ✅（OpenCADStudio TW；備援 CADCraft） | ✅（OpenCADStudio TW；備援 CADCraft） |
| 出 PDF（配置出圖，monochrome.ctb） | ✅（同上） | ✅（同上） | ✅（同上） |
| Open CalcSheet Studio 交叉驗算 | ✅ | ✅（dmg，尚待實測） | ✅（`.deb`，aarch64 已實測） |

> 出圖統一經 `tools/acad/acc.py`：預設由 OpenCADStudio TW 以 `--http` 背景實例產 DWG／PDF，
> 設 `CIVIL_AI_CAD_BACKEND=cadcraft` 改走 accoreconsole／CADCraft。出圖後務必目視 PDF 中文。

### 環境變數（想改路徑時才需要，程式不必改）

```bash
CIVIL_AI_ROOT      # 專案根目錄（預設＝repo 位置）
CIVIL_AI_REGS_DB   # 規範索引 sqlite（預設 data/法規/_regs_index.sqlite）
ARTCRAFT_LAUNCHER_EXE  # ArtCraft Launcher 執行檔（必備；PATH 上有 artcraft-launcher 時可不設）
BLENDER            # Blender 執行檔（必備；PATH 上有 blender 時可不設）
ARTCRAFT_HOME      # ArtCraft 各 App 安裝根目錄（Windows 預設 C:\Program\ArtCraft）
AUTOCAD_HOME       # AutoCAD 安裝目錄（含 accoreconsole.exe；僅備援後端用）
SOLIDCRAFT_CLI     # SolidCraft CLI 完整路徑
INGETRAZO_HOME     # IngeTrazo 安裝根目錄（預設 C:\Program Files\IngeTrazo）
INGETRAZO_MCP      # IngeTrazo MCP 橋完整路徑（預設 <HOME>\ingetrazo-mcp.exe）
BLENDER            # Blender 執行檔
OPENCADSTUDIO_EXE  # OpenCADStudio TW 執行檔（只在解析不到時才設；勿指向上游版）
OCSS_EXE           # Open CalcSheet Studio TW 執行檔
OCSS_API_TOKEN     # OCSS token 臨時覆寫（預設讀 TW 版 preferences.json 的 mcpToken；機密，勿寫入檔案）
OCSS_PORT          # OCSS 埠臨時覆寫（預設 3879）
CIVIL_AI_CAD_BACKEND # 出圖後端；預設 OpenCADStudio TW，設 cadcraft 才退回備援的 accoreconsole／CADCraft
CAD_FONTS          # CAD 字體庫來源目錄（預設＝專案內 CAD_FONTS/，已隨 repo 附；--install 會把它複製進 OpenCADStudio 字型夾）
CIVIL_AI_STD_BLOCKS # 公司標準元件 DWG 資料夾（_ref 重建腳本用）
```

Windows 設定方式（ PowerShell，永久）：`setx ARTCRAFT_HOME "C:\Program\ArtCraft"`；
macOS／Linux：寫進 `~/.bashrc` 或 `~/.zshrc` 的 `export ARTCRAFT_HOME=...`。

### 常見問題

| 症狀 | 原因與解法 |
|---|---|
| `python: command not found` | Windows 只裝了 py launcher → 用 `py -3`；macOS/Linux 用 `python3` |
| `pip install` 被拒（externally-managed-environment） | 先建 venv（步驟 2），或加 `--break-system-packages` |
| 中文變問號／方框 | CAD 軟體找不到 SHX 字型。OpenCADStudio TW：執行 `python tools/project_paths.py --configure` 把 `CAD_FONTS/` 複製進它的字型夾（`--install` 已自動做過），重開圖並目視 PDF。備援用 AutoCAD 才需 `python tools/install_cad_fonts.py --apply`（需系統管理員權限），或在 OPTIONS → 字型檔名加入該資料夾 |
| `規範索引 missing` | 還沒跑 `python tools/regs/build_index.py`（需先 `fetch_regs.py`） |
| `找不到 ArtCraft` | ArtCraft 為建議安裝（非 CAD 必備）。未安裝或路徑非預設時，設 `ARTCRAFT_HOME` |
| 產不出 DWG | 先確認 OpenCADStudio TW 已裝好（`python tools/project_paths.py --install`）；它是預設後端。只有改用備援後端（`CIVIL_AI_CAD_BACKEND=cadcraft`）時，才檢查 AutoCAD／CADCraft 與 `AUTOCAD_HOME` |
| IngeTrazo MCP 工具呼叫失敗 | 它只是 GUI 的橋：先開 IngeTrazo → 開文件 → Extensões ▸ AI Bridge (MCP)，再跑 `python tools\ingetrazo\ingetrazo_check.py --call`；`tools/list` 過關不代表能用 |
| `project_paths.py` 顯示「偵測到上游版…本專案不採用」 | 只裝了上游版。跑 `python tools/project_paths.py --install` 裝 TW 版（見步驟 3.1） |
| OCSS `probe` 回 401「token 不正確」 | 連到了上游版（兩版搶埠 3879，先開者佔），或換版／換 token 後沒重跑 `register-mcp --apply`。關掉上游版、開 TW 版並啟用 API 後重跑 |
| Linux 上 OCSS 視窗全黑 | WebKitGTK GPU 緩衝區無權限。從選單或 `~/.local/bin/open-calcsheet-studio-tw` 開（已帶 `WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1`）；`apt` 升級後重跑 `--install` 補回 |
| Linux 選單看不到 OpenCADStudio TW | AppImage 不會自建選單項目；重跑 `python tools/project_paths.py --install` 會補「Open CAD Studio TW」。選單沒更新可 `xfce4-panel -r` 或重新登入 |
| 出圖回 400「Drawing edit lock is held」 | 你在 OpenCADStudio 視窗開著同一張 DXF，持有編輯鎖。先在 GUI 存檔並關圖再重跑 |
| 想要 Claude Code 跨 session 記住專案脈絡 | 裝 claude-mem：`powershell -ExecutionPolicy Bypass -File ".agents\setup\claude-mem-install.ps1"`（需 Node 20+）。它只影響 Claude Code 的記憶，**不改本專案任何產線行為**，見 [`docs/claude-mem安裝與使用.md`](docs/claude-mem安裝與使用.md) |

完整清單（15 套 ArtCraft 對照、MCP 伺服器、Skills、資料取得方式、給智能體的自動配置指令範本）見
**[`docs/環境需求與自動配置.md`](docs/環境需求與自動配置.md)**；
Open CalcSheet Studio 的整合、單位陷阱與能力邊界見 **[`docs/OpenCalcSheetStudio_整合與開放計算環境.md`](docs/OpenCalcSheetStudio_整合與開放計算環境.md)**；
IngeTrazo（3D／BIM、GUI＋MCP 橋）見 **[`docs/IngeTrazo操作指引.md`](docs/IngeTrazo操作指引.md)**；
Claude Code 的跨 session 持久記憶見 **[`docs/claude-mem安裝與使用.md`](docs/claude-mem安裝與使用.md)**。

## 核心概念：案件主檔是唯一數據來源

一份 `cases/<案名>/case.json`（schema `civil-case/1`）寫一次數量，**設計圖、預算書、報告書都由它派生**，
不再維護三份 JSON。`case_core.check` 會驗算模型算式，不符直接 error 中止。

```jsonc
{
  "schema": "civil-case/1",
  "case_name": "示範案",
  "type": "wall",                 // road / wall / channel / slope
  "quantities": {
    "model": "wall",
    "wall_type": "cantilever",    // gravity / cantilever
    "H": 4.0, "L": 50.0, ...      // 幾何參數
  }
}
```

## 工具鏈地圖

```
                         ┌─ site_basemap ─→ a3_sheet ──→ DWG/PDF/PNG
  case.json ──check──┬───┤
  (唯一數量來源)       │   ├─ wall_section ─→ 斷面圖/配筋圖 ─→ dwg
                     │   ├─ boq_build ───→ 預算書 xlsx/PDF
                     │   └─ make_report ─→ 設計報告 docx/PDF
                     └─ design/*（20 個計算器）← 規範公式庫 regs/verified
```

| 層 | 目錄 | 說明 |
|---|---|---|
| 設計計算 | `tools/design/` | 20 個計算器，統一 JSON 入口 `design_api.py`；每個都有 selftest |
| 數量模型 | `tools/case_package/qty_models.py` | 依類別（road／wall／channel／slope）算數量，**不可用道路公式硬套牆／溝** |
| 出圖 | `tools/a3_sheet/`、`tools/wall_section/`、`tools/box_section/` | ezdxf 建模 → `acc.py`（預設 OpenCADStudio TW；備援 accoreconsole／CADCraft）轉 DWG／PDF |
| 預算 | `tools/boq/` | `boq_rules.py` 費率層已與真實預算書對帳；`price_audit.py` 稽核單價來源 |
| 報告 | `tools/report/` | 14 章骨架；`verify_report.py` 做 R1~R16 回讀驗證 |
| 規範 | `tools/regs/` | 下載、索引、查詢、**已驗證公式／表格庫** |
| 品管 | `tools/a3_sheet/check_delivery.py`、`tools/selftest/` | E1~E18 出圖品管、圖數對帳、全案回歸 |
| 交叉驗算 | `tools/crosscheck/` | 同一題用本專案引擎與 Open CalcSheet Studio TW 各算一次比對（`ocss_crosscheck.py probe／eval／checks`）；需桌面程式開著，**不進**回歸預設流程。開放環境的結果須交叉驗算才可進交付 |
| 外部 3D／BIM（選用；**SketchUp 開源平替**） | IngeTrazo（<https://ingetrazo.com/en/>）＋ MCP 橋 | 3D 構造、IFC4／數量 CSV、地形剖面；**只補能力、不進交件**，見 `docs/IngeTrazo操作指引.md` |

## 規範公式圖表庫

`tools/regs/verified/` 是本專案最花時間的部分：把 34 份現行台灣土木規範的**公式與表格**逐條轉成
機器可讀、可算、可回查的結構化資料。

| 指標 | 數量 |
|---|---|
| 已驗證條目 | **1,011**（612 公式／399 表格） |
| 覆蓋規範 | 34 份（水保、道路、排水、邊坡、鋪面、交通、施工、橋梁、建築結構…） |
| flagged 條文已轉換／已涵蓋 | **959 / 1,384（69.3%）** |
| 待核（原文疑誤／來源缺漏） | 0 |

每條都有：LaTeX、變數與單位、可執行程式碼、適用條件、**測試案例**、以及與原書頁碼的對照。
取用方式：

```bash
python tools/regs/regq.py --clause swc_tech 119         # 條文全文
python -c "import sys; sys.path.insert(0,'tools/regs'); import verified as V; \
f,t=V.load(); e=f['swc_tech:119'] if 'swc_tech:119' in f else None; print(e and e['latex'])"  # 公式
```

品質保證（每次改動都跑）：

```bash
python tools/regs/payload_check.py --library   # 結構與數值檢查
python tools/regs/verified_selftest.py         # 每條測試案例重算
python tools/regs/regq_selftest.py             # 查詢台問答
python tools/regs/design_conformance.py        # 引擎 ↔ 已驗證庫 雙向比對
```

方法論寫在 [`docs/規範公式圖表入庫SOP.md`](docs/規範公式圖表入庫SOP.md)，
踩過的坑在 [`docs/踩坑紀錄.md`](docs/踩坑紀錄.md)（含索引 `docs/經驗索引_INDEX.md`）。

## 交付前的六道閘門

| # | 閘門 | 指令 |
|---|---|---|
| 1 | 設計檢核全過 | `case_core.py check` |
| 2 | E1~E18 出圖品管 | `check_delivery.py` |
| 3 | 圖／數對帳（DXF 量回與 case.json 比對） | `dxf_takeoff.py`（已內建於 section 軸） |
| 4 | 配筋圖間距對帳 | `dxf_takeoff.py --rebar` |
| 5 | 設計段落注入（報告的 `_derived` 無 error） | `case_package` 內建 |
| 6 | 全案回歸 | `tools/selftest/regression.py` |

總表見 [`docs/交付閘門總表.md`](docs/交付閘門總表.md)。

## 目錄結構

```
├── AGENTS.md                 共用作業規範（智能體常駐主規範）
├── README.md
├── requirements.txt
├── .mcp.json.example         MCP 設定範本（本機 .mcp.json 不入版控）
├── CAD_FONTS/               TOMO 用 SHX 字型（推薦 gbenor.shx＋CHINA1.SHX），自動複製進 OpenCADStudio TW
├── 怎麼用.md                 給人看的入口（三步驟、四類案件、六道閘門）
├── tools/
│   ├── project_paths.py      ★ 路徑與外部程式的唯一解析入口（跨平台、無絕對路徑）
│   ├── design/               20 個設計計算器 + 統一 JSON 入口
│   ├── case_package/         案件主檔、數量模型、三軸編排
│   ├── a3_sheet/             A3 出圖與 E1~E18 品管
│   ├── wall_section/         斷面圖／配筋圖
│   ├── site_basemap/         現況底圖（NLSC／OSM → TWD97 DXF）
│   ├── cadastral/            地籍套繪圖
│   ├── boq/                  預算書（boq_rules 費率、prices 單價庫）
│   ├── report/               設計報告書
│   ├── regs/                 規範下載／索引／查詢／已驗證公式庫
│   │   ├── verified/         ★ 1,011 條已驗證公式與表格
│   │   ├── page_crop.py      PDF 裁圖（讀原頁公式）
│   │   ├── page_index.py     印刷頁碼 → PDF 頁
│   │   ├── locate_pages.py   關鍵字定位頁碼
│   │   ├── dump_tables.py    find_tables 表格骨架
│   │   ├── audit_qualitative.py / audit_skip_reasons.py / reconcile_progress.py
│   │   └── payload_check.py / verified_selftest.py / design_conformance.py
│   ├── selftest/             全案回歸
│   ├── acad/                 統一出圖入口 acc.py（預設 OpenCADStudio TW）、出圖型式 CTB
│   ├── crosscheck/           OCSS 交叉驗算（ocss_client.py、ocss_crosscheck.py、ocss_tools_doc.py）
│   ├── install/              外部工具自動安裝（toolchain.py，由 project_paths --install 呼叫）
│   ├── mcp/                  MCP 一次註冊到各 AI 客戶端（register_all.py）
│   └── clean_project.py      清理暫存（--dry-run / --apply）
├── data/                     法規全文／索引、臺中市建物_114.7z（隨 repo 附，Clone/Fork 後需就地解壓）
├── cases/                    案件主檔
├── docs/                     知識文件（產線說明、法規庫、踩坑紀錄）
├── templates/                報告與規範條文模板
├── 標準圖圖庫/                公司標準圖（自有資料，不入版控）
└── out/                      交付物唯一落點（不入版控）
```

## 資料來源與授權

- **法規全文**：各級政府機關公開資料（交通部、內政部國土管理署、農業部、臺中市…），
  由 `tools/regs/fetch_regs.py` 下載並記錄來源 URL 與版本於 `data/法規/_regs_manifest.json`。
- **地圖與地籍**：內政部國土測繪中心（NLSC）、臺中市開放資料、OpenStreetMap。
- **規範公式庫**：由本專案逐條轉錄並加註出處（規範名稱、版次、頁碼、條號）。
  **引用前請回原規範確認**；本庫不是法規的替代品，正式設計須經技師覆核。
- 本 repo 的程式碼可自由使用與修改；但**規範本文的著作權屬原發布機關**，
  `data/法規/` 內的 PDF 與全文不隨 repo 散布，請用 `fetch_regs.py` 自行下載。

> 本專案輸出之設計圖、預算書與報告書，**設計責任仍由簽證技師承擔**。
