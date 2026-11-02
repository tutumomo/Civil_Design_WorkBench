"""同一區域放大渲染兩個 DXF，做去階梯前後的 A/B 比較。

用法: python render_zoom.py a.dxf b.dxf
會自動挑 20_建物 中帶中庭（孔洞）最大的那棟，在其範圍內放大渲染兩版。
"""
import sys

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

LAYER = "20_建物"


def pick_zoom_box(dxf):
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    best = None
    for e in msp.query("LWPOLYLINE"):
        if e.dxf.layer != LAYER or not e.closed:
            continue
        pts = list(e.get_points("xy"))
        if len(pts) < 8:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if best is None or w * h > best[0]:
            best = (w * h, min(xs), min(ys), max(xs), max(ys))
    return best


def render(dxf, box, out, pad=6.0):
    x0, y0, x1, y1 = box
    doc = ezdxf.readfile(dxf)
    fig = plt.figure(figsize=(14, 10), dpi=130)
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.BLACK,
        min_lineweight=0.15,
    )
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(
        doc.modelspace(),
        filter_func=lambda e: e.dxftype() != "IMAGE" and doc.layers.get(e.dxf.layer).is_on(),
    )
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("saved", out)


if __name__ == "__main__":
    a, b = sys.argv[1], sys.argv[2]
    box = pick_zoom_box(a)
    print("zoom box:", [round(v, 2) for v in box])
    render(a, box[1:], a[:-4] + "_zoomA.png")
    render(b, box[1:], b[:-4] + "_zoomB.png")
