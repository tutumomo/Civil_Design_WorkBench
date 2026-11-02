"""道路邊線萃取（EMAPX99 灰緣法，EXP-C2 / 2026-10-26 Gemini 實作 + MiniMax Code 通用化）

原理（2D 區塊生長，非逐斷面掃描 → 線條天生平順）：
  1. 灰緣：EMAPX99 之灰色路緣線（R≈G≈B 且 160~242）
  2. 封口：形態學閉運算補上被地號文字／等高線切斷的 1 px 灰緣
  3. 水密阻隔：灰緣＋建物＋水體聯集作為牆，剩餘白區以 4-連通分區
  4. 種子：以 OSM 道路中心線沿線取樣，標記面積 15~8000 m² 的白區為道路
  5. 再生長：把種子區膨脹回灰緣中線，得到完整道路面
  6. 等值線：取道路面外框 → 去圖框邊 → despeckle → 保角 Chaikin 平滑

用法：
  python road_edges.py --model <模型空間 DXF> [--start-lat --start-lon --end-lat --end-lon]
                        [--replace-layer 10_道路邊線_現況] [--out <輸出 DXF>]
"""
import os, sys, math, json, argparse
import numpy as np, cv2, ezdxf
from PIL import Image
from shapely.geometry import LineString, Polygon, box

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geomtools import smooth_mask, contours, despeckle, chaikin_keep_corners, max_deviation

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--out", default=None)
ap.add_argument("--replace-layer", default="10_道路邊線_現況")
ap.add_argument("--start-lat", type=float, default=None)
ap.add_argument("--start-lon", type=float, default=None)
ap.add_argument("--end-lat", type=float, default=None)
ap.add_argument("--end-lon", type=float, default=None)
ap.add_argument("--meta", default=None)
A = ap.parse_args()

MD = os.path.dirname(os.path.abspath(A.model))
M = json.load(open(A.meta or os.path.join(MD, "basemap_meta.json"), encoding="utf-8"))
E0, N0, E1, N1, RES = M["E0"], M["N0"], M["E1"], M["N1"], M["res_m"]

emap = np.asarray(Image.open(os.path.join(MD, "emap_EMAPX99_TWD97.png")).convert("RGB")).astype(int)
H, W = emap.shape[:2]
def m2px(e, n): return int(round((e - E0) / RES)), int(round((N1 - n) / RES))
def px2m(P):
    P = np.asarray(P, float)
    return np.c_[E0 + (P[:, 0] + 0.5) * RES, N1 - (P[:, 1] + 0.5) * RES]

doc = ezdxf.readfile(A.model); msp = doc.modelspace()
osm_lines = [LineString(list(e.get_points("xy"))) for e in msp.query('LWPOLYLINE[layer=="13_道路中心線_OSM"]')]

# 1~2 灰緣與封口
gray_curb = ((np.abs(emap[..., 0] - emap[..., 1]) <= 6) & (np.abs(emap[..., 1] - emap[..., 2]) <= 6)
              & (emap[..., 0] >= 160) & (emap[..., 0] <= 242)).astype(np.uint8)
b_mask = (np.abs(emap - np.array([233, 226, 233])).sum(2) <= 12).astype(np.uint8)
w_mask = (np.abs(emap - np.array([149, 213, 251])).sum(2) <= 15).astype(np.uint8)
curb_closed = cv2.morphologyEx(gray_curb, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
wall = cv2.dilate(((curb_closed > 0) | (b_mask > 0) | (w_mask > 0)).astype(np.uint8), np.ones((2, 2), np.uint8))
white = (wall == 0).astype(np.uint8)
n_cc, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)

# 4 種子：OSM 中心線沿線
seed = set()
for ln in osm_lines:
    for s in np.arange(0, ln.length, 1.0):
        p = ln.interpolate(s); x, y = m2px(p.x, p.y)
        for dy in (-4, 0, 4):
            for dx in (-4, 0, 4):
                yy, xx = y + dy, x + dx
                if 0 <= xx < W and 0 <= yy < H:
                    lb = int(labels[yy, xx])
                    if lb > 0:
                        a = stats[lb, cv2.CC_STAT_AREA] * RES * RES
                        if 15.0 <= a <= 8000.0: seed.add(lb)

# 4b 種子：指定起終點附近（含路口支線）
if A.start_lat is not None:
    from pyproj import Transformer
    tf = Transformer.from_crs(4326, 3826, always_xy=True)
    P1 = tf.transform(A.start_lon, A.start_lat); P2 = tf.transform(A.end_lon, A.end_lat)
    for (pe, pn) in (P1, P2):
        for de in ((-10, -10), (-10, 10), (10, -10), (10, 10), (0, 0)):
            x, y = m2px(pe + de[0], pn + de[1])
            if 0 <= x < W and 0 <= y < H:
                lb = int(labels[y, x])
                if lb > 0:
                    a = stats[lb, cv2.CC_STAT_AREA] * RES * RES
                    if 15.0 <= a <= 8000.0: seed.add(lb)
print(f"灰緣水密區 {n_cc-1} 個，種子命中 {len(seed)} 個")

# 5 再生長
rm = np.isin(labels, list(seed)).astype(np.uint8)
rm = cv2.dilate(rm, np.ones((3, 3), np.uint8))
rm = cv2.morphologyEx(rm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
rm = smooth_mask(rm, 7)

# 6 等值線 → 平滑
FR = box(E0, N0, E1, N1).exterior.buffer(0.6)
raw, edges = [], []
for o, hs in contours(rm, 15.0, 2000, holes=True):
    for ring in [o] + hs:
        if Polygon(px2m(ring)).area < 20.0: continue
        g = LineString(np.vstack([px2m(ring), px2m(ring)[:1]])).difference(FR)
        for s in getattr(g, "geoms", [g]):
            if not s.is_empty and s.length > 10.0:
                raw.append(despeckle(np.array(s.coords), closed=False))
for P in raw: edges.append(chaikin_keep_corners(P))
dev = max([max_deviation(a, b) for a, b in zip(edges, raw)] or [0.0])
print(f"萃出道路邊線 {len(edges)} 條，最大平滑偏移 {dev:.3f} m")
for i, P in enumerate(edges):
    print(f"  #{i} 長 {LineString(P).length:7.1f} m")

if A.replace_layer:
    for e in list(msp.query(f'*[layer=="{A.replace_layer}"]')):
        msp.delete_entity(e)
    for P in edges:
        msp.add_lwpolyline([tuple(p) for p in P], close=False, dxfattribs={"layer": A.replace_layer})
out = A.out or A.model
doc.saveas(out)
M["road_smooth_max_dev_m"] = round(dev, 3)
M["counts"]["road_edges"] = len(edges)
json.dump(M, open(os.path.join(MD, "basemap_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已更新", out)
