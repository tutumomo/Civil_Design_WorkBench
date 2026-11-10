# -*- coding: utf-8 -*-
"""交件品管檢核器（A3 圖紙成果）

把「踩過的坑」變成可自動擋錯的檢查。第二輪比拼前務必先跑這支，全部 PASS 才交件。

用法：
  python check_delivery.py <成果.dxf> [--scale 600] [--layout 全區工程位置圖]
                          [--require-dwg] [--json out.json]

檢查項目（E=錯誤，W=警告）
  E1  doc.audit() 錯誤數須為 0
  E2  $INSUNITS=6、$MEASUREMENT=1
  E3  TOMO 樣式存在且 font=gbenor.shx、bigfont=CHINA1.SHX
  E4  所有 TEXT/MTEXT 一律使用 TOMO（含圖框）
  E5  出圖視口只能有 1 個（id=1 的紙面視口不算）
  E6  視口實測比例 = 指定比例
  E7  視口須落在圖框內框之內
  E8  模型圖元範圍須完整覆蓋視口視窗（避免邊緣留白）
  E9  【重點】新增的圖紙空間標註不得侵入「標題欄帶」「技師執業圖記區」
  E10 新增標註之間不得互相重疊（比例尺數字疊字就是這類）
  E11 建物數 > Hatch 數（漏 Hatch）
  E12 圖層命名須符合 `數字前綴_中文說明`
  E15 【出圖規定】文字出圖字高須為 本文 3／附註 4／標題 5 mm
      圖紙空間直接比對（樣板 A3圖框 原有文字除外）；模型空間文字以「字高×1000/比例」換算（僅計開啟圖層）
  E16 【出圖規定】比例須為標準比例尺（清單見 tools\\drawing_rules.py）
  E17 【出圖規定】顏色 1~8 對應線粗（0.10／0.15~0.20／0.35~0.40 mm）且與圖層一致
      色表與 helper 見 tools\\drawing_rules.py；樣板圖層（圖框、Defpoints…）不計
  E18  出圖型式記錄（DXF 標頭 TOMO_PLOTSTYLE）須為 monochrome.ctb（灰階）
  W1  新增標註壓在視口（地圖）上——可接受但可讀性較差
  W2  沒有 .dwg 兄弟檔（公司實務要 DWG）
  W3  沒有 .pdf 出圖
  W6  DXF 未記錄出圖型式（舊圖或手動出圖）

退出碼：0=全過（可有警告） 1=有錯誤
"""
import os
import re
import sys
import json
import argparse
from collections import Counter

import ezdxf
from ezdxf import bbox as ezb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from drawing_rules import (TEXT_HEIGHTS, is_standard_scale, STANDARD_SCALES,
                           PLOT_STYLE_SHEET, PLOT_STYLE_TAG, plot_style_issues)   # 本項目出圖規定

# ---- A3圖框.dwt 的固定幾何（紙面 mm）----
FRAME_INNER = (10.03, 29.00, 410.27, 287.45)      # 可繪區 x0,y0,x1,y1
TITLE_BLOCK = (9.79, 10.40, 410.27, 29.03)        # 標題欄帶（不得放任何新增標註）
STAMP_ZONE = (363.50, 29.00, 410.30, 80.90)       # 技師執業圖記區（須留白）
TEMPLATE_LAYERS = {"圖框", "執業圖記開關", "Defpoints", "VIEWPORTS", "0"}

LAYER_RE = re.compile(r"^\d{2}_")
MPU = 1000.0     # 每模型單位多少 mm；--units cm 時於 main() 改 10


def est_width(s, h):
    """CHINA1.SHX 中文字實測約 1.2h 寬、gbenor 英數約 0.8h；ezdxf 對 SHX 中文寬度低估約 2 成"""
    return sum(1.2 * h if ord(c) >= 0x2E80 else 0.8 * h for c in s)


def rect_of(e, pad=0.0):
    try:
        b = ezb.extents([e], fast=True)
    except Exception:
        return None
    if not b.has_data:
        return None
    x0, x1 = b.extmin.x, b.extmax.x
    if e.dxftype() == "TEXT" and not e.dxf.get("rotation", 0):
        need = est_width(e.dxf.text, e.dxf.height) - (x1 - x0)
        if need > 0:                                   # 依對齊方式往外擴：左對齊往右、置中兩側、靠右往左
            ha = e.dxf.get("halign", 0)
            if ha in (1, 4):
                x0, x1 = x0 - need / 2, x1 + need / 2
            elif ha == 2:
                x0 -= need
            else:
                x1 += need
    return (x0 - pad, b.extmin.y - pad, x1 + pad, b.extmax.y + pad)


def overlap(a, b, tol=0.0):
    """回傳重疊面積（mm²），tol>0 時容許邊界相接"""
    w = min(a[2], b[2]) - max(a[0], b[0]) - tol
    h = min(a[3], b[3]) - max(a[1], b[1]) - tol
    return w * h if (w > 0 and h > 0) else 0.0


def inside(inner, outer):
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--scale", type=int, default=600)
    ap.add_argument("--units", choices=["m", "cm"], default="m",
                    help="模型空間單位。m(預設) 時 INSUNITS=6、1000mm/單位；"
                         "cm 時 INSUNITS=5、10mm/單位")
    ap.add_argument("--layout", default=None, help="預設取第一個非 Model 版面")
    ap.add_argument("--building-layer", default="20_建物")
    ap.add_argument("--hatch-layer", default="21_建物_HATCH")
    ap.add_argument("--require-dwg", action="store_true")
    ap.add_argument("--plot-style", default=PLOT_STYLE_SHEET,
                    help="出圖型式（CTB）；預設 monochrome.ctb")
    ap.add_argument("--require-layer", action="append", default=[],
                    help="必要圖層（可重複）；該層不存在或沒有圖元即報錯")
    ap.add_argument("--template", default=os.path.join(HERE, "A3圖框_template.dxf"),
                    help="圖框樣板 DXF；其原有文字不受 E15 字高規定約束")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    errs, warns, info = [], [], {}
    if a.units == "cm":
        global MPU
        MPU = 10.0
    doc = ezdxf.readfile(a.dxf)

    # ---- E1 audit ----
    n_audit = len(doc.audit().errors)
    info["audit_errors"] = n_audit
    if n_audit:
        errs.append("E1 audit 錯誤 %d 個" % n_audit)

    # ---- E2 單位 ----
    iu, mm = doc.header.get("$INSUNITS"), doc.header.get("$MEASUREMENT")
    info["INSUNITS"], info["MEASUREMENT"] = iu, mm
    info["units"] = a.units
    want_iu = 6 if a.units == "m" else 5
    if iu != want_iu or mm != 1:
        errs.append("E2 單位不對：$INSUNITS=%s（%s 應 %d）、$MEASUREMENT=%s（應 1）"
                    % (iu, a.units, want_iu, mm))

    # ---- E3/E4 字型 ----
    tomo = doc.styles.get("TOMO") if "TOMO" in doc.styles else None
    if tomo is None:
        errs.append("E3 沒有 TOMO 文字樣式")
    else:
        f, bf = tomo.dxf.font, tomo.dxf.get("bigfont", "")
        info["TOMO"] = {"font": f, "bigfont": bf}
        if f.lower() != "gbenor.shx" or bf.lower() != "china1.shx":
            errs.append("E3 TOMO 字型不對：font=%s bigfont=%s" % (f, bf))
    style_use = Counter()
    for lay in doc.layouts:
        for e in lay.query("TEXT MTEXT"):
            if e.dxf.layer in TEMPLATE_LAYERS:      # 樣板自帶文字不追究
                continue
            style_use[e.dxf.style] += 1
    info["text_styles_used"] = dict(style_use)
    bad_style = {k: v for k, v in style_use.items() if k != "TOMO"}
    if bad_style:
        errs.append("E4 有非 TOMO 文字：%s" % bad_style)

    # ---- 版面 ----
    if a.layout:
        lay = doc.layouts.get(a.layout)
    else:
        lay = [l for l in doc.layouts if l.name != "Model"][0]
    info["layout"] = lay.name

    # ---- E5~E8 視口 ----
    vps = [v for v in lay.query("VIEWPORT") if v.dxf.get("id", 1) != 1]
    info["plot_viewports"] = len(vps)
    if len(vps) != 1:
        errs.append("E5 出圖視口有 %d 個（應為 1）" % len(vps))
    for v in vps:
        w, h, vh = v.dxf.width, v.dxf.height, v.dxf.view_height
        real = vh * MPU / h if h else 0
        info["viewport"] = {"w": round(w, 2), "h": round(h, 2),
                            "view_height": round(vh, 3), "scale": round(real, 1),
                            "center": [round(v.dxf.center.x, 2), round(v.dxf.center.y, 2)]}
        if abs(real - a.scale) > 0.5:
            errs.append("E6 視口比例 1:%.1f（應 1:%d）" % (real, a.scale))
        vr = (v.dxf.center.x - w / 2, v.dxf.center.y - h / 2,
              v.dxf.center.x + w / 2, v.dxf.center.y + h / 2)
        info["viewport_rect"] = [round(x, 2) for x in vr]
        if not inside(vr, (FRAME_INNER[0] - 1, FRAME_INNER[1] - 1,
                           FRAME_INNER[2] + 1, FRAME_INNER[3] + 1)):
            errs.append("E7 視口超出圖框內框：%s vs %s" % (info["viewport_rect"], FRAME_INNER))
        # E8 模型覆蓋
        msp = doc.modelspace()
        mb = ezb.extents(msp, fast=True)
        if mb.has_data:
            need_w = w * a.scale / MPU
            need_h = h * a.scale / MPU
            cx, cy = v.dxf.view_center_point.x, v.dxf.view_center_point.y
            win = (cx - need_w / 2, cy - need_h / 2, cx + need_w / 2, cy + need_h / 2)
            mw, mh = mb.extmax.x - mb.extmin.x, mb.extmax.y - mb.extmin.y
            info["model_extent"] = [round(mw, 1), round(mh, 1)]
            info["window_needed"] = [round(need_w, 1), round(need_h, 1)]
            if mw < need_w * 0.995 or mh < need_h * 0.995:
                warns.append("W0 模型範圍 %.1fx%.1f m 小於視口需求 %.1fx%.1f m，圖面邊緣會留白"
                             % (mw, mh, need_w, need_h))
            info["window_rect"] = [round(x, 1) for x in win]

    # 樣板原有文字位置（含被改字的業主/圖名/案名）；不在此集合者視為新增標註（make_sheet 也寫在「圖框」層）
    tpl_pos = set()
    if a.template and os.path.exists(a.template):
        for tl in ezdxf.readfile(a.template).layouts:
            if tl.name != "Model":
                for e in tl.query("TEXT MTEXT"):
                    tpl_pos.add((round(e.dxf.insert.x, 1), round(e.dxf.insert.y, 1)))
    else:
        warns.append("W7 找不到圖框樣板 %s，改以圖層判定新增標註" % a.template)

    def is_tpl(e):
        if tpl_pos:
            return (round(e.dxf.insert.x, 1), round(e.dxf.insert.y, 1)) in tpl_pos
        return e.dxf.layer in TEMPLATE_LAYERS

    # ---- E9/E10 版面碰撞（幾何判定，不依賴圖層）----
    # 樣板本身的文字互不重疊（實測 baseline = 0），所以任何重疊都是人為造成。
    all_txt = []
    for e in lay.query("TEXT MTEXT"):
        r = rect_of(e, pad=0.3)
        if not r:
            continue
        txt = (e.dxf.text if e.dxftype() == "TEXT" else e.text).strip().replace("\n", "/")
        all_txt.append((txt[:24], r, "樣板" if is_tpl(e) else e.dxf.layer))
    added = [t for t in all_txt if t[2] != "樣板"]
    info["paper_texts"], info["added_annotations"] = len(all_txt), len(added)

    def straddles(r, zone):
        """文字跨越保護區邊界＝壓字；完全在區內＝可能是樣板本身的欄位標籤"""
        inx = overlap(r, zone) > 0
        if not inx:
            return False
        fully = inside(r, zone)
        return not fully

    for txt, r, ly in all_txt:
        if straddles(r, TITLE_BLOCK):
            errs.append("E9 「%s」跨越標題欄邊界（y=29.03）：bbox=(%.1f,%.1f)-(%.1f,%.1f)"
                        % (txt, r[0], r[1], r[2], r[3]))
        elif straddles(r, STAMP_ZONE):
            errs.append("E9 「%s」跨越技師執業圖記區邊界" % txt)
        elif ly == "樣板":
            continue
        elif inside(r, TITLE_BLOCK):                  # 標題欄填值（設計/繪圖/日期…）屬正常
            if ly not in TEMPLATE_LAYERS:
                warns.append("W6 「%s」整塊落在標題欄內（非樣板圖層），請目視確認是否壓到欄位" % txt)
        elif not inside(r, FRAME_INNER):
            errs.append("E9 「%s」超出圖框內框：bbox=(%.1f,%.1f)-(%.1f,%.1f)" % (txt, r[0], r[1], r[2], r[3]))

    for i in range(len(all_txt)):
        for j in range(i + 1, len(all_txt)):
            if overlap(all_txt[i][1], all_txt[j][1], tol=0.15) > 0:
                errs.append("E10 「%s」與「%s」疊字" % (all_txt[i][0], all_txt[j][0]))

    if "viewport_rect" in info:
        for txt, r, ly in added:
            if overlap(r, tuple(info["viewport_rect"])) > 0 and ly.startswith(("91_", "92_")):
                warns.append("W1 「%s」壓在地圖視口上（建議移到圖框邊界留白區）" % txt)
                break

    # ---- E11 建物 Hatch ----
    msp = doc.modelspace()
    nb = len([e for e in msp.query("LWPOLYLINE") if e.dxf.layer == a.building_layer])
    nh = len([e for e in msp.query("HATCH") if e.dxf.layer == a.hatch_layer])
    info["buildings"], info["building_hatches"] = nb, nh
    if nb and nh < nb:
        errs.append("E11 建物 %d 棟但 Hatch 只有 %d 個（漏 Hatch）" % (nb, nh))
    if nb == 0:
        warns.append("W2 建物圖層 %s 沒有圖元——確認建物資料源是否漏抓" % a.building_layer)

    # ---- E12 圖層命名（只檢查「有圖元」的圖層，排除樣板圖層）----
    used = Counter()
    for l in doc.layouts:
        for e in l:
            used[e.dxf.layer] += 1
    bad_layers = [n for n in used if n not in TEMPLATE_LAYERS and not LAYER_RE.match(n)]
    info["layers_violating_naming"] = sorted(bad_layers)
    if bad_layers:
        warns.append("W3 圖層命名不合規範（數字前綴_中文說明）：%s" % sorted(bad_layers))

    # ---- E15 字高（出圖規定）----
    def text_h(e):
        return e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height

    def legal(h_mm):
        return any(abs(h_mm - s) <= 0.02 for s in TEXT_HEIGHTS)

    bad_h = []
    for e in lay.query("TEXT MTEXT"):
        if is_tpl(e):                                 # 樣板 A3圖框 原有文字不受規定約束
            continue
        h = text_h(e)
        if not legal(h):
            txt = (e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()).strip().replace("\n", "/")
            bad_h.append("圖紙「%s」%.2f mm" % (txt[:16], h))
    msp = doc.modelspace()
    off = {l.dxf.name for l in doc.layers if l.is_off() or l.is_frozen()}
    for e in msp.query("TEXT MTEXT"):
        if e.dxf.layer in off:
            continue
        h = text_h(e) * MPU / a.scale
        if not legal(h):
            txt = (e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()).strip().replace("\n", "/")
            bad_h.append("模型「%s」出圖 %.2f mm" % (txt[:16], h))
    info["text_height_violations"] = len(bad_h)
    if bad_h:
        errs.append("E15 字高不符出圖規定（本文 3／附註 4／標題 5 mm）%d 處：%s%s"
                    % (len(bad_h), "；".join(bad_h[:8]), " …" if len(bad_h) > 8 else ""))

    # ---- E16 標準比例（出圖規定）----
    if not is_standard_scale(a.scale):
        errs.append("E16 比例 1/%d 不是標準比例尺（%s）" % (a.scale, "、".join("1/%d" % s for s in STANDARD_SCALES)))

    # ---- E17 出圖樣式：顏色 1~8 → 線粗（出圖規定）----
    ps_err, ps_warn = plot_style_issues(doc, skip=TEMPLATE_LAYERS)
    info["plot_style_violations"] = len(ps_err)
    if ps_err:
        errs.append("E17 出圖樣式不符（顏色 1~8 對應線粗）%d 處：%s%s"
                    % (len(ps_err), "；".join(ps_err[:6]), " …" if len(ps_err) > 6 else ""))
    warns += ps_warn

    # ---- E18 出圖型式標記（monochrome.ctb）----
    try:
        tag = doc.header.custom_vars.get(PLOT_STYLE_TAG)
    except KeyError:
        tag = None
    info["plot_style"] = tag
    if tag is None:
        errs.append("E18 DXF 未記錄出圖型式（應為 %s）；請用 apply_plot_style.py 補寫" % a.plot_style)
    elif tag != a.plot_style:
        errs.append("E18 出圖型式記錄為 %s，應為 %s（灰階出圖）" % (tag, a.plot_style))

    # ---- W 檔案兄弟 ----
    base = os.path.splitext(a.dxf)[0]
    has_dwg = os.path.exists(base + ".dwg")
    info["has_dwg"] = has_dwg
    if a.require_dwg and not has_dwg:
        errs.append("E13 缺少 .dwg（公司實務以 DWG 交件）")
    elif not has_dwg:
        warns.append("W4 沒有 .dwg 兄弟檔")
    d = os.path.dirname(os.path.abspath(a.dxf))
    pdfs = []
    for root in (d, os.path.join(d, "out")):
        if os.path.isdir(root):
            pdfs += [f for f in os.listdir(root) if f.lower().endswith(".pdf")]
    info["pdf_found"] = pdfs
    if not pdfs:
        warns.append("W5 同資料夾沒有 .pdf 出圖")

    # ---- E14 必要圖層 ----
    if a.require_layer:
        miss = []
        for name in a.require_layer:
            if used.get(name, 0) == 0:
                miss.append(name)
        info["required_layers_missing"] = miss
        if miss:
            errs.append("E14 必要圖層不存在或沒有圖元：%s" % miss)

    # ---- 輸出 ----
    print("=" * 62)
    print("交件品管檢核：%s" % os.path.basename(a.dxf))
    print("=" * 62)
    for k, v in info.items():
        print("  %-22s %s" % (k, v))
    print("-" * 62)
    if errs:
        print("✗ 錯誤 %d 項" % len(errs))
        for e in errs:
            print("   " + e)
    else:
        print("✓ 錯誤 0 項")
    if warns:
        print("△ 警告 %d 項" % len(warns))
        for w in warns:
            print("   " + w)
    print("-" * 62)
    print("結論：%s" % ("可交件" if not errs else "不可交件，先修"))

    if a.json:
        json.dump({"file": a.dxf, "info": info, "errors": errs, "warnings": warns},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    sys.exit(0 if not errs else 1)


if __name__ == "__main__":
    main()
