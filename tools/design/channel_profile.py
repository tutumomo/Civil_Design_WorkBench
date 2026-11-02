"""Water-surface profile of a prismatic open channel (standard step method).

Supports rectangular (side slope 0) and trapezoidal sections with uniform
Manning roughness.  The profile is marched upstream from a downstream control
depth; each step solves the energy equation

    z_u + y_u + V_u²/2g = z_d + y_d + V_d²/2g + L·(Sf_u + Sf_d)/2 + he

with Sf = (n·V / R^(2/3))².  The standard step method is the usual hand
calculation behind 公路排水設計規範 第四章 and 水土保持技術規範 §84; it is
one-dimensional and assumes no hydraulic jump, no bridge/culvert constriction
and no lateral inflow inside the modelled reach.

Profile classification follows the usual mild/steep + zone 1/2/3 scheme; it is
reported for the designer to read, not used as a check.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

G = 9.81


class ChannelProfileError(ValueError):
    pass


def _num(name: str, value: Any, *, minimum: float | None = None,
         maximum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ChannelProfileError("%s 必須是數字" % name) from exc
    if not math.isfinite(v):
        raise ChannelProfileError("%s 必須是有限數字" % name)
    if minimum is not None and v < minimum:
        raise ChannelProfileError("%s 不可小於 %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise ChannelProfileError("%s 不可大於 %s" % (name, maximum))
    return v


def geometry(bottom_width_m: float, side_slope_h_v: float, depth_m: float) -> dict[str, float]:
    b, m, y = bottom_width_m, side_slope_h_v, depth_m
    area = b * y + m * y * y
    top = b + 2.0 * m * y
    wetted = b + 2.0 * y * math.sqrt(1.0 + m * m)
    radius = area / wetted if wetted > 0.0 else 0.0
    return {
        "area_m2": area,
        "top_width_m": top,
        "wetted_perimeter_m": wetted,
        "hydraulic_radius_m": radius,
    }


def conveyance_flow(bottom_width_m: float, side_slope_h_v: float,
                    depth_m: float, slope: float, manning_n: float) -> float:
    if slope <= 0.0 or depth_m <= 0.0:
        return 0.0
    g = geometry(bottom_width_m, side_slope_h_v, depth_m)
    return (g["area_m2"] * g["hydraulic_radius_m"] ** (2.0 / 3.0)
            * math.sqrt(slope) / manning_n)


def normal_depth(q: float, bottom_width_m: float, side_slope_h_v: float,
                 slope: float, manning_n: float, depth_max: float) -> float | None:
    if q <= 0.0:
        return 0.0
    if slope <= 0.0:
        return None
    if conveyance_flow(bottom_width_m, side_slope_h_v, depth_max, slope, manning_n) < q:
        return None
    lo, hi = 0.0, depth_max
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        if conveyance_flow(bottom_width_m, side_slope_h_v, mid, slope, manning_n) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def critical_depth(q: float, bottom_width_m: float, side_slope_h_v: float,
                   depth_max: float) -> float:
    if q <= 0.0:
        return 0.0

    def froude_sq(y: float) -> float:
        g = geometry(bottom_width_m, side_slope_h_v, y)
        return q * q * g["top_width_m"] / (G * g["area_m2"] ** 3)

    # Froude number falls as depth grows in a prismatic section, so a root
    # exists in (0, depth_max] only when the full section is subcritical.
    if froude_sq(depth_max) >= 1.0:
        return depth_max
    lo, hi = 1e-6, depth_max
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        # froude_sq decreases with depth: f > 1 means the root is deeper.
        if froude_sq(mid) > 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _section_state(q: float, b: float, m: float, y: float,
                   slope: float, n: float) -> dict[str, float]:
    g = geometry(b, m, y)
    v = q / g["area_m2"] if g["area_m2"] > 0.0 else 0.0
    sf = (n * v / g["hydraulic_radius_m"] ** (2.0 / 3.0)) ** 2 if g["hydraulic_radius_m"] > 0 else 0.0
    froude = v / math.sqrt(G * (g["area_m2"] / g["top_width_m"])) if g["top_width_m"] > 0 else 0.0
    return {
        "depth_m": y,
        "velocity_m_s": v,
        "specific_energy_m": y + v * v / (2.0 * G),
        "friction_slope": sf,
        "froude": froude,
        "area_m2": g["area_m2"],
        "hydraulic_radius_m": g["hydraulic_radius_m"],
    }


def profile_type(y: float, yn: float | None, yc: float, mild: bool) -> str:
    family = "M" if mild else "S"
    if yn is None:
        return "%s（正常水深超出斷面）" % family
    if mild:
        if y > yn:
            return "M1"
        if y >= yc:
            return "M2"
        return "M3"
    if y > yc:
        return "S1"
    if y > yn:
        return "S2"
    return "S3"


def analyse(
    *,
    design_flow_m3s: float,
    bottom_width_m: float,
    side_slope_h_v: float = 0.0,
    slope: float,
    manning_n: float = 0.014,
    reach_length_m: float,
    step_m: float = 10.0,
    control_depth_m: float | None = None,
    channel_depth_m: float | None = None,
    freeboard_min_m: float = 0.0,
    minor_loss_coefficient: float = 0.0,
    velocity_min_m_s: float = 0.0,
    velocity_max_m_s: float | None = None,
) -> dict[str, Any]:
    q = _num("design_flow_m3s", design_flow_m3s, minimum=0.0)
    b = _num("bottom_width_m", bottom_width_m, minimum=1e-6)
    m = _num("side_slope_h_v", side_slope_h_v, minimum=0.0)
    s0 = _num("slope", slope, minimum=0.0)
    n = _num("manning_n", manning_n, minimum=1e-9)
    length = _num("reach_length_m", reach_length_m, minimum=1e-6)
    step = _num("step_m", step_m, minimum=0.01)
    fb = _num("freeboard_min_m", freeboard_min_m, minimum=0.0)
    ke = _num("minor_loss_coefficient", minor_loss_coefficient, minimum=0.0)
    v_min = _num("velocity_min_m_s", velocity_min_m_s, minimum=0.0)

    depth_max = channel_depth_m if channel_depth_m else max(5.0, 3.0 * b)
    depth_max = _num("channel_depth_m", depth_max, minimum=1e-3)
    yc = critical_depth(q, b, m, depth_max)
    yn = normal_depth(q, b, m, s0, n, depth_max)
    if control_depth_m is None:
        y_down = yc
        control_basis = "下游自由出流：取臨界水深"
    else:
        y_down = _num("control_depth_m", control_depth_m, minimum=1e-6)
        control_basis = "指定下游控制水深"
    if y_down > depth_max:
        raise ChannelProfileError(
            "下游控制水深 %.3f m 超過斷面深 %.3f m" % (y_down, depth_max)
        )

    subcritical = y_down >= yc
    mild = yn is None or yn > yc
    stations: list[dict[str, Any]] = []
    warnings: list[str] = []
    x = 0.0
    y = y_down
    state = _section_state(q, b, m, y, s0, n)
    stations.append({
        "chainage_m": 0.0,
        "bed_elevation_m": 0.0,
        "water_surface_m": y,
        "profile": profile_type(y, yn, yc, mild),
        **{k: state[k] for k in ("depth_m", "velocity_m_s", "area_m2",
                                 "hydraulic_radius_m", "froude",
                                 "specific_energy_m", "friction_slope")},
    })

    truncated = False
    while x < length - 1e-9:
        dx = min(step, length - x)
        # Bed elevation measured from the downstream control section: the bed
        # rises upstream by S0·x.
        z_d = x * s0
        z_u = (x + dx) * s0
        target = z_d + state["specific_energy_m"]

        def residual(y_try: float) -> float:
            st = _section_state(q, b, m, y_try, s0, n)
            hf = 0.5 * dx * (st["friction_slope"] + state["friction_slope"])
            he = ke * st["velocity_m_s"] ** 2 / (2.0 * G)
            # Energy balance: H_up = H_down + hf + he
            return z_u + st["specific_energy_m"] - hf - he - target

        lo, hi = (yc, depth_max) if subcritical else (1e-4, yc)
        # Scan the branch for a sign change; endpoint-only bracketing fails
        # when the friction slope blows up at very shallow depths.
        grid = [lo + (hi - lo) * i / 200.0 for i in range(201)]
        vals = [residual(yy) for yy in grid]
        brackets = [
            (grid[i], grid[i + 1]) for i in range(200)
            if vals[i] == 0.0 or vals[i] * vals[i + 1] <= 0.0
        ]
        # Near-zero depths can produce spurious sign changes; take the root
        # closest to the previous station so the profile stays continuous.
        bracket = min(
            brackets,
            key=lambda pr: abs(0.5 * (pr[0] + pr[1]) - state["depth_m"]),
            default=None,
        )
        if bracket is None:
            truncated = True
            warnings.append(
                "里程 %.1f m 之後標準步法在斷面內找不到解（可能已達堤頂、發生水躍或水面線轉折），"
                "剖面在此截斷。" % (x + dx)
            )
            break
        lo, hi = bracket
        f_lo = residual(lo)
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if residual(mid) * f_lo <= 0.0:
                hi = mid
            else:
                lo, f_lo = mid, residual(mid)
        y = 0.5 * (lo + hi)
        x += dx
        state = _section_state(q, b, m, y, s0, n)
        stations.append({
            "chainage_m": x,
            "bed_elevation_m": z_u,
            "water_surface_m": z_u + y,
            "profile": profile_type(y, yn, yc, mild),
            **{k: state[k] for k in ("depth_m", "velocity_m_s", "area_m2",
                                     "hydraulic_radius_m", "froude",
                                     "specific_energy_m", "friction_slope")},
        })
        if len(stations) > 20000:
            warnings.append("測站數過多，已於 20,000 站停止。")
            break

    depths = [s["depth_m"] for s in stations]
    velocities = [s["velocity_m_s"] for s in stations]
    checks: list[dict[str, Any]] = []
    if channel_depth_m:
        worst = max(depths) + fb
        checks.append({
            "item": "最高水深＋出水高 ≤ 斷面深",
            "value": worst, "limit": depth_max,
            "ok": worst <= depth_max + 1e-9, "unit": "m", "relation": "le",
        })
    if v_min > 0.0:
        low = min(velocities)
        checks.append({
            "item": "最小流速 ≥ 容許最小流速（水保 §85）",
            "value": low, "limit": v_min,
            "ok": low >= v_min - 1e-9, "unit": "m/s", "relation": "ge",
            "severity": "advisory",
        })
    if velocity_max_m_s is not None:
        v_max = _num("velocity_max_m_s", velocity_max_m_s, minimum=0.0)
        high = max(velocities)
        checks.append({
            "item": "最大流速 ≤ 容許最大流速（水保 §85）",
            "value": high, "limit": v_max,
            "ok": high <= v_max + 1e-9, "unit": "m/s", "relation": "le",
        })

    if not subcritical:
        warnings.append(
            "下游控制水深低於臨界水深，以超臨界流向上游演算；"
            "如實際為緩變流亞臨界，請改以亞臨界控制斷面重算。"
        )
    warnings.append(
        "標準步法為一維緩變流，不處理水躍、橋涵束縮、側流入流與彎道二次流；"
        "分段糙度或斷面變化大時應分段計算。"
    )

    return {
        "engine": "channel_profile",
        "version": "0.1",
        "inputs": {
            "design_flow_m3s": q, "bottom_width_m": b, "side_slope_h_v": m,
            "slope": s0, "manning_n": n, "reach_length_m": length, "step_m": step,
            "control_depth_m": control_depth_m, "channel_depth_m": channel_depth_m,
        },
        "normal_depth_m": yn,
        "critical_depth_m": yc,
        "regime": "亞臨界（緩流）" if subcritical else "超臨界（急流）",
        "slope_class": "緩坡（M）" if mild else "陡坡（S）",
        "control_basis": control_basis,
        "stations": stations,
        "max_depth_m": max(depths),
        "max_velocity_m_s": max(velocities),
        "min_velocity_m_s": min(velocities),
        "profile_reached": stations[-1]["chainage_m"],
        "truncated": truncated,
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in checks if c.get("severity") != "advisory"),
        "basis": [
            "水土保持技術規範 §84（曼寧公式）、§85（容許流速）、§86（出水高）",
            "公路排水設計規範第四章（渠道水理、水面線）",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    lines = [
        "設計流量 %.3f m³/s；正常水深 %s、臨界水深 %.3f m；%s、%s"
        % (
            result["inputs"]["design_flow_m3s"],
            "—" if result["normal_depth_m"] is None else "%.3f m" % result["normal_depth_m"],
            result["critical_depth_m"], result["slope_class"], result["regime"],
        ),
        "下游控制：%s（%.3f m）；演算至 %.1f m，最高水深 %.3f m、最大流速 %.2f m/s"
        % (
            result["control_basis"], result["stations"][0]["depth_m"],
            result["profile_reached"], result["max_depth_m"], result["max_velocity_m_s"],
        ),
    ]
    lines.append("  里程(m)   水深(m)  流速(m/s)  Fr    剖面")
    for st in result["stations"]:
        lines.append("  %8.1f  %7.3f  %8.3f  %5.2f  %s"
                     % (st["chainage_m"], st["depth_m"], st["velocity_m_s"],
                        st["froude"], st["profile"]))
    for c in result["checks"]:
        mark = "OK" if c["ok"] else ("NOTE" if c.get("severity") == "advisory" else "NG")
        sign = "≥" if c["relation"] == "ge" else "≤"
        lines.append("  [%s] %s：%.3f %s（%s %.3f）"
                     % (mark, c["item"], c["value"], c["unit"], sign, c["limit"]))
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（矩形 b=0.4 m、Q=0.3937 m³/s、S=0.5%、n=0.014）。"""
    from _selftest_util import Checker

    c = Checker("明渠水面線（標準步法）")
    q, b, slope, n = 0.3937, 0.4, 0.005, 0.014
    r = analyse(design_flow_m3s=q, bottom_width_m=b, side_slope_h_v=0.0, slope=slope,
                manning_n=n, reach_length_m=100.0, step_m=20.0, control_depth_m=0.62,
                channel_depth_m=0.9)
    c.close("臨界水深 yc＝(q²/g)^(1/3)", r["critical_depth_m"],
            ((q / b) ** 2 / 9.81) ** (1.0 / 3.0), tol=1e-3)
    yn = r["normal_depth_m"]
    area = b * yn
    radius = area / (b + 2.0 * yn)
    c.close("正常水深代回 Manning 得 Q", area * radius ** (2.0 / 3.0) * slope ** 0.5 / n, q, tol=1e-3)
    s0, s1 = r["stations"][0], r["stations"][1]
    v0 = q / (b * 0.62)
    r0 = b * 0.62 / (b + 2.0 * 0.62)
    sf0 = n ** 2 * v0 ** 2 / r0 ** (4.0 / 3.0)
    c.close("控制斷面流速 V＝Q/A", s0["velocity_m_s"], v0, tol=1e-3)
    c.close("摩擦坡降 Sf＝n²V²/R^(4/3)", s0["friction_slope"], sf0, tol=1e-4)
    c.close("比能 E＝y＋V²/2g", s0["specific_energy_m"], 0.62 + v0 ** 2 / (2.0 * 9.81), tol=1e-3)
    dx = s1["chainage_m"] - s0["chainage_m"]
    head_up = s1["water_surface_m"] + s1["velocity_m_s"] ** 2 / (2.0 * 9.81)
    head_down = s0["water_surface_m"] + s0["velocity_m_s"] ** 2 / (2.0 * 9.81)
    c.close("相鄰斷面能量平衡", head_up,
            head_down + 0.5 * (s0["friction_slope"] + s1["friction_slope"]) * dx, tol=1e-3)
    return c.run()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(description="明渠水面線（標準步法）")
    ap.add_argument("--q", type=float, required=True, help="設計流量 m³/s")
    ap.add_argument("--width", type=float, required=True, help="底寬 m")
    ap.add_argument("--side", type=float, default=0.0, help="側坡 H:V（矩形填 0）")
    ap.add_argument("--slope", type=float, required=True)
    ap.add_argument("--manning", type=float, default=0.014)
    ap.add_argument("--length", type=float, required=True, help="演算長度 m")
    ap.add_argument("--step", type=float, default=10.0)
    ap.add_argument("--control", type=float, default=None, help="下游控制水深 m")
    ap.add_argument("--depth", type=float, default=None, help="斷面深 m")
    ap.add_argument("--freeboard", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyse(
        design_flow_m3s=a.q, bottom_width_m=a.width, side_slope_h_v=a.side,
        slope=a.slope, manning_n=a.manning, reach_length_m=a.length, step_m=a.step,
        control_depth_m=a.control, channel_depth_m=a.depth, freeboard_min_m=a.freeboard,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else format_report(r))
    raise SystemExit(0 if r["pass"] else 1)
