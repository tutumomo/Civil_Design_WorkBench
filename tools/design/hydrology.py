r"""集水區水文分析（水土保持技術規範第 16~19 條）。

為什麼要這個模組
----------------
先前排水溝的設計流量 0.50 m³/s 是**假設值** —— 沒有集水區面積、沒有降雨強度、
沒有重現期。斷面選配算得再精，餵進去的流量是猜的，結論就只有「在假設成立時」有效。

本模組依規範把設計流量算出來：降雨強度 → 集流時間 → 逕流係數 → 合理化公式。

條文依據（全文見 data\法規\水土保持技術規範_1140507_全文.txt）
----------------------------------------------------------------
**第 16 條（降雨強度推估）**
    I_t^T / I_60^25 = (G + H·log T) · A / (t + B)^C          …(1)
    I_60^25 = (P / (25.29 + 0.094·P))^2                       …(2)
    A = (P / (−189.96 + 0.31·P))^2                           …(3)
    B = 55                                                   …(4)
    C = (P / (−381.71 + 1.45·P))^2                           …(5)
    G = (P / (42.89 + 1.33·P))^2                             …(6)
    H = (P / (−65.33 + 1.836·P))^2                           …(7)
  T 重現期(年)、t 降雨延時/集流時間(分)、P 年平均降雨量(mm)。
  ※ 條文寫「**不得小於**」本公式推估值 → 這是下限，設計可取更高值。
  ※ log 採常用對數（以 10 為底）。

**第 17 條（逕流量分析）**
    Qp = (1/360)·C·I·A         （A ≤ 1000 ha，無實測資料時）
    Qp m³/s、C 逕流係數、I mm/hr、A 公頃

**第 18 條（逕流係數）** —— 查表；開發中 C 以 1.0 計。

**第 19 條（集流時間）**
    tc = t1 + t2，t1 = l / v
    天然河段芮哈(Rziha)公式：t2 = L / W，W = 72·(H/L)^0.6
    t2 小時、W km/hr、H 溪流縱斷面高程差(km)、L 溪流長度(km)
    漫地流長度：開發坡面 ≤100 m、集水區 ≤300 m，超過部分併入流下時間。
"""

import math

# 第 18 條逕流係數表（下限, 上限）
RUNOFF_C = {
    "無開發整地區": {
        "陡峻山地": (0.75, 0.90),
        "山嶺區": (0.70, 0.80),
        "丘陵地或森林": (0.50, 0.75),
        "平坦耕地": (0.45, 0.60),
        "非農業使用": (0.75, 0.95),
    },
    "開發整地區": {
        "陡峻山地": (0.95, 0.95),
        "山嶺區": (0.90, 0.90),
        "丘陵地或森林": (0.90, 0.90),
        "平坦耕地": (0.85, 0.85),
        "非農業使用": (0.95, 1.00),
    },
}

SLOPE_LIMITS = {"開發坡面": 100.0, "集水區": 300.0}


def intensity_coefficients(P):
    """第 16 條係數（P = 年平均降雨量 mm）。"""
    return {
        "I60_25": (P / (25.29 + 0.094 * P)) ** 2,
        "A": (P / (-189.96 + 0.31 * P)) ** 2,
        "B": 55.0,
        "C": (P / (-381.71 + 1.45 * P)) ** 2,
        "G": (P / (42.89 + 1.33 * P)) ** 2,
        "H": (P / (-65.33 + 1.836 * P)) ** 2,
    }


def rainfall_intensity(P, T, t, coef=None):
    """第 16 條：重現期 T 年、延時 t 分鐘之降雨強度 I_t^T（mm/hr）。"""
    c = coef or intensity_coefficients(P)
    if T <= 0 or t <= 0:
        raise ValueError("T 與 t 必須為正")
    ratio = (c["G"] + c["H"] * math.log10(T)) * c["A"] / ((t + c["B"]) ** c["C"])
    return c["I60_25"] * ratio


def runoff_coefficient(condition, developed=False, upper=False):
    """第 18 條逕流係數。developed=True 表「開發整地區（整地後）」；
    upper=True 取表中上限（保守）。開發中之 C 值一律 1.0。"""
    key = "開發整地區" if developed else "無開發整地區"
    lo, hi = RUNOFF_C[key][condition]
    return hi if upper else lo


def time_of_concentration(l_m, v_ms, L_km=0.0, H_km=0.0, area_type="集水區"):
    """第 19 條集流時間 tc（分鐘）。

    l_m 漫地流長度(m)、v_ms 漫地流流速(m/s，規範採 0.3~0.6)、
    L_km 溪流長度(km)、H_km 高程差(km)。
    """
    if not (0.3 - 1e-9 <= v_ms <= 0.6 + 1e-9):
        raise ValueError("漫地流流速應在 0.3~0.6 m/s（第 19 條）")
    if l_m > SLOPE_LIMITS[area_type]:
        raise ValueError(
            "漫地流長度 %s 超過 %s 上限 %.0f m（第 19 條：超過部分須併入流下時間）"
            % (l_m, area_type, SLOPE_LIMITS[area_type]))
    t1_min = (l_m / v_ms) / 60.0
    t2_hr = 0.0
    W = None
    if L_km > 0:
        W = 72.0 * (max(H_km, 1e-9) / L_km) ** 0.6       # km/hr（芮哈）
        t2_hr = L_km / W
    return {"t1_min": round(t1_min, 4), "t2_hr": round(t2_hr, 4),
            "W_kmh": round(W, 4) if W else None,
            "tc_min": round(t1_min + t2_hr * 60.0, 4)}


def design_flow(P, T, area_ha, condition, developed=False, upper_c=False,
                l_m=100.0, v_ms=0.4, L_km=0.0, H_km=0.0, area_type="集水區",
                t_override_min=None):
    """第 17 條合理化公式求洪峰流量。回傳完整中間值，便於報告引用。"""
    if area_ha > 1000.0:
        raise ValueError("面積超過 1000 ha，第 17 條規定須採單位歷線分析")
    coef = intensity_coefficients(P)
    tc = time_of_concentration(l_m, v_ms, L_km, H_km, area_type)
    t = float(t_override_min) if t_override_min else tc["tc_min"]
    I = rainfall_intensity(P, T, t, coef)
    C = runoff_coefficient(condition, developed, upper_c)
    Qp = C * I * area_ha / 360.0
    return {
        "P_mm": P, "T_year": T, "area_ha": area_ha,
        "condition": condition, "developed": developed,
        "C": round(C, 3),
        "tc_min": round(t, 3),
        "t_used_min": round(t, 3),
        "I_mm_hr": round(I, 2),
        "Qp_m3s": round(Qp, 4),
        "coef": {k: round(v, 5) for k, v in coef.items()},
        "tc_detail": tc,
        "formula": "Qp = (1/360)·C·I·A（第17條）",
        "checks": [
            {"item": "漫地流流速（第 19 條）", "value": v_ms, "limit": [0.3, 0.6],
             "ok": True, "unit": "m/s"},
            {"item": "漫地流長度（第 19 條）", "value": l_m, "limit": SLOPE_LIMITS[area_type],
             "ok": True, "unit": "m", "relation": "le"},
            {"item": "集水面積（第 17 條合理化公式適用）", "value": area_ha, "limit": 1000.0,
             "ok": True, "unit": "ha", "relation": "le"},
        ],
    }


def format_report(r):
    L = [f"年平均降雨量 P={r['P_mm']:.0f} mm、重現期 T={r['T_year']:.0f} 年、"
         f"集水區面積 A={r['area_ha']:.3f} ha",
         f"  集流時間 tc={r['tc_min']:.2f} 分"
         f"（流入 {r['tc_detail']['t1_min']:.2f} 分 ＋ 流下 {r['tc_detail']['t2_hr']*60:.2f} 分）",
         f"  降雨強度 I({r['T_year']:.0f}年,{r['t_used_min']:.1f}分)={r['I_mm_hr']:.2f} mm/hr（第16條）",
         f"  逕流係數 C={r['C']:.3f}（{r['condition']}，"
         f"{'開發整地區' if r['developed'] else '無開發整地區'}，第18條）",
         f"  → 洪峰流量 Qp = (1/360)×{r['C']:.3f}×{r['I_mm_hr']:.2f}×{r['area_ha']:.3f}"
         f" = {r['Qp_m3s']:.4f} m³/s（第17條）",
         "",
         "  ⚠ 第16條規定「不得小於」公式推估值 —— 本值為**下限**，設計得取更高。"]
    return "\n".join(L)


def selftest():
    """手算對照（P=2000 mm、T=25 年、A=2 ha、丘陵地或森林 C=0.5）。"""
    from _selftest_util import Checker

    c = Checker("集水區水文（第 16～19 條）")
    P, T, area = 2000.0, 25.0, 2.0
    r = design_flow(P, T, area, "丘陵地或森林", l_m=100.0, v_ms=0.4)
    t = 100.0 / 0.4 / 60.0
    I60 = (P / (25.29 + 0.094 * P)) ** 2
    coef_a = (P / (-189.96 + 0.31 * P)) ** 2
    coef_c = (P / (-381.71 + 1.45 * P)) ** 2
    coef_g = (P / (42.89 + 1.33 * P)) ** 2
    coef_h = (P / (-65.33 + 1.836 * P)) ** 2
    I = I60 * (coef_g + coef_h * math.log10(T)) * coef_a / (t + 55.0) ** coef_c
    c.close("集流時間 t＝l/v", r["tc_min"], t, tol=1e-3)
    c.close("第 16 條降雨強度 I", r["I_mm_hr"], I, tol=1e-3)
    c.close("逕流係數 C（無開發整地區下限）", r["C"], 0.5)
    c.close("洪峰流量 Qp＝C·I·A/360", r["Qp_m3s"], 0.5 * I * area / 360.0, tol=1e-3)
    W = 72.0 * (0.05 / 1.0) ** 0.6
    stream = time_of_concentration(100.0, 0.4, L_km=1.0, H_km=0.05)
    c.close("芮哈流下時間 t2＝L/W", stream["t2_hr"], 1.0 / W, tol=1e-3)
    return c.run()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json
    ap = argparse.ArgumentParser(description="集水區水文分析（水保第16~19條）")
    ap.add_argument("--P", type=float, required=True, help="年平均降雨量 mm")
    ap.add_argument("--T", type=float, default=25.0, help="重現期 年")
    ap.add_argument("--area", type=float, required=True, help="集水區面積 ha")
    ap.add_argument("--condition", default="丘陵地或森林", choices=list(RUNOFF_C["無開發整地區"]))
    ap.add_argument("--developed", action="store_true", help="開發整地區（整地後）")
    ap.add_argument("--upper-c", action="store_true", help="逕流係數取表中上限")
    ap.add_argument("--l", type=float, default=100.0, help="漫地流長度 m")
    ap.add_argument("--v", type=float, default=0.4, help="漫地流流速 m/s (0.3~0.6)")
    ap.add_argument("--L", type=float, default=0.0, help="溪流長度 km")
    ap.add_argument("--H", type=float, default=0.0, help="高程差 km")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = design_flow(a.P, a.T, a.area, a.condition, a.developed, a.upper_c,
                    a.l, a.v, a.L, a.H)
    print(format_report(r))
    if a.json:
        print()
        print(json.dumps(r, ensure_ascii=False, indent=1))
