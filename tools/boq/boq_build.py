"""工程預算書產生器：案件 JSON → GridCraft 指令碼 → 5 工作表 .xlsx ＋ .pdf ＋ 計算書 JSON。

用法
----
    set PYTHONIOENCODING=utf-8
    python <專案根目錄>\\tools\\boq\\boq_build.py ^
        <案件.json> --out-dir <輸出資料夾> [--no-pdf] [--dry-run]

產出（`<工程名稱>_預算書.*`）
------------------------------
    .xlsx         5 工作表：封面 / 總表 / 詳細表 / 單價分析表 / 數量計算（費率層是活公式）
    .pdf          上述 5 工作表全部頁面（A4，自動縮放一頁寬）
    _計算書.json   所有中間值與逐項計算（稽核用）
    _指令.jsonl    實際送給 GridCraft 的指令（可重跑、可 diff）

設計原則
--------
1. **費率層用 Excel 公式**，與公司既有預算書習慣一致：客戶改數量時自動重算，可用 `gridcraft-cli check` 驗算。
2. **數量／單位為靜態值**，由案件 JSON 提供（來源應為「數量計算」工作表或 DXF 量測結果）。
3. **計算核心在 `boq_rules.py`**（已與真實預算書對帳），本檔只負責排版與呼叫工具。
4. 產生後**自我驗證**：回讀 xlsx 的總計，必須等於 Python 算出的總計，否則 exit 1。
"""

import argparse
import sys as _sys
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from project_paths import artcraft_cli  # noqa: E402
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boq_rules as R  # noqa: E402

GRIDCRAFT = artcraft_cli("GridCraft") or ""

FONT_TITLE = "標楷體"
FONT_BODY = "新細明體"
NUM_AMOUNT = "#,##0"
NUM_PRICE = "#,##0.0"
NUM_PRICE2 = "#,##0.00"


# --------------------------------------------------------------------------- #
# 指令收集
# --------------------------------------------------------------------------- #
class Cmd:
    def __init__(self):
        self.lines = []

    def add(self, cid, **params):
        self.lines.append(f"{cid}={json.dumps(params, ensure_ascii=False)}")
        return self

    def values(self, rng, rows):
        return self.add("range.setValues", range=rng, values=rows)

    def merge(self, rng):
        return self.add("home.mergeCells", range=rng)

    def activate(self, sheet):
        return self.add("sheet.activate", sheet=sheet)

    def font(self, rng, name):
        return self.add("home.fontName", range=rng, name=name)

    def size(self, rng, pt):
        return self.add("home.fontSize", range=rng, size=pt)

    def bold(self, rng, on=True):
        return self.add("home.bold", range=rng, on=on)

    def align(self, rng, mode):
        return self.add({"left": "home.alignLeft", "center": "home.alignCenter",
                         "right": "home.alignRight"}[mode], range=rng)

    def middle(self, rng):
        return self.add("home.alignMiddle", range=rng)

    def borders(self, rng, preset="all"):
        return self.add("home.borders", range=rng, preset=preset)

    def numfmt(self, rng, fmt):
        return self.add("home.numberFormat", range=rng, format=fmt)

    def wrap(self, rng, on=True):
        return self.add("home.wrapText", range=rng, on=on)

    def widths(self, sheet, pairs):
        for cols, chars in pairs:
            self.add("home.columnWidth", sheet=sheet, cols=cols, chars=chars)
        return self

    def heights(self, sheet, pairs):
        for rows, pts in pairs:
            self.add("home.rowHeight", sheet=sheet, rows=rows, points=pts)
        return self

    def page(self, sheet, area, landscape=True):
        self.add("pageLayout.pageSetup", sheet=sheet,
                 orientation="landscape" if landscape else "portrait", paper="A4")
        self.add("pageLayout.printArea", sheet=sheet, range=area)
        self.add("pageLayout.scaleToFit", sheet=sheet, width=1, height=0)
        return self



def _code(no):
    """項次保持文字型（01 不可變 1）：純數字者加前置單引號強制文字。"""
    s = str(no)
    return f"'{s}" if s.isdigit() else s

# --------------------------------------------------------------------------- #
# 版面規劃（先把所有列號算好，才能做跨表引用）
# --------------------------------------------------------------------------- #
def plan_layout(items):
    # --- 單價分析表：每個有 analysis 的品項一個區塊 ---
    ana = {}
    row = 6                      # 1~5 為表頭
    for idx, it in enumerate(items):
        if not it.get("analysis"):
            continue
        n = len(it["analysis"])
        start = row + 2           # 區塊標題 + 工料表頭
        end = start + n - 1
        total_row = end + 1       # 「合計」列
        unit_row = total_row + 1  # 「每 X 單價計」列
        ana[idx] = {"title": row, "head": row + 1, "start": start,
                    "end": end, "total": total_row, "unitrow": unit_row}
        row = unit_row + 2        # 區塊間隔一列

    # --- 詳細表 ---
    d_head = 6
    d_first = 9
    r_sa = d_first + len(items)
    r_q = r_sa + 1
    r_s = r_q + 1
    r_i = r_s + 1
    r_p = r_i + 1
    r_t = r_p + 1
    r_con = r_t + 1
    r_sec2 = r_con + 2
    r_mg = r_sec2 + 1
    r_mg_note = r_mg + 1
    r_air = r_mg_note + 1
    r_sup = r_air + 1
    r_sup_note = r_sup + 1
    r_ind = r_sup_note + 2
    r_tot = r_ind + 1
    detail = dict(head=d_head, first=d_first, sa=r_sa, q=r_q, s=r_s, i=r_i, p=r_p,
                  t=r_t, con=r_con, sec2=r_sec2, mg=r_mg, mg_note=r_mg_note,
                  air=r_air, sup=r_sup, sup_note=r_sup_note, ind=r_ind, tot=r_tot)

    # --- 總表（固定 21 列版面，對應參考案）---
    summary = dict(head=6, first_fee=8, con=14, sec2=16, mg=17, air=18,
                   sup=19, ind=20, tot=21)

    # --- 數量計算 ---
    quant = dict(head=5, first=6)
    return {"ana": ana, "detail": detail, "summary": summary, "quant": quant}


# --------------------------------------------------------------------------- #
# 各工作表內容
# --------------------------------------------------------------------------- #
def emit_cover(c, case):
    c.activate("封面")
    c.values("A2", [["工程名稱", "", case.get("project", "")]])
    c.values("A3", [["施工地點", "", case.get("location", "")]])
    c.values("A4", [["編製日期", "", case.get("date", "")]])
    c.values("A5", [["工程編號", "", case.get("code", "")]])
    c.values("A7", [[case.get("project", "") + "　施工預算書"]])
    c.values("A10", [["承辦技師 執業圖記及簽署", "", "", "委託設計 監造單位"]])
    c.values("A16", [[case.get("agency", "")]])
    for r in ("C2:F2", "C3:F3", "C4:F4", "C5:F5", "A7:H8", "A10:C10", "E10:H10", "A16:H17"):
        c.merge(r)
    c.font("A2:A5", FONT_BODY).size("A2:A5", 12)
    c.font("C2:F5", FONT_BODY).size("C2:F5", 12)
    c.font("A7:H8", FONT_TITLE).size("A7:H8", 26).bold("A7:H8")
    c.align("A7:H8", "center").middle("A7:H8")
    c.font("A10:H10", FONT_BODY).size("A10:H10", 11).align("A10:H10", "center")
    c.font("A16:H17", FONT_TITLE).size("A16:H17", 20).bold("A16:H17")
    c.align("A16:H17", "center").middle("A16:H17")
    c.widths("封面", [("A:A", 12), ("B:B", 3), ("C:F", 14), ("G:H", 12)])
    c.heights("封面", [("1:1", 26), ("7:8", 46), ("10:10", 52), ("16:17", 36)])
    c.page("封面", "A1:H20", landscape=False)


def emit_analysis(c, items, L):
    """單價分析表。"""
    c.activate("單價分析表")
    c.values("A1", [[items and "" or ""]])
    c.add("range.setValues", range="A1", values=[["單價分析表"]])
    first_item = next(iter(L["ana"]), None)
    for idx, it in enumerate(items):
        a = L["ana"].get(idx)
        if not a:
            continue
        no = it.get("no", "")
        basis = float(it.get("basis", 1) or 1)
        unit_lbl = f"{basis:g} {it.get('unit', '')}" if basis != 1 else it.get("unit", "")
        c.values(f"A{a['title']}", [[f"一.{no}", it.get("name", ""), "",
                                     "", "", f"單位：{unit_lbl}", ""]])
        c.merge(f"B{a['title']}:E{a['title']}")
        c.values(f"B{a['head']}", [["工料名稱", "單位", "數量", "單價", "複價", "編碼(備註)"]])
        rows = []
        for g in it["analysis"]:
            rows.append([g.get("name", ""), g.get("unit", ""), g.get("qty", 0),
                         g.get("price", 0), None, g.get("note", "")])
        c.values(f"B{a['start']}", rows)
        for i in range(len(rows)):
            r = a["start"] + i
            c.values(f"F{r}", [[f"=ROUND(D{r}*E{r},2)"]])
        c.values(f"B{a['total']}", [["合計", "", "", "", None, ""]])
        c.values(f"F{a['total']}", [[f"=SUM(F{a['start']}:F{a['end']})"]])
        c.values(f"B{a['unitrow']}", [[f"每 {it.get('unit', '')}", "", "", "單價計", None, ""]])
        c.merge(f"B{a['unitrow']}:E{a['unitrow']}")
        if basis != 1:
            c.values(f"F{a['unitrow']}", [[f"=ROUND(F{a['total']}/{basis:g},2)"]])
        else:
            c.values(f"F{a['unitrow']}", [[f"=F{a['total']}"]])
        # 格式
        c.font(f"A{a['title']}:G{a['title']}", FONT_BODY).size(f"A{a['title']}:G{a['title']}", 11).bold(f"A{a['title']}:G{a['title']}")
        c.font(f"B{a['head']}:G{a['head']}", FONT_BODY).size(f"B{a['head']}:G{a['head']}", 10).bold(f"B{a['head']}:G{a['head']}")
        c.borders(f"B{a['head']}:G{a['unitrow']}", "all")
        c.font(f"B{a['start']}:G{a['unitrow']}", FONT_BODY).size(f"B{a['start']}:G{a['unitrow']}", 10)
        c.align(f"C{a['head']}:C{a['unitrow']}", "center")
        c.numfmt(f"D{a['start']}:D{a['unitrow']}", NUM_PRICE2)
        c.numfmt(f"E{a['start']}:F{a['unitrow']}", NUM_PRICE2)
        c.bold(f"B{a['unitrow']}:F{a['unitrow']}")

    # 表頭區
    c.values("A2", [[f"工程名稱：{c._case_project}"]])
    c.values("A3", [[f"施工地點：{c._case_location}"]])
    c.values("A5", [["編號", "工料名稱", "", "", "", "編碼"]])
    c.font("A1:G1", FONT_TITLE).size("A1:G1", 16).bold("A1:G1")
    c.font("A2:G5", FONT_BODY).size("A2:G5", 10)
    c.widths("單價分析表", [("A:A", 10), ("B:B", 34), ("C:C", 8), ("D:D", 10),
                            ("E:E", 12), ("F:F", 13), ("G:G", 14)])
    last = max((v["unitrow"] for v in L["ana"].values()), default=10)
    c.page("單價分析表", f"A1:G{last}")


def emit_detail(c, case, calc, L):
    items, D = calc["items"], L["detail"]
    c.activate("詳細表")
    c.values("A1", [[case.get("agency", "")]])
    c.values("A2", [["詳細價目表"]])
    c.values("A3", [[case.get("date", "")]])
    c.values("A4", [[f"工程名稱：{case.get('project', '')}", "", "", "", "", "", "會計科目:"]])
    c.values("A5", [[f"施工地點：{case.get('location', '')}", "", "", "", "", "",
                     f"工程案號:{case.get('code', '')}"]])

    rows = [["項 次", "項　目　及　說　明", "單　位", "數　量", "單　價", "複　價", "編碼(備註)"],
            ["壹", "發包工程費", "", "", "", "", ""],
            ["一", "直接工程費", "", "", "", "", ""]]
    for it in items:
        rows.append([_code(it.get("no", "")), it.get("name", ""), it.get("unit", ""),
                     it["qty"], None, None, it.get("note", "")])
    rows += [
        ["", "小計A(壹.一)", "", "", "", None, ""],
        ["二", "工程品質管制費", "式", 1, None, None, "約小計A×0.6%"],
        ["三", "職業安全衛生管理費", "式", 1, None, None, "約小計A×0.5%"],
        ["四", "營造綜合保險費(約小計Ax0.6%)", "式", 1, None, None, "檢具核銷"],
        ["五", "承包商利潤及管理費(約小計Ax7%)", "式", 1, None, None, ""],
        ["六", "營業稅(5%)", "式", 1, None, None, ""],
        ["", "發包工程費(壹)合計", "", "", "", None, ""],
        ["", "", "", "", "", "", ""],
        ["貳", "間接工程費", "", "", "", "", ""],
        ["一", "主辦機關工程管理費(500萬元以下3.5%)", "式", 1, None, None, ""],
        ["", "", "", "", "", "", ""],
        ["二", "空氣污染防制費(約發包工程費0.3%)", "式", 1, None, None, "檢據核銷"],
        ["三", "設計監造費(500萬元以下10.5%*0.9)", "式", 1, None, None, ""],
        ["", "", "", "", "", "", ""],
        ["", "間接工程費 小計", "", "", "", None, ""],
        ["", "總計", "", "", "", None, ""],
    ]
    grid = [[("" if v is None else v) for v in r] for r in rows]
    c.values(f"A{D['head']}", grid)

    # 單價：有分析表者引用合計列
    for idx, it in enumerate(items):
        r = D["first"] + idx
        a = L["ana"].get(idx)
        if a:
            c.values(f"E{r}", [[f"=單價分析表!F{a['unitrow']}"]])
        else:
            c.values(f"E{r}", [[it["price"]]])
        c.values(f"F{r}", [[f"=ROUND(D{r}*E{r},0)"]])

    # 費率層（人工調整額：利潤／空污，參考案分別為 -505 與 +54；0 時不加尾項）
    adj_p = calc["rates"].get("adj_profit", 0) or 0
    adj_a = calc["rates"].get("adj_air", 0) or 0
    tail_p = f"{adj_p:+g}" if adj_p else ""
    tail_a = f"{adj_a:+g}" if adj_a else ""
    c.values(f"F{D['sa']}", [[f"=SUM(F{D['first']}:F{D['first'] + len(items) - 1})"]])
    c.values(f"E{D['q']}", [[f"=ROUND(F{D['sa']}*0.006,-1)"]])
    c.values(f"E{D['s']}", [[f"=ROUND(F{D['sa']}*0.005,-1)"]])
    c.values(f"E{D['i']}", [[f"=ROUND(F{D['sa']}*0.006,-1)"]])
    c.values(f"E{D['p']}", [[f"=ROUND(F{D['sa']}*0.07,0){tail_p}"]])
    c.values(f"E{D['t']}", [[f"=ROUND(SUM(F{D['sa']}:F{D['p']})*0.05,0)"]])
    for r in (D["q"], D["s"], D["i"], D["p"], D["t"]):
        c.values(f"F{r}", [[f"=ROUND(E{r}*D{r},0)"]])
    c.values(f"F{D['con']}", [[f"=SUM(F{D['sa']}:F{D['t']})"]])
    c.values(f"E{D['mg']}", [[f"=ROUND((F{D['con']}-F{D['t']}-F{D['i']})*0.035,0)"]])
    c.values(f"E{D['air']}", [[f"=ROUND(F{D['con']}*0.003,0){tail_a}"]])
    c.values(f"E{D['sup']}", [[f"=ROUND((F{D['con']}-F{D['t']}-F{D['p']}-F{D['i']})*0.105*0.9,0)"]])
    for r in (D["mg"], D["air"], D["sup"]):
        c.values(f"F{r}", [[f"=ROUND(E{r}*D{r},0)"]])
    c.values(f"F{D['ind']}", [[f"=SUM(F{D['mg']}:F{D['sup']})"]])
    c.values(f"F{D['tot']}", [[f"=F{D['con']}+F{D['ind']}"]])

    # 公式說明列（文字，說明該列算法，與參考案習慣一致）
    c.values(f"B{D['mg_note']}", [[f"=(\"(\"&F{D['con']}&\"-\"&F{D['t']}&\"-\"&F{D['i']}&\")*0.035\")"]])
    c.values(f"B{D['sup_note']}", [[f"=(\"(\"&F{D['con']}&\"-\"&F{D['t']}&\"-\"&F{D['p']}&\"-\"&F{D['i']}&\")*0.105*0.9\")"]])

    # 格式
    c.font("A1:G1", FONT_BODY).size("A1:G1", 14).bold("A1:G1")
    c.font("A2:G2", FONT_TITLE).size("A2:G2", 16).bold("A2:G2")
    c.font("A4:G5", FONT_BODY).size("A4:G5", 10)
    hdr = f"A{D['head']}:G{D['head']}"
    c.font(hdr, FONT_BODY).size(hdr, 10).bold(hdr).align(hdr, "center").wrap(hdr).middle(hdr)
    body = f"A{D['first']}:G{D['tot']}"
    c.font(body, FONT_BODY).size(body, 10)
    c.borders(f"A{D['head']}:G{D['tot']}", "all")
    c.wrap(f"B{D['first']}:B{D['tot']}")
    c.align(f"A{D['first']}:A{D['tot']}", "center")
    c.align(f"C{D['first']}:E{D['tot']}", "center")
    c.middle(body)
    c.numfmt(f"D{D['first']}:D{D['tot']}", NUM_PRICE)
    c.numfmt(f"E{D['first']}:E{D['tot']}", NUM_PRICE)
    c.numfmt(f"F{D['first']}:F{D['tot']}", NUM_AMOUNT)
    for r in (D["sa"], D["con"], D["ind"]):
        c.bold(f"A{r}:G{r}")
    c.bold(f"A{D['tot']}:G{D['tot']}").size(f"A{D['tot']}:G{D['tot']}", 11)
    c.font(f"B{D['mg_note']}:G{D['sup_note']}", FONT_BODY).size(f"B{D['mg_note']}:G{D['sup_note']}", 9)
    c.widths("詳細表", [("A:A", 6), ("B:B", 46), ("C:C", 7), ("D:D", 10),
                        ("E:E", 12), ("F:F", 13), ("G:G", 16)])
    c.heights("詳細表", [("1:1", 22), ("2:2", 24), (f"{D['first']}:{D['tot']}", 19)])
    c.page("詳細表", f"A1:G{D['tot']}")


def emit_summary(c, case, calc, L):
    S, D = L["summary"], L["detail"]
    c.activate("總表")
    c.values("A1", [[case.get("agency", "")]])
    c.values("A2", [["總　表"]])
    c.values("A3", [[case.get("date", "")]])
    c.values("A4", [[f"工程名稱：{case.get('project', '')}", "", "", "", "", "", "", "", "", "", "會計科目:"]])
    c.values("A5", [[f"施工地點：{case.get('location', '')}", "", "", "", "", "", "", "", "", "",
                     f"工程案號:{case.get('code', '')}"]])
    c.values(f"A{S['head']}", [["項 次", "項　目　及　說　明", "單 位", "數 量", "單 價", "複　價", "編碼(備註)"]])
    c.values(f"A{S['head'] + 1}", [["壹", "發包工程費", "", "", "", "", ""]])
    c.values(f"A{S['first_fee']}", [["一", "直接工程費", "式", 1,
                                     f"=詳細表!F{D['sa']}", f"=D{S['first_fee']}*E{S['first_fee']}", ""]])
    fee_rows = [
        (S["first_fee"] + 1, "二", "工程品質管制費", f"=詳細表!E{D['q']}", "約0.6%"),
        (S["first_fee"] + 2, "三", "職業安全衛生管理費", f"=詳細表!E{D['s']}", "約0.5%"),
        (S["first_fee"] + 3, "四", "營造綜合保險費(約小計Ax0.6%)", f"=詳細表!E{D['i']}", "檢具核銷"),
        (S["first_fee"] + 4, "五", "承包商利潤及管理費(約小計Ax7%)", f"=詳細表!E{D['p']}", ""),
        (S["first_fee"] + 5, "六", "營業稅(5%)", f"=詳細表!E{D['t']}", ""),
    ]
    for r, no, name, eform, note in fee_rows:
        c.values(f"A{r}", [[no, name, "式", 1, eform, f"=ROUND(D{r}*E{r},0)", note]])
    c.values(f"B{S['con']}", [["發包工程費(壹)合計", "", "", "", f"=詳細表!F{D['con']}", ""]])
    c.values(f"A{S['sec2']}", [["貳", "間接工程費", "", "", "", "", ""]])
    ind_rows = [
        (S["mg"], "一", "主辦機關工程管理費(500萬元以下3.5%)", f"=詳細表!E{D['mg']}", ""),
        (S["air"], "二", "空氣污染防制費(約發包工程費0.3%)", f"=詳細表!E{D['air']}", "檢據核銷"),
        (S["sup"], "三", "設計監造費(500萬元以下10.5%*0.9)", f"=詳細表!E{D['sup']}", ""),
    ]
    for r, no, name, eform, note in ind_rows:
        c.values(f"A{r}", [[no, name, "式", 1, eform, f"=ROUND(D{r}*E{r},0)", note]])
    c.values(f"B{S['ind']}", [["間接工程費 小計", "", "", "", f"=SUM(F{S['mg']}:F{S['sup']})", ""]])
    c.values(f"B{S['tot']}", [["總計", "", "", "", f"=F{S['con']}+F{S['ind']}", ""]])
    # 合計列跨欄合併
    for r in (S["con"], S["ind"], S["tot"]):
        c.merge(f"B{r}:E{r}")
        c.align(f"B{r}:B{r}", "center")

    c.font("A1:G1", FONT_BODY).size("A1:G1", 14).bold("A1:G1")
    c.font("A2:G2", FONT_TITLE).size("A2:G2", 16).bold("A2:G2")
    c.font("A4:G5", FONT_BODY).size("A4:G5", 10)
    hdr = f"A{S['head']}:G{S['head']}"
    c.font(hdr, FONT_BODY).size(hdr, 10).bold(hdr).align(hdr, "center").wrap(hdr).middle(hdr)
    body = f"A{S['first_fee']}:G{S['tot']}"
    c.font(body, FONT_BODY).size(body, 10)
    c.borders(f"A{S['head']}:G{S['tot']}", "all")
    c.wrap(f"B{S['first_fee']}:B{S['tot']}")
    c.align(f"A{S['first_fee']}:A{S['tot']}", "center")
    c.align(f"C{S['first_fee']}:E{S['tot']}", "center")
    c.middle(body)
    c.numfmt(f"D{S['first_fee']}:D{S['tot']}", NUM_PRICE)
    c.numfmt(f"E{S['first_fee']}:E{S['tot']}", NUM_PRICE)
    c.numfmt(f"F{S['first_fee']}:F{S['tot']}", NUM_AMOUNT)
    for r in (S["con"], S["ind"]):
        c.bold(f"A{r}:G{r}")
    c.bold(f"A{S['tot']}:G{S['tot']}").size(f"A{S['tot']}:G{S['tot']}", 11)
    c.widths("總表", [("A:A", 6), ("B:B", 40), ("C:C", 7), ("D:D", 8),
                      ("E:E", 12), ("F:F", 13), ("G:G", 12)])
    c.heights("總表", [("1:1", 22), ("2:2", 24), (f"{S['first_fee']}:{S['tot']}", 19)])
    c.page("總表", f"A1:G{S['tot']}")


def emit_quantity(c, calc, L):
    Q = L["quant"]
    c.activate("數量計算")
    c.values("A1", [["工程數量計算表"]])
    rows = []
    for it in calc["items"]:
        # 前置單引號＝強制文字，避免單獨的 "=" 被當成未完成公式（GridCraft 會報 unexpected end of formula）
        rows.append([_code(it.get("no", "")), it.get("name", ""), it.get("calc", ""),
                     "'=", it["qty"], it.get("unit", "")])
    c.values(f"A{Q['head']}", [["編號", "項　目", "計　算　式", "", "數　量", "單　位"]])
    c.values(f"A{Q['first']}", rows)
    last = Q["first"] + max(len(rows) - 1, 0)
    c.font("A1:F1", FONT_TITLE).size("A1:F1", 16).bold("A1:F1")
    hdr = f"A{Q['head']}:F{Q['head']}"
    c.font(hdr, FONT_BODY).size(hdr, 10).bold(hdr).align(hdr, "center").middle(hdr)
    body = f"A{Q['first']}:F{last}"
    c.font(body, FONT_BODY).size(body, 10).middle(body)
    c.borders(f"A{Q['head']}:F{last}", "all")
    c.align(f"A{Q['first']}:A{last}", "center")
    c.align(f"D{Q['first']}:F{last}", "center")
    c.numfmt(f"E{Q['first']}:E{last}", NUM_PRICE)
    c.widths("數量計算", [("A:A", 8), ("B:B", 46), ("C:C", 26), ("D:D", 5),
                          ("E:E", 10), ("F:F", 7)])
    c.page("數量計算", f"A1:F{last}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def default_out(case_path):
    r"""AGENTS.md 1.1：交付物一律 <專案>out<案名>；非 cases 結構則退回案件旁的 out。"""
    p = os.path.abspath(case_path)
    d = os.path.dirname(p)
    if os.path.basename(d) == "_case":          # out\<案名>\_case\boq_case.json
        return os.path.dirname(d)
    if os.path.basename(os.path.dirname(d)) == "cases":   # cases\<案名>\case.json
        return os.path.join(os.path.dirname(os.path.dirname(d)), "out", os.path.basename(d))
    return os.path.join(d, "out")

def main():
    ap = argparse.ArgumentParser(description="工程預算書產生器")
    ap.add_argument("case", help="案件 JSON")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    case = json.load(open(a.case, encoding="utf-8"))
    items = case.get("items", [])
    if not items:
        sys.exit("案件 JSON 沒有 items")
    calc = R.compute(items, case.get("rates"))

    out = a.out_dir or default_out(a.case)
    os.makedirs(out, exist_ok=True)
    base = os.path.join(out, f"{case.get('project', '未命名')}_預算書")

    L = plan_layout(items)

    c = Cmd()
    c.add("file.new")
    for s in ("封面", "總表", "詳細表", "單價分析表", "數量計算"):
        c.add("home.insertSheet", name=s)
    c._case_project = case.get("project", "")
    c._case_location = case.get("location", "")

    emit_cover(c, case)
    emit_summary(c, case, calc, L)
    emit_detail(c, case, calc, L)
    emit_analysis(c, items, L)
    emit_quantity(c, calc, L)

    # 刪掉預設工作表（若有）
    c.add("home.deleteSheet", sheet="Sheet1")
    c.add("file.saveAs", path=base + ".xlsx")
    if not a.no_pdf:
        c.add("file.exportPdf", path=base + ".pdf", sheets="all", fitToPage=True)

    script = base + "_指令.jsonl"
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(c.lines) + "\n")

    audit = base + "_計算書.json"
    with open(audit, "w", encoding="utf-8") as f:
        json.dump({"case": {k: v for k, v in case.items() if k != "items"},
                   "items": [{k: it[k] for k in ("no", "name", "unit", "qty", "price", "amount", "calc")
                              if k in it} for it in calc["items"]],
                   "fees": {k: calc[k] for k in
                            ("direct", "quality", "safety", "insurance", "profit", "tax",
                             "contract", "agency_mgmt", "air", "supervision", "indirect", "total")},
                   "rates": calc["rates"]}, f, ensure_ascii=False, indent=1)

    print(f"項數 {len(items)}　直接工程費 {R.fmt(calc['direct'])}　"
          f"發包工程費 {R.fmt(calc['contract'])}　總計 {R.fmt(calc['total'])}")
    print(f"指令 {len(c.lines)} 條 → {script}")
    if a.dry_run:
        print("（dry-run：未執行）")
        return

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([GRIDCRAFT, "run", "--script", script, "--quiet"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    if r.returncode != 0:
        print("STDOUT:", r.stdout[-2000:])
        print("STDERR:", r.stderr[-2000:])
        sys.exit(f"gridcraft run 失敗，exit {r.returncode}")

    # ---- 自我驗證：回讀總計 ----
    rd = subprocess.run([GRIDCRAFT, "eval", f"=詳細表!F{L['detail']['tot']}",
                         "--in", base + ".xlsx"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env)
    got = rd.stdout.strip()
    try:
        got_v = float(got.replace(",", ""))
    except ValueError:
        sys.exit(f"回讀總計失敗：{got!r} / {rd.stderr[-500:]}")

    ok = abs(got_v - calc["total"]) < 0.5
    print(f"xlsx 回讀總計 {R.fmt(got_v)}　Python {R.fmt(calc['total'])}　"
          f"{'一致 ✓' if ok else '不一致 ✗'}")
    if not ok:
        sys.exit("總計不一致，拒絕交件")

    chk = subprocess.run([GRIDCRAFT, "check", base + ".xlsx"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env)
    print("check：", (chk.stdout.strip().splitlines() or [""])[-1])
    print(f"產出：{base}.xlsx" + ("" if a.no_pdf else f"、{base}.pdf") + f"、{audit}")
    for p in (base + ".xlsx", base + ".pdf"):
        if os.path.exists(p):
            print(f"  {os.path.basename(p)}  {os.path.getsize(p):,} B")
    sys.exit(0 if (ok and chk.returncode == 0) else 1)


if __name__ == "__main__":
    main()
