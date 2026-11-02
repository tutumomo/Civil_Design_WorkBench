"""離線實驗：建物輪廓去階梯的最佳化方式比較（重用已下載的 emap 影像，不連線）。

比較三種做法，輸出同一視窗的放大圖與客觀指標：
  A 基準        ：現行（smooth_mask(3) + approxPolyDP 4px + regularize）
  B 向量去階梯  ：A + despeckle(tol)
  C 光柵預平滑  ：對 b_mask 先高斯模糊再二值化（消除 0.27 m 原始階梯）+ A
"""
import math
import os
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geomtools import smooth_mask, contours, regularize, despeckle

CACHE = str(Path(__file__).resolve().parents[2] / "_temp" / "exp_smooth")
OUT = str(Path(__file__).resolve().parents[2] / "_temp" / "exp_smooth" / "out")
os.makedirs(OUT, exist_ok=True)
RES = 0.10
E0, N1 = 215039.2690356667, 2667467.575648392
E1, N0 = 215399.2690356667, 2667247.575648392

emap = np.asarray(Image.open(os.path.join(CACHE, "emap_EMAPX99_TWD97.png")).convert("RGB")).astype(int)
near = lambda c, tol=10: np.abs(emap - np.array(c)).sum(2) <= tol
b0 = cv2.morphologyEx(near((233, 226, 233)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

# 取最大的一棟建物作為比較視窗
def biggest(m):
    best = None
    for o, hs in contours(m, 4.0, 800, holes=True):
        xs, ys = o[:, 0], o[:, 1]
        a = (xs.max() - xs.min()) * (ys.max() - ys.min())
        if best is None or a > best[0]:
            best = (a, o, hs)
    return best


def blur_mask(m, sigma):
    if sigma <= 0:
        return m
    f = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma)
    return (f >= 0.5).astype(np.uint8)


def metrics(polys):
    n_v = 0
    stair = 0
    elen = []
    for o, hs in polys:
        pts = o
        n = len(pts)
        n_v += n
        for i in range(n):
            a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
            la = math.hypot(b[0] - a[0], b[1] - a[1])
            lc = math.hypot(c[0] - b[0], c[1] - b[1])
            elen += [la, lc]
            vx, vy = c[0] - a[0], c[1] - a[1]
            L = math.hypot(vx, vy)
            dev = 0.0 if L < 1e-9 else abs((b[0] - a[0]) * vy - (b[1] - a[1]) * vx) / L
            if min(la, lc) < 3.0 and 0.4 < dev < 2.5:
                stair += 1
    el = np.array(elen)
    return n_v, stair, float(np.median(el)), float((el < 0.8).mean())


def px2m(P):
    P = np.asarray(P, float)
    return np.c_[E0 + (P[:, 0] + 0.5) * RES, N1 - (P[:, 1] + 0.5) * RES]


def render(polys, win, out, scale=2):
    x0, y0, x1, y1 = win
    cvx0 = int((x0 - E0) / RES); cvx1 = int((x1 - E0) / RES)
    cvy0 = int((N1 - y1) / RES); cvy1 = int((N1 - y0) / RES)
    img = np.full((cvy1 - cvy0, cvx1 - cvx0, 3), 255, np.uint8)
    for o, hs in polys:
        for ring, col in [(o, (0, 0, 0))] + [(h, (120, 120, 120)) for h in hs]:
            # ring 為公尺 → 像素（左上角=(E0,N1)，每像素 RES 公尺）
            pts = np.array([[int(round((p[0] - E0) / RES - 0.5)) - cvx0,
                             int(round((N1 - p[1]) / RES - 0.5)) - cvy0] for p in ring], np.int32)
            cv2.polylines(img, [pts], True, col, 2)
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    cv2.imencode(".png", img)[1].tofile(out)      # Windows 中文路徑：imwrite 會靜默失敗
    return out


CASES = [
    ("A_baseline", 0.0, 0.0),
    ("B_despeckle_035", 0.0, 0.35),
    ("B_despeckle_070", 0.0, 0.70),
    ("C_blur_1.0", 1.0, 0.0),
    ("C_blur_1.8", 1.8, 0.0),
    ("C_blur_2.6", 2.6, 0.0),
    ("C_blur_1.8_dsp035", 1.8, 0.35),
]

# 先用基準找最大建物
base_polys = []
for o, hs in contours(smooth_mask(b0, 3), 4.0, 800, holes=True):
    base_polys.append((regularize(px2m(o)), [regularize(px2m(h)) for h in hs]))
area, o0, h0 = biggest(b0)
xs, ys = o0[:, 0], o0[:, 1]
# 視窗：該棟建物右半（階梯最明顯處）
wm = (xs.min() + xs.max()) / 2
sel = xs >= wm
wy0, wy1 = ys[sel].min(), ys[sel].max()
wx0, wx1 = xs[sel].min(), xs[sel].max()
WIN = (E0 + wx0 * RES, N1 - wy1 * RES, E0 + wx1 * RES, N1 - wy0 * RES)
print("視窗 (m):", [round(v, 1) for v in WIN])

print(f"\n{'案例':<20}{'頂點':>7}{'階梯點':>8}{'邊長中位':>10}{'短邊%':>9}")
for name, sigma, tol in CASES:
    m = smooth_mask(blur_mask(b0, sigma), 3)
    polys = []
    for o, hs in contours(m, 4.0, 800, holes=True):
        om = px2m(o)
        if tol:
            om = despeckle(om, tol)
        om = regularize(om)
        polys.append((om, [regularize(px2m(h)) for h in hs]))
    n_v, stair, med, shortpct = metrics(polys)
    print(f"{name:<20}{n_v:>7}{stair:>8}{med:>10.2f}{shortpct*100:>8.1f}%")
    render(polys, WIN, os.path.join(OUT, f"{name}.png"))
print("\n圖輸出於", OUT)
