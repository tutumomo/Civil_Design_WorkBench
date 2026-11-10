# -*- coding: utf-8 -*-
"""把模型空間線稿併入 A3 圖框，建立指定比例的圖紙空間視口。

用法：
  python make_a3_sheet.py --base 線稿.dxf --frame A3圖框.dxf --meta basemap_meta.json \
      --scale 600 --out 成果.dxf --title "臺中市南區現況平面圖" --drawing "現況平面圖"

  --frame 可以是 .dwt（會自動用 CADCraft convert 轉成 DXF）
  --meta 省略時，用 --center E,N 指定模型中心

產出：模型空間線稿 + A3 布局（圖框、1:scale 視口、指北針、比例尺、已填標題欄）

設計要點（踩過的坑，勿改）：
  * 樣板內建 VIEWPORT 是壞的（581x378mm 超出圖框），一律刪除重建
  * 線稿自帶的 90_圖框/91_指北針/92_比例尺/93_說明 要刪掉，圖例改放圖紙空間
  * view_height(模型m) = 視口高(mm) × 比例分母 / 1000   ← 模型單位為公尺時
  * 併檔前目標文件必須先有 TOMO 樣式，否則匯入的 TEXT 掉樣式
"""
import argparse, json, os, sys, tempfile
import sys as _sys
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
import ezdxf
from ezdxf.addons import Importer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drawing_rules import add_plot_layer, tag_plot_style   # noqa: E402

DROP_LAYERS = {"90_圖框", "91_指北針", "92_比例尺", "93_說明"}

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True, help="模型空間線稿 DXF")
ap.add_argument("--frame", required=True, help="A3 圖框 .dxf 或 .dwt")
ap.add_argument("--meta", default=None, help="basemap_meta.json（取 center_E/center_N）")
ap.add_argument("--center", default=None, help="模型中心 E,N（無 meta 時使用）")
ap.add_argument("--scale", type=int, default=600, help="出圖比例分母，預設 600")
ap.add_argument("--layout", default="全區工程位置圖", help="圖框布局名稱")
ap.add_argument("--out", required=True)
ap.add_argument("--title", default="", help="工程名稱")
ap.add_argument("--drawing", default="", help="圖名")
ap.add_argument("--designer", default="", help="設計者")
ap.add_argument("--date", default="", help="日期")
ap.add_argument("--frame-in", default="10.03,10.45,410.27,287.45",
                help="圖框內框 x0,y0,x1,y1（mm），預設 A3 標準圖框")
ap.add_argument("--title-bottom", type=float, default=29.0, help="標題欄上緣 y（mm）")
ap.add_argument("--no-legend", action="store_true", help="不加指北針與比例尺")
A = ap.parse_args()

# ---- 圖框來源處理 ----
frame = A.frame
if frame.lower().endswith(".dwt"):
    tmp = os.path.join(tempfile.gettempdir(), "_a3_frame_tmp.dxf")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acad"))
    from acc import to_dxf   # noqa: E402  後端由 CIVIL_AI_CAD_BACKEND 決定（預設 OpenCADStudio）
    to_dxf(frame, tmp)
    if not os.path.exists(tmp):
        sys.exit("DWT 轉 DXF 失敗")
    frame = tmp
    print("DWT -> DXF:", tmp)

doc = ezdxf.readfile(frame)
lay = doc.layouts.get(A.layout)
if lay is None:
    sys.exit(f"布局 {A.layout!r} 不存在，可用: {[l.name for l in doc.layouts]}")

# ---- 模型中心 ----
if A.meta:
    m = json.load(open(A.meta, encoding="utf-8"))
    CE, CN = m["center_E"], m["center_N"]
elif A.center:
    CE, CN = [float(v) for v in A.center.split(",")]
else:
    sys.exit("需要 --meta 或 --center")

# ---- 併入模型空間 ----
if "TOMO" not in doc.styles:
    st = doc.styles.add("TOMO", font="gbenor.shx")
    st.dxf.bigfont = "CHINESE.SHX"
src = ezdxf.readfile(A.base)
imp = Importer(src, doc)
imp.import_modelspace()
imp.finalize()
msp = doc.modelspace()

killed = 0
for e in list(msp):
    if e.dxf.layer in DROP_LAYERS:
        msp.delete_entity(e)
        killed += 1
print(f"移除線稿自帶圖例實體: {killed}")

# ---- 重建視口 ----
x0, y0, x1, y1 = [float(v) for v in A.frame_in.split(",")]
y0 = max(y0, A.title_bottom)
VW, VH = x1 - x0, y1 - y0
CX, CY = (x0 + x1) / 2, (y0 + y1) / 2

for vp in list(lay.query("VIEWPORT")):
    lay.delete_entity(vp)

vh_model = VH * A.scale / 1000.0
lay.add_viewport(center=(CX, CY), size=(VW, VH),
                 view_center_point=(CE, CN), view_height=vh_model).dxf.status = 1
print(f"視口 {VW:.2f}x{VH:.2f} mm  view_height={vh_model:.3f} m  比例 1:{A.scale}")
print(f"模型覆蓋 {VW*A.scale/1000:.1f} x {vh_model:.1f} m  中心 E{CE:.2f} N{CN:.2f}")

# ---- 圖紙空間圖例 ----
def pl(pts, layer, close=False):
    lay.add_lwpolyline([tuple(p) for p in pts], close=close, dxfattribs={"layer": layer})

for name in ("91_指北針", "92_比例尺"):
    add_plot_layer(doc, name, color=7)

if not A.no_legend:
    ax, ay, R = x1 - 22, y1 - 26, 8.0
    lay.add_circle((ax, ay), R, dxfattribs={"layer": "91_指北針"})
    tip = (ax, ay + R * 1.15); lft = (ax - R * 0.55, ay - R * 0.75)
    rgt = (ax + R * 0.55, ay - R * 0.75); ntc = (ax, ay - R * 0.25)
    pl([tip, rgt, ntc, lft], "91_指北針", True)
    h = lay.add_hatch(color=256, dxfattribs={"layer": "91_指北針"}); h.set_solid_fill(color=256)
    h.paths.add_polyline_path([tip, ntc, lft], is_closed=True)
    lay.add_text("N", height=5.0, dxfattribs={"layer": "91_指北針", "style": "TOMO"}
                 ).set_placement((ax, ay + R * 1.55), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    seg_mm = 10.0                                  # 圖面每格 10 mm
    seg_m = seg_mm * A.scale / 1000.0              # 對應的實際長度
    bx, by, bh = x0 + 12, y0 + 12, 2.2
    for i in range(5):
        sx = bx + i * seg_mm
        pl([(sx, by), (sx + seg_mm, by), (sx + seg_mm, by + bh), (sx, by + bh)], "92_比例尺", True)
        if i % 2 == 0:
            hb = lay.add_hatch(color=256, dxfattribs={"layer": "92_比例尺"}); hb.set_solid_fill(color=256)
            hb.paths.add_polyline_path([(sx, by), (sx + seg_mm, by),
                                        (sx + seg_mm, by + bh), (sx, by + bh)], is_closed=True)
    for i in range(6):
        lay.add_text(f"{seg_m*i:g}", height=2.0, dxfattribs={"layer": "92_比例尺", "style": "TOMO"}
                     ).set_placement((bx + i * seg_mm, by + bh + 1.0),
                                     align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    lay.add_text("m", height=2.0, dxfattribs={"layer": "92_比例尺", "style": "TOMO"}
                 ).set_placement((bx + 5 * seg_mm + 1.5, by + bh + 1.0),
                                 align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)
    lay.add_text(f"S = 1:{A.scale}", height=2.5, dxfattribs={"layer": "92_比例尺", "style": "TOMO"}
                 ).set_placement((bx, by - 2.2), align=ezdxf.enums.TextEntityAlignment.TOP_LEFT)

# ---- 標題欄 ----
FILL = [(A.title, 175.5, 23.1, 3.0), (A.drawing, 175.5, 13.5, 3.0),
        (f"1/{A.scale}", 247.0, 13.9, 3.0), (A.date, 95.0, 11.9, 2.8),
        (A.designer, 95.0, 24.3, 2.8)]
for txt, x, y, h in FILL:
    if txt:
        lay.add_text(txt, height=h, dxfattribs={"layer": "圖框", "style": "TOMO"}
                     ).set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)

tag_plot_style(doc)
doc.saveas(A.out)

# ---- 驗證 ----
d = ezdxf.readfile(A.out)
L = d.layouts.get(A.layout)
errs = len(d.audit().errors)
for v in L.query("VIEWPORT"):
    real = v.dxf.view_height * 1000 / v.dxf.height
    print(f"[驗證] audit={errs}  INSUNITS={d.header.get('$INSUNITS')}  "
          f"視口實測比例 1:{real:.1f}  view_h={v.dxf.view_height:.3f} m")
print("saved:", A.out)
