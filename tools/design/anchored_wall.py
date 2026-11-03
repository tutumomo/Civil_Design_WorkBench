"""錨定擋土牆（地錨背拉 RC 牆面）設計（水土保持技術規範 §118 八、§119～120；公路邊坡工程設計規範第六章）。

適用情境
--------
§118 八：錨定擋土牆適用於岩層破碎帶、節理發達或崩塌、地滑地區；條文未訂高度上限，
但地錨本身須依《公路邊坡工程設計規範》第六章（104.12）設計：
- 表 C6.4-1 單一地錨最小安全係數：臨時性 抗張材 1.6／地層-漿體 2.0／抗張材-漿體 2.0；
  長久性 2.0／3.0／3.0（使用 2 年以上屬長久性）。
- C6.7：自由段須穿過可能滑動面，原則 ≥ 4 m；摩擦型錨碇段 ≥ 3 m，一般 3～10 m，
  超過臨界長度後錨碇力不再成比例增加。
- C6.9：工作荷重下混凝土基座壓應力 < 0.30 fc'。
- C6.10：容許荷重＝min（抗張材極限／FS、錨碇段極限／FS）；設計荷重不得大於容許荷重。
- C6.11：鎖定荷重通常較設計荷重高 10～20%。

幾何（z 由牆頂往下，單位 m）
----------------------------
    height_m                 牆高 H（土壓作用高度，牆頂至基底）
    wall_thickness_m         牆面厚 t
    base_width_m             基腳寬 B（預設＝t）
    base_thickness_m         基腳厚（自重用）
    front_soil_depth_m       牆前覆土深；有效高＝H－覆土深（§118 末段：露出地面之高度）
    anchor_depths_m          各排地錨距牆頂深度 [z1, z2, …]
    horizontal_spacing_m     地錨水平間距 sh
    inclination_deg          地錨俯角 α（與水平夾角）

力學假設
--------
- 土壓：預設採 FHWA GEC-4 視土壓包絡（總力 0.65·Ka·γ·H²、梯形分佈）；
  亦可選三角形 Rankine 分佈（剛性牆面、岩盤）。上載＝Ka·q 均佈。
- 地震：M-O 增量 ΔKAE·γ·H²/2 以均佈作用（FHWA GEC-4 對背拉牆的建議），
  另加牆面慣性力 kh·γc·t。
- 牆面：鉛直向視為以各排地錨及基底為支點的連續梁（每公尺寬），
  以勁度法求支點反力，再由靜力積分得彎矩與剪力；水平向以地錨為支點，
  M＝p·sh²/10（連續版近似）。
- 地錨設計荷重 T＝R·sh / cosα；常時與地震取大者，地震工況沿用相同安全係數（保守）。
- 基底：水平反力由基底摩擦（＋選用牆前被動土壓）抵抗；地錨鉛直分力 R·tanα 計入正壓力。
- 載重組合沿用本工作區 rc_design 的 100 年版慣例：常時 U＝1.7H；地震 U＝0.75（1.7H＋1.87E）。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import earth_pressure as EP  # noqa: E402
import rc_design as RC  # noqa: E402
from retaining_wall import LIMITS  # noqa: E402


class AnchoredWallError(ValueError):
    """Invalid anchored wall input."""


SPEC = {
    "label": "錨定擋土牆",
    "max_effective_height_m": None,
    "basis": "水土保持技術規範 §118 八：適用於岩層破碎帶、節理發達或崩塌、地滑地區（未訂高度上限）",
}
ANCHOR_CODE = "公路邊坡工程設計規範（104.12）第六章"

# 表 C6.4-1 單一地錨最小安全係數
ANCHOR_FS = {
    "temporary": {"label": "臨時性地錨（使用 2 年以內）", "tendon": 1.6, "ground_grout": 2.0, "tendon_grout": 2.0},
    "permanent": {"label": "長久性地錨（使用 2 年以上）", "tendon": 2.0, "ground_grout": 3.0, "tendon_grout": 3.0},
}

# 七線鋼絞線（CNS 3332 SWPR7B）：直徑 mm、斷面積 mm²、最小破斷荷重 kN
STRANDS = {
    "12.7": {"label": "12.7 mm（0.5\"）七線鋼絞線", "d_mm": 12.7, "area_mm2": 98.71, "Pu_kN": 183.0},
    "15.2": {"label": "15.2 mm（0.6\"）七線鋼絞線", "d_mm": 15.2, "area_mm2": 138.7, "Pu_kN": 261.0},
}

# 地層-漿體極限握裹（kPa）參考值：取自 FHWA GEC-4 表列範圍的偏低代表值，
# 公路邊坡 C6.4／C6.10 要求以證明試驗確認，正式設計不可直接採用。
BOND_PRESETS = [
    {"value": 100, "label": "堅硬黏土（約 100 kPa）"},
    {"value": 150, "label": "中等緊密砂（約 150 kPa）"},
    {"value": 250, "label": "緊密砂礫（約 250 kPa）"},
    {"value": 400, "label": "軟岩：泥岩、頁岩（約 400 kPa）"},
    {"value": 700, "label": "風化砂岩、破碎岩（約 700 kPa）"},
    {"value": 1000, "label": "較新鮮砂岩、石灰岩（約 1000 kPa）"},
]

GAMMA_CONC = 24.0
LOAD_STATIC = 1.7
LOAD_SEISMIC_H = 0.75 * 1.7
LOAD_SEISMIC_E = 0.75 * 1.87
MIN_FREE_LENGTH_M = 4.0        # C6.7
MIN_BOND_LENGTH_M = 3.0        # C6.4／C6.7
MAX_BOND_LENGTH_M = 10.0       # C6.7 一般上限（臨界長度）
PLATE_BEARING_RATIO = 0.30     # C6.9
LOCKOFF_MAX_RATIO = 0.70       # FHWA GEC-4 慣例：鎖定荷重 ≤ 0.70 Pu
TOL = 1e-9


def _f(data: Mapping[str, Any], key: str, default: float | None = None, *, minimum: float | None = None,
       positive: bool = False) -> float:
    value = data.get(key, default)
    if value is None or value == "":
        if default is None:
            raise AnchoredWallError("缺少必要欄位：%s" % key)
        value = default
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise AnchoredWallError("%s 必須為數字" % key) from exc
    if not math.isfinite(value):
        raise AnchoredWallError("%s 必須為有限數字" % key)
    if positive and value <= 0:
        raise AnchoredWallError("%s 必須大於 0" % key)
    if minimum is not None and value < minimum:
        raise AnchoredWallError("%s 不可小於 %s" % (key, minimum))
    return value


# --------------------------------------------------------------------------
# 連續梁（鉛直向牆面）：勁度法求支點反力，再以靜力積分求 M、V
# --------------------------------------------------------------------------

def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            raise AnchoredWallError("牆面支承不足（至少需一排地錨加基底）")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def beam_reactions(H: float, supports: Sequence[float], pressure, breakpoints: Sequence[float] = ()) -> list[float]:
    """鉛直連續梁（z 向下、牆頂自由），pressure(z) 為每公尺寬側壓 kPa，回傳各支點水平反力 kN/m。

    節點取支點、端點與壓力折點，元素內壓力為線性，等值節點力為精確解；EI 為常數，不影響反力。
    """

    nodes = sorted({0.0, H, *supports, *[b for b in breakpoints if 0.0 < b < H]})
    nn = len(nodes)
    K = [[0.0] * (2 * nn) for _ in range(2 * nn)]
    F = [0.0] * (2 * nn)
    for e in range(nn - 1):
        z1, z2 = nodes[e], nodes[e + 1]
        L = z2 - z1
        w1, w2 = pressure(z1 + 1e-12), pressure(z2 - 1e-12)
        k = [[12 / L ** 3, 6 / L ** 2, -12 / L ** 3, 6 / L ** 2],
             [6 / L ** 2, 4 / L, -6 / L ** 2, 2 / L],
             [-12 / L ** 3, -6 / L ** 2, 12 / L ** 3, -6 / L ** 2],
             [6 / L ** 2, 2 / L, -6 / L ** 2, 4 / L]]
        fe = [L * (7 * w1 + 3 * w2) / 20.0, L * L * (3 * w1 + 2 * w2) / 60.0,
              L * (3 * w1 + 7 * w2) / 20.0, -L * L * (2 * w1 + 3 * w2) / 60.0]
        dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        for i in range(4):
            F[dofs[i]] += fe[i]
            for j in range(4):
                K[dofs[i]][dofs[j]] += k[i][j]
    fixed = {2 * nodes.index(s) for s in supports}
    free = [i for i in range(2 * nn) if i not in fixed]
    d_free = _solve([[K[i][j] for j in free] for i in free], [F[i] for i in free])
    d = [0.0] * (2 * nn)
    for i, v in zip(free, d_free):
        d[i] = v
    # 反力（以抵抗外力方向為正）＝ F − K·d 於受束自由度
    out = []
    for s in supports:
        i = 2 * nodes.index(s)
        out.append(F[i] - sum(K[i][j] * d[j] for j in range(2 * nn)))
    return out


def _integrate(pressure, z0: float, z1: float, n: int = 400) -> tuple[float, float]:
    """∫p dz 與 ∫p·z dz（Simpson）。"""
    if z1 <= z0:
        return 0.0, 0.0
    n += n % 2
    h = (z1 - z0) / n
    s0 = s1 = 0.0
    for i in range(n + 1):
        z = z0 + i * h
        w = 1 if i in (0, n) else (4 if i % 2 else 2)
        p = pressure(z)
        s0 += w * p
        s1 += w * p * z
    return s0 * h / 3.0, s1 * h / 3.0


def moment_shear(H: float, supports: Sequence[float], reactions: Sequence[float], pressure,
                 step: float = 0.01) -> list[tuple[float, float, float]]:
    """由牆頂往下取自由體：M>0 表示背面（土側）受拉、M<0 表示正面受拉。回傳 [(z, M, V)]。"""

    pts = sorted({round(i * step, 6) for i in range(int(H / step) + 1)} | {H, *supports})
    out = []
    for z in pts:
        P, Pz = _integrate(pressure, 0.0, z, 200)
        M = z * P - Pz
        V = P
        for zs, R in zip(supports, reactions):
            if zs < z - TOL:
                M -= R * (z - zs)
                V -= R
        out.append((z, M, V))
    return out


# --------------------------------------------------------------------------
# 土壓分佈
# --------------------------------------------------------------------------

def _pressures(g, soil, kh):
    gamma = float(soil["gamma"])
    phi = float(soil["phi_deg"])
    beta = float(soil.get("backfill_slope_deg") or 0.0)
    qs = float(soil.get("surcharge_kpa") or 0.0)
    H = g["H"]
    try:
        ka = EP.coulomb_active_coefficient(phi, wall_friction_deg=beta, backfill_slope_deg=beta)
        kae = (EP.coulomb_active_coefficient(phi, wall_friction_deg=beta, backfill_slope_deg=beta, kh=kh)
               if kh > 0 else ka)
    except EP.EarthPressureError as exc:
        raise AnchoredWallError("土壓力無解：%s" % exc) from exc
    cb = math.cos(math.radians(beta))
    ka_h, kae_h = ka * cb, kae * cb
    z1, zn = g["anchors"][0]["depth_m"], g["anchors"][-1]["depth_m"]
    h1, hn1 = z1, H - zn
    breaks: list[float] = []
    if g["distribution"] == "apparent":
        P_tot = 0.65 * ka_h * gamma * H * H
        p_max = P_tot / (H - h1 / 3.0 - hn1 / 3.0)
        za, zb = 2.0 * h1 / 3.0, H - 2.0 * hn1 / 3.0
        breaks = [za, zb]

        def p_earth(z):
            if z < za:
                return p_max * z / za if za > 0 else p_max
            if z > zb:
                return p_max * (H - z) / (H - zb) if H > zb else p_max
            return p_max
    else:
        P_tot = 0.5 * ka_h * gamma * H * H
        p_max = ka_h * gamma * H

        def p_earth(z):
            return ka_h * gamma * z
    p_q = ka_h * qs
    dP = 0.5 * (kae_h - ka_h) * gamma * H * H if kh > 0 else 0.0
    p_eq = dP / H + kh * GAMMA_CONC * g["t"] if kh > 0 else 0.0

    def p_static(z):
        return p_earth(z) + p_q

    def p_seis(z):
        return p_eq

    return {
        "Ka": ka, "Ka_h": ka_h, "KAE": kae, "KAE_h": kae_h,
        "P_earth_kN_per_m": P_tot, "p_max_kPa": p_max, "p_surcharge_kPa": p_q,
        "dPae_kN_per_m": dP, "p_seismic_kPa": p_eq, "breakpoints": breaks,
        "static": p_static, "seismic": p_seis,
    }


# --------------------------------------------------------------------------
# 輸入整理
# --------------------------------------------------------------------------

def geometry(q: Mapping[str, Any]) -> dict[str, Any]:
    H = _f(q, "height_m", positive=True)
    t = _f(q, "wall_thickness_m", positive=True)
    B = _f(q, "base_width_m", t, positive=True)
    tb = _f(q, "base_thickness_m", 0.0, minimum=0.0)
    ds = _f(q, "front_soil_depth_m", 0.0, minimum=0.0)
    sh = _f(q, "horizontal_spacing_m", positive=True)
    alpha = _f(q, "inclination_deg", 20.0, minimum=0.0)
    if alpha >= 60:
        raise AnchoredWallError("地錨俯角須小於 60°")
    if B < t - TOL:
        raise AnchoredWallError("基腳寬不可小於牆面厚")
    if tb >= H:
        raise AnchoredWallError("基腳厚必須小於牆高")
    if ds >= H:
        raise AnchoredWallError("牆前覆土深必須小於牆高")
    distribution = str(q.get("pressure_distribution") or "apparent")
    if distribution not in ("apparent", "triangular"):
        raise AnchoredWallError("pressure_distribution 須為 apparent（視土壓包絡）或 triangular（三角形）")
    service = str(q.get("service") or "permanent")
    if service not in ANCHOR_FS:
        raise AnchoredWallError("service 須為 permanent（長久性）或 temporary（臨時性）")
    strand = str(q.get("strand_type") or "12.7")
    if strand not in STRANDS:
        raise AnchoredWallError("strand_type 須為 12.7 或 15.2")

    defaults = {
        "strands": _f(q, "strands", 4, positive=True),
        "free_length_m": _f(q, "free_length_m", 6.0, positive=True),
        "bond_length_m": _f(q, "bond_length_m", 6.0, positive=True),
        "drill_diameter_mm": _f(q, "drill_diameter_mm", 135.0, positive=True),
    }
    rows = q.get("anchors")
    if not rows:
        depths = q.get("anchor_depths_m")
        if isinstance(depths, (int, float)):
            depths = [depths]
        if not depths:
            raise AnchoredWallError("請提供 anchor_depths_m（各排地錨距牆頂深度）")
        rows = [{"depth_m": z} for z in depths]
    anchors = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise AnchoredWallError("anchors 第 %d 筆必須是物件" % i)
        a = {"row": i, "depth_m": _f(row, "depth_m", positive=True)}
        for k, v in defaults.items():
            a[k] = _f(row, k, v, positive=True)
        a["strands"] = int(round(a["strands"]))
        anchors.append(a)
    anchors.sort(key=lambda a: a["depth_m"])
    for i, a in enumerate(anchors, 1):
        a["row"] = i
        if a["depth_m"] >= H - 0.3:
            raise AnchoredWallError("第 %d 排地錨深度 %.2f m 太接近或超過牆底（須 < H－0.3 m）" % (i, a["depth_m"]))
    for a, b in zip(anchors, anchors[1:]):
        if b["depth_m"] - a["depth_m"] < 0.5:
            raise AnchoredWallError("地錨排距 %.2f m 過小（< 0.5 m）" % (b["depth_m"] - a["depth_m"]))
    return {"H": H, "t": t, "B": B, "tb": tb, "ds": ds, "eff": H - ds, "sh": sh, "alpha": alpha,
            "distribution": distribution, "service": service, "strand": strand, "anchors": anchors}


def _free_length_required(g, phi_deg, z):
    """自由段須穿過 Rankine 主動破壞面（自牆底以 45°+φ/2 上揚）再加 max(1.5 m, 0.2H)，且 ≥ 4 m。"""
    theta = math.radians(45.0 + phi_deg / 2.0)
    a = math.radians(g["alpha"])
    s_plane = (g["H"] - z) / (math.cos(a) * math.tan(theta) + math.sin(a))
    return s_plane, max(MIN_FREE_LENGTH_M, s_plane + max(1.5, 0.2 * g["H"]))


# --------------------------------------------------------------------------
# 主分析
# --------------------------------------------------------------------------

def analyse(q: Mapping[str, Any], soil: Mapping[str, Any] | None = None,
            seismic: Mapping[str, Any] | None = None,
            concrete: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """錨定擋土牆：土壓分佈、牆面連續梁、地錨抗張／握裹／自由段、基座、基底滑動承載、牆面配筋。"""

    g = geometry(q)
    soil = dict({
        "gamma": 18.0, "phi_deg": 30.0, "backfill_slope_deg": 0.0, "surcharge_kpa": 0.0,
        "allowable_bearing_kpa": 300.0, "base_friction": 0.5, "bond_strength_kpa": 400.0,
        "tendon_bond_mpa": 2.0, "include_passive": False,
    }, **(soil or {}))
    kh = float((seismic or {}).get("kh") or 0.0)
    if kh < 0:
        raise AnchoredWallError("kh 不可為負")
    cc = dict(RC.CONCRETE, **(concrete or {}))
    plate = _f(q, "bearing_plate_m", 0.30, positive=True)
    lock_factor = _f(q, "lockoff_factor", 1.15, positive=True)
    tau_g = _f(soil, "bond_strength_kpa", positive=True)
    tau_tg = _f(soil, "tendon_bond_mpa", positive=True)
    phi = float(soil["phi_deg"])

    pr = _pressures(g, soil, kh)
    H = g["H"]
    supports = [a["depth_m"] for a in g["anchors"]] + [H]
    R_s = beam_reactions(H, supports, pr["static"], pr["breakpoints"])
    R_e = beam_reactions(H, supports, pr["seismic"], pr["breakpoints"]) if kh > 0 else [0.0] * len(supports)
    ms_s = moment_shear(H, supports, R_s, pr["static"])
    ms_e = moment_shear(H, supports, R_e, pr["seismic"]) if kh > 0 else [(z, 0.0, 0.0) for z, _, _ in ms_s]

    fs = ANCHOR_FS[g["service"]]
    sd = STRANDS[g["strand"]]
    ca, ta = math.cos(math.radians(g["alpha"])), math.tan(math.radians(g["alpha"]))
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    anchors_out = []
    fc = cc["fc_mpa"]
    d_wall = g["t"] * 1000.0 - cc["cover_mm"] - 10.0
    for a, rs, re_ in zip(g["anchors"], R_s, R_e):
        if rs <= 0:
            warnings.append("第 %d 排地錨反力 %.1f kN/m ≤ 0（不受拉），請調整排距或刪除此排。" % (a["row"], rs))
        T_s = max(rs, 0.0) * g["sh"] / ca
        T_e = max(rs + re_, 0.0) * g["sh"] / ca
        T = max(T_s, T_e)
        Pu = a["strands"] * sd["Pu_kN"]
        T_allow_tendon = Pu / fs["tendon"]
        D = a["drill_diameter_mm"] / 1000.0
        T_ult_ground = math.pi * D * a["bond_length_m"] * tau_g
        T_ult_tg = a["strands"] * math.pi * sd["d_mm"] / 1000.0 * a["bond_length_m"] * tau_tg * 1000.0
        T_allow = min(T_allow_tendon, T_ult_ground / fs["ground_grout"], T_ult_tg / fs["tendon_grout"])
        Lb_ground = T * fs["ground_grout"] / (math.pi * D * tau_g)
        Lb_tg = T * fs["tendon_grout"] / (a["strands"] * math.pi * sd["d_mm"] / 1000.0 * tau_tg * 1000.0)
        Lb_req = max(MIN_BOND_LENGTH_M, Lb_ground, Lb_tg)
        n_req = max(1, math.ceil(T * fs["tendon"] / sd["Pu_kN"] - 1e-9))
        s_plane, Lf_req = _free_length_required(g, phi, a["depth_m"])
        lock = T * lock_factor
        sigma_plate = T / (plate * plate) / 1000.0                     # MPa
        # 錨頭沖剪（雙向剪力，臨界周長距承壓鈑 d/2）
        Vu_p = max(LOAD_STATIC * T_s, LOAD_SEISMIC_H * T_s + LOAD_SEISMIC_E * (T_e - T_s))
        bo = 4.0 * (plate * 1000.0 + d_wall)
        phiVc_p = cc["phi_shear"] * 0.33 * math.sqrt(fc) * bo * d_wall / 1000.0
        L_total = a["free_length_m"] + a["bond_length_m"]
        row = dict(a, R_static_kN_per_m=round(rs, 3), R_seismic_kN_per_m=round(rs + re_, 3),
                   T_static_kN=round(T_s, 2), T_seismic_kN=round(T_e, 2), T_design_kN=round(T, 2),
                   Pu_kN=round(Pu, 1), T_allow_tendon_kN=round(T_allow_tendon, 2),
                   T_ult_ground_kN=round(T_ult_ground, 2), T_ult_tendon_grout_kN=round(T_ult_tg, 2),
                   T_allow_kN=round(T_allow, 2), strands_required=n_req,
                   bond_length_required_m=round(Lb_req, 2), bond_by_ground_m=round(Lb_ground, 2),
                   bond_by_tendon_grout_m=round(Lb_tg, 2), failure_plane_distance_m=round(s_plane, 2),
                   free_length_required_m=round(Lf_req, 2), lockoff_kN=round(lock, 2),
                   plate_stress_mpa=round(sigma_plate, 3), punching_Vu_kN=round(Vu_p, 2),
                   punching_phiVc_kN=round(phiVc_p, 2), total_length_m=round(L_total, 2),
                   horizontal_reach_m=round(L_total * ca, 2))
        anchors_out.append(row)
        tag = "第 %d 排地錨（z=%.2f m）" % (a["row"], a["depth_m"])
        checks += [
            {"item": "%s 抗張材 T ≤ Pu/%.1f（%d-%s mm）" % (tag, fs["tendon"], a["strands"], g["strand"]),
             "value": T, "limit": T_allow_tendon, "ok": T <= T_allow_tendon + TOL, "unit": "kN", "relation": "le"},
            {"item": "%s 錨碇段長（地層-漿體 FS %.1f、抗張材-漿體 FS %.1f、≥ %.0f m）"
                     % (tag, fs["ground_grout"], fs["tendon_grout"], MIN_BOND_LENGTH_M),
             "value": a["bond_length_m"], "limit": Lb_req, "ok": a["bond_length_m"] >= Lb_req - TOL,
             "unit": "m", "relation": "ge"},
            {"item": "%s 自由段長（穿過破壞面＋max(1.5 m, 0.2H)，且 ≥ 4 m）" % tag,
             "value": a["free_length_m"], "limit": Lf_req, "ok": a["free_length_m"] >= Lf_req - TOL,
             "unit": "m", "relation": "ge"},
            {"item": "%s 鎖定荷重 ≤ 0.70 Pu（FHWA GEC-4 慣例）" % tag,
             "value": lock, "limit": LOCKOFF_MAX_RATIO * Pu, "ok": lock <= LOCKOFF_MAX_RATIO * Pu + TOL,
             "unit": "kN", "relation": "le"},
            {"item": "%s 承壓鈑下混凝土壓應力 ≤ 0.30 fc'" % tag,
             "value": sigma_plate, "limit": PLATE_BEARING_RATIO * fc,
             "ok": sigma_plate <= PLATE_BEARING_RATIO * fc + TOL, "unit": "MPa", "relation": "le"},
            {"item": "%s 錨頭處牆面沖剪" % tag, "value": Vu_p, "limit": phiVc_p,
             "ok": Vu_p <= phiVc_p + TOL, "unit": "kN", "relation": "le"},
        ]
        if a["bond_length_m"] > MAX_BOND_LENGTH_M:
            warnings.append("%s 錨碇段 %.1f m 超過一般上限 10 m，錨碇力不會再成比例增加（C6.7），"
                            "宜增加地錨數量或改擴座式。" % (tag, a["bond_length_m"]))
        if T < 0.25 * Pu and T > 0:
            warnings.append("%s 設計荷重僅 %.0f%% Pu，鋼絞線可減為 %d 股。" % (tag, 100 * T / Pu, n_req))

    # 基底：水平反力、正壓力、滑動與承載
    Rb_s = R_s[-1]
    Rb_e = R_s[-1] + R_e[-1]
    W = GAMMA_CONC * (g["t"] * (H - g["tb"]) + g["B"] * g["tb"])
    N_s = W + sum(max(r, 0.0) for r in R_s[:-1]) * ta
    N_e = W + sum(max(r + e, 0.0) for r, e in zip(R_s[:-1], R_e[:-1])) * ta
    # 預設只取一半被動抵抗（位移相容）
    passive = EP.toe_passive_resistance(
        depth_m=g["ds"], gamma_kn_m3=float(soil["gamma"]), phi_deg=phi,
        **EP.passive_options(q, soil, default_include=False, default_ratio=0.5))
    Pp = passive["Pp_kN_per_m"]
    mu = float(soil["base_friction"])
    base = []
    for case, Rb, N, lim_key in (("常時", Rb_s, N_s, "sliding_static"), ("地震", Rb_e, N_e, "sliding_seismic")):
        if case == "地震" and kh <= 0:
            continue
        FS = (mu * N + Pp) / Rb if Rb > TOL else float("inf")
        q_b = N / g["B"]
        base.append({"case": case, "R_base_kN_per_m": round(Rb, 3), "N_kN_per_m": round(N, 3),
                     "passive_kN_per_m": round(Pp, 3), "FS_sliding": FS, "q_kPa": round(q_b, 2)})
        checks.append({"item": "基底滑動（%s）" % case, "value": FS, "limit": LIMITS[lim_key],
                       "ok": FS >= LIMITS[lim_key], "unit": "FS", "relation": "ge"})
        checks.append({"item": "基底承載（%s，均佈）" % case, "value": q_b,
                       "limit": float(soil["allowable_bearing_kpa"]),
                       "ok": q_b <= float(soil["allowable_bearing_kpa"]), "unit": "kPa", "relation": "le"})

    # 牆面配筋
    def _fac(ms, me):
        return max(LOAD_STATIC * ms, LOAD_SEISMIC_H * ms + LOAD_SEISMIC_E * me) if kh > 0 else LOAD_STATIC * ms

    Mu_back = max(0.0, max(_fac(m1, m2) for (_, m1, _), (_, m2, _) in zip(ms_s, ms_e)))
    Mu_front = max(0.0, max(_fac(-m1, -m2) for (_, m1, _), (_, m2, _) in zip(ms_s, ms_e)))
    def _fac_v(v1, v2):
        if kh <= 0:
            return LOAD_STATIC * abs(v1)
        return max(LOAD_STATIC * abs(v1), abs(LOAD_SEISMIC_H * v1 + LOAD_SEISMIC_E * v2))

    Vu = max(_fac_v(v1, v2) for (_, _, v1), (_, _, v2) in zip(ms_s, ms_e))
    p_u = max(_fac(pr["static"](z), pr["seismic"](z)) for z, _, _ in ms_s)
    Mh = p_u * g["sh"] ** 2 / 10.0
    h_mm = g["t"] * 1000.0
    members = []
    for name, Mu in (("牆面鉛直筋（背面，地錨處）", Mu_back), ("牆面鉛直筋（正面，跨中）", Mu_front),
                     ("牆面水平筋（背面，地錨處）", Mh), ("牆面水平筋（正面，跨中）", Mh)):
        fl = RC.flexure_design(Mu, b_mm=1000.0, h_mm=h_mm, cc=cc)
        members.append({"member": name, "Mu_kNm_per_m": round(Mu, 3), "flexure": fl})
        checks.append({"item": "%s 撓曲" % name, "value": Mu, "limit": fl.get("phiMn_kNm"),
                       "ok": bool(fl.get("ok")), "unit": "kN·m/m", "relation": "le"})
    shr = RC.shear_check(Vu, b_mm=1000.0, h_mm=h_mm, cc=cc)
    checks.append({"item": "牆面剪力（鉛直向，取支點最大值）", "value": Vu, "limit": shr["phiVc_kN"],
                   "ok": bool(shr["ok"]), "unit": "kN/m", "relation": "le"})

    warnings += [
        "整體穩定（含牆、地層與地錨的深層滑動）未在本計算器內檢核，須依公路邊坡 6.12 另以邊坡穩定分析確認；"
        "自由段只檢查是否穿過 Rankine 主動破壞面。",
        "地層-漿體握裹強度為設計假設值，須以證明試驗確認（公路邊坡 C6.4、C6.7）；施工時每支地錨應做驗收試驗。",
        "牆面鉛直向視為以各排地錨為支點的連續梁，水平向取 p·sh²/10，非雙向版精算；"
        "若採格梁或獨立錨座，須另行設計。",
        "黏著力、地下水壓未計；黏土層不適用砂土視土壓包絡，須改用 Terzaghi-Peck 黏土包絡。",
        "載重組合採 100 年版慣例 1.7H 與 0.75(1.7H＋1.87E)；地震時地錨沿用常時安全係數（保守）。",
    ]
    if g["distribution"] == "apparent" and float(soil.get("backfill_slope_deg") or 0) > 0:
        warnings.append("背填有坡度時視土壓包絡僅為近似，坡度大時建議改用三角形分佈或楔形分析。")
    if g["sh"] < 1.5:
        warnings.append("地錨水平間距 %.2f m < 1.5 m，須檢討群錨效應（公路邊坡 6.6）。" % g["sh"])
    if g["alpha"] < 10 or g["alpha"] > 45:
        warnings.append("地錨俯角 %.0f° 不在常用 10～45° 範圍，灌漿與施工性須確認。" % g["alpha"])
    max_reach = max(a["horizontal_reach_m"] for a in anchors_out)
    warnings.append("地錨最大水平伸入 %.1f m，請確認在用地／地權範圍內（公路邊坡 C6.3）。" % max_reach)
    warnings += EP.passive_warnings(passive, kh > 0)

    out = {
        "wall_type": "anchored",
        "wall_label": SPEC["label"],
        "geometry": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in g.items() if k != "anchors"},
        "applicability": {"basis": SPEC["basis"],
                          "notes": ["有效高（露出地面）%.2f m；§118 八未訂上限，地錨依%s設計" % (g["eff"], ANCHOR_CODE)]},
        "soil": soil,
        "seismic": {"kh": kh},
        "concrete": {k: cc[k] for k in ("fc_mpa", "fy_mpa", "cover_mm")},
        "anchor_fs": dict(fs),
        "strand": dict(sd, type=g["strand"]),
        "pressure": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in pr.items()
                     if k not in ("static", "seismic")},
        "anchors": anchors_out,
        "base": base,
        "passive": passive,
        "wall": {"members": members, "shear": shr, "Vu_kN_per_m": round(Vu, 3),
                 "p_u_max_kPa": round(p_u, 3),
                 "moment_static": [{"z_m": round(z, 3), "M_kNm_per_m": round(m, 3), "V_kN_per_m": round(v, 3)}
                                   for z, m, v in ms_s[::10] + [ms_s[-1]]]},
        "concrete_m3_per_m": round(g["t"] * (H - g["tb"]) + g["B"] * g["tb"], 4),
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in checks),
    }
    out["reinforcement"] = RC.design_anchored_wall_steel(q, out, cc=cc)
    out["rebar_kg_per_m"] = out["reinforcement"]["total_kg_per_m"]
    return out


def format_report(res: Mapping[str, Any]) -> str:
    g = res["geometry"]
    pr = res["pressure"]
    fs = res["anchor_fs"]
    lines = [
        "%s：牆高 %.2f m、有效高 %.2f m、牆面厚 %.2f m、基腳 %.2f×%.2f m；混凝土 %.3f m³/m"
        % (res["wall_label"], g["H"], g["eff"], g["t"], g["B"], g["tb"], res["concrete_m3_per_m"]),
        "地錨：%d 排、水平間距 %.2f m、俯角 %.0f°、%s；%s（FS 抗張材 %.1f／地層-漿體 %.1f／抗張材-漿體 %.1f）"
        % (len(res["anchors"]), g["sh"], g["alpha"], res["strand"]["label"], fs["label"],
           fs["tendon"], fs["ground_grout"], fs["tendon_grout"]),
        "土壓：%s、Ka(水平)=%.3f、總土壓 %.1f kN/m、p_max=%.1f kPa、上載 %.1f kPa%s"
        % ("FHWA 視土壓包絡" if g["distribution"] == "apparent" else "三角形分佈", pr["Ka_h"],
           pr["P_earth_kN_per_m"], pr["p_max_kPa"], pr["p_surcharge_kPa"],
           "；地震增量 %.1f kN/m（均佈 %.2f kPa，含牆面慣性）" % (pr["dPae_kN_per_m"], pr["p_seismic_kPa"])
           if res["seismic"]["kh"] > 0 else ""),
        "牆面配筋量：%.2f kg/m（含 %.0f%% 搭接、錨定與損耗）"
        % (res["rebar_kg_per_m"], res["reinforcement"]["lap_allowance"] * 100.0),
        "",
    ]
    for a in res["anchors"]:
        lines.append(
            "  第 %d 排 z=%.2f m：R=%.1f kN/m → T設計=%.1f kN（容許 %.1f）；%d 股（需 %d）；"
            "錨碇段 %.1f m（需 %.2f）、自由段 %.1f m（需 %.2f）；鎖定 %.1f kN；總長 %.1f m"
            % (a["row"], a["depth_m"], a["R_seismic_kN_per_m"] if res["seismic"]["kh"] > 0 else a["R_static_kN_per_m"],
               a["T_design_kN"], a["T_allow_kN"], a["strands"], a["strands_required"], a["bond_length_m"],
               a["bond_length_required_m"], a["free_length_m"], a["free_length_required_m"], a["lockoff_kN"],
               a["total_length_m"]))
    for b in res["base"]:
        lines.append("  基底（%s）：R=%.1f kN/m、N=%.1f kN/m、FS滑=%.2f、q=%.1f kPa"
                     % (b["case"], b["R_base_kN_per_m"], b["N_kN_per_m"], b["FS_sliding"], b["q_kPa"]))
    passive_line = EP.passive_summary(res.get("passive") or {})
    if passive_line:
        lines.append("  " + passive_line)
    for m in res["wall"]["members"]:
        fl = m["flexure"]
        lines.append("  %s：Mu=%.2f kN·m/m → %s@%s（φMn=%s）"
                     % (m["member"], m["Mu_kNm_per_m"], fl.get("bar", "-"), fl.get("spacing_mm", "-"),
                        fl.get("phiMn_kNm", "-")))
    lines.append("")
    for c in res["checks"]:
        lim = c["limit"]
        lines.append("  [%s] %s：%.3f / %s" % ("OK" if c["ok"] else "NG", c["item"], c["value"],
                                                "-" if lim is None else "%.3f" % lim))
    lines.append("")
    lines.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整地錨或牆面"))
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（錨定牆 H=7 m、三排地錨，每項可獨立驗算）。"""
    from _selftest_util import Checker

    c = Checker("錨定擋土牆（H = 7 m）")
    q = {"height_m": 7.0, "wall_thickness_m": 0.4, "base_width_m": 1.2,
         "base_thickness_m": 0.5, "front_soil_depth_m": 1.0,
         "anchor_depths_m": [1.5, 3.5, 5.5], "horizontal_spacing_m": 2.5,
         "inclination_deg": 20.0, "service": "permanent", "strand_type": "12.7",
         "strands": 4, "free_length_m": 7.0, "bond_length_m": 6.0,
         "drill_diameter_mm": 135.0, "bearing_plate_m": 0.3,
         "lockoff_factor": 1.15, "pressure_distribution": "apparent"}
    soil = {"gamma": 19.0, "phi_deg": 30.0, "backfill_slope_deg": 0.0,
            "surcharge_kpa": 10.0, "allowable_bearing_kpa": 300.0,
            "base_friction": 0.55, "bond_strength_kpa": 400.0,
            "tendon_bond_mpa": 2.0, "include_passive": False}
    r = analyse(q, soil=soil, seismic={"kh": 0.15},
                concrete={"fc_mpa": 21.0, "fy_mpa": 420.0, "cover_mm": 75.0})
    p = r["pressure"]
    a0 = r["anchors"][0]
    c.close("主動土壓力係數 Ka", p["Ka"],
            math.tan(math.radians(45.0 - 30.0 / 2)) ** 2, tol=1e-4)
    c.close("視土壓包絡 P", p["P_earth_kN_per_m"],
            0.65 * p["Ka"] * 19.0 * 7.0 ** 2, tol=1e-4)
    c.close("抗張材容許拉力", a0["T_allow_tendon_kN"], a0["Pu_kN"] / 2.0, tol=1e-4)
    c.close("地錨容許拉力", a0["T_allow_kN"],
            min(a0["Pu_kN"] / 2.0, a0["T_ult_ground_kN"] / 3.0,
                a0["T_ult_tendon_grout_kN"] / 3.0), tol=1e-4)
    c.true("錨碇段長 ≥ 需求且 ≥ 3 m",
           a0["bond_length_m"] >= a0["bond_length_required_m"] and a0["bond_length_m"] >= 3.0)
    c.true("自由段長 ≥ 需求且 ≥ 4 m",
           a0["free_length_m"] >= a0["free_length_required_m"] and a0["free_length_m"] >= 4.0)
    with_passive = analyse(q, soil=dict(soil, include_passive=True), seismic={"kh": 0.15},
                           concrete={"fc_mpa": 21.0, "fy_mpa": 420.0, "cover_mm": 75.0})
    b0, bp = r["base"][0], with_passive["base"][0]
    c.close("牆趾被動土壓力 Pp（預設折減 0.5）", bp["passive_kN_per_m"],
            0.5 * 0.5 * 3.0 * 19.0 * 1.0 ** 2, tol=1e-3)
    c.close("計入 Pp 後基底抗滑 FS", bp["FS_sliding"],
            (b0["N_kN_per_m"] * 0.55 + 14.25) / b0["R_base_kN_per_m"], tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    ap = argparse.ArgumentParser(description="錨定擋土牆（地錨背拉 RC 牆面）設計")
    ap.add_argument("json", help="輸入 JSON（section／soil／kh／concrete）")
    args = ap.parse_args()
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    res = analyse(data.get("section") or data, soil=data.get("soil"),
                  seismic={"kh": float(data.get("kh", 0.0))}, concrete=data.get("concrete"))
    print(format_report(res))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
