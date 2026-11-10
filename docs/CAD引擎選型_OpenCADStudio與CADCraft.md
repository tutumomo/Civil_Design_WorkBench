# CAD 引擎選型：OpenCADStudio vs ArtCraft CADCraft

> 建立日期：2026-11-08｜量測環境：Linux aarch64 / NVIDIA GB10
> 版本：不寫死（外部工具更新頻繁）；即時查 `python tools/project_paths.py --versions`，歷史基準見 [`docs/已驗證環境快照.md`](已驗證環境快照.md)

> ⚠️ **2026-11-10 更新：本檔 §1 分工表與 §9 建議已被 §13 取代。** 產線預設後端改為 **OpenCADStudio**（經 `tools/acad/acc.py`），
> §9 第 4、5 點（批次一律 cadcraft-cli、OCS 不進 `case_package.py`）不再適用。§2~§8、§10~§12 的實測數據仍可作歷史參考。

## 1. 結論（先講該用哪一套）

**兩者並用，各守一段產線；不是二選一。**

| 產線環節 | 指定工具 | 理由（實測） |
|---|---|---|
| DXF → DWG（交付格式） | **cadcraft-cli** | 快 10 倍、記憶體 1/3，且 `acc.py` 現行 Linux 後端即為它 |
| DWG/DXF → PDF + CTB 出圖型式 | **OpenCADStudio `/api/v1/plot`** | 唯一能「指定 `plot_style` 並出 A3 橫式 monochrome PDF」的路徑；cadcraft-cli 的 headless PDF 走模型空間、採圖層原色 |
| DWG/DXF → PNG / SVG | **cadcraft-cli** | `convert` 直接支援；OCS 的 PNG 需經 `ocs_render`（執行中程式） |
| 需保住 `TOMO_PLOTSTYLE` 的往返 | **OpenCADStudio** | cadcraft-cli 會丟掉該自訂標頭變數（E18 失敗） |
| 幾何檢視、標註、圖層、MLEADER 等編輯 | **OpenCADStudio GUI** | 431 條 cadcraft 命令 vs OCS 完整 DIM/MLEADER/LAYER 家族 |
| AI 深度操作（意圖級工具） | **OpenCADStudio `--mcp`** | 22 個 `ocs_*` 意圖工具 vs cadcraft 12 個低階工具 |

> ⚠️ **2026-11-08 重要更正**：本文件初版誤稱「OpenCADStudio 無法出 PDF」。該結論只在 **`--export` 子命令**成立 ——
> `--export` 確實只接受 `.dwg/.dxf/.dwt`。但 OpenCADStudio 另有 **`POST /api/v1/plot`** REST 端點（由 `--http PORT` 啟動），
> 可無介面輸出 PDF，並支援 `layout`、`paper`、`scale`、`fit`、`orientation`、**`plot_style`**。
> 已實測在真實 A3 案圖上產出 420×297 橫式、黑白、中文正確的 PDF（見 §12）。

## 2. 架構與來源差異

| 項目 | OpenCADStudio | ArtCraft CADCraft |
|---|---|---|
| 來源 | GitHub 開源（GPL-3.0），HakanSeven12 | ArtCraft Launcher 套件（16 個 App） |
| 語言 | Rust（73%）＋ Fluent | 原生 C++/Rust |
| 桌面 GUI | 有（wgpu GPU 加速，Vulkan 可用） | `cadcraft.exe` |
| 無介面 CLI | `--export / --serve / --batch / --mcp` | `cadcraft-cli {info,convert,run,commands,mcp}` |
| 網頁版 | 有（opencadstudio.com） | 無 |
| 授權 | GPL-3.0 | 見 ArtCraft 授權 |

## 3. 保真度實測（同一份真實案圖往返）

樣本：`out/地籍套繪_豐原區西湳里/豐原區西湳段地籍套繪圖.dxf`（1.0 MB）

| 指標 | 原始 | OpenCADStudio 往返 | cadcraft-cli 往返 |
|---|---|---|---|
| 模型空間實體 | 1550 | **1550** | **1550** |
| 圖層 / 圖塊 | 12 / 3 | 12 / 3 | 12 / 3 |
| 紙空間實體 | 99 | 99 | 99 |
| LWPOLYLINE / HATCH / TEXT / LINE | 798/397/204/149 | 完全相同 | 完全相同 |
| ANSI31 Hatch 樣式 | 保留 | 保留 | 保留 |
| 中文文字內容 | 保留 | 保留 | 保留 |
| TOMO 字型（gbenor.shx + CHINA1.SHX） | 保留 | **保留** | **保留** |
| `TOMO_PLOTSTYLE` 自訂變數 | monochrome.ctb | **monochrome.ctb** | **遺失（None）** |
| DWG 版本 | — | AC1032（2018） | AC1032（2018） |
| 圖紙尺寸／旋轉 | 297×420 rot=1 | 297×420 rot=1 | 297×420 rot=1 |

**唯一失分點：cadcraft-cli 丟失 `TOMO_PLOTSTYLE`。** 直接後果是 `check_delivery.py` 判 E18 錯誤：

```
(C) cadcraft-cli 往返
✗ 錯誤 1 項
   E18 DXF 未記錄出圖型式（應為 monochrome.ctb）；請用 apply_plot_style.py 補寫
結論：不可交件，先修
```

補救成本低（跑 `tools/acad/apply_plot_style.py`），且這是既有已知工序。

## 4. 效能實測（三次取樣）

| 工具 | 耗時 | 峰值記憶體 |
|---|---|---|
| cadcraft-cli | **0.03–0.05 s** | **85 MB** |
| OpenCADStudio | 0.43 s（穩定） | 256 MB |

cadcraft-cli 快約 10–14 倍、記憶體約 1/3。對批次（數十至數百張圖）有實質差距。

## 5. 出圖能力（決定性差異）

| 輸出 | OpenCADStudio | cadcraft-cli |
|---|---|---|
| `.dwg` / `.dxf` / `.dwt` | ✅ `--export` | ✅ `convert` / `save` |
| `.pdf` | ❌ `--export` 拒絕（僅支援 dwg/dxf/dwt）；`PLOT` 在 `--batch` 下需互動，無法無人值守 | ✅ `convert IN.dxf OUT.pdf` |
| `.png` | ⚠️ 僅 `ocs_render`（MCP，執行中程式） | ✅ `convert IN.dxf OUT.png`（2400×1600） |
| `.svg` | ❌ | ✅ |
| CTB 出圖型式 | GUI 可載入編輯；headless 無對應旗標 | 專案以 `apply_plot_style.py` 補寫 |

**兩者都能無人值守產 PDF，但性質不同**（PDF 是 §6 交件門檻的必備檔）：

| | cadcraft-cli | OpenCADStudio `/api/v1/plot` |
|---|---|---|
| 觸發方式 | `convert IN.dxf OUT.pdf` | `POST http://127.0.0.1:PORT/api/v1/plot` |
| 空間 | 僅模型空間 | `layout` 可指定 `Model` / 圖紙名 / `all` |
| 出圖型式 | 無（採圖層原色） | **支援 `plot_style: "monochrome.ctb"`** |
| 紙張 | 固定 | `paper` / `orientation` / `scale` / `fit` / `center` / `window` |
| 中文（紙空間） | 不輸出（只畫模型空間） | **正常輸出** |

> HEADLESS 出圖注意：`cadcraft-cli convert ... .pdf` 走模型空間、採圖層原色（非 monochrome），
> 中文若在紙空間則不會出現在模型空間輸出。需要「A3 橫式＋monochrome CTB＋紙空間中文」時，
> 改走 OpenCADStudio `/api/v1/plot`（見 §12），或維持 `tools/acad/acc.py::publish()`。

## 6. 指令廣度

| 項目 | OpenCADStudio | cadcraft-cli |
|---|---|---|
| 可用命令數 | 未提供 `commands` 列舉；release notes 覆蓋完整 DIM 家族、MLEADER、LAYWALK、LAYISO、表格、約束、`ARRAYPATH` | **431 條**（`cadcraft-cli commands` 實測 JSON 陣列長度） |
| 3D | 實體基本體、擠出、迴轉、掃掠、放樣、布林、ACIS 細分 | 弱（3D 相關命令僅 5 條） |
| 標註 | `DIM*` 家族齊備（OVERRIDE/DISASSOCIATE/REASSOCIATE/BREAK/INSPECT…） | 有 DIM 但無此深度 |

## 7. AI 介面（MCP）

| 項目 | OpenCADStudio `--mcp` | cadcraft-cli `mcp` |
|---|---|---|
| 工具數 | **22** | **12** |
| 工具風格 | 意圖級：`ocs_inspect / ocs_query / ocs_run / ocs_measure / ocs_render / ocs_save_verified / ocs_audit / ocs_capture / ocs_find_text / ocs_select / ocs_sessions` | 低階：`command_line / script / execute / inspect_drawing / query_entities / render / find_text / save` |
| 特色 | `ocs_save_verified`（指定目標版本＋損耗記錄＋重開比對＋SHA-256） | `execute`（JSON 參數直呼任一命令） |
| 架構師指南 | `cad://guides/{workflow,architecture,capture,batch-bindings}` | 無 |

OpenCADStudio 的 MCP 面明顯更「給 agent 用」；cadcraft 的 12 工具勝在底層命令覆蓋面（431 條全可經 `execute` 觸達）。

## 8. 已知限制

**OpenCADStudio**
- `--export` 子命令**不出 PDF/PNG/SVG**（僅 `.dwg/.dxf/.dwt`）。要出 PDF 必須另起 `--http` 服務走 `POST /api/v1/plot`，多一道手續但可完全腳本化。
- **SHX 需手動指定字型夾**（預設不找）：未設定時開 TOMO 圖面會警告 `Missing fonts: CHINA1.SHX, gbenor.shx`。
  設定 `~/.config/OpenCADStudio/settings.json` → `settings.fonts_folder` 指向 `CAD_FONTS/` 後即正常讀取，警告消失。
  鑑別實測見 §11。
- IFCCAD（`.ifccad`）為 alpha，官方明示「後續版本可能無法重開、不保證相容」，僅供測試。
- GPL-3.0：若要把其程式碼併入本專案工具鏈需注意授權傳染性（呼叫外部執行檔不受影響）。

**cadcraft-cli**
- 丟失 `TOMO_PLOTSTYLE`（E18）→ 須跑 `apply_plot_style.py`。
- 不讀 SHX，只吃已安裝 TTF/TTC；中文替代需 `CADCRAFT_FONTALT=msjh.ttc`（只認檔名）。
- 3D 能力薄弱。

## 9. 對本專案的使用情境建議

1. **既有六道閘門產線不變**：`make_sheet.py` → `acc.py`（Linux 後端 cadcraft）→ `check_delivery.py`。不要為了新工具改動已驗證的閘門。
2. **OpenCADStudio 當「人類檢視 + AI 深度編輯」的補充**：
   - 需要肉眼核對 DIM/MLEADER/表格排版時，用 `opencadstudio <圖檔>` 開 GUI。
   - 需要 AI 做「量測、選取、找字、逐實體檢視」時，用 `opencadstudio --mcp` 掛上，取 `ocs_measure / ocs_query / ocs_find_text` 這類意圖工具。
3. **需要保住出圖型式的往返**（例如把公司來圖改樣式後回存），走 OpenCADStudio，可省掉 `apply_plot_style.py` 一道工序。
4. **批次轉檔／出 PDF**（幾十張以上），一律 cadcraft-cli，勿用 OpenCADStudio。
5. **不要**把 OpenCADStudio 放進 `case_package.py` 的三軸自動流程：它無法產 PDF，會使交付清單缺件。

## 10. 重跑驗證的方式

```bash
# 樣本
SRC=out/地籍套繪_豐原區西湳里/豐原區西湳段地籍套繪圖.dxf

# 往返保真度
opencadstudio --export "$SRC" _temp/x_ocs.dwg
opencadstudio --export _temp/x_ocs.dwg _temp/x_ocs_rt.dxf
python3 tools/a3_sheet/check_delivery.py _temp/x_ocs_rt.dxf --scale 1000

cadcraft-cli convert "$SRC" _temp/x_cc.dwg
cadcraft-cli convert _temp/x_cc.dwg _temp/x_cc_rt.dxf
python3 tools/a3_sheet/check_delivery.py _temp/x_cc_rt.dxf --scale 1000   # 預期 E18 失敗
```

## 11. 附錄：OpenCADStudio 的 SHX 字型與 CTB 設定（2026-11-08 補測）

### 11.1 設定位置

`~/.config/OpenCADStudio/settings.json` 的 `settings` 節有三個資料夾鍵，預設皆為 `null`：

| 鍵 | 用途 | 本專案建議值 |
|---|---|---|
| `fonts_folder` | SHX／TTF 字型搜尋夾 | `/home/altos/Civil_Design_WorkBench/CAD_FONTS` |
| `plot_styles_folder` | CTB／STB 出圖型式夾 | `/home/altos/Civil_Design_WorkBench/tools/acad/plot` |
| `support_folder` | 支援檔案夾 | 未設（維持 `null`） |

設定後無須重啟，下次啟動即生效。

### 11.2 鑑別實測（證明是真的讀到字型，不是抑制警告）

用同一份含 TOMO（`gbenor.shx` + `CHINA1.SHX`）的 DXF，只改 `fonts_folder`：

| `fonts_folder` | 開啟時輸出 |
|---|---|
| `null` | `*警告*  Missing fonts: CHINA1.SHX, gbenor.shx` |
| 空目錄 | `*警告*  Missing fonts: CHINA1.SHX, gbenor.shx` |
| 只放 `gbenor.shx` | `*警告*  Missing fonts: CHINA1.SHX` ← **只缺缺的那一個** |
| `CAD_FONTS/`（兩檔齊備） | 無警告 |

第三列是關鍵：只補 `gbenor.shx` 時警告只剩 `CHINA1.SHX`，證明程式是逐檔在該目錄中查找，而非「有設定就閉嘴」。

### 11.3 備份

改設定前已整檔備份：`/home/altos/OpenCADStudio-settings-backup-20261108-094614.json`

還原方式：
```bash
cp /home/altos/OpenCADStudio-settings-backup-20261108-094614.json \
   ~/.config/OpenCADStudio/settings.json
```

### 11.4 與 cadcraft-cli 的差異

cadcraft-cli 沒有等價的「字型夾」設定，只能用環境變數 `CADCRAFT_FONTALT=msjh.ttc` 指定**單一替代字型檔名**，且只吃已安裝的 TTF/TTC、不讀 SHX。
因此在「TOMO 圖面的正確字形呈現」這件事上，OpenCADStudio 設定好 `fonts_folder` 後反而更完整。

## 12. OpenCADStudio 無人值守出 PDF（2026-11-08 補測，推翻初版結論）

### 12.1 結論

**OpenCADStudio 可以無介面輸出 PDF**，走 REST 端點 `POST /api/v1/plot`，由 `--http PORT` 啟動的服務提供。

初版說「不能轉 PDF」只對 `--export` 子命令成立：

```
$ opencadstudio --export in.dxf out.pdf
export: cannot write out.pdf: unsupported output format .pdf; supported formats: .dwg, .dxf, .dwt
```

GUI 端的 `Ctrl+P`（= `PLOT` 指令）本來就有「Export PDF / Export SVG」，對應的程式化介面就是這個 REST 端點。

### 12.2 啟動與認證

```bash
export OCS_API_TOKEN="$(openssl rand -hex 24)"     # 或讓程式自己印在啟動訊息中
opencadstudio --http 4271 --new &
# 服務約 0.53 s 就緒（實測）
curl -s http://127.0.0.1:4271/api/v1/ready \
  -H "Authorization: Bearer $OCS_API_TOKEN"
```

### 12.3 出圖請求

```bash
curl -s -X POST http://127.0.0.1:4271/api/v1/plot \
  -H "Authorization: Bearer $OCS_API_TOKEN" \
  -H 'content-type: application/json' \
  -d '{
        "path":       "/abs/out/圖名.pdf",
        "layout":     "全區工程位置圖",
        "plot_style": "monochrome.ctb"
      }'
```

| 參數 | 值 | 說明 |
|---|---|---|
| `path` | 絕對路徑 | 必填，未給會回 `400 Missing path` |
| `layout` | `Model` / 圖紙名 / `all` | `all` 會逐圖紙輸出 |
| `plot_style` | `monochrome.ctb` | 出圖型式，支援 CTB |
| `paper` / `orientation` / `scale` / `fit` / `center` / `window` | — | 紙張與縮放控制 |
| `per_page` | `true` | 搭配 `layout: "all"`，每張圖紙各寫一個 PDF，回傳 `result.files` |

回應範例：
```json
{"ok":true,"result":{"page_sizes":[[420.0,297.0]],"pages":1,"path":"…/圖名.pdf"},"status":"waiting_input"}
```

> `status: "waiting_input"` 是「指令列回到待命」的正常狀態，**不是失敗**；判成功看 `ok: true` 與 `result.pages`。

### 12.4 實測結果（真實專案 A3 案圖）

樣本：`out/地籍套繪_豐原區西湳里/豐原區西湳段地籍套繪圖.dxf`

| 步驟 | 端點 | 耗時 |
|---|---|---|
| 開檔 | `POST /api/v1/open` | 0.48 s |
| 存 DWG | `POST /api/v1/save` | 0.01 s |
| 出 PDF | `POST /api/v1/plot` | 0.22 s |

產出：`Pages: 2`、`Page size: 1191 x 842 pts (A3)`、910 KB。
目視檢查確認：**A3 橫式、全黑白（monochrome.ctb 生效）、中文字形正確（TOMO/SHX）、標題欄與圖例完整**。

### 12.5 兩個實務注意事項

1. **別用 `layout: "all"`**：專案圖面常有多個圖紙，其中 `Layout1` 是空的，`all` 會多出一頁空白。要用**圖紙名稱**（如 `"全區工程位置圖"`）或 `"Model"`。
2. **`--http` 只綁本機**，且必須帶 token；token 可由 `OCS_API_TOKEN` 環境變數預先指定，避免每次解析啟動訊息。

### 12.6 修正後的工具分工

| 需求 | 用哪套 |
|---|---|
| 帶 CTB、A3 橫式、紙空間中文的 PDF | **OpenCADStudio `/api/v1/plot`** |
| 快速批次 DXF→DWG | **cadcraft-cli convert** |
| PNG / SVG | **cadcraft-cli convert** |
| 保住 `TOMO_PLOTSTYLE` | **OpenCADStudio** |

## 13. 預設後端切換為 OpenCADStudio（2026-11-10）

### 13.1 起因與結論

重編譯版 OpenCADStudio 已能正確解析 TOMO 的 SHX 中文大字體；`tools/acad/acc.py` 預設後端由 `cadcraft` 切為 `ocs`。
`CIVIL_AI_CAD_BACKEND=cadcraft` 保留為退路（有 `accoreconsole` 用它，否則 `cadcraft-cli`）。

| 產線環節 | 新預設 | 備註 |
|---|---|---|
| DWT／DWG→DXF、DXF→DWG | OCS（`acc.to_dxf`／`acc.to_dwg`） | `make_a3_sheet.py`、`fix_tomo_font.py` 原本直接呼叫 `cadcraft-cli`，已改走 `acc.py` |
| DXF→DWG＋PDF 出圖 | OCS `/api/v1/plot` | `plot_style` 傳專案 CTB **絕對路徑** |
| PNG／SVG 預覽 | 不變（`cadcraft-cli convert`） | `acc.py` 不涵蓋；OCS 的 PNG 需經 `ocs_render`（MCP） |

### 13.2 實測依據（Windows，同一份排水溝 D-02 DXF）

| 版本 | 中文 | 英數字 | PDF |
|---|---|---|---|
| OCS 2026.44（舊） | ✓ | 偏大、字距鬆（高度與中文不一致） | 369 KB |
| OCS 2026.45.1（重編譯） | ✓ | 與中文高度一致 | 378 KB |
| `accoreconsole`（本機） | **✗ 完全沒有文字**（PDF 5 KB，SHX 找不到） | — | 5 KB |

> **誠實註記**：舊版 2026.44 在這台 Windows（`fonts_folder` 已設定）中文也正常，所以 **2026-11-08 的亂碼很可能是 Linux 環境
> （或當時 `fonts_folder` 未設）造成，而不是新舊版差異**；新版可確認的改善只有英數字大小。Linux／macOS 尚未以新版重測。

其餘驗證：`check_delivery.py` E1~E18 對 OCS 出的 D-02 為 0 錯誤，DWG→DXF 往返後 `TOMO_PLOTSTYLE`（E18）保留；
`fix_tomo_font.py` 對 DWG 副本 `--apply` 後回讀 TOMO＝`gbenor.shx + CHINESE.SHX`、實體完整；全案回歸 11 案基準全部相符。

### 13.3 切換時抓到的三個坑（皆已在 `acc.py` 修正）

1. **CTB 只給名稱會用到別的檔**：OCS 把 `"monochrome.ctb"` 解析成 `%APPDATA%\OpenCADStudio\plotstyles\monochrome.ctb`
   （檔頭格式與專案的不同，`ctb.py` 讀不開），線寬變 0.09／0.30 mm；`check_delivery.py` 只檢查 DXF 內記錄的名稱，**抓不到**。
   改傳 `tools/acad/plot/monochrome.ctb` 絕對路徑後為 0.10／0.15／0.20／0.35 mm。
2. **殘留檔**：被強殺的服務留 `.<檔名>.ocs.lock`；覆寫既有 DWG 時 OCS 自留 `<檔名>.bak`。`acc.py` 清「本次才出現」的殘留。
3. **解析器抓到舊版**：`~/.local/bin/opencadstudio.cmd` 指向 `--install` 下載的舊 portable；MSI 安裝版不登錄安裝路徑。
   `opencadstudio_exe()` 改以環境變數根目錄＋模糊名稱比對尋找，不寫死路徑（見 `docs/環境需求與自動配置.md` §8.7）。

### 13.4 仍須注意

- **Linux／macOS 換新版前先重測**：出圖後把 PDF 轉 PNG 目視中文；`acc.py` 會在 OCS 回報 `missing_fonts` 時於 stderr 警告。
- OCS 設定 `plot_styles_folder` 目前可維持 `null`（已由絕對路徑繞過）；`fonts_folder` 仍必須指向 `CAD_FONTS/`。
- 啟動「MCP 控制」選項與本產線無關：產線用的是獨立的 `--http` 服務，App 不必開著。

