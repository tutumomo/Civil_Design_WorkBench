r"""從 DXF 圖面量測數量，並與案件檔的衍生數量對帳。

為什麼要這個模組
----------------
先前所有數量都是「人填」或「模型派生」。但圖才是最終交付物 —— 如果圖上畫的
跟數量表算的不是同一個東西，那兩邊都不可信。

本模組把圖讀回來量：圖層長度、閉合多邊形面積（可扣內腔）、圖塊數量，
再跟 `qty_models` 的衍生值比對。**對不起來就代表圖與數量已經分家。**

單位：DXF 模型空間 1 unit = 1 m（AGENTS.md §2 契約），故長度 m、面積 m²。

⚠ 面積量測的關鍵：**必須扣掉內腔**
--------------------------------
實測三張斷面圖：

| 圖 | 30_ 圖層多邊形 | 扣內腔後 | 模型斷面積 |
|---|---|---|---|
| 擋土牆重力式 | 3.3750 | — | 3.375 ✓ |
| 擋土牆懸臂式 | 1.7520 | — | 1.752 ✓ |
| 排水溝 U 型 | 0.7350 | − 0.3600 = **0.3750** | 0.375 ✓ |

排水溝的 30_ 圖層只畫「外框矩形」（W×總高 = 0.70×1.05 = 0.735），
內腔（B×H = 0.40×0.90 = 0.360）放在 `34_溝內腔`。
**不扣內腔，混凝土量會多算 96%。**
"""

import math
import os

import ezdxf


def _poly_area(pts):
    """鞋帶公式（有號面積；逆時針為正）。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _entity_pts(e):
    try:
        return [(v[0], v[1]) for v in e.get_points()]
    except Exception:
        return []


def _expand_bbox(d, x, y):
    """把一個點併進圖層的包圍盒（xmin/xmax/ymin/ymax）。"""
    x, y = float(x), float(y)
    if d["xmin"] is None or x < d["xmin"]:
        d["xmin"] = x
    if d["xmax"] is None or x > d["xmax"]:
        d["xmax"] = x
    if d["ymin"] is None or y < d["ymin"]:
        d["ymin"] = y
    if d["ymax"] is None or y > d["ymax"]:
        d["ymax"] = y


def measure(dxf_path, void_layers=("34_溝內腔",), skip_layers=("90_圖框",)):
    """量測 DXF 模型空間，回傳 {layer: {area, length, count, entities}}。

    area   —— 閉合多邊形 |面積| 之和（m²）
    length —— LINE／LWPOLYLINE 長度之和（m）
    count  —— 圖元數

    `areas`  —— 各閉合多邊形的面積清單（m²，依圖元順序）。
                 同一圖層可能同時畫「實體」與「示意剖面」等多塊，
                 只看總和會把不同語意的量混在一起；對帳要挑特定塊時用得到。
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    out = {}
    for e in msp:
        lay = e.dxf.layer
        if lay in skip_layers or lay.startswith("90_"):
            continue
        d = out.setdefault(lay, {"area": 0.0, "length": 0.0, "count": 0,
                                 "entities": {}, "areas": [], "lengths": [],
                                 "xmin": None, "xmax": None, "ymin": None, "ymax": None})
        t = e.dxftype()
        d["count"] += 1
        d["entities"][t] = d["entities"].get(t, 0) + 1
        if t == "LWPOLYLINE":
            pts = _entity_pts(e)
            for (px, py) in pts:
                _expand_bbox(d, px, py)
            if e.closed and len(pts) >= 3:
                a = abs(_poly_area(pts))
                d["area"] += a
                d["areas"].append(round(a, 4))
            for i in range(len(pts) - 1):
                seg = math.dist(pts[i], pts[i + 1])
                d["length"] += seg
                d["lengths"].append(round(seg, 4))
        elif t == "LINE":
            _expand_bbox(d, e.dxf.start.x, e.dxf.start.y)
            _expand_bbox(d, e.dxf.end.x, e.dxf.end.y)
            seg = math.dist((e.dxf.start.x, e.dxf.start.y),
                            (e.dxf.end.x, e.dxf.end.y))
            d["length"] += seg
            d["lengths"].append(round(seg, 4))
        elif t == "CIRCLE":
            seg = 2 * math.pi * e.dxf.radius
            d["length"] += seg
            d["lengths"].append(round(seg, 4))
    for d in out.values():
        d["area"] = round(d["area"], 4)
        d["length"] = round(d["length"], 2)
    return out


def net_area(meas, gross_layer="30_擋土牆混凝土", void_layers=("34_溝內腔",)):
    """混凝土淨面積 = 外框面積 − 內腔面積。"""
    gross = meas.get(gross_layer, {}).get("area", 0.0)
    void = sum(meas.get(l, {}).get("area", 0.0) for l in void_layers)
    return round(gross - void, 4), round(gross, 4), round(void, 4)


# 各模型的混凝土圖層（擋土牆／排水溝沿用舊名，箱涵另立）
SECTION_LAYERS = {
    "box_culvert": ("30_箱涵混凝土", ("34_箱涵內腔",)),
}


# --------------------------------------------------------------------------- #
# 模型對帳規格表（把圖／數對帳從「只會擋土牆／箱涵」擴到全部可出圖模型）
# --------------------------------------------------------------------------- #
# 每筆規格說明「量哪個圖層」與「期望值怎麼推」，兩者必須同一語意，
# 否則對帳就是在比不相干的兩個量（比對結果看似相符，實則毫無意義）。
#
# `unit` 量測單位：m²（面積）／m（長度）／個（數量）。
# `expect` 從 `quantities.values`（案件輸入）推導期望值；
# 若該輸入在案件檔中不存在，spec 會回傳 None → 誠實標「案件檔缺輸入，無法對帳」。
#
# ⚠ 語意差異要寫在 `note` 裡，因為「圖上量的」與「模型算的」有時是同一個量的
# 不同視角（例如基腳圖同時畫平面與剖面，平面面積與剖面積不同）。
RECONCILE_SPECS = {
    "rc_beam": {
        "layer": "30_構材混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _rect_area_mm(q, "b_mm", "h_mm"),
        "note": "圖上量梁斷面外框 b×h；模型取計算器輸入之斷面尺寸。",
    },
    "rc_column": {
        "layer": "30_構材混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _rect_area_mm(q, "b_mm", "h_mm"),
        "note": "圖上量柱斷面外框 b×h；模型取計算器輸入之斷面尺寸。",
    },
    "foundation_isolated": {
        "layer": "30_基腳混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _footing_drawn_area(q),
        "note": "F-1 同時畫平面（B×L）與剖面（B×t）兩塊，量到的是兩塊之和；"
                "模型＝基腳平面面積 ＋ 剖面面積（剖面為基腳本體一端，非示意）。",
    },
    "foundation_combined": {
        "layer": "30_基腳混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _footing_drawn_area(q),
        "note": "F-2 同時畫平面（B×L）與剖面（L×t）兩塊，量到的是兩塊之和；"
                "模型＝基腳平面面積 ＋ 剖面面積（剖面為基腳本體一端，非示意）。",
    },
    "channel_cover": {
        "layer": "30_溝蓋混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _channel_cover_area(q),
        "note": "C-01 為溝蓋斷面詳圖，量到的是每延米蓋版斷面積；"
                "模型取「總寬（淨寬＋兩側溝壁）× 版厚」，與圖上蓋版同寬。",
    },
    "detention_basin": {
        "layer": "30_池體輪廓", "unit": "m²", "kind": "area",
        "expect": lambda q: _detention_drawn_area(q),
        # 池頂外框與池底矩形都是閉合多邊形；池底＝內側較小的那塊。
        # 取「所有閉合塊中與模型值相符者」會變成自我實現，故改依幾何判定：
        # 池頂外框含池底（面積更大），池底＝最小的那塊閉合矩形。
        "pick": lambda d: min(d["areas"]) if d["areas"] else None,
        "note": "P-1 畫三樣東西：池頂外框、池底矩形、縱剖面折線。"
                "只有「池底矩形面積＝池底 L×W」能與數量模型同語意，"
                "故對帳只取該矩形（其餘為示意，不計價）。",
    },
    "sediment_basin": {
        "layer": "30_池體輪廓", "unit": "m²", "kind": "area",
        "expect": lambda q: _basin_footprint(q),
        "note": "P-2 畫池底平面（L×W）與縱剖面折線；對帳只取池底矩形"
                "（剖面為示意，不計價）。",
    },
    "steel_column": {
        "layer": "32_承台混凝土", "unit": "m²", "kind": "area",
        "expect": lambda q: _steel_pedestal_area(q),
        # 承台平面（B×N）與承台剖面兩塊都在此圖層；平面塊較小，剖面塊較大。
        "pick": lambda d: min(d["areas"]) if d["areas"] else None,
        "note": "SC-1 的 `32_承台混凝土` 畫兩塊：承台平面（B×N）與承台剖面；"
                "對帳取面積較小的平面塊，模型取計算結果之承台尺寸。",
    },
    "building_frame": {
        "layer": "30_柱", "unit": "m²", "kind": "area",
        "expect": lambda q: _frame_column_area(q),
        "note": "FR-1 量到所有柱斷面積之和；模型取柱數×柱斷面。",
    },
    "channel_profile": {
        "layer": "30_溝底線", "unit": "m", "kind": "xspan",
        "expect": lambda q: _float_or_none(q, "reach_length_m"),
        "note": "L-1 是**縱橫異比例**圖（垂直方向誇大最高 30 倍），"
                "圖上折線長度不是真實長度；對帳取溝底線的**水平投影長度**"
                "（X 座標跨度）＝計算段長 reach_length_m。",
    },
    "pile_group": {
        "layer": "30_樁位", "unit": "個", "kind": "count",
        "expect": lambda q: _pile_count(q),
        "note": "FP-1 以圓點標示樁位；模型取計算器結果之樁數。",
    },
    "settlement": {
        "layer": "30_基腳", "unit": "m²", "kind": "area",
        "expect": lambda q: _settlement_footing_area(q),
        "pick": lambda d: sum(d["areas"]) if d["areas"] else None,
        "note": "FS-1 量到所有基腳矩形面積之和；模型取各基腳 B×L 合計。",
    },
    "drainage_network": {
        "layer": None, "unit": None, "kind": "na",
        "expect": lambda q: None,
        "note": "NW-1 為示意圖（節點間距按版面比例，非實距），"
                "圖上長度不代表實際管長，故不做數量對帳。",
    },
    # ---- 邊坡：坡面斜長（斷面圖）----
    # 注意語意：坡面「面積」是斜長 × 邊坡長度的展開量，斷面圖上量不到；
    # 斷面圖能對的是地表線長度：坡面斜長 ＋ 前後平台延伸 ＋ 階段平台。
    # `35_坡面線` 圖層同時含「地表折線」與「加粗坡面線（0,0)→(run,H)）」，
    # 兩者重疊，故量到值 = 地表線長度 ＋ 坡面斜長。
    "slope": {
        "layer": "35_坡面線", "unit": "m", "kind": "length",
        "expect": lambda q: _slope_surface_line_length(q),
        "note": "E-01 為邊坡**斷面**圖：量到的是地表線長度（地表折線＋重疊的加粗坡面線）；"
                "模型為坡面斜長＋前後平台延伸(各 3 m)＋階段平台寬。"
                "坡面面積是斜長×邊坡長度的展開量，斷面圖上量不到，不在此對帳。",
    },
}


def _float_or_none(d, key):
    v = (d or {}).get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(d, key):
    v = (d or {}).get(key)
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _rect_area_mm(q, b_key, h_key):
    """mm 級矩形斷面積 → m²。"""
    b = _float_or_none(q, b_key)
    h = _float_or_none(q, h_key)
    if b is None or h is None:
        return None
    return b * h / 1.0e6


def _footing_plan_area(q):
    """基腳底面積 B×L（m²）。B、L 在 `geometry` 下或平鍵皆可。"""
    g = (q or {}).get("geometry") or {}
    b = _float_or_none(g, "B_m")
    l = _float_or_none(g, "L_m")
    if b is None:
        b = _float_or_none(q, "B_m")
    if l is None:
        l = _float_or_none(q, "L_m")
    if b is None or l is None:
        return None
    return b * l


def _footing_drawn_area(q):
    """基腳圖上的混凝土面積（m²）＝平面 B×L ＋ 剖面 B×t。

    F-1／F-2 同一圖層畫兩塊：平面視圖（矩形 B×L）與剖面視圖（矩形 B×t），
    兩塊都在 `30_基腳混凝土`。量測會把兩塊加總，所以期望值也要含剖面塊。

    剖面塊的長邊：獨立基腳是 B，聯合基腳是 L（沿柱列方向剖）。
    """
    g = (q or {}).get("geometry") or {}
    b = _float_or_none(g, "B_m")
    l = _float_or_none(g, "L_m")
    t = _float_or_none(g, "thickness_m")
    if b is None:
        b = _float_or_none(q, "B_m")
    if l is None:
        l = _float_or_none(q, "L_m")
    if t is None:
        t = _float_or_none(q, "thickness_m")
    if b is None or l is None or t is None:
        return None
    combined = bool((q or {}).get("columns")) or _model_is_combined(q)
    sec_len = l if combined else b
    return b * l + sec_len * t


def _model_is_combined(q):
    """案件 model 是否為聯合基腳。"""
    return str((q or {}).get("model") or "").strip() == "foundation_combined"


def _channel_cover_area(q):
    """溝蓋斷面積（m²）＝蓋版寬度 × 版厚。

    圖上蓋版橫跨「既有溝壁內側淨寬 ＋ 兩側壁厚」＝total_width_m，
    故期望值用總寬而非淨寬（用淨寬會差 2×壁厚，實測 66.7%）。
    """
    g = (q or {}).get("geometry") or {}
    w = _float_or_none(g, "clear_width_m")
    t = _float_or_none(g, "slab_thickness_mm")
    tw = _float_or_none(g, "wall_thickness_m")
    total = _float_or_none(g, "total_width_m")
    if w is None:
        w = _float_or_none(q, "clear_width_m")
    if t is None:
        t = _float_or_none(q, "slab_thickness_mm")
    if tw is None:
        tw = _float_or_none(q, "wall_thickness_m")
    if total is None and w is not None and tw is not None:
        total = w + 2.0 * tw
    if total is None:
        total = w
    if total is None or t is None:
        return None
    return total * t / 1000.0


def _basin_footprint(q):
    """池底面積（m²）。滯洪池在 `basin` 下；沉砂池為平鍵。"""
    b = (q or {}).get("basin") or {}
    l = _float_or_none(b, "bottom_length_m")
    w = _float_or_none(b, "bottom_width_m")
    if l is None:
        l = _float_or_none(q, "bottom_length_m")
    if w is None:
        w = _float_or_none(q, "bottom_width_m")
    if l is None:
        l = _float_or_none(q, "length_m")
    if w is None:
        w = _float_or_none(q, "width_m")
    if l is None or w is None:
        return None
    return l * w


def _detention_drawn_area(q):
    """滯洪池池底面積（m²）＝池底 L×W（`basin.bottom_length_m` × `bottom_width_m`）。"""
    return _basin_footprint(q)


def _steel_pedestal_area(q):
    """鋼柱承台面積（m²）。尺寸在 `base_plate` 結果或平鍵。"""
    bp = (q or {}).get("base_plate") or {}
    b = _float_or_none(bp, "pedestal_B_m")
    n = _float_or_none(bp, "pedestal_N_m")
    if b is None:
        b = _float_or_none(q, "pedestal_B_m")
    if n is None:
        n = _float_or_none(q, "pedestal_N_m")
    if b is None or n is None:
        return None
    return b * n


def _pile_count(q):
    """樁數（個）。`n_piles` 在計算結果裡，或由 `piles[]` 長度取得。"""
    n = _int_or_none(q, "n_piles")
    if n is not None:
        return n
    piles = (q or {}).get("piles") or []
    return len(piles) if piles else None


def _channel_profile_bed_length(q):
    """溝底線斜長（m）＝水平計算段長 ＋ 縱落差。

    圖上的溝底線是斜線：水平投影＝reach_length_m，縱落差＝reach_length_m × slope。
    模型取斜長（與圖上量測同語意），不是水平長度。
    """
    L = _float_or_none(q, "reach_length_m")
    if L is None:
        return None
    s = _float_or_none(q, "slope")
    if s is None:
        return L
    return math.hypot(L, L * s)


def _frame_column_area(q):
    """構架柱總面積（m²）＝Σ 柱投影面積。

    FR-1 是**立面圖**：柱畫成「寬 × 層高」的矩形（寬 0.45 m、層高 3.5 m → 1.575 m²），
    不是平面的柱斷面（0.45×0.45）。故此處以立面投影面積對帳。
    """
    g = (q or {}).get("geometry") or {}
    cw = _float_or_none(g, "column_mm")
    if cw is None:
        # 結果裡 `column_mm` 是 [寬, 深] 陣列（輸入的 `column_width_mm` 為單值）
        cm = g.get("column_mm")
        if isinstance(cm, (list, tuple)) and cm:
            cw = _float_or_none({"v": cm[0]}, "v")
        elif cm is not None:
            cw = _float_or_none(g, "column_mm")
    cw_in = _float_or_none(g, "column_width_mm")
    if cw_in is not None:
        cw = cw_in
    grid = g.get("x_grid_m") or q.get("x_grid_m")
    elevs = g.get("elevations_m") or q.get("elevations_m")
    if cw is None or not grid or not elevs:
        return None
    storeys = g.get("storey_heights_m") or q.get("storey_heights_m")
    if not storeys:
        # 由高程差推各層高
        storeys = [round(elevs[i + 1] - elevs[i], 6) for i in range(len(elevs) - 1)]
    if not storeys or not grid:
        return None
    total = 0.0
    for h in storeys:
        total += len(grid) * (cw / 1000.0) * float(h)
    return total


def _settlement_footing_area(q):
    """基腳沉陷：Σ B×L（m²）。基腳清單在 `footings[]`。"""
    fs = (q or {}).get("footings") or []
    total = 0.0
    any_found = False
    for f in fs:
        b = _float_or_none(f, "B_m")
        l = _float_or_none(f, "L_m")
        if b is None or l is None:
            continue
        total += b * l
        any_found = True
    return total if any_found else None


def _slope_surface_line_length(q):
    """邊坡斷面圖 `35_坡面線` 圖層的預期長度（m）。

    圖層內容 = 地表折線（坡趾前平台 3 m → 坡面 → 坡頂平台 3 m，含階段平台）
                ＋ 加粗坡面線（0,0)→(run,H)，與地表折線的坡面段重疊。
    所以量到值 = 坡面斜長 + 前後平台 6 m + 階段平台寬總和 + 坡面斜長（重疊的粗線）。
    階段坡面每段斜長合計仍等於整段坡面斜長（平台為水平，不增加斜長）。

    另含坡頂／坡腳各一道「坡面排水溝」小凹槽（同圖層），其長度由排水溝幾何
    決定、與數量模型無直接對應，故一併算入期望值（兩道凹槽的周長）。
    """
    h = _float_or_none(q, "height_m")
    beta = _float_or_none(q, "slope_angle_deg")
    if h is None or beta is None or beta <= 0:
        return None
    face = h / math.sin(math.radians(beta))
    bench_w = _float_or_none(q, "bench_width_m") or 0.0
    bench_n = _float_or_none(q, "bench_count") or 0.0
    pad = 3.0                      # make_wall_section 內的 PAD（前後平台延伸）
    return 2.0 * face + 2.0 * pad + bench_w * bench_n + 2.0 * _slope_drain_len()


def _slope_drain_len():
    """坡面排水溝凹槽的周長（m）—— 與 make_wall_section 的畫法一致。

    凹槽畫成 4 點折線（半寬 0.30 m、深 0.25 m 的梯形缺角）：
    (x-0.30, 0) → (x-0.20, -0.25) → (x+0.20, -0.25) → (x+0.30, 0)。
    """
    dx, dy = 0.10, 0.25
    bottom = 0.40
    side = math.hypot(dx, dy)
    return 2.0 * side + bottom


def _measured_value(meas, spec):
    """依規格從量測結果取對應的值。"""
    layer = spec.get("layer")
    if not layer:
        return None
    d = meas.get(layer)
    if d is None:
        return None
    pick = spec.get("pick")
    if pick:
        return pick(d)
    kind = spec.get("kind")
    if kind == "area":
        return d["area"]
    if kind == "length":
        return d["length"]
    if kind == "count":
        return d["count"]
    if kind == "xspan":
        # 水平投影長度：縱橫異比例圖上唯一能與真實長度相比的量
        if d.get("xmin") is None or d.get("xmax") is None:
            return None
        return d["xmax"] - d["xmin"]
    return None


REBAR_LAYER = "40_鋼筋"


def measure_rebar(dxf_path, max_radius=0.02):
    """量配筋圖上的鋼筋圓點，推算各排的實際間距（支／米）。

    `40_鋼筋` 圖層上混了兩種圓：
      · 真正的鋼筋斷面（半徑 = 鋼筋徑/2，D13≈0.0065、D16≈0.008）
      · 筋號圓標（半徑 0.055，用來標 A／B／C）
    必須用半徑過濾，否則圓標會被當成鋼筋（實測會多出 3 個假點）。

    回傳 [{x_m, n, y_lo, y_hi, span_m, spacing_m, per_m}]，依 x 分群。
    """
    import ezdxf as _ez
    doc = _ez.readfile(dxf_path)
    cs = [e for e in doc.modelspace().query("CIRCLE")
          if e.dxf.layer == REBAR_LAYER and e.dxf.radius <= max_radius]
    cols = {}
    for e in cs:
        c = e.dxf.center
        cols.setdefault(round(c.x / 0.010), []).append((c.x, c.y))
    out = []
    for k in sorted(cols):
        pts = sorted(cols[k], key=lambda p: p[1])
        n = len(pts)
        span = pts[-1][1] - pts[0][1]
        sp = span / (n - 1) if n > 1 else None
        out.append({"x_m": round(sum(p[0] for p in pts) / n, 3), "n": n,
                    "y_lo": round(pts[0][1], 3), "y_hi": round(pts[-1][1], 3),
                    "span_m": round(span, 3),
                    "spacing_m": round(sp, 3) if sp else None,
                    "per_m": round(1.0 / sp, 1) if sp else None})
    return out


def measure_rebar_rows(dxf_path, max_radius=0.02):
    """同一批鋼筋圓點改以 **水平列（y 分群）** 量間距。

    底板／溝底筋是沿 x 等距排列的，用垂直欄分群會全部變成單點（n=1），
    量不到間距。配筋圖對帳必須同時看「豎向排」與「水平排」兩種。
    """
    import ezdxf as _ez
    doc = _ez.readfile(dxf_path)
    cs = [e for e in doc.modelspace().query("CIRCLE")
          if e.dxf.layer == REBAR_LAYER and e.dxf.radius <= max_radius]
    rows = {}
    for e in cs:
        c = e.dxf.center
        rows.setdefault(round(c.y / 0.010), []).append((c.x, c.y))
    out = []
    for k in sorted(rows):
        pts = sorted(rows[k], key=lambda p: p[0])
        n = len(pts)
        span = pts[-1][0] - pts[0][0]
        sp = span / (n - 1) if n > 1 else None
        out.append({"y_m": round(sum(p[1] for p in pts) / n, 3), "n": n,
                    "x_lo": round(pts[0][0], 3), "x_hi": round(pts[-1][0], 3),
                    "span_m": round(span, 3),
                    "spacing_m": round(sp, 3) if sp else None,
                    "per_m": round(1.0 / sp, 1) if sp else None})
    return out


def measure_rebar_chain(dxf_path, max_radius=0.02):
    """量**斜面**上的鋼筋間距（重力式牆面有坡度，垂直欄／水平列都分不到組）。

    作法：只取「同一高度只有一根」的點（斜面豎向筋），依 y 排序後算相鄰點距離。
    底板筋在同一 y 有一整排，會被這個條件排除，不會污染結果。
    回傳 ``{"n", "spacing_m", "per_m"}`` 或 ``None``。
    """
    import ezdxf as _ez
    doc = _ez.readfile(dxf_path)
    cs = [e for e in doc.modelspace().query("CIRCLE")
          if e.dxf.layer == REBAR_LAYER and e.dxf.radius <= max_radius]
    by_y = {}
    for e in cs:
        c = e.dxf.center
        by_y.setdefault(round(c.y / 0.005), []).append((c.x, c.y))
    pts = sorted((v[0] for v in by_y.values() if len(v) == 1),
                 key=lambda p: p[1])
    if len(pts) < 3:
        return None
    ds = [((pts[i + 1][0] - pts[i][0]) ** 2
           + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
          for i in range(len(pts) - 1)]
    ds = sorted(d for d in ds if 0.05 <= d <= 1.0)
    if len(ds) < 2:
        return None
    sp = ds[len(ds) // 2]
    return {"n": len(pts), "spacing_m": round(sp, 3), "per_m": round(1.0 / sp, 1)}


def measure_rebar_lines(dxf_path, min_len=0.15):
    """量配筋圖上 40_鋼筋 圖層的主筋實線（LWPOLYLINE / LINE）。

    確保圖面上確實畫出受力主筋連續實線（而非只有圓點）。
    回傳 {"count": int, "total_len_m": float, "polylines": int, "lines": int}
    """
    import ezdxf as _ez
    doc = _ez.readfile(dxf_path)
    msp = doc.modelspace()
    polys = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == REBAR_LAYER]
    lines = [e for e in msp.query("LINE") if e.dxf.layer == REBAR_LAYER]

    total_len = 0.0
    valid_polys = 0
    for p in polys:
        pts = list(p.get_points())
        if len(pts) < 2:
            continue
        plen = sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
                   for i in range(len(pts) - 1))
        if plen >= min_len:
            total_len += plen
            valid_polys += 1

    valid_lines = 0
    for ln in lines:
        s, e = ln.dxf.start, ln.dxf.end
        llen = ((e.x - s.x) ** 2 + (e.y - s.y) ** 2) ** 0.5
        if llen >= min_len:
            total_len += llen
            valid_lines += 1

    return {
        "count": valid_polys + valid_lines,
        "polylines": valid_polys,
        "lines": valid_lines,
        "total_len_m": round(total_len, 3)
    }


def check_rebar(dxf_path, case_path):
    """把配筋圖量到的間距與案件（= 配筋表）的設計間距對帳，並檢核受力主筋實線。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    model, q, _ = CC.quantity_context(case)
    cols = measure_rebar(dxf_path)
    rows_ = measure_rebar_rows(dxf_path)
    main_lines = measure_rebar_lines(dxf_path)
    lines_ok = True
    lines_err = None
    # 設計間距：直接從配筋設計算（case 的 section 段只有比例與檔名，沒有間距）
    want = set()
    sec = case.get("section") or {}
    for k in ("stem_spacing_mm", "base_spacing_mm"):
        if sec.get(k):
            want.add(int(sec[k]))
    if not want:
        _dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "design")
        if _dd not in sys.path:
            sys.path.insert(0, _dd)
        try:
            import rc_design as RC
            if model == "wall":
                import wall_system as WS
                _wr = WS.analyse(q, case)
                _wd = WS.rebar_design(q, _wr)
                want.update(WS.spacing_candidates(q, _wr, _wd))
            elif model == "channel":
                import channel_hydraulics as CH
                _hy = case.get("hydraulics") or {}
                _hr = CH.analyse(float(_hy.get("design_flow_m3s") or 0.5),
                                 float(q["inner_width_m"]), float(q["depth_m"]),
                                 float(_hy.get("slope") or 0.005),
                                 {"manning_n": float(_hy.get("manning_n") or 0.014)})
                want.add(int(RC.design_channel_wall(q, _hr)["main"]["spacing_mm"]))
            elif model == "box_culvert":
                # 箱涵：8 個受拉面各自的設計間距（頂／底板、內外牆、中間牆兩面）
                _bd = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "box_section")
                if _bd not in sys.path:
                    sys.path.insert(0, _bd)
                import make_box_section as MBS
                _res = MBS.analyse_box(case, q)
                for _e in (_res.get("reinforcement") or {}).get("elements", []):
                    _sp = (_e.get("flexure") or {}).get("spacing_mm")
                    if _sp:
                        want.add(int(_sp))
        except Exception:
            pass

    if want:
        if main_lines["count"] == 0 or main_lines["total_len_m"] < 0.3:
            lines_ok = False
            lines_err = "圖面 40_鋼筋 圖層未畫出受力主筋實線（LWPOLYLINE/LINE），僅有圓點或實線總長不足！"

    # 水平列若只有 2 點（重力式牆面有坡度，同一高度的前後兩根筋距離會逐層變化），
    # 那不是「間距」而是兩面層的淨距，必須排除，否則會產生大量假間距。
    got = sorted({int(round(m["spacing_m"] * 1000))
                  for m in cols
                  if m["spacing_m"] and 0.05 <= m["spacing_m"] <= 1.0}
                 | {int(round(m["spacing_m"] * 1000))
                    for m in rows_
                    if m["spacing_m"] and m["n"] >= 3
                    and 0.05 <= m["spacing_m"] <= 1.0})
    # 斜面豎向筋（重力式牆面）在垂直欄／水平列都成不了組 → 補一條「沿面層」量測
    if want and not all(any(abs(g - w) <= 10 for g in got) for w in want):
        chain = measure_rebar_chain(dxf_path)
        if chain:
            got = sorted(set(got) | {int(round(chain["spacing_m"] * 1000))})
    return {"cols": cols, "design_mm": sorted(want), "found_mm": got,
            "main_lines": main_lines, "lines_ok": lines_ok, "lines_err": lines_err,
            "ok": None if not want else (all(any(abs(g - w) <= 10 for g in got) for w in want) and lines_ok)}


PAVING_LAYER = "15_刨鋪範圍"


def check_road(case_path, dxf_path, tol_pct=1.0):
    r"""道路案：量「15_刨鋪範圍」多邊形的面積，與案件數量對帳。

    道路平面圖是「現況底圖」，本來就沒有刨鋪範圍；這一層由
    `tools\takeoff\paving_extent.py` 從實測邊線產生後再拿來對帳。
    """
    import sys
    meas = measure(dxf_path)
    if PAVING_LAYER not in meas:
        return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
                "model": "road", "dxf": os.path.basename(dxf_path),
                "rows": [], "diff_pct": None, "tol_pct": tol_pct,
                "ok": False, "measure": meas,
                "error": "圖上沒有圖層「%s」—— 刨鋪範圍未畫出，無法對帳。"
                         "請先用 tools/takeoff/paving_extent.py 產生。" % PAVING_LAYER}
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    _, q, _ = CC.unit_context(case) if hasattr(CC, "unit_context") else CC.quantity_context(case)
    area_drawn = meas[PAVING_LAYER]["area"]
    # ⚠ 道路長度**不可**用「周長 ÷ 2」：閉合多邊形的周長 = 兩側邊線 + 兩個端蓋，
    # 除 2 會把端蓋算進去（實測 164.18 vs 實際 161.15，差 2%）。長度請用
    # paving_extent.py 輸出的 JSON（那裡有沿中心線算的弧長）。
    # 道路對帳只比**面積** —— 它才是決定 AC 體積的量（area × thickness）。
    rows, ok = [], True
    exp = float(q.get("area_m2") or 0)
    if exp:
        d = abs(area_drawn - exp) / exp * 100.0
        good = d <= tol_pct
        ok = ok and good
        rows.append({"item": "刨鋪面積", "drawn": round(area_drawn, 2),
                     "model": round(exp, 2), "diff_pct": round(d, 4),
                     "ok": good, "unit": "m²"})
    else:
        rows.append({"item": "刨鋪面積", "drawn": round(area_drawn, 2),
                     "model": None, "diff_pct": None, "ok": None, "unit": "m²"})
    return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
            "model": "road", "dxf": os.path.basename(dxf_path),
            "rows": rows, "diff_pct": max((r["diff_pct"] or 0) for r in rows) if rows else None,
            "tol_pct": tol_pct, "ok": ok, "measure": meas}


#: 案件 model → 設計計算器 id。兩者命名不一致的只有這幾個
#: （出圖模型的 model 名是圖面語意，計算器 id 是計算功能名）。
MODEL_CALC_ID = {
    "rc_beam": "rc_beam",
    "rc_column": "rc_column",
    "foundation_isolated": "foundation_isolated",
    "foundation_combined": "foundation_combined",
    "channel_cover": "channel_cover",
    "detention_basin": "detention_basin",
    "sediment_basin": "sediment_basin",
    "steel_column": "steel_column",
    "building_frame": "building_frame",
    "channel_profile": "channel_profile",
    "pile_group": "foundation_pile",
    "settlement": "settlement_assessment",
}


def _merge_engine_result(model, q, case):
    """把設計計算器的**結果**併進 q，供對帳期望值使用。

    為什麼必要：出圖工具的圖上數字取自計算結果（`design_section.build_case`
    把結果寫進案件檔的 `quantities.values`），但其中有些量（例如樁數
    `n_piles`、承台尺寸 `base_plate`、沉陷基腳清單 `footings`）
    只存在於計算結果，案件輸入裡沒有。若只讀輸入就會誤判成「缺輸入，無法對帳」。

    合併策略：把結果頂層鍵平鋪進 q（不覆寫既有輸入鍵），並保留原始輸入，
    讓 `expect` 可以兩邊都取到。
    """
    calc_id = MODEL_CALC_ID.get(model)
    if not calc_id:
        return q
    try:
        import sys as _sys
        HERE = os.path.dirname(os.path.abspath(__file__))
        _dd = os.path.join(os.path.dirname(HERE), "design")
        if _dd not in _sys.path:
            _sys.path.insert(0, _dd)
        import design_api as API
        env = API.run_calculation(calc_id, q)
        result = (env or {}).get("result") or {}
    except Exception:
        return q
    merged = dict(q)
    merged.setdefault("model", model)
    for k, v in result.items():
        if k not in merged or merged.get(k) in (None, ""):
            merged[k] = v
    # 常見的巢狀結果（geometry／base_plate 等）也平鋪一份，方便 expect 取值。
    for nest in ("geometry", "base_plate"):
        sub = result.get(nest)
        if isinstance(sub, dict):
            for k, v in sub.items():
                merged.setdefault(k, v)
    return merged


def _check_by_spec(case_path, dxf_path, model, q, meas, spec, tol_pct):
    """依 `RECONCILE_SPECS` 的模型規格做圖／數對帳。

    三種結果要分清楚，**不可**混為一談：
      * `ok=True`  —— 量測值與期望值在容差內。
      * `ok=False` —— 量到值但超出容差（真的對不上）。
      * `ok=None`  —— **沒有對帳**（圖層不存在／案件缺輸入／該模型不適用對帳）。
                        這種情況必須明寫原因，絕不可當成通過。
    """
    base = {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
            "model": model, "dxf": os.path.basename(dxf_path),
            "tol_pct": tol_pct, "measure": meas}
    unit = spec.get("unit") or ""
    note = spec.get("note") or ""

    if spec.get("kind") == "na":
        # 該模型本來就不適用數量對帳（例如示意圖）。
        base.update(rows=[], diff_pct=None, ok=None, note=note,
                    reason="此模型不適用數量對帳")
        return base

    layer = spec.get("layer")
    if layer not in meas:
        base.update(rows=[], diff_pct=None, ok=None, note=note,
                    reason="圖上沒有圖層「%s」，無法對帳。" % layer)
        return base

    drawn = _measured_value(meas, spec)
    expect = spec["expect"](q)
    if expect is None:
        base.update(rows=[], diff_pct=None, ok=None, note=note,
                    reason="案件檔缺對帳所需的輸入，無法對帳。")
        return base

    diff_pct = abs(drawn - expect) / expect * 100.0 if expect else None
    ok = diff_pct is not None and diff_pct <= tol_pct
    rows = [{"item": "圖面%s" % ("量測值" if spec.get("kind") == "count" else "量測"),
             "drawn": round(drawn, 4), "model": round(expect, 4),
             "diff_pct": round(diff_pct, 4) if diff_pct is not None else None,
             "ok": ok, "unit": unit}]
    base.update(rows=rows, diff_pct=round(diff_pct, 4) if diff_pct is not None else None,
                ok=ok, note=note)
    return base


def check_case(case_path, dxf_path, tol_pct=0.5):
    """把圖面量測值與案件檔的衍生數量對帳。"""
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "case_package"))
    import case_core as CC
    import qty_models as QM

    case = CC.load(case_path)
    if (case.get("quantities") or {}).get("model") == "block_wall":
        # 疊式／砌石牆（D2）：數量模型未納入 case_core；斷面積以 block_wall 引擎為準。
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "design"))
        import block_wall as _BW
        model = "block_wall"
        q = dict(case["quantities"].get("values") or {})
        q["section_area_m2"] = _BW.analyse(
            q, case.get("soil") or {}, case.get("seismic") or {})["geometry"]["area_m2_per_m"]
    else:
        model, q, _ = CC.quantity_context(case)
    meas = measure(dxf_path)

    # ---- 新路徑：模型有專屬對帳規格 → 依規格比對（item 3）----
    spec = RECONCILE_SPECS.get(model)
    if spec is not None:
        q = _merge_engine_result(model, q, case)
        return _check_by_spec(case_path, dxf_path, model, q, meas, spec, tol_pct)

    gross_layer, void_layers = SECTION_LAYERS.get(
        model, ("30_擋土牆混凝土", ("34_溝內腔",)))
    net, gross, void = net_area(meas, gross_layer, void_layers)

    # 扶壁式的 S-01/S-02 是「兩扶壁間」的實體斷面，扶壁以虛線表示；
    # 混凝土體積仍含扶壁分攤。對帳必須用 section_area_typical_m2，
    # 否則會把扶壁分攤算成圖面漏畫（8 m 案實測差 27.9%）。
    _key = getattr(QM, "DRAWN_SECTION_AREA_KEY", "")
    if model == "box_culvert":
        # 箱涵的斷面積鍵名由數量模型定義，這裡直接由幾何輸入重算（外框－孔洞），
        # 不寫死鍵名也避免與 qty_models 的鍵名不一致。
        # 孔洞是含內角 45° 加腋的八邊形：每孔淨空 = B×H − 2c²（4 個角各 c²/2）。
        _c = float(q.get("inner_chamfer_m", 0.0) or 0.0)
        expect = (float(q["outer_width_m"]) * float(q["outer_height_m"])
                  - int(q["cell_count"]) * (float(q["clear_width_m"])
                  * float(q["clear_height_m"]) - 2.0 * _c * _c))
    else:
        expect = float((q.get(_key) if _key else None) or q.get("section_area_m2") or 0)
    diff_pct = (abs(net - expect) / expect * 100.0) if expect else None
    rows = [
        {"item": "圖面混凝土外框面積", "drawn": gross, "model": None, "unit": "m²"},
        {"item": "圖面內腔面積（應扣）", "drawn": void, "model": None, "unit": "m²"},
        {"item": "圖面混凝土淨面積（實體斷面）", "drawn": net,
         "model": round(expect, 4), "unit": "m²"},
    ]
    ok = diff_pct is not None and diff_pct <= tol_pct
    return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
            "model": model, "dxf": os.path.basename(dxf_path),
            "rows": rows, "diff_pct": round(diff_pct, 4) if diff_pct is not None else None,
            "tol_pct": tol_pct, "ok": ok, "measure": meas}


def format_report(r):
    L = [f"案件：{r['case']}（model={r['model']}）  DXF：{r['dxf']}", ""]
    L.append("  圖層量測：")
    for lay, d in sorted(r["measure"].items()):
        L.append("    %-18s 面積 %8.4f m²  長度 %9.2f m  圖元 %d %s"
                 % (lay, d["area"], d["length"], d["count"],
                    d["entities"] if d["entities"] else ""))
    L.append("")
    L.append("  對帳：")
    if r.get("reason"):
        # 沒有對帳 ≠ 對帳通過。這裡要把原因寫清楚，讓呼叫端不能誤判。
        L.append("    → ⚠ 未對帳：%s" % r["reason"])
        if r.get("note"):
            L.append("      （%s）" % r["note"])
        return "\n".join(L)
    for row in r["rows"]:
        m = "—" if row["model"] is None else "%.4f" % row["model"]
        L.append("    %-22s 圖面 %.4f %s ／ 模型 %s"
                 % (row["item"], row["drawn"], row["unit"], m))
    if r["diff_pct"] is not None:
        L.append("    → 差異 %.4f%%（容許 %.2f%%）  %s"
                 % (r["diff_pct"], r["tol_pct"], "符合" if r["ok"] else "**不符**"))
    else:
        L.append("    → 案件檔無 section_area_m2，無法對帳")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DXF 圖面數量量測與案件檔對帳")
    ap.add_argument("dxf", help="要量測的 DXF")
    ap.add_argument("--case", help="案件 JSON（給了就做對帳）")
    ap.add_argument("--tol", type=float, default=0.5, help="容許差異 %%（預設 0.5）")
    ap.add_argument("--rebar", action="store_true", help="改量配筋圖的鋼筋圓點間距")
    a = ap.parse_args()
    if a.rebar:
        cols = measure_rebar(a.dxf)
        rows_ = measure_rebar_rows(a.dxf)
        print("  鋼筋圓點分群（已排除筋號圓標 r>0.02）：")
        for c in cols:
            print("    x≈%5.3f  n=%2d  y %.3f~%.3f（跨 %.3f）"
                  % (c["x_m"], c["n"], c["y_lo"], c["y_hi"], c["span_m"])
                  + ("  間距 %.3f m → %4.1f 支/米" % (c["spacing_m"], c["per_m"])
                     if c["spacing_m"] else "  （單點）"))
        print("  水平列（底板／溝底筋）：")
        for r in rows_:
            if not r["spacing_m"] or r["n"] < 3:
                continue
            print("    y≈%5.3f  n=%2d  x %.3f~%.3f  間距 %.3f m → %4.1f 支/米"
                  % (r["y_m"], r["n"], r["x_lo"], r["x_hi"],
                     r["spacing_m"], r["per_m"]))
        if a.case:
            r = check_rebar(a.dxf, a.case)
            if r.get("main_lines"):
                ml = r["main_lines"]
                print("  受力主筋實線（40_鋼筋 圖層）：%d 條（折線 %d、直線 %d），總長 %.2f m"
                      % (ml["count"], ml["polylines"], ml["lines"], ml["total_len_m"]))
                if not r.get("lines_ok"):
                    print("  [錯誤] %s" % r.get("lines_err"))
            print("\n  配筋表設計間距 %s mm；圖面量到 %s mm → %s"
                  % (r["design_mm"], r["found_mm"],
                     "相符" if r["ok"] else ("無法比對" if r["ok"] is None else "**不符**")))
            raise SystemExit(0 if (r["ok"] is not False) else 1)
        raise SystemExit(0)
    if a.case:
        r = check_case(a.case, a.dxf, a.tol)
        if r.get("error") or r["model"] == "road":
            # 道路案（或斷面圖缺 section_area_m2）→ 走道路對帳
            r2 = check_road(a.case, a.dxf, max(a.tol, 1.0))
            if not r.get("error") and not (r["diff_pct"] is None):
                pass
            print(r2.get("error") or "")
            for row in r2["rows"]:
                m = "—" if row["model"] is None else "%.2f" % row["model"]
                d = "—" if row["diff_pct"] is None else "%.4f%%" % row["diff_pct"]
                v = "" if row["ok"] is None else ("  符合" if row["ok"] else "  **不符**")
                print("    %-10s 圖面 %10.2f ／ 案件 %s ／ 差異 %s%s"
                      % (row["item"], row["drawn"], m, d, v))
            raise SystemExit(0 if r2["ok"] else 1)
        print(format_report(r))
        # 退出碼語意：0＝對帳相符；1＝對上了但超出容差；2＝未對帳（無法比對）。
        # 「未對帳」不可與「相符」共用 0，否則呼叫端會把沒比過的當成比過。
        if r["ok"] is None:
            raise SystemExit(2)
        raise SystemExit(0 if r["ok"] else 1)
    meas = measure(a.dxf)
    for lay, d in sorted(meas.items()):
        print("  %-18s 面積 %8.4f m²  長度 %9.2f m  圖元 %d"
              % (lay, d["area"], d["length"], d["count"]))
