# -*- coding: utf-8 -*-
"""路旁避車彎 3D 景觀模擬（單位：公尺，Z 向上）

版面（-Y = 近側（車道外側）、+Y = 靠坡側；X 沿道路方向，+X 往東）：
  近側草坡      y < -4.50
  主線車道      y = -4.50 ~ 0.00（單車道 4.5 m，貫通不中斷）
  避車彎        x = 2.0~7.0 向坡側加寬 3.20 m；前後漸變段各 5.0 m（S 曲線）
  路緣石        沿避車彎輪廓，寬 0.20、高 0.20（路側唯一混凝土構造，本圖無擋土牆）
  路側綠帶      緣石背 1.00 m（0.20 + 1.00 = 1.20 ＝原圖「1.2M」路側淨寬）
  植生邊坡      自坡趾水平 9.5 m，爬升 0.12 → 5.30
  平台／涼亭    y > crest，z = 5.30
  停放車輛      4.6 x 1.88 m，平行道路，車頭朝 -X（與行車方向箭頭一致）
"""
import bpy, bmesh, math, random, os, sys, json
from mathutils import Vector, Euler, Matrix, noise

# 輸出路徑一律由 tools/project_paths.py 解析（AGENTS.md §3：不得寫死磁碟絕對路徑）
# ⚠ blender_runner 會把本腳本複製到 _temp\blender\<ts>_<script>\user_script.py 再 exec，
#   __file__ 因此指向複本而非 tools\landscape3d\，固定層數的 dirname 會失效
#   （曾出現 ModuleNotFoundError: No module named 'project_paths'）。
#   改為由 __file__ 與 cwd 向上逐層找 project_paths.py，並支援 CIVIL_AI_ROOT。
def _find_tools_dir():
    roots = []
    env_root = os.environ.get("CIVIL_AI_ROOT")
    if env_root:
        roots.append(env_root)
    for start in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        cur = start
        for _ in range(6):
            roots.append(cur)
            cur = os.path.dirname(cur)
    for r in roots:
        for c in (r, os.path.join(r, "tools")):
            if os.path.isfile(os.path.join(c, "project_paths.py")):
                return c
    return None


_TOOLS = _find_tools_dir()
if _TOOLS and _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
try:
    from project_paths import out_dir  # noqa: E402
    _DEFAULT_OUT = str(out_dir("路旁避車彎_3D"))
except Exception:  # 找不到 tools\project_paths.py 時退回專案根目錄相對路徑
    _DEFAULT_OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "out", "路旁避車彎_3D"))

# 參數覆寫：優先 ARGS（blender_runner 的 --arg），其次環境變數。
# MSIX 封裝啟動的 Blender 收不到呼叫端的 $env:，命令列 --arg 才是可靠通道。
_ARGV = globals().get("ARGS") or {}


def _opt(name, default=""):
    v = _ARGV.get(name)
    if v in (None, ""):
        v = os.environ.get(name)
    return default if v in (None, "") else v


OUT = str(_opt("BAY_OUT") or _DEFAULT_OUT)
os.makedirs(OUT, exist_ok=True)
random.seed(20261106)
ARTIFACTS = []

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1.0

# ----------------------------------------------------------------- 材質
def _bsdf(m):
    return m.node_tree.nodes["Principled BSDF"]

def setin(bsdf, key, val):
    if key in bsdf.inputs:
        bsdf.inputs[key].default_value = val

def s2l(c):
    """把「螢幕上看到的顏色」轉成線性值。Blender 的 Base Color 是線性的，
    直接填 0.40 的灰在畫面上會變成近白的 0.67，導致整張圖過曝發粉白。"""
    def f(u):
        u = max(0.0, min(1.0, float(u)))
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    return tuple(f(u) for u in c)

def mat(name, base=(0.5, 0.5, 0.5), rough=0.8, metal=0.0, var=None,
        bump=0.0, scale=9.0, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = _bsdf(m)
    base = s2l(base)
    var = s2l(var) if var else None
    setin(bsdf, "Base Color", (*base, 1.0))
    setin(bsdf, "Roughness", rough)
    setin(bsdf, "Metallic", metal)
    setin(bsdf, "Specular IOR Level", spec)
    if var:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = scale
        tex.inputs["Detail"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*base, 1.0)
        ramp.color_ramp.elements[1].color = (*var, 1.0)
        nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if bump:
        t2 = nt.nodes.new("ShaderNodeTexNoise")
        t2.inputs["Scale"].default_value = scale * 7.0
        t2.inputs["Detail"].default_value = 8.0
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = bump
        nt.links.new(t2.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    return m

def foliage_mat(name, c1, c2, c3=None, rough=0.85, bump=0.25):
    """以 Object Info > Random 讓每個物件取不同色調，避免一整片同色。"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = _bsdf(m)
    setin(bsdf, "Roughness", rough)
    c1, c2, c3 = s2l(c1), s2l(c2), s2l(c3 or c2)
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = 0.0, (*c1, 1.0)
    el[1].position, el[1].color = 1.0, (*c3, 1.0)
    mid = el.new(0.5)
    mid.color = (*c2, 1.0)
    nt.links.new(oi.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if bump:
        t2 = nt.nodes.new("ShaderNodeTexNoise")
        t2.inputs["Scale"].default_value = 55.0
        t2.inputs["Detail"].default_value = 8.0
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = bump
        nt.links.new(t2.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    return m

# 以下色值一律填「畫面上看到的顏色」（sRGB），由 s2l() 轉線性
M_ASPHALT = mat("M_瀝青", (0.34, 0.335, 0.325), 0.92, var=(0.42, 0.415, 0.405), bump=0.12, scale=3.0)
M_LINE    = mat("M_標線", (0.93, 0.93, 0.90), 0.55)
M_CONC    = mat("M_混凝土", (0.80, 0.78, 0.73), 0.85, var=(0.88, 0.86, 0.81), bump=0.25, scale=4.0)
M_BUFFER  = mat("M_緩衝帶", (0.56, 0.51, 0.41), 0.95, var=(0.68, 0.63, 0.52), bump=0.4, scale=12.0)
M_GRASS   = mat("M_草坡", (0.33, 0.45, 0.19), 0.88, var=(0.45, 0.56, 0.25), bump=0.45, scale=6.0)
M_GRASS2  = mat("M_草地", (0.30, 0.42, 0.17), 0.88, var=(0.40, 0.51, 0.22), bump=0.35, scale=5.0)
M_CANOPY  = foliage_mat("M_樹冠", (0.19, 0.35, 0.14), (0.27, 0.44, 0.18), (0.35, 0.51, 0.22))
M_CANOPY2 = foliage_mat("M_樹冠淺", (0.29, 0.43, 0.17), (0.39, 0.51, 0.20), (0.48, 0.57, 0.24))
M_HEDGE   = foliage_mat("M_灌木", (0.17, 0.31, 0.12), (0.23, 0.39, 0.15), (0.31, 0.45, 0.18), bump=0.3)
M_FLOWER_R = foliage_mat("M_紅花", (0.78, 0.20, 0.23), (0.87, 0.31, 0.32), (0.93, 0.47, 0.44))
M_FLOWER_P = foliage_mat("M_粉花", (0.87, 0.46, 0.52), (0.93, 0.61, 0.64), (0.97, 0.77, 0.76))
M_TRUNK   = mat("M_樹幹", (0.30, 0.21, 0.15), 0.90, var=(0.42, 0.31, 0.22), bump=0.3, scale=18.0)
M_STONE   = mat("M_石材", (0.72, 0.70, 0.65), 0.82, var=(0.84, 0.82, 0.77), bump=0.3, scale=6.0)
M_WOOD    = mat("M_木構", (0.45, 0.26, 0.16), 0.75, var=(0.58, 0.36, 0.22), bump=0.2, scale=10.0)
M_RED     = mat("M_柱紅", (0.60, 0.11, 0.10), 0.60)
M_ROOF    = mat("M_屋瓦", (0.62, 0.45, 0.24), 0.70, var=(0.74, 0.56, 0.32), bump=0.15, scale=14.0)
M_BODY    = mat("M_車身", (0.90, 0.90, 0.89), 0.33, metal=0.25,
                var=(0.86, 0.86, 0.85), scale=2.0)
M_GLASS   = mat("M_玻璃", (0.15, 0.175, 0.20), 0.16, metal=0.25)
M_LAMP    = mat("M_車燈", (0.86, 0.87, 0.86), 0.14, metal=0.30)
M_TIRE    = mat("M_輪胎", (0.10, 0.10, 0.11), 0.92)
# 亮銀 0.78/metal 0.9 會把天空與草坡全反射成鏡面球（實測像玩具），改霧面鋁灰
M_HUB     = mat("M_鋁圈", (0.46, 0.47, 0.49), 0.55, metal=0.45)
M_DARK    = mat("M_深色件", (0.10, 0.10, 0.11), 0.55)
M_HILL    = mat("M_遠山", (0.55, 0.66, 0.62), 0.95, var=(0.64, 0.73, 0.69), scale=3.0)
M_HILL2   = mat("M_遠山2", (0.66, 0.75, 0.72), 0.95, var=(0.73, 0.80, 0.77), scale=2.5)

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

def box(name, loc, size, material=None, rot=(0.0, 0.0, 0.0), bevel=0.0):
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
        md.segments = 3
        md.limit_method = 'ANGLE'
    return ob

def cyl(name, loc, r1, r2, depth, seg=16, material=None, rot=(0.0, 0.0, 0.0), smooth=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r1, radius2=r2, depth=depth)
    ob = obj_from_bm(name, bm, material, smooth)
    ob.location = loc
    ob.rotation_euler = Euler(rot)
    return ob

def blob(name, loc, r, material, subdiv=2, squash=1.0, jitter=0.22, scale_z=None):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r)
    for v in bm.verts:
        v.co *= 1.0 + random.uniform(-jitter, jitter)
        v.co.z *= squash
    ob = obj_from_bm(name, bm, material, smooth=True)
    ob.location = loc
    if scale_z:
        ob.scale = (1.0, 1.0, scale_z)
    return ob

def grid_mesh(name, x0, x1, y0, y1, nx, ny, zfn, material=None, smooth=True):
    bm = bmesh.new()
    verts = [[None] * (ny + 1) for _ in range(nx + 1)]
    for i in range(nx + 1):
        for j in range(ny + 1):
            u, v = i / nx, j / ny
            x = x0 + (x1 - x0) * u
            y = y0 + (y1 - y0) * v
            verts[i][j] = bm.verts.new((x, y, zfn(x, y)))
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    bm.normal_update()
    return obj_from_bm(name, bm, material, smooth)

def nz(x, y, s=0.3, seed=0.0):
    return noise.noise(Vector((x * s + seed, y * s + seed, seed * 0.37)))

def make_tree(x, y, z, h=6.5, canopy_r=2.1, seed=0, mat_canopy=None, thin=False):
    random.seed(seed)
    tr = 0.085 if thin else 0.135
    cyl("30_樹幹", (x, y, z + h * 0.42), tr * h / 6.0, tr * 0.42 * h / 6.0, h * 0.84, seg=10, material=M_TRUNK)
    # 少數分枝
    for _ in range(2 if thin else 3):
        a = random.uniform(0, math.tau)
        cyl("30_分枝", (x + 0.11 * h * math.cos(a), y + 0.11 * h * math.sin(a), z + h * 0.62),
            0.055, 0.03, h * 0.35, seg=6, material=M_TRUNK,
            rot=(0, math.radians(random.uniform(22, 42)), a))
    mc = mat_canopy or M_CANOPY
    n = 4 if thin else random.randint(6, 9)
    for i in range(n):
        a = random.uniform(0, math.tau)
        rad = random.uniform(0.0, canopy_r * 0.72)
        cz = z + h * (0.72 + random.uniform(-0.10, 0.22))
        blob("31_樹冠", (x + rad * math.cos(a), y + rad * math.sin(a), cz),
             canopy_r * random.uniform(0.42, 0.68), mc, subdiv=2, squash=0.82, jitter=0.26)

def pavilion(x0, y0, z0):
    base_r, col_h = 2.20, 2.85
    seg = 6
    rot0 = math.radians(30)
    cyl("60_涼亭台基", (x0, y0, z0 + 0.16), base_r + 0.55, base_r + 0.55, 0.32, seg=seg,
        material=M_STONE, rot=(0, 0, rot0))
    # 台階（朝道路側，-Y）
    for k in range(3):
        box("60_台階", (x0, y0 - (base_r + 0.55) - 0.22 - k * 0.34, z0 + 0.13 - k * 0.055),
            (3.0, 0.36, 0.26 - k * 0.06), M_STONE, bevel=0.02)
    zc = z0 + 0.32
    for k in range(seg):
        a = rot0 + math.radians(360.0 * k / seg)
        cyl("61_亭柱", (x0 + base_r * math.cos(a), y0 + base_r * math.sin(a), zc + col_h / 2),
            0.115, 0.105, col_h, seg=12, material=M_RED)
    # 柱間欄杆
    for k in range(seg):
        a1 = rot0 + math.radians(360.0 * k / seg)
        a2 = rot0 + math.radians(360.0 * (k + 1) / seg)
        mx = x0 + base_r * (math.cos(a1) + math.cos(a2)) / 2
        my = y0 + base_r * (math.sin(a1) + math.sin(a2)) / 2
        ang = math.atan2(math.sin(a2) - math.sin(a1), math.cos(a2) - math.cos(a1))
        L = 2 * base_r * math.sin(math.radians(30))
        if k != 2:  # 留一面作為入口
            box("62_欄杆", (mx, my, zc + 0.52), (L * 0.94, 0.07, 0.09), M_WOOD,
                rot=(0, 0, ang), bevel=0.01)
    # 簷口（額枋）
    cyl("63_額枋", (x0, y0, zc + col_h + 0.10), base_r + 0.26, base_r + 0.26, 0.20, seg=seg,
        material=M_WOOD, rot=(0, 0, rot0))
    # 屋頂（六角攢尖，帶反曲）
    zr = zc + col_h + 0.20
    rings = [(3.15, 0.00), (2.95, 0.30), (2.55, 0.66), (2.00, 1.00),
             (1.35, 1.28), (0.70, 1.46), (0.10, 1.56)]
    bm = bmesh.new()
    loops = []
    for rad, dz in rings:
        ring = []
        for k in range(seg):
            a = rot0 + math.radians(360.0 * k / seg) + math.radians(30)
            ring.append(bm.verts.new((x0 + rad * math.cos(a), y0 + rad * math.sin(a), zr + dz)))
        loops.append(ring)
    for i in range(len(loops) - 1):
        for k in range(seg):
            k2 = (k + 1) % seg
            bm.faces.new((loops[i][k], loops[i][k2], loops[i + 1][k2], loops[i + 1][k]))
    bm.normal_update()
    obj_from_bm("64_屋頂", bm, M_ROOF, smooth=True)
    # 屋脊紅邊
    cyl("65_屋簷", (x0, y0, zr + 0.03), 3.17, 3.10, 0.10, seg=seg, material=M_RED, rot=(0, 0, rot0))
    # 寶頂
    cyl("66_寶頂桿", (x0, y0, zr + 1.66), 0.035, 0.02, 0.30, seg=8, material=M_RED)
    blob("66_寶頂", (x0, y0, zr + 1.86), 0.16, M_RED, subdiv=2, jitter=0.1)
    # 亭前花台
    for _ in range(70):
        a = random.uniform(0, math.tau)
        rad = random.uniform(base_r + 0.4, base_r + 2.6)
        px, py = x0 + rad * math.cos(a) * 0.9, y0 + rad * math.sin(a) * 0.75 - 0.6
        if py < y0 - 3.2:
            continue
        blob("67_花台", (px, py, plateau_z(px, py) + 0.16), random.uniform(0.12, 0.26),
             random.choice([M_FLOWER_R, M_FLOWER_P, M_HEDGE]), subdiv=1, jitter=0.2)

def suv(cx, cy, yaw=0.0):
    L, W = 4.60, 1.88
    def place(ob, tilt=0.0):
        lx, ly, lz = ob.location
        # 必須「疊加」而非覆寫：cyl() 已設好的軸向旋轉（輪胎繞 X 轉 90°）
        # 若在這裡直接指派 Euler 會被蓋掉，輪胎就變成水平圓盤、整圈看不見（實測踩雷）
        m = ob.rotation_euler.to_matrix().to_4x4()
        if tilt:
            m = Matrix.Rotation(tilt, 4, 'Y') @ m
        ob.rotation_euler = (Matrix.Rotation(yaw, 4, 'Z') @ m).to_euler()
        ob.location = (cx + lx * math.cos(yaw) - ly * math.sin(yaw),
                       cy + lx * math.sin(yaw) + ly * math.cos(yaw),
                       lz)
        return ob
    # 車身
    body = box("70_車身", (0, 0, 0.74), (L, W, 0.60), M_BODY, bevel=0.16)
    place(body)
    # 車室（前擋斜、後窗略斜）
    bm = bmesh.new()
    # 車室後緣須逼近車尾（SUV 是廂式車身）；原本只到 -0.30L，後方留 0.98 m 平台，
    # 讀起來像皮卡貨斗 —— 這是「看起來不像休旅車」的主因
    bx_f, bx_r = L * 0.272, -L * 0.355
    tx_f, tx_r = bx_f - 0.36, bx_r + 0.16
    base_z, top_z = 1.02, 1.60
    by, ty = W * 0.472, W * 0.430
    co = [(bx_r, -by, base_z), (bx_f, -by, base_z), (bx_f, by, base_z), (bx_r, by, base_z),
          (tx_r, -ty, top_z), (tx_f, -ty, top_z), (tx_f, ty, top_z), (tx_r, ty, top_z)]
    vs = [bm.verts.new(c) for c in co]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    for f in faces:
        bm.faces.new([vs[i] for i in f])
    bm.normal_update()
    cab = obj_from_bm("71_車室", bm, M_BODY)
    cab.modifiers.new("bev", 'BEVEL').width = 0.05
    cab.modifiers["bev"].segments = 2
    place(cab)
    # 玻璃（貼合車室斜面；tilt 由幾何反算，再隨 yaw 一起轉到世界座標）
    ws_t = math.atan2(bx_f - tx_f, top_z - base_z)
    ws_len = math.hypot(tx_f - bx_f, top_z - base_z) + 0.03
    place(box("72_前擋", ((bx_f + tx_f) / 2, 0, (base_z + top_z) / 2 + 0.005),
              (0.03, ty * 1.94, ws_len), M_GLASS), tilt=-ws_t)
    rw_t = math.atan2(tx_r - bx_r, top_z - base_z)
    rw_len = (math.hypot(tx_r - bx_r, top_z - base_z) + 0.03) * 0.74
    # 後窗須比車室窄、且不佔滿整個高度，否則整片深色會讀成廂型車尾門
    rw_f = 0.50
    place(box("74_後窗", (bx_r + rw_f * (tx_r - bx_r), 0, base_z + rw_f * (top_z - base_z) + 0.005),
              (0.03, ty * 1.35, rw_len), M_GLASS), tilt=rw_t)
    # 側窗改成貼合車室側面的四邊形；原本用長方體再硬拉頂點，前緣會縮到 A 柱後方
    # 留下大片白色三角，且上緣浮出車室斜面
    for s in (-1, 1):
        gb = bmesh.new()
        # 側窗後緣不貼到車室後緣：留一段車色 C 柱／後側板，否則整條深色玻璃
        # 一路拉到車尾，遠看就是廂型車或長軸旅行車（實測踩雷）
        gx_r = max(bx_r + 0.10, -1.16)
        corners = [(bx_f - 0.10, s * (by + 0.006), base_z + 0.05),
                   (gx_r, s * (by + 0.006), base_z + 0.05),
                   (gx_r + 0.06, s * (ty + 0.010), top_z - 0.07),
                   (tx_f - 0.06, s * (ty + 0.010), top_z - 0.07)]
        gv = [gb.verts.new(c) for c in corners]
        gb.faces.new(gv)
        gb.normal_update()
        place(obj_from_bm("73_側窗", gb, M_GLASS))
        # B／C 柱：側窗若是一整條連續深色帶，整台車會讀成廂型車或加長禮車；
        # 加兩道細柱把側窗切成三片，才像休旅車
        # 車柱用車色、加寬到 0.13 m：深色細柱在玻璃上會讀成浮起的小黑塊，
        # 車色寬柱才讀得出「三片側窗」
        for _pxx in (0.02, -1.00):
            place(box("73_車柱", (_pxx, s * (ty + 0.010), (base_z + top_z) / 2),
                      (0.13, 0.03, top_z - base_z - 0.10), M_BODY))
    # 車頂行李架
    for s in (-1, 1):
        place(box("75_行李架", (-0.30, s * W * 0.34, top_z + 0.026), (1.55, 0.07, 0.05), M_DARK))
    # 後照鏡＋下裙
    for s in (-1, 1):
        # 後照鏡要落在 A 柱根部腰線上；原 x=0.92 在車窗中段，看起來像浮在玻璃上
        place(box("75_後照鏡臂", (1.31, s * (W * 0.50), 1.11), (0.05, 0.12, 0.04), M_DARK))
        place(box("75_後照鏡", (1.32, s * (W * 0.545), 1.115), (0.09, 0.15, 0.10), M_BODY, bevel=0.02))
    # 側裙（窄條、略突出車身，避免被車身包住看不到）
    place(box("70_下裙", (0, 0, 0.44), (L * 0.88, W * 1.010, 0.10), M_DARK, bevel=0.02))
    # 車門接縫、把手、尾門接縫（避免車側大片素白）
    for s in (-1, 1):
        for sx in (0.34, -0.30, -0.96):
            place(box("70_車門縫", (sx, s * (W / 2 + 0.004), 0.80),
                      (0.012, 0.022, 0.45), M_DARK))
        place(box("70_把手", (0.06, s * (W / 2 + 0.016), 0.95),
                  (0.21, 0.034, 0.05), M_DARK, bevel=0.008))
        # 前葉子板折線
        place(box("70_折線", (L * 0.40, s * (W / 2 + 0.003), 0.72),
                  (0.014, 0.02, 0.34), M_DARK))
    place(box("70_尾門縫", (-L * 0.497, 0, 1.00), (0.018, W * 0.86, 0.016), M_DARK))
    # 輪胎＋鋁圈
    for sx in (-1, 1):
        for sy in (-1, 1):
            px, py = sx * L * 0.315, sy * (W / 2 - 0.075)
            # 輪拱陰影：無輪拱開口的素色車側會讀成廂型車，用一圈深色盤假造開口
            place(cyl("76_輪拱", (px, sy * (W / 2 + 0.001), 0.36), 0.425, 0.425, 0.012, seg=20,
                      material=M_DARK, rot=(math.radians(90), 0, 0)))
            place(cyl("76_輪胎", (px, py, 0.36), 0.36, 0.36, 0.25, seg=20, material=M_TIRE,
                      rot=(math.radians(90), 0, 0)))
            # 鋁圈外緣須凸出胎面 3 cm，否則與胎側共面會 z-fighting（實測會整顆變黑）
            # 鋁圈半徑原本 0.235（胎半徑的 65%），加上高反射材質 → 整顆讀成銀色球
            place(cyl("77_鋁圈", (px, py + sy * 0.105, 0.36), 0.160, 0.160, 0.06, seg=16,
                      material=M_HUB, rot=(math.radians(90), 0, 0)))
    # 燈組
    for s in (-1, 1):
        place(box("78_頭燈", (L * 0.49, s * 0.60, 0.88), (0.06, 0.42, 0.16), M_LAMP))
        place(box("79_尾燈", (-L * 0.49, s * 0.66, 0.92), (0.05, 0.30, 0.26), M_FLOWER_R))
    place(box("80_水箱護罩", (L * 0.505, 0, 0.70), (0.04, 1.30, 0.20), M_DARK))
    place(box("80_前保桿", (L * 0.49, 0, 0.42), (0.09, 1.70, 0.22), M_DARK, bevel=0.03))
    place(box("80_後保桿", (-L * 0.49, 0, 0.42), (0.09, 1.70, 0.22), M_DARK, bevel=0.03))
    place(box("81_車牌", (L * 0.50, 0, 0.44), (0.02, 0.34, 0.14), M_LINE))
    # 車底不再放暗板：那塊平板會露出車身外、讀成黑色托盤（實測踩雷），
    # 落地陰影交給燈光與地面材質

# ===================================================== 版面常數（避車彎）
# -Y = 近側（車道外側）；+Y = 靠坡側；X 沿道路方向
Y_LANE_FRONT = -4.50          # 車道外側（近側）邊線
LANE_W = 4.50                 # 主線車道淨寬（貫通不中斷）
BAY_DEPTH = 3.20              # 避車彎向坡側加寬深度
BAY_X0, BAY_X1 = 2.00, 7.00   # 避車彎全深段 5.0 m
TAPER = 5.00                  # 前後漸變段（S 曲線）各 5.0 m
CURB_W, CURB_H = 0.20, 0.20   # 路緣石：高 20 cm，路側唯一的混凝土構造（無擋土牆）
VERGE_W = 1.00                # 路側綠帶（緣石背至坡趾）
                              #   緣石 0.20 + 綠帶 1.00 = 1.20 m ＝原圖「1.2M」淨寬
TOE_Z = 0.12                  # 坡趾起坡高程（綠帶面略高於路面，坡面由此起算）
SLOPE_W = 9.50
Z_TOP = 5.30
CAR_X, CAR_Y = 4.50, 1.62
X_A, X_B = -60.0, 60.0


def sstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def bay_edge(x):
    """車道靠坡側邊線的 y：0 = 無避車彎，BAY_DEPTH = 避車彎全深。"""
    if x <= BAY_X0 - TAPER or x >= BAY_X1 + TAPER:
        return 0.0
    if x < BAY_X0:
        return BAY_DEPTH * sstep((x - (BAY_X0 - TAPER)) / TAPER)
    if x <= BAY_X1:
        return BAY_DEPTH
    return BAY_DEPTH * (1.0 - sstep((x - BAY_X1) / TAPER))


def toe_y(x):
    """坡趾 y：路緣石背 + 路側綠帶（＝路面邊線外 1.20 m）。"""
    return bay_edge(x) + CURB_W + VERGE_W


def crest(x):
    return toe_y(x) + SLOPE_W


def road_z(x, y):
    w = max(1.0, bay_edge(x) - Y_LANE_FRONT)
    t = (y - Y_LANE_FRONT) / w
    return -0.018 * t * t + 0.004 * nz(x, y, 2.0, 3.0)


def verge_z(x, y):
    t = min(1.0, max(0.0, (Y_LANE_FRONT - y) / 8.0))
    return -0.06 - 1.5 * t * t + 0.05 * nz(x, y, 0.5, 1.0)


def slope_z(x, y):
    v = (y - toe_y(x)) / SLOPE_W
    v = max(0.0, min(1.0, v))
    return TOE_Z + (Z_TOP - TOE_Z) * (v ** 1.12) + 0.13 * nz(x, y, 0.35, 5.0) * (1.0 - 0.3 * v)


def plateau_z(x, y):
    return Z_TOP + 0.22 * nz(x, y, 0.12, 8.0)


def band(name, xs, nv, ylo, yhi, zfn, material, smooth=True):
    """沿 X 掃掠的曲面帶：每一站 x 的 y 由 ylo(x)..yhi(x) 內插 nv 段。"""
    bm = bmesh.new()
    rows = []
    for x in xs:
        y0, y1 = ylo(x), yhi(x)
        row = [bm.verts.new((x, y0 + (y1 - y0) * (j / float(nv)),
                             zfn(x, y0 + (y1 - y0) * (j / float(nv)))))
               for j in range(nv + 1)]
        rows.append(row)
    for i in range(len(rows) - 1):
        for j in range(nv):
            bm.faces.new((rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1]))
    bm.normal_update()
    for f in bm.faces:
        if f.normal.z < 0.0:
            f.normal_flip()
    bm.normal_update()
    return obj_from_bm(name, bm, material, smooth)


def sweep(name, xs, yfn, thick, zb, zt, material, smooth=False):
    """沿 X 掃掠四邊形斷面（路緣石、緣石頂倒角）。"""
    bm = bmesh.new()
    rings = []
    for x in xs:
        y0 = yfn(x)
        rings.append([bm.verts.new((x, y0, zb)),
                      bm.verts.new((x, y0 + thick, zb)),
                      bm.verts.new((x, y0 + thick, zt)),
                      bm.verts.new((x, y0, zt))])
    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        for k in range(4):
            k2 = (k + 1) % 4
            bm.faces.new((a[k], a[k2], b[k2], b[k]))
    bm.faces.new(tuple(rings[0][::-1]))
    bm.faces.new(tuple(rings[-1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.normal_update()
    return obj_from_bm(name, bm, material, smooth)


XS_FINE = [X_A + (X_B - X_A) * i / 300.0 for i in range(301)]
XS_MID = [X_A + (X_B - X_A) * i / 150.0 for i in range(151)]
XS_COARSE = [X_A + (X_B - X_A) * i / 60.0 for i in range(61)]

# ------------------------------------------------------------ 路面與近側
band("00_車道", XS_FINE, 24, lambda x: Y_LANE_FRONT, bay_edge, road_z, M_ASPHALT)
band("00_近側草坡", XS_COARSE, 18, lambda x: -40.0,
     lambda x: Y_LANE_FRONT, verge_z, M_GRASS2)

# 路緣石（沿避車彎輪廓轉折，車道與坡側唯一的實體界線；高 20 cm）
sweep("03_路緣石", XS_FINE, bay_edge, CURB_W, -0.10, CURB_H - 0.03, M_CONC)
# 緣石頂倒角（頂面內縮 6 cm，讀起來才像預鑄緣石，而不是一道矮牆）
sweep("03_路緣石頂", XS_FINE, lambda x: bay_edge(x) + 0.03,
      CURB_W - 0.06, CURB_H - 0.03, CURB_H, M_CONC)

# 路側綠帶（原圖 1.2 m 淨寬 = 緣石 0.20 + 綠帶 1.00）
band("03_路側綠帶", XS_MID, 4, lambda x: bay_edge(x) + CURB_W,
     toe_y, lambda x, y: 0.03 + 0.03 * nz(x, y, 1.2, 2.0), M_GRASS2)

# 植生邊坡（坡趾直接起坡，無擋土牆）
band("21_植生邊坡", XS_FINE, 34, toe_y, lambda x: toe_y(x) + SLOPE_W,
     slope_z, M_GRASS)
band("22_平台", XS_COARSE, 26, lambda x: crest(x) - 0.06,
     lambda x: 90.0, plateau_z, M_GRASS2)

# ------------------------------------------------------------ 標線
band("40_邊線_外側", XS_FINE, 1, lambda x: Y_LANE_FRONT + 0.20,
     lambda x: Y_LANE_FRONT + 0.32, lambda x, y: road_z(x, y) + 0.006, M_LINE)
band("40_邊線_坡側", XS_FINE, 1, lambda x: bay_edge(x) - 0.30,
     lambda x: bay_edge(x) - 0.18, lambda x, y: road_z(x, y) + 0.006, M_LINE)


def arrow(name, cx, cy, length=2.60, width=0.30, head=0.90, sign=-1.0):
    bm = bmesh.new()
    x0 = cx - sign * length / 2.0
    x1 = cx + sign * length / 2.0
    hs = x1 - sign * head
    pts = [(x0, -width / 2), (hs, -width / 2), (hs, -width * 1.85), (x1, 0.0),
           (hs, width * 1.85), (hs, width / 2), (x0, width / 2)]
    vs = [bm.verts.new((px, cy + py, road_z(px, cy) + 0.007)) for px, py in pts]
    bm.faces.new(vs)
    bm.normal_update()
    for f in bm.faces:
        if f.normal.z < 0.0:
            f.normal_flip()
    return obj_from_bm(name, bm, M_LINE)


arrow("40_行車方向箭頭", -10.0, (Y_LANE_FRONT + 0.0) / 2.0, sign=-1.0)

# ------------------------------------------------------------ 植栽
TREE_ROWS = [
    (-30.0, 9.0, 7.2, 2.4, 80), (-22.0, 6.0, 6.8, 2.2, 71),
    (-15.0, 10.5, 7.6, 2.5, 72), (-8.0, 5.8, 6.2, 2.0, 73),
    (0.5, 8.2, 7.6, 2.5, 74), (9.0, 5.2, 6.6, 2.1, 75),
    (9.6, 12.5, 7.9, 2.6, 76), (22.0, 7.0, 7.0, 2.3, 77),
    (28.5, 11.5, 8.0, 2.7, 78), (35.0, 6.2, 6.4, 2.1, 79),
]
for _i, (_tx, _dy, _th, _tcr, _tsd) in enumerate(TREE_ROWS):
    _ty = crest(_tx) + _dy
    make_tree(_tx, _ty, plateau_z(_tx, _ty) - 0.20, _th, _tcr, _tsd,
              M_CANOPY if _i % 2 else M_CANOPY2)
# 近側草坡外圍的遠景樹
for _i, (_tx, _ty, _th, _tcr, _tsd) in enumerate([(-26.0, -13.0, 7.4, 2.4, 81),
                                                 (-13.0, -17.5, 8.0, 2.6, 82),
                                                 (14.0, -14.5, 7.2, 2.3, 83),
                                                 (27.0, -18.0, 8.2, 2.7, 84)]):
    make_tree(_tx, _ty, verge_z(_tx, _ty) - 0.20, _th, _tcr, _tsd, M_CANOPY2)

pavilion(17.0, crest(17.0) + 5.2, Z_TOP)

# 坡趾紅花灌木帶（沿避車彎輪廓，對應原圖坡腳的紅花植栽帶）
random.seed(20261106)
_x = -26.0
while _x < 30.0:
    _y = toe_y(_x) + 0.50
    blob("51_灌木", (_x, _y, slope_z(_x, _y) + 0.12),
         0.40 * random.uniform(0.85, 1.15),
         random.choice([M_FLOWER_R, M_FLOWER_R, M_FLOWER_P, M_HEDGE]),
         subdiv=1, squash=0.85, jitter=0.28)
    _x += 1.05 * random.uniform(0.85, 1.15)
# 坡面散生灌木
for _ in range(48):
    _x = random.uniform(-24.0, 26.0)
    _v = random.uniform(0.12, 0.86)
    _y = toe_y(_x) + SLOPE_W * _v
    blob("52_坡面灌木", (_x, _y, slope_z(_x, _y) + 0.14), random.uniform(0.30, 0.62),
         random.choice([M_HEDGE, M_HEDGE, M_CANOPY2]), subdiv=1, squash=0.78, jitter=0.26)
# 近側草坡灌木
for _ in range(36):
    _x = random.uniform(-34.0, 34.0)
    _y = random.uniform(-13.5, Y_LANE_FRONT - 0.4)
    blob("53_近側灌木", (_x, _y, verge_z(_x, _y) + 0.12), random.uniform(0.28, 0.55),
         M_HEDGE, subdiv=1, squash=0.75, jitter=0.24)

# ------------------------------------------------------------ 停放車輛
# 車頭朝 -X（與行車方向箭頭同向）；4.60 x 1.88 m，置於 5.0 x 3.2 m 避車彎內
suv(CAR_X, CAR_Y, yaw=math.pi)

# ------------------------------------------------------------ 遠景
grid_mesh("90_遠山1", -220, 220, 110, 190, 24, 6,
          lambda x, y: 7.0 + 0.10 * (y - 110) + 2.6 * nz(x, y, 0.02, 3), M_HILL)
grid_mesh("90_遠山2", -300, 300, 190, 320, 24, 6,
          lambda x, y: 13.0 + 0.10 * (y - 190) + 3.6 * nz(x, y, 0.015, 5), M_HILL2)

print("geometry objects=%d" % len(bpy.data.objects))

# ------------------------------------------------------------ 燈光與天空
world = bpy.data.worlds.new("W_天空")
scene.world = world
world.use_nodes = True
nt = world.node_tree
bg = nt.nodes["Background"]
sky = nt.nodes.new("ShaderNodeTexSky")
for st in ('MULTIPLE_SCATTERING', 'NISHITA'):
    try:
        sky.sky_type = st
        break
    except Exception:
        continue
try:
    sky.sun_elevation = math.radians(32)
    sky.sun_rotation = math.radians(45)
    sky.altitude = 200.0
    sky.air_density = 1.0
    sky.dust_density = 2.2
except Exception:
    pass
nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.38

sun_d = bpy.data.lights.new("L_陽光", type='SUN')
sun_d.energy = 3.7
sun_d.angle = math.radians(1.4)
sun_d.color = (1.0, 0.945, 0.855)
sun = bpy.data.objects.new("L_陽光", sun_d)
bpy.context.collection.objects.link(sun)
sun.rotation_euler = Euler((math.radians(55), 0.0, math.radians(-45)))
sun.location = (-20, -20, 20)

fill_d = bpy.data.lights.new("L_補光", type='AREA')
fill_d.energy = 380.0
fill_d.size = 26.0
fill_d.color = (0.80, 0.88, 1.0)
fill = bpy.data.objects.new("L_補光", fill_d)
bpy.context.collection.objects.link(fill)
fill.location = (6, -16, 12)
fill.rotation_euler = Euler((math.radians(52), 0, math.radians(18)))

# ------------------------------------------------------------ 相機
def make_cam(name, loc, target, lens=30.0):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    ob = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return ob


# 主視角：斜向沿路，看得見前漸變段 → 避車彎 → 後漸變段的 S 形輪廓
cam_main = make_cam("CAM_主視角", (-17.0, -11.5, 5.20), (3.0, 3.80, 1.30), 34.0)
# 近景：貼近避車彎，看清車、20 cm 路緣石與坡腳綠帶的關係
cam_bay = make_cam("CAM_避車彎近景", (12.4, -6.30, 1.55), (4.30, 2.35, 0.65), 30.0)
# 鳥瞰：俯視 S 曲線與停放位置
cam_air = make_cam("CAM_鳥瞰", (3.0, -17.5, 17.5), (2.50, 6.00, 1.40), 28.0)

# ------------------------------------------------------------ 渲染設定
scene.render.engine = 'CYCLES'
cy = getattr(scene, "cycles", None)
if cy is not None:
    for k, v in (("device", 'CPU'), ("samples", 64), ("use_adaptive_sampling", True),
                 ("adaptive_threshold", 0.02), ("use_denoising", True),
                 ("max_bounces", 4), ("diffuse_bounces", 2),
                 ("glossy_bounces", 2), ("transmission_bounces", 1),
                 ("time_limit", 150.0)):
        try:
            setattr(cy, k, v)
        except Exception as exc:
            print("cycles 參數略過：", k, exc)

scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.image_settings.color_depth = '8'
for _k, _v in (("view_transform", 'AgX'), ("exposure", -1.15)):
    try:
        setattr(scene.view_settings, _k, _v)
    except Exception as exc:
        print("色彩管理略過：", _k, exc)
_LOOK_OK = None
for _cand in ('AgX - Punchy', 'AgX - Medium High Contrast', 'Medium High Contrast', 'Punchy'):
    try:
        scene.view_settings.look = _cand
        _LOOK_OK = _cand
        break
    except Exception:
        continue
print("view_transform=%s look=%s exposure=%.2f" % (
    scene.view_settings.view_transform, _LOOK_OK, scene.view_settings.exposure))
try:
    scene.render.use_persistent_data = True
except Exception:
    pass

BLEND = os.path.join(OUT, "路旁避車彎_3D場景.blend")
try:
    # 不要在 out\ 產生 .blend1 自動備份（交付夾只放交付檔）
    bpy.context.preferences.filepaths.save_version = 0
except Exception as exc:
    print("save_version 設定略過：", exc)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
ARTIFACTS.append(BLEND)

VIEWS = [
    (cam_main, "路旁避車彎_3D_主視角.png"),
    (cam_bay, "路旁避車彎_3D_避車彎近景.png"),
    (cam_air, "路旁避車彎_3D_鳥瞰圖.png"),
]
PREVIEW = str(_opt("BAY_PREVIEW")).strip().lower() not in ("", "0", "false", "no", "none")
if PREVIEW:
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    try:
        scene.cycles.samples = 32
        scene.cycles.time_limit = 100.0
    except Exception:
        pass
    VIEWS = [VIEWS[0]]
else:
    try:
        scene.cycles.samples = 110
        scene.cycles.time_limit = 260.0
        scene.cycles.adaptive_threshold = 0.015
    except Exception:
        pass
print("PREVIEW=%s res=%dx%d" % (PREVIEW, scene.render.resolution_x, scene.render.resolution_y))

renders = []
for cam, fname in VIEWS:
    if PREVIEW:
        fname = "PREVIEW_" + fname
    scene.camera = cam
    path = os.path.join(OUT, fname)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders.append({"view": fname, "path": path,
                    "bytes": os.path.getsize(path) if os.path.exists(path) else -1})
    ARTIFACTS.append(path)

faces = 0
for ob in bpy.data.objects:
    if ob.type == 'MESH':
        faces += len(ob.data.polygons)

RESULT = {
    "out_dir": OUT,
    "blend": BLEND,
    "renders": renders,
    "objects": len(bpy.data.objects),
    "faces": faces,
    "engine": scene.render.engine,
    "units": "metric / 1 BU = 1 m",
    "bay_edge_at_x5": bay_edge(5.0),
    "toe_y_at_x5": toe_y(5.0),
    "curb_h_m": CURB_H,
}
print(json.dumps(RESULT, ensure_ascii=False, indent=1))
