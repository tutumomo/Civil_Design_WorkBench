r"""從 DXF 圖面量測數量，並與案件檔的衍生數量對帳。

為什麼要這個模組
----------------
先前所有數量都是「人填」或「模型派生」。但圖才是最終交付物 —— 如果圖上畫的
跟數量表算的不是同一個東西，那兩邊都不可信。

本模組把圖讀回來量：圖層長度、閉合多邊形面積（可扣內腔）、圖塊數量，
再跟 `qty_models` 的衍生值比對。**對不起來就代表圖與數量已經分家。**

單位：DXF 模型空間 1 unit = 1 m（AGENTS.md §2 契約），故長度 m、面積 m²。

⚠ 面積量測的關鍵：**必須扣掉內腔**
--------------------------------
實測三張斷面圖：

| 圖 | 30_ 圖層多邊形 | 扣內腔後 | 模型斷面積 |
|---|---|---|---|
| 擋土牆重力式 | 3.3750 | — | 3.375 ✓ |
| 擋土牆懸臂式 | 1.7520 | — | 1.752 ✓ |
| 排水溝 U 型 | 0.7350 | − 0.3600 = **0.3750** | 0.375 ✓ |

排水溝的 30_ 圖層只畫「外框矩形」（W×總高 = 0.70×1.05 = 0.735），
內腔（B×H = 0.40×0.90 = 0.360）放在 `34_溝內腔`。
**不扣內腔，混凝土量會多算 96%。**
"""

import math
import os

import ezdxf


def _poly_area(pts):
    """鞋帶公式（有號面積；逆時針為正）。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _entity_pts(e):
    try:
        return [(v[0], v[1]) for v in e.get_points()]
    except Exception:
        return []


def measure(dxf_path, void_layers=("34_溝內腔",), skip_layers=("90_圖框",)):
    """量測 DXF 模型空間，回傳 {layer: {area, length, count, entities}}。

    area   —— 閉合多邊形 |面積| 之和（m²）
    length —— LINE／LWPOLYLINE 長度之和（m）
    count  —— 圖元數
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    out = {}
    for e in msp:
        lay = e.dxf.layer
        if lay in skip_layers or lay.startswith("90_"):
            continue
        d = out.setdefault(lay, {"area": 0.0, "length": 0.0, "count": 0, "entities": {}})
        t = e.dxftype()
        d["count"] += 1
        d["entities"][t] = d["entities"].get(t, 0) + 1
        if t == "LWPOLYLINE":
            pts = _entity_pts(e)
            if e.closed and len(pts) >= 3:
                d["area"] += abs(_poly_area(pts))
            for i in range(len(pts) - 1):
                d["length"] += math.dist(pts[i], pts[i + 1])
        elif t == "LINE":
            d["length"] += math.dist((e.dxf.start.x, e.dxf.start.y),
                                    (e.dxf.end.x, e.dxf.end.y))
        elif t == "CIRCLE":
            d["length"] += 2 * math.pi * e.dxf.radius
    for d in out.values():
        d["area"] = round(d["area"], 4)
        d["length"] = round(d["length"], 2)
    return out


def net_area(meas, gross_layer="30_擋土牆混凝土", void_layers=("34_溝內腔",)):
    """混凝土淨面積 = 外框面積 − 內腔面積。"""
    gross = meas.get(gross_layer, {}).get("area", 0.0)
    void = sum(meas.get(l, {}).get("area", 0.0) for l in void_layers)
    return round(gross - void, 4), round(gross, 4), round(void, 4)


REBAR_LAYER = "40_鋼筋"


def measure_rebar(dxf_path, max_radius=0.02):
    """量配筋圖上的鋼筋圓點，推算各排的實際間距（支／米）。

    `40_鋼筋` 圖層上混了兩種圓：
      · 真正的鋼筋斷面（半徑 = 鋼筋徑/2，D13≈0.0065、D16≈0.008）
      · 筋號圓標（半徑 0.055，用來標 A／B／C）
    必須用半徑過濾，否則圓標會被當成鋼筋（實測會多出 3 個假點）。

    回傳 [{x_m, n, y_lo, y_hi, span_m, spacing_m, per_m}]，依 x 分群。
    """
    import ezdxf as _ez
    doc = _ez.readfile(dxf_path)
    cs = [e for e in doc.modelspace().query("CIRCLE")
          if e.dxf.layer == REBAR_LAYER and e.dxf.radius <= max_radius]
    cols = {}
    for e in cs:
        c = e.dxf.center
        cols.setdefault(round(c.x / 0.010), []).append((c.x, c.y))
    out = []
    for k in sorted(cols):
        pts = sorted(cols[k], key=lambda p: p[1])
        n = len(pts)
        span = pts[-1][1] - pts[0][1]
        sp = span / (n - 1) if n > 1 else None
        out.append({"x_m": round(sum(p[0] for p in pts) / n, 3), "n": n,
                    "y_lo": round(pts[0][1], 3), "y_hi": round(pts[-1][1], 3),
                    "span_m": round(span, 3),
                    "spacing_m": round(sp, 3) if sp else None,
                    "per_m": round(1.0 / sp, 1) if sp else None})
    return out


def check_rebar(dxf_path, case_path):
    """把配筋圖量到的間距與案件（= 配筋表）的設計間距對帳。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    model, q, _ = CC.quantity_context(case)
    cols = measure_rebar(dxf_path)
    # 設計間距：直接從配筋設計算（case 的 section 段只有比例與檔名，沒有間距）
    want = set()
    sec = case.get("section") or {}
    for k in ("stem_spacing_mm", "base_spacing_mm"):
        if sec.get(k):
            want.add(int(sec[k]))
    if not want:
        _dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "design")
        if _dd not in sys.path:
            sys.path.insert(0, _dd)
        try:
            import rc_design as RC
            if model == "wall":
                import retaining_wall as RW
                _wr = RW.analyse(q, soil=case.get("soil") or {})
                if _wr["wall_type"] != "gravity":
                    _st = RC.design_cantilever_stem(q, _wr)
                    _bs = RC.design_base_slab(q, _wr)
                    want.add(int(_st["main"]["spacing_mm"]))
                    if _bs:
                        want.add(int(_bs["members"][0]["main"]["spacing_mm"]))
            elif model == "channel":
                import channel_hydraulics as CH
                _hy = case.get("hydraulics") or {}
                _hr = CH.analyse(float(_hy.get("design_flow_m3s") or 0.5),
                                 float(q["inner_width_m"]), float(q["depth_m"]),
                                 float(_hy.get("slope") or 0.005),
                                 {"manning_n": float(_hy.get("manning_n") or 0.014)})
                want.add(int(RC.design_channel_wall(q, _hr)["main"]["spacing_mm"]))
        except Exception:
            pass
    got = sorted({int(round(c["spacing_m"] * 1000)) for c in cols
                  if c["spacing_m"] and 0.05 <= c["spacing_m"] <= 1.0})
    return {"cols": cols, "design_mm": sorted(want), "found_mm": got,
            "ok": None if not want else all(any(abs(g - w) <= 10 for g in got) for w in want)}


PAVING_LAYER = "15_刨鋪範圍"


def check_road(case_path, dxf_path, tol_pct=1.0):
    r"""道路案：量「15_刨鋪範圍」多邊形的面積，與案件數量對帳。

    道路平面圖是「現況底圖」，本來就沒有刨鋪範圍；這一層由
    `tools\takeoff\paving_extent.py` 從實測邊線產生後再拿來對帳。
    """
    import sys
    meas = measure(dxf_path)
    if PAVING_LAYER not in meas:
        return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
                "model": "road", "dxf": os.path.basename(dxf_path),
                "rows": [], "diff_pct": None, "tol_pct": tol_pct,
                "ok": False, "measure": meas,
                "error": "圖上沒有圖層「%s」—— 刨鋪範圍未畫出，無法對帳。"
                         "請先用 tools/takeoff/paving_extent.py 產生。" % PAVING_LAYER}
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    _, q, _ = CC.unit_context(case) if hasattr(CC, "unit_context") else CC.quantity_context(case)
    area_drawn = meas[PAVING_LAYER]["area"]
    # ⚠ 道路長度**不可**用「周長 ÷ 2」：閉合多邊形的周長 = 兩側邊線 + 兩個端蓋，
    # 除 2 會把端蓋算進去（實測 164.18 vs 實際 161.15，差 2%）。長度請用
    # paving_extent.py 輸出的 JSON（那裡有沿中心線算的弧長）。
    # 道路對帳只比**面積** —— 它才是決定 AC 體積的量（area × thickness）。
    rows, ok = [], True
    exp = float(q.get("area_m2") or 0)
    if exp:
        d = abs(area_drawn - exp) / exp * 100.0
        good = d <= tol_pct
        ok = ok and good
        rows.append({"item": "刨鋪面積", "drawn": round(area_drawn, 2),
                     "model": round(exp, 2), "diff_pct": round(d, 4),
                     "ok": good, "unit": "m²"})
    else:
        rows.append({"item": "刨鋪面積", "drawn": round(area_drawn, 2),
                     "model": None, "diff_pct": None, "ok": None, "unit": "m²"})
    return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
            "model": "road", "dxf": os.path.basename(dxf_path),
            "rows": rows, "diff_pct": max((r["diff_pct"] or 0) for r in rows) if rows else None,
            "tol_pct": tol_pct, "ok": ok, "measure": meas}


def check_case(case_path, dxf_path, tol_pct=0.5):
    """把圖面量測值與案件檔的衍生數量對帳。"""
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "case_package"))
    import case_core as CC

    case = CC.load(case_path)
    model, q, _ = CC.quantity_context(case)
    meas = measure(dxf_path)
    net, gross, void = net_area(meas)

    expect = float(q.get("section_area_m2") or 0)
    diff_pct = (abs(net - expect) / expect * 100.0) if expect else None
    rows = [
        {"item": "圖面混凝土外框面積", "drawn": gross, "model": None, "unit": "m²"},
        {"item": "圖面內腔面積（應扣）", "drawn": void, "model": None, "unit": "m²"},
        {"item": "圖面混凝土淨面積", "drawn": net, "model": round(expect, 4), "unit": "m²"},
    ]
    ok = diff_pct is not None and diff_pct <= tol_pct
    return {"case": os.path.basename(os.path.dirname(os.path.abspath(case_path))),
            "model": model, "dxf": os.path.basename(dxf_path),
            "rows": rows, "diff_pct": round(diff_pct, 4) if diff_pct is not None else None,
            "tol_pct": tol_pct, "ok": ok, "measure": meas}


def format_report(r):
    L = [f"案件：{r['case']}（model={r['model']}）  DXF：{r['dxf']}", ""]
    L.append("  圖層量測：")
    for lay, d in sorted(r["measure"].items()):
        L.append("    %-18s 面積 %8.4f m²  長度 %9.2f m  圖元 %d %s"
                 % (lay, d["area"], d["length"], d["count"],
                    d["entities"] if d["entities"] else ""))
    L.append("")
    L.append("  對帳：")
    for row in r["rows"]:
        m = "—" if row["model"] is None else "%.4f" % row["model"]
        L.append("    %-22s 圖面 %.4f %s ／ 模型 %s"
                 % (row["item"], row["drawn"], row["unit"], m))
    if r["diff_pct"] is not None:
        L.append("    → 差異 %.4f%%（容許 %.2f%%）  %s"
                 % (r["diff_pct"], r["tol_pct"], "符合" if r["ok"] else "**不符**"))
    else:
        L.append("    → 案件檔無 section_area_m2，無法對帳")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DXF 圖面數量量測與案件檔對帳")
    ap.add_argument("dxf", help="要量測的 DXF")
    ap.add_argument("--case", help="案件 JSON（給了就做對帳）")
    ap.add_argument("--tol", type=float, default=0.5, help="容許差異 %%（預設 0.5）")
    ap.add_argument("--rebar", action="store_true", help="改量配筋圖的鋼筋圓點間距")
    a = ap.parse_args()
    if a.rebar:
        cols = measure_rebar(a.dxf)
        print("  鋼筋圓點分群（已排除筋號圓標 r>0.02）：")
        for c in cols:
            print("    x≈%5.3f  n=%2d  y %.3f~%.3f（跨 %.3f）"
                  % (c["x_m"], c["n"], c["y_lo"], c["y_hi"], c["span_m"])
                  + ("  間距 %.3f m → %4.1f 支/米" % (c["spacing_m"], c["per_m"])
                     if c["spacing_m"] else "  （單點）"))
        if a.case:
            r = check_rebar(a.dxf, a.case)
            print("\n  配筋表設計間距 %s mm；圖面量到 %s mm → %s"
                  % (r["design_mm"], r["found_mm"],
                     "相符" if r["ok"] else ("無法比對" if r["ok"] is None else "**不符**")))
            raise SystemExit(0 if (r["ok"] is not False) else 1)
        raise SystemExit(0)
    if a.case:
        r = check_case(a.case, a.dxf, a.tol)
        if r.get("error") or r["model"] == "road":
            # 道路案（或斷面圖缺 section_area_m2）→ 走道路對帳
            r2 = check_road(a.case, a.dxf, max(a.tol, 1.0))
            if not r.get("error") and not (r["diff_pct"] is None):
                pass
            print(r2.get("error") or "")
            for row in r2["rows"]:
                m = "—" if row["model"] is None else "%.2f" % row["model"]
                d = "—" if row["diff_pct"] is None else "%.4f%%" % row["diff_pct"]
                v = "" if row["ok"] is None else ("  符合" if row["ok"] else "  **不符**")
                print("    %-10s 圖面 %10.2f ／ 案件 %s ／ 差異 %s%s"
                      % (row["item"], row["drawn"], m, d, v))
            raise SystemExit(0 if r2["ok"] else 1)
        print(format_report(r))
        raise SystemExit(0 if r["ok"] else 1)
    meas = measure(a.dxf)
    for lay, d in sorted(meas.items()):
        print("  %-18s 面積 %8.4f m²  長度 %9.2f m  圖元 %d"
              % (lay, d["area"], d["length"], d["count"]))
