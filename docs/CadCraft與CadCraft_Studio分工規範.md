# CadCraft 與 CadCraft Studio 分工規範（AI 智能體自動感知指引）

> **建立日期**：2026-11-06｜**適用對象**：全專案智能體（Claude、Gemini/Antigravity、Codex、OpenCode 等）
> **核心原則**：**以 AI 智能體代替人工操作為前提，嚴格區隔「後台自動化代工引擎」與「前台人類可視化驗收看板」。**

---

## 1. 命名重疊與背景真相（Two CadCrafts Collision）

本機環境中存在兩套包含「CadCraft」名稱的獨立軟體體系，智能體在規劃或執行任務時**嚴禁混淆**：

| 比較項目 | **ArtCraft 系列的 CADCraft** | **CadCraft Studio 套件** |
| :--- | :--- | :--- |
| **安裝路徑** | `C:\Program\ArtCraft\CADCraft\` | `C:\Program\CadCraft Studio\` |
| **軟體家族** | **ArtCraft Launcher**（內含 16 套 App：CADCraft, GridCraft, PdfCraft...） | **CadCraft Studio Suite**（內含 8 套工程 App：CadCraft, CivilCraft, TakeoffCraft...） |
| **技術架構** | **原生 64 位元 C++/Rust/Win32** | **WebView2 殼層 ＋ WebAssembly/Three.js（Web 技術）** |
| **可執行檔** | • `cadcraft-cli.exe`（無介面命令列 / MCP 伺服器）<br>• `cadcraft.exe`（原生桌面視窗） | • `CadCraft Studio.exe`（GUI 主視窗，帶 `--app=<name>` 參數） |
| **無介面 CLI** | **完整支援**（`info`, `convert`, `run`, `mcp`, `roundtrip`） | **無獨立 CLI**（必須在視窗運行狀態下透過本機 HTTP/MCP 遙控） |
| **AI 代工角色** | **後台主力工作馬（Workhorse）** | **前台人類驗收看板（Human Review Hub）** |

---

## 2. 智能體分工鐵則（Execution Rules）

### 鐵則一：後台全自動化作業 ➔ 唯一指定 `cadcraft-cli.exe`（ArtCraft）
凡是涉及以下情境，智能體**一律使用 ArtCraft 的 `cadcraft-cli.exe`**，嚴禁嘗試呼叫 CadCraft Studio：
1. **DWG / DXF / PDF / SVG 格式互轉**（例如將 ezdxf 產生的線稿轉為原生 2018 DWG 或渲染 PDF）。
2. **無介面（Headless）批次作業**：在背景幾百毫秒內靜默完成，不彈出任何視窗、不搶奪使用者滑鼠焦點。
3. **圖面幾何與結構資訊萃取**：透過 `cadcraft-cli info <drawing>` 輸出結構化 JSON。
4. **標準 MCP 伺服器直連**：以 `cadcraft-cli mcp` 作為底層繪圖工具伺服器。

> **程式路徑解析規範**：
> 必須透過 `tools/project_paths.py` 的 `artcraft_cli("CADCraft")` 動態取得路徑，禁止寫死絕對路徑。

---

### 鐵則二：前台人類驗收與互動模組 ➔ 使用 `CadCraft Studio`
CadCraft Studio 是為「人類工程師在螢幕前檢視、審查與手動微調」而設計的圖形套件：
1. **人類驗收開圖（Human-in-the-Loop）**：當智能體完成設計圖（`.dwg` 或 `.dxf`）並通過 E1~E18 品管後，若需提醒使用者在螢幕上肉眼檢視，可呼叫或提示啟動：
   ```powershell
   & "C:\Program\CadCraft Studio\CadCraft Studio.exe" --app=cadcraft "out\<案名>\<檔案>.dwg"
   ```
2. **特定工程專業模組**：
   - **CivilCraft**：地形面三角網（TIN）、土方挖填平衡計算、縱斷面出圖（操作詳見 `docs/CadCraft_Studio操作指引.md`）。
   - **TakeoffCraft**：視覺化圖面算量、工程項目計價（需使用者在 GUI 開啟連線並提供 Token）。
   - **MarkupCraft**：圖面紅線審查與審圖批註。

---

## 3. 常見反模式與禁忌（Anti-Patterns）

* ❌ **禁忌 1**：試圖用 UI 自動化或腳本去「點擊」CadCraft Studio 來進行背景轉檔或出圖（這會導致不可預期的視窗延遲、焦點喪失與渲染失敗）。
* ❌ **禁忌 2**：以為 `cadcraft-cli` 可以叫出 CivilCraft 或 TakeoffCraft 的特有功能（那是 Studio Web Suite 專屬模組，CLI 本體只專注於核心 2D/3D CAD 圖面操作）。
* ❌ **禁忌 3**：在無人值守的自動化排程中啟動 `CadCraft Studio.exe`（無介面環境中 Studio 無法自動完成閉環）。

---

## 4. 程式碼整合速查

```python
from project_paths import artcraft_cli, cadcraft_studio_exe

# 1. 後台自動化代工（轉檔、繪圖、檢驗）
cli = artcraft_cli("CADCraft")  # 回傳: C:\Program\ArtCraft\CADCraft\cadcraft-cli.exe
# 範例：轉檔
# subprocess.run([cli, "convert", "input.dxf", "output.dwg"], check=True)

# 2. 人類視覺化檢視（啟動 Studio GUI 視窗）
studio = cadcraft_studio_exe()  # 回傳: C:\Program\CadCraft Studio\CadCraft Studio.exe
# 範例：為使用者開圖檢視
# subprocess.Popen([studio, "--app=cadcraft", "out/案名/平面圖.dwg"])
```
