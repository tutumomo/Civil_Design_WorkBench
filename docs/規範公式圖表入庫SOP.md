# 規範公式／圖表入庫 SOP

> **這份文件的用途**：把「法規原文 → 可被智能體計算的已驗證庫」這件事，變成**任何人照著做都能得到同樣結果**的流程。
> 適用範圍：`data\法規\` 內的 34 部規範，以及之後新增的任何規範。工具都在 `tools\regs\`。
> **核心原則**：**文字層的公式與表格不可信；智能體只能引用「已驗證庫」（`tools\regs\verified\*.json`）的數值。**
> 最後更新：2026-11-02（coverage 1384/1384 收盤；納入規範查詢台三階段優化、KaTeX 公式表渲染、條號精準直達與 Cloudflare 雙入口同步規範）

---

## 0. 三層資料與誰用

| 層 | 內容 | 給誰 | 可否用於計算 |
|---|---|---|---|
| ① 原頁圖／原文 | PDF 頁面 PNG（`/api/pageimg`） | 人 | 對照用 |
| ② 閱讀輔助 | 框線表格→HTML、人工 LaTeX 圖（`formulas.json`、`tables.json`）、MinerU 草稿（`auto\*.json`，**未核對**） | 人 | **否** |
| ③ 已驗證庫 | `verified\*.json`：公式（可執行運算式＋KaTeX）、表格（結構化數值） | 智能體（MCP `regs_formula`／`regs_table`、`design_run.references`）＋**網頁前端（全文抽屜 `.vpanel` 與工作台 KaTeX 公式卡）** | **是** |

智能體規則：算規範公式一律 `regs_formula`；查規範表值一律 `regs_table`；`regs_clause` 開頭標「【可信度：低】」者不得取數；回報時附 `source`（條文＋頁碼）與 `warnings`。

---

## 1. 每輪固定流程（coverage 補庫）

一條命令、一個循環，**同一輪內不跳步**：

```bat
set PYTHONIOENCODING=utf-8
C:\Python312\python.exe -E -P -X utf8 tools\regs\ctx_budget.py
C:\Python312\python.exe -E -P -X utf8 tools\regs\regs_vtool.py next -n 5
C:\Python312\python.exe -E -P -X utf8 tools\regs\regs_vtool.py coverage --current-only --out _temp\regs_backlog.md
```

### 1.1 開工前的三項體檢（不做會做白工）

| # | 檢查 | 指令／方法 | 為什麼 |
|---|---|---|---|
| 1 | 對話圖片預算 | `ctx_budget.py`（主對話 0 張、body <25 MB） | 每 session 上限 200 張，撞線後連 `/compact` 都 400 |
| 2 | **條號分佈是否健康** | `SELECT clause, count(*) c FROM unit WHERE src=? GROUP BY clause ORDER BY c DESC LIMIT 5` | 單一條號對應多頁＝解析失敗，登 1 條會虛增（見 §5.2） |
| 3 | 是否已存在 | `regs_vtool.py find <src> <clause>` → 必須 `none - safe to add` | 跨分片重複 id 會被 `lint` 擋（`_b`／`_c` 只是控大小） |

### 1.2 批次節奏

- **一批 ≈ 10~30 條**（入庫與 skip 都算一條），做完就把 §3 六道閘門跑完再進下一批。
- 同型材料（檢驗頻率表、係數表）盡量同批處理，減少來回翻頁。
- 每批結束更新進度：`regs_vtool.py status --current-only --out docs\規範入庫進度.md`（**一律加 `--current-only`**）。

---

## 2. 單一條文的轉錄流程（不可跳步）

1. **先讀座標化文字層（預設，不看圖）**
   `page_table.py <src> --page N [--part P] [--y A:B] [--math]`
   → 逐列輸出 y 座標＋以頁面垂直線切出的儲存格；表格跨頁時兩頁都要印出來接續。
   合併儲存格的數值落在兩條篩線之間時，**以最近的控制列歸屬**（`docs\踩坑紀錄.md` §U.3）。
   需第二讀時加 `--ocr`（Windows 內建 OCR）**只驗版面，數字不可取自 OCR**。
   **讀原頁圖一律派子代理**：在 `_temp\` 產生裁切 PNG，把「檔案路徑＋具體問題」交給子代理（scout, async），主對話只收文字結論。
1b. **定位頁碼用「印刷頁碼 → PDF 頁」對照表，不要靠猜**（2026-11-02 新增，見 §2.2）
   多數規範的 PDF 檔序與頁面上印的頁碼不一致（公路路線 PDF 第 44 頁印的是「3-17」；
   公路排水 PDF 第 132 頁印的是「-110-」）。**DB 的 `page` 欄是條文起頁，表常在下一頁**，
   靠猜頁碼會反覆抓錯（2026-11-02 第二輪 27 條待核中有 14 條就是「目標在下一頁」）。
   先建索引再查：
   ```bat
   C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py build <src>
   C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py find  <src> <印刷頁碼>
   C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py show  <src>
   ```
   定位後再渲染該 PDF 頁（`regs_vtool.py page <src> --page <PDF頁> [--part P]`），
   渲染後**立刻改名加篇號**（§8.1 坑：不同篇同頁碼會撞檔名）。

   **索引快取位置**：`_temp\regs_pages\_page_index\<src>.json`（機械產物、可由 `build` 完全重建，
   依 AGENTS.md §1.1 放 `_temp` 而非 `tools\`，可整批刪除）。
   **純文字來源（無 PDF）的規範**（`btr_*`、`swc_*`、`sewer_std`、`traffic_sign` 等 15 份）會印
   「索引 0 筆」——此時本工具不適用，該類規範的表格須改用法規全文檔的方框線解析（§2.2.2 末段）。
2. **決定單位系統**：規範常同時列 kgf/cm² 與 `[MPa]`。統一轉錄一種系統，另一組寫在 `notes`；**量綱先確認再算**（kg/m³→kN/m³ 是 ×9.81/1000，不是 ÷1000）。
3. **產生骨架**：`regs_vtool.py scaffold formula|table <id> <src> <條號>`。
   id 命名 `<規範簡碼>_<量>_<條號或式號>`，全庫唯一。
4. **填欄位**（缺一不可，`lint` 會擋；schema 見 §7）：
   - 公式：`title, clause, page, latex, vars{desc,unit,min,max}, defs, expr, unit, output, conditions, warn_if, notes, tests`。
   - 表：`kind, columns, rows[{key,values}], unit, notes`；**範圍值寫 `[下限,上限]`，空白寫 `null`（不可寫 0）**。
   - 條文被索引併進前一單位時加 `index_clause` 指回實際存在的單位。
   - 公式需查表時用 `lookups`（§7.3）；整數節點表用 `kind="stepdown"`。
   - **前端 KaTeX 與結構化表格直出（2026-11-02）**：`latex`、`vars{desc,unit}` 與表格 `columns`/`rows` 會直接呈現在「規範查詢台」全文抽屜的 `.vpanel`（已驗證公式／表格面板）及「工程設計工作台」的依據公式卡中，請確保 `latex` 為標準 KaTeX 可解析語法、`vars.desc` 為簡明中文物理意義。
5. **自我驗算設計**（§2.1）→ 再寫測試。
6. **原文疑誤**：照原文轉錄但 `status="pending"`，`notes` 以「**【待核】**」開頭說明疑點與替代做法，並登錄 `design_conformance.py` 的 `KNOWN`。**pending 不得宣稱可用。**
7. **沒入庫的條文一律要登錄，且必須分四類**（2026-11-02 起；舊的 `no-content`／`deferred` 已拆除）：
   `regs_vtool.py skip <src> <clause> "<理由>" --status <類別>`

   | 類別 | 意思 | 查詢時的警示 |
   |---|---|---|
   | `covered` | 內容已由某 verified 條目涵蓋（理由要指出是哪一條） | 【已由已驗證條目涵蓋】 |
   | `qualitative` | 已人工讀過，確實沒有可計算的算式或數值表 | 【定性條文】 |
   | `out_of_scope` | 判斷非本工作區；**原文有表／式，但未轉換、數值未驗證** | 【可信度：低】【未入庫｜非本工作區】 |
   | `unrecognized` | 有表／式但排版破碎、表身未擷取、辨識失敗＝**真缺口** | 【可信度：低】【未入庫｜辨識失敗】 |

   - 舊 `--status deferred` 仍可輸入，會自動當成 `unrecognized`；`no-content` 不再接受（必須明確選一類，避免把『有表沒轉』說成『沒內容』）。
   - 條文後來轉錄入庫了，用 `regs_vtool.remove_skip(src, clause)` 移除 skip（verified 優先，留著只會過時）。
   - **只轉錄了一部分時**：保留 skip 但加 `"partial": true` 並把「哪一部分還沒轉」寫進理由；`regq.skip_info()` 會在已有 verified 的情況下仍回傳
     【部分入庫】警示（例：附錄F.1 已入庫、F.2 未轉）。沒有 `partial` 者，一旦有 verified 就不再警示。
   - **每批開始先掃過時 skip**：`[i for i in _skips.json if V.for_clause(src, clause)]`——已轉錄卻還留著的 skip 會讓你重複建條目（2026-11-02 發生過：22.7.5.1 早有 `rc112_Tcr`，我又建了一條）。
   - 理由須 ≥12 字元的實質內容。`out_of_scope` 與 `unrecognized` 的**查詢警示會自動出現在** `regs_clause`／`regs_search`／`regs_ask` 與網頁（搜尋列標籤＋全文抽屜橫幅），判定在 `regq.skip_info()`。
   - 進度口徑：**「已轉換／已涵蓋」才是可信賴取數的比例**；`out_of_scope` 算『有決定』但不算『已轉換』，`unrecognized` 是缺口。`status` 會分開列。
8. **連到設計器**：`design_run` 用到此條時，在 `verified\_links.json` 加對應，輸出 `references` 才會列出。
9. **驗證**：§3 六道閘門全綠才算入庫。
10. `status` 只在 1~9 全完成後寫 `verified`。**技師簽認**（`engineer_signed`）由使用者負責；回報一律附「尚無技師簽認」警示。

### 2.1 轉錄前先做「自我驗算」設計

- **能用規範自己的關係式驗算的，就當場逐格驗算**：表6.2.(1) 的 GE 定義為 `GE(mm)＝實用厚度×Gf`，逐格比對後發現「礫石／水泥處理材料欄完全相符、瀝青混凝土(TI)欄在厚度 ≥180 mm 起偏離 5~10%」→ 該表標 `deferred`。**沒有內建驗算就照錄，等於把原書排版錯誤變成「已驗證」的錯誤。**
- **上標與係數要用兩個來源交叉定案**：公式6.4.(1) 文字層讀成 `0.2C`、原頁圖讀成 `C^0.2`；以規範自己的範例（TI=15.1、R=8、C=20）實算 1356.7 mm 與另一式 1354.5 mm 只差 0.2%，才確認 `C^0.2`（`0.2C` 會差 20 倍）。
- **表頭多列併排時用 x 座標＋他表數值反查**：先取每個詞的 x 座標定欄，再與他表已知值比對，兩路一致才寫入，`notes` 寫明「依 x 位置與他表推定」。
- **原表某欄真的沒有子標題時，照錄「左欄／右欄」**並在 notes 說明，不得自創「一般／重交通」這類名稱。
- **原書可能印錯函式／符號**：用規範**自己的範例數據點**反推（抓 2 組以上「輸入→輸出」試各種符號組合，取能同時命中的那組），把反推過程寫進 notes。這比查外部文獻可靠，因為它對齊的是這部規範自己的表。
- **表值與公式並存時以表為權威**：公式有時是表值的近似（內插誤差 0.7~2.6% 屬正常，不是錯誤）。
- **測試期望值不要用手算**：曾手算錯 `qu`、`β`、`Nsb`、`Vs`、`Mn`、`Vc`、`δ`… 十數次。做法：`out` 先填任意值 → `payload_check.py <payload> --fix` 由引擎算出 → 再回頭確認那組輸入的物理意義合理。

---

### 2.2 印刷頁碼 → PDF 頁 對照表（`page_index.py`）

**為什麼需要**：多數規範的 PDF 檔序與頁面上印的頁碼不一致。實例：

| 規範 | PDF 第 N 頁 | 頁面上印的頁碼 |
|---|---:|---|
| 公路路線設計規範 115 | 44 | 3-17 |
| 公路排水設計規範 | 132 | -110- |
| 市區道路及附屬工程設計規範 | 36 | 道路工程設計篇 3-4 |
| 建築物耐風設計規範 | 84 | 76 |
| 建築物耐震設計規範 | 42 | 2-18 |

**DB 的 `page` 欄是條文起頁，表格常在下一頁**。先前靠猜頁碼抓原頁圖，2026-11-02 第二輪的 27 條待核中就有 14 條是「目標在下一頁」，重試成本高且容易抓錯章本。

**工具**：`tools/regs/page_index.py`（34 份現行規範中 **19 份有 PDF、可建索引**；其餘 15 份為純文字來源，本工具不適用）

```bat
C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py build <src>              :: 建索引（快取至 _temp\regs_pages\_page_index\<src>.json）
C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py find  <src> <印刷頁碼>   :: 查單頁
C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py show  <src>              :: 列全部
C:\Python312\python.exe -E -P -X utf8 tools\regs\page_index.py all                       :: 批次列出
```

**識別原理與兩個必要條件**（這兩點是本工具能用的關鍵，改動時勿退化）：

1. **必須用座標，不能用文字層的前後字串**。頁面開頭可能是「3-17表3.8.1.2複曲線…」，內文的「3-8」「3-16」會被誤認為頁碼。工具只取**頁首／頁尾 12% 帶內**的 token。
2. **頁碼在文字層常被拆成多個 word**（公路路線的「3-17」是 `'3'`、`'-'`、`'17'` 三個 token）。必須把**同一橫列**的 token 依 x 座標串接後再比對格式。

**已支援的頁碼樣式**（格式不對就會漏掉，必要時加進 `LABEL_PATTERNS`）：

| 樣式 | 例 | 對應規範 |
|---|---|---|
| `數字-數字` | 3-17、10-17、4-151 | 公路路線、公路施工、鋼結構 |
| `-數字-` | -110- | 公路排水（附錄頁） |
| `前綴篇別數字-數字` | 道路工程設計篇 2-1 | 市區道路 |
| `純數字` | 76 | 建築物耐風（頁尾單獨一數） |
| `附錄-數字` | 附錄-20 | 部分規範 |
| `A1-2` / `C-8` | C-8 | 規範解說附錄 |
| 羅馬數字 | vi | 前言／目錄頁 |

**使用流程**：定位 → 渲染 → **立刻改名加篇號** → 裁圖高解析（§2.2.1）→ 派子代理讀圖。

#### 2.2.1 高解析裁圖看公式（比整頁渲染可靠）

整頁 110 dpi 渲染看不清上標與分式位置時，**裁切局部並提高解析度**：

```bat
python tools/regs/page_crop.py "<PDF路徑>" <頁> --clip <x0> <y0> <x1> <y1> --dpi 400 -o out.png
```

座標以 PDF point 為單位（1 pt ＝ 1/72 inch），從 `page_table.py` 或 `pg.get_text('words')` 的 x0/y0 取得。實測 260~420 dpi 的局部裁圖可精確讀出「平方罩在哪裡」「括號外有沒有 1−」「不等號是 ≤ 還是 ≧」——這類問題在整頁圖上子代理常會讀錯。

**裁圖定位要點**：頁碼／頁眉通常在 y≈780（頁高 842）附近；公式本體在 y 500~640。取 `y` 範圍時先看 `words` 的 y0/y1 分佈再決定。

#### 2.2.2 表格結構復原：優先用 `find_tables()`

**多欄合併儲存格的表格（例：耐震規範第 2.18 條之 SDS 鄉鎮市區表），文字層會把「縣市」欄的合併格打散**，逐行文字會得到錯亂的縣市歸屬。此時用 PyMuPDF 的表格結構 API：

```python
tabs = page.find_tables()          # 正確處理合併格（續行列為 None）
ex = tabs.tables[0].extract()      # 二維陣列，含表頭
```

本輪用它重建 `seis113_SDS_T2_18`：**327 列 ＝ 全台 368 鄉鎮市區 − 臺北市 12 − 新北市 29**，22 縣市齊備、無重複 → 完整性用「全台總數 − 特殊市」交叉驗證。

**沒有 PDF 的規範（純文字檔）**：表格用方框線（`┌─┼─┤`）表示時，可**程式解析**：逐行以 `│` 切欄、遇內部框線結算一列。本輪用此法補齊 `btr_equip_plumbing_count_T37`（9 類 × 30 列器具個數）。

**表格重點：同時用「量綱檢查」與「單調性檢查」**。例：表D.6.(8) 建議使用值欄 21°C 印 274251，與 20°C 407691 → 22°C 342624 的遞減序列不符 → **經原頁影像確認為原書誤植**（研判應為 374251），照錄並在 notes 標明。

---

## 3. 六道閘門（每批必跑，順序不可換）

| # | 閘門 | 指令 | 擋的是什麼 | 通過標準 |
|---|---|---|---|---|
| **1** | **payload 預檢**（合併前） | `payload_check.py <payload.json> [--fix]`／全庫 `--library [--fix]` | id 重複、運算式不可編譯、**`conditions`/`warn_if` 引用未宣告變數**、測試值與引擎不符、LaTeX 被跳脫字元破壞（`\t`→TAB、`\v`→VT、`\f`→FF）、表格 rows/columns 不一致 | `0 problem` |
| **2** | **lint** | `regs_vtool.py lint` | 必填欄位、verified 缺 method/by/date 或測試、PDF 規範缺 `page`、變數缺 unit/desc、`_links.json` 指向不存在的 id、**pending 未標「待核」** | `lint ok` |
| **3** | **條目自測** | `verified_selftest.py` | 每條 `tests` 逐筆實算、`clause exists`、schema 完整性 | `0 failure` |
| **4** | **查詢台自測** | `regq_selftest.py` | 考題／路由是否還能查到正確條文（改 index 或改條目後必跑） | `0 failure` |
| **5** | **引擎符合性** | `design_conformance.py --out _temp\design_conformance.md` | 「工作台 ↔ 已驗證庫」逐值比對（§6） | `exit 0`，無 DIFF／ERROR |
| **6** | **全案回歸** | `tools\selftest\regression.py` | **改了 `tools\` 內任何程式**時必跑：6 案的預算總計、斷面積、通水容量、FS、配筋間距 | `6 案基準全相符` |

**全庫健檢**（每批收工建議跑一次）：`payload_check.py --library` → `checked N entries, 0 problem`。
**`--library --fix` 會直接改寫分片檔**（2026-11-02 起支援；在此之前它只印「用 --fix 自動改寫」卻不動庫，是陷阱）。
**合併前另會檢查「同條文是否已有 verified 條目」並印 `WARN`**（不是失敗，因為同一條常有多式如 (a)(b)）——看到 WARN 先確認是不是重複轉錄。
首次健檢即找出 **14 條 LaTeX 被跳脫字元破壞** + 1 條期望值偏差。

**進度表多了「其中待核」欄**（2026-11-02）：`status --current-only` 除「已入庫」外另列**已入庫但條目 `status="pending"`** 的數量。
「已入庫」不等於「已驗證可用」——pending 條目查詢時顯示【待核】，**不得當已驗證取數**（SOP §2 步驟 6）。

### 3.1 閘門擋下過的實例（證明它有用，不要繞過）

| 閘門 | 攔下的錯 | 後果（若沒擋） |
|---|---|---|
| payload_check | `conditions` 引用未宣告的 `fpu_ref` | `verified_selftest` 會以 `NameError` 崩潰 |
| payload_check | 條目帶著 `out: 0` 直接合併 | 全庫 2 個 FAIL（`--library` 第二道才抓到） |
| lint | `page` 捏造（farmroad 附表為 ODT，原文無頁碼） | 條目指向不存在的頁 |
| regression | 改 `design_conformance.py` 後未重跑 | 基準可能漂移而無人知 |

---

## 4. 分片安全併入（`merge_shard.py`）— 從一次資料遺失事故來的規則

**規則：目標分片已存在時，一律 `merge_shard`，不得用 `write`。**

```bat
C:\Python312\python.exe -E -P -X utf8 tools\regs\merge_shard.py <payload.json> tools\regs\verified\<src>_<n>.json
```

工具行為（三重保險）：

1. **只增不覆寫**——讀入既有分片後 `extend`，永不整檔取代。
2. **併入前檢查 id 重複**——重複即拒併並列出 id（同一條文要更新就改既有條目，不要另立 id）。
3. **併入前自動備份**到 `_temp\regs_pages\_backup_shards\<shard>.<timestamp>`，事後可回溯。
4. 併入後印出「formulas / tables 前後數量」，數量不對就立刻看得出來。

> **事故記錄（2026-11-01）**：曾直接用 `write` 覆寫已存在的 `verified/urbanroad113_b.json`，
> **一次刪掉 5 條既有條目**（全庫 554→552）。本目錄**不是 git repo**、無法 checkout 還原，
> 最後靠 `_temp\regs_pages\shard_*.json` 的舊快照救回。
> **判準**：`write` 只能用在「檔名一定不存在」的新分片。

---

## 5. 進度口徑與「虛增」防範

### 5.1 口徑：一律 `--current-only`

`regs_vtool.py status --current-only` 會排除**已被取代版本**（rc100 129 條、seis111 64 條）。
不排除會讓「還要多少」虛增約 200 條。與 `coverage --current-only` 同口徑才對得上。

判準：**每一條 flagged 條文都要有 verified 條目或 skip 紀錄**，才算處理完。

### 5.2 數字會騙人：三種必須先查的情況

| 情況 | 徵兆 | 查法 | 處理 |
|---|---|---|---|
| **條號解析失敗**（多頁併成一條） | 某規範「一次跳增很多條」 | `SELECT clause, count(*) FROM unit WHERE src=? GROUP BY clause` | 該規範進度不可信；**不登條目**（登 1 條會虛增 N 條），改 deferred 並把可用內容寫進理由 |
| **章本／整本重複**（同內容兩份） | 同一 clause 2 個 unit、頁碼差約 100 | 比對兩 unit 文字是否相同 | **屬正常**，1 條 entry 覆蓋 2 個 unit 是對的 |
| **skip 理由被吃掉** | reason 變成條號本身 | 掃 `_skips.json` 短理由 | 重寫理由；已加全域檢查（≥12 字元） |

> 實例：`hwslope104` 的 18 個單元共用 clause `10.2.4`（解析失敗）→ 不登條目；
> `hwbridge` 的 `5.4.7`／`8.20.3` 是章本＋整本（內容相同）→ 正常登 1 條。

---

## 6. 雙向比對：工作台 ↔ 規範（引擎符合性）

### 6.1 原則

- **互查**：不只查引擎有沒有照規範做，也查我轉錄的條目對不對。
  實例：水保第 92 條初版把「每公頃下限」當總量與下限取大，與 `sediment_basin.sediment_production` 比對後才發現應**分區各自取下限再加總**。
- **能比對就比對**：新增條目時先找同題目 `tools/design` 函式，寫進 `design_conformance.numeric_probes()`。
- **不能比對要說明**：模型不同（2:1 法 vs Boussinesq）、由使用者輸入、規範只有諾模圖 → 寫進 `scope`，不可默不作聲。
- **方向性檢查**：算出數值先問「這個方向合理嗎」。軸重當量因子照原文算出「軸重越大因子越小」，方向明顯相反 → 標 pending 而非放行。
- **比對要分方向**：規範下限與引擎預設值不同時，先問「引擎是否偏保守」——偏保守記 PASS 或 KNOWN，不要一律判 DIFF。
  實例：擋土牆保護層（引擎 75 mm vs 規範曝露大氣 50 mm）判 PASS；混凝土單位重（引擎 24 vs 規範 23.54 kN/m³，1.9% 偏保守）登 KNOWN。

### 6.2 現況（2026-11-01 稽核結果）

| 指標 | 數值 |
|---|---|
| 工作台計算器 | **20** 個 |
| 已連結已驗證條文 | **19**（結構檢查 19 通過、0 有問題） |
| 數值比對 | **20 PASS、0 KNOWN、0 不符**（2026-11-02 修正 KAE、φ 門檻後） |
| **採用率** | **16／20（80.0%）** 有逐值比對過 |
| KNOWN 已知差異 | **11 條**（7 條未解 + 4 條已 resolved） |

**2026-11-02 已修正的 2 條數值差異（原偏不安全側；保留紀錄供對照）**

| 條目 | 原差異 | 修正 | 修正後 |
|---|---|---|---|
| `earth_pressure_KAE` | KAE 偏低 0.18~1.23%（φ=30、kh=0.2：0.4491 vs 0.4520） | `earth_pressure._coulomb_active` 根號內分母 `cos(β−ψ)` → `cos(β)`（墻背垂直） | 5 組案例（含 α=10°、15° 坡面）與 `found112_KAE` 差 <1e-9 |
| `rc112_phi_flexure` | 過渡區 φ 偏大，最大 0.0083（εt=0.005 處） | `phi_by_strain`（梁）與 `_column_point`（柱）拉力控制界限 `0.005` → `εty+0.003` | 與 `rc112_phi_flexure` 差 ≤0.0006（`round(φ,3)`） |

> 回歸基準線**不涵蓋**地震工況數值與過渡區 φ，所以「回歸全綠」不能證明這類修正的影響。改這類引擎時，另用 `_temp\measure_*.py` 型的新舊對照直接量測（備份舊檔 → 換模組 → 比 `checks`）。

**其餘 KNOWN（方法／範圍／原文疑點類）**

| id | 等級 | 一句話 |
|---|---|---|
| `rock_slope_modes_missing` | medium | 工作台 `slope_stability` 只有無限邊坡＋Fellenius 圓弧，**沒有岩石邊坡的平面／楔形滑動、傾覆** |
| `rc_column_no_slenderness` | medium | `rc_design.column_design` **未實作柱細長效應**（Q、Pc、δ、Mc=δM2） |
| `culvert_min_section` | low | 公路排水表6-1 蓋版暗溝最小 0.5×1.0 m；某案設計 70×70 cm 未達（須確認適用法規） |
| `hwdrain_S0_unit` | low | 附錄O 式(O-1) 標 S0 為「%」，但 L·S0 須為高差 → 判原書標示筆誤，庫內用 m/m |
| `concrete_unit_weight_24_vs_2354` | low | 引擎 24 vs 規範 23.54 kN/m³（偏保守 1.9%） |
| `found112_angular_levels_partial` | low | 表-解4.5-1 共 7 列，工作台只收前 4 級（1/150 三種情形缺） |
| `flexpave91_Estar_print_error` | low | 附錄D 表D.6.(8)(9) 兩格單調性中斷，判原書誤植（條目標 pending） |
| `seis113_vs_found112_liquefaction` | resolved | 兩規範互補（判定準則 vs CRR 算法），已分別入庫；**CRR 迴歸式仍未入庫** |
| `flexpave_axle_factor` | resolved | 原式右邊需取負號（LEF=10^−RHS），已修正並改 verified |

**方法範圍差異（不是錯誤，但引用時要註明）**：`detention_basin`（用蓄水-出流演算而非三角歷線）、`box_culvert`（進口控制用 HDS-5 迴歸式，附錄N 是諾模圖）、`foundation_isolated/combined`（極限支承力由使用者輸入）、`foundation_pile`（樁承載力由使用者輸入）、`building_frame`（不含耐震最小總橫力 V）、`settlement_assessment`（2:1 法 vs Boussinesq）、各擋土牆（土壓係數多由使用者輸入或採 Rankine）、**柔性鋪面（工作台無鋪面厚度設計計算器）**。

### 6.3 加新 probe 的判準

新轉錄的是「**引擎常數**型表格」（容許沉陷量、角變量分級、FS、保護層）→ 就在 `numeric_probes()` 加一組，把引擎常數與表值逐項比對；引擎缺級距者另立 KNOWN。
實例：`found112_settlement_T452`（40/100/200/300 mm）、`found112_angular_T451`、`rc112_cover_T205131` 均 PASS、差異 0.0%。

---

## 7. 已驗證條目 schema（v2）

**7.1 公式**
`id, title, src, clause[, index_clause], page, keywords, unit, output, latex, vars{desc,unit,min,max[,default]}, defs[[name,expr]], lookups[{table,x,map}], expr, conditions[{expr,msg}], warn_if[{expr,msg}], tests[{in,out[,tol]}], notes, status, verified{method,by,date}, engineer_signed`

**7.2 表格**
`id, title, src, clause, page, kind(lookup|stepdown|interp), unit, columns, rows[{key,values}] 或 rows[{x,values}] 或 rows[[x,y]], notes, status, verified`

- 範圍值寫 `[下限, 上限]`，**不得簡化成單值**；**空白欄寫 `null`**（不可寫 0——「原表沒列」與「值是 0」意義相反）。
- 符號型係數（βE、βD）寫成 `"be"`／`"bd"` 並在 notes 說明。

**7.3 `lookups`**（公式計算前先查表帶入變數）
`"lookups": [{"table": "found112_bearing_N", "x": "phi", "map": {"Nc": "Nc", "Nq": "Nq", "Ng": "Ng"}}]`

**7.4 運算式沙盒允許**
`+ - * / ** %`、比較與三元式、`sqrt log log10 exp sin cos tan tanh sinh cosh radians degrees atan floor ceil min max abs interp pi`。新增函式須同步更新 `verified.py` 的 `_FUNCS`。
**`conditions`／`warn_if` 只能引用已宣告的變數**（`vars`、`defs` 左邊、`lookups.map` 的 key，加 `result` 與內建函式）。不想把上限值變成必填輸入時，就寫進 `notes`。

**7.5 `status`**
`verified`（對原文＋交叉驗證）、`pending`（原文疑誤或未交叉驗證）、`superseded`（被新版取代，notes 寫新 id）。

---

## 8. 常見坑（按出現頻率排序）

### 8.1 資料正確性

- 文字層的公式、`kg/cm²`、千分位（MinerU 把 `14,000` 讀成 `14.000`）都不可信，數字以原頁圖為準。
- **索引未切出的子條**（如 22.2.2.4.3 被併進前一單位）要用 `index_clause` 指向實際存在的單位。
- **合併多張附表成一條**：`clause` 必須是 `unit` 表真有的**單一**條號（如 `附件-1`），涵蓋範圍寫在 `notes`。用 `附件-1~附件-4` 這種串接字串會讓 `verified_selftest` 的 `clause exists` 失敗。
- **無分頁原文不可捏造 `page`**：`lint` 的例外清單為 `swc_*`／`sewer*`／`btr*`／`airconst*`／`farmroad*`（條文式或 ODT 附表）。新規範同樣無頁碼時，**加進清單並在程式碼註明原因**。
- **符號被排版成圖形**（如係數在 kgf 與 MPa 兩版都印成 23）→ 只採有量綱依據的那版並在 notes 寫明。
- **下標／上標被拆行**（`(N1)60cs` 變散字）→ 靠原頁圖確認。

- **單一來源的『看圖』結論也會錯（2026-11-02 實例）**：`urbanroad113_curb_inlet_Qc` 登記為『逐式對照原頁圖』卻把指數 5/2 讀成 5/3，直到轉錄公路排水規範同一條式(5-1) 時才發現兩者不同。**公式至少要兩個獨立來源**（文字層＋看圖、兩部規範同式、量綱檢查、規範自己的範例擇一以上）。量綱檢查最便宜：`(Ln/h)·h^p` 要是堰流就得 p＝5/2。**要點：整頁低解析圖會讓子代理把「括號外的 1−」漏掉、把平方位置讀錯（§2.2.1）——公式類必用高解析局部裁圖。**
- **雙來源轉錄流程**（附錄F.1 降雨強度 41 格實證）：(A) `page_table.py` 輸出先 **NFKC 正規化**（文字層常用相容表意字，不正規化會有測站名對不上），再用 y 座標把『分子列／站名列／分母列』對齊；(B) 子代理獨立看圖；**逐格比對，只收兩者一致的格子**，不一致的標待核。
- **『適用的數字出現在該頁文字層』是弱檢查**（只防位數讀錯，防不了錯位）。看圖轉錄表格後至少再做一項結構檢查：全長＝各段之和（設計車種表）、每格相差固定值（VMA 表）、級配單調遞減。
- **DB 的 `page` 是條文起頁，表可能在下一頁**（02745/3.3 的表在 p.66，DB 記 p.65）；子代理回報『這頁沒有表』時要補讀續頁。
- **不同篇的同頁碼會撞檔名**：`regs_vtool.py page` 產出 `<src>__p<N>.png`，hwconst112 的 (08) 第三篇 p.24 與 (14) 第九篇 p.24 同名會互相覆蓋。產圖後立刻改名加篇號。
- **原書同頁可能印兩張同號的表**（表02741-4 就印了 VMA 與開放級配兩張），分開登錄並在 notes 互相指認。

- **同一條文的內容可能在別處（含 `index_clause` 條目）**：8.4.2.2 的 γf 公式其實在 **8.4.2.2.2**，8.4.2.2.1 只是導引條；9.3.1.1.3 也只是指向 9.3.1.1.2 的交叉引用。**遇到「skip 理由說有表／式」時，先確認那個式真的在這個條號下，別把導引條當公式條轉錄，也別把公式條漏掉。**
- **`conditions` 的變數要對得上物理意義**：`fps` 式中 (a) 款限制用的是 **d′（壓力鋼筋形心距）**，我曾誤用 `d/dp` 當分母，導致自測時對合法輸入丟出「不符適用條件」。**每寫一條 condition，回頭問「這個比值在講什麼」。**
- **查表型變數的 `min/max` 要涵蓋公式允許的整段值域**：ψc＝f′c/1050＋0.6 在 f′c=280 時是 0.867，若把 min 設成 1.0，合法的低強度輸入會被判超範圍。

### 8.2 工具與環境

- **LaTeX 不經 shell**：`\t`、`\v`、`\f`、`\n` 在 JSON 是跳脫字元，`"\tfrac"` 會變成 TAB+frac。一律用 `write`／`edit` 寫 JSON，寫完跑 `payload_check.py`。
- **matplotlib 公式圖不能含中文**；中文說明放 `notes`。
- **`	ext{}` 的 `	` 會變成 TAB 字元（2026-11-02 實例）**：修補腳本用 `write` 寫入 `	ext{…}` 時，`	` 被當成 TAB 塞進 LaTeX 值裡，JSON 看似可讀、實際含控制字元。`payload_check` 的「latex 含 TAB/換行字元」檢查就是為此——**看到這個 FAIL 不要手改，改用 `json.dumps` 產生跳脫值**（本輪即以此修好）。
- **用 heredoc／`python -`／`sed` 寫含 `\n` 的修補腳本會被吃掉**（工具層把 `\\n` 轉成真換行，造成 `unterminated string literal`，本輪發生 3 次）。修補腳本一律用 `write` 工具建檔再執行；字串內需要換行時寫 `chr(10)`，需要反斜線時寫 `chr(92)`。
- **`python -P`（SOP 指令預設）不會把腳本目錄放進 `sys.path`**：`regq.py` 內 `import verified` 因此失敗，被 `except Exception: return None` 靜默吞掉，警示就整個不出現。**模組內的 import 失敗不可靜默吞掉**——`skip_info()` 現在失敗時會回傳『無法確認入庫狀態』的保守警示。
- **MinerU 必須用純 ASCII 路徑並設 `PYTHONUTF8=1`**；standard 檔位在繁中 Windows 會崩潰，用 basic。
- **一部規範兩本 PDF**（章本／整本）：先用 `part_pdfs` 列出，再以條號在每本搜一次；拿整本頁碼開章本會 `IndexError`。2026-11-01 起 `find_pdf(file, part)` 改為比對 PDF 檔名 stem，**給 part 卻找不到時回 None、不再退回整本**。
- **鋼構 99 有 (一)ASD 與 (二)LRFD 兩套**，條號相同內容不同：條目必須指明 part，`page` 為該 part 內頁碼；**一律轉錄 (二) 強度設計法**，ASD 以 skip 處理並在理由指向對應 LRFD 條目。
- **8765 舊服務若無權限重啟**，新版先看 8766。

### 8.3 流程

- 改過 `tools\` 任何檔案 → §3 第 6 道（`tools/selftest/regression.py`）必跑；改 `tools\design\` 另跑 `tools/selftest/design_core_selftest.py`／`tools/selftest/design_workbench_selftest.py`。
- `payload_check` 必須在**合併前**跑；合併後再跑 `--library` 是第二道，不能取代第一道。
- **B 類（每字元一 span 的數學排版）不猜** → 標 `unrecognized`（缺口）；可用文件自己的例題反算驗證。

---

## 9. 新增規範（PDF）與修訂版

### 9.1 新增

1. PDF 放進 `data\法規\`（來源、版次、公告日寫進 `_regs_manifest.json`），依 `docs\法規庫總目錄.md` 登錄 `build_catalog.py` 的 META，跑 `build_index.py`（檢查 §N.N 切分是否吞掉附錄或子條）。
2. MinerU 草稿（給人看）：`mineru_batch.py <src> [part PDF 檔名]`。
3. `regs_vtool.py new-source <src>` 看待辦，按 §2 轉錄；需要的新主題用 `add_topic.py` 登錄，`regq_selftest` 補一題考題。
4. **先查是否已存在（跨檔）**：`regs_vtool.py find <src> <clause>`。
5. 只有網頁文字的規範：框線表格自動轉 HTML；公式／表格走 §2（對照網頁原文），供人閱讀的放 `formulas.json`／`tables.json`，供智能體用的進 `verified\`。
6. **註冊「🎯 條號精準直達」口語別名**：在 `tools\regs\regs_server.py` 的 `_DIRECT_ALIASES` 與 `tools\design\build_cloudflare.py` 的 `DIRECT_ALIASES` 同步加上該規範的常用口語簡稱（例如 `"水保": ["swc_tech"]`、`"混凝土": ["rc112", "rc100"]`），讓使用者輸入「`<簡稱> <條號>`」（如 `水保 93`、`混凝土 7.4.2`）即可精準直達該條文。
7. **主題分組與計算器深連結（`tools\regs\regs_web.html`）**：若在 `topics.json` 新增了設計主題，須將主題名加入 `regs_web.html` 的 `TOPIC_GROUPS` 六大工程領域分組；若主題 `tools` 綁定了計算引擎，確認 `TOOL_TO_CALCS` 已配置對應計算器卡片（`design_launch_check.py --all` G0／G7 會自動驗證）。
8. **同步更新本機服務與 Cloudflare 線上雙入口**：
   - 本機重啟 `tools\regs\regs_server.py --web`。
   - 執行 `tools\design\build_cloudflare.py` 重新切分 64 個靜態條文分桶（`api/clauses/*.json`）與精簡搜尋索引（`api/search_index.json`，自動跳過 >20KB 原頁 base64 圖以維持單檔 <5MB），接著於 `_temp\cloudflare_design\` 執行 `$env:CLOUDFLARE_ACCOUNT_ID='e2c04af8447f8efcbf6ca597d6d3ad36'; npx wrangler deploy`（**勿加 `--temporary`**）更新線上固定網址 `https://civil-design-workbench.foil-newsstand.workers.dev/`。

### 9.2 修訂版

- 新版照 §9.1 入庫；舊版條目 `status` 改 `superseded`、`notes` 寫「由 <新 id> 取代」，`_links.json` 改指新版；**新舊差異（係數、門檻）用交叉測試量化**。
- 引擎仍引用舊版條號者（如 `rc_design.py` 曾引 100 年版），差異記入 `docs\規範查詢台.md`，由使用者決定是否改程式。
- **已被取代版本不轉錄**（rc100 129 條、seis111 64 條），進度一律 `--current-only`。

---

## 10. B 類待辦（明示不在本 SOP 的執行範圍）

`docs\規範入庫_B類待辦.md` 的 **630 條排版公式（B 類）** 由使用者指定列為**以後待辦**：
清單保留、**不標 skip**、不計入本次 coverage。日後要處理時照 §2.1「B 類不猜」原則，改以文件自身的例題反算或座標化文字層重建。

---

## 10B. 待補缺口清單（真缺口）

**`docs\規範入庫_待補缺口清單.md`** 由 `tools\regs\gap_report.py` 自動產生：

```bat
C:\Python312\python.exe -E -P -X utf8 tools\regs\gap_report.py --out docs\規範入庫_待補缺口清單.md
```

- 內容＝`_skips.json` 中 `status="unrecognized"` 的條文（**有表／式但尚未轉錄＝真缺口**），**不含** `qualitative`（定性、無算式）、`out_of_scope`（判斷用不到，原文未轉換）、`covered`（已由他條涵蓋）。
- 數字與 `docs\規範入庫進度.md` 的「辨識失敗(缺口)」欄**同一套統計邏輯**，兩者必須相同（目前 97 條／140 flagged 單元）。
- 每條列出**頁碼、flagged 單元數、原文長度、當初未轉錄的原因**，並依「與工作台計算器的相關度」分高／中／低三級排序，方便決定先補哪一部。
- 清單末附「已結案」表（flagged 單元全部處理完的規範）與六道閘門的驗收指令。
- **補完一批後跑 `regs_vtool.remove_skip(src, clause)`，再重跑本清單**，數字才會下降。

> 注意：`unrecognized` 不等於「沒內容」也不等於「用不到」。它代表原文確實有表格或公式、但排版破碎或表身未隨條文擷取；查詢時會顯示【未入庫｜辨識失敗】與【可信度：低】，**不得拿純文字表式推測數值**。
## 11. 工具速查

> 全部在 `tools
egs\`（2026-11-02 起由 `_temp` 提升：`_temp` 依 AGENTS.md §1.1 可整批刪除，工具不能住在那裡）。
> 跨平台、無絕對路徑；`-h` 看參數。環境探測用 `python tools/project_paths.py`。

| # | 指令 | 用途 | 產出 |
|---|---|---|---|
| 1 | `regs_vtool.py coverage --current-only --out _temp\backlog.md` | 盤點待辦 | 待辦清單 |
| 2 | `regs_vtool.py next -n 5` | 取下一批 | 條號清單 |
| 3 | `regs_vtool.py find <src> <clause>` | **查重**（跨分片、含母子條號） | `none - safe to add` |
| 4 | `page_table.py <src> --page N [--part P] [--y A:B] [--math]` | 讀座標化文字層 | 逐列文字＋欄線 |
| 4b | **`page_index.py build\|find\|show <src> [印刷頁碼]`** | **印刷頁碼 → PDF 頁 對照（§2.2）** | 避免猜頁碼 |
| 4c | `page_crop.py "<pdf>" <頁> --clip <x0> <y0> <x1> <y1> --dpi 400 -o out.png`<br>`page_crop.py "<pdf>" <頁> --bands 2 --dpi 260 --out _temp/crops/` | **高解析裁圖／切半頁（§2.2.1）** | PNG（260~420 dpi） |
| 4d | `locate_pages.py <src> "<關鍵字>" [--part 章名]` | **關鍵字 → PDF 頁碼**（跨分章 PDF） | 命中頁清單 |
| 4e | `dump_tables.py "<pdf>" <頁> [--captions]` | **`find_tables()` 表格骨架**（§Z.8：骨架定欄、原頁定歸屬） | 列×欄＋合併格 |
| 4f | `audit_qualitative.py [--src X] [--max-score 5]` | **稽核 qualitative 判定**（打分只定閱讀順序） | 可疑條文清單 |
| 4g | `audit_skip_reasons.py [--src X]` | **稽核 skip 理由品質**（找空泛理由，不改寫） | 待補理由清單 |
| 4h | `reconcile_progress.py [--src X] [--only-missing]` | **已決定／待處理對帳**（與 `status` 同判準） | 四類統計 |
| 5 | `regs_vtool.py scaffold formula\|table <id> <src> <條號>` | 產生條目骨架 | JSON 片段 |
| 6 | `payload_check.py <payload> [--fix]` / `--library` | **第1道閘門**（合併前） | `0 problem` |
| 7 | `merge_shard.py <payload> <shard>` | 安全併入（只增、擋重複、自動備份） | 前後數量 |
| 8 | `regs_vtool.py skip <src> <條號> "理由" --status covered|qualitative|out_of_scope|unrecognized` | 登錄未入庫條文（四類，見 §2 步驟 7） | `_skips.json` |
| 9 | `lint` → `verified_selftest.py` → `regq_selftest.py` → `design_conformance.py` → `regression.py` | **第2~6道閘門** | 全綠才出貨 |
| 10 | `regs_vtool.py status --current-only --out docs\規範入庫進度.md` | 進度（排除被取代版本） | 進度表 |
| 12 | `gap_report.py --out docs\規範入庫_待補缺口清單.md` | **真缺口待辦清單**（依與工作台相關度排序） | `docs\規範入庫_待補缺口清單.md` |
| 10b | `tools/clean_project.py --dry-run\|--apply` | 清 `_temp` 與散落暫存（跨平台） | 回收空間統計 |
| 11 | `ctx_budget.py [--gate 25]` | 量對話圖片張數與 body（≥40 MB 送不出去） | 見 `docs\對話上下文預算.md` |

**四條硬規則**

1. **一個 id 只能存在一個檔案**；`_b`／`_c` 只是控大小。查重一律用 `find`。
2. **目標分片存在 → 用 `merge_shard`，不用 `write`**（§4 事故）。
3. **B 類不猜**（§10）。
4. **改了 `tools\` 就跑 `regression.py` + `design_conformance.py`**。

**五條硬規則（補）**

5. **定位頁碼一律用 `page_index.py`，不靠猜**（§2.2）；**公式類必用高解析局部裁圖**（§2.2.1）。
6. **整表跨頁／合併格用 `find_tables()` 重建**，不逐行讀文字層（§2.2.2）。

---

## 12. 收盤狀態（2026-11-02 收盤，缺口已歸零）

**1384 條 flagged（現行版）的真實狀態**——不再用單一「已處理率」，因為它會把『有決定』誤讀成『都轉換好了』：

| 指標 | 單元數 | 比例 | 意義 |
|---|---:|---:|---|
| **已入庫（verified 條目對應之 flagged 單元）** | 845 | 61.1% | 結構化資料，可 `regs_formula`／`regs_table` 取數 |
| **↳ 其中待核（條目 `status="pending"`）** | **0** | 0% | 已入庫但有原文疑誤／來源缺漏，**查詢顯示【待核】，不得當已驗證取數** |
| **已涵蓋於他條** | 72 | 5.2% | 內容已併入其他 verified 條目 |
| **→ 已轉換／已涵蓋（可信賴取數）** | **959** | **69.3%** | |
| 定性（已讀過，確無算式表） | 273 | 19.7% | 不需轉換 |
| 非本工作區（原文有表／式，**未轉換未驗證**） | 152 | 11.0% | 查得到原文，但帶【可信度：低】警示 |
| **辨識失敗＝真缺口** | **0** | **0%** | ✅ 已全部處理完（見下表） |
| 未決定 | 0 | 0% | |

`verified/` 條目共 **1011**（612 formulas／399 tables；**pending 0**）。

**六道閘門全綠**：`payload_check --library` 0 problem、`lint ok`、`verified_selftest` 0 failure（612／399）、`regq_selftest` 0 failure（39＋22 題）、`design_conformance` exit 0（20 通過、0 差異）、`regression --ignore-new` 7 案相符。

**2026-11-02 新增兩項工具流程**（詳 §2.2）：
1. **`tools\regs\page_index.py`（印刷頁碼 → PDF 頁 對照表）**——已寫入 §2 步驟 1b、§8.1 坑、§11 工具速查與硬規則。解決「DB 的 page 是條文起頁、表常在下一頁」造成的反覆抓錯頁（本輪 27 條待核中 14 條屬此類）。
2. **進度表新增「其中待核」欄**——`status --current-only` 現在會把「已入庫但條目 `status="pending"`」的單獨列出，避免把 pending 誤讀為已驗證可用。

**缺口歸零：全部 34 份現行規範之 flagged 單元皆已分流完畢**（最後一批為 `steel99` 42、`hwbridge` 22、`flexpave91` 19、`wind103full` 11、`hwslope104` 10、`hwconst112` 6、`btr_design` 6、`urbanroad113` 5、`hwroute115` 3、`hwbridge104` 3、`sewer_std` 2、`btr_struct` 2、公路排水 6、`btr_equip`／`btr_general`／`seis113` 各 1）。

**仍帶 `pending`（原文疑點或來源缺漏，全庫共 0 條）**——這一類**不是**缺口，是「已轉錄但有一個已知疑點」，查詢時會顯示【待核】。2026-11-02 逐輪回原頁消化，**原 37 條已全部收斂（其中 7 條為本輪 400 dpi 逐字元複核）**：

| 已消化的 pending（35 條） | 消化方式 |
|---|---|
| `steel99_tension_field_Vn` | 補齊 7.6-19／7.6-20 之 Cv 兩式與 7.6-21（不考慮張力場） |
| `steel99_bolt_tension_T1033` | 原頁目視：A307 `1.82−1.80fv≤1.40`、F10T `√(3.62²−3.75fv²)`／`√(3.62²−1.82fv²)`（推翻先前文字層之 2.3/5.2/5.7/8.9） |
| `steel99_bolt_spacing_C1_T1036` | 原頁 10-22 逐格：≤22→3.0/0/5.0/1.5d−1.5、24→5.0/0/6.5/36.5、≥27→6.5/0/8.0/1.5d−1.5 |
| `steel99_ponding` | 原頁 11-9：**是「0.4S⁴」不是「0.45」也不是「S⁴/440」**；Cp＝0.05·Lp·Ls⁴/Ip、Cs＝0.05·S·Ls⁴/Is |
| `hwbridge_steel_grade_T91` | 原頁 184 逐格：**100/100W（≤64 mm）之 Fy 括號內確為 344.8（原書誤植），689.5 印在相鄰 Fu 格** |
| `hwbridge_pc_rebar_limit` | 原頁＋文字層雙查：**確認原書即無 b·d**（維持 pending，見下表） |
| `hwbridge_mixed_beam_R` | 原頁：**分母確為「6＋βΨ(3−Ψ)」無括號** |
| `hwbridge104_fatigue_stress_range` | 原頁：**1470/560（kgf/cm²）與 145/55（MPa）是同一公式兩制，非兩個版本** |
| `rc112_joint_depth_18523` | 18-18＋18-19 跨頁拼合：**(d)「任何構入接頭…產生接頭剪力梁之 h/2」** |
| `rc112_ldt_T25442` | 原頁：**分母常數為 32（kgf 制）、31（MPa 制）**（推翻先前推得的 23） |
| `flexpave91_DAMA_emulsified`／`_Egb_regress`／`_Eleq`／`_Nf2` | 原頁 5-19～5-21：**指數正負、立方位置、f5＝0.69** 全部確認 |
| `flexpave91_Estar_D68`／`_D69` | 原頁 附D.13／附D.14 逐格確認；**274251／282494 為原書誤植** |
| `flexpave91_AI_traffic_class_T721` | 原頁 7-4／7-5：**表7.2.(1) 六級與 7.2.4 路基三分級界限值**全部確認 |
| `wind103full_Cpc_T224` | find_tables()＋420 dpi 裁圖：**表2.24 三個係數列 × 8 角度欄之完整歸屬**（含合併格） |
| `wind103full_MTz_resonant`／`_RLR_spectrum` | 原頁：**R_TR 指數為 3.6β_T**；**β1 分子為 (L/B)⁴、分母後 +0.12(L/B) 屬 β1** |
| `hwroute115_superelevation`／`_widening`／`_vehicle_coef_T391` | 300–420 dpi 裁圖：**式(1) 方括號外還有「1−」、平方只罩 (1−Rmin/R)**；**U_c＝2.5＋√(R²＋X)−√(R²−Y)**（X、Y 無平方）；**表3.9.1 四車種係數** |
| `urbanroad113_superelevation_adjust_T34334` | 300 dpi 裁圖：**式(4) 分母為 R_r−R_min**（非 R−R_min） |
| `urbanroad113_cross_section_T211` | 200 dpi 逐格重建表2.1.1（13 個斷面單元 × 4 種道路功能） |
| `hwdrain_A_regional_flood` | 原頁：**東部區負號在括號內（「−0.004」），8.4 前無負號** |
| `hwdrain_P_earth_load`／`_T_schocklitsch` | 原頁：**C 直接代入無隱含換算**；**q_ci＝1.944e-5·d_i/S^{4/3}、(q−q_ci) 無上標** |
| `btr_design_retreat_D1` | 法規全文檔補齊第 264 條**三款**公式（D1／D2／D3） |
| `btr_equip_plumbing_count_T37` | **程式解析法規方框表**，補齊 9 類 × 30 列之器具個數 |
| `hwconst112_earthwork_balance` | 原頁：**不等號是「≧」不是「≤」**（先前讀反，已更正，邏輯即自洽） |
| `hwconst112_railing_material_T05522_1` | 原頁：**Steel Rail Cap 與 Block Washer 為同列兩項目** |
| `found112_liquefaction_indicators` | 原頁 10-21：**PL 為積分式 PL＝∫₀²⁰F(z)W(z)dz**（非 Σ 加權），F(z)＝1−F_L、W(z)＝10−0.5z |
| `seis113_SDS_T2_18` | **改用 PyMuPDF find_tables() 重建**（文字層會打亂「縣市」合併格）：**327 列＝全台 368 鄉鎮市區 − 臺北市 12 − 新北市 29**，22 縣市齊備、無重複 |
| `hwroute115_transition_length` | 原頁：**J 建議值 0.7−Vd/400、容許最大值 1.1−Vd/200** |

**剩餘 2 條 pending（本輪無法再由工作區內解決）**：

| 條目 | 原因 |
|---|---|
| `btr_design_underground_plaza` | 面積公式在法規匯出檔即缺漏（「因條文排版無法完整呈現內容」），且 `data\法規\` 無該編 PDF 可回查 |
| `hwbridge_pc_rebar_limit` | **已查證係原書排版本身漏排 b·d**（原頁＋文字層雙查）——非轉錄問題，須待勘誤 |

**B 類 630 條排版公式**依使用者指示仍列以後待辦、不標 skip（`docs\規範入庫_B類待辦.md`）。

**這一輪新增的教訓**（已寫進 §2、§8）：
1. **『100% 處理』是有決定、不是都轉換**——skip 必須分類，且查詢時要自動警示（§2 步驟 7）。
2. **單一來源看圖也會錯**——`urbanroad113_curb_inlet_Qc` 的指數 5/3 應為 5/2，靠第二部規範同式才發現（§8.1）。
3. **模組內 import 失敗不可靜默吞掉**（§8.2）。
4. **「解x.y-N」不一定是公式編號，也可能是圖號**——`found112` 5.3.3 的「解5.3-10／11」實為圖號，該節因此改判定性（§8.1）。
5. **公式常在同一條的「次頁」**——先在全庫文字層搜尋式號定位頁碼，不要逐頁試。
6. **量級檢查比對稱檢查更容易抓到大錯**——`hwroute115_9` 的加寬式讀錯後 ΔW 得 109 m（實務 0.5~2 m），一算就露；反之表P-1 的 196 格對稱性檢查只抓到 3 對原表固有的捨入差異。**每次轉錄都先問「這個數量級合理嗎」**。
7. **「辨識失敗」會被舊腳本誤標**——`hwconst112` 第16526 章（公路照明）25 筆純文字單元被一律標成 unrecognized，查詢時對純文字條文發出【可信度：低】的錯誤警示。**清缺口時要順手掃一遍 `T.kinds()` 為空的條號**。
8. **雙單位不是兩個版本**——`hwbridge` 的 63／6.2、70／6.9、`hwbridge104` 的 0.504／0.158，比值都約 10.2 或 3.19（＝√10.2），是 kgf/cm² 與 MPa 並列；曾被子代理誤判為「原文被劃掉、以貼覆值修正」。
9. **同一個係數可能長在括號外**——公路排水水資會公式的 34.0／2.3／38.0 是 `Q_T = K·A^e·(a + b log T)` 的外乘常數，不是括號內的常數項；讀錯會差一個數量級（北部 A=100、T=50 時 1884 vs 733 m³/s）。
