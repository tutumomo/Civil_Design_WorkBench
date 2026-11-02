r"""排水溝水力計算（Manning）——由設計流量反推 U 型溝斷面。

為什麼要這個模組
----------------
先前排水溝斷面（B=0.60、H=0.90）是**設計假設值**：沒有流量、沒有流速、沒有縱坡。
那種圖能拿去排版，但拿到工地，第一個問題會是「這個斷面為什麼夠？」

本模組把水理算出來：曼寧公式求等速流、檢核流速上下限、算出餘裕（出水高），
並能反推「通過要求的最小斷面」。

規範依據（已查證條文）
--------------------
《水土保持技術規範》第 82~87 條（坡地排水系統），民國 114 年 5 月 7 日修正
（農農保字第1142667525號公告）。全文存於 `data\法規\水土保持技術規範_1140507_全文.txt`。

| 項目 | 條文值 | 條號 |
|---|---|---|
| 平均流速 | v = (1/n)·R^(2/3)·S^(1/2)，R=A/P | 第 84 條 |
| 最小容許流速（混凝土／RC） | **≥ 0.8 m/s**（避免淤積） | 第 85 條一 |
| 最大容許流速（混凝土，常流水） | **4.57~6.10 m/s**（程式取 4.57 保守） | 第 85 條二(一) |
| 最大容許流速（無常流） | 混凝土 6.1、RC 12 m/s | 第 85 條二(二) |
| 出水高 | **設計水深 × 25%**，最小 **20 cm** | 第 86 條 |
| 設計洪水量重現期 | 坡地農地 10 年；其他非農業使用 25 年 | 第 83 條一 |
| 邊溝坡度 | 陡於 0.2%；山區農路陡於 0.5% | 第 78 條一(一) |
| 側溝最小寬深 | 寬度及深度 ≥ 30 cm | 第 78 條一(二) |
| 涵管 | 不設計滿流，水深 ≤ 內徑 0.75 倍 | 第 87 條 |

**仍屬慣例、非條文的只有兩項**：曼寧粗糙係數 n（第84條只給公式，n 依材料選）、
容量安全係數 1.2（保守加成）。此二者於報告中標明即可。

單位：m、m³/s、m/s
"""

import math

G = 9.81

# ⚠ 2026-10-28 依《水土保持技術規範》（民國114年5月7日修正）條文修正：
#   先前用「工程慣例值」，實測有三處與條文不符（最小流速 0.6→0.8、最大流速 3.0→4.57、
#   出水高 20%→25%）。現在全部改成條文值並標註條號。
DEFAULTS = {
    "manning_n": 0.014,        # 混凝土一般粗糙度（第84條僅規定公式，n 值仍須依材料選定）
    # 第 85 條一：混凝土或鋼筋混凝土排水設施最小容許流速 0.8 m/s
    "min_velocity": 0.8,
    # 第 85 條二(一)：混凝土（常流水）最大容許流速 4.57~6.10，取保守下限 4.57
    # 第 85 條二(二)：無常流時混凝土 6.1 m/s、鋼筋混凝土 12 m/s
    "max_velocity": 4.57,
    "max_velocity_no_flow_conc": 6.1,
    "max_velocity_no_flow_rc": 12.0,
    "capacity_sf": 1.2,        # Q_cap / Q_design（慣例，非條文）
    # 第 86 條：出水高依設計水深 25% 計算，最小值 20 cm（L型、拋物線型除外）
    "freeboard_min_m": 0.20,
    "freeboard_ratio": 0.25,
    # 第 78 條一(一)：邊溝坡度須陡於 0.2%；山區農路邊溝須陡於 0.5%
    "slope_min": 0.002,
    "slope_min_mountain_farm": 0.005,
    "slope_max": 0.10,
    # 第 78 條一(二)：U形／矩形／梯形側溝之寬度及深度最小 30 cm
    "min_dim_m": 0.30,
    # 第 78 條二(一)：橫向排水以每隔 150 m 設置一處為原則
    "cross_drain_spacing_m": 150.0,
    # 第 87 條：涵管不設計滿流，水深不大於內徑 0.75 倍
    "culvert_max_fill_ratio": 0.75,
}


def section_props(b, h):
    """矩形（U 型溝內腔）通水斷面性質。b=內寬 m，h=水深 m。"""
    A = b * h
    P = b + 2 * h                     # 濕周（U 型溝：底 + 兩側）
    R = A / P if P > 0 else 0.0
    T = b                             # 水面寬
    return dict(A=A, P=P, R=R, T=T, b=b, h=h)


def capacity(b, h, n, S):
    """曼寧公式：Q = (1/n) A R^(2/3) S^(1/2)。"""
    pr = section_props(b, h)
    if pr["R"] <= 0 or S <= 0:
        return 0.0, pr
    Q = (1.0 / n) * pr["A"] * pr["R"] ** (2.0 / 3.0) * math.sqrt(S)
    return Q, pr


def normal_depth(Q, b, n, S, h_max=10.0, tol=1e-6):
    """給定流量求正常水深（二分法，單調遞增 → 收斂保證）。"""
    lo, hi = 0.0, h_max
    if capacity(b, hi, n, S)[0] < Q:
        return None                       # 斷面容量不足
    for _ in range(200):
        mid = (lo + hi) / 2.0
        Qm = capacity(b, mid, n, S)[0]
        if Qm < Q:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def analyse(Q_design, b, h_total, S, params=None):
    """檢核既有斷面。

    Q_design：設計流量 m³/s
    b：內寬 m；h_total：溝深（內腔高） m；S：縱坡（小數，0.005 = 0.5%）
    """
    p = dict(DEFAULTS, **(params or {}))
    n = float(p["manning_n"])

    Q_cap, pr = capacity(b, h_total, n, S)
    V_full = Q_cap / pr["A"] if pr["A"] > 0 else 0.0

    h_n = normal_depth(Q_design, b, n, S, h_max=h_total * 1.5)
    fb_req = max(float(p["freeboard_min_m"]), float(p["freeboard_ratio"]) * (h_n or 0.0))

    checks = []

    # 1) 容量
    checks.append({
        "item": "通水容量（Q_cap ≥ %.2f×Q_design）" % float(p["capacity_sf"]),
        "value": Q_cap, "limit": Q_design * float(p["capacity_sf"]),
        "ok": Q_cap >= Q_design * float(p["capacity_sf"]), "unit": "m³/s"})

    # 2) 正常水深 vs 溝深（須留出水高）
    if h_n is None:
        checks.append({"item": "正常水深（斷面容量不足）", "value": None,
                       "limit": h_total, "ok": False, "unit": "m"})
        V_design = None
    else:
        checks.append({
            "item": "正常水深 h_n + 出水高 ≤ 溝深",
            "value": h_n + fb_req, "limit": h_total,
            "ok": (h_n + fb_req) <= h_total + 1e-9, "unit": "m"})
        pr_n = section_props(b, h_n)
        V_design = Q_design / pr_n["A"] if pr_n["A"] > 0 else 0.0
        checks.append({
            "item": "設計流速 ≥ 最小流速（避免淤積）",
            "value": V_design, "limit": float(p["min_velocity"]),
            "ok": V_design >= float(p["min_velocity"]), "unit": "m/s"})
        checks.append({
            "item": "設計流速 ≤ 最大流速（避免沖刷）",
            "value": V_design, "limit": float(p["max_velocity"]),
            "ok": V_design <= float(p["max_velocity"]), "unit": "m/s"})
        # 福祿數（自由水面流不宜為臨界流 0.9~1.1）
        Fr = V_design / math.sqrt(G * pr_n["A"] / pr_n["T"]) if pr_n["A"] > 0 else 0.0
        checks.append({
            "item": "福祿數（避開臨界流 0.9~1.1）",
            "value": Fr, "limit": "0.9~1.1",
            "ok": not (0.9 <= Fr <= 1.1), "unit": "-"})

    # ---- 第 78 條：邊溝坡度與最小寬深 ----
    s_min = float(p["slope_min"])
    checks.append({
        "item": "邊溝坡度（第78條一(一)：須陡於 0.2%）",
        "value": S * 100, "limit": "> %.2f%%" % (s_min * 100),
        "ok": S > s_min, "unit": "%"})
    min_dim = float(p["min_dim_m"])
    checks.append({
        "item": "側溝寬度（第78條一(二)：最小 30 cm）",
        "value": b, "limit": "≥ %.2f m" % min_dim,
        "ok": b >= min_dim - 1e-9, "unit": "m"})
    checks.append({
        "item": "側溝深度（第78條一(二)：最小 30 cm）",
        "value": h_total, "limit": "≥ %.2f m" % min_dim,
        "ok": h_total >= min_dim - 1e-9, "unit": "m"})

    return {
        "Q_design": Q_design, "b": b, "h_total": h_total, "S": S,
        "manning_n": n,
        "A_full": round(pr["A"], 4), "P_full": round(pr["P"], 4),
        "R_full": round(pr["R"], 4),
        "Q_cap_m3s": round(Q_cap, 4),
        "V_full_ms": round(V_full, 3),
        "h_normal_m": round(h_n, 4) if h_n is not None else None,
        "V_design_ms": round(V_design, 3) if V_design is not None else None,
        "freeboard_required_m": round(fb_req, 3),
        "checks": checks,
        "pass": all(c["ok"] for c in checks),
    }


def size_channel(Q_design, S, params=None, b_choices=None, h_choices=None,
                 wall_t=0.15, base_t=0.15):
    """由設計流量反推最小 U 型溝斷面（內寬 b、溝深 h）。

    搜尋策略：內寬由 0.3 m 起、溝深由 0.3 m 起，取「兩者乘積最小且全部檢核通過」那組。
    """
    p = dict(DEFAULTS, **(params or {}))
    if b_choices is None:
        b_choices = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    if h_choices is None:
        h_choices = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5]

    best = None
    tried = 0
    for b in b_choices:
        for h in h_choices:
            tried += 1
            res = analyse(Q_design, b, h, S, p)
            if res["pass"]:
                key = b * h
                if best is None or key < best["area_bh"]:
                    best = {"b": b, "h": h, "res": res, "area_bh": key}
    if best:
        best["q"] = {
            "inner_width_m": best["b"], "depth_m": best["h"],
            "wall_thickness_m": wall_t, "base_thickness_m": base_t,
        }
    return best, tried


def check_culvert(Q_design, diameter_m, n, slope, params=None):
    """涵管容量檢核（第 87 條：不設計滿流，水深 ≤ 內徑 0.75 倍）。

    採圓管部分滿流近似：以 0.8D 水深之通水面積估算容量。
    """
    p = dict(DEFAULTS, **(params or {}))
    D = float(diameter_m)
    ratio = float(p["culvert_max_fill_ratio"])
    h = ratio * D
    if h >= D:
        return {"ok": False, "error": "水深超過內徑"}
    # 圓弓形斷面積（水深 h）
    import math as _m
    theta = 2.0 * _m.acos(max(-1.0, min(1.0, 1.0 - 2.0 * h / D)))
    A = (D * D / 8.0) * (theta - _m.sin(theta))
    P_wet = D * theta / 2.0
    R = A / P_wet if P_wet > 0 else 0.0
    Q_cap = (1.0 / float(p["manning_n"])) * A * R ** (2.0 / 3.0) * _m.sqrt(max(slope, 1e-9))
    return {
        "ok": Q_cap >= Q_design * float(p["capacity_sf"]),
        "D_m": D, "h_ratio": ratio, "A_m2": round(A, 4),
        "Q_cap_m3s": round(Q_cap, 4), "Q_design": Q_design,
        "requirement": "Q_cap ≥ %.2f×Q 且水深 ≤ %.2fD（第87條）" % (
            float(p["capacity_sf"]), ratio),
    }


def size_culvert(Q_design, n, slope, params=None, d_choices=None):
    """反推通過第 87 條檢核（不滿流、水深 ≤0.75D）的最小涵管內徑。"""
    if d_choices is None:
        d_choices = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 1.8, 2.0]
    for D in d_choices:
        r = check_culvert(Q_design, D, n, slope, params)
        if r.get("ok"):
            r["note"] = "選用 Ø%.2f m 為通過第 87 條檢核之最小內徑" % D
            return r
    return {"ok": False, "note": "在候選管徑中找不到容量足夠者，建議加大管徑或改箱涵"}


def cross_drain_count(length_m, params=None):
    """橫向排水設施數量（第 78 條二(一)：每 150 m 一處）。"""
    p = dict(DEFAULTS, **(params or {}))
    import math as _m
    return max(1, int(_m.ceil(float(length_m) / float(p["cross_drain_spacing_m"]))))


def format_report(res):
    L = []
    L.append("設計流量 Q=%.3f m³/s、縱坡 S=%.4f（%.2f%%）、曼寧 n=%.3f" % (
        res["Q_design"], res["S"], res["S"] * 100, res["manning_n"]))
    L.append("斷面：內寬 b=%.2f m、溝深 h=%.2f m；滿水深 A=%.4f m²、濕周 P=%.3f m、水力半徑 R=%.4f m" % (
        res["b"], res["h_total"], res["A_full"], res["P_full"], res["R_full"]))
    L.append("通水容量 Q_cap=%.3f m³/s（滿水流速 %.2f m/s）" % (
        res["Q_cap_m3s"], res["V_full_ms"]))
    if res["h_normal_m"] is not None:
        L.append("設計流量下正常水深 h_n=%.3f m、流速 V=%.2f m/s；所需出水高 %.2f m" % (
            res["h_normal_m"], res["V_design_ms"], res["freeboard_required_m"]))
    L.append("")
    for c in res["checks"]:
        v = "—" if c["value"] is None else ("%.3f" % c["value"] if isinstance(c["value"], float) else str(c["value"]))
        lim = c["limit"] if isinstance(c["limit"], str) else "%.3f" % c["limit"]
        L.append("  [%s] %s：%s / 要求 %s" % ("OK" if c["ok"] else "NG", c["item"], v, lim))
    L.append("")
    L.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整斷面或縱坡"))
    return "\n".join(L)


def selftest():
    """手算對照（矩形溝 0.4×0.9 m、S=0.5%、n=0.014）。"""
    from _selftest_util import Checker

    c = Checker("排水溝水力（Manning）")
    Q, b, h, S, n = 0.3937, 0.4, 0.9, 0.005, 0.014
    r = analyse(Q, b, h, S, {"manning_n": n})
    A = b * h
    P = b + 2.0 * h
    R = A / P
    c.close("滿流面積 A＝b·h", r["A_full"], A, tol=1e-4)
    c.close("濕周 P＝b＋2h", r["P_full"], P, tol=1e-4)
    c.close("水力半徑 R＝A/P", r["R_full"], R, tol=1e-4)
    c.close("Manning 容量 Q＝A·R^(2/3)·S^½/n", r["Q_cap_m3s"],
            A * R ** (2.0 / 3.0) * S ** 0.5 / n, tol=1e-3)
    y = r["h_normal_m"]
    Ay = b * y
    Ry = Ay / (b + 2.0 * y)
    c.close("等速流水深代回 Manning 得 Q", Ay * Ry ** (2.0 / 3.0) * S ** 0.5 / n, Q, tol=1e-3)
    c.close("設計流速 V＝Q/A", r["V_design_ms"], Q / Ay, tol=1e-3)
    c.close("出水高需求 max(0.20, 0.25y)", r["freeboard_required_m"], max(0.20, 0.25 * y), tol=1e-3)
    return c.run()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json
    ap = argparse.ArgumentParser(description="排水溝水力計算（Manning）")
    ap.add_argument("case", nargs="?", help="case.json（channel 模型）")
    ap.add_argument("--Q", type=float, default=None, help="設計流量 m³/s")
    ap.add_argument("--b", type=float, default=None, help="內寬 m")
    ap.add_argument("--h", type=float, default=None, help="溝深 m")
    ap.add_argument("--S", type=float, default=0.005, help="縱坡（0.005 = 0.5%%）")
    ap.add_argument("--n", type=float, default=DEFAULTS["manning_n"])
    ap.add_argument("--size", action="store_true", help="反推通過檢核的最小斷面")
    a = ap.parse_args()

    params = {"manning_n": a.n}
    if a.size:
        best, tried = size_channel(a.Q, a.S, params)
        print("試 %d 組" % tried)
        if not best:
            print("找不到通過的斷面（檢查流量／縱坡是否合理）")
            raise SystemExit(1)
        print(format_report(best["res"]))
        print("\n建議斷面：", json.dumps(best["q"], ensure_ascii=False))
        raise SystemExit(0)

    if a.case:
        case = json.load(open(a.case, encoding="utf-8"))
        v = ((case.get("quantities") or {}).get("values")
             or case.get("quantities") or {})
        Q = a.Q if a.Q is not None else float(
            ((case.get("hydraulics") or {}).get("design_flow_m3s")) or 0.5)
        b = a.b if a.b is not None else float(v["inner_width_m"])
        h = a.h if a.h is not None else float(v["depth_m"])
    else:
        if a.Q is None or a.b is None or a.h is None:
            ap.error("未給 case.json 時，必須給 --Q --b --h")
        Q, b, h = a.Q, a.b, a.h

    res = analyse(Q, b, h, a.S, params)
    print(format_report(res))
    print()
    print(json.dumps({k: res[k] for k in
                      ("Q_cap_m3s", "h_normal_m", "V_design_ms", "freeboard_required_m", "pass")},
                     ensure_ascii=False))
    raise SystemExit(0 if res["pass"] else 1)
