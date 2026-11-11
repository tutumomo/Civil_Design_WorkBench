# -*- coding: utf-8 -*-
"""基腳圖（D5）：獨立基腳 F-1、聯合基腳 F-2（平面＋剖面＋配筋標註）。

圖上數值來源
------------
* 配筋：引擎 `concrete.flexure`（bar、spacing_mm，每公尺寬）— 不另挑鋼筋。
  獨立基腳雙向同配；聯合基腳另取 `beam_design.flexure` 作縱向底筋、`beam_design.shear` 作箍筋摘要。
* 尺寸：`geometry`（B、L、thickness、柱斷面）；聯合基腳柱位取 `columns[].x_m`。
* 保護層：計算器 `cover_mm`；沒填用引擎預設 40 mm 並於說明欄標「假設值」。
* 計算結果沒決定的元素（柱腳插筋、頂筋、柱偏心位置、基腳下級配）不繪、不標數值，說明欄明寫。
  獨立基腳柱假設居中；聯合基腳引擎沒有柱斷面尺寸，柱位僅以中心線示意。

用法
----
    .venv/bin/python tools/foundation_section/make_foundation.py <case.json> --out out/<案名>/F-1.dxf
案件檔：`quantities.model` 為 `foundation_isolated` 或 `foundation_combined`。
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

L_CONC = "30_基腳混凝土"
L_HATCH = "31_基腳剖面線"
L_COL = "32_柱"
L_REBAR = "40_鋼筋"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

DEFAULT_COVER_MM = 40.0                        # 與引擎 foundation_design 預設相同
BAR_DIA = {"D10": 9.53, "D13": 12.7, "D16": 15.9, "D19": 19.1, "D22": 22.2,
           "D25": 25.4, "D29": 28.7, "D32": 32.2, "D36": 35.8}
KINDS = ("foundation_isolated", "foundation_combined")
STUB_M = 0.35                                   # 剖面柱腳示意高度


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") not in KINDS:
        raise SystemExit("本工具只做基腳（model 應為 %s，現在是 %r）" % ("／".join(KINDS), q.get("model")))
    return case, q["model"], dict(q.get("values") or {})


def run_engine(kind, values):
    import design_api as D

    env = D.run_calculation(kind, values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or "concrete" not in res:
        raise SystemExit("%s 引擎沒有可用結果。" % kind)
    return res


def _g(x):
    x = float(x)
    return "%d" % round(x) if abs(x - round(x)) < 1e-9 else "%.1f" % x


def cover_of(values):
    c = values.get("cover_mm")
    return (float(c), False) if c not in (None, "") else (DEFAULT_COVER_MM, True)


def layout(kind, res, values):
    """純計算：圖面所需的幾何與配筋（自測直接呼叫）。"""
    gm = res["geometry"]
    cover, assumed = cover_of(values)
    fl = res["concrete"]["flexure"]
    lay = {"kind": kind, "t": float(gm["thickness_m"]), "cover": cover / 1000.0,
           "cover_assumed": assumed, "bar": fl["bar"], "db": BAR_DIA[fl["bar"]] / 1000.0,
           "spacing": float(fl["spacing_mm"]), "d_mm": float(res["concrete"]["d_mm"])}
    if kind == "foundation_isolated":
        lay.update(B=float(gm["B_m"]), L=float(gm["L_m"]),
                   cb=float(gm["column_b_m"]), cl=float(gm["column_l_m"]))
    else:
        lay.update(B=float(gm["B_m"]), L=float(gm["L_m"]),
                   cols=[(float(c["x_m"]), float(c["P_kN"])) for c in res["columns"]])
        bf = res["beam_design"]["flexure"]
        st = res["beam_design"]["shear"]["stirrup"]
        lay.update(lbar=bf["bar"], lspacing=float(bf["spacing_mm"]),
                   tie=st["bar"], tie_spacing=float(st["spacing_mm"]), legs=int(st["legs"]))
    return lay


def dot_positions(width_m, cover_m, db_m, spacing_mm):
    """沿 width 方向、自保護層起每 spacing 一支（端部不超出保護層）。"""
    xs, x, sp = [], cover_m + db_m / 2.0, spacing_mm / 1000.0
    while x <= width_m - cover_m - db_m / 2.0 + 1e-9:
        xs.append(x)
        x += sp
    return xs


def labels(lay):
    if lay["kind"] == "foundation_isolated":
        return {"bot": "底筋雙向 %s@%s" % (lay["bar"], _g(lay["spacing"])),
                "cover": "保護層 %s" % _g(lay["cover"] * 1000.0),
                "col": "柱 %s×%s" % (_g(lay["cb"] * 1000.0), _g(lay["cl"] * 1000.0))}
    return {"trans": "橫向底筋 %s@%s" % (lay["bar"], _g(lay["spacing"])),
            "long": "縱向底筋 %s@%s" % (lay["lbar"], _g(lay["lspacing"])),
            "cover": "保護層 %s" % _g(lay["cover"] * 1000.0)}


def ensure_layers(doc):
    for name, color in [(L_CONC, 5), (L_HATCH, 8), (L_COL, 5), (L_REBAR, 1), (L_DIM, 3),
                        (L_NOTE, 7), (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def draw(doc, lay, scale, dimstyle):
    msp = doc.modelspace()
    iso = lay["kind"] == "foundation_isolated"
    B, L, t, c, db = lay["B"], lay["L"], lay["t"], lay["cover"], lay["db"]
    th = DR.model_h(3.0, scale)
    hs = max((1.5 * scale / 1000.0) / 3.175, 1e-4)
    Lab = labels(lay)

    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=dimstyle,
                               dxfattribs={"layer": L_DIM})
        d.render()

    def text(s, p):
        tt = msp.add_text(s, height=th, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        tt.set_placement(p, align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

    def callout(s, p, q):
        msp.add_line(p, q, dxfattribs={"layer": L_NOTE})
        text(s, (q[0] + 0.05, q[1] - th / 2.0))

    # 平面：x 向取 L（聯合）或 B（獨立）為橫軸，y 向為另一邊
    W, Hh = (B, L) if iso else (L, B)
    plan = [(0, 0), (W, 0), (W, Hh), (0, Hh)]
    msp.add_lwpolyline(plan, close=True, dxfattribs={"layer": L_CONC})
    if iso:
        x0, y0 = (W - lay["cb"]) / 2.0, (Hh - lay["cl"]) / 2.0
        msp.add_lwpolyline([(x0, y0), (x0 + lay["cb"], y0), (x0 + lay["cb"], y0 + lay["cl"]),
                            (x0, y0 + lay["cl"])], close=True, dxfattribs={"layer": L_COL})
        # 底筋示意：每向各畫兩支，標註取結果
        for off in (c + db, Hh - c - db):
            msp.add_line((c, off), (W - c, off), dxfattribs={"layer": L_REBAR})
        for off in (c + db, W - c - db):
            msp.add_line((off, c), (off, Hh - c), dxfattribs={"layer": L_REBAR})
        dim((0, 0), (W, 0), (0, -0.30))
        dim((0, 0), (0, Hh), (-0.30, 0))
        callout(Lab["bot"], (W - c - db, Hh * 0.7), (W + 0.35, Hh * 0.7))
        callout(Lab["col"], (x0 + lay["cb"], y0 + lay["cl"]), (W + 0.35, Hh * 0.9))
        sec_x0 = 0.0
        sw = W
    else:
        for x, p in lay["cols"]:
            msp.add_line((x, -0.1), (x, Hh + 0.1), dxfattribs={"layer": L_COL})
            text("P=%s kN" % _g(p), (x + 0.05, Hh + 0.12))
        for off in (c + db, Hh - c - db):
            msp.add_line((c, off), (W - c, off), dxfattribs={"layer": L_REBAR})
        dim((0, 0), (W, 0), (0, -0.30))
        dim((0, 0), (0, Hh), (-0.30, 0))
        callout(Lab["long"], (W - c - db, Hh - c - db), (W + 0.35, Hh * 0.8))
        sec_x0 = 0.0
        sw = W
    # 剖面：置於平面下方
    sb = -(1.5 + t)
    sec = [(sec_x0, sb), (sec_x0 + sw, sb), (sec_x0 + sw, sb + t), (sec_x0, sb + t)]
    msp.add_lwpolyline(sec, close=True, dxfattribs={"layer": L_CONC})
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=hs)
    h.paths.add_polyline_path(sec, is_closed=True)
    if iso:
        cx0 = sec_x0 + (sw - lay["cb"]) / 2.0
        msp.add_lwpolyline([(cx0, sb + t), (cx0, sb + t + STUB_M), (cx0 + lay["cb"], sb + t + STUB_M),
                            (cx0 + lay["cb"], sb + t)], dxfattribs={"layer": L_COL})
    else:
        for x, _p in lay["cols"]:
            msp.add_line((x, sb + t), (x, sb + t + STUB_M), dxfattribs={"layer": L_COL})
    y1 = sb + c + db / 2.0                       # 沿剖面方向的底筋（線）
    y2 = y1 + db                                 # 垂直剖面方向的底筋（點）
    msp.add_line((sec_x0 + c, y1), (sec_x0 + sw - c, y1), dxfattribs={"layer": L_REBAR})
    n = 0
    for x in dot_positions(sw, c, db, lay["spacing"]):
        msp.add_circle((sec_x0 + x, y2), db / 2.0, dxfattribs={"layer": L_REBAR})
        n += 1
    dim((sec_x0, sb), (sec_x0 + sw, sb), (0, sb - 0.30))
    dim((sec_x0, sb), (sec_x0, sb + t), (-0.30, sb))
    callout(Lab["trans"] if not iso else Lab["bot"], (sec_x0 + sw - c - 0.05, y2), (sec_x0 + sw + 0.35, sb + t * 0.6))
    callout(Lab["cover"], (sec_x0 + sw - c / 2.0, sb + c / 2.0), (sec_x0 + sw + 0.35, sb + t * 0.2))
    return {"n_dots": n, "sec_base": sb}


def build_blocks(lay, res):
    cc = res["concrete"]
    fl = cc["flexure"]
    rows = [("斷面", "B×L×t %s×%s×%s m" % (_g_m(lay["B"]), _g_m(lay["L"]), _g_m(lay["t"]))),
            ("有效深度 d", "%s mm" % _g(cc["d_mm"])),
            ("底筋（橫）", "%s@%s（As=%.0f mm2/m）" % (lay["bar"], _g(lay["spacing"]), fl["As_prov_mm2"])),
            ("φMn／Mu", "%.1f／%.1f kN·m/m（%.3f）" % (fl["phiMn_kNm"], fl["Mu_kNm"], fl["utilization"])),
            ("沖剪 Vp／φVn", "%.0f／%.0f kN" % (cc["punching_force_kN"], cc["punching_capacity_kN"]))]
    if lay["kind"] == "foundation_combined":
        rows.insert(3, ("底筋（縱）", "%s@%s" % (lay["lbar"], _g(lay["lspacing"]))))
        rows.append(("箍筋摘要", "%s@%s %d 肢" % (lay["tie"], _g(lay["tie_spacing"]), lay["legs"])))
    q = res["pressure"]
    rows.append(("基底壓力 max／min", "%.1f／%.1f kPa" % (q["q_max_kpa"], q["q_min_kpa"])))
    title = "獨立基腳摘要" if lay["kind"] == "foundation_isolated" else "聯合基腳摘要"
    return [{"title": title, "rows": [[(0.0, k), (50.0, v)] for k, v in rows]}]


def _g_m(x):
    return ("%.3f" % float(x)).rstrip("0").rstrip(".")


def build_notes(lay, res):
    iso = lay["kind"] == "foundation_isolated"
    n = ["1. 本圖為%s平面與剖面配筋圖，圖上尺寸單位為公尺（m）、配筋表單位為毫米（mm），比例見標題欄。"
         % ("獨立基腳" if iso else "聯合基腳"),
         "2. 圖上標註數值皆取自設計計算結果；%s。" % ("全部檢核通過" if res.get("pass") else "有未通過項目，不得施工")]
    if lay["cover_assumed"]:
        n.append("%d. 假設值：保護層 %s mm（計算器未輸入、採引擎預設），須依設計確認。"
                 % (len(n) + 1, _g(lay["cover"] * 1000.0)))
    n.append("%d. 底筋示意線僅表示方向，實際根數依標註間距；柱腳插筋、頂筋、彎鉤與錨定計算結果未提供，圖未繪。" % (len(n) + 1))
    if iso:
        n.append("%d. 柱假設位於基腳中心（計算器無柱偏心輸入）；彎矩僅反映在基底壓力。" % (len(n) + 1))
    else:
        n.append("%d. 計算器無柱斷面尺寸，柱位僅以中心線示意；縱向底筋取 beam_design，橫向取 concrete 檢核。" % (len(n) + 1))
    n.append("%d. 初步設計，地質承載力須由地質報告確認；基礎下級配與墊層未計。" % (len(n) + 1))
    return n


def main():
    ap = argparse.ArgumentParser(description="基腳圖（D5）")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--unit", default="m", choices=["m", "cm"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--drafter", default="Claude（AI）")
    ap.add_argument("--sheet-no", default=None)
    ap.add_argument("--rebar", action="store_true")
    ap.add_argument("--template", default=MWS.TEMPLATE)
    a = ap.parse_args()

    case, kind, values = load_values(a.case)
    res = run_engine(kind, values)
    lay = layout(kind, res, values)
    iso = kind == "foundation_isolated"
    W, Hh = (lay["B"], lay["L"]) if iso else (lay["L"], lay["B"])

    def need(sc):
        lw = max(len(v) for v in labels(lay).values()) * 3.0 * 1.1 * sc / 1000.0
        mw = W + 0.35 + lw + 0.8
        mh = Hh + 1.5 + lay["t"] + STUB_M + 1.2
        return mw * 1000.0 / sc <= 183.0 and mh * 1000.0 / sc <= 249.45

    if str(a.scale).lower() == "auto":
        a.scale = next((s for s in DR.STANDARD_SCALES if need(s)), max(DR.STANDARD_SCALES))
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
    info = draw(doc, lay, a.scale, ds)

    no = a.sheet_no or ("F-1" if iso else "F-2")
    proj = a.project or (case.get("project") or {}).get("full_name") or "基腳"
    MBS.build_paper(doc, {}, case, a.scale, proj, no,
                    {"blocks": build_blocks(lay, res), "notes": build_notes(lay, res)},
                    "獨立基腳配筋圖" if iso else "聯合基腳配筋圖", no,
                    unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  %s B=%.2f L=%.2f t=%.2f 底筋 %s@%s 比例 1/%d　剖面點數 %d" % (
        "獨立基腳" if iso else "聯合基腳", lay["B"], lay["L"], lay["t"], lay["bar"],
        _g(lay["spacing"]), a.scale, info["n_dots"]))
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
