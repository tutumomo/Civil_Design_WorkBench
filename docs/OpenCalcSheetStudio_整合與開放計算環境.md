# Open CalcSheet Studio 整合與開放計算環境

> 定位：本專案的**第 5 條計算通道**——不是取代 `tools/design/`，而是補上「逐式可稽核的計算過程」與「第二套獨立算法」。
> 建立：2026-11-10（全部內容為當日實機驗證，非推測）。

## 1. 一句話定位

| 工具 | 給什麼 | 性質 |
|---|---|---|
| `tools/design/`（`design_run`） | 權威數值 | 封閉、有回歸基線、規範條號已驗證 |
| **Open CalcSheet Studio** | 可稽核的計算書 ＋ 開放計算環境 | 開放、逐式展開、需自律 |
| `tools/report/make_report.py` | 排版交付 | 不計算 |

三者串起來才是完整鏈條：`design_run` 定案 → OCSS 寫過程 → 交叉驗算 → `make_report.py` 排版。

OCSS 的台灣版另有 **17 個 `tw-*` 現成模板**，但那只是它的示範應用；真正的價值在底層的計算語言。

## 2. 實測環境（2026-11-10，Windows 11）

* 桌面程式：**TW 版**（fork 本地化版，資料夾「Open CalcSheet Studio TW」、識別碼 `tw.opencalcsheet.studio`）。本機同時裝有上游版（「Open CalcSheet Studio」、`studio.openstructuralcalculation.app`），**本專案只綁 TW 版**；路徑**不寫死**，見第 6.4 節
* 橋接器：`http://127.0.0.1:3879`，MCP 在 `/mcp`、REST 在 `/api/v1`，同一支 Rust 橋接器、同一份工具 registry（49 個工具）
* 模組 22 個：台灣 17 個（全部 `gereed`）＋上游 5 個（`ligger`、`doorsnede-spanningen`、`balklaag`、`tweepaalspoer`、`rekentaal-demo`）
* 版本查詢：`python tools/crosscheck/ocss_crosscheck.py probe`（**不要把版本號當規格寫進程式或檢核條件**，見 AGENTS.md §3）

台灣 17 個模組：RC 梁／柱／單向板、獨立基腳、樁帽、鋼梁、鋼柱、懸臂式擋土牆、重力式擋土牆、排水溝、箱涵、滯洪池、沉砂池、水面線標準步進、地震力、風力、靜載重與活載重。

## 3. 三種用法

### 3.1 模板（標準檢核）

套現成 `tw-*` 模板、灌輸入、取 UC 與合格判定。適合「規範已有明定公式」的常規檢核。

```
sheet_add(templateId="tw-retaining-wall") → sheet_set_input(values) → sheet_evaluate
```

輸入欄位名是英文變數（`H_wall`、`phi_deg`…），`label` 為中文並帶規範條號。實測 12 個輸入對應 `tools/design/retaining_wall.py` 的參數，一次 evaluate 回 19 個 UC 分量與 `passes`。

### 3.2 開放計算環境（本節重點）

任意計算書都能寫，不必套模板。語言特性（實測）：

| 能力 | 實測結果 |
|---|---|
| 單位運算 | `b*y` 自動得 m²；`to MPa`／`to N/mm^2` 可強制換算 |
| 條件 | `#if … #else … #end if` |
| 迴圈 | `#repeat n` 內可更新變數 → 可寫迭代法（二分法、牛頓法） |
| 隱藏 | `#hide … #show`，中間迭代不上版面 |
| 錯誤攔截 | 語法錯誤回 `errorLines: 1` 並在該行標 Error |
| 鉅集 | `#def` 巨集、`#include` 外部片段 |
| 跨表 | `#2.R_paal` 引用他表值，自動依賴排序、循環偵測 |
| 繪圖 | 內嵌 SVG（可綁變數）、`$Plot` 曲線、`@js`＋three.js |

**驗證案例**（`tools/crosscheck/checks/water_depth_manning.json`）：矩形渠正常水深，二分法 80 次迭代。

```
本專案 channel_hydraulics.normal_depth(Q=1, b=1, n=0.015, S=0.001) = 0.9890881180763245 m
OCSS 開放環境手寫計算書                                          = 0.9890878956801226 m
差值 2.2e-7 m（純為迭代次數差異）
```

### 3.3 MCP／REST 給智能體

49 個工具，MCP 與 REST 完全等價（`POST /api/v1/tools/{name}` 帶 MCP 參數即可）。註冊方式見第 6 節。**逐一工具的用途、參數與路由見 [`OpenCalcSheetStudio_工具清單.md`](OpenCalcSheetStudio_工具清單.md)**（由 `tools/crosscheck/ocss_tools_doc.py` 從執行中的 OCSS 生成，升版後重跑；`--check` 可比對是否過期）。

**工作表種類（2026.45.2-tw.5 起，`sheet_add` 的 `kind` 參數）**：`calculation`（預設，土木計算）｜`markdown`（說明文字）｜`graph`（節點圖）｜`drawing`（繪圖工作表）｜`spreadsheet`（XLSX 活頁簿）｜`jupyter`（`.ipynb` 工作資料夾）｜`marimo`（`.py` 筆記本）；PDF 另有 `sheet_add_pdf`。對應的「整張取代」工具為 `sheet_set_markdown`／`sheet_set_graph`／`sheet_set_drawing`／`sheet_set_spreadsheet`／`sheet_set_jupyter`／`sheet_set_marimo`（2026.45.2-tw.5 新增，6 項；tw.4 以前只有 `sheet_set_source`／`sheet_set_input`／`sheet_set_pdf`）。

## 4. 能力邊界（重要）

| 可以做 | 不要期待 |
|---|---|
| 公式鏈計算：土壓力、水理、載重組合、RC 斷面檢核 | 通用 FEM（連續梁、剛架、版殼、土體、滲流）——**沒有內建求解器** |
| 迭代求解（自己寫二分法／牛頓法，固定次數） | 「迭代至收斂」語法——只有固定次數的 `#repeat`／`#for lo:hi` |
| 查表與內插（`hlookup`／`vlookup`／`take`／`get`） | 自動判斷結果合理性——它只做量綱運算，不會提醒數字荒唐 |
| 樁支承板有限元（`plaat_palen()`，DKT 元素） | 其他任何有限元模型 |
| 產出 IFC／IFCX（`export_ifc`，實測正常） | **API 產 PDF**——`export_pdf` 在一般安裝版回 501（無 rapportengine）；PDF 只能在 App 內按「Rapport」 |

`@toets` 區塊會把檢核丟給隨附的 Open FEM Studio；但 **API 與匯出不會去問它**，沒回答的一律標「未檢核」，永遠不會被當成「合格」。

## 5. 兩個單位陷阱（不報錯，最危險）

OCSS 對單位是「誠實但不體貼」：它標對單位，卻不會阻止你產出工程上荒唐的結果。這兩條已內建自動偵測（`ocss_client.unit_warnings()`）。

### 陷阱 1：分數次方污染單位

```
R = 0.3321 m
Q = A*R^(2/3)*S^(1/2)     →  單位 m^2.6666666666666665
```

數值正確、單位荒謬、`errorLines = 0`。Manning 這類公式必踩。

**SOP**：先無因次化，算完再掛回目標單位。

```
R_m = R/(1 m)                                  // 純數
Q   = (1/n)*(A/(1 m^2))*R_m^(2/3)*S_0^(1/2) m^3/s
```

### 陷阱 2：單位不會收斂到慣用單位

```
sigma = M/W        →  40 kN/mm²     （= 40000 MPa，差 1000 倍）
sigma = M/W to MPa →  40000 MPa
```

**SOP**：每個結果顯式指定目標單位（`to MPa`、`to kN`、`to m^3/s`），不靠自動推導。寫計算書時當成硬規則。

## 6. 工具與設定

### 6.0 安裝（必備工具，`git clone` 後由 `--install` 自動完成）

Open CalcSheet Studio（來源 [`tutumomo/Open-CalcSheet-Studio`](https://github.com/tutumomo/Open-CalcSheet-Studio)）自 2026-11-10 起為**必備工具**，與 OpenCADStudio 同列於 `tools/install/toolchain.py`，鍵名 `OpenCalcSheet`：

```bash
python tools/project_paths.py --install --dry-run               # 先看計畫
python tools/project_paths.py --install                         # 補齊所有缺漏（含 OpenCADStudio）
python tools/project_paths.py --install --only OpenCalcSheet    # 只補它
```

| 平台 | 行為 |
|---|---|
| Windows | 取 release 中檔名含 `.TW_` 的 `*_x64-setup.exe`（安裝到「Open CalcSheet Studio TW」，與上游並存）→ 以同 release 的 `SHA256SUMS.txt` 校驗（不符即刪檔並中止）→ `setup.exe /S` 靜默安裝（可能跳 UAC，請使用者核准）→ 以 `opencalcsheet_exe()` 確認。失敗時安裝檔保留在系統暫存夾，印出手動執行指令 |
| Linux | `.deb` 需 root，**只下載並印出 `sudo apt install …`**，由使用者自行執行 |
| macOS | 掛載 dmg → 複製 `.app`（沿用 OpenCADStudio 的流程，**尚未實測**） |

* 已安裝（由 `opencalcsheet_exe()` 判定）則略過，**不自動升級**；要升級請手動下載新版。
* 偵測**不執行**它的 `--version`／`--help`（實測會卡死），完全靠路徑解析。
* 實測（2026-11-10，Windows）：資產挑選、SHA256 校驗、已安裝略過皆驗證通過；靜默安裝步驟本身因本機已裝而未實際執行，換一台乾淨機器第一次跑時請留意安裝程式是否彈 UAC 或安裝到非預期位置。

**安裝後還有兩步，`--install` 不會代做**（需要程式實際跑過才有 token）：

1. 開啟 Open CalcSheet Studio 一次，並在設定中啟用 MCP／API（token 與埠才會寫進 `preferences.json`）。
2. 產生 MCP 條目並驗證連線：

```bash
python tools/crosscheck/ocss_crosscheck.py register-mcp          # 預覽（token 以 **** 隱藏）
python tools/crosscheck/ocss_crosscheck.py register-mcp --apply  # 寫入本機 .mcp.json（先備份 .mcp.json.bak）
python tools/crosscheck/ocss_crosscheck.py probe                 # 確認連線與 17 個 tw-* 模組
```

### 6.1 交叉驗算 CLI

```bash
python tools/crosscheck/ocss_crosscheck.py probe           # 連線、版本、模組清單
python tools/crosscheck/ocss_crosscheck.py eval --expr "M = 20 kN*m\nW = 500 mm^3\nsigma = M/W to MPa"
python tools/crosscheck/ocss_crosscheck.py eval --file _temp/x.cpd
python tools/crosscheck/ocss_crosscheck.py checks          # 跑內建對照案例
python tools/crosscheck/ocss_crosscheck.py register-mcp    # 預覽 .mcp.json 條目；加 --apply 才寫檔
```

**前提：桌面程式必須開著。** 橋接器隨 App 啟動，關掉就沒有埠；沒有 headless 模式，也**不要**執行 `--version`／`--help`（實測會卡住）。因此本工具**不納入** `tools/selftest/regression.py` 的預設流程。

新增對照案例：在 `tools/crosscheck/checks/` 放一個 JSON，`reference` 指本專案引擎的檔案／函式／參數，`ocss` 放計算書與要取用的結果變數，`tolerance` 給 `rel`／`abs`。CLI 會自動載入引擎、執行、比對數值與單位。

**template／formula 型案例**（X1 起）：`{"type": "template", "calculator": ..., "payload": ..., "template": "tw-*", "ocss_inputs": {...}, "compare": [...]}`；無模板者用 `"type": "formula"` 改寫 `"source"`（逐行手寫公式鏈，一律無因次化）。比較項可用 `reciprocal`（UC→FS）與 `scale`（兩邊單位不同，例 m→mm）。差異超過容差時必須寫 `disposition`（`engine_fixed`／`template_issue`／`explained`＋理由），沒有處置的差異視為失敗。

現有案例（2026-11-11，14 項；13 過、1 項刻意維持未處置＝懸臂牆 M_over）：

| 案例檔 | 對象 | 結果 |
|---|---|---|
| `channel_hydraulics_template.json` | 排水溝 ↔ `tw-drainage-channel` | 6 項全過 |
| `gravity_wall_template.json` | 重力牆 ↔ `tw-gravity-retaining-wall` | 全過（超載設 0 對齊） |
| `box_culvert_template.json` | 箱涵 ↔ `tw-box-culvert` | 2 項處置（倒角扣面積、載重模型不同） |
| `wall_stability_template.json` | 懸臂牆 ↔ `tw-retaining-wall` | M_over 差 1.2%，**刻意未處置**（引擎不計超載、土壓高度不含底板厚） |
| `foundation_isolated_template.json` | 獨立基腳 ↔ `tw-isolated-footing` | 6 項全過（自重／覆土歸零對齊） |
| `rc_beam_template.json` | RC 梁 ↔ `tw-rc-beam` | V_c 全等；A_s,min／φM_n 差 1.1%／1.3%，處置為「本專案撓曲 d＝h−50 未扣主筋半徑」 |
| `rc_column_template.json` | RC 柱 ↔ `tw-rc-column` | A_st 差 0.2%；φM_n 差 6.3%，處置為「120 點應變相容曲線 vs 三點簡化折線」 |
| `steel_column_template.json` | 鋼柱柱腳 ↔ `tw-steel-column` | 7 項全過（錨栓改 4 支以對齊模板假設）；**查出並修正兩個引擎錯誤**（見下） |
| `foundation_pile_formula.json` | 樁群 ↔ 手寫公式鏈 | R_max／R_min 全等（`tw-pile-cap` 無單樁反力輸出，R_out 是幾何距離） |
| `channel_profile_template.json` | 水面線 ↔ `tw-backwater-profile` | 5 項全過（y_n／y_c／y_max／V_max／V_min，差 <1e-4%） |
| `hydrology_formula.json`／`channel_cover_formula.json`／`foundation_combined_formula.json` | X4 公式鏈 | 全過（最大差 0.005%） |

**X3 查出的引擎錯誤（2026-11-11 已修）**：
1. `steel_column._contact_pressure()` 基板接觸壓力寫成 `M×(L/2)/S`（多乘 L/2）且 x／y 向邊長互換 → q_max 低估 (L/2) 倍（例 0.5×0.55 m 基板、P=700 kN、M=280 kN·m：應 13,653 kPa，原式只給 5,600 kPa），連帶基板厚度與揚起判定偏不安全。
2. `steel_column.base_plate_bearing()` 規範式回傳 kgf，卻以 `/100` 換算 tf（應 `/1000`）→ 混凝土承壓設計強度 φPp 高估 **10 倍**（61,752 kN vs 正確 6,175 kN）。

**不可比（已查明，不是沒做）**：滯洪池 `tw-detention-basin` 用水保 §35 合理化公式＋體積法（無演算），本專案 `detention_basin` 用 Modified Puls 入流歷線演算，唯一共有的孔口式 Q = Cd·A·√(2gh) 兩邊一致（h = 1.8 m、D = 0.2 m 時 0.1158 m³/s），但沒有共同的情境輸出；沉砂池 `tw-sediment-basin` 用 §35 Rm·Km 表法，本專案用一般 USLE 產量，基準不同。砌石／蛇籠牆（`block_wall`）無對應模板（`tw-gravity-retaining-wall` 是有筋重力式，另案比過）。三者以 `design_core_selftest.py` 的手算對照為準。

**尚未處置、待技師決定**：`rc_column` 的互制曲線未套 rc112 10.3.6.2 拴柱 `0.80P0` 軸壓上限（近純軸壓時偏高）；`retaining_wall.analyse()` 不計超載、土壓高度不含底板厚（X2 已知）；`foundation_isolated` 的壓力只吃柱載重 P／M，不含基腳自重與覆土（模板含）。三者都會改動設計結果與回歸基準，屬設計變更。

### 6.1b 逐式計算書（X5）與上游載重模組（X6）

```bash
# X5：把交叉驗算案例做成 OCSS 專案檔（.ifccalculation）＋機讀結果 JSON
python tools/crosscheck/ocss_calcbook.py build --out out/<案名> --name <案名>
python tools/crosscheck/ocss_calcbook.py summary --out out/<案名> --name <案名>

# X6：地震／風／靜活載模組 → building_frame 建議值（不動專案、不覆寫使用者輸入）
python tools/crosscheck/ocss_load_suggest.py suggest --file _temp/loads.json
python tools/crosscheck/ocss_load_suggest.py merge --file _temp/case_payload.json --out _temp/merged.json
```

**X5 逐式計算書**：`checks/*.json` 的每個案例做成一張工作表，輸入值直接內嵌在那一行（literal 改寫數值、prompt 整段換掉 `?{預設}`、choice 在 `@select` 區塊之後補一行賦值），技師在 App 裡看得到每一行怎麼算出來。產出 `out/<案名>/<案名>_逐式計算書.ifccalculation`（可開啟、可列印）與 `out/<案名>/<案名>_交叉驗算結果.json`（schema `civil-ocss-calcbook/1`，逐項帶本專案值／OCSS 值／單位／相對差異／處置）。

**不動使用者專案**：專案有未儲存變更且沒有檔案路徑時，工具**直接中止**並提示先在 App 裡存檔（開新專案會遺失內容）。有檔案路徑者先存檔再開新專案。失敗時自動清掉自己加的工作表，不留半套東西擋住下次執行。

**接進報告**：`make_report.py --crosscheck <json>` → 報告附錄 D「計算交叉驗算紀錄」（8 欄比對表：對照案例／比對項目／本專案／OCSS／單位／相對差異／結果／處置，另附產製資訊表）。`case_package.py` 有 `crosscheck` 軸（`--with-crosscheck`），報告軸會自動帶上該 JSON。

**X6 上游載重模組**：`tw-seismic-load`／`tw-wind-load`／`tw-dead-live-loads` 以無狀態 `evaluate` 跑，回傳 11 項 `building_frame` 建議值，每項標註來源模板與公式意義。`merge_loads()` 只補**未填**欄位，永不覆寫使用者輸入。**地震只帶入絕對值 `base_shear_kn`**——OCSS 的 V/W 係數分母是它自己的 W 口徑，與 `building_frame` 自算總重量不同，帶入係數會算錯（係數只列為參考值）。單位換算：1 kgf/m² = 9.80665/1000 kN/m²、1 tf = 9.80665 kN。

### 6.1c 模板對照表（X0）

```bash
python tools/crosscheck/ocss_map_gen.py --list   # 只列統計
python tools/crosscheck/ocss_map_gen.py          # 產生缺少的對照表
```

17 個 `tw-*` 模板各有 `tools/crosscheck/maps/<模板Id>.json`。OCSS 側取自盤點原始資料（`maps/_inventory/`），本專案側取自既有對照案例實際用到的欄位；**輸出對應**（`compare` 欄）只收實際驗過的項，**未核實的輸入欄位**一律列在 `unmapped` 並附「候選」欄位名供人工核實——不臆測對應。已存在的人工對照表不被覆寫。

### 6.2 Token 與埠（機密）

依序取用，**一律不寫死**：

1. 環境變數 `OCSS_API_TOKEN`、`OCSS_PORT`
2. **TW 版** `preferences.json` 的 `mcpToken`、`mcpPoort`（路徑由 `project_paths.ocss_settings_dir()` 跨平台解析，指向 `tw.opencalcsheet.studio`；可用 `OCSS_SETTINGS_DIR` 覆寫）
3. 埠預設 3879

**上游版與 TW 版的 token 不同、預設埠相同**：兩版同時開啟時由先開者佔用 3879。`probe` 回 401「token 不正確」通常代表連到了上游版——關掉上游版，或把 TW 版改用其他埠並設 `OCSS_PORT`。

Token 只在使用時讀入記憶體，不寫入檔案、不印出、不進版控。`.mcp.json` 已列在 `.gitignore`，MCP 註冊所需的 token 只存在該本機檔。

### 6.3 MCP 註冊

專案內優先用 §6.0 的 `ocss_crosscheck.py register-mcp --apply`（寫進本機 `.mcp.json`，不進版控；token 由 preferences 讀入、不印出）。**改了埠或換 token 後要重跑一次。**

要註冊到使用者層級（所有專案共用）則手動：

```bash
claude mcp add --transport http --scope user open-calcsheet-studio \
  http://127.0.0.1:3879/mcp --header "Authorization: Bearer <token>"
```

`--header` 要放最後；`<token>` 請自行取自 `preferences.json` 的 `mcpToken`，不要貼進任何文件或對話。

### 6.4 執行檔路徑

`project_paths.opencalcsheet_exe()`（**只認 TW 版，不退回上游**）：環境變數 `OCSS_EXE` → Windows 安裝根目錄下「去空格／點／連字號、不分大小寫」後**完全等於** `opencalcsheetstudiotw` 的資料夾 → macOS 同名 `.app` → Linux 同名 `.desktop` 的 Exec、`~/.local/bin/open-calcsheet-studio-tw`、PATH 的 `open-calcsheet-studio-tw`。兩版執行檔都叫 `open-calcsheet-studio`，因此**不能**再用執行檔名或 `startswith` 比對。**不要在程式或文件寫死安裝路徑**（與 OpenCADStudio 同一原則，見 EXP-B15）。

**Linux（aarch64，2026-11-10 以 TW 版 v2026.45.2-tw.4 實測）**：官方只給 `.deb`，正式安裝用 `sudo apt install <deb>`（套件 `open-calc-sheet-studio-tw`，執行檔 `/usr/bin/open-calcsheet-studio`，選單 `/usr/share/applications/Open CalcSheet Studio TW.desktop`，解析器靠這個 desktop 檔認出 TW 版）。裝好後再跑一次 `--install`，會寫防黑屏啟動腳本 `~/.local/bin/open-calcsheet-studio-tw`，並在 `~/.local/share/applications/` 放同名 desktop 檔蓋過系統那份（Exec 指向啟動腳本）。無 root 時的備案： `dpkg-deb -x <deb> <目錄>` 解壓，把 `usr/bin/open-calcsheet-studio` 連結成 **`~/.local/bin/open-calcsheet-studio-tw`**（與上游區隔，解析器認這個名字）；解壓不會建選單項目，需自寫 `~/.local/share/applications/Open CalcSheet Studio TW.desktop`。TW 版設定檔在 `~/.local/share/tw.opencalcsheet.studio/`（上游為 `studio.openstructuralcalculation.app`）。視窗全黑時以 `WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1` 啟動（見 EXP-J4）。

## 7. 已知限制與風險

1. **必須開 GUI**：不是常駐服務、不能 headless。任何「自動跑」的流程都要先確認程式在跑。
2. **API 無 PDF**：`export_pdf` 回 501。要含圖的完整計算書，只能在 App 內人工按「Rapport」。
3. **會弄髒專案狀態**：任何 `sheet_add`／`sheet_remove` 都讓專案變「未儲存」，即使刪回原狀也不會復原旗標。批次操作建議用 `calc_evaluate`（無狀態），或在獨立專案裡做。
4. **正確性責任在寫的人**：模板有 91 支檢查腳本把關，自由書寫沒有。開放環境的結果**必須**回到 `design_run` 或手算核對才可進交付。
5. **規範等級差異**：台灣版部分模組仍依賴 B 級（官方來源但未進已驗證庫）條文，例如 `swc_tech` §12、78、86、87、93、118–120。交叉驗算出現差異時，先查是不是這一邊的資料等級問題。
6. **單一請求循序**：橋接器一次處理一個請求，逾時 120 秒。批次驗算要循序，不要並發。

## 8. 後續（尚未實作）

* `case.json` → 模板輸入的自動灌值：`cases/<案名>/case.json` 的水理參數並不完整（例如 `排水溝U型` 只有幾何與數量，沒有 Q、n、S），逐模組對照表需要人工定義，不可猜測。X0 的對照表（§6.1c）已把每個模板的欄位對應列出，可作為人工定義的基礎。
* 待技師決定的差異（會動回歸基準，屬設計變更）：懸臂牆 M_over（差 1.2%）、`rc_column` 互制曲線未套 0.80P0 軸壓上限、`foundation_isolated` 壓力未含基腳自重與覆土。
