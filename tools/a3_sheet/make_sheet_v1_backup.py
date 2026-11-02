"""模型空間描圖 DXF（site_basemap 產出）+ A3圖框樣板 → A3 配置 + 裁切 viewport（指定比例）→ DXF/DWG/PDF
用法：
  python make_sheet.py --model <..._現況平面圖_TWD97.dxf> --scale 600 --title 現況平面圖 --project 工程名稱 --out <輸出.dxf> --publish
範圍不足時會警告：site_basemap 的 --width/--height 至少要 400.3×比例/1000 與 258.4×比例/1000 公尺。
"""
import os, sys, json, shutil, time, argparse, ezdxf
from ezdxf.addons import Importer
from ezdxf.enums import TextEntityAlignment as TA
HERE = os.path.dirname(os.path.abspath(__file__)); TOOLS = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(TOOLS, "site_basemap"), os.path.join(TOOLS, "acad")]

# A3圖框.dwt 的版面（紙面 mm）。換樣板時用 --dwt 並在此新增一組。
PROFILE = {"A3圖框": dict(layout="全區工程位置圖", X0=10.0, Y0=29.0, X1=410.3, Y1=287.4,
                        stamp=(363.5, 80.9),          # 技師執業圖記區左上角（右下角落挖空）
                        notes=(215.0, 58.0),          # 說明/比例尺區右上角（左下角落挖空）
                        arrow=(383.0, 256.0))}        # 指北針區左下角（右上角落挖空）

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True); ap.add_argument("--meta", default=None)
ap.add_argument("--template", default=os.path.join(HERE, "A3圖框_template.dxf"))
ap.add_argument("--dwt", default=None, help="改用其他 .dwt，先自動轉 DXF")
ap.add_argument("--profile", default="A3圖框"); ap.add_argument("--scale", type=int, default=600)
ap.add_argument("--title", default="現況平面圖"); ap.add_argument("--project", default="")
ap.add_argument("--out", required=True); ap.add_argument("--publish", action="store_true", help="另存 DWG 並出 PDF")
ap.add_argument("--no-water-names", action="store_true")
A = ap.parse_args()
P = PROFILE[A.profile]; K = A.scale / 1000.0
MD = os.path.dirname(os.path.abspath(A.model)); OUTD = os.path.dirname(os.path.abspath(A.out)); os.makedirs(OUTD, exist_ok=True)
M = json.load(open(A.meta or os.path.join(MD, "basemap_meta.json"), encoding="utf-8"))
tpl = A.template
if A.dwt:
    from acc import to_dxf
    tpl = to_dxf(A.dwt, os.path.join(OUTD, "_template_from_dwt.dxf"))
base, src = ezdxf.readfile(tpl), ezdxf.readfile(A.model)
X0, Y0, X1, Y1 = P["X0"], P["Y0"], P["X1"], P["Y1"]; w, h = X1 - X0, Y1 - Y0
need_w, need_h = w * K, h * K
if M["E1"] - M["E0"] < need_w or M["N1"] - M["N0"] < need_h:
    print(f"警告：模型範圍 {M['E1']-M['E0']:.0f}x{M['N1']-M['N0']:.0f} m 小於 viewport 需求 {need_w:.0f}x{need_h:.0f} m，圖面邊緣會留白")

# ---- 1. 模型空間：匯入描圖（排除工具自帶 90~93 圖框類圖層），影像重建 ----
SKIP = ("90_", "91_", "92_", "93_")
imp = Importer(src, base); imp.import_tables(["layers"])
imp.import_entities([e for e in src.modelspace() if e.dxftype() != "IMAGE" and not e.dxf.layer.startswith(SKIP)], base.modelspace())
imp.finalize()
for e in src.modelspace().query("IMAGE"):
    f = os.path.basename(e.image_def.dxf.filename)
    if os.path.abspath(MD) != os.path.abspath(OUTD): shutil.copy2(os.path.join(MD, f), os.path.join(OUTD, f))
    d = base.add_image_def(filename=f, size_in_pixel=(int(e.dxf.image_size.x), int(e.dxf.image_size.y)))
    base.modelspace().add_image(d, insert=e.dxf.insert, size_in_units=(M["E1"] - M["E0"], M["N1"] - M["N0"]), dxfattribs={"layer": e.dxf.layer})
for n in ("00_正射影像_NLSC", "01_公有地地籍影像", "02_電子地圖影像", "12_公有地地籍界線"):
    if n in base.layers: base.layers.get(n).off()

# ---- 1b. 河道名稱（OSM，取與河道面重疊最多者；查不到標「河道」）----
if not A.no_water_names and base.modelspace().query('LWPOLYLINE[layer=="22_水道"]'):
    from nlsc import S, from97, to97
    from shapely.geometry import Polygon, LineString
    lo, la = from97.transform([M["E0"], M["E1"]], [M["N0"], M["N1"]]); bb = f"{la[0]},{lo[0]},{la[1]},{lo[1]}"
    q = f'[out:json][timeout:60];(way["waterway"]({bb});way["natural"="water"]({bb}););out geom;'
    named = []
    for k in range(3):
        try:
            for el in S.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=90).json()["elements"]:
                nm, g = el.get("tags", {}).get("name"), el.get("geometry")
                if nm and g: named.append((nm, LineString(list(zip(*to97.transform([p["lon"] for p in g], [p["lat"] for p in g]))))))
            break
        except Exception as ex: print("OSM 河道名稱重試", ex); time.sleep(15)
    base.layers.add("23_河道名稱", color=5)
    for wp in base.modelspace().query('LWPOLYLINE[layer=="22_水道"]'):
        poly = Polygon(list(wp.get_points("xy"))).buffer(0)
        hit = sorted(((poly.intersection(ln.buffer(3)).area, nm) for nm, ln in named), reverse=True)
        nm = hit[0][1] if hit and hit[0][0] > 0 else "河道"; c = poly.representative_point()
        base.modelspace().add_text(nm, height=4.0 * K, dxfattribs={"layer": "23_河道名稱", "style": "TOMO"}).set_placement((c.x, c.y), align=TA.MIDDLE_CENTER)
        print("河道標註", nm)

# ---- 2. 圖紙空間：viewport + 非矩形裁切（WIPEOUT 出圖無效，一律用裁切挖空）----
L = base.layouts.get(P["layout"]); CE, CN = M["center_E"], M["center_N"]
(SX, SY), (NX, NY), (AX, AY) = P["stamp"], P["notes"], P["arrow"]
vp = L.add_viewport(center=((X0 + X1) / 2, (Y0 + Y1) / 2), size=(w, h), view_center_point=(CE, CN),
                    view_height=h * K, dxfattribs={"layer": "Defpoints"})
clip = L.add_lwpolyline([(X0, NY), (NX, NY), (NX, Y0), (SX, Y0), (SX, SY), (X1, SY), (X1, AY), (AX, AY), (AX, Y1), (X0, Y1)],
                        close=True, dxfattribs={"layer": "Defpoints"})
vp.dxf.clipping_boundary_handle = clip.dxf.handle; clip.set_reactors([vp.dxf.handle])
vp.dxf.flags = vp.dxf.flags | 65536 | 16384                     # 非矩形裁切 + 鎖定縮放
FR = {"layer": "圖框"}; STY = {"style": "TOMO", "layer": "圖框"}
L.add_lwpolyline([(X0, NY), (NX, NY), (NX, Y0)], dxfattribs=FR); L.add_lwpolyline([(X1, AY), (AX, AY), (AX, Y1)], dxfattribs=FR)
# 指北針（圖北＝TWD97 坐標北）
ax, ay = (AX + X1) / 2, (AY + Y1) / 2 - 2
L.add_circle((ax, ay), 7.0, dxfattribs=FR)
tip, lft, rgt, ntc = (ax, ay + 9), (ax - 4, ay - 6), (ax + 4, ay - 6), (ax, ay - 2.5)
L.add_lwpolyline([tip, rgt, ntc, lft], close=True, dxfattribs=FR)
hs = L.add_hatch(color=256, dxfattribs=FR); hs.set_solid_fill(color=256); hs.paths.add_polyline_path([tip, ntc, lft], is_closed=True)
L.add_text("N", height=4.0, dxfattribs=STY).set_placement((ax, ay + 12.5), align=TA.MIDDLE_CENTER)
# 圖示比例尺：取 5 等分、總長 ≤ 說明區寬的整數公尺
nice = [5, 10, 20, 25, 50, 100, 200, 250, 500]
Lm = max(v for v in nice if v / K <= (NX - X0) * 0.5); seg = Lm / 5 / K; bx, by, bh = X0 + 8, Y0 + 7, 2.0
for i in range(5):
    pts = [(bx + i * seg, by), (bx + (i + 1) * seg, by), (bx + (i + 1) * seg, by + bh), (bx + i * seg, by + bh)]
    L.add_lwpolyline(pts, close=True, dxfattribs=FR)
    if i % 2 == 0:
        hb = L.add_hatch(color=256, dxfattribs=FR); hb.set_solid_fill(color=256); hb.paths.add_polyline_path(pts, is_closed=True)
for i in range(6):
    L.add_text(f"{Lm/5*i:g}" + (" m" if i == 5 else ""), height=2.5, dxfattribs=STY).set_placement((bx + i * seg, by + bh + 1.2), align=TA.BOTTOM_CENTER)
L.add_text(f"比例尺 S=1/{A.scale}", height=3.0, dxfattribs=STY).set_placement((bx, by - 2.0), align=TA.TOP_LEFT)
note = (f"坐標 TWD97 TM2 (EPSG:3826)，模型單位公尺；圖北為坐標北。中心 E {CE:.3f}  N {CN:.3f}\\P"
        "建物/道路/河道：NLSC 通用電子地圖向量化；道路用地：NLSC 公有土地地籍圖(僅供參考)；路名/河名：OpenStreetMap\\P"
        "自動產製，未經測量，不含高程")
L.add_mtext(note, dxfattribs={"style": "TOMO", "layer": "圖框", "char_height": 2.0, "insert": (bx, by + 10.5), "width": NX - bx - 5, "attachment_point": 7})
for t in L.query("TEXT"):
    if t.dxf.text == "圖名": t.dxf.text = A.title
    if t.dxf.text == "案名" and A.project: t.dxf.text = A.project
lbl = next((t for t in L.query("TEXT") if t.dxf.text == "比例尺"), None)
if lbl: L.add_text(f"1/{A.scale}", height=3.0, dxfattribs=STY).set_placement((lbl.dxf.insert.x + 15, lbl.dxf.insert.y))
base.layouts.set_active_layout(P["layout"]); base.saveas(A.out)

# ---- 3. 自我檢核（AGENTS.md §7）----
d = ezdxf.readfile(A.out); errs = len(d.audit().errors)
v = [x for x in d.layouts.get(P["layout"]).query("VIEWPORT") if x.dxf.id != 1][0]
ratio = v.dxf.height / v.dxf.view_height
assert abs(ratio - 1000 / A.scale) < 1e-6, f"viewport 比例錯誤 {ratio}"
assert v.dxf.flags & 65536 and v.dxf.flags & 16384, "裁切或鎖定未設定"
st = d.styles.get("TOMO"); assert st.dxf.font.lower() == "gbenor.shx" and st.dxf.bigfont.lower() == "china1.shx"
print(f"DXF OK {A.out} | audit {errs} | 1/{A.scale} (紙/模 {ratio:.4f} mm/m) | 裁切+鎖定 | 模型物件 {len(d.modelspace())}")

# ---- 4. AutoCAD 核心另存 DWG＋出 PDF（實機驗證；必做，ezdxf 能寫不代表 AutoCAD 會照解讀）----
if A.publish:
    from acc import publish
    r = publish(A.out, pdf=True); print("PUBLISH", r)
    try:
        import fitz
        pg = fitz.open(r[".pdf"])[0]; png = os.path.splitext(A.out)[0] + "_pdf.png"
        pg.get_pixmap(dpi=110).save(png); print("PDF 預覽", png, f"{pg.rect.width*25.4/72:.1f}x{pg.rect.height*25.4/72:.1f} mm")
    except Exception as ex: print("PDF 轉圖略過", ex)
