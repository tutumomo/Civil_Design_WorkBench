"""扶壁式擋土牆穩定與構材設計（水土保持技術規範 §118 五、§119～121）。

為什麼另立模組
--------------
扶壁式的「穩定」與懸臂式同一套剛體檢核，但「構材」完全不同：
- 牆板（莖板）不再是懸臂板，而是**以扶壁為支承、水平向連續的版**；
- 踵板同樣以扶壁為支承，承受覆土減基底反力的淨向下載重；
- 扶壁本身是自基礎懸出的**變斷面 T 形梁**，拉力筋沿傾斜背面配置，
  並需以水平繫筋拉住牆板、鉛直繫筋拉住踵板。

幾何（x 由前趾往後、y 由基底往上，單位 m）
------------------------------------------
    toe_length_m  前趾長 Lt        stem_thickness_m  牆板厚 ts
    base_width_m  底板寬 B         base_thickness_m  底板厚 tb
    height_m      牆板高 H（底板頂以上）
    counterfort_spacing_m    扶壁中心距 S
    counterfort_thickness_m  扶壁厚 tc
    counterfort_top_width_m  扶壁頂寬（0＝三角形）
    front_soil_depth_m       前趾覆土深；§118 有效高＝H－前趾覆土深

力學假設
--------
- 土壓作用於踵端虛擬鉛直牆背（高 Hv＝H＋tb＋斜填土升高），Coulomb δ＝β
  （對鉛直牆背等同 Rankine 斜填土）；地震用 Mononobe-Okabe 增量，作用點 0.6Hv。
- 慣性力＝kh ×（混凝土＋踵板覆土），作用於各自形心。
- 上載只計入土壓（不計其在踵板上的穩定重量，保守）。
- 牆板水平彎矩：連續版係數 M−＝pS²/12（扶壁處、背面受拉）、M＋＝pS²/16（跨中、前面受拉）；
  牆板鉛直彎矩採 Huntington 簡化：底部 M−＝0.03·p_b·H·S、M＋＝M−/4。
- 踵板：w＝覆土＋自重＋上載－踵端基底反力（取最小值，保守），M−＝wS²/12、M＋＝wS²/16。
- 趾板：以牆板為固定端之懸臂板，由基底反力分佈積分。
- 扶壁：底部斷面以腹板寬 tc 的矩形梁設計（翼板受壓區未計，保守），
  有效深度取牆板前緣至傾斜背面之垂距；剪力不計斜向拉力筋的分擔（保守）。
- 載重組合沿用本工作區 rc_design 的 100 年版慣例：常時 U＝1.7H；
  地震 U＝0.75（1.7H＋1.87E）。取兩者包絡。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import earth_pressure as EP  # noqa: E402
import rc_design as RC  # noqa: E402
from retaining_wall import LIMITS  # noqa: E402


class CounterfortWallError(ValueError):
    """Invalid counterfort wall input."""


SPEC = {
    "label": "扶壁式擋土牆",
    "max_effective_height_m": 10.0,
    "basis": "水土保持技術規範 §118 五：有效高 10 m 以下為原則",
}
GAMMA_CONC = 24.0
LOAD_STATIC = 1.7
LOAD_SEISMIC_H = 0.75 * 1.7
LOAD_SEISMIC_E = 0.75 * 1.87
TIE_BAR = ("D13", "D16", "D19")
MAIN_BARS = ("D25", "D29", "D32")


def _f(data: Mapping[str, Any], key: str, default: float | None = None, *, minimum: float | None = None,
       positive: bool = False) -> float:
    value = data.get(key, default)
    if value is None:
        raise CounterfortWallError("缺少必要欄位：%s" % key)
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise CounterfortWallError("%s 必須為數字" % key) from exc
    if not math.isfinite(value):
        raise CounterfortWallError("%s 必須為有限數字" % key)
    if positive and value <= 0:
        raise CounterfortWallError("%s 必須大於 0" % key)
    if minimum is not None and value < minimum:
        raise CounterfortWallError("%s 不可小於 %s" % (key, minimum))
    return value


def geometry(q: Mapping[str, Any]) -> dict[str, float]:
    H = _f(q, "height_m", positive=True)
    ts = _f(q, "stem_thickness_m", positive=True)
    B = _f(q, "base_width_m", positive=True)
    tb = _f(q, "base_thickness_m", positive=True)
    Lt = _f(q, "toe_length_m", 0.0, minimum=0.0)
    S = _f(q, "counterfort_spacing_m", positive=True)
    tc = _f(q, "counterfort_thickness_m", positive=True)
    ctop = _f(q, "counterfort_top_width_m", 0.0, minimum=0.0)
    ds = _f(q, "front_soil_depth_m", 0.0, minimum=0.0)
    heel = B - Lt - ts
    if heel <= 0:
        raise CounterfortWallError("踵板長度 B－前趾－牆板厚 必須大於 0")
    if tc >= S:
        raise CounterfortWallError("扶壁厚必須小於扶壁中心距")
    if ctop > heel:
        raise CounterfortWallError("扶壁頂寬不可大於踵板長")
    if ds >= H:
        raise CounterfortWallError("前趾覆土深必須小於牆板高")
    eff = H - ds
    if eff > SPEC["max_effective_height_m"] + 1e-9:
        raise CounterfortWallError(
            "%s有效高 %.2f m 超過適用上限 %.1f m（%s）"
            % (SPEC["label"], eff, SPEC["max_effective_height_m"], SPEC["basis"]))
    return {"H": H, "ts": ts, "B": B, "tb": tb, "Lt": Lt, "S": S, "tc": tc, "ctop": ctop,
            "ds": ds, "heel": heel, "eff": eff, "clear_span": S - tc}


def _weights(g, gamma_s, beta_deg):
    """每公尺牆長的自重、覆土與形心（對前趾底 x=0, y=0）。"""

    H, ts, B, tb, Lt, S, tc, ctop, heel = (g[k] for k in ("H", "ts", "B", "tb", "Lt", "S", "tc", "ctop", "heel"))
    x0 = Lt + ts                        # 牆板背面
    parts = []
    parts.append(("底板", "conc", B * tb * GAMMA_CONC, B / 2.0, tb / 2.0))
    parts.append(("牆板", "conc", ts * H * GAMMA_CONC, Lt + ts / 2.0, tb + H / 2.0))
    a_cf = 0.5 * (heel + ctop) * H      # 扶壁側面積（梯形，上下兩邊水平）
    xc_rel = (heel ** 2 + heel * ctop + ctop ** 2) / (3.0 * (heel + ctop))
    yc_rel = H * (heel + 2.0 * ctop) / (3.0 * (heel + ctop))
    share = tc / S                      # 每公尺牆長分攤
    parts.append(("扶壁", "conc", a_cf * share * GAMMA_CONC, x0 + xc_rel, tb + yc_rel))
    soil_full = heel * H * gamma_s
    soil_cf = a_cf * share * gamma_s
    w_soil = soil_full - soil_cf
    x_soil = (soil_full * (x0 + heel / 2.0) - soil_cf * (x0 + xc_rel)) / w_soil
    y_soil = (soil_full * (tb + H / 2.0) - soil_cf * (tb + yc_rel)) / w_soil
    parts.append(("踵板覆土", "soil", w_soil, x_soil, y_soil))
    rise = heel * math.tan(math.radians(beta_deg))
    if rise > 1e-9:
        parts.append(("斜填土楔", "soil", 0.5 * heel * rise * gamma_s, x0 + 2.0 * heel / 3.0, tb + H + rise / 3.0))
    if g["ds"] > 0 and Lt > 0:
        parts.append(("前趾覆土", "soil", Lt * g["ds"] * gamma_s, Lt / 2.0, tb + g["ds"] / 2.0))
    return parts, rise


def _bearing(N, M_net, B):
    x_R = M_net / N if N > 0 else 0.0
    e = B / 2.0 - x_R
    if abs(e) <= B / 6.0 + 1e-12:
        q_max = N / B * (1 + 6 * abs(e) / B)
        q_min = N / B * (1 - 6 * abs(e) / B)
        Lp = B
    else:
        Lp = 3.0 * (B / 2.0 - abs(e))
        q_max = 2.0 * N / Lp if Lp > 0 else float("inf")
        q_min = 0.0
    return x_R, e, q_max, q_min, Lp


def _stability(g, soil, kh, passive_options):
    gamma = float(soil["gamma"])
    phi = float(soil["phi_deg"])
    beta = float(soil.get("backfill_slope_deg") or 0.0)
    qs = float(soil.get("surcharge_kpa") or 0.0)
    B, tb, H = g["B"], g["tb"], g["H"]
    parts, rise = _weights(g, gamma, beta)
    Hv = H + tb + rise
    delta = beta
    ka = EP.coulomb_active_coefficient(phi, wall_friction_deg=delta, backfill_slope_deg=beta)
    cd, sd = math.cos(math.radians(delta)), math.sin(math.radians(delta))
    Pa = 0.5 * ka * gamma * Hv ** 2
    Pq = ka * qs * Hv
    forces = [("主動土壓", Pa, Hv / 3.0), ("上載土壓", Pq, Hv / 2.0)]
    dP = 0.0
    kae = ka
    if kh > 0:
        kae = EP.coulomb_active_coefficient(phi, wall_friction_deg=delta, backfill_slope_deg=beta, kh=kh)
        dP = 0.5 * (kae - ka) * gamma * Hv ** 2
        forces.append(("地震土壓增量", dP, 0.6 * Hv))

    N = sum(p[2] for p in parts)
    M_r = sum(p[2] * p[3] for p in parts)
    T = 0.0
    M_o = 0.0
    for _, P, y in forces:
        T += P * cd
        M_o += P * cd * y
        N += P * sd
        M_r += P * sd * B
    F_eq = 0.0
    if kh > 0:
        for _, _, W, _, y in parts:
            F_eq += kh * W
            M_o += kh * W * y
        T += F_eq
    mu = float(soil["base_friction"])
    passive = EP.toe_passive_resistance(
        depth_m=g["ds"] + tb, gamma_kn_m3=gamma, phi_deg=phi, **passive_options)
    FS_s = (mu * N + passive["Pp_kN_per_m"]) / T if T > 0 else float("inf")
    FS_o = M_r / M_o if M_o > 0 else float("inf")
    x_R, e, q_max, q_min, Lp = _bearing(N, M_r - M_o, B)
    frac = 0.5 if soil.get("foundation") == "rock" else 1.0 / 3.0
    lo, hi = B * (0.5 - frac / 2.0), B * (0.5 + frac / 2.0)
    q_a = float(soil["allowable_bearing_kpa"])
    q_ult = float(soil.get("ultimate_bearing_kpa") or 3.0 * q_a)
    FS_b = q_ult / q_max if q_max > 0 else float("inf")
    seismic = kh > 0
    case = "地震" if seismic else "常時"
    s_lim = LIMITS["sliding_seismic" if seismic else "sliding_static"]
    o_lim = LIMITS["overturning_seismic" if seismic else "overturning_static"]
    checks = [
        {"item": "滑動（%s）" % case, "value": FS_s, "limit": s_lim, "ok": FS_s >= s_lim, "unit": "FS"},
        {"item": "傾倒（%s）" % case, "value": FS_o, "limit": o_lim, "ok": FS_o >= o_lim, "unit": "FS"},
        {"item": "合力作用點（%s，%s 中段）" % (case, "1/2" if frac == 0.5 else "1/3"), "value": x_R,
         "limit": [lo, hi], "ok": lo - 0.0005 * B <= x_R <= hi + 0.0005 * B, "unit": "m"},
        {"item": "基礎承載（%s，FS＝q_ult/q_max）" % case, "value": FS_b, "limit": LIMITS["bearing"],
         "ok": FS_b >= LIMITS["bearing"] and q_max <= q_a, "unit": "FS", "relation": "ge"},
        {"item": "基底最大應力（%s）≤ 容許承載力" % case, "value": q_max, "limit": q_a,
         "ok": q_max <= q_a, "unit": "kPa", "relation": "le"},
    ]
    return {
        "case": case, "kh": kh, "Ka": ka, "KAE": kae, "Hv_m": Hv, "delta_deg": delta,
        "Pa_kN_per_m": Pa, "Pq_kN_per_m": Pq, "dPae_kN_per_m": dP, "F_inertia_kN_per_m": F_eq,
        "N_kN_per_m": N, "T_kN_per_m": T, "M_resist_kNm": M_r, "M_over_kNm": M_o,
        "Pp_kN_per_m": passive["Pp_kN_per_m"], "passive": passive,
        "FS_sliding": FS_s, "FS_overturning": FS_o, "x_R_m": x_R, "e_m": e,
        "q_max_kPa": q_max, "q_min_kPa": q_min, "compressed_length_m": Lp,
        "parts": [{"name": n, "kind": k, "W_kN_per_m": W, "x_m": x, "y_m": y} for n, k, W, x, y in parts],
        "checks": checks,
    }


def _slab(name, Mu, Vu, h_m, cc, *, M_service=None):
    flex = RC.flexure_design(Mu, b_mm=1000.0, h_mm=h_m * 1000.0, cc=cc)
    shr = RC.shear_check(Vu, b_mm=1000.0, h_mm=h_m * 1000.0, cc=cc) if Vu is not None else None
    ok = bool(flex.get("ok")) and (shr is None or bool(shr.get("ok")))
    return {"member": name, "Mu_kNm_per_m": round(Mu, 3),
            "Vu_kN_per_m": None if Vu is None else round(Vu, 3),
            "thickness_mm": round(h_m * 1000.0, 1), "flexure": flex, "shear": shr, "ok": ok}


def _bars_for_area(As_req, width_mm, cover_mm, *, prefer=MAIN_BARS, max_layers=2):
    for name in prefer:
        db, ab = RC.REBAR_SIZES[name]
        n = max(2, math.ceil(As_req / ab - 1e-9))
        clear = max(25.0, db)
        usable = width_mm - 2.0 * cover_mm - 2.0 * 13.0
        per_layer = max(1, int((usable + clear) // (db + clear)))
        layers = math.ceil(n / per_layer)
        if layers <= max_layers:
            return {"bar": name, "count": n, "layers": layers, "per_layer_max": per_layer,
                    "As_prov_mm2": round(n * ab, 1), "fits": True}
    name = prefer[-1]
    db, ab = RC.REBAR_SIZES[name]
    n = max(2, math.ceil(As_req / ab - 1e-9))
    return {"bar": name, "count": n, "layers": None, "per_layer_max": None,
            "As_prov_mm2": round(n * ab, 1), "fits": False}


def _tie(name, Tu_kN_per_m, cc):
    fy = cc["fy_mpa"]
    As_req = Tu_kN_per_m * 1000.0 / (0.9 * fy)          # mm²／每公尺
    bar, spacing, As_prov = RC._pick_bars(As_req / 2.0, cc["cover_mm"], prefer=TIE_BAR)  # 兩肢
    return {"member": name, "Tu_kN_per_m": round(Tu_kN_per_m, 3), "As_req_mm2_per_m": round(As_req, 1),
            "bar": bar, "spacing_mm": spacing, "legs": 2, "As_prov_mm2_per_m": round(2.0 * As_prov, 1),
            "ok": 2.0 * As_prov >= As_req * 0.999}


def _counterfort_design(g, Ka_h, dKae_h, soil, cc, kh):
    """扶壁底部斷面（腹板寬 tc）的撓曲、剪力配筋。"""

    gamma = float(soil["gamma"])
    qs = float(soil.get("surcharge_kpa") or 0.0)
    H, S, tc, ts, heel, ctop = g["H"], g["S"], g["tc"], g["ts"], g["heel"], g["ctop"]
    fc, fy = cc["fc_mpa"], cc["fy_mpa"]
    # 牆板高度範圍內，一個扶壁承擔寬度 S 的土壓
    V_s = S * (0.5 * Ka_h * gamma * H ** 2 + Ka_h * qs * H)
    M_s = S * (Ka_h * gamma * H ** 3 / 6.0 + Ka_h * qs * H ** 2 / 2.0)
    V_e = S * dKae_h * gamma * H ** 2 * 0.5 if kh > 0 else 0.0
    M_e = V_e * 0.6 * H
    Mu = max(LOAD_STATIC * M_s, LOAD_SEISMIC_H * M_s + LOAD_SEISMIC_E * M_e)
    Vu = max(LOAD_STATIC * V_s, LOAD_SEISMIC_H * V_s + LOAD_SEISMIC_E * V_e)
    theta = math.atan2(H, heel - ctop)
    d = (ts + heel) * math.sin(theta) * 1000.0 - cc["cover_mm"] - 30.0
    b = tc * 1000.0
    out = {"theta_deg": round(math.degrees(theta), 2), "d_mm": round(d, 1), "b_mm": round(b, 1),
           "M_service_kNm": round(M_s, 3), "V_service_kN": round(V_s, 3),
           "Mu_kNm": round(Mu, 3), "Vu_kN": round(Vu, 3)}
    if d <= 0:
        out.update(ok=False, error="扶壁有效深度 ≤ 0")
        return out
    phi = 0.9
    R = Mu * 1e6 / (phi * b * d * d)
    disc = 1.0 - 2.0 * R / (0.85 * fc)
    if disc < 0:
        out.update(ok=False, error="扶壁斷面不足（單筋上限），須加厚扶壁或加長踵板")
        return out
    As_req = (0.85 * fc / fy) * (1.0 - math.sqrt(disc)) * b * d
    As_min = max(1.4 * b * d / fy, 0.25 * math.sqrt(fc) * b * d / fy)
    As_design = max(As_req, As_min)
    bars = _bars_for_area(As_design, b, cc["cover_mm"])
    As_prov = bars["As_prov_mm2"]
    a = As_prov * fy / (0.85 * fc * b)
    phi_f, et, basis = RC.phi_by_strain(As_prov, b, d, fc, fy, cc.get("Es_mpa"))
    phiMn = phi_f * As_prov * fy * (d - a / 2.0) / 1e6
    # 剪力：Vc＝0.17√fc'·b·d；不足則配兩肢水平箍筋
    Vc = 0.17 * math.sqrt(fc) * b * d / 1000.0
    phiVc = 0.75 * Vc
    stirrup = None
    shear_ok = True
    phiVn = phiVc
    if Vu > phiVc:
        Vs = Vu / 0.75 - Vc
        Vs_max = 0.66 * math.sqrt(fc) * b * d / 1000.0
        Av = 2.0 * RC.REBAR_SIZES["D13"][1]
        s_req = Av * fy * d / (Vs * 1000.0)
        s_max = min(d / 2.0, 600.0) if Vs <= 0.33 * math.sqrt(fc) * b * d / 1000.0 else min(d / 4.0, 300.0)
        s = math.floor(min(s_req, s_max) / 10.0) * 10.0
        Vs_prov = Av * fy * d / max(s, 1.0) / 1000.0
        phiVn = 0.75 * (Vc + min(Vs_prov, Vs_max))
        shear_ok = Vs <= Vs_max and s >= 75.0 and phiVn >= Vu
        stirrup = {"bar": "D13", "legs": 2, "spacing_mm": s, "Vs_req_kN": round(Vs, 3),
                   "Vs_prov_kN": round(Vs_prov, 3), "Vs_max_kN": round(Vs_max, 3)}
    out.update({
        "As_req_mm2": round(As_req, 1), "As_min_mm2": round(As_min, 1), "main": bars,
        "phi": phi_f, "epsilon_t": round(et, 5), "phi_basis": basis, "phiMn_kNm": round(phiMn, 3),
        "phiVc_kN": round(phiVc, 3), "phiVn_kN": round(phiVn, 3), "stirrup": stirrup,
        "flexure_ok": phiMn >= Mu and bars["fits"], "shear_ok": shear_ok,
    })
    out["ok"] = bool(out["flexure_ok"] and shear_ok)
    return out


def _structure(g, static, seismic, soil, cc):
    gamma = float(soil["gamma"])
    qs = float(soil.get("surcharge_kpa") or 0.0)
    beta = float(soil.get("backfill_slope_deg") or 0.0)
    H, S, ts, tb, B, Lt, heel = g["H"], g["S"], g["ts"], g["tb"], g["B"], g["Lt"], g["heel"]
    cd = math.cos(math.radians(static["delta_deg"]))
    Ka_h = static["Ka"] * cd
    kh = seismic["kh"] if seismic else 0.0
    dKae_h = (seismic["KAE"] - seismic["Ka"]) * cd if seismic else 0.0

    def env(Ms, Me):
        return max(LOAD_STATIC * Ms, LOAD_SEISMIC_H * Ms + LOAD_SEISMIC_E * Me)

    # ---- 牆板：分上、中、下三帶，取各帶底部壓力 ----
    members = []
    p_eq = dKae_h * gamma * H        # 地震增量以等值均佈近似（ΔP/H）
    for label, z in (("上帶", H / 3.0), ("中帶", 2.0 * H / 3.0), ("下帶", H)):
        p = Ka_h * (gamma * z + qs)
        pe = p_eq * 0.5 if kh > 0 else 0.0
        members.append(_slab("牆板%s 水平負彎矩（扶壁處，背面受拉）" % label,
                             env(p * S ** 2 / 12.0, pe * S ** 2 / 12.0),
                             env(p * S / 2.0, pe * S / 2.0), ts, cc))
        members.append(_slab("牆板%s 水平正彎矩（跨中，前面受拉）" % label,
                             env(p * S ** 2 / 16.0, pe * S ** 2 / 16.0), None, ts, cc))
    p_b = Ka_h * (gamma * H + qs)
    pe_b = p_eq * 0.5 if kh > 0 else 0.0
    Mv = 0.03 * p_b * H * S
    Mv_e = 0.03 * pe_b * H * S
    members.append(_slab("牆板底部鉛直負彎矩（Huntington，背面受拉）", env(Mv, Mv_e), None, ts, cc))
    members.append(_slab("牆板鉛直正彎矩（Huntington，前面受拉）", env(Mv / 4.0, Mv_e / 4.0), None, ts, cc))

    # ---- 基底反力分佈（常時）----
    q_max, q_min, Lp, e = static["q_max_kPa"], static["q_min_kPa"], static["compressed_length_m"], static["e_m"]
    toe_high = e >= 0      # 合力偏向前趾 → 最大值在前趾

    def qx(x):
        if Lp >= B - 1e-9:
            a, b_ = (q_max, q_min) if toe_high else (q_min, q_max)
            return a + (b_ - a) * x / B
        if toe_high:
            return max(0.0, q_max * (1.0 - x / Lp))
        return max(0.0, q_max * (1.0 - (B - x) / Lp))

    # ---- 踵板：以扶壁為支承的連續版 ----
    rise = heel * math.tan(math.radians(beta))
    w_down = gamma * H + GAMMA_CONC * tb + qs + 0.5 * gamma * rise
    q_heel_min = min(qx(Lt + ts), qx(B))
    w_heel = max(0.0, w_down - q_heel_min)
    members.append(_slab("踵板負彎矩（扶壁處，上層受拉）", LOAD_STATIC * w_heel * S ** 2 / 12.0,
                         LOAD_STATIC * w_heel * S / 2.0, tb, cc))
    members.append(_slab("踵板正彎矩（跨中，下層受拉）", LOAD_STATIC * w_heel * S ** 2 / 16.0, None, tb, cc))

    # ---- 趾板：懸臂板 ----
    if Lt > 0:
        n = 400
        h = Lt / n
        M_t = V_t = 0.0
        d_toe = max(tb - (cc["cover_mm"] + 10.0) / 1000.0, 0.0)
        for i in range(n):
            x = (i + 0.5) * h
            w = qx(x) - GAMMA_CONC * tb - gamma * g["ds"]
            if x <= Lt - d_toe:          # 剪力臨界斷面在距牆板面 d 處
                V_t += w * h
            M_t += w * h * (Lt - x)
        members.append(_slab("趾板（懸臂，下層受拉）", LOAD_STATIC * max(M_t, 0.0),
                             LOAD_STATIC * max(V_t, 0.0), tb, cc))

    cf = _counterfort_design(g, Ka_h, dKae_h, soil, cc, kh)
    ties = [
        _tie("扶壁—牆板水平繫筋（牆板底部）", env(p_b * S, pe_b * S), cc),
        _tie("扶壁—踵板鉛直繫筋", LOAD_STATIC * w_heel * S, cc),
    ]
    return {"slabs": members, "counterfort": cf, "ties": ties,
            "heel_net_load_kPa": round(w_heel, 3), "heel_min_bearing_kPa": round(q_heel_min, 3),
            "Ka_h": round(Ka_h, 5), "dKae_h": round(dKae_h, 5)}


def analyse(q: Mapping[str, Any], soil: Mapping[str, Any] | None = None,
            seismic: Mapping[str, Any] | None = None,
            concrete: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """扶壁式擋土牆：常時（＋地震）穩定、牆板／踵板／趾板／扶壁／繫筋設計。"""

    g = geometry(q)
    soil = dict({
        "gamma": 18.0, "phi_deg": 30.0, "c_kpa": 0.0, "backfill_slope_deg": 0.0,
        "surcharge_kpa": 0.0, "allowable_bearing_kpa": 200.0, "base_friction": 0.5,
        "foundation": "soil",
    }, **(soil or {}))
    kh = float((seismic or {}).get("kh") or 0.0)
    if kh < 0:
        raise CounterfortWallError("kh 不可為負")
    cc = dict(RC.CONCRETE, **(concrete or {}))
    passive_options = EP.passive_options(q, soil, default_include=False, default_ratio=1.0)
    try:
        static = _stability(g, soil, 0.0, passive_options)
        quake = _stability(g, soil, kh, passive_options) if kh > 0 else None
    except EP.EarthPressureError as exc:
        raise CounterfortWallError("土壓力無解：%s" % exc) from exc
    struct = _structure(g, static, quake, soil, cc)

    checks = list(static["checks"])
    if quake:
        checks += quake["checks"]
    for m in struct["slabs"]:
        fl = m["flexure"]
        checks.append({"item": "%s 撓曲" % m["member"], "value": m["Mu_kNm_per_m"],
                       "limit": fl.get("phiMn_kNm"), "ok": bool(fl.get("ok")), "unit": "kN·m/m",
                       "relation": "le"})
        if m["shear"]:
            checks.append({"item": "%s 剪力" % m["member"], "value": m["Vu_kN_per_m"],
                           "limit": m["shear"]["phiVc_kN"], "ok": bool(m["shear"]["ok"]),
                           "unit": "kN/m", "relation": "le"})
    cf = struct["counterfort"]
    checks.append({"item": "扶壁底部撓曲（T 梁，腹板寬 %.2f m）" % g["tc"], "value": cf["Mu_kNm"],
                   "limit": cf.get("phiMn_kNm"), "ok": bool(cf.get("flexure_ok")), "unit": "kN·m",
                   "relation": "le"})
    checks.append({"item": "扶壁底部剪力", "value": cf["Vu_kN"],
                   "limit": cf.get("phiVn_kN"),
                   "ok": bool(cf.get("shear_ok")), "unit": "kN", "relation": "le"})
    for t in struct["ties"]:
        checks.append({"item": t["member"], "value": t["As_req_mm2_per_m"], "limit": t["As_prov_mm2_per_m"],
                       "ok": t["ok"], "unit": "mm²/m", "relation": "le"})

    warnings = [
        "回填土黏著力未計（保守）；牆後地下水未計，排水不良時須另檢核靜水壓。",
        "牆板與踵板採連續版係數及 Huntington 簡化，非雙向版精算；扶壁以腹板矩形斷面設計（保守）。",
        "載重組合採 100 年版慣例 1.7H 與 0.75(1.7H＋1.87E)；改用 112 年版時須換組合。",
    ]
    warnings += EP.passive_warnings(static["passive"], kh > 0)
    ratio = g["S"] / g["H"]
    if not (0.3 <= ratio <= 0.7):
        warnings.append("扶壁中心距 %.2f m 為牆高的 %.2f 倍，常用範圍約 0.3～0.6H，請確認經濟性。" % (g["S"], ratio))
    if g["H"] < 6.0:
        warnings.append("牆高 < 6 m 時扶壁式通常不如懸臂式經濟，請比較。")

    concrete_m3_per_m = (g["B"] * g["tb"] + g["ts"] * g["H"]
                         + 0.5 * (g["heel"] + g["ctop"]) * g["H"] * g["tc"] / g["S"])
    return {
        "wall_type": "counterfort",
        "wall_label": SPEC["label"],
        "geometry": {k: round(v, 4) for k, v in g.items()},
        "applicability": {"basis": SPEC["basis"],
                          "notes": ["有效高（露出地面）%.2f m ≤ %.1f m" % (g["eff"], SPEC["max_effective_height_m"])]},
        "soil": soil,
        "seismic": {"kh": kh},
        "concrete": {k: cc[k] for k in ("fc_mpa", "fy_mpa", "cover_mm")},
        "stability": {"static": static, "seismic": quake},
        "structure": struct,
        "concrete_m3_per_m": round(concrete_m3_per_m, 4),
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in checks),
    }


def format_report(res: Mapping[str, Any]) -> str:
    g = res["geometry"]
    lines = [
        "%s：牆板高 %.2f m、有效高 %.2f m、底板 %.2f×%.2f m（前趾 %.2f、踵板 %.2f）、牆板厚 %.2f m"
        % (res["wall_label"], g["H"], g["eff"], g["B"], g["tb"], g["Lt"], g["heel"], g["ts"]),
        "扶壁：中心距 %.2f m、厚 %.2f m、頂寬 %.2f m；混凝土 %.3f m³/m"
        % (g["S"], g["tc"], g["ctop"], res["concrete_m3_per_m"]),
        "材料：fc'=%.0f MPa、fy=%.0f MPa、保護層 %.0f mm；kh=%.2f"
        % (res["concrete"]["fc_mpa"], res["concrete"]["fy_mpa"], res["concrete"]["cover_mm"], res["seismic"]["kh"]),
        "",
    ]
    for case in (res["stability"]["static"], res["stability"]["seismic"]):
        if not case:
            continue
        lines.append("%s：Ka=%.3f、Hv=%.2f m、N=%.1f kN/m、T=%.1f kN/m、FS滑=%.2f、FS倒=%.2f、x_R=%.3f m、q=%.1f～%.1f kPa"
                     % (case["case"], case["Ka"] if case["kh"] == 0 else case["KAE"], case["Hv_m"],
                        case["N_kN_per_m"], case["T_kN_per_m"], case["FS_sliding"], case["FS_overturning"],
                        case["x_R_m"], case["q_min_kPa"], case["q_max_kPa"]))
    passive_line = EP.passive_summary(res["stability"]["static"]["passive"])
    if passive_line:
        lines.append(passive_line)
    lines.append("")
    st = res["structure"]
    for m in st["slabs"]:
        fl = m["flexure"]
        lines.append("  %s：Mu=%.2f kN·m/m → %s@%s（φMn=%s）"
                     % (m["member"], m["Mu_kNm_per_m"], fl.get("bar", "-"), fl.get("spacing_mm", "-"),
                        fl.get("phiMn_kNm", "-")))
    cf = st["counterfort"]
    if cf.get("main"):
        mb = cf["main"]
        lines.append("  扶壁拉力筋：Mu=%.1f kN·m、d=%.0f mm → %d-%s（%s 層），φMn=%.1f kN·m"
                     % (cf["Mu_kNm"], cf["d_mm"], mb["count"], mb["bar"], mb["layers"] or "排不下",
                        cf["phiMn_kNm"]))
        if cf.get("stirrup"):
            lines.append("  扶壁水平箍筋：%s 兩肢 @%s mm" % (cf["stirrup"]["bar"], cf["stirrup"]["spacing_mm"]))
    elif cf.get("error"):
        lines.append("  扶壁：%s" % cf["error"])
    for t in st["ties"]:
        lines.append("  %s：Tu=%.1f kN/m → %s 兩肢 @%s mm" % (t["member"], t["Tu_kN_per_m"], t["bar"], t["spacing_mm"]))
    lines.append("")
    for c in res["checks"]:
        lim = c["limit"]
        lim_txt = "%.3f~%.3f" % tuple(lim) if isinstance(lim, (list, tuple)) else (
            "-" if lim is None else "%.3f" % lim)
        lines.append("  [%s] %s：%.3f / %s" % ("OK" if c["ok"] else "NG", c["item"], c["value"], lim_txt))
    lines.append("")
    lines.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整斷面或配筋"))
    return "\n".join(lines)


def size_section(height_m: float, soil: Mapping[str, Any] | None = None, kh: float = 0.0,
                 concrete: Mapping[str, Any] | None = None, *, front_soil_depth_m: float = 0.0,
                 counterfort_spacing_m: float | None = None, include_passive: bool | None = None,
                 passive_ratio: float | None = None) -> dict[str, Any]:
    """由牆高反推通過全部檢核、混凝土量最少的扶壁式斷面（格點搜尋）。"""

    H = float(height_m)
    if counterfort_spacing_m is None:
        counterfort_spacing_m = min(3.5, max(2.5, round(H * 0.4 * 2) / 2))
    S = float(counterfort_spacing_m)
    best = None
    tried = 0
    B = round(0.45 * H, 1)
    while B <= 1.2 * H + 1e-9:
        found_here = None
        for toe_ratio in (0.15, 0.2, 0.25, 0.3):
            for tb in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
                for ts in (0.3, 0.35, 0.4, 0.5):
                    for tc in (0.3, 0.4, 0.5, 0.6):
                        q = {"height_m": H, "stem_thickness_m": ts, "base_width_m": B,
                             "base_thickness_m": tb, "toe_length_m": round(toe_ratio * B, 2),
                             "counterfort_spacing_m": S, "counterfort_thickness_m": tc,
                             "counterfort_top_width_m": 0.3, "front_soil_depth_m": front_soil_depth_m}
                        if include_passive is not None:
                            q["include_passive"] = include_passive
                        if passive_ratio is not None:
                            q["passive_ratio"] = passive_ratio
                        tried += 1
                        try:
                            res = analyse(q, soil, {"kh": kh}, concrete)
                        except CounterfortWallError:
                            continue
                        if res["pass"] and (found_here is None
                                            or res["concrete_m3_per_m"] < found_here["concrete_m3_per_m"]):
                            found_here = res
                        if res["pass"]:
                            break        # 同一組 tb/ts 下更厚的扶壁只會更多混凝土
        if found_here is not None:
            best = found_here
            break
        B = round(B + 0.1, 2)
    return {"found": best is not None, "tried": tried, "section": None if best is None else {
        k: best["geometry"][k2] for k, k2 in (("height_m", "H"), ("stem_thickness_m", "ts"),
                                                ("base_width_m", "B"), ("base_thickness_m", "tb"),
                                                ("toe_length_m", "Lt"), ("counterfort_spacing_m", "S"),
                                                ("counterfort_thickness_m", "tc"),
                                                ("counterfort_top_width_m", "ctop"),
                                                ("front_soil_depth_m", "ds"))},
        "result": best}


def selftest() -> int:
    """手算對照（扶壁式 H=8 m、常時工況，每項可獨立驗算）。"""
    from _selftest_util import Checker

    c = Checker("扶壁式擋土牆（H = 8 m）")
    q = {"height_m": 8.0, "stem_thickness_m": 0.3, "base_width_m": 6.6,
         "base_thickness_m": 0.6, "toe_length_m": 1.98,
         "counterfort_spacing_m": 3.0, "counterfort_thickness_m": 0.4,
         "counterfort_top_width_m": 0.3, "front_soil_depth_m": 1.0}
    soil = {"gamma": 18.0, "phi_deg": 30.0, "backfill_slope_deg": 0.0,
            "surcharge_kpa": 0.0, "allowable_bearing_kpa": 300.0,
            "base_friction": 0.6, "foundation": "soil"}
    r = analyse(q, soil=soil, seismic={"kh": 0.15},
                concrete={"fc_mpa": 21.0, "fy_mpa": 420.0, "cover_mm": 75.0})
    st = r["stability"]["static"]
    g = r["geometry"]
    c.close("主動土壓力係數 Ka", st["Ka"],
            math.tan(math.radians(45.0 - 30.0 / 2)) ** 2, tol=1e-4)
    c.close("主動土壓力 Pa", st["Pa_kN_per_m"],
            0.5 * st["Ka"] * 18.0 * st["Hv_m"] ** 2, tol=1e-4)
    c.close("基底抗滑 FS", st["FS_sliding"],
            st["N_kN_per_m"] * 0.6 / st["T_kN_per_m"], tol=1e-4)
    c.close("基底抗傾倒 FS", st["FS_overturning"],
            st["M_resist_kNm"] / st["M_over_kNm"], tol=1e-4)
    c.close("最大承壓 q", st["q_max_kPa"],
            st["N_kN_per_m"] / g["B"] * (1.0 + 6.0 * st["e_m"] / g["B"]), tol=1e-4)
    with_passive = analyse({**q, "include_passive": True}, soil=soil, seismic={"kh": 0.15},
                           concrete={"fc_mpa": 21.0, "fy_mpa": 420.0, "cover_mm": 75.0})
    sp = with_passive["stability"]["static"]
    c.close("牆趾被動土壓力 Pp（D＝覆土＋底板）", sp["Pp_kN_per_m"],
            0.5 * 3.0 * 18.0 * 1.6 ** 2, tol=1e-3)
    c.close("計入 Pp 後抗滑 FS", sp["FS_sliding"],
            (st["N_kN_per_m"] * 0.6 + 69.12) / st["T_kN_per_m"], tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    ap = argparse.ArgumentParser(description="扶壁式擋土牆穩定與構材設計")
    ap.add_argument("json", help="輸入 JSON（section／soil／kh／concrete）")
    ap.add_argument("--size", action="store_true", help="依 section.height_m 反推通過檢核的斷面")
    args = ap.parse_args()
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if args.size:
        sec = data.get("section") or data
        out = size_section(float(sec["height_m"]), data.get("soil"), float(data.get("kh", 0.0)),
                           data.get("concrete"), front_soil_depth_m=float(sec.get("front_soil_depth_m", 0.0)),
                           counterfort_spacing_m=sec.get("counterfort_spacing_m"))
        if not out["found"]:
            print("搜尋 %d 組仍找不到通過的斷面，請檢查土壤參數或改用其他牆型。" % out["tried"])
            sys.exit(1)
        print("反推斷面（搜尋 %d 組）：%s" % (out["tried"], json.dumps(out["section"], ensure_ascii=False)))
        print(format_report(out["result"]))
        sys.exit(0)
    res = analyse(data.get("section") or data, soil=data.get("soil"),
                  seismic={"kh": float(data.get("kh", 0.0))}, concrete=data.get("concrete"))
    print(format_report(res))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
