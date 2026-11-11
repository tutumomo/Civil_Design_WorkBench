# -*- coding: utf-8 -*-
"""排水網路示意圖 NW-1（D11）：`drainage_network` 結果 → A3 DXF/DWG/PDF。

為什麼是「示意圖」
------------------
`drainage_network` 的節點**沒有座標**（只有 id 與入流），所以不可能畫真實平面位置。
本工具用圖論排版：拓撲分層（上游在上、匯流向下）＋層內重心法排序；排版尺寸以
**紙面 mm** 設計（節點半徑 6 mm、水平間距 46 mm、層距 44 mm，節點多時等比縮小），
再以固定的名目比例 1:50 換算成模型座標——因此不論網路多大，紙面上的節點大小與間距
都一致，這正是示意圖該有的樣子。圖面明示「示意圖 非比例」，**不做任何尺寸標註**；
標題欄的比例尺只是視口比例（供列印），說明第 1 條寫明不得量測。

圖上數值來源
------------
節點：`nodes[]`（local_inflow／incoming／outgoing／terminal_outfall）；
排水路：`links[]`（flow_m3s、capacity_m3s、capacity_ratio、normal_depth_m、velocity_m_s、ok）；
渠道內尺寸與坡度來自輸入的 `inner_width_m`／`depth_m`／`slope`（結果只回傳流量與容量）。
圖上只標「編號」與「Q／Qcap（比值）」避免標註互相壓字，完整規格與水深流速見右欄流量表。

用法
----
    .venv/bin/python tools/network_section/make_network.py <case.json> --out out/<案名>/NW-1.dxf
案件檔 `quantities.model == "drainage_network"`。
"""

import argparse
import json
import os
import sys

import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _sub in ("tools", "tools/a3_sheet", "tools/design", "tools/regs",
             "tools/wall_section", "tools/box_section"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

import drawing_rules as DR                    # noqa: E402
import make_wall_section as MWS               # noqa: E402
import make_box_section as MBS                # noqa: E402

L_NODE = "30_節點"
L_LINK = "31_排水路"
L_OUT = "32_放流口"
L_MARK = "43_標註"

# 排版尺寸一律以紙面 mm 設計（示意圖不隨網路大小改變外觀）
R_MM = 6.0            # 節點半徑
DX_MM = 50.0          # 同層節點水平間距
DY_MM = 44.0          # 層距
DX_MIN, DY_MIN = 24.0, 30.0
PAD_L_MM = 8.0        # 左緣（節點圓外）
PAD_R_MM = 54.0       # 右緣（節點右側的入流／出流文字）
PAD_T_MM = 16.0       # 「上游在上」說明
PAD_B_MM = 18.0       # 放流口標籤
NOMINAL_SCALE = 50    # 名目比例：模型 = 紙面 mm × 50/1000（視口比例，不代表實距）
SHEET_W, SHEET_H = 183.0, 249.45
TYPE_TEXT = {"channel": "渠道", "fixed": "指定容量", "pipe": "管涵", "culvert": "箱涵"}


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") != "drainage_network":
        raise SystemExit("本工具只做排水網路示意圖（model 應為 drainage_network，現在是 %r）"
                         % q.get("model"))
    return case, dict(q.get("values") or {})


def run_engine(values):
    import design_api as D

    env = D.run_calculation("drainage_network", values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or not res.get("nodes"):
        raise SystemExit("drainage_network 引擎沒有網路結果，無法出圖。")
    return res


def levels_of(res):
    """拓撲分層（Kahn 最長路徑）＋層內重心排序；有環即明確拒絕（純計算）。"""
    ids = [str(n["id"]) for n in res["nodes"]]
    preds = {i: [] for i in ids}
    succs = {i: [] for i in ids}
    for lk in res["links"]:
        a, b = str(lk["from"]), str(lk["to"])
        if a not in preds or b not in preds:
            raise SystemExit("排水路 %s 接到的節點不在 nodes 內（%s→%s）" % (lk["id"], a, b))
        succs[a].append(b)
        preds[b].append(a)

    indeg = {i: len(preds[i]) for i in ids}
    level = {i: 0 for i in ids}
    queue = sorted(i for i in ids if indeg[i] == 0)
    seen = []
    while queue:
        i = queue.pop(0)
        seen.append(i)
        for j in sorted(succs[i]):
            level[j] = max(level[j], level[i] + 1)
            indeg[j] -= 1
            if indeg[j] == 0:
                queue.append(j)
    if len(seen) != len(ids):
        raise SystemExit("排水網路有環（或接不到來源），無法排版示意圖。")

    groups = {}
    for i in ids:
        groups.setdefault(level[i], []).append(i)
    for lv in groups:
        groups[lv].sort()
    idx = {}
    for lv in sorted(groups):                      # 由上而下：依上游平均位置
        g = groups[lv]

        def bary(i):
            ps = [idx[p] for p in preds[i] if p in idx]
            return (sum(ps) / len(ps)) if ps else float(len(g))
        g.sort(key=lambda i: (bary(i), i))
        for k, i in enumerate(g):
            idx[i] = k
    for lv in sorted(groups, reverse=True):        # 再由下而上：依下游平均位置
        g = groups[lv]

        def bary2(i):
            ss = [idx[s] for s in succs[i] if s in idx]
            return (sum(ss) / len(ss)) if ss else float(len(g))
        g.sort(key=lambda i: (bary2(i), i))
        for k, i in enumerate(g):
            idx[i] = k
    return groups


def fit_units(groups):
    """節點數／層數過多時等比縮小間距，仍放不下就報錯（尚未實作分張）。"""
    max_n = max(len(g) for g in groups.values())
    n_lv = len(groups)
    dx, dy = DX_MM, DY_MM
    for _ in range(40):
        w = (max_n - 1) * dx + 2 * R_MM + PAD_L_MM + PAD_R_MM
        h = (n_lv - 1) * dy + 2 * R_MM + PAD_T_MM + PAD_B_MM
        if w <= SHEET_W and h <= SHEET_H:
            return dx, dy
        shrink = min(SHEET_W / w, SHEET_H / h)
        dx = max(DX_MIN, dx * shrink)
        dy = max(DY_MIN, dy * shrink)
        if dx <= DX_MIN and dy <= DY_MIN:
            break
    raise SystemExit("網路 %d 節點／%d 層，縮到最小間距仍放不進 A3 可繪區；"
                     "本工具尚未實作分張。" % (max_n, n_lv))


def network_layout(res):
    """節點座標（紙面 mm，y 向下為下游）與排版尺寸（純計算，自測直接呼叫）。"""
    groups = levels_of(res)
    dx, dy = fit_units(groups)
    pos = {}
    for lv, g in groups.items():
        m = len(g)
        for k, i in enumerate(g):
            pos[i] = ((k - (m - 1) / 2.0) * dx, -lv * dy)
    return {"pos_mm": pos, "groups": groups, "dx_mm": dx, "dy_mm": dy,
            "links": [{"id": str(lk["id"]), "from": str(lk["from"]), "to": str(lk["to"])}
                      for lk in res["links"]]}


def to_model(p_mm):
    """紙面 mm → 模型 m（固定名目比例，外觀不隨網路大小改變）。"""
    return (p_mm[0] * NOMINAL_SCALE / 1000.0, p_mm[1] * NOMINAL_SCALE / 1000.0)


def ensure_layers(doc):
    for name, color in [(L_NODE, 6), (L_LINK, 5), (L_OUT, 1), (L_MARK, 7),
                        (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def _text(msp, s, p, layer=L_MARK, h=0.1,
          align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT):
    t = msp.add_text(str(s), height=h, dxfattribs={"layer": layer, "style": "TOMO"})
    t.set_placement(p, align=align)
    return t


def draw(doc, res, geo):
    msp = doc.modelspace()
    th = DR.model_h(3.0, NOMINAL_SCALE)
    r = R_MM * NOMINAL_SCALE / 1000.0
    pos = {k: to_model(v) for k, v in geo["pos_mm"].items()}
    nodes = {str(n["id"]): n for n in res["nodes"]}

    for lk in res["links"]:
        a, b = str(lk["from"]), str(lk["to"])
        (x0, y0), (x1, y1) = pos[a], pos[b]
        ym = (y0 + y1) / 2.0
        path = [(x0, y0 - r), (x0, ym), (x1, ym), (x1, y1 + r)]
        msp.add_lwpolyline(path, dxfattribs={"layer": L_LINK})
        tip = path[-1]
        ah = 1.2 * th
        msp.add_line(tip, (tip[0] - ah, tip[1] + 1.8 * ah), dxfattribs={"layer": L_LINK})
        msp.add_line(tip, (tip[0] + ah, tip[1] + 1.8 * ah), dxfattribs={"layer": L_LINK})
        # 標註貼在「來源端的垂直段」旁邊（每條路各自一段，不會互相壓字）；
        # 同層（y 相同）的橫向排水路沒有垂直段，退回畫在兩節點中點上方
        if abs(y1 - y0) > 2.2 * r:
            # 標註放在來源節點外側：最右邊的節點往左寫，其餘往右寫，兩兩不會對撞
            side = -1.0 if abs(x0 - max(pos[k][0] for k in pos)) < 1e-9 else 1.0
            lx = x0 + side * 0.9 * th
            ly = y0 - r - 1.0 * th
            align = (ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT if side > 0
                     else ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT)
            ly2 = ly - 3.6 * th
            align2 = align
        else:
            lx = (x0 + x1) / 2.0
            ly = y0 + r + 1.0 * th
            ly2 = ly + 3.6 * th
            align = align2 = ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER
        _text(msp, "%s %s" % (lk["id"], TYPE_TEXT.get(str(lk.get("type")),
                                                      str(lk.get("type")))),
              (lx, ly), L_MARK, th, align)
        _text(msp, "Q/Qcap %.2f%s" % (float(lk["capacity_ratio"]),
                                      "" if lk.get("ok") else " 超量"),
              (lx, ly2), L_MARK, th, align2)

    for nid, (x, y) in pos.items():
        n = nodes[nid]
        msp.add_circle((x, y), r, dxfattribs={"layer": L_NODE})
        _text(msp, nid, (x, y - 0.5 * th), L_NODE, th,
              ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        if n.get("terminal_outfall"):
            msp.add_circle((x, y), r * 1.4, dxfattribs={"layer": L_OUT})
            _text(msp, "放流口 %.2f m³/s" % float(n.get("outgoing_m3s") or 0.0),
                  (x, y - r * 1.4 - 0.6 * th), L_OUT, th,
                  ezdxf.enums.TextEntityAlignment.TOP_CENTER)
        else:
            _text(msp, "入 %.2f｜出 %.2f" % (float(n.get("local_inflow_m3s") or 0.0),
                                            float(n.get("outgoing_m3s") or 0.0)),
                  (x + r + 0.6 * th, y - 0.5 * th), L_MARK, th)

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    _text(msp, "上游（入流）在上、流向由上向下；節點位置為拓撲排版，非實距",
          (min(xs) - r, max(ys) + r + 1.0 * th), L_MARK, th)
    return {"th": th, "r": r}


def build_blocks(res, values):
    ng = [c for c in res.get("checks", []) if not c.get("ok")]
    groups = levels_of(res)
    summary = [
        ("節點數", "%d（%d 層）" % (len(res["nodes"]), len(groups))),
        ("排水路數", "%d" % len(res["links"])),
        ("總本地入流", "%.2f m³/s" % float(res["total_local_inflow_m3s"])),
        ("終端放流量", "%.2f m³/s" % float(res["terminal_outflow_m3s"])),
        ("流量平衡誤差", "%.4f m³/s" % float(res["flow_balance_error_m3s"])),
        ("檢核項目", "%d 項，NG %d 項" % (len(res.get("checks", [])), len(ng))),
    ]
    inp = {str(l.get("id")): l for l in values.get("links") or []}
    rows = []
    for lk in res["links"]:
        lid = str(lk["id"])
        v = inp.get(lid) or {}
        kind = TYPE_TEXT.get(str(lk.get("type")), str(lk.get("type")))
        spec = kind
        if lk.get("type") == "channel" and v.get("inner_width_m") is not None:
            spec = "%.1f×%.1f" % (float(v["inner_width_m"]), float(v.get("depth_m") or 0.0))
        rows.append([
            # 「→」後面若不隔空白，TC 大字的 SHX 會把下一個 ASCII 字吃掉（實測 A→C 變 A→☒）
            (0.0, lid), (26.0, "%s → %s" % (lk["from"], lk["to"])), (58.0, spec),
            (96.0, "%.2f" % float(lk["flow_m3s"])),
            (122.0, "%.2f" % float(lk["capacity_m3s"])),
            (148.0, "%.2f" % float(lk["capacity_ratio"])),
            (172.0, "-" if lk.get("normal_depth_m") is None
             else "%.2f" % float(lk["normal_depth_m"])),
            (192.0, "OK" if lk.get("ok") else "NG")])
    return [
        {"title": "網路摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in summary]},
        {"title": "排水路流量表（m／m³/s）",
         "header": [(0.0, "編號"), (26.0, "起→訖"), (58.0, "型式／內尺寸"),
                    (96.0, "設計 Q"), (122.0, "容量"), (148.0, "Q/Qcap"),
                    (172.0, "h_n"), (192.0, "判定")],
         "rows": rows},
    ]


def build_notes(res):
    ng = [c for c in res.get("checks", []) if not c.get("ok")]
    n = ["1. 本圖為排水網路示意圖：節點沒有座標，位置由拓撲分層＋層內重心法自動排版，"
         "與實際平面位置及距離無關；圖上不做尺寸標註，標題欄比例尺僅為視口比例（供列印），"
         "不得依本圖量測實距。",
         "2. 節點數字為本地入流與出流（m³/s）；雙圈者為終端放流口。",
         "3. 排水路圖上標「編號 型式」與「設計流量／容量（Q/Qcap）」；渠道內尺寸、坡度、"
         "正常水深與流速見右欄排水路流量表（尺寸取自輸入，流量與容量取自結果）。",
         "4. 網路演算為穩態流量分配；未含迴水、滯洪、抽水與操作規則。",
         "5. 引擎限制（原文見計算結果）：僅穩態峰值流量分配，未含蓄水與時間延遲；"
         "容量按正常水深計，未含漸變流水面線、迴水與進出口控制；渠段容量未計阻塞、"
         "淤積與出口沖刷。"]
    n.append("%d. %s" % (len(n) + 1, "本題檢核全部通過。" if not ng
                         else "本題有 %d 項檢核未通過，不得施工。" % len(ng)))
    return n


def _not_to_scale(lay):
    """把 build_paper 的比例尺換成「示意圖 非比例」：示意圖畫比例尺會誤導量測。"""
    ref = next((t for t in lay.query("TEXT")
                if str(t.dxf.text).startswith("比例尺") and "1:" in str(t.dxf.text)), None)
    if ref is None:                                    # pragma: no cover - 樣板異常
        return
    x, y = ref.dxf.insert.x, ref.dxf.insert.y
    for kind in ("TEXT", "LWPOLYLINE", "SOLID"):
        for e in list(lay.query(kind)):
            if e.dxf.layer == MWS.L_SCALE:
                lay.delete_entity(e)
    # 一句話就好：視口只有約 92 mm 寬，長句會伸出圖框，完整說明在說明欄第 1 條
    t = lay.add_text("示意圖 非比例（不得量測實距）",
                     height=4.0, dxfattribs={"layer": MWS.L_SCALE, "style": "TOMO"})
    t.set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)


def main():
    ap = argparse.ArgumentParser(description="排水網路示意圖（D11）")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto",
                    help="視口比例（示意圖固定用 1:%d，此參數僅接受該值或 auto）" % NOMINAL_SCALE)
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--unit", default="m", choices=["m", "cm"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--drafter", default="Claude（AI）")
    ap.add_argument("--sheet-no", default=None)
    ap.add_argument("--rebar", action="store_true")
    ap.add_argument("--template", default=MWS.TEMPLATE)
    a = ap.parse_args()

    case, values = load_values(a.case)
    res = run_engine(values)
    geo = network_layout(res)
    if str(a.scale).lower() != "auto" and int(a.scale) != NOMINAL_SCALE:
        raise SystemExit("示意圖固定用 1:%d（節點間距以紙面 mm 設計，換比例只會改模型單位、"
                         "外觀不變）；請用 --scale auto。" % NOMINAL_SCALE)
    H = NOMINAL_SCALE
    DR.require_standard_scale(H)

    doc = ezdxf.readfile(a.template)
    others = [l.name for l in doc.layouts if l.name != "Model"]
    if MBS.LAYOUT_NAME in doc.layouts:
        lay0 = doc.layouts.get(MBS.LAYOUT_NAME)
    elif others:
        doc.layouts.rename(others[0], MBS.LAYOUT_NAME)
        lay0 = doc.layouts.get(MBS.LAYOUT_NAME)
    else:
        lay0 = doc.layouts.new(MBS.LAYOUT_NAME)
    for v in [e for e in lay0.query("VIEWPORT") if e.dxf.id != 1]:
        lay0.delete_entity(v)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    for name in [l.name for l in doc.layouts if l.name not in ("Model", MBS.LAYOUT_NAME)]:
        try:
            doc.layouts.delete(name)
        except Exception as ex:                       # pragma: no cover
            print("  ⚠ 無法刪除版面 %s：%s" % (name, ex))

    MWS.ensure_tomo(doc)
    ensure_layers(doc)
    draw(doc, res, geo)

    no = a.sheet_no or "NW-1"
    proj = a.project or (case.get("project") or {}).get("full_name") or "排水網路"
    MBS.build_paper(doc, {}, case, H, proj, no,
                    {"blocks": build_blocks(res, values), "notes": build_notes(res)},
                    "排水網路示意圖", no, unit=a.unit, drafter=a.drafter)
    _not_to_scale(doc.layouts.get(MBS.LAYOUT_NAME))
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  比例尺 1:%d（視口比例，示意圖不做尺寸）、%d 節點／%d 層、%d 條排水路、"
          "節點間距 %.0f×%.0f mm"
          % (H, len(res["nodes"]), len(geo["groups"]), len(res["links"]),
             geo["dx_mm"], geo["dy_mm"]))
    if a.publish:
        sys.path.insert(0, os.path.join(ROOT, "tools", "acad"))
        from acc import publish
        r = publish(out, pdf=True)
        print("PUBLISH", r)
        try:
            import fitz
            pg = fitz.open(r[".pdf"])[0]
            png = os.path.splitext(out)[0] + "_pdf.png"
            pg.get_pixmap(dpi=110).save(png)
            print("PDF 預覽 %s" % png)
        except Exception as ex:
            print("PDF 轉圖略過", ex)


if __name__ == "__main__":
    main()
