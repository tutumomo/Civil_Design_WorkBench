# -*- coding: utf-8 -*-
"""社區公園景觀配置圖：模型空間（公尺、TWD97）→ A3 圖紙（1:200）→ DWG／PDF／PNG。

設計資料全部來自 `park_layout.py`（平面圖與 3D 共用同一份座標），本檔只負責「畫」。

用法（專案 .venv）：
    .venv/bin/python tools/park_plan/make_park_plan.py --out "out/社區公園_40x25" --publish --check

產出（--out 目錄內）：
    <案名>_景觀配置平面圖_A3.dxf/.dwg/.pdf/.png
    <案名>_景觀配置平面圖_A3_check.json（E1~E18 品管結果）

出圖規定（`本項目的出圖規定(不定期新增).md`）：
    * 圖紙字高 本文 3／附註 4／標題 5 mm；模型空間字高 = 3 × 200/1000 = 0.6 m
    * 比例 1:200（標準比例尺）
    * 圖層顏色 1~8 對應固定線粗、出圖型式 monochrome.ctb（`tools/drawing_rules.py`）
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

import matplotlib                                   # AGENTS.md §3：一定要先設 Agg
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
import numpy as np                                  # noqa: E402
import ezdxf                                        # noqa: E402
from ezdxf.enums import TextEntityAlignment as TA   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools" / "park_plan"),
                str(ROOT / "tools" / "acad")]
from drawing_rules import (H_BODY, H_NOTE, H_TITLE, model_h, require_standard_scale,  # noqa: E402
                           add_plot_layer, tag_plot_style)
import park_layout as P                             # noqa: E402

TEMPLATE = ROOT / "tools" / "a3_sheet" / "A3圖框_template.dxf"
LAYOUT = "全區工程位置圖"

# ---------------------------------------------------------------- 版面（紙面 mm）
VP_X, VP_Y = 16.0, 66.0          # 視口左下角
VP_W, VP_H = 224.0, 150.0        # 視口尺寸（1:200 → 涵蓋 44.8 × 30.0 m）
COL_X = 246.0                    # 右欄左緣
COL_R = 360.0                    # 右欄右緣（不得超過 363.5，技師圖記區起點）

# ---------------------------------------------------------------- 圖層（顏色 → 線粗）
LAYERS = {
    "01_地界線": 6,        # 0.40 最重要
    "02_周邊道路": 8,      # 0.10
    "03_鄰地範圍": 8,
    "05_等高線": 8,
    "06_高程點": 7,
    "10_步道": 5,          # 0.35
    "11_步道_HATCH": 8,
    "12_廣場": 5,
    "13_廣場_HATCH": 8,
    "20_水池": 5,
    "21_水池_水面": 3,
    "22_景觀石牆": 4,      # 0.25
    "30_喬木": 3,          # 0.20
    "31_灌木": 3,
    "32_草紋": 8,
    "40_景觀燈": 1,        # 0.20
    "41_石造座椅": 4,
    "50_尺寸標註": 7,
    "51_圖說指引": 7,
    "93_圖例": 7,
    "94_植栽表": 7,
    "95_說明": 7,
    "91_指北針": 7,
    "92_比例尺": 7,
}


def build(args):
    scale = require_standard_scale(args.scale)
    K = scale / 1000.0
    HM, HN, HT = model_h(H_BODY, scale), model_h(H_NOTE, scale), model_h(H_TITLE, scale)

    # ------------------------------------------------------------ 主檔＝圖框樣板
    doc = ezdxf.readfile(TEMPLATE)
    lay = doc.layouts.get(LAYOUT)
    if lay is None:
        raise SystemExit(f"樣板沒有布局 {LAYOUT!r}")
    msp = doc.modelspace()
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    for name, color in LAYERS.items():
        add_plot_layer(doc, name, color=color)

    # TOMO 已存在（樣板），保險起見補一次
    if "TOMO" not in doc.styles:
        st = doc.styles.add("TOMO", font="gbenor.shx")
        st.dxf.bigfont = "CHINA1.SHX"
    ST = {"style": "TOMO"}

    # ------------------------------------------------------------ 繪圖小工具
    # 設計資料是局部座標（原點在公園西南角）；**所有圖元在寫入時平移到 TWD97**，
    # 否則模型在 (0,0) 附近、視口卻指著 E215020 → 圖紙上空無一物（2026-11-07 踩過）。
    OX, OY = P.ORIGIN_E, P.ORIGIN_N

    def T(x, y):
        return (float(x) + OX, float(y) + OY)

    def poly(pts, layer, closed=True):
        msp.add_lwpolyline([T(x, y) for x, y in pts], close=closed,
                           dxfattribs={"layer": layer})

    def line(p0, p1, layer):
        msp.add_line(T(*p0), T(*p1), dxfattribs={"layer": layer})

    def circle(c, r, layer):
        msp.add_circle(T(*c), float(r), dxfattribs={"layer": layer})

    def txt(s, x, y, layer, h=HM, align=TA.MIDDLE_CENTER, rot=0.0):
        t = msp.add_text(s, height=h, dxfattribs={"layer": layer, "rotation": rot, **ST})
        t.set_placement(T(x, y), align=align)

    def hatch(pts_list, layer, pattern="ANSI31", scale_=2.0, angle=45.0):
        """pts_list：第一個為外框，其餘為孔洞（島）；圖層顏色由圖層決定。"""
        h = msp.add_hatch(dxfattribs={"layer": layer})
        h.set_pattern_fill(pattern, scale=scale_, angle=angle)
        h.paths.add_polyline_path([T(x, y) for x, y in pts_list[0]], is_closed=True)
        for hole in pts_list[1:]:
            h.paths.add_polyline_path([T(x, y) for x, y in hole], is_closed=True)
        h.dxf.hatch_style = 0        # normal（島嶼鏤空）
        return h

    # CADCraft 出圖**不畫模型空間的「圖案填充（pattern hatch）」**（實測 ANSI31／NET 皆空白，
    # 但 SOLID 填充正常）；紙空間的 hatch 正常。因此鋪面、灌木、座椅的質感一律
    # 用「明確的線」畫，不用 pattern hatch——這樣 AutoCAD 與 CADCraft 出圖都一致。

    def ticks_along(pts, half, spacing=0.55, layer="11_步道_HATCH", shrink=0.94):
        """沿中心線每 spacing 畫一道橫向短線（鋪面版縫）。"""
        L = P.polyline_length(pts, closed=True) if pts[0] == pts[-1] else P.polyline_length(pts)
        total = P.polyline_length(pts, closed=False)
        n = max(1, int(total / spacing))
        for i in range(n):
            s_ = (i + 0.5) * total / n
            x, y, (tx, ty) = P.walk_polyline(pts, False, s_)
            nx, ny = -ty, tx
            line((x - nx * half * shrink, y - ny * half * shrink),
                 (x + nx * half * shrink, y + ny * half * shrink), layer)

    def closed_ticks(pts, half, spacing=0.55, layer="11_步道_HATCH", shrink=0.94):
        """封閉環狀步道：沿整圈中心線每 spacing 一道橫線。"""
        total = P.polyline_length(pts, closed=True)
        n = max(1, int(total / spacing))
        for i in range(n):
            s_ = (i + 0.5) * total / n
            x, y, (tx, ty) = P.walk_polyline(pts, True, s_)
            nx, ny = -ty, tx
            line((x - nx * half * shrink, y - ny * half * shrink),
                 (x + nx * half * shrink, y + ny * half * shrink), layer)

    def dots_in(poly_pts, spacing=0.65, layer="13_廣場_HATCH", r=0.035):
        """鋪面點狀質感（洗石子）：格點落在多邊形內才畫。"""
        xs = [p_[0] for p_ in poly_pts]; ys = [p_[1] for p_ in poly_pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        yy = y0 + spacing / 2
        while yy < y1:
            xx = x0 + spacing / 2
            while xx < x1:
                if P.point_in_polygon(xx, yy, poly_pts):
                    circle((xx, yy), r, layer)
                xx += spacing
            yy += spacing

    def tufts_in(poly_pts, spacing=0.72, layer="31_灌木", s=0.16):
        """灌木叢點景：小 V 形葉叢。"""
        xs = [p_[0] for p_ in poly_pts]; ys = [p_[1] for p_ in poly_pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        yy = y0 + spacing / 2
        while yy < y1:
            xx = x0 + spacing / 2
            while xx < x1:
                if P.point_in_polygon(xx, yy, poly_pts):
                    line((xx - s, yy - s * 0.6), (xx, yy + s * 0.9), layer)
                    line((xx, yy + s * 0.9), (xx + s, yy - s * 0.6), layer)
                xx += spacing
            yy += spacing

    # ------------------------------------------------------------ 1. 邊界與周邊
    WIN_X0, WIN_Y0 = P.ORIGIN_E - 2.4 - P.ORIGIN_E, -4.0      # 視口涵蓋範圍（局部座標）
    WIN_X1, WIN_Y1 = 42.4, 26.0
    poly([(WIN_X0, WIN_Y0), (WIN_X1, WIN_Y0), (WIN_X1, WIN_Y1), (WIN_X0, WIN_Y1)],
         "03_鄰地範圍", True)

    # 周邊道路（南側，y<0）：路面邊線＋中心線（局部座標；本案測試基地臨 8 m 道路）
    poly([(-2.4, -2.20), (42.4, -2.20)], "02_周邊道路", False)
    poly([(-2.4, 0.0), (42.4, 0.0)], "02_周邊道路", False)
    poly([(-2.4, -1.10), (42.4, -1.10)], "02_周邊道路", False)
    txt("8 M 計畫道路", 4.0, -1.72, "02_周邊道路", HM)
    txt("人行道 1.10", 34.0, -0.60, "02_周邊道路", HM)

    # 地界線（粗、最重要）
    poly([(0, 0), (P.SITE_W, 0), (P.SITE_W, P.SITE_H), (0, P.SITE_H)], "01_地界線", True)
    for sx in (0.0, P.SITE_W):
        for sy in (0.0, P.SITE_H):
            line((sx - 0.30, sy), (sx + 0.30, sy), "01_地界線")
            line((sx, sy - 0.30), (sx, sy + 0.30), "01_地界線")

    # ------------------------------------------------------------ 2. 等高線
    gx = np.arange(-2.0, 42.01, 0.20)
    gy = np.arange(-3.6, 26.01, 0.20)
    Z = np.array([[P.terrain_z(float(x), float(y)) for x in gx] for y in gy])
    levels = [round(v, 2) for v in np.arange(0.20, 1.35, 0.20)]
    cs = plt.contour(gx, gy, Z, levels=levels)

    def grass_ok(x, y):
        return P.path_offset(x, y) > 0.05 and not P.in_plaza(x, y)

    for lev, segs in zip(cs.levels, cs.allsegs):
        for seg in segs:
            run = []
            for x, y in seg:
                if grass_ok(x, y):
                    run.append((x, y))
                else:
                    if len(run) >= 2:
                        poly(run, "05_等高線", False)
                    run = []
            if len(run) >= 2:
                poly(run, "05_等高線", False)
    plt.close("all")

    # 高程標註：丘頂與入口廣場
    def spot(x, y, z=None, label=None):
        z = P.terrain_z(x, y) if z is None else z
        s = 0.28
        poly([(x - s, y), (x, y + s * 1.25), (x + s, y)], "06_高程點", True)
        txt(f"{z:.2f}", x, y + s * 2.1, "06_高程點", HM,
            align=TA.BOTTOM_CENTER)

    for m in P.MOUNDS:
        spot(m["cx"], m["cy"], P.GRADE + m["h"])
    spot(20.0, 0.9, P.GRADE)
    spot(3.0, 3.0, P.terrain_z(3.0, 3.0))

    # ------------------------------------------------------------ 3. 步道與廣場
    for p in P.PATHS:
        ring = P.ribbon(p["pts"], p["width"] / 2.0, closed=p["closed"])
        if p["closed"]:
            n = len(ring) // 2
            outer, inner = ring[:n], ring[n:][::-1]
            poly(outer, "10_步道", True)
            poly(inner, "10_步道", True)
            closed_ticks(p["pts"], p["width"] / 2.0, spacing=0.55)
        else:
            poly(ring, "10_步道", True)
            ticks_along(p["pts"], p["width"] / 2.0, spacing=0.55)

    # 入口廣場
    pr = P.PLAZA_RECT
    plaza = [(pr[0], pr[1]), (pr[2], pr[1]), (pr[2], pr[3]), (pr[0], pr[3])]
    poly(plaza, "12_廣場", True)
    node = P.PLAZA_NODE
    node_pts = [(node["cx"] + node["r"] * math.cos(2 * math.pi * i / 48),
                 node["cy"] + node["r"] * math.sin(2 * math.pi * i / 48)) for i in range(48)]
    poly(node_pts, "12_廣場", True)
    dots_in(plaza, spacing=0.60)
    dots_in(node_pts, spacing=0.60)

    # ------------------------------------------------------------ 4. 水池／景名牆
    po = P.POOL
    inner = [(po["x0"], po["y0"]), (po["x1"], po["y0"]), (po["x1"], po["y1"]), (po["x0"], po["y1"])]
    c = po["coping"]
    outer = [(po["x0"] - c, po["y0"] - c), (po["x1"] + c, po["y0"] - c),
             (po["x1"] + c, po["y1"] + c), (po["x0"] - c, po["y1"] + c)]
    poly(outer, "20_水池", True)
    poly(inner, "20_水池", True)
    # 池緣石：沿著外框每 0.45 m 一道放射短線（石塊分縫）
    for i in range(int((po["x1"] - po["x0"]) / 0.45) + 1):
        xx = po["x0"] + i * 0.45
        if xx > po["x1"]:
            xx = po["x1"]
        line((xx, po["y0"] - c), (xx, po["y0"]), "22_景觀石牆")
        line((xx, po["y1"]), (xx, po["y1"] + c), "22_景觀石牆")
    for i in range(int((po["y1"] - po["y0"]) / 0.45) + 1):
        yy = po["y0"] + i * 0.45
        if yy > po["y1"]:
            yy = po["y1"]
        line((po["x0"] - c, yy), (po["x0"], yy), "22_景觀石牆")
        line((po["x1"], yy), (po["x1"] + c, yy), "22_景觀石牆")
    # 水面波紋（水平線，週期性正弦）
    n_wave = 5
    for i in range(n_wave):
        y = po["y0"] + (po["y1"] - po["y0"]) * (i + 0.5) / n_wave
        pts = [(po["x0"] + (po["x1"] - po["x0"]) * t / 40,
                y + 0.05 * math.sin(t * 0.9 + i)) for t in range(41)]
        poly(pts, "21_水池_水面", False)
    # 落水牆（景石）
    sp = po["spout"]
    poly([(sp["x0"], sp["y0"]), (sp["x1"], sp["y0"]), (sp["x1"], sp["y1"]), (sp["x0"], sp["y1"])],
         "22_景觀石牆", True)
    for i in range(1, 4):
        xx = sp["x0"] + (sp["x1"] - sp["x0"]) * i / 4
        line((xx, sp["y0"]), (xx, sp["y1"]), "22_景觀石牆")
    txt("石砌落水牆", sp["x0"] - 0.2, sp["y1"] + 0.55, "22_景觀石牆", HM,
        align=TA.MIDDLE_RIGHT)
    line((sp["x0"] - 0.15, sp["y1"] + 0.5), (sp["x0"] + 0.1, sp["y1"] + 0.1), "51_圖說指引")

    for w in P.NAME_WALLS:
        x0, x1, y, th = w["x0"], w["x1"], w["y"], w["thick"]
        rect = [(x0, y - th / 2), (x1, y - th / 2), (x1, y + th / 2), (x0, y + th / 2)]
        poly(rect, "22_景觀石牆", True)
        line((x0, y), (x1, y), "22_景觀石牆")
    for m in P.MONOLITHS:
        rect = [(m["x"] - m["w"] / 2, m["y"] - m["d"] / 2), (m["x"] + m["w"] / 2, m["y"] - m["d"] / 2),
                (m["x"] + m["w"] / 2, m["y"] + m["d"] / 2), (m["x"] - m["w"] / 2, m["y"] + m["d"] / 2)]
        poly(rect, "22_景觀石牆", True)
        line((rect[0][0], rect[0][1]), (rect[2][0], rect[2][1]), "22_景觀石牆")
    txt("社區公園", 18.05, 0.32, "22_景觀石牆", HN)
    txt("入口廣場", 23.2, 0.95, "51_圖說指引", HM)

    # ------------------------------------------------------------ 5. 草紋（草地）
    rng = np.random.default_rng(20261107)
    tufts = 0
    for gx_i in np.arange(0.6, P.SITE_W, 1.25):
        for gy_i in np.arange(0.6, P.SITE_H, 1.25):
            x = gx_i + float(rng.uniform(-0.22, 0.22))
            y = gy_i + float(rng.uniform(-0.22, 0.22))
            if not (0.4 < x < P.SITE_W - 0.4 and 0.4 < y < P.SITE_H - 0.4):
                continue
            if P.path_offset(x, y) < 0.30 or P.in_plaza(x, y):
                continue
            if any(P.point_in_polygon(x, y, sp_) for _, sp_ in P.SHRUB_POLYS):
                continue
            if any(math.hypot(x - t["x"], y - t["y"]) < 1.7 for t in P.TREES):
                continue
            if (po["x0"] - 0.6 < x < po["x1"] + 0.6) and (po["y0"] - 0.6 < y < po["y1"] + 0.6):
                continue
            s = 0.16
            for dx in (-0.10, 0.0, 0.10):
                line((x + dx, y), (x + dx * 1.7, y + s), "32_草紋")
            tufts += 1

    # ------------------------------------------------------------ 6. 植栽
    for b, bed in P.SHRUB_POLYS:
        poly(bed, "31_灌木", True)
        tufts_in(bed, spacing=1.05, s=0.14)
        cx = sum(p_[0] for p_ in bed) / len(bed)
        cy = sum(p_[1] for p_ in bed) / len(bed)
        txt(b["code"], cx, cy, "31_灌木", HM)

    for t in P.TREES:
        # 樹冠採「雲朵形」輪廓（景觀圖慣例），不用放射線——放射線在 1:200 會與等高線混淆
        r = t["canopy"]
        pts = []
        for i in range(48):
            a = 2 * math.pi * i / 48
            rr = r * (1.0 + 0.055 * math.sin(9 * a) + 0.025 * math.sin(17 * a))
            pts.append((t["x"] + rr * math.cos(a), t["y"] + rr * math.sin(a)))
        poly(pts, "30_喬木", True)
        circle((t["x"], t["y"]), 0.14, "30_喬木")          # 樹幹
        txt(t["code"], t["x"], t["y"] + 0.30, "30_喬木", HM, align=TA.MIDDLE_CENTER)

    # ------------------------------------------------------------ 7. 燈具／座椅
    for l in P.LIGHTS:
        x, y = l["x"], l["y"]
        if l["kind"] == "bole":
            circle((x, y), 0.24, "40_景觀燈")
            for k in range(4):
                a = math.pi / 4 + k * math.pi / 2
                line((x + 0.24 * math.cos(a), y + 0.24 * math.sin(a)),
                     (x + 0.44 * math.cos(a), y + 0.44 * math.sin(a)), "40_景觀燈")
        else:
            circle((x, y), 0.36, "40_景觀燈")
            h = msp.add_hatch(dxfattribs={"layer": "40_景觀燈"})
            h.set_solid_fill(color=256)
            h.paths.add_polyline_path(
                [T(x + 0.36 * math.cos(2 * math.pi * i / 16),
                   y + 0.36 * math.sin(2 * math.pi * i / 16)) for i in range(16)], is_closed=True)
        txt(l["code"], x + 0.55, y + 0.5, "40_景觀燈", HM, align=TA.BOTTOM_LEFT)

    for b in P.BENCHES:
        a = math.radians(b["angle"])
        ca, sa = math.cos(a), math.sin(a)
        hl, hw = P.BENCH_L / 2, P.BENCH_W / 2
        corners = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
        rect = [(b["x"] + u * ca - v * sa, b["y"] + u * sa + v * ca) for u, v in corners]
        poly(rect, "41_石造座椅", True)
        for u in (-hl * 0.45, 0.0, hl * 0.45):
            line((b["x"] + u * ca - hw * 0.9 * sa, b["y"] + u * sa + hw * 0.9 * ca),
                 (b["x"] + u * ca + hw * 0.9 * sa, b["y"] + u * sa - hw * 0.9 * ca),
                 "41_石造座椅")
        # 兩塊石墩
        for u in (-hl + 0.30, hl - 0.30):
            seg = [(b["x"] + (u - 0.16) * ca - (hw + 0.06) * sa, b["y"] + (u - 0.16) * sa + (hw + 0.06) * ca),
                   (b["x"] + (u + 0.16) * ca - (hw + 0.06) * sa, b["y"] + (u + 0.16) * sa + (hw + 0.06) * ca)]
            line(seg[0], seg[1], "41_石造座椅")
        txt(b["code"], b["x"], b["y"] + 0.62, "41_石造座椅", HM)

    # ------------------------------------------------------------ 8. 尺寸標註
    ds = doc.dimstyles.new("PARK200")
    ds.dxf.dimtxt = HM
    ds.dxf.dimasz = 0.45
    ds.dxf.dimexe = 0.40
    ds.dxf.dimexo = 0.25
    ds.dxf.dimgap = 0.18
    ds.dxf.dimdec = 2
    ds.dxf.dimlunit = 2
    ds.dxf.dimtad = 1
    ds.dxf.dimtxsty = "TOMO"
    ds.dxf.dimclrd = 256
    ds.dxf.dimclre = 256
    ds.dxf.dimclrt = 256
    DIM = {"dimstyle": "PARK200", "layer": "50_尺寸標註"}

    def hdim(x0, x1, y, y_base):
        msp.add_linear_dim(base=T(x0, y_base), p1=T(x0, y), p2=T(x1, y),
                           dxfattribs=DIM).render()

    def vdim(y0, y1, x, x_base):
        msp.add_linear_dim(base=T(x_base, y0), p1=T(x, y0), p2=T(x, y1), angle=90,
                           dxfattribs=DIM).render()

    hdim(0.0, P.SITE_W, -0.15, -3.30)               # 總寬 40.00
    vdim(0.0, P.SITE_H, -0.15, -3.10)               # 總深 25.00
    hdim(pr[0], pr[2], -0.02, -0.72)                 # 入口廣場寬 10.00
    hdim(po["x0"], po["x1"], po["y0"] - 0.02, po["y0"] - 0.55)   # 水池 3.20
    vdim(po["y0"], po["y1"], po["x0"] - 0.32, po["x0"] - 0.95)
    # 步道寬度（取環狀步道右側垂直段）
    p_loop = P.PATHS[0]
    x_r, y_r, _ = P.walk_polyline(p_loop["pts"], True, 26.0)
    msp.add_aligned_dim(p1=T(x_r + P.PATH_W_MAIN / 2, y_r), p2=T(x_r - P.PATH_W_MAIN / 2, y_r),
                        distance=0.0, dxfattribs=DIM, override={"dimtad": 2}).render()
    txt("W=2.40", x_r + 0.95, y_r - 0.95, "50_尺寸標註", HM, align=TA.BOTTOM_LEFT)

    # ------------------------------------------------------------ 9. 圖紙空間：視口
    for vp in list(lay.query("VIEWPORT")):
        lay.delete_entity(vp)
    CE, CN = P.to_real(P.SITE_W / 2, (WIN_Y0 + WIN_Y1) / 2)
    vh_model = VP_H * K
    vp = lay.add_viewport(center=(VP_X + VP_W / 2, VP_Y + VP_H / 2), size=(VP_W, VP_H),
                          view_center_point=(CE, CN), view_height=vh_model,
                          dxfattribs={"layer": "Defpoints"})
    # status 必須是 2（1 代表「圖紙空間自身那個視口」，設 1 會讓 CADCraft 不出圖）
    vp.dxf.status = 2
    vp.dxf.flags = vp.dxf.flags | 16384          # 鎖定縮放

    # ------------------------------------------------------------ 10. 紙面輔助工具
    def ptxt(s, x, y, h=H_BODY, lyr="95_說明", align=TA.BOTTOM_LEFT, rot=0.0):
        t = lay.add_text(s, height=h, dxfattribs={"layer": lyr, "rotation": rot, **ST})
        t.set_placement((x, y), align=align)

    def pline(pts, lyr, closed=False):
        lay.add_lwpolyline([(float(x), float(y)) for x, y in pts], close=closed,
                           dxfattribs={"layer": lyr})

    def pcircle(c, r, lyr):
        lay.add_circle((c[0], c[1]), r, dxfattribs={"layer": lyr})

    def phatch(pts, lyr, pattern="ANSI31", scale_=0.6, angle=45):
        h = lay.add_hatch(dxfattribs={"layer": lyr})
        h.set_pattern_fill(pattern, scale=scale_, angle=angle)
        h.paths.add_polyline_path([(float(x), float(y)) for x, y in pts], is_closed=True)
        return h

    # 指北針（右欄上緣）
    ax, ay, R = COL_R - 12, 272.0, 6.0
    pcircle((ax, ay), R, "91_指北針")
    tip, lft = (ax, ay + R * 1.25), (ax - R * 0.5, ay - R * 0.85)
    rgt, ntc = (ax + R * 0.5, ay - R * 0.85), (ax, ay - R * 0.2)
    pline([tip, rgt, ntc, lft], "91_指北針", True)
    hh = lay.add_hatch(dxfattribs={"layer": "91_指北針"})
    hh.set_solid_fill(color=256)
    hh.paths.add_polyline_path([tip, ntc, lft], is_closed=True)
    ptxt("N", ax, ay + R * 1.55, H_NOTE, "91_指北針", TA.BOTTOM_CENTER)

    # 比例尺（右欄）
    seg_mm, bx, by, bh = 10.0, COL_X - 6, 254.0, 2.2
    for i in range(5):
        sx = bx + i * seg_mm
        pline([(sx, by), (sx + seg_mm, by), (sx + seg_mm, by + bh), (sx, by + bh)],
              "92_比例尺", True)
        if i % 2 == 0:
            hb = lay.add_hatch(dxfattribs={"layer": "92_比例尺"})
            hb.set_solid_fill(color=256)
            hb.paths.add_polyline_path([(sx, by), (sx + seg_mm, by),
                                        (sx + seg_mm, by + bh), (sx, by + bh)], is_closed=True)
    seg_m = seg_mm * scale / 1000.0
    for i in range(6):
        ptxt(f"{seg_m*i:g}", bx + i * seg_mm, by + bh + 1.0, H_BODY, "92_比例尺", TA.BOTTOM_CENTER)
    ptxt("m", bx + 5 * seg_mm + 5.5, by + bh + 1.0, H_BODY, "92_比例尺", TA.BOTTOM_LEFT)
    ptxt(f"S = 1:{scale}", bx, by - 4.2, H_BODY, "92_比例尺", TA.BOTTOM_LEFT)

    # ------------------------------------------------------------ 11. 圖例
    ly = 243.0
    ptxt("圖　例", COL_X, ly, H_NOTE, "93_圖例")
    lyr_items = [
        ("步道（透水鋪面）", "path"),
        ("入口廣場（洗石子）", "plaza"),
        ("景觀水池", "pool"),
        ("喬木（含樹冠投影）", "tree"),
        ("灌木群植", "shrub"),
        ("石造座椅", "bench"),
        ("景觀燈（矮柱／高燈）", "lamp"),
    ]
    row = ly - 7.0
    for label, kind in lyr_items:
        sx0, sx1 = COL_X, COL_X + 20
        syc = row + 1.2
        if kind == "path":
            pline([(sx0, syc - 2.4), (sx1, syc - 2.4), (sx1, syc + 2.4), (sx0, syc + 2.4)],
                  "93_圖例", True)
            for i in range(7):
                xx = sx0 + 2.0 + i * 2.6
                pline([(xx, syc - 2.2), (xx + 1.6, syc + 2.2)], "11_步道_HATCH")
        elif kind == "plaza":
            pline([(sx0, syc - 2.4), (sx1, syc - 2.4), (sx1, syc + 2.4), (sx0, syc + 2.4)],
                  "93_圖例", True)
            for i in range(5):
                for j in range(2):
                    pcircle((sx0 + 2.5 + i * 3.6, syc - 1.1 + j * 2.2), 0.45, "13_廣場_HATCH")
        elif kind == "pool":
            pline([(sx0, syc - 2.4), (sx1, syc - 2.4), (sx1, syc + 2.4), (sx0, syc + 2.4)],
                  "93_圖例", True)
            for i in range(3):
                yy = syc - 1.4 + i * 1.4
                pline([(sx0 + 1.0 + t * 0.45, yy + 0.5 * math.sin(t * 1.0 + i))
                       for t in range(40)], "21_水池_水面")
        elif kind == "tree":
            pcircle((sx0 + 3.0, syc), 2.6, "93_圖例")
            pcircle((sx0 + 3.0, syc), 1.4, "93_圖例")
        elif kind == "shrub":
            pts = [(sx0 + 10.0 + 9.0 * math.cos(2 * math.pi * i / 24) * (1 + 0.06 * math.sin(i * 2.2)),
                    syc + 2.2 * math.sin(2 * math.pi * i / 24)) for i in range(24)]
            pline(pts, "93_圖例", True)
            for i in range(4):
                xx = sx0 + 3.0 + i * 4.0
                pline([(xx - 1.2, syc - 1.2), (xx, syc + 1.4), (xx + 1.2, syc - 1.2)], "31_灌木")
        elif kind == "bench":
            pline([(sx0 + 1.0, syc - 1.0), (sx0 + 9.0, syc - 1.0),
                   (sx0 + 9.0, syc + 1.0), (sx0 + 1.0, syc + 1.0)], "93_圖例", True)
            for i in range(5):
                xx = sx0 + 1.8 + i * 1.7
                pline([(xx, syc - 0.9), (xx, syc + 0.9)], "41_石造座椅")
        else:
            pcircle((sx0 + 5.0, syc), 1.1, "93_圖例")
            for k in range(4):
                a = math.pi / 4 + k * math.pi / 2
                pline([(sx0 + 5.0 + 1.1 * math.cos(a), syc + 1.1 * math.sin(a)),
                       (sx0 + 5.0 + 2.0 * math.cos(a), syc + 2.0 * math.sin(a))], "93_圖例")
        ptxt(label, sx1 + 4.0, row, H_BODY, "93_圖例")
        row -= 7.0

    # ------------------------------------------------------------ 12. 植栽表
    q = P.quantities()
    ty = 186.0
    ptxt("植栽表", COL_X, ty, H_NOTE, "94_植栽表")
    cols = [(COL_X, COL_X + 12), (COL_X + 14, COL_X + 36),
            (COL_X + 38, COL_X + 84), (COL_X + 88, COL_R)]
    head = ["編號", "樹種", "規格", "數量"]
    rows = []
    seen = {}
    for t in P.TREES:
        seen.setdefault(t["sp"], []).append(t["code"])
    for i, (sp, codes) in enumerate(seen.items()):
        spec = P.TREE_SPECS[sp]
        short = {"苦楝": "H6-8m D12cm", "臺灣欒樹": "H6-9m D12cm", "樟樹": "H7-9m D15cm",
                 "光蠟樹": "H5-7m D10cm", "茄苳": "H6-9m D12cm"}[sp]
        rows.append([f"T{i+1:02d}", sp, short, f"{len(codes)} 株"])
    rows.append(["S", "灌木", "3 株/m2", f"{q['shrub_count']} 株"])

    gy0 = ty - 6.0
    pline([(cols[0][0], gy0 + 4.6), (COL_R, gy0 + 4.6)], "94_植栽表")
    for i, (c0, c1) in enumerate(cols):
        pline([(c0, gy0 + 4.6), (c0, gy0 - 5.5 * len(rows) - 0.4)], "94_植栽表")
        ptxt(head[i], c0 + 1.2, gy0, H_BODY, "94_植栽表")
    pline([(COL_R, gy0 + 4.6), (COL_R, gy0 - 5.5 * len(rows) - 0.4)], "94_植栽表")
    pline([(cols[0][0], gy0 - 2.6), (COL_R, gy0 - 2.6)], "94_植栽表")
    for r, vals in enumerate(rows):
        yy = gy0 - 2.6 - 5.5 * (r + 1) + 1.2
        for i, v in enumerate(vals):
            ptxt(v, cols[i][0] + 1.2, yy, H_BODY, "94_植栽表")
    pline([(cols[0][0], gy0 - 5.5 * (len(rows) + 1)), (COL_R, gy0 - 5.5 * (len(rows) + 1))],
          "94_植栽表")

    # ------------------------------------------------------------ 13. 數量表
    qy = gy0 - 5.5 * (len(rows) + 1) - 9.0
    ptxt("主要數量表", COL_X, qy, H_NOTE, "94_植栽表")
    qrows = [
        ("基地面積", f"{q['site_area']:,.0f} m2"),
        ("步道（W=2.4）", f"{q['path_area']:.1f} m2 / {q['path_len_main']+q['path_len_link']:.1f} m"),
        ("廣場", f"{q['plaza_area']:.1f} m2"),
        ("水池", f"{q['pool_area']:.1f} m2（水深 0.37 m）"),
        ("灌木", f"{q['shrub_area']:.1f} m2"),
        ("草地", f"{q['grass_area']:.1f} m2"),
        ("喬木", f"{q['tree_count']} 株"),
        ("景觀燈", f"{q['light_count']} 盞（矮柱 {q['light_bole']}／高燈 {q['light_pole']}）"),
        ("石造座椅", f"{q['bench_count']} 座"),
    ]
    qy -= 6.0
    for name, val in qrows:
        ptxt(name, COL_X, qy, H_BODY, "94_植栽表")
        ptxt(val, COL_X + 34, qy, H_BODY, "94_植栽表")
        qy -= 5.5

    # ------------------------------------------------------------ 14. 說明
    ny = 59.0
    notes = [
        "1. 本圖為景觀配置平面圖，尺寸以公尺為單位，高程以公尺計。",
        "2. 基地 40.0 × 25.0 m＝1,000 m2；整地高程 EL.+0.05，土丘最高 EL.+1.30。",
        "3. 步道淨寬 2.40 m、縱坡小於 5%，採透水鋪面；水池水深 0.37 m，池底池壁 RC 防水粉刷。",
        "4. 喬木植穴 1.2 × 1.2 × 0.9 m 客土改良；灌木帶種植密度 3 株/m2。",
        "5. 矮柱燈高 0.90 m 間距約 8 m、高燈 3.50 m；高程以既有道路面為 ±0.00，施工前應實測放樣。",
    ]
    ptxt("說　明", 12.0, ny + 5.0, H_NOTE, "95_說明")
    for i, s_ in enumerate(notes):
        ptxt(s_, 12.0, ny - i * 6.5, H_BODY, "95_說明")

    # ------------------------------------------------------------ 15. 標題欄
    # 標題欄：**改字（圖名／案名／業主）＋ 標籤右側偏移填值**，不要另外疊一個新文字，
    # 否則會壓在樣板標籤上（E10 疊字）。此寫法與 tools/a3_sheet/make_sheet.py 一致。
    labels = {}
    for e in lay.query("TEXT"):
        labels.setdefault(e.dxf.text.replace(" ", ""), e)
        if e.dxf.text == "臺中市大雅區公所" and args.owner:
            e.dxf.text = args.owner
        if e.dxf.text == "圖名" and args.drawing:      # 只改值儲存格的占位字，不動「圖    名」標籤
            e.dxf.text = args.drawing
        if e.dxf.text == "案名" and args.project:
            e.dxf.text = args.project

    def fill(label, value, dx=12.6, dy=0.0):
        lb = labels.get(label)
        if lb is not None and value:
            ptxt(value, lb.dxf.insert.x + dx, lb.dxf.insert.y + dy, H_BODY, "圖框")

    fill("設計", args.designer, dx=13.0)
    fill("繪圖", args.drafter, dx=13.0)
    fill("日期", args.date, dx=13.0)
    fill("比例尺", f"1/{scale}", dx=15.5)
    fill("圖序", args.sheet, dx=14.5)

    tag_plot_style(doc)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dxf_path = out / f"{args.name}_景觀配置平面圖_A3.dxf"
    doc.saveas(dxf_path)

    result = dict(dxf=str(dxf_path), tufts=tufts, extents=[WIN_X0, WIN_Y0, WIN_X1, WIN_Y1],
                  viewport=[VP_X, VP_Y, VP_W, VP_H], scale=scale)
    return result, dxf_path, q


def main():
    ap = argparse.ArgumentParser(description="社區公園景觀配置平面圖（A3 / 1:200）")
    ap.add_argument("--out", default=str(ROOT / "out" / "社區公園_40x25"))
    ap.add_argument("--name", default="社區公園")
    ap.add_argument("--scale", type=int, default=200)
    ap.add_argument("--project", default="臺中市○○社區公園景觀改善工程")
    ap.add_argument("--drawing", default="景觀配置平面圖")
    ap.add_argument("--owner", default="○○社區發展協會")
    ap.add_argument("--designer", default="景觀設計：AI 協作（技師覆核）")
    ap.add_argument("--drafter", default="繪圖：AI 協作")
    ap.add_argument("--date", default="民國 115 年 11 月 07 日")
    ap.add_argument("--sheet", default="1/1")
    ap.add_argument("--publish", action="store_true", help="另存 DWG 並出 PDF（CADCraft／AutoCAD）")
    ap.add_argument("--check", action="store_true", help="跑 check_delivery E1~E18 品管")
    ap.add_argument("--png", action="store_true", help="PDF 轉 PNG 預覽")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    P.validate(verbose=True)
    res, dxf_path, qty = build(args)
    print("模型 DXF：", dxf_path)
    print("草紋符號：", res["tufts"], "　視口：", res["viewport"], "　比例 1:%d" % res["scale"])

    out = Path(args.out)
    if args.publish:
        from acc import publish
        got = publish(str(dxf_path), pdf=True)
        print("出圖：", {k: os.path.basename(v) for k, v in got.items()})

    if args.png:
        pdf = out / f"{args.name}_景觀配置平面圖_A3.pdf"
        if pdf.exists():
            png = out / f"{args.name}_景觀配置平面圖_A3.png"
            subprocess.run(["pdftoppm", "-r", "200", "-png", "-singlefile", str(pdf), str(png.with_suffix(""))],
                           check=False)
            print("PNG：", png)

    if args.check:
        chk = out / f"{args.name}_景觀配置平面圖_A3_check.json"
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "a3_sheet" / "check_delivery.py"),
                            str(dxf_path), "--scale", str(args.scale), "--require-dwg",
                            "--require-layer", "10_步道", "--require-layer", "30_喬木",
                            "--require-layer", "20_水池", "--json", str(chk)],
                           capture_output=True, text=True)
        print(r.stdout[-4000:])
        if r.stderr.strip():
            print("check stderr:", r.stderr[-1200:])
        print("check 退出碼 =", r.returncode)

    if args.json:
        Path(args.json).write_text(
            __import__("json").dumps(dict(result=res, quantities=qty), ensure_ascii=False, indent=1),
            encoding="utf-8")


if __name__ == "__main__":
    main()
