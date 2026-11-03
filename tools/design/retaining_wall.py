"""擋土牆穩定分析（水土保持技術規範第 119～120 條）。

為什麼要這個模組
----------------
先前的擋土牆斷面是「慣例值」——沒有做過穩定分析。那種圖能拿去做文件，但拿到工地會被技師退回。
本模組把第 119～120 條的要求算出來：主動土壓力（Rankine）、滑動、傾倒、基礎承載、合力作用點，
常時與地震兩種工況。

規範依據（原文見 docs\\水土保持技術規範_擋土牆條文.md）
--------------------------------------------------------
第 119 條：作用力須含自重、加載荷重、土壓力、水壓力、地震力、基礎承載力。
第 120 條：
  一、滑動 FS ≥ 1.5（常時）／≥ 1.2（地震）
  二、傾倒 FS ≥ 2.0（常時）／≥ 1.5（地震）；合力作用點須在
      岩盤基礎 1/2 中段內、土層基礎 1/3 中段內
  三、基礎應力須在容許承載力內，FS ≥ 3

單位：全部 SI（m、kN、kN/m²、度）
"""

import math
from collections.abc import Mapping
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import earth_pressure as EP
from wall_geometry import WallGeometryError, component_weights, parse as parse_wall_geometry

GAMMA_CONC = 24.0          # 混凝土單位重 kN/m³
GAMMA_SOIL = 18.0          # 回填土單位重 kN/m³（假設值，須以試驗替換）
GAMMA_WATER = 9.81

LIMITS = {
    "sliding_static": 1.5,
    "sliding_seismic": 1.2,
    "overturning_static": 2.0,
    "overturning_seismic": 1.5,
    "bearing": 3.0,
}

# 水土保持技術規範第118條「種類及適用範圍」的牆型與有效高上限。
# 上限不是通過門檻；仍須完成第119～120條的穩定與材料檢核。
WALL_TYPE_SPECS = {
    "gravity": {
        "label": "重力式",
        "max_height_m": 4.0,
        "basis": "水土保持技術規範 §118 二：有效高 4 m 以下為原則",
    },
    "semigravity": {
        "label": "半重力式",
        "max_height_m": 4.0,
        "basis": "水土保持技術規範 §118 三：有效高 4 m 以下為原則",
    },
    "cantilever": {
        "label": "懸臂式",
        "max_height_m": 8.0,
        "basis": "水土保持技術規範 §118 四：有效高 8 m 以下為原則",
    },
}


def validate_wall_applicability(wall_type, height_m):
    """Validate the §118 effective-height range for a supported wall type."""

    wall_type = str(wall_type or "").strip().lower()
    spec = WALL_TYPE_SPECS.get(wall_type)
    if spec is None:
        raise ValueError(
            "不支援的擋土牆牆型：%s；目前僅支援 %s。"
            % (wall_type or "（空白）", "、".join(WALL_TYPE_SPECS))
        )
    H = float(height_m)
    if not math.isfinite(H) or H <= 0:
        raise ValueError("擋土牆有效高必須為正數。")
    maximum = float(spec["max_height_m"])
    if H > maximum + 1e-9:
        raise ValueError(
            "%s擋土牆有效高 %.2f m 超過適用上限 %.1f m（%s）。"
            % (spec["label"], H, maximum, spec["basis"])
        )
    return spec


def _rankine_ka(phi_deg, delta_deg=0.0):
    """Rankine 主動土壓力係數（簡化：不計牆背摩擦，偏保守）。"""
    phi = math.radians(phi_deg)
    return (1 - math.sin(phi)) / (1 + math.sin(phi))


def _geometry(q):
    """Return the legacy stability view backed by the shared geometry module."""
    try:
        geom = parse_wall_geometry(q)
    except WallGeometryError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "pts": geom.polygon(),
        "H": geom.retained_height_m,
        "T": float(geom.parameters.get("stem_thickness_m", geom.parameters.get("top_width_m", 0.0))),
        "BL": geom.base_width_m,
        "BT": geom.base_thickness_m,
        "wall_type": geom.wall_type,
        "shared": geom,
    }


def _poly_area_centroid(pts):
    """多邊形面積與形心（鞋帶公式 + 形心公式）。"""
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-12:
        return 0.0, 0.0, 0.0
    return abs(a), cx / (6 * a), cy / (6 * a)


def _soil_value(block, *names, default=None):
    for name in names:
        if name in block and block[name] is not None:
            return block[name]
    return default


def _toe_passive(q, soil, geom, *, gamma, phi_deg, c_kpa):
    """牆趾覆土被動土壓力；半重力式預設計入，其餘牆型須明確勾選。"""

    depth = float(geom.parameters.get("toe_soil_depth_m", q.get("toe_soil_depth_m")) or 0.0)
    options = EP.passive_options(
        q, soil, default_include=geom.wall_type == "semigravity", default_ratio=1.0
    )
    ys = [y for _, y in geom.points]
    total_height = max(ys) - min(ys)
    if options["include"] and depth >= total_height:
        raise ValueError(
            "牆趾覆土深 %.2f m 必須小於牆總高 %.2f m。" % (depth, total_height)
        )
    return EP.toe_passive_resistance(
        depth_m=depth, gamma_kn_m3=gamma, phi_deg=phi_deg, cohesion_kpa=c_kpa, **options
    )


def _analyse_semigravity(q, soil=None, seismic=None, foundation_soil=None, backfill=None):
    """Stability analysis for a semi-gravity wall.

    Geometry is shared with quantities/drawings.  Active pressure uses the
    Coulomb wedge with wall friction and Mononobe-Okabe seismic increment.
    """

    g = _geometry(q)
    geom = g["shared"]
    soil = dict(
        {
            "gamma": GAMMA_SOIL,
            "phi_deg": 32.0,
            "c_kpa": 0.0,
            "allowable_bearing_kpa": 200.0,
            "foundation": "soil",
        },
        **(soil or {}),
    )
    seismic = dict({"kh": 0.0, "kv": 0.0}, **(seismic or {}))

    embedded_foundation = soil.get("foundation_soil")
    if foundation_soil is None and isinstance(embedded_foundation, Mapping):
        foundation_soil = embedded_foundation
    elif foundation_soil is None and isinstance(soil.get("foundation"), Mapping):
        foundation_soil = soil["foundation"]
    foundation_soil = dict(foundation_soil or {})

    embedded_backfill = soil.get("backfill") or soil.get("backfill_soil")
    if backfill is None and isinstance(embedded_backfill, Mapping):
        backfill = embedded_backfill
    backfill = dict(backfill or {})

    gamma_foundation = float(
        _soil_value(
            foundation_soil,
            "gamma_kn_m3",
            "gamma",
            default=_soil_value(soil, "gamma", default=GAMMA_SOIL),
        )
    )
    phi_foundation = float(
        _soil_value(
            foundation_soil,
            "phi_deg",
            default=_soil_value(soil, "phi_deg", default=32.0),
        )
    )
    c_foundation = float(
        _soil_value(
            foundation_soil,
            "c_kpa",
            default=_soil_value(soil, "c_kpa", default=0.0),
        )
    )
    gamma_backfill = float(
        _soil_value(
            backfill,
            "gamma_kn_m3",
            "gamma",
            default=_soil_value(soil, "backfill_gamma", default=GAMMA_SOIL),
        )
    )
    phi_backfill = float(
        _soil_value(
            backfill,
            "phi_deg",
            default=_soil_value(soil, "backfill_phi_deg", default=30.0),
        )
    )
    c_backfill = float(
        _soil_value(
            backfill,
            "c_kpa",
            default=_soil_value(soil, "backfill_c_kpa", default=0.0),
        )
    )
    delta = float(
        _soil_value(
            backfill,
            "wall_friction_deg",
            default=_soil_value(
                q,
                "wall_friction_deg",
                default=(2.0 / 3.0) * phi_backfill,
            ),
        )
    )
    surcharge = float(
        _soil_value(
            q,
            "surcharge_kpa",
            default=_soil_value(backfill, "surcharge_kpa", default=0.0),
        )
    )
    groundwater = _soil_value(
        q,
        "groundwater_depth_m",
        default=_soil_value(backfill, "groundwater_depth_m", default=None),
    )
    saturated_gamma = _soil_value(
        backfill,
        "saturated_unit_weight_kn_m3",
        default=_soil_value(q, "saturated_unit_weight_kn_m3", default=None),
    )
    gamma_conc = float(
        _soil_value(
            q,
            "concrete_unit_weight_kn_m3",
            default=_soil_value(soil, "concrete_unit_weight_kn_m3", default=GAMMA_CONC),
        )
    )

    rows = component_weights(
        geom,
        concrete_unit_weight_kn_m3=gamma_conc,
        soil_unit_weight_kn_m3=gamma_foundation,
    )
    W_static = sum(r["weight_kn_per_m"] for r in rows)
    M_weight = sum(r["mx_knm_per_m"] for r in rows)
    base_bottom = min(y for _, y in geom.points)
    y_centroid = (
        sum(r["weight_kn_per_m"] * (r["centroid_m"][1] - base_bottom) for r in rows)
        / W_static
        if W_static > 0
        else 0.0
    )

    pressure = EP.active_earth_pressure(
        height_m=geom.height_m,
        gamma_kn_m3=gamma_backfill,
        phi_deg=phi_backfill,
        cohesion_kpa=c_backfill,
        surcharge_kpa=surcharge,
        groundwater_depth_m=groundwater,
        saturated_unit_weight_kn_m3=saturated_gamma,
        wall_friction_deg=delta,
        backfill_slope_deg=float(q.get("backfill_slope_deg", 0.0)),
        wall_angle_deg=float(q.get("wall_angle_deg", 90.0)),
        kh=float(seismic["kh"]),
        kv=float(seismic["kv"]),
    )

    kh = float(seismic["kh"])
    kv = float(seismic["kv"])
    pv_total = pressure.vertical_kn_per_m + pressure.seismic_increment_vertical_kn_per_m
    N = W_static * (1.0 - kv) + pv_total
    M_resist = M_weight * (1.0 - kv) + pv_total * geom.base_width_m
    inertia = W_static * kh
    M_over = (
        pressure.horizontal_kn_per_m * pressure.application_height_m
        + pressure.seismic_increment_moment_knm_per_m
        + inertia * y_centroid
    )
    H_drive = (
        pressure.horizontal_kn_per_m
        + pressure.seismic_increment_horizontal_kn_per_m
        + inertia
    )

    passive = _toe_passive(
        q, soil, geom, gamma=gamma_foundation, phi_deg=phi_foundation, c_kpa=c_foundation
    )
    explicit_friction = _soil_value(
        foundation_soil,
        "base_friction",
        default=_soil_value(q, "base_friction", default=None),
    )
    friction = (
        float(explicit_friction)
        if explicit_friction is not None
        else math.tan(math.radians((2.0 / 3.0) * phi_foundation))
    )
    cohesion_resistance = (2.0 / 3.0) * c_foundation * geom.base_width_m
    R_sliding = cohesion_resistance + N * friction + passive["Pp_kN_per_m"]
    FS_sliding = R_sliding / H_drive if H_drive > 0 else float("inf")
    FS_over = M_resist / M_over if M_over > 0 else float("inf")

    x_R = (M_resist - M_over) / N if N > 0 else 0.0
    e = geom.base_width_m / 2.0 - x_R
    if abs(e) <= geom.base_width_m / 6.0:
        q_max = (N / geom.base_width_m) * (1.0 + 6.0 * abs(e) / geom.base_width_m)
        q_min = (N / geom.base_width_m) * (1.0 - 6.0 * abs(e) / geom.base_width_m)
    else:
        contact_length = 3.0 * (geom.base_width_m / 2.0 - abs(e))
        q_max = 2.0 * N / contact_length if contact_length > 1e-9 else float("inf")
        q_min = 0.0

    q_a = float(
        _soil_value(
            soil,
            "allowable_bearing_kpa",
            default=_soil_value(foundation_soil, "allowable_bearing_kpa", default=200.0),
        )
    )
    q_ult_key = "ultimate_bearing_seismic_kpa" if kh > 0 else "ultimate_bearing_kpa"
    q_ult = float(
        _soil_value(
            foundation_soil,
            q_ult_key,
            "ultimate_bearing_kpa",
            default=_soil_value(soil, q_ult_key, default=_soil_value(soil, "ultimate_bearing_kpa", default=3.0 * q_a)),
        )
    )
    FS_bearing = q_ult / q_max if q_max > 0 else float("inf")

    limits = dict(LIMITS)
    if kh > 0:
        s_lim, o_lim = limits["sliding_seismic"], limits["overturning_seismic"]
    else:
        s_lim, o_lim = limits["sliding_static"], limits["overturning_static"]
    frac = 0.5 if soil.get("foundation") == "rock" else 1.0 / 3.0
    x_lo, x_hi = (
        geom.base_width_m * (0.5 - frac / 2.0),
        geom.base_width_m * (0.5 + frac / 2.0),
    )

    checks = [
        {
            "item": "滑動（%s）" % ("地震" if kh > 0 else "常時"),
            "value": FS_sliding,
            "limit": s_lim,
            "ok": FS_sliding >= s_lim,
            "unit": "FS",
        },
        {
            "item": "傾倒（%s）" % ("地震" if kh > 0 else "常時"),
            "value": FS_over,
            "limit": o_lim,
            "ok": FS_over >= o_lim,
            "unit": "FS",
        },
        {
            "item": "合力作用點（%s基礎，1/3 中段）" % (
                "岩盤" if soil.get("foundation") == "rock" else "土層"
            ),
            "value": x_R,
            "limit": (x_lo, x_hi),
            "ok": (x_lo - 0.0005 * geom.base_width_m)
            <= x_R
            <= (x_hi + 0.0005 * geom.base_width_m),
            "unit": "m",
        },
        {
            "item": "基礎承載（FS＝q_ult/q_max）",
            "value": FS_bearing,
            "limit": limits["bearing"],
            "ok": FS_bearing >= limits["bearing"],
            "unit": "FS",
            "relation": "ge",
        },
        {
            "item": "基底最大應力 ≤ 容許承載力",
            "value": q_max,
            "limit": q_a,
            "ok": q_max <= q_a,
            "unit": "kPa",
            "relation": "le",
        },
    ]

    return {
        "wall_type": "semigravity",
        "geometry": {
            "H": geom.height_m,
            "T": geom.parameters.get("top_width_m", 0.0),
            "BL": geom.base_width_m,
            "BT": geom.base_thickness_m,
            "area_m2_per_m": round(geom.area_m2_per_m, 6),
            "centroid": (round(geom.centroid_m[0], 4), round(geom.centroid_m[1], 4)),
            "components": rows,
        },
        # 報告／數量共用同一份土工參數契約。半重力式的摩擦係數可能是由
        # foundation_soil 或 tan(2φ/3) 推得，不能只留在區域變數裡，否則
        # case_core 取 res["soil"]["base_friction"] 會 KeyError，讓第 6～8 章
        # 整批消失（實測 4 m 半重力式報告 design_sections_error='base_friction'）。
        "soil": dict(soil, base_friction=friction),
        "foundation_soil": foundation_soil,
        "backfill": backfill,
        "seismic": {"kh": kh, "kv": kv},
        "Ka": round(pressure.coefficient, 5),
        "Pa_kN_per_m": round(pressure.horizontal_kn_per_m, 3),
        "Pa_cohesion_deducted": 0.0,
        "y_Pa_m": round(pressure.application_height_m, 4),
        "W_conc_kN_per_m": round(
            sum(r["weight_kn_per_m"] for r in rows if r["material"] == "concrete"), 3
        ),
        "W_soil_kN_per_m": round(
            sum(r["weight_kn_per_m"] for r in rows if r["material"] == "soil"), 3
        ),
        "W_kN_per_m": round(W_static, 3),
        "Pav_kN_per_m": round(pv_total, 3),
        "Pp_kN_per_m": round(passive["Pp_kN_per_m"], 3),
        "passive": passive,
        "F_eq_kN_per_m": round(inertia, 3),
        "M_resist_kNm": round(M_resist, 3),
        "M_over_kNm": round(M_over, 3),
        "x_R_m": round(x_R, 4),
        "e_m": round(e, 4),
        "q_max_kPa": round(q_max, 2),
        "q_min_kPa": round(q_min, 2),
        "q_ult_kPa": round(q_ult, 2),
        "checks": checks,
        "warnings": EP.passive_warnings(passive, kh > 0),
        "pass": all(c["ok"] for c in checks),
        "pressure": pressure.as_dict(),
        "basis": [
            "水土保持技術規範第 119～120 條",
            "Coulomb 主動土壓；地震增量採 Mononobe-Okabe",
            "承載 FS 採 q_ult/q_max，q_ult 應由地質/承載分析提供",
        ],
    }


def analyse_semigravity(q, soil=None, seismic=None, foundation_soil=None, backfill=None):
    """Public entry point for semi-gravity walls."""

    g = _geometry(q)
    validate_wall_applicability(g["wall_type"], g["H"])
    return _analyse_semigravity(
        q,
        soil=soil,
        seismic=seismic,
        foundation_soil=foundation_soil,
        backfill=backfill,
    )


def analyse(q, soil=None, seismic=None):
    """執行穩定分析。

    q：quantities.values（含 wall_type／height_m／stem_thickness_m／base_width_m／base_thickness_m）
    soil：{gamma, phi_deg, c_kpa, allowable_bearing_kpa, base_friction, foundation(soil|rock)}
    seismic：{kh}（水平地震係數，0 表示不做地震工況）
    """
    g = _geometry(q)
    validate_wall_applicability(g["wall_type"], g["H"])
    if g["wall_type"] == "semigravity":
        return _analyse_semigravity(q, soil=soil, seismic=seismic)
    soil = dict({
        "gamma": GAMMA_SOIL,
        "phi_deg": 30.0,
        "c_kpa": 0.0,
        "allowable_bearing_kpa": 200.0,
        "base_friction": 0.5,          # 混凝土/土 界面摩擦係數（tanδ）
        "foundation": "soil",          # soil → 合力需在 1/3 中段；rock → 1/2
    }, **(soil or {}))
    seismic = dict({"kh": 0.0}, **(seismic or {}))

    H, T, BL, BT = g["H"], g["T"], g["BL"], g["BT"]
    gamma_s = float(soil["gamma"])
    Ka = _rankine_ka(float(soil["phi_deg"]))

    # ---- 主動土壓力（Rankine，水平分量；牆背假設鉛直、填土面水平）----
    Pa = 0.5 * Ka * gamma_s * H ** 2                  # kN/m
    # 若有黏著力，扣 2c√Ka·H（取正值）
    Pa_c = 0.0
    if float(soil["c_kpa"]) > 0:
        Pa_c = min(2 * float(soil["c_kpa"]) * math.sqrt(Ka) * H, Pa * 0.9)
        Pa -= Pa_c
        Pa = max(Pa, 0.0)
    y_Pa = H / 3.0                                     # 距牆底

    # ---- 自重與形心 ----
    area, cx, cy = g["shared"].area_m2_per_m, *g["shared"].centroid_m
    W_conc = area * GAMMA_CONC                         # kN/m
    M_W = W_conc * cx

    # ---- 懸臂式的關鍵：**踵板上方覆土重量**才是主要穩定力 ----
    # 先前漏算這一塊 → 懸臂式不論斷面多大都驗不過（實測掃 330 組全 NG）。
    # 幾何：牆身佔 x=0..T，踵板由 x=T 到 x=BL，其上覆土高 H、單位重 γs。
    W_soil = 0.0
    x_soil = 0.0
    if g["wall_type"] == "cantilever":
        heel_w = max(BL - T, 0.0)
        W_soil = heel_w * H * gamma_s
        x_soil = T + heel_w / 2.0
        M_W += W_soil * x_soil

    W = W_conc + W_soil                                # 總垂直力（抗滑、承載用）

    # ---- 牆趾覆土被動土壓力（只計入抗滑）----
    passive = _toe_passive(
        q, soil, g["shared"],
        gamma=gamma_s, phi_deg=float(soil["phi_deg"]), c_kpa=float(soil["c_kpa"]),
    )

    # ---- 地震力（擬靜態法：總重 × kh）----
    kh = float(seismic["kh"])
    F_eq = W * kh
    y_eq = ((W_conc * cy) + (W_soil * (H / 2.0))) / W if W > 0 else 0.0

    # ---- 滑動檢核 ----
    # 抗滑 = 底部摩擦 × 有效垂直力（地震時垂直力不變，慣例不再折減）
    N = W
    R_friction = float(soil["base_friction"]) * N
    M_active_base = Pa * (cy + y_Pa) if False else 0.0  # 佔位，保持可讀
    T_drive = Pa + F_eq
    FS_sliding = (R_friction + passive["Pp_kN_per_m"]) / T_drive if T_drive > 0 else float("inf")

    # ---- 傾倒檢核（對前趾 x=0, y=0 取力矩）----
    M_resist = M_W                                     # 自重穩定力矩
    M_over = Pa * (BT + y_Pa) + F_eq * y_eq             # 傾倒力矩（土壓作用於基底以上 BT+y_Pa）
    FS_over = M_resist / M_over if M_over > 0 else float("inf")

    # ---- 合力作用點（距前趾 x 的距離）----
    M_net = M_resist - M_over
    x_R = M_net / N if N > 0 else 0.0
    # 中段要求
    frac = 0.5 if soil["foundation"] == "rock" else 1.0 / 3.0
    x_lo, x_hi = BL * (0.5 - frac / 2), BL * (0.5 + frac / 2)

    # ---- 基礎承載（梯形分佈；e 為偏心距）----
    e = BL / 2.0 - x_R
    if abs(e) <= BL / 6.0:
        q_max = (N / BL) * (1 + 6 * abs(e) / BL)
        q_min = (N / BL) * (1 - 6 * abs(e) / BL)
    else:
        # 偏心過大：只用受壓區（2×(BL/2 - |e|)）
        Lp = 3 * (BL / 2.0 - abs(e))
        q_max = 2 * N / max(Lp, 1e-9) if Lp > 0 else float("inf")
        q_min = 0.0
    q_a = float(soil["allowable_bearing_kpa"])
    # 第 120 條三：「基礎之應力必須在土壤容許承載力之內，其安全係數不得小於三」
    # → 兩個獨立要求：① q_max ≤ q_a（容許值）；② q_ult / q_max ≥ 3。
    # 先前把「q_a / q_max ≥ 3」當成檢核，等於把容許值裡已含的 FS 再乘一次（重複計算），
    # 導致任何斷面都驗不過。容許值若未給極限值，慣例取 q_ult = 3 × q_a。
    q_ult = float(soil.get("ultimate_bearing_kpa") or (3.0 * q_a))
    FS_bearing = q_ult / q_max if q_max > 0 else float("inf")

    # ---- 判定 ----
    limits = dict(LIMITS)
    if kh > 0:
        s_lim, o_lim = limits["sliding_seismic"], limits["overturning_seismic"]
    else:
        s_lim, o_lim = limits["sliding_static"], limits["overturning_static"]

    checks = [
        {"item": "滑動（%s）" % ("地震" if kh > 0 else "常時"),
         "value": FS_sliding, "limit": s_lim, "ok": FS_sliding >= s_lim,
         "unit": "FS"},
        {"item": "傾倒（%s）" % ("地震" if kh > 0 else "常時"),
         "value": FS_over, "limit": o_lim, "ok": FS_over >= o_lim,
         "unit": "FS"},
        {"item": "合力作用點（%s基礎，%d/%d 中段）" % (
            "岩盤" if soil["foundation"] == "rock" else "土層",
            1 if frac == 0.5 else 1, 2 if frac == 0.5 else 3),
         # 邊界容差：1.95×1/3 = 0.649999…，浮點誤差會讓「剛好在中段邊界」被判不合格
         # （實測 x_R=0.6499 差 0.0001 m 被判 False）。取 0.05% BL 作容差。
         "value": x_R, "limit": (x_lo, x_hi),
         "ok": (x_lo - 0.0005 * BL) <= x_R <= (x_hi + 0.0005 * BL), "unit": "m"},
        {"item": "基礎承載（FS＝q_ult/q_max）", "value": FS_bearing, "limit": limits["bearing"],
         "ok": (FS_bearing >= limits["bearing"]) and (q_max <= q_a), "unit": "FS",
         "relation": "ge"},
        {"item": "基底最大應力 ≤ 容許承載力", "value": q_max, "limit": q_a,
         "ok": q_max <= q_a, "unit": "kPa", "relation": "le"},
    ]

    return {
        "wall_type": g["wall_type"],
        "geometry": {"H": H, "T": T, "BL": BL, "BT": BT,
                     "area_m2_per_m": round(area, 6),
                     "centroid": (round(cx, 4), round(cy, 4))},
        "soil": soil,
        "seismic": {"kh": kh},
        "Ka": round(Ka, 5),
        "Pa_kN_per_m": round(Pa, 3),
        "Pa_cohesion_deducted": round(Pa_c, 3),
        "y_Pa_m": round(y_Pa, 4),
        "W_conc_kN_per_m": round(W_conc, 3),
        "W_soil_kN_per_m": round(W_soil, 3),
        "W_kN_per_m": round(W, 3),
        "Pp_kN_per_m": round(passive["Pp_kN_per_m"], 3),
        "passive": passive,
        "F_eq_kN_per_m": round(F_eq, 3),
        "M_resist_kNm": round(M_resist, 3),
        "M_over_kNm": round(M_over, 3),
        "x_R_m": round(x_R, 4),
        "e_m": round(e, 4),
        "q_max_kPa": round(q_max, 2),
        "q_ult_kPa": round(q_ult, 2),
        "q_min_kPa": round(q_min, 2),
        "checks": checks,
        "warnings": EP.passive_warnings(passive, kh > 0),
        "pass": all(c["ok"] for c in checks),
    }


def format_report(res):
    """把結果排成人看得懂的段落（給設計報告第 6～7 章用）。"""
    g, s = res["geometry"], res["soil"]
    L = []
    wall_labels = {
        "gravity": "重力式（梯形）",
        "cantilever": "懸臂式（薄牆＋底板）",
        "semigravity": "半重力式（厚牆＋底板）",
    }
    wall_type = res.get("wall_type", "gravity")
    L.append("牆型：%s；H=%.2f m、T=%.2f m、底寬=%.2f m%s" % (
        wall_labels.get(wall_type, wall_type),
        g["H"], g["T"], g["BL"],
        "" if wall_type == "gravity" else "、底板厚=%.2f m" % g["BT"]))
    L.append("斷面積 %.4f m²/m、形心 (%.3f, %.3f) m、自重 W=%.2f kN/m" % (
        g["area_m2_per_m"], g["centroid"][0], g["centroid"][1], res["W_kN_per_m"]))
    L.append("土工參數（假設值）：γ=%.1f kN/m³、φ=%.0f°、c=%.1f kPa；Ka=%.4f" % (
        s["gamma"], s["phi_deg"], s["c_kpa"], res["Ka"]))
    L.append("主動土壓力 Pa=%.2f kN/m，作用於牆底以上 %.3f m" % (
        res["Pa_kN_per_m"], res["y_Pa_m"]))
    passive_line = EP.passive_summary(res.get("passive") or {})
    if passive_line:
        L.append(passive_line)
    if res["seismic"]["kh"] > 0:
        L.append("地震力（擬靜態 kh=%.2f）：Feq=%.2f kN/m" % (
            res["seismic"]["kh"], res["F_eq_kN_per_m"]))
    L.append("")
    for c in res["checks"]:
        relation = c.get("relation")
        if isinstance(c["limit"], tuple):
            L.append("  [%s] %s = %.3f m（允許 %.3f～%.3f）" % (
                "OK" if c["ok"] else "NG", c["item"], c["value"], c["limit"][0], c["limit"][1]))
        else:
            if relation == "le":
                criterion = "≤ %.2f" % c["limit"]
            elif relation == "ge":
                criterion = "≥ %.2f" % c["limit"]
            else:
                criterion = "≥ %.2f" % c["limit"]
            L.append("  [%s] %s = %.2f（%s）" % (
                "OK" if c["ok"] else "NG", c["item"], c["value"], criterion))
    L.append("")
    L.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整斷面"))
    return "\n".join(L)

# --------------------------------------------------------------------------- #
# 断面選配（真正的「設計」：依穩定需求反推斷面）
# --------------------------------------------------------------------------- #
def size_section(H, soil=None, wall_type="gravity", kh=0.0,
                 t_choices=None, bl_ratio=None, min_bl=0.9, toe_passive=None):
    """在給定牆高與土工參數下，找出**通過所有穩定檢核**的最小斷面。

    搜尋策略（由小到大、先省料後保險）：
      重力式  ：固定頂寬 T，底寬 BL 由 0.30H 掃到 0.90H（步 0.05H）；T 由 0.30 m 掃到 0.60 m
      懸臂式  ：固定牆身 T=0.25~0.50 m，底寬 BL 由 0.40H 掃到 0.90H；底板厚 BT 由 0.30H 掃到 0.50H

    toe_passive：併入每個候選斷面的牆趾被動土壓力欄位
    （toe_soil_depth_m／include_passive／passive_ratio）。

    回傳 (best, tried_count)；best 為含 q 與 res 的 dict，找不到則 None。
    """
    wall_type = str(wall_type or "gravity").strip().lower()
    validate_wall_applicability(wall_type, H)
    soil = dict({
        "gamma": GAMMA_SOIL, "phi_deg": 30.0, "c_kpa": 0.0,
        "allowable_bearing_kpa": 200.0, "base_friction": 0.5, "foundation": "soil",
    }, **(soil or {}))
    toe_passive = dict(toe_passive or {})

    if t_choices is None:
        t_choices = ([0.30, 0.35, 0.40, 0.45, 0.50, 0.60] if wall_type == "gravity"
                     else [0.25, 0.30, 0.35, 0.40, 0.45, 0.50])
    if bl_ratio is None:
        lo = 0.30 if wall_type == "gravity" else 0.40
        bl_ratio = [round(lo + 0.05 * i, 2) for i in range(int((0.90 - lo) / 0.05) + 1)]

    tried = 0
    best = None
    for T in t_choices:
        for r in bl_ratio:
            BL = max(round(r * H, 2), min_bl)
            if wall_type == "gravity":
                cand = {"wall_type": "gravity", "height_m": H, "stem_thickness_m": T,
                        "base_width_m": BL, "base_thickness_m": 0.0, **toe_passive}
            else:
                for bt_r in (0.12, 0.15, 0.18, 0.22):
                    cand = {"wall_type": "cantilever", "height_m": H, "stem_thickness_m": T,
                            "base_width_m": BL, "base_thickness_m": round(bt_r * H, 2), **toe_passive}
                    tried += 1
                    res = analyse(cand, soil, {"kh": kh})
                    if res["pass"]:
                        area = res["geometry"]["area_m2_per_m"]
                        if best is None or area < best["res"]["geometry"]["area_m2_per_m"]:
                            best = {"q": cand, "res": res}
                    break   # 先用 0.30H 掃一輪，沒過再換 BT（下方補掃）
            if wall_type == "gravity":
                tried += 1
                res = analyse(cand, soil, {"kh": kh})
                if res["pass"]:
                    if best is None or res["geometry"]["area_m2_per_m"] < best["res"]["geometry"]["area_m2_per_m"]:
                        best = {"q": cand, "res": res}

    # 懸臂式若上面沒找到，再把 BT 加厚重掃
    if best is None and wall_type != "gravity":
        for T in t_choices:
            for r in bl_ratio:
                BL = max(round(r * H, 2), min_bl)
                for bt_r in (0.15, 0.18, 0.22, 0.25):
                    cand = {"wall_type": "cantilever", "height_m": H, "stem_thickness_m": T,
                            "base_width_m": BL, "base_thickness_m": round(bt_r * H, 2), **toe_passive}
                    tried += 1
                    res = analyse(cand, soil, {"kh": kh})
                    if res["pass"]:
                        if best is None or res["geometry"]["area_m2_per_m"] < best["res"]["geometry"]["area_m2_per_m"]:
                            best = {"q": cand, "res": res}
    return best, tried


def selftest() -> int:
    """手算對照（懸臂式 3 m，每項可獨立驗算）。"""
    from _selftest_util import Checker

    c = Checker("擋土牆穩定（懸臂式 3 m）")
    q = {"wall_type": "cantilever", "height_m": 3.0, "stem_thickness_m": 0.35,
         "base_width_m": 1.95, "base_thickness_m": 0.36}
    r = analyse(q)
    c.close("主動土壓力係數 Ka", r["Ka"],
            math.tan(math.radians(45.0 - 30.0 / 2)) ** 2, tol=1e-4)
    c.close("主動土壓力 Pa", r["Pa_kN_per_m"], 0.5 * r["Ka"] * 18.0 * 3.0 ** 2, tol=1e-4)
    c.close("合力作用點 y", r["y_Pa_m"], 3.0 / 3.0)
    c.close("混凝土重量", r["W_conc_kN_per_m"], r["geometry"]["area_m2_per_m"] * 24.0)
    c.close("抗滑 FS", r["checks"][0]["value"],
            r["W_kN_per_m"] * r["soil"]["base_friction"] / r["Pa_kN_per_m"])
    c.close("最大承壓 q", r["q_max_kPa"],
            r["W_kN_per_m"] / 1.95 * (1.0 + 6.0 * r["e_m"] / 1.95), tol=1e-4)
    passive = analyse({**q, "toe_soil_depth_m": 0.6, "include_passive": True})
    c.close("牆趾被動土壓力 Pp", passive["Pp_kN_per_m"], 0.5 * 3.0 * 18.0 * 0.6 ** 2, tol=1e-3)
    c.close("計入 Pp 後抗滑 FS", passive["checks"][0]["value"],
            (r["W_kN_per_m"] * 0.5 + 9.72) / r["Pa_kN_per_m"], tol=1e-3)
    c.close("Pp 不影響抗傾倒 FS", passive["checks"][1]["value"], r["checks"][1]["value"])
    half = analyse({**q, "toe_soil_depth_m": 0.6, "include_passive": True, "passive_ratio": 0.5})
    c.close("折減比 0.5 的 Pp", half["Pp_kN_per_m"], 4.86, tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(description="擋土牆穩定分析與斷面選配")
    ap.add_argument("case_json", help="case.json 或含 quantities/soil 的 JSON")
    ap.add_argument("--kh", type=float, default=0.0, help="水平地震係數")
    ap.add_argument("--json", action="store_true", help="輸出完整 JSON")
    ap.add_argument(
        "--size",
        action="store_true",
        help="依牆高反推通過穩定檢核的最小重力式／懸臂式斷面",
    )
    a = ap.parse_args()
    with open(a.case_json, encoding="utf-8") as fh:
        case = json.load(fh)
    q = (case.get("quantities") or {}).get("values") or case.get("quantities") or {}
    soil = case.get("soil") or {}
    if a.size:
        wall_type = str(q.get("wall_type") or "gravity")
        if wall_type not in ("gravity", "cantilever"):
            ap.error("--size 目前只支援 gravity 或 cantilever；半重力式請直接輸入完整斷面。")
        if q.get("height_m") is None:
            ap.error("--size 需要 quantities.values.height_m")
        best, tried = size_section(
            float(q["height_m"]),
            soil=soil,
            wall_type=wall_type,
            kh=a.kh,
            toe_passive={
                k: q[k]
                for k in ("toe_soil_depth_m", "include_passive", "passive_ratio")
                if k in q
            },
        )
        if best is None:
            print("找不到通過檢核的斷面（已試 %d 組）。" % tried)
            raise SystemExit(1)
        payload = {"tried": tried, "selected": best}
        if a.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("已試 %d 組；選用斷面：" % tried)
            print(json.dumps(best["q"], ensure_ascii=False, indent=2))
            print()
            print(format_report(best["res"]))
        raise SystemExit(0 if best["res"]["pass"] else 1)
    res = analyse(q, soil=soil, seismic={"kh": a.kh})
    print(
        json.dumps(res, ensure_ascii=False, indent=2)
        if a.json
        else format_report(res)
    )
    raise SystemExit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
