# -*- coding: utf-8 -*-
"""地籍套繪圖產線（A3，預設 1:500）：以指定經緯度為中心，取半徑 R 的地籍坵塊、地段界、建物，
產出 DXF／DWG（可另出 PDF 並跑交件品管）。

資料來源
  1. 臺中市開放 ArcGIS  Dynamic3857/TCLandType
       Land_O（坵塊：AA49 地號／KCNT 段名／AA48 段代碼／AA45 使用分區代碼）
       Sect_O（段籍：段界多邊形）
     https://lohas.taichung.gov.tw/arcgis168/rest/services/Dynamic3857/TCLandType/MapServer
  2. 臺中市建物 GIS（114 年期 SHP，TWD97 TM2）
  3. 內政部國土測繪中心 村里門牌定位 API（行政區）

用法
  python make_cadastral_map.py --lat 24.1114 --lon 120.6579 --radius 50 ^
      --out D:\公司案件.AI\地籍套繪_xxx --scale 500 --publish --check

注意
  * 地籍界址以地政事務所核發之地籍圖謄本／複丈成果圖為準，本圖僅供規劃參考。
  * 只讀不寫外部資料源；每次執行都會留一份 <圖名>_meta.json 記錄來源與數量。
"""
import os, sys, json, math, datetime, argparse, io, subprocess, time
from pathlib import Path

import requests, urllib3
urllib3.disable_warnings()

import shapefile
import ezdxf
from ezdxf.enums import TextEntityAlignment as TA
from shapely.geometry import Polygon, Point, box as shp_box

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path[:0] = [TOOLS, os.path.join(TOOLS, "a3_sheet"), os.path.join(TOOLS, "acad")]
from drawing_rules import (H_BODY, H_NOTE, H_TITLE, model_h,
                           require_standard_scale, add_plot_layer, tag_plot_style)

ARCGIS = "https://lohas.taichung.gov.tw/arcgis168/rest/services/Dynamic3857"
SHP_BLDG = Path(os.environ.get("CIVIL_AI_BLDG_SHP")
                or (Path(__file__).resolve().parents[2] / "data" / "臺中市建物" / "01-SHP" / "114期末_B0001_1216n.shp"))
TEMPLATE = os.path.join(TOOLS, "a3_sheet", "A3圖框_template.dxf")
LAYOUT = "全區工程位置圖"

# A3圖框版面（紙面 mm）— 與 make_sheet.py 同一份圖框
X0, Y0, X1, Y1 = 10.0, 29.0, 410.3, 287.4
CX, SY = 363.5, 80.9
BAND = 30.0                      # 地圖區下緣留給「說明／資料來源」的紙面高度

L_PARCEL = "30_地籍界線"
L_NUM = "31_地號"
L_SECT = "32_地段界線"
L_BLDG = "20_建物"
L_BHATCH = "21_建物_HATCH"
L_RANGE = "40_範圍線_50M"
L_CENTER = "41_中心點"


# ----------------------------------------------------------------------------- 基本工具
def get_json(url, params, tries=3, timeout=90):
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, verify=False,
                             headers={"User-Agent": "Mozilla/5.0 (civil-design-agent)"})
            j = r.json()
            if "error" in j:
                raise RuntimeError(j["error"])
            return j
        except Exception as ex:                                   # 網路抖動重試
            last = ex
            time.sleep(1.5 * (k + 1))
    raise RuntimeError("查詢失敗 %s：%s" % (url, last))


def to_twd97(lat, lon):
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
    return tr.transform(lon, lat)


def admin_of(lat, lon):
    """內政部國土測繪中心 村里門牌定位：回傳 縣市／鄉鎮區／村里"""
    import re
    url = "https://api.nlsc.gov.tw/other/TownVillagePointQuery/%s/%s/4326" % (lon, lat)
    try:
        t = requests.get(url, timeout=30, verify=False,
                         headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception:
        return {}
    out = {}
    for k in ("ctyName", "townName", "villageName", "officeName"):
        m = re.search(r"<%s>([^<]*)</%s>" % (k, k), t)
        if m:
            out[k] = m.group(1).strip()
    return out


def est_width(s, h):
    """CHINA1.SHX 中文字約 1.2h 寬、gbenor 英數約 0.8h（與 check_delivery 同一個估法）"""
    return sum(1.2 * h if ord(c) >= 0x2E80 else 0.8 * h for c in s)


def polylabel(poly, cell=None):
    """內接點（近似 pole of inaccessibility）：格點搜索 + 逐次細分"""
    minx, miny, maxx, maxy = poly.bounds
    w, h = maxx - minx, maxy - miny
    if cell is None:
        cell = max(0.25, min(w, h) / 14.0)
    best, bestd = poly.representative_point(), -1.0
    y = miny
    while y <= maxy + 1e-9:
        x = minx
        while x <= maxx + 1e-9:
            p = Point(x, y)
            if poly.contains(p):
                d = poly.boundary.distance(p)
                if d > bestd:
                    best, bestd = p, d
            x += cell
        y += cell
    step = cell / 2.0
    for _ in range(5):
        cx, cy = best.x, best.y
        for dx in (-step, 0.0, step):
            for dy in (-step, 0.0, step):
                p = Point(cx + dx, cy + dy)
                if poly.contains(p):
                    d = poly.boundary.distance(p)
                    if d > bestd:
                        best, bestd = p, d
        step /= 2.0
    return best, bestd


def split_polygons(g):
    """MultiPolygon / GeometryCollection -> list of Polygon (buffer(0) may split)"""
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    out = []
    for sub in getattr(g, "geoms", []):
        out.extend(split_polygons(sub))
    return out


def rings_to_polygon(rings):
    """Esri rings（外環＋內洞）→ shapely Polygon"""
    polys = []
    for r in rings:
        if len(r) >= 4:
            p = Polygon(r)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                polys.extend(split_polygons(p))
    if not polys:
        return None
    polys.sort(key=lambda p: -p.area)
    outer = polys[0]
    holes = []
    for p in polys[1:]:
        if outer.contains(p.representative_point()):
            holes.append(list(p.exterior.coords))
    try:
        out = Polygon(list(outer.exterior.coords), holes)
        return out if out.is_valid else out.buffer(0)
    except Exception:
        return outer


def fmt_no(aa49):
    """8 碼地號 → 母號-子號；子號 0000 只寫母號"""
    s = (aa49 or "").strip()
    if len(s) == 8 and s.isdigit():
        return s[:4] if s[4:] == "0000" else "%s-%s" % (s[:4], s[4:])
    return s


def ensure_linetypes(doc):
    """補上 DASHED／CENTER 等標準線型（樣板只有 HIDDEN）"""
    have = set(lt.dxf.name for lt in doc.linetypes)
    if {"DASHED", "CENTER"} <= have:
        return
    try:
        from ezdxf.tools.standards import linetypes as std_linetypes
        for name, desc, pattern in std_linetypes():
            if name not in doc.linetypes:
                doc.linetypes.add(name, desc, pattern)
    except Exception:
        from ezdxf.addons import Importer
        tmp = ezdxf.new("R2013", setup=True)
        imp = Importer(tmp, doc)
        imp.import_tables(["linetypes"])
        imp.finalize()
    for need in ("DASHED", "CENTER"):
        if need not in doc.linetypes:
            doc.linetypes.add(need, "Dashed __ __ __", [0.5, 0.25, -0.25])


# ----------------------------------------------------------------------------- 資料抓取
def fetch_parcels(E, N, d):
    url = ARCGIS + "/TCLandType/MapServer/0/query"
    feats, off = [], 0
    while True:
        p = {"f": "json",
             "geometry": json.dumps({"xmin": E - d, "ymin": N - d, "xmax": E + d, "ymax": N + d,
                                     "spatialReference": {"wkid": 3826}}),
             "geometryType": "esriGeometryEnvelope", "inSR": "3826",
             "spatialRel": "esriSpatialRelIntersects",
             "outFields": "AA49,KCNT,UNIT,AA48,AA46,AA45,Shape_Area",
             "returnGeometry": "true", "outSR": "3826", "geometryPrecision": "3",
             "resultOffset": str(off)}
        j = get_json(url, p)
        fs = j.get("features", [])
        feats += fs
        if not j.get("exceededTransferLimit") or not fs:
            break
        off += len(fs)
    return feats


def fetch_sections(E, N, d):
    url = ARCGIS + "/TCLandType/MapServer/1/query"
    p = {"f": "json",
         "geometry": json.dumps({"xmin": E - d, "ymin": N - d, "xmax": E + d, "ymax": N + d,
                                 "spatialReference": {"wkid": 3826}}),
         "geometryType": "esriGeometryEnvelope", "inSR": "3826",
         "spatialRel": "esriSpatialRelIntersects",
         "outFields": "KCNT,UNIT,AA48,Sect,COUNT_AA49",
         "returnGeometry": "true", "outSR": "3826", "geometryPrecision": "3"}
    return get_json(url, p).get("features", [])


def fetch_buildings(bbox):
    sf = shapefile.Reader(SHP_BLDG, encoding="utf-8")
    out = []
    for sr in sf.iterShapeRecords(bbox=bbox):
        g = sr.shape
        pts = g.points
        parts = list(g.parts) + [len(pts)]
        for i in range(len(parts) - 1):
            ring = pts[parts[i]:parts[i + 1]]
            if len(ring) >= 4:
                out.append(ring)
    return out


# ----------------------------------------------------------------------------- 標註
def add_label(msp, s, x, y, h):
    msp.add_text(s, height=h, dxfattribs={"style": "TOMO", "layer": L_NUM}).set_placement(
        (x, y), align=TA.MIDDLE_CENTER)


def label_parcels(msp, parcels, win, h):
    """地號標註：先試坵塊內接點，放不下才外移並拉引線"""
    placed = []
    n_in = n_out = n_fail = 0

    def clash(b):
        for o in placed:
            if min(b[2], o[2]) - max(b[0], o[0]) > 0 and min(b[3], o[3]) - max(b[1], o[1]) > 0:
                return True
        return False

    def rect(cx, cy, w, hh):
        return (cx - w / 2, cy - hh / 2, cx + w / 2, cy + hh / 2)

    wpx0, wpy0, wpx1, wpy1 = win
    win_poly = shp_box(*win)

    for p in parcels:
        txt = fmt_no(p["aa49"])
        if not txt:
            continue
        poly = p["poly"]
        if not poly.intersects(win_poly):
            continue
        vis = poly.intersection(win_poly)
        if vis.is_empty:
            continue
        if vis.geom_type != "Polygon":
            parts = split_polygons(vis)
            if not parts:
                continue
            vis = max(parts, key=lambda g: g.area)
        tw, th = est_width(txt, h) + 0.3, h * 1.35
        pt, _ = polylabel(vis)
        bb = rect(pt.x, pt.y, tw, th)
        if vis.contains(shp_box(*bb)) and not clash(bb):
            add_label(msp, txt, pt.x, pt.y, h)
            placed.append(bb)
            n_in += 1
            continue
        best = None
        for r in (2, 3.5, 5, 7, 9, 12, 15, 18, 22, 26, 30, 35, 40, 45):
            for a in range(0, 360, 15):
                ang = math.radians(a)
                qx, qy = pt.x + r * math.cos(ang), pt.y + r * math.sin(ang)
                bb2 = rect(qx, qy, tw, th)
                if bb2[0] < wpx0 or bb2[2] > wpx1 or bb2[1] < wpy0 or bb2[3] > wpy1:
                    continue
                if clash(bb2):
                    continue
                best = (qx, qy, bb2)
                break
            if best:
                break
        if best is None:
            best = (pt.x, pt.y, bb)
            n_fail += 1
        qx, qy, bb2 = best
        add_label(msp, txt, qx, qy, h)
        placed.append(bb2)
        dx, dy = pt.x - qx, pt.y - qy
        if abs(dx) * th > abs(dy) * tw:
            sx, sy = qx + math.copysign(tw / 2, dx), qy
        else:
            sx, sy = qx, qy + math.copysign(th / 2, dy)
        msp.add_line((sx, sy), (pt.x, pt.y), dxfattribs={"layer": L_NUM})
        n_out += 1
    return n_in, n_out, n_fail


# ----------------------------------------------------------------------------- 圖紙空間
def build_sheet(doc, E, N, A, adm, center_p, n_parcel, n_bldg):
    K = A.scale / 1000.0
    L = doc.layouts.get(LAYOUT)
    for v in [v for v in L.query("VIEWPORT") if v.dxf.get("id", 1) != 1]:
        L.delete_entity(v)

    mw, mh = CX - X0, Y1 - (Y0 + BAND)
    vp = L.add_viewport(center=(X0 + mw / 2, Y0 + BAND + mh / 2), size=(mw, mh),
                        view_center_point=(E, N), view_height=mh * K,
                        dxfattribs={"layer": "Defpoints"})
    vp.dxf.flags = vp.dxf.flags | 16384

    def t(s, x, y, ht=H_BODY, al=TA.MIDDLE_CENTER):
        L.add_text(s, height=ht, dxfattribs={"style": "TOMO", "layer": "圖框"}).set_placement((x, y), align=al)

    def pl(pts, close=False, lt=None):
        a = {"layer": "圖框"}
        if lt:
            a["linetype"] = lt
        return L.add_polyline2d(pts, close=close, dxfattribs=a)

    def hatch(pts, pattern=None):
        hh = L.add_hatch(color=256, dxfattribs={"layer": "圖框"})
        if pattern:
            hh.set_pattern_fill(pattern, color=256, scale=6)
        else:
            hh.set_solid_fill(color=256)
        hh.paths.add_polyline_path(pts, is_closed=True)

    cx = (CX + X1) / 2
    cw = X1 - CX

    pl([(X0, Y0 + BAND), (CX, Y0 + BAND)])
    pl([(CX, SY), (CX, Y1)])

    # 指北針
    yy = Y1 - 6
    t("指 北", cx, yy, H_TITLE)
    ay = yy - 19
    L.add_circle((cx, ay), 7.0, dxfattribs={"layer": "圖框"})
    tip, lft, rgt, ntc = (cx, ay + 9), (cx - 4, ay - 6), (cx + 4, ay - 6), (cx, ay - 2.5)
    pl([tip, rgt, ntc, lft], True)
    hatch([tip, ntc, lft])
    t("N", cx, ay + 12, H_TITLE)
    t("圖北為", cx, ay - 11.5, H_NOTE)
    t("TWD97 坐標北", cx, ay - 18, H_NOTE)
    yy = ay - 22.5
    pl([(CX, yy), (X1, yy)])

    # 比例尺
    yy -= 6
    t("比 例 尺", cx, yy, H_TITLE)
    yy -= 6.5
    t("S=1/%d" % A.scale, cx, yy, H_BODY)
    Lm = max(v for v in (5, 10, 20, 25, 50) if v / K <= cw - 18)
    seg = Lm / 4.0 / K
    bx = cx - 2 * seg - 4.0
    by = yy - 9.5
    for i in range(4):
        pts = [(bx + i * seg, by), (bx + (i + 1) * seg, by),
               (bx + (i + 1) * seg, by + 1.8), (bx + i * seg, by + 1.8)]
        pl(pts, True)
        if i % 2 == 0:
            hatch(pts)
    for i in (0, 2, 4):
        t("%g" % (Lm / 4 * i), bx + i * seg, by + 4.3, H_BODY)
    t("(m)", bx + 4 * seg + 7.0, by + 0.9, H_BODY)
    yy = by - 4
    pl([(CX, yy), (X1, yy)])

    # 圖例
    yy -= 6
    t("圖 例", cx, yy, H_TITLE)
    yy -= 7.5

    def row(label):
        nonlocal yy
        t(label, CX + 15, yy, H_BODY, TA.MIDDLE_LEFT)
        y0 = yy
        yy -= 6.5
        return y0

    y = row("地籍坵塊界線")
    pl([(CX + 2.5, y), (CX + 12.5, y)])
    y = row("地段界線")
    pl([(CX + 2.5, y), (CX + 12.5, y)], lt="DASHED")
    y = row("建物")
    r = [(CX + 2.5, y - 2), (CX + 12.5, y - 2), (CX + 12.5, y + 2), (CX + 2.5, y + 2)]
    pl(r, True)
    hatch(r, "ANSI31")
    y = row("範圍線 R=%gm" % A.radius)
    L.add_circle((CX + 7.5, y), 3.4, dxfattribs={"layer": "圖框", "linetype": "DASHED"})
    y = row("中心點")
    pl([(CX + 4.5, y), (CX + 10.5, y)])
    pl([(CX + 7.5, y - 1.4), (CX + 7.5, y + 1.4)])
    yy += 2.5
    pl([(CX, yy), (X1, yy)])

    # 案址
    yy -= 6
    t("案 址", cx, yy, H_TITLE)
    yy -= 7
    loc = "%s%s%s" % (adm.get("ctyName", ""), adm.get("townName", ""), adm.get("villageName", ""))
    sect = (center_p["kcnt"] if center_p else "") or "－"
    no = fmt_no(center_p["aa49"]) if center_p else "－"
    for s_ in [loc or "（行政區查詢失敗）", "地段：%s" % sect, "地號：%s" % no,
               "E %.3f" % E, "N %.3f" % N, "半徑 %g m" % A.radius]:
        t(s_, CX + 2.5, yy, H_BODY, TA.MIDDLE_LEFT)
        yy -= 5.0
    assert yy > SY + 2, "右側欄內容超出技師圖記區（yy=%.1f）" % yy

    # 說明／資料來源（限 y=29.03~59 之下緣帶，不得侵入標題欄帶）
    t("說 明", X0 + 3, Y0 + BAND - 3.0, H_TITLE, TA.MIDDLE_LEFT)
    lines = [
        "1. 地籍坵塊、地段界線：臺中市開放空間資訊 TCLandType（TWD97 TM2，EPSG:3826）；建物：臺中市建物 GIS（114 年期）。",
        "2. 圖面中心 E %.3f／N %.3f（WGS84 %.7f, %.7f），套繪半徑 %g m；坵塊 %d 筆、建物 %d 棟。"
        % (E, N, A.lat, A.lon, A.radius, n_parcel, n_bldg),
        "3. 地籍界址以地政事務所核發之地籍圖謄本、複丈成果圖為準；本圖自動產製、未經實地測量。",
        "4. 僅供規劃參考，不得作為產權、鑑界或建築線指定之依據。行政區：內政部國土測繪中心。",
    ]
    L.add_mtext("\\P".join(lines), dxfattribs={
        "style": "TOMO", "layer": "圖框", "char_height": 3,
        "insert": (X0 + 3, Y0 + BAND - 8.0), "width": (CX - X0) - 10,
        "attachment_point": 1, "line_spacing_factor": 0.9})

    # 標題欄
    today = datetime.date.today()
    roc = "%d.%02d.%02d" % (today.year - 1911, today.month, today.day)
    twn = adm.get("townName", "")
    sect_txt = (center_p["kcnt"] if center_p else "") or ""
    project = ("%s%s地籍套繪" % (twn, sect_txt)).strip()
    T = dict((x.dxf.text, x) for x in L.query("TEXT"))
    if "案名" in T and project:
        T["案名"].dxf.text = project
    if "圖名" in T:
        T["圖名"].dxf.text = "地籍套繪圖"
    if "臺中市大雅區公所" in T:
        T["臺中市大雅區公所"].dxf.text = A.owner
    if "A-01" in T:
        T["A-01"].dxf.text = A.sheet_no
    STY = {"style": "TOMO", "layer": "圖框"}

    def fill(label, value, dx=12.0, dy=0.0, ht=H_BODY):
        lb = T.get(label)
        if lb is not None and value:
            L.add_text(value, height=ht, dxfattribs=STY).set_placement(
                (lb.dxf.insert.x + dx, lb.dxf.insert.y + dy))

    fill("設計", A.designer)
    fill("繪圖", A.drafter)
    fill("日期", roc)
    fill("比例尺", "1/%d" % A.scale, dx=15.0)
    fill("圖序", "1/1", dx=14.0)


# ----------------------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius", type=float, default=50.0, help="套繪半徑（m），預設 50")
    ap.add_argument("--scale", type=int, default=500)
    ap.add_argument("--name", default="", help="圖名／檔名（預設由行政區與段名自動組）")
    ap.add_argument("--out", required=True, help="輸出資料夾")
    ap.add_argument("--owner", default="（業主待填）", help="業主欄")
    ap.add_argument("--designer", default="")
    ap.add_argument("--drafter", default="Cindy（AI）")
    ap.add_argument("--sheet-no", default="C-01")
    ap.add_argument("--publish", action="store_true", help="另存 DWG 並由 AutoCAD 出 PDF")
    ap.add_argument("--check", action="store_true", help="跑 check_delivery.py 品管")
    A = ap.parse_args()

    require_standard_scale(A.scale)
    K = A.scale / 1000.0

    E, N = to_twd97(A.lat, A.lon)
    adm = admin_of(A.lat, A.lon)

    MAPW, MAPH = CX - X0, Y1 - (Y0 + BAND)
    need_w, need_h = MAPW * K, MAPH * K
    fetch_d = max(A.radius * 1.9, need_w / 2 + 6, need_h / 2 + 6)

    print("中心 TWD97 E=%.3f N=%.3f；行政區 %s%s%s"
          % (E, N, adm.get("ctyName", ""), adm.get("townName", ""), adm.get("villageName", "")))
    print("視口 %.1fx%.1f mm → 模型 %.1fx%.1f m；抓取半徑 %.0f m" % (MAPW, MAPH, need_w, need_h, fetch_d))

    feats = fetch_parcels(E, N, fetch_d)
    sects = fetch_sections(E, N, fetch_d)
    blds = fetch_buildings((E - fetch_d, N - fetch_d, E + fetch_d, N + fetch_d))
    print("坵塊 %d 筆、段籍 %d 筆、建物 %d 筆" % (len(feats), len(sects), len(blds)))
    if not feats:
        raise SystemExit("沒有取得任何坵塊，停止產圖（請確認座標或服務狀態）")

    parcels = []
    for f in feats:
        a, g = f.get("attributes", {}), (f.get("geometry") or {})
        poly = rings_to_polygon(g.get("rings") or [])
        if poly is None or poly.is_empty:
            continue
        parcels.append({"poly": poly, "aa49": str(a.get("AA49") or ""),
                        "kcnt": (a.get("KCNT") or "").strip(),
                        "unit": (a.get("UNIT") or "").strip(),
                        "aa48": (a.get("AA48") or "").strip(),
                        "use": (a.get("AA45") or "").strip(),
                        "area": float(a.get("Shape_Area") or poly.area)})
    parcels.sort(key=lambda p: -p["poly"].area)

    sects_poly = []
    for f in sects:
        poly = rings_to_polygon((f.get("geometry") or {}).get("rings") or [])
        if poly is not None and not poly.is_empty:
            sects_poly.append(poly)

    dmax = max([abs(p["poly"].area - p["area"]) / max(p["area"], 1e-6) for p in parcels] or [0])

    center = Point(E, N)
    hit = [p for p in parcels if p["poly"].contains(center) or p["poly"].buffer(0.02).contains(center)]
    center_p = max(hit, key=lambda p: p["poly"].area) if hit else None
    if center_p:
        print("中心坵塊：%s %s  面積 %.2f m²" % (center_p["kcnt"], fmt_no(center_p["aa49"]), center_p["area"]))

    doc = ezdxf.readfile(TEMPLATE)
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    st = doc.styles.get("TOMO") if "TOMO" in doc.styles else doc.styles.add("TOMO", font="gbenor.shx")
    st.dxf.font = "gbenor.shx"
    st.dxf.bigfont = "CHINA1.SHX"
    ensure_linetypes(doc)

    add_plot_layer(doc, L_BLDG, 4)
    add_plot_layer(doc, L_BHATCH, 8)
    add_plot_layer(doc, L_PARCEL, 1)
    add_plot_layer(doc, L_NUM, 7)
    add_plot_layer(doc, L_SECT, 5)
    add_plot_layer(doc, L_RANGE, 5)
    add_plot_layer(doc, L_CENTER, 6)

    msp = doc.modelspace()

    for p in parcels:
        for sub in split_polygons(p["poly"]):
            for ring in [sub.exterior] + list(sub.interiors):
                msp.add_lwpolyline(list(ring.coords), close=True,
                                   dxfattribs={"layer": L_PARCEL})

    clip = shp_box(E - need_w / 2 - 30, N - need_h / 2 - 30,
                   E + need_w / 2 + 30, N + need_h / 2 + 30)
    for poly in sects_poly:
        for sub in split_polygons(poly.intersection(clip)):
            for ring in [sub.exterior] + list(sub.interiors):
                msp.add_lwpolyline(list(ring.coords), close=True,
                                   dxfattribs={"layer": L_SECT, "linetype": "DASHED"})

    for ring in blds:
        pts = [(x, y) for x, y in ring]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_BLDG})
        h = msp.add_hatch(color=8, dxfattribs={"layer": L_BHATCH})
        h.set_pattern_fill("ANSI31", color=8, scale=5.0)
        h.paths.add_polyline_path(pts, is_closed=True)

    msp.add_circle((E, N), A.radius, dxfattribs={"layer": L_RANGE, "linetype": "DASHED"})
    cc = A.radius * 0.03
    msp.add_line((E - cc, N), (E + cc, N), dxfattribs={"layer": L_CENTER})
    msp.add_line((E, N - cc), (E, N + cc), dxfattribs={"layer": L_CENTER})
    msp.add_circle((E, N), cc * 0.55, dxfattribs={"layer": L_CENTER})

    win = (E - need_w / 2 + 1.0, N - need_h / 2 + 1.0, E + need_w / 2 - 1.0, N + need_h / 2 - 1.0)
    hp = model_h(H_BODY, A.scale)
    n_in, n_out, n_fail = label_parcels(msp, parcels, win, hp)
    print("地號標註：塊內 %d、引線外置 %d%s" % (n_in, n_out, ("、無處可放 %d" % n_fail) if n_fail else ""))

    build_sheet(doc, E, N, A, adm, center_p, len(parcels), len(blds))

    tag_plot_style(doc)
    os.makedirs(A.out, exist_ok=True)
    from collections import Counter
    sect_fallback = Counter(p["kcnt"] for p in parcels if p["kcnt"])
    short = A.name or ("%s%s地籍套繪圖" % (
        adm.get("townName", ""),
        (center_p["kcnt"] if center_p and center_p["kcnt"] else
         (sect_fallback.most_common(1)[0][0] if sect_fallback else ""))))
    short = short.replace("/", "_").replace("\\", "_")
    dxf_path = os.path.join(A.out, short + ".dxf")
    doc.saveas(dxf_path)
    print("DXF", dxf_path)

    d = ezdxf.readfile(dxf_path)
    errs = d.audit().errors
    lay = d.layouts.get(LAYOUT)
    vps = [v for v in lay.query("VIEWPORT") if v.dxf.get("id", 1) != 1]
    assert len(vps) == 1, "視口數 %d" % len(vps)
    v = vps[0]
    ratio = v.dxf.view_height * 1000.0 / v.dxf.height
    assert abs(ratio - A.scale) < 0.5, "視口比例 1:%.1f" % ratio
    assert v.dxf.flags & 16384, "視口未鎖定"

    meta = {
        "center": {"lat": A.lat, "lon": A.lon, "E": round(E, 3), "N": round(N, 3)},
        "admin": adm, "radius_m": A.radius, "scale": A.scale,
        "parcels": len(parcels), "sections": len(sects_poly), "buildings": len(blds),
        "labels_inside": n_in, "labels_leader": n_out, "labels_failed": n_fail,
        "center_parcel": ({"kcnt": center_p["kcnt"], "aa49": center_p["aa49"],
                           "area_m2": round(center_p["area"], 2),
                           "use_code": center_p["use"]} if center_p else None),
        "area_max_rel_diff": round(dmax, 6),
        "parcel_area_sum_m2": round(sum(p["area"] for p in parcels), 2),
        "source": {"cadastre": ARCGIS + "/TCLandType/MapServer (Land_O / Sect_O)",
                   "building": SHP_BLDG,
                   "admin": "https://api.nlsc.gov.tw/other/TownVillagePointQuery"},
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "audit_errors": len(errs),
    }
    io.open(os.path.join(A.out, short + "_meta.json"), "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=2))
    print("OK  audit %d｜坵塊 %d｜建物 %d｜1:%d｜面積最大相對差 %.4f%%"
          % (len(errs), len(parcels), len(blds), A.scale, dmax * 100))

    if A.publish:
        from acc import publish
        r = publish(dxf_path, pdf=True)
        print("PUBLISH", r)
        try:
            import fitz
            pg = fitz.open(r[".pdf"])[0]
            png = os.path.splitext(dxf_path)[0] + "_pdf.png"
            pg.get_pixmap(dpi=120).save(png)
            print("PDF 預覽", png, "%.1fx%.1f mm" % (pg.rect.width * 25.4 / 72, pg.rect.height * 25.4 / 72))
        except Exception as ex:
            print("PDF 轉圖略過", ex)

    if A.check:
        ck = os.path.join(TOOLS, "a3_sheet", "check_delivery.py")
        r = subprocess.run([sys.executable, ck, dxf_path, "--scale", str(A.scale),
                            "--layout", LAYOUT, "--require-dwg"],
                           capture_output=True, text=True, encoding="utf-8")
        print(r.stdout[-6000:])
        if r.stderr:
            print(r.stderr[-800:])
        if r.returncode != 0:
            print("CHECK FAILED")
            sys.exit(1)


if __name__ == "__main__":
    main()
