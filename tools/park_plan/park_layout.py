# -*- coding: utf-8 -*-
"""社區公園 40 x 25 m —— 設計資料與幾何（平面圖與 3D 共用的唯一來源）。

為什麼要有這支
--------------
平面圖（`tools/park_plan/make_park_plan.py`，ezdxf）與 3D 景觀模擬
（`tools/landscape3d/park_scene.py`，Blender）如果各寫一份座標，改一個數字就會出現
「圖上步道在這裡、3D 裡步道在那裡」的對不上——而這種錯在透視圖上幾乎看不出來。

所以：**所有座標、高程、植栽編號只在這裡寫一次**。兩邊都 import 本模組，
改 `SITE_W`／`MOUNDS`／植栽清單後重跑，圖與模型同步改。

本模組只用標準庫（`math`），因為 Blender 的 Python 沒有 shapely／numpy。

座標系
------
* 局部座標：原點在公園**西南角**，X 向東、Y 向北，單位公尺，範圍 0..SITE_W / 0..SITE_H。
* 真實座標：`to_real()` 平移成 TWD97 TM2（EPSG:3826）。本測試案址暫定臺中，
  正式案件必須換成實際測量座標（見 `docs/公園景觀設計產線.md`）。

高程
----
* 基地整地高程 `GRADE = 0.05 m`（步道與廣場面）。
* 草地＝`GRADE` ＋ 低頻起伏 ＋ 土丘（`MOUNDS`），且**在步道／廣場廊帶內平滑壓平**到
  `GRADE`，確保步道不懸空、也不被土丘切斷（`terrain_z()` 的混合機制）。
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------- 基本尺寸
SITE_W, SITE_H = 40.0, 25.0          # 基地 40 x 25 m
GRADE = 0.05                          # 步道／廣場整地高程（m）
ORIGIN_E, ORIGIN_N = 215_000.0, 2_669_000.0   # 測試案址（臺中 TWD97 TM2 假東移）

PATH_W_MAIN = 2.4                     # 主步道淨寬
PATH_W_LINK = 2.4                     # 入口銜接步道
FLAT_BLEND = 2.20                     # 步道外側多遠之内壓平到 GRADE（m）

# 土丘（中央草丘＋三個邊坡草丘）：cx, cy 中心、r 影響半徑、h 丘頂高於 GRADE
MOUNDS = (
    dict(tag="A", cx=17.6, cy=14.6, r=6.40, h=1.25, name="中央草丘"),
    dict(tag="B", cx=3.80, cy=20.40, r=3.60, h=0.70, name="西側草丘"),
    dict(tag="C", cx=33.60, cy=5.40, r=4.00, h=0.55, name="東南草丘"),
    dict(tag="D", cx=31.40, cy=21.60, r=3.40, h=0.80, name="東北草丘"),
)
UNDULATION = 0.06                     # 草地低頻起伏振幅（m）


# ---------------------------------------------------------------- 幾何小工具
def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 1.0 if x >= edge1 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def dist_point_seg(px, py, ax, ay, bx, by) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return math.hypot(dx, dy)


def dist_to_polyline(px, py, pts, closed=True) -> float:
    n = len(pts)
    best = 1e18
    last = n if closed else n - 1
    for i in range(last):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        d = dist_point_seg(px, py, ax, ay, bx, by)
        if d < best:
            best = d
    return best


def polyline_length(pts, closed=False) -> float:
    total = 0.0
    n = len(pts)
    last = n if closed else n - 1
    for i in range(last):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        total += math.hypot(bx - ax, by - ay)
    return total


def point_in_polygon(px, py, poly) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            x = (xj - xi) * (py - yi) / (yj - yi + 1e-18) + xi
            if px < x:
                inside = not inside
        j = i
    return inside


def polygon_area(poly) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ribbon(pts, half_width, closed=True):
    """中心線 → 帶狀外框（外側/內側各偏移半寬，頂點用前後段法線平均，miter）。

    回傳單一封閉多邊形（外側去程 + 內側回程），供 hatch 與 3D 鋪面共用。
    封閉曲線（環狀步道）時回傳「外環 + 內環」兩條，呼叫端自行處理孔洞。
    """
    n = len(pts)
    outer, inner = [], []
    for i in range(n):
        if closed:
            p0 = pts[(i - 1) % n]
            p1 = pts[i]
            p2 = pts[(i + 1) % n]
        else:
            p0 = pts[max(i - 1, 0)]
            p1 = pts[i]
            p2 = pts[min(i + 1, n - 1)]
        # 前後段單位法線（端點的「前一段」或「後一段」長度可能為 0，
        # 若照舊公式取平均會得到零向量，miter 係數爆成 half/0.35 → 帶寬放大 3 倍，
        # 2026-11-07 的入口銜接步道就因此變成 6.9 m 寬的板子）
        def nrm(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 1e-9:
                return None
            return (-dy / L, dx / L)

        n1 = nrm(p0, p1)
        n2 = nrm(p1, p2)
        seg_n = [n for n in (n1, n2) if n is not None]
        if not seg_n:
            nx, ny = 0.0, 0.0
        else:
            nx = sum(n[0] for n in seg_n) / len(seg_n)
            ny = sum(n[1] for n in seg_n) / len(seg_n)
            L = math.hypot(nx, ny) or 1.0
            nx, ny = nx / L, ny / L
        # miter 補償：取前後段最小的投影，避免內角過衝
        if seg_n:
            cos_half = min(1.0, min(nx * n[0] + ny * n[1] for n in seg_n))
            cos_half = max(0.35, cos_half)
        else:
            cos_half = 1.0
        k = half_width / cos_half
        outer.append((p1[0] + nx * k, p1[1] + ny * k))
        inner.append((p1[0] - nx * k, p1[1] - ny * k))
    if closed:
        return outer + inner[::-1]
    return outer + inner[::-1]


def rounded_rect(x0, y0, x1, y1, r, seg=14):
    """圓角矩形中心線（順時針由左下角起）。"""
    pts = []

    def arc(cx, cy, a0, a1):
        for i in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    arc(x0 + r, y0 + r, 180, 270)      # 左下角
    arc(x1 - r, y0 + r, 270, 360)      # 右下角
    arc(x1 - r, y1 - r, 0, 90)         # 右上角
    arc(x0 + r, y1 - r, 90, 180)       # 左上角
    # 去掉重複首點
    if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
        pts.pop()
    return pts


def rounded_polyline(pts, r):
    """折線 → 圓角折線（把每個轉角換成半徑 r 的圓弧，每段至少 4 段）。"""
    out = [pts[0]]
    n = len(pts)
    for i in range(1, n - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1]); L1 = math.hypot(*v1) or 1
        v2 = (p2[0] - p1[0], p2[1] - p1[1]); L2 = math.hypot(*v2) or 1
        rr = min(r, L1 * 0.45, L2 * 0.45)
        a = (p1[0] - v1[0] / L1 * rr, p1[1] - v1[1] / L1 * rr)
        b = (p1[0] + v2[0] / L2 * rr, p1[1] + v2[1] / L2 * rr)
        out.append(a)
        for k in range(1, 6):
            t = k / 6.0
            # 以二次貝茲近似圓角（視覺足夠，且不需算角度）
            x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * p1[0] + t * t * b[0]
            y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * p1[1] + t * t * b[1]
            out.append((x, y))
        out.append(b)
    out.append(pts[-1])
    return out


# ---------------------------------------------------------------- 平面配置
def _loop():
    return rounded_rect(8.20, 7.60, 31.80, 20.40, 5.00)


#: 主要步道（環狀主步道 + 入口銜接段）
PATHS = (
    dict(name="主步道", code="P1", width=PATH_W_MAIN, closed=True, pts=_loop()),
    dict(name="入口銜接", code="P2", width=PATH_W_MAIN, closed=False,
         pts=[(20.0, 5.98), (20.0, 6.42)]),
)

#: 入口廣場（矩形）＋ 東側節點廣場（圓形）
PLAZA_RECT = (15.0, 0.0, 25.0, 6.00)
PLAZA_NODE = dict(cx=31.80, cy=14.00, r=3.00)      # 環狀步道東側節點廣場

#: 入口水池（含石砌落水牆）——案主要求的「帶水池的入口意象」
POOL = dict(x0=18.40, y0=1.60, x1=21.60, y1=4.00, coping=0.30,
            water_z=GRADE + 0.10, coping_h=0.16, depth=0.42,
            spout=dict(x0=19.55, y0=3.72, x1=20.45, y1=4.02, h=0.88))

#: 入口景石柱（一高一低，框出入口動線；古樸石材）
MONOLITHS = (
    dict(code="M1", x=18.15, y=0.32, w=0.52, d=0.52, h=1.50),
    dict(code="M2", x=21.85, y=0.32, w=0.52, d=0.52, h=1.15),
)

#: 入口景名牆（兩段，中間 3.2 m 開口即入口動線）
NAME_WALLS = (
    dict(x0=15.00, x1=18.40, y=0.32, thick=0.32, h=0.62),
    dict(x0=21.60, x1=25.00, y=0.32, thick=0.32, h=0.62),
)

# ---------------------------------------------------------------- 植栽
#: 喬木（code 對應植栽表；canopy＝樹冠半徑，h＝樹高）
TREES = (
    dict(code="T01", sp="苦楝",  latin="Melia azedarach",        x=17.10, y=15.80, canopy=2.60, h=7.6),
    dict(code="T02", sp="臺灣欒樹", latin="Koelreuteria henryi",  x=19.90, y=13.10, canopy=2.40, h=7.0),
    dict(code="T03", sp="樟樹",  latin="Cinnamomum camphora",    x=15.00, y=12.40, canopy=2.80, h=8.2),
    dict(code="T04", sp="光蠟樹", latin="Fraxinus griffithii",    x=20.60, y=16.90, canopy=2.20, h=6.4),
    dict(code="T05", sp="樟樹",  latin="Cinnamomum camphora",    x=10.60, y=22.40, canopy=2.90, h=8.2),
    dict(code="T06", sp="苦楝",  latin="Melia azedarach",        x=25.20, y=23.30, canopy=2.50, h=7.6),
    dict(code="T07", sp="臺灣欒樹", latin="Koelreuteria henryi",  x=31.40, y=21.90, canopy=2.30, h=7.0),
    dict(code="T08", sp="光蠟樹", latin="Fraxinus griffithii",    x=5.20, y=10.20, canopy=2.40, h=6.4),
    dict(code="T09", sp="茄苳",  latin="Bischofia javanica",      x=5.60, y=5.40, canopy=2.60, h=7.0),
    dict(code="T10", sp="樟樹",  latin="Cinnamomum camphora",    x=9.40, y=2.80, canopy=2.70, h=8.2),
    dict(code="T11", sp="苦楝",  latin="Melia azedarach",        x=30.60, y=2.60, canopy=2.50, h=7.6),
    dict(code="T12", sp="臺灣欒樹", latin="Koelreuteria henryi",  x=35.80, y=12.20, canopy=2.40, h=7.0),
    dict(code="T13", sp="光蠟樹", latin="Fraxinus griffithii",    x=34.60, y=17.80, canopy=2.30, h=6.4),
    dict(code="T14", sp="茄苳",  latin="Bischofia javanica",      x=13.60, y=3.10, canopy=2.60, h=7.0),
    dict(code="T15", sp="茄苳",  latin="Bischofia javanica",      x=26.40, y=3.10, canopy=2.60, h=7.0),
)

#: 灌木群植帶（矩形基準 + 程式加波浪邊，見 shrub_bed_polygon()）
SHRUB_BEDS = (
    dict(code="S1", name="南側臨路綠籬", box=(0.80, 0.60, 13.60, 2.40)),
    dict(code="S2", name="南側臨路綠籬", box=(26.40, 0.60, 39.20, 2.40)),
    dict(code="S3", name="北側邊界綠帶", box=(0.80, 22.60, 39.20, 24.20)),
    dict(code="S4", name="西側邊界綠帶", box=(0.80, 3.20, 2.60, 22.20)),
    dict(code="S5", name="東側邊界綠帶", box=(37.40, 3.20, 39.20, 22.20)),
    dict(code="S6", name="入口西側花台", box=(13.20, 4.20, 14.60, 6.60)),
    dict(code="S7", name="入口東側花台", box=(25.40, 4.20, 26.80, 6.60)),
)

# ---------------------------------------------------------------- 沿步道定位
# 燈具與座椅一律「沿步道里程 + 向外偏移」生成，不手寫座標——
# 手寫座標會在改步道寬度或線形時壓到步道（2026-11-07 首版即如此），
# 而這種錯在透視圖上完全看不出來。

def walk_polyline(pts, closed, s):
    """沿折線走 s 公尺，回傳 (x, y, 單位切線)。"""
    n = len(pts)
    last = n if closed else n - 1
    remain = s % polyline_length(pts, closed) if closed else s
    for i in range(last):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if remain <= L or i == last - 1:
            t = (remain / L) if L > 1e-9 else 0.0
            t = min(t, 1.0)
            tx, ty = (b[0] - a[0]) / (L or 1), (b[1] - a[1]) / (L or 1)
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, (tx, ty)
        remain -= L
    a = pts[0]
    return a[0], a[1], (1.0, 0.0)


def path_side_point(path, s, offset, outward=True):
    """步道中心線里程 s 處，往（外側|內側）偏移 offset 公尺的點；回傳 (x, y, 方位角deg)。

    中心線為逆時針（CCW），外側法線 = (ty, -tx)。"""
    x, y, (tx, ty) = walk_polyline(path["pts"], path["closed"], s)
    nx, ny = (ty, -tx) if outward else (-ty, tx)
    ang = math.degrees(math.atan2(ty, tx))
    return x + nx * offset, y + ny * offset, ang


#: 景觀燈（bole＝矮柱燈 0.9 m；pole＝景觀高燈 3.5 m）
LIGHTS = tuple(
    [dict(code=f"L{i+1:02d}", kind="bole", x=x, y=y, h=0.90)
     for i, (x, y, _) in enumerate(
         [path_side_point(PATHS[0], s, PATH_W_MAIN / 2 + 0.45)
          for s in (2.0, 10.0, 18.0, 26.0, 34.0, 42.0, 50.0, 58.0)])]
    + [dict(code="L09", kind="bole", x=15.65, y=0.95, h=0.90),
       dict(code="L10", kind="bole", x=24.35, y=0.95, h=0.90),
       dict(code="L11", kind="pole", x=16.30, y=2.10, h=3.50),
       dict(code="L12", kind="pole", x=23.70, y=2.10, h=3.50)]
)

#: 古樸石造座椅（1.8 m 石板 + 兩塊石墩；angle 為長軸方位角，度，0＝沿 X）
#: 沿環狀步道外側 1.15 m 處、長軸順著步道方向（＝坐在椅上可看中央草丘）
BENCHES = tuple(
    [dict(code=f"B{i+1:02d}", x=x, y=y, angle=ang)
     for i, (x, y, ang) in enumerate(
         [path_side_point(PATHS[0], s, PATH_W_MAIN / 2 + 1.15, outward=False)
          for s in (7.0, 24.0, 41.0, 57.0)])]
    + [dict(code="B05", x=16.10, y=5.40, angle=0),
       dict(code="B06", x=23.90, y=5.40, angle=0)]
)
BENCH_L, BENCH_W, BENCH_H = 1.80, 0.46, 0.44

#: 植栽規格（給植栽表用）
TREE_SPECS = {
    "苦楝":    dict(latin="Melia azedarach",       spec="高 6.0–8.0 m，米高直徑 12 cm"),
    "臺灣欒樹": dict(latin="Koelreuteria henryi",   spec="高 6.0–9.0 m，米高直徑 12 cm"),
    "樟樹":    dict(latin="Cinnamomum camphora",   spec="高 7.0–9.0 m，米高直徑 15 cm"),
    "光蠟樹":  dict(latin="Fraxinus griffithii",   spec="高 5.0–7.0 m，米高直徑 10 cm"),
    "茄苳":    dict(latin="Bischofia javanica",    spec="高 6.0–9.0 m，米高直徑 12 cm"),
}
SHRUB_SPEC = dict(spec="杜鵑／桂花／矮仙丹混合，3 株/m²，高 0.45–0.70 m")


def shrub_bed_polygon(box, amp=0.55, waves=(1.7, 2.9), steps=34):
    """矩形 → 波浪邊的灌木帶（確定性，不用亂數；平面與 3D 共用）。"""
    x0, y0, x1, y1 = box
    pts = []

    def edge(a, b, phase):
        ax, ay = a
        bx, by = b
        L = math.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) / L, (bx - ax) / L
        n = max(4, int(L / 0.4))
        for i in range(n):
            t = i / n
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            d = amp * (0.6 * math.sin(waves[0] * 6.0 * t + phase)
                       + 0.4 * math.sin(waves[1] * 6.0 * t + phase * 1.7))
            pts.append((x + nx * d, y + ny * d))

    edge((x0, y0), (x1, y0), 0.0)
    edge((x1, y0), (x1, y1), 1.9)
    edge((x1, y1), (x0, y1), 3.4)
    edge((x0, y1), (x0, y0), 5.1)
    return pts


SHRUB_POLYS = tuple((b, shrub_bed_polygon(b["box"])) for b in SHRUB_BEDS)


# ---------------------------------------------------------------- 高程
def _bump(x, y, m):
    d = math.hypot(x - m["cx"], y - m["cy"]) / m["r"]
    if d >= 1.0:
        return 0.0
    return m["h"] * smoothstep(0.0, 1.0, 1.0 - d)


def ground_z(x, y) -> float:
    """未壓平的草地高程：整地高程 + 低頻起伏 + 土丘。"""
    z = GRADE
    z += UNDULATION * math.sin(x * 0.33 + 0.7) * math.cos(y * 0.29 - 0.4)
    for m in MOUNDS:
        z += _bump(x, y, m)
    return z


def in_node_plaza(x, y) -> bool:
    n = PLAZA_NODE
    return math.hypot(x - n["cx"], y - n["cy"]) <= n["r"]


def in_plaza(x, y) -> bool:
    x0, y0, x1, y1 = PLAZA_RECT
    if x0 <= x <= x1 and y0 <= y <= y1:
        return True
    return in_node_plaza(x, y)


def path_offset(x, y):
    """回傳 (d - half_width)：負值代表落在步道面內。"""
    best = 1e18
    for p in PATHS:
        d = dist_to_polyline(x, y, p["pts"], p["closed"])
        best = min(best, d - p["width"] / 2.0)
    return best


def terrain_z(x, y) -> float:
    """最終地表高程：步道／廣場面固定 GRADE，外側 2.2 m 内平滑過渡回草地。"""
    if in_plaza(x, y) or path_offset(x, y) <= 0.0:
        return GRADE
    t = smoothstep(0.0, 1.0, path_offset(x, y) / FLAT_BLEND)
    return GRADE + (ground_z(x, y) - GRADE) * t


def slope_at(x, y, d=0.25):
    """數值坡度（無因次），供步道可及性與物件放置檢核。"""
    dzx = (terrain_z(x + d, y) - terrain_z(x - d, y)) / (2 * d)
    dzy = (terrain_z(x, y + d) - terrain_z(x, y - d)) / (2 * d)
    return math.hypot(dzx, dzy)


# ---------------------------------------------------------------- 座標轉換
def to_real(x, y):
    """局部（m）→ TWD97 TM2（EPSG:3826）。"""
    return (ORIGIN_E + x, ORIGIN_N + y)


def to_local(e, n):
    return (e - ORIGIN_E, n - ORIGIN_N)


# ---------------------------------------------------------------- 數量
def quantities():
    """設計數量（平面圖的數量表與交付清單共用）。"""
    main = PATHS[0]
    link = PATHS[1]
    path_area = (polyline_length(main["pts"], closed=True) * main["width"]
                 + polyline_length(link["pts"]) * link["width"])
    plaza_area = ((PLAZA_RECT[2] - PLAZA_RECT[0]) * (PLAZA_RECT[3] - PLAZA_RECT[1])
                  + math.pi * PLAZA_NODE["r"] ** 2)
    # 節點廣場與環狀步道重疊，扣除重疊段（保守以 3.0 m 寬 x 6.0 m 長估算）
    plaza_area -= 3.0 * 6.0 * 0.55
    pool_inner = ((POOL["x1"] - POOL["x0"]) * (POOL["y1"] - POOL["y0"]))
    shrub_area = sum(polygon_area(poly) for _, poly in SHRUB_POLYS)
    bed_planting = sum(polygon_area(box_poly(b["box"])) for b in SHRUB_BEDS
                       if b["code"] in ("S6", "S7"))
    tree_area = sum(math.pi * t["canopy"] ** 2 * 0.55 for t in TREES)   # 樹冠投影僅供參考
    grass = (SITE_W * SITE_H) - path_area - plaza_area - pool_inner - shrub_area - bed_planting
    return dict(
        site_area=SITE_W * SITE_H,
        path_len_main=polyline_length(main["pts"], closed=True),
        path_len_link=polyline_length(link["pts"]),
        path_area=path_area,
        plaza_area=plaza_area,
        pool_area=pool_inner,
        water_volume=pool_inner * (POOL["water_z"] - (GRADE - POOL["depth"])),
        shrub_area=shrub_area + bed_planting,
        shrub_count=int(round((shrub_area + bed_planting) * 3)),
        grass_area=grass,
        tree_count=len(TREES),
        tree_shade_area=tree_area,
        light_count=len(LIGHTS),
        light_bole=len([l for l in LIGHTS if l["kind"] == "bole"]),
        light_pole=len([l for l in LIGHTS if l["kind"] == "pole"]),
        bench_count=len(BENCHES),
        monolith_count=len(MONOLITHS),
        wall_len=sum(w["x1"] - w["x0"] for w in NAME_WALLS),
    )


def box_poly(box):
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def tree_species_counts():
    out = {}
    for t in TREES:
        out[t["sp"]] = out.get(t["sp"], 0) + 1
    return out


# ---------------------------------------------------------------- 自檢
def validate(verbose=True):
    """幾何自檢：步道寬度、坡度、物件是否壓到步道／水池。回傳問題清單。"""
    issues = []

    # 1. 步道縱坡（沿中心線取樣）
    for p in PATHS:
        pts = p["pts"]
        worst = 0.0
        for i in range(len(pts) - 1):
            z0 = terrain_z(*pts[i])
            z1 = terrain_z(*pts[i + 1])
            L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            if L > 1e-6:
                worst = max(worst, abs(z1 - z0) / L)
        if worst > 0.05:
            issues.append(f"{p['name']} 縱坡 {worst*100:.1f}% 超過 5%")

    # 2. 樹木是否壓到步道／廣場／水池
    for t in TREES:
        if path_offset(t["x"], t["y"]) < 0.4:
            issues.append(f"{t['code']} 距離步道邊緣僅 {path_offset(t['x'], t['y']):.2f} m")
        if in_plaza(t["x"], t["y"]):
            issues.append(f"{t['code']} 落在廣場鋪面上（需設植栽穴）")
        if slope_at(t["x"], t["y"]) > 0.35:
            issues.append(f"{t['code']} 位於陡坡（坡度 {slope_at(t['x'], t['y']):.2f}）")

    # 3. 座椅、燈具是否壓到步道
    for b in BENCHES:
        if path_offset(b["x"], b["y"]) < 0.2:
            issues.append(f"{b['code']} 座椅壓到步道（淨距 {path_offset(b['x'], b['y']):.2f} m）")
    for l in LIGHTS:
        if path_offset(l["x"], l["y"]) < 0.35:
            issues.append(f"{l['code']} 燈具太貼步道邊緣（{path_offset(l['x'], l['y']):.2f} m）")

    # 4. 水池須落在入口廣場內
    if not in_plaza(POOL["x0"], POOL["y0"]) or not in_plaza(POOL["x1"], POOL["y1"]):
        issues.append("水池未完全落在入口廣場內")
    if verbose:
        if issues:
            print("[park_layout] 幾何自檢：%d 項待修" % len(issues))
            for s in issues:
                print("   -", s)
        else:
            print("[park_layout] 幾何自檢：OK（步道縱坡、物件淨距、水池位置皆通過）")
    return issues


if __name__ == "__main__":
    validate()
    q = quantities()
    for k, v in q.items():
        print(f"  {k:18s} {v if isinstance(v, int) else round(v, 2)}")
    print("土丘丘頂高程：", [(m["tag"], round(GRADE + m["h"], 2)) for m in MOUNDS])
