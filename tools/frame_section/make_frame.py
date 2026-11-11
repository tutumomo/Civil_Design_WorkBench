# -*- coding: utf-8 -*-
"""構架立面圖 FR-1（D9）：`building_frame` 結果 → A3 DXF/DWG/PDF。

圖面內容
--------
立面線架圖（柱線、樓層線、梁柱構材）＋構材編號＋右欄「構架摘要」與「構材配筋表」。
所有幾何取自 `building_frame` 結果的 `geometry`（x_grid_m、elevations_m、beam_mm、column_mm、
support）；構材編號直接沿用引擎命名：梁 `B{樓層}_{跨}`、柱 `C{樓層}_{軸}`（樓層 1 = 地面層，
第 0 層為基礎節點），因此圖上每一支構材都能回查到結果的 `designs[]`。

圖上數值來源
------------
構材配筋表逐列引用 `designs[]`：梁列 `flexure.bar/spacing_mm`、`shear.bar/spacing_mm/legs`、
`Mu_kNm`；柱列 `chosen.bars_total/bar/bars_per_face`、`ties.bar/spacing_mm`、`Pu_kN`。
**梁主筋是引擎以「每米寬」選出的間距**（`rc_design._pick_bars` 的輸出慣例），不是
300 mm 樑寬的實際支數；本圖照列引擎值並在說明欄揭露，不在繪圖端自行換算支數。

分張限制
--------
本工具一次只出單張 A3：跨度／樓層過多，連 1:200 都放不進 A3 可繪區時**直接報錯**
（尚未實作跨數或樓層分張），不縮非標準比例硬塞。

用法
----
    .venv/bin/python tools/frame_section/make_frame.py <case.json> --out out/<案名>/FR-1.dxf
案件檔 `quantities.model == "building_frame"`。
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

L_COL = "30_柱"
L_BEAM = "31_梁"
L_GRD = "32_地盤線"
L_HATCH = "33_地盤剖面線"
L_AXIS = "34_軸線"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

# 模型空間（m）的標註通道位置：左側層高、下方跨徑與總寬、右側總高
DIM_L_M = 1.8
DIM_R_M = 1.8
DIM_BAY_Y = -0.9
DIM_TOT_Y = -2.1
AXIS_OVER_M = 1.0        # 軸線伸出屋頂
GROUND_H = 0.30          # 地盤線以下剖面線帶寬
SUPPORT_TEXT = {"fixed": "固定", "pinned": "鉸接"}
# 本圖的可用比例上限：DR.STANDARD_SCALES 含 1:1000 以上的測量用比例，
# 構架立面縮到那時候構材已不可辨識，超過此值一律視為「放不下」而報錯。
MAX_SHEET_SCALE = 250


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") != "building_frame":
        raise SystemExit("本工具只做構架立面圖（model 應為 building_frame，現在是 %r）"
                         % q.get("model"))
    return case, dict(q.get("values") or {})


def run_engine(values):
    import design_api as D

    env = D.run_calculation("building_frame", values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or not res.get("geometry") or not res.get("designs"):
        raise SystemExit("building_frame 引擎沒有構架結果，無法出圖。")
    return res


def frame_geo(res):
    """由結果 geometry 推出畫圖用的梁柱矩形（純計算，自測直接呼叫）。"""
    g = res["geometry"]
    grid = [float(x) for x in g["x_grid_m"]]
    elevs = [float(y) for y in g["elevations_m"]]
    bw, bd = (float(v) / 1000.0 for v in g["beam_mm"])
    cw, cd = (float(v) / 1000.0 for v in g["column_mm"])
    beams = []
    for level in range(1, len(elevs)):
        for ix in range(len(grid) - 1):
            beams.append({
                "member": "B%d_%d" % (level, ix), "level": level, "bay": ix,
                "x0": grid[ix] + cw / 2.0, "x1": grid[ix + 1] - cw / 2.0,
                "y_top": elevs[level], "y_bot": elevs[level] - bd,
                "cx": (grid[ix] + grid[ix + 1]) / 2.0,
            })
    cols = []
    for level in range(1, len(elevs)):
        for ix in range(len(grid)):
            cols.append({
                "member": "C%d_%d" % (level, ix), "level": level, "axis": ix,
                "x": grid[ix], "y0": elevs[level - 1], "y1": elevs[level],
                "label_x": grid[ix] + cw / 2.0 + 0.10,
                "label_y": (elevs[level - 1] + elevs[level]) / 2.0,
            })
    return {"grid": grid, "elevs": elevs, "beam_w": bw, "beam_d": bd,
            "col_w": cw, "col_d": cd, "beams": beams, "columns": cols,
            "support": str(g.get("support") or "fixed"),
            "storey_heights": [float(v) for v in g["storey_heights_m"]]}


def content_size(geo):
    """模型內容尺寸（m）：含左右標註通道、下方跨徑標註與上方軸線圈。"""
    x0, x1 = geo["grid"][0], geo["grid"][-1]
    top = geo["elevs"][-1]
    w = (x1 - x0) + DIM_L_M + DIM_R_M
    h = top + GROUND_H + abs(DIM_TOT_Y) + AXIS_OVER_M + 1.2
    return w, h


def pick_scale(geo):
    """放得進 A3 可繪區（183×249 mm）的最小標準比例（上限 MAX_SHEET_SCALE）。"""
    w, h = content_size(geo)
    for s in DR.STANDARD_SCALES:
        if s > MAX_SHEET_SCALE:
            break
        if w * 1000.0 / s <= 183.0 and h * 1000.0 / s <= 249.45:
            return s
    raise SystemExit("構架 %.1f×%.1f m 連 1:%d 都放不進 A3 可繪區（183×249 mm）；"
                     "本工具尚未實作跨數／樓層分張，請拆分子構架後重跑。"
                     % (w, h, MAX_SHEET_SCALE))


def schedule_rows(res):
    """構材配筋表：逐列引用 designs[]（樑為每米寬選筋，見說明欄）。"""
    design = {d["member"]: d for d in res.get("designs", [])}
    out = []
    for m in res.get("members", []):
        mid = m["member"]
        d = design.get(mid) or {}
        if m["kind"] == "beam":
            f = d.get("flexure") or {}
            sh = d.get("shear") or {}
            b_mm, h_mm = f.get("b_mm"), f.get("h_mm")
            util = max(float(f.get("utilization") or 0.0), float(sh.get("utilization") or 0.0))
            out.append({
                "id": mid, "kind": "梁",
                "section": "%d×%d" % (round(b_mm / 10.0), round(h_mm / 10.0))
                if b_mm and h_mm else "-",
                "main": "%s@%d" % (f.get("bar", "-"), f.get("spacing_mm", 0)),
                "stirrup": "%s@%d %d肢" % (sh.get("bar", "-"), sh.get("spacing_mm", 0),
                                           sh.get("legs", 2)),
                "Mu": "%.0f" % float(m.get("Mu_kNm") or 0.0),
                "Pu": "-",
                "util": "%.3f" % util,
                "ok": bool(m.get("ok")) and bool(f.get("ok")) and bool(sh.get("ok")),
            })
        else:
            ch = d.get("chosen") or {}
            ties = d.get("ties") or {}
            out.append({
                "id": mid, "kind": "柱",
                "section": "%d×%d" % (round(float(d.get("b_mm") or 0) / 10.0),
                                      round(float(d.get("h_mm") or 0) / 10.0)),
                "main": "%d-%s（%d/面）" % (ch.get("bars_total", 0), ch.get("bar", "-"),
                                           ch.get("bars_per_face", 0)),
                "stirrup": "%s@%d" % (ties.get("bar", "-"), round(ties.get("spacing_mm") or 0)),
                "Mu": "-",
                "Pu": "%.0f" % float(m.get("Pu_kN") or 0.0),
                "util": "%.3f" % float(ch.get("utilization") or 0.0),
                "ok": bool(m.get("ok")) and bool(ch.get("ok")),
            })
    return out


def _governing_drift(res):
    rows = res.get("drift") or []
    if not rows:
        return None
    return max(rows, key=lambda r: float(r.get("max_storey_drift_ratio") or 0.0))


def summary_rows(res):
    g = res["geometry"]
    grid = [float(v) for v in g["x_grid_m"]]
    elevs = [float(v) for v in g["elevations_m"]]
    bw, bd = (float(v) for v in g["beam_mm"])
    cw, cd = (float(v) for v in g["column_mm"])
    spans = [b - a for a, b in zip(grid, grid[1:])]
    drift = _governing_drift(res)
    ng = [c for c in res.get("checks", []) if not c.get("ok")]
    rows = [
        ("跨度", "%d 跨（%s m）" % (len(spans), "＋".join("%.2f" % s for s in spans))),
        ("層數／層高", "%d 層／%.2f m" % (len(g["storey_heights_m"]),
                                          float(g["storey_heights_m"][0]))),
        ("總高", "%.2f m" % elevs[-1]),
        ("梁／柱斷面（b×h）", "%d×%d／%d×%d cm" % (
            round(bw / 10.0), round(bd / 10.0), round(cw / 10.0), round(cd / 10.0))),
        ("柱支承", SUPPORT_TEXT.get(str(g.get("support")), str(g.get("support")))),
        ("靜載重合計", "%.0f kN" % float(res["loads"]["total_dead_weight_kn"])),
    ]
    if drift is not None:
        rows.append(("最大層間位移比", "%.5f（%s／%sF），限 %.3f %s" % (
            float(drift["max_storey_drift_ratio"]), drift.get("combination", "-"),
            drift.get("storey", "-"), float(drift["limit"]),
            "OK" if drift.get("ok") else "NG")))
    rows.append(("檢核項目", "%d 項，NG %d 項" % (len(res.get("checks", [])), len(ng))))
    return rows


def ensure_layers(doc):
    # 顏色對應 monochrome.ctb 線粗：柱 0.40、梁 0.35、地盤線 0.20、剖面線 0.10、軸線 0.15
    for name, color in [(L_COL, 6), (L_BEAM, 5), (L_GRD, 1), (L_HATCH, 8),
                        (L_AXIS, 7), (L_DIM, 7), (L_NOTE, 7),
                        (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def draw(doc, geo, res, H):
    msp = doc.modelspace()
    th = DR.model_h(3.0, H)
    th2 = DR.model_h(3.0, H)   # E15：本文一律 3 mm
    grid, elevs = geo["grid"], geo["elevs"]
    cw = geo["col_w"]
    top = elevs[-1]
    x0, x1 = grid[0], grid[-1]
    hidden = {"linetype": "HIDDEN"} if "HIDDEN" in doc.linetypes else {}

    def text(s, p, layer=L_NOTE, h=None, align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT):
        t = msp.add_text(s, height=h or th, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement(p, align=align)
        return t

    # 地盤線與地盤剖面線帶
    grd = [(x0 - 1.0, -GROUND_H), (x1 + 1.0, -GROUND_H), (x1 + 1.0, 0.0), (x0 - 1.0, 0.0)]
    msp.add_lwpolyline(grd, close=True, dxfattribs={"layer": L_HATCH})
    hh = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    hh.set_pattern_fill("ANSI31", color=256, scale=max(H / 1000.0, 1e-4))
    hh.paths.add_polyline_path(grd, is_closed=True)
    msp.add_line((x0 - 1.0, 0.0), (x1 + 1.0, 0.0), dxfattribs={"layer": L_GRD})

    # 軸線（HIDDEN：樣板無 DASHED）
    for ix, gx in enumerate(grid):
        msp.add_line((gx, -GROUND_H), (gx, top + AXIS_OVER_M),
                     dxfattribs=dict({"layer": L_AXIS}, **hidden))
        r = 1.6 * th
        msp.add_circle((gx, top + AXIS_OVER_M + r), r, dxfattribs={"layer": L_AXIS})
        text("X%d" % (ix + 1), (gx, top + AXIS_OVER_M + r - th / 2.0), L_AXIS,
             h=th, align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # 梁（柱面之間）與柱
    for b in geo["beams"]:
        msp.add_lwpolyline([(b["x0"], b["y_bot"]), (b["x1"], b["y_bot"]),
                            (b["x1"], b["y_top"]), (b["x0"], b["y_top"])],
                           close=True, dxfattribs={"layer": L_BEAM})
        text(b["member"], (b["cx"], b["y_top"] + 0.6 * th2), L_NOTE, h=th2,
             align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    for c in geo["columns"]:
        msp.add_lwpolyline([(c["x"] - cw / 2.0, c["y0"]), (c["x"] + cw / 2.0, c["y0"]),
                            (c["x"] + cw / 2.0, c["y1"]), (c["x"] - cw / 2.0, c["y1"])],
                           close=True, dxfattribs={"layer": L_COL})
        text(c["member"], (c["label_x"], c["label_y"] - th2 / 2.0), L_NOTE, h=th2)

    # 地面高程 ±0.00（掛在地盤剖面線帶下方，避免壓在剖面線上）
    text("GL ±0.00", (x0 - 0.05, -GROUND_H - 0.15 * th), L_NOTE, h=th2,
         align=ezdxf.enums.TextEntityAlignment.TOP_RIGHT)

    # 尺寸：層高（左）、跨徑（下）、總寬（下）、總高（右）
    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=MWS.ensure_dimstyle(doc, H, "m"),
                               dxfattribs={"layer": L_DIM})
        d.render()

    for lv in range(1, len(elevs)):
        dim((x0, elevs[lv - 1]), (x0, elevs[lv]), (x0 - DIM_L_M, elevs[lv - 1]))
    for i in range(len(grid) - 1):
        dim((grid[i], 0.0), (grid[i + 1], 0.0), (grid[i], DIM_BAY_Y))
    dim((x0, 0.0), (x1, 0.0), (x0, DIM_TOT_Y))
    dim((x1, 0.0), (x1, top), (x1 + DIM_R_M, 0.0))
    return {"th": th, "top": top, "width": x1 - x0}


def build_blocks(res, rows, summary):
    head = [(0.0, "編號"), (22.0, "斷面(cm)"), (46.0, "主筋（樑每米／柱支數）"),
            (96.0, "箍筋"), (130.0, "Mu(kN·m)"), (158.0, "Pu(kN)"), (180.0, "利用率＊")]
    tbl = []
    for r in rows:
        tbl.append([(0.0, r["id"]), (22.0, r["section"]), (46.0, r["main"]),
                    (96.0, r["stirrup"]), (130.0, r["Mu"]), (158.0, r["Pu"]),
                    (180.0, r["util"])])
    return [
        {"title": "構架摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in summary]},
        {"title": "構材配筋表（尺寸單位：cm）", "header": head, "rows": tbl},
    ]


def build_notes(res, rows, H):
    ng = [c for c in res.get("checks", []) if not c.get("ok")]
    n = ["1. 本圖為 2D 代表構架立面，依結果 geometry 繪製；軸線 X1…Xn 由繪圖端依 x_grid_m 編列，"
         "與引擎節點編號無關。",
         "2. 構材編號沿用引擎：B{樓層}_{跨}、C{樓層}_{軸}；樓層 1 = 地面層，第 0 層為基礎節點。",
         "3. 樑主筋為引擎每米寬選筋規格（As_prov 為 mm²/m），樑寬的實際支數與淨距須由技師"
         "另行換算；本表只列引擎輸出。",
         "4. 柱主筋為引擎 chosen 方案（每面支數×總支數），箍筋為引擎初步值 ties。",
         "5. ＊利用率：樑取撓曲與剪力較大者，柱取軸彎利用率。",
         "6. 梁深為結構深度（不含樓版）；不畫樓版、接頭與配筋詳圖（詳圖見 B-01／CL-1）。",
         "7. 引擎限制：2D 代表構架、柱僅單軸彎曲，未含二階效應、接頭剪力與錨定；地震力為"
         "等值靜力法。" + ("本題 %d 項檢核全部通過。" % len(res.get("checks", []))
                        if not ng else "本題有 %d 項未通過，不得施工。" % len(ng)),
         "8. 本工具一次只出單張 A3；1:%d 仍放不下時直接報錯，尚未實作自動分張。"
         % MAX_SHEET_SCALE]
    return n


def main():
    ap = argparse.ArgumentParser(description="構架立面圖（D9）")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto", help="比例；auto 由構架外廓決定")
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
    geo = frame_geo(res)
    auto = pick_scale(geo)
    H = auto if str(a.scale).lower() == "auto" else int(a.scale)
    DR.require_standard_scale(H)
    if H > MAX_SHEET_SCALE:
        raise SystemExit("比例 1:%d 超出本圖可用上限 1:%d（構材已不可辨識），"
                         "請改用 auto 或拆分子構架。" % (H, MAX_SHEET_SCALE))
    w, h = content_size(geo)
    if w * 1000.0 / H > 183.0 or h * 1000.0 / H > 249.45:
        raise SystemExit("1:%d 版面 %.1f×%.1f mm 超出 A3 可繪區（183×249 mm），"
                         "請改比例或拆分構架。" % (H, w * 1000.0 / H, h * 1000.0 / H))

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
    info = draw(doc, geo, res, H)

    rows = schedule_rows(res)
    summary = summary_rows(res)
    no = a.sheet_no or "FR-1"
    proj = a.project or (case.get("project") or {}).get("full_name") or "建築構架"
    MBS.build_paper(doc, {}, case, H, proj, no,
                    {"blocks": build_blocks(res, rows, summary),
                     "notes": build_notes(res, rows, H)},
                    "構架立面圖", no, unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  比例尺 1:%d、%d 層／%d 跨、構材 %d 支（梁 %d、柱 %d）、版面 %.1f×%.1f mm"
          % (H, len(geo["storey_heights"]), len(geo["grid"]) - 1, len(rows),
             len(geo["beams"]), len(geo["columns"]),
             w * 1000.0 / H, h * 1000.0 / H))
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
