# Cloudflare 部署紀錄（工程設計工作台／規範查詢台）

> 線上固定網址：**`https://civil-design-workbench.foil-newsstand.workers.dev/`**
> （工作台 `…/design`、規範查詢台 `…/`）
> 帳號：`Foil Newsstand`／Account ID `e2c04af8447f8efcbf6ca597d6d3ad36`
> Worker 名稱：`civil-design-workbench`

## 1. 部署流程（固定兩步，勿加 `--temporary`）

```powershell
$env:PYTHONIOENCODING='utf-8'
cd <專案根目錄>
# 1) 重建 bundle（22 計算器 + 規範庫 + 前端；輸出到全新目錄避免舊檔殘留）
C:\Python312\python.exe -E -P -X utf8 tools\design\build_cloudflare.py --out _temp\cf_deploy_<日期>
# 2) 部署（wrangler.toml 已內含 account_id；**不可加 --temporary**，否則網域會過期）
cd _temp\cf_deploy_<日期>
npx wrangler deploy
```

- `build_cloudflare.py` 會自產 `worker.js` 與 `wrangler.toml`（含 `account_id`）。
- 部署後 **必做線上驗收**（§3），不可只看 wrangler 印 URL。

## 2. 部署紀錄

| 日期 | 對應 commit | Worker Version ID | Bundle 摘要 | 線上驗收 |
|---|---|---|---|---|
| 2026-11-04 | `9e109a3` | `62bf3688-06c8-4465-b202-c40f20ebba3f` | 22 計算器／177 個 Python 模組／1011 筆已驗證條文／29 主題／34 來源／12004 條文（64 分桶）／8904 列搜尋索引／22 張公式圖／188 個靜態資產 | 通過（見 §3） |
| 2026-11-04（第二次） | `v2026.11.04-5` | `979b1fd8-53b4-412c-b9a1-30fe02349a32` | 同 22 計算器；`wall_stability` 更名「擋土牆穩定與配筋」，新增 fc′／fy／保護層／主筋／構造筋欄位與配筋結果 | 通過：catalog 標題與 14 個欄位正確；瀏覽器端 Pyodide 實跑 `ok=true`、14 項檢核、138.46 kg/m |
| 2026-11-04（第三次） | `v2026.11.04-6` | `016ef24f-bc0e-4059-b9ea-eaf838a24479`（重部署後 `bfeb3067-bb8c-4918-ba7c-7a47933b040a`） | 同 22 計算器；**RC 鋼筋損耗率全專案改 6%**（`rc_design.LAP_ALLOWANCE` 0.12→0.06，牆／溝／涵一致），硬寫「12%」字串改為動態取值 | 通過：線上實跑「配筋設計（含 6% 搭接、錨定與損耗）：131.04 kg/m」、頁面無 12% 殘留、綜合判定全部通過 |

## 3. 線上驗收清單（每次部署必跑）

1. `GET /api/design/health` → `{"ok":true,"calculators":22,...}`。
2. `GET /api/design/catalog` → `calculators` 數量與本機 `design_api` 目錄一致。
3. `GET /design` 與 `GET /` → HTTP 200。
4. **瀏覽器實跑一次計算**（線上採 `mode=cloudflare-edge-pyodide`，
   Python 引擎在**使用者瀏覽器端**執行，伺服器端 `POST /api/design/run`
   會回 404，**這是設計如此、不是故障**）：
   用 Playwright 開 `/design` → 取 `/api/design/catalog` 的
   `counterfort_wall.example` → 呼叫頁面內 `executeDesignRun(calcId, payload)`
   → 確認 `ok=true`、`checks` 全過、summary 含新版數值
   （2026-11-04 實測：30 檢核 0 失敗、配筋量 621.47 kg/m、扶壁 8-D32、d=4515 mm）。

## 4. 已知限制

- 線上計算＝瀏覽器端 Pyodide，首次啟動需載入引擎，較慢；不做伺服器端運算。
- 線上版本與本機 repo 必須同步：更新程式後要重建並重新部署，否則線上仍是舊版。
- `_temp\cf_deploy_*` 為暫存物（§1.1 可整批刪除），線上版本以 Worker 為準。
