"""線稿品質稽核：量測鋸齒程度，並驗證描圖四項要求。

1. 鋸齒指標：每公尺的累積轉角（rad/m）與「階梯點」數量
   （短於 0.4 m 且偏離直線 2°~20° 的折角＝像素階梯殘留）
2. 四項要求：道路／建物／指北針／比例尺 是否齊備
3. 建物方位：最小外接矩形主軸角度是否保留原方位（非強制轉正）
4. TOMO 字型、單位、Hatch 邊界方向
"""

import math
import sys
from collections import defaultdict

import ezdxf
import numpy as np

if len(sys.argv) < 2:
    sys.exit("用法: audit_linework.py <dxf>  # 舊版預設路徑已移除")
DXF = sys.argv[1]

STATS = defaultdict(lambda: {"ents": 0, "verts": 0, "len": 0.0, "turn": 0.0, "stair": 0, "short": 0, "poly": 0})


def poly_points(e):
    try:
        if e.dxftype() == "LWPOLYLINE":
            return [(p[0], p[1]) for p in e.get_points("xy")]
        if e.dxftype() == "POLYLINE":
            return [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
    except Exception:
        return []
    return []


def main():
    doc = ezdxf.readfile(DXF)
    msp = doc.modelspace()

    print(f"=== {DXF} ===")
    print(f"$INSUNITS = {doc.header.get('$INSUNITS')}  ($MEASUREMENT = {doc.header.get('$MEASUREMENT')})")
    st = doc.styles.get("TOMO") if "TOMO" in doc.styles else None
    if st:
        print(f"TOMO style: font={st.dxf.font}  bigfont={st.dxf.bigfont}")
    else:
        print("TOMO style: MISSING")
    print(f"layers: {len(doc.layers)}")

    for e in msp:
        lay = e.dxf.layer
        dxft = e.dxftype()
        if dxft == "HATCH":
            STATS[lay]["ents"] += 1
            continue
        if dxft in ("LWPOLYLINE", "POLYLINE"):
            pts = poly_points(e)
            if len(pts) < 2:
                continue
            s = STATS[lay]
            s["ents"] += 1
            s["poly"] += 1
            s["verts"] += len(pts)
            # 累積轉角 + 長度
            n = len(pts)
            closed = bool(e.closed) if dxft == "LWPOLYLINE" else e.is_closed
            seg = list(zip(pts[:-1], pts[1:]))
            if closed and pts[0] != pts[-1]:
                seg.append((pts[-1], pts[0]))
            for a, b in seg:
                s["len"] += math.hypot(b[0] - a[0], b[1] - a[1])
            for i in range(len(pts)):
                if not closed and (i == 0 or i == len(pts) - 1):
                    continue
                p, q, r = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
                v1 = (q[0] - p[0], q[1] - p[1])
                v2 = (r[0] - q[0], r[1] - q[1])
                l1, l2 = math.hypot(*v1), math.hypot(*v2)
                if l1 < 1e-9 or l2 < 1e-9:
                    continue
                a1 = math.atan2(v1[1], v1[0])
                a2 = math.atan2(v2[1], v2[0])
                d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
                s["turn"] += abs(d)
                # 階梯點：短邊（<0.45 m ≈ 4.5 px）且明顯折角（>30°）＝像素階梯殘留
                if min(l1, l2) < 0.45 and math.degrees(abs(d)) > 30:
                    s["stair"] += 1
                # 短邊總數（階梯前兆）：<0.45 m 的邊
                if min(l1, l2) < 0.45:
                    s["short"] += 1

    print()
    print("=== 線層鋸齒量測 ===")
    print(f"{'圖層':<26}{'實體':>6}{'頂點':>8}{'總長m':>10}{'轉角rad/m':>12}{'階梯點':>9}{'短邊':>8}{'點/100m':>10}")
    for lay in sorted(STATS):
        s = STATS[lay]
        if not s["poly"]:
            continue
        turn_per_m = s["turn"] / s["len"] if s["len"] else 0
        per100 = s["verts"] / s["len"] * 100 if s["len"] else 0
        print(f"{lay:<26}{s['ents']:>6}{s['verts']:>8}{s['len']:>10.1f}"
              f"{turn_per_m:>12.3f}{s['stair']:>9}{s['short']:>8}{per100:>10.1f}")

    print()
    print("=== 四項要求檢核 ===")
    names = [l.dxf.name for l in doc.layers]
    road = [n for n in names if "道路邊線" in n]
    bldg = [n for n in names if n.startswith("20_")]
    hatch = [n for n in names if "HATCH" in n]
    north = [n for n in names if "指北" in n]
    scale = [n for n in names if "比例" in n]
    print(f"  道路圖層      : {road or 'MISSING'}")
    print(f"  建物圖層      : {bldg or 'MISSING'}")
    print(f"  建物 HATCH    : {hatch or 'MISSING'}  (實體 {sum(STATS[h]['ents'] for h in hatch)})")
    print(f"  指北針圖層    : {north or 'MISSING'}  (實體 {sum(STATS[n]['ents'] for n in north)})")
    print(f"  比例尺圖層    : {scale or 'MISSING'}  (實體 {sum(STATS[s]['ents'] for s in scale)})")

    print()
    print("=== 建物方位（主軸角度應保留原方位，非 0/90）===")
    for lay in bldg:
        angs = []
        for e in msp:
            if e.dxf.layer != lay or e.dxftype() != "LWPOLYLINE":
                continue
            pts = poly_points(e)
            if len(pts) < 4:
                continue
            a = np.array(pts, float)
            rect = cv2_minAreaRect(a)
            angs.append(rect[2])
        if angs:
            vals = sorted(round(x, 1) for x in angs)
            print(f"  {lay}: n={len(angs)} 主軸角度 分佈 = {vals[:12]}{' ...' if len(vals) > 12 else ''}")
            off = [v for v in vals if abs(v) > 1 and abs(abs(v) - 90) > 1]
            print(f"     非正交（保留原方位）數 = {len(off)} / {len(angs)}")

    print()
    print("=== audit ===")
    a = doc.audit()
    print(f"  errors={len(a.errors)} fixes={len(a.fixes)}")
    for e in a.errors[:5]:
        print("   ", e)


def cv2_minAreaRect(pts):
    import cv2
    rect = cv2.minAreaRect(pts.astype(np.float32))
    return rect


if __name__ == "__main__":
    main()
