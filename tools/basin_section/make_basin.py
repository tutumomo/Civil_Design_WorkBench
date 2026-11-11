# -*- coding: utf-8 -*-
"""滯洪池 P-1、沉砂池 P-2 平面＋縱剖面圖（D6）。

圖上數值來源
------------
* 滯洪池 `detention_basin`：池底長寬、邊坡 H:V、壩頂高、孔口（口徑、底高）、堰（堰頂高、堰長）取自
  計算器輸入；計算最高水位 `max_stage_m`、尖峰入／出流、最大蓄水量、出水高檢核取自結果。
  高程一律以池底為 ±0.00（計算器為相對水位）。
* 沉砂池 `sediment_basin`：長 `length_m`、寬 `width_m`、深 `depth_m`、容量 `capacity_m3` 取自結果。
  引擎沒有池壁型式與邊坡，圖為「土池示意」（直壁），說明欄與圖上註明「池壁結構另行設計」。
* 計算結果未決定的元素（緊急溢洪道、出口工構造、壩頂寬、護坡）不繪不標，說明欄明寫。

用法
----
    .venv/bin/python tools/basin_section/make_basin.py <case.json> --out out/<案名>/P-1.dxf
案件檔 `quantities.model` 為 `detention_basin` 或 `sediment_basin`。
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

L_BASIN = "30_池體輪廓"
L_WATER = "33_水位"
L_OUTLET = "34_出口工"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"
KINDS = ("detention_basin", "sediment_basin")
GROUND_STUB_M = 1.0                            # 壩頂外側地面示意長度（無輸入，不標尺寸）


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") not in KINDS:
        raise SystemExit("本工具只做滯洪池／沉砂池（model 應為 %s，現在是 %r）"
                         % ("／".join(KINDS), q.get("model")))
    return case, q["model"], dict(q.get("values") or {})


def run_engine(kind, values):
    import design_api as D

    env = D.run_calculation(kind, values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or res.get("ok") is False:
        raise SystemExit("%s 引擎沒有可用結果：%s" % (kind, (res or {}).get("error", "")))
    return res


def _g(x, nd=2):
    return ("%.*f" % (nd, float(x)))


def _gi(x):
    x = float(x)
    return "%d" % round(x) if abs(x - round(x)) < 1e-9 else "%.1f" % x


def layout(kind, res, values):
    """純計算：幾何與高程標註（自測直接呼叫）。"""
    if kind == "sediment_basin":
        return {"kind": kind, "L": float(res["length_m"]), "W": float(res["width_m"]),
                "D": float(res["depth_m"]), "cap": float(res["capacity_m3"])}
    b, o = values["basin"], (values.get("outlet") or {})
    lay = {"kind": kind, "Lb": float(b["bottom_length_m"]), "Wb": float(b["bottom_width_m"]),
           "z": float(b["side_slope_h_v"]), "crest": float(b["dam_crest_m"]),
           "free": float(b.get("freeboard_min_m", 0.0)), "hwl": float(res["max_stage_m"]),
           "orifice": None, "weir": None}
    ori = o.get("orifice")
    if ori and float(ori.get("diameter_m", 0.0)) > 0:
        inv = float(ori.get("invert_m", 0.0))
        lay["orifice"] = {"d": float(ori["diameter_m"]), "invert": inv,
                          "count": int(ori.get("count", 1) or 1)}
    w = o.get("weir")
    if w:
        lay["weir"] = {"crest": float(w["crest_m"]), "length": float(w["length_m"])}
    lay["Wp"] = lay["Lb"] + 2.0 * lay["z"] * lay["crest"]
    lay["Hp"] = lay["Wb"] + 2.0 * lay["z"] * lay["crest"]
    return lay


def _el(el):
    return ("%+.2f" % el) if abs(el) > 1e-9 else "±0.00"


def levels(lay):
    """剖面右側高程標註（文字, 高程 m），皆取自輸入或結果。"""
    out = [("壩頂 %s" % _el(lay["crest"]), lay["crest"]),
           ("計算最高水位 %s" % _el(lay["hwl"]), lay["hwl"]),
           ("池底 %s" % _el(0.0), 0.0)]
    if lay["orifice"]:
        o = lay["orifice"]
        out.append(("孔口 %%%%c%s×%d 底 %s" % (_gi(o["d"] * 1000.0), o["count"], _el(o["invert"])),
                    o["invert"]))
    if lay["weir"]:
        out.append(("堰頂 %s 堰長 %s" % (_el(lay["weir"]["crest"]), _gi(lay["weir"]["length"])),
                    lay["weir"]["crest"]))
    return out


def ensure_layers(doc):
    for name, color in [(L_BASIN, 5), (L_WATER, 5), (L_OUTLET, 1), (L_DIM, 3), (L_NOTE, 7),
                        (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def _mk(doc, scale, dimstyle):
    msp = doc.modelspace()
    th = DR.model_h(3.0, scale)

    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=dimstyle,
                               dxfattribs={"layer": L_DIM})
        d.render()

    def text(s, p, layer=L_NOTE):
        t = msp.add_text(s, height=th, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement(p, align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

    return msp, th, dim, text


def draw_detention(doc, lay, scale, dimstyle):
    msp, th, dim, text = _mk(doc, scale, dimstyle)
    Lb, Wb, z, Hc = lay["Lb"], lay["Wb"], lay["z"], lay["crest"]
    Wp, Hp = lay["Wp"], lay["Hp"]
    off = z * Hc
    # 平面：池頂（外）與池底（內）
    msp.add_lwpolyline([(0, 0), (Wp, 0), (Wp, Hp), (0, Hp)], close=True, dxfattribs={"layer": L_BASIN})
    msp.add_lwpolyline([(off, off), (off + Lb, off), (off + Lb, off + Wb), (off, off + Wb)],
                       close=True, dxfattribs={"layer": L_BASIN})
    dim((0, 0), (Wp, 0), (0, -0.8))
    dim((0, 0), (0, Hp), (-0.8, 0))
    text("池底 %s×%s" % (_gi(Lb), _gi(Wb)), (off + 0.3, off + Wb / 2.0))
    # 剖面（沿長向，置於平面下方）
    sb = -(3.0 + Hc)                              # 剖面池底高程線在模型 y
    xl, xr = off, off + Lb
    prof = [(0.0, sb + Hc), (xl, sb), (xr, sb), (Wp, sb + Hc)]
    msp.add_lwpolyline(prof, dxfattribs={"layer": L_BASIN})
    msp.add_line((-GROUND_STUB_M, sb + Hc), (0.0, sb + Hc), dxfattribs={"layer": L_BASIN})
    msp.add_line((Wp, sb + Hc), (Wp + GROUND_STUB_M, sb + Hc), dxfattribs={"layer": L_BASIN})
    # 水位線（取結果）
    h = lay["hwl"]
    xw0, xw1 = xl - z * h, xr + z * h
    msp.add_line((xw0, sb + h), (xw1, sb + h), dxfattribs={"layer": L_WATER, "linetype": "DASHED"}
                 if "DASHED" in doc.linetypes else {"layer": L_WATER})
    # 孔口（右側邊坡）
    tx = Wp + GROUND_STUB_M + 0.5
    if lay["orifice"]:
        o = lay["orifice"]
        for yy in (o["invert"], o["invert"] + o["d"]):
            x_on = xr + z * yy
            msp.add_line((x_on, sb + yy), (x_on + 0.8, sb + yy), dxfattribs={"layer": L_OUTLET})
    if lay["weir"]:
        wc = lay["weir"]["crest"]
        x_on = xr + z * wc
        msp.add_line((x_on, sb + wc), (x_on + 0.8, sb + wc), dxfattribs={"layer": L_OUTLET})
    # 高程標註：由上往下依序排開（最小間距 1.8 字高），引線由實際高程斜接到文字
    ys, prev = [], None
    for txt, el in sorted(levels(lay), key=lambda t: -t[1]):
        y = el if prev is None else min(el, prev - 1.8 * th)
        ys.append((txt, el, y))
        prev = y
    for txt, el, y in ys:
        msp.add_line((Wp + GROUND_STUB_M - 0.2, sb + el), (tx - 0.1, sb + y), dxfattribs={"layer": L_NOTE})
        text(txt, (tx, sb + y - th / 2.0))
    dim((xl, sb), (xr, sb), (0, sb - 0.5))
    dim((Wp, sb), (Wp, sb + Hc), (Wp + 0.6, sb))
    return {"sec_base": sb}


def draw_sediment(doc, lay, scale, dimstyle):
    msp, th, dim, text = _mk(doc, scale, dimstyle)
    L, W, D = lay["L"], lay["W"], lay["D"]
    msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True, dxfattribs={"layer": L_BASIN})
    dim((0, 0), (L, 0), (0, -0.8))
    dim((0, 0), (0, W), (-0.8, 0))
    text("池長×寬 %s×%s" % (_g(L), _g(W)), (0.4, W / 2.0))
    sb = -(3.0 + D)
    msp.add_lwpolyline([(-GROUND_STUB_M, sb + D), (0, sb + D), (0, sb), (L, sb), (L, sb + D),
                        (L + GROUND_STUB_M, sb + D)], dxfattribs={"layer": L_BASIN})
    dim((0, sb), (L, sb), (0, sb - 0.5))
    dim((L, sb), (L, sb + D), (L + 0.6, sb))
    tx = L + GROUND_STUB_M + 0.5
    text("池深 %s" % _g(D), (tx, sb + D / 2.0))
    text("容量 %s m3" % _gi(lay["cap"]), (tx, sb + D / 2.0 - th * 2.2))
    text("池壁結構另行設計", (tx, sb + D / 2.0 - th * 4.4))
    return {"sec_base": sb}


def build_blocks(lay, res, values):
    if lay["kind"] == "sediment_basin":
        pr = res["production"]
        rows = [("容量", "%s m3（%s m3/ha）" % (_gi(res["capacity_m3"]), _g(res["rate_m3_per_ha"], 1))),
                ("池長×寬×深", "%s×%s×%s m" % (_g(lay["L"]), _g(lay["W"]), _g(lay["D"]))),
                ("長寬比", _g(res["side_ratio"], 1)),
                ("泥砂產量", "%s m3" % _gi(pr["production_m3"])),
                ("清砂", str(res.get("cleaning", "")))]
        title = "沉砂池摘要"
    else:
        ck = {c["item"]: c for c in res["checks"]}
        rows = [("池底 長×寬", "%s×%s m" % (_gi(lay["Lb"]), _gi(lay["Wb"]))),
                ("邊坡 H:V", "%s : 1" % _gi(lay["z"])),
                ("壩頂高", "%s m" % _g(lay["crest"])),
                ("尖峰入流", "%.3f m3/s" % res["peak_inflow_m3s"]),
                ("尖峰出流", "%.3f m3/s（衰減 %.1f%%）" % (res["peak_outflow_m3s"], res["peak_attenuation"] * 100)),
                ("最高水位", "%s m" % _g(res["max_stage_m"])),
                ("最大蓄水量", "%s m3" % _gi(res["max_storage_m3"]))]
        c2 = ck.get("最高水位＋出水高")
        if c2:
            rows.append(("水位＋出水高／壩頂", "%s／%s m" % (_g(c2["value"]), _g(c2["limit"]))))
        title = "滯洪池摘要"
    return [{"title": title, "rows": [[(0.0, k), (50.0, v)] for k, v in rows]}]


def build_notes(lay, res):
    sed = lay["kind"] == "sediment_basin"
    n = ["1. 本圖為%s平面與縱剖面示意圖，圖上尺寸單位為公尺（m），比例見標題欄。"
         % ("沉砂池" if sed else "滯洪池"),
         "2. 圖上標註數值皆取自設計計算結果或計算器輸入；%s。" % (
             "全部檢核通過" if res.get("pass", all(c.get("ok", True) for c in res.get("checks", []))
                          ) else "有未通過或僅供複核項目，不得逕行施工")]
    if sed:
        n.append("3. 計算器僅決定容量與長寬深，無池壁型式與邊坡；本圖為土池示意（直壁），池壁結構另行設計。")
        n.append("4. 入出口、溢流設施與清砂動線計算結果未提供，圖未繪。")
    else:
        n.append("3. 高程以池底為 ±0.00（計算器為相對水位），絕對高程由現地測量決定。")
        n.append("4. 緊急溢洪道、壩頂寬、護坡與出口工構造計算結果未提供，圖未繪；孔口／堰僅示意位置。")
        n.append("5. 計算未計上游時序、多峰雨型與下游迴水；初步設計，須技師覆核。")
    return n


def main():
    ap = argparse.ArgumentParser(description="滯洪池／沉砂池圖（D6）")
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
    sed = kind == "sediment_basin"
    if sed:
        W_m, H_m = lay["L"], lay["W"] + 3.0 + lay["D"]
    else:
        W_m, H_m = lay["Wp"], lay["Hp"] + 3.0 + lay["crest"]

    def need(sc):
        paper_w = (W_m + GROUND_STUB_M * 2 + 1.5) * 1000.0 / sc + 20 * 3.0 * 1.1
        paper_h = (H_m + 2.5) * 1000.0 / sc
        return paper_w <= 183.0 and paper_h <= 249.45

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
    (draw_sediment if sed else draw_detention)(doc, lay, a.scale, ds)

    no = a.sheet_no or ("P-2" if sed else "P-1")
    proj = a.project or (case.get("project") or {}).get("full_name") or "池體"
    MBS.build_paper(doc, {}, case, a.scale, proj, no,
                    {"blocks": build_blocks(lay, res, values), "notes": build_notes(lay, res)},
                    "沉砂池平面剖面圖" if sed else "滯洪池平面剖面圖", no,
                    unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
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
