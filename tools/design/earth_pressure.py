"""Earth-pressure primitives shared by walls, culverts and foundations.

Sign conventions
----------------
Angles are degrees in public APIs.  ``wall_angle_deg`` is the angle of the
retained-side wall face measured from the horizontal; a vertical wall is 90°.
``backfill_slope_deg`` rises away from the wall.  ``wall_friction_deg`` is the
positive interface friction angle used by the Coulomb/Mononobe-Okabe forms.

All forces are per metre of wall length and all moments act about the wall
base at the toe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


GAMMA_WATER = 9.81


class EarthPressureError(ValueError):
    """Raised for invalid geometry or an inadmissible pressure coefficient."""


def _finite(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise EarthPressureError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise EarthPressureError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise EarthPressureError(f"{name} must be >= {minimum}; got {v}.")
    return v


def _rad(value: float) -> float:
    return math.radians(value)


def _coulomb_active(
    phi_deg: float,
    delta_deg: float,
    beta_deg: float,
    wall_angle_deg: float,
    kh: float,
    kv: float,
) -> float:
    phi = _rad(phi_deg)
    delta = _rad(delta_deg)
    beta = _rad(beta_deg)
    alpha = _rad(wall_angle_deg)

    if not (0.0 < phi_deg < 90.0):
        raise EarthPressureError("phi_deg must be between 0 and 90 degrees.")
    if abs(beta_deg) >= phi_deg:
        raise EarthPressureError("backfill_slope_deg must be smaller than phi_deg.")
    if wall_angle_deg <= 0.0 or wall_angle_deg > 90.0:
        raise EarthPressureError("wall_angle_deg must be in (0, 90].")
    if delta_deg < 0.0 or delta_deg >= phi_deg:
        raise EarthPressureError("wall_friction_deg must satisfy 0 <= delta < phi.")
    if kh < 0.0 or kv >= 1.0:
        raise EarthPressureError("kh must be non-negative and kv must be less than 1.")

    if kh > 0.0 or kv != 0.0:
        if abs(wall_angle_deg - 90.0) > 1e-9:
            raise EarthPressureError(
                "Mononobe-Okabe currently requires a vertical retained-side wall face "
                "(wall_angle_deg=90)."
            )
        theta = math.atan2(kh, 1.0 - kv)
        root_arg = (
            math.sin(phi + delta)
            * math.sin(phi - beta - theta)
            / (math.cos(delta + theta) * math.cos(beta))
        )
        # 112 版式(7.3-12)：根號內分母為 cos(θw−α)，θw＝墻背與垂直面交角（上方已限定 wall_angle=90°，
        # 故 θw＝0），α＝墻後地表傾角（此處 beta）→ cos(beta)。
        # 舊版誤用 cos(beta − theta)，theta 是地震角 ψ，會使 KAE 偏低 0.2~0.7%（不安全側）。
        if root_arg < 0.0:
            raise EarthPressureError(
                "No real Coulomb/Mononobe-Okabe wedge for these parameters."
            )
        denominator = (
            math.cos(theta)
            * math.cos(delta + theta)
            * (1.0 + math.sqrt(root_arg)) ** 2
        )
        if abs(denominator) < 1e-14:
            raise EarthPressureError("Degenerate active-pressure coefficient.")
        ka = math.cos(phi - theta) ** 2 / denominator
    else:
        root_arg = (
            math.sin(phi + delta)
            * math.sin(phi - beta)
            / (math.sin(alpha - delta) * math.sin(alpha + beta))
        )
        if root_arg < 0.0:
            raise EarthPressureError("No real Coulomb active wedge for these parameters.")
        denominator = (
            math.sin(alpha) ** 2
            * math.sin(alpha - delta)
            * (1.0 + math.sqrt(root_arg)) ** 2
        )
        if abs(denominator) < 1e-14:
            raise EarthPressureError("Degenerate active-pressure coefficient.")
        ka = math.sin(alpha + phi) ** 2 / denominator
    if not math.isfinite(ka) or ka <= 0.0:
        raise EarthPressureError("Computed active-pressure coefficient is not positive.")
    return ka


def coulomb_active_coefficient(
    phi_deg: float,
    *,
    wall_friction_deg: float = 0.0,
    backfill_slope_deg: float = 0.0,
    wall_angle_deg: float = 90.0,
    kh: float = 0.0,
    kv: float = 0.0,
) -> float:
    """Return Coulomb active coefficient, with Mononobe-Okabe for seismic."""

    return _coulomb_active(
        _finite("phi_deg", phi_deg),
        _finite("wall_friction_deg", wall_friction_deg, minimum=0.0),
        _finite("backfill_slope_deg", backfill_slope_deg),
        _finite("wall_angle_deg", wall_angle_deg),
        _finite("kh", kh, minimum=0.0),
        _finite("kv", kv),
    )


def rankine_active_coefficient(
    phi_deg: float, *, backfill_slope_deg: float = 0.0
) -> float:
    """Return the Rankine active coefficient for a smooth vertical wall."""

    phi = _rad(_finite("phi_deg", phi_deg))
    beta = _rad(_finite("backfill_slope_deg", backfill_slope_deg))
    if not (0.0 < phi_deg < 90.0):
        raise EarthPressureError("phi_deg must be between 0 and 90 degrees.")
    if abs(beta) >= phi:
        raise EarthPressureError("backfill_slope_deg must be smaller than phi_deg.")
    c = math.cos(beta)
    value = c * (c - math.sqrt(max(0.0, math.cos(beta) ** 2 - math.cos(phi) ** 2)))
    value /= c * (c + math.sqrt(max(0.0, math.cos(beta) ** 2 - math.cos(phi) ** 2)))
    return value


def rankine_passive_coefficient(
    phi_deg: float, *, backfill_slope_deg: float = 0.0
) -> float:
    """Return the Rankine passive coefficient for a smooth vertical wall."""

    ka = rankine_active_coefficient(phi_deg, backfill_slope_deg=backfill_slope_deg)
    if ka <= 0.0:
        raise EarthPressureError("Degenerate passive-pressure coefficient.")
    return 1.0 / ka


def coulomb_passive_coefficient(
    phi_deg: float,
    *,
    wall_friction_deg: float = 0.0,
    backfill_slope_deg: float = 0.0,
    wall_angle_deg: float = 90.0,
) -> float:
    """Return the Coulomb passive coefficient for static loading."""

    phi = _rad(_finite("phi_deg", phi_deg))
    delta = _rad(_finite("wall_friction_deg", wall_friction_deg, minimum=0.0))
    beta = _rad(_finite("backfill_slope_deg", backfill_slope_deg))
    alpha = _rad(_finite("wall_angle_deg", wall_angle_deg))
    if not (0.0 < phi_deg < 90.0):
        raise EarthPressureError("phi_deg must be between 0 and 90 degrees.")
    root_arg = math.sin(phi + delta) * math.sin(phi + beta) / (
        math.sin(alpha - delta) * math.sin(alpha + beta)
    )
    if root_arg < 0.0:
        raise EarthPressureError("No real Coulomb passive wedge for these parameters.")
    denominator = (
        math.sin(alpha - phi) ** 2
        * math.sin(alpha + delta)
        * (1.0 - math.sqrt(root_arg)) ** 2
    )
    if abs(denominator) < 1e-14:
        raise EarthPressureError("Degenerate passive-pressure coefficient.")
    kp = math.sin(alpha + phi) ** 2 / denominator
    if not math.isfinite(kp) or kp <= 0.0:
        raise EarthPressureError("Computed passive-pressure coefficient is not positive.")
    return kp


@dataclass(frozen=True)
class PressureResult:
    coefficient: float
    total_normal_kn_per_m: float
    horizontal_kn_per_m: float
    vertical_kn_per_m: float
    application_height_m: float
    moment_knm_per_m: float
    soil_horizontal_kn_per_m: float
    water_horizontal_kn_per_m: float
    seismic_increment_horizontal_kn_per_m: float
    seismic_increment_normal_kn_per_m: float
    seismic_increment_vertical_kn_per_m: float
    seismic_increment_application_height_m: float
    seismic_increment_moment_knm_per_m: float
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["metadata"] = dict(self.metadata)
        return result


def _integrate_profile(
    height_m: float,
    pressure_at_depth: Any,
    *,
    intervals: int = 400,
) -> tuple[float, float]:
    """Integrate a pressure function and its first moment about the base."""

    if intervals % 2:
        intervals += 1
    h = height_m / intervals
    force = 0.0
    moment = 0.0
    for i in range(intervals + 1):
        z = i * h
        p = max(0.0, float(pressure_at_depth(z)))
        weight = 1.0 if i in (0, intervals) else (4.0 if i % 2 else 2.0)
        force += weight * p
        moment += weight * p * (height_m - z)
    scale = h / 3.0
    return force * scale, moment * scale


def active_earth_pressure(
    *,
    height_m: float,
    gamma_kn_m3: float,
    phi_deg: float,
    cohesion_kpa: float = 0.0,
    surcharge_kpa: float = 0.0,
    groundwater_depth_m: float | None = None,
    saturated_unit_weight_kn_m3: float | None = None,
    wall_friction_deg: float | None = None,
    backfill_slope_deg: float = 0.0,
    wall_angle_deg: float = 90.0,
    kh: float = 0.0,
    kv: float = 0.0,
) -> PressureResult:
    """Compute static active pressure and an M-O seismic increment.

    The static profile includes surcharge, effective soil unit weight below the
    water table and hydrostatic pressure.  The seismic increment is reported
    separately so callers can apply their required load combination explicitly.
    """

    H = _finite("height_m", height_m, minimum=1e-9)
    gamma = _finite("gamma_kn_m3", gamma_kn_m3, minimum=1e-9)
    phi = _finite("phi_deg", phi_deg)
    c = _finite("cohesion_kpa", cohesion_kpa, minimum=0.0)
    q = _finite("surcharge_kpa", surcharge_kpa, minimum=0.0)
    kh = _finite("kh", kh, minimum=0.0)
    kv = _finite("kv", kv)
    delta = 2.0 * phi / 3.0 if wall_friction_deg is None else _finite(
        "wall_friction_deg", wall_friction_deg, minimum=0.0
    )
    if delta >= phi:
        raise EarthPressureError("wall_friction_deg must be smaller than phi_deg.")

    ka = coulomb_active_coefficient(
        phi,
        wall_friction_deg=delta,
        backfill_slope_deg=backfill_slope_deg,
        wall_angle_deg=wall_angle_deg,
    )
    if groundwater_depth_m is None:
        zw = H + 1.0
    else:
        zw = _finite("groundwater_depth_m", groundwater_depth_m, minimum=0.0)
    gamma_sat = (
        gamma
        if saturated_unit_weight_kn_m3 is None
        else _finite(
            "saturated_unit_weight_kn_m3",
            saturated_unit_weight_kn_m3,
            minimum=gamma,
        )
    )
    gamma_eff = gamma_sat - GAMMA_WATER
    cos_d = math.cos(_rad(delta))
    sin_d = math.sin(_rad(delta))

    def soil_normal(z: float) -> float:
        z_eff = min(z, zw)
        below = max(0.0, z - zw)
        sigma_v = q + gamma * z_eff + gamma_eff * below
        return max(0.0, ka * sigma_v - 2.0 * c * math.sqrt(ka))

    def water_horizontal(z: float) -> float:
        return GAMMA_WATER * max(0.0, z - zw)

    soil_normal_force, soil_normal_moment = _integrate_profile(H, soil_normal)
    water_h, water_m = _integrate_profile(H, water_horizontal)
    soil_h = soil_normal_force * cos_d
    soil_v = soil_normal_force * sin_d
    horizontal = soil_h + water_h
    moment = soil_normal_moment * cos_d + water_m
    application = moment / horizontal if horizontal > 1e-12 else 0.0

    seismic_normal = 0.0
    seismic_arm = 0.6 * H
    if kh > 0.0:
        kae = coulomb_active_coefficient(
            phi,
            wall_friction_deg=delta,
            backfill_slope_deg=backfill_slope_deg,
            wall_angle_deg=wall_angle_deg,
            kh=kh,
            kv=kv,
        )
        # Mononobe-Okabe total pressure minus the static Coulomb pressure.
        seismic_normal = max(0.0, 0.5 * (kae - ka) * gamma * H * H)
    seismic_h = seismic_normal * cos_d
    seismic_v = seismic_normal * sin_d

    return PressureResult(
        coefficient=ka,
        total_normal_kn_per_m=soil_normal_force,
        horizontal_kn_per_m=horizontal,
        vertical_kn_per_m=soil_v,
        application_height_m=application,
        moment_knm_per_m=moment,
        soil_horizontal_kn_per_m=soil_h,
        water_horizontal_kn_per_m=water_h,
        seismic_increment_horizontal_kn_per_m=seismic_h,
        seismic_increment_normal_kn_per_m=seismic_normal,
        seismic_increment_vertical_kn_per_m=seismic_v,
        seismic_increment_application_height_m=seismic_arm,
        seismic_increment_moment_knm_per_m=seismic_h * seismic_arm,
        metadata={
            "method": "Coulomb active profile with Mononobe-Okabe increment",
            "wall_friction_deg": delta,
            "groundwater_depth_m": None if groundwater_depth_m is None else zw,
            "saturated_unit_weight_kn_m3": gamma_sat,
            "effective_unit_weight_below_water_kn_m3": gamma_eff,
            "cohesion_used_kpa": c,
            "surcharge_kpa": q,
            "seismic_increment_arm_rule": "0.60 * retained height",
        },
    )


def hydrostatic_force(
    *,
    water_height_m: float,
    gamma_water_kn_m3: float = GAMMA_WATER,
) -> dict[str, float]:
    """Return triangular hydrostatic force, lever arm and base moment."""

    h = _finite("water_height_m", water_height_m, minimum=0.0)
    gamma = _finite("gamma_water_kn_m3", gamma_water_kn_m3, minimum=1e-9)
    if h == 0.0:
        return {
            "force_kn_per_m": 0.0,
            "application_height_m": 0.0,
            "moment_knm_per_m": 0.0,
        }
    force = 0.5 * gamma * h * h
    arm = h / 3.0
    return {
        "force_kn_per_m": force,
        "application_height_m": arm,
        "moment_knm_per_m": force * arm,
    }


def passive_rankine_force(
    *,
    depth_m: float,
    gamma_kn_m3: float,
    phi_deg: float,
    cohesion_kpa: float = 0.0,
    surcharge_kpa: float = 0.0,
    backfill_slope_deg: float = 0.0,
) -> dict[str, float]:
    """Return horizontal passive resistance on the exposed side."""

    H = _finite("depth_m", depth_m, minimum=0.0)
    gamma = _finite("gamma_kn_m3", gamma_kn_m3, minimum=1e-9)
    c = _finite("cohesion_kpa", cohesion_kpa, minimum=0.0)
    q = _finite("surcharge_kpa", surcharge_kpa, minimum=0.0)
    kp = rankine_passive_coefficient(phi_deg, backfill_slope_deg=backfill_slope_deg)
    force = 0.5 * kp * gamma * H * H + kp * q * H + 2.0 * c * math.sqrt(kp) * H
    triangular = 0.5 * kp * gamma * H * H
    uniform = kp * q * H + 2.0 * c * math.sqrt(kp) * H
    arm = (
        triangular * H / 3.0 + uniform * H / 2.0
    ) / force if force > 1e-12 else 0.0
    return {
        "coefficient": kp,
        "force_kn_per_m": force,
        "application_height_m": arm,
        "moment_knm_per_m": force * arm,
    }


def passive_options(
    section: Mapping[str, Any] | None,
    soil: Mapping[str, Any] | None,
    *,
    default_include: bool,
    default_ratio: float,
) -> dict[str, Any]:
    """Read include_passive / passive_ratio from the section, then the soil block."""

    def pick(key: str, default: Any) -> Any:
        for block in (section, soil):
            if block and block.get(key) is not None:
                return block[key]
        return default

    return {
        "include": bool(pick("include_passive", default_include)),
        "ratio": pick("passive_ratio", default_ratio),
    }


def toe_passive_resistance(
    *,
    depth_m: float,
    gamma_kn_m3: float,
    phi_deg: float,
    cohesion_kpa: float = 0.0,
    include: bool = True,
    ratio: float = 1.0,
) -> dict[str, Any]:
    """Rankine passive resistance of the soil in front of the wall toe.

    ``depth_m`` is measured from the underside of the base.  The result only
    enters the sliding check: (mu N + Pp) / T.
    """

    D = _finite("depth_m", depth_m, minimum=0.0)
    reduction = _finite("passive_ratio", ratio)
    if not 0.0 <= reduction <= 1.0:
        raise EarthPressureError("被動土壓折減比須介於 0～1，目前為 %s。" % reduction)
    included = bool(include) and D > 0.0
    full = passive_rankine_force(
        depth_m=D if included else 0.0,
        gamma_kn_m3=gamma_kn_m3,
        phi_deg=phi_deg,
        cohesion_kpa=cohesion_kpa,
    )
    return {
        "included": included,
        "depth_m": D,
        "Kp": full["coefficient"],
        "ratio": reduction,
        "Pp_full_kN_per_m": full["force_kn_per_m"],
        "Pp_kN_per_m": full["force_kn_per_m"] * reduction,
        "application_height_m": full["application_height_m"],
    }


def passive_summary(passive: Mapping[str, Any]) -> str:
    """One line for reports; empty when passive resistance was not counted."""

    if not passive.get("included"):
        return ""
    return "牆趾被動土壓力 Pp=%.2f kN/m（D=%.2f m、Kp=%.3f、折減比 %.2f，僅計入抗滑）" % (
        passive["Pp_kN_per_m"], passive["depth_m"], passive["Kp"], passive["ratio"])


def passive_warnings(passive: Mapping[str, Any], seismic: bool) -> list[str]:
    """Conditions the designer must honour for the toe passive resistance."""

    if not passive.get("included"):
        if float(passive.get("depth_m") or 0.0) > 0.0:
            return ["牆趾覆土 D=%.2f m 未計入被動土壓力（保守）。" % passive["depth_m"]]
        return []
    notes = [passive_summary(passive) + "；覆土須分層夯實且永久不得移除，否則不得計入。"]
    if seismic:
        notes.append("地震工況沿用靜態 Rankine Kp，未作地震折減。")
    return notes

