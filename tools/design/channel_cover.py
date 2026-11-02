"""RC 路側溝加蓋：溝蓋版撓曲、剪力、裂縫、撓度與植筋設計。

適用於既有 U 型或矩形 RC 明溝，於溝壁頂植筋後澆置（或預鑄）RC 溝蓋，
承受 HS20-44 後輪載重（可再乘重型貨車係數 1.25）。

載重側依《公路橋梁設計規範》4.3.3 情況 A（主筋垂直車行方向、跨徑
0.6~7.2 m）：每公尺寬度活載重彎矩 M = P(S+6.0)/6.9（未含衝擊），
衝擊係數 I = 15.24/(S+38.1)，上限 30%。原頁文字層已核對。

配筋側依《建築物混凝土結構設計規範》（112.08.10 版）第 22 章撓曲、
剪力與第 24 章版最小鋼筋。植筋拉力握裹依第 17 章黏結式錨栓，特徵握裹
應力取表 17.6.5.2.5 室外值（開裂 14 kgf/cm²、未開裂 45 kgf/cm²）。

限制：
- 只做簡支版正彎矩；不把 20 cm 溝壁當固接支承（邊距不足，固接不可靠）。
- 植筋拉力需求採「抗掀名義比例」，非規範明文，預設 10% 輪載。
- 未檢核既有溝壁側向穩定、基礎承載、疲勞、溫度與地震。
- 植筋膠須有黏結式錨栓評估準則（ACI 355.4）認證，並依產品資料覆核。
"""

from __future__ import annotations

import math
from typing import Any, Mapping


SCHEMA = "civil-design-channel-cover/1"
KN_PER_KGF = 0.00980665
KGCM2_PER_MPA = 10.197162
REBAR = {
    "D10": (9.53, 71.0),
    "D13": (12.7, 127.0),
    "D16": (15.9, 199.0),
    "D19": (19.1, 287.0),
    "D22": (22.2, 387.0),
    "D25": (25.4, 507.0),
    "D29": (28.7, 647.0),
}


class ChannelCoverError(ValueError):
    """輸入不合法或超出適用範圍。"""


def _num(
    node: Mapping[str, Any],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = node.get(key, default)
    if value in (None, ""):
        value = default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ChannelCoverError("%s 必須是數值" % key) from exc
    if not math.isfinite(number):
        raise ChannelCoverError("%s 必須是有限數值" % key)
    if minimum is not None and number < minimum:
        raise ChannelCoverError("%s 不得小於 %g" % (key, minimum))
    if maximum is not None and number > maximum:
        raise ChannelCoverError("%s 不得大於 %g" % (key, maximum))
    return number


def _beta1(fc_mpa: float) -> float:
    if fc_mpa <= 28.0:
        return 0.85
    return max(0.65, 0.85 - 0.05 * (fc_mpa - 28.0) / 7.0)


def _phi_flexure(As_mm2: float, b_mm: float, d_mm: float, fc_mpa: float, fy_mpa: float) -> tuple[float, float]:
    """依淨拉應變回傳 (φ, εt)；RC 112 表 21.2.2。"""
    a = As_mm2 * fy_mpa / (0.85 * fc_mpa * b_mm)
    c = a / _beta1(fc_mpa)
    if c <= 0:
        return 0.90, 0.005
    et = 0.003 * (d_mm - c) / c
    ety = fy_mpa / 200000.0
    if et >= 0.005:
        return 0.90, et
    if et <= ety:
        return 0.65, et
    phi = 0.65 + 0.25 * (et - ety) / (0.005 - ety)
    return phi, et


def _pick_bars(
    as_req_mm2: float,
    *,
    s_max_mm: float,
    allowed: tuple[str, ...] = ("D13", "D16", "D19", "D22", "D25"),
    s_min_mm: float = 75.0,
) -> dict[str, Any]:
    """由需求鋼筋量選筋；回傳 name／db／area／spacing／As_prov。"""
    candidates: list[dict[str, Any]] = []
    for name in allowed:
        db, area = REBAR[name]
        if as_req_mm2 <= 0:
            spacing = s_max_mm
        else:
            spacing = area * 1000.0 / as_req_mm2
        spacing = math.floor(min(spacing, s_max_mm) / 5.0) * 5.0
        if spacing < s_min_mm:
            continue
        as_prov = area * 1000.0 / spacing
        candidates.append(
            {
                "bar": name,
                "db_mm": db,
                "area_mm2": area,
                "spacing_mm": spacing,
                "As_prov_mm2": round(as_prov, 1),
                "over_mm2": round(as_prov - as_req_mm2, 1),
            }
        )
    if not candidates:
        # 需求超過單層最小間距可容納量：回傳最大筋、最小間距，讓上層判 ok=False
        # 並繼續搜尋較厚版，而不是直接中斷。
        name = max(allowed, key=lambda n: REBAR[n][1])
        db, area = REBAR[name]
        return {
            "bar": name,
            "db_mm": db,
            "area_mm2": area,
            "spacing_mm": s_min_mm,
            "As_prov_mm2": round(area * 1000.0 / s_min_mm, 1),
            "over_mm2": round(area * 1000.0 / s_min_mm - as_req_mm2, 1),
        }
    # 取「剛好足夠且間距最大」者：先篩 As_prov >= As_req，再取間距最大。
    enough = [c for c in candidates if c["As_prov_mm2"] >= as_req_mm2]
    pool = enough or candidates
    # 取「剛好足夠且最經濟」者；避免大直徑大間距造成鋼筋量遠超需求。
    pool.sort(key=lambda c: (c["over_mm2"], -c["spacing_mm"]))
    return pool[0]


def _flexure(
    mu_knm: float,
    *,
    b_mm: float,
    h_mm: float,
    fc_mpa: float,
    fy_mpa: float,
    cover_mm: float,
    s_max_mm: float,
    allowed: tuple[str, ...] = ("D16", "D19", "D22", "D25", "D29"),
    s_min_mm: float = 100.0,
) -> dict[str, Any]:
    """單筋矩形版撓曲設計（每公尺寬）。"""
    # 先以 D19 估 d，選筋後再用實際 db 重算。
    d_est = h_mm - cover_mm - 9.5
    if d_est <= 0:
        raise ChannelCoverError("版厚不足，有效深度 d ≤ 0")
    mu_nmm = mu_knm * 1e6
    rn = mu_nmm / (0.90 * b_mm * d_est * d_est)
    disc = 1.0 - 2.0 * rn / (0.85 * fc_mpa)
    if disc < 0:
        return {"ok": False, "error": "斷面不足，R 超過單筋上限", "Mu_kNm": round(mu_knm, 2)}
    rho = 0.85 * fc_mpa / fy_mpa * (1.0 - math.sqrt(disc))
    as_req = rho * b_mm * d_est
    as_min1 = 0.0018 * b_mm * h_mm
    as_min2 = 1.4 * b_mm * d_est / fy_mpa
    as_min = max(as_min1, as_min2)
    as_design = max(as_req, as_min)
    picked: dict[str, Any] = {}
    phi_mn = 0.0
    d = 0.0
    et = 0.0
    phi = 0.0
    as_prov = 0.0
    for _ in range(10):
        picked = _pick_bars(as_design, s_max_mm=s_max_mm, allowed=allowed, s_min_mm=s_min_mm)
        db = picked["db_mm"]
        d = h_mm - cover_mm - db / 2.0
        as_prov = picked["As_prov_mm2"]
        a = as_prov * fy_mpa / (0.85 * fc_mpa * b_mm)
        mn = as_prov * fy_mpa * (d - a / 2.0) / 1e6
        phi, et = _phi_flexure(as_prov, b_mm, d, fc_mpa, fy_mpa)
        phi_mn = phi * mn
        if phi_mn >= mu_knm:
            break
        # 選筋後 d 會因較大直徑而減少；按不足比例放大需求重選。
        as_design = as_prov * max(1.03, mu_knm / max(phi_mn, 1e-9) * 1.02)
        if picked["spacing_mm"] <= s_min_mm:
            break
    return {
        "ok": phi_mn >= mu_knm,
        "Mu_kNm": round(mu_knm, 2),
        "phiMn_kNm": round(phi_mn, 2),
        "utilization": round(mu_knm / phi_mn, 3) if phi_mn > 0 else None,
        "d_mm": round(d, 1),
        "phi": round(phi, 3),
        "epsilon_t": round(et, 5),
        "As_req_mm2": round(as_req, 1),
        "As_min_mm2": round(as_min, 1),
        "As_design_mm2": round(as_design, 1),
        "As_prov_mm2": as_prov,
        "governed_by": "最小鋼筋" if as_min > as_req else "撓曲強度",
        "source": "自動",
        "flexure_ok": phi_mn >= mu_knm,
        "as_ok": as_prov >= as_min,
        "spacing_ok": s_min_mm <= picked["spacing_mm"] <= s_max_mm,
        **picked,
    }


def _specified_flexure(
    mu_knm: float,
    *,
    bar: str,
    spacing_mm: float,
    b_mm: float,
    h_mm: float,
    fc_mpa: float,
    fy_mpa: float,
    cover_mm: float,
    s_max_mm: float,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """依使用者指定的筋徑與間距計算撓曲，不做任何自動調整。"""
    if bar not in REBAR:
        raise ChannelCoverError("不支援的鋼筋號數 %s（可用 D10～D29）" % bar)
    db, area = REBAR[bar]
    d = h_mm - cover_mm - db / 2.0
    if d <= 0:
        raise ChannelCoverError("版厚不足，指定主筋的有效深度 d ≤ 0")
    if base is None:
        base = _flexure(
            mu_knm, b_mm=b_mm, h_mm=h_mm, fc_mpa=fc_mpa, fy_mpa=fy_mpa,
            cover_mm=cover_mm, s_max_mm=s_max_mm,
        )
    if "error" in base and "As_min_mm2" not in base:
        raise ChannelCoverError(str(base["error"]))
    as_prov = area * 1000.0 / spacing_mm
    a = as_prov * fy_mpa / (0.85 * fc_mpa * b_mm)
    phi, et = _phi_flexure(as_prov, b_mm, d, fc_mpa, fy_mpa)
    phi_mn = phi * as_prov * fy_mpa * (d - a / 2.0) / 1e6
    as_min = float(base.get("As_min_mm2", 0.0))
    spacing_min = db + 25.0
    if spacing_mm < spacing_min:
        raise ChannelCoverError(
            "主筋間距 %g mm 小於可施工最小淨間距（db+25＝%g mm）" % (spacing_mm, spacing_min)
        )
    flexure_ok = phi_mn >= mu_knm
    as_ok = as_prov >= as_min
    spacing_ok = spacing_mm <= s_max_mm
    return {
        "ok": flexure_ok and as_ok and spacing_ok,
        "Mu_kNm": round(mu_knm, 2),
        "phiMn_kNm": round(phi_mn, 2),
        "utilization": round(mu_knm / phi_mn, 3) if phi_mn > 0 else None,
        "d_mm": round(d, 1),
        "phi": round(phi, 3),
        "epsilon_t": round(et, 5),
        "As_req_mm2": round(float(base.get("As_req_mm2", 0.0)), 1),
        "As_min_mm2": round(as_min, 1),
        "As_design_mm2": round(as_prov, 1),
        "As_prov_mm2": round(as_prov, 1),
        "governed_by": "使用者指定",
        "source": "指定",
        "flexure_ok": flexure_ok,
        "as_ok": as_ok,
        "spacing_ok": spacing_ok,
        "bar": bar,
        "db_mm": db,
        "area_mm2": area,
        "spacing_mm": spacing_mm,
        "over_mm2": round(as_prov - float(base.get("As_req_mm2", 0.0)), 1),
    }


def _specified_bars(
    as_req_mm2: float,
    *,
    bar: str,
    spacing_mm: float,
    s_max_mm: float,
) -> dict[str, Any]:
    """依使用者指定的筋徑與間距計算一般鋼筋（分佈筋等）。"""
    if bar not in REBAR:
        raise ChannelCoverError("不支援的鋼筋號數 %s（可用 D10～D29）" % bar)
    db, area = REBAR[bar]
    as_prov = area * 1000.0 / spacing_mm
    spacing_min = db + 25.0
    if spacing_mm < spacing_min:
        raise ChannelCoverError(
            "鋼筋間距 %g mm 小於可施工最小淨間距（db+25＝%g mm）" % (spacing_mm, spacing_min)
        )
    return {
        "ok": as_prov >= as_req_mm2 and spacing_mm <= s_max_mm,
        "as_ok": as_prov >= as_req_mm2,
        "spacing_ok": spacing_mm <= s_max_mm,
        "source": "指定",
        "bar": bar,
        "db_mm": db,
        "area_mm2": area,
        "spacing_mm": spacing_mm,
        "As_prov_mm2": round(as_prov, 1),
        "over_mm2": round(as_prov - as_req_mm2, 1),
    }


def _crack_width(
    *,
    as_mm2: float,
    b_mm: float,
    h_mm: float,
    d_mm: float,
    spacing_mm: float,
    cover_mm: float,
    fc_mpa: float,
    m_service_knm: float,
) -> dict[str, Any]:
    """RC 112 24.3.2 裂縫寬度（w = 2fs/Es·√(dc²+(s/2)²)）。"""
    es = 200000.0
    ec = 4700.0 * math.sqrt(fc_mpa)
    n = es / ec
    # 中性軸（開裂斷面，單筋）
    rho = as_mm2 / (b_mm * d_mm)
    k = math.sqrt((rho * n) ** 2 + 2.0 * rho * n) - rho * n
    kd = k * d_mm
    j = 1.0 - k / 3.0
    fs = m_service_knm * 1e6 / (as_mm2 * j * d_mm) if as_mm2 > 0 else 0.0
    dc = cover_mm + 12.7
    w = 2.0 * fs / es * math.sqrt(dc ** 2 + (spacing_mm / 2.0) ** 2)
    return {
        "ok": w <= 0.30,
        "w_mm": round(w, 3),
        "limit_mm": 0.30,
        "fs_mpa": round(fs, 1),
        "dc_mm": round(dc, 1),
        "note": "w＝2fs/Es·√(dc²+(s/2)²)；dc＝保護層＋db/2（保守取 D25）",
    }


def _design_slab_section(
    mu_knm: float,
    m_service_knm: float,
    *,
    b_mm: float,
    h_mm: float,
    fc_mpa: float,
    fy_mpa: float,
    cover_mm: float,
    s_max_mm: float,
    allowed: tuple[str, ...] = ("D16", "D19", "D22", "D25", "D29"),
    s_min_mm: float = 100.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """撓曲＋裂縫聯合選筋。

    只用撓曲強度選筋會落在「剛好通過」的鋼筋量，服務載重下 fs 偏高、
    間距也偏大，裂縫寬度常反而不過。本函式逐一列舉「筋徑×間距」，
    在同時滿足 φMn ≥ Mu 與 w ≤ 0.30 mm 的組合中，取鋼筋量最少者。
    """
    base = _flexure(
        mu_knm, b_mm=b_mm, h_mm=h_mm, fc_mpa=fc_mpa, fy_mpa=fy_mpa,
        cover_mm=cover_mm, s_max_mm=s_max_mm, allowed=allowed, s_min_mm=s_min_mm,
    )
    as_min = base.get("As_min_mm2", 0.0)
    best: dict[str, Any] | None = None
    best_crack: dict[str, Any] | None = None
    for name in allowed:
        db, area = REBAR[name]
        d = h_mm - cover_mm - db / 2.0
        if d <= 0:
            continue
        spacing = s_min_mm
        while spacing <= s_max_mm + 1e-9:
            as_prov = area * 1000.0 / spacing
            if as_prov + 1e-9 < as_min:
                spacing += 5.0
                continue
            a = as_prov * fy_mpa / (0.85 * fc_mpa * b_mm)
            phi, et = _phi_flexure(as_prov, b_mm, d, fc_mpa, fy_mpa)
            phi_mn = phi * as_prov * fy_mpa * (d - a / 2.0) / 1e6
            if phi_mn + 1e-9 < mu_knm:
                spacing += 5.0
                continue
            crack = _crack_width(
                as_mm2=as_prov, b_mm=b_mm, h_mm=h_mm, d_mm=d,
                spacing_mm=spacing, cover_mm=cover_mm, fc_mpa=fc_mpa,
                m_service_knm=m_service_knm,
            )
            if crack["ok"] and (best is None or as_prov < best["As_prov_mm2"] - 0.5):
                best = {
                    "ok": True,
                    "Mu_kNm": round(mu_knm, 2),
                    "phiMn_kNm": round(phi_mn, 2),
                    "utilization": round(mu_knm / phi_mn, 3),
                    "d_mm": round(d, 1),
                    "phi": round(phi, 3),
                    "epsilon_t": round(et, 5),
                    "As_req_mm2": round(base["As_req_mm2"], 1),
                    "As_min_mm2": round(as_min, 1),
                    "As_design_mm2": round(as_prov, 1),
                    "As_prov_mm2": round(as_prov, 1),
                    "source": "自動",
                    "flexure_ok": True,
                    "as_ok": True,
                    "spacing_ok": True,
                    "bar": name,
                    "db_mm": db,
                    "area_mm2": area,
                    "spacing_mm": spacing,
                    "over_mm2": round(as_prov - base["As_req_mm2"], 1),
                }
                best_crack = crack
            spacing += 5.0
    if best is None or best_crack is None:
        # 回傳強度設計結果（crack 取同一配置），讓上層判 ok=False 並換版厚。
        flex = base
        crack = _crack_width(
            as_mm2=flex.get("As_prov_mm2", 0.0), b_mm=b_mm, h_mm=h_mm,
            d_mm=flex.get("d_mm", 0.0), spacing_mm=flex.get("spacing_mm", s_max_mm),
            cover_mm=cover_mm, fc_mpa=fc_mpa, m_service_knm=m_service_knm,
        )
        return flex, crack
    strength_ok = bool(base.get("ok"))
    base_crack = _crack_width(
        as_mm2=base.get("As_prov_mm2", 0.0), b_mm=b_mm, h_mm=h_mm,
        d_mm=base.get("d_mm", 0.0), spacing_mm=base.get("spacing_mm", s_max_mm),
        cover_mm=cover_mm, fc_mpa=fc_mpa, m_service_knm=m_service_knm,
    )
    if strength_ok and not base_crack["ok"]:
        best["governed_by"] = "裂縫控制（主筋加密）"
        best["As_strength_mm2"] = base["As_prov_mm2"]
    else:
        best["governed_by"] = base.get("governed_by", "撓曲強度")
    return best, best_crack


def _deflection(
    *,
    h_mm: float,
    b_mm: float,
    d_mm: float,
    as_mm2: float,
    fc_mpa: float,
    span_m: float,
    m_service_knm: float,
    m_cr_knm: float,
) -> dict[str, Any]:
    ec = 4700.0 * math.sqrt(fc_mpa)
    ig = b_mm * h_mm ** 3 / 12.0
    fr = 0.62 * math.sqrt(fc_mpa)
    # 開裂斷面 Icr
    n = 200000.0 / ec
    rho = as_mm2 / (b_mm * d_mm)
    k = math.sqrt((rho * n) ** 2 + 2.0 * rho * n) - rho * n
    icr = b_mm * (k * d_mm) ** 3 / 3.0 + n * as_mm2 * (d_mm - k * d_mm) ** 2
    ratio = min(1.0, (m_cr_knm / m_service_knm) ** 3) if m_service_knm > 0 else 1.0
    ie = ratio * ig + (1.0 - ratio) * icr
    ie = max(ie, 0.1 * ig)
    # 以等效均佈載重模擬集中輪載：δ = 5wL⁴/(384EI)，w_eq = 8P/πL？此處用集中載重式。
    p_kn = 4.0 * m_service_knm / span_m  # 簡支跨中集中載重 M=PL/4
    delta_mm = p_kn * 1000.0 * (span_m * 1000.0) ** 3 / (48.0 * ec * ie)
    limit_mm = span_m * 1000.0 / 800.0
    return {
        "ok": delta_mm <= limit_mm,
        "delta_mm": round(delta_mm, 2),
        "limit_mm": round(limit_mm, 2),
        "Ig_mm4": round(ig, 0),
        "Icr_mm4": round(icr, 0),
        "Ie_mm4": round(ie, 0),
        "Ec_mpa": round(ec, 0),
    }


def _anchor_tension(
    *,
    da_mm: float,
    hef_mm: float,
    fc_mpa: float,
    tau_kgf_cm2: float,
    tau_uncr_kgf_cm2: float,
    ca_mm: float,
    fy_mpa: float,
) -> dict[str, Any]:
    """單根黏結式錨栓拉力容量（kgf→kN）。"""
    da_cm = da_mm / 10.0
    hef_cm = hef_mm / 10.0
    fc_kgf = fc_mpa * KGCM2_PER_MPA
    as_mm2 = math.pi * da_mm ** 2 / 4.0
    nba = tau_kgf_cm2 * math.pi * da_cm * hef_cm
    cna = 10.0 * da_cm * math.sqrt(max(tau_uncr_kgf_cm2, 1e-9) / 77.0)
    ca_cm = ca_mm / 10.0
    psi_ed = 1.0 if ca_cm >= cna else 0.7 + 0.3 * ca_cm / cna
    cac = 2.0 * hef_cm
    psi_cp = 1.0 if ca_cm >= cac else max(ca_cm / cac, cna / cac)
    na = psi_ed * psi_cp * nba
    nb = 7.0 * math.sqrt(fc_kgf) * hef_cm ** 1.5
    psi_ed_n = min(1.0, ca_cm / (1.5 * hef_cm)) if hef_cm > 0 else 0.0
    ncb = psi_ed_n * nb
    nsa = as_mm2 * fy_mpa / 1000.0
    phi_na_kn = 0.65 * na * KN_PER_KGF
    phi_ncb_kn = 0.65 * ncb * KN_PER_KGF
    phi_nsa_kn = 0.75 * nsa
    cap = min(phi_na_kn, phi_ncb_kn, phi_nsa_kn)
    return {
        "Nba_kgf": round(nba, 1),
        "Na_kgf": round(na, 1),
        "Nb_kgf": round(nb, 1),
        "Ncb_kgf": round(ncb, 1),
        "Nsa_kN": round(nsa, 1),
        "phiNa_kN": round(phi_na_kn, 2),
        "phiNcb_kN": round(phi_ncb_kn, 2),
        "phiNsa_kN": round(phi_nsa_kn, 2),
        "capacity_kN": round(cap, 2),
        "cNa_cm": round(cna, 2),
        "psi_ed_Na": round(psi_ed, 3),
        "psi_cp_Na": round(psi_cp, 3),
        "psi_ed_N": round(psi_ed_n, 3),
        "governed_by": (
            "鋼材" if cap == phi_nsa_kn
            else ("混凝土拉破" if cap == phi_ncb_kn else "握裹")
        ),
    }


def _anchor_shear(
    *,
    da_mm: float,
    hef_mm: float,
    fc_mpa: float,
    ca_mm: float,
    fy_mpa: float,
) -> dict[str, Any]:
    da_cm = da_mm / 10.0
    hef_cm = hef_mm / 10.0
    fc_kgf = fc_mpa * KGCM2_PER_MPA
    as_mm2 = math.pi * da_mm ** 2 / 4.0
    le_cm = min(hef_cm, 8.0 * da_cm)
    ca1 = ca_mm / 10.0
    vb = min(
        1.86 * (le_cm / da_cm) ** 0.2 * math.sqrt(da_cm) * math.sqrt(fc_kgf) * ca1 ** 1.5,
        3.8 * math.sqrt(fc_kgf) * ca1 ** 1.5,
    )
    vsa = 0.6 * as_mm2 * fy_mpa / 1000.0
    vcb = vb
    cap = min(0.65 * vsa, 0.70 * vcb * KN_PER_KGF)
    return {
        "Vb_kgf": round(vb, 1),
        "Vsa_kN": round(vsa, 1),
        "phiVsa_kN": round(0.65 * vsa, 2),
        "phiVcb_kN": round(0.70 * vcb * KN_PER_KGF, 2),
        "capacity_kN": round(cap, 2),
        "le_cm": round(le_cm, 2),
    }


def analyse(payload: Mapping[str, Any]) -> dict[str, Any]:
    """溝蓋版＋植筋聯合設計。"""
    if not isinstance(payload, Mapping):
        raise ChannelCoverError("payload 必須是 JSON 物件")
    geo = payload.get("geometry") or {}
    mat = payload.get("materials") or {}
    loads = payload.get("loads") or {}
    conn = payload.get("connection") or {}
    slab_opt = payload.get("slab") or {}
    for name, node in (
        ("geometry", geo), ("materials", mat), ("loads", loads),
        ("connection", conn), ("slab", slab_opt),
    ):
        if not isinstance(node, Mapping):
            raise ChannelCoverError("%s 必須是 JSON 物件" % name)

    def _rebar_spec(prefix: str, label: str) -> tuple[str | None, float | None]:
        bar = str(slab_opt.get(prefix + "_bar") or "").strip().upper()
        raw = slab_opt.get(prefix + "_spacing_mm")
        spacing: float | None = None
        if raw not in (None, ""):
            spacing = _num(slab_opt, prefix + "_spacing_mm", 0.0, minimum=0.0, maximum=1000.0)
            if spacing == 0.0:
                spacing = None
        if bool(bar) != bool(spacing):
            raise ChannelCoverError(
                "%s須同時指定號數與間距（間距 0 或留空＝自動設計）" % label
            )
        if bar and bar not in REBAR:
            raise ChannelCoverError("%s號數 %s 不支援（可用 D10～D29）" % (label, bar))
        return (bar, spacing) if bar and spacing else (None, None)

    main_bar_spec, main_spacing_spec = _rebar_spec("main", "主筋")
    dist_bar_spec, dist_spacing_spec = _rebar_spec("dist", "分佈筋")

    b_clear = _num(geo, "clear_width_m", 0.60, minimum=0.30, maximum=3.00)
    t_wall = _num(geo, "wall_thickness_m", 0.20, minimum=0.10, maximum=0.60)
    cover_mm = _num(geo, "cover_mm", 50.0, minimum=25.0, maximum=100.0)
    bearing_min_mm = _num(geo, "bearing_length_min_mm", 75.0, minimum=50.0)

    fc_slab = _num(mat, "slab_fc_mpa", 28.0, minimum=17.0, maximum=70.0)
    fc_wall = _num(mat, "wall_fc_mpa", 21.0, minimum=13.0, maximum=70.0)
    fy = _num(mat, "fy_mpa", 420.0, minimum=280.0, maximum=550.0)
    gamma_c = _num(mat, "unit_weight_kn_m3", 24.0, minimum=18.0, maximum=26.0)

    vehicle = str(loads.get("vehicle") or "hs20_1_25").strip().lower()
    if vehicle not in ("hs20", "hs20_1_25"):
        raise ChannelCoverError("vehicle 必須是 hs20 或 hs20_1_25")
    heavy = 1.25 if vehicle == "hs20_1_25" else 1.0
    live_factor = _num(loads, "live_load_factor", 1.67, minimum=1.0, maximum=2.0)
    if bool(loads.get("deck_beta_1_0", False)):
        live_factor = 1.0
    wearing_kpa = _num(loads, "wearing_surface_kpa", 0.0, minimum=0.0, maximum=15.0)
    uplift_factor = _num(loads, "uplift_factor", 0.10, minimum=0.0, maximum=0.30)
    horizontal_kn_m = _num(loads, "horizontal_force_kN_m", 0.0, minimum=0.0, maximum=100.0)

    model = str(conn.get("model") or "simple").strip().lower()
    if model not in ("simple", "partial_fixity"):
        raise ChannelCoverError("connection.model 必須是 simple 或 partial_fixity")
    fixity = 0.0
    if model == "partial_fixity":
        fixity = _num(conn, "fixity_ratio", 0.50, minimum=0.0, maximum=0.75)
    bar_name = str(conn.get("bar") or "D16").strip().upper()
    if bar_name not in ("D13", "D16"):
        raise ChannelCoverError("20 cm 溝壁的植筋邊距僅容許 D13 或 D16（6db ≤ 100 mm）")
    da_mm, _ = REBAR[bar_name]
    anchor_spacing = _num(conn, "spacing_mm", 150.0, minimum=100.0, maximum=400.0)
    hef_in = conn.get("embedment_mm")
    hef_mm = _num(conn, "embedment_mm", min(15.0 * da_mm, 200.0), minimum=80.0, maximum=300.0) if hef_in not in (None, "") else min(15.0 * da_mm, 200.0)
    cracked = bool(conn.get("cracked", True))
    tau_cr = _num(conn, "tau_cr_kgf_cm2", 14.0, minimum=5.0, maximum=40.0)
    tau_uncr = _num(conn, "tau_uncr_kgf_cm2", 45.0, minimum=20.0, maximum=100.0)
    tau_used = tau_cr if cracked else tau_uncr
    surface = str(conn.get("surface_condition") or "roughened").strip().lower()
    if surface not in ("roughened", "smooth"):
        raise ChannelCoverError("surface_condition 必須是 roughened 或 smooth")
    mu_friction = 1.0 if surface == "roughened" else 0.6

    p20_kgf = 7300.0
    p20_kn = p20_kgf * KN_PER_KGF

    # ── 版厚自動搜尋 ─────────────────────────────────────────────────────
    h_in = geo.get("slab_thickness_mm")
    explicit_h = h_in not in (None, "")
    if not explicit_h:
        thicknesses = [200 + 25 * i for i in range(0, 9)]  # 200~400
    else:
        thicknesses = [_num(geo, "slab_thickness_mm", 250.0, minimum=180.0, maximum=500.0)]

    attempts: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    for h_mm in thicknesses:
        s_cc = b_clear + t_wall
        s_eff = min(s_cc, b_clear + h_mm / 1000.0)
        if not (0.6 <= s_eff <= 7.2):
            attempts.append({"h_mm": h_mm, "ok": False, "reason": "有效跨徑 %.3f m 不在 0.6~7.2 m" % s_eff})
            continue
        impact = min(15.24 / (s_eff + 38.1), 0.30)
        m_ll = p20_kn * heavy * (s_eff + 6.0) / 6.9 * (1.0 + impact)
        w_self = gamma_c * h_mm / 1000.0
        m_d = (w_self + wearing_kpa) * s_eff ** 2 / 8.0
        mu = 1.25 * m_d + live_factor * m_ll
        vu = 1.25 * ((w_self + wearing_kpa) * s_eff / 2.0) + live_factor * p20_kn * heavy * (1.0 + impact) / 2.0
        s_max = min(3.0 * h_mm, 450.0)
        m_service = m_d + m_ll
        base_flex = _flexure(
            mu, b_mm=1000.0, h_mm=h_mm, fc_mpa=fc_slab, fy_mpa=fy,
            cover_mm=cover_mm, s_max_mm=s_max,
        )
        if main_bar_spec and main_spacing_spec:
            flex = _specified_flexure(
                mu, bar=main_bar_spec, spacing_mm=main_spacing_spec,
                b_mm=1000.0, h_mm=h_mm, fc_mpa=fc_slab, fy_mpa=fy,
                cover_mm=cover_mm, s_max_mm=s_max, base=base_flex,
            )
            crack = _crack_width(
                as_mm2=flex["As_prov_mm2"], b_mm=1000.0, h_mm=h_mm,
                d_mm=flex["d_mm"], spacing_mm=flex["spacing_mm"],
                cover_mm=cover_mm, fc_mpa=fc_slab, m_service_knm=m_service,
            )
        else:
            flex, crack = _design_slab_section(
                mu, m_service, b_mm=1000.0, h_mm=h_mm, fc_mpa=fc_slab, fy_mpa=fy,
                cover_mm=cover_mm, s_max_mm=s_max,
            )
        ok = bool(flex.get("ok")) and bool(crack["ok"])
        attempts.append(
            {
                "h_mm": h_mm,
                "ok": ok,
                "source": flex.get("source"),
                "S_m": round(s_eff, 3),
                "Mu_kNm": round(mu, 1),
                "phiMn_kNm": flex.get("phiMn_kNm"),
                "bar": flex.get("bar"),
                "spacing_mm": flex.get("spacing_mm"),
                "w_mm": crack["w_mm"],
            }
        )
        if ok or explicit_h:
            chosen = {
                "h_mm": h_mm, "s_eff": s_eff, "s_cc": s_cc, "impact": impact,
                "m_ll": m_ll, "m_d": m_d, "mu": mu, "vu": vu,
                "w_self": w_self, "flex": flex, "crack": crack, "s_max": s_max,
            }
            break
    if chosen is None:
        raise ChannelCoverError(
            "可用版厚在「撓曲＋裂縫控制」下均無法通過；"
            "請加大版厚、提高 fc′ 或改雙層配筋"
        )
    if "d_mm" not in chosen["flex"]:
        raise ChannelCoverError(str(chosen["flex"].get("error") or "版厚不足，無法計算"))

    h_mm = chosen["h_mm"]
    s_eff = chosen["s_eff"]
    impact = chosen["impact"]
    m_ll = chosen["m_ll"]
    m_d = chosen["m_d"]
    mu = chosen["mu"]
    vu_side = chosen["vu"]
    flex = chosen["flex"]
    crack = chosen["crack"]
    s_max = chosen["s_max"]

    # ── 分佈鋼筋（公路橋梁設計規範第 9 節）──────────────────────────────
    pct = min(121.0 / math.sqrt(s_eff), 67.0)
    as_dist_req = flex["As_req_mm2"] * pct / 100.0
    as_temp = 0.0018 * 1000.0 * h_mm
    as_dist_design = max(as_dist_req, as_temp)
    dist_s_max = min(5.0 * h_mm, 450.0)
    if dist_bar_spec and dist_spacing_spec:
        dist = _specified_bars(
            as_dist_design, bar=dist_bar_spec,
            spacing_mm=dist_spacing_spec, s_max_mm=dist_s_max,
        )
    else:
        dist = _pick_bars(
            as_dist_design,
            s_max_mm=dist_s_max,
            allowed=("D10", "D13", "D16", "D19"),
        )
    # 分佈筋兩側 1/4 可減半，惟為施工一致，全跨同量；另列半量檢核。
    dist_half_ok = dist["As_prov_mm2"] >= 0.5 * as_dist_req

    # ── 頂層鋼筋 ─────────────────────────────────────────────────────────
    as_top_req = max(0.0018 * 1000.0 * h_mm, fixity * flex["As_req_mm2"])
    top = _pick_bars(
        as_top_req,
        s_max_mm=min(3.0 * h_mm, 300.0),
        allowed=("D13", "D16", "D19", "D22"),
    )

    # ── 剪力 ─────────────────────────────────────────────────────────────
    d_main = flex["d_mm"]
    phi_v = 0.75
    vc_n = 0.53 * math.sqrt(fc_slab) * 1000.0 * d_main
    phi_vc = phi_v * vc_n / 1000.0
    vc_ok = phi_vc >= vu_side

    # ── 撓度（裂縫已於選筋時檢核）────────────────────────────────────────
    m_service = m_d + m_ll
    ig = 1000.0 * h_mm ** 3 / 12.0
    m_cr = 0.62 * math.sqrt(fc_slab) * ig / (h_mm / 2.0) / 1e6
    defl = _deflection(
        h_mm=h_mm, b_mm=1000.0, d_mm=d_main, as_mm2=flex["As_prov_mm2"],
        fc_mpa=fc_slab, span_m=s_eff, m_service_knm=m_service, m_cr_knm=m_cr,
    )

    # ── 溝壁頂承壓 ───────────────────────────────────────────────────────
    bearing_area_m2 = t_wall * 1.0
    q_bearing_kpa = vu_side / bearing_area_m2
    q_allow_kpa = 0.35 * fc_wall * 1000.0  # MPa → kPa
    bearing_ok = q_bearing_kpa <= q_allow_kpa

    # ── 植筋 ─────────────────────────────────────────────────────────────
    # 每側每米植筋根數
    n_per_m = 1000.0 / anchor_spacing
    as_anchor_total = n_per_m * REBAR[bar_name][1]
    t_uplift = uplift_factor * p20_kn * heavy * live_factor  # kN/m，每側
    t_per_bar = t_uplift / n_per_m
    # 垂直剪力由溝壁頂承壓傳遞；植筋只承擔水平力（溫度、收縮、制動）。
    v_per_bar = horizontal_kn_m / n_per_m
    ca_mm = t_wall * 1000.0 / 2.0
    tension = _anchor_tension(
        da_mm=da_mm, hef_mm=hef_mm, fc_mpa=fc_wall, tau_kgf_cm2=tau_used,
        tau_uncr_kgf_cm2=tau_uncr, ca_mm=ca_mm, fy_mpa=fy,
    )
    shear_cap = _anchor_shear(
        da_mm=da_mm, hef_mm=hef_mm, fc_mpa=fc_wall, ca_mm=ca_mm, fy_mpa=fy,
    )
    interaction = (
        t_per_bar / tension["capacity_kN"] if tension["capacity_kN"] > 0 else 99.0
    ) + (
        v_per_bar / shear_cap["capacity_kN"] if shear_cap["capacity_kN"] > 0 else 99.0
    )
    tension_ok = t_per_bar <= tension["capacity_kN"]
    shear_ok = v_per_bar <= shear_cap["capacity_kN"]
    interaction_ok = interaction <= 1.2
    edge_min_mm = 6.0 * da_mm
    spacing_min_mm = 6.0 * da_mm
    edge_ok = ca_mm >= edge_min_mm
    spacing_ok = anchor_spacing >= spacing_min_mm
    friction_cap = 0.75 * mu_friction * as_anchor_total * fy / 1000.0
    friction_ok = friction_cap >= vu_side

    # ── 檢核表 ───────────────────────────────────────────────────────────
    checks: list[dict[str, Any]] = [
        {"item": "有效跨徑 S（0.6~7.2 m）", "value": round(s_eff, 3), "limit": 7.2, "unit": "m", "relation": "le", "ok": 0.6 <= s_eff <= 7.2},
        {"item": "版厚（重車最小 200 mm）", "value": h_mm, "limit": 200.0, "unit": "mm", "relation": "ge", "ok": h_mm >= 200.0},
        {"item": "主筋撓曲 φMn", "value": flex["Mu_kNm"], "limit": flex["phiMn_kNm"], "unit": "kN·m/m", "relation": "le", "ok": flex.get("flexure_ok", flex["ok"])},
        {"item": "主筋量 As", "value": flex["As_prov_mm2"], "limit": flex["As_min_mm2"], "unit": "mm²/m", "relation": "ge", "ok": flex.get("as_ok", True)},
        {"item": "主筋間距 s", "value": flex["spacing_mm"], "limit": round(s_max, 1), "unit": "mm", "relation": "le", "ok": flex.get("spacing_ok", True)},
        {"item": "混凝土剪力 φVc", "value": round(vu_side, 2), "limit": round(phi_vc, 2), "unit": "kN/m", "relation": "le", "ok": vc_ok},
        {"item": "裂縫寬度 w", "value": crack["w_mm"], "limit": 0.30, "unit": "mm", "relation": "le", "ok": crack["ok"]},
        {"item": "活載重撓度 δ", "value": defl["delta_mm"], "limit": defl["limit_mm"], "unit": "mm", "relation": "le", "ok": defl["ok"]},
        {"item": "溝壁頂承壓 q", "value": round(q_bearing_kpa, 1), "limit": round(q_allow_kpa, 1), "unit": "kPa", "relation": "le", "ok": bearing_ok},
        {"item": "植筋拉力（鋼材／握裹／拉破取小）", "value": round(t_per_bar, 2), "limit": tension["capacity_kN"], "unit": "kN/根", "relation": "le", "ok": tension_ok},
        {"item": "植筋剪力（鋼材／剪破取小）", "value": round(v_per_bar, 2), "limit": shear_cap["capacity_kN"], "unit": "kN/根", "relation": "le", "ok": shear_ok},
        {"item": "植筋拉剪互制", "value": round(interaction, 3), "limit": 1.2, "unit": "-", "relation": "le", "ok": interaction_ok},
        {"item": "植筋邊距 ca", "value": round(ca_mm, 1), "limit": round(edge_min_mm, 1), "unit": "mm", "relation": "ge", "ok": edge_ok},
        {"item": "植筋間距 s", "value": anchor_spacing, "limit": round(spacing_min_mm, 1), "unit": "mm", "relation": "ge", "ok": spacing_ok},
        {"item": "界面剪力摩擦 φVn", "value": round(vu_side, 2), "limit": round(friction_cap, 2), "unit": "kN/m", "relation": "le", "ok": friction_ok},
        {"item": "分佈筋兩側 1/4 半量", "value": dist["As_prov_mm2"], "limit": round(0.5 * as_dist_req, 1), "unit": "mm²/m", "relation": "ge", "ok": dist_half_ok},
        {"item": "分佈筋量 As", "value": dist["As_prov_mm2"], "limit": round(as_dist_design, 1), "unit": "mm²/m", "relation": "ge", "ok": dist.get("as_ok", True)},
        {"item": "分佈筋間距 s", "value": dist["spacing_mm"], "limit": round(dist_s_max, 1), "unit": "mm", "relation": "le", "ok": dist.get("spacing_ok", True)},
        {"item": "支承長度", "value": round(t_wall * 1000.0, 1), "limit": bearing_min_mm, "unit": "mm", "relation": "ge", "ok": t_wall * 1000.0 >= bearing_min_mm},
    ]

    warnings: list[str] = []
    if vehicle == "hs20_1_25":
        warnings.append("已依公路橋梁設計規範 §3.7.6 採 HS20-44 的 1.25 倍（省市重要道路／重型貨車）。")
    warnings.append("活載重彎矩採公路橋梁設計規範 4.3.3 情況 A（主筋垂直車行方向）；路側溝蓋非橋面板，屬類推適用。")
    warnings.append("有效跨徑 S=%.3f m 取支承中心距與「淨跨＋版厚」較小者；本案例由支承中心距控制。" % s_eff)
    warnings.append("既有溝壁 fc′ 假設 %.0f kgf/cm²，須以鑽心或回彈確認；不足時植筋容量與承壓需重算。" % (fc_wall * KGCM2_PER_MPA))
    if cracked:
        warnings.append("植筋握裹採開裂混凝土 τcr=%.1f kgf/cm²（表17.6.5.2.5 室外值）；若能證明使用載重下不開裂，得改 τuncr=%.1f。" % (tau_cr, tau_uncr))
    warnings.append("植筋拉力需求採抗掀名義比例 %.0f%% 輪載（非規範明文）；若監造另有規定，應改以該值重算。" % (uplift_factor * 100))
    warnings.append("未檢核既有溝壁側向穩定、基礎承載、疲勞（公路橋梁設計規範 7.3.9）、溫度與地震。")
    warnings.append("植筋膠須符合黏結式錨栓評估準則（ACI 355.4）並有產品測試資料；表17.6.5.2.5 僅為無產品資料時之下限。")
    warnings.append("溝壁頂面須打毛清潔、植筋孔吹塵乾燥；澆置前不得積水。")
    warnings.append("主筋兩端須伸入溝壁頂支承區至少 150 mm，端部作 90° 標準彎鉤；支承長度不足時須加大溝壁或增設托座。")
    if model == "partial_fixity":
        warnings.append("已採部分固接模型（fixity=%.2f）；20 cm 溝壁的固接可靠性有限，頂筋與植筋須確實錨定。" % fixity)
    if flex.get("governed_by") == "裂縫控制（主筋加密）":
        warnings.append(
            "主筋由裂縫控制加密為 %s@%g（強度僅需 %g mm²/m）：服務載重下 fs=%.0f MPa、w=%.3f mm。"
            % (flex["bar"], flex["spacing_mm"], flex.get("As_strength_mm2", 0.0),
               crack["fs_mpa"], crack["w_mm"])
        )
    if not crack["ok"]:
        warnings.append("裂縫寬度仍超過 0.30 mm；請加大版厚、提高 fc′ 或改雙層配筋，勿再放大主筋間距。")
    if main_bar_spec:
        warnings.append("主筋採使用者指定 %s@%g，程式未自動調整；下列檢核直接判定指定配置。" % (main_bar_spec, main_spacing_spec))
        if not flex.get("flexure_ok", True):
            warnings.append("指定主筋撓曲強度不足（φMn < Mu）；請加密間距、加大筋徑或加厚版。")
        if not flex.get("as_ok", True):
            warnings.append("指定主筋量低於最小鋼筋量 As,min。")
        if not flex.get("spacing_ok", True):
            warnings.append("指定主筋間距超出可施工範圍（db+25 mm ～ 3h／450 mm）。")
    if dist_bar_spec and not dist.get("ok", True):
        warnings.append("指定分佈筋量或間距不足（需求 %g mm²/m、上限 %g mm）。" % (as_dist_design, dist_s_max))
    if not edge_ok:
        warnings.append("植筋邊距不足 6db；請改用較小直徑、偏置鑽孔或加大溝壁斷面。")
    if not tension_ok:
        warnings.append("植筋拉力容量不足；優先將間距加密至 100 mm，或改用 D16／加大溝壁厚度。")
    if not shear_ok:
        warnings.append("植筋剪力容量不足；請加密間距或改以剪力榫傳遞水平力。")

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "geometry": {
            "clear_width_m": b_clear,
            "wall_thickness_m": t_wall,
            "total_width_m": round(b_clear + 2.0 * t_wall, 3),
            "slab_thickness_mm": h_mm,
            "cover_mm": cover_mm,
            "bearing_center_m": round(b_clear + t_wall, 3),
            "effective_span_m": round(s_eff, 3),
        },
        "materials": {
            "slab_fc_mpa": fc_slab,
            "slab_fc_kgf_cm2": round(fc_slab * KGCM2_PER_MPA, 0),
            "wall_fc_mpa": fc_wall,
            "wall_fc_kgf_cm2": round(fc_wall * KGCM2_PER_MPA, 0),
            "fy_mpa": fy,
        },
        "loads": {
            "vehicle": vehicle,
            "heavy_truck_factor": heavy,
            "P20_kgf": p20_kgf,
            "impact": round(impact, 4),
            "live_load_factor": live_factor,
            "dead_moment_kNm": round(m_d, 2),
            "live_moment_service_kNm": round(m_ll, 2),
            "design_moment_kNm": round(mu, 2),
            "design_shear_kN_m": round(vu_side, 2),
        },
        "slab": {
            "main": flex,
            "distribution": {
                "percent_of_main": round(pct, 1),
                "As_req_mm2": round(as_dist_req, 1),
                "As_temp_mm2": round(as_temp, 1),
                **dist,
            },
            "top": {
                "As_req_mm2": round(as_top_req, 1),
                **top,
            },
            "shear": {
                "phiVc_kN_m": round(phi_vc, 2),
                "Vu_kN_m": round(vu_side, 2),
                "ok": vc_ok,
            },
            "crack": crack,
            "deflection": defl,
        },
        "wall_bearing": {
            "q_kpa": round(q_bearing_kpa, 1),
            "q_allow_kpa": round(q_allow_kpa, 1),
            "ok": bearing_ok,
        },
        "anchors": {
            "bar": bar_name,
            "diameter_mm": da_mm,
            "spacing_mm": anchor_spacing,
            "embedment_mm": hef_mm,
            "hole_diameter_mm": round(da_mm + 4.0, 0),
            "edge_mm": round(ca_mm, 1),
            "per_meter": round(n_per_m, 2),
            "tau_used_kgf_cm2": tau_used,
            "cracked": cracked,
            "tension_demand_kN": round(t_per_bar, 2),
            "shear_demand_kN": round(v_per_bar, 2),
            "tension": tension,
            "shear": shear_cap,
            "interaction": round(interaction, 3),
            "friction": {
                "mu": mu_friction,
                "surface": surface,
                "phiVn_kN_m": round(friction_cap, 2),
                "demand_kN_m": round(vu_side, 2),
                "ok": friction_ok,
            },
        },
        "checks": checks,
        "warnings": warnings,
        "codes": [
            "公路橋梁設計規範（98.12 初版；104.04.13／109.01.03 修訂）§3.7.6、§4.3、§7.1.5、§9",
            "建築物混凝土結構設計規範（112.08.10）§17.6.5、§17.7、§17.9、§22.9",
            "公路工程施工規範（112.02.22）§01525 施工縫及植筋",
        ],
        "pass": all(c["ok"] for c in checks),
        "thickness_search": attempts,
        "design_notes": [
            "主筋垂直車行方向（橫向跨越溝寬）；分佈筋平行車行方向。",
            "分佈鋼筋量取主筋需求量的 %.1f%%（121/√S，上限 67%%），全跨同量配置。" % pct,
            "頂筋按溫度鋼筋 0.0018bh 配置%s。" % ("，另加部分固接負彎矩鋼筋" if fixity > 0 else ""),
            "植筋採 %s@%g，埋深 %g mm，孔徑 %g mm。" % (bar_name, anchor_spacing, hef_mm, round(da_mm + 4.0)),
            "垂直剪力由溝壁頂承壓傳遞；植筋只承擔上拔力與水平力，不以植筋傳遞垂直剪力。",
            "分佈筋全跨同量配置，較規範「跨中 1/2 全量、兩側 1/4 半量」保守。",
            (
                "主筋與分佈筋採使用者指定配置（主筋 %s@%g、分佈筋 %s@%g），"
                "程式僅檢核不代為調整。" % (main_bar_spec, main_spacing_spec, dist_bar_spec, dist_spacing_spec)
                if (main_bar_spec and dist_bar_spec) else
                "主筋採使用者指定配置 %s@%g，程式僅檢核不代為調整。" % (main_bar_spec, main_spacing_spec)
                if main_bar_spec else
                "分佈筋採使用者指定配置 %s@%g，程式僅檢核不代為調整。" % (dist_bar_spec, dist_spacing_spec)
                if dist_bar_spec else
                "配筋由程式依撓曲＋裂縫控制自動選配。"
            ),
        ],
    }
    return result


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return ("%%.%df" % digits) % value
    return str(value)


def format_report(result: Mapping[str, Any]) -> str:
    geo = result.get("geometry") or {}
    loads = result.get("loads") or {}
    slab = result.get("slab") or {}
    main = slab.get("main") or {}
    dist = slab.get("distribution") or {}
    top = slab.get("top") or {}
    anc = result.get("anchors") or {}
    bearing = result.get("wall_bearing") or {}
    lines: list[str] = []
    lines.append("RC 路側溝加蓋設計（溝蓋版＋植筋）")
    lines.append(
        "斷面：淨寬 %s m、溝壁 %s m、全寬 %s m、版厚 %s mm、有效跨徑 %s m"
        % (_fmt(geo.get("clear_width_m")), _fmt(geo.get("wall_thickness_m")),
           _fmt(geo.get("total_width_m")), _fmt(geo.get("slab_thickness_mm"), 0),
           _fmt(geo.get("effective_span_m"), 3))
    )
    lines.append(
        "載重：HS20 後輪 %s kgf、重車係數 %s、衝擊 %s%%、活載重因數 %s"
        % (_fmt(loads.get("P20_kgf"), 0), _fmt(loads.get("heavy_truck_factor")),
           _fmt((loads.get("impact") or 0) * 100, 1), _fmt(loads.get("live_load_factor")))
    )
    lines.append(
        "彎矩：靜載 %s、活載（服務）%s、設計 %s kN·m/m"
        % (_fmt(loads.get("dead_moment_kNm")), _fmt(loads.get("live_moment_service_kNm")),
           _fmt(loads.get("design_moment_kNm")))
    )
    lines.append(
        "主筋：%s@%s mm（As=%s mm²/m，φMn=%s ≥ Mu=%s kN·m/m）"
        % (main.get("bar"), _fmt(main.get("spacing_mm"), 0), _fmt(main.get("As_prov_mm2"), 0),
           _fmt(main.get("phiMn_kNm")), _fmt(main.get("Mu_kNm")))
    )
    lines.append(
        "分佈筋：%s@%s mm（需求量 %s%% 主筋，As=%s mm²/m）"
        % (dist.get("bar"), _fmt(dist.get("spacing_mm"), 0), _fmt(dist.get("percent_of_main"), 1),
           _fmt(dist.get("As_prov_mm2"), 0))
    )
    lines.append(
        "頂筋：%s@%s mm（As=%s mm²/m）"
        % (top.get("bar"), _fmt(top.get("spacing_mm"), 0), _fmt(top.get("As_prov_mm2"), 0))
    )
    lines.append(
        "植筋：%s@%s mm、埋深 %s mm、孔徑 %s mm、邊距 %s mm；每側 %s 根/m"
        % (anc.get("bar"), _fmt(anc.get("spacing_mm"), 0), _fmt(anc.get("embedment_mm"), 0),
           _fmt(anc.get("hole_diameter_mm"), 0), _fmt(anc.get("edge_mm"), 0),
           _fmt(anc.get("per_meter")))
    )
    lines.append(
        "植筋需求：拉力 %s kN/根、剪力 %s kN/根；容量 %s／%s kN；互制 %s"
        % (_fmt(anc.get("tension_demand_kN")), _fmt(anc.get("shear_demand_kN")),
           _fmt((anc.get("tension") or {}).get("capacity_kN")),
           _fmt((anc.get("shear") or {}).get("capacity_kN")), _fmt(anc.get("interaction")))
    )
    lines.append(
        "溝壁承壓：q=%s ≤ %s kPa" % (_fmt(bearing.get("q_kpa"), 1), _fmt(bearing.get("q_allow_kpa"), 1))
    )
    notes = result.get("design_notes") or []
    if notes:
        lines.append("設計說明：")
        for note in notes:
            lines.append("  - %s" % note)
    lines.append("檢核結果：")
    for check in result.get("checks") or []:
        tag = "OK" if check.get("ok") else "NG"
        lines.append(
            "  [%s] %s：%s（限 %s %s）"
            % (tag, check.get("item", ""), _fmt(check.get("value")),
               _fmt(check.get("limit")), check.get("unit", ""))
        )
    lines.append("整體判定：%s" % ("通過" if result.get("pass") else "未通過"))
    warnings = result.get("warnings") or []
    if warnings:
        lines.append("提醒：")
        for message in warnings:
            lines.append("  - %s" % message)
    return "\n".join(lines)


def example_payload() -> dict[str, Any]:
    """使用者的案例：淨寬 60 cm、溝壁 20 cm、溝蓋 fc′=280 kgf/cm²、重車。"""
    return {
        "geometry": {
            "clear_width_m": 0.60,
            "wall_thickness_m": 0.20,
            "slab_thickness_mm": 250.0,
            "cover_mm": 50.0,
        },
        "materials": {
            "slab_fc_mpa": 28.0,
            "wall_fc_mpa": 21.0,
            "fy_mpa": 420.0,
            "unit_weight_kn_m3": 24.0,
        },
        "loads": {
            "vehicle": "hs20_1_25",
            "live_load_factor": 1.67,
            "deck_beta_1_0": False,
            "wearing_surface_kpa": 0.0,
            "uplift_factor": 0.10,
            "horizontal_force_kN_m": 0.0,
        },
        "slab": {
            "main_bar": "",
            "main_spacing_mm": 0.0,
            "dist_bar": "",
            "dist_spacing_mm": 0.0,
        },
        "connection": {
            "model": "simple",
            "fixity_ratio": 0.50,
            "bar": "D16",
            "spacing_mm": 150.0,
            "embedment_mm": 200.0,
            "cracked": True,
            "tau_cr_kgf_cm2": 14.0,
            "tau_uncr_kgf_cm2": 45.0,
            "surface_condition": "roughened",
        },
    }


def selftest() -> int:
    from _selftest_util import Checker

    c = Checker("RC 路側溝加蓋")
    payload = example_payload()
    r = analyse(payload)
    geo = r["geometry"]
    loads = r["loads"]
    main = r["slab"]["main"]
    dist = r["slab"]["distribution"]
    anc = r["anchors"]

    s = 0.60 + 0.20
    c.close("有效跨徑 S＝淨寬＋壁厚", geo["effective_span_m"], s, tol=1e-9)
    impact = min(15.24 / (s + 38.1), 0.30)
    c.close("衝擊係數 I＝15.24/(S+38.1) 上限 30%", loads["impact"], impact, tol=1e-9)
    m_ll = 7300 * KN_PER_KGF * 1.25 * (s + 6.0) / 6.9 * (1.0 + impact)
    c.close("活載彎矩 M＝P·1.25·(S+6.0)/6.9·(1+I)", loads["live_moment_service_kNm"], m_ll, tol=1e-3)
    m_d = 24.0 * geo["slab_thickness_mm"] / 1000.0 * s ** 2 / 8.0
    c.close("靜載彎矩 wS²/8", loads["dead_moment_kNm"], m_d, tol=1e-3)
    mu = 1.25 * m_d + 1.67 * m_ll
    c.close("設計彎矩 1.25D＋1.67L", loads["design_moment_kNm"], mu, tol=1e-3)
    c.true("主筋撓曲通過", main["ok"], "φMn=%.2f" % main["phiMn_kNm"])
    c.close("分佈筋百分比 min(121/√S,67)", dist["percent_of_main"], min(121.0 / math.sqrt(s), 67.0), tol=1e-9)
    c.true("分佈筋量 ≥ 主筋需求×百分比", dist["As_prov_mm2"] >= dist["As_req_mm2"])
    c.true("溝壁承壓通過", r["wall_bearing"]["ok"])
    c.true("植筋邊距 ≥6db", anc["edge_mm"] >= 6.0 * anc["diameter_mm"])
    c.true("植筋間距 ≥6db", anc["spacing_mm"] >= 6.0 * anc["diameter_mm"])
    c.true("植筋拉力容量通過", anc["tension_demand_kN"] <= anc["tension"]["capacity_kN"])
    c.true("植筋剪力容量通過", anc["shear_demand_kN"] <= anc["shear"]["capacity_kN"])
    c.true("拉剪互制 ≤1.2", anc["interaction"] <= 1.2)
    c.true("界面剪力摩擦通過", anc["friction"]["ok"])
    c.close("植筋握裹 Nba＝τ·π·da·hef", anc["tension"]["Nba_kgf"],
            anc["tau_used_kgf_cm2"] * math.pi * (anc["diameter_mm"] / 10.0) * (anc["embedment_mm"] / 10.0), tol=1e-4)
    c.close("承壓 q＝Vu/(t×1m)", r["wall_bearing"]["q_kpa"],
            loads["design_shear_kN_m"] / 0.20, tol=1e-4)
    # 指定配筋檢核模式（淨寬 0.40 m、HS20 單輪）
    p2 = example_payload()
    p2["geometry"]["clear_width_m"] = 0.40
    p2["loads"]["vehicle"] = "hs20"
    p2["loads"]["live_load_factor"] = 1.0
    p2["slab"] = {"main_bar": "D16", "main_spacing_mm": 150.0}
    r2 = analyse(p2)
    c.true("指定 D16@150 裂縫 NG 如實回報（不自動改筋）",
           (not r2["slab"]["crack"]["ok"]) and (not r2["pass"]))
    p2["slab"]["main_spacing_mm"] = 125.0
    r3 = analyse(p2)
    c.true("指定 D16@125 裂縫通過", r3["slab"]["crack"]["ok"])
    c.close("指定主筋 As＝199000/125", r3["slab"]["main"]["As_prov_mm2"],
            199000.0 / 125.0, tol=0.1)
    c.true("整體判定通過", r["pass"])
    return c.run()


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import json

    print(json.dumps(analyse(example_payload()), ensure_ascii=False, indent=2))
