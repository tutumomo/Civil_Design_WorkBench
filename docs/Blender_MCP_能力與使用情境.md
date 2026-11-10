# Blender MCP：能力與使用情境

> `blender` 是本專案 MCP 通道之一（`tools/blender/blender_mcp.py`，stdio）。它讓 AI 智能體**在背景**操作 Blender：
> 寫一段 `bpy` Python 就能建模、量測、匯出、渲染，不會跳出視窗，也不干擾你開著的 Blender。
> 實際用起來很順手：改一個數字、重出一張圖，通常只要幾十秒到幾分鐘。

## 1. 五個工具

| 工具 | 做什麼 | 重要參數 | 典型用途 |
|---|---|---|---|
| `blender_info` | 探測 Blender 安裝方式（直接執行檔／Windows MSIX）、版本、add-on | `probe=true` 會真的啟動一次讀版本 | 開工前確認環境；換電腦後第一步 |
| `blender_run_python` | 背景執行一段 `bpy` 腳本，回傳結構化結果 | `script`、`blend_file`（先開既有 .blend）、`args`（腳本裡用 `ARGS` 取）、`timeout_s` | 建模、量測、改場景、匯出 glb／stl／.blend |
| `blender_render` | 渲染一張靜態圖並回傳檔案 | `output_path`、`script`（建場腳本）、`blend_file`、`engine`（CYCLES／BLENDER_EEVEE）、`samples`、`resolution`、`camera`、`transparent` | 3D 意象圖、正交俯視補圖、多視角 |
| `blender_convert` | 3D 格式互轉 | `input_path`、`output_path`；支援 obj／fbx／stl／ply／gltf／glb／usd／usda／usdc／abc | SolidCraft／CAD 模型轉可交付格式；回傳物件數與三角面數可對帳 |
| `blender_selftest` | 端到端自檢：版本 → 建立方體 → 渲染 → 檢查成品 | 無 | 換電腦、升級 Blender 後先跑；看 `checks` 每項 `passed` |

**回傳欄位固定**：`ok`、`error`、`traceback`、`log_tail`、`result`、`artifacts`、`wall_s`。
失敗時不必猜：每次呼叫都會建一個工作目錄 `_temp/blender/<時間>_<名稱>/`，裡面有 `user_script.py`、`blender.log`、`result.json`，可直接追。

### 腳本怎麼把結果「機讀」回來

在腳本裡設兩個全域變數即可：

```python
RESULT = {"長": 12.0, "面積_m2": 36.5}        # 任意 JSON，會出現在回傳的 result
ARTIFACTS = ["/絕對路徑/成品.glb"]              # 會檢查檔案是否真的存在，列在 artifacts
```

只 `print()` 的話，`result` 會是 null，只能翻 log。

## 2. 使用情境

| 情境 | 你說什麼 | 智能體怎麼用 | 產出 |
|---|---|---|---|
| **景觀平面圖／手繪圖 → 3D 意象圖** | 「把這張公園平面圖做成 3D 模擬」 | 先送判讀確認表，確認後用 `tools/landscape3d/` 的場景腳本，`blender_run_python` 建模存 .blend，`blender_render` 出多視角 | `out/<案名>/` 下的透視圖、正交俯視補圖、`.blend`。**意象，不是施工圖** |
| **改一個數字重出圖** | 「路寬改 6 m、再出一次」 | 場景常數集中在腳本開頭，用 `args` 覆寫後只重建重出 | 參考實測：建模＋4 張約 2.5 分鐘；載入既有 .blend 補 1 張約 40 秒（Cycles CPU、1600×900） |
| **補一張不改模型的視角** | 「再給我一張正交俯視」 | `blender_render` 搭配 `blend_file`，腳本只加相機 | 新視角圖，原模型不動 |
| **用程式量測，不靠目視** | 「這個坡面實際多長？車道淨寬夠嗎？」 | `blender_run_python` 讀物件 `dimensions`、頂點座標，寫進 `RESULT` | 數字（可與設計值對帳），避免只憑畫面判斷 |
| **模型格式轉換與對帳** | 「把 SolidCraft 的 STL 轉 glb 給簡報用」 | `blender_convert`，看回傳的 `objects`／`triangles` 確認有讀進來 | 轉好的檔案＋面數對帳 |
| **簡報／報告用的擬真圖** | 「這個擋土牆做一張帶光影的示意圖」 | 腳本建場景、`blender_render` 出 PNG（可 `transparent=true` 去背） | PNG，可放進 GridCraft／WordCraft／DeckCraft 的文件 |
| **換電腦後確認環境** | 「Blender 能用嗎？」 | `blender_info(probe=true)` → `blender_selftest` | `checks` 全部 `passed` 才算數 |

> 與 SolidCraft 的分工：**SolidCraft 做精確的參數化構造物**（STEP／STL／3MF，要尺寸準確）；
> **Blender 做場景、光影、材質與意象圖**。兩者可接力：SolidCraft 出模型 → `blender_convert` 轉檔 → Blender 放進場景渲染。

## 3. 約定與限制

- **單位與座標**：1 Blender unit = 1 公尺，Z 軸向上（與本專案一致）。
- **輸出位置**：交付成品寫到 `out/<案名>/`；暫存（工作目錄）自動落在 `_temp/blender/`，隨時可刪。
- **腳本內的路徑請用絕對路徑**。實測：腳本以工作目錄為 cwd，寫相對路徑會落在 `_temp/blender/<job>/` 裡，
  `artifacts` 會是空的、之後 `blender_convert` 也找不到檔案。可用 `args` 把絕對路徑傳進去（例如 `ARGS["out"]`）。
- **`blend_file` 模式不要呼叫 `bpy.ops.wm.read_factory_settings()`**，否則剛載入的場景會被清空。
- **每次呼叫是獨立的 Blender 行程**，不保留上一次的場景；要延續就存 .blend，下次用 `blend_file` 開。
- **渲染時間**：Cycles 走 CPU 較穩；`time_limit` 是早停機制，兩次同設定出圖的像素不會完全相同，對帳看解析度、檔案大小與肉眼，不要比像素雜湊。
- **成品要驗證**：`blender_render` 的 `result.bytes` 大於 0 才算真的出圖；交付前用肉眼看過圖。
- **不寫死版本**：Blender 更新頻繁，相容性以 `blender_selftest` 為準，不把版本號當規格。

## 4. 各平台

| 平台 | 啟動方式 | 說明 |
|---|---|---|
| Windows（Microsoft Store 版） | 以 MSIX 封裝身分經 PowerShell 啟動 | 直接呼叫 `blender.exe` 會被拒絕；runner 已處理 |
| Windows／macOS／Linux（一般安裝版） | 直接執行 | 用環境變數 `BLENDER`（或 `CIVIL_AI_BLENDER`）指定，或讓 `blender` 在 PATH 上 |

2026-11-10 在 Linux（aarch64）實測：`blender_selftest` 4 項全過；`blender_run_python` 回傳 `RESULT`、
`blender_convert` glb → obj 對帳（物件數、三角面數）皆正常。同日修正一個 Linux／macOS 上的問題：
舊版 runner 無論平台都先呼叫 PowerShell，沒有 PowerShell 的機器會直接丟 `FileNotFoundError`；
現在非 Windows 會跳過 MSIX 探測，改走 `BLENDER` 環境變數與 PATH。

## 5. 註冊與驗證

```bash
python tools/mcp/register_all.py --only blender --dry-run   # 看會改哪些客戶端設定
python tools/mcp/register_all.py --only blender --apply     # 寫入（每個檔先備份），然後重開 AI 客戶端
```

註冊後請 AI 跑一次 `blender_selftest`，`ok` 為 true 才算接通。命令列等價用法（不經 MCP）：

```bash
python tools/blender/blender_runner.py info --probe
python tools/blender/blender_runner.py run <script.py> --blend <場景.blend> --arg KEY=VALUE
python tools/blender/blender_runner.py render <output.png> --script <建場.py> --engine CYCLES --samples 64
```

## 6. 延伸閱讀

- [`3D景觀模擬_作業經驗與踩坑.md`](3D景觀模擬_作業經驗與踩坑.md)：手繪圖轉 3D 的完整流程（判讀確認表、建模手法、渲染設定與時間預算）。
- `tools/landscape3d/`：可重用的場景腳本（避車彎、社區公園、俯視補圖、紙模風格）。
- [`AI工具鏈_MCP整合_2026-11-03.md`](AI工具鏈_MCP整合_2026-11-03.md)：六條 MCP 通道的整合紀錄。
- [`口語操作手冊_ArtCraft與CAD工具.md`](口語操作手冊_ArtCraft與CAD工具.md)：用白話操作各工具。
