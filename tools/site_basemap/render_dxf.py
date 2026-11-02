"""把 DXF 渲染成 PNG 供目視檢核（只畫開啟的圖層，不畫影像）。用法: python render_dxf.py 檔案.dxf"""
import sys, ezdxf, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
fn = sys.argv[1]; doc = ezdxf.readfile(fn)
fig = plt.figure(figsize=(24, 17), dpi=110); ax = fig.add_axes([0, 0, 1, 1])
ctx = RenderContext(doc)
cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK, min_lineweight=0.15)
Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(),
    filter_func=lambda e: e.dxftype() != "IMAGE" and doc.layers.get(e.dxf.layer).is_on())
out = fn[:-4] + "_render.png"; fig.savefig(out, dpi=110); print(out)
