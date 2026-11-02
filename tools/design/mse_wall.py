"""加勁擋土牆（加勁土壤構造物）外部與內部穩定分析。

規範依據
--------
- 水土保持技術規範 §118 六(三)：加勁土壤構造物總有效高 8 m 以下為原則（有效高＝露出地面高）。
- 同 §119～120：外部穩定（滑動、傾倒、合力作用點、承載）的安全係數門檻與其他牆型共用。
- 內部穩定（拉斷、拉出）採 FHWA-NHI-10-024／FHWA-NHI-00-043 簡化法（容許應力法）。

模型
----
外部：加勁區視為寬 L、高 H 的剛體；牆後保留土以 Coulomb（δ＝β）作用於加勁區後緣虛擬牆背，
      地震用 Mononobe-Okabe 增量 ×50% 加上加勁區慣性力 PIR＝kh·γr·H·(H/2)（取不超過 L），
      承載用 Meyerhof 均佈 σv＝ΣV/(L−2e)。
內部：各層 σv＝γr·z＋q，σh＝Kr·σv，Tmax＝σh·Sv（每公尺寬）。
      Kr/Ka：伸張性（土工格網、土工織物）＝1.0；非伸張性鋼條帶 1.7→1.2（z＝0→6 m 線性）。
      破壞面：伸張性用 Rankine 線（45°＋φ/2 由趾部起），非伸張性用雙線性（上半 0.3H、下半 0.6(H−z)）。
      拉斷 FS＝Tal·Rc／Tmax ≥ 1.5；拉出 Pr＝F*·α·σv'·Le·C·Rc，FS＝Pr／Tmax ≥ 1.5，且 Le ≥ 0.9 m。
      地震：內部慣性力 Pi＝kh·（主動區重量），依各層 Le 比例分配；拉斷 FS ≥ 1.125、拉出 FS ≥ 1.1（F*×0.8）。

限制：面版連接強度、面版本身、複合（穿越加勁區）滑動、整體圓弧滑動、排水與沉陷未檢核。
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
from retaining_wall import LIMITS  # noqa: E402


class MSEWallError(ValueError):
    """Invalid MSE wall input."""


SPEC = {
    "label": "加勁擋土牆（加勁土壤構造物）",
    "max_effective_height_m": 8.0,
    "basis": "水土保持技術規範 §118 六(三)：總有效高 8 m 以下為原則",
}

# F*、α 的預設值依 FHWA-NHI-10-024 表 3-3／3-4 之保守預設；有拉出試驗時應以試驗值取代。
REINFORCEMENT_TYPES: dict[str, dict[str, Any]] = {
    "geogrid": {"label": "土工格網（伸張性）", "extensible": True, "alpha": 0.8,
                "F_star_factor": 0.67, "C": 2.0},
    "geotextile": {"label": "土工織物（伸張性）", "extensible": True, "alpha": 0.6,
                   "F_star_factor": 0.67, "C": 2.0},
    "steel_strip": {"label": "鋼條帶（非伸張性，肋紋）", "extensible": False, "alpha": 1.0,
                    "F_star_top": 2.0, "C": 2.0},
}

FS_RUPTURE = 1.5
FS_PULLOUT = 1.5
FS_RUPTURE_EQ = 1.125     # 地震 0.75×1.5
FS_PULLOUT_EQ = 1.1
LE_MIN = 0.9
TOL = 1e-9


def _f(d: Mapping[str, Any], key: str, default: float | None = None, *, positive=False, minimum=None) -> float:
    v = d.get(key, default)
    if v is None:
        raise MSEWallError("缺少必要欄位：%s" % key)
    try:
        v = float(v)
    except (TypeError, ValueError) as exc:
        raise MSEWallError("%s 必須為數字" % key) from exc
    if not math.isfinite(v):
        raise MSEWallError("%s 必須為有限數字" % key)
    if positive and v <= 0:
        raise MSEWallError("%s 必須大於 0" % key)
    if minimum is not None and v < minimum:
        raise MSEWallError("%s 不可小於 %s" % (key, minimum))
    return v


def _layers(q: Mapping[str, Any], H: float) -> list[float]:
    if q.get("layers_m"):
        ys = sorted(float(y) for y in q["layers_m"])
    else:
        Sv = _f(q, "vertical_spacing_m", positive=True)
        y = _f(q, "first_layer_m", Sv / 2.0, positive=True)
        ys = []
        while y < H - TOL:
            ys.append(round(y, 6))
            y += Sv
    if not ys:
        raise MSEWallError("至少需要一層加勁材")
    if ys[0] <= 0 or ys[-1] >= H:
        raise MSEWallError("加勁材高程須介於 0 與牆高之間")
    gaps = [ys[0]] + [b - a for a, b in zip(ys, ys[1:])] + [H - ys[-1]]
    if max(gaps) > 1.0 + TOL and not q.get("allow_large_spacing"):
        # FHWA 建議伸張性加勁材垂直間距不大於 0.8 m，鋼材 0.75 m；> 1.0 m 一律擋下
        raise MSEWallError("加勁材垂直間距 %.2f m 過大（> 1.0 m）" % max(gaps))
    return ys


def _ratio_kr(rtype: dict[str, Any], z: float) -> float:
    if rtype["extensible"]:
        return 1.0
    return 1.7 - 0.5 * min(z, 6.0) / 6.0


def _f_star(rtype: dict[str, Any], z: float, phi_r: float, override: float | None) -> float:
    if override is not None:
        return float(override)
    tanp = math.tan(math.radians(phi_r))
    if rtype["extensible"]:
        return rtype["F_star_factor"] * tanp
    top = rtype["F_star_top"]
    return top + (tanp - top) * min(z, 6.0) / 6.0


def _active_length(rtype: dict[str, Any], H: float, y: float, phi_r: float) -> float:
    z = H - y
    if rtype["extensible"]:
        return y * math.tan(math.radians(45.0 - phi_r / 2.0))
    return 0.3 * H if z <= H / 2.0 else 0.6 * y


def analyse(q: Mapping[str, Any], soil: Mapping[str, Any] | None = None,
            seismic: Mapping[str, Any] | None = None) -> dict[str, Any]:
    H = _f(q, "height_m", positive=True)
    emb = _f(q, "embedment_m", 0.0, minimum=0.0)
    if emb >= H:
        raise MSEWallError("埋入深度必須小於牆高")
    eff = H - emb
    if eff > SPEC["max_effective_height_m"] + TOL:
        raise MSEWallError("%s有效高 %.2f m 超過適用上限 %.1f m（%s）"
                           % (SPEC["label"], eff, SPEC["max_effective_height_m"], SPEC["basis"]))
    L = _f(q, "reinforcement_length_m", positive=True)
    rkey = str(q.get("reinforcement_type") or "geogrid").strip().lower()
    rtype = REINFORCEMENT_TYPES.get(rkey)
    if rtype is None:
        raise MSEWallError("不支援的加勁材：%s；可用 %s" % (rkey, "、".join(REINFORCEMENT_TYPES)))
    Tal = _f(q, "long_term_strength_kN_per_m", positive=True)
    Rc = _f(q, "coverage_ratio", 1.0, positive=True)
    if Rc > 1.0 + TOL:
        raise MSEWallError("coverage_ratio（覆蓋率 Rc）不可大於 1")
    alpha = _f(q, "scale_correction_alpha", rtype["alpha"], positive=True)
    F_override = q.get("pullout_factor_F_star")
    ys = _layers(q, H)

    soil = dict({
        "reinforced_gamma": 19.0, "reinforced_phi_deg": 34.0,
        "retained_gamma": 18.0, "retained_phi_deg": 30.0,
        "foundation_phi_deg": 30.0, "backfill_slope_deg": 0.0, "surcharge_kpa": 0.0,
        "allowable_bearing_kpa": 200.0, "base_friction": None, "foundation": "soil",
    }, **(soil or {}))
    kh = float((seismic or {}).get("kh") or 0.0)
    if kh < 0:
        raise MSEWallError("kh 不可為負")
    gr, phr = float(soil["reinforced_gamma"]), float(soil["reinforced_phi_deg"])
    gb, phb = float(soil["retained_gamma"]), float(soil["retained_phi_deg"])
    beta = float(soil["backfill_slope_deg"])
    qs = float(soil["surcharge_kpa"])
    mu = soil.get("base_friction")
    if mu is None:
        mu = math.tan(math.radians(min(phr, float(soil["foundation_phi_deg"]))))
    mu = float(mu)
    passive = EP.toe_passive_resistance(
        depth_m=emb, gamma_kn_m3=float(soil.get("foundation_gamma") or gb),
        phi_deg=float(soil["foundation_phi_deg"]),
        **EP.passive_options(q, soil, default_include=False, default_ratio=1.0))

    # ---------------- 外部穩定 ----------------
    rise = L * math.tan(math.radians(beta))
    h = H + rise
    try:
        Kab = EP.coulomb_active_coefficient(phb, wall_friction_deg=beta, backfill_slope_deg=beta)
        Kae = EP.coulomb_active_coefficient(phb, wall_friction_deg=beta, backfill_slope_deg=beta, kh=kh) if kh > 0 else Kab
    except EP.EarthPressureError as exc:
        raise MSEWallError("土壓力無解：%s" % exc) from exc
    cb, sb = math.cos(math.radians(beta)), math.sin(math.radians(beta))
    W1 = gr * H * L
    W2 = 0.5 * L * rise * gb
    F1 = 0.5 * Kab * gb * h * h
    F2 = Kab * qs * h

    def external(case_kh: float) -> dict[str, Any]:
        V = W1 + W2 + (F1 + F2) * sb
        Ph = (F1 + F2) * cb
        Mr = W1 * L / 2.0 + W2 * 2.0 * L / 3.0 + (F1 + F2) * sb * L
        Mo = F1 * cb * h / 3.0 + F2 * cb * h / 2.0
        extra = {}
        if case_kh > 0:
            dPae = 0.5 * (Kae - Kab) * gb * h * h
            PIR = case_kh * gr * H * min(0.5 * H, L)
            Ph += 0.5 * dPae * cb + PIR
            V += 0.5 * dPae * sb
            Mr += 0.5 * dPae * sb * L
            Mo += 0.5 * dPae * cb * 0.6 * h + PIR * H / 2.0
            extra = {"dPae_kN_per_m": dPae, "PIR_kN_per_m": PIR}
        FS_s = (mu * V + passive["Pp_kN_per_m"]) / Ph if Ph > 0 else float("inf")
        FS_o = Mr / Mo if Mo > 0 else float("inf")
        e = L / 2.0 - (Mr - Mo) / V
        sig = V / (L - 2.0 * abs(e)) if L - 2.0 * abs(e) > 0 else float("inf")
        return {"V_kN_per_m": V, "Ph_kN_per_m": Ph, "M_resist_kNm": Mr, "M_over_kNm": Mo,
                "FS_sliding": FS_s, "FS_overturning": FS_o, "e_m": e, "sigma_v_kPa": sig, **extra}

    ext_s = external(0.0)
    ext_e = external(kh) if kh > 0 else None
    frac_lim = L / 4.0 if soil["foundation"] == "rock" else L / 6.0
    q_a = float(soil["allowable_bearing_kpa"])
    q_ult = float(soil.get("ultimate_bearing_kpa") or 3.0 * q_a)
    checks: list[dict[str, Any]] = []
    for ext, case, s_lim, o_lim in ((ext_s, "常時", LIMITS["sliding_static"], LIMITS["overturning_static"]),
                                    (ext_e, "地震", LIMITS["sliding_seismic"], LIMITS["overturning_seismic"])):
        if ext is None:
            continue
        FS_b = q_ult / ext["sigma_v_kPa"] if ext["sigma_v_kPa"] > 0 else float("inf")
        checks += [
            {"item": "外部滑動（%s）" % case, "value": ext["FS_sliding"], "limit": s_lim,
             "ok": ext["FS_sliding"] >= s_lim, "unit": "FS"},
            {"item": "外部傾倒（%s）" % case, "value": ext["FS_overturning"], "limit": o_lim,
             "ok": ext["FS_overturning"] >= o_lim, "unit": "FS"},
            {"item": "偏心距 |e|（%s，%s）" % (case, "≤ L/4 岩盤" if soil["foundation"] == "rock" else "≤ L/6 土層"),
             "value": abs(ext["e_m"]), "limit": frac_lim, "ok": abs(ext["e_m"]) <= frac_lim + TOL,
             "unit": "m", "relation": "le"},
            {"item": "基礎承載（%s，Meyerhof，FS＝q_ult/σv）" % case, "value": FS_b, "limit": LIMITS["bearing"],
             "ok": FS_b >= LIMITS["bearing"] and ext["sigma_v_kPa"] <= q_a, "unit": "FS", "relation": "ge"},
            {"item": "基底均佈應力 σv（%s）≤ 容許承載力" % case, "value": ext["sigma_v_kPa"], "limit": q_a,
             "ok": ext["sigma_v_kPa"] <= q_a, "unit": "kPa", "relation": "le"},
        ]
    checks.append({"item": "加勁長度 L ≥ 0.7H", "value": L, "limit": 0.7 * H, "ok": L >= 0.7 * H - TOL,
                   "unit": "m", "relation": "ge"})
    checks.append({"item": "加勁長度 L ≥ 2.4 m（FHWA 最小值）", "value": L, "limit": 2.4, "ok": L >= 2.4 - TOL,
                   "unit": "m", "relation": "ge"})

    # ---------------- 內部穩定 ----------------
    Ka_r = math.tan(math.radians(45.0 - phr / 2.0)) ** 2
    bounds = [0.0] + [(a + b) / 2.0 for a, b in zip(ys, ys[1:])] + [H]
    layers = []
    for i, y in enumerate(ys):
        z = H - y
        Sv = bounds[i + 1] - bounds[i]
        Kr = Ka_r * _ratio_kr(rtype, z)
        sig_v = gr * z + qs
        Tmax = Kr * sig_v * Sv
        La = _active_length(rtype, H, y, phr)
        Le = max(L - La, 0.0)
        Fs = _f_star(rtype, z, phr, F_override)
        sig_v_eff = gr * z          # 拉出抵抗不計活載上載
        Pr = Fs * alpha * sig_v_eff * Le * rtype["C"] * Rc
        layers.append({"layer": i + 1, "y_m": round(y, 4), "z_m": round(z, 4), "Sv_m": round(Sv, 4),
                       "Kr": round(Kr, 5), "sigma_v_kPa": round(sig_v, 3), "Tmax_kN_per_m": Tmax,
                       "La_m": round(La, 4), "Le_m": round(Le, 4), "F_star": round(Fs, 4),
                       "Pr_kN_per_m": Pr,
                       "FS_rupture": Tal * Rc / Tmax if Tmax > 0 else float("inf"),
                       "FS_pullout": Pr / Tmax if Tmax > 0 else float("inf")})
    if kh > 0:
        # 主動區重量（每公尺牆長）：沿破壞面積分
        n = 200
        W_a = sum(_active_length(rtype, H, (k + 0.5) * H / n, phr) for k in range(n)) * H / n * gr
        Pi = kh * W_a
        sum_le = sum(l["Le_m"] for l in layers) or 1.0
        for l in layers:
            Tmd = Pi * l["Le_m"] / sum_le
            l["Tmd_kN_per_m"] = Tmd
            Ttot = l["Tmax_kN_per_m"] + Tmd
            Pr_eq = 0.8 * l["Pr_kN_per_m"]
            l["FS_rupture_eq"] = Tal * Rc / Ttot if Ttot > 0 else float("inf")
            l["FS_pullout_eq"] = Pr_eq / Ttot if Ttot > 0 else float("inf")
    for l in layers:
        tag = "第 %d 層（y=%.2f m）" % (l["layer"], l["y_m"])
        checks.append({"item": "%s拉斷" % tag, "value": l["FS_rupture"], "limit": FS_RUPTURE,
                       "ok": l["FS_rupture"] >= FS_RUPTURE, "unit": "FS"})
        checks.append({"item": "%s拉出" % tag, "value": l["FS_pullout"], "limit": FS_PULLOUT,
                       "ok": l["FS_pullout"] >= FS_PULLOUT, "unit": "FS"})
        checks.append({"item": "%s錨定長度 Le" % tag, "value": l["Le_m"], "limit": LE_MIN,
                       "ok": l["Le_m"] >= LE_MIN - TOL, "unit": "m", "relation": "ge"})
        if kh > 0:
            checks.append({"item": "%s拉斷（地震）" % tag, "value": l["FS_rupture_eq"], "limit": FS_RUPTURE_EQ,
                           "ok": l["FS_rupture_eq"] >= FS_RUPTURE_EQ, "unit": "FS"})
            checks.append({"item": "%s拉出（地震）" % tag, "value": l["FS_pullout_eq"], "limit": FS_PULLOUT_EQ,
                           "ok": l["FS_pullout_eq"] >= FS_PULLOUT_EQ, "unit": "FS"})

    warnings = [
        "Tal 應為長期設計強度（已扣潛變、施工損傷、耐久性折減）；F*、α 為 FHWA 保守預設值，有拉出試驗應取代。",
        "面版連接強度、面版、複合滑動與整體圓弧滑動未檢核；整體穩定請另用 slope_stability.py。",
        "加勁區與牆後須設排水，未計靜水壓。",
    ]
    if rise > 0:
        warnings.append("斜填土時內部 σv 未計牆頂斜坡土重（偏不保守），坡度大時請以等值上載輸入。")
    warnings += EP.passive_warnings(passive, kh > 0)
    return {
        "wall_type": "mse",
        "wall_label": SPEC["label"],
        "reinforcement": {"type": rkey, "label": rtype["label"], "Tal_kN_per_m": Tal, "coverage_ratio": Rc,
                          "alpha": alpha, "length_m": L, "count": len(ys)},
        "geometry": {"height_m": H, "embedment_m": emb, "effective_height_m": round(eff, 4),
                     "reinforcement_length_m": L, "layers_m": ys},
        "applicability": {"basis": SPEC["basis"],
                          "notes": ["有效高（露出地面）%.2f m ≤ %.1f m" % (eff, SPEC["max_effective_height_m"])]},
        "soil": dict(soil, base_friction=mu),
        "seismic": {"kh": kh},
        "Ka_retained": Kab, "Kae_retained": Kae, "Ka_reinforced": Ka_r,
        "external": {"static": ext_s, "seismic": ext_e},
        "passive": passive,
        "layers": layers,
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in checks),
    }


def format_report(res: Mapping[str, Any]) -> str:
    g, r = res["geometry"], res["reinforcement"]
    lines = [
        "%s：牆高 %.2f m、埋入 %.2f m、有效高 %.2f m；%s %d 層、長 %.2f m、Tal=%.1f kN/m、Rc=%.2f"
        % (res["wall_label"], g["height_m"], g["embedment_m"], g["effective_height_m"], r["label"],
           r["count"], r["length_m"], r["Tal_kN_per_m"], r["coverage_ratio"]),
        "保留土 Ka=%.3f、加勁土 Ka=%.3f、基底 μ=%.3f；kh=%.2f"
        % (res["Ka_retained"], res["Ka_reinforced"], res["soil"]["base_friction"], res["seismic"]["kh"]),
        "",
    ]
    for case, ext in (("常時", res["external"]["static"]), ("地震", res["external"]["seismic"])):
        if ext:
            lines.append("外部（%s）：V=%.1f kN/m、Ph=%.1f kN/m、FS滑=%.2f、FS倒=%.2f、e=%.3f m、σv=%.1f kPa"
                         % (case, ext["V_kN_per_m"], ext["Ph_kN_per_m"], ext["FS_sliding"],
                            ext["FS_overturning"], ext["e_m"], ext["sigma_v_kPa"]))
    passive_line = EP.passive_summary(res.get("passive") or {})
    if passive_line:
        lines.append(passive_line)
    lines.append("")
    lines.append("內部：層  y(m)  Sv  Kr  Tmax(kN/m)  Le(m)  FS拉斷  FS拉出")
    for l in res["layers"]:
        lines.append("  %2d  %.2f  %.2f  %.3f  %.2f  %.2f  %.2f  %.2f"
                     % (l["layer"], l["y_m"], l["Sv_m"], l["Kr"], l["Tmax_kN_per_m"], l["Le_m"],
                        l["FS_rupture"], l["FS_pullout"]))
    lines.append("")
    for c in res["checks"]:
        if c["ok"] and "第 " in c["item"]:
            continue          # 逐層通過項不重複列出（已見上表）
        lines.append("  [%s] %s：%.3f / %.3f" % ("OK" if c["ok"] else "NG", c["item"], c["value"], c["limit"]))
    lines.append("")
    lines.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整加勁長度、間距或強度"))
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（加勁擋土牆 H=6 m、常時工況，每項可獨立驗算）。"""
    from _selftest_util import Checker

    c = Checker("加勁擋土牆（H = 6 m）")
    q = {"height_m": 6.0, "embedment_m": 0.6, "reinforcement_type": "geogrid",
         "reinforcement_length_m": 5.4, "vertical_spacing_m": 0.6,
         "first_layer_m": 0.3, "long_term_strength_kN_per_m": 40.0,
         "coverage_ratio": 1.0}
    soil = {"reinforced_gamma": 19.0, "reinforced_phi_deg": 34.0,
            "retained_gamma": 18.0, "retained_phi_deg": 30.0,
            "foundation_phi_deg": 30.0, "backfill_slope_deg": 0.0,
            "surcharge_kpa": 10.0, "allowable_bearing_kpa": 300.0,
            "foundation": "soil"}
    r = analyse(q, soil=soil, seismic={"kh": 0.15})
    ext = r["external"]["static"]
    c.close("擋土側 Ka", r["Ka_retained"],
            math.tan(math.radians(45.0 - 30.0 / 2)) ** 2, tol=1e-4)
    c.close("加勁側 Ka", r["Ka_reinforced"],
            math.tan(math.radians(45.0 - 34.0 / 2)) ** 2, tol=1e-4)
    c.close("外部主動土壓力 Ph", ext["Ph_kN_per_m"],
            0.5 * r["Ka_retained"] * 18.0 * 6.0 ** 2
            + 10.0 * r["Ka_retained"] * 6.0, tol=1e-4)
    c.close("外部抗滑 FS", ext["FS_sliding"],
            ext["V_kN_per_m"] * math.tan(math.radians(30.0))
            / ext["Ph_kN_per_m"], tol=1e-4)
    c.close("外部抗傾倒 FS", ext["FS_overturning"],
            ext["M_resist_kNm"] / ext["M_over_kNm"], tol=1e-4)
    with_passive = analyse({**q, "include_passive": True}, soil=soil, seismic={"kh": 0.15})
    c.close("牆趾被動土壓力 Pp", with_passive["passive"]["Pp_kN_per_m"],
            0.5 * 3.0 * 18.0 * 0.6 ** 2, tol=1e-3)
    c.close("計入 Pp 後外部抗滑 FS", with_passive["external"]["static"]["FS_sliding"],
            (ext["V_kN_per_m"] * math.tan(math.radians(30.0)) + 9.72)
            / ext["Ph_kN_per_m"], tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    ap = argparse.ArgumentParser(description="加勁擋土牆外部與內部穩定分析")
    ap.add_argument("json", help="輸入 JSON（section／soil／kh）")
    args = ap.parse_args()
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    res = analyse(data.get("section") or data, soil=data.get("soil"), seismic={"kh": float(data.get("kh", 0.0))})
    print(format_report(res))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
