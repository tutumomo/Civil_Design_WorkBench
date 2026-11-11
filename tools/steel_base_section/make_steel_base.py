# -*- coding: utf-8 -*-
"""鋼柱柱腳詳圖 SC-1（D8）：`steel_column` 結果 → A3 DXF/DWG/PDF。

圖面內容
--------
* 平面：承台（虛線）、基板、H 型鋼斷面、錨栓孔位；標註基板 B×N、錨栓間距、錨栓至板邊距離。
* 立面：承台（剖面線）、灌漿層（`grout_above_concrete` > 0 才畫）、基板、柱身（截斷示意）、
  錨栓（埋入深度 `embedment_mm`）。

圖上數值來源（DG2）
------------------
全部取自 `steel_column` 結果：斷面 `section`、基板 `base_plate.plate_*`、承台 `base_plate.pedestal_*`、
支承情況 `base_plate.support_condition`、錨栓 `anchors.*`（直徑、埋深、孔位、材質）、
檢核 `checks`（邊距、埋深、承壓、板厚、拉力、剪力、互制）。
**計算結果沒決定的元素不畫不標**：承台高度、錨栓孔徑、螺帽／墊圈尺寸、焊道、加勁板、剪力榫、
承台配筋——說明欄逐項列出。柱身以固定 1.0 m 截斷示意（不是柱長）。

用法
----
    .venv/bin/python tools/steel_base_section/make_steel_base.py <case.json> --out out/<案名>/SC-1.dxf
案件檔 `quantities.model == "steel_column"`。
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

L_STEEL = "30_鋼構材"
L_PLATE = "31_基板"
L_CONC = "32_承台混凝土"
L_HATCH = "33_承台剖面線"
L_GROUT = "34_灌漿層"
L_ANCHOR = "40_錨栓"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

COL_SHOW_M = 1.0        # 柱身截斷示意高度（非柱長）
PED_EXTRA_M = 0.15      # 承台只畫到埋深以下這麼多，再以斷線收尾（高度未由計算器決定）
NUT_RATIO = 1.6         # 螺帽示意寬度＝直徑 × 此值


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") != "steel_column":
        raise SystemExit("本工具只做鋼柱柱腳（model 應為 steel_column，現在是 %r）" % q.get("model"))
    return case, dict(q.get("values") or {})


def run_engine(values):
    import design_api as D

    env = D.run_calculation("steel_column", values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or "base_plate" not in res:
        raise SystemExit("steel_column 引擎沒有可用結果。")
    return res


def _g(x, nd=2):
    return "%.*f" % (nd, float(x))


def _gi(x):
    x = float(x)
    return "%d" % round(x) if abs(x - round(x)) < 1e-9 else "%.1f" % x


def support_label(value):
    """支承情況中文說明：直接讀設計計算器目錄的選項標籤（同一份註冊表，不另抄一份）。"""
    try:
        import design_api as D

        for c in D.CATALOG:
            if c["id"] != "steel_column":
                continue
            rule = (c.get("field_rules") or {}).get("base_plate.support_condition") or {}
            for ch in rule.get("choices") or []:
                if ch.get("value") == value:
                    return str(ch.get("label", value))
    except Exception:                              # pragma: no cover - 目錄異常時退回原值
        pass
    return str(value)


def check_of(res, key):
    for c in res.get("checks", []):
        if key in str(c.get("item", "")):
            return c
    return None


def layout(values, res):
    """純計算：圖面所需幾何與數值（自測直接呼叫）。"""
    sec = res["section"]
    bp = res["base_plate"]
    an = res["anchors"]
    lay = {
        "B": float(bp["plate_B_m"]), "N": float(bp["plate_N_m"]),
        "t": float(bp["plate_t_mm"]) / 1000.0,
        "ped_B": float(bp["pedestal_B_m"]), "ped_N": float(bp["pedestal_N_m"]),
        "grout": float(bp.get("grout_above_concrete") or 0.0),
        "fc": float(bp.get("fc_mpa") or 0.0),
        "support": str(bp.get("support_condition") or ""),
        "h": float(sec["h_mm"]) / 1000.0, "b": float(sec["b_mm"]) / 1000.0,
        "tw": float(sec["tw_mm"]) / 1000.0, "tf": float(sec["tf_mm"]) / 1000.0,
        "h_mm": float(sec["h_mm"]), "b_mm": float(sec["b_mm"]),
        "tw_mm": float(sec["tw_mm"]), "tf_mm": float(sec["tf_mm"]),
        "d": float(an["diameter_mm"]) / 1000.0, "d_mm": float(an["diameter_mm"]),
        "embed": float(an["embedment_mm"]) / 1000.0, "embed_mm": float(an["embedment_mm"]),
        "positions": [(float(p["x_m"]), float(p["y_m"])) for p in an.get("positions") or []],
        "n_anchor": len(an.get("positions") or []),
        "grade": str(an.get("grade_label") or an.get("grade") or ""),
        "shear_path": str((an.get("shear") or {}).get("path") or ""),
        "shear_desc": str((an.get("shear") or {}).get("description") or ""),
        "tensions": [float(t) for t in an.get("tensions_kn") or []],
        "t_max": float(an.get("max_tension_kn") or 0.0),
        "t_cap": float((an.get("capacity") or {}).get("tension_capacity_kN") or 0.0),
        "shear_cap": float((an.get("shear") or {}).get("capacity_kN") or 0.0),
        "shear_V": float((an.get("shear") or {}).get("V_total_kN") or 0.0),
        "interaction": float((an.get("interaction") or {}).get("ratio") or 0.0),
        "col_ratio": res["column"]["interaction"]["ratio"],
        "fy": float(res["column"]["fy_mpa"]), "Fu": float(res["column"]["Fu_mpa"]),
        "P": float(res["column"]["axial_P_kN"]),
        "Mx": float(res["column"]["moment_Mx_kNm"]),
        "q_max": float(bp["contact_pressure_x"]["q_max_kpa"]),
        "q_min": float(bp["contact_pressure_x"]["q_min_kpa"]),
        "uplift": bool(bp["contact_pressure_x"].get("uplift")),
        "cap_bearing": float(bp["bearing"]["capacity_kN"]),
        "dem_bearing": float(bp["compression_demand_kN"]),
        "t_req_flange": float(bp["thickness"]["required_thickness_flange_mm"]),
        "t_req_web": float(bp["thickness"]["required_thickness_web_mm"]),
        "t_plate_mm": float(bp["plate_t_mm"]),
        "grout_note": str(bp.get("support_condition") or ""),
    }
    edge = check_of(res, "至基板邊緣")
    embed = check_of(res, "埋入深度")
    lay["edge_ok"] = bool(edge["ok"]) if edge else None
    lay["edge_edge"] = float(edge["value"]) if edge else None
    lay["edge_limit"] = float(edge["limit"]) if edge else None
    lay["embed_ok"] = bool(embed["ok"]) if embed else None
    if lay["h"] > lay["N"] + 1e-9 or lay["b"] > lay["B"] + 1e-9:
        raise SystemExit("柱斷面 %.0f×%.0f 大於基板 %.0f×%.0f，柱腳詳圖不成立；請調整基板尺寸。"
                         % (lay["h_mm"], lay["b_mm"], lay["B"] * 1000, lay["N"] * 1000))
    if lay["B"] > lay["ped_B"] + 1e-9 or lay["N"] > lay["ped_N"] + 1e-9:
        raise SystemExit("基板 %.0f×%.0f 大於承台 %.0f×%.0f；請調整承台尺寸。"
                         % (lay["B"] * 1000, lay["N"] * 1000, lay["ped_B"] * 1000, lay["ped_N"] * 1000))
    if lay["positions"]:
        lay["edge_draw"] = min(lay["B"] / 2.0 - abs(x) for x, _ in lay["positions"])
        lay["anchor_span"] = max(x for x, _ in lay["positions"]) - min(x for x, _ in lay["positions"])
    else:
        lay["edge_draw"] = None
        lay["anchor_span"] = 0.0
    return lay


def labels(lay):
    return {"plate": "基板 %s×%s×%s" % (_g(lay["B"] * 1000, 0), _g(lay["N"] * 1000, 0), _gi(lay["t_plate_mm"])),
            "col": "H%s×%s×%s×%s" % (_gi(lay["h_mm"]), _gi(lay["b_mm"]), _gi(lay["tw_mm"]), _gi(lay["tf_mm"])),
            "anchor": "錨栓 %d-%%%%c%s 埋深 %s" % (lay["n_anchor"], _gi(lay["d_mm"]), _gi(lay["embed_mm"])),
            "ped": "承台 %s×%s" % (_g(lay["ped_B"] * 1000, 0), _g(lay["ped_N"] * 1000, 0)),
            "grout": "灌漿層 %s" % _gi(lay["grout"] * 1000),
            "t": "t=%s" % _gi(lay["t_plate_mm"])}


def ensure_layers(doc):
    # monochrome.ctb：1=0.20、3=0.20、4=0.25、5=0.35、8=0.10 mm
    for name, color in [(L_STEEL, 5), (L_PLATE, 5), (L_CONC, 1), (L_HATCH, 8),
                        (L_GROUT, 8), (L_ANCHOR, 4), (L_DIM, 3), (L_NOTE, 7),
                        (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def h_section_polys(lay):
    """H 型鋼在平面的三個矩形（上翼板、腹板、下翼板），單位 m，對稱於原點。"""
    b, h, tw, tf = lay["b"], lay["h"], lay["tw"], lay["tf"]
    ys = h / 2.0
    return [[(-b / 2, ys - tf), (b / 2, ys - tf), (b / 2, ys), (-b / 2, ys)],
            [(-tw / 2, -ys + tf), (tw / 2, -ys + tf), (tw / 2, ys - tf), (-tw / 2, ys - tf)],
            [(-b / 2, -ys), (b / 2, -ys), (b / 2, -ys + tf), (-b / 2, -ys + tf)]]


def bottom_spacer(doc, y, scale, half_w):
    """不列印的留白線：build_paper 的比例尺標題會被放在視口下緣上方 8.5 mm，
    圖形若剛好畫到視口底就會被壓過去。底部留一條不列印的構造線把內容往上抬。"""
    name = "00_出圖留白"
    DR.add_plot_layer(doc, name, color=7)           # 線粗與顏色一起寫好，E17 才不會抓 -3
    doc.layers.get(name).dxf.plot = 0
    doc.modelspace().add_line((-half_w, y), (half_w, y), dxfattribs={"layer": name})


def draw(doc, lay, scale, dimstyle):
    msp = doc.modelspace()
    th = DR.model_h(3.0, scale)
    hs = max((1.5 * scale / 1000.0) / 3.175, 1e-4)
    B, N, t = lay["B"], lay["N"], lay["t"]
    Lab = labels(lay)

    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=dimstyle,
                               dxfattribs={"layer": L_DIM})
        d.render()

    def text(s, p, layer=L_NOTE, align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT):
        tt = msp.add_text(s, height=th, dxfattribs={"layer": layer, "style": "TOMO"})
        tt.set_placement(p, align=align)

    def callout(s, p, q):
        msp.add_line(p, q, dxfattribs={"layer": L_NOTE})
        text(s, (q[0], q[1] - th / 2.0))

    # ---------------- 平面 ----------------
    msp.add_lwpolyline([(-B / 2, -N / 2), (B / 2, -N / 2), (B / 2, N / 2), (-B / 2, N / 2)],
                       close=True, dxfattribs={"layer": L_PLATE})
    ped = [(-lay["ped_B"] / 2, -lay["ped_N"] / 2), (lay["ped_B"] / 2, -lay["ped_N"] / 2),
           (lay["ped_B"] / 2, lay["ped_N"] / 2), (-lay["ped_B"] / 2, lay["ped_N"] / 2)]
    attrs = {"layer": L_CONC}
    for lt in ("DASHED", "HIDDEN"):                 # 樣板只有 HIDDEN，退回它才看得出是虛線
        if lt in doc.linetypes:
            attrs["linetype"] = lt
            break
    msp.add_lwpolyline(ped, close=True, dxfattribs=attrs)
    for poly in h_section_polys(lay):
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer": L_STEEL})
    for x, y in lay["positions"]:
        msp.add_circle((x, y), lay["d"] / 2.0, dxfattribs={"layer": L_ANCHOR})
    dim((-B / 2, -N / 2), (B / 2, -N / 2), (0, -N / 2 - 0.18))
    dim((-B / 2, -N / 2), (-B / 2, N / 2), (-B / 2 - 0.18, 0))
    if lay["positions"]:
        xs = sorted({round(x, 6) for x, _ in lay["positions"]})
        if len(xs) > 1:
            dim((xs[0], N / 2), (xs[-1], N / 2), (0, lay["ped_N"] / 2 + 0.10))
    text("平面圖", (-lay["ped_B"] / 2.0, lay["ped_N"] / 2.0 + 0.30), L_NOTE)
    top_right = (B / 2, N / 2)
    callout(Lab["plate"], top_right, (B / 2 + 0.25, N / 2 + 0.10))
    callout(Lab["col"], (lay["b"] / 2, lay["h"] / 2), (B / 2 + 0.25, N / 2 - 0.06))
    callout(Lab["ped"], (lay["ped_B"] / 2, -lay["ped_N"] / 2), (B / 2 + 0.25, -N / 2 + 0.02))
    if lay["positions"]:
        ax, ay = lay["positions"][-1]
        callout(Lab["anchor"], (ax, ay), (B / 2 + 0.25, -N / 2 - 0.10))

    # ---------------- 立面（置於平面下方，承台頂＝z 0） ----------------
    depth = lay["embed"] + PED_EXTRA_M
    y_off = -N / 2.0 - 0.45 - (COL_SHOW_M + t + lay["grout"] + depth)

    def Z(z):
        return y_off + z

    pb, pg = lay["ped_B"], lay["grout"]
    ped_z = [(pb / 2.0, Z(0.0)), (pb / 2.0, Z(-depth)), (-pb / 2.0, Z(-depth)), (-pb / 2.0, Z(0.0))]
    msp.add_lwpolyline(ped_z, close=True, dxfattribs={"layer": L_CONC})
    hh = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    hh.set_pattern_fill("ANSI31", color=256, scale=hs)
    hh.paths.add_polyline_path(ped_z, is_closed=True)
    # 承台底以斷線收尾（高度未由計算器決定）
    zb = Z(-depth)
    for dx in (-0.05, 0.05):
        msp.add_line((-pb / 2.0 + dx, zb - 0.03), (-pb / 2.0 + dx + 0.10, zb + 0.03),
                     dxfattribs={"layer": L_NOTE})
        msp.add_line((pb / 2.0 + dx - 0.10, zb - 0.03), (pb / 2.0 + dx, zb + 0.03),
                     dxfattribs={"layer": L_NOTE})
    if pg > 0:
        msp.add_lwpolyline([(-pb / 2.0, Z(0.0)), (pb / 2.0, Z(0.0)),
                            (pb / 2.0, Z(pg)), (-pb / 2.0, Z(pg))],
                           close=True, dxfattribs={"layer": L_GROUT})
    z0 = pg                                        # 基板底
    msp.add_lwpolyline([(-B / 2.0, Z(z0)), (B / 2.0, Z(z0)), (B / 2.0, Z(z0 + t)),
                        (-B / 2.0, Z(z0 + t))], close=True, dxfattribs={"layer": L_PLATE})
    zc = z0 + t
    msp.add_lwpolyline([(-lay["b"] / 2.0, Z(zc)), (lay["b"] / 2.0, Z(zc)),
                        (lay["b"] / 2.0, Z(zc + COL_SHOW_M)), (-lay["b"] / 2.0, Z(zc + COL_SHOW_M))],
                       close=True, dxfattribs={"layer": L_STEEL})
    # 柱身截斷（雙斜線）
    for dx in (-0.03, 0.03):
        msp.add_line((-lay["b"] / 2.0, Z(zc + COL_SHOW_M) + dx),
                     (lay["b"] / 2.0, Z(zc + COL_SHOW_M) - dx), dxfattribs={"layer": L_NOTE})
    # 錨栓：螺帽（示意）＋桿身＋底部螺帽
    nut_w, nut_h = lay["d"] * NUT_RATIO, lay["d"] * 1.0
    for x in sorted({round(p[0], 6) for p in lay["positions"]}):   # 同一 x 的兩排錨栓在立面重疊，只畫一次
        msp.add_line((x, Z(zc)), (x, Z(-lay["embed"])), dxfattribs={"layer": L_ANCHOR})
        msp.add_lwpolyline([(x - nut_w / 2, Z(zc)), (x + nut_w / 2, Z(zc)),
                            (x + nut_w / 2, Z(zc + nut_h)), (x - nut_w / 2, Z(zc + nut_h))],
                           close=True, dxfattribs={"layer": L_ANCHOR})
        msp.add_lwpolyline([(x - nut_w / 2, Z(-lay["embed"])), (x + nut_w / 2, Z(-lay["embed"])),
                            (x + nut_w / 2, Z(-lay["embed"] + nut_h)),
                            (x - nut_w / 2, Z(-lay["embed"] + nut_h))],
                           close=True, dxfattribs={"layer": L_ANCHOR})
    dim((-B / 2.0, Z(z0)), (B / 2.0, Z(z0)), (0, Z(z0) - 0.10))
    dim((B / 2.0, Z(0.0)), (B / 2.0, Z(-lay["embed"])), (B / 2.0 + 0.18, 0))
    dim((-pb / 2.0, Z(0.0)), (pb / 2.0, Z(0.0)), (0, Z(0.0) - 0.10))
    tx = B / 2.0 + 0.35
    callout(Lab["t"], (B / 2.0, Z(z0 + t / 2.0)), (tx, Z(z0 + t) + 0.06))
    if pg > 0:
        callout(Lab["grout"], (-pb / 2.0, Z(pg / 2.0)), (-pb / 2.0 - 0.30, Z(pg) + 0.10))
    callout(Lab["col"], (lay["b"] / 2.0, Z(zc + COL_SHOW_M * 0.6)), (tx, Z(zc + COL_SHOW_M * 0.85)))
    callout(Lab["anchor"], (lay["positions"][-1][0] if lay["positions"] else 0.0, Z(-lay["embed"] * 0.35)),
            (tx, Z(-lay["embed"] * 0.22)))
    callout("承台（高度另定）", (pb / 2.0, Z(-depth * 0.6)), (tx, Z(-depth * 0.55)))
    text("立面圖（承台頂 ±0.00）", (-pb / 2.0 - 0.06, Z(0.0) + 0.04), L_NOTE,
         ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT)
    bottom_spacer(doc, Z(-depth) - DR.model_h(12.0, scale), scale,
                  max(pb / 2.0, lay["B"] / 2.0))
    return {"depth": depth, "y_off": y_off}


def build_blocks(lay):
    rows = [("柱斷面", "H%s×%s×%s×%s mm（fy %s／Fu %s）"
             % (_gi(lay["h_mm"]), _gi(lay["b_mm"]), _gi(lay["tw_mm"]), _gi(lay["tf_mm"]),
                _gi(lay["fy"]), _gi(lay["Fu"]))),
            ("基板 B×N×t", "%s×%s×%s mm" % (_g(lay["B"] * 1000, 0), _g(lay["N"] * 1000, 0),
                                             _gi(lay["t_plate_mm"]))),
            ("承台 B×N", "%s×%s mm（fc′ %s）" % (_g(lay["ped_B"] * 1000, 0), _g(lay["ped_N"] * 1000, 0),
                                               _gi(lay["fc"]))),
            ("支承情況", support_label(lay["support"])),
            ("基板厚 需求／採用", "%s／%s mm（翼板方向）"
             % (_g(lay["t_req_flange"], 1), _gi(lay["t_plate_mm"]))),
            ("基板厚 腹板方向（參考）", "%s mm ＞ 板厚（見說明）" % _g(lay["t_req_web"], 1)),
            ("混凝土承壓 需求／容量", "%.0f／%.0f kN" % (lay["dem_bearing"], lay["cap_bearing"])),
            ("接觸壓力 q_max／q_min", "%.0f／%.0f kPa%s" % (lay["q_max"], lay["q_min"],
                                                       "（揚起）" if lay["uplift"] else "")),
            ("錨栓", "%d-%%%%c%s %s" % (lay["n_anchor"], _gi(lay["d_mm"]), lay["grade"])),
            ("錨栓埋深 hef", "%s mm" % _gi(lay["embed_mm"])),
            ("錨栓最大拉力／容量", "%.1f／%.1f kN" % (lay["t_max"], lay["t_cap"])),
            ("剪力（%s）需求／容量" % ("摩擦" if lay["shear_path"] == "friction" else lay["shear_path"]),
             "%.1f／%.1f kN" % (lay["shear_V"], lay["shear_cap"])),
            ("錨栓拉剪互制", "%.3f ≤ 1.0" % lay["interaction"]),
            ("梁柱互制", "%.3f ≤ 1.0（P %.0f kN、Mx %.0f kN·m）"
             % (lay["col_ratio"], lay["P"], lay["Mx"]))]
    if lay["edge_edge"] is not None:
        rows.append(("錨栓至板邊距離", "%s／%s mm" % (_gi(lay["edge_edge"]), _gi(lay["edge_limit"]))))
    return [{"title": "柱腳摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in rows]}]


def build_notes(lay, res):
    n = ["1. 本圖為鋼柱柱腳詳圖，圖上尺寸單位為公尺（m）、板材與螺栓尺寸為毫米（mm），比例見標題欄。",
         "2. 圖上標註數值皆取自設計計算結果；%s。" % (
             ("全部檢核通過" if lay["t_req_web"] <= lay["t_plate_mm"] + 1e-9
              else "除腹板方向基板厚為參考值（見第 4 條）外，其餘檢核通過")
             if res.get("pass") else "有未通過項目，不得施工")]
    n.append("%d. 承台高度計算結果未提供：立面只畫到錨栓埋深以下 %s mm，並以斷線收尾；"
             "承台配筋與尺寸須另行設計。" % (len(n) + 1, _gi(PED_EXTRA_M * 1000)))
    if lay["t_req_web"] > lay["t_plate_mm"] + 1e-9:
        n.append("%d. 基板厚：翼板方向懸臂法需求 %s mm ≤ 板厚 %s mm，但腹板方向懸臂值 %s mm 大於板厚，"
                 "計算器標為「參考」（未計翼板 T 形梁作用）；須依 AISC DG1 T 形梁或加勁板法覆核，必要時增設加勁板。"
                 % (len(n) + 1, _g(lay["t_req_flange"], 1), _gi(lay["t_plate_mm"]), _g(lay["t_req_web"], 1)))
    if lay["uplift"]:
        n.append("%d. 接觸壓力出現負值（q_min %s kPa）：柱腳會揚起／搖滾，錨栓受拉；"
                 "支承行為須依實際接頭（鉸接或固定）確認，錨栓拉力已按彈性錨栓群法計算。" % (len(n) + 1, _g(lay["q_min"], 0)))
    n.append("%d. 錨栓孔徑、螺帽與墊圈尺寸、柱與基板焊道、剪力榫、灌漿配比計算結果未提供，圖上以示意繪製。"
             % (len(n) + 1))
    n.append("%d. 柱身只畫 %s m 截斷示意，不是柱長；柱長與構架關係見構架立面圖。" % (len(n) + 1, _gi(COL_SHOW_M)))
    n.append("%d. 基板厚度採 AISC DG1 簡化懸臂法、錨栓拉力採彈性錨栓群法（非我國規範明文公式）；初步設計，須技師覆核。"
             % (len(n) + 1))
    return n


def main():
    ap = argparse.ArgumentParser(description="鋼柱柱腳詳圖（D8）")
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

    case, values = load_values(a.case)
    res = run_engine(values)
    lay = layout(values, res)
    depth = lay["embed"] + PED_EXTRA_M

    def need(sc):
        lw = max(len(v) for v in labels(lay).values()) * 3.0 * 1.1 * sc / 1000.0
        mw = max(lay["ped_B"], lay["B"]) + 0.18 + 0.25 + lw + 0.5
        mh = lay["N"] + 0.6 + COL_SHOW_M + lay["t"] + lay["grout"] + depth + 0.4
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

    no = a.sheet_no or "SC-1"
    proj = a.project or (case.get("project") or {}).get("full_name") or "鋼構柱"
    MBS.build_paper(doc, {}, case, a.scale, proj, no,
                    {"blocks": build_blocks(lay), "notes": build_notes(lay, res)},
                    "鋼柱柱腳詳圖", no, unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  H%.0f×%.0f 基板 %.0f×%.0f×%.0f 錨栓 %d-Ø%.0f 埋深 %.0f 比例 1/%d"
          % (lay["h_mm"], lay["b_mm"], lay["B"] * 1000, lay["N"] * 1000, lay["t_plate_mm"],
             lay["n_anchor"], lay["d_mm"], lay["embed_mm"], a.scale))
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
