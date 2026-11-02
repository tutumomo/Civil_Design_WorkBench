"""把既有 DXF 的圖層配色套成《出圖樣式與線粗》規定。

用途：規定上線前產出的舊圖（例如 AC 刨鋪案的 A3）不必重跑整條產線，
      只換圖層顏色與線粗、補上出圖型式標記；幾何與圖紙空間內容完全不動。

用法：
  python tools\\acad\\apply_plot_style.py <圖.dxf>            只改 DXF
  python tools\\acad\\apply_plot_style.py <圖.dxf> --publish  另出 DWG＋PDF＋PNG

規則：顏色 1~8 對應固定線粗（tools\\drawing_rules.py 的 LINE_WEIGHT_BY_COLOR），
      已知圖層顏色來自 PLAN_LAYER_COLORS；圖層關閉狀態（負色值）會保留。
"""
import argparse, os, sys
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
from drawing_rules import (PLAN_LAYER_COLORS, LINE_WEIGHT_BY_COLOR,
                            add_plot_layer, dxf_lineweight, tag_plot_style)

SKIP = {"0", "Defpoints", "VIEWPORTS"}


def apply_plot_style(doc):
    """回傳實際改動的清單（給人看的字串）"""
    changed = []
    for name, color in PLAN_LAYER_COLORS.items():
        if name not in doc.layers:
            continue
        lay = doc.layers.get(name)
        was_off = lay.dxf.color < 0
        before = (lay.dxf.color, lay.dxf.get("lineweight", -3))
        add_plot_layer(doc, name, color=color)
        if was_off:
            lay.off()
        after = (lay.dxf.color, lay.dxf.get("lineweight", -3))
        if before != after:
            changed.append("%s 顏色/線粗 %s → %s" % (name, before, after))
    for lay in doc.layers:
        if lay.dxf.name in PLAN_LAYER_COLORS or lay.dxf.name in SKIP:
            continue
        was_off = lay.dxf.color < 0
        c = abs(lay.dxf.color)
        if c not in LINE_WEIGHT_BY_COLOR:
            continue
        want = dxf_lineweight(LINE_WEIGHT_BY_COLOR[c])
        if lay.dxf.get("lineweight", -3) != want:
            lay.dxf.lineweight = want
            if was_off:
                lay.off()
            changed.append("%s 線粗 → %s" % (lay.dxf.name, want))
    return changed


def normalize_entities(doc):
    """顏色與線粗一律交給圖層決定：把圖元自帶的顏色改回 BYLAYER。
    規則要求「元件依重要性用不同顏色並放不同圖層」，圖元自帶顏色會蓋掉這套設計。"""
    n = 0
    spaces = list(doc.layouts) + [b for b in doc.blocks if not b.is_any_layout]
    for space in spaces:
        for e in space:
            hit = False
            if e.dxf.get("color", 256) not in (256, 0):
                e.dxf.color = 256
                hit = True
            if e.dxf.get("lineweight", -1) not in (-1, -2, -3):
                e.dxf.lineweight = -1
                hit = True
            if e.dxf.get("true_color", None) is not None:
                del e.dxf.true_color
                hit = True
            if hit:
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--publish", action="store_true", help="另存 DWG 並由 AutoCAD 出 PDF")
    ap.add_argument("--no-tag", action="store_true", help="不寫入出圖型式標記")
    ap.add_argument("--keep-entity-colors", action="store_true",
                    help="保留圖元自帶顏色（預設改回 BYLAYER）")
    a = ap.parse_args()
    doc = ezdxf.readfile(a.dxf)
    changed = apply_plot_style(doc)
    n_ent = 0
    if not a.keep_entity_colors:
        n_ent = normalize_entities(doc)
    if not a.no_tag:
        tag_plot_style(doc)
    doc.saveas(a.dxf)
    print("套用出圖樣式：%d 處" % len(changed))
    print("圖元顏色改回 BYLAYER：%d 個" % n_ent)
    for c in changed:
        print("  " + c)
    if a.publish:
        from acc import publish
        r = publish(a.dxf, pdf=True)
        print("PUBLISH", r)
        try:
            import fitz
            pg = fitz.open(r[".pdf"])[0]
            png = os.path.splitext(a.dxf)[0] + "_pdf.png"
            pg.get_pixmap(dpi=110).save(png)
            print("PDF 預覽", png)
        except Exception as ex:
            print("PDF 轉圖略過", ex)


if __name__ == "__main__":
    main()
