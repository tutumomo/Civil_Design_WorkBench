# -*- coding: utf-8 -*-
"""溝蓋版斷面＋配筋／植筋詳圖（C-01）產線：計算器輸入 → A3 DXF/DWG/PDF。

定位
----
`channel_cover` 計算器（既有明溝加 RC 蓋版、溝壁頂植筋）的施工詳圖。植筋與配筋
是施工會照做的圖，**圖上每一個數值都取自 `channel_cover` 引擎結果欄位**，
沒有任何手填尺寸。對照表見 `docs/計算器出圖SOP.md` §2 與本檔 `labels()`。

* 結果來源：`design_api.run_calculation("channel_cover", payload)`（civil-design-channel-cover/1）
* 圖框／字型／尺寸樣式／品管：沿用 `make_box_section`、`make_wall_section`（不重造輪子）
* 圖上**未由結果決定**的元素（溝壁下段高度、植筋伸入蓋版長度、端部彎鉤）一律不標數值，
  並在說明欄明寫，由技師另行指示。

用法
----
    .venv/bin/python tools/channel_cover/make_channel_cover.py <case.json> \\
        --scale auto --out out/<案名>/C-01_溝蓋詳圖.dxf [--publish]
案件檔：`quantities.model == "channel_cover"`，`quantities.values` 為計算器輸入。
"""

import argparse
import json
import math
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

L_SLAB = "30_溝蓋混凝土"
L_HATCH = "31_溝蓋剖面線"
L_WALL = "35_既有溝壁"
L_REBAR = "40_鋼筋"
L_ANCHOR = "41_植筋"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

#: 溝壁下段示意高度（m）：計算器沒有溝深輸入，只畫示意段並於說明欄註明。
WALL_STUB_M = 0.60


# --------------------------------------------------------------------------- #
# 案件 → 引擎結果
# --------------------------------------------------------------------------- #
def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") != "channel_cover":
        raise SystemExit("本工具只做溝蓋詳圖（quantities.model 應為 channel_cover，現在是 %r）"
                         % q.get("model"))
    return case, dict(q.get("values") or {})


def run_engine(values):
    import design_api as D

    env = D.run_calculation("channel_cover", values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or res.get("schema") != "civil-design-channel-cover/1":
        raise SystemExit("channel_cover 引擎沒有回傳結果，無法出圖。")
    return res


def _g(x, nd=0):
    """數值轉字串：整數不帶小數點（120.0 → 120）。"""
    x = float(x)
    return ("%d" % round(x)) if abs(x - round(x)) < 1e-9 and nd == 0 else ("%.*f" % (nd or 1, x))


def _limit(r, key):
    """checks[] 中 item 含 key 者的 limit（圖上限值一律取結果，不寫死）。"""
    for c in r.get("checks", []):
        if key in str(c.get("item", "")):
            return float(c["limit"])
    raise KeyError(key)


def labels(r):
    """圖上所有「來自結果的標註字串」。自測以此 + 結果原欄位逐項核對。"""
    s, a = r["slab"], r["anchors"]
    ma, di, tp = s["main"], s["distribution"], s["top"]
    return {
        "main": "主筋 %s@%s（沿溝長）" % (ma["bar"], _g(ma["spacing_mm"])),
        "dist": "分佈筋 %s@%s" % (di["bar"], _g(di["spacing_mm"])),
        "top": "頂筋 %s@%s" % (tp["bar"], _g(tp["spacing_mm"])),
        "anchor": "植筋 %s@%s" % (a["bar"], _g(a["spacing_mm"])),
        "embed": "埋深 %s" % _g(a["embedment_mm"]),
        "hole": "孔徑 %%%%c%s" % _g(a["hole_diameter_mm"]),
        "edge": "邊距 %s" % _g(a["edge_mm"]),
        "cover": "保護層 %s" % _g(r["geometry"]["cover_mm"]),
    }


# --------------------------------------------------------------------------- #
# 模型空間
# --------------------------------------------------------------------------- #
def ensure_layers(doc):
    spec = [(L_SLAB, 5), (L_HATCH, 8), (L_WALL, 5), (L_REBAR, 1), (L_ANCHOR, 1),
            (L_DIM, 3), (L_NOTE, 7), (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7),
            (MWS.L_DESC, 7)]
    for name, color in spec:
        DR.add_plot_layer(doc, name, color=color)


def geometry(r):
    gm = r["geometry"]
    return {
        "Wt": gm["total_width_m"], "B": gm["clear_width_m"],
        "tw": gm["wall_thickness_m"], "t": gm["slab_thickness_mm"] / 1000.0,
        "cover": gm["cover_mm"] / 1000.0, "S": gm["bearing_center_m"],
        "hw": WALL_STUB_M,
    }


def label_width_m(r, scale):
    """右側標註文字估算寬度（模型 m）：最長標註 × 字寬（SHX 中文保守 ×1.1）。"""
    longest = max(len(v) for v in labels(r).values())
    return (longest * 3.0 * 1.1) * scale / 1000.0 + 0.5


def draw_section(doc, r, scale, dimstyle):
    msp = doc.modelspace()
    g = geometry(r)
    s, a = r["slab"], r["anchors"]
    Wt, tw, t, hw, cv = g["Wt"], g["tw"], g["t"], g["hw"], g["cover"]
    yb, yt = hw, hw + t                       # 蓋版底、頂
    th = DR.model_h(3.0, scale)              # 3 mm 字高（模型 m）
    hatch_scale = max((1.5 * scale / 1000.0) / 3.175, 1e-4)

    # ---- 既有溝壁（兩側）----
    walls = [(0.0, tw), (Wt - tw, Wt)]
    for x0, x1 in walls:
        poly = [(x0, 0.0), (x1, 0.0), (x1, yb), (x0, yb)]
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer": L_WALL})
        h = msp.add_hatch(color=256, dxfattribs={"layer": L_WALL})
        h.set_pattern_fill("ANSI33", color=256, scale=hatch_scale)
        h.paths.add_polyline_path(poly, is_closed=True)

    # ---- 蓋版 ----
    slab = [(0.0, yb), (Wt, yb), (Wt, yt), (0.0, yt)]
    msp.add_lwpolyline(slab, close=True, dxfattribs={"layer": L_SLAB})
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=hatch_scale)
    h.paths.add_polyline_path(slab, is_closed=True)

    # ---- 鋼筋（斷面示意）----
    d_main = s["main"]["db_mm"] / 1000.0
    d_dist = s["distribution"]["db_mm"] / 1000.0
    d_top = s["top"]["db_mm"] / 1000.0
    y_main = yb + cv + d_main / 2.0
    y_dist = yb + cv + d_main + d_dist / 2.0
    y_top = yt - cv - d_top / 2.0
    # 主筋：垂直車行方向，橫跨溝寬 → 斷面中是一條線
    msp.add_line((cv, y_main), (Wt - cv, y_main), dxfattribs={"layer": L_REBAR})
    # 分佈筋／頂筋：沿溝長 → 斷面中是圓點，間距取結果
    def dots(y, db, spacing_mm):
        sp, n, x = spacing_mm / 1000.0, 0, cv + db / 2.0
        while x <= Wt - cv - db / 2.0 + 1e-9:
            msp.add_circle((x, y), db / 2.0, dxfattribs={"layer": L_REBAR})
            x += sp
            n += 1
        return n
    n_dist = dots(y_dist, d_dist, s["distribution"]["spacing_mm"])
    n_top = dots(y_top, d_top, s["top"]["spacing_mm"])

    # ---- 植筋（每側溝壁頂一支剖面）----
    da = a["diameter_mm"] / 1000.0
    hole = a["hole_diameter_mm"] / 1000.0
    emb = a["embedment_mm"] / 1000.0
    edge = a["edge_mm"] / 1000.0
    anchor_x = []
    for side, (x0, x1) in zip(("L", "R"), walls):
        # 邊距＝植筋中心到溝壁「外側」面；左壁由 x0 起，右壁由 x1 起往內
        cx = x0 + edge if side == "L" else x1 - edge
        anchor_x.append(cx)
        msp.add_lwpolyline([(cx - hole / 2, yb), (cx - hole / 2, yb - emb),
                            (cx + hole / 2, yb - emb), (cx + hole / 2, yb)],
                           dxfattribs={"layer": L_ANCHOR})
        msp.add_lwpolyline([(cx - da / 2, yb - emb), (cx - da / 2, yt - cv),
                            (cx + da / 2, yt - cv), (cx + da / 2, yb - emb)],
                           close=True, dxfattribs={"layer": L_ANCHOR})

    # ---- 尺寸 ----
    def dim(p1, p2, base, angle=None):
        if angle is None:
            angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=dimstyle, dxfattribs={"layer": L_DIM})
        d.render()

    yb_base = -0.30
    dim((0.0, 0.0), (tw, 0.0), (0.0, -0.18))
    dim((tw, 0.0), (Wt - tw, 0.0), (0.0, -0.18))
    dim((Wt - tw, 0.0), (Wt, 0.0), (0.0, -0.18))
    dim((0.0, 0.0), (Wt, 0.0), (0.0, yb_base - 0.12))
    dim((0.0, yb), (0.0, yt), (-0.22, yb))                    # 蓋版厚
    dim((tw / 2.0, yt), (Wt - tw / 2.0, yt), (0.0, yt + 0.22))  # 支承中心距
    dim((0.0, yb - emb), (0.0, yb), (-0.22, yb))             # 植筋埋深

    # ---- 標註（引線＋文字）----
    L = labels(r)
    tx = Wt + 0.55

    def callout(text, p, ty):
        msp.add_line(p, (tx - 0.05, ty), dxfattribs={"layer": L_NOTE})
        t_ = msp.add_text(text, height=th, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t_.set_placement((tx, ty - th / 2.0), align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

    step = th * 2.2
    ty0 = yt + th
    callout(L["top"], (Wt - cv - 0.05, y_top), ty0)
    callout(L["dist"], (Wt - cv - 0.12, y_dist), ty0 - step)
    callout(L["main"], (Wt - cv, y_main), ty0 - 2 * step)
    callout("%s  %s" % (L["anchor"], L["embed"]), (anchor_x[1], yb - emb / 2.0), ty0 - 3.6 * step)
    callout("%s  %s" % (L["hole"], L["edge"]), (anchor_x[1] + hole / 2.0, yb - emb + 0.03),
            ty0 - 4.8 * step)
    callout(L["cover"], (Wt - cv / 2.0, yt - cv / 2.0), ty0 - 6.0 * step)
    return {"geom": g, "n_dist": n_dist, "n_top": n_top, "anchor_x": anchor_x}


# --------------------------------------------------------------------------- #
# 右欄表格（用 make_box_section.build_paper 的 blocks 通道）
# --------------------------------------------------------------------------- #
def build_blocks(r):
    s, a = r["slab"], r["anchors"]
    ma, di, tp = s["main"], s["distribution"], s["top"]
    gm, ld = r["geometry"], r["loads"]
    rebar_rows = [
        [(0.0, "1"), (9.0, "主筋（橫跨溝寬）"), (60.0, ma["bar"]),
         (76.0, _g(ma["spacing_mm"])), (100.0, "%.0f" % ma["As_prov_mm2"])],
        [(0.0, "2"), (9.0, "分佈筋（沿溝長）"), (60.0, di["bar"]),
         (76.0, _g(di["spacing_mm"])), (100.0, "%.0f" % di["As_prov_mm2"])],
        [(0.0, "3"), (9.0, "頂筋（溫度筋）"), (60.0, tp["bar"]),
         (76.0, _g(tp["spacing_mm"])), (100.0, "%.0f" % tp["As_prov_mm2"])],
    ]
    t = a["tension"]
    anchor_rows = [
        [(0.0, "規格"), (50.0, "%s@%s" % (a["bar"], _g(a["spacing_mm"])))],
        [(0.0, "埋深／孔徑"), (50.0, "%s／%%%%c%s mm" % (_g(a["embedment_mm"]), _g(a["hole_diameter_mm"])))],
        [(0.0, "邊距"), (50.0, "%s mm" % _g(a["edge_mm"]))],
        [(0.0, "每公尺根數"), (50.0, "%.2f" % a["per_meter"])],
        [(0.0, "拉力需求／容量"), (50.0, "%.2f／%.2f kN/根" % (a["tension_demand_kN"], t["capacity_kN"]))],
        [(0.0, "拉剪互制 實際／限值"), (50.0, "%.3f／%s" % (a["interaction"], _g(_limit(r, "植筋拉剪互制"), 1)))],
        [(0.0, "控制模式"), (50.0, str(t.get("governed_by", "")))],
    ]
    design_rows = [
        [(0.0, "有效跨徑 S"), (50.0, "%.3f m" % gm["effective_span_m"])],
        [(0.0, "設計彎矩 Mu"), (50.0, "%.2f kN·m/m" % ld["design_moment_kNm"])],
        [(0.0, "φMn"), (50.0, "%.2f kN·m/m（使用率 %.3f）" % (s["main"]["phiMn_kNm"], s["main"]["utilization"]))],
        [(0.0, "剪力 Vu／φVc"), (50.0, "%.2f／%.2f kN/m" % (s["shear"]["Vu_kN_m"], s["shear"]["phiVc_kN_m"]))],
        [(0.0, "裂縫 w"), (50.0, "%.2f／%.2f mm" % (s["crack"]["w_mm"], s["crack"]["limit_mm"]))],
        [(0.0, "撓度 δ"), (50.0, "%.1f／%.1f mm" % (s["deflection"]["delta_mm"], s["deflection"]["limit_mm"]))],
    ]
    return [
        {"title": "配筋表（每公尺）",
         "header": [(0.0, "編號"), (9.0, "位置"), (60.0, "筋號"), (76.0, "間距(mm)"),
                    (100.0, "As(mm2/m)")], "rows": rebar_rows},
        {"title": "植筋規格", "rows": anchor_rows},
        {"title": "設計摘要", "rows": design_rows},
    ]


def build_notes(r):
    notes = ["1. 本圖為溝蓋版斷面與配筋／植筋詳圖，每公尺長；尺寸單位為公尺（m）。",
             "2. 圖上標註數值皆取自 channel_cover 設計結果；%s。" % (
                 "全部檢核通過" if r.get("pass") else "有未通過項目，不得施工")]
    notes += ["%d. %s" % (3 + i, w) for i, w in enumerate(r.get("design_notes", [])[:4])]
    k = 3 + len(r.get("design_notes", [])[:4])
    notes += [
        "%d. 溝壁下段高度為示意（%.1f m），計算器無溝深輸入，現地依實況。" % (k, WALL_STUB_M),
        "%d. 植筋伸入蓋版長度與主筋端部彎鉤未由計算結果決定，圖未標註，施工前由技師另行指示。" % (k + 1),
        "%d. 頂筋方向計算結果未指定，圖示為與分佈筋同向之示意。" % (k + 2),
    ]
    return notes


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="溝蓋版詳圖（C-01）產線")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--unit", default="m", choices=["m", "cm"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--drafter", default="Claude（AI）")
    ap.add_argument("--sheet-no", default=None)
    ap.add_argument("--rebar", action="store_true", help="（保留，與其他出圖工具介面一致）")
    ap.add_argument("--template", default=MWS.TEMPLATE)
    a = ap.parse_args()

    case, values = load_values(a.case)
    r = run_engine(values)
    g = geometry(r)

    if str(a.scale).lower() == "auto":
        for sc in DR.STANDARD_SCALES:
            mw = g["Wt"] + 0.55 + label_width_m(r, sc) + 0.4
            mh = g["hw"] + g["t"] + 1.3
            if mw * 1000.0 / sc <= 183.0 and mh * 1000.0 / sc <= 249.45:
                a.scale = sc
                break
        else:
            a.scale = max(DR.STANDARD_SCALES)
        print("自動比例：採 1:%d" % a.scale)
    else:
        a.scale = int(a.scale)
        DR.require_standard_scale(a.scale)

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
    ds = MWS.ensure_dimstyle(doc, a.scale, a.unit)
    info = draw_section(doc, r, a.scale, ds)

    proj = a.project or (case.get("project") or {}).get("full_name") or "溝蓋工程"
    sheet_no = a.sheet_no or "C-01"
    MBS.build_paper(doc, g, case, a.scale, proj, sheet_no,
                    {"blocks": build_blocks(r), "notes": build_notes(r)},
                    "溝蓋版詳圖", "C-01", unit=a.unit, drafter=a.drafter)

    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  溝寬 %.2f 溝壁厚 %.2f 版厚 %.3f 跨徑 %.3f 比例 1/%d　分佈筋 %d 點／頂筋 %d 點"
          % (g["B"], g["tw"], g["t"], g["S"], a.scale, info["n_dist"], info["n_top"]))

    if a.publish:
        sys.path.insert(0, os.path.join(ROOT, "tools", "acad"))
        from acc import publish
        res = publish(out, pdf=True)
        print("PUBLISH", res)
        try:
            import fitz
            pg = fitz.open(res[".pdf"])[0]
            png = os.path.splitext(out)[0] + "_pdf.png"
            pg.get_pixmap(dpi=110).save(png)
            print("PDF 預覽 %s" % png)
        except Exception as ex:
            print("PDF 轉圖略過", ex)


if __name__ == "__main__":
    main()
