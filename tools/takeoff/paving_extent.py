r"""由道路實測邊線產生「刨鋪範圍」多邊形，並與案件數量對帳。

為什麼要這個模組
----------------
道路案的數量（length_m=160.84、area_m2=850.6）來自當初的實測紀錄，但**圖上沒有畫出
刨鋪範圍** —— `現況平面圖` 只畫現況道路邊線（圖上量到的兩條邊線合計 51 m，
與 160.84 m 完全不符）。於是道路這條線的「圖／數對帳」一直是空的。

本模組把 `road_edges_meta.json` 裡的實測幾何（`edge_a`／`edge_b` 各 726 點、
設計中心線 `design_cl`、樁號 `design_s1`／`s2`）組成刨鋪範圍多邊形：
**沿中心線累積弧長裁到 s1~s2**，再把兩側邊線首尾相接圍成閉合多邊形。

⚠ 不裁切的後果
------------
直接用整條邊線圍多邊形 = **915.0 m²**，比案件 850.6 多 7.57%。
原因：邊線含兩端延伸，超出設計樁號範圍（全長 173.24 m vs 設計 160.965 m）。
裁到 s1~s2 後 = **851.1 m²**，與案件 **差 0.06%**。

輸出：`<案名>_刨鋪範圍_TWD97.dxf`（圖層 `15_刨鋪範圍`）＋ `_刨鋪範圍.json`。
**不動既有交付的 A3 圖** —— 要不要把這層併進 A3 屬於改動已交付檔案，須使用者同意。
"""

import json
import math
import os
import sys

import ezdxf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drawing_rules import add_plot_layer, tag_plot_style   # noqa: E402

LAYER = "15_刨鋪範圍"


def _arclen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _area(poly):
    s, n = 0.0, len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def build_paving_polygon(meta_path):
    """回傳 {poly, area_m2, length_m, s1, s2, avg_width_m, trimmed}。"""
    m = json.load(open(meta_path, encoding="utf-8"))
    if "edge_a" not in m or "edge_b" not in m:
        raise ValueError("meta 缺少 edge_a／edge_b，無法建立刨鋪範圍")
    a, b, cl = m["edge_a"], m["edge_b"], m.get("design_cl")
    s1 = float(m.get("design_s1") or 0.0)
    s2 = float(m.get("design_s2") or 0.0)

    # 無樁號資料 → 用整條邊線（並在回傳中標明未裁切）
    if not cl or s2 <= s1:
        poly = a + list(reversed(b))
        L = (_arclen(a) + _arclen(b)) / 2.0
        A = _area(poly)
        return {"poly": poly, "area_m2": A, "length_m": L, "s1": None, "s2": None,
                "avg_width_m": A / L if L else 0.0, "trimmed": False}

    cum = [0.0]
    for i in range(len(cl) - 1):
        cum.append(cum[-1] + math.dist(cl[i], cl[i + 1]))

    def idx_at(s):
        for i in range(len(cum)):
            if cum[i] >= s:
                return i
        return len(cum) - 1

    def interp(pts, i, s):
        s0, s1v = cum[i - 1], cum[i]
        if abs(s1v - s0) < 1e-9:
            return tuple(pts[i])
        t = (s - s0) / (s1v - s0)
        return (pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t,
                pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t)

    i1, i2 = idx_at(s1), idx_at(s2)
    ea = [interp(a, i1, s1)] + a[i1:i2] + [interp(a, i2, s2)]
    eb = [interp(b, i1, s1)] + b[i1:i2] + [interp(b, i2, s2)]
    poly = ea + list(reversed(eb))
    A = _area(poly)
    L = (_arclen(ea) + _arclen(eb)) / 2.0
    return {"poly": poly, "area_m2": A, "length_m": L, "s1": s1, "s2": s2,
            "avg_width_m": A / L if L else 0.0, "trimmed": True}


def write_dxf(res, out_path, crs_note="TWD97 TM2 EPSG:3826"):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6          # 公尺
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()
    add_plot_layer(doc, LAYER, importance="major")   # 刨鋪範圍屬重要線（0.35 mm）
    msp.add_lwpolyline(res["poly"], close=True, dxfattribs={"layer": LAYER})
    tag_plot_style(doc)
    doc.saveas(out_path)
    return out_path


def check_against_case(res, case_path, tol_pct=1.0):
    """與案件檔的 length_m／area_m2 對帳。"""
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    _, q, _ = CC.quantity_context(case)
    rows, ok = [], True
    for key, got, label in (("length_m", res["length_m"], "道路長度"),
                            ("area_m2", res["area_m2"], "刨鋪面積")):
        exp = float(q.get(key) or 0)
        if not exp:
            rows.append({"item": label, "drawn": round(got, 2), "model": None,
                         "diff_pct": None, "ok": None})
            continue
        d = abs(got - exp) / exp * 100.0
        good = d <= tol_pct
        ok = ok and good
        rows.append({"item": label, "drawn": round(got, 2), "model": round(exp, 2),
                     "diff_pct": round(d, 4), "ok": good})
    return {"rows": rows, "ok": ok, "tol_pct": tol_pct,
            "trimmed": res["trimmed"], "s1": res["s1"], "s2": res["s2"],
            "avg_width_m": round(res["avg_width_m"], 3)}


def format_report(res, chk=None):
    L = []
    if res["trimmed"]:
        L.append("  刨鋪範圍：沿中心線裁切至樁號 %.2f ～ %.2f m（全長 %.2f m）"
                 % (res["s1"], res["s2"], res["s2"] - res["s1"]))
    else:
        L.append("  ⚠ 無樁號資料，採整條邊線（未裁切）—— 面積會偏大")
    L.append("  長度 %.2f m、面積 %.1f m²、等效平均寬度 %.3f m"
             % (res["length_m"], res["area_m2"], res["avg_width_m"]))
    if chk:
        L.append("")
        L.append("  對帳：")
        for r in chk["rows"]:
            m = "—" if r["model"] is None else "%.2f" % r["model"]
            d = "—" if r["diff_pct"] is None else "%.4f%%" % r["diff_pct"]
            v = "" if r["ok"] is None else ("  符合" if r["ok"] else "  **不符**")
            L.append("    %-10s 圖面 %10.2f ／ 案件 %s ／ 差異 %s%s"
                     % (r["item"], r["drawn"], m, d, v))
        L.append("    → %s（容許 %.2f%%）"
                 % ("全部符合" if chk["ok"] else "有未符合項", chk["tol_pct"]))
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="由實測邊線產生刨鋪範圍並與案件數量對帳")
    ap.add_argument("meta", help="road_edges_meta.json")
    ap.add_argument("--out", help="輸出 DXF（圖層 15_刨鋪範圍）")
    ap.add_argument("--case", help="案件 JSON（給了就對帳）")
    ap.add_argument("--tol", type=float, default=1.0, help="容許差異 %%（預設 1.0）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = build_paving_polygon(a.meta)
    chk = check_against_case(res, a.case, a.tol) if a.case else None
    print(format_report(res, chk))
    if a.out:
        write_dxf(res, a.out)
        print("\n  已輸出 %s" % a.out)
        js = os.path.splitext(a.out)[0] + ".json"
        json.dump({k: res[k] for k in ("area_m2", "length_m", "s1", "s2",
                                       "avg_width_m", "trimmed")},
                  open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print()
        print(json.dumps({k: res[k] for k in ("area_m2", "length_m", "s1", "s2",
                                              "avg_width_m", "trimmed")},
                         ensure_ascii=False, indent=1))
    raise SystemExit(0 if (chk is None or chk["ok"]) else 1)
