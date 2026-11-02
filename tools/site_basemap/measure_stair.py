"""量測 v2 建物多邊形的真實階梯尺度：邊長分布 + 折角偏差分布。"""

import math
import sys
from collections import Counter

import ezdxf
import numpy as np

DXF = sys.argv[1]
LAYER = sys.argv[2] if len(sys.argv) > 2 else "20_建物"
doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

all_len = []
all_dev = []
turn_hist = Counter()
big = []

for e in msp.query("LWPOLYLINE"):
    if e.dxf.layer != LAYER:
        continue
    pts = [(p[0], p[1]) for p in e.get_points("xy")]
    n = len(pts)
    if n < 3:
        continue
    devs = []
    for i in range(n):
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        la = math.hypot(b[0] - a[0], b[1] - a[1])
        lc = math.hypot(c[0] - b[0], c[1] - b[1])
        all_len += [la, lc]
        vx, vy = c[0] - a[0], c[1] - a[1]
        L = math.hypot(vx, vy)
        dev = 0.0 if L < 1e-9 else abs((b[0] - a[0]) * vy - (b[1] - a[1]) * vx) / L
        devs.append((dev, la, lc))
        all_dev.append(dev)
        if dev < 1.0:
            turn_hist[round(dev, 1)] += 1
    big.append((n, max(d[0] for d in devs), sorted((round(d[0], 2) for d in devs), reverse=True)[:5]))

all_len = np.array(all_len)
all_dev = np.array(all_dev)
print(f"=== {LAYER} @ {DXF.split(chr(92))[-1]} ===")
print(f"多邊形數 {len(big)}  總頂點 {len(all_dev)}")
print(f"邊長 (m): min={all_len.min():.2f} p10={np.percentile(all_len,10):.2f} "
      f"中位={np.median(all_len):.2f} p90={np.percentile(all_len,90):.2f} max={all_len.max():.2f}")
print(f"  <0.45m 的邊: {(all_len<0.45).sum()} / {len(all_len)} ({100*(all_len<0.45).mean():.1f}%)")
print(f"  <0.8m  的邊: {(all_len<0.8).sum()} / {len(all_len)} ({100*(all_len<0.8).mean():.1f}%)")
print(f"偏差 (m): 中位={np.median(all_dev):.2f} p25={np.percentile(all_dev,25):.2f} "
      f"p75={np.percentile(all_dev,75):.2f} max={all_dev.max():.2f}")
for thr in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
    print(f"  偏差 < {thr:.1f} m 的頂點: {(all_dev<thr).sum():4d} / {len(all_dev)}")
print("\n偏差分布 (m: 次數, 只列 <1.0):")
for k in sorted(turn_hist):
    print(f"   {k:.1f} : {turn_hist[k]}")
print("\n頂點最多的 6 棟（頂點數, 最大偏差, 前5大偏差）:")
for row in sorted(big, key=lambda r: -r[0])[:6]:
    print("   ", row)
