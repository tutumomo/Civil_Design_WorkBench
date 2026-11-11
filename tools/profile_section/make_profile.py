# -*- coding: utf-8 -*-
"""水面線縱斷面圖 L-1（D7）：`channel_profile` 結果 → A3 DXF/DWG/PDF。

縱橫異比例
----------
橫向（樁號）採標題欄比例 H（標準比例尺，E16 檢核此值）；縱向（高程）另採標準比例尺 V，
垂直誇大 k = H/V。模型空間座標為「x＝樁號 m、y＝高程 × k」，視口比例仍是單一 1:H，
因此紙面上 x、y 都依 H 縮放，**縱向自然變成 1:V**。因為 y 被乘了 k，
圖上**不使用會自動量測的線性標註**（量出來會差 k 倍）：高程與樁號一律文字標註真值。

圖上數值來源
------------
全部取自 `channel_profile` 結果：`stations[]`（樁號、溝底高、水面高、水深、流速、Fr、斷面型態）、
`normal_depth_m`、`critical_depth_m`、`checks`；溝深（溝頂線）取自輸入 `channel_depth_m`。
樁號 0 為下游控制端、往上游遞增（引擎標準步法由下游往上游）；高程為相對值（樁號 0 溝底＝0.00）。
出水高不足＝「水深＋出水高 > 溝深」的樁號，逐站標示（出水高取自檢核結果，不另猜）。

用法
----
    .venv/bin/python tools/profile_section/make_profile.py <case.json> --out out/<案名>/L-1.dxf
案件檔 `quantities.model == "channel_profile"`。
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

L_BED = "30_溝底線"
L_TOP = "31_溝頂線"
L_WS = "33_水面線"
L_NORM = "34_正常水深線"
L_CRIT = "35_臨界水深線"
L_DIM = "42_尺寸"
L_NOTE = "43_標註"
LINES = (("top", L_TOP), ("ws", L_WS), ("norm", L_NORM), ("crit", L_CRIT), ("bed", L_BED))

# 紙面邊界（mm）：文字一律 3 mm 字高；模型空間邊界由此換算，供自動比例與視口計算
MARGIN_L = 15.0        # 左側高程刻度文字欄
MARGIN_R = 9.0         # 右端樁號箭頭與標註
MARGIN_T = 12.0        # 「出水高不足」標註
MARGIN_B = 20.0        # 樁號軸線＋樁號＋軸名
TARGET_V_MM = 52.0     # 縱向希望佔的紙面高度
MAX_EXAGGERATION = 30  # 垂直誇大上限


def load_values(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    q = case.get("quantities") or {}
    if q.get("model") != "channel_profile":
        raise SystemExit("本工具只做水面線縱斷面（model 應為 channel_profile，現在是 %r）"
                         % q.get("model"))
    return case, dict(q.get("values") or {})


def run_engine(values):
    import design_api as D

    env = D.run_calculation("channel_profile", values)
    res = env.get("result") if isinstance(env, dict) else None
    if not res or not res.get("stations"):
        raise SystemExit("channel_profile 引擎沒有水面線結果，無法出圖。")
    return res


def channel_depth(values, res):
    v = values.get("channel_depth_m")
    if v in (None, ""):
        v = (res.get("inputs") or {}).get("channel_depth_m")
    if v in (None, ""):
        raise SystemExit("缺少 channel_depth_m（溝深），無法畫溝頂線。")
    return float(v)


def freeboard_of(res):
    """出水高＝檢核「最高水深＋出水高」的值扣最高水深（取自結果，不另猜）。"""
    for c in res.get("checks", []):
        if "出水高" in str(c.get("item", "")):
            return float(c["value"]) - float(res["max_depth_m"])
    return None


def build_lines(res, crest):
    """各線真值序列 (樁號 m, 高程 m) 與出水高不足樁號（純計算，自測直接呼叫）。"""
    st = res["stations"]
    fb = freeboard_of(res)
    lines = {
        "bed": [(s["chainage_m"], s["bed_elevation_m"]) for s in st],
        "top": [(s["chainage_m"], s["bed_elevation_m"] + crest) for s in st],
        "ws": [(s["chainage_m"], s["water_surface_m"]) for s in st],
        "norm": [(s["chainage_m"], s["bed_elevation_m"] + res["normal_depth_m"]) for s in st],
        "crit": [(s["chainage_m"], s["bed_elevation_m"] + res["critical_depth_m"]) for s in st],
    }
    short = [s["chainage_m"] for s in st
             if fb is not None and s["depth_m"] + fb > crest + 1e-9]
    return lines, short, fb


def elevation_range(lines):
    hi = max(y for k in ("top", "ws", "norm", "crit") for _, y in lines[k])
    lo = min(y for k in ("bed",) for _, y in lines[k])
    return lo, hi


def _ktext(k):
    """垂直誇大倍數：整數就寫整數，否則兩位小數（避免 26.6667 這種字串上圖）。"""
    k = float(k)
    return "%d" % round(k) if abs(k - round(k)) < 1e-9 else "%.2f" % k


def tick_step(span, vscale):
    """高程刻度間距：紙面間距 ≥ 8 mm（3 mm 字高才不會擠在一起）。"""
    paper = span * 1000.0 / float(vscale)
    allowed = max(2, int(paper / 8.0))
    for step in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0):
        if span / step <= allowed:
            return step
    return 10.0


def pick_scales(reach, span):
    """H：橫向連同左右標註欄放得進紙面寬 183 mm；V：縱向最接近 TARGET_V_MM、k ≤ 上限的標準比例。"""
    overhead = MARGIN_L + MARGIN_R
    h = next((s for s in DR.STANDARD_SCALES
              if reach * 1000.0 / s <= 183.0 - overhead), None)
    if h is None:
        raise SystemExit("渠長 %.0f m 連 1:%d 都放不進 A3，請縮短渠段或分張出圖。"
                         % (reach, max(DR.STANDARD_SCALES)))
    want = span * 1000.0 / TARGET_V_MM
    cands = [s for s in DR.STANDARD_SCALES if s >= h / float(MAX_EXAGGERATION)]
    v = min(cands, key=lambda s: (abs(s - want), s))
    v = min(v, h)
    if span * 1000.0 / v + MARGIN_T + MARGIN_B > 249.45:
        raise SystemExit("高程變化 %.2f m 在 1:%d 下高 %.0f mm，超出 A3 可繪區；請改比例或分張出圖。"
                         % (span, v, span * 1000.0 / v))
    return h, v


def ensure_layers(doc):
    # 顏色對應 monochrome.ctb 線粗（1~3→0.20、5→0.35、6→0.40、7→0.15、8→0.10 mm）：
    # 水面線最粗、溝底與溝頂次之、正常／臨界水深為輔助細虛線
    for name, color in [(L_BED, 5), (L_TOP, 1), (L_WS, 6), (L_NORM, 8), (L_CRIT, 8),
                        (L_DIM, 7), (L_NOTE, 7), (MWS.L_LEGEND, 7), (MWS.L_SCALE, 7),
                        (MWS.L_DESC, 7)]:
        DR.add_plot_layer(doc, name, color=color)


def short_runs(short, stations):
    """連續（相鄰一站）的出水高不足樁號併成 (起, 迄) 區段；單站則以站距一半為寬。"""
    if not short:
        return []
    chs = [s["chainage_m"] for s in stations]
    gap = (chs[1] - chs[0]) if len(chs) > 1 else 0.0
    runs, a, prev = [], short[0], short[0]
    for ch in short[1:]:
        if ch - prev <= gap + 1e-9:
            prev = ch
            continue
        runs.append((a, prev))
        a = prev = ch
    runs.append((a, prev))
    out = []
    for a, b in runs:
        if abs(b - a) < 1e-9:
            out.append((max(0.0, a - gap / 2.0), a + gap / 2.0))
        else:
            out.append((a, b))
    return out


def draw(doc, res, crest, H, V):
    msp = doc.modelspace()
    k = H / float(V)
    th = DR.model_h(3.0, H)                       # 3 mm 字高（模型單位）
    lines, short, fb = build_lines(res, crest)
    reach = max(x for x, _ in lines["bed"])
    lo, hi = elevation_range(lines)

    dashed = {"linetype": "DASHED"} if "DASHED" in doc.linetypes else {}
    for key, layer in LINES:
        attribs = {"layer": layer}
        if key in ("norm", "crit"):
            attribs.update(dashed)
        msp.add_lwpolyline([(x, y * k) for x, y in lines[key]], dxfattribs=attribs)

    def text(s, p, layer=L_NOTE, align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT):
        t = msp.add_text(s, height=th, dxfattribs={"layer": layer, "style": "TOMO"})
        t.set_placement(p, align=align)

    # 左側高程刻度（真值）：刻度間距以紙面 ≥ 8 mm 為準，起點對齊 step 的整數倍
    step = tick_step(hi - lo, V)
    first = math.ceil(lo / step - 1e-9) * step
    els, el, n = [], first, 0
    while el <= hi + 1e-9:
        els.append(el)
        el += step
        n += 1
    for el in els:
        msp.add_line((-1.2 * th, el * k), (0.0, el * k), dxfattribs={"layer": L_DIM})
        text("%.2f" % el, (-1.6 * th, el * k - th / 2.0), L_DIM,
             ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT)

    # 樁號軸線與刻度（真值）
    y_ax = lo * k - 3.0 * th
    msp.add_line((0.0, y_ax), (reach, y_ax), dxfattribs={"layer": L_DIM})
    for ch in [s["chainage_m"] for s in res["stations"]]:
        msp.add_line((ch, y_ax), (ch, y_ax + 1.0 * th), dxfattribs={"layer": L_DIM})
        text("%g" % ch, (ch, y_ax - 0.8 * th), L_DIM,
             ezdxf.enums.TextEntityAlignment.TOP_CENTER)
    text("樁號 m（0 為下游端）／高程 m", (0.0, y_ax - 5.0 * th), L_DIM)
    # 樁號軸往上游箭頭
    msp.add_line((reach, y_ax), (reach + 2.5 * th, y_ax), dxfattribs={"layer": L_DIM})

    # 出水高不足：連續樁號併成一段，用括線標在溝頂線上方（逐站打標籤會疊字）
    for a, b in short_runs(short, res["stations"]):
        y = max(e for x, e in lines["top"] if a - 1e-9 <= x <= b + 1e-9) * k
        yb = y + 1.6 * th
        msp.add_line((a, yb), (b, yb), dxfattribs={"layer": L_NOTE})
        for x in (a, b):
            msp.add_line((x, y + 0.4 * th), (x, yb), dxfattribs={"layer": L_NOTE})
        text("出水高不足區段", ((a + b) / 2.0 - 4.5 * th, yb + 0.4 * th))
    return {"k": k, "reach": reach, "short": short, "step": step, "ticks": n,
            "runs": short_runs(short, res["stations"])}


def build_blocks(res, crest, H, V, fb, short):
    k = H / float(V)
    rows = [("橫向比例", "1:%d（樁號）" % H),
            ("縱向比例", "1:%d（高程，垂直誇大 %s 倍）" % (V, _ktext(k))),
            ("渠長", "%.1f m" % res["profile_reached"]),
            ("正常水深 yn", "%.3f m" % res["normal_depth_m"]),
            ("臨界水深 yc", "%.3f m" % res["critical_depth_m"]),
            ("流況／坡度類別", "%s／%s" % (res["regime"], res["slope_class"])),
            ("水深 max", "%.3f m" % res["max_depth_m"]),
            ("流速 min／max", "%.2f／%.2f m/s" % (res["min_velocity_m_s"], res["max_velocity_m_s"])),
            ("溝深", "%.2f m" % crest),
            ("出水高不足", "無" if not short else "、".join("%g m" % c for c in short))]
    for c in res.get("checks", []):
        rows.append((str(c["item"])[:14], "%.3f／%.3f %s（%s）" % (
            c["value"], c["limit"], c.get("unit", ""), "OK" if c["ok"] else "NG")))
    legend = [{"title": "圖例（線粗 mm）",
               "rows": [[(0.0, "溝頂線（溝底＋溝深）"), (88.0, "0.20")],
                        [(0.0, "水面線（計算水面）"), (88.0, "0.40")],
                        [(0.0, "正常水深線（溝底＋yn）"), (88.0, "0.10 虛線")],
                        [(0.0, "臨界水深線（溝底＋yc）"), (88.0, "0.10 虛線")],
                        [(0.0, "溝底線"), (88.0, "0.35")]]}]
    return [{"title": "水面線摘要", "rows": [[(0.0, a), (62.0, b)] for a, b in rows]}] + legend


def build_notes(res, H, V, fb):
    k = H / float(V)
    n = ["1. 本圖為排水溝水面線縱斷面圖：橫向（樁號）1:%d、縱向（高程）1:%d，垂直誇大 %s 倍，"
         "圖上比例尺僅代表橫向。" % (H, V, _ktext(k)),
         "2. 圖上不做自動量測尺寸（直接量會差 %s 倍）；高程與樁號皆以文字標註真值。" % _ktext(k),
         "3. 樁號 0 為下游控制端、往上游遞增；高程為相對值（樁號 0 溝底＝0.00），絕對高程由現地測量決定。",
         "4. 水面線為標準步法一維緩變流結果，不處理水躍、束縮、側流入流與彎道二次流；"
         "圖上數值皆取自 channel_profile 結果，%s。" % ("全部檢核通過" if res.get("pass") else "有未通過項目，不得施工")]
    if fb is not None:
        n.append("%d. 出水高採 %.2f m（取自檢核結果）；溝頂線＝溝底＋溝深，未含牆頂護角與超高地。" % (len(n) + 1, fb))
    n += ["%d. 圖面僅供設計檢討，施工前須由技師覆核並併同平面圖、斷面圖核對樁號。" % (len(n) + 1)]
    return n


def _redraw_scale(lay, H, V):
    """重畫比例尺：build_paper 的比例尺以「1 m」為全長，粗比例尺（1:1000）下只有 1 mm、
    刻度文字必然疊字；縱斷面又必須同時標出縱向比例。改用 10 m／格並在標題寫明兩種比例。"""
    ref = next((t for t in lay.query("TEXT")
                if str(t.dxf.text).startswith("比例尺") and "1:" in str(t.dxf.text)), None)
    if ref is None:                                # pragma: no cover - 樣板異常
        return
    vx0, sy = ref.dxf.insert.x, ref.dxf.insert.y - 5.5
    for kind in ("TEXT", "LWPOLYLINE", "SOLID"):
        for e in list(lay.query(kind)):
            if e.dxf.layer == MWS.L_SCALE:
                lay.delete_entity(e)

    def put(x, y, s, h=3.0):
        t = lay.add_text(str(s), height=h, dxfattribs={"layer": MWS.L_SCALE, "style": "TOMO"})
        t.set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

    seg = 10.0 * 1000.0 / H                        # 每格 10 m 的紙面長度（mm）
    for i in range(2):
        x0 = vx0 + i * seg
        poly = [(x0, sy), (x0 + seg, sy), (x0 + seg, sy + 3.0), (x0, sy + 3.0)]
        lay.add_lwpolyline(poly, close=True, dxfattribs={"layer": MWS.L_SCALE})
        if i == 0:
            # 實心格：以兩個三角形填滿（4 點 SOLID 的點序在部分出圖器會畫成 X 交叉）
            lay.add_solid([poly[0], poly[1], poly[2]], dxfattribs={"layer": MWS.L_SCALE})
            lay.add_solid([poly[0], poly[2], poly[3]], dxfattribs={"layer": MWS.L_SCALE})
    put(vx0 - 0.8, sy - 5.0, "0")
    put(vx0 + seg - 2.4, sy - 5.0, "10")
    put(vx0 + 2 * seg - 3.2, sy - 5.0, "20")
    put(vx0, sy + 5.5, "比例尺 橫向 1:%d／縱向 1:%d（垂直誇大 %s 倍）（尺寸單位：m）"
        % (H, V, _ktext(H / float(V))), 4.0)


def main():
    ap = argparse.ArgumentParser(description="水面線縱斷面圖（D7）")
    ap.add_argument("case")
    ap.add_argument("--scale", default="auto", help="橫向比例（標題欄比例）；auto 由渠長決定")
    ap.add_argument("--vscale", default="auto", help="縱向比例；auto 由高程範圍決定")
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
    crest = channel_depth(values, res)
    lines, short, fb = build_lines(res, crest)
    reach = max(x for x, _ in lines["bed"])
    lo, hi = elevation_range(lines)
    h_auto, v_auto = pick_scales(reach, hi - lo)

    H = h_auto if str(a.scale).lower() == "auto" else int(a.scale)
    DR.require_standard_scale(H)
    V = v_auto if str(a.vscale).lower() == "auto" else int(a.vscale)
    DR.require_standard_scale(V)
    if V > H:
        raise SystemExit("縱向 1:%d 不得小於橫向 1:%d（縱斷面必須垂直誇大）。" % (V, H))
    if H / float(V) > MAX_EXAGGERATION + 1e-9:
        raise SystemExit("垂直誇大 %s 倍超過上限 %d 倍，請改分張出圖。"
                         % (_ktext(H / float(V)), MAX_EXAGGERATION))
    th = DR.model_h(3.0, H)
    mw = reach + (MARGIN_L + MARGIN_R) * H / 1000.0
    mh = (hi - lo) * H / float(V) + (MARGIN_T + MARGIN_B) * H / 1000.0
    if mw * 1000.0 / H > 183.0 or mh * 1000.0 / H > 249.45:
        raise SystemExit("1:%d 版面 %.1f×%.1f mm 超出 A3 可繪區（183×249 mm），請改比例或分張。"
                         % (H, mw * 1000.0 / H, mh * 1000.0 / H))
    print("橫向 1:%d／縱向 1:%d（誇大 %s 倍）版面 %.1f×%.1f mm"
          % (H, V, _ktext(H / float(V)), mw * 1000.0 / H, mh * 1000.0 / H))

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
    info = draw(doc, res, crest, H, V)

    no = a.sheet_no or "L-1"
    proj = a.project or (case.get("project") or {}).get("full_name") or "排水溝"
    MBS.build_paper(doc, {}, case, H, proj, no,
                    {"blocks": build_blocks(res, crest, H, V, fb, short),
                     "notes": build_notes(res, H, V, fb)},
                    "水面線縱斷面圖", no, unit=a.unit, drafter=a.drafter)
    _redraw_scale(doc.layouts.get(MBS.LAYOUT_NAME), H, V)
    doc.layouts.set_active_layout(MBS.LAYOUT_NAME)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    DR.tag_plot_style(doc)
    doc.saveas(out)
    print("DXF OK %s" % out)
    print("  渠長 %.0f m、樁號 %d 站、出水高不足 %d 站、高程刻度 %d 格"
          % (reach, len(res["stations"]), len(info["short"]), info["ticks"]))
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
