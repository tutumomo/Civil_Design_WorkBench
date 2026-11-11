# -*- coding: utf-8 -*-
"""樁位配置圖 FP-1／基腳沉陷配置圖 FS-1（D10）。

兩支引擎共用同一套「平面配置圖」骨架，差別只在物件與右欄表格：

* `foundation_pile`（樁帽／樁群載重分配）→ **FP-1 樁位配置圖**：樁位（x,y）、逐樁軸力、
  樁群形心十字、樁距與總尺寸標註、樁群摘要、樁載重表。
* `settlement_assessment`（沉陷與角變量評估）→ **FS-1 基腳沉陷配置圖**：基腳 B×L 平面、
  逐基腳總沉陷量、超限標示、基腳沉陷表、相鄰角變量表。

圖上數值來源
------------
全部取自計算結果：樁位與軸力取自 `piles[]`，樁群性質取自 `Ix_m2`／`Iy_m2`／`P_kN`／
`Mx_kNm`／`My_kNm`，檢核取自 `checks[]`；基腳位置／尺寸取自 `footings[]`，
沉陷分項取自 `immediate_settlement_mm`／`primary_consolidation_mm`／`secondary_compression_mm`，
角變量取自 `angular_distortion`。

**計算器沒有給的，一律不畫**（同 D8 慣例）：
* 樁徑、樁長、樁帽尺寸與配筋未由 `foundation_pile` 決定——圖上樁以**符號**表示，
  圓的大小不代表實際樁徑，圖名與說明明寫「配置圖，非樁帽配筋圖」。
* 基腳埋深、高程與柱位未由 `settlement_assessment` 決定——平面只畫基腳外廓與相對位置。

用法
----
    .venv/bin/python tools/foundation_plan/make_foundation_plan.py <case.json> --out out/<案名>/FP-1.dxf
案件檔 `quantities.model` 為 `pile_group` 或 `settlement`。
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

L_ITEM = "30_樁位"
L_FOOT = "30_基腳"
L_MARK = "31_標記"
L_AXIS = "32_軸線"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

DIM_GAP_TEXT = 4.0       # 第一道尺寸線距物件＝4 個字高（紙面 12 mm）
MAX_SHEET_SCALE = 250    # 超過此比例構材不可辨識，一律視為放不下
MAX_LIST_PILES = 20      # 樁數超過此值不再逐樁列表（圖上仍逐樁標軸力）
MODELS = {"pile_group": "FP-1", "settlement": "FS-1"}


def load_case(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    model = q.get("model")
    if model not in MODELS:
        raise SystemExit("本工具只做樁位配置圖／基腳沉陷配置圖（model 應為 pile_group 或 "
                         "settlement，現在是 %r）" % model)
    return case, dict(q.get("values") or {}), model


def run_engine(calc_id, values):
    import design_api as D

    env = D.run_calculation(calc_id, values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res:
        raise SystemExit("%s 引擎沒有結果，無法出圖。" % calc_id)
    return res


def pile_geo(res):
    """樁位與外廓（純計算，自測直接呼叫）。"""
    piles = [{"no": int(p["pile"]), "x": float(p["x_m"]), "y": float(p["y_m"]),
              "P": float(p["P_kN"]), "ok": bool(p.get("ok"))} for p in res["piles"]]
    xs = [p["x"] for p in piles]
    ys = [p["y"] for p in piles]
    return {"piles": piles, "bbox": (min(xs), min(ys), max(xs), max(ys)),
            "xs": sorted(set(xs)), "ys": sorted(set(ys)),
            "n": int(res["n_piles"])}


def _ratio_text(v):
    """角變量同時給小數與倒數（1/xxx）：只給 5 位小數會把 0.000388 顯示成 0.00039。"""
    v = float(v or 0.0)
    if v <= 0:
        return "%.6f" % v
    return "%.6f（約 1/%s）" % (v, format(int(round(1.0 / v)), ","))


def footing_geo(res):
    """基腳矩形與外廓（純計算，自測直接呼叫）。"""
    fs = []
    for f in res["footings"]:
        b, l = float(f["B_m"]), float(f["L_m"])
        x, y = float(f["x_m"]), float(f["y_m"])
        fs.append({"id": str(f["id"]), "x": x, "y": y, "B": b, "L": l,
                   "x0": x - b / 2.0, "x1": x + b / 2.0,
                   "y0": y - l / 2.0, "y1": y + l / 2.0,
                   "total": float(f["total_settlement_mm"]),
                   "immediate": float(f["immediate_settlement_mm"]),
                   "primary": float(f["primary_consolidation_mm"]),
                   "secondary": float(f["secondary_compression_mm"]),
                   "allow": float(f["allowable_total_mm"]),
                   "q": float(f["q_kpa"]), "ok": bool(f.get("ok"))})
    return {"footings": fs,
            "bbox": (min(f["x0"] for f in fs), min(f["y0"] for f in fs),
                     max(f["x1"] for f in fs), max(f["y1"] for f in fs)),
            "xs": sorted({f["x"] for f in fs}), "ys": sorted({f["y"] for f in fs}),
            "n": len(fs)}


def content_size(geo, scale):
    """模型內容尺寸（m）：物件外廓＋四周標註通道（通道以字高換算，隨比例改變）。"""
    th = DR.model_h(3.0, scale)
    gap = DIM_GAP_TEXT * th
    x0, y0, x1, y1 = geo["bbox"]
    # 左：第一道尺寸線；右：總高尺寸線；下：總寬尺寸線（第二道）
    return ((x1 - x0) + gap + gap + th, (y1 - y0) + 2 * gap + th)


def pick_scale(geo):
    """外廓（含標註通道）放得進 A3 可繪區的最小標準比例。"""
    for s in DR.STANDARD_SCALES:
        if s > MAX_SHEET_SCALE:
            break
        w, h = content_size(geo, s)
        if w * 1000.0 / s <= 183.0 and h * 1000.0 / s <= 249.45:
            return s
    x0, y0, x1, y1 = geo["bbox"]
    raise SystemExit("配置範圍 %.1f×%.1f m 連 1:%d 都放不進 A3 可繪區；"
                     "本工具尚未實作分張，請縮小範圍或分批出圖。"
                     % (x1 - x0, y1 - y0, MAX_SHEET_SCALE))


def ensure_layers(doc, kind):
    item = L_ITEM if kind == "pile" else L_FOOT
    for name, color in [(item, 5), (L_MARK, 7), (L_AXIS, 8), (L_DIM, 7), (L_NOTE, 7),
                        (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7), (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def _text(msp, s, p, layer=L_NOTE, h=0.1,
          align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT):
    t = msp.add_text(str(s), height=h, dxfattribs={"layer": layer, "style": "TOMO"})
    t.set_placement(p, align=align)
    return t


def _axes_and_dims(msp, doc, H, geo, th):
    """軸線（細虛線）＋樁距／基腳間距／總尺寸標註。"""
    x0, y0, x1, y1 = geo["bbox"]
    hidden = {"linetype": "HIDDEN"} if "HIDDEN" in doc.linetypes else {}
    ext = 1.2 * th
    for x in geo["xs"]:
        msp.add_line((x, y0 - ext), (x, y1 + ext), dxfattribs=dict({"layer": L_AXIS}, **hidden))
    for y in geo["ys"]:
        msp.add_line((x0 - ext, y), (x1 + ext, y), dxfattribs=dict({"layer": L_AXIS}, **hidden))
    ds = MWS.ensure_dimstyle(doc, H, "m")

    def dim(p1, p2, base):
        angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=ds,
                               dxfattribs={"layer": L_DIM})
        d.render()

    gap = DIM_GAP_TEXT * th
    xs, ys = geo["xs"], geo["ys"]
    for i in range(len(xs) - 1):
        dim((xs[i], y0), (xs[i + 1], y0), (xs[i], y0 - gap))
    for i in range(len(ys) - 1):
        dim((x0, ys[i]), (x0, ys[i + 1]), (x0 - gap, ys[i]))
    # 只有 3 條以上軸線時總尺寸才與樁距不同，否則會出現兩個一樣的標註
    if len(xs) > 2:
        dim((xs[0], y0), (xs[-1], y0), (xs[0], y0 - 2 * gap))
    if len(ys) > 2:
        dim((x0, ys[0]), (x0, ys[-1]), (x1 + gap, ys[0]))


def draw_pile(doc, res, geo, H):
    msp = doc.modelspace()
    th = DR.model_h(3.0, H)
    r = 1.2 * th                                    # 樁符號半徑（紙面 3.6 mm），不代表樁徑
    for p in geo["piles"]:
        msp.add_circle((p["x"], p["y"]), r, dxfattribs={"layer": L_ITEM})
        lab = "P%d %.0f kN" % (p["no"], p["P"])
        if p["P"] < -1e-9:
            lab += " 拉力"
        elif not p["ok"]:
            lab += " 超限"
        # 樁號與軸力寫在樁符號右側單行：寫在圓下的話會被樁距標註的延伸線穿過
        _text(msp, lab, (p["x"] + r + 0.4 * th, p["y"] - 0.5 * th), L_MARK, th)
    # 樁群形心（輸入座標原點）十字
    c = 3.0 * th
    msp.add_line((-c, 0.0), (c, 0.0), dxfattribs={"layer": L_MARK})
    msp.add_line((0.0, -c), (0.0, c), dxfattribs={"layer": L_MARK})
    _text(msp, "樁群形心 (0,0)", (c * 1.2, -0.5 * th), L_MARK, th)
    _axes_and_dims(msp, doc, H, geo, th)
    return {"th": th, "r": r}


def draw_settlement(doc, res, geo, H):
    msp = doc.modelspace()
    th = DR.model_h(3.0, H)
    for f in geo["footings"]:
        msp.add_lwpolyline([(f["x0"], f["y0"]), (f["x1"], f["y0"]),
                            (f["x1"], f["y1"]), (f["x0"], f["y1"])],
                           close=True, dxfattribs={"layer": L_FOOT})
        cx, cy = (f["x0"] + f["x1"]) / 2.0, (f["y0"] + f["y1"]) / 2.0
        _text(msp, f["id"], (cx, cy + 0.3 * th), L_MARK, th,
              ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
        lab = "%.1f mm" % f["total"] + ("" if f["ok"] else " 超限")
        _text(msp, lab, (cx, cy - 0.3 * th), L_MARK, th,
              ezdxf.enums.TextEntityAlignment.TOP_CENTER)
    _axes_and_dims(msp, doc, H, geo, th)
    return {"th": th}


def pile_blocks(res, geo):
    summary = [
        ("樁數", "%d 支" % geo["n"]),
        ("垂直載重 P", "%.0f kN" % float(res["P_kN"])),
        ("Mx／My", "%.0f／%.0f kN·m" % (float(res["Mx_kNm"]), float(res["My_kNm"]))),
        ("Ix／Iy", "%.3f／%.3f m²" % (float(res["Ix_m2"]), float(res["Iy_m2"]))),
        ("最大樁軸力", "%.1f kN" % float(res["max_pile_load_kN"])),
        ("最小樁軸力", "%.1f kN" % float(res["min_pile_load_kN"])),
        ("容許樁軸力", "%.1f kN" % float(res["Q_allow_kN"])),
    ]
    for c in res.get("checks", []):
        summary.append((str(c["item"])[:12], "%.1f／%.1f %s（%s）" % (
            c["value"], c["limit"], c.get("unit", ""), "OK" if c["ok"] else "NG")))
    blocks = [{"title": "樁群摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in summary]}]
    if geo["n"] <= MAX_LIST_PILES:
        rows = [[(0.0, "P%d" % p["no"]), (22.0, "%.2f" % p["x"]), (58.0, "%.2f" % p["y"]),
                 (96.0, "%.1f" % p["P"]),
                 (132.0, "拉力" if p["P"] < -1e-9 else ("OK" if p["ok"] else "超限"))]
                for p in geo["piles"]]
        blocks.append({"title": "樁載重表（x／y 單位 m、軸力 kN）",
                       "header": [(0.0, "樁號"), (22.0, "x(m)"), (58.0, "y(m)"),
                                  (96.0, "軸力(kN)"), (132.0, "判定")],
                       "rows": rows})
    return blocks


def settlement_blocks(res, geo):
    ad = res.get("angular_distortion") or {}
    summary = [
        ("基腳數", "%d 座" % geo["n"]),
        ("評估方法", "分層瞬時＋1D 壓密"),
        ("最大總沉陷", "%.1f mm" % max(f["total"] for f in geo["footings"])),
        ("容許總沉陷", "%.0f mm" % geo["footings"][0]["allow"]),
        ("最大角變量", _ratio_text(ad.get("max_angular_distortion"))),
        ("容許角變量", "%.5f（1/%d）" % (float(ad.get("allowable_angular_distortion", 0.0)),
                                         int(ad.get("allowable_reciprocal", 0) or 0))),
        ("判定", "OK" if res.get("pass") else "NG"),
    ]
    rows = [[(0.0, f["id"]), (22.0, "%g×%g" % (f["B"], f["L"])), (66.0, "%.0f" % f["q"]),
             (96.0, "%.1f" % f["immediate"]), (124.0, "%.1f" % (f["primary"] + f["secondary"])),
             (158.0, "%.1f" % f["total"]),
             (186.0, "OK" if f["ok"] else "超限")]
            for f in geo["footings"]]
    blocks = [
        {"title": "沉陷摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in summary]},
        {"title": "基腳沉陷表（沉陷量 mm、q 為 kPa）",
         "header": [(0.0, "基腳"), (22.0, "B×L(m)"), (66.0, "q"), (96.0, "瞬時"),
                    (124.0, "壓密＋次壓"), (158.0, "總計"), (186.0, "判定")],
         "rows": rows},
    ]
    pairs = ad.get("pairs") or []
    if pairs:
        pmax = max(float(p["angular_distortion"]) for p in pairs)
        blocks.append({
            "title": "相鄰基腳角變量（已扣除剛體轉動）",
            "header": [(0.0, "配對"), (36.0, "距離(m)"), (82.0, "Δ(mm)"),
                       (124.0, "δ/L")],
            "rows": [[(0.0, "%s–%s" % (p["a"], p["b"])),
                      (36.0, "%.2f" % float(p["distance_m"])),
                      (82.0, "%.2f" % float(p["settlement_difference_mm"])),
                      (124.0, "%.6f%s" % (float(p["angular_distortion"]),
                                          "＊" if abs(float(p["angular_distortion"]) - pmax) < 1e-12
                                          else ""))]
                     for p in pairs],
        })
    return blocks


def pile_notes(res, geo):
    ng = [c for c in res.get("checks", []) if not c.get("ok")]
    tens = [p for p in geo["piles"] if p["P"] < -1e-9]
    n = ["1. 本圖為樁位配置圖：樁位 (x,y) 與逐樁軸力取自 foundation_pile 結果；樁徑、樁長、"
         "樁帽尺寸與配筋未由計算器決定，圖上樁以符號表示（圓的大小不代表實際樁徑），"
         "不得作為樁帽配筋圖使用。",
         "2. 座標原點即計算輸入的 (0,0)，十字為樁群形心；單位 m。",
         "3. 樁軸力採等勁度、剛性樁帽假設；未含側向力、群樁效率、沉陷與上舉。",
         "4. 最大／最小樁軸力與容許值之比對見摘要表，數值取自 checks。"]
    if tens:
        n.append("%d. 有 %d 支樁出現拉力（軸力負值），圖上已標「拉力」，須另行檢核抗拉與上舉。"
                 % (len(n) + 1, len(tens)))
    n.append("%d. %s" % (len(n) + 1, "本題檢核全部通過。" if not ng
                         else "本題有 %d 項檢核未通過，不得施工。" % len(ng)))
    n.append("%d. 本工具一次只出單張 A3；1:%d 仍放不下時直接報錯，尚未實作分張。"
             % (len(n) + 1, MAX_SHEET_SCALE))
    if geo["n"] > MAX_LIST_PILES:
        n.append("%d. 樁數 %d 超過 %d，右欄不逐樁列表；逐樁軸力仍標在圖上。"
                 % (len(n) + 1, geo["n"], MAX_LIST_PILES))
    return n


def settlement_notes(res, geo):
    ad = res.get("angular_distortion") or {}
    bad = [f for f in geo["footings"] if not f["ok"]]
    n = ["1. 本圖為基腳沉陷配置圖：基腳位置、B×L 與沉陷量取自 settlement_assessment；"
         "基腳埋深、高程與柱位未由計算器決定，平面僅示意相對位置。",
         "2. 總沉陷＝瞬時＋壓密＋次壓縮三項相加，分項見右表；容許總沉陷取自結果。",
         "3. 角變量為相鄰基腳配對中扣除剛體轉動（%s 迴歸）後的最大值，＊為控制配對。"
         % str(ad.get("rigid_body_model") or "plane"),
         "4. 沉陷與角變量為篩選分析，非土壤－結構互制；未含未壓密土層、樁基側向反應與筏基 FEM。"]
    if bad:
        n.append("%d. 有 %d 座基腳總沉陷超過容許值（圖上標「超限」），不得施工。"
                 % (len(n) + 1, len(bad)))
    n.append("%d. %s" % (len(n) + 1, "本題檢核全部通過。" if res.get("pass")
                         else "本題有未通過項目，不得施工。"))
    n.append("%d. 本工具一次只出單張 A3；1:%d 仍放不下時直接報錯，尚未實作分張。"
             % (len(n) + 1, MAX_SHEET_SCALE))
    return n


def main():
    ap = argparse.ArgumentParser(description="樁位配置圖／基腳沉陷配置圖（D10）")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto", help="比例；auto 由配置範圍決定")
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--unit", default="m", choices=["m", "cm"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--drafter", default="Claude（AI）")
    ap.add_argument("--sheet-no", default=None)
    ap.add_argument("--rebar", action="store_true")
    ap.add_argument("--template", default=MWS.TEMPLATE)
    a = ap.parse_args()

    case, values, model = load_case(a.case)
    pile = model == "pile_group"
    res = run_engine("foundation_pile" if pile else "settlement_assessment", values)
    geo = pile_geo(res) if pile else footing_geo(res)

    H = pick_scale(geo) if str(a.scale).lower() == "auto" else int(a.scale)
    DR.require_standard_scale(H)
    if H > MAX_SHEET_SCALE:
        raise SystemExit("比例 1:%d 超出本圖可用上限 1:%d，請改用 auto 或分批出圖。"
                         % (H, MAX_SHEET_SCALE))
    x0, y0, x1, y1 = geo["bbox"]
    cw_m, ch_m = content_size(geo, H)
    if cw_m * 1000.0 / H > 183.0 or ch_m * 1000.0 / H > 249.45:
        raise SystemExit("1:%d 版面 %.1f×%.1f mm 超出 A3 可繪區（183×249 mm），"
                         "請改比例或分批出圖。" % (H, cw_m * 1000.0 / H, ch_m * 1000.0 / H))

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
    ensure_layers(doc, "pile" if pile else "settlement")
    if pile:
        draw_pile(doc, res, geo, H)
        blocks, notes = pile_blocks(res, geo), pile_notes(res, geo)
        title, no = "樁位配置圖", (a.sheet_no or "FP-1")
    else:
        draw_settlement(doc, res, geo, H)
        blocks, notes = settlement_blocks(res, geo), settlement_notes(res, geo)
        title, no = "基腳沉陷配置圖", (a.sheet_no or "FS-1")

    proj = a.project or (case.get("project") or {}).get("full_name") or title
    MBS.build_paper(doc, {}, case, H, proj, no,
                    {"blocks": blocks, "notes": notes}, title, no,
                    unit=a.unit, drafter=a.drafter)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  %s 比例尺 1:%d、%d 件、配置範圍 %.1f×%.1f m、版面 %.1f×%.1f mm"
          % (no, H, geo["n"], x1 - x0, y1 - y0,
             cw_m * 1000.0 / H, ch_m * 1000.0 / H))
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
