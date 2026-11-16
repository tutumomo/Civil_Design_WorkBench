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
* 橋接器：`http://127.0.0.1:3879`，MCP 在 `/mcp`、REST 在 `/api/v1`，同一支 Rust 橋接器、同一份工具 registry（60 個工具，2026.46.2）
* 模組 28 個：台灣 23 個（全部 `gereed`）＋上游 5 個（`ligger`、`doorsnede-spanningen`、`balklaag`、`tweepaalspoer`、`rekentaal-demo`）
* 版本查詢：`python tools/crosscheck/ocss_crosscheck.py probe`（**不要把版本號當規格寫進程式或檢核條件**，見 AGENTS.md §3）

台灣 23 個模組：RC 梁／柱／單向板、獨立基腳、聯合基腳、樁帽、樁基礎、鋼梁、鋼柱、懸臂式擋土牆、重力式擋土牆、排水溝、跌水工、箱涵、滯洪池、沉砂池、水面線標準步進、雨水下水道、橋梁耐震、木構造、地震力、風力、靜載重與活載重。（2026.46.2 起新增聯合基腳、樁基礎、跌水工、雨水下水道、橋梁耐震、木構造。）

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

60 個工具，MCP 與 REST 完全等價（`POST /api/v1/tools/{name}` 帶 MCP 參數即可）。註冊方式見第 6 節。**逐一工具的用途、參數與路由見 [`OpenCalcSheetStudio_工具清單.md`](OpenCalcSheetStudio_工具清單.md)**（由 `tools/crosscheck/ocss_tools_doc.py` 從執行中的 OCSS 生成，升版後重跑；`--check` 可比對是否過期）。

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
| macOS | 掛載 dmg → 複製 `.app` 到 `/Applications`（`/Applications` 不可寫時改放 `~/.local/opt`）→ 建 `~/.local/bin/open-calcsheet-studio-tw` symlink。**2026-11-11 已實測（arm64，v2026.45.2-tw.5）**：dmg 內 app 名為「Open CalcSheet Studio TW.app」，解析器直接認得，不需改名 |

* 已安裝（由 `opencalcsheet_exe()` 判定）則略過，**不自動升級**；要升級請手動下載新版（見下）。
* **升級時別被版本號騙**：同一輪 `2026.45.2` 會連發 `-tw.1`…`-tw.5`，`.deb` 的 `Version` 欄與檔名都不帶 `-tw.N`，
  只看 `dpkg -l` 或 `probe` 的版本字串分不出 tw.4 與 tw.5。判斷是否真的換成功要**比對執行檔雜湊或安裝日期**：

  ```bash
  sha256sum /usr/bin/open-calcsheet-studio          # 升級前後比對
  ls -l --time-style=long-iso /usr/bin/open-calcsheet-studio
  ```

  Linux 升級流程（2026-11-11 tw.4 → tw.5、2026-11-13 → 2026.46.1 各實測一次）：
  `gh release download <tag> -R tutumomo/Open-CalcSheet-Studio -p "Open.CalcSheet.Studio.TW_<ver>_arm64.deb" -p SHA256SUMS.txt`
  → `sha256sum` 比對 → `sudo dpkg -i <deb>` → 重啟 App → `ocss_crosscheck.py probe`、`ocss_tools_doc.py`。
  deb 只換 `/usr/bin` 與系統 desktop，`~/.local/bin/open-calcsheet-studio-tw` 包裝腳本與使用者層 desktop 會留著。
* 偵測**不執行**它的 `--version`／`--help`（實測會卡死），完全靠路徑解析。
* 實測（2026-11-10，Windows）：資產挑選、SHA256 校驗、已安裝略過皆驗證通過；靜默安裝步驟本身因本機已裝而未實際執行，換一台乾淨機器第一次跑時請留意安裝程式是否彈 UAC 或安裝到非預期位置。

**安裝後還有兩步，`--install` 不會代做**（需要程式實際跑過才有 token）：

1. 開啟 Open CalcSheet Studio 一次，並在設定中啟用 MCP／API（token 與埠才會寫進 `preferences.json`）。
2. 產生 MCP 條目並驗證連線：

```bash
python tools/crosscheck/ocss_crosscheck.py register-mcp          # 預覽（token 以 **** 隱藏）
python tools/crosscheck/ocss_crosscheck.py register-mcp --apply  # 寫入本機 .mcp.json（先備份 .mcp.json.bak）
python tools/crosscheck/ocss_crosscheck.py probe                 # 確認連線與 23 個 tw-* 模組
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

### 6.1d 工作台即時交叉驗算（X7，2026-11-16）

上面的批次對照跑的是 `checks/*.json` 裡**固定的一組參數**，證明「公式對得上」；這一層跑的是工作台上**當下任何一組參數**，讓技師改完尺寸後立刻看兩套算法是否還是同一個答案。

**入口**：設計工作台的「🔬 OCSS 交叉驗算」面板（結果區，設計圖面板下方），兩顆按鈕：「以 OCSS 再算一次」（背景比對，結果顯示在網頁）與「在 OCSS 開啟計算表」（把同一份逐式計算打開在 OCSS 視窗裡看，見 §6.1e）。屬第二意見，**不阻擋**「產生設計圖」。

```bash
python tools/crosscheck/ocss_live.py --list                 # 各計算器的三態能力
python tools/crosscheck/ocss_live.py channel_hydraulics      # 用計算器範例參數
python tools/crosscheck/ocss_live.py steel_column --payload _temp/p.json --json
python tools/crosscheck/ocss_live.py channel_hydraulics --open   # 在 OCSS 開啟計算表
```

**伺服器端點**（`tools/regs/regs_server.py`）：

| 端點 | 用途 |
|---|---|
| `GET /api/design/crosscheck/capabilities` | 三態能力表，不連 OCSS |
| `GET /api/design/crosscheck/status` | OCSS 是否可用、版本；**不回傳 token** |
| `POST /api/design/crosscheck` | 執行比對；**只接受本機請求**（`client_address` 為 127.x／::1） |
| `POST /api/design/crosscheck/open` | 在 OCSS 開啟該組參數的計算表（§6.1e）；同樣**只接受本機請求** |

**三態能力表**（`ocss_live.capability_map()`）：`supported`（可立即驗算）／`offline_only`（已有固定參數的批次案例，尚未開放任意參數）／`none`（尚無對照）。2026-11-16 只開放三個**全項吻合**的計算器：

| 計算器 | 模板 | 比對範圍 |
|---|---|---|
| `channel_hydraulics` | `tw-drainage-channel` | 滿流通水量與流速、正常水深、設計流速、福祿數、所需出水高 |
| `foundation_isolated` | `tw-isolated-footing` | 基底面積、平均／最大／最小基底壓力、雙向偏心距 |
| `steel_column` | `tw-steel-column` | 基板承壓面積與圍束面積、混凝土承壓設計強度、基板接觸壓力、錨栓最大拉力與拉力設計強度 |

**每個計算器要寫三樣東西**（`SPECS`）：參數對應（值一律取自引擎**實際採用**的結果，含預設值，不另維護一套預設邏輯）、對齊說明（為了讓兩邊比同一件事而歸零／固定的輸入，原樣回給畫面）、逐項適用條件（不可比的項目標 `skipped` 並寫原因，**不比、也不算吻合**）。

**為什麼容差帶絕對值**：本專案引擎回傳的是四捨五入後的數字（例 `Q_cap_m3s` 取 4 位小數）。任意參數下小數值的相對誤差會被捨入放大（0.0500 ↔ 0.04996 相對差 0.08%，但只差半個末位），所以每項的 `abs` 取「該欄位末位的一半」——那是**回報精度**，不是放寬容差；超出末位的差異仍判為差異。

**已查明不可比的情形（不比，且寫明原因）**：

| 情境 | 原因 |
|---|---|
| 設計流量 > 滿流容量 | 模板把水深固定成 `1.05H` 當溢流記號，不是實際正常水深（實測 Q=5、Q_cap=1.2426 → d_n=0.84、fb_req=0.21） |
| 鋼柱雙向彎矩同時存在 | 模板把兩向疊加成角隅壓力（`P/A ± Mx/Sx ± My/Sy`），本專案分向各報一組，不是同一個量 |
| 鋼柱錨栓不是「以柱心為中心的 4 支矩形」 | 模板固定用 `T = Mx/(2·by) + My/(2·bx) − Pu/4`，本專案用彈性錨栓群法逐支求解 |
| 鋼柱 ASD | 模板的容許應力法只檢核純軸壓柱構材，不算柱腳基板與錨栓 |
| 鋼柱受拉（P < 0） | 模板以受壓柱腳為對象；引擎取 `max(P,0)` |
| 錨栓等級不在 A307／F10T | 模板「螺牙桿件」固定 `Fu = 400 MPa`，與該等級實際 Fu 不同 |

**對齊做法**（回給畫面，使用者看得到）：基腳把自重與覆土歸零（`γc = γs = 0`、`Df = 0`）、因數化載重直接填服務載重、配筋沿用模板預設；排水溝把 `use_rational` 設 0 走直接輸入、側坡 `z = 0`；鋼柱彎矩取絕對值、未填墩座時兩邊都取 `A2 = A1`。

**預先防護**：模板的 `ok_*` 旗標在 `#hide` 區塊內、`evaluate` 讀不到，所以適用範圍改在 Python 端先檢查並給**具體原因**（例「基腳厚度 150 mm 小於 OCSS 模板下限 200 mm」），而不是丟一句「模板沒有產生結果」。evaluate 後若探針變數不存在，再以通用訊息回報並列出該模板的適用範圍。

**不回傳 OCSS 的整體 UC／合格判定**：那混了沒對齊的部分（基腳自重歸零、配筋用模板預設），拿來當結論會誤導。回傳的是逐項數值、對齊說明與略過原因。

**自測**：`tools/selftest/ocss_live_selftest.py`（假客戶端，不需桌面程式，已納入 `run_all.py` 的 `ocss-live`）。

### 6.1e 在 OCSS 視窗開啟計算表（2026-11-16）

§6.1d 的比對只把結果貼回網頁，逐式計算表本身看不到。`ocss_live.open_sheet()` 把**同一組參數**的計算表直接開在 OCSS 視窗裡，讓使用者自己往下讀每一行算式。

**入口**：工作台面板的「在 OCSS 開啟計算表」按鈕 → `POST /api/design/crosscheck/open`（`{"calculator": …, "payload": …}`，只接受本機請求）；CLI 為 `ocss_live.py <計算器> --open`。

**做法**：`_prepare()` 重跑本專案引擎取得實際採用的值 → `ocss_calcbook.bake_inputs()` 把值**內嵌進算式同一行**（不留下 `?{預設}` 提示，模板預設值不會被誤當成本案參數）→ 在首行插入說明橫幅（OCSS 的文字行以 `'` 開頭、可含 HTML）→ 開新專案、加工作表、`sheet_evaluate`、`sheet_select`、`project_save_as`。

**輸出**：`out/design_workbench/crosscheck/<計算器>_<YYYYmmdd-HHMMSS>.ifccalculation`（可重開、可交付稽核）。

**不會弄丟使用者的東西**：

| OCSS 目前狀態 | 處理 |
|---|---|
| 專案有未儲存變更、**有**檔案路徑 | 先 `project_save()` 存回原檔（回應 `saved_previous: true`），再換成新專案 |
| 專案有未儲存變更、**沒有**檔案路徑 | 停下來回 `error` 並要求先存檔；**完全不動專案** |
| 中途 `sheet_evaluate` 失敗 | 嘗試 `project_open(原檔路徑)` 把原本那份開回來，並在訊息裡寫明結果 |

**橫幅**：計算表最上面會寫「這是設計工作台產生的交叉驗算用計算表、本專案引擎的值已內嵌在下列算式」，並列出**寫進這張表的輸入值**（例：渠道底寬 B = 0.65 m、渠道淨深 H = 1.05 m、渠底縱坡 S = 0.012…），再註明**模板自身的 UC／合格判定不代表本專案結果**（模板含側壁配筋預設值、自重歸零等對齊處理）。實測模板自身 UC：排水溝 0.98、鋼柱 **1.69**（鋼柱模板把未對齊的項目一起算進去，看數值就好、不要拿它當本專案的使用率）、獨立基腳 0.73。

**參數有沒有真的寫進去：三層交代（2026-11-16 補）**——使用者回報「改了尺寸，開啟的計算表卻不是那組參數」，所以不再只回一句成功：

1. **工作表頂端橫幅**列出寫入值（見上），使用者在 OCSS 裡當場就能對。
2. **工作台面板**列出同一份「項目／模板變數／寫入值」表，並另附可展開的「工作台送出的原始 JSON」（`payload_echo`）——用來分辨「前端沒送到」與「模板沒收」。
3. **讀回驗證**：存檔後用 `GET /sheets/{id}` 取回 App 手上那份文字，逐項以 `變數 = 值` 的行比對（`_verify_inputs()`，數值容差 1e-9 相對）。全部吻合才回 `verified: true`；有任何一項不符就回 `status: error` 並點名「哪一項應為多少、實際是多少／找不到」——**不再可能出現「顯示成功但表上是別組參數」**。實測三個計算器：排水溝 8 項、獨立基腳 21 項、鋼柱 25 項全部讀回吻合。

**開啟後順帶切到 `code-output` 檢視**（`PUT /api/v1/view`）：讓視窗顯示「算式＋結果」而不是上一次留下的視覺化版面，也順帶強制重繪。**這一步必須放在 `project/save-as` 之後**——實測存檔會把檢視模式重設回 `code-visual`，順序顛倒等於沒切。`view_set` 失敗只記在回應的 `view_set: false`，不影響開啟結果。

**會與你的輸入不同、而且是刻意的**（面板「為了能對照而做的處理」與橫幅都有列）：鋼柱的柱斷面換成模板內建 CNS 型鋼表中最接近的規格（例：你的 H400×300 → 模板 RH 300×300）、獨立基腳的自重與覆土歸零並以服務載重當因數化載重、配筋一律沿用模板預設、排水溝的側坡固定 z = 0。這些是「兩邊比同一件事」的必要對齊，不是漏傳。

**實測踩到的兩件事**：

1. `sheet_evaluate` 回的是 `numbers`（實測空 dict）、`uc`、`passes`、`errorLines`、`norm`，**沒有 `lines`**；只有無狀態的 `/evaluate` 才有 `lines`。行數改由寫入的計算文字非空白行計算，**在加橫幅之前**先算。
2. 加橫幅後行數會多一行，自測只檢查 `line_count > 0`，另加「首行是橫幅且含『不代表本專案結果』」的檢查。
3. 浮點數直接 `repr()` 進算式行會出現 `285.52160000000003`，所以鋼柱的 `fc_in`（MPa × 10.1972）取 2 位小數再寫入；驗證比對的是**寫進去的那個值**，不是未取整的原值。

**把視窗拉到前景**：`_raise_window()` 在 Windows 以 ctypes `EnumWindows` 找標題含 `CalcSheet`／`計算書` 的視窗，`ShowWindow(h, 9)` + `SetForegroundWindow(h)`；任何失敗都回 `False`（只是沒跳前景，不影響功能）。

**不做的兩件事**：不改使用者 OCSS 內的模板檔（只讀模板、開新專案）；不把 token 放進回應或專案檔。

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
