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
sys.path.insert(0, os.path.join(ROOT, "tools", "design"))

import drawing_rules as DR                    # noqa: E402
from drawing_rules import model_h             # noqa: E402
import case_core as CC                       # noqa: E402
import wall_geometry as _WG                   # noqa: E402

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


def unit_spec(unit):
    """圖面尺寸單位（m／cm）。

    **模型空間永遠是公尺**（AGENTS.md §2：公制公尺、$INSUNITS=6），
    這裡只改「圖面標註單位」：以尺寸樣式的線性換算係數（dimlfac）、
    小數位（dimdec）與字尾（dimpost）達成，不動幾何。
    """
    u = str(unit or "m").strip().lower()
    if u in ("cm", "公分"):
        return {"key": "cm", "label": "cm", "factor": 100.0, "dec": 0,
                # DIMPOST 必須含 "<>" 佔位符，否則 ezdxf 與 AutoCAD 都視為
                # 無效格式（DXFValueError: Invalid dimpost string）。
                "post": "<> cm"}
    if u in ("m", "公尺", "meter", "metre"):
        return {"key": "m", "label": "m", "factor": 1.0, "dec": 2,
                "post": "<> m"}
    raise SystemExit("圖面單位只支援 m 或 cm（收到 %s）" % unit)


def fmt_len(value_m, unit="m", dec=None):
    """把公尺值格式化成「圖面單位」的長度字串。

    m  → "3.00 m"（小數 2 位）；cm → "300 cm"（整數）。
    右欄尺寸表、說明文字與配筋表長度欄都走這裡，確保同一張圖上
    不會出現「標註是 cm、右欄卻寫 m」的混用。
    """
    us = unit_spec(unit)
    if us["key"] == "cm":
        return "%d cm" % int(round(float(value_m) * 100.0))
    if dec is None:
        dec = 2
    return "%.*f m" % (dec, float(value_m))


def unit_name(unit="m"):
    """圖面單位的正式名稱（供說明文字用）。"""
    return "公分（cm）" if unit_spec(unit)["key"] == "cm" else "公尺（m）"


_NOTE_LEN_RE = None


def notes_in_unit(notes, unit="m"):
    """把說明文字裡的「數值 + m」統一轉成圖面單位。

    說明文字在各分支硬寫「尺寸單位為公尺（m）」與「H=3.00 m」之類的句子；
    圖面單位改成 cm 時若不跟著改，右欄會與尺寸標註打架。
    這裡以正則統一處理：`<數字> m` → `<數值> cm`（cm 單位時），
    並把「尺寸單位為公尺（m）」換成對應的單位名稱。
    """
    import re
    global _NOTE_LEN_RE
    if _NOTE_LEN_RE is None:
        _NOTE_LEN_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*m(?![\w])")
    un = unit_name(unit)
    out = []
    for n in notes:
        t = n.replace("尺寸單位為公尺（m）", "尺寸單位為%s" % un)
        t = _NOTE_LEN_RE.sub(lambda m: fmt_len(float(m.group(1)), unit), t)
        out.append(t)
    return out


def est_text_w(s, h=3.0):
    """估算文字寬度（mm）：CJK 1.35h、英數 0.9h（比 ezdxf 實測寬度多留約一成安全裕度）。

    與 `tools/a3_sheet/check_delivery.py` 的 `est_width()`（CJK 1.2h／英數 0.8h）
    同源但略保守 —— ezdxf 對 SHX 中文字寬度會低估約兩成，先量寬再排版才不會壓字。
    """
    return sum(1.35 * h if ord(c) >= 0x2E80 else 0.9 * h for c in s)


#: 說明文字最寬可用寬度（mm）。右欄自 x=210 起算，右端 410.3 mm 是圖框內框，
#: x=363.5 mm 起是「技師執業圖記區」必須留白 → 說明單行不得超過 363.5-210-3。
NOTE_MAX_W = 148.0

#: 可作為斷行點的標點（避免把數字或專有名詞切開）
_NOTE_BREAKS = " 、，。；：）」』】"


def wrap_notes(notes, max_w=NOTE_MAX_W, h=3.0):
    """說明文字過寬時自動折行，避免壓到技師圖記區（E9）。

    踩坑紀錄 §AM：邊坡標準斷面圖的第 6 條說明（37 字）實際寬度 162 mm，
    自 x=210 畫到 372 mm，跨進 x≥363.5 的技師圖記區 → check_delivery E9 不通過，
    整案 exit 1。這裡在出圖端就折行（續行以三個空白縮排），不放寬品管規則。
    """
    out = []
    for s in notes:
        if est_text_w(s, h) <= max_w:
            out.append(s)
            continue
        line = ""
        last_break = -1
        for ch in s:
            if est_text_w(line + ch, h) > max_w and line.strip():
                if last_break > 0:
                    head, tail = line[:last_break], line[last_break:]
                    line = head.rstrip()
                else:
                    head, tail = line, ""
                    line = ""
                out.append(line)
                line = "   " + tail + ch
            else:
                line += ch
            if ch in _NOTE_BREAKS or ch == " ":
                last_break = len(line) - 1
        if line.strip():
            out.append(line)
    return out


def ensure_dimstyle(doc, scale, unit="m"):
    name = "TOMO尺寸"
    h = model_h(3.0, scale)                    # 本文 3 mm 換算
    us = unit_spec(unit)
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
    ds.dxf.dimdec = us["dec"]
    # 線性換算係數：模型為公尺，標註要 cm 時乘 100（不動幾何）。
    ds.dxf.dimlfac = us["factor"]
    ds.dxf.dimpost = us["post"]
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


def _draw_advanced_wall_section(doc, q, scale, dimstyle, rebar=None):
    """Typical section for counterfort / anchored / MSE walls.

    Counterfort is shown as a dashed longitudinal stiffener, not as a
    closed concrete polygon: S-01/S-02 are typical sections between
    counterforts, and their closed area must equal ``section_area_m2``.
    """

    msp = doc.modelspace()
    wt = str(q.get("wall_type", "")).strip().lower()
    WD = float(q.get("weep_diameter_m", 0.05))
    NZ = int(q.get("weep_rows", 3) or 3)
    BACK = float(q.get("backfill_thickness_m", 0.3))
    FILT = 0.10
    hs = model_h(3.0, scale)
    hb = model_h(3.0, scale)
    _dash = "DASHED" if "DASHED" in doc.linetypes else "CONTINUOUS"
    g = _WG.parse(dict(q, wall_type=wt))
    pts = list(g.points)
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_CONC})
    hatch_scale = (1.5 * scale / 1000.0) / 3.175
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=max(hatch_scale, 1e-4))
    h.paths.add_polyline_path(pts, is_closed=True)

    def put(x, y, s, layer=L_NOTE):
        t = msp.add_text(s, height=hb, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement((x, y))

    def dim(p1, p2, base, angle=None):
        if angle is None:
            angle = 90 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 0
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                               dimstyle=dimstyle, dxfattribs={"layer": L_DIM})
        d.render()

    def face_x(bot, top, y):
        if abs(top[1] - bot[1]) < 1e-9:
            return top[0]
        return bot[0] + (top[0] - bot[0]) * (y - bot[1]) / (top[1] - bot[1])

    def dots_v(x, y0, y1, spacing, bar="D16"):
        dia = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
               "D22": 0.022, "D25": 0.025, "D29": 0.029, "D32": 0.032}.get(bar, 0.016)
        yy = y0 + 0.10
        while yy <= y1 - 0.08:
            msp.add_circle((x, yy), dia / 2.0, dxfattribs={"layer": L_REBAR})
            yy += spacing / 1000.0

    def dots_h(y, x0, x1, spacing, bar="D16"):
        dia = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
               "D22": 0.022, "D25": 0.025, "D29": 0.029, "D32": 0.032}.get(bar, 0.016)
        xx = x0 + 0.08
        while xx <= x1 - 0.08:
            msp.add_circle((xx, y), dia / 2.0, dxfattribs={"layer": L_REBAR})
            xx += spacing / 1000.0

    kp = g.key_points
    if wt == "counterfort":
        H = float(q["height_m"])
        ts = float(q["stem_thickness_m"])
        BL = float(q["base_width_m"])
        BT = float(q["base_thickness_m"])
        Lt = float(q["toe_length_m"])
        S = float(q["counterfort_spacing_m"])
        tc = float(q["counterfort_thickness_m"])
        ctop = float(q["counterfort_top_width_m"])
        ds = float(q.get("front_soil_depth_m") or 0)
        back_lo = Lt + ts
        backfill = [(back_lo, -BT), (back_lo + BACK, -BT),
                    (back_lo + BACK, H), (back_lo, H)]
        msp.add_lwpolyline(backfill, close=True, dxfattribs={"layer": L_BACK})
        h2 = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
        h2.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
        h2.paths.add_polyline_path(backfill, is_closed=True)
        filt = [(back_lo + BACK, -BT), (back_lo + BACK + FILT, -BT),
                (back_lo + BACK + FILT, H), (back_lo + BACK, H)]
        msp.add_lwpolyline(filt, close=True, dxfattribs={"layer": L_BACK})
        # Counterfort outline (longitudinal stiffener), dashed and not a
        # closed concrete polygon so take-off area stays per-metre typical.
        cf_pts = [(back_lo, 0.0), (BL, 0.0), (back_lo + ctop, H), (back_lo, H),
                  (back_lo, 0.0)]
        msp.add_lwpolyline(cf_pts, close=False,
                           dxfattribs={"layer": L_NOTE, "linetype": _dash})
        put((back_lo + min(ctop * 0.5, (BL - back_lo) * 0.25)), H * 0.55,
            "扶壁（斷面外）")
        # front toe soil
        if ds > 0 and Lt > 0:
            toe = [(0.0, 0.0), (Lt, 0.0), (Lt, ds), (0.0, ds)]
            msp.add_lwpolyline(toe, close=True, dxfattribs={"layer": L_BACK})
            hc = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
            hc.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
            hc.paths.add_polyline_path(toe, is_closed=True)
        ys = [H / (NZ + 1) * (k + 1) for k in range(NZ)]
        for y in ys:
            x = face_x((Lt, 0.0), (Lt, H), y)
            msp.add_circle((x, y), WD / 2, dxfattribs={"layer": L_WEEP})
            msp.add_line((x, y), (x - 0.12, y), dxfattribs={"layer": L_WEEP})
        dim((Lt, 0.0), (Lt, H), (Lt - 0.45, 0.0))
        dim((0.0, -BT), (BL, -BT), (0.0, -BT - 0.35))
        dim((Lt, H), (Lt + ts, H), (Lt, H + 0.35))
        dim((BL + 0.06, -BT), (BL + 0.06, 0.0), (BL + 0.50, -BT))
        dim((back_lo, 0.0), (BL, 0.0), (back_lo, -BT - 0.70))
        sp_stem = int((rebar or {}).get("stem_spacing_mm", 260))
        sp_base = int((rebar or {}).get("base_spacing_mm", 110))
        dots_v(Lt + 0.075, 0.0, H, sp_stem, (rebar or {}).get("stem_bar", "D16"))
        dots_v(back_lo - 0.075, 0.0, H, sp_stem, (rebar or {}).get("stem_bar", "D16"))
        dots_h(-BT + 0.075, 0.0, BL, sp_base, (rebar or {}).get("base_bar", "D16"))
        dots_h(-0.075, 0.0, BL, sp_base, (rebar or {}).get("base_bar", "D16"))
        # 6 必須落在扶壁虛線內，7 才是基礎開挖線；先前 6 誤指開挖線，
        # 與右欄「部位圖例」對不上。
        cf_tag = (back_lo + (BL - back_lo) * 0.45, H * 0.28)
        for n, (x, y) in enumerate(((Lt + ts * 0.5, H * 0.55),
                                    (BL * 0.55, -BT * 0.5),
                                    (back_lo + BACK / 2, H * 0.55),
                                    (back_lo + BACK + FILT / 2, H * 0.30),
                                    (-0.17, ys[-1] if ys else H * 0.9),
                                    cf_tag,
                                    (-0.30, -BT - 0.10)), 1):
            msp.add_circle((x, y), 0.055, dxfattribs={"layer": L_NOTE})
            t = msp.add_text(str(n), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
            t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)
        return dict(H=H, T=ts, BL=BL, BT=BT, WD=WD, NZ=NZ, BACK=BACK, FILT=FILT,
                    TOE=ds, wall_type=wt, weep_ys=ys, top_y=H,
                    title_note="擋土牆標準斷面圖", drawing_no="S-01",
                    counterfort_spacing_m=S, counterfort_thickness_m=tc,
                    toe_length_m=Lt, front_soil_depth_m=ds)

    if wt == "anchored":
        H = float(q["height_m"])
        t = float(q["wall_thickness_m"])
        BL = float(q["base_width_m"])
        BT = float(q["base_thickness_m"])
        hw = H - BT
        ds = float(q.get("front_soil_depth_m") or 0)
        backfill = [(t, -BT), (t + BACK, -BT), (t + BACK, H), (t, H)]
        msp.add_lwpolyline(backfill, close=True, dxfattribs={"layer": L_BACK})
        h2 = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
        h2.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
        h2.paths.add_polyline_path(backfill, is_closed=True)
        # 反濾層要真的畫出來；否則圖例「4 反濾層」的圓標會懸在空白處。
        filt = [(t + BACK, -BT), (t + BACK + FILT, -BT),
                (t + BACK + FILT, H), (t + BACK, H)]
        msp.add_lwpolyline(filt, close=True, dxfattribs={"layer": L_BACK})
        if ds > 0:
            toe = [(-0.5, 0.0), (0.0, 0.0), (0.0, ds), (-0.5, ds)]
            msp.add_lwpolyline(toe, close=True, dxfattribs={"layer": L_BACK})
        ys = [H / (NZ + 1) * (k + 1) for k in range(NZ)]
        for y in ys:
            msp.add_circle((0.0, y), WD / 2, dxfattribs={"layer": L_WEEP})
            msp.add_line((0.0, y), (-0.12, y), dxfattribs={"layer": L_WEEP})
        alpha = math.radians(float(q.get("inclination_deg") or 20))
        for row, z in enumerate(q.get("anchor_depths_m") or [], 1):
            z = float(z)
            Lf = float(q.get("free_length_m") or 6.0)
            Lb = float(q.get("bond_length_m") or 6.0)
            y0 = H - z
            p0 = (t, y0)
            # S-01/S-02 是牆身標準斷面，不是地錨詳圖。只畫前 2 m 並以
            # 折斷線收尾，避免 13 m 地錨把斷面比例逼到 1:200 而失去可讀性。
            Lpreview = min(Lf, 2.0)
            p1 = (t + Lpreview * math.cos(alpha), y0 - Lpreview * math.sin(alpha))
            msp.add_line(p0, p1, dxfattribs={"layer": L_NOTE, "linetype": _dash})
            brk = 0.12
            msp.add_line((p1[0] - brk * math.sin(alpha), p1[1] - brk * math.cos(alpha)),
                         (p1[0] + brk * math.sin(alpha), p1[1] + brk * math.cos(alpha)),
                         dxfattribs={"layer": L_NOTE})
            msp.add_line((t - 0.18, y0 + 0.15), (t - 0.18, y0 - 0.15),
                         dxfattribs={"layer": L_REBAR})
            put(t + 0.15, y0 + 0.12,
                "地錨 %d（L=%.1f m）" % (row, Lf + Lb))
        dim((0.0, 0.0), (0.0, H), (-0.55, 0.0))
        dim((0.0, -BT), (BL, -BT), (0.0, -BT - 0.35))
        dim((0.0, hw), (t, hw), (0.0, hw + 0.35))
        dim((BL + 0.06, -BT), (BL + 0.06, 0.0), (BL + 0.50, -BT))
        sp_wall = int((rebar or {}).get("stem_spacing_mm", 180))
        sp_base = int((rebar or {}).get("base_spacing_mm", 200))
        base_bar = (rebar or {}).get("base_bar", "D16")
        dots_v(0.075, 0.0, hw, sp_wall, (rebar or {}).get("stem_bar", "D16"))
        dots_v(t - 0.075, 0.0, hw, sp_wall, (rebar or {}).get("stem_bar", "D16"))
        dots_h(-BT + 0.075, 0.0, BL, sp_base, base_bar)
        dots_h(-0.075, 0.0, BL, sp_base, base_bar)
        # 6 放在第一排地錨前段，7 才是基礎開挖線。
        _depths = [float(v) for v in (q.get("anchor_depths_m") or [])]
        _z = min(_depths) if _depths else H * 0.15
        _y0 = H - _z
        anchor_tag = (t + 0.95 * math.cos(alpha), _y0 - 0.95 * math.sin(alpha))
        for n, (x, y) in enumerate(((t * 0.5, hw * 0.55),
                                    (BL * 0.55, -BT * 0.5),
                                    (t + BACK / 2, H * 0.55),
                                    (t + BACK + FILT / 2, H * 0.30),
                                    (-0.17, ys[-1] if ys else H * 0.9),
                                    anchor_tag,
                                    (-0.30, -BT - 0.10)), 1):
            msp.add_circle((x, y), 0.055, dxfattribs={"layer": L_NOTE})
            tt = msp.add_text(str(n), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
            tt.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)
        return dict(H=H, T=t, BL=BL, BT=BT, WD=WD, NZ=NZ, BACK=BACK, FILT=FILT,
                    TOE=ds, wall_type=wt, weep_ys=ys, top_y=H,
                    title_note="擋土牆標準斷面圖", drawing_no="S-01",
                    anchor_rows=len(q.get("anchor_depths_m") or []),
                    horizontal_spacing_m=float(q.get("horizontal_spacing_m") or 0),
                    inclination_deg=float(q.get("inclination_deg") or 0))

    # MSE
    H = float(q["height_m"])
    t = float(q.get("face_panel_thickness_m") or 0.20)
    L = float(q["reinforcement_length_m"])
    emb = float(q.get("embedment_m") or 0.0)
    block = str(q.get("facing_type") or "").lower() == "segmented_block"
    soil = [(t, 0.0), (t + L, 0.0), (t + L, H), (t, H)]
    msp.add_lwpolyline(soil, close=True, dxfattribs={"layer": L_BACK})
    hs2 = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
    hs2.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
    hs2.paths.add_polyline_path(soil, is_closed=True)
    ys = []
    y = float(q.get("first_layer_m") or 0.3)
    spacing = float(q.get("vertical_spacing_m") or 0.6)
    while y <= H + 1e-9:
        ys.append(y)
        msp.add_line((t, y), (t + L, y), dxfattribs={"layer": L_REBAR, "linetype": _dash})
        y += spacing
    msp.add_line((-0.8, 0.0), (0.0, 0.0), dxfattribs={"layer": L_NOTE})
    if emb > 0:
        msp.add_line((0.0, -emb), (0.0, 0.0), dxfattribs={"layer": L_NOTE, "linetype": _dash})
        msp.add_line((0.0, -emb), (t + L, -emb), dxfattribs={"layer": L_NOTE, "linetype": _dash})
    for yy in (H / (NZ + 1) * (k + 1) for k in range(NZ)):
        msp.add_circle((0.0, yy), WD / 2, dxfattribs={"layer": L_WEEP})
    if not block:
        sp = int((rebar or {}).get("stem_spacing_mm", 260))
        dots_v(0.065, 0.0, H, sp, (rebar or {}).get("stem_bar", "D13"))
        dots_v(t - 0.065, 0.0, H, sp, (rebar or {}).get("stem_bar", "D13"))
    dim((0.0, 0.0), (0.0, H), (-0.55, 0.0))
    dim((0.0, H), (t, H), (0.0, H + 0.35))
    dim((t, 0.0), (t + L, 0.0), (t, -0.45))
    if emb > 0:
        dim((0.0, -emb), (0.0, 0.0), (-0.75, -emb))
    # 4 必須落在基礎埋入段（地面線以下的面版），先前誤放在加勁區中段，
    # 與右欄「4 基礎埋入段」對不上；6 則移到開挖線左端外側。
    _emb_tag_y = -emb * 0.5 if emb > 0.05 else -0.12
    _exc_tag = (-0.30, (-emb if emb > 0.0 else 0.0) - 0.10)
    for n, (x, yy) in enumerate(((t * 0.5, H * 0.55),
                                  (t + L * 0.45, H * 0.55),
                                  (t + L * 0.18, H * 0.25),
                                  (t + 0.30, _emb_tag_y),
                                  (-0.17, H * 0.85),
                                  _exc_tag), 1):
        msp.add_circle((x, yy), 0.055, dxfattribs={"layer": L_NOTE})
        tt = msp.add_text(str(n), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        tt.set_placement((x, yy), align=TextEntityAlignment.MIDDLE_CENTER)
    return dict(H=H, T=t, BL=L, BT=0.0, WD=WD, NZ=NZ, BACK=0.0, FILT=0.0,
                TOE=0.0, wall_type=wt, weep_ys=[H / (NZ + 1) * (k + 1) for k in range(NZ)],
                top_y=H, title_note="擋土牆標準斷面圖", drawing_no="S-01",
                reinforcement_length_m=L, embedment_m=emb,
                vertical_spacing_m=float(q.get("vertical_spacing_m") or 0.6))


def draw_section(doc, q, scale, dimstyle, rebar=None):
    msp = doc.modelspace()
    wall_type = str(q.get("wall_type", "cantilever")).strip().lower()
    if wall_type in ("counterfort", "anchored", "mse"):
        return _draw_advanced_wall_section(doc, q, scale, dimstyle, rebar=rebar)
    H = float(q["height_m"]); T = float(q["stem_thickness_m"])
    BL = float(q["base_width_m"]); BT = float(q["base_thickness_m"])
    WD = float(q.get("weep_diameter_m", 0.05))
    NZ = int(q.get("weep_rows", 3) or 3)
    BACK = float(q.get("backfill_thickness_m", 0.3))
    FILT = 0.10                                  # 反濾層厚（固定 10 cm）
    # 牆趾（主動土壓力側）覆土深度：設計值 >= 0.60 m，圖上要畫出來，
    # 否則圖面是「素地」、計算卻用了被動土壓，兩者對不起來。
    TOE = float(q.get("toe_soil_depth_m", 0.0) or 0.0)

    # ---- 混凝土斷面：一律取自 wall_geometry（圖面與穩定分析共用同一份幾何）----
    # 重力式＝梯形、懸臂式＝薄牆＋底板、半重力式＝底板＋牆身＋前後坡。
    # 先前這裡自行拼點，半重力式會被畫成懸臂式；改成單一來源後不會再走鐘。
    # 重力式不計牆趾被動土壓（retaining_wall 的 default_include 為 False），
    # 圖上就不該畫出 1.5 m 覆土，否則圖面與穩定分析的假設互相矛盾。
    if wall_type == "gravity":
        TOE = 0.0
    _wg = _WG.parse(dict(q, wall_type=wall_type))
    kp = _wg.key_points
    pts = list(_wg.points)
    top_y = float(_wg.retained_height_m)          # 牆頂（背填頂）高程
    base_y = min(p[1] for p in pts)               # 基礎底（重力式＝0）
    if wall_type == "gravity":
        front_bot, back_bot = (0.0, 0.0), (BL, 0.0)
    else:
        front_bot, back_bot = kp["stem_front_base"], kp["stem_back_base"]
    front_top, back_top = kp["top_front"], kp["top_back"]
    top_width = abs(back_top[0] - front_top[0])

    def _x_at(p_bot, p_top, y):
        """面層在高度 y 的 x（牆面有坡度時線性內插）。"""
        dy = p_top[1] - p_bot[1]
        if abs(dy) < 1e-9:
            return p_top[0]
        return p_bot[0] + (p_top[0] - p_bot[0]) * (y - p_bot[1]) / dy

    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_CONC})
    # 剖面線間距：紙面約 1.5 mm。模型 1 unit = 1 m、ANSI31 圖案基準間距 3.175 unit
    # 先前寫 scale/20（1:20 → 1.0 unit ≈ 3.2 m 間距）→ 3 m 高的牆只畫得出 1 條線。
    hatch_scale = (1.5 * scale / 1000.0) / 3.175
    h = msp.add_hatch(color=256, dxfattribs={"layer": L_HATCH})
    h.set_pattern_fill("ANSI31", color=256, scale=max(hatch_scale, 1e-4))
    h.paths.add_polyline_path(pts, is_closed=True)

    # ---- 背填（透水性材料）+ 反濾層 ----
    # 一律由牆背實際位置起算；重力式的牆背鉛直在 x=BL、半重力式則可能有背坡。
    b_lo, b_hi = back_bot[0], back_top[0]
    back_pts = [(b_lo, 0.0), (b_lo + BACK, 0.0),
                (b_hi + BACK, top_y), (b_hi, top_y)]
    msp.add_lwpolyline(back_pts, close=True, dxfattribs={"layer": L_BACK})
    h2 = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
    h2.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
    h2.paths.add_polyline_path(back_pts, is_closed=True)
    filt = [(b_lo + BACK, 0.0), (b_lo + BACK + FILT, 0.0),
            (b_hi + BACK + FILT, top_y), (b_hi + BACK, top_y)]
    msp.add_lwpolyline(filt, close=True, dxfattribs={"layer": L_BACK})
    # 背填／反濾層分界線（兩者都是 L_BACK 圖層，沒有這條線看不出分界）
    msp.add_line((b_lo + BACK, 0.0), (b_hi + BACK, top_y),
                 dxfattribs={"layer": L_BACK})

    # ---- 原地面線（前後地面）----
    # 有牆趾覆土時，前方地面抬到 y=TOE（覆土面），牆面在該高度的 x 由正面坡度反算。
    gx = 0.6
    if TOE > 1e-9 and wall_type in ("gravity", "semigravity"):
        xf = _x_at(front_bot, front_top, min(TOE, top_y))
        msp.add_line((-gx, TOE), (xf, TOE), dxfattribs={"layer": L_NOTE})
        cover = [(-gx, 0.0), (xf, 0.0), (xf, TOE), (-gx, TOE)]
        msp.add_lwpolyline(cover, close=True, dxfattribs={"layer": L_BACK})
        hc = msp.add_hatch(color=256, dxfattribs={"layer": L_BACK})
        hc.set_pattern_fill("ANSI37", color=256, scale=max(hatch_scale, 1e-4))
        hc.paths.add_polyline_path(cover, is_closed=True)
    else:
        msp.add_line((-gx, 0.0), (0.0, 0.0), dxfattribs={"layer": L_NOTE})
    msp.add_line((b_hi + BACK + FILT, top_y), (b_hi + BACK + FILT + 0.5, top_y),
                 dxfattribs={"layer": L_NOTE})

    # ---- 開挖線（虛線）----
    ex0 = -0.45
    ex1 = max(p[0] for p in pts) + BACK + FILT + 0.2
    msp.add_line((ex0, 0.15), (ex0, base_y - 0.15), dxfattribs={"layer": L_EXC})
    msp.add_line((ex0, base_y - 0.15), (ex1, base_y - 0.15), dxfattribs={"layer": L_EXC})
    msp.add_line((ex1, base_y - 0.15), (ex1, 0.15), dxfattribs={"layer": L_EXC})

    # ---- 排水孔（Ø5cm，等距）----
    ys = [top_y / (NZ + 1) * (k + 1) for k in range(NZ)]
    for y in ys:
        x_face = _x_at(front_bot, front_top, y)
        msp.add_circle((x_face, y), WD / 2, dxfattribs={"layer": L_WEEP})
        msp.add_line((x_face, y), (x_face - 0.12, y),
                     dxfattribs={"layer": L_WEEP})   # 洩水管出水口

    # ---- 背填頂面（回填面）----
    msp.add_line((b_hi + BACK + FILT, top_y), (b_lo + BACK + FILT, 0.0),
                 dxfattribs={"layer": L_BACK})

    # ---- 鋼筋 ----
    # 有配筋設計結果（S-02 配筋圖）→ 依設計的筋號與間距配置；否則用示意值（S-01 標準斷面圖）。
    cover = 0.075
    # 示意預設也要跟牆型一致：重力式／半重力式是名目構造筋 D13@250＋D16@200。
    if wall_type in ("gravity", "semigravity"):
        _RB = {"stem": ("D13", 250), "base": ("D16", 200)}
    else:
        _RB = {"stem": ("D16", 200), "base": ("D16", 210)}
    if rebar:
        _RB["stem"] = (rebar.get("stem_bar", "D16"), int(rebar.get("stem_spacing_mm", 200)))
        _RB["base"] = (rebar.get("base_bar", "D16"), int(rebar.get("base_spacing_mm", 210)))
    _dia = {"D10": 0.010, "D13": 0.013, "D16": 0.016, "D19": 0.019,
            "D22": 0.022, "D25": 0.025}
    d16 = _dia.get(_RB["stem"][0], 0.016)
    dbase = _dia.get(_RB["base"][0], 0.016)
    sp_stem = _RB["stem"][1] / 1000.0
    sp_base = _RB["base"][1] / 1000.0
    # 豎向筋：沿實際面層配置（重力式的牆面是有坡度的，不能固定在 x=T）。
    # 間距 250 mm 是「沿著面層量」，斜面在鉛直方向的投影會小於 250
    # （先前的寫法用 y += 250，斜面實際間距變成 285 mm）。
    # 重力式／半重力式只配露出側單面（與 design_mass_wall_steel 一致）；
    # 懸臂式才是牆面＋牆背雙面。
    _mass_wall = wall_type in ("gravity", "semigravity")

    def _face_levels(p_bot, p_top, spacing):
        dx_, dy_ = p_top[0] - p_bot[0], p_top[1] - p_bot[1]
        L = math.hypot(dx_, dy_)
        if L < 1e-9:
            return []
        out_, s_ = [], cover + 0.05
        while s_ <= L - cover:
            out_.append(p_bot[1] + dy_ * (s_ / L))
            s_ += spacing
        return out_

    for y in _face_levels(front_bot, front_top, sp_stem):
        msp.add_circle((_x_at(front_bot, front_top, y) + cover, y),
                       d16 / 2, dxfattribs={"layer": L_REBAR})
    if not _mass_wall:
        for y in _face_levels(back_bot, back_top, sp_stem):
            msp.add_circle((_x_at(back_bot, back_top, y) - cover, y),
                           d16 / 2, dxfattribs={"layer": L_REBAR})
    if base_y < -1e-9:
        # 懸臂式／半重力式：底板上下兩層縱向筋
        for yy in (base_y + cover, -cover):
            x = cover
            while x <= BL - cover:
                msp.add_circle((x, yy), dbase / 2, dxfattribs={"layer": L_REBAR})
                x += sp_base
    else:
        # 重力式：底部縱向構造筋一層
        x = cover
        while x <= BL - cover:
            msp.add_circle((x, cover), dbase / 2, dxfattribs={"layer": L_REBAR})
            x += sp_base
    # 水平分布筋（沿牆長方向）在此斷面是「圓點」、不是長線；
    # 重力式／半重力式的 D13@250 雙向鋼筋網在斷面上就是同一排 dots，不再另畫線。
    # 懸臂式牆身的分布筋只在受壓面，畫一條線標示其位置。
    if not _mass_wall:
        for yy in (cover, top_y - cover):
            msp.add_line((_x_at(front_bot, front_top, yy) + cover, yy),
                         (_x_at(back_bot, back_top, yy) - cover, yy),
                         dxfattribs={"layer": L_REBAR})

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

    dim((0, 0), (0, top_y), (-0.45, 0))             # 牆身（露出）高
    if wall_type == "gravity":
        dim((BL - T, H), (BL, H), (BL - T, H + 0.35))   # 頂寬 T（背面在 BL）
    elif wall_type == "semigravity":
        dim((0, base_y), (0, top_y), (-0.90, 0))        # 總高 H（含底板）
        dim(front_top, back_top, (front_top[0], top_y + 0.35))   # 頂寬
    else:
        dim((0, H), (T, H), (0, H + 0.35))              # 牆身厚 T
    if wall_type == "gravity":
        dim((0, 0), (BL, 0), (0, -0.35))            # 底寬 BL
    else:
        dim((0, -BT), (BL, -BT), (0, -BT - 0.30))   # 底板寬 BL
        dim((BL + 0.05, -BT), (BL + 0.05, 0.0), (BL + 0.45, -BT))   # 底板厚 BT
    if len(ys) >= 2:
        # 排水孔間距往左再退一階，避免與牆高／總高尺寸線疊在同一條 x
        _wx = -1.20 if wall_type == "semigravity" else -0.85
        dim((0, ys[0]), (0, ys[1]), (_wx, 0))       # 排水孔間距

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
        _xm = (front_bot[0] + back_bot[0]) / 2.0
        tags = [
            (1, (_xm, top_y * 0.55)),                 # 牆身
            (2, (BL / 2, -BT / 2)),                   # 底板
            (3, (b_hi + BACK / 2, top_y * 0.55)),     # 背填
            (4, (b_hi + BACK + FILT / 2, top_y * 0.30)),  # 反濾層
            (5, (-0.17, ys[-1] if ys else top_y * 0.9)),  # 洩水管
            (6, (-0.30, -BT - 0.05)),                 # 開挖線
        ]
    for n, (x, y) in tags:
        msp.add_circle((x, y), 0.055, dxfattribs={"layer": L_NOTE})
        t = msp.add_text(str(n), height=hb, dxfattribs={"layer": L_NOTE, "style": "TOMO"})
        t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)

    # ---- 鋼筋標註：引線 + 圓標（名稱見右側鋼筋圖例）----
    _ya, _yb2 = top_y * 0.80, top_y * 0.50
    if _mass_wall:
        # 單面配筋：A、B 都指向露出側（A 豎向、B 水平），引線往左拉出牆體
        _xa = _x_at(front_bot, front_top, _ya)
        _xb2 = _x_at(front_bot, front_top, _yb2)
        bars = [
            ("A", (_xa - 0.30, _ya), (_xa - 0.02, _ya)),
            ("B", (_xb2 - 0.30, _yb2), (_xb2 - 0.02, _yb2)),
            ("C", (BL * 0.72, base_y - 0.28), (BL * 0.72, base_y + 0.02)),
        ]
    else:
        _xa = _x_at(back_bot, back_top, _ya)
        _xb2 = _x_at(front_bot, front_top, _yb2)
        bars = [
            ("A", (_xa + 0.30, _ya), (_xa + 0.02, _ya)),       # 牆背筋
            ("B", (_xb2 - 0.30, _yb2), (_xb2 - 0.02, _yb2)),   # 牆面筋
            ("C", (BL * 0.72, base_y - 0.28), (BL * 0.72, base_y + 0.02)),
        ]
    for n, (tx, ty), (lx, ly) in bars:
        msp.add_circle((tx, ty), 0.055, dxfattribs={"layer": L_REBAR})
        t = msp.add_text(n, height=hb, dxfattribs={"layer": L_REBAR, "style": "TOMO"})
        t.set_placement((tx, ty), align=TextEntityAlignment.MIDDLE_CENTER)
        msp.add_line((tx - 0.06, ty), (lx, ly), dxfattribs={"layer": L_REBAR})

    return dict(H=H, T=top_width, BL=BL, BT=BT, WD=WD, NZ=NZ, BACK=BACK, FILT=FILT,
                TOE=TOE, wall_type=wall_type, weep_ys=ys, top_y=top_y,
                title_note="擋土牆標準斷面圖", drawing_no="S-01")


# --------------------------------------------------------------------------- #
# 配筋表：把配筋設計結果轉成 S-02 右欄可直接列印的列
# --------------------------------------------------------------------------- #
def _member_flex(member):
    return (member or {}).get("flexure") or {}


def _member_by(slabs, *tokens):
    for member in slabs or []:
        name = str(member.get("member") or "")
        if all(token in name for token in tokens):
            return member
    return None


def _schedule_row(no, pos, bar, spacing=None, per_m=None, *, spacing_text=None,
                  checked=True):
    return {"no": no, "pos": pos, "bar": bar, "spacing": spacing,
            "per_m": per_m, "spacing_text": spacing_text, "checked": checked}


def _build_rebar_schedule(wt, design, q, result):
    """Return printable S-02 rows from the type-dispatched rebar design."""

    rows = []
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        for i, item in enumerate(mass.get("rows") or []):
            is_face = "牆面" in str(item.get("item") or "")
            bar = mass["face_bar"] if is_face else mass["base_bar"]
            spacing = mass["face_spacing_mm"] if is_face else mass["base_spacing_mm"]
            rows.append(_schedule_row(
                "ABC"[i],
                "牆面豎筋" if i == 0 else "牆面橫筋" if i == 1 else "底部縱筋",
                bar, int(round(spacing)), 1000.0 / max(float(spacing), 1.0),
            ))
        return rows

    if wt == "cantilever":
        stem = (design.get("structural") or {}).get("stem") or {}
        main = stem.get("main") or {}
        rows.append(_schedule_row(
            "A", "牆身主筋(背側)", main.get("bar", "D16"),
            int(round(main.get("spacing_mm") or 200)),
            1000.0 / max(float(main.get("spacing_mm") or 200), 1.0),
        ))
        rows.append(_schedule_row(
            "B", "牆身分布筋(面側)", stem.get("dist_bar", "D13"),
            int(round(stem.get("dist_spacing_mm") or 250)),
            1000.0 / max(float(stem.get("dist_spacing_mm") or 250), 1.0),
        ))
        for i, member in enumerate(((design.get("structural") or {}).get("base") or {}).get("members") or []):
            fl = _member_flex(member)
            rows.append(_schedule_row(
                "C" if i == 0 else "D",
                "踵板上層筋" if i == 0 else "趾板上層筋",
                fl.get("bar", "D16"), int(round(fl.get("spacing_mm") or 210)),
                1000.0 / max(float(fl.get("spacing_mm") or 210), 1.0),
            ))
        return rows

    if wt == "counterfort":
        slabs = (result.get("structure") or {}).get("slabs") or []
        specs = [
            ("A", "牆板背豎筋", ("牆板", "鉛直負彎矩")),
            ("B", "牆板面豎筋", ("牆板", "鉛直正彎矩")),
            ("C", "牆板水平筋", ("牆板", "水平負彎矩")),
            ("D", "踵板上下層", ("踵板負彎矩",)),
            ("E", "趾板下層筋", ("趾板",)),
        ]
        for no, pos, tokens in specs:
            member = _member_by(slabs, *tokens)
            fl = _member_flex(member)
            if fl.get("bar") and fl.get("spacing_mm"):
                rows.append(_schedule_row(
                    no, pos, fl["bar"], int(round(fl["spacing_mm"])),
                    1000.0 / max(float(fl["spacing_mm"]), 1.0),
                ))
        cf = (result.get("structure") or {}).get("counterfort") or {}
        main = cf.get("main") or {}
        g = result.get("geometry") or {}
        if main.get("bar") and main.get("count"):
            rows.append(_schedule_row(
                "F", "扶壁拉力筋", main["bar"], None,
                float(main["count"]) / max(float(g.get("S") or 1.0), 1e-9),
                spacing_text="%d支/道" % int(main["count"]), checked=False,
            ))
        stirrup = cf.get("stirrup") or {}
        if stirrup.get("bar") and stirrup.get("spacing_mm"):
            rows.append(_schedule_row(
                "G", "扶壁水平箍筋", stirrup["bar"],
                int(round(stirrup["spacing_mm"])), None,
                spacing_text="%d（兩肢）" % int(round(stirrup["spacing_mm"])),
                checked=False,
            ))
        ties = (result.get("structure") or {}).get("ties") or []
        if ties:
            tie = ties[0]
            rows.append(_schedule_row(
                "H", "扶壁繫筋", tie.get("bar", "D13"),
                int(round(tie.get("spacing_mm") or 300)),
                None, spacing_text="%d（兩肢）" % int(round(tie.get("spacing_mm") or 300)),
                checked=False,
            ))
        return rows

    if wt == "anchored":
        members = (result.get("wall") or {}).get("members") or []
        specs = [
            ("A", "牆面背豎筋", ("鉛直筋", "背面")),
            ("B", "牆面面豎筋", ("鉛直筋", "正面")),
            ("C", "牆面背橫筋", ("水平筋", "背面")),
            ("D", "牆面面橫筋", ("水平筋", "正面")),
        ]
        for no, pos, tokens in specs:
            member = _member_by(members, *tokens)
            fl = _member_flex(member)
            if fl.get("bar") and fl.get("spacing_mm"):
                rows.append(_schedule_row(
                    no, pos, fl["bar"], int(round(fl["spacing_mm"])),
                    1000.0 / max(float(fl["spacing_mm"]), 1.0),
                ))
        base = (design.get("structural") or {}).get("base_rebar") or {}
        if base.get("bar"):
            rows.append(_schedule_row(
                "E", "基腳上下層筋", base["bar"],
                int(round(base.get("spacing_mm") or 200)),
                1000.0 / max(float(base.get("spacing_mm") or 200), 1.0),
            ))
        rows.append(_schedule_row(
            "F", "地錨承壓網", "D13", 200, 5.0,
            spacing_text="200（雙向）", checked=False,
        ))
        return rows

    if wt == "mse":
        st = design.get("structural") or {}
        bar = st.get("bar") or "D13"
        spacing = int(round(st.get("spacing_mm") or 260))
        rows.append(_schedule_row("A", "面版水平筋", bar, spacing,
                                  1000.0 / max(float(spacing), 1.0)))
        rows.append(_schedule_row("B", "面版豎向筋", bar, spacing,
                                  1000.0 / max(float(spacing), 1.0)))
        return rows

    return rows


def _rebar_geometry(wt, design, q, result):
    """Bars/spacings actually drawn as repeated dots in S-02."""

    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        return {"stem_bar": mass["face_bar"],
                "stem_spacing_mm": mass["face_spacing_mm"],
                "base_bar": mass["base_bar"],
                "base_spacing_mm": mass["base_spacing_mm"]}
    if wt == "cantilever":
        stem = (design.get("structural") or {}).get("stem") or {}
        main = stem.get("main") or {}
        members = ((design.get("structural") or {}).get("base") or {}).get("members") or []
        base = _member_flex(members[0]) if members else {}
        return {"stem_bar": main.get("bar", "D16"),
                "stem_spacing_mm": main.get("spacing_mm", 200),
                "base_bar": base.get("bar", "D16"),
                "base_spacing_mm": base.get("spacing_mm", 210)}
    if wt == "counterfort":
        slabs = (result.get("structure") or {}).get("slabs") or []
        wall = [m for m in slabs if "牆板" in str(m.get("member")) and "鉛直" in str(m.get("member"))]
        base = [m for m in slabs if "踵板" in str(m.get("member")) or "趾板" in str(m.get("member"))]
        wall = min(wall, key=lambda m: float(_member_flex(m).get("spacing_mm") or 1e9)) if wall else None
        base = min(base, key=lambda m: float(_member_flex(m).get("spacing_mm") or 1e9)) if base else None
        wf, bf = _member_flex(wall), _member_flex(base)
        return {"stem_bar": wf.get("bar", "D16"),
                "stem_spacing_mm": wf.get("spacing_mm", 240),
                "base_bar": bf.get("bar", "D16"),
                "base_spacing_mm": bf.get("spacing_mm", 180)}
    if wt == "anchored":
        members = [m for m in ((result.get("wall") or {}).get("members") or [])
                   if "鉛直" in str(m.get("member"))]
        wall = min(members, key=lambda m: float(_member_flex(m).get("spacing_mm") or 1e9)) if members else None
        wf = _member_flex(wall)
        base = (design.get("structural") or {}).get("base_rebar") or {}
        return {"stem_bar": wf.get("bar", "D16"),
                "stem_spacing_mm": wf.get("spacing_mm", 180),
                "base_bar": base.get("bar", "D16"),
                "base_spacing_mm": base.get("spacing_mm", 200)}
    if wt == "mse":
        st = design.get("structural") or {}
        return {"stem_bar": st.get("bar", "D13"),
                "stem_spacing_mm": st.get("spacing_mm", 260),
                "base_bar": "D13", "base_spacing_mm": 200}
    return {}


def _auto_wall_extent(q):
    """Estimate the drawn S-01/S-02 model extent before choosing a scale."""

    g = _WG.parse(q)
    xs = [p[0] for p in g.points]
    ys = [p[1] for p in g.points]
    wt = str(q.get("wall_type") or "").strip().lower()
    # 右側留 0.95 m：背填／反濾層之外還有尺寸線與鋼筋標註；
    # 原本 0.50 會讓 3 m 重力式估 3.35 m、實際 bbox 3.79 m，
    # 自動比例誤選 1:20 後才在出圖前被 183 mm 視口上限擋下。
    left, right = 0.90, 0.95
    top, bottom = 0.80, 0.90
    if wt == "counterfort":
        # 背填＋反濾層會突出底板尾端，右側另留圖說空間。
        back = float(q.get("backfill_thickness_m", 0.3))
        right = max(right, back + 0.55)
    if wt == "anchored":
        # The S-01/S-02 typical section shows the first 2 m of anchor and
        # breaks the line; full anchor length belongs to the anchor detail.
        alpha = math.radians(float(q.get("inclination_deg") or 20))
        xs.append(float(q.get("wall_thickness_m", 0.3)) + 2.0 * math.cos(alpha))
        right = max(right, 0.95)
        bottom = max(bottom, 1.10)
    if wt == "mse":
        # 加勁材長度 L 是斷面外廓的一部分，先前只估面版厚度會低估總寬。
        xs.append(float(q.get("face_panel_thickness_m") or 0.20)
                  + float(q["reinforcement_length_m"]))
        right = max(right, 0.55)
        bottom = max(bottom, float(q.get("embedment_m") or 0.0) + 0.80)
    return (max(xs) - min(xs) + left + right,
            max(ys) - min(ys) + top + bottom)


# --------------------------------------------------------------------------- #
# 圖紙空間：視口、比例尺、圖例、說明、標題欄
# --------------------------------------------------------------------------- #
def build_paper(doc, geom, case, scale, project, sheet_no, rebar_schedule=None,
                unit="m"):
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
    # 可用區：x 22.0 ~ 205.0、y 34.0 ~ (Y1-4)
    # 右欄（x >= 210）保留給圖例／配筋表／尺寸表／說明。視口若延伸到右欄，
    # 圖例文字會壓在斷面線條上（S-01 實測發生），因此寬度上限固定為 183 mm。
    avail_w, avail_h = 183.0, (Y1 - 4.0) - 34.0
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
    # 視口框線不可出圖：放到「不列印」圖層，否則 PDF 會多一圈矩形框。
    _vp_layer = "00_視口框"
    if _vp_layer not in doc.layers:
        _l = doc.layers.add(_vp_layer, color=7)
    else:
        _l = doc.layers.get(_vp_layer)
    _l.dxf.plot = 0
    _l.dxf.lineweight = 15          # E17：顏色 7 對應 0.15 mm（即使不列印仍須符表）
    vp.dxf.layer = _vp_layer

    is_grav = geom.get("wall_type") in ("gravity", "semigravity")
    is_chan = geom.get("wall_type") == "channel"
    is_slope = geom.get("slope_deg") is not None
    is_mse = geom.get("wall_type") == "mse"
    # 加勁式只有 RC 面版、沒有底板，保護層依面版取 50 mm；其餘牆型 75 mm。
    _cover_default = 50 if (is_mse or is_chan) else 75

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
    us = unit_spec(unit)
    put(vx0 - 0.8, sy - 5.0, "0", 3.0, L_SCALE)
    # 3 mm 字約 5 mm 寬；seg < 8 mm 時（例如 1:100 只有 5 mm）中間標籤會與端點標籤疊字（E10）
    # 刻度只標數值、單位寫在標題（"尺寸單位：m／cm"），避免「0.5 m」與「1 m」在 1:50 疊字。
    if seg >= 8.0:
        put(vx0 + seg - 1.2, sy - 5.0, "%g" % (us["factor"] / 2.0), 3.0, L_SCALE)
    put(vx0 + 2 * seg - 1.6, sy - 5.0, "%g" % us["factor"], 3.0, L_SCALE)
    put(vx0, sy + 5.5, "比例尺 1:%d（尺寸單位：%s）" % (scale, us["label"]),
        4.0, L_SCALE)

    # ---- 右欄排版：由上而下動態累加 ----
    # 先前各區塊用固定 y（278／222／158／88），只要資料列數一變就互相重疊；
    # 現在統一由 RX／RY_TOP 起算，每個區塊結束後才接下一個。
    # 圖框內頂線實測在 y≈281 mm；原本 278 會讓 5 mm 標題字頂端穿出框線
    # （S-01/S-02 的「鋼筋圖例／配筋表」都被切掉上半）。下移 7 mm。
    RX, RY_TOP = 210.0, 271.0
    ROW_H, TITLE_H, GAP_H = 6.0, 5.0, 6.0
    _cursor = {"y": RY_TOP}

    def _title(text, layer=L_LEGEND, h=TITLE_H):
        put(RX, _cursor["y"], text, h, layer)
        _cursor["y"] -= (h + 4.0)

    def _row(a, b=None, dx=62.0, h=3.0, layer=L_LEGEND):
        put(RX, _cursor["y"], a, h, layer)
        if b is not None:
            put(RX + dx, _cursor["y"], b, h, layer)
        _cursor["y"] -= ROW_H

    def _gap(v=GAP_H):
        _cursor["y"] -= v

    # 右欄尺寸表／說明一律走 fmt_len()，與尺寸標註（dimlfac）同一單位，
    # 避免「圖上標 300 cm、右欄卻寫 3.00 m」或反之。
    def L(v, dec=None):
        return fmt_len(v, unit, dec)

    # 一般斷面圖放「鋼筋圖例」（示意）；S-02 配筋圖放「配筋表」（依配筋設計結果）。
    # 邊坡沒有鋼筋 —— 印「鋼筋圖例」會與圖名性質相反（同型錯誤先前已踩過一次）。
    if is_slope:
        _title("坡面圖例")
        _sl = [("① 坡頂平台", "整平後植生"), ("② 坡面（植生）", "草種撒播或舖植"),
               ("③ 坡趾", "坡腳排水／護坡"), ("④ 坡面排水溝", "坡頂、坡腳各一道"),
               ("⑤ 最不利滑動圓", "圓弧滑動分析結果"),
               ("⑥ 地下水位", "虛線（未調查時以無水計）")]
        for _a, _b in _sl:
            _row(_a, _b, dx=52.0)
    else:
        _title("配筋表" if rebar_schedule else "鋼筋圖例")

    if rebar_schedule:
        # 欄位：筋號 / 位置 / 鋼筋 / 間距 / 每米支數
        put(RX, _cursor["y"], "筋號", 3.0, L_LEGEND)
        put(RX + 10.0, _cursor["y"], "位置", 3.0, L_LEGEND)
        put(RX + 48.0, _cursor["y"], "鋼筋", 3.0, L_LEGEND)
        put(RX + 68.0, _cursor["y"], "間距", 3.0, L_LEGEND)
        put(RX + 88.0, _cursor["y"], "支/米", 3.0, L_LEGEND)
        _cursor["y"] -= ROW_H
        for row in rebar_schedule:
            put(RX, _cursor["y"], row["no"], 3.0, L_LEGEND)
            put(RX + 10.0, _cursor["y"], row["pos"][:8], 3.0, L_LEGEND)
            put(RX + 48.0, _cursor["y"], row["bar"], 3.0, L_LEGEND)
            spacing = row.get("spacing")
            spacing_txt = (str(int(round(spacing))) if spacing
                           else (row.get("spacing_text") or "—"))
            per_m = row.get("per_m")
            put(RX + 68.0, _cursor["y"], spacing_txt, 3.0, L_LEGEND)
            put(RX + 88.0, _cursor["y"], ("%.1f" % per_m) if per_m else "—",
                3.0, L_LEGEND)
            _cursor["y"] -= ROW_H
        _row("保護層", "%d mm" % int(case.get("_cover_mm", _cover_default)),
             dx=14.0, h=3.0)
    else:
        if is_slope:
            rows = []
        elif is_chan:
            rows = [("A  D13@200 溝壁內側筋（雙層）", "13 mm"),
                    ("B  D13@200 溝壁外側筋（雙層）", "13 mm"),
                    ("C  D13@200 溝底筋", "13 mm"),
                    ("   保護層", "50 mm")]
        elif is_grav:
            # 重力式／半重力式靠自重穩定，僅需名目構造筋（非撓曲主筋）
            rows = [("A  D13@250 牆面豎向筋", "13 mm"),
                    ("B  D13@250 牆面水平筋", "13 mm"),
                    ("C  D16@200 底部縱筋", "16 mm"),
                    ("   保護層", "75 mm")]
        elif is_mse:
            # 加勁式只有 RC 面版，沒有底板；先前共用一般牆型的圖例，
            # 會印出根本不存在的「C 底板筋」。圖例改依實際面版配筋。
            _rg = geom.get("rebar_geom") or {}
            _mb = str(_rg.get("stem_bar", "D13"))
            _ms = int(round(float(_rg.get("stem_spacing_mm", 260))))
            rows = [("A  %s@%d 面版水平筋" % (_mb, _ms), "%s mm" % _mb[1:]),
                    ("B  %s@%d 面版豎向筋" % (_mb, _ms), "%s mm" % _mb[1:]),
                    ("   保護層", "50 mm")]
        else:
            # S-01 只畫牆身與底板的代表點；圖例數值取自同一份配筋設計，
            # 以免「圖例 D16@200、配筋表 D16@260」兩張圖各說各話。
            _rg = geom.get("rebar_geom") or {}
            _sb = str(_rg.get("stem_bar", "D16"))
            _ss = int(round(float(_rg.get("stem_spacing_mm", 200))))
            _bb = str(_rg.get("base_bar", "D16"))
            _bs = int(round(float(_rg.get("base_spacing_mm", 210))))
            rows = [("A  %s@%d 牆身豎向筋（雙層）" % (_sb, _ss), "%s mm" % _sb[1:]),
                    ("B  D13@250 分布筋（示意）", "13 mm"),
                    ("C  %s@%d 底板筋（上下層）" % (_bb, _bs), "%s mm" % _bb[1:]),
                    ("   保護層", "75 mm")]
        for name, spec in rows:
            # 右欄間距加大到 70 mm：鋼筋圖例的筋號說明最寬約 63 mm
            # （「A  D16@220 牆身豎向筋（雙層）」），擠在 62 mm 會壓到右側
            # 的「16 mm」直徑欄 → E10 疊字（排水溝／懸臂式／錨定式／扶壁式四案都中）。
            _row(name, spec, dx=70.0)

    # ---- 部位圖例 ----
    _gap(6.0)
    _title("部位圖例")
    if is_slope:
        parts = [("1", "坡頂平台"), ("2", "坡面（植生）"), ("3", "坡趾"),
                 ("4", "坡面排水溝"), ("5", "滑動圓"), ("6", "地下水位")]
    elif is_chan:
        parts = [("1", "溝壁"), ("2", "溝底"), ("3", "通水斷面"), ("4", "基礎開挖線")]
    elif geom.get("wall_type") == "gravity":
        parts = [("1", "牆身（梯形斷面）"), ("2", "底寬 BL"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    elif geom.get("wall_type") == "semigravity":
        parts = [("1", "牆身（厚牆＋前後坡）"), ("2", "底板"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    elif geom.get("wall_type") == "counterfort":
        parts = [("1", "牆板"), ("2", "底板（前趾＋踵板）"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "扶壁（虛線，斷面外）"),
                 ("7", "基礎開挖線")]
    elif geom.get("wall_type") == "anchored":
        parts = [("1", "RC 牆面"), ("2", "基腳"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "地錨（詳錨碇詳圖）"),
                 ("7", "基礎開挖線")]
    elif geom.get("wall_type") == "mse":
        parts = [("1", "RC 預鑄／場鑄面版"), ("2", "加勁區填方"), ("3", "加勁材"),
                 ("4", "基礎埋入段"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    else:
        parts = [("1", "牆身"), ("2", "底板"), ("3", "背填級配碎石"),
                 ("4", "反濾層"), ("5", "洩水管／排水孔"), ("6", "基礎開挖線")]
    for k, v in parts:
        _row(k, v, dx=6.0)

    # ---- 斷面尺寸表 ----
    _gap(6.0)
    _title("斷面尺寸表")
    if geom.get("wall_type") == "channel":
        data = [("溝深 H", L(geom["H"])),
                ("內寬 B", L(geom["B"])),
                ("外寬 W", L(geom["W"])),
                ("溝壁厚 t", L(geom["T"])),
                ("溝底厚 tb", L(geom["BT"])),
                ("總高", L(geom["H"] + geom["BT"])),
                ("最小構造厚度", L(0.15))]
    elif geom.get("slope_deg") is not None:
        # 邊坡斷面尺寸表
        data = [("坡高 H", L(geom["H"])),
                ("坡角 β", "%.1f°" % geom["slope_deg"]),
                ("水平投影", L(geom["run"])),
                ("坡面斜長", L(geom["face"])),
                ("坡度", "1 : %.2f" % (1.0 / math.tan(math.radians(geom["slope_deg"])))),
                ("階段平台", ("%d 階 × %s" % (geom["BN"], L(geom["BW"])))
                 if geom["BN"] else "無"),
                ("地下水位", ("%.2f H" % geom["GW"]) if geom["GW"] > 0 else "無")]
        if geom.get("slip"):
            data.append(("最不利滑動圓", "FS = %.2f" % geom["slip"]["FS"]))
    elif geom.get("wall_type") == "counterfort":
        heel = geom["BL"] - geom.get("toe_length_m", 0.0) - geom["T"]
        data = [("牆板高 H／有效高", "%s／%s" % (
                    L(geom["H"]), L(geom["H"] - geom.get("front_soil_depth_m", 0.0)))),
                ("牆板厚 ts", L(geom["T"])),
                ("底板 B／tb", "%s／%s" % (L(geom["BL"]), L(geom["BT"]))),
                ("前趾／踵板", "%s／%s" % (L(geom.get("toe_length_m", 0.0)), L(heel))),
                ("扶壁 S／tc", "%s／%s" % (
                    geom.get("counterfort_spacing_m", 0),
                    L(geom.get("counterfort_thickness_m", 0))))]
    elif geom.get("wall_type") == "anchored":
        data = [("牆高 H", L(geom["H"])),
                ("有效高", L(geom["H"] - geom.get("TOE", 0.0))),
                ("牆面厚 t", L(geom["T"])),
                ("基腳寬 B", L(geom["BL"])),
                ("基腳厚 tb", L(geom["BT"])),
                ("地錨排數", "%d 排" % geom.get("anchor_rows", 0)),
                ("水平間距", L(geom.get("horizontal_spacing_m", 0))),
                ("地錨俯角", "%.1f°" % geom.get("inclination_deg", 0))]
    elif geom.get("wall_type") == "mse":
        data = [("牆高 H", L(geom["H"])),
                ("埋入深度", L(geom.get("embedment_m", 0))),
                ("有效高", L(geom["H"] - geom.get("embedment_m", 0))),
                ("RC 面版厚 t", L(geom["T"])),
                ("加勁材長 L", L(geom["BL"])),
                ("加勁材層距", L(geom.get("vertical_spacing_m", 0))),
                ("排水孔", "Ø%d cm × %d 排" % (round(geom["WD"] * 100), geom["NZ"]))]
    else:
        is_grav2 = geom.get("wall_type") == "gravity"
        data = [("牆高 H", L(geom["H"])),
                ("頂寬 T", L(geom["T"])),
                ("底寬 BL", L(geom["BL"]))]
        if not is_grav2:
            data.append(("底板厚 BT", L(geom["BT"])))
        data += [("排水孔", "Ø%d cm × %d 排" % (round(geom["WD"] * 100), geom["NZ"])),
                 ("背填厚", L(geom["BACK"])),
                 ("反濾層厚", L(geom["FILT"]))]
        if geom.get("TOE", 0) > 1e-9:
            data.append(("牆趾覆土", "%s（≥%s）" % (L(geom["TOE"]), L(0.60))))
    for k, v in data:
        _row(k, v)

    # ---- 說明（右欄最下方，避開標題欄；不再壓在斷面上）----
    _gap(6.0)
    _title("說明", layer=L_DESC)
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
    elif rebar_schedule and is_grav:
        notes = [
            "1. 本圖為擋土牆配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 本牆為重力式／半重力式，靠自重維持穩定；牆身不設撓曲主筋。",
            "3. 圖示鋼筋為溫度收縮與構造需求之名目鋼筋，非由強度計算控制。",
            "4. 筋號與間距詳右側配筋表；保護層 75 mm（迎土面）。",
            "5. 搭接與錨定長度依混凝土結構設計規範，本圖未標示；止滑榫另依實際設置設計。",
            "6. 鋼筋施工前須經技師核可；名目鋼筋量應與數量表一致。",
        ]
    elif rebar_schedule and geom.get("wall_type") == "counterfort":
        notes = [
            "1. 本圖為扶壁式擋土牆配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 牆板三帶彎矩、踵板連續版、趾板懸臂、扶壁 T 梁與繫筋均依設計結果配置。",
            "3. 扶壁以虛線表示，實體斷面為兩扶壁間之標準斷面；扶壁主筋與箍筋詳配筋表。",
            "4. 筋號與間距詳右側配筋表；保護層 75 mm（迎土面）。",
            "5. 搭接、錨定與彎鉤長度依混凝土結構設計規範；施工詳圖須另繪。",
            "6. 鋼筋量已含 6% 搭接、錨定與損耗，並與數量表、預算書同源。",
        ]
    elif rebar_schedule and geom.get("wall_type") == "anchored":
        notes = [
            "1. 本圖為錨定式擋土牆配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 牆面以各排地錨與基底為支承之連續梁設計，四向筋依正負彎矩配置。",
            "3. 地錨僅畫前 2 m 並以折斷線收尾；自由段、錨碇段與錨頭詳圖應另製。",
            "4. 筋號與間距詳右側配筋表；保護層 75 mm（迎土面）。",
            "5. 基腳採上下層橫向筋與縱向分布筋，已計入鋼筋量；錨頭鋼鈑與螺旋筋另計。",
            "6. 深層穩定與握裹強度未在本圖檢核，須另案分析並以試驗確認。",
        ]
    elif rebar_schedule and geom.get("wall_type") == "mse":
        notes = [
            "1. 本圖為加勁式擋土牆 RC 面版配筋圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. RC 面版以加勁材層距與面版寬度較大者作單向版初步設計。",
            "3. 加勁材以水平虛線表示；材料規格、拉斷與拉出檢核詳計算書。",
            "4. 筋號與間距詳右側配筋表；面版保護層 50 mm。",
            "5. 面版－加勁材連接器、吊裝與溫度收縮細節須依產品型錄另計。",
            "6. 鋼筋量僅計 RC 面版，不含加勁材、連接器與基礎處理。",
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
    elif geom.get("wall_type") == "counterfort":
        notes = [
            "1. 本圖為扶壁式擋土牆標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 扶壁以虛線表示，實體斷面為兩扶壁間之標準斷面。",
            "3. 排水孔依水土保持技術規範第121條配置，須設反濾層與洩水管。",
            "4. 背填須使用透水性良好之級配碎石並分層夯實。",
            "5. 本圖未含扶壁配筋、地質資料與深層穩定；正式設計須另附計算書。",
        ]
    elif geom.get("wall_type") == "anchored":
        notes = [
            "1. 本圖為錨定式擋土牆標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 地錨僅畫前 2 m 並以折斷線收尾；錨碇段長度與詳圖另製。",
            "3. 排水孔依水土保持技術規範第121條配置，須設反濾層與洩水管。",
            "4. 地錨施工前須做握裹試驗，並確認錨碇段位於用地範圍內。",
            "5. 本圖未含地錨詳圖、深層穩定與台階開挖；正式設計須另附計算書。",
        ]
    elif geom.get("wall_type") == "mse":
        notes = [
            "1. 本圖為加勁式擋土牆標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
            "2. 加勁材以水平虛線示意；層距、長度與材料規格依計算書配置。",
            "3. 面版後方須設排水層，避免靜水壓累積。",
            "4. 基礎須整平夯實，埋入段不得任意開挖移除。",
            "5. 本圖未含加勁材連接細部、複合滑動與整體圓弧滑動；須另案檢核。",
        ]
    else:
        notes = [
        "1. 本圖為擋土牆標準斷面圖，尺寸單位為公尺（m），比例 1:%d。" % scale,
        "2. 排水孔依水土保持技術規範第121條：直徑 5 cm 以上、每 2 m2 牆面至少 1 孔，",
        "   須設反濾層與洩水管防止阻塞。",
        "3. 伸縮縫依第121條每 20～40 m 一處；本單元長 20 m 設 1 處。",
        "4. 背填須使用透水性良好之級配碎石並分層夯實。",
        ]
        if geom.get("TOE", 0.0) > 1e-9:
            notes += [
                "5. 牆趾（主動土壓力側）覆土 %.2f m（不得小於 0.60 m），夯實後方得計入被動土壓；"
                % geom["TOE"],
                "   覆土不得開挖移除，損壞時應即回填夯實。",
            ]
        notes += [
            "6. 鋼筋尺寸與間距為示意，正式配筋須依結構計算結果調整並經技師核可。",
            "7. 本圖未含高程與地質資料；施工前須依實際地探與現地測量覆核。",
        ]
    # 說明文字的長度值一併換成圖面單位（m／cm），與尺寸標註、右欄尺寸表一致。
    notes = notes_in_unit(notes, unit)
    notes = wrap_notes(notes)
    # 說明行距 5.2 mm（字高 3.0），確保 7 行仍留在標題欄之上。
    for s in notes:
        put(RX, _cursor["y"], s, 3.0, L_DESC)
        _cursor["y"] -= 5.2
    if _cursor["y"] < 62.0:
        print("警告：右欄說明已接近標題欄（最後一行 y=%.1f mm）" % _cursor["y"])

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
    ap.add_argument("--unit", default="m", choices=["m", "cm"],
                    help="圖面尺寸標註單位（m／cm）；模型空間一律為公尺")
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
            try:
                mw, mh = _auto_wall_extent(q)
            except Exception:
                mh = float(q.get("height_m", 3)) + float(q.get("base_thickness_m", 0) or 0) + 0.9
                mw = float(q.get("base_width_m", 2)) + 1.9
        else:
            mh = float(q.get("depth_m", 1)) + float(q.get("base_thickness_m", 0) or 0) + 0.9
            mw = float(q.get("inner_width_m", 1)) + 2 * float(q.get("wall_thickness_m", 0.15)) + 1.4
        _aw = _avail_w_slope if model == "slope" else 183.0
        need = max(mh * 1000.0 / 249.4, mw * 1000.0 / _aw)
        cands = [x for x in DR.STANDARD_SCALES if x >= need]
        a.scale = cands[0] if cands else max(DR.STANDARD_SCALES)
        print("自動比例：斷面概估 %.2f×%.2f m → 需 1:%.1f 以上 → 採 1:%d"
              % (mw, mh, need, a.scale))
    else:
        a.scale = int(a.scale)
        DR.require_standard_scale(a.scale)

    # ---- S-02 配筋圖：先跑配筋設計，取得各構材實際筋號與間距 ----
    rb_design, rb_schedule, _rb_geom = None, None, None
    # S-01 的「鋼筋圖例」也要跟 S-02 同源。先前 S-01 走示意值，
    # 會出現「S-01 寫 D16@200、S-02 配筋表寫 D16@260」兩張圖各說各話。
    if not a.rebar and model == "wall":
        try:
            import sys as _sys
            _dd = os.path.join(ROOT, "tools", "design")
            if _dd not in _sys.path:
                _sys.path.insert(0, _dd)
            import wall_system as _WS
            _wr0 = _WS.analyse(q, case)
            _rd0 = _WS.rebar_design(q, _wr0)
            _rb_geom = _rebar_geometry(
                _rd0.get("wall_type"), _rd0, q, _wr0)
        except Exception as ex:
            print("警告：S-01 無法取得配筋設計，圖例改用示意值：%s" % ex)
    if a.rebar:
        import sys as _sys
        _dd = os.path.join(ROOT, "tools", "design")
        if _dd not in _sys.path:
            _sys.path.insert(0, _dd)
        try:
            import rc_design as _RC
            import wall_system as _WS
        except Exception as ex:
            raise SystemExit(f"配筋圖需要 tools\\design 模組：{ex}")
        if model == "wall":
            _wr = _WS.analyse(q, case)
            rb_design = _WS.rebar_design(q, _wr)
            rb_schedule = _build_rebar_schedule(
                rb_design.get("wall_type"), rb_design, q, _wr)
            if not rb_schedule:
                raise SystemExit("配筋表為空：wall_type=%s 沒有可列印的鋼筋列。"
                                 % rb_design.get("wall_type"))
            _rb_geom = _rebar_geometry(
                rb_design.get("wall_type"), rb_design, q, _wr)
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
            _rb_geom = {"stem_bar": _cm.get("bar", "D16"),
                        "stem_spacing_mm": _cm.get("spacing_mm", 200)}
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
    ds = ensure_dimstyle(doc, a.scale, a.unit)

    if model == "channel":
        geom = draw_channel_section(doc, q, a.scale, ds, rebar=_rb_geom)
    elif model == "slope":
        geom = draw_slope_section(doc, q, a.scale, ds)      # 邊坡無配筋圖
    else:
        geom = draw_section(doc, q, a.scale, ds, rebar=_rb_geom)
    if _rb_geom:
        # 讓 S-01 的鋼筋圖例與 S-02 共用同一份設計值，不再各自寫死。
        geom["rebar_geom"] = dict(_rb_geom)
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
            case["_cover_mm"] = 50 if q.get("wall_type") == "mse" else 75
    lay, vp = build_paper(doc, geom, case, a.scale, proj, a.sheet_no,
                          rebar_schedule=rb_schedule, unit=a.unit)

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
