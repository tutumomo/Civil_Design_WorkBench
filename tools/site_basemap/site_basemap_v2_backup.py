"""案址經緯度 → TWD97 現況平面線稿 DXF（道路邊線、道路用地界、建物+Hatch、指北、比例尺）
說明見 D:\\公司案件.AI\\docs\\現況平面底圖作業流程.md；踩坑見 docs\\踩坑紀錄.md   v2 2026-10-22
"""
import argparse, os, sys, json, time, math, shutil, numpy as np, cv2, ezdxf
from shapely.geometry import LineString, Polygon, box
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlsc import fetch_twd97, to97, from97, S
from geomtools import smooth_mask, contours, regularize, despeckle
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--lat", type=float, required=True); ap.add_argument("--lon", type=float, required=True)
ap.add_argument("--name", required=True, help="案名，用於資料夾與檔名")
ap.add_argument("--width", type=float, default=360); ap.add_argument("--height", type=float, default=220)
ap.add_argument("--scale", type=int, default=1000, help="出圖比例分母，用於比例尺註記與字高")
ap.add_argument("--out", default=None); ap.add_argument("--no-osm", action="store_true")
ap.add_argument("--cache", default=None, help="重用此資料夾已下載的底圖影像（離線：不連 NLSC/OSM）")
A = ap.parse_args()
RES = 0.10
OUT = A.out or str(Path(__file__).resolve().parents[2] / "out" / A.name); os.makedirs(OUT, exist_ok=True)
CE, CN = to97.transform(A.lon, A.lat)
E0, E1, N0, N1 = CE - A.width / 2, CE + A.width / 2, CN - A.height / 2, CN + A.height / 2
TXT = 2.5 * A.scale / 1000                       # 出圖 2.5 mm 字高換算成公尺
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def px2m(P): P = np.asarray(P, float); return np.c_[E0 + (P[:, 0] + 0.5) * RES, N1 - (P[:, 1] + 0.5) * RES]

CACHE_FILES = ("ortho_PHOTO2_TWD97.jpg", "cadastral_LAND_TWD97.png", "emap_EMAPX99_TWD97.png")
if A.cache:                       # 離線重用已下載底圖：不連 NLSC、不打 Overpass
    ortho = Image.open(os.path.join(A.cache, CACHE_FILES[0])).convert("RGB")
    land  = Image.open(os.path.join(A.cache, CACHE_FILES[1]))
    emap  = Image.open(os.path.join(A.cache, CACHE_FILES[2])).convert("RGB")
    assert ortho.size == emap.size == land.size, f"cache 影像尺寸不符 {ortho.size} {emap.size} {land.size}"
    for f in CACHE_FILES:         # 外部參考影像必須與 DXF 同資料夾（AGENTS.md §3）
        shutil.copy(os.path.join(A.cache, f), os.path.join(OUT, f))
    log(f"cache mode: {A.cache}  size={ortho.size}")
else:
    ortho = fetch_twd97("PHOTO2", 19, "RGB", E0, N0, E1, N1, RES, log)        # z19 原生，z20 僅插值
    land = fetch_twd97("LAND_OPENDATA", 20, "RGBA", E0, N0, E1, N1, RES, log)
    emap = fetch_twd97("EMAPX99", 19, "RGB", E0, N0, E1, N1, RES, log)        # 無文字電子地圖：建物/道路
    ortho.save(os.path.join(OUT, "ortho_PHOTO2_TWD97.jpg"), quality=92)
    land.save(os.path.join(OUT, "cadastral_LAND_TWD97.png"))
    emap.save(os.path.join(OUT, "emap_EMAPX99_TWD97.png"))

# ---- 電子地圖分類（配色見踩坑紀錄 C）----
E = np.asarray(emap).astype(int)
def near(c, tol=10): return np.abs(E - np.array(c)).sum(2) <= tol
b_mask = cv2.morphologyEx(near((233, 226, 233)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
w_mask = near((149, 213, 251), 12).astype(np.uint8)
gray = (np.abs(E[..., 0] - E[..., 1]) < 4) & (np.abs(E[..., 1] - E[..., 2]) < 4) & (E[..., 0] >= 185) & (E[..., 0] <= 215)
r_mask = ((E.min(2) >= 250) | gray).astype(np.uint8)
n, lab, st, _ = cv2.connectedComponentsWithStats(r_mask, connectivity=8)
r_mask = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] * RES * RES >= 30]).astype(np.uint8)
r_mask = smooth_mask(r_mask, 9)                 # 0.9 m：消除斜線反鋸齒造成的鋸齒

# ---- 公有地地籍：分塊、判斷道路地號、平滑 ----
a = np.asarray(land); al, rgb = a[..., 3], a[..., :3].astype(int)
line = (al > 200) & (rgb[..., 0] > 200) & (rgb[..., 1] < 60) & (rgb[..., 2] < 60)
fill = (al > 0) | line
n, lab = cv2.connectedComponents((fill & ~line).astype(np.uint8), connectivity=4)
parcels, road_union = [], np.zeros_like(r_mask)
for i in range(1, n):
    m = (lab == i).astype(np.uint8)
    if m.sum() * RES * RES < 2.0: continue
    m = smooth_mask(cv2.dilate(m, np.ones((3, 3), np.uint8)), 7)        # 補半條線寬 + 去地號文字凸塊
    if r_mask[m > 0].mean() > 0.5: road_union |= m                         # 多數落在電子地圖道路上 → 道路地號
    parcels += [despeckle(px2m(o)) for o, _ in contours(m, 4.0, 200)]
road_union = smooth_mask(cv2.morphologyEx(road_union, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)), 7)
road_lots = [despeckle(px2m(o)) for o, _ in contours(road_union, 4.0, 500)]

# ---- 建物：向量化 → 主軸正交化（依實際方位）----
buildings = []
for o, hs in contours(smooth_mask(b_mask, 3), 4.0, 800, holes=True):       # <8 m² 不計
    buildings.append((regularize(px2m(o)), [regularize(px2m(h)) for h in hs]))
waters = [despeckle(px2m(o)) for o, _ in contours(smooth_mask(w_mask, 5), 3.0, 2000)]
# 現況道路邊線：道路區外框扣掉圖框邊
from shapely.ops import unary_union
BL = unary_union([LineString(np.vstack([o, o[:1]])) for o, _ in buildings] + [LineString(np.vstack([w, w[:1]])) for w in waters]).buffer(1.0)   # 貼建物的段落由建物線代表，避免雙線
FR = box(E0, N0, E1, N1).exterior.buffer(0.5).union(BL)
road_edges = []
for o, hs in contours(r_mask, 5.0, 3000, holes=True):
    for ring in [o] + hs:
        g = LineString(np.vstack([px2m(ring), px2m(ring)[:1]])).difference(FR)
        road_edges += [despeckle(np.array(s.coords), closed=False) for s in getattr(g, "geoms", [g]) if not s.is_empty and s.length > 5]      # <5 m 碎線不留
log(f"parcels {len(parcels)} | road lots {len(road_lots)} | road edges {len(road_edges)} | buildings {len(buildings)} | water {len(waters)}")

# ---- OSM 道路中心線與路名（建物改用電子地圖，不再取 OSM 建物）----
roads, osm_ok = [], (A.no_osm or bool(A.cache))
if not A.no_osm and not A.cache:
    lo, la = from97.transform([E0, E1], [N0, N1])
    q = f'[out:json][timeout:60];way["highway"]({la[0]},{lo[0]},{la[1]},{lo[1]});out geom;'
    for k, ep in enumerate(["https://overpass-api.de/api/interpreter"] * 3 + ["https://overpass.kumi.systems/api/interpreter"]):
        if k: time.sleep(15)          # 主端點常限流回非 JSON（踩坑紀錄 G）
        try:
            js = S.post(ep, data={"data": q}, timeout=90).json()
            for w in js["elements"]:
                g = w.get("geometry")
                if g: roads.append((list(zip(*to97.transform([p["lon"] for p in g], [p["lat"] for p in g]))), w.get("tags", {}).get("name", "")))
            osm_ok = True; log("OSM roads", len(roads)); break
        except Exception as ex: log("OSM fail", ep, ex)

# ---- DXF ----
doc = ezdxf.new("R2018", setup=True)
doc.header["$INSUNITS"] = 6; doc.header["$MEASUREMENT"] = 1; doc.header["$LUNITS"] = 2
sty = doc.styles.add("TOMO", font="gbenor.shx"); sty.dxf.bigfont = "CHINA1.SHX"
LAYERS = {"00_正射影像_NLSC": 8, "01_公有地地籍影像": 1, "02_電子地圖影像": 8,
          "10_道路邊線_現況": 7, "11_道路用地界_地籍": 1, "12_公有地地籍界線": 9, "13_道路中心線_OSM": 2,
          "14_道路名稱": 7, "20_建物": 4, "21_建物_HATCH": 8, "22_水道": 5,
          "90_圖框": 7, "91_指北針": 7, "92_比例尺": 7, "93_說明": 7}
for k, c in LAYERS.items(): doc.layers.add(k, color=c)
for k in ("00_正射影像_NLSC", "01_公有地地籍影像", "02_電子地圖影像", "12_公有地地籍界線"): doc.layers.get(k).off()
msp = doc.modelspace()
for lay, f, img in [("00_正射影像_NLSC", "ortho_PHOTO2_TWD97.jpg", ortho), ("01_公有地地籍影像", "cadastral_LAND_TWD97.png", land),
                    ("02_電子地圖影像", "emap_EMAPX99_TWD97.png", emap)]:
    msp.add_image(doc.add_image_def(filename=f, size_in_pixel=img.size), insert=(E0, N0),
                  size_in_units=(E1 - E0, N1 - N0), dxfattribs={"layer": lay})
def orient(P, ccw):
    P = np.asarray(P); a = np.dot(P[:, 0], np.roll(P[:, 1], -1)) - np.dot(P[:, 1], np.roll(P[:, 0], -1))
    return P if (a > 0) == ccw else P[::-1]
def pl(P, lay, close=False): msp.add_lwpolyline([tuple(p) for p in P], close=close, dxfattribs={"layer": lay})
for P in road_edges: pl(P, "10_道路邊線_現況")
for P in road_lots: pl(P, "11_道路用地界_地籍", True)
for P in parcels: pl(P, "12_公有地地籍界線", True)
for P in waters: pl(P, "22_水道", True)
for o, hs in buildings:
    pl(o, "20_建物", True); [pl(h, "20_建物", True) for h in hs]
    h = msp.add_hatch(color=256, dxfattribs={"layer": "21_建物_HATCH", "hatch_style": 0})   # Normal：孤島(中庭)鏤空
    h.set_pattern_fill("ANSI31", scale=0.5 * A.scale / 1000)
    h.paths.add_polyline_path([tuple(p) for p in orient(o, True)], is_closed=True, flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL)
    for hh in hs: h.paths.add_polyline_path([tuple(p) for p in orient(hh, False)], is_closed=True, flags=ezdxf.const.BOUNDARY_PATH_OUTERMOST)
BB = box(E0, N0, E1, N1); named = set()
for pts, name in roads:
    if len(pts) < 2: continue
    g = LineString(pts).intersection(BB)
    for seg in getattr(g, "geoms", [g]):
        if seg.is_empty or seg.geom_type != "LineString": continue
        pl(np.array(seg.coords), "13_道路中心線_OSM")
        if name and seg.length > 30 and (name, round(seg.length)) not in named:
            named.add((name, round(seg.length)))
            p0, p1, mid = (seg.interpolate(t, normalized=True) for t in (0.45, 0.55, 0.5))
            ang = math.degrees(math.atan2(p1.y - p0.y, p1.x - p0.x)); ang += 180 if ang < -90 else (-180 if ang > 90 else 0)
            msp.add_text(name, height=TXT * 1.2, rotation=ang, dxfattribs={"layer": "14_道路名稱", "style": "TOMO"}).set_placement(
                (mid.x, mid.y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

# ---- 圖框、指北針、比例尺、說明（皆放在圖框外，不壓圖面）----
K = A.scale / 1000                                # 1:1000 時 1 mm 圖面 = 1 m
pl([(E0, N0), (E1, N0), (E1, N1), (E0, N1)], "90_圖框", True)
msp.add_circle((CE, CN), 1.0 * K, dxfattribs={"layer": "90_圖框"})
ax, ay = E1 + 12 * K, N1 - 14 * K                  # 指北針（TWD97 坐標北，與真北差約子午線收斂角）
msp.add_circle((ax, ay), 7 * K, dxfattribs={"layer": "91_指北針"})
tip, lft, rgt, ntc = (ax, ay + 9 * K), (ax - 4 * K, ay - 6 * K), (ax + 4 * K, ay - 6 * K), (ax, ay - 2.5 * K)
pl([tip, rgt, ntc, lft], "91_指北針", True)
hs = msp.add_hatch(color=256, dxfattribs={"layer": "91_指北針"}); hs.set_solid_fill(color=256)
hs.paths.add_polyline_path([tip, ntc, lft], is_closed=True)
msp.add_text("N", height=TXT * 2, dxfattribs={"layer": "91_指北針", "style": "TOMO"}).set_placement(
    (ax, ay + 12.5 * K), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
nice = [5, 10, 20, 25, 50, 100, 200, 250, 500]
Lb = max(v for v in nice if v <= A.width / 6) if A.width / 6 >= 5 else 5
seg, bh, bx, by = Lb / 5, 1.5 * K, E1 - Lb, N0 - 10 * K
for i in range(5):
    x0 = bx + i * seg
    pl([(x0, by), (x0 + seg, by), (x0 + seg, by + bh), (x0, by + bh)], "92_比例尺", True)
    if i % 2 == 0:
        hb = msp.add_hatch(color=256, dxfattribs={"layer": "92_比例尺"}); hb.set_solid_fill(color=256)
        hb.paths.add_polyline_path([(x0, by), (x0 + seg, by), (x0 + seg, by + bh), (x0, by + bh)], is_closed=True)
for i in range(6):
    v = seg * i; lbl = f"{v:g}" + (" m" if i == 5 else "")
    msp.add_text(lbl, height=TXT, dxfattribs={"layer": "92_比例尺", "style": "TOMO"}).set_placement(
        (bx + v, by + bh + 1.2 * K), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
msp.add_text(f"比例尺 S=1/{A.scale}（出圖尺寸 {A.width/K:.0f}×{A.height/K:.0f} mm）", height=TXT,
             dxfattribs={"layer": "92_比例尺", "style": "TOMO"}).set_placement(
    (bx + Lb / 2, by - 1.5 * K), align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)
note = (f"{A.name} 現況平面圖（自動產製，未經測量）\\P"
        f"坐標系統 TWD97 TM2 (EPSG:3826)，單位公尺；圖北為坐標北。中心點 {A.lat:.6f}, {A.lon:.6f} → E {CE:.3f}  N {CN:.3f}\\P"
        "建物、現況道路邊線：國土測繪中心 通用電子地圖 EMAPX99 向量化並正交化；連棟建物合併為建物群\\P"
        "道路用地界、公有地界：國土測繪中心 公有土地地籍圖 LAND_OPENDATA 向量化，僅供參考，界址以地政事務所為準\\P"
        "底圖影像：國土測繪中心 PHOTO2（年份以影像浮水印為準，圖層預設關閉）；道路中心線/路名：OpenStreetMap (ODbL)\\P"
        "本圖不含高程。產製日期 " + time.strftime("%Y-%m-%d"))
msp.add_mtext(note, dxfattribs={"layer": "93_說明", "style": "TOMO", "char_height": TXT * 0.8,
                                "insert": (E0, N0 - 4 * K), "width": A.width * 0.62})
fn = os.path.join(OUT, f"{A.name}_現況平面圖_TWD97.dxf")
doc.saveas(fn)
json.dump({"name": A.name, "lat": A.lat, "lon": A.lon, "crs": "EPSG:3826", "center_E": CE, "center_N": CN,
           "E0": E0, "N0": N0, "E1": E1, "N1": N1, "res_m": RES, "scale": A.scale, "osm_ok": osm_ok,
           "counts": {"road_edges": len(road_edges), "road_lots": len(road_lots), "parcels": len(parcels),
                      "buildings": len(buildings), "water": len(waters), "osm_roads": len(roads)}, "dxf": os.path.basename(fn)},
          open(os.path.join(OUT, "basemap_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- 自我檢核（AGENTS.md §7）：重讀 DXF、檢查單位與字型、輸出套疊圖與線稿預覽 ----
d2 = ezdxf.readfile(fn); errs = len(d2.audit().errors); s2 = d2.styles.get("TOMO")
assert d2.header["$INSUNITS"] == 6 and s2.dxf.font == "gbenor.shx" and s2.dxf.bigfont == "CHINA1.SHX"
col = {"10_道路邊線_現況": (255, 255, 255), "11_道路用地界_地籍": (0, 0, 255), "20_建物": (0, 255, 255), "22_水道": (255, 160, 0)}
over = cv2.cvtColor(np.asarray(ortho), cv2.COLOR_RGB2BGR).copy(); paper = np.full_like(over, 255)
for e in d2.modelspace().query("LWPOLYLINE"):
    if e.dxf.layer in col:
        pts = np.array([[(x - E0) / RES, (N1 - y) / RES] for x, y in e.get_points("xy")], np.int32)
        cv2.polylines(over, [pts], e.closed, col[e.dxf.layer], 3)
        cv2.polylines(paper, [pts], e.closed, (0, 0, 0) if e.dxf.layer != "11_道路用地界_地籍" else (0, 0, 255), 2)
for name, im in (("_check_overlay.jpg", over), ("_check_linework.jpg", paper)):
    w = min(1800, im.shape[1]); cv2.imencode(".jpg", cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1]))),
                                              [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(os.path.join(OUT, name))
log(f"DONE {fn} | audit errors {errs} | entities {len(d2.modelspace())} | osm_ok {osm_ok}")
