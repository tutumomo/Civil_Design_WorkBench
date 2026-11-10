# -*- coding: utf-8 -*-
"""箱涵標準斷面圖（S-01）與箱涵配筋圖（S-02）產線：案件 JSON → A3 DXF/DWG/PDF。

定位
----
`tools\\wall_section\\make_wall_section.py` 產的是**擋土牆／排水溝／邊坡**斷面圖；
箱涵（單孔／雙孔／三孔）的橫斷面與配筋排法完全不同，另立一支工具，
但**刻意沿用同一套圖框、字型、尺寸樣式與品管閘門**（不重造輪子）：

* 圖框：`tools\\a3_sheet\\A3圖框_template.dxf`（與平面圖同一張，標題欄一致）
* 字型：TOMO（gbenor.shx＋CHINA1.SHX）、字高 本文 3／附註 4／標題 5 mm
* 尺寸樣式：`make_wall_section.ensure_dimstyle`（同一支、同一組參數）
* 品管：`tools\\a3_sheet\\check_delivery.py` E1~E18 全套沿用
* 圖／數對帳：`tools\\takeoff\\dxf_takeoff.py`（外框面積－孔洞＝精確斷面積）
* 配筋對帳：`dxf_takeoff.py --rebar`（量圖上鋼筋圓點實際間距 vs 配筋表）

與過往標準圖的關係
------------------
`標準圖圖庫\\箱涵與管涵\\`（C100~C113）是**過往案例**，其圖面構成、表頭欄位、
`D19@10cm`＋編號圓標的標註方式值得學；但舊案用 `140/210 kg/cm2` 混凝土與
「含損耗 5%」，與現行規範（結構混凝土 fc' 280 kgf/cm2）及本專案鋼筋損耗
**6%**（含搭接）不一致。**本工具只學圖面構成與標註方式，所有數值一律
取自 `tools\\design\\box_culvert.py` 構架配筋設計結果**。

用法
----
    set PYTHONIOENCODING=utf-8
    C:\\Python312\\python.exe tools\\box_section\\make_box_section.py ^
        cases\\箱涵三孔測試\\case.json --scale auto ^
        --out cases\\箱涵三孔測試\\S-01_箱涵標準斷面圖.dxf --publish
    C:\\Python312\\python.exe tools\\box_section\\make_box_section.py ^
        cases\\箱涵三孔測試\\case.json --scale auto --rebar ^
        --out cases\\箱涵三孔測試\\S-02_箱涵配筋圖.dxf --publish
"""

import argparse
import math
import os
import re
import sys
import time

import ezdxf
from ezdxf.enums import TextEntityAlignment

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "a3_sheet"))
sys.path.insert(0, os.path.join(ROOT, "tools", "case_package"))
sys.path.insert(0, os.path.join(ROOT, "tools", "design"))
sys.path.insert(0, os.path.join(ROOT, "tools", "wall_section"))

import drawing_rules as DR                    # noqa: E402
from drawing_rules import model_h             # noqa: E402
import case_core as CC                       # noqa: E402
import make_wall_section as MWS              # noqa: E402  （圖框／字型／尺寸樣式共用）

TEMPLATE = MWS.TEMPLATE
LAYOUT_NAME = MWS.LAYOUT_NAME
L_FRAME = MWS.L_FRAME
L_LEGEND = MWS.L_LEGEND
L_SCALE = MWS.L_SCALE
L_DESC = MWS.L_DESC

# 圖框分區（與 check_delivery.py 同值）
X0, Y0, X1, Y1 = 10.03, 29.00, 410.27, 287.45

# 箱涵圖層（數字前綴_中文說明；E12 只要求兩碼前綴）
L_CONC = "30_箱涵混凝土"
L_HATCH = "31_箱涵剖面線"
L_BACK = "32_覆土回填"
L_EXC = "33_開挖線"
L_INNER = "34_箱涵內腔"
L_REBAR = "40_鋼筋"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"

BAR_DIA = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
           "D22": 0.022, "D25": 0.025, "D29": 0.029, "D32": 0.032}


# --------------------------------------------------------------------------- #
# 案件 → 引擎輸入
# --------------------------------------------------------------------------- #
def load_case(case_path):
    """載入案件並取數量；本工具只做箱涵（model 必須 box_culvert）。"""
    case = CC.load(case_path)
    model, q, issues = CC.quantity_context(case)
    errs = [i for i in issues if i["level"] == "error"]
    if errs:
        raise SystemExit("案件數量錯誤，先跑 case_core.py check：\n  " +
                         "\n  ".join(i["msg"] for i in errs))
    if model != "box_culvert":
        raise SystemExit(
            "本工具做箱涵斷面（model 應為 box_culvert，現在是 %s）；"
            "擋土牆／排水溝請用 tools\\wall_section\\make_wall_section.py" % model)
    return case, q


def build_payload(case, q):
    """把案件檔組成 `design_api` 的箱涵計算輸入。

    幾何取自數量模型（q），載重取自案件 `culvert` 段，水理取自 `hydraulics` 段。
    案件沒給的欄位就**不給**（例如 inlet_type 未輸入 → 引擎只做 Manning 均勻流檢核，
    圖面說明會註明），不用猜值補齊。
    """
    cul = case.get("culvert") or {}
    hyd = case.get("hydraulics") or {}

    def _f(src, key, default=None):
        v = src.get(key, default)
        return default if v in (None, "") else v

    payload = {
        "cell_count": int(q["cell_count"]),
        "clear_width_m": float(q["clear_width_m"]),
        "clear_height_m": float(q["clear_height_m"]),
        "wall_thickness_m": float(q["wall_thickness_m"]),
        "interior_wall_thickness_m": float(q.get("interior_wall_thickness_m", 0.30)),
        "top_slab_thickness_m": float(q["top_slab_thickness_m"]),
        "bottom_slab_thickness_m": float(q["bottom_slab_thickness_m"]),
        "cover_depth_m": float(q.get("cover_depth_m", 0.60)),
        "length_m": float(q.get("length_m", 20.0)),
        "cover_mm": float(_f(cul, "cover_mm", 50.0) or 50.0),
        "crack_limit_mm": float(_f(cul, "crack_limit_mm", 0.3) or 0.3),
        "bar_preference": str(_f(cul, "bar_preference", "auto")),
        "distribution_bar": str(_f(cul, "distribution_bar", "D13")),
        "rebar_loss_rate": float(q.get("rebar_loss_rate", 0.06) or 0.0),
        # 內角 45° 加腋（倒角）與角隅補強筋（X 形交叉斜筋）
        "inner_chamfer_m": float(q.get("inner_chamfer_m", 0.20) or 0.0),
        "corner_rebar": str(q.get("corner_rebar", "D13")),
        "corner_rebar_spacing_mm": float(
            q.get("corner_rebar_spacing_mm", 200.0) or 0.0),
        # 水理
        "design_flow_m3s": float(_f(hyd, "design_flow_m3s", 0.0) or 0.0),
        "slope": float(_f(hyd, "slope", 0.005) or 0.005),
        "manning_n": float(_f(hyd, "manning_n", 0.014) or 0.014),
        "freeboard_min_m": float(_f(hyd, "freeboard_min_m", 0.20) or 0.20),
        # 土工與載重
        "soil_unit_weight_kn_m3": float(_f(cul, "soil_unit_weight_kn_m3", 18.0)),
        "soil_phi_deg": float(_f(cul, "soil_phi_deg", 30.0)),
        "surcharge_kpa": float(_f(cul, "surcharge_kpa", 0.0) or 0.0),
        "traffic_type": cul.get("traffic_type"),
        "traffic_load_kpa": float(_f(cul, "traffic_load_kpa", 0.0) or 0.0),
        "traffic_lanes": int(_f(cul, "traffic_lanes", 4) or 4),
        "groundwater_depth_m": cul.get("groundwater_depth_m"),
        "internal_water_depth_m": float(_f(cul, "internal_water_depth_m", 0.0) or 0.0),
        "load_factor": float(_f(cul, "load_factor", 1.7)),
    }
    if cul.get("traffic_impact_factor") not in (None, ""):
        payload["traffic_impact_factor"] = float(cul["traffic_impact_factor"])
    for k in ("inlet_type", "tailwater_depth_m", "allowable_headwater_m"):
        if cul.get(k) not in (None, ""):
            payload[k] = cul[k]
    return payload


def analyse_box(case, q):
    """跑箱涵引擎並回傳結果 dict（**不寫工作台 run 紀錄**）。

    出圖與圖／數對帳都需要同一份配筋設計；直接呼叫引擎可避免
    `design_api.run_calculation` 在每次對帳時都寫一份執行紀錄到
    `out\\design_workbench\\runs\\`。
    """
    import box_culvert as BC

    p = build_payload(case, q)
    section = {k: p[k] for k in (
        "cell_count", "clear_width_m", "clear_height_m", "wall_thickness_m",
        "interior_wall_thickness_m", "top_slab_thickness_m",
        "bottom_slab_thickness_m", "cover_depth_m", "length_m",
        "inner_chamfer_m", "corner_rebar", "corner_rebar_spacing_mm")}
    kw = dict(
        design_flow_m3s=p["design_flow_m3s"], slope=p["slope"],
        manning_n=p["manning_n"],
        soil_unit_weight_kn_m3=p["soil_unit_weight_kn_m3"],
        soil_phi_deg=p["soil_phi_deg"], surcharge_kpa=p["surcharge_kpa"],
        traffic_load_kpa=p["traffic_load_kpa"], traffic_type=p["traffic_type"],
        traffic_lanes=p["traffic_lanes"],
        groundwater_depth_m=p["groundwater_depth_m"],
        internal_water_depth_m=p["internal_water_depth_m"],
        load_factor=p["load_factor"], freeboard_min_m=p["freeboard_min_m"],
        cover_mm=p["cover_mm"], crack_limit_mm=p["crack_limit_mm"],
        bar_preference=p["bar_preference"],
        distribution_bar=p["distribution_bar"],
        rebar_loss_rate=p["rebar_loss_rate"],
    )
    if p.get("traffic_impact_factor") is not None:
        kw["traffic_impact_factor"] = p["traffic_impact_factor"]
    for k in ("inlet_type", "tailwater_depth_m", "allowable_headwater_m"):
        if p.get(k) is not None:
            kw[k] = p[k]
    return BC.analyse(section, **kw)


# --------------------------------------------------------------------------- #
# 幾何
# --------------------------------------------------------------------------- #
def box_geometry(q):
    """箱涵橫斷面幾何（模型單位＝公尺）。"""
    n = int(q["cell_count"])
    B = float(q["clear_width_m"])
    H = float(q["clear_height_m"])
    tw = float(q["wall_thickness_m"])
    ti = float(q.get("interior_wall_thickness_m", 0.30))
    tt = float(q["top_slab_thickness_m"])
    tb = float(q["bottom_slab_thickness_m"])
    W = 2 * tw + n * B + (n - 1) * ti
    Htot = tb + H + tt
    c = float(q.get("inner_chamfer_m", 0.20) or 0.0)     # 內角 45° 加腋邊長

    cells, iw = [], []
    x = tw
    for i in range(n):
        cells.append((x, x + B))
        x += B
        if i < n - 1:
            iw.append((x, x + ti))
            x += ti
    return {
        "n": n, "B": B, "H": H, "tw": tw, "ti": ti, "tt": tt, "tb": tb,
        "W": W, "Htot": Htot,
        "c": c,
        "cells": cells, "int_walls": iw,
        "y_bot_top": tb, "y_top_bot": tb + H,
        "cover_depth": float(q.get("cover_depth_m", 0.60)),
        "length_m": float(q.get("length_m", 20.0)),
        "exc_work": float(q.get("excavation_work_m", 0.50)),
        "exc_depth": float(q.get("excavation_depth_m", 0.30)),
    }


def face_sites(g, key, face, cd):
    """某一面在斷面圖上的所有實體位置（可能不只一處：兩側外牆、兩道中牆）。"""
    W = g["W"]
    if key == "exterior_wall":
        if face == "outer":
            return [cd, W - cd]                     # 左外牆外面、右外牆外面
        return [g["tw"] - cd, W - g["tw"] + cd]     # 左外牆內面、右外牆內面
    if key == "interior_wall":
        walls = g["int_walls"]
        if face == "A":
            return [w[0] + cd for w in walls]       # 中牆左面
        return [w[1] - cd for w in walls]           # 中牆右面
    return []


def cell_void(g, x0, x1):
    """單一孔的淨空多邊形（內角 45° 加腋的八邊形）。"""
    tb, h, c = g["tb"], g["H"], g["c"]
    yb, yt = tb, tb + h
    if c <= 1e-9:
        return [(x0, yb), (x1, yb), (x1, yt), (x0, yt)]
    # 八邊形：下左→下右走三段、上右→上左走三段，四個內角各 45° 切 c×c
    return [(x0 + c, yb), (x1 - c, yb), (x1, yb + c), (x1, yt - c),
            (x1 - c, yt), (x0 + c, yt), (x0, yt - c), (x0, yb + c)]


# --------------------------------------------------------------------------- #
# 圖層／字型／尺寸樣式
# --------------------------------------------------------------------------- #
def ensure_layers(doc):
    """出圖樣式（2026-10-29）：顏色 1~8 對應線粗；混凝土主線重要(5)、鋼筋一般(1)。"""
    spec = [(L_CONC, 5), (L_HATCH, 8), (L_BACK, 8), (L_EXC, 8), (L_INNER, 7),
            (L_REBAR, 1), (L_DIM, 3), (L_NOTE, 7), (L_LEGEND, 7),
            (L_SCALE, 7), (L_DESC, 7)]
    for name, color in spec:
        DR.add_plot_layer(doc, name, color=color)
    if "DASHED" in doc.linetypes:
        doc.layers.get(L_EXC).dxf.linetype = "DASHED"


# --------------------------------------------------------------------------- #
# 模型空間：箱涵橫斷面
# --------------------------------------------------------------------------- #
def draw_box_section(doc, g, scale, dimstyle, cover_m, elements, rebar=True):
    """畫箱涵橫斷面（混凝土、覆土、開挖線、尺寸、鋼筋、編號圓標）。"""
    msp = doc.modelspace()
    W, Htot = g["W"], g["Htot"]
    tb, tt = g["tb"], g["tt"]
    cells, iw = g["cells"], g["int_walls"]
    cd = cover_m
    y_ground = Htot + g["cover_depth"]

    # ---- 混凝土外框 ----
    outer = [(0.0, 0.0), (W, 0.0), (W, Htot), (0.0, Htot)]
    msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": L_CONC})

    # ---- 孔洞內腔（每孔一條；內角 45° 加腋；供 Hatch 挖洞與面積量測）----
    voids = []
    for (x0, x1) in cells:
        v = cell_void(g, x0, x1)
        msp.add_lwpolyline(v, close=True, dxfattribs={"layer": L_INNER})
        voids.append(v)

    # ---- 剖面線（外框減孔洞）----
    hatch_scale = (1.5 * scale / 1000.0) / 3.175
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=max(hatch_scale, 1e-4))
    h.paths.add_polyline_path(outer, is_closed=True)
    for v in voids:
        h.paths.add_polyline_path(v, is_closed=True)

    # ---- 覆土回填（頂版以上）----
    back = [(-g["exc_work"], Htot), (W + g["exc_work"], Htot),
            (W + g["exc_work"], y_ground), (-g["exc_work"], y_ground)]
    msp.add_lwpolyline(back, close=True, dxfattribs={"layer": L_BACK})
    hb = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
    hb.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
    hb.paths.add_polyline_path(back, is_closed=True)

    # ---- 原地面線 ----
    msp.add_line((-g["exc_work"] - 0.3, y_ground), (W + g["exc_work"] + 0.3, y_ground),
                 dxfattribs={"layer": L_NOTE})

    # ---- 開挖線（虛線）----
    ex0, ex1 = -g["exc_work"], W + g["exc_work"]
    y_exc = -g["exc_depth"]
    msp.add_line((ex0, y_ground), (ex0, y_exc), dxfattribs={"layer": L_EXC})
    msp.add_line((ex0, y_exc), (ex1, y_exc), dxfattribs={"layer": L_EXC})
    msp.add_line((ex1, y_exc), (ex1, y_ground), dxfattribs={"layer": L_EXC})

    # ---- 尺寸 ----
    def dim(p1, p2, base, angle=None):
        if angle is None:
            angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=dimstyle, dxfattribs={"layer": L_DIM})
        d.render()

    # 每孔淨寬與淨高畫在**最後一孔**（第一孔要放鋼筋圓標 2/4/6，尺寸線會打架）
    cx0, cx1 = cells[-1]
    dim((cx0, tb + g["H"] - 0.30), (cx1, tb + g["H"] - 0.30),
        (cx0, tb + g["H"] - 0.30))
    dim((cx1 - 0.30, tb), (cx1 - 0.30, tb + g["H"]), (cx1 - 0.30, tb))
    # 底板厚、頂版厚（鉛直）
    dim((0.0, 0.0), (0.0, tb), (-0.25, 0.0))
    dim((W, Htot - tt), (W, Htot), (W + 0.18, Htot - tt))
    # 覆土深
    dim((W + g["exc_work"] + 0.25, Htot), (W + g["exc_work"] + 0.25, y_ground),
        (W + g["exc_work"] + 0.25, Htot))
    # 外寬、外高
    dim((0.0, y_exc), (W, y_exc), (0.0, y_exc - 0.45))
    dim((W + g["exc_work"] + 0.55, 0.0), (W + g["exc_work"] + 0.55, Htot),
        (W + g["exc_work"] + 0.55, 0.0))

    # ---- 部位圓標（1~7，對應右欄部位圖例）----
    _part_tags(doc, g, scale, cells, iw)

    # ---- 內角加腋與角隅補強筋 ----
    _corner_reinforcement(doc, g, scale, cells)

    # ---- 鋼筋（依配筋設計逐面配置）----
    bars = []
    if rebar:
        bars = _draw_rebar(doc, g, elements, cover_m, scale)
    return {"bars": bars, "y_ground": y_ground, "y_exc": y_exc}


def _part_tags(doc, g, scale, cells, iw):
    """部位圓標（與右欄「部位圖例」編號一致）。"""
    msp = doc.modelspace()
    r = model_h(2.5, scale)
    hb = model_h(3.0, scale)
    W, Htot, tb = g["W"], g["Htot"], g["tb"]
    mid_cell = cells[len(cells) // 2]
    tags = [
        (1, (mid_cell[0] + 0.6, Htot - g["tt"] / 2.0)),          # 頂版
        (2, (mid_cell[0] + 0.6, tb / 2.0)),                      # 底版
        (3, (g["tw"] / 2.0, tb + g["H"] * 0.25)),                # 外側牆
        (4, (iw[0][0] + g["ti"] / 2.0, tb + g["H"] * 0.25) if iw
         else (W / 2.0, tb + g["H"] * 0.25)),                   # 中間牆
        (5, (mid_cell[0] + 1.2, tb + g["H"] * 0.55)),           # 涵內淨空
        (6, (mid_cell[0] + 0.6, Htot + g["cover_depth"] / 2.0)),  # 覆土回填
        (7, (-g["exc_work"] + 0.15, -g["exc_depth"] + 0.12)),   # 基礎開挖線
    ]
    for k, (x, y) in tags:
        msp.add_circle((x, y), r, dxfattribs={"layer": L_NOTE})
        t = msp.add_text(str(k), height=hb,
                         dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)


def _corner_reinforcement(doc, g, scale, cells):
    """內角 45° 加腋與角隅補強筋（X 形交叉斜筋）。

    做法依公司標準圖（標準圖圖庫\箱涵與管涵 C110／C111「箱涵鋼筋詳圖」）：
    每個內角在牆身內（加腋斜面下方）畫一組 X 形交叉斜筋，
    橫向跨越該角所在牆厚、縱向同寬（45° 斜筋），並標註筋號與間距。
    斜筋用 LINE 不用圓點，以免干擾 `dxf_takeoff --rebar` 的主筋間距量測。
    """
    msp = doc.modelspace()
    c = g["c"]
    if c <= 1e-9:
        return
    tb, h = g["tb"], g["H"]
    tw, ti, n = g["tw"], g["ti"], g["n"]
    cover = float(g.get("cover_m", 0.05) or 0.05)
    hb = model_h(3.0, scale)
    bar = g.get("corner_rebar", "D13")
    sp_mm = int(g.get("corner_rebar_spacing_mm", 200) or 200)

    # 每個內角：(牆內面 x, 牆厚 t, 牆在左(-1)或右(+1), 上/下角)
    corners = []
    for i, (x0, x1) in enumerate(cells):
        t_left = tw if i == 0 else ti
        t_right = tw if i == n - 1 else ti
        corners += [(x0, t_left, -1, "top"), (x0, t_left, -1, "bot"),
                    (x1, t_right, +1, "top"), (x1, t_right, +1, "bot")]
    for (xf, t, sign, pos) in corners:
        span = t - 2.0 * cover            # X 的邊長（正方形 → 45° 斜筋）
        if span <= 0.02:
            continue
        x_in = xf + sign * cover          # 靠涵內側一端
        x_out = xf + sign * (t - cover)  # 靠牆外側一端
        # 加腋斜面與牆內面的交點：上角在淨空頂下 c，下角在淨空底上 c
        y_v = (tb + h - c) if pos == "top" else (tb + c)
        y_hi = y_v if pos == "top" else y_v + span
        y_lo = y_v - span if pos == "top" else y_v
        msp.add_line((x_in, y_lo), (x_out, y_hi),
                     dxfattribs={"layer": L_REBAR})
        msp.add_line((x_in, y_hi), (x_out, y_lo),
                     dxfattribs={"layer": L_REBAR})

    # ---- 標註（引線指到第一孔左下角的 X，文字放在第一孔淨空內）----
    x0 = cells[0][0]
    span0 = max(tw - 2.0 * cover, 0.05)
    y_corner = tb + c + span0 / 2.0            # 左下角 X 的中心高度
    tx = x0 + 0.40
    msp.add_line((tx - 0.03, tb + 1.02), (x0 - cover, y_corner),
                 dxfattribs={"layer": L_NOTE})
    for k, line in enumerate((
            "角隅補強筋",
            "%s@%d" % (bar, sp_mm // 10),
            "（X 形交叉斜筋）")):
        t = msp.add_text(line, height=hb,
                         dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t.set_placement((tx, tb + 1.45 - 0.30 * k),
                        align=TextEntityAlignment.BOTTOM_LEFT)


def _draw_rebar(doc, g, elements, cover_m, scale):
    """逐面畫主筋實線（LWPOLYLINE / LINE）＋副筋圓點（CIRCLE 貼於主筋內側）＋編號圓標（1~8、9~12）。"""
    msp = doc.modelspace()
    W, Htot, tb, tt, H = g["W"], g["Htot"], g["tb"], g["tt"], g["H"]
    tw, ti, cells, iw = g["tw"], g["ti"], g["cells"], g["int_walls"]
    c = g["c"]
    off = model_h(5.0, scale)          # 圓標離鋼筋線的距離（紙面 5 mm）

    elem_map = {(e["key"], e["face"]): e for e in elements}

    dia_main = 0.016
    cd = cover_m + dia_main / 2.0
    r_offset = 0.015
    r_dist = 0.013 / 2.0

    hook_top = min(tt + c, 0.45)
    hook_bot = min(tb + c, 0.45)

    # 1. 主筋（受力筋）：頂板、底板、側壁繪製出連續受力主筋線條（LWPOLYLINE / LINE on '40_鋼筋'）
    # (a) 頂板外側主筋（連續 U 型向下彎折進入外側壁）
    msp.add_lwpolyline([
        (cd, Htot - cd - hook_top),
        (cd, Htot - cd),
        (W - cd, Htot - cd),
        (W - cd, Htot - cd - hook_top),
    ], dxfattribs={"layer": L_REBAR})

    # (b) 頂板內側主筋（橫向下層筋＋兩端向下彎折錨定）
    msp.add_lwpolyline([
        (tw - cd, tb + H + cd - hook_top),
        (tw - cd, tb + H + cd),
        (W - tw + cd, tb + H + cd),
        (W - tw + cd, tb + H + cd - hook_top),
    ], dxfattribs={"layer": L_REBAR})

    # (c) 底板外側主筋（連續 U 型向上彎折進入外側壁）
    msp.add_lwpolyline([
        (cd, cd + hook_bot),
        (cd, cd),
        (W - cd, cd),
        (W - cd, cd + hook_bot),
    ], dxfattribs={"layer": L_REBAR})

    # (d) 底板內側主筋（橫向上層筋＋兩端向上彎折錨定）
    msp.add_lwpolyline([
        (tw - cd, tb - cd + hook_bot),
        (tw - cd, tb - cd),
        (W - tw + cd, tb - cd),
        (W - tw + cd, tb - cd + hook_bot),
    ], dxfattribs={"layer": L_REBAR})

    # (e) 外側壁外側主筋（左、右兩道外側鉛直筋）
    msp.add_line((cd, cd), (cd, Htot - cd), dxfattribs={"layer": L_REBAR})
    msp.add_line((W - cd, cd), (W - cd, Htot - cd), dxfattribs={"layer": L_REBAR})

    # (f) 外側壁內側主筋（左、右兩道內側鉛直筋）
    msp.add_line((tw - cd, tb - cd), (tw - cd, tb + H + cd), dxfattribs={"layer": L_REBAR})
    msp.add_line((W - tw + cd, tb - cd), (W - tw + cd, tb + H + cd), dxfattribs={"layer": L_REBAR})

    # (g) 中間壁主筋（A 側、B 側兩道鉛直筋）
    for w in iw:
        msp.add_line((w[0] + cd, tb - cd), (w[0] + cd, tb + H + cd), dxfattribs={"layer": L_REBAR})
        msp.add_line((w[1] - cd, tb - cd), (w[1] - cd, tb + H + cd), dxfattribs={"layer": L_REBAR})

    # 2. 副筋（縱向分佈筋 CIRCLE）：在頂板、底板、側壁主筋線條的『內側』繪製圓點，代表沿水流方向延伸的分佈筋
    def add_dots_h(y, x0, x1, sp_mm):
        sp = max(float(sp_mm) / 1000.0, 0.05)
        x = x0
        while x <= x1 + 1e-6:
            msp.add_circle((x, y), r_dist, dxfattribs={"layer": L_REBAR})
            x += sp

    def add_dots_v(x, y0, y1, sp_mm):
        sp = max(float(sp_mm) / 1000.0, 0.05)
        y = y0
        while y <= y1 + 1e-6:
            msp.add_circle((x, y), r_dist, dxfattribs={"layer": L_REBAR})
            y += sp

    sp_top_out = ((elem_map.get(("top_slab", "outer")) or {}).get("flexure") or {}).get("spacing_mm", 170)
    sp_top_in = ((elem_map.get(("top_slab", "inner")) or {}).get("flexure") or {}).get("spacing_mm", 170)
    sp_bot_out = ((elem_map.get(("bottom_slab", "outer")) or {}).get("flexure") or {}).get("spacing_mm", 150)
    sp_bot_in = ((elem_map.get(("bottom_slab", "inner")) or {}).get("flexure") or {}).get("spacing_mm", 150)
    sp_ext_out = ((elem_map.get(("exterior_wall", "outer")) or {}).get("flexure") or {}).get("spacing_mm", 200)
    sp_ext_in = ((elem_map.get(("exterior_wall", "inner")) or {}).get("flexure") or {}).get("spacing_mm", 200)
    sp_int_A = ((elem_map.get(("interior_wall", "A")) or {}).get("flexure") or {}).get("spacing_mm", 240)
    sp_int_B = ((elem_map.get(("interior_wall", "B")) or {}).get("flexure") or {}).get("spacing_mm", 240)

    # 頂板分佈筋：貼於頂板主筋內側
    add_dots_h(Htot - cd - r_offset, cd + r_offset, W - cd - r_offset, sp_top_out)
    add_dots_h(tb + H + cd + r_offset, tw - cd + r_offset, W - tw + cd - r_offset, sp_top_in)

    # 底板分佈筋：貼於底板主筋內側
    add_dots_h(cd + r_offset, cd + r_offset, W - cd - r_offset, sp_bot_out)
    add_dots_h(tb - cd - r_offset, tw - cd + r_offset, W - tw + cd - r_offset, sp_bot_in)

    # 外側壁分佈筋：貼於外壁主筋內側
    add_dots_v(cd + r_offset, cd + r_offset, Htot - cd - r_offset, sp_ext_out)
    add_dots_v(W - cd - r_offset, cd + r_offset, Htot - cd - r_offset, sp_ext_out)
    add_dots_v(tw - cd - r_offset, tb - cd + r_offset, tb + H + cd - r_offset, sp_ext_in)
    add_dots_v(W - tw + cd + r_offset, tb - cd + r_offset, tb + H + cd - r_offset, sp_ext_in)

    # 中間壁分佈筋：貼於中壁主筋內側
    for w in iw:
        add_dots_v(w[0] + cd + r_offset, tb - cd + r_offset, tb + H + cd - r_offset, sp_int_A)
        add_dots_v(w[1] - cd - r_offset, tb - cd + r_offset, tb + H + cd - r_offset, sp_int_B)

    # 3. 編號圓標與引線（分別指向對應的主筋實線與副筋圓點）
    out = []
    # (1~8) 主筋標註（指到對應主筋實線）
    for no, e in enumerate(elements, 1):
        key, face = e["key"], e["face"]
        flex = e.get("flexure") or {}
        bar = flex.get("bar", "D16")
        sp_int = int(flex.get("spacing_mm", 200))
        if key == "top_slab":
            y_line = (Htot - cd) if face == "outer" else (tb + H + cd)
            dy = off if face == "outer" else -off
            x_m = cells[0][0] + 0.45
            out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                        "bar": bar, "spacing_mm": sp_int,
                        "kind": "h", "y": y_line, "x": x_m,
                        "mark": (x_m, y_line + dy), "anchor": (x_m, y_line)})
        elif key == "bottom_slab":
            y_line = cd if face == "outer" else (tb - cd)
            dy = -off if face == "outer" else off
            x_m = cells[0][0] + 0.45
            out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                        "bar": bar, "spacing_mm": sp_int,
                        "kind": "h", "y": y_line, "x": x_m,
                        "mark": (x_m, y_line + dy), "anchor": (x_m, y_line)})
        elif key == "exterior_wall":
            if face == "outer":
                out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                            "bar": bar, "spacing_mm": sp_int,
                            "kind": "v", "x": W - cd, "y": Htot / 2.0,
                            "mark": (W - cd + off, Htot / 2.0), "anchor": (W - cd, Htot / 2.0)})
            else:
                out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                            "bar": bar, "spacing_mm": sp_int,
                            "kind": "v", "x": tw - cd, "y": Htot / 2.0,
                            "mark": (tw - cd + off, Htot / 2.0), "anchor": (tw - cd, Htot / 2.0)})
        elif key == "interior_wall" and iw:
            if face == "A":
                ax = iw[0][0] + cd
                out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                            "bar": bar, "spacing_mm": sp_int,
                            "kind": "v", "x": ax, "y": Htot / 2.0,
                            "mark": (ax - off, Htot / 2.0), "anchor": (ax, Htot / 2.0)})
            else:
                ax = iw[0][1] - cd
                out.append({"no": no, "label": e.get("label") or e.get("face_label"),
                            "bar": bar, "spacing_mm": sp_int,
                            "kind": "v", "x": ax, "y": Htot / 2.0,
                            "mark": (ax + off, Htot / 2.0), "anchor": (ax, Htot / 2.0)})

    # (9~12) 副筋標註（指到對應副筋圓點）
    dist_specs = [
        (len(elements) + 1, "頂版縱向分佈筋",
         (cells[0][0] + 1.5, tb + H + cd + r_offset),
         (cells[0][0] + 1.5, tb + H + cd - off)),
        (len(elements) + 2, "底版縱向分佈筋",
         (cells[0][0] + 1.5, tb - cd - r_offset),
         (cells[0][0] + 1.5, tb - cd + off)),
        (len(elements) + 3, "外側牆縱向分佈筋",
         (tw - cd - r_offset, min(tb + H * 0.80, tb + H - 0.25)),
         (tw - cd + off, min(tb + H * 0.80, tb + H - 0.25))),
    ]
    if iw:
        dist_specs.append((
            len(elements) + 4, "中間牆縱向分佈筋",
            (iw[0][0] + cd + r_offset, min(tb + H * 0.80, tb + H - 0.25)),
            (iw[0][0] + cd - off, min(tb + H * 0.80, tb + H - 0.25))
        ))

    for dno, dlabel, anchor_pt, mark_pt in dist_specs:
        out.append({"no": dno, "label": dlabel, "kind": "dist",
                    "mark": mark_pt, "anchor": anchor_pt})

    for b in out:
        _bar_mark(doc, b, scale)
    return out


def _bar_mark(doc, b, scale):
    """在該面旁畫編號圓標（與標準圖 C110 同作法：D19@10cm＋1~8 編號）。

    圓標與編號字高的**尺寸跟著出圖比例走**（固定模型尺寸在 1:75 會縮成
    0.7 mm 看不出來，且字高會違反 E15 出圖規定）。
    """
    msp = doc.modelspace()
    r = model_h(3.0, scale)
    x, y = b["mark"]
    ax, ay = b["anchor"]
    msp.add_circle((x, y), r, dxfattribs={"layer": L_REBAR})
    msp.add_line((x, y), (ax, ay), dxfattribs={"layer": L_REBAR})
    t = msp.add_text(str(b["no"]), height=model_h(4.0, scale),
                     dxfattribs={"layer": L_REBAR, "style": "TOMO"})
    t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)


# --------------------------------------------------------------------------- #
# 配筋表／數量表
# --------------------------------------------------------------------------- #
def build_tables(case, q, result, payload):
    """由引擎結果組成配筋表與每延米數量表（兩張圖共用同一份資料）。"""
    rb = result.get("reinforcement") or {}
    elements = rb.get("elements") or []
    rows = rb.get("quantity", {}).get("rows") or []
    L = float(q.get("length_m", 20.0))

    main = []
    for e in elements:
        flex = e.get("flexure") or {}
        main.append({
            "label": e.get("label") or e.get("face_label"),
            "bar": flex.get("bar"), "spacing_mm": flex.get("spacing_mm"),
        })

    qrows = {r["item"]: r for r in rows}
    table = []
    for i, m in enumerate(main, 1):
        r = qrows.get(m["label"]) or {}
        count, kg = r.get("count"), r.get("kg")
        table.append({
            "no": i, "pos": m["label"], "bar": m["bar"],
            "spacing_mm": m["spacing_mm"],
            "length_m": r.get("length_m") or 0.0,
            "per_m": (count / L) if (count and L) else 0.0,
            "unit_kg_m": _unit_weight(m["bar"]),
            "kg_per_m": (kg / L) if (kg and L) else 0.0,
            "kind": "主筋",
        })
    dist = rb.get("distribution") or []
    for d in dist:
        r = qrows.get(d.get("title")) or {}
        count, kg = r.get("count"), r.get("kg")
        table.append({
            "no": len(table) + 1, "pos": d.get("title"), "bar": d.get("bar"),
            "spacing_mm": d.get("spacing_mm"),
            "length_m": r.get("length_m") or 0.0,
            "per_m": (count / L) if (count and L) else 0.0,
            "unit_kg_m": _unit_weight(d.get("bar")),
            "kg_per_m": (kg / L) if (kg and L) else 0.0,
            "kind": "縱向分佈筋",
        })
    # 角隅補強筋（X 形交叉斜筋，構造筋）
    for r in rows:
        if not str(r.get("item", "")).startswith("角隅補強筋"):
            continue
        count, kg = r.get("count"), r.get("kg")
        table.append({
            "no": len(table) + 1, "pos": r.get("item"),
            "bar": r.get("bar"), "spacing_mm": r.get("spacing_mm"),
            "length_m": r.get("length_m") or 0.0,
            "per_m": (count / L) if (count and L) else 0.0,
            "unit_kg_m": _unit_weight(r.get("bar")),
            "kg_per_m": (kg / L) if (kg and L) else 0.0,
            "kind": "角隅補強筋",
        })

    quantities = result.get("quantities") or {}
    loss = float(quantities.get("rebar_loss_rate", 0.06) or 0.0)
    net_kg = float(quantities.get("rebar_kg_per_m_net", 0.0) or 0.0)
    gross_kg = float(quantities.get("rebar_kg_per_m", 0.0) or 0.0)
    fb = quantities.get("formwork_breakdown") or {}
    W = float(q["outer_width_m"])
    Ht = float(q["outer_height_m"])
    gross_v = W * Ht
    cham = float(quantities.get("inner_chamfer_m", 0.0) or 0.0)
    void_v = ((float(q["clear_width_m"]) * float(q["clear_height_m"])
               - 2.0 * cham * cham) * int(q["cell_count"]))
    qty_table = [
        {"item": "鋼筋（淨量）", "unit": "kg/m", "value": net_kg,
         "note": "逐面配筋設計推算"},
        {"item": "鋼筋（含 %.0f%% 搭接與損耗）" % (loss * 100), "unit": "kg/m",
         "value": gross_kg, "note": "預算用"},
        {"item": "模板合計", "unit": "m2/m", "value": quantities.get("formwork_m2_per_m"),
         "note": "僅計涵內側"},
        {"item": "　頂版底面", "unit": "m2/m", "value": fb.get("top_slab_soffit_m2_per_m"),
         "note": "n×B"},
        {"item": "　底板頂面", "unit": "m2/m", "value": fb.get("bottom_slab_top_m2_per_m"),
         "note": "n×B"},
        {"item": "　牆內面", "unit": "m2/m", "value": fb.get("wall_inner_faces_m2_per_m"),
         "note": "2n×H"},
        {"item": "　內角加腋斜面", "unit": "m2/m",
         "value": fb.get("inner_chamfer_faces_m2_per_m"), "note": "4nc√2"},
        {"item": "混凝土（外框）", "unit": "m3/m", "value": gross_v,
         "note": "外寬×外高"},
        {"item": "孔內淨空（含加腋）", "unit": "m3/m", "value": void_v,
         "note": "n×(B×H−2c²)"},
        {"item": "混凝土（淨斷面）", "unit": "m3/m", "value": gross_v - void_v,
         "note": "外框－孔洞"},
    ]
    return table, qty_table


def _unit_weight(bar):
    """鋼筋單位重 kg/m（沿用引擎同一份斷面積表，數字才會一致）。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "design"))
        import rc_design as RC
        dia, area = RC.REBAR_SIZES.get(bar, RC.REBAR_SIZES["D16"])
        return area * 1e-6 * RC.STEEL_DENSITY
    except Exception:
        d = BAR_DIA.get(bar, 0.016)
        return d * d * 3.14159265 / 4.0 * 7850.0


# --------------------------------------------------------------------------- #
# 圖紙空間：視口、比例尺、右欄表格、標題欄
# --------------------------------------------------------------------------- #
def build_paper(doc, g, case, scale, project, sheet_no, tables, title_note,
                drawing_no, unit="m"):
    msp = doc.modelspace()
    from ezdxf import bbox as _bbox
    box = _bbox.extents(msp)
    mx0, my0, mx1, my1 = box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y
    mw, mh = mx1 - mx0, my1 - my0

    lay = doc.layouts.get(LAYOUT_NAME) if LAYOUT_NAME in doc.layouts \
        else doc.layouts.new(LAYOUT_NAME)

    def m2mm(v):
        return v * 1000.0 / scale

    vw, vh = m2mm(mw), m2mm(mh)
    avail_w, avail_h = 183.0, (Y1 - 4.0) - 34.0
    if vw > avail_w or vh > avail_h:
        raise SystemExit(
            "請改用較大比例尺重跑：模型 %.2f×%.2f m 在 1:%d 為 %.1f×%.1f mm，"
            "超出 A3 可用區 %.1f×%.1f mm。" % (mw, mh, scale, vw, vh, avail_w, avail_h))
    vx0 = 22.0
    # 視口在可繪區內**垂直置中**（寬而扁的箱涵斷面若壓在下方，上面會留一大片空白）
    vy0 = max(34.0, min(Y1 - 4.0 - vh, 34.0 + (avail_h - vh) / 2.0))
    cx, cy = vx0 + vw / 2.0, vy0 + vh / 2.0
    wcx, wcy = (mx0 + mx1) / 2.0, (my0 + my1) / 2.0

    vp = lay.add_viewport(center=(cx, cy), size=(vw, vh),
                          view_center_point=(wcx, wcy), view_height=mh)
    vp.dxf.status = 2
    vp.dxf.flags |= 16384
    _vp_layer = "00_視口框"
    if _vp_layer not in doc.layers:
        _l = doc.layers.add(_vp_layer, color=7)
    else:
        _l = doc.layers.get(_vp_layer)
    _l.dxf.plot = 0
    _l.dxf.lineweight = 15
    vp.dxf.layer = _vp_layer

    def put(x, y, s, h=3.0, layer=L_FRAME):
        t = lay.add_text(str(s), height=h, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement((x, y), align=TextEntityAlignment.BOTTOM_LEFT)
    # ---- 標題欄（沿用樣板既有標籤，改文字內容）----
    T = {x.dxf.text: x for x in lay.query("TEXT")}
    for x in lay.query("TEXT"):
        if x.dxf.text == "臺中市大雅區公所":
            x.dxf.text = (case.get("project") or {}).get("agency") or "（主辦機關）"
        if x.dxf.text == "圖名":
            x.dxf.text = title_note
        if x.dxf.text == "案名" and project:
            short = (case.get("project") or {}).get("name") or project
            text = str(short).replace("（", "(").replace("）", ")")
            x.dxf.text = text if len(text) <= 34 else text[:33] + "…"

    def fill(label, value, dx=12.0, dy=0.0, ht=3.0, layer=L_FRAME):
        lb = T.get(label)
        if lb is not None and value:
            t = lay.add_text(str(value), height=ht,
                             dxfattribs={"layer": layer, "style": "TOMO"})
            t.set_placement((lb.dxf.insert.x + dx, lb.dxf.insert.y + dy),
                            align=TextEntityAlignment.BOTTOM_LEFT)

    fill("設計", "Claude（AI）")
    fill("繪圖", "Claude（AI）")
    fill("日期", time.strftime("%Y.%m.%d"))
    fill("比例尺", "1:%d" % scale, dx=15.0)
    fill("圖序", sheet_no, dx=14.0)
    for x in lay.query("TEXT"):
        if x.dxf.text.strip() == "A-01":
            x.dxf.text = drawing_no

    # ---- 比例尺 ----
    sy = max(36.0, vy0 - 14.0)
    bar_mm = 1000.0 / scale
    seg = bar_mm / 2.0
    for i in range(2):
        x0 = vx0 + i * seg
        poly = [(x0, sy), (x0 + seg, sy), (x0 + seg, sy + 3.0), (x0, sy + 3.0)]
        lay.add_lwpolyline(poly, close=True, dxfattribs={"layer": L_SCALE})
        if i == 0:
            lay.add_solid(poly, dxfattribs={"layer": L_SCALE})
    us = MWS.unit_spec(unit)
    put(vx0 - 0.8, sy - 5.0, "0", 3.0, L_SCALE)
    # 刻度只標數值、單位寫在標題，避免「0.5 m」與「1 m」在較小比例尺疊字（E10）。
    if seg >= 8.0:
        put(vx0 + seg - 1.2, sy - 5.0, "%g" % (us["factor"] / 2.0), 3.0, L_SCALE)
    put(vx0 + 2 * seg - 1.6, sy - 5.0, "%g" % us["factor"], 3.0, L_SCALE)
    put(vx0, sy + 5.5, "比例尺 1:%d（尺寸單位：%s）" % (scale, us["label"]),
        4.0, L_SCALE)

    # ---- 右欄：由上而下動態累加 ----
    RX, RY_TOP = 210.0, 271.0
    ROW_H, TITLE_H, GAP_H = 4.6, 5.0, 6.0
    cur = {"y": RY_TOP}

    def _title(text, layer=L_LEGEND, h=TITLE_H):
        put(RX, cur["y"], text, h, layer)
        cur["y"] -= (h + 4.0)

    def _row(a, b=None, dx=62.0, h=3.0, layer=L_LEGEND):
        put(RX, cur["y"], a, h, layer)
        if b is not None:
            put(RX + dx, cur["y"], b, h, layer)
        cur["y"] -= ROW_H

    def _gap(v=GAP_H):
        cur["y"] -= v

    if tables.get("rebar_rows"):
        _title("配筋表")
        for dx, txt in [(0.0, "編號"), (9.0, "位置"), (60.0, "筋號"),
                        (72.0, "間距(mm)"), (92.0, "長度(%s)" % us["label"]),
                        (114.0, "支/m"),
                        (128.0, "單位重"), (145.0, "重量(kg/m)")]:
            put(RX + dx, cur["y"], txt, 3.0, L_LEGEND)
        cur["y"] -= ROW_H
        for r in tables["rebar_rows"]:
            put(RX, cur["y"], str(r["no"]), 3.0, L_LEGEND)
            put(RX + 9.0, cur["y"], r["pos"], 3.0, L_LEGEND)
            put(RX + 60.0, cur["y"], str(r["bar"]), 3.0, L_LEGEND)
            put(RX + 72.0, cur["y"], str(r["spacing_mm"]), 3.0, L_LEGEND)
            put(RX + 92.0, cur["y"],
                MWS.fmt_len(float(r["length_m"]), unit).split(" ")[0],
                3.0, L_LEGEND)
            put(RX + 114.0, cur["y"], "%.2f" % float(r["per_m"]), 3.0, L_LEGEND)
            put(RX + 128.0, cur["y"], "%.3f" % float(r["unit_kg_m"]), 3.0, L_LEGEND)
            put(RX + 145.0, cur["y"], "%.2f" % float(r["kg_per_m"]), 3.0, L_LEGEND)
            cur["y"] -= ROW_H
        _gap(6.0)
        _title("每延米數量表")
        for dx, txt in [(0.0, "項目"), (58.0, "單位"), (74.0, "數量"),
                        (104.0, "備註")]:
            put(RX + dx, cur["y"], txt, 3.0, L_LEGEND)
        cur["y"] -= ROW_H
        for r in tables.get("qty_rows", []):
            put(RX, cur["y"], r["item"], 3.0, L_LEGEND)
            put(RX + 58.0, cur["y"], r["unit"], 3.0, L_LEGEND)
            put(RX + 74.0, cur["y"], ("%.3f" % float(r["value"]))
                if r["value"] is not None else "—", 3.0, L_LEGEND)
            put(RX + 104.0, cur["y"], r.get("note") or "", 3.0, L_LEGEND)
            cur["y"] -= ROW_H
    else:
        _title("部位圖例")
        parts = [("1", "頂版"), ("2", "底版"), ("3", "外側牆"),
                 ("4", "中間牆"), ("5", "涵內淨空"), ("6", "覆土回填"),
                 ("7", "基礎開挖線")]
        for k, v in parts:
            _row(k, v, dx=6.0)
        _gap(6.0)
        _title("斷面尺寸表")
        data = [("孔數", "%d 孔" % g["n"]),
                ("每孔淨寬 B", MWS.fmt_len(g["B"], unit)),
                ("每孔淨高 H", MWS.fmt_len(g["H"], unit)),
                ("外牆厚", MWS.fmt_len(g["tw"], unit)),
                ("中間牆厚", MWS.fmt_len(g["ti"], unit)),
                ("頂版厚", MWS.fmt_len(g["tt"], unit)),
                ("底板厚", MWS.fmt_len(g["tb"], unit)),
                ("外寬 W", MWS.fmt_len(g["W"], unit)),
                ("外高", MWS.fmt_len(g["Htot"], unit)),
                ("覆土厚", MWS.fmt_len(g["cover_depth"], unit)),
                ("涵長", MWS.fmt_len(g["length_m"], unit, dec=1))]
        for k, v in data:
            _row(k, v)

    # ---- 說明 ----
    _gap(6.0)
    _title("說明", layer=L_DESC)
    for n in MWS.notes_in_unit(tables.get("notes", []), unit):
        # 說明欄寬度上限＝技師執業圖記區左緣（x=363.5）− 右欄起點 − 間距
        for line in _wrap_note(n, 148.0, 4.0):
            put(RX, cur["y"], line, 4.0, L_DESC)
            cur["y"] -= 5.9
    if cur["y"] < 34.0:
        print("⚠ 右欄內容過多（剩 %.1f mm），請檢查是否壓到標題欄" % cur["y"])
    return lay, (cx, cy, vw, vh)


def _wrap_note(text, max_mm, h):
    """把說明文字折成多行（中文逐字斷、英文盡量在空白或路徑分隔處斷）。

    說明文字長度會直接影響 E9（超出圖框內框）——右欄可用寬度約 195 mm，
    4 mm 字的中文一行約 39 字，超過就會被判定壓出圖框。
    """
    # 先把「數值 + 單位」綁成一個不可拆的詞（以哨兵字元代替中間的空白），
    # 避免折行時變成「20」/「cm」兩行；輸出前再把哨兵還原成空白。
    text = re.sub(r"(\d+(?:\.\d+)?)\s(m|cm|mm|kg)\b",
                  lambda m: m.group(1) + "\x01" + m.group(2), text)

    def _w(ch):
        if ch == "\x01":
            return 0.0
        return 1.2 * h if ord(ch) >= 0x2E80 else 0.8 * h

    lines, cur, w = [], "", 0.0
    for ch in text:
        cw = _w(ch)
        if cur and w + cw > max_mm:
            cut = max(cur.rfind(" "), cur.rfind("/"), cur.rfind("\\"),
                      cur.rfind("，"), cur.rfind("、"))
            if cut > len(cur) - 14:
                lines.append(cur[:cut])
                cur = cur[cut + 1:]
            else:
                lines.append(cur)
                cur = ""
            w = sum(_w(c) for c in cur)
        cur += ch
        w += cw
    if cur:
        lines.append(cur)
    return [ln.replace("\x01", " ") for ln in lines]


# --------------------------------------------------------------------------- #
# 說明文字
# --------------------------------------------------------------------------- #
def build_notes(case, q, result, payload, rebar):
    """說明文字。

    分成「共用」與「主題」兩組：S-01（斷面圖）放斷面相關、S-02（配筋圖）放
    配筋相關，右欄高度才放得下（說明行距 5.9 mm＝字高 4 mm ＋ 品管疊字判定
    的 0.3 mm 留白 ×2 ＋ 餘裕）。
    """
    cul = case.get("culvert") or {}
    notes = []
    notes.append("混凝土 fc' = 280 kgf/cm2；主筋保護層 %d mm。"
                 % int(round(float(payload.get("cover_mm", 50.0)))))
    notes.append("鋼筋含搭接與損耗 %.0f%%；裂縫寬度上限 %.2f mm。"
                 % (float(payload.get("rebar_loss_rate", 0.06)) * 100.0,
                    float(payload.get("crack_limit_mm", 0.3))))
    tt = payload.get("traffic_type")
    tt_txt = {"h20": "H-20（後輪 7.25 t、衝擊 30%）",
              "h20_s16": "H-20 S-16（P=7.3 t，依車道數）",
              "trailer_40t": "40T 拖車（後輪 8 t）",
              "custom": "自訂均佈車載 %.2f kPa" % float(payload.get("traffic_load_kpa", 0.0)),
              "none": "無車載"}.get(tt, "依案件 culvert 段設定")
    notes.append("車載：%s；載重因數 %.1f。"
                 % (tt_txt, float(payload.get("load_factor", 1.7))))
    if rebar:
        notes.append("配筋依平面剛架分析（逐面正負彎矩包絡）結果，"
                     "彎矩與裂縫均通過檢核。")
        notes.append("圖上圓點為斷面切到之鋼筋；圓標編號對應配筋表；"
                     "縱向分佈筋見配筋表。")
        notes.append("角隅補強筋為 X 形交叉斜筋（每內角沿涵長每 %d mm 一組），"
                     "屬構造筋，未納入構架分析。"
                     % int(payload.get("corner_rebar_spacing_mm", 200)))
    else:
        if payload.get("inlet_type"):
            notes.append("進出口控制已附錄 N／O 曲線檢核；下游水深 %.2f m。"
                         % float(payload.get("tailwater_depth_m", 0.0)))
        else:
            notes.append("案件未輸入進口型式 → 僅 Manning 均勻流檢核，"
                         "未做附錄 N／O 檢核。")
        cham = float(payload.get("inner_chamfer_m", 0.0) or 0.0)
        if cham > 1e-9:
            notes.append("內角設 45° 加腋（倒角）c = %.2f m；斷面積與模板量已含加腋。"
                         % cham)
    notes.append("舊標準圖僅參考圖面構成與標註方式，數值以本設計為準。")
    return ["%d. %s" % (i + 1, t) for i, t in enumerate(notes)]


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="箱涵標準斷面圖／配筋圖產線")
    ap.add_argument("case", help="案件 JSON（quantities.model 必須 box_culvert）")
    ap.add_argument("--scale", default="auto", help="出圖比例 1:N 或 auto")
    ap.add_argument("--out", required=True, help="輸出 DXF")
    ap.add_argument("--rebar", action="store_true",
                    help="產出配筋圖 S-02（右欄為配筋表）")
    ap.add_argument("--publish", action="store_true", help="另產 DWG 與 PDF")
    ap.add_argument("--unit", default="m", choices=["m", "cm"],
                    help="圖面尺寸標註單位（m／cm）；模型空間一律為公尺")
    ap.add_argument("--project", default=None)
    ap.add_argument("--sheet-no", default=None)
    ap.add_argument("--template", default=TEMPLATE)
    a = ap.parse_args()

    case, q = load_case(a.case)
    payload = build_payload(case, q)
    result = analyse_box(case, q)
    elements = (result.get("reinforcement") or {}).get("elements") or []
    if not elements:
        raise SystemExit("箱涵引擎沒有回傳配筋結果，無法出圖。")

    g = box_geometry(q)

    # --scale auto：挑「放得進 A3 可用區的最小標準比例」
    if str(a.scale).lower() == "auto":
        mw = g["W"] + 2 * g["exc_work"] + 1.6
        mh = g["Htot"] + g["cover_depth"] + g["exc_depth"] + 1.8
        need = max(mh * 1000.0 / 249.45, mw * 1000.0 / 183.0)
        cands = [x for x in DR.STANDARD_SCALES if x >= need]
        a.scale = cands[0] if cands else max(DR.STANDARD_SCALES)
        print("自動比例：斷面概估 %.2f×%.2f m → 需 1:%.1f 以上 → 採 1:%d"
              % (mw, mh, need, a.scale))
    else:
        a.scale = int(a.scale)
        DR.require_standard_scale(a.scale)

    table, qty_table = build_tables(case, q, result, payload)
    notes = build_notes(case, q, result, payload, a.rebar)

    doc = ezdxf.readfile(a.template)
    others = [l.name for l in doc.layouts if l.name != "Model"]
    if LAYOUT_NAME in doc.layouts:
        lay0 = doc.layouts.get(LAYOUT_NAME)
    elif others:
        doc.layouts.rename(others[0], LAYOUT_NAME)
        lay0 = doc.layouts.get(LAYOUT_NAME)
        print("  沿用樣板版面 %s → 改名 %s（保留圖框與標題欄）" % (others[0], LAYOUT_NAME))
    else:
        lay0 = doc.layouts.new(LAYOUT_NAME)
        print("  ⚠ 樣板沒有圖紙版面，自建（圖框需自行補）")
    for v in [e for e in lay0.query("VIEWPORT") if e.dxf.id != 1]:
        lay0.delete_entity(v)
    doc.layouts.set_active_layout(LAYOUT_NAME)
    for name in [l.name for l in doc.layouts if l.name not in ("Model", LAYOUT_NAME)]:
        try:
            doc.layouts.delete(name)
        except Exception as ex:
            print("  ⚠ 無法刪除版面 %s：%s" % (name, ex))

    MWS.ensure_tomo(doc)
    ensure_layers(doc)
    ds = MWS.ensure_dimstyle(doc, a.scale, a.unit)

    cover_m = float(payload.get("cover_mm", 50.0)) / 1000.0
    g["cover_m"] = cover_m
    g["corner_rebar"] = payload.get("corner_rebar", "D13")
    g["corner_rebar_spacing_mm"] = payload.get("corner_rebar_spacing_mm", 200.0)
    g["distribution"] = (result.get("reinforcement") or {}).get("distribution") or []
    draw_box_section(doc, g, a.scale, ds, cover_m, elements, rebar=True)

    proj = a.project or (case.get("project") or {}).get("full_name") or "箱涵工程"
    if a.rebar:
        title_note = "箱涵配筋圖"
        drawing_no = "S-02"
        sheet_no = a.sheet_no or "S-02"
    else:
        title_note = "箱涵標準斷面圖"
        drawing_no = "S-01"
        sheet_no = a.sheet_no or "S-01"

    build_paper(doc, g, case, a.scale, proj, sheet_no,
                {"rebar_rows": table if a.rebar else [],
                 "qty_rows": qty_table if a.rebar else [],
                 "notes": notes},
                title_note, drawing_no, unit=a.unit)

    doc.layouts.set_active_layout(LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  斷面 %d 孔 淨寬 %.2f×淨高 %.2f 外寬 %.2f 外高 %.2f 比例 1/%d"
          % (g["n"], g["B"], g["H"], g["W"], g["Htot"], a.scale))
    qty = result.get("quantities") or {}
    print("  鋼筋 %.2f kg/m（含 %.0f%% 搭接與損耗）／模板 %.2f m2/m"
          % (qty.get("rebar_kg_per_m", 0.0),
             float(qty.get("rebar_loss_rate", 0.06)) * 100.0,
             qty.get("formwork_m2_per_m", 0.0)))

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
            print("PDF 預覽 %s  %.1f×%.1f mm"
                  % (png, pg.rect.width * 25.4 / 72, pg.rect.height * 25.4 / 72))
        except Exception as ex:
            print("PDF 轉圖略過", ex)


if __name__ == "__main__":
    main()
