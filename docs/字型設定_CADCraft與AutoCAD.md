# 字型設定：CADCraft 與 AutoCAD 是兩套完全不同的機制

> 實測日期 **2026-11-03**｜環境：Windows、`cadcraft-cli 0.17.0 (f389d6a)`、AutoCAD 2022 `accoreconsole`。
> 本文結論全部來自本機實跑（PNG 雜湊比對 ＋ 目視），不是讀設定檔推論。凡標「實測」的都有檔案可回溯。

## 0. 一句話版本

`CAD_FONTS\` 與 `C:\CadFont[S]\` 裡的都是 **SHX**，那是 **AutoCAD／accoreconsole** 在用的；
**CADCraft 完全不讀 SHX**，它只吃 TrueType/OpenType（`.ttf / .otf / .ttc`），而且只吃**已安裝到系統字型夾**的。
CADCraft 確實有兩支字型環境變數，但**沒有任何變數可以把「資料夾」或「檔案路徑」餵給它**。

## 1. 三種情境，照抄就好

| 你要做的事 | 正確做法 | 指令 |
|---|---|---|
| 出正式 A3 圖（DWG＋PDF），`TOMO` 樣式中文字要對 | 讓 `gbenor.shx`／`CHINESE.SHX` 進 AutoCAD 自己的字型夾 | `python tools/install_cad_fonts.py --apply`（需系統管理員） |
| 用 CADCraft 開我們產的 DXF 校對（`TOMO` 是 SHX 樣式） | 設 `CADCRAFT_FONTALT` 把 SHX 樣式字換成已安裝的 TTF | `$env:CADCRAFT_FONTALT = "msjh.ttc"` |
| 想用 `C:\Fonts\` 或 `CAD_FONTS\` 裡的 `.ttf/.ttc` | **先安裝到系統字型夾**，再重新啟動 CADCraft | 雙擊安裝，或複製到 `C:\Windows\Fonts`（需管理員） |

## 2. 機制：為什麼「設環境變數指向字型夾」行不通

DXF 只存**檔名字串**（`font="gbenor.shx"`、`bigfont="CHINESE.SHX"`），**不內嵌字型**。所以「字型在哪」完全由開圖的程式自己決定，兩套程式的答案不同：

| | AutoCAD／`accoreconsole` | CADCraft |
|---|---|---|
| 讀 SHX？ | 讀，這是它的原生格式 | **不讀**（README 明載「SHX fonts … aren't read yet」） |
| 找字型的範圍 | 安裝目錄 `…\AutoCAD 2022\Fonts\` ＋ 支援搜尋路徑 ＋ 圖面所在資料夾 | 開機掃一次系統字型資料庫：`C:\Windows\Fonts` ＋ 使用者字型夾 |
| 沒有 SHX 字型時 | 靜默替換成別的 bigfont（不警告） | 用自帶的單線字（stroke font）畫英數；缺的中文字再從「有該字的已安裝字型」補 |
| 可用環境變數 | `ACAD`（支援路徑）、`FONTALT`／`FONTMAP` 等 | `CADCRAFT_FONTALT`、`CADCRAFT_FONTFALLBACK` |

所以「讓 CADCraft 抓 `C:\CadFont[S]`」這件事在架構上就不成立——**它根本不解譯 SHX**；而「路徑」也不是它的輸入格式。

## 3. 實測證據

測試圖：一張 `TOMO`（`gbenor.shx` ＋ `bigfont=CHINESE.SHX`）與一行 TTF（`msjh.ttc`）的兩行中英文字，換不同變數各輸出一次 PNG 比對雜湊。
**雜湊相同＝該變數沒生效；不同＝生效。**

| # | 設定 | PNG 大小 | 雜湊前 16 碼 | 判讀 |
|---|---|---|---|---|
| A | 不設任何變數（基準） | 54,655 | `3CF7154D95140818` | 中文**正常**（系統自動補到微軟正黑體），英數為單線字 |
| B | `FONTFALLBACK=msjh.ttc` | 54,655 | `3CF7154D95140818` | 與 A **完全相同** → 因為預設本來就挑到 JhengHei，等於沒差 |
| C | `FONTALT=msjh.ttc` | 67,275 | `9042EC35B0E35EBE` | **生效**：整段換成正黑體 |
| D | `FONTFALLBACK=mingliu.ttc` | 58,752 | `1C0EC37718588FD3` | **生效**：中文字形變細明體 |
| E | `FONTFALLBACK=kaiu.ttf` | 62,036 | `02FB4E123E6FBB29` | **生效**：標楷體 |
| F | `FONTFALLBACK=NoSuchFontXYZ.ttf` | 54,655 | `3CF7154D95140818` | 找不到字型時**靜默退回預設**，不報錯 |
| G | `FONTFALLBACK=PMingLiU`（家族名稱） | 54,655 | `3CF7154D95140818` | **家族名稱無效**，只認**檔名** |
| H | `FONTFALLBACK=C:\Fonts\古印體.ttc`（完整路徑） | 54,655 | `3CF7154D95140818` | **完整路徑無效** |
| I | `FONTALT=C:\Fonts\古印體.ttc`（完整路徑） | 54,655 | `3CF7154D95140818` | **完整路徑無效** |
| J | `FONTALT=C:\CadFont[S]\CHINESE.SHX` | 54,655 | `3CF7154D95140818` | **SHX 靜默忽略** |

真實案件圖再驗一次（`out\擋土牆3m重力式_北屯民政里\…_斷面圖_S-01.dxf`，`TOMO` 樣式）：

| 設定 | PNG 大小 | 差異 |
|---|---|---|
| 不設 | 255,087 | 圈標字母為單線字 |
| `FONTALT=msjh.ttc` | 257,685 | 圈標字母成正黑體，其餘完全相同 |

→ **實務結論：不設也能看、也看得懂**（中文本來就會自動補字）；`FONTALT` 只是把英數字形換成正式字體，屬於「校對時比較順眼」的加分項，不是必要條件。

## 4. 建議設定

```powershell
# 用 CADCraft 開 TOMO/SHX 圖面時，把 SHX 樣式字換成已安裝的 TrueType
$env:CADCRAFT_FONTALT = "msjh.ttc"          # 微軟正黑體，Windows 內建

# 只有「某個字型缺字」時才輪到它；預設就會挑到微軟正黑體，通常不必設
$env:CADCRAFT_FONTFALLBACK = "msjh.ttc"     # 想換字形就改 mingliu.ttc（明體）／kaiu.ttf（標楷體）
```

- **一律用檔名**（`msjh.ttc`）。家族名稱（`PMingLiU`）與完整路徑**實測無效**。
- **永久生效**（使用者層級，開新視窗才生效）：`setx CADCRAFT_FONTALT msjh.ttc`
- **清除**：設為空字串或 `.`
- 桌面版 CADCraft 同樣讀這兩個變數（README：可用 `SETVAR` 或在環境變數設定）；更換字型後要**重新啟動** CADCraft，字型資料夾只在啟動時掃一次。
- 多個候選用逗號分隔、**前面優先**：`Noto Sans CJK TC, msjh.ttc`

## 5. 明確行不通的做法（別再試）

| 想法 | 實測結果 |
|---|---|
| 設環境變數指向一個「字型資料夾」 | 不存在這種變數，CADCraft 沒有字型搜尋路徑設定 |
| `CADCRAFT_FONTALT=C:\Fonts\xxx.ttc` 用完整路徑 | 無效（H／I） |
| 指 `.shx` 檔（含 `C:\CadFont[S]\CHINESE.SHX`） | 靜默忽略（J） |
| 讓 CADCraft 用到 `C:\CadFont[S]` 的 140 個 SHX | 不可能，SHX 未實作 |
| 用 `C:\Fonts\` 的 20＋個中文藝術字 | 未安裝＝看不到；**先安裝**才可能 |
| 用家族名稱（`PMingLiU`、`Microsoft JhengHei`） | 實測無效（G），改檔名 |

**唯一能讓新字型被 CADCraft 看到的方法**：安裝到 `C:\Windows\Fonts`（需管理員）或使用者字型夾，再重啟 CADCraft。

## 6. 本機字型資產現況（2026-11-03 盤點）

| 位置 | 內容 | AutoCAD 看得到 | CADCraft 看得到 |
|---|---|---|---|
| `D:\Civil_Design_WorkBench\CAD_FONTS\` | **2 檔**：`gbenor.shx` 5,186 B、`CHINESE.SHX` 927,309 B | 否（要複製到 AutoCAD Fonts） | 否 |
| `C:\CadFont[S]\` | **299 檔，其中 140 個 `.SHX`**（`CHINA1/2/…`、`chineset.shx`、`gbcbig.shx`、`bigfont.shx`、`gbeitc.shx`…）＋1 個 `.TTC` | 否（除非加進支援路徑） | 否 |
| `C:\Fonts\` | 20＋個中文 TTF/TTC（古印體、勘亭流、揮灑體…） | 否（未安裝） | 否（未安裝） |
| `C:\Windows\Fonts\` | `msjh.ttc`（微軟正黑）、`msyh.ttc`、`simsun.ttc`、`mingliu.ttc`、`kaiu.ttf` 等 | 是 | 是 |
| `…\AutoCAD 2022\Fonts\` | **74 個 SHX**；`gbenor.shx` **有**、`chineset.shx`／`gbcbig.shx` **有**、**`CHINESE.SHX` 缺** | 是 | 否 |

### ⚠ `CHINESE.SHX` 沒裝進 AutoCAD，但出圖中文仍正常（實測）

`out\擋土牆3m重力式_北屯民政里\…_斷面圖_S-01.pdf` 的 `TOMO` 中文**顯示正常** → AutoCAD 有自動替換成功，**不是壞圖**。
但替換是**靜默的**（不警告），且替換字型的字寬未必等於 `CHINESE.SHX`（本專案按 1.2h 估算中文字寬，見 `check_delivery.py` 的 E3 說明）。
**建議**：跑 `python tools/install_cad_fonts.py --apply`（會寫入 `C:\Program Files\Autodesk\AutoCAD 2022\Fonts`，需系統管理員權限 → 動前先取得使用者同意），讓實際字型與規範一致。

## 7. 驗收方法：雜湊比對法

懷疑「環境變數到底有沒有生效」時，不要靠眼睛，用雜湊：

```powershell
$env:PATH = "C:\Program\ArtCraft\CADCraft;" + $env:PATH
Remove-Item Env:CADCRAFT_FONTALT -ErrorAction SilentlyContinue
& cadcraft-cli convert in.dxf base.png
$env:CADCRAFT_FONTALT = "msjh.ttc"
& cadcraft-cli convert in.dxf alt.png
Get-FileHash base.png, alt.png -Algorithm SHA256 | Select-Object Hash
```

- 兩個雜湊**相同** → 變數沒生效（字型沒被找到，或本來就是同一個字型）。
- 兩個雜湊**不同** → 生效。

## 8. 踩到的兩個坑

1. **`C:\CadFont[S]` 用 PowerShell 檢查會誤判「不存在」。** `[S]` 在 PowerShell 路徑中是**萬用字元**（字元集），`Test-Path "C:\CadFont[S]"` 實際去找 `C:\CadFontS`。
   路徑含 `[ ]` 一律用 `-LiteralPath`：
   ```powershell
   Test-Path -LiteralPath "C:\CadFont[S]"
   Get-ChildItem -LiteralPath "C:\CadFont[S]" -Filter *.shx
   ```
   這與「Blender 是 Microsoft Store 版、`Test-Path` 找不到就誤判未安裝」屬同一類**假陰性**：*「檔案不存在」≠「沒安裝」*。
2. **`acc.py publish` 遇到 `accoreconsole` 停在提示時會一起掛住。** 本次實測（`_temp\font_probe`，一個極簡 DXF）掛超過 10 分鐘未返回，`acc.py` 內建的 240 秒逾時沒有把它收掉（疑為子行程繼承管線導致 `communicate()` 阻塞，待查），最後手動 `Stop-Process`。
   **對策**：開圖前確認圖紙名／配置存在；卡住就查 `%USERPROFILE%\ArtCraft-Work\acc_tmp\<hash>\acc_log.txt` 尾段並清掉 `accoreconsole` 行程，不要一直重跑。

## 9. 智能體檢查清單

- [ ] 要「出正式圖」→ 走 `acc.py`／`make_sheet.py --publish`（AutoCAD，SHX）；**不要**期待 CADCraft 出正式 DWG。
- [ ] 要「用 CADCraft 校對」→ 先設 `CADCRAFT_FONTALT=msjh.ttc`，否則英數會是單線字（圖仍可讀）。
- [ ] 要「新增字型」→ 先安裝到系統字型夾、重啟 CADCraft；**不要**想用環境變數指資料夾或路徑。
- [ ] 看到中文變方框 → 先確認是 AutoCAD 端（缺 SHX）還是 CADCraft 端（缺已安裝 CJK 字型），兩者解法不同。
- [ ] 檢查含 `[ ]` 的路徑 → 一律 `-LiteralPath`。
- [ ] 改過字型相關設定後 → 用第 7 節雜湊法驗證，不要憑印象。

## 參考

- CADCraft 官方 README「Fonts」章節（`CADCRAFT_FONTALT`／`CADCRAFT_FONTFALLBACK`、SHX 尚未支援）：<https://github.com/storytold/cadcraft>
- `tools\project_paths.py`：`cad_fonts_dir()`／`cad_font()` —— 解析順序 `CAD_FONTS` 環境變數 → 專案 `CAD_FONTS/` → AutoCAD Fonts → `C:\CadFont[S]`
- `tools\install_cad_fonts.py`：把 `gbenor.shx`／`CHINESE.SHX` 複製到 AutoCAD 字型目錄（`--apply` 才實際寫入）
- `tools\a3_sheet\check_delivery.py` E3：`TOMO` 樣式與中文字寬 1.2h 的估算基礎
