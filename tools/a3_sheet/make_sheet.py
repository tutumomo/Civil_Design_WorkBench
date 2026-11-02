"""模型空間描圖 DXF（site_basemap 產出）+ A3圖框樣板 → A3 配置（矩形 viewport＋右側資訊欄）→ DXF/DWG/PDF   v2
v2（第一輪比拼檢討）：右側資訊欄（指北/比例尺/圖例/案址/資料來源）、標題欄自動填（行政區、民國日期、繪圖、圖序）、
                     河道水流箭頭、黑白出圖可辨的線型（用地界虛線、中心線點劃線）。
v3（本項目出圖規定）：字高改為本文 3／附註 4／標題 5 mm（模型空間依比例換算）、--scale 限標準比例尺、
                     資料來源移至地圖區左下附註區（viewport 非矩形裁切）。規定見 tools\\drawing_rules.py。
用法：python make_sheet.py --model <..._現況平面圖_TWD97.dxf> --scale 600 --out <輸出.dxf> --publish
     [--project 工程名稱] [--title 圖名] [--owner 業主] [--designer 設計] [--drafter 繪圖]
範圍：site_basemap 的 --width ≥ 353.5×比例/1000+20、--height ≥ 258.4×比例/1000+20（公尺）。
"""
import os, sys, json, shutil, time, math, datetime, argparse, ezdxf
from ezdxf.addons import Importer
from ezdxf.enums import TextEntityAlignment as TA
HERE = os.path.dirname(os.path.abspath(__file__)); TOOLS = os.path.dirname(HERE)
sys.path[:0] = [TOOLS, os.path.join(TOOLS, "site_basemap"), os.path.join(TOOLS, "acad")]
from drawing_rules import (H_BODY, H_NOTE, H_TITLE, model_h, require_standard_scale,
                           add_plot_layer, tag_plot_style)   # 本項目出圖規定

# A3圖框.dwt 版面（紙面 mm）：地圖區 X0..CX × Y0..Y1；右側欄 CX..X1 × SY..Y1；SY 以下為技師執業圖記區
PROFILE = {"A3圖框": dict(layout="全區工程位置圖", X0=10.0, Y0=29.0, X1=410.3, Y1=287.4, CX=363.5, SY=80.9)}

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True); ap.add_argument("--meta", default=None)
ap.add_argument("--template", default=os.path.join(HERE, "A3圖框_template.dxf"))
ap.add_argument("--dwt", default=None, help="改用其他 .dwt，先自動轉 DXF")
ap.add_argument("--profile", default="A3圖框"); ap.add_argument("--scale", type=int, default=600)
ap.add_argument("--title", default="現況平面圖"); ap.add_argument("--project", default="")
ap.add_argument("--owner", default="", help="標題欄業主；空白時填案址縣市行政區")
ap.add_argument("--designer", default=""); ap.add_argument("--drafter", default="Claude（AI）")
ap.add_argument("--sheet-no", default="1/1")
ap.add_argument("--out", required=True); ap.add_argument("--publish", action="store_true", help="另存 DWG 並由 AutoCAD 出 PDF")
ap.add_argument("--no-water-names", action="store_true")
A = ap.parse_args()
require_standard_scale(A.scale)
P = PROFILE[A.profile]; K = A.scale / 1000.0
MD = os.path.dirname(os.path.abspath(A.model)); OUTD = os.path.dirname(os.path.abspath(A.out)); os.makedirs(OUTD, exist_ok=True)
M = json.load(open(A.meta or os.path.join(MD, "basemap_meta.json"), encoding="utf-8"))
AD = M.get("admin") or {}
tpl = A.template
if A.dwt:
    from acc import to_dxf
    tpl = to_dxf(A.dwt, os.path.join(OUTD, "_template_from_dwt.dxf"))
base, src = ezdxf.readfile(tpl), ezdxf.readfile(A.model)
X0, Y0, X1, Y1, CX, SY = P["X0"], P["Y0"], P["X1"], P["Y1"], P["CX"], P["SY"]
w, h = CX - X0, Y1 - Y0
if M["E1"] - M["E0"] < w * K or M["N1"] - M["N0"] < h * K:
    print(f"警告：模型範圍 {M['E1']-M['E0']:.0f}x{M['N1']-M['N0']:.0f} m 小於 viewport 需求 {w*K:.0f}x{h*K:.0f} m，圖面邊緣會留白")

# ---- 1. 模型空間：匯入描圖（排除工具自帶 90~93 圖框類），影像重建；黑白可辨線型 ----
SKIP = ("90_", "91_", "92_", "93_")
imp = Importer(src, base); imp.import_tables(["layers", "linetypes"])
imp.import_entities([e for e in src.modelspace() if e.dxftype() != "IMAGE" and not e.dxf.layer.startswith(SKIP)], base.modelspace())
imp.finalize()
RS = A.scale / M.get("scale", A.scale)                               # 底圖字高依其 --scale 換算；出圖比例不同時等比修正
if abs(RS - 1) > 1e-9:
    for e in base.modelspace().query("TEXT MTEXT"):
        if e.dxftype() == "TEXT": e.dxf.height *= RS
        else: e.dxf.char_height *= RS
    print(f"底圖比例 1/{M.get('scale')} ≠ 出圖 1/{A.scale}，模型文字字高 ×{RS:.3f}")
for e in src.modelspace().query("IMAGE"):
    f = os.path.basename(e.image_def.dxf.filename)
    if os.path.abspath(MD) != os.path.abspath(OUTD): shutil.copy2(os.path.join(MD, f), os.path.join(OUTD, f))
    d = base.add_image_def(filename=f, size_in_pixel=(int(e.dxf.image_size.x), int(e.dxf.image_size.y)))
    base.modelspace().add_image(d, insert=e.dxf.insert, size_in_units=(M["E1"] - M["E0"], M["N1"] - M["N0"]), dxfattribs={"layer": e.dxf.layer})
for n in ("00_正射影像_NLSC", "01_公有地地籍影像", "02_電子地圖影像", "12_公有地地籍界線"):
    if n in base.layers: base.layers.get(n).off()
LT = {"DASHED": [19.05, 12.7, -6.35], "CENTER": [50.8, 31.75, -6.35, 6.35, -6.35]}   # acadiso.lin（mm）
for lt, pat in LT.items():
    if lt not in base.linetypes: base.linetypes.add(lt, pattern=pat)
if "11_道路用地界_地籍" in base.layers: base.layers.get("11_道路用地界_地籍").dxf.linetype = "DASHED"
if "13_道路中心線_OSM" in base.layers: base.layers.get("13_道路中心線_OSM").dxf.linetype = "CENTER"
base.header["$PSLTSCALE"] = 1; base.header["$LTSCALE"] = 0.35        # 圖紙上虛線約 4.4 mm 一段

# ---- 1b. 河道名稱＋水流方向箭頭（OSM waterway 的繪製方向即流向）----
WL = "23_河道標示"
if not A.no_water_names and base.modelspace().query('LWPOLYLINE[layer=="22_水道"]'):
    from nlsc import S, from97, to97
    from shapely.geometry import Polygon, LineString
    lo, la = from97.transform([M["E0"], M["E1"]], [M["N0"], M["N1"]]); bb = f"{la[0]},{lo[0]},{la[1]},{lo[1]}"
    q = f'[out:json][timeout:60];(way["waterway"]({bb});way["natural"="water"]({bb}););out geom;'
    named = []
    for k in range(3):
        try:
            for el in S.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=90).json()["elements"]:
                tg, g = el.get("tags", {}), el.get("geometry")
                if g: named.append((tg.get("name", ""), "waterway" in tg, LineString(list(zip(*to97.transform([p["lon"] for p in g], [p["lat"] for p in g]))))))
            break
        except Exception as ex: print("OSM 河道重試", ex); time.sleep(15)
    add_plot_layer(base, WL, color=5)
    for wp in base.modelspace().query('LWPOLYLINE[layer=="22_水道"]'):
        poly = Polygon(list(wp.get_points("xy"))).buffer(0)
        hit = sorted(((poly.intersection(ln.buffer(3)).area, nm, isw, ln) for nm, isw, ln in named if nm), key=lambda t: -t[0])
        nm = hit[0][1] if hit and hit[0][0] > 0 else "河道"; c = poly.representative_point()
        base.modelspace().add_text(nm, height=model_h(H_BODY, A.scale), dxfattribs={"layer": WL, "style": "TOMO"}).set_placement((c.x, c.y), align=TA.MIDDLE_CENTER)
        ws = [t for t in hit if t[2] and t[0] > 0]                     # 有流向的 waterway 線
        if ws:
            ln = ws[0][3]; s0 = ln.project(c); p0, p1 = ln.interpolate(max(s0 - 1, 0)), ln.interpolate(min(s0 + 1, ln.length))
            ang = math.atan2(p1.y - p0.y, p1.x - p0.x); ux, uy = math.cos(ang), math.sin(ang); nx, ny = -uy, ux
            bx_, by_ = c.x - nx * 6 * K, c.y - ny * 6 * K               # 箭頭放名稱旁
            tail, head = (bx_ - ux * 6 * K, by_ - uy * 6 * K), (bx_ + ux * 6 * K, by_ + uy * 6 * K)
            base.modelspace().add_line(tail, head, dxfattribs={"layer": WL})
            wing = [(head[0] - ux * 2.5 * K + nx * 1.2 * K, head[1] - uy * 2.5 * K + ny * 1.2 * K), head,
                    (head[0] - ux * 2.5 * K - nx * 1.2 * K, head[1] - uy * 2.5 * K - ny * 1.2 * K)]
            hh = base.modelspace().add_hatch(color=256, dxfattribs={"layer": WL}); hh.set_solid_fill(color=256)
            hh.paths.add_polyline_path(wing, is_closed=True)
        print("河道標示", nm, "流向箭頭" if ws else "（無流向資料）")

# ---- 2. 圖紙空間：viewport（地圖區，挖空左下「資料來源」附註區），比例鎖定 ----
# 出圖規定：本文 3 mm、附註 4 mm 放不進 46.8 mm 寬的右側欄，故資料來源改放地圖區左下角（EXP-B4 非矩形裁切）
NW, NH = 200.0, 52.0                                                  # 左下附註區寬高（mm）
NX, NY = X0 + NW, Y0 + NH
L = base.layouts.get(P["layout"]); CE, CN = M["center_E"], M["center_N"]
vp = L.add_viewport(center=((X0 + CX) / 2, (Y0 + Y1) / 2), size=(w, h), view_center_point=(CE, CN),
                    view_height=h * K, dxfattribs={"layer": "Defpoints"})
clip = L.add_lwpolyline([(X0, NY), (NX, NY), (NX, Y0), (CX, Y0), (CX, Y1), (X0, Y1)], close=True,
                        dxfattribs={"layer": "Defpoints"})
vp.dxf.clipping_boundary_handle = clip.dxf.handle; clip.set_reactors([vp.dxf.handle])
vp.dxf.flags = vp.dxf.flags | 65536 | 16384                          # 非矩形裁切 + 鎖定縮放
FR = {"layer": "圖框"}; STY = {"style": "TOMO", "layer": "圖框"}
def t(s, x, y, ht=H_BODY, al=TA.MIDDLE_CENTER): L.add_text(s, height=ht, dxfattribs=STY).set_placement((x, y), align=al)
def pl(pts, close=False, lay="圖框", lt=None):
    a = {"layer": lay}
    if lt: a["linetype"] = lt
    return L.add_lwpolyline(pts, close=close, dxfattribs=a)
pl([(CX, SY), (CX, Y1)])                                             # 地圖區與右側欄分隔線
cx = (CX + X1) / 2; cw = X1 - CX
# 字高分級（出圖規定）：區塊標題 H_TITLE 5 mm、內文 H_BODY 3 mm、附註說明 H_NOTE 4 mm

# ---- 3. 右側欄：指北針 ----
yy = Y1 - 6; t("指 北", cx, yy, H_TITLE); ay = yy - 19
L.add_circle((cx, ay), 7.0, dxfattribs=FR)
tip, lft, rgt, ntc = (cx, ay + 9), (cx - 4, ay - 6), (cx + 4, ay - 6), (cx, ay - 2.5)
pl([tip, rgt, ntc, lft], True)
hs = L.add_hatch(color=256, dxfattribs=FR); hs.set_solid_fill(color=256); hs.paths.add_polyline_path([tip, ntc, lft], is_closed=True)
t("N", cx, ay + 12, H_TITLE)
t("圖北為", cx, ay - 11.5, H_NOTE); t("TWD97 坐標北", cx, ay - 18, H_NOTE)
yy = ay - 22.5; pl([(CX, yy), (X1, yy)])

# ---- 4. 右側欄：比例尺 ----
yy -= 6; t("比 例 尺", cx, yy, H_TITLE); yy -= 6.5; t(f"S=1/{A.scale}", cx, yy, H_BODY)
nice = [5, 10, 20, 25, 50, 100, 200, 250, 500]
Lm = max(v for v in nice if v / K <= cw - 18); seg = Lm / 4 / K; bx = cx - 2 * seg - 4.0; by = yy - 9.5
for i in range(4):
    pts = [(bx + i * seg, by), (bx + (i + 1) * seg, by), (bx + (i + 1) * seg, by + 1.8), (bx + i * seg, by + 1.8)]
    pl(pts, True)
    if i % 2 == 0:
        hb = L.add_hatch(color=256, dxfattribs=FR); hb.set_solid_fill(color=256); hb.paths.add_polyline_path(pts, is_closed=True)
for i in (0, 2, 4): t(f"{Lm/4*i:g}", bx + i * seg, by + 4.3, H_BODY)  # 3 mm 數字只標 0、中點、全長，避免疊字
t("(m)", bx + 4 * seg + 7.0, by + 0.9, H_BODY)
yy = by - 4; pl([(CX, yy), (X1, yy)])

# ---- 5. 右側欄：圖例 ----
yy -= 6; t("圖 例", cx, yy, H_TITLE); yy -= 7.5
def row(label):
    global yy
    t(label, CX + 15, yy, H_BODY, TA.MIDDLE_LEFT); y0 = yy; yy -= 6.5; return y0
y = row("道路邊線(現況)"); pl([(CX + 2.5, y), (CX + 12.5, y)])        # 半形括號：3 mm 全形會超出欄寬
y = row("道路用地界(地籍)"); pl([(CX + 2.5, y), (CX + 12.5, y)], lt="DASHED")
y = row("道路中心線"); pl([(CX + 2.5, y), (CX + 12.5, y)], lt="CENTER")
y = row("建物")
r = [(CX + 2.5, y - 2), (CX + 12.5, y - 2), (CX + 12.5, y + 2), (CX + 2.5, y + 2)]; pl(r, True)
hb = L.add_hatch(color=256, dxfattribs=FR); hb.set_pattern_fill("ANSI31", color=256, scale=0.5); hb.paths.add_polyline_path(r, is_closed=True)
y = row("河道")
r = [(CX + 2.5, y - 2), (CX + 12.5, y - 2), (CX + 12.5, y + 2), (CX + 2.5, y + 2)]; pl(r, True)
hb = L.add_hatch(color=256, dxfattribs=FR); hb.set_pattern_fill("DASH", color=256, scale=12, angle=0); hb.paths.add_polyline_path(r, is_closed=True)
y = row("水流方向")
pl([(CX + 2.5, y), (CX + 10.5, y)])
ha = L.add_hatch(color=256, dxfattribs=FR); ha.set_solid_fill(color=256)
ha.paths.add_polyline_path([(CX + 9.5, y + 1.2), (CX + 12.5, y), (CX + 9.5, y - 1.2)], is_closed=True)
yy += 2.5; pl([(CX, yy), (X1, yy)])

# ---- 6. 右側欄：案址資訊 ----
yy -= 6; t("案 址", cx, yy, H_TITLE); yy -= 7
loc = f"{AD.get('ctyName','')}{AD.get('townName','')}{AD.get('villageName','')}"
for s_ in [loc or "（行政區查詢失敗）", f"地段：{AD.get('sectName','') or '-'}",
           f"E {CE:.3f}", f"N {CN:.3f}", f"緯 {M['lat']:.6f}", f"經 {M['lon']:.6f}"]:
    t(s_, CX + 2.5, yy, H_BODY, TA.MIDDLE_LEFT); yy -= 5.0
assert yy > SY + 2, f"右側欄內容超出技師圖記區（yy={yy:.1f}）"

# ---- 6b. 左下附註區：資料來源（附註 4 mm）----
pl([(X0, NY), (NX, NY), (NX, Y0)])
t("資 料 來 源", X0 + 3, NY - 5, H_TITLE, TA.MIDDLE_LEFT)
bsrc = M.get("bldg_source", "國土測繪中心 通用電子地圖")
note = (f"1. 建物：{bsrc}\\P"
        "2. 道路邊線、河道：國土測繪中心 通用電子地圖向量化"
        + (f"（平滑最大偏移 {M['road_smooth_max_dev_m']:.2f} m）" if "road_smooth_max_dev_m" in M else "") + "\\P"
        "3. 道路用地界：國土測繪中心 公有土地地籍圖，僅供參考\\P"
        "4. 路名、河名、流向：OpenStreetMap (ODbL)\\P"
        "5. 坐標 TWD97 TM2 (EPSG:3826)，單位公尺；自動產製，未經測量，不含高程")
L.add_mtext(note, dxfattribs={"style": "TOMO", "layer": "圖框", "char_height": H_NOTE, "insert": (X0 + 3, NY - 10),
                              "width": NW - 6, "attachment_point": 1, "line_spacing_factor": 0.9})

# ---- 7. 標題欄（第一輪檢討：業主欄沿用「大雅區公所」與案址不符、設計/繪圖/日期留白）----
today = datetime.date.today(); roc = f"{today.year - 1911}.{today.month:02d}.{today.day:02d}"
owner = A.owner or (f"{AD.get('ctyName','')}{AD.get('townName','')}" if AD.get("townName") else "")
project = A.project or (f"{AD.get('townName','')}{AD.get('villageName','')}現況測繪" if AD.get("townName") else "")
T = {x.dxf.text: x for x in L.query("TEXT")}
for x in L.query("TEXT"):
    if x.dxf.text == "臺中市大雅區公所" and owner: x.dxf.text = owner
    if x.dxf.text == "圖名": x.dxf.text = A.title
    if x.dxf.text == "案名" and project: x.dxf.text = project
def fill(label, value, dx=12.0, dy=0.0, ht=H_BODY):
    lb = T.get(label)
    if lb is not None and value:
        L.add_text(value, height=ht, dxfattribs=STY).set_placement((lb.dxf.insert.x + dx, lb.dxf.insert.y + dy))
fill("設計", A.designer); fill("繪圖", A.drafter); fill("日期", roc)
fill("比例尺", f"1/{A.scale}", dx=15.0); fill("圖序", A.sheet_no, dx=14.0)
base.layouts.set_active_layout(P["layout"]); tag_plot_style(base); base.saveas(A.out)

# ---- 8. 自我檢核（AGENTS.md §7）----
d = ezdxf.readfile(A.out); errs = len(d.audit().errors)
v = [x for x in d.layouts.get(P["layout"]).query("VIEWPORT") if x.dxf.id != 1][0]
ratio = v.dxf.height / v.dxf.view_height
assert abs(ratio - 1000 / A.scale) < 1e-6, f"viewport 比例錯誤 {ratio}"
assert v.dxf.flags & 16384 and v.dxf.flags & 65536, "viewport 未鎖定或未裁切"
st = d.styles.get("TOMO"); assert st.dxf.font.lower() == "gbenor.shx" and st.dxf.bigfont.lower() == "china1.shx"
for lt in ("DASHED", "CENTER"): assert lt in d.linetypes, f"缺線型 {lt}"
print(f"DXF OK {A.out} | audit {errs} | 1/{A.scale} (紙/模 {ratio:.4f} mm/m) | 鎖定 | 模型物件 {len(d.modelspace())} | 業主「{owner}」日期 {roc}")

# ---- 9. AutoCAD 核心另存 DWG＋出 PDF（實機驗證；必做）----
if A.publish:
    from acc import publish
    r = publish(A.out, pdf=True); print("PUBLISH", r)
    try:
        import fitz
        pg = fitz.open(r[".pdf"])[0]; png = os.path.splitext(A.out)[0] + "_pdf.png"
        pg.get_pixmap(dpi=110).save(png); print("PDF 預覽", png, f"{pg.rect.width*25.4/72:.1f}x{pg.rect.height*25.4/72:.1f} mm")
    except Exception as ex: print("PDF 轉圖略過", ex)
