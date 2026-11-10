# 設計計算器上架 SOP

> 版本：1.1（2026-11-02，納入工作台與規範查詢台三階段優化、深連結與 Cloudflare 雙入口發佈）
>
> 適用：任何要把「新的設計計算」放進工作區的人與智能體。成品一律要能在四個入口
> （本機 `/design` 網頁工作台、Cloudflare 線上雙入口、`design_cli.py`、MCP `design_run`）跑出同一個結果，並可由「規範查詢台」直接點卡跳轉。
>
> 實例：`steel_column`（鋼構柱＋柱腳基板＋基礎螺栓）即依本 SOP 上架，逐關對照見附錄 A。

---

## 0. 完成定義（Definition of Done）

八道關卡全過才算「上架」，缺一關就只能說「引擎寫好了」：

| 關卡 | 內容 | 檢核方式 | 未過的後果 |
|---|---|---|---|
| G0 | 目錄與 `RUNNERS` 一致；`topics.json` 全部主題皆掛入 `TOPIC_GROUPS` | `design_launch_check.py` | 計算器漏接或主題落入未分類 |
| G1 | 引擎檔案存在且可編譯 | 同上 | 什麼都跑不動 |
| G2 | `CATALOG` 中介資料齊全 | 同上 | 工作台卡片空白、AI 找不到 |
| G3 | 範例可執行且 `ok=True` | 同上 | 使用者一按就報錯 |
| G4 | `summary`／`checks` 形狀可用 | 同上（不足為 WARN） | 結果頁看不懂 |
| G5 | 已驗證條文連結解得開且 `verified` | 同上 | 計算書無法回溯依據、KaTeX 公式卡空白 |
| G6 | 字串欄位一律下拉選單或有白名單 | 同上 | 使用者手打錯字，靜默算錯 |
| G7 | `topics.json` 主題卡列了這支引擎，**且 `regs_web.html` 的 `TOOL_TO_CALCS` 掛載深連結** | 同上 | 口語查詢查不到、設計依據卡無「🧮 對應工程設計計算器」跳轉按鈕 |
| G8 | 工作台中文標籤、**SVG 幾何示意圖與情境範本**、文件、`--selftest` | 同上（WARN） | 可用但初學者看不懂幾何定義與典型值 |

一鍵檢核：

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = 'python'

& $PY -E -P -X utf8 tools\selftest\design_launch_check.py <calculator_id>
& $PY -E -P -X utf8 tools\selftest\design_launch_check.py --all      # 全套 22 支
& $PY -E -P -X utf8 tools\selftest\design_launch_check.py --all --json
```

退出碼 `0` 才算上架完成；`1` 有 FAIL；`2` 計算器 id 打錯。

---

## 1. 階段一：用戶提需求（先問清楚，不要急著寫）

使用者通常只講一句話（例：「幫我做鋼構柱跟基礎螺栓」）。動工前先把下面這張表填滿，
**填不出來的格子就是待問清單**：

| 欄位 | 為什麼一定要有 | 沒有的下場 |
|---|---|---|
| 工項與構造型式 | 決定公式族 | 用錯模型（例：把埋入式柱腳當露出式算） |
| 適用法規與**版本** | 條號、係數、安全係數都不同 | 引用失效條文，計算書被退 |
| 設計法（ASD／LRFD） | 兩版公式與折減係數不同 | 混用，結果無意義 |
| 單位制 | 規範用 tf/cm²、介面用 kN/m | 差 10 倍以上 |
| 幾何輸入範圍 | 決定適用上限與防呆 | 超限照算，得出假通過 |
| 載重與組合 | 需求側的來源 | 用服務載重比設計強度 |
| 輸出要什麼 | 檢核表？配筋？數量？ | 做完才發現不能用 |
| 驗收標準 | 誰說「可以了」 | 無限來回 |

同時要問清楚**不做什麼**（限制清單）。限制不是免責聲明，是避免使用者誤用。

---

## 2. 階段二：不確定就先問（本 SOP 的硬規則）

**寧可停下來問一句，也不要在假設上蓋三層樓。**

### 2.1 決策邊界

| 情況 | 處理方式 |
|---|---|
| 規範條文明寫、且已有已驗證條目 | 直接做，不必問 |
| 規範沒寫、業界有慣用做法（例：基板懸臂法、錨栓群法） | **必須問**：要不要採用？並在輸出標「非規範明文」 |
| 同一問題有兩個以上合理模型 | **必須問**：選哪個（附一句話差異與影響方向） |
| 版本／年份可能不同（規範改版、單價年度） | **必須問**：用哪一版 |
| 使用者的說法有兩種解讀（例：「柱腳」＝露出式或埋入式） | **必須問**：先確認為哪一種 |
| 只是排版、命名、預設值微調 | 自行決定，回報時說明 |
| 會改變「通過／不通過」的假設（土層參數、K 值、μ） | **必須問**：或明確標示為待確認假設並在輸出頂端警示 |

### 2.2 必問清單（六類）

1. **設計法**：ASD（(一) 版）或 LRFD（(二) 版）？全案擇一。
2. **適用上限**：高度／跨度／孔數上限是多少？超過要不要直接拒算？
3. **模型選擇**：規範未明文的簡化法可否採用？（要說出替代方案與保守方向）
4. **單位與座標**：長度 m 或 mm？力 kN 或 tf？角度度或弧度？
5. **輸入範圍與預設值**：沒填的欄位要用什麼預設？預設值是保守還是不保守？
6. **驗收標準**：要看到什麼才算完成（檢核表／斷面圖／數量／報告）？

### 2.3 問法範例（一次問完，不要逐題騷擾）

> 這個柱腳計算有三件事會改變結果，想先跟你確認：
> ①設計法用 LRFD（(二) 版）還是 ASD（(一) 版）？
> ②基板厚度我國規範沒有公式，業界慣用 AISC DG1 懸臂法，可以採用嗎（會在輸出標示非規範明文）？
> ③錨栓拉力要用「彈性錨栓群法」還是「剛性基板＋混凝土壓力三角」？前者對稱、後者考慮揚起，結果可能差 2 倍。

若使用者不在線、或題目屬一次性試算，**可以先用預設值做完並在輸出與回報中標明**，
但不得把「未確認的假設」寫成「已確認」。

---

## 3. 階段三：引擎實作（`tools\design\<id>.py`）

### 3.1 模組契約（五個一定要有的東西）

```python
class XxxError(ValueError):
    """輸入不合法時丟出，design_api 會轉成結構化錯誤。"""

def analyse(payload: Mapping[str, Any]) -> dict[str, Any]:
    """回傳 {schema, <專業結果...>, checks, warnings, references, pass}"""

def format_report(result: Mapping[str, Any]) -> str:
    """人可讀摘要；design_api 會自動呼叫（模組需具名 format_report）。"""

def example_payload(method: str = "lrfd") -> dict[str, Any]:
    """給 CATALOG 與工作台「回到範例」用；必須是完整可跑的 JSON。"""

def selftest() -> dict[str, Any]:
    """封閉解／手算對照；CLI 以 --selftest 呼叫，回傳通過數與明細。"""
```

外加 `main()`：`--payload_json <file>`、`--selftest`、`--json`。

### 3.2 計算紀律

- **不得用心算或聊天文字取代計算**：所有數值走引擎，回報只引用引擎輸出。
- **單位只在一處換算**：模組頂端定義換算常數（例 `TF_PER_MPA`），內文不再各自換。
- **每個檢核列都要有** `item／value／limit／unit／ok`；純資訊列標 `severity: "advisory"`。
- **`pass` 只算非 advisory 的檢核**；advisory 不通過不得讓整體變失敗。
- **超限要拒算**（丟 `XxxError`），不要算出一個看起來通過的數字。
- **限制寫在 docstring 與 `CATALOG.limitations` 兩處**，兩邊一致。

### 3.3 手算對照（`selftest()` 最小要求）

至少涵蓋：斷面／幾何性質、每個主要公式一題、邊界條件一題、端到端一題、錯誤輸入一題。
手算值要**在程式裡用獨立算式再算一次**（不是把引擎輸出抄成期望值）。

---

## 4. 階段四：串接 `design_api` 與工作台

### 4.1 `tools\design\design_api.py`

1. `CATALOG` 加一筆：`id／group／title／oral／description／engine／codes／limitations／field_rules／example`。
   - `oral` 放使用者真的會講的話（例：「柱腳」「錨栓」「基板」），口語查詢靠它。
   - `example` 用 `example_payload()` 回傳，不要手抄一份（避免兩份漂移）。
2. `_run_xxx(payload)` 轉呼叫引擎，**不在 API 層重算任何公式**。
3. `RUNNERS["<id>"] = _run_xxx`。
4. `field_rules`：**只要引擎只接受固定值，就必須是 `type: "select"`**。
   巢狀欄位用完整路徑（`column.fy_mpa`），陣列用 `path[]`（`links[].type`）。
5. 欄位標籤放 `field_rules[path].label`，不要靠前端硬編。

### 4.2 `tools\design\workbench_web.html`（含三階段初學者友善介面契約）

- `LABELS` 補中文標籤（鍵後面接 `:`，例 `design_method:"設計法"`）。
- `NUMERIC_HINT` 補新數字鍵，讓新增列／空值仍當數字處理。
- **幾何示意圖（`CALC_SCHEMAS[<id>]`）**：必畫動態 SVG 構造示意圖（標註關鍵尺寸代號如 `H, B, t`），讓輸入變動時即時刷新數值標籤。
- **欄位工程小幫手（`FIELD_HELP`）**：為關鍵工程參數補上 `tip`（物理意義與法規依據）與 `range`（典型常用範圍，例 `常見：210~280 kgf/cm²`）。
- **情境範本（`SCENARIO_PRESETS[<id>]`）**：提供 2~3 組實務常見情境按鈕（如「一般山坡地農路 H=3m」「重載道路 H=5m」），方便初學者一鍵載入典型參數。
- **選型精靈（`WIZARD_TREE`）與不通過診斷（`DIAGNOSIS_RULES`）**：把新計算器掛入頂部「🧭 不確定選哪個工具？」決策樹，並針對該計算器常見的檢核失敗項補充具體改善建議（如「加大底板踵部寬度」、「提高混凝土強度」）。
- **（選配）自動反推最小斷面**：若引擎提供 `size_section()`／`size_channel()`，一併接入 `design_api.size_calculation()` 與 `SIZERS`，工作台會自動顯示「🪄 自動反推最小安全斷面」按鈕。
- 純量物件陣列（例 `anchors.positions`）會自動長成清單編輯器，不必改前端程式；布林值自動變勾選框，不要為它寫 select。

### 4.3 驗收這一步的判準

```powershell
& $PY -E -P -X utf8 tools\design\design_cli.py show <id>
& $PY -E -P -X utf8 tools\selftest\design_workbench_selftest.py
```

`design_workbench_selftest.py` 內建三條硬規則，新計算器會直接被掃到：
①目錄與 `RUNNERS` 必須完全一致；②每個範例都要 `ok=True`；③example 的字串葉節點
必須是 select 或列在 `FREE_TEXT_FIELDS` 白名單。

---

## 5. 階段五：條文、口語查詢與雙向深連結（最常被漏掉的一關）

### 5.1 已驗證條文連結 `tools\regs\verified\_links.json`

```json
 "steel_column": ["steel99_Fa_asd", "steel99_concrete_bearing_Pp", "..."]
```

- 只列**引擎真的會呼叫**的 id（`refs.formula()`／`refs.table()` 用到的）。
- 條目必須已存在於 `tools\regs\verified\*.json` 且 `status=verified`；
  **不要在 `_links.json` 裡新增公式條目**，公式要另外走《規範公式圖表入庫 SOP》。
- `design_api._enrich_references()` 會自動由已驗證庫補齊 `latex`、`vars`、`columns/rows`，供工作台結果頁渲染 KaTeX 公式卡與展開「讀條文全文」Modal。
- 轉錄值（尚未入庫的表列數字）不得偽裝成 verified，輸出要附「轉錄值」提醒。

### 5.2 主題卡 `tools\regs\topics.json`

沒有主題卡 → `regs_ask "鋼構柱柱腳要多大"` 找不到這支工具（本次上架就是漏這一關）。

```json
{
 "name": "鋼構柱腳",
 "aliases": ["鋼柱", "柱腳", "基板", "基礎螺栓", "錨栓"],
 "scope": "...",
 "core":   [{"src": "steel99", "clause": "10.9", "note": "..."}],
 "prereq": [{"src": "steel99", "clause": "4.8",  "note": "..."}],
 "tools":  ["tools\\design\\steel_column.py"],
 "notes":  ["..."]
}
```

- `src` 與 `clause` 必須能在索引查到，否則 `regq_selftest.py` 直接 FAIL。
- `name` 與 `aliases` 全庫唯一（重複會被 selftest 抓到）。
- **同時在 `tools\regs\exams.json` 的 `route` 加一筆口語測試**（`["問句", "主題名"]`），
  把路由鎖住；否則日後改關鍵字會靜默失聯。
- 加完跑 `tools\regs\regq_selftest.py`，確認索引、別名唯一性與路由測試全過。

### 5.3 規範查詢台深連結與主題分組 `tools\regs\regs_web.html`

為確保使用者在「規範查詢台」查到設計依據卡時，能看到**「🧮 對應工程設計計算器」**互動卡片並一鍵跳轉至 `/design?calc=<id>`（由 `design_launch_check.py` G0／G7 自動把關）：

1. **`TOOL_TO_CALCS` 映射表**：在 `tools\regs\regs_web.html` 的 `TOOL_TO_CALCS` 補上 `"tools\\design\\<engine>.py"` 對應該計算器之 `{ id, title, desc }`：
   ```javascript
   "tools\\design\\steel_column.py": [
     { id: "steel_column", title: "鋼構柱、柱腳基板與基礎螺栓", desc: "H 型鋼柱軸壓彎矩互制、柱腳基板厚度與錨栓拉剪檢核" }
   ]
   ```
2. **`TOPIC_GROUPS` 六大工程領域分組**：若新增了主題卡，將主題名稱加入 `tools\regs\regs_web.html` 的 `TOPIC_GROUPS` 對應領域（水保與坡地／排水與箱涵／擋土與邊坡／基礎與大地／結構與抗震／道路與交通），避免落入未分類。

---

## 6. 階段六：測試（四道既有 + 一道專屬 + 一道上架）

```powershell
& $PY -E -P -X utf8 tools\design\<id>.py --selftest        # 專屬手算對照
& $PY -E -P -X utf8 tools\selftest\design_core_selftest.py  # 共用核心 + 你的測試類
& $PY -E -P -X utf8 tools\selftest\design_workbench_selftest.py
& $PY -E -P -X utf8 tools\regs\regq_selftest.py
& $PY -E -P -X utf8 tools\selftest\regression.py
& $PY -E -P -X utf8 tools\selftest\design_launch_check.py <id>
```

- `design_core_selftest.py` 要加一個 `<Xxx>Tests` 類，放**手算對照**（不是煙霧測試）。
- `design_workbench_selftest.py` 要加「目錄／欄位規則／範例可跑」三類斷言。
- `regression.py` 若有既有案件因此改變，**先確認是不是預期**；要改基準才用 `--update`。
- 全部跑完才准說「完成」；有任何一項沒跑，回報要寫「未驗證」。

---

## 7. 階段七：本機上架驗證與 Cloudflare 雙入口同步發佈（寫檔成功 ≠ 使用者按得動）

### 7.1 本機重啟與驗收（`127.0.0.1:8765`）

**`design_api` 是在請求時才 import，行程啟動後就快取在 `sys.modules`。**
改完 `design_api.py`／`workbench_web.html`／`regs_web.html` 後，只重新整理瀏覽器不會生效。

```powershell
# 1. 確認舊行程是否還在（有回應就是還在）
curl.exe -s http://127.0.0.1:8765/api/design/health

# 2. 重啟（先關掉 8765 的 listener，再起）
& $PY -E -P -X utf8 tools\regs\regs_server.py --web

# 3. 確認目錄真的換了（不是看快取）
curl.exe -s http://127.0.0.1:8765/api/design/catalog

# 4. 實跑一次（persist=false 以免污染紀錄）
curl.exe -s -X POST http://127.0.0.1:8765/api/design/run ^
  -H "Content-Type: application/json" ^
  -d "{\"calculator\":\"<id>\",\"payload\":{...},\"persist\":false}"

# 5. 開瀏覽器看表單：http://127.0.0.1:8765/design?calc=<id>
```

驗收看四件事：①計算器出現在目錄且分組正確；②表單欄位標籤是中文、列舉是下拉、上方有 SVG 示意圖與情境範本；
③按「執行計算」得到「全部通過／未通過」且檢核列與 KaTeX 條文卡可讀；④在「規範查詢台」（`/`）點對應主題卡，底部出現「🧮 對應工程設計計算器」卡片並可點卡跳轉。

### 7.2 Cloudflare Workers 線上雙入口同步發佈

本工作區線上固定網址為 **`https://civil-design-workbench.foil-newsstand.workers.dev/`**（已認領綁定永久帳號 `Foil Newsstand`，Account ID：`e2c04af8447f8efcbf6ca597d6d3ad36`）。
本機修改並驗證通過後，必須重新打包 Pyodide＋靜態規範庫並部署至該固定網址（**嚴禁加 `--temporary`**，否則會產生新的臨時網址或因舊臨時憑證失效而報 9109 錯誤）：

```powershell
# 1. 產出 Cloudflare 雙入口靜態包（輸出至 _temp\cloudflare_design\）
& $PY -E -P -X utf8 tools\design\build_cloudflare.py

# 2. 部署至已認領的 Foil Newsstand 永久帳號（勿加 --temporary）
$env:CLOUDFLARE_ACCOUNT_ID = 'e2c04af8447f8efcbf6ca597d6d3ad36'
Set-Location <專案根目錄>\_temp\cloudflare_design
npx wrangler deploy
```

---

## 8. 階段八：文件與回報

| 要更新的檔案 | 更新什麼 |
|---|---|
| `docs\<工項>計算SOP.md` | 工具現況（已完成／未完成）、模型選擇與限制 |
| `docs\設計工作台.md` | 計算器總數與地圖、欄位規則表（若是新列舉） |
| `docs\設計計算工具索引.md` | 工項一列、口語分派一列 |
| `docs\設計計算核心_擴充藍圖.md` | 能力現況表（有／缺） |
| `AGENTS.md` | 總數與觸發器（若新增了口語入口） |
| `怎麼用.md` | 使用者速查表（若是常用工項） |

回報格式（缺一項就不算完整）：

1. 交付了哪些檔案（只列 `out\` 的交付物；工具與文件列路徑）。
2. 每道測試的**實際輸出**（不是「應該會過」）。
3. 未驗證或已知限制（含非規範明文的模型、轉錄值、適用上限）。
4. 既有但與本次無關的問題（明講「未修」）。

---

## 9. 常見失敗與修法

| 症狀 | 原因 | 修法 |
|---|---|---|
| 目錄顯示 22 支但健康檢查仍是舊的 | server 快取了舊 `design_api` | 重啟 `regs_server.py --web` |
| 表單是文字框不是下拉 | `field_rules` 少了該路徑或打成簡名 | 用完整路徑 `a.b.c`；跑 `design_workbench_selftest` |
| 新計算器一按就 500 | `RUNNERS` 沒接或引擎丟未捕捉例外 | 先跑 `design_cli.py run <id>` 看原始錯誤 |
| `regs_ask` 查不到新工具 | `topics.json` 沒有主題卡 | 補卡 + 跑 `regq_selftest.py` |
| 條文連結顯示未驗證 | 條目不存在或 `status` 不是 verified | 先入庫，再寫進 `_links.json` |
| `regression.py` 顯示基準不符 | 真的改變了設計數值 | 確認預期後才 `--update` |
| 上架檢核 G6 FAIL | example 有新字串欄位沒給 select | 補 `field_rules`，或列入 `FREE_TEXT_FIELDS` |
| 上架檢核 G7 FAIL | `regs_web.html` 的 `TOOL_TO_CALCS` 未掛載該引擎 | 在 `TOOL_TO_CALCS` 補上 `"tools\\design\\<engine>.py": [{ id, title, desc }]` |
| 上架檢核 G4 WARN | 檢核列缺 `unit`／`limit` | 先問「這真的是通過／不通過嗎？」不是就移到 `summary`／`result`；真要在 `checks` 內，至少標 `severity:"advisory"` 且補 `unit` |
| 回歸基準不符 | 真的改變了設計數值（例：鋼筋損耗 12%→6%、模板補上頂版底面） | 先列差異與原因，確認是本次刻意變更才 `regression.py --update`；回報要寫前後值 |
| Excel 公式與程式不一致 | 只看工作表文字標籤，沒看儲存格實際數值 | 用 `xlrd` 逐格 dump 公式列與數值列；**以數值為準**（工作簿曾把 `1.2` 寫成 `1+0.3`） |
| 同一數量有兩套算法 | 引擎與 `qty_models` 各寫一份 | 數量只能有一個定義：改引擎時同步 `qty_models`／`case.json`，並用回歸鎖住 |
| 工具單獨執行就 `ModuleNotFoundError: project_paths` | `tools\<子夾>\` 的檔案把專案根寫成 `parents[2]`（=`tools\`） | 改 `parents[1]`；驗收時**脫離 `case_package` 直接跑** `-h` |
| 回歸全綠但產物是舊的 | 讀 `cases\<案名>\out` 與舊 `交付狀態.json` | 一律 `--out-dir out\<案名>`，`ok` 只看本次退出碼與本次各軸狀態 |
| 回歸永遠 exit 1 | 既有案件資料缺口（如 `boq.items` 空）混在新失敗裡 | 基準已記錄的 `ok=false` 列「既有未通過」；只有新變紅才失敗 |
| 資訊性數字被當成檢核 | 例如「車載重換算均佈」沒有 limit | 不要放 `checks`；由 `summary`、`result` 或報告本文呈現 |
| Cloudflare 線上版沒看到更新或報 `9109` | 誤加 `--temporary` 吃到過期臨時憑證或產生新網址 | 移除 `--temporary`，設定 `$env:CLOUDFLARE_ACCOUNT_ID='e2c04af8447f8efcbf6ca597d6d3ad36'` 跑 `npx wrangler deploy` |

---

## 10. 工項專用 SOP 索引

上架 SOP 只管「怎麼把計算器接進工作台」；工項本身的模型、公式、限制與
驗證，寫在對應的計算 SOP：

| 工項 | SOP | 內容 |
|---|---|---|
| 鋼構柱＋柱腳＋基礎螺栓 | [`鋼構柱與基礎螺栓計算SOP.md`](鋼構柱與基礎螺栓計算SOP.md) | 鋼構規範、基板、錨栓、墩座 |
| 單孔／雙孔／三孔箱涵 | [`箱涵計算SOP.md`](箱涵計算SOP.md) | 車載五型、逐面配筋、每延米鋼筋／模板、Excel 對照 |
| 全體設計計算產線 | [`設計計算產線.md`](設計計算產線.md) | 各引擎公式、對帳、限制 |

> 新增工項時，**兩份都要有**：上架 SOP 的 G0～G8，以及該工項的計算 SOP。
> 只有程式、沒有計算 SOP，下一個人會不知道公式從哪來、哪些情況不能套。

---

## 附錄 A：`steel_column` 逐關對照（2026-11-02 再次檢核）

| 關卡 | 結果 | 證據 |
|---|---|---|
| G1 | ok | `tools\design\steel_column.py`，`steel_column.py --selftest` 11/11 |
| G2 | ok | 群組「鋼結構」、engine `steel_column.py`、codes 鋼構造規範 99.09.16 |
| G3 | ok | 範例 LRFD／ASD 皆 `pass=True`、14 項檢核 |
| G4 | ok | 14 列皆有 item/value/limit/unit/ok；summary 2000 字 |
| G5 | ok | `_links.json` 17 條，全部 `status=verified` |
| G6 | ok | 4 個字串欄位（設計法／支承情況／錨栓材質／剪力路徑）皆為 select |
| G7 | **本次補齊** | 原無主題卡、口語查詢路由為 `None`；已新增「鋼構柱腳」11 條 core＋3 條 prereq，並在 `exams.json` 加 2 筆路由測試（`regq_selftest`：38 exam＋20 routing、0 failure） |
| G8 | ok | 工作台欄位全有中文標籤；4 份文件提及；引擎自帶 `--selftest` |

配套測試：`design_core_selftest.py` 99 tests OK、`design_workbench_selftest.py` 0 failure、
`regq_selftest.py` 0 failure、`regression.py` 基準全部相符、`verified_selftest.py` 478 公式／344 表 0 failure。

---

## 附錄 B：`--all` 目前的既有 WARN（非本次新增，未修）

`design_launch_check.py --all` 的 23 項 WARN 全部是舊計算器的既有狀況：

- 19 支引擎沒有 `--selftest` 入口（手算對照寫在 `design_core_selftest.py`）。
- `building_frame` 沒有 `_links.json` 條目（references 為 0）。
- `hydrology` 無 `checks`（純計算值型，沒有通過／不通過）。
- `sediment_basin`／`slope_stability` 部分檢核列缺 `unit` 或 `limit`。

這些不影響計算正確性，但會讓工作台結果頁較難讀；要補的時候照本 SOP 一併修。
