"""Box-culvert inlet/outlet control hydraulics (公路排水設計規範 §6.2, 附錄 N/O).

Design headwater is the larger of inlet control and outlet control
(§6.2.1 item 3).  Flow is split equally between identical cells.

Inlet control uses the FHWA HDS-5 (2005) regression equations, which are the
source of the 附錄 N nomographs (SI form, Ku = 1.811):

  unsubmerged form 1  HW/D = Hc/D + K·X^M − 0.5·S      (X ≤ 3.5)
  unsubmerged form 2  HW/D = K·X^M                     (X ≤ 3.5)
  submerged           HW/D = c·X² + Y − 0.5·S           (X ≥ 4.0)
  X = Ku·Q/(A·D^0.5); 3.5 < X < 4.0 is linearly interpolated.

The regression equations and the hand-drawn nomographs differ by a few
percent (附錄 N.2 example: 1.86 vs 1.75 for 30°~75° flares).

Outlet control follows 附錄 O, eqs. O-1/O-2:

  Hw = Hf + h0 − L·S0
  Hf = (1 + Ke + 19.6·n²·L / R^1.33)·V²/2g
  h0 = TW when TW ≥ D, otherwise max(TW, (dc + D)/2)       (§6.2.2)
"""

from __future__ import annotations

import math
from typing import Any, Mapping

G = 9.81
KU_SI = 1.811
X_UNSUBMERGED_MAX = 3.5
X_SUBMERGED_MIN = 4.0

# HDS-5 Table A.1 (concrete box) with matching 附錄 O 表 O-1 Ke values.
# M is written as 2/3 rather than the table's rounded 0.667; the difference is
# under 0.02% and keeps the exponent exact for hand checks.
_M_TWO_THIRDS = 2.0 / 3.0
INLET_TYPES: dict[str, dict[str, Any]] = {
    "wingwall_30_75": {
        "label": "翼牆張角 30°～75°（方邊頂緣）",
        "chart": "附錄 N.2 型式(1)／HDS-5 Chart 8",
        "form": 1, "K": 0.026, "M": 1.0, "c": 0.0347, "Y": 0.81, "Ke": 0.4,
    },
    "wingwall_90_15": {
        "label": "翼牆張角 90° 及 15°（端牆或小張角，方邊）",
        "chart": "附錄 N.2 型式(2)／HDS-5 Chart 8",
        "form": 1, "K": 0.061, "M": 0.75, "c": 0.0400, "Y": 0.80, "Ke": 0.5,
    },
    "wingwall_0": {
        "label": "翼牆張角 0°（平行延伸側牆，方邊）",
        "chart": "附錄 N.2 型式(3)／HDS-5 Chart 8",
        "form": 1, "K": 0.061, "M": 0.75, "c": 0.0423, "Y": 0.82, "Ke": 0.7,
    },
    "wingwall_45_top_bevel": {
        "label": "翼牆張角 45°＋頂緣斜切（d=0.043D）",
        "chart": "HDS-5 Chart 9",
        "form": 2, "K": 0.510, "M": _M_TWO_THIRDS, "c": 0.0309, "Y": 0.80, "Ke": 0.2,
    },
    "wingwall_18_34_top_bevel": {
        "label": "翼牆張角 18°～33.7°＋頂緣斜切（d=0.083D）",
        "chart": "HDS-5 Chart 9",
        "form": 2, "K": 0.486, "M": _M_TWO_THIRDS, "c": 0.0249, "Y": 0.83, "Ke": 0.2,
    },
    "headwall_chamfer": {
        "label": "90° 端牆、無翼牆，19 mm 倒角（視同方邊）",
        "chart": "HDS-5 Chart 10",
        "form": 2, "K": 0.515, "M": _M_TWO_THIRDS, "c": 0.0375, "Y": 0.79, "Ke": 0.5,
    },
    "headwall_bevel_45": {
        "label": "90° 端牆、無翼牆，45° 斜切邊",
        "chart": "HDS-5 Chart 10",
        "form": 2, "K": 0.495, "M": _M_TWO_THIRDS, "c": 0.0314, "Y": 0.82, "Ke": 0.2,
    },
    "headwall_bevel_33": {
        "label": "90° 端牆、無翼牆，33.7° 斜切邊",
        "chart": "HDS-5 Chart 10",
        "form": 2, "K": 0.486, "M": _M_TWO_THIRDS, "c": 0.0252, "Y": 0.865, "Ke": 0.2,
    },
}

# 公路排水設計規範 表 6-1：箱涵最小淨寬 × 淨高。
MIN_CLEAR_WIDTH_M = 1.0
MIN_CLEAR_HEIGHT_M = 1.0
HW_D_LIMIT_DEFAULT = 1.5

# §6.5 / §6.6 geometry rules: key -> (item, limit, relation, mandatory?).
HEADWORK_RULES: dict[str, tuple[str, float, str, bool]] = {
    "headwall_top_above_crown_m": ("端牆頂高出涵頂（§6.5.1）", 0.30, "ge", True),
    "headwall_thickness_m": ("端牆厚度（§6.5.1 宜大於 25 cm）", 0.25, "ge", False),
    "wingwall_angle_deg": ("翼牆與端牆夾角 θ（§6.5.2）", 120.0, "le", False),
    "wingwall_tail_height_m": ("翼牆尾端淨高（§6.5.2）", 0.10, "ge", True),
    "wingwall_thickness_m": ("翼牆厚度（§6.5.2 宜大於 15 cm）", 0.15, "ge", False),
    "drop_inlet_headwall_above_full_m": ("落水井：端牆頂高出滿水位（§6.6）", 0.30, "ge", True),
    "drop_inlet_floor_below_invert_m": ("落水井：井底低於涵底（§6.6）", 0.20, "ge", True),
}


class CulvertHydraulicsError(ValueError):
    pass


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise CulvertHydraulicsError("%s 必須是數字" % name) from exc
    if not math.isfinite(v):
        raise CulvertHydraulicsError("%s 必須是有限數字" % name)
    if minimum is not None and v < minimum:
        raise CulvertHydraulicsError("%s 不可小於 %s" % (name, minimum))
    return v


def critical_depth(q_cell: float, width: float, height: float) -> float:
    """Critical depth of a rectangular cell, capped at the clear height."""
    if q_cell <= 0.0:
        return 0.0
    return min(((q_cell / width) ** 2 / G) ** (1.0 / 3.0), height)


def normal_depth(q_cell: float, width: float, height: float, slope: float,
                 manning_n: float) -> float | None:
    """Manning normal depth of one cell; None when it exceeds the clear height."""
    if q_cell <= 0.0:
        return 0.0
    if slope <= 0.0:
        return None

    def flow(y: float) -> float:
        a = width * y
        r = a / (width + 2.0 * y)
        return a * r ** (2.0 / 3.0) * math.sqrt(slope) / manning_n

    if flow(height) < q_cell:
        return None
    lo, hi = 0.0, height
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if flow(mid) < q_cell:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _unsubmerged_hw_d(x: float, dc: float, height: float, slope: float,
                      coef: Mapping[str, Any]) -> float:
    base = coef["K"] * x ** coef["M"]
    if coef["form"] == 1:
        return 1.5 * dc / height + base - 0.5 * slope
    return base


def _submerged_hw_d(x: float, slope: float, coef: Mapping[str, Any]) -> float:
    return coef["c"] * x * x + coef["Y"] - 0.5 * slope


def inlet_control(q_cell: float, width: float, height: float, slope: float,
                  inlet_type: str) -> dict[str, Any]:
    coef = INLET_TYPES.get(inlet_type)
    if coef is None:
        raise CulvertHydraulicsError(
            "未知進口型式：%s（可用：%s）" % (inlet_type, "、".join(INLET_TYPES))
        )
    area = width * height
    x = KU_SI * q_cell / (area * math.sqrt(height))
    dc = critical_depth(q_cell, width, height)
    if q_cell <= 0.0:
        hw_d, regime = 0.0, "無流量"
    elif x <= X_UNSUBMERGED_MAX:
        hw_d, regime = _unsubmerged_hw_d(x, dc, height, slope, coef), "非潛沒（堰流）"
    elif x >= X_SUBMERGED_MIN:
        hw_d, regime = _submerged_hw_d(x, slope, coef), "潛沒（孔口流）"
    else:
        # Interpolate between the end points of the two curves; the
        # unsubmerged end point needs dc at the flow where X = 3.5.
        q_lo = X_UNSUBMERGED_MAX * area * math.sqrt(height) / KU_SI
        lo = _unsubmerged_hw_d(X_UNSUBMERGED_MAX, critical_depth(q_lo, width, height),
                               height, slope, coef)
        hi = _submerged_hw_d(X_SUBMERGED_MIN, slope, coef)
        w = (x - X_UNSUBMERGED_MAX) / (X_SUBMERGED_MIN - X_UNSUBMERGED_MAX)
        hw_d, regime = lo + w * (hi - lo), "過渡區（內插）"
    hw_d = max(hw_d, 0.0)
    return {
        "inlet_type": inlet_type,
        "inlet_label": coef["label"],
        "chart": coef["chart"],
        "coefficients": {k: coef[k] for k in ("form", "K", "M", "c", "Y")},
        "discharge_intensity_X": x,
        "critical_depth_m": dc,
        "regime": regime,
        "hw_over_d": hw_d,
        "headwater_m": hw_d * height,
    }


def outlet_control(q_cell: float, width: float, height: float, slope: float,
                   length_m: float, manning_n: float, ke: float,
                   tailwater_m: float) -> dict[str, Any]:
    area = width * height
    radius = area / (2.0 * (width + height))
    velocity = q_cell / area
    dc = critical_depth(q_cell, width, height)
    friction = 19.6 * manning_n ** 2 * length_m / radius ** 1.33
    hf = (1.0 + ke + friction) * velocity ** 2 / (2.0 * G)
    if tailwater_m >= height:
        h0, h0_basis = tailwater_m, "下游水深 TW（高過涵頂）"
    else:
        avg = 0.5 * (dc + height)
        h0, h0_basis = (
            (tailwater_m, "下游水深 TW") if tailwater_m > avg
            else (avg, "(dc + D)/2")
        )
    hw = max(hf + h0 - length_m * slope, 0.0) if q_cell > 0.0 else 0.0
    return {
        "Ke": ke,
        "full_flow_velocity_m_s": velocity,
        "hydraulic_radius_full_m": radius,
        "friction_term": friction,
        "head_loss_m": hf,
        "critical_depth_m": dc,
        "tailwater_m": tailwater_m,
        "h0_m": h0,
        "h0_basis": h0_basis,
        "fall_m": length_m * slope,
        "headwater_m": hw,
        "hw_over_d": hw / height,
    }


def analyse(
    *,
    design_flow_m3s: float,
    clear_width_m: float,
    clear_height_m: float,
    cell_count: int = 1,
    length_m: float,
    slope: float,
    manning_n: float = 0.014,
    inlet_type: str = "wingwall_30_75",
    entrance_loss_ke: float | None = None,
    tailwater_depth_m: float = 0.0,
    allowable_headwater_m: float | None = None,
    hw_d_limit: float = HW_D_LIMIT_DEFAULT,
    outlet_velocity_limit_m_s: float | None = None,
    headworks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    q = _num("design_flow_m3s", design_flow_m3s, minimum=0.0)
    b = _num("clear_width_m", clear_width_m, minimum=1e-6)
    d = _num("clear_height_m", clear_height_m, minimum=1e-6)
    cells = int(_num("cell_count", cell_count, minimum=1))
    length = _num("length_m", length_m, minimum=0.0)
    s0 = _num("slope", slope, minimum=0.0)
    n = _num("manning_n", manning_n, minimum=1e-6)
    tw = _num("tailwater_depth_m", tailwater_depth_m, minimum=0.0)
    hw_d_lim = _num("hw_d_limit", hw_d_limit, minimum=0.0)

    q_cell = q / cells
    inlet = inlet_control(q_cell, b, d, s0, inlet_type)
    ke = (INLET_TYPES[inlet_type]["Ke"] if entrance_loss_ke is None
          else _num("entrance_loss_ke", entrance_loss_ke, minimum=0.0))
    outlet = outlet_control(q_cell, b, d, s0, length, n, ke, tw)

    if outlet["headwater_m"] > inlet["headwater_m"]:
        control, hw = "出口控制", outlet["headwater_m"]
    else:
        control, hw = "進口控制", inlet["headwater_m"]
    hw_d = hw / d

    # Outlet depth (HDS-5): inlet control -> barrel normal depth;
    # outlet control -> dc, TW or D depending on tailwater.
    yn = normal_depth(q_cell, b, d, s0, n)
    dc = inlet["critical_depth_m"]
    if control == "進口控制":
        y_out = d if yn is None else max(yn, 1e-9)
        y_basis = "涵內正常水深" if yn is not None else "正常水深超過淨高，取 D"
    elif tw >= d:
        y_out, y_basis = d, "下游水位高過涵頂，取 D"
    elif tw > dc:
        y_out, y_basis = tw, "下游水深 TW"
    else:
        y_out, y_basis = max(dc, 1e-9), "臨界水深 dc"
    v_out = q_cell / (b * y_out) if q_cell > 0.0 else 0.0

    checks: list[dict[str, Any]] = [
        {
            "item": "箱涵最小淨寬（表 6-1）",
            "value": b, "limit": MIN_CLEAR_WIDTH_M,
            "ok": b >= MIN_CLEAR_WIDTH_M - 1e-12, "unit": "m", "relation": "ge",
        },
        {
            "item": "箱涵最小淨高（表 6-1）",
            "value": d, "limit": MIN_CLEAR_HEIGHT_M,
            "ok": d >= MIN_CLEAR_HEIGHT_M - 1e-12, "unit": "m", "relation": "ge",
        },
        {
            "item": "設計上游水深 HW/D（§6.2.1 第4項，%s）" % control,
            "value": hw_d, "limit": hw_d_lim,
            "ok": hw_d <= hw_d_lim + 1e-12, "unit": "-", "relation": "le",
            "severity": "advisory",
        },
        {
            "item": "滿管流速（對照 RC 無常流 12 m/s，§85 二(二)）",
            "value": outlet["full_flow_velocity_m_s"], "limit": 12.0,
            "ok": outlet["full_flow_velocity_m_s"] <= 12.0 + 1e-12,
            "unit": "m/s", "relation": "le", "severity": "advisory",
        },
    ]
    warnings: list[str] = [
        "§6.2.1 第4項原文為 HW/D「宜儘量控制在1.5以上」，依水理意義判讀為「以下」；"
        "此項列為提醒，上限可用 hw_d_limit 調整。",
    ]
    if allowable_headwater_m is not None:
        hw_allow = _num("allowable_headwater_m", allowable_headwater_m, minimum=0.0)
        checks.append({
            "item": "設計上游水深 ≤ 最高容許上游水深（§6.2.1 第1項）",
            "value": hw, "limit": hw_allow,
            "ok": hw <= hw_allow + 1e-12, "unit": "m", "relation": "le",
        })
    else:
        warnings.append(
            "未輸入最高容許上游水深（路堤容許浸水高度），§6.2.1 第1項未檢核。"
        )
    if outlet_velocity_limit_m_s is not None:
        v_lim = _num("outlet_velocity_limit_m_s", outlet_velocity_limit_m_s, minimum=0.0)
        checks.append({
            "item": "出口流速 ≤ 下游容許流速（§6.4）",
            "value": v_out, "limit": v_lim,
            "ok": v_out <= v_lim + 1e-12, "unit": "m/s", "relation": "le",
        })

    for key, raw in (headworks or {}).items():
        rule = HEADWORK_RULES.get(key)
        if rule is None or raw is None or raw == "":
            continue
        item, limit, relation, mandatory = rule
        value = _num(key, raw)
        ok = value >= limit - 1e-12 if relation == "ge" else value <= limit + 1e-12
        check = {"item": item, "value": value, "limit": limit, "ok": ok,
                 "unit": "°" if key.endswith("_deg") else "m", "relation": relation}
        if not mandatory:
            check["severity"] = "advisory"
        checks.append(check)

    if hw > d + 1e-9:
        warnings.append(
            "上游水深高於涵頂（HW/D=%.2f），進口潛沒；§6.1.2 第4項建議涵內維持明渠流。" % hw_d
        )
    if tw >= d:
        warnings.append("下游水深高於涵頂，出口潛沒、涵內滿流。")
    if control == "出口控制" and hw < 0.75 * d:
        warnings.append(
            "出口控制且 HW < 0.75D：附錄 O 滿流能量式僅為近似，"
            "低水頭時宜以迴水曲線計算。"
        )
    if cells > 1:
        warnings.append("多孔箱涵假設各孔同尺寸、流量平均分配（每孔 %.3f m³/s）。" % q_cell)
    warnings.append(
        "進口控制採 HDS-5 迴歸式，與附錄 N 線解圖約有 5～8% 差異；"
        "端牆、翼牆基腳須埋入沖刷線以下（§6.5），本計算未檢核沖刷深度。"
    )

    blocking = [c for c in checks if c.get("severity") != "advisory"]
    return {
        "engine": "culvert_hydraulics",
        "version": "0.1",
        "inputs": {
            "design_flow_m3s": q, "cell_count": cells, "clear_width_m": b,
            "clear_height_m": d, "length_m": length, "slope": s0,
            "manning_n": n, "inlet_type": inlet_type, "tailwater_depth_m": tw,
            "allowable_headwater_m": allowable_headwater_m, "hw_d_limit": hw_d_lim,
        },
        "flow_per_cell_m3s": q_cell,
        "inlet": inlet,
        "outlet": outlet,
        "governing": {"control": control, "headwater_m": hw, "hw_over_d": hw_d},
        "outlet_velocity": {
            "depth_m": y_out, "basis": y_basis, "velocity_m_s": v_out,
            "normal_depth_m": yn,
        },
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in blocking),
        "basis": [
            "公路排水設計規範 §6.1.4 表 6-1、§6.2.1～6.2.4、§6.5、§6.6",
            "附錄 N（HDS-5 2005 進口控制）、附錄 O 式 O-1／O-2、表 O-1 Ke",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    inlet, outlet, gov = result["inlet"], result["outlet"], result["governing"]
    lines = [
        "每孔流量 %.3f m³/s；進口型式：%s" % (result["flow_per_cell_m3s"], inlet["inlet_label"]),
        "進口控制 HW = %.3f m（HW/D %.3f，%s，X=%.2f）"
        % (inlet["headwater_m"], inlet["hw_over_d"], inlet["regime"],
           inlet["discharge_intensity_X"]),
        "出口控制 HW = %.3f m（Hf %.3f + h0 %.3f − LS %.3f；Ke %.2f）"
        % (outlet["headwater_m"], outlet["head_loss_m"], outlet["h0_m"],
           outlet["fall_m"], outlet["Ke"]),
        "設計上游水深 %.3f m（%s），出口流速 %.2f m/s（%s）"
        % (gov["headwater_m"], gov["control"],
           result["outlet_velocity"]["velocity_m_s"], result["outlet_velocity"]["basis"]),
    ]
    for c in result["checks"]:
        mark = "OK" if c["ok"] else ("NOTE" if c.get("severity") == "advisory" else "NG")
        sign = "≥" if c["relation"] == "ge" else "≤"
        lines.append("  [%s] %s：%.3f%s（%s %.3f）"
                     % (mark, c["item"], c["value"],
                        "" if c["unit"] == "-" else " " + c["unit"], sign, c["limit"]))
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="箱涵進口／出口控制水理（公路排水設計規範 §6.2）")
    ap.add_argument("--q", type=float, required=True, help="設計流量 m³/s")
    ap.add_argument("--width", type=float, required=True, help="每孔淨寬 m")
    ap.add_argument("--height", type=float, required=True, help="淨高 m")
    ap.add_argument("--cells", type=int, default=1)
    ap.add_argument("--length", type=float, required=True, help="涵長 m")
    ap.add_argument("--slope", type=float, default=0.005)
    ap.add_argument("--manning", type=float, default=0.014)
    ap.add_argument("--inlet", default="wingwall_30_75", choices=sorted(INLET_TYPES))
    ap.add_argument("--ke", type=float, default=None, help="自訂進口損失係數")
    ap.add_argument("--tw", type=float, default=0.0, help="下游水深 m")
    ap.add_argument("--hw-allow", type=float, default=None, help="最高容許上游水深 m")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyse(
        design_flow_m3s=a.q, clear_width_m=a.width, clear_height_m=a.height,
        cell_count=a.cells, length_m=a.length, slope=a.slope, manning_n=a.manning,
        inlet_type=a.inlet, entrance_loss_ke=a.ke, tailwater_depth_m=a.tw,
        allowable_headwater_m=a.hw_allow,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else format_report(r))
    raise SystemExit(0 if r["pass"] else 1)
