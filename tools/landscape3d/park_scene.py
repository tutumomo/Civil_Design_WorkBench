# -*- coding: utf-8 -*-
"""社區公園 40 x 25 m —— 手繪質感 3D 景觀意象（Blender headless）。

設計資料全部 import 自 `tools/park_plan/park_layout.py`（與平面圖同一份座標），
本檔只負責建模、打光、出圖；紙張質感在出圖後由 `paper_style.py` 疊上去。

執行（Linux，Blender 在 PATH）：
    blender -b --factory-startup --python tools/landscape3d/park_scene.py
    blender -b --factory-startup --python tools/landscape3d/park_scene.py -- --preview

參數：
    --out DIR      輸出目錄（預設 out/社區公園_40x25）
    --preview      640x360 / 24 samples，只出主視角，檔名加 PREVIEW_
    --views a,b    只出指定視角（main/entry/aerial/hill）

產出：
    <案名>_3D場景.blend
    <案名>_3D_主視角.png／_入口近景.png／_鳥瞰.png／_丘頂視角.png
"""
from __future__ import annotations

import json
import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Euler, Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
for _cand in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "park_plan")):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import park_layout as P          # noqa: E402

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=""):
    for i, a in enumerate(ARGV):
        if a == f"--{name}":
            return ARGV[i + 1] if i + 1 < len(ARGV) else default
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    return default


def flag(name):
    return f"--{name}" in ARGV


OUT = os.path.abspath(opt("out", os.path.join(ROOT, "out", "社區公園_40x25")))
os.makedirs(OUT, exist_ok=True)
NAME = opt("name", "社區公園")
PREVIEW = flag("preview")
ONLY = [v.strip() for v in opt("views", "").split(",") if v.strip()]

ARTIFACTS = []
RESULT = {}

random.seed(20261107)

# ------------------------------------------------------------------ 場景初始化
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1.0

# ------------------------------------------------------------------ 材質
# 手繪感的關鍵：低對比、低彩度的「水彩／色鉛筆」色盤 + 極低鏡面反射。
# 顏色用 sRGB 直覺值填，內部轉線性，避免整張圖偏白。
def s2l(c):
    def f(u):
        u = max(0.0, min(1.0, float(u)))
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    return tuple(f(u) for u in c)


def mat(name, base, rough=0.92, spec=0.14, var=None, bump=0.0, scale=8.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base = s2l(base)
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    if var:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = scale
        tex.inputs["Detail"].default_value = 5.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*base, 1.0)
        ramp.color_ramp.elements[1].color = (*s2l(var), 1.0)
        nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if bump:
        t2 = nt.nodes.new("ShaderNodeTexNoise")
        t2.inputs["Scale"].default_value = scale * 9.0
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = bump
        nt.links.new(t2.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def foliage(name, c1, c2, c3, rough=0.95, bump=0.05):
    """每株取不同色（Object Info > Random），避免整片同色。"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.1
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = 0.0, (*s2l(c1), 1.0)
    el[1].position, el[1].color = 1.0, (*s2l(c3), 1.0)
    el.new(0.5).color = (*s2l(c2), 1.0)
    nt.links.new(oi.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if bump:
        t2 = nt.nodes.new("ShaderNodeTexNoise")
        t2.inputs["Scale"].default_value = 40.0
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = bump
        nt.links.new(t2.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    return m


# 色盤（水彩感）：草綠偏灰、鋪面暖灰、石材米灰、水色青灰
M_GRASS = mat("草地", (0.470, 0.560, 0.330), var=(0.545, 0.620, 0.390), scale=3.2, bump=0.35)
M_GRASS_DARK = mat("草地_坡面", (0.420, 0.510, 0.300), var=(0.500, 0.575, 0.360), scale=3.6, bump=0.35)
M_PATH = mat("步道_透水鋪面", (0.760, 0.720, 0.640), var=(0.680, 0.640, 0.560), scale=12.0, bump=0.30)
M_PLAZA = mat("廣場_洗石子", (0.790, 0.755, 0.685), var=(0.720, 0.685, 0.620), scale=14.0, bump=0.22)
M_STONE = mat("石材", (0.700, 0.675, 0.620), var=(0.620, 0.600, 0.550), scale=22.0, bump=0.45)
M_STONE_D = mat("石材_深", (0.560, 0.540, 0.500), var=(0.610, 0.590, 0.545), scale=18.0, bump=0.45)
M_WATER = mat("水面", (0.400, 0.560, 0.575), rough=0.09, spec=0.85, var=(0.470, 0.640, 0.650), scale=6.0)
M_METAL = mat("燈具金屬", (0.300, 0.315, 0.300), rough=0.55, spec=0.5)
M_GLOW = mat("燈罩", (0.960, 0.900, 0.720), rough=0.6, spec=0.2)
M_TRUNK = mat("樹幹", (0.330, 0.275, 0.220), var=(0.400, 0.345, 0.275), scale=16.0, bump=0.4)
M_SHRUB = foliage("灌木_杜鵑桂花", (0.400, 0.510, 0.290), (0.470, 0.575, 0.330), (0.350, 0.455, 0.265))
M_CANOPY_A = foliage("樹冠_樟樹", (0.330, 0.470, 0.290), (0.400, 0.545, 0.330), (0.290, 0.420, 0.265))
M_CANOPY_B = foliage("樹冠_欒樹", (0.400, 0.520, 0.300), (0.480, 0.590, 0.350), (0.360, 0.480, 0.280))
M_CANOPY_C = foliage("樹冠_苦楝", (0.360, 0.500, 0.310), (0.430, 0.565, 0.345), (0.320, 0.450, 0.280))
M_CANOPY_D = foliage("樹冠_光蠟樹", (0.385, 0.520, 0.325), (0.455, 0.585, 0.365), (0.340, 0.465, 0.290))
M_ASPHALT = mat("瀝青", (0.320, 0.320, 0.310), var=(0.380, 0.380, 0.365), scale=10.0, bump=0.25)

CANOPY_BY_SPECIES = {
    "樟樹": M_CANOPY_A, "臺灣欒樹": M_CANOPY_B, "苦楝": M_CANOPY_C,
    "光蠟樹": M_CANOPY_D, "茄苳": M_CANOPY_A,
}

# ------------------------------------------------------------------ 幾何工具
def obj_from_bm(name, bm, material=None, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    if material:
        ob.data.materials.append(material)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return ob


def box(name, loc, size, material, rot=(0, 0, 0), bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    ob = obj_from_bm(name, bm, material)
    ob.location = loc
    ob.rotation_euler = Euler(rot)
    if bevel > 0:
        md = ob.modifiers.new("bev", 'BEVEL')
        md.width = bevel
        md.segments = 2
        md.limit_method = 'ANGLE'
    return ob


def cyl(name, loc, r1, r2, depth, seg=16, material=None, rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r1, radius2=r2, depth=depth)
    ob = obj_from_bm(name, bm, material, smooth=True)
    ob.location = loc
    ob.rotation_euler = Euler(rot)
    return ob


def blob(name, loc, r, material, subdiv=3, squash=0.86, jitter=0.08):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r)
    for v in bm.verts:
        v.co *= 1.0 + random.uniform(-jitter, jitter)
        v.co.z *= squash
    ob = obj_from_bm(name, bm, material, smooth=True)
    ob.location = loc
    return ob


def grid_mesh(name, x0, x1, y0, y1, nx, ny, zfn, material=None, smooth=True):
    bm = bmesh.new()
    verts = [[None] * (ny + 1) for _ in range(nx + 1)]
    for i in range(nx + 1):
        for j in range(ny + 1):
            x = x0 + (x1 - x0) * i / nx
            y = y0 + (y1 - y0) * j / ny
            verts[i][j] = bm.verts.new((x, y, zfn(x, y)))
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    bm.normal_update()
    return obj_from_bm(name, bm, material, smooth)


def _faces_up(bm):
    """鋪面是單層平面，法線朝下時 Cycles 會把它算成近黑（實測入口銜接段整片黑）。
    recalc_face_normals 只保證「一致」，不保證朝上，所以逐一檢查 normal.z。"""
    bm.normal_update()
    bad = [f for f in bm.faces if f.normal.z < 0]
    if bad:
        bmesh.ops.reverse_faces(bm, faces=bad)
        bm.normal_update()
    return bm



def flat_ring(name, outer, inner, z, material):
    """外環 + 內環（同點數）→ 帶狀鋪面（步道環）。"""
    n = len(outer)
    bm = bmesh.new()
    ov = [bm.verts.new((x, y, z)) for x, y in outer]
    iv = [bm.verts.new((x, y, z)) for x, y in inner]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((ov[i], ov[j], iv[j], iv[i]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    _faces_up(bm)
    ob = obj_from_bm(name, bm, material, smooth=False)
    return ob


def flat_strip(name, ring, z, material):
    """開放步道：ring = 外側去程 + 內側回程（同點數）→ 四邊形帶 + 兩端封口。"""
    n = len(ring) // 2
    a, b = ring[:n], ring[n:][::-1]
    bm = bmesh.new()
    av = [bm.verts.new((x, y, z)) for x, y in a]
    bv = [bm.verts.new((x, y, z)) for x, y in b]
    for i in range(n - 1):
        bm.faces.new((av[i], av[i + 1], bv[i + 1], bv[i]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    _faces_up(bm)
    return obj_from_bm(name, bm, material, smooth=False)


def flat_poly(name, pts, z, material):
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z)) for x, y in pts]
    try:
        bm.faces.new(vs)
    except ValueError:
        pass
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    _faces_up(bm)
    return obj_from_bm(name, bm, material, smooth=False)


# ------------------------------------------------------------------ 地表
G = P.GRADE
# 鋪面（步道／廣場）是「鋪在整地高程上的面層」，底下要留構造厚度：
# 廊帶內的地表下降 3 cm，鋪面在 +1.2 cm → 實體上分開 4.2 cm。
# 不分開就會與地表共面，Cycles 會出現共面交錯的黑色斑塊（2026-11-07 實測）。
PAVE_LIFT = 0.012
BED_DROP = 0.090


def _terrain_display(x, y):
    z = P.terrain_z(x, y)
    if P.path_offset(x, y) <= 0.0 or P.in_plaza(x, y):
        z -= BED_DROP
    return z


terrain = grid_mesh("01_草地", 0.0, P.SITE_W, 0.0, P.SITE_H, 200, 125,
                    _terrain_display, M_GRASS)

# 周邊：人行道（y -1.10..0）＋道路（y -9..-1.10），與平面圖同一條線
box("01_人行道", (20.0, -0.55, 0.02), (46.0, 1.10, 0.16), M_PLAZA)
box("01_道路", (20.0, -4.60, -0.10), (46.0, 6.90, 0.16), M_ASPHALT)
box("01_路緣石", (20.0, -1.12, 0.06), (46.0, 0.14, 0.20), M_STONE_D)

# ------------------------------------------------------------------ 舖面
for p in P.PATHS:
    ring = P.ribbon(p["pts"], p["width"] / 2.0, closed=p["closed"])
    if p["closed"]:
        n = len(ring) // 2
        flat_ring("10_" + p["code"] + "_步道", ring[:n], ring[n:][::-1], G + PAVE_LIFT, M_PATH)
    else:
        flat_strip("10_" + p["code"] + "_步道", ring, G + PAVE_LIFT, M_PATH)

pr = P.PLAZA_RECT
flat_poly("12_入口廣場", [(pr[0], pr[1]), (pr[2], pr[1]), (pr[2], pr[3]), (pr[0], pr[3])],
          G + PAVE_LIFT, M_PLAZA)
cyl("12_節點廣場", (P.PLAZA_NODE["cx"], P.PLAZA_NODE["cy"], G + PAVE_LIFT),
    P.PLAZA_NODE["r"], P.PLAZA_NODE["r"], 0.02, seg=48, material=M_PLAZA)

# ------------------------------------------------------------------ 水池
po = P.POOL
c = po["coping"]
# 池壁：只在內緣做 5 cm 內襯牆＋池底；**不要**再放與池緣石重疊的大塊牆體
# （重疊面會 z-fighting，實測會渲染成整圈黑塊）。
_wall_top = G + po["coping_h"]
_wall_bot = G - po["depth"]
_wall_h = _wall_top - _wall_bot
_wall_cz = (_wall_top + _wall_bot) / 2
_t = 0.05
box("20_池壁_S", ((po["x0"] + po["x1"]) / 2, po["y0"] + _t / 2, _wall_cz),
    (po["x1"] - po["x0"], _t, _wall_h), M_STONE)
box("20_池壁_N", ((po["x0"] + po["x1"]) / 2, po["y1"] - _t / 2, _wall_cz),
    (po["x1"] - po["x0"], _t, _wall_h), M_STONE)
for i, xx in enumerate((po["x0"] + _t / 2, po["x1"] - _t / 2)):
    box(f"20_池壁_{i}", (xx, (po["y0"] + po["y1"]) / 2, _wall_cz),
        (_t, po["y1"] - po["y0"], _wall_h), M_STONE)
# 池底
box("20_池底", ((po["x0"] + po["x1"]) / 2, (po["y0"] + po["y1"]) / 2, G - po["depth"] - 0.05),
    (po["x1"] - po["x0"], po["y1"] - po["y0"], 0.10), M_STONE_D)
# 水面
flat_poly("21_水面", [(po["x0"] + 0.05, po["y0"] + 0.05), (po["x1"] - 0.05, po["y0"] + 0.05),
                      (po["x1"] - 0.05, po["y1"] - 0.05), (po["x0"] + 0.05, po["y1"] - 0.05)],
          po["water_z"], M_WATER)
# 池緣石（一塊一塊，古樸感）
step = 0.46
nx_ = int(round((po["x1"] - po["x0"]) / step))
for i in range(nx_ + 1):
    xx = po["x0"] + i * (po["x1"] - po["x0"]) / max(nx_, 1)
    for yy in (po["y0"] - c / 2, po["y1"] + c / 2):
        box("22_池緣石", (xx, yy, po["coping_h"] / 2 + G),
            (step * 0.92, c * 0.95, po["coping_h"]), M_STONE,
            rot=(0, 0, random.uniform(-0.01, 0.01)), bevel=0.01)
ny_ = int(round((po["y1"] - po["y0"]) / step))
for j in range(1, ny_):
    yy = po["y0"] + j * (po["y1"] - po["y0"]) / ny_
    for xx in (po["x0"] - c / 2, po["x1"] + c / 2):
        box("22_池緣石", (xx, yy, po["coping_h"] / 2 + G),
            (c * 0.95, step * 0.92, po["coping_h"]), M_STONE,
            rot=(0, 0, random.uniform(-0.02, 0.02)), bevel=0.01)

# 落水牆（景石）＋水幕
sp = po["spout"]
box("22_落水牆", ((sp["x0"] + sp["x1"]) / 2, (sp["y0"] + sp["y1"]) / 2, G + sp["h"] / 2),
    (sp["x1"] - sp["x0"], sp["y1"] - sp["y0"], sp["h"]), M_STONE_D, bevel=0.03)
flat_poly("21_水幕", [(sp["x0"] + 0.10, sp["y0"] + 0.02), (sp["x1"] - 0.10, sp["y0"] + 0.02),
                      (sp["x1"] - 0.10, sp["y0"] + 0.05), (sp["x0"] + 0.10, sp["y0"] + 0.05)],
          G + sp["h"] - 0.10, M_WATER)
box("21_水幕_垂直", ((sp["x0"] + sp["x1"]) / 2, sp["y0"] + 0.03, G + sp["h"] / 2 - 0.02),
    (sp["x1"] - sp["x0"] - 0.20, 0.02, sp["h"] - 0.10), M_WATER)

# 入口景石柱（框出入口動線）
for m in P.MONOLITHS:
    box(f"22_{m['code']}_景石柱", (m["x"], m["y"], G + m["h"] / 2),
        (m["w"], m["d"], m["h"]), M_STONE_D, bevel=0.03)
    box(f"22_{m['code']}_景石柱頂", (m["x"], m["y"], G + m["h"] + 0.02),
        (m["w"] + 0.05, m["d"] + 0.05, 0.04), M_STONE, bevel=0.01)

# 入口景名牆
for i, w in enumerate(P.NAME_WALLS):
    cx = (w["x0"] + w["x1"]) / 2
    box(f"22_景名牆{i+1}", (cx, w["y"], G + w["h"] / 2),
        (w["x1"] - w["x0"], w["thick"], w["h"]), M_STONE, bevel=0.02)
    box(f"22_景名牆{ i+1 }_壓頂", (cx, w["y"], G + w["h"] + 0.03),
        (w["x1"] - w["x0"] + 0.06, w["thick"] + 0.06, 0.06), M_STONE_D, bevel=0.01)

# ------------------------------------------------------------------ 座椅
def stone_bench(code, x, y, ang_deg, z):
    a = math.radians(ang_deg)
    hl, hw = P.BENCH_L / 2, P.BENCH_W / 2
    box(f"41_{code}_板", (x, y, z + P.BENCH_H), (P.BENCH_L, P.BENCH_W, 0.13), M_STONE,
        rot=(0, 0, a), bevel=0.02)
    for u in (-hl + 0.34, hl - 0.34):
        lx = x + u * math.cos(a)
        ly = y + u * math.sin(a)
        box(f"41_{code}_墩", (lx, ly, z + (P.BENCH_H - 0.07) / 2),
            (0.30, P.BENCH_W * 0.78, P.BENCH_H - 0.07), M_STONE_D, rot=(0, 0, a), bevel=0.02)


for b in P.BENCHES:
    stone_bench(b["code"], b["x"], b["y"], b["angle"], P.terrain_z(b["x"], b["y"]))

# ------------------------------------------------------------------ 景觀燈
for l in P.LIGHTS:
    z = P.terrain_z(l["x"], l["y"])
    if l["kind"] == "bole":
        cyl(f"40_{l['code']}_柱", (l["x"], l["y"], z + l["h"] / 2), 0.075, 0.065, l["h"], seg=12,
            material=M_METAL)
        cyl(f"40_{l['code']}_罩", (l["x"], l["y"], z + l["h"] - 0.02), 0.085, 0.085, 0.16, seg=12,
            material=M_GLOW)
        cyl(f"40_{l['code']}_頂", (l["x"], l["y"], z + l["h"] + 0.09), 0.10, 0.06, 0.06, seg=12,
            material=M_METAL)
    else:
        cyl(f"40_{l['code']}_桿", (l["x"], l["y"], z + l["h"] / 2), 0.055, 0.045, l["h"], seg=10,
            material=M_METAL)
        cyl(f"40_{l['code']}_燈頭", (l["x"], l["y"], z + l["h"] + 0.06), 0.20, 0.05, 0.16, seg=12,
            material=M_METAL)
        cyl(f"40_{l['code']}_燈罩", (l["x"], l["y"], z + l["h"] - 0.02), 0.17, 0.17, 0.05, seg=12,
            material=M_GLOW)

# ------------------------------------------------------------------ 喬木
def tree(t):
    x, y = t["x"], t["y"]
    z = P.terrain_z(x, y)
    h, r = t["h"], t["canopy"]
    cyl(f"30_{t['code']}_幹", (x, y, z + h * 0.40), r * 0.085, r * 0.045, h * 0.82, seg=10,
        material=M_TRUNK)
    for _ in range(3):
        a = random.uniform(0, math.tau)
        cyl(f"30_{t['code']}_枝",
            (x + r * 0.16 * math.cos(a), y + r * 0.16 * math.sin(a), z + h * 0.60),
            r * 0.028, r * 0.014, h * 0.30, seg=6, material=M_TRUNK,
            rot=(0, math.radians(random.uniform(24, 40)), a))
    mcan = CANOPY_BY_SPECIES.get(t["sp"], M_CANOPY_A)
    # 一株樹的樹冠合成「單一網格」：Freestyle 只會描外輪廓，
    # 若留成 9 顆獨立球，線稿會把每顆球的交界全畫出來（像線框模型）。
    bm = bmesh.new()
    for i in range(9):
        a = random.uniform(0, math.tau)
        rad = r * (0.72 if i < 4 else 0.42) * random.uniform(0.55, 1.0)
        cx = x + rad * math.cos(a)
        cy = y + rad * math.sin(a)
        cz = z + h * (0.72 + random.uniform(-0.05, 0.16))
        rr = r * random.uniform(0.48, 0.72)
        b2 = bmesh.new()
        bmesh.ops.create_icosphere(b2, subdivisions=3, radius=rr)
        for v in b2.verts:
            v.co *= 1.0 + random.uniform(-0.08, 0.08)
            v.co.z *= 0.80
            v.co += Vector((cx, cy, cz))
        me2 = bpy.data.meshes.new("_tmp")
        b2.to_mesh(me2)
        b2.free()
        bm.from_mesh(me2)
        bpy.data.meshes.remove(me2)
    bm.normal_update()
    obj_from_bm(f"30_{t['code']}_冠", bm, mcan, smooth=True)


for t in P.TREES:
    tree(t)

# ------------------------------------------------------------------ 灌木
count_shrub = 0
for bed_meta, bed in P.SHRUB_POLYS:
    xs = [q[0] for q in bed]
    ys = [q[1] for q in bed]
    x = min(xs) + 0.4
    while x < max(xs):
        y = min(ys) + 0.4
        while y < max(ys):
            jx = x + random.uniform(-0.22, 0.22)
            jy = y + random.uniform(-0.22, 0.22)
            if P.point_in_polygon(jx, jy, bed):
                z = P.terrain_z(jx, jy)
                rr = random.uniform(0.40, 0.62)
                blob(f"31_{bed_meta['code']}_灌木", (jx, jy, z + rr * 0.50), rr, M_SHRUB,
                     subdiv=2, squash=0.72, jitter=0.10)
                count_shrub += 1
            y += 0.72
        x += 0.72

# ------------------------------------------------------------------ 地形微物：汀步石（草丘上）
for i in range(5):
    a = -0.6 + i * 0.30
    px = 17.6 + math.cos(a) * 4.2
    py = 14.6 + math.sin(a) * 3.4
    cyl(f"32_汀步{i}", (px, py, P.terrain_z(px, py) + 0.03), 0.30, 0.28, 0.07, seg=10,
        material=M_STONE)

# ------------------------------------------------------------------ 光照
world = bpy.data.worlds.new("W_天空")
scene.world = world
world.use_nodes = True
nt = world.node_tree
for n in list(nt.nodes):
    if n.type != 'OUTPUT_WORLD':
        nt.nodes.remove(n)
out = [n for n in nt.nodes if n.type == 'OUTPUT_WORLD'][0]

# 天空分成「相機看到的顏色」與「照明用的環境光」兩路：
# 直接用 Sky Texture 打光會過曝（Nishita 亮度極高），所以相機路徑壓低強度、
# 照明走路徑用低強度的淡藍灰——這也是水彩天空該有的低對比。
# 相機看到的天空：垂直漸層（手工灰藍→米白），像水彩紙上的天空留白
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
mr = nt.nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value = -0.08
mr.inputs["From Max"].default_value = 0.55
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.80, 0.845, 0.875, 1.0)
ramp.color_ramp.elements[1].position = 1.0
ramp.color_ramp.elements[1].color = (0.56, 0.68, 0.82, 1.0)
nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])

bg_cam = nt.nodes.new("ShaderNodeBackground")
bg_cam.inputs["Strength"].default_value = 1.0
nt.links.new(ramp.outputs["Color"], bg_cam.inputs["Color"])

bg_amb = nt.nodes.new("ShaderNodeBackground")
bg_amb.inputs["Color"].default_value = (0.60, 0.70, 0.82, 1.0)
bg_amb.inputs["Strength"].default_value = 0.85
mix = nt.nodes.new("ShaderNodeMixShader")
lp = nt.nodes.new("ShaderNodeLightPath")
nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
nt.links.new(bg_amb.outputs["Background"], mix.inputs[1])
nt.links.new(bg_cam.outputs["Background"], mix.inputs[2])
nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])

sun_d = bpy.data.lights.new("L_陽光", type='SUN')
sun_d.energy = 1.55
sun_d.angle = math.radians(3.2)          # 大角度＝柔和陰影，手繪感需要軟陰影
sun_d.color = (1.0, 0.965, 0.905)
sun = bpy.data.objects.new("L_陽光", sun_d)
bpy.context.collection.objects.link(sun)
sun.rotation_euler = Euler((math.radians(52), 0.0, math.radians(-38)))
sun.location = (-14, -14, 18)

fill_d = bpy.data.lights.new("L_補光", type='AREA')
fill_d.energy = 180.0
fill_d.size = 24.0
fill_d.color = (0.82, 0.89, 1.0)
fill = bpy.data.objects.new("L_補光", fill_d)
bpy.context.collection.objects.link(fill)
fill.location = (26, -12, 14)
fill.rotation_euler = Euler((math.radians(56), 0, math.radians(28)))


# ------------------------------------------------------------------ 相機
def make_cam(name, loc, target, lens=32.0):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    ob = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(ob)
    for old in [o for o in bpy.data.objects if o.name.startswith(name + ".")]:
        bpy.data.objects.remove(old, do_unlink=True)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return ob


cam_main = make_cam("CAM_主視角", (42.5, -13.5, 6.4), (18.0, 9.5, 1.3), 40.0)
cam_entry = make_cam("CAM_入口近景", (19.2, -6.6, 1.62), (20.15, 3.4, 0.80), 42.0)
cam_air = make_cam("CAM_鳥瞰", (50.0, -21.0, 21.0), (19.5, 11.0, 0.6), 34.0)
cam_hill = make_cam("CAM_丘頂視角", (18.2, 15.6, 2.90), (21.5, 2.0, 0.30), 34.0)

# ------------------------------------------------------------------ 渲染設定
scene.render.engine = 'CYCLES'
cy = scene.cycles
DEV = opt("device", "cpu")
if DEV in ("auto", "gpu", "cuda"):
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = 'CUDA'
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == 'CUDA']
        if gpus:
            for d in prefs.devices:
                d.use = (d.type == 'CUDA')
            cy.device = 'GPU'
            print("[park_scene] GPU 渲染：", [d.name for d in gpus])
        else:
            cy.device = 'CPU'
    except Exception as exc:
        print("[park_scene] GPU 不可用，改用 CPU：", exc)
        cy.device = 'CPU'
if DEV in ("cpu",):
    cy.device = 'CPU'

cy.samples = 110
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.015
cy.use_denoising = True
cy.max_bounces = 4
cy.diffuse_bounces = 2
cy.glossy_bounces = 2
cy.transmission_bounces = 2
cy.time_limit = 240.0

scene.render.resolution_x = 1800
scene.render.resolution_y = 1012
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.image_settings.color_depth = '8'
scene.view_settings.view_transform = 'AgX'
scene.view_settings.exposure = 0.05
for cand in ('AgX - Medium High Contrast', 'AgX - Punchy', 'None'):
    try:
        scene.view_settings.look = cand
        break
    except Exception:
        continue

# ---- Freestyle 線稿（手繪感的骨架）----
# 樹冠是「多顆球堆疊」，用 silhouette 會把每顆球的分界都畫出來（看起來像線框模型）。
# 所以分兩組線稿：硬景（牆、池、燈、椅、鋪面）畫輪廓＋轉折；樹冠只畫「邊界」。
scene.render.use_freestyle = False
vl = scene.view_layers[0]
vl.use_freestyle = False

fs = vl.freestyle_settings
fs.crease_angle = math.radians(100)
fs.use_culling = True
for ls in list(fs.linesets):
    fs.linesets.remove(ls)
ls = fs.linesets.new("線稿")
ls.select_silhouette = True
ls.select_border = True
ls.select_crease = True
ls.select_edge_mark = False
ls.select_contour = False
ls.linestyle.color = (0.16, 0.14, 0.13)
ls.linestyle.thickness = 1.55

try:
    scene.render.use_persistent_data = True
except Exception:
    pass

# ------------------------------------------------------------------ 出圖
VIEWS = [("main", cam_main, f"{NAME}_3D_主視角.png"),
         ("entry", cam_entry, f"{NAME}_3D_入口近景.png"),
         ("aerial", cam_air, f"{NAME}_3D_鳥瞰.png"),
         ("hill", cam_hill, f"{NAME}_3D_丘頂視角.png")]
if ONLY:
    VIEWS = [v for v in VIEWS if v[0] in ONLY]

if PREVIEW:
    scene.render.resolution_x, scene.render.resolution_y = 720, 405
    cy.samples = 24
    cy.time_limit = 90.0
    if not ONLY:
        VIEWS = VIEWS[:1]

BLEND = os.path.join(OUT, f"{NAME}_3D場景.blend")
try:
    bpy.context.preferences.filepaths.save_version = 0     # 不要在交付夾留 .blend1
except Exception:
    pass
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
ARTIFACTS.append(BLEND)

renders = []
for key, cam, fname in VIEWS:
    if PREVIEW:
        fname = "PREVIEW_" + fname
    scene.camera = cam
    path = os.path.join(OUT, fname)
    scene.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as exc:
        # GB10 的 CUDA 13 與本版 Blender 的 CUDA 核心不相容（編譯失敗），自動退回 CPU，
        # 不要讓一個 GPU 問題把整批出圖廢掉。
        print("[park_scene] GPU 失敗，改 CPU 重試：", str(exc)[:160])
        cy.device = 'CPU'
        RESULT["device_fallback"] = "CUDA 編譯失敗，改用 CPU"
        bpy.ops.render.render(write_still=True)
    renders.append({"view": key, "file": fname, "path": path,
                    "bytes": os.path.getsize(path) if os.path.exists(path) else -1})
    ARTIFACTS.append(path)
    print("[park_scene] 完成", fname)

faces = sum(len(o.data.polygons) for o in bpy.data.objects if o.type == 'MESH')
q = P.quantities()
RESULT = {
    "out_dir": OUT,
    "blend": BLEND,
    "renders": renders,
    "objects": len(bpy.data.objects),
    "faces": faces,
    "shrubs": count_shrub,
    "trees": len(P.TREES),
    "lights": len(P.LIGHTS),
    "benches": len(P.BENCHES),
    "grade_m": P.GRADE,
    "mound_peak_m": round(P.GRADE + max(m["h"] for m in P.MOUNDS), 2),
    "site_m": [P.SITE_W, P.SITE_H],
    "path_width_m": P.PATH_W_MAIN,
    "pool_water_z_m": round(P.POOL["water_z"], 3),
    "quantities": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in q.items()},
    "engine": scene.render.engine,
    "device": cy.device,
    "samples": cy.samples,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "freestyle": False,
}
print("RESULT:", json.dumps(RESULT, ensure_ascii=False, indent=1))
with open(os.path.join(OUT, "_park_scene_result.json"), "w", encoding="utf-8") as fh:
    json.dump(dict(result=RESULT, artifacts=ARTIFACTS), fh, ensure_ascii=False, indent=1)
