r"""沉砂設施容量設計（水土保持技術規範第 35、92、93 條；下水道工程設施標準第 12 條）。

為什麼要這個模組
----------------
第 93 條說「沉砂設施容量以泥砂生產量計算」，泥砂生產量要先用第 35 條的 USLE 估算、再依第
92 條打折與設下限、依第 93 條乘 1.5（臨時性）。這四步以前靠手算，數字無法追溯。本模組把
它們串起來，每個數字都標明出自哪一條。

條文依據（全文 data\法規\水土保持技術規範_1140507_全文.txt、下水道工程設施標準_1141104_全文.txt）
--------------------------------------------------------------------------------------
**第 35 條（山坡地土壤流失量之估算）**
    Am = Rm × Km × L × S × C × P                 公噸/公頃/年
    換算成體積以每立方公尺 1.4 公噸計之
    開挖整地：C 不得小於 0.05、P 不得小於 0.5

**第 92 條（泥砂生產量之估計）**
    臨時性：以 USLE 估算值之 1/2；但開挖整地部分每公頃不得小於 250 m³，
            未開挖整地或完成水土保持處理部分每公頃不得小於 30 m³
    永久性：完成水土保持處理或未開挖整地部分每公頃不得小於 30 m³
    得就不透水鋪面之面積扣除

**第 93 條（沉砂池設計容量）**
    容量 = 泥砂生產量；臨時性再乘 1.5
    深度以 1.5～3.5 m 為宜（與滯洪設施垂直共構且具合理性者不在此限）
    永久性至少每年清除一次；臨時性每次豪雨後立即清除

**下水道工程設施標準第 12 條（市區雨水下水道，快速複核用）**
    沉砂量以計畫開發面積每公頃 30 m³ 估算；
    山坡地開發施工期間臨時沉砂池每公頃 20～150 m³

三個必須自己決定的輸入（程式不代猜）
------------------------------------
1. Rm（降雨沖蝕指數）、Km（土壤沖蝕指數）、LS（坡長×坡度因子）：第 35 條要求用「台灣各地區
   之參數值」，請依現地或主管機關公告值填。
2. 年期 years：第 92 條未載明計算年期；本程式把 USLE 年產量乘上年期（預設 1 年）。年期越長
   容量越大，請依實際施工期填。下限（250／30 m³/ha）是設計容量下限，不隨年期放大。
3. 開挖整地面積與不透水面積：下限與扣除都按面積分攤（不透水先扣非開挖部分）。
"""

import argparse
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import rc_design as RC  # noqa: E402

# 第 35 條
SOIL_DENSITY = 1.4          # 公噸/m³
C_MIN = 0.05                # 開挖整地 C 下限
P_MIN = 0.50                # 開挖整地 P 下限

# 第 92 條
TEMP_USLE_FACTOR = 0.5
FLOOR_EXCAVATED = 250.0     # m³/ha，臨時性開挖整地部分
FLOOR_OTHER = 30.0          # m³/ha，未開挖或已完成水土保持處理部分

# 第 93 條
TEMP_CAPACITY_FACTOR = 1.5
DEPTH_MIN, DEPTH_MAX = 1.5, 3.5

# 下水道工程設施標準第 12 條
SEWER_RATE = 30.0           # m³/ha
SEWER_TEMP_RANGE = (20.0, 150.0)

# 選配結構／水理檢核的工程預設值。這些是常用計算常數，非法規明定數值。
WATER_GAMMA = 9.81          # kN/m³
CONCRETE_GAMMA = 24.0       # kN/m³
ORIFICE_CD = 0.62
WEIR_CW = 1.84              # 矩形銳緣堰 SI 式 Q=Cw·L·H^1.5


def usle(Rm, Km, LS, C, P):
    """第 35 條：Am = Rm×Km×L×S×C×P（公噸/公頃/年）。LS 可為 L×S 的乘積。"""
    if min(Rm, Km, LS, C, P) < 0:
        raise ValueError("USLE 參數不可為負")
    return Rm * Km * LS * C * P


def annual_volume_per_ha(Am):
    """第 35 條：1 m³ = 1.4 公噸 → m³/公頃/年。"""
    return Am / SOIL_DENSITY


def sediment_production(area_ha, excavated_ha=0.0, impervious_ha=0.0, kind="temporary",
                        years=1.0, Am=None, Rm=None, Km=None, LS=None, C=None, P=None):
    """第 92 條泥砂生產量（m³）。

    area_ha       計畫開發面積（公頃）
    excavated_ha  其中開挖整地部分（公頃）
    impervious_ha 不透水鋪面面積（公頃）→ 依第 92 條末項扣除（先扣非開挖部分）
    kind          "temporary"（臨時性）或 "permanent"（永久性）
    years         年期（年）
    Am            直接給土壤流失量（公噸/公頃/年）時，可省略下方五個參數
    """
    if kind not in ("temporary", "permanent"):
        raise ValueError("kind 只能是 temporary 或 permanent")
    if area_ha <= 0:
        raise ValueError("area_ha 必須大於 0")
    if not 0 <= excavated_ha <= area_ha:
        raise ValueError("excavated_ha 必須介於 0 與 area_ha 之間")
    if not 0 <= impervious_ha <= area_ha:
        raise ValueError("impervious_ha 必須介於 0 與 area_ha 之間")
    if years <= 0:
        raise ValueError("years 必須大於 0")
    if Am is None:
        if None in (Rm, Km, LS, C, P):
            raise ValueError("請給 Am，或給齊 Rm、Km、LS、C、P")
        Am = usle(Rm, Km, LS, C, P)

    # 不透水面積先從非開挖部分扣，不足再扣開挖部分
    other = area_ha - excavated_ha
    deduct_other = min(impervious_ha, other)
    deduct_exc = min(impervious_ha - deduct_other, excavated_ha)
    parts = [("開挖整地", excavated_ha - deduct_exc, FLOOR_EXCAVATED if kind == "temporary" else 0.0),
             ("未開挖或已完成水土保持處理", other - deduct_other, FLOOR_OTHER)]

    v_per_ha_year = annual_volume_per_ha(Am)
    factor = TEMP_USLE_FACTOR if kind == "temporary" else 1.0
    rows, total = [], 0.0
    for name, ha, floor in parts:
        if ha <= 0:
            continue
        computed = v_per_ha_year * years * ha * factor
        floor_vol = floor * ha
        volume = max(computed, floor_vol)
        rows.append({"part": name, "area_ha": ha, "computed_m3": computed, "floor_m3": floor_vol,
                     "floor_m3_per_ha": floor, "used_m3": volume,
                     "governed_by": "下限" if floor_vol > computed else "USLE"})
        total += volume
    return {"Am_t_ha_yr": Am, "m3_per_ha_yr": v_per_ha_year, "kind": kind, "years": years,
            "usle_factor": factor, "parts": rows, "production_m3": total,
            "effective_ha": sum(r["area_ha"] for r in rows)}


def analyse(area_ha, excavated_ha=0.0, impervious_ha=0.0, kind="temporary", years=1.0,
            depth=None, side_ratio=1.5, Am=None, Rm=None, Km=None, LS=None, C=None, P=None):
    """第 92、93 條：容量、深度、池面積與檢核；另附下水道標準第 12 條快速複核。"""
    prod = sediment_production(area_ha, excavated_ha, impervious_ha, kind, years,
                               Am=Am, Rm=Rm, Km=Km, LS=LS, C=C, P=P)
    capacity = prod["production_m3"] * (TEMP_CAPACITY_FACTOR if kind == "temporary" else 1.0)

    d = 2.0 if depth is None else float(depth)  # 未指定時取常用 2.0 m（仍在 1.5~3.5 m 內）
    checks = []
    if d < DEPTH_MIN or d > DEPTH_MAX:
        requested = d
        d = min(max(d, DEPTH_MIN), DEPTH_MAX)
        checks.append({"item": "深度", "ok": False,
                       "value": requested, "limit": [DEPTH_MIN, DEPTH_MAX], "unit": "m",
                       "msg": f"指定 {requested:.2f} m 超出第 93 條 {DEPTH_MIN}~{DEPTH_MAX} m，已調整為 {d:.2f} m"
                              f"（與滯洪設施垂直共構且具合理性者得不受限）"})
    else:
        checks.append({"item": "深度", "ok": True,
                       "value": d, "limit": [DEPTH_MIN, DEPTH_MAX], "unit": "m",
                       "msg": f"深度 {d:.2f} m 在 {DEPTH_MIN}~{DEPTH_MAX} m 範圍內"})

    footprint = capacity / d
    w = math.sqrt(footprint / side_ratio)
    length = w * side_ratio
    rate = capacity / area_ha

    if kind == "temporary":
        lo, hi = SEWER_TEMP_RANGE
        ok = lo <= rate <= hi
        checks.append({"item": "下水道標準第 12 條（臨時）", "ok": ok,
                       "severity": "advisory", "value": rate, "limit": [lo, hi], "unit": "m³/ha",
                       "msg": f"{rate:.1f} m³/ha（標準 {lo:.0f}~{hi:.0f} m³/ha）"
                              + ("" if ok else " —— 僅供複核：仍以水保規範第 92 條為準，兩者不一致要說明理由")})
    else:
        ok = rate >= SEWER_RATE
        checks.append({"item": "下水道標準第 12 條（每公頃 30 m³）", "ok": ok,
                       "severity": "advisory", "value": rate, "limit": SEWER_RATE, "unit": "m³/ha",
                       "relation": "ge",
                       "msg": f"{rate:.1f} m³/ha" + ("" if ok else f"，低於 {SEWER_RATE:.0f} m³/ha")})

    floors = [r["part"] for r in prod["parts"] if r["governed_by"] == "下限"]
    return {"production": prod, "capacity_m3": capacity, "depth_m": d, "footprint_m2": footprint,
            "length_m": length, "width_m": w, "side_ratio": side_ratio, "rate_m3_per_ha": rate,
            "checks": checks, "floors_govern": floors,
            "cleaning": "每次豪雨後立即清除" if kind == "temporary" else "至少每年清除一次"}


def hydrostatic_force_moment(inside_head_m, outside_head_m, wall_height_m=None,
                              gamma=WATER_GAMMA):
    """池壁在內、外水位差下之每公尺彎矩與剪力。

    以牆頂為 z=0、牆底為 z=H，壓力 p(z)=γ(h-z)（水位以下），對牆底取力矩：
        M = ∫ |p_in(z)-p_out(z)|·(H-z) dz
    水位較高的一側控制；H 未給時取兩側較高水位。
    """
    if inside_head_m < 0 or outside_head_m < 0:
        raise ValueError("水位不可為負")
    inside, outside = float(inside_head_m), float(outside_head_m)
    hi, lo = max(inside, outside), min(inside, outside)
    height = hi if wall_height_m is None else float(wall_height_m)
    if height <= 0:
        raise ValueError("wall_height_m 必須大於 0")
    if height + 1e-12 < hi:
        raise ValueError("wall_height_m 不可低於較高水位")

    # 兩側三角形水壓對牆底之力矩可相加（方向相反），各為 γh³/6。
    moment = gamma * (hi ** 3 - lo ** 3) / 6.0
    shear = gamma * (hi * hi - lo * lo) / 2.0
    return {"moment_kNm_per_m": moment, "shear_kN_per_m": shear,
            "net_head_m": hi - lo, "governing_head_m": hi,
            "inside_dominant": inside >= outside}


def _design_section(member, moment_kNm_per_m, shear_kN_per_m, thickness_m,
                    fc=21.0, fy=420.0, cover_mm=50.0, load_factor=1.7, wall=False):
    """以 rc_design.py 的撓曲、剪力、裂縫公式做每公尺條帶初步檢核。"""
    t_mm = thickness_m * 1000.0
    cc = {"fc_mpa": fc, "fy_mpa": fy, "cover_mm": cover_mm,
          "crack_limit_mm": 0.3}
    Mu = load_factor * moment_kNm_per_m
    Vu = load_factor * shear_kN_per_m
    # rc_design 的裂縫間距式要求正鋼筋應力；零水壓時以極小彎矩取得最小鋼筋配置。
    flex = RC.flexure_design(max(Mu, 1e-9), b_mm=1000.0, h_mm=t_mm, cc=cc)
    shear = RC.shear_check(Vu, b_mm=1000.0, h_mm=t_mm, cc=cc)
    if flex.get("ok") and flex.get("As_prov_mm2"):
        crack = RC.crack_width(flex["As_prov_mm2"], spacing_mm=flex["spacing_mm"],
                               h_mm=t_mm, cc=cc, M_service_kNm=moment_kNm_per_m)
    else:
        crack = {"ok": False, "w_mm": None, "limit_mm": 0.3}

    if wall:
        minimum = RC.wall_min_steel(1000.0, t_mm)
        As_secondary = max(minimum["As_horizontal_min_mm2"],
                           flex.get("As_prov_mm2", 0.0) / 3.0)
        secondary_basis = "牆水平筋 ρt=0.0025，且不小於主筋 1/3"
    else:
        d_mm = t_mm - cover_mm - 10.0
        As_secondary = max(0.0018 * 1000.0 * t_mm, 1.4 * 1000.0 * d_mm / fy)
        secondary_basis = "版溫度收縮筋與最小鋼筋取較大者"
    sec_name, sec_sp, sec_As = RC._pick_bars(As_secondary, cover_mm, t_mm,
                                             prefer=("D13", "D10"))

    return {
        "member": member, "thickness_mm": round(t_mm, 1),
        "M_service_kNm_per_m": round(moment_kNm_per_m, 3),
        "Mu_kNm_per_m": round(Mu, 3),
        "V_service_kN_per_m": round(shear_kN_per_m, 3),
        "Vu_kN_per_m": round(Vu, 3),
        "flexure": flex, "shear": shear, "crack": crack,
        "secondary_bar": sec_name, "secondary_spacing_mm": sec_sp,
        "secondary_As_mm2_per_m": round(sec_As, 1),
        "secondary_basis": secondary_basis,
        "ok": bool(flex.get("ok") and flex.get("spacing_ok", True)
                   and shear.get("ok") and crack.get("ok")),
    }


def structural_design(capacity_result, wall_t_m=0.25, base_t_m=0.25, water_level_m=None,
                      groundwater_head_m=0.0, fc_mpa=21.0, fy_mpa=420.0, cover_mm=50.0,
                      load_factor=1.7, buoyancy_fs_min=1.1):
    """沉砂池池壁／底板初步 RC 配筋與空池浮力檢核。

    `groundwater_head_m` 定義為地下室外地水位高出池底板底面的高度。
    池壁同時比較「池內設計水位＋外側地下水」與「空池＋外側地下水」，
    取彎矩較大者；未計池外土壓力、地震、施工載重與溫度效應。
    """
    for name, value in (("wall_t_m", wall_t_m), ("base_t_m", base_t_m),
                        ("load_factor", load_factor)):
        if value <= 0:
            raise ValueError(f"{name} 必須大於 0")
    if min(fc_mpa, fy_mpa, cover_mm) <= 0:
        raise ValueError("混凝土強度、鋼筋強度與保護層必須大於 0")
    if groundwater_head_m < 0:
        raise ValueError("groundwater_head_m 不可為負")

    depth = float(capacity_result["depth_m"])
    inside = depth if water_level_m is None else float(water_level_m)
    if inside < 0 or inside > depth:
        raise ValueError(f"water_level_m 必須介於 0 與池深 {depth:g} m")
    outside_wall = min(float(groundwater_head_m), depth)
    scenarios = [("池內設計水位", inside, outside_wall)]
    if groundwater_head_m > 0:
        scenarios.append(("空池外水位", 0.0, outside_wall))
    wall_cases = []
    for name, hi, ho in scenarios:
        r = hydrostatic_force_moment(hi, ho, wall_height_m=depth)
        r.update(name=name, inside_head_m=hi, outside_head_m=ho)
        wall_cases.append(r)
    wall_load = max(wall_cases, key=lambda x: x["moment_kNm_per_m"])
    wall = _design_section("池壁（牆底控制斷面）", wall_load["moment_kNm_per_m"],
                           wall_load["shear_kN_per_m"], wall_t_m, fc_mpa, fy_mpa,
                           cover_mm, load_factor, wall=True)

    length, width = float(capacity_result["length_m"]), float(capacity_result["width_m"])
    base = None
    if groundwater_head_m > 0:
        uplift_kpa = WATER_GAMMA * groundwater_head_m
        slab_weight_kpa = CONCRETE_GAMMA * base_t_m
        net_kpa = max(0.0, uplift_kpa - slab_weight_kpa)
        span = min(length, width)
        # 四周與池壁整體澆置，保守取固定端負彎矩 wL²/12 設計上下層鋼筋。
        M_base = net_kpa * span ** 2 / 12.0
        V_base = net_kpa * span / 2.0
        slab = _design_section("池底板（固定端條帶）", M_base, V_base, base_t_m,
                                fc_mpa, fy_mpa, cover_mm, load_factor, wall=False)

        floor_volume = length * width * base_t_m
        wall_volume = (2.0 * depth * wall_t_m * (length + width)
                       - 4.0 * depth * wall_t_m ** 2)
        resisting_kN = (floor_volume + max(wall_volume, 0.0)) * CONCRETE_GAMMA
        uplift_kN = uplift_kpa * length * width
        fs = resisting_kN / uplift_kN if uplift_kN > 0 else float("inf")
        base = {
            "uplift_kPa": round(uplift_kpa, 3),
            "slab_weight_kPa": round(slab_weight_kpa, 3),
            "net_uplift_kPa": round(net_kpa, 3),
            "span_m": round(span, 3),
            "design": slab,
            "resisting_kN": round(resisting_kN, 1),
            "uplift_kN": round(uplift_kN, 1),
            "buoyancy_fs": round(fs, 3),
            "buoyancy_fs_min": buoyancy_fs_min,
            "buoyancy_ok": fs >= buoyancy_fs_min,
        }

    return {
        "wall_cases": wall_cases, "governing_wall_case": wall_load["name"],
        "wall": wall, "base": base,
        "water_level_m": round(inside, 3),
        "groundwater_head_m": round(float(groundwater_head_m), 3),
        "ok": bool(wall["ok"] and (base["design"]["ok"] and base["buoyancy_ok"] if base else True)),
        "limitations": [
            "初步檢核只計水壓力；未計池外土壓力、地震、施工載重、溫度與收縮效應。",
            "底板以四周固定之單向條帶 wL²/12 保守估算，未做版殼有限元素分析。",
            "未檢核錨定、搭接、剪力筋、基礎承載與開挖穩定；正式設計須由技師覆核。",
            "浮力安全係數門檻是工程預設值，非法規明定；應依個案與主管機關要求調整。",
        ],
    }


def outlet_and_overflow_design(design_q_m3s, outlet_head_m, outlet_d_m=None, orifice_cd=ORIFICE_CD,
                               overflow_head_m=None, overflow_length_m=None, weir_cw=WEIR_CW):
    """孔口出流與矩形溢流堰初步檢核。

    Q孔口 = Cd·A·√(2gh)；Q堰 = Cw·L·H^1.5。
    Cd、Cw 是常用工程係數，非法規明定；進出口形狀、阻塞與淹沒效應須個案修正。
    """
    if design_q_m3s <= 0 or outlet_head_m <= 0:
        raise ValueError("design_q_m3s 與 outlet_head_m 必須大於 0")
    if orifice_cd <= 0 or weir_cw <= 0:
        raise ValueError("孔口與堰流係數必須大於 0")
    if outlet_d_m is not None and outlet_d_m <= 0:
        raise ValueError("outlet_d_m 必須大於 0")

    required_area = design_q_m3s / (orifice_cd * math.sqrt(2.0 * 9.81 * outlet_head_m))
    sized_d = math.sqrt(4.0 * required_area / math.pi)
    d = sized_d if outlet_d_m is None else float(outlet_d_m)
    area = math.pi * d ** 2 / 4.0
    outlet_capacity = orifice_cd * area * math.sqrt(2.0 * 9.81 * outlet_head_m)
    outlet = {
        "design_q_m3s": design_q_m3s, "head_m": outlet_head_m,
        "cd": orifice_cd, "required_area_m2": round(required_area, 6),
        "sized_diameter_m": round(sized_d, 4), "diameter_m": round(d, 4),
        "capacity_m3s": round(outlet_capacity, 5),
        "ok": outlet_capacity >= design_q_m3s - 1e-12,
        "sized": outlet_d_m is None,
    }

    overflow = None
    if overflow_head_m is not None:
        if overflow_head_m <= 0:
            raise ValueError("overflow_head_m 必須大於 0")
        required_length = design_q_m3s / (weir_cw * overflow_head_m ** 1.5)
        length = required_length if overflow_length_m is None else float(overflow_length_m)
        if length <= 0:
            raise ValueError("overflow_length_m 必須大於 0")
        capacity = weir_cw * length * overflow_head_m ** 1.5
        overflow = {
            "design_q_m3s": design_q_m3s, "head_m": overflow_head_m,
            "cw": weir_cw, "required_length_m": round(required_length, 4),
            "length_m": round(length, 4), "capacity_m3s": round(capacity, 5),
            "ok": capacity >= design_q_m3s - 1e-12, "sized": overflow_length_m is None,
        }
    return {
        "outlet": outlet, "overflow": overflow,
        "note": "孔口與溢流堰各自以完整設計流量檢核（全量備援的保守假設），不把兩者容量相加。",
        "limitations": [
            "Cd、Cw 為常用經驗係數，應依孔口形狀、堰型、進流條件與模型試驗修正。",
            "未計出口淹沒、尾水、阻塞、攔污柵與消能；出水口底高仍須依排水路常水位檢核。",
        ],
    }


def format_report(r):
    p = r["production"]
    kind = "臨時性" if p["kind"] == "temporary" else "永久性"
    out = [f"沉砂設施容量計算（水保規範第 35、92、93 條）｜{kind}｜年期 {p['years']:g} 年",
           f"USLE：Am = {p['Am_t_ha_yr']:.2f} 公噸/公頃/年 = {p['m3_per_ha_yr']:.2f} m³/公頃/年"
           f"（1 m³ = {SOIL_DENSITY} 公噸，第 35 條）", ""]
    out.append(f"泥砂生產量（第 92 條，USLE × {p['usle_factor']:g}）：")
    for x in p["parts"]:
        floor = f"下限 {x['floor_m3']:.0f} m³" if x["floor_m3_per_ha"] else "無下限"
        out.append(f"  - {x['part']} {x['area_ha']:.3f} ha：USLE {x['computed_m3']:.1f} m³、"
                   f"{floor} → 採 {x['used_m3']:.1f} m³（{x['governed_by']}）")
    out.append(f"  合計 {p['production_m3']:.1f} m³（有效面積 {p['effective_ha']:.3f} ha）")
    out.append("")
    out.append(f"設計容量（第 93 條）＝ {r['capacity_m3']:.1f} m³")
    out.append(f"深度 {r['depth_m']:.2f} m → 池底面積 {r['footprint_m2']:.1f} m²，"
               f"約 {r['length_m']:.1f} m × {r['width_m']:.1f} m（長寬比 {r['side_ratio']:g}）")
    out.append(f"單位面積沉砂量 {r['rate_m3_per_ha']:.1f} m³/ha")
    out.append("")
    out.append("檢核：")
    out += [f"  [{'OK' if c['ok'] else '注意'}] {c['item']}：{c['msg']}" for c in r["checks"]]
    if r["floors_govern"]:
        out.append(f"  ※ 由下限控制的部分：{'、'.join(r['floors_govern'])}（第 92 條）")
    out.append(f"  維護：{r['cleaning']}（第 93 條）")

    if r.get("structure"):
        s = r["structure"]
        out.append("")
        out.append("結構初步檢核（RC 配筋；非正式施工圖）")
        out.append(f"  控制牆況：{s['governing_wall_case']}；池內水位 {s['water_level_m']:.2f} m、"
                   f"外側地下水 {s['groundwater_head_m']:.2f} m")
        for member in (s["wall"], (s.get("base") or {}).get("design")):
            if not member:
                continue
            flex, shear, crack = member["flexure"], member["shear"], member["crack"]
            bar = flex.get("bar", "—")
            sp = flex.get("spacing_mm", "—")
            spacing_max = flex.get("spacing_max_mm")
            spacing_txt = ("不受水壓控制" if not spacing_max or spacing_max > 10000
                           else f"{spacing_max:g} mm")
            out.append(
                f"  {member['member']} t={member['thickness_mm']/1000:.2f} m："
                f"M={member['M_service_kNm_per_m']:.2f} kN·m/m → Mu={member['Mu_kNm_per_m']:.2f}；"
                f"主筋 {bar}@{sp} mm，φMn={flex.get('phiMn_kNm', 0):.2f} kN·m/m；"
                f"剪力 φVc={shear.get('phiVc_kN', 0):.2f} kN/m；"
                f"裂縫 {crack.get('w_mm', '—')} mm、"
                f"間距上限 {spacing_txt}"
            )
            out.append(
                f"    次要筋 {member['secondary_bar']}@{member['secondary_spacing_mm']} mm"
                f"（{member['secondary_As_mm2_per_m']:.0f} mm²/m；{member['secondary_basis']}）"
                f" → {'OK' if member['ok'] else '不通過'}"
            )
        if s.get("base"):
            b = s["base"]
            out.append(
                f"  空池浮力：上浮 {b['uplift_kPa']:.2f} kPa、底板自重 {b['slab_weight_kPa']:.2f} kPa、"
                f"淨上浮 {b['net_uplift_kPa']:.2f} kPa；FS={b['buoyancy_fs']:.2f}"
                f"（門檻 {b['buoyancy_fs_min']:.2f}）→ {'OK' if b['buoyancy_ok'] else '不通過'}"
            )
        else:
            out.append("  空池浮力：未提供地下水資料，未執行（不得視為已通過）。")
        out.append(f"  綜合初步判定：{'OK' if s['ok'] else '不通過／需調整斷面'}")
        out.append("  ※ " + "；".join(s["limitations"]))

    if r.get("outlet"):
        h = r["outlet"]
        o = h["outlet"]
        out.append("")
        out.append("出水口與溢流初步水理（孔口／矩形堰）")
        out.append(
            f"  孔口：Q={o['design_q_m3s']:.4f} m³/s、水頭 {o['head_m']:.2f} m、Cd={o['cd']:.2f} → "
            f"需求孔徑 {o['sized_diameter_m']*1000:.0f} mm；採 D={o['diameter_m']*1000:.0f} mm，"
            f"容量 {o['capacity_m3s']:.4f} m³/s → {'OK' if o['ok'] else '不足'}"
        )
        if h.get("overflow"):
            w = h["overflow"]
            out.append(
                f"  矩形溢流堰：Q={w['design_q_m3s']:.4f} m³/s、溢流水頭 {w['head_m']:.2f} m、"
                f"Cw={w['cw']:.2f} → 需求長度 {w['required_length_m']:.2f} m；"
                f"採 L={w['length_m']:.2f} m，容量 {w['capacity_m3s']:.4f} m³/s"
                f" → {'OK' if w['ok'] else '不足'}"
            )
        out.append(f"  ※ {h['note']}")
        out.append("  ※ " + "；".join(h["limitations"]))
    return "\n".join(out)


def selftest():
    """手算對帳（每項都可獨立驗算）。"""
    cases = []

    def check(name, got, want, tol=1e-6):
        ok = abs(got - want) <= tol * max(1.0, abs(want))
        cases.append((ok, f"{name}: {got:.6g}（預期 {want:.6g}）"))

    # 第 35 條：Am = 8000×0.05×4×0.05×0.5 = 40 t/ha/yr；÷1.4 = 28.5714 m³/ha/yr
    check("USLE Am", usle(8000, 0.05, 4, 0.05, 0.5), 40.0)
    check("年體積", annual_volume_per_ha(40.0), 40 / 1.4)
    # 第 92 條下限：開挖 1.2 ha×250=300、其他 0.6 ha×30=18（USLE 值都較小）→ 318
    p = sediment_production(2.0, 1.2, 0.2, "temporary", 1.0, Am=40.0)
    check("臨時泥砂生產量（下限控制）", p["production_m3"], 318.0)
    check("有效面積（扣不透水 0.2 ha）", p["effective_ha"], 1.8)
    # 第 93 條：臨時再乘 1.5 → 477
    r = analyse(2.0, 1.2, 0.2, "temporary", 1.0, depth=2.0, Am=40.0)
    check("臨時設計容量", r["capacity_m3"], 477.0)
    check("池底面積", r["footprint_m2"], 477.0 / 2.0)
    # 永久性：開挖部分不打折、無下限；其他部分 30 m³/ha 下限
    p2 = sediment_production(2.0, 1.2, 0.0, "permanent", 1.0, Am=280.0)   # 200 m³/ha/yr
    check("永久性開挖部分（USLE 控制）", p2["parts"][0]["used_m3"], 240.0)
    check("永久性其他部分（USLE 控制）", p2["parts"][1]["used_m3"], 160.0)
    cases.append((p2["parts"][1]["governed_by"] == "USLE", "永久性其他部分：USLE 160 > 下限 24 → USLE 控制"))
    # 土壤流失量很小時，30 m³/ha 下限要接手：Am=7 → 5 m³/ha/yr × 0.8 ha = 4 < 24
    p2b = sediment_production(2.0, 1.2, 0.0, "permanent", 1.0, Am=7.0)
    check("永久性其他部分（下限接手）", p2b["parts"][1]["used_m3"], 24.0)
    cases.append((p2b["parts"][1]["governed_by"] == "下限", "永久性其他部分：5×0.8=4 < 24 → 由下限控制"))
    # 深度超出範圍要調整並標記
    r2 = analyse(1.0, 0.0, 0.0, "permanent", 1.0, depth=5.0, Am=140.0)
    check("深度上限調整", r2["depth_m"], 3.5)
    cases.append((all(c["ok"] for c in r2["checks"]) is False, "深度超限會有注意事項"))
    # 年期加乘（下限不隨年期放大）
    p3 = sediment_production(1.0, 0.0, 0.0, "permanent", 3.0, Am=140.0)   # 100 m³/ha/yr
    check("3 年期 USLE 量", p3["production_m3"], 300.0)

    # 選配結構／水理公式手算對帳
    hyd = hydrostatic_force_moment(2.0, 0.0)
    check("全池水壓彎矩 γh³/6", hyd["moment_kNm_per_m"], 9.81 * 2.0 ** 3 / 6.0)
    check("全池水壓剪力 γh²/2", hyd["shear_kN_per_m"], 9.81 * 2.0 ** 2 / 2.0)
    hyd2 = hydrostatic_force_moment(2.0, 1.0)
    check("內外水位差彎矩", hyd2["moment_kNm_per_m"],
          9.81 * (2 ** 3 - 1 ** 3) / 6)
    check("內外水位差剪力", hyd2["shear_kN_per_m"],
          9.81 * (2 ** 2 - 1 ** 2) / 2)

    out = outlet_and_overflow_design(0.1, 1.0, overflow_head_m=0.3)
    check("孔口需求孔徑", out["outlet"]["sized_diameter_m"],
          math.sqrt(4 * (0.1 / (0.62 * math.sqrt(2 * 9.81 * 1.0))) / math.pi), tol=1e-4)
    out2 = outlet_and_overflow_design(0.1, 1.0, outlet_d_m=0.3,
                                       overflow_head_m=0.3, overflow_length_m=2.0)
    check("孔口容量 CdA√(2gh)", out2["outlet"]["capacity_m3s"],
          0.62 * (math.pi * 0.3 ** 2 / 4) * math.sqrt(2 * 9.81), tol=1e-4)
    check("矩形堰容量 1.84LH^1.5", out2["overflow"]["capacity_m3s"],
          1.84 * 2.0 * 0.3 ** 1.5, tol=1e-4)

    st = structural_design(r, wall_t_m=0.30, base_t_m=0.30, water_level_m=2.0,
                           groundwater_head_m=0.5, fc_mpa=21, fy_mpa=420,
                           cover_mm=50, load_factor=1.7)
    cases.append((st["wall"]["flexure"]["As_prov_mm2"]
                  >= st["wall"]["flexure"]["As_req_mm2"],
                  "池壁主筋實際量 >= 需求量"))
    cases.append((st["base"]["design"]["secondary_As_mm2_per_m"] > 0,
                  "底板次要筋可選配"))
    check("地下水浮力 = γw·h", st["base"]["uplift_kPa"], 9.81 * 0.5, tol=1e-4)
    for ok, msg in cases:
        print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    return 0 if all(ok for ok, _ in cases) else 1


def main():
    ap = argparse.ArgumentParser(description="沉砂設施容量設計（水保第 35、92、93 條）")
    ap.add_argument("--area", type=float, help="計畫開發面積 ha")
    ap.add_argument("--excavated", type=float, default=0.0, help="開挖整地部分 ha")
    ap.add_argument("--impervious", type=float, default=0.0, help="不透水鋪面 ha（第 92 條得扣除）")
    ap.add_argument("--kind", choices=["temporary", "permanent"], default="temporary")
    ap.add_argument("--years", type=float, default=1.0, help="年期（年），預設 1")
    ap.add_argument("--Am", type=float, help="土壤流失量 公噸/公頃/年（給了就不必給 Rm/Km/LS/C/P）")
    ap.add_argument("--Rm", type=float, help="降雨沖蝕指數")
    ap.add_argument("--Km", type=float, help="土壤沖蝕指數")
    ap.add_argument("--LS", type=float, help="坡長×坡度因子")
    ap.add_argument("--C", type=float, help=f"覆蓋與管理因子（開挖整地下限 {C_MIN}）")
    ap.add_argument("--P", type=float, help=f"水土保持處理因子（開挖整地下限 {P_MIN}）")
    ap.add_argument("--depth", type=float, help=f"池深 m（{DEPTH_MIN}~{DEPTH_MAX}）")
    ap.add_argument("--ratio", type=float, default=1.5, help="長寬比，預設 1.5")
    ap.add_argument("--structure", action="store_true",
                    help="加做池壁／底板 RC 配筋與空池浮力初步檢核")
    ap.add_argument("--wall-t", type=float, default=0.25, help="池壁厚度 m，預設 0.25")
    ap.add_argument("--bottom-t", type=float, default=0.25, help="池底板厚度 m，預設 0.25")
    ap.add_argument("--fc-mpa", type=float, default=21.0, help="混凝土 fc' MPa，預設 21")
    ap.add_argument("--fy-mpa", type=float, default=420.0, help="鋼筋 fy MPa，預設 420")
    ap.add_argument("--cover", type=float, default=50.0, help="鋼筋保護層 mm，預設 50")
    ap.add_argument("--water-level", type=float,
                    help="池內設計水位（自池底起算 m）；未給時取全池深")
    ap.add_argument("--groundwater-head", type=float, default=0.0,
                    help="外側地下水高出池底板的高度 m，預設 0（未知時不得視為已檢核）")
    ap.add_argument("--load-factor", type=float, default=1.7,
                    help="水壓載重放大係數，預設 1.7")
    ap.add_argument("--buoyancy-fs", type=float, default=1.1,
                    help="空池浮力最小安全係數，預設 1.1（工程預設，非法規值）")
    ap.add_argument("--design-q", type=float,
                    help="出水口／溢流設計流量 m³/s；有給才做水理檢核")
    ap.add_argument("--outlet-head", type=float,
                    help="孔口中心至設計水位的有效水頭 m")
    ap.add_argument("--outlet-d", type=float,
                    help="指定孔口直徑 m；未給時由設計流量反算")
    ap.add_argument("--orifice-cd", type=float, default=ORIFICE_CD,
                    help=f"孔口流量係數，預設 {ORIFICE_CD}")
    ap.add_argument("--overflow-head", type=float,
                    help="矩形溢流堰設計水頭 m；有給才做溢流檢核")
    ap.add_argument("--overflow-length", type=float,
                    help="指定溢流堰長 m；未給時由設計流量反算")
    ap.add_argument("--weir-cw", type=float, default=WEIR_CW,
                    help=f"矩形堰係數，預設 {WEIR_CW}（SI 式）")
    ap.add_argument("--selftest", action="store_true", help="跑手算對帳")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.area is None:
        ap.error("需要 --area（或 --selftest）")
    for name, v, floor in (("C", a.C, C_MIN), ("P", a.P, P_MIN)):
        if v is not None and v < floor:
            ap.error(f"{name}={v} 低於第 35 條開挖整地下限 {floor}")
    r = analyse(a.area, a.excavated, a.impervious, a.kind, a.years, a.depth, a.ratio,
                Am=a.Am, Rm=a.Rm, Km=a.Km, LS=a.LS, C=a.C, P=a.P)
    if a.structure:
        r["structure"] = structural_design(
            r, wall_t_m=a.wall_t, base_t_m=a.bottom_t,
            water_level_m=a.water_level, groundwater_head_m=a.groundwater_head,
            fc_mpa=a.fc_mpa, fy_mpa=a.fy_mpa, cover_mm=a.cover,
            load_factor=a.load_factor, buoyancy_fs_min=a.buoyancy_fs,
        )
    if a.design_q is not None:
        if a.outlet_head is None:
            ap.error("使用 --design-q 時必須提供 --outlet-head")
        r["outlet"] = outlet_and_overflow_design(
            a.design_q, a.outlet_head, outlet_d_m=a.outlet_d,
            orifice_cd=a.orifice_cd, overflow_head_m=a.overflow_head,
            overflow_length_m=a.overflow_length, weir_cw=a.weir_cw,
        )
    elif a.outlet_head is not None or a.outlet_d is not None or a.overflow_head is not None:
        ap.error("孔口／溢流參數需搭配 --design-q 使用")
    print(format_report(r))
    failed = []
    if r.get("structure") and not r["structure"]["ok"]:
        failed.append("結構初步檢核")
    if r.get("outlet"):
        if not r["outlet"]["outlet"]["ok"]:
            failed.append("孔口出水容量")
        if r["outlet"].get("overflow") and not r["outlet"]["overflow"]["ok"]:
            failed.append("溢流容量")
    if failed:
        print(f"\n[不通過] {'、'.join(failed)}；請調整尺寸或參數後重跑。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
