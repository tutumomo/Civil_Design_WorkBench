"""道路邊線萃取 v2 — 直接追蹤 EMAPX99 灰緣像素（適用鄉道：區塊生長會吞掉整片農地）

作法：
  1. 取 EMAPX99 灰色路緣像素（1 px 線）
  2. 篩出中心線走廊（±14 m）與里程區間內的像素
  3. 以全段偏移直方圖找兩個主峰 → 將像素分群為左、右路緣
  4. 逐里程取各群中位偏移 → 大窗移動平均 → 重建平順邊線
用法：python road_edges.py --model <dxf> --method curb --start-lat ... --end-lat ...
"""
import os, sys, math, json, argparse
import numpy as np, cv2, ezdxf
from PIL import Image
from shapely.geometry import LineString, Point

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geomtools import chaikin_keep_corners, max_deviation

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--out", default=None)
ap.add_argument("--method", default="curb", choices=["curb"])
ap.add_argument("--start-lat", type=float, required=True)
ap.add_argument("--start-lon", type=float, required=True)
ap.add_argument("--end-lat", type=float, required=True)
ap.add_argument("--end-lon", type=float, required=True)
ap.add_argument("--corridor", type=float, default=14.0)
ap.add_argument("--layer", default="10_道路邊線_現況")
A = ap.parse_args()

MD = os.path.dirname(os.path.abspath(A.model))
M = json.load(open(os.path.join(MD, "basemap_meta.json"), encoding="utf-8"))
E0, N0, E1, N1, RES = M["E0"], M["N0"], M["E1"], M["N1"], M["res_m"]
emap = np.asarray(Image.open(os.path.join(MD, "emap_EMAPX99_TWD97.png")).convert("RGB")).astype(int)
H, W = emap.shape[:2]

def m2px(e, n): return int(round((e - E0) / RES)), int(round((N1 - n) / RES))

doc = ezdxf.readfile(A.model); msp = doc.modelspace()
osm = [LineString(list(e.get_points("xy"))) for e in msp.query('LWPOLYLINE[layer=="13_道路中心線_OSM"]')]

def chaikin(pts, iters=2):
    P = list(pts)
    for _ in range(iters):
        Q = [P[0]]
        for i in range(len(P)-1):
            a, b = P[i], P[i+1]
            Q.append((0.75*a[0]+0.25*b[0], 0.75*a[1]+0.25*b[1]))
            Q.append((0.25*a[0]+0.75*b[0], 0.25*a[1]+0.75*b[1]))
        Q.append(P[-1]); P = Q
    return P

from pyproj import Transformer
tf = Transformer.from_crs(4326, 3826, always_xy=True)
P1 = tf.transform(A.start_lon, A.start_lat); P2 = tf.transform(A.end_lon, A.end_lat)
cl0 = min(osm, key=lambda l: max(l.distance(Point(P1)), l.distance(Point(P2))))
cl = LineString(chaikin(cl0.coords, iters=2))
s1, s2 = sorted([cl.project(Point(P1)), cl.project(Point(P2))])
print(f"中心線 {cl.length:.1f} m，里程 {s1:.1f}~{s2:.1f}")

def nrm(s):
    p0 = cl.interpolate(max(0, s-1.5)); p1 = cl.interpolate(min(cl.length, s+1.5))
    tx, ty = p1.x-p0.x, p1.y-p0.y; L = math.hypot(tx, ty) or 1.0
    return -ty/L, tx/L

# 1 灰緣像素
gray = ((np.abs(emap[...,0]-emap[...,1])<=6) & (np.abs(emap[...,1]-emap[...,2])<=6)
        & (emap[...,0]>=160) & (emap[...,0]<=242))
ys, xs = np.nonzero(gray)
E = E0 + (xs + 0.5) * RES
N = N1 - (ys + 0.5) * RES
print(f"灰緣像素 {len(xs)} 個")

# 2 走廊篩選 + 偏移/里程
offs, sts = [], []
for e, n in zip(E, N):
    p = Point(e, n)
    s = cl.project(p)
    if not (s1-12 <= s <= s2+12): continue
    c = cl.interpolate(s); nx, ny = nrm(s)
    o = (e-c.x)*nx + (n-c.y)*ny
    if abs(o) > A.corridor: continue
    offs.append(o); sts.append(s)
offs = np.array(offs); sts = np.array(sts)
print(f"走廊內灰緣像素 {len(offs)} 個（±{A.corridor} m）")

# 3 直方圖找兩個主峰
bins = np.arange(-A.corridor, A.corridor + 0.2, 0.2)
hist, edges_h = np.histogram(offs, bins=bins)
centers = (edges_h[:-1] + edges_h[1:]) / 2
sm = np.convolve(hist, np.ones(5), mode="same")
peaks = []
for i in range(2, len(sm)-2):
    if sm[i] >= sm[i-1] and sm[i] >= sm[i+1] and sm[i] > sm.max()*0.12:
        peaks.append((sm[i], centers[i]))
peaks.sort(reverse=True)
p1 = peaks[0][1]
p2 = None
for c, o in peaks[1:]:
    if abs(o-p1) > 2.5:
        p2 = o; break
if p2 is None: p2 = p1 - 4.0
p1, p2 = min(p1, p2), max(p1, p2)
print(f"路緣主峰偏移：{p1:+.2f} m 與 {p2:+.2f} m（平均路寬 {p2-p1:.2f} m）")

# 4 逐里程分群中位偏移
def side_offsets(peak, stations=None):
    sel = np.abs(offs-peak) <= 2.0
    o, s = offs[sel], sts[sel]
    res = []
    step = 0.5
    if stations is None: stations = np.arange(s1, s2+step, step)
    for sv in stations:
        m = np.abs(s-sv) <= step
        res.append(float(np.median(o[m])) if m.sum() >= 2 else None)
    return list(stations), res

def fill_smooth(vals, win=16):
    idx = [i for i, v in enumerate(vals) if v is not None]
    if not idx: return None
    for i, v in enumerate(vals):
        if v is None: vals[i] = vals[min(idx, key=lambda k: abs(k-i))]
    for _ in range(3):
        sm = []
        for i in range(len(vals)):
            lo, hi = max(0, i-win), min(len(vals), i+win+1)
            sm.append(float(np.mean(vals[lo:hi])))
        vals = sm
    return vals

ss, o1 = side_offsets(p1)
_, o2 = side_offsets(p2, stations=ss)          # 同一組車站，長度必然一致
o1 = fill_smooth(o1); o2 = fill_smooth(o2)
if o1 is None or o2 is None: raise SystemExit("灰緣分群失敗")

# 4b 端點外推：灰緣在起終點附近（路口）常缺漏，以末端 15 m 線性外推補足
def extrapolate(ss, vals, extend_lo, extend_hi, tail=15.0):
    """兩側共用同一組延伸車站，避免長度錯位"""
    n = len(ss); step = ss[1]-ss[0]
    lo_i = max(0, int(np.searchsorted(ss, ss[0]+tail))-1)
    hi_i = min(n-1, int(np.searchsorted(ss, ss[-1]-tail))+1)
    slope_lo = (vals[lo_i]-vals[0])/max(ss[lo_i]-ss[0], 1e-6)
    slope_hi = (vals[-1]-vals[hi_i])/max(ss[-1]-ss[hi_i], 1e-6)
    s_lo = list(np.arange(extend_lo, ss[0], step))
    s_hi = list(np.arange(ss[-1]+step, extend_hi, step))
    v_lo = [vals[0] + slope_lo*(s-ss[0]) for s in s_lo]
    v_hi = [vals[-1] + slope_hi*(s-ss[-1]) for s in s_hi]
    all_s = np.array(list(ss)+s_lo+s_hi)
    all_v = np.array(list(vals)+v_lo+v_hi)
    order = np.argsort(all_s)                     # 依里程排序，避免折返
    return all_s[order], all_v[order]

ss_e, o1 = extrapolate(ss, o1, s1-8, s2+8)
ss_e, o2 = extrapolate(ss, o2, s1-8, s2+8)
ss = ss_e
pts1, pts2 = [], []
for sv, a, b in zip(ss, o1, o2):
    c = cl.interpolate(sv); nx, ny = nrm(sv)
    pts1.append((c.x + nx*a, c.y + ny*a))
    pts2.append((c.x + nx*b, c.y + ny*b))
pts1 = chaikin(pts1, iters=1); pts2 = chaikin(pts2, iters=1)
w = [b-a for a, b in zip(o1, o2)]
print(f"路寬：中位 {np.median(w):.2f} m，min {min(w):.2f}，max {max(w):.2f}；"
      f"邊線長 {LineString(pts1).length:.1f} / {LineString(pts2).length:.1f} m")

for e in list(msp.query(f'*[layer=="{A.layer}"]')): msp.delete_entity(e)
msp.add_lwpolyline([tuple(p) for p in pts1], close=False, dxfattribs={"layer": A.layer})
msp.add_lwpolyline([tuple(p) for p in pts2], close=False, dxfattribs={"layer": A.layer})
out = A.out or A.model
doc.saveas(out)
# 輸出給下游設計腳本使用
dcl_pts = [((a[0]+b[0])/2, (a[1]+b[1])/2) for a, b in zip(pts1, pts2)]
dcl = LineString(dcl_pts)
d_s1, d_s2 = sorted([dcl.project(Point(P1)), dcl.project(Point(P2))])
json.dump({"method": "curb", "peak_offsets": [round(p1,2), round(p2,2)],
           "width_median": round(float(np.median(w)), 2),
           "width_min": round(min(w),2), "width_max": round(max(w),2),
           "osm_offset_center_m": round(float((p1+p2)/2), 2),
           "design_cl": [list(p) for p in dcl_pts],
           "design_s1": d_s1, "design_s2": d_s2,
           "design_len_m": round(abs(d_s2-d_s1), 2),
           "P1": list(P1), "P2": list(P2),
           "edge_a": [list(p) for p in pts1], "edge_b": [list(p) for p in pts2]},
          open(os.path.join(MD, "road_edges_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已更新", out)
