# site_basemap v3 升級（2026-10-22 第一輪比拼檢討後）— 由 site_basemap.py 以 exec 載入，共用其變數
# 1) 官方建物 SHP 優先（逐棟、方位天生正確）  2) 道路邊線彎道 Chaikin 平滑＋偏移指標  3) 行政區反查
import glob, re

# ---- 1. 官方建物 SHP（臺中市建物GIS圖資，TWD97 TM2）----
BSRC_NOTE = "國土測繪中心 通用電子地圖 EMAPX99 向量化並正交化（連棟合併為建物群）"
_src = A.bldg_shp
if _src and os.path.exists(_src):
    import shapefile
    files = [_src] if _src.lower().endswith(".shp") else glob.glob(os.path.join(_src, "**", "*.shp"), recursive=True)
    BBX = box(E0, N0, E1, N1); shp_b, seen, used = [], set(), []
    for f in files:
        prj = f[:-4] + ".prj"
        if os.path.exists(prj):
            t = open(prj, encoding="utf-8", errors="replace").read()
            if not ("TWD97" in t.upper() and "121" in t and "250000" in t):
                log("略過非 TWD97 TM2 的 SHP", f); continue
        r = shapefile.Reader(f, encoding="utf-8", encodingErrors="replace")
        x0, y0, x1, y1 = r.bbox[:4]
        if x1 < E0 or x0 > E1 or y1 < N0 or y0 > N1: continue
        n0 = len(shp_b)
        for sr in r.iterShapeRecords(bbox=(E0, N0, E1, N1)):
            pts = np.asarray(sr.shape.points, float)[:, :2]; pa = list(sr.shape.parts) + [len(pts)]
            polys = []
            for i in range(len(pa) - 1):
                rg = pts[pa[i]:pa[i + 1]]
                if len(rg) > 1 and np.allclose(rg[0], rg[-1]): rg = rg[:-1]
                if len(rg) < 3: continue
                sa = np.dot(rg[:, 0], np.roll(rg[:, 1], -1)) - np.dot(rg[:, 1], np.roll(rg[:, 0], -1))
                if sa < 0 or not polys: polys.append([rg, []])          # SHP：外框順時針、內洞逆時針
                else: polys[-1][1].append(rg)
            for o, hs in polys:
                g = Polygon(o, hs).buffer(0).intersection(BBX)
                for pg in getattr(g, "geoms", [g]):
                    if pg.geom_type != "Polygon" or pg.area < 4: continue
                    key = (round(pg.centroid.x, 1), round(pg.centroid.y, 1), round(pg.area))
                    if key in seen: continue
                    seen.add(key)
                    shp_b.append((np.asarray(pg.exterior.coords)[:-1], [np.asarray(i.coords)[:-1] for i in pg.interiors]))
        if len(shp_b) > n0: used.append(os.path.basename(f))
    if shp_b:
        buildings = shp_b
        BSRC_NOTE = f"臺中市政府 建物GIS圖資（{'、'.join(used)}）逐棟繪製，方位依原始圖資"
    log(f"官方建物 SHP：{len(shp_b)} 棟（來源檔 {used or '無涵蓋本案'}）")
else:
    log("未提供官方建物 SHP，建物改用電子地圖：", _src)

# ---- 2. 道路邊線彎道平滑（轉角保留），量測最大偏移作品質指標 ----
_raw = road_edges
road_edges = [chaikin_keep_corners(P) for P in _raw]
SMOOTH_DEV = max([max_deviation(a, b) for a, b in zip(road_edges, _raw)] or [0.0])
log(f"道路邊線 Chaikin 平滑完成，最大偏移 {SMOOTH_DEV:.3f} m")

# ---- 3. 行政區反查（國土測繪中心 TownVillagePointQuery）----
ADMIN = {}
try:
    _t = S.get(f"https://api.nlsc.gov.tw/other/TownVillagePointQuery/{A.lon}/{A.lat}/4326", timeout=20).text
    for k in ("ctyName", "townName", "villageName", "sectName", "officeName"):
        m = re.search(f"<{k}>(.*?)</{k}>", _t); ADMIN[k] = m.group(1) if m else ""
    log("行政區", ADMIN)
except Exception as ex:
    log("行政區查詢失敗", ex)
