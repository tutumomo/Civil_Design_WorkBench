# -*- coding: utf-8 -*-
"""RC 梁（B-01）、柱（CL-1）斷面配筋圖產線（D4）：計算器輸入 → A3 DXF/DWG/PDF。

圖上數值來源
------------
* 柱：`rc_column` 結果 `chosen`（bar、bars_per_face、bars_total、centre_spacing_mm）與 `ties`；
  主筋點位直接用引擎的 `centre_spacing_mm` 排，不另算。
* 梁：`rc_beam` 結果 `flexure`／`shear`／`crack`。**引擎沒有回傳梁主筋支數**
  （`spacing_mm`／`As_prov_mm2` 是以每公尺寬為基準的選筋結果，對梁沒有意義），
  繪圖端以 `n = ceil(As_design / 單支面積)` 推算支數，**圖與說明欄皆明寫「支數由繪圖端推算」**，
  並以 `As_prov(n) ≥ As_design` 與淨距規定把關；排不下則拒絕出圖。
* 保護層：計算器輸入 `cover_mm`；沒填用 40 mm 並於說明欄標「假設值」。
* 計算結果沒決定的元素（梁上層架立筋、箍筋彎鉤、柱箍筋型式）不繪、不標數值，說明欄明寫。

用法
----
    .venv/bin/python tools/rc_section/make_rc_section.py <case.json> --out out/<案名>/B-01.dxf
案件檔：`quantities.model` 為 `rc_beam` 或 `rc_column`，`quantities.values` 為計算器輸入。
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

L_CONC = "30_構材混凝土"
L_HATCH = "31_構材剖面線"
L_REBAR = "40_鋼筋"
L_TIE = "41_箍筋"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

DEFAULT_COVER_MM = 40.0
BAR_DIA = {"D10": 9.53, "D13": 12.7, "D16": 15.9, "D19": 19.1, "D22": 22.2,
           "D25": 25.4, "D29": 28.7, "D32": 32.2, "D36": 35.8}
BAR_AREA = {"D10": 71.0, "D13": 127.0, "D16": 199.0, "D19": 287.0, "D22": 387.0,
            "D25": 507.0, "D29": 645.0, "D32": 794.0, "D36": 1006.0}
MIN_CLEAR_MM = 25.0


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") not in ("rc_beam", "rc_column"):
        raise SystemExit("本工具只做 RC 梁／柱斷面（model 應為 rc_beam／rc_column，現在是 %r）"
                         % q.get("model"))
    return case, q["model"], dict(q.get("values") or {})


def run_engine(kind, values):
    import design_api as D

    env = D.run_calculation(kind, values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or res.get("ok") is False:
        raise SystemExit("%s 引擎沒有可用結果：%s" % (kind, (res or {}).get("error", "")))
    return res


def _g(x):
    x = float(x)
    return "%d" % round(x) if abs(x - round(x)) < 1e-9 else "%.1f" % x


def cover_of(values):
    c = values.get("cover_mm")
    return (float(c), False) if c not in (None, "") else (DEFAULT_COVER_MM, True)


# --------------------------------------------------------------------------- #
# 配筋排列（純計算，自測直接呼叫）
# --------------------------------------------------------------------------- #
def beam_layout(res, values):
    fl, sh = res["flexure"], res["shear"]
    b, h = float(fl["b_mm"]), float(fl["h_mm"])
    cover, assumed = cover_of(values)
    bar = fl["bar"]
    db, area = BAR_DIA[bar], BAR_AREA[bar]
    tie = sh["stirrup"]["bar"]
    dt = BAR_DIA[tie]
    n = max(2, int(math.ceil(float(fl["As_design_mm2"]) / area - 1e-9)))
    avail = b - 2.0 * (cover + dt) - db            # 首末支中心距
    clear = avail / (n - 1) - db
    if clear < max(MIN_CLEAR_MM, db):
        raise SystemExit("梁寬 %.0f 單層排不下 %d-%s（淨距 %.1f mm < %.1f mm），"
                         "請加寬或改大號筋後重算。" % (b, n, bar, clear, max(MIN_CLEAR_MM, db)))
    y = cover + dt + db / 2.0
    xs = [cover + dt + db / 2.0 + i * avail / (n - 1) for i in range(n)]
    return {"b": b, "h": h, "cover": cover, "cover_assumed": assumed, "bar": bar, "db": db,
            "n": n, "pts": [(x, y) for x in xs], "tie": tie, "dt": dt,
            "tie_spacing": sh["stirrup"]["spacing_mm"], "legs": sh["stirrup"]["legs"],
            "As_prov_n": n * area, "clear": clear}


def column_layout(res, values):
    ch, ti = res["chosen"], res["ties"]
    b, h = float(res["b_mm"]), float(res["h_mm"])
    cover, assumed = cover_of(values)
    bar, nf = ch["bar"], int(ch["bars_per_face"])
    db = BAR_DIA[bar]
    dt = BAR_DIA[ti["bar"]]
    sp = float(ch["centre_spacing_mm"])
    x0 = (b - (nf - 1) * sp) / 2.0                 # 引擎間距，對稱置中
    d1 = cover + 10.0 + db / 2.0                   # 與引擎 column_design 相同的 y 向算式
    pts = [(x0 + i * sp, d1) for i in range(nf)] + [(x0 + i * sp, h - d1) for i in range(nf)]
    return {"b": b, "h": h, "cover": cover, "cover_assumed": assumed, "bar": bar, "db": db,
            "nf": nf, "n": 2 * nf, "pts": pts, "tie": ti["bar"], "dt": dt,
            "tie_spacing": ti["spacing_mm"], "sp": sp}


def labels(kind, res, lay):
    if kind == "rc_beam":
        return {"main": "主筋 %d-%s" % (lay["n"], lay["bar"]),
                "tie": "箍筋 %s@%s（%d 肢）" % (lay["tie"], _g(lay["tie_spacing"]), lay["legs"]),
                "cover": "保護層 %s" % _g(lay["cover"])}
    return {"main": "主筋 %d-%s（每面 %d 支）" % (lay["n"], lay["bar"], lay["nf"]),
            "tie": "箍筋 %s@%s" % (lay["tie"], _g(lay["tie_spacing"])),
            "cover": "保護層 %s" % _g(lay["cover"])}


def ensure_layers(doc):
    for name, color in [(L_CONC, 5), (L_HATCH, 8), (L_REBAR, 1), (L_TIE, 1), (L_DIM, 3),
                        (L_NOTE, 7), (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def draw_section(doc, kind, res, lay, scale, dimstyle):
    msp = doc.modelspace()
    m = 1.0 / 1000.0
    b, h, c, dt, db = lay["b"] * m, lay["h"] * m, lay["cover"] * m, lay["dt"] * m, lay["db"] * m
    th = DR.model_h(3.0, scale)
    outer = [(0, 0), (b, 0), (b, h), (0, h)]
    msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": L_CONC})
    hh = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    hh.set_pattern_fill("ANSI31", color=256, scale=max((1.5 * scale / 1000.0) / 3.175, 1e-4))
    hh.paths.add_polyline_path(outer, is_closed=True)
    # 箍筋（外緣距混凝土面＝保護層）
    tie = [(c, c), (b - c, c), (b - c, h - c), (c, h - c)]
    msp.add_lwpolyline(tie, close=True, dxfattribs={"layer": L_TIE, "const_width": dt})
    for x, y in lay["pts"]:
        msp.add_circle((x * m, y * m), db / 2.0,
                       dxfattribs={"layer": L_REBAR})
        msp.add_circle((x * m, y * m), db / 2.0 * 0.45, dxfattribs={"layer": L_REBAR})

    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=dimstyle,
                               dxfattribs={"layer": L_DIM})
        d.render()

    dim((0, 0), (b, 0), (0, -0.20))
    dim((0, 0), (0, h), (-0.20, 0))
    L = labels(kind, res, lay)
    tx = b + 0.45
    step = th * 2.4

    def callout(text, p, ty):
        msp.add_line(p, (tx - 0.05, ty), dxfattribs={"layer": L_NOTE})
        t = msp.add_text(text, height=th, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t.set_placement((tx, ty - th / 2.0),
                        align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

    px, py = lay["pts"][-1][0] * m, lay["pts"][-1][1] * m
    mid = h / 2.0
    callout(L["cover"], (b - c / 2.0, h - c / 2.0), mid + step)
    callout(L["tie"], (b - c, mid), mid)
    callout(L["main"], (px + db / 2, py), mid - step)
    return lay


def build_blocks(kind, res, lay):
    rows = []
    if kind == "rc_beam":
        fl, sh, cr = res["flexure"], res["shear"], res["crack"]
        rows = [
            ("斷面 b×h", "%s×%s mm" % (_g(lay["b"]), _g(lay["h"]))),
            ("有效深度 d", "%s mm" % _g(fl["d_mm"])),
            ("主筋", "%d-%s（As=%.0f mm2）" % (lay["n"], lay["bar"], lay["As_prov_n"])),
            ("As 需求／最小", "%.1f／%.1f mm2" % (fl["As_req_mm2"], fl["As_min_mm2"])),
            ("φMn／Mu", "%.1f／%.1f kN·m（%.3f）" % (fl["phiMn_kNm"], fl["Mu_kNm"], fl["utilization"])),
            ("箍筋", "%s@%s %d 肢" % (lay["tie"], _g(lay["tie_spacing"]), lay["legs"])),
            ("φVn／Vu", "%.1f／%.1f kN（%.3f）" % (sh["phiVn_kN"], sh["Vu_kN"], sh["utilization"])),
            ("裂縫 w／限值", "%.2f／%.2f mm" % (cr["w_mm"], cr["limit_mm"])),
        ]
        title = "梁配筋摘要"
    else:
        ch = res["chosen"]
        rows = [
            ("斷面 b×h", "%s×%s mm" % (_g(lay["b"]), _g(lay["h"]))),
            ("主筋", "%d-%s（每面 %d 支）" % (lay["n"], lay["bar"], lay["nf"])),
            ("As／ρ", "%.0f mm2／%.4f" % (ch["As_mm2"], ch["ratio"])),
            ("橫向中心距", "%.1f mm（淨距限值 %.1f）" % (ch["centre_spacing_mm"], ch["min_spacing_mm"])),
            ("φMn／Mu", "%.1f／%.1f kN·m（%.3f）" % (ch["phiMn_available_kNm"], res["Mu_kNm"], ch["utilization"])),
            ("Pu", "%.0f kN" % res["Pu_kN"]),
            ("箍筋", "%s@%s" % (lay["tie"], _g(lay["tie_spacing"]))),
            ("控制", str(res.get("governing", ""))),
        ]
        title = "柱配筋摘要"
    return [{"title": title, "rows": [[(0.0, k), (50.0, v)] for k, v in rows]}]


def build_notes(kind, res, lay):
    n = ["1. 本圖為RC%s斷面配筋圖，圖上尺寸單位為公尺（m）、配筋表單位為毫米（mm），比例見標題欄。"
         % ("梁" if kind == "rc_beam" else "柱"),
         "2. 圖上標註數值皆取自設計計算結果；%s。" % ("全部檢核通過" if res.get("ok", True) else "有未通過項目，不得施工")]
    if lay["cover_assumed"]:
        n.append("%d. 假設值：保護層 %s mm（計算器未輸入、採預設），須依設計確認。"
                 % (len(n) + 1, _g(lay["cover"])))
    if kind == "rc_beam":
        n.append("%d. 主筋支數由繪圖端依 As_design／單支面積推算，計算器未直接輸出支數；施工前由技師確認。" % (len(n) + 1))
        n.append("%d. 上層架立筋與箍筋彎鉤計算結果未提供，圖未繪；耐震圍束、扭力、接頭與錨定另計。" % (len(n) + 1))
    else:
        n.append("%d. 主筋依引擎橫向中心距對稱排列；箍筋型式、彎鉤與繫筋未由計算結果決定，圖以外框示意。" % (len(n) + 1))
        n.append("%d. 僅單向彎矩、兩對邊配筋之初步設計；雙向彎矩、細長效應、接頭與耐震圍束另計。" % (len(n) + 1))
    return n


def main():
    ap = argparse.ArgumentParser(description="RC 梁／柱斷面配筋圖（D4）")
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
    lay = beam_layout(res, values) if kind == "rc_beam" else column_layout(res, values)
    b, h = lay["b"] / 1000.0, lay["h"] / 1000.0

    def need(sc):
        lw = max(len(v) for v in labels(kind, res, lay).values()) * 3.0 * 1.1 * sc / 1000.0
        return (b + 0.45 + lw + 0.4) * 1000.0 / sc <= 183.0 and (h + 0.6) * 1000.0 / sc <= 249.45

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
    draw_section(doc, kind, res, lay, a.scale, ds)

    beam = kind == "rc_beam"
    no = a.sheet_no or ("B-01" if beam else "CL-1")
    proj = a.project or (case.get("project") or {}).get("full_name") or "RC構材"
    MBS.build_paper(doc, {}, case, a.scale, proj, no,
                    {"blocks": build_blocks(kind, res, lay), "notes": build_notes(kind, res, lay)},
                    "RC梁斷面配筋圖" if beam else "RC柱斷面配筋圖", no,
                    unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  %s %.0f×%.0f mm 主筋 %d-%s 比例 1/%d" % ("梁" if beam else "柱", lay["b"], lay["h"],
                                              lay["n"], lay["bar"], a.scale))
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
