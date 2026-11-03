# 專案收工 SOP（Civil_Design_WorkBench）

> 版本：1.0（2026-11-03，使用者核可）
>
> 觸發：使用者說「收工」、「關帳」或「closeout」。
>
> 核可事項：
> 1. 版本採 CalVer `vYYYY.MM.DD-N`（同一天第 N 次收工）。
> 2. 「收工」一律授權 commit、tag 與 push `main`；若使用者另說「先不推」
>    則跳過 push 並在回報註明。
> 3. 本 SOP 落地於 `docs\專案收工SOP.md`，並在 `AGENTS.md` §5 加觸發器。
> 4. 每次收工只 stage「本次收工清單」白名單，不得掃入其他 dirty 檔。
>
> 定位：本 SOP 是通用 14 步收工流程的**專案落地版**；通用版仍是背景原則，
> 但檔案落地、交付六道閘門、設計回歸與工作台重啟以本 SOP 為準。

---

## 0. 完成定義（Definition of Done）

「本階段作業完成」必須同時滿足：

1. 本次承諾的功能／文件全部完成，沒有用「下次再補」掩蓋。
2. 本次改動的模組測試全過；全案回歸基準相符。
3. 文件與程式一致（欄位、預設值、數量公式、限制）。
4. 本次經驗已收編進 SOP／踩坑紀錄／索引。
5. 已知限制與未修問題已列清單，沒有混進本次 commit。
6. 交付物只存在 `out\<案名>\`；`_temp\` 沒有唯一副本。

---

## 1. 範圍凍結（先做，不可跳）

1. 列出「本次收工清單」：本次階段的程式、文件、資料、測試。
2. 明講「本次不做」：既有 dirty 檔、其他 agent 的修改、無關 bug。
3. 建立兩個清單：
   - **納入 commit**：本次階段實際改的檔案（白名單）。
   - **保留不動**：其他 dirty／untracked／stash。
4. 未經使用者點名，不得把保留清單的檔案 stage 進 commit。

---

## 2. 工作區盤點

```powershell
git status --short --branch
git stash list
git diff --stat
```

- 分辨「本次修改／既有 dirty／未追蹤／別人的工作」。
- **不得 revert、不得 checkout、不得刪除**非本次修改。
- 記錄目前 branch、HEAD、stash 數量。

---

## 3. 本次範圍測試

依改動模組跑對應測試，不能只跑一支就宣稱全過：

| 改到什麼 | 必跑 |
|---|---|
| `tools\design\*` | `design_core_selftest.py`、該引擎 `--selftest` |
| `design_api.py`／工作台 | `design_workbench_selftest.py`、`design_launch_check.py <id>` |
| `qty_models.py`／`case_core.py` | `regression.py`、受影響案件的一致性檢查 |
| 繪圖／出圖 | `check_delivery.py`、圖／數對帳 |
| 規範查詢台 | `regq_selftest.py`、`verified_selftest.py` |

---

## 4. 全案回歸

```powershell
$env:PYTHONIOENCODING='utf-8'
C:\Python312\python.exe tools\selftest\regression.py
```

- **基準相符**才算過。
- 基準不符時，先列差異、算比例、確認是否為本次**刻意**變更。
- 只有確認是刻意變更才 `--update`；回報必須寫「前值 → 後值 → 原因」。
- 既有的 `ok=false` 案件（例如 `擋土牆3m重力式_北屯民政里`）要標明
  「本次未修、非本次造成」，不可假裝全綠。

---

## 5. 交付六道閘門（有案件交付才跑）

1. 設計檢核全過（`case_core.check`）。
2. 出圖品管 E1～E18（`check_delivery.py`）。
3. 圖／數對帳（`dxf_takeoff.py`）。
4. 配筋圖間距對帳（`--rebar`）。
5. 設計段落注入（`report_case.json` 的 `_derived.design_sections_error` 必須為空）。
6. 全案回歸。

任一道不過即視為未完成，不得用「圖看起來正常」代替。

---

## 6. 工作台重啟與 HTTP 驗收

`design_api` 會被 server 快取，改過一定要重啟：

```powershell
# 先停舊的 regs_server（依實際 PID）
Get-Process python | Where-Object { $_.Path -like '*Python312*' }

# 重啟（背景、隱藏視窗）
Start-Process -FilePath 'C:\Python312\python.exe' `
  -ArgumentList 'tools\regs\regs_server.py','--web' `
  -WorkingDirectory 'D:\Civil_Design_WorkBench' -WindowStyle Hidden

# 驗收
Invoke-WebRequest http://127.0.0.1:8765/design -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8765/api/design/health
Invoke-RestMethod http://127.0.0.1:8765/api/design/catalog
```

- `catalog` 要看得到本次新增／修改的欄位與計算器。
- 至少對本次計算器做一次 `POST /api/design/run`，確認 `ok=true`、
  檢核數與 `summary` 正確。
- 有 Cloudflare 線上版且本次改到 `design_api`／工作台時，另跑
  `npx wrangler deploy` 並比對線上／本機 catalog 與一次計算結果；
  未部署要明講「線上版仍為舊版」。

---

## 7. 文件同步

依改動範圍更新，缺一項就不算完成：

| 檔案 | 更新什麼 |
|---|---|
| `docs\設計計算產線.md` | 公式、對帳值、限制 |
| `docs\<工項>計算SOP.md` | 工項流程與常見錯誤 |
| `docs\設計計算工具索引.md` | 工具一列、口語分派 |
| `docs\設計工作台.md` | 計算器地圖、欄位規則 |
| `docs\設計計算核心_擴充藍圖.md` | 能力現況／缺口 |
| `docs\設計計算器上架SOP.md` | 新的上架教訓 |
| `AGENTS.md` | 總數、觸發器、口語入口（僅在使用者核可時） |
| `怎麼用.md` | 使用者速查（常用工項） |

---

## 8. 經驗收編

1. 本次新坑寫進 `docs\踩坑紀錄.md`（新分類或對應分類最下方，註日期）。
2. 同步更新 `docs\經驗索引_INDEX.md`，**先查 id 是否已被別章使用**。
3. 若經驗已成流程，寫進對應 SOP，不要只留在踩坑紀錄。
4. 經驗內容要包含：症狀、原因、修法、可執行證據、限制。

---

## 9. 暫存與敏感資訊

```powershell
git diff --check
git status --short
```

- 掃本次 diff 是否含 API key、token、password、連線字串。
- `claude_desktop_config.json` 含明文金鑰，**嚴禁輸出內容**。
- 確認 `.env`／`.pem`／`.key` 沒被 stage。
- `_temp\` 可整批刪除；刪前確認沒有唯一副本。
- 交付清單只列 `out\<案名>\`，不列 `_temp\`。

---

## 10. Git 差異整理

- 只 stage 第 1 步白名單的檔案。
- **禁用 `git add -A`／`git add .`**（會掃進別人的 dirty 檔）。
- 逐檔 `git add <path>`，再 `git diff --cached --stat` 確認範圍。
- 若本次包含二進位產出（DWG／PDF／XLSX），確認是 `out\` 的交付物，
  不是 `_temp\` 的中間檔。

---

## 11. Commit

```powershell
git commit -m "feat(box_culvert): 補齊車載、逐面配筋與每延米數量"
git log -1 --oneline
```

- Conventional Commits：`feat`／`fix`／`docs`／`test`／`chore`。
- 一個 commit 只含本次階段；不要把 unrelated dirty 檔混進來。
- 若本次有多個獨立主題，拆成多個 commit。

---

## 12. Tag

本專案採 **CalVer**：

```text
vYYYY.MM.DD-N     （例：v2026.11.03-1，同一天第二次收工為 -2）
```

```powershell
git tag -a v2026.11.03-1 -m "box culvert: traffic + rebar + quantities"
git tag --points-at HEAD
```

- Tag 必須指向本次 commit。
- 同一天重複收工遞增 `-N`；不得重用已存在的 tag。

---

## 13. Push 與遠端驗證

```powershell
git fetch origin
git log HEAD..origin/main --oneline
git push origin main
git push origin v2026.11.03-1
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

- 先確認遠端沒有新提交；有就先 rebase／merge，解衝突後**重跑第 3～5 步**。
- 遠端 SHA 必須等於本地 HEAD；tag 必須存在遠端。
- Push 失敗要診斷 remote／credential／權限，不得假裝完成。
- 若使用者明確說「先不推」，跳過本步並在回報寫「未推」。

---

## 14. 服務重啟與煙霧測試

- 重啟 `regs_server.py --web`（若本次有改 API／工作台）。
- 確認 `/design`、`/api/design/health`、`/api/design/catalog` 正常。
- 若本次有背景服務／自動化，確認它們的狀態與下次執行時間。
- 告知使用者如何自行檢查（網址、指令）。

---

## 15. 最終回報（必填）

1. 版本號、commit hash、tag。
2. 本次檔案清單（程式／文件／資料／交付物分開列）。
3. 每道測試的**實際輸出**（不是「應該會過」）。
4. 保留的 dirty／untracked／stash。
5. 未修但相關的既有問題（明講「未修」）。
6. 已知限制與風險。
7. 自評可信度 1～10。
8. 下一次接手的入口：先讀哪個 SOP、先跑哪個指令。

---

## 16. 失敗處理原則

- 測試失敗：先修，不進入 commit；真的修不了就停下回報，不用「已知悉」帶過。
- 回歸不符：先確認是否刻意變更；不是就找回歸原因。
- Push 失敗：不重試到被鎖帳號；記錄錯誤碼與下一步。
- 交付閘門失敗：不產交付清單、不宣稱完成。
- 任何「未做」都要寫進最終回報，不用完成字眼掩蓋。

---

## 附：本次收工清單模板

```text
階段：箱涵車載／逐面配筋／每延米數量
納入 commit：
  tools/design/box_culvert.py
  tools/design/design_api.py
  tools/design/frame_analysis.py
  tools/design/rc_design.py
  tools/case_package/case_core.py
  tools/case_package/qty_models.py
  cases/箱涵三孔測試/case.json
  tools/selftest/baseline.json
  tools/selftest/design_core_selftest.py
  tools/selftest/design_workbench_selftest.py
  tools/selftest/regression.py
  docs/箱涵計算SOP.md
  docs/專案收工SOP.md
  docs/設計計算產線.md
  docs/設計計算工具索引.md
  docs/設計工作台.md
  docs/設計計算核心_擴充藍圖.md
  docs/設計計算器上架SOP.md
  docs/踩坑紀錄.md
  docs/經驗索引_INDEX.md
  AGENTS.md
保留不動：
  （其餘既有 dirty／untracked，逐項列 git status）
測試：
  box_culvert --selftest 16/16
  design_core_selftest 142 OK
  design_workbench_selftest 0 failure
  design_launch_check box_culvert 0 FAIL / 0 WARN
  regression 7 案基準相符（北屯案既有 NG）
版本：v2026.11.03-1
```
