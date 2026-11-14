#!/usr/bin/env python3
"""由執行中的 Open CalcSheet Studio（OCSS）即時抓工具 registry，重生 docs/OpenCalcSheetStudio_工具清單.md。

用法（OCSS 桌面程式須開著、已啟用 API）::

    python tools/crosscheck/ocss_tools_doc.py            # 重寫文件
    python tools/crosscheck/ocss_tools_doc.py --check    # 只比對：與現況不同回傳 1（不寫檔）

只輸出工具名／說明／參數／路由，不含 token。OCSS 升版後工具可能增減，重跑本腳本即可更新清單；
中文「用途」字典在本檔 PURPOSE，新工具沒有條目時會標「（待補）」。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from ocss_client import OcssClient, OcssError  # noqa: E402
from project_paths import ROOT as PROJECT_ROOT  # noqa: E402

OUT = PROJECT_ROOT / "docs" / "OpenCalcSheetStudio_工具清單.md"

# 分組（顯示順序）：組名 → 工具名
GROUPS: list[tuple[str, list[str]]] = [
    ("應用與專案檔", ["app_info", "project_get", "project_new", "project_open", "project_save",
                  "project_save_as", "recent_files", "project_set_name", "project_set_data",
                  "project_set_visibility"]),
    ("結構報告書", ["report_get", "report_set"]),
    ("編輯歷史", ["undo", "redo"]),
    ("模組與工作表", ["modules_list", "sheets_list", "sheet_add", "sheet_add_pdf", "sheet_get",
                 "sheet_set_source", "sheet_set_input", "sheet_set_pdf", "sheet_rename",
                 "sheet_duplicate", "sheet_move", "sheet_remove", "sheet_select"]),
    ("工作表內容取代（2026.45.2-tw.5 新增）",
     ["sheet_set_markdown", "sheet_set_graph", "sheet_set_drawing",
      "sheet_set_spreadsheet", "sheet_set_jupyter", "sheet_set_marimo"]),
    ("計算", ["sheet_evaluate", "calc_evaluate", "sheet_insert_formula"]),
    ("批次與背景工作（不動專案，2026.46.2 新增）",
     ["calc_evaluate_batch", "job_start", "job_status", "job_cancel"]),
    ("拋棄式工作階段（不動使用者專案，2026.46.2 新增）", ["session_new", "session_close"]),
    ("工作表讀取、執行與繪圖（2026.46.2 新增）",
     ["sheet_read", "sheet_run", "sheet_reset_input", "sheet_drawing", "module_schema"]),
    ("模組庫與公式庫", ["library_list", "library_install", "library_remove", "formulas_list",
                   "formula_get"]),
    ("匯出與列印", ["ifc_get", "export_ifc", "export_pdf", "print"]),
    ("檢視與設定", ["view_get", "view_set", "settings_get", "settings_set"]),
]

# 中文用途（一行）。⚠ 為本專案實測踩過的坑，細節見整合文件 §7 與經驗索引 EXP-J*。
PURPOSE: dict[str, str] = {
    "app_info": "App 名稱／版本、MCP 與 REST 位址、OpenAPI 文件位置、是否唯讀。連線冒煙測試用",
    "project_get": "讀目前專案：名稱、檔案路徑、是否未儲存、專案資料欄位（可加 evaluate）",
    "project_new": "開新空白專案。有未儲存變更時回 CONFLICT，除非 force=true",
    "project_open": "由路徑開啟 .ifccalculation（或舊 .ifc-calculation／.cpd）。同樣受未儲存保護",
    "project_save": "覆存專案檔；專案還沒有檔案時需給 path",
    "project_save_as": "另存新檔（自動補 .ifccalculation），專案改指向新檔",
    "recent_files": "最近開啟／儲存的專案清單（File > Recent）",
    "project_set_name": "設定專案名稱（檔名與列印標題）",
    "project_set_data": "設定專案資料欄位，套用到所有工作表：tw_klasse 用途別 1-4、tw_terrein 地況 A/B/C、tw_V10 基本風速、tw_SDS／tw_SD1 設計譜加速度、tw_DesignLife、project_nummer 等；只能改既有欄位，任一值無效則全部不寫",
    "project_set_visibility": "顯示／隱藏專案樹中的『專案資料表單』或『報告』",
    "report_get": "讀結構報告書（封面、語言、修訂、章節、假設、荷重、版面），可用 dot path 只讀一部分",
    "report_set": "以 dot path 設報告欄位，例如 belastingen.wind.gebouwhoogte",
    "undo": "復原上一個變更（同 Ctrl+Z，不分是誰改的）",
    "redo": "重做被復原的變更（同 Ctrl+Y）",
    "modules_list": "列出可用 sheet_add 加入的計算模組與資料庫工作表（templateId、name）。台灣模組以 tw- 開頭",
    "sheets_list": "依序列出專案所有工作表（id、name、種類 calculation/pdf/spreadsheet/markdown/graph/drawing/jupyter…），可加 evaluate",
    "sheet_add": "新增計算工作表：用 templateId 套模板，或直接給 source 計算文字。⚠ 會讓專案變『未儲存』且刪回去也不復原",
    "sheet_add_pdf": "新增 PDF 工作表（供應商計算書、FEM 報告等），給 path 或 base64",
    "sheet_get": "讀單一工作表：計算文字 source、輸入欄位（含選單與目前值），可加 evaluate",
    "sheet_set_source": "取代工作表的計算文字；已填輸入值保留。可 undo",
    "sheet_set_input": "設工作表輸入欄位或選單值，單一 name/value 或多個 values",
    "sheet_set_pdf": "替換 PDF 工作表的 PDF 檔（名稱與位置不變）",
    "sheet_set_markdown": "取代 Markdown 工作表的文字（text）；省略的欄位保持原值",
    "sheet_set_graph": "取代工作表整張圖（graph：{versie, nodes, verbindingen}），計算會重跑",
    "sheet_set_drawing": "改繪圖工作表：drawing 取代整張，或只給 paper／orientation",
    "sheet_set_spreadsheet": "以本機檔（path）或 base64 取代試算表工作表的 XLSX 活頁簿",
    "sheet_set_jupyter": "以本機檔（path）或 base64 取代 Jupyter 工作表的工作資料夾（ZIP，含 .ipynb）",
    "sheet_set_marimo": "取代 Marimo 筆記本工作表的程式碼（code，.py 含 @app.cell）；輸出屬於舊程式碼",
    "sheet_rename": "改工作表名稱（專案樹、報告、列印都會顯示）",
    "sheet_duplicate": "複製工作表（含文字與輸入），插在原表後並開啟",
    "sheet_move": "上移／下移工作表（影響報告與列印順序）",
    "sheet_remove": "刪除工作表，可 undo",
    "sheet_select": "讓 App 開啟指定工作表（id 可為 'project'＝專案資料、'report'＝報告），給使用者看",
    "sheet_evaluate": "以該表自己的輸入與專案資料計算，回傳標題、規範、控制 UC 值、結果與檢核",
    "calc_evaluate": "無狀態試算一段計算文字，不動專案、逐行回結果。批次驗算首選（不污染專案）",
    "calc_evaluate_batch": "一次試算多段計算文字（每項同 calc_evaluate），不動專案；上限 200 項，逐項回結果或該項錯誤。超過 120 秒的工作改用 job_start",
    "job_start": "在背景開始多段試算（同 calc_evaluate_batch 的項目），立即回 jobId；不動專案，工作只存在記憶體（保留最近 20 筆已結束工作）",
    "job_status": "查背景工作狀態（running／done／cancelled）與已完成項數；results=true（預設）回目前已算出的結果",
    "job_cancel": "停止背景工作（在目前這項算完後停）；已算出的結果仍可由 job_status 取得",
    "session_new": "開拋棄式工作表：先把目前專案（名稱、路徑、工作表、報告、undo、未儲存旗標）收起，換成空專案；之後的操作都不進使用者專案與最近檔案",
    "session_close": "關閉 session_new 開的拋棄式工作表，把原專案完整放回（含未儲存旗標與 undo 歷史）；沒有開 session 時回 CONFLICT",
    "sheet_read": "以資料形式讀任一工作表：試算表逐格（值、公式、顯示文字）、圖形節點輸出與錯誤、Jupyter 逐 cell（source、execution count、輸出）、Marimo 等",
    "sheet_run": "執行工作表並回傳新內容（同 sheet_read）。Jupyter：依序執行所有 code cell，遇錯停止，輸出存入專案；Marimo：重新載入並執行所有 cell。⚠ 會改動專案",
    "sheet_reset_input": "把工作表輸入值還原為交付設計值（由 sheet_set_input 設的值，未設過的回計算文字預設）；可指定 names，省略則全部已改欄位還原；一步 undo",
    "sheet_drawing": "匯出繪圖工作表為 SVG 或 DXF（標註與 {{…}} 文字已代入計算結果，例如標註 'L/2' 隨 L 變）。座標為實際毫米（SVG 寫 data-eenheid=\"mm\"；DXF 依 $INSUNITS：4＝mm、6＝m）；回應另列出所有綁定的變數",
    "module_schema": "由 modules_list 的模組描述輸入欄位（name、label、kind、unit、default、choices）與計算文字引用的規範條號，供客戶端組 case.json；欄位範圍不在文字中宣告，回傳與該欄位相關的比較式作為防護條件",
    "sheet_insert_formula": "把公式庫的公式（含輸入與範例值）插入工作表計算文字",
    "library_list": "線上模組庫（OpenAEC Foundation 公開倉庫）全部模組：id、版本、是否已安裝；refresh 強制重抓。⚠ 連外",
    "library_install": "由模組庫安裝／更新模組（用 id）。⚠ 連外",
    "library_remove": "移除由模組庫裝的模組；同 id 內建模組會回復",
    "formulas_list": "搜尋公式庫（力學與 Eurocode EN 1990~1999 標準公式），可依 query／group 篩選",
    "formula_get": "讀單一公式與其計算文字",
    "ifc_get": "取整個專案或單一工作表的 IFC 文字：format=ifcx（IFCX JSON）或 ifc（STEP）",
    "export_ifc": "把 IFCX（.ifcx）或 IFC（STEP .ifc）寫到檔案",
    "export_pdf": "經 report engine 寫計算書 PDF（封面＋工作表）。⚠ 一般安裝版回 501 NOT_AVAILABLE，含圖 PDF 只能 App 內按『Rapport』",
    "print": "觸發 App 的列印（what='report' 報告 或單表）。⚠ 會開系統對話框，需人在場",
    "view_get": "讀目前工作表的檢視模式（code-visual／code-output／visual-output／print-preview／ifc）",
    "view_set": "切換目前工作表的檢視模式",
    "settings_get": "讀 App 設定：主題、語言、文字大小、單位（角度模式、預設顯示單位）",
    "settings_set": "改 App 設定（theme、language、textSize、units）",
}

KIND_ZH = {"read": "讀取", "mutate": "改動專案", "file": "檔案 I/O", "ui": "介面操作"}


def _type_str(sch: dict) -> str:
    t = sch.get("type")
    if isinstance(t, list):
        t = "｜".join(t)
    if t == "array":
        it = sch.get("items", {})
        t = f"array<{_type_str(it)}>" if it else "array"
    return t or ("enum" if "enum" in sch else "any")


def _enum_str(sch: dict) -> str:
    e = sch.get("enum")
    if not e:
        return ""
    if len(e) <= 8:
        return "：" + "／".join(f"`{x}`" for x in e)
    return f"：{len(e)} 個選項（見 `tools/list`）"


def _hints(a: dict) -> str:
    out = ["唯讀" if a.get("readOnlyHint") else "會改動"]
    if a.get("destructiveHint"):
        out.append("破壞性")
    out.append("冪等" if a.get("idempotentHint") else "非冪等")
    if a.get("openWorldHint"):
        out.append("連外")
    return "、".join(out)


def _params(schema: dict) -> list[str]:
    props = (schema or {}).get("properties", {}) or {}
    req = set((schema or {}).get("required", []) or [])
    rows = []
    for name, sch in props.items():
        desc = (sch.get("description") or "").replace("\n", " ").replace("|", "\\|")
        rows.append(f"| `{name}` | {_type_str(sch)}{_enum_str(sch)} | {'是' if name in req else ''} | {desc} |")
    return rows


def render(tools: list[dict], version: str) -> str:
    by = {t["name"]: t for t in tools}
    listed = {n for _, names in GROUPS for n in names}
    extra = [n for n in by if n not in listed]
    missing = [n for n in listed if n not in by]

    L: list[str] = []
    A = L.append
    A("# Open CalcSheet Studio 工具清單（MCP／REST）")
    A("")
    A("> 本檔由 `python tools/crosscheck/ocss_tools_doc.py` 從**執行中的 OCSS 即時抓取**後生成，**請勿手改**；"
      "OCSS 升版後重跑即可更新。整合脈絡、單位陷阱與能力邊界見 "
      "[`OpenCalcSheetStudio_整合與開放計算環境.md`](OpenCalcSheetStudio_整合與開放計算環境.md)。")
    A("")
    A(f"- **OCSS 版本**：{version}　**工具總數**：{len(tools)}")
    kinds: dict[str, int] = {}
    for t in tools:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    A("- **分類（kind）**：" + "、".join(f"{KIND_ZH.get(k, k)} {v}" for k, v in sorted(kinds.items())))
    A("- **同一份 registry、三種進入點**：MCP `http://127.0.0.1:3879/mcp`、REST 通用 `POST /api/v1/tools/<name>`、"
      "以及部分工具的語意化 REST 路由（下表『REST 路由』）。三者行為一致，token 相同。")
    A("- **認證**：`Authorization: Bearer <token>`；token 在 `preferences.json` 的 `mcpToken`（機密，不入文件／版控）。")
    A("- **Linux 設定檔位置**：`~/.local/share/tw.opencalcsheet.studio/preferences.json`（TW 版；上游為 `studio.openstructuralcalculation.app`）"
      "（Tauri `app_data_dir`；非 `~/.config`）。")
    A("")
    A("## 本專案使用建議")
    A("")
    A("1. **交叉驗算首選 `calc_evaluate`**：無狀態、不動專案、不會讓專案變『未儲存』。腳本端走 `tools/crosscheck/ocss_client.py`。")
    A("2. **要改專案才用 `sheet_*`／`project_*`**：`sheet_add`／`sheet_remove` 一旦做了，專案即標未儲存，刪回原狀也不復原；`project_new`／`project_open` 遇未儲存會 CONFLICT。")
    A("3. **台灣模組** `modules_list` 中以 `tw-` 開頭（RC 梁柱板、基腳、樁帽、鋼梁柱、擋土牆、排水溝、滯洪池、箱涵、沉砂池、重力式擋土牆、水面線、地震力、風力、載重彙整），"
      "專案資料欄位 `tw_*`（用途別、地況、V10、SDS、SD1）要先用 `project_set_data` 設好。")
    A("4. **不要用的**：`export_pdf`（一般版 501）、`print`（開系統對話框）。IFC 匯出（`export_ifc`／`ifc_get`）正常。")
    A("5. **連外工具**（`openWorldHint`）：`library_list`、`library_install`，會連 OpenAEC Foundation 模組庫；離線環境勿用。")
    A("6. **嚴禁對 OCSS 執行檔跑 `--version`／`--help`**：它們不會印說明，而是直接啟動 GUI 並卡住（本機 Linux 實測亦同）。查版本用 `ocss_crosscheck.py probe` 或 `app_info`。")
    A("")
    A("## 總覽")
    A("")
    for gname, names in GROUPS:
        A(f"### {gname}")
        A("")
        A("| 工具 | 類別 | 特性 | 用途 |")
        A("|---|---|---|---|")
        for n in names:
            t = by.get(n)
            if not t:
                continue
            A(f"| `{n}` | {KIND_ZH.get(t['kind'], t['kind'])} | {_hints(t.get('annotations', {}))} | {PURPOSE.get(n, '（待補）')} |")
        A("")
    if extra:
        A("### 未分組（OCSS 新增，請補進 GROUPS／PURPOSE）")
        A("")
        for n in extra:
            A(f"- `{n}`：{(by[n].get('description') or '')[:120]}")
        A("")

    A("## 逐一規格")
    A("")
    A("每個工具列：特性、REST 路由、參數表與 OCSS 原文說明（英文，原樣保留以免失真）。")
    A("")
    for gname, names in GROUPS:
        A(f"### {gname}")
        A("")
        for n in names:
            t = by.get(n)
            if not t:
                continue
            A(f"#### `{n}`")
            A("")
            A(f"- **用途**：{PURPOSE.get(n, '（待補）')}")
            A(f"- **類別／特性**：{KIND_ZH.get(t['kind'], t['kind'])}；{_hints(t.get('annotations', {}))}")
            routes = "、".join(f"`{r['method']} {r['path']}`" for r in t.get("routes", []))
            A(f"- **REST 路由**：{routes}")
            rows = _params(t.get("inputSchema", {}))
            if rows:
                A("")
                A("| 參數 | 型別 | 必填 | 說明 |")
                A("|---|---|---|---|")
                L.extend(rows)
            else:
                A("- **參數**：無")
            A("")
            A("> " + (t.get("description") or "").replace("\n", "\n> "))
            A("")
    if missing:
        A(f"<!-- 注意：GROUPS 內有但 OCSS 已不存在的工具：{', '.join(missing)} -->")
    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="只比對，不寫檔；不同回傳 1")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()
    try:
        c = OcssClient(port=args.port)
        info = c.info()
        tools = c.tools()
    except OcssError as e:
        print(f"✗ {e}")
        return 2
    ver = info.get("version") or info.get("appVersion") or "?"
    text = render(tools, str(ver))
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("✓ 與現況一致" if same else "✗ 文件與 OCSS 現況不同，請重跑本腳本")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"✓ 已寫入 {OUT.relative_to(PROJECT_ROOT)}（{len(tools)} 個工具，OCSS {ver}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
