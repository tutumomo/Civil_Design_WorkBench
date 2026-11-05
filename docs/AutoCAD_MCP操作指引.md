# AutoCAD MCP（autocad-mcp-pro 1.6.0）操作指引（純 DXF 模式實測版）

> 實測日期：2026-10-28｜安裝：`<使用者家目錄>\mcp\autocad-mcp-pro\.venv`｜測試成果：`<專案根目錄>\_autocad_mcp測試\`（遷移前舊路徑的產物，現已不存在）

## 1. 設定（已套用）

| 用戶端 | 設定檔 | 後端 | 允許資料夾 |
|---|---|---|---|
| Claude Code（本工作區） | `.mcp.json` | `ezdxf`（純 DXF，不碰 AutoCAD 視窗） | `<專案根目錄>` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json`（改前備份 `.bak_20261028105125`） | 由 `com` 改 `ezdxf` | 由 `D:\公司案件` 改 `<專案根目錄>`（遷移前） |
| Codex | `~\.codex\config.toml`（另一份安裝 `~\.agents\mcp\autocad-mcp-pro`，autocad-mcp-pro **1.7.0**） | 由 `com` 改 `ezdxf`（2026-10-28 改；改前備份 `config.toml.bak_202610281145`） | `<專案根目錄>` |

- Claude Code 首次在本工作區開新對話會詢問是否啟用 `.mcp.json` 的 `autocad`，同意即可；工具以 `mcp__autocad__*` 出現（242 個，延遲載入）。
- **禁止**改回 `com` 後端：會操作共用 GUI AutoCAD，違反 AGENTS.md §3。
- **Codex 端需重啟 Codex** 才會載入新的 `[mcp_servers.autocad.env]`。

## 2. 實測結果

| 項目 | 結果 |
|---|---|
| 量測（`analysis_measure_entity`／`analysis_measure_area`） | 建物 120、64 m²、含中庭 HATCH 146 m²（扣洞）、座標面積 120 m² **全部正確**；ARC 不能量面積（屬正常） |
| 繪圖（圖層、聚合線、直線、文字、線性標註） | 成功；DXF `audit 0`、`$INSUNITS=6` |
| 路徑限制 | 寫入 `D:\公司案件\` **被拒** ✔ |
| AutoCAD 相容 | MCP 產出 DXF → `acc.py publish(pdf=False)` 轉 DWG → 回讀，圖元完整 ✔ |
| `drawing_export_dwg` | ✘ 需 ODA File Converter（未安裝）→ 一律改用 `acc.py` |
| `drawing_export_pdf` | ✔（matplotlib 渲染，僅供預覽；交件 PDF 仍用 `acc.py`） |
| `drawing_critique` | 依 ISO 機械製圖規則，對本工作區 A3 只報 1 項（標註字高 2 mm）；**不能取代 `check_delivery.py`** |

### 2.1 Codex 端專屬實測（1.7.0，`~\.agents\mcp\autocad-mcp-pro`）

| 項目 | 結果 |
|---|---|
| `system_status.active_backend` | `ezdxf` ✔（`system_about` 顯示 `active_backend: ezdxf`） |
| 工具數 | 243 個（`TOOL_PROFILE=full` + `TOOL_PACKS=all`） |
| 工作區內寫檔 | `<專案根目錄>\_codex_mcp測試\codex_ezdxf_probe.dxf` 建立成功（18,637 B；遷移前舊路徑的產物，現已不存在） |
| 圖面內容 | `drawing_audit` 0 錯誤；ezdxf 回讀：`$INSUNITS=6`、圖層 `10_道路邊線_現況`、LINE 長度 10.0 m ✔ |
| **越權寫入 `D:\公司案件\`** | `drawing_save_as` 與 `drawing_open` **皆被拒**：`Path rejected: ... is not inside any allowed directory. Allowed directories: <專案根目錄>`（遷移前實測原文） ✔；該處未產生任何檔案 |

- 重現腳本：`<使用者家目錄>\.agents\mcp\autocad-mcp-pro\codex_ezdxf_test.py`（以 `mcp` stdio client 帶上述 env 直啟 `autocad-mcp.exe`）。

## 3. 陷阱

1. **`drawing_understand` 單位推論不適用土木圖**：以門扇寬等建築特徵推單位，把 R20 m 圓弧誤認門扇而判為英寸（`agree:false`）。一律以 DXF `$INSUNITS=6` 為準，忽略其推論。
2. **無法建立 TOMO 樣式**：`textstyle_create` 沒有 bigfont 參數；新圖 Standard 為 `arial.ttf`。文字需符合規範時，存檔後用 ezdxf 補：`st=doc.styles.add("TOMO", font="gbenor.shx"); st.dxf.bigfont="CHINA1.SHX"` 並把文字改用 TOMO。
3. **標註預設在圖層 0、字高 2.5（dimtxt 2）**：須依本項目出圖規定（本文 3／附註 4／標題 5 mm）調整 dimstyle。
4. `acc.py publish(pdf=True)` 的出圖腳本只適用「圖紙配置」；只有模型空間的圖會卡提示逾時 → 用 `pdf=False` 只轉 DWG。

## 4. 定位

- **適合**：讀別人的 DWG/DXF 做量測、統計、圖層盤點；快速補畫標註、表格、圖塊；修改既有 DXF。
- **不取代**：底圖產製（`tools\site_basemap`）、A3 出圖（`tools\a3_sheet\make_sheet.py`）、交件 DWG（`acc.py`）、交件檢核（`check_delivery.py`）。
