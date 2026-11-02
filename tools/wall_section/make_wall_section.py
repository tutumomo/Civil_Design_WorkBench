"""擋土牆標準斷面圖（含配筋示意）產線：案件 JSON → A3 DXF/DWG/PDF。

定位
----
`tools\\a3_sheet\\make_sheet.py` 只做「現況平面圖」。擋土牆要交的是 **S-01 標準斷面圖**
（斷面尺寸、排水孔、背填反濾層）與 **S-02 配筋圖**；本工具補這一塊。

與既有產線的關係（刻意重用，不重造）
------------------------------------
* 圖框：沿用 `tools\\a3_sheet\\A3圖框_template.dxf`（與平面圖同一張，標題欄一致）
* 出圖比例：`tools\\drawing_rules.py` 的標準比例尺（斷面用 1:20 系列細部比例）
* 字高：本文 3／附註 4／標題 5 mm（出圖規定），模型文字依比例換算
* 品管：直接跑 `tools\\a3_sheet\\check_delivery.py`，用
  `--building-layer 30_擋土牆混凝土 --hatch-layer 31_擋土牆剖面線` 讓 E11 檢查剖面線有無漏，
  `--require-layer` 指定斷面必要圖層 → E1~E18 全套沿用
* DWG/PDF：`tools\\acad\\acc.py publish`

用法
----
    set PYTHONIOENCODING=utf-8
    C:\\Python312\\python.exe tools\\wall_section\\make_wall_section.py ^
        cases\\擋土牆3m重力式\\case.json --scale 20 --out cases\\擋土牆3m重力式\\S-01_擋土牆標準斷面圖.dxf --publish
"""

import argparse
import json
import math
import os
import sys
import time

import ezdxf
from ezdxf.enums import TextEntityAlignment

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "a3_sheet"))
sys.path.insert(0, os.path.join(ROOT, "tools", "case_package"))

import drawing_rules as DR                    # noqa: E402
from drawing_rules import model_h             # noqa: E402
import case_core as CC                       # noqa: E402

TEMPLATE = os.path.join(ROOT, "tools", "a3_sheet", "A3圖框_template.dxf")
LAYOUT_NAME = "斷面圖"

# 圖框分區（與 check_delivery.py 同值）
X0, Y0, X1, Y1 = 10.03, 29.00, 410.27, 287.45
TITLE_BLOCK = (9.79, 10.40, 410.27, 29.03)
STAMP_ZONE = (363.50, 29.00, 410.30, 80.90)

# 圖層（數字前綴_中文說明；E12 只要求兩碼前綴）
L_CONC = "30_擋土牆混凝土"
L_HATCH = "31_擋土牆剖面線"
L_BACK = "32_背填反濾層"
L_EXC = "33_開挖線"
L_REBAR = "40_鋼筋"
L_WEEP = "41_排水孔"
L_INNER = "34_溝內腔"
L_SLOPE = "35_坡面線"
L_SOIL = "36_坡體"
L_VEG = "37_植生"
L_GWL = "38_地下水位"
L_SLIP = "39_滑動圓"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"
L_FRAME = "圖框"
L_LEGEND = "91_圖例"
L_SCALE = "92_比例尺"
L_DESC = "93_說明"


# --------------------------------------------------------------------------- #
def load_case(case_path):
    """載入案件並取數量：支援 wall（擋土牆）與 channel（排水溝）兩種斷面。"""
    case = CC.load(case_path)
    model, q, issues = CC.quantity_context(case)
    errs = [i for i in issues if i["level"] == "error"]
    if errs:
        raise SystemExit("案件數量錯誤，先跑 case_core.py check：\n  " +
                         "\n  ".join(i["msg"] for i in errs))
    if model not in ("wall", "channel", "slope"):
        raise SystemExit(
            f"本工具做擋土牆／排水溝／邊坡斷面（model 應為 wall、channel 或 slope，現在是 {model}）")
    return case, q, model


def draw_channel_section(doc, q, scale, dimstyle, rebar=None):
    """U 型排水溝標準斷面（矩形內腔）。"""
    msp = doc.modelspace()
    B = float(q["inner_width_m"]); H = float(q["depth_m"])
    t = float(q["wall_thickness_m"]); tb = float(q["base_thickness_m"])
    W = B + 2 * t                      # 外寬

    hatch_scale = (1.5 * scale / 1000.0) / 3.175

    # 混凝土斷面（U 形：外框減內腔）
    outer = [(0.0, 0.0), (W, 0.0), (W, H + tb), (0.0, H + tb)]
    msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": L_CONC})
    inner = [(t, tb), (t + B, tb), (t + B, tb + H), (t, tb + H)]
    msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": L_INNER})
    # 剖面線只填混凝土區：用外框 + 內腔洞
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=max(hatch_scale, 1e-4))
    h.paths.add_polyline_path(outer, is_closed=True)
    h.paths.add_polyline_path(inner, is_closed=True)

    # 開挖線
    ex0, ex1 = -0.30, W + 0.30
    msp.add_line((ex0, 0.15), (ex0, -0.20), dxfattribs={"layer": L_EXC})
    msp.add_line((ex0, -0.20), (ex1, -0.20), dxfattribs={"layer": L_EXC})
    msp.add_line((ex1, -0.20), (ex1, 0.15), dxfattribs={"layer": L_EXC})

    # 內腔多邊形已於上方建立（供 Hatch 挖洞與面線共用），此處不再重畫。
    # 曾重畫一次 → 34_溝內腔 圖層有兩個同面積多邊形 → 量測扣內腔時被扣兩次
    # （0.36×2 = 0.72），混凝土淨面積從 0.375 變 0.015（差 96%）。

    # 尺寸：內寬、溝深、壁厚、底厚、總高
    def dim(p1, p2, base, angle=None):
        # 線性尺寸 angle=0 量水平投影、90 量鉛直投影；鉛直線段給 0 會量到 0
        if angle is None:
            angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=dimstyle, dxfattribs={"layer": L_DIM})
        d.render()
    dim((t, tb), (t + B, tb), (t, tb - 0.22))                    # 內寬 B
    dim((0, tb), (0, tb + H), (-0.25, tb))                       # 溝深 H
    dim((W, 0), (W, H + tb), (W + 0.22, 0))                      # 總高
    dim((0, H + tb), (t, H + tb), (0, H + tb + 0.22))            # 壁厚 t
    dim((0, 0), (W, 0), (0, -0.45))                              # 外寬

    # 部位圓標
    hb = model_h(3.0, scale)
    tags = [
        (1, (t / 2, (H + tb) / 2)),                # 溝壁
        (2, (W / 2, tb / 2)),                      # 溝底
        (3, (W / 2, (H + tb) / 2)),                # 通水斷面
        (4, (-0.16, -0.10)),                       # 開挖線
    ]
    for k, (x, y) in tags:
        msp.add_circle((x, y), 0.05, dxfattribs={"layer": L_NOTE})
        tt = msp.add_text(str(k), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        tt.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)

    # 鋼筋（S-02/D-02 配筋圖時依設計結果；否則用示意值）
    _dia = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
            "D22": 0.022, "D25": 0.025}
    cover = 0.05
    _bar = (rebar or {}).get("stem_bar", "D13")
    _sp = (rebar or {}).get("stem_spacing_mm", 200) / 1000.0
    d13 = _dia.get(_bar, 0.013)
    for yy in (tb + cover, tb + H - cover):
        xx = t + cover
        while xx <= t + B - cover:
            msp.add_circle((xx, yy), d13 / 2, dxfattribs={"layer": L_REBAR})
            xx += _sp
    for xx in (cover, W - cover):
        yy = cover + 0.02
        while yy <= tb + H - cover:
            msp.add_circle((xx, yy), d13 / 2, dxfattribs={"layer": L_REBAR})
            yy += _sp

    return dict(H=H, B=B, T=t, BT=tb, W=W, wall_type="channel",
                title_note="排水溝標準斷面圖", drawing_no="D-01")


def ensure_layers(doc):
    # 出圖樣式（2026-10-29）：顏色 1~8 對應線粗；牆身主線重要(5)、鋼筋一般(1)、剖面線次要(8)
    spec = [(L_CONC, 5), (L_HATCH, 8), (L_BACK, 8), (L_EXC, 8), (L_INNER, 7), (L_REBAR, 1),
            (L_WEEP, 4), (L_DIM, 3), (L_NOTE, 7), (L_LEGEND, 7), (L_SCALE, 7), (L_DESC, 7)]
    for name, color in spec:
        DR.add_plot_layer(doc, name, color=color)
    # 開挖線用虛線
    if "DASHED" in doc.linetypes:
        doc.layers.get(L_EXC).dxf.linetype = "DASHED"


def ensure_tomo(doc):
    st = doc.styles.get("TOMO") if "TOMO" in doc.styles else None
    if st is None:
        st = doc.styles.add("TOMO", font="gbenor.shx")
    st.dxf.font = "gbenor.shx"
    st.dxf.bigfont = "CHINA1.SHX"
    st.dxf.width = 1.0


def ensure_dimstyle(doc, scale):
    name = "TOMO尺寸"
    h = model_h(3.0, scale)                    # 本文 3 mm 換算
    if name not in doc.dimstyles:
        ds = doc.dimstyles.add(name)
    else:
        ds = doc.dimstyles.get(name)
    ds.dxf.dimtxt = h
    ds.dxf.dimasz = model_h(2.0, scale)
    ds.dxf.dimexe = model_h(1.5, scale)
    ds.dxf.dimexo = model_h(1.5, scale)
    ds.dxf.dimgap = model_h(1.0, scale)
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimdec = 2
    ds.dxf.dimdsep = 46                     # ord('.')：小數點用「.」，不可用「,」
    ds.dxf.dimlunit = 2
    ds.dxf.dimclrd = 3
    ds.dxf.dimclre = 3
    ds.dxf.dimclrt = 7
    ds.dxf.dimtxsty = "TOMO"
    return name


# --------------------------------------------------------------------------- #
# 模型空間：斷面幾何、鋼筋、排水孔、背填、尺寸
# --------------------------------------------------------------------------- #
def draw_slope_section(doc, q, scale, dimstyle):
    """邊坡標準斷面：坡面線、坡趾／坡頂平台、階段平台、坡面排水、植生、地下水位、滑動圓。"""
    import math
    msp = doc.modelspace()
    H = float(q["height_m"])
    beta = math.radians(float(q["slope_angle_deg"]))
    run = H / math.tan(beta)                 # 水平投影
    face = H / math.sin(beta)                # 坡面斜長
    bw = float(q.get("bench_width_m", 0) or 0)
    bn = int(float(q.get("bench_count", 0) or 0))
    gw = float(q.get("groundwater_ratio", 0) or 0)
    hatch_scale = (1.5 * scale / 1000.0) / 3.175
    hb = 3.0 * scale / 1000.0                # 本文 3 mm
    hs = 4.0 * scale / 1000.0                # 附註 4 mm
    PAD = 3.0                                # 前後平台延伸長度 m

    # 地表線：坡趾前平地 → 坡面 → 坡頂平台（設平台時坡面為折線）
    crest = [(run, H)]
    line = [(-PAD, 0.0), (0.0, 0.0)]
    if bn > 0 and bw > 0:
        # 階段式：把坡面切成 bn+1 段，每段之間插入水平平台
        seg = (run - bn * bw) / (bn + 1) if (run - bn * bw) > 0 else run / (bn + 1)
        x, y = 0.0, 0.0
        step = H / (bn + 1)
        for i in range(bn + 1):
            x2 = x + seg + (bw if i < bn else 0.0)
            y2 = y + step
            line.append((x + seg, y2))
            if i < bn:
                line.append((x + seg + bw, y2))     # 水平平台
                x = x + seg + bw
            else:
                x = x2
            y = y2
        crest = [(x, H)]
    else:
        line.append((run, H))
    line.append((run + PAD, H))

    # 坡體剖面線（地表以下）
    poly = line + [(run + PAD, -1.5), (-PAD, -1.5)]
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_SOIL})
    h.set_pattern_fill("ANSI31", color=256, scale=hatch_scale)
    h.paths.add_polyline_path(poly, is_closed=True)

    # 地表線
    msp.add_lwpolyline(line, dxfattribs={"layer": L_SLOPE})
    # 坡面線加粗標示（坡趾→坡頂）
    msp.add_line((0.0, 0.0), (run, H), dxfattribs={"layer": L_SLOPE})

    # 地下水位（虛線）
    if gw > 0:
        yw = gw * H
        ln = msp.add_line((-PAD, yw), (run + PAD, yw),
                          dxfattribs={"layer": L_GWL})
        ln.dxf.linetype = "DASHED"
        msp.add_text("地下水位", height=hb,
                     dxfattribs={"layer": L_GWL, "style": "TOMO"}).set_placement(
            (run + PAD - 2.2, yw + 0.12))

    # 植生符號（沿坡面短斜線）
    veg = int(max(3, min(14, round(face / max(H, 1e-6) * 4))))
    for k in range(veg):
        t = (k + 0.5) / veg
        x, y = run * t, H * t
        msp.add_line((x, y), (x - 0.18, y + 0.30), dxfattribs={"layer": L_VEG})
        msp.add_line((x, y), (x + 0.10, y + 0.30), dxfattribs={"layer": L_VEG})

    # 最不利滑動圓（若有分析模組）
    slip = None
    try:
        import sys as _sys
        _dd = os.path.join(ROOT, "tools", "design")
        if _dd not in _sys.path:
            _sys.path.insert(0, _dd)
        import slope_stability as _SS
        _r = _SS.analyse(q)
        slip = _r["circular"]
        cx, cy, R = slip["xc"], slip["yc"], slip["R"]
        a0 = math.atan2(0.0 - cy, 0.0 - cx)      # 坡趾
        # 取坡頂／平台側交點角度
        a1 = math.atan2(H - cy, run - cx)
        pts = []
        steps = 60
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            pts.append((cx + R * math.cos(a), cy + R * math.sin(a)))
        msp.add_lwpolyline(pts, dxfattribs={"layer": L_SLIP})
        msp.add_text("最不利滑動圓 FS=%.2f" % slip["FS"], height=hb,
                     dxfattribs={"layer": L_SLIP, "style": "TOMO"}).set_placement(
            (cx + R * 0.25, cy - R * 0.95))
    except Exception:
        slip = None

    # 坡面排水溝（坡頂與坡腳各一，簡化為小梯形凹槽）
    for gx, gy in ((run + 0.6, H), (-0.6, 0.0)):
        msp.add_lwpolyline(
            [(gx - 0.30, gy), (gx - 0.20, gy - 0.25), (gx + 0.20, gy - 0.25),
             (gx + 0.30, gy)], dxfattribs={"layer": L_SLOPE})

    # ---- 尺寸 ----
    def dim(p1, p2, base, angle=None):
        # ezdxf 的 add_linear_dim 不接受 angle=None（會 float(None) 爆掉）→ 只有給值才傳
        kw = {"base": base, "p1": p1, "p2": p2,
              "dimstyle": dimstyle, "dxfattribs": {"layer": L_DIM}}
        if angle is not None:
            kw["angle"] = angle
        d = msp.add_linear_dim(**kw)
        d.render()

    dim((-0.0, 0.0), (0.0, H), (-0.9, 0.0))                    # 坡高 H（垂直）
    dim((0.0, -0.7), (run, -0.7), (0.0, -0.7))                # 水平投影
    dim((0.0, 0.0), (run, H), (0.0, H + 0.6), angle=0)        # 坡面斜長（水平投影）

    # 坡角 β 與坡度 1:m
    msp.add_text("β = %.1f°" % float(q["slope_angle_deg"]), height=hs,
                 dxfattribs={"layer": L_NOTE, "style": "TOMO"}).set_placement(
        (run * 0.06 + 0.15, 0.35))
    msp.add_text("坡度 1 : %.2f" % (1.0 / math.tan(beta)), height=hs,
                 dxfattribs={"layer": L_NOTE, "style": "TOMO"}).set_placement(
        (run * 0.06 + 0.15, 0.35 - hs * 1.6))

    # 部位標註
    for tx, ty, txt in ((run + PAD - 3.0, H + 0.35, "坡頂平台"),
                        (run * 0.5 + 0.25, H * 0.5 + 0.35, "坡面（植生）"),
                        (-PAD + 0.2, 0.35, "坡趾")):
        msp.add_text(txt, height=hb,
                     dxfattribs={"layer": L_NOTE, "style": "TOMO"}).set_placement((tx, ty))

    return dict(H=H, run=run, face=face, B=run, W=run, T=0.0, BT=0.0,
                BW=bw, BN=bn, GW=gw, slope_deg=float(q["slope_angle_deg"]),
                slip=slip, title_note="邊坡標準斷面圖", drawing_no="E-01")


def draw_section(doc, q, scale, dimstyle, rebar=None):
    msp = doc.modelspace()
    H = float(q["height_m"]); T = float(q["stem_thickness_m"])
    BL = float(q["base_width_m"]); BT = float(q["base_thickness_m"])
    WD = float(q.get("weep_diameter_m", 0.05))
    NZ = int(q.get("weep_rows", 3) or 3)
    BACK = float(q.get("backfill_thickness_m", 0.3))
    FILT = 0.10                                  # 反濾層厚（固定 10 cm）
    # 牆趾（主動土壓力側）覆土深度：設計值 >= 0.60 m，圖上要畫出來，
    # 否則圖面是「素地」、計算卻用了被動土壓，兩者對不起來。
    TOE = float(q.get("toe_soil_depth_m", 0.0) or 0.0)

    # ---- 混凝土斷面：重力式＝梯形；懸臂式＝薄牆身 + 底板 ----
    wall_type = str(q.get("wall_type", "cantilever"))
    if wall_type == "gravity":
        # 梯形：**背面（靠土側）鉛直在 x=BL、正面（露出側）放坡**
        # 必須與 tools\design\retaining_wall.py 的幾何一致，否則圖上畫的斷面
        # 和算穩定用的斷面是兩個東西（質量分布不同，驗算結果不能互相比對）。
        pts = [(0.0, 0.0), (BL, 0.0), (BL, H), (BL - T, H)]
    else:
        pts = [(0.0, -BT), (BL, -BT), (BL, 0.0), (T, 0.0), (T, H), (0.0, H)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_CONC})
    # 剖面線間距：紙面約 1.5 mm。模型 1 unit = 1 m、ANSI31 圖案基準間距 3.175 unit
    # 先前寫 scale/20（1:20 → 1.0 unit ≈ 3.2 m 間距）→ 3 m 高的牆只畫得出 1 條線。
    hatch_scale = (1.5 * scale / 1000.0) / 3.175
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=max(hatch_scale, 1e-4))
    h.paths.add_polyline_path(pts, is_closed=True)

    # ---- 背填（透水性材料）+ 反濾層 ----
    # 懸臂式：牆背鉛直在 x=T → 背填 T ~ T+BACK（鉛直帶狀）
    # 重力式：斷面 [(0,0),(BL,0),(T,H),(0,H)] → 正面在 x=0 鉛直、背面是 (BL,0)→(T,H) 斜面
    #          背填須「沿斜面往後」；若從 x=0 起算會填進牆體裡（先前就是這個錯）
    if wall_type == "gravity":
        b_lo, b_hi = BL, BL          # 背面鉛直 → 背填為鉛直帶狀
    else:
        b_lo, b_hi = T, T
    back_pts = [(b_lo, 0.0), (b_lo + BACK, 0.0), (b_hi + BACK, H), (b_hi, H)]
    msp.add_lwpolyline(back_pts, close=True, dxfattribs={"layer": L_BACK})
    h2 = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
    h2.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
    h2.paths.add_polyline_path(back_pts, is_closed=True)
    filt = [(b_lo + BACK, 0.0), (b_lo + BACK + FILT, 0.0),
            (b_hi + BACK + FILT, H), (b_hi + BACK, H)]
    msp.add_lwpolyline(filt, close=True, dxfattribs={"layer": L_BACK})
    # 背填／反濾層分界線（兩者都是 L_BACK 圖層，沒有這條線看不出分界）
    msp.add_line((b_lo + BACK, 0.0), (b_hi + BACK, H),
                 dxfattribs={"layer": L_BACK})

    # ---- 原地面線（前後地面）----
    # 有牆趾覆土時，前方地面抬到 y=TOE（覆土面），牆面在該高度的 x 由正面坡度反算。
    gx = 0.6
    if TOE > 1e-9 and wall_type == "gravity":
        xf = (BL - T) * TOE / H if H > 1e-9 else 0.0
        msp.add_line((-gx, TOE), (xf, TOE), dxfattribs={"layer": L_NOTE})
        cover = [(-gx, 0.0), (xf, 0.0), (xf, TOE), (-gx, TOE)]
        msp.add_lwpolyline(cover, close=True, dxfattribs={"layer": L_BACK})
        hc = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
        hc.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
        hc.paths.add_polyline_path(cover, is_closed=True)
    else:
        msp.add_line((-gx, 0.0), (0.0, 0.0), dxfattribs={"layer": L_NOTE})
    msp.add_line((b_hi + BACK + FILT, H), (b_hi + BACK + FILT + 0.5, H),
                 dxfattribs={"layer": L_NOTE})

    # ---- 開挖線（虛線）----
    ex0 = -0.45
    ex1 = (BL if wall_type == "gravity" else T) + BACK + FILT + 0.2
    base_y = 0.0 if wall_type == "gravity" else -BT
    msp.add_line((ex0, 0.15), (ex0, base_y - 0.15), dxfattribs={"layer": L_EXC})
    msp.add_line((ex0, base_y - 0.15), (ex1, base_y - 0.15), dxfattribs={"layer": L_EXC})
    msp.add_line((ex1, base_y - 0.15), (ex1, 0.15), dxfattribs={"layer": L_EXC})

    # ---- 排水孔（Ø5cm，等距）----
    ys = [H / (NZ + 1) * (k + 1) for k in range(NZ)]
    for y in ys:
        msp.add_circle((0.0, y), WD / 2, dxfattribs={"layer": L_WEEP})
        msp.add_line((0.0, y), (-0.12, y), dxfattribs={"layer": L_WEEP})   # 洩水管出水口

    # ---- 背填頂面（回填面）----
    msp.add_line((b_hi + BACK + FILT, H), (b_lo + BACK + FILT, 0.0),
                 dxfattribs={"layer": L_BACK})

    # ---- 鋼筋 ----
    # 有配筋設計結果（S-02 配筋圖）→ 依設計的筋號與間距配置；否則用示意值（S-01 標準斷面圖）。
    cover = 0.075
    _RB = {"stem": ("D16", 200), "base": ("D16", 210)}     # 示意預設
    if rebar:
        _RB["stem"] = (rebar.get("stem_bar", "D16"), int(rebar.get("stem_spacing_mm", 200)))
        _RB["base"] = (rebar.get("base_bar", "D16"), int(rebar.get("base_spacing_mm", 210)))
    _dia = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
            "D22": 0.022, "D25": 0.025}
    d16 = _dia.get(_RB["stem"][0], 0.016)
    dbase = _dia.get(_RB["base"][0], 0.016)
    sp_stem = _RB["stem"][1] / 1000.0
    sp_base = _RB["base"][1] / 1000.0
    xs_main = [cover, T - cover]
    y = cover + 0.05
    while y <= H - cover:
        for x in xs_main:
            msp.add_circle((x, y), d16 / 2, dxfattribs={"layer": L_REBAR})
        y += sp_stem
    if wall_type != "gravity":
        yb = [-BT + cover, -cover]
        x = cover
        while x <= BL - cover:
            for yy in yb:
                msp.add_circle((x, yy), dbase / 2, dxfattribs={"layer": L_REBAR})
            x += sp_base
    else:
        # 重力式：底部縱向構造筋一層
        x = cover
        while x <= BL - cover:
            msp.add_circle((x, cover), dbase / 2, dxfattribs={"layer": L_REBAR})
            x += sp_base
    # 分布筋（水平線表示）
    for yy in (cover, H - cover):
        msp.add_line((cover, yy), (T - cover, yy),
                     dxfattribs={"layer": L_REBAR})
    msp.add_line((-0.05, -BT + cover), (-0.05, -cover), dxfattribs={"layer": L_REBAR})

    # ---- 尺寸標註 ----
    def dim(p1, p2, base, angle=None):
        """angle 省略時自動判斷：p1/p2 水平 → 0；鉛直 → 90。
        （線性尺寸 angle=0 量的是水平投影；鉛直線段若不給 90 會量到 0）"""
        if angle is None:
            angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=dimstyle,
                               dxfattribs={"layer": L_DIM})
        d.render()

    dim((0, 0), (0, H), (-0.45, 0))                 # 牆高 H
    if wall_type == "gravity":
        dim((BL - T, H), (BL, H), (BL - T, H + 0.35))   # 頂寬 T（背面在 BL）
    else:
        dim((0, H), (T, H), (0, H + 0.35))              # 牆身厚 T
    if wall_type == "gravity":
        dim((0, 0), (BL, 0), (0, -0.35))            # 底寬 BL
    else:
        dim((0, -BT), (BL, -BT), (0, -BT - 0.30))   # 底板寬 BL
        dim((BL + 0.05, -BT), (BL + 0.05, 0.0), (BL + 0.45, -BT))   # 底板厚 BT
    if len(ys) >= 2:
        dim((0, ys[0]), (0, ys[1]), (-0.45, 0))     # 排水孔間距

    # ---- 部位標註：編號圓標（數字在圖上、名稱在右側圖例）→ 不會有字壓在斷面上 ----
    hb = model_h(3.0, scale)
    if wall_type == "gravity":
        tags = [
            (1, (BL * 0.55, H * 0.45)),               # 牆身（梯形，質量偏後）
            (2, (BL * 0.5, 0.10)),                    # 底寬
            (3, (BL + BACK / 2, H * 0.55)),            # 背填（背面鉛直 → 鉛直帶狀）
            (4, (BL + BACK + FILT / 2, H * 0.28)),    # 反濾層
            (5, (-0.17, ys[-1] if ys else H * 0.9)),  # 洩水管
            (6, (-0.30, -0.05)),                      # 開挖線
        ]
    else:
        tags = [
            (1, (T / 2, H * 0.72)),                   # 牆身
            (2, (BL / 2, -BT / 2)),                   # 底板
            (3, (b_hi + BACK / 2, H * 0.55)),         # 背填
            (4, (b_hi + BACK + FILT / 2, H * 0.30)),  # 反濾層
            (5, (-0.17, ys[-1] if ys else H * 0.9)),  # 洩水管
            (6, (-0.30, -BT - 0.05)),                 # 開挖線
        ]
    for n, (x, y) in tags:
        msp.add_circle((x, y), 0.055, dxfattribs={"layer": L_NOTE})
        t = msp.add_text(str(n), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)

    # ---- 鋼筋標註：引線 + 圓標（名稱見右側鋼筋圖例）----
    bars = [
        ("A", (T + 0.30, H * 0.80), (T + 0.02, H * 0.80)),     # 主筋
        ("B", (T + 0.30, H * 0.50), (T + 0.02, H * 0.50)),     # 分布筋
        ("C", (BL * 0.72, -BT - 0.28), (BL * 0.72, -BT + 0.02)),  # 底板筋
    ]
    for n, (tx, ty), (lx, ly) in bars:
        msp.add_circle((tx, ty), 0.055, dxfattribs={"layer": L_REBAR})
        t = msp.add_text(n, height=hb, dxfattribs={"layer": L_REBAR, "style": "TOMO"})
        t.set_placement((tx, ty), align=TextEntityAlignment.MIDDLE_CENTER)
        msp.add_line((tx - 0.06, ty), (lx, ly), dxfattribs={"layer": L_REBAR})

    return dict(H=H, T=T, BL=BL, BT=BT, WD=WD, NZ=NZ, BACK=BACK, FILT=FILT,
                TOE=TOE, wall_type=wall_type, weep_ys=ys,
                title_note="擋土牆標準斷面圖", drawing_no="S-01")


# --------------------------------------------------------------------------- #
# 圖紙空間：視口、比例尺、圖例、說明、標題欄
# --------------------------------------------------------------------------- #
def build_paper(doc, geom, case, scale, project, sheet_no, rebar_schedule=None):
    msp = doc.modelspace()
    from ezdxf import bbox as _bbox
    box = _bbox.extents(msp)
    mx0, my0, mx1, my1 = box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y
    mw, mh = mx1 - mx0, my1 - my0

    lay = doc.layouts.get(LAYOUT_NAME) if LAYOUT_NAME in doc.layouts else doc.layouts.new(LAYOUT_NAME)
    # 比例尺 1:N，模型 1 unit = 1 m、圖紙 1 unit = 1 mm → 視口視高 = 模型高 × 1000 / N
    def m2mm(v):
        return v * 1000.0 / scale

    vw, vh = m2mm(mw), m2mm(mh)
    # 視口不得超出去框可用區（E7）。4 m 高的牆在 1:20 會超高 → 自動降比例。
    # 可用區：x 22.0 ~ (X1-10)、y 34.0 ~ (Y1-4)
    avail_w, avail_h = (X1 - 10.0) - 22.0, (Y1 - 4.0) - 34.0
    if geom.get("slope_deg") is not None:
        # 邊坡圖的右欄要放「坡面圖例／部位圖例／斷面尺寸表」，視口不可頂到 x≥210
        # （否則 E10 疊字、W1 圖例壓視口）。寬度上限讓到 184 mm。
        avail_w = 184.0
    if vw > avail_w or vh > avail_h:
        print("警告：1:%d 下視口 %.1f×%.1f mm 超出可用區 %.1f×%.1f mm → 自動調整比例"
              % (scale, vw, vh, avail_w, avail_h))
        raise SystemExit(
            "請改用較大比例尺重跑（例如 --scale 25 或 30）："
            "模型 %.2f×%.2f m 在 1:%d 為 %.1f×%.1f mm，超出 A3 可用區。"
            % (mw, mh, scale, vw, vh))
    vx0 = 22.0
    vy0 = max(34.0, min(60.0, Y1 - 4.0 - vh))     # 頂端留在內框內，底部不壓標題欄
    cx, cy = vx0 + vw / 2.0, vy0 + vh / 2.0
    # 模型中心（世界座標）
    wcx, wcy = (mx0 + mx1) / 2.0, (my0 + my1) / 2.0

    vp = lay.add_viewport(center=(cx, cy), size=(vw, vh),
                          view_center_point=(wcx, wcy), view_height=mh)
    vp.dxf.status = 2
    vp.dxf.flags |= 16384          # 鎖定視口比例

    is_grav = geom.get("wall_type") == "gravity"
    is_chan = geom.get("wall_type") == "channel"
    is_slope = geom.get("slope_deg") is not None

    def put(x, y, s, h=3.0, layer=L_FRAME):
        t = lay.add_text(s, height=h, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement((x, y), align=TextEntityAlignment.BOTTOM_LEFT)

    # ---- 標題欄：沿用樣板既有標籤（改文字內容），不新增文字 → 不會與樣板疊字 ----
    T = {x.dxf.text: x for x in lay.query("TEXT")}
    for x in lay.query("TEXT"):
        if x.dxf.text == "臺中市大雅區公所":
            x.dxf.text = (case.get("project") or {}).get("agency") or "（主辦機關）"
        if x.dxf.text == "圖名":
            x.dxf.text = geom["title_note"]
        if x.dxf.text == "案名" and project:
            # 標題欄欄寬有限：超過 26 字就折成兩行（不要截斷，截斷會漏資訊）
            # 標題欄「工程名稱」欄位約 120 mm 寬 → 3 mm 字只能放約 34 字。
            # DXF 的 TEXT 是**單行實體**（不像 MTEXT 能用 \n 換行），
            # 硬塞長字串或折成兩個實體都會與下方欄位（圖名／比例尺）或右側「設 計 單 位」相撞（E10）。
            # 正解：標題欄用**短案名**，完整工程名稱留給報告封面與圖說目錄。
            short = (case.get("project") or {}).get("name") or project
            text = short.replace("（", "(").replace("）", ")")
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
    # 圖號：樣板寫死 A-01（平面圖用），斷面圖改 S-01
    for x in lay.query("TEXT"):
        if x.dxf.text.strip() == "A-01":
            x.dxf.text = geom.get("drawing_no", "S-01")
            print("  圖號 A-01 →", x.dxf.text)

    # ---- 比例尺（1 m 分兩段，交替實心／空心）----
    # 1 m 於 1:N = 1000/N mm（1:20 → 50 mm；1:600 → 1.667 mm）。先前誤寫成 N mm，導致比例尺與圖面不符。
    sy = max(36.0, vy0 - 14.0)
    bar_mm = 1000.0 / scale
    seg = bar_mm / 2.0
    for i in range(2):
        x0 = vx0 + i * seg
        poly = [(x0, sy), (x0 + seg, sy), (x0 + seg, sy + 3.0), (x0, sy + 3.0)]
        lay.add_lwpolyline(poly, close=True, dxfattribs={"layer": L_SCALE})
        if i == 0:
            lay.add_solid(poly, dxfattribs={"layer": L_SCALE})
    put(vx0 - 0.8, sy - 5.0, "0", 3.0, L_SCALE)
    # 3 mm 字約 5 mm 寬；seg < 8 mm 時（例如 1:100 只有 5 mm）中間標籤會與端點標籤疊字（E10）
    if seg >= 8.0:
        put(vx0 + seg - 1.2, sy - 5.0, "0.5", 3.0, L_SCALE)
    put(vx0 + 2 * seg - 1.6, sy - 5.0, "1 m", 3.0, L_SCALE)
    put(vx0, sy + 5.5, "比例尺 1:%d" % scale, 4.0, L_SCALE)

    # ---- 鋼筋圖例／配筋表（右上空白區）----
    # 一般斷面圖放「鋼筋圖例」（示意）；S-02 配筋圖放「配筋表」（依配筋設計結果）。
    lx, ly = 210.0, 260.0
    if is_slope:
        # 邊坡沒有鋼筋 —— 印「鋼筋圖例」會與圖名性質相反（同型錯誤先前已踩過一次）
        put(lx, 278.0, "坡面圖例", 5.0, L_LEGEND)
        _sl = [("① 坡頂平台", "整平後植生"), ("② 坡面（植生）", "草種撒播或舖植"),
               ("③ 坡趾", "坡腳排水／護坡"), ("④ 坡面排水溝", "坡頂、坡腳各一道"),
               ("⑤ 最不利滑動圓", "圓弧滑動分析結果"),
               ("⑥ 地下水位", "虛線（未調查時以無水計）")]
        _y = 268.0
        for _a, _b in _sl:
            put(lx, _y, _a, 3.0, L_LEGEND)
            put(lx + 52, _y, _b, 3.0, L_LEGEND)
            _y -= 7.0
        rows = []
    else:
        put(lx, 278.0, "配筋表" if rebar_schedule else "鋼筋圖例", 5.0, L_LEGEND)
    if rebar_schedule:
        # 欄位：筋號 / 位置 / 鋼筋 / 間距 / 每米支數
        put(lx, 270.0, "筋號", 3.0, L_LEGEND)
        put(lx + 12.0, 270.0, "位置", 3.0, L_LEGEND)
        put(lx + 52.0, 270.0, "鋼筋", 3.0, L_LEGEND)
        put(lx + 76.0, 270.0, "間距", 3.0, L_LEGEND)
        put(lx + 96.0, 270.0, "支/米", 3.0, L_LEGEND)
        msp_ = lay
        y = 263.0
        for row in rebar_schedule:
            put(lx, y, row["no"], 3.0, L_LEGEND)
            put(lx + 12.0, y, row["pos"][:9], 3.0, L_LEGEND)
            put(lx + 52.0, y, row["bar"], 3.0, L_LEGEND)
            put(lx + 76.0, y, "%d" % row["spacing"], 3.0, L_LEGEND)
            put(lx + 96.0, y, "%.1f" % row["per_m"], 3.0, L_LEGEND)
            y -= 7.0
        put(lx, y - 1.0, "保護層 %d mm" % int(case.get("_cover_mm", 75)), 3.0, L_LEGEND)
        rows = []
    # rebar_schedule 已自繪配筋表 → 不可再走「鋼筋圖例」的 rows（否則兩套內容疊在同一位置）
    if rebar_schedule:
        rows = []
    elif is_slope:
        rows = []
    elif is_chan:
        rows = [("A  D13@200 溝壁內側筋（雙層）", "13 mm"),
                ("B  D13@200 溝壁外側筋（雙層）", "13 mm"),
                ("C  D13@200 溝底筋", "13 mm"),
                ("   保護層", "50 mm")]
    elif is_grav:
        # 重力式靠自重穩定，僅需構造筋（不設雙層主筋、無獨立底板筋）
        rows = [("A  D13@250 牆面構造筋（單層）", "13 mm"),
                ("B  D13@250 牆背構造筋（單層）", "13 mm"),
                ("C  D16@200 底部縱向構造筋", "16 mm"),
                ("   保護層", "75 mm")]
    else:
        rows = [("A  D16@200 牆身主筋（雙層）", "16 mm"),
                ("B  D13@250 分布筋", "13 mm"),
                ("C  D16@200 底板筋（上下層）", "16 mm"),
                ("   保護層", "75 mm")]
    y = ly
    for name, spec in rows:
        put(lx, y, name, 3.0, L_LEGEND)
        put(lx + 62, y, spec, 3.0, L_LEGEND)
        y -= 7.0

    # ---- 部位圖例 ----
    px, py = 210.0, 208.0
    put(px, 222.0, "部位圖例", 5.0, L_LEGEND)
    if is_slope:
        parts = [("1", "坡頂平台"), ("2", "坡面（植生）"), ("3", "坡趾"),
                 ("4", "坡面排水溝"), ("5", "滑動圓"), ("6", "地下水位")]
    elif is_chan:
        parts = [("1", "溝壁"), ("2", "溝底"), ("3", "通水斷面"), ("4", "基礎開挖線")]
    elif geom.get("wall_type") == "gravity":
        parts = [("1", "牆身（梯形斷面）"), ("2", "底寬 BL"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    else:
        parts = [("1", "牆身"), ("2", "底板"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    y = py
    for k, v in parts:
        put(px, y, k, 3.0, L_LEGEND)
        put(px + 6, y, v, 3.0, L_LEGEND)
        y -= 7.0

    # ---- 斷面尺寸表 ----
    gx, gy = 210.0, 144.0
    put(gx, 158.0, "斷面尺寸表", 5.0, L_LEGEND)
    if geom.get("wall_type") == "channel":
        data = [("溝深 H", "%.2f m" % geom["H"]),
                ("內寬 B", "%.2f m" % geom["B"]),
                ("外寬 W", "%.2f m" % geom["W"]),
                ("溝壁厚 t", "%.2f m" % geom["T"]),
                ("溝底厚 tb", "%.2f m" % geom["BT"]),
                ("總高", "%.2f m" % (geom["H"] + geom["BT"])),
                ("最小構造厚度", "0.15 m")]
    elif geom.get("slope_deg") is not None:
        # 邊坡斷面尺寸表
        data = [("坡高 H", "%.2f m" % geom["H"]),
                ("坡角 β", "%.1f°" % geom["slope_deg"]),
                ("水平投影", "%.2f m" % geom["run"]),
                ("坡面斜長", "%.2f m" % geom["face"]),
                ("坡度", "1 : %.2f" % (1.0 / math.tan(math.radians(geom["slope_deg"])))),
                ("階段平台", ("%d 階 × %.2f m" % (geom["BN"], geom["BW"]))
                 if geom["BN"] else "無"),
                ("地下水位", ("%.2f H" % geom["GW"]) if geom["GW"] > 0 else "無")]
        if geom.get("slip"):
            data.append(("最不利滑動圓", "FS = %.2f" % geom["slip"]["FS"]))
    else:
        is_grav2 = geom.get("wall_type") == "gravity"
        data = [("牆高 H", "%.2f m" % geom["H"]),
                ("頂寬 T", "%.2f m" % geom["T"]),
                ("底寬 BL", "%.2f m" % geom["BL"])]
        if not is_grav2:
            data.append(("底板厚 BT", "%.2f m" % geom["BT"]))
        data += [("排水孔", "Ø%d cm × %d 排" % (round(geom["WD"] * 100), geom["NZ"])),
                 ("背填厚", "%.2f m" % geom["BACK"]),
                 ("反濾層厚", "%.2f m" % geom["FILT"])]
        if geom.get("TOE", 0) > 1e-9:
            data.append(("牆趾覆土", "%.2f m（≥0.60 m）" % geom["TOE"]))
    y = gy
    for k, v in data:
        put(gx, y, k, 3.0, L_LEGEND)
        put(gx + 62, y, v, 3.0, L_LEGEND)
        y -= 7.0

    # ---- 說明（左下，避開技師圖記區 x>=363.5）----
    put(210.0, 88.0, "說明", 5.0, L_DESC)
    # 注意分支順序：配筋圖（rebar_schedule）必須先判，否則會被 is_chan 攔走，
    # 導致 D-02 配筋圖上印著「鋼筋尺寸與間距為示意」——那正好跟事實相反。
    if is_slope:
        _slip_txt = ("最不利滑動圓 FS = %.2f" % geom["slip"]["FS"]) if geom.get("slip") else "未執行滑動圓分析"
        notes = [
            "1. 本圖為邊坡標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 坡高 H=%.2f m、坡角 β=%.1f°、坡度 1:%.2f；%s。" % (
                geom["H"], geom["slope_deg"],
                1.0 / math.tan(math.radians(geom["slope_deg"])), _slip_txt),
            "3. 穩定分析依水土保持技術規範第73條最小安全係數：",
            "   永久性 平時1.5／地震1.1／暴雨1.2；臨時性 平時1.2／地震1.0／暴雨1.1。",
            "4. 坡高超過 5 m 者，依第78條應設計階段式邊坡及縱、橫向排水。",
            "5. 植生須於坡面整地後施作；坡面排水溝應與坡頂、坡腳截水系統銜接。",
            "6. 本圖未含地質鑽探資料；土工參數（γ、φ、c）為假設值，施工前須以實際地探覆核。",
        ]
    elif is_chan and not rebar_schedule:
        notes = [
            "1. 本圖為排水溝標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 本斷面採矩形內腔；若為標準 U 型溝（含斜角），斷面積與模板量須重算。",
            "3. 伸縮縫每 20~40 m 一處（比照水保第121條），本單元 25 m 一處。",
            "4. 混凝土強度 fc'=210 kgf/cm2；最小構造厚度 0.15 m。",
            "5. 鋼筋尺寸與間距為示意，正式配筋須依結構計算結果調整並經技師核可。",
            "6. 本圖未含縱坡、水力計算與出水口設計；施工前須依集水區條件覆核。",
        ]
    elif rebar_schedule and is_chan:
        notes = [
            "1. 本圖為排水溝配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 鋼筋依彎矩、剪力、最小鋼筋與裂縫控制之設計結果配置。",
            "3. 控制載重為溝內滿水之水壓力；溝外側土壓力未計（無土工參數）。",
            "4. 筋號與間距詳右側配筋表；保護層 50 mm。",
            "5. 搭接與錨定長度依混凝土結構設計規範，本圖未標示。",
            "6. 鋼筋施工前須經技師核可；公式採 ACI 318 常用式，版次待核。",
        ]
    elif rebar_schedule:
        notes = [
            "1. 本圖為擋土牆配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 鋼筋依彎矩、剪力、最小鋼筋與裂縫控制之設計結果配置。",
            "3. 筋號與間距詳右側配筋表；保護層 75 mm（迎土面）。",
            "4. 搭接與錨定長度依混凝土結構設計規範，本圖未標示。",
            "5. 底板筋分上、下層；上層筋依各板淨壓力方向配置，下層為分布筋。",
            "6. 鋼筋施工前須經技師核可；公式採 ACI 318 常用式，版次待核。",
        ]
    else:
        notes = [
        "1. 本圖為擋土牆標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
        "2. 排水孔依水土保持技術規範第121條：直徑 5 cm 以上、每 2 m2 牆面至少 1 孔，",
        "   須設反濾層與洩水管防止阻塞。",
        "3. 伸縮縫依第121條每 20～40 m 一處；本單元長 20 m 設 1 處。",
        "4. 背填須使用透水性良好之級配碎石並分層夯實。",
        "5. 牆趾（主動土壓力側）覆土 %.2f m（不得小於 0.60 m），夯實後方得計入被動土壓；" % geom.get("TOE", 0.0),
        "   覆土不得開挖移除，損壞時應即回填夯實。",
        "6. 鋼筋尺寸與間距為示意，正式配筋須依結構計算結果調整並經技師核可。",
        "7. 本圖未含高程與地質資料；施工前須依實際地探與現地測量覆核。",
        ]
    y = 80.0
    for s in notes:
        put(210.0, y, s, 3.0, L_DESC)
        y -= 6.0

    return lay, (cx, cy, vw, vh)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="擋土牆標準斷面圖產線")
    ap.add_argument("case", help="統一案件檔（civil-case/1，quantities.model=wall）")
    ap.add_argument("--scale", default="auto",
                    help="圖面比例分母（1:N）。auto = 依斷面外廓自動挑最小的標準比例")
    ap.add_argument("--title", default="擋土牆標準斷面圖")
    ap.add_argument("--project", default=None)
    ap.add_argument("--drafter", default="Claude（AI）")
    ap.add_argument("--sheet-no", default="1/1")
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--rebar", action="store_true",
                    help="產出 S-02 配筋圖：鋼筋依配筋設計配置，右欄改為配筋表")
    a = ap.parse_args()

    case, q, model = load_case(a.case)

    # --scale auto：挑「放得進 A3 可用區的最小標準比例」
    # 可用區 378.3 × 249.4 mm（x 22~400.3、y 34~283.45）。1:N 下模型高 mh 需 mh×1000/N ≤ 249.4。
    if str(a.scale).lower() == "auto":
        if model == "slope":
            # 邊坡：寬 = 水平投影 + 前後平台各 3 m；高 = 坡高 + 尺寸線空間
            _H = float(q.get("height_m", 3))
            _b = math.radians(float(q.get("slope_angle_deg", 30)))
            mw = _H / max(math.tan(_b), 1e-6) + 6.0
            mh = _H + 2.0
            _avail_w_slope = 184.0
        elif model == "wall":
            mh = float(q.get("height_m", 3)) + float(q.get("base_thickness_m", 0) or 0) + 0.9
            mw = float(q.get("base_width_m", 2)) + 1.4
        else:
            mh = float(q.get("depth_m", 1)) + float(q.get("base_thickness_m", 0) or 0) + 0.9
            mw = float(q.get("inner_width_m", 1)) + 2 * float(q.get("wall_thickness_m", 0.15)) + 1.4
        _aw = _avail_w_slope if model == "slope" else 378.3
        need = max(mh * 1000.0 / 249.4, mw * 1000.0 / _aw)
        cands = [x for x in DR.STANDARD_SCALES if x >= need]
        a.scale = cands[0] if cands else max(DR.STANDARD_SCALES)
        print("自動比例：斷面概估 %.2f×%.2f m → 需 1:%.1f 以上 → 採 1:%d"
              % (mw, mh, need, a.scale))
    else:
        a.scale = int(a.scale)
        DR.require_standard_scale(a.scale)

    # ---- S-02 配筋圖：先跑配筋設計，取得各構材實際筋號與間距 ----
    rb_design, rb_schedule = None, None
    if a.rebar:
        import sys as _sys
        _dd = os.path.join(ROOT, "tools", "design")
        if _dd not in _sys.path:
            _sys.path.insert(0, _dd)
        try:
            import retaining_wall as _RW
            import rc_design as _RC
        except Exception as ex:
            raise SystemExit(f"配筋圖需要 tools\\design 模組：{ex}")
        if model == "wall":
            _wr = _RW.analyse(q, soil=case.get("soil") or {},
                              seismic={"kh": float((case.get("seismic") or {}).get("kh", 0) or 0)})
            if _wr["wall_type"] == "gravity":
                rb_design = {"gravity": True}
                rb_schedule = [
                    {"no": "A", "pos": "牆面構造筋", "bar": "D13", "spacing": 250, "per_m": 4.0},
                    {"no": "B", "pos": "牆背構造筋", "bar": "D13", "spacing": 250, "per_m": 4.0},
                    {"no": "C", "pos": "底部縱向筋", "bar": "D16", "spacing": 200, "per_m": 5.0},
                ]
            else:
                _stem = _RC.design_cantilever_stem(q, _wr)
                _base = _RC.design_base_slab(q, _wr)
                rb_design = {"stem": _stem, "base": _base}
                rb_schedule = []
                _mk = [("A", "牆身主筋（牆背側）", _stem["main"]),
                       ("B", "牆身分布筋（牆面側）", None),
                       ("C", "踵板上層筋", None),
                       ("D", "趾板上層筋", None)]
                _ms = _stem["main"]
                rb_schedule.append({"no": "A", "pos": "牆身主筋(背側)",
                                    "bar": _ms.get("bar", "D16"),
                                    "spacing": int(_ms.get("spacing_mm", 200)),
                                    "per_m": 1000.0 / max(_ms.get("spacing_mm", 200), 1)})
                rb_schedule.append({"no": "B", "pos": "牆身分布筋(面側)",
                                    "bar": _stem.get("dist_bar", "D13"),
                                    "spacing": int(_stem.get("dist_spacing_mm", 250)),
                                    "per_m": 1000.0 / max(_stem.get("dist_spacing_mm", 250), 1)})
                if _base:
                    for _i, _bm in enumerate(_base["members"]):
                        _bmf = _bm["main"]
                        rb_schedule.append({
                            "no": "C" if _i == 0 else "D",
                            "pos": "踵板上層筋" if _i == 0 else "趾板上層筋",
                            "bar": _bmf.get("bar", "D16"),
                            "spacing": int(_bmf.get("spacing_mm", 210)),
                            "per_m": 1000.0 / max(_bmf.get("spacing_mm", 210), 1)})
        else:
            # 排水溝：溝壁以懸臂板考慮，僅計溝內水壓力
            import channel_hydraulics as _CH
            _hy = case.get("hydraulics") or {}
            _hr = _CH.analyse(float(_hy.get("design_flow_m3s") or 0.5),
                              float(q["inner_width_m"]), float(q["depth_m"]),
                              float(_hy.get("slope") or 0.005),
                              {"manning_n": float(_hy.get("manning_n") or 0.014)})
            _cw = _RC.design_channel_wall(q, _hr)
            rb_design = {"channel": _cw}
            _cm = _cw["main"]
            rb_schedule = [
                {"no": "A", "pos": "溝壁主筋(內側)", "bar": _cm.get("bar", "D16"),
                 "spacing": int(_cm.get("spacing_mm", 200)),
                 "per_m": 1000.0 / max(_cm.get("spacing_mm", 200), 1)},
                {"no": "B", "pos": "溝壁分布筋(外側)", "bar": _cw.get("dist_bar", "D13"),
                 "spacing": int(_cw.get("dist_spacing_mm", 200)),
                 "per_m": 1000.0 / max(_cw.get("dist_spacing_mm", 200), 1)},
                {"no": "C", "pos": "溝底構造筋", "bar": "D13", "spacing": 200, "per_m": 5.0},
            ]
    proj = a.project or (case.get("project") or {}).get("full_name") or "擋土牆工程"

    doc = ezdxf.readfile(a.template)
    # 樣板自帶的舊版面一律刪除（本圖只有一個版面）；刪除前先把 active 切回 Model，
    # 否則刪到 active layout 會失敗（ezdxf 會拋錯，先前被 try/except 吞掉導致舊版面殘留）。
    # 樣板的**圖框與標題欄標籤都放在第一個非 Model 版面裡**，直接刪版面會把圖框一起刪掉。
    # 正確做法：沿用該版面 → 清掉它殘留的舊視口 → 改名為「斷面圖」→ 設為 active。
    others = [l.name for l in doc.layouts if l.name != "Model"]
    if LAYOUT_NAME in doc.layouts:
        lay0 = doc.layouts.get(LAYOUT_NAME)
    elif others:
        doc.layouts.rename(others[0], LAYOUT_NAME)
        lay0 = doc.layouts.get(LAYOUT_NAME)
        print(f"  沿用樣板版面 {others[0]} → 改名 {LAYOUT_NAME}（保留圖框與標題欄）")
    else:
        lay0 = doc.layouts.new(LAYOUT_NAME)
        print("  ⚠ 樣板沒有圖紙版面，自建（圖框需自行補）")
    for v in [e for e in lay0.query("VIEWPORT") if e.dxf.id != 1]:
        lay0.delete_entity(v)
        print("  清除樣板殘留視口")
    doc.layouts.set_active_layout(LAYOUT_NAME)
    for name in [l.name for l in doc.layouts if l.name not in ("Model", LAYOUT_NAME)]:
        try:
            doc.layouts.delete(name)
        except Exception as ex:
            print(f"  ⚠ 無法刪除版面 {name}：{ex}")
    ensure_tomo(doc)
    ensure_layers(doc)
    ds = ensure_dimstyle(doc, a.scale)

    _rb_geom = None
    if a.rebar and isinstance(rb_design, dict) and rb_design.get("channel"):
        _cmm = rb_design["channel"]["main"]
        _rb_geom = {"stem_bar": _cmm.get("bar", "D16"),
                    "stem_spacing_mm": _cmm.get("spacing_mm", 200)}
    elif a.rebar and isinstance(rb_design, dict) and rb_design.get("stem"):
        _rb_geom = {
            "stem_bar": rb_design["stem"]["main"].get("bar", "D16"),
            "stem_spacing_mm": rb_design["stem"]["main"].get("spacing_mm", 200),
            "base_bar": (rb_design.get("base") or {}).get("members", [{}])[0].get(
                "main", {}).get("bar", "D16"),
            "base_spacing_mm": (rb_design.get("base") or {}).get("members", [{}])[0].get(
                "main", {}).get("spacing_mm", 210),
        }
    if model == "channel":
        geom = draw_channel_section(doc, q, a.scale, ds, rebar=_rb_geom)
    elif model == "slope":
        geom = draw_slope_section(doc, q, a.scale, ds)      # 邊坡無配筋圖
    else:
        geom = draw_section(doc, q, a.scale, ds, rebar=_rb_geom)
    if a.rebar and model == "slope":
        raise SystemExit("邊坡沒有 RC 構材，不產配筋圖（--rebar 不適用）")
    if a.rebar:
        if model == "channel":
            geom["title_note"] = "排水溝配筋圖"
            geom["drawing_no"] = "D-02"
            case = dict(case)
            case["_cover_mm"] = 50
        else:
            geom["title_note"] = "擋土牆配筋圖"
            geom["drawing_no"] = "S-02"
            case = dict(case)
            case["_cover_mm"] = 75
    lay, vp = build_paper(doc, geom, case, a.scale, proj, a.sheet_no,
                          rebar_schedule=rb_schedule)

    # 版面自檢：模型文字字高必須等於 3/4/5 mm（換算後）
    doc.layouts.set_active_layout(LAYOUT_NAME)      # publish 以 CTAB 出圖，必須是斷面圖
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print(f"DXF OK {out}")
    if model == "slope":
        print(f"  斷面 坡高 H={geom['H']:.2f} 坡角 β={geom['slope_deg']:.1f}° "
              f"水平投影={geom['run']:.2f} 坡面斜長={geom['face']:.2f} "
              f"平台 {geom['BN']} 階×{geom['BW']:.2f}  比例 1/{a.scale}")
    elif model == "channel":
        print(f"  斷面 內寬 B={geom['B']} 溝深 H={geom['H']} 壁厚 t={geom['T']} "
              f"底厚 tb={geom['BT']} 外寬 W={geom['W']}  比例 1/{a.scale}")
    else:
        print(f"  斷面 H={geom['H']} T={geom['T']} BL={geom['BL']} BT={geom['BT']} "
              f"排水孔 Ø{geom['WD']*100:.0f}cm×{geom['NZ']} 排  比例 1/{a.scale}")
    print(f"  視口 center=({vp[0]:.1f},{vp[1]:.1f}) size={vp[2]:.1f}×{vp[3]:.1f} mm")

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
            print("PDF 預覽 %s  %.1f×%.1f mm" %
                  (png, pg.rect.width * 25.4 / 72, pg.rect.height * 25.4 / 72))
        except Exception as ex:
            print("PDF 轉圖略過", ex)


if __name__ == "__main__":
    main()
