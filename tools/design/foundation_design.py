"""Preliminary footing, pile-cap and settlement checks.

All loads use compression-positive sign for vertical force ``P``.  Moments are
positive magnitudes; the module takes absolute values in pressure envelopes.
This is a design aid, not a substitute for site-specific geotechnical and
structural design.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rc_design as RC


class FoundationError(ValueError):
    """Raised for invalid footing geometry or loads."""


# 建築物基礎構造設計規範 §4.5.4 表-解4.5-2 的一般容許總沉陷量。
# 這些是上限，不是「只要低於上限就安全」；差異沉陷與角變量仍須另案檢核。
SETTLEMENT_LIMITS_MM = {
    "plain_concrete_continuous": 40.0,
    "rc_isolated_or_combined": 100.0,
    "rc_continuous": 200.0,
    "rc_raft": 300.0,
}

# 建築物基礎構造設計規範 §4.5.4 表-解4.5-1。
# 1/500 是「不容許裂縫產生的安全限度（含安全係數）」，
# 因此作為預設檢核門檻；其他值保留作損害程度判讀，不自動取代設計者決定。
DEFAULT_ANGULAR_DISTORTION_LIMIT = 1.0 / 500.0
ANGULAR_DISTORTION_DAMAGE_LEVELS = (
    {"ratio": 1.0 / 600.0, "description": "斜撐構架有受損危險"},
    {"ratio": 1.0 / 500.0, "description": "不容許裂縫產生的安全限度（含安全係數）"},
    {"ratio": 1.0 / 300.0, "description": "隔間牆開始發生裂縫（不含安全係數）"},
    {"ratio": 1.0 / 250.0, "description": "剛性高層建築物開始有明顯傾斜"},
    {"ratio": 1.0 / 150.0, "description": "隔間牆及磚牆產生相當多裂縫；結構性損壞"},
)


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise FoundationError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise FoundationError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise FoundationError(f"{name} must be >= {minimum}; got {v}.")
    return v


@dataclass(frozen=True)
class FootingLoads:
    P_kN: float
    Mx_kNm: float = 0.0
    My_kNm: float = 0.0
    Hx_kN: float = 0.0
    Hy_kN: float = 0.0


def pressure_distribution(
    P_kN: float,
    Mx_kNm: float,
    My_kNm: float,
    B_m: float,
    L_m: float,
) -> dict[str, float]:
    """Elastic bearing pressure on a rigid rectangular footing.

    ``Mx`` varies pressure along ``L``; ``My`` varies along ``B``.  Taking the
    absolute moments is conservative for the extreme corner pressure.
    """

    P = _num("P_kN", P_kN)
    Mx = abs(_num("Mx_kNm", Mx_kNm))
    My = abs(_num("My_kNm", My_kNm))
    B = _num("B_m", B_m, minimum=1e-6)
    L = _num("L_m", L_m, minimum=1e-6)
    A = B * L
    Sx = B * L * L / 6.0
    Sy = L * B * B / 6.0
    base = P / A
    delta = Mx / Sx + My / Sy
    return {
        "area_m2": A,
        "P_kN": P,
        "Mx_kNm": Mx,
        "My_kNm": My,
        "Sx_m3": Sx,
        "Sy_m3": Sy,
        "q_average_kpa": base,
        "q_max_kpa": base + delta,
        "q_min_kpa": base - delta,
        "e_x_m": My / P if abs(P) > 1e-12 else math.inf,
        "e_y_m": Mx / P if abs(P) > 1e-12 else math.inf,
        "contact_full": base - delta >= -1e-9,
    }


def constrained_modulus_from_elastic(
    elastic_modulus_kpa: float,
    poisson_ratio: float,
) -> float:
    """Convert isotropic elastic modulus E to one-dimensional constrained modulus M."""

    E = _num("elastic_modulus_kpa", elastic_modulus_kpa, minimum=1e-9)
    nu = _num("poisson_ratio", poisson_ratio, minimum=0.0)
    if nu >= 0.5:
        raise FoundationError("poisson_ratio must be less than 0.5.")
    return E * (1.0 - nu) / ((1.0 + nu) * (1.0 - 2.0 * nu))


def settlement_by_layers(
    q_kpa: float,
    B_m: float,
    L_m: float,
    layers: Iterable[Mapping[str, Any]],
    *,
    foundation_type: str = "rc_isolated_or_combined",
    allowable_total_mm: float | None = None,
    stress_distribution: str = "2v1",
    subdivisions: int = 20,
) -> dict[str, Any]:
    """Estimate immediate settlement layer by layer.

    Vertical stress is spread below the footing by the 2:1 method from
    §4.4.3.  Each layer supplies either ``constrained_modulus_kpa`` or
    ``elastic_modulus_kpa`` plus ``poisson_ratio``.  The one-dimensional
    compression of each sublayer is ``delta_sigma * thickness / M``.

    This is an immediate-settlement estimate for service loads.  It does not
    calculate consolidation or secondary compression, and a single-footing
    result cannot establish differential settlement or angular distortion.
    """

    q = _num("q_kpa", q_kpa, minimum=0.0)
    B = _num("B_m", B_m, minimum=1e-9)
    L = _num("L_m", L_m, minimum=1e-9)
    if stress_distribution != "2v1":
        raise FoundationError("Only stress_distribution='2v1' is currently supported.")
    n = int(_num("subdivisions", subdivisions, minimum=1.0))
    if n > 1000:
        raise FoundationError("subdivisions must be <= 1000.")
    rows = []
    total_settlement_m = 0.0
    depth_m = 0.0
    q_base = q * B * L
    for index, layer in enumerate(layers, 1):
        if not isinstance(layer, Mapping):
            raise FoundationError("Each settlement layer must be a mapping.")
        thickness = _num(
            f"layer {index} thickness_m",
            layer.get("thickness_m"),
            minimum=1e-9,
        )
        if layer.get("constrained_modulus_kpa") not in (None, ""):
            modulus = _num(
                f"layer {index} constrained_modulus_kpa",
                layer.get("constrained_modulus_kpa"),
                minimum=1e-9,
            )
            modulus_source = "constrained_modulus_kpa"
        else:
            modulus = constrained_modulus_from_elastic(
                _num(
                    f"layer {index} elastic_modulus_kpa",
                    layer.get("elastic_modulus_kpa"),
                    minimum=1e-9,
                ),
                _num(
                    f"layer {index} poisson_ratio",
                    layer.get("poisson_ratio", 0.3),
                    minimum=0.0,
                ),
            )
            modulus_source = "elastic_modulus_kpa"
        dz = thickness / n
        layer_settlement_m = 0.0
        stress_sum = 0.0
        for j in range(n):
            z = depth_m + (j + 0.5) * dz
            sigma_z = q_base / ((B + z) * (L + z))
            layer_settlement_m += sigma_z * dz / modulus
            stress_sum += sigma_z * dz
        total_settlement_m += layer_settlement_m
        rows.append(
            {
                "layer": index,
                "depth_from_m": round(depth_m, 4),
                "depth_to_m": round(depth_m + thickness, 4),
                "thickness_m": round(thickness, 4),
                "modulus_kpa": round(modulus, 3),
                "modulus_source": modulus_source,
                "mean_stress_increment_kpa": round(stress_sum / thickness, 4),
                "settlement_mm": round(layer_settlement_m * 1000.0, 4),
            }
        )
        depth_m += thickness
    if not rows:
        raise FoundationError("At least one settlement layer is required.")
    if allowable_total_mm in (None, ""):
        if foundation_type not in SETTLEMENT_LIMITS_MM:
            raise FoundationError(
                "foundation_type must be one of: "
                + ", ".join(sorted(SETTLEMENT_LIMITS_MM))
            )
        allowable_mm = SETTLEMENT_LIMITS_MM[foundation_type]
    else:
        allowable_mm = _num(
            "allowable_total_mm", allowable_total_mm, minimum=0.0
        )
    total_mm = total_settlement_m * 1000.0
    return {
        "method": "layered 2:1 stress spread",
        "q_kpa": round(q, 3),
        "B_m": round(B, 4),
        "L_m": round(L, 4),
        "foundation_type": foundation_type,
        "total_settlement_mm": round(total_mm, 4),
        "allowable_total_mm": round(allowable_mm, 4),
        "ok": total_mm <= allowable_mm + 1e-9,
        "layers": rows,
        "notes": [
            "Uses service load and immediate settlement; consolidation and secondary compression are not included.",
            "Differential settlement and angular distortion require a footing layout or soil-structure interaction model.",
        ],
    }


def _midpoint_stress_increment_2v1(
    q_kpa: float,
    B_m: float,
    L_m: float,
    depth_to_top_m: float,
    thickness_m: float,
) -> float:
    """Return the 2:1 vertical stress increment at a layer midpoint."""

    z = depth_to_top_m + thickness_m / 2.0
    return q_kpa * B_m * L_m / ((B_m + z) * (L_m + z))


def consolidation_by_layers(
    q_kpa: float,
    B_m: float,
    L_m: float,
    layers: Iterable[Mapping[str, Any]],
    *,
    foundation_type: str = "rc_isolated_or_combined",
    allowable_total_mm: float | None = None,
    stress_distribution: str = "2v1",
) -> dict[str, Any]:
    """Estimate one-dimensional primary and secondary consolidation.

    The primary-consolidation equations follow ``建築物基礎構造設計規範``
    §4.4.6 and the supplementary formulas for normally consolidated and
    overconsolidated soils.  Secondary compression follows §4.4.7.

    Each layer must supply:

    * ``thickness_m``
    * ``initial_effective_stress_kpa`` at the layer midpoint
    * ``compression_index`` (``Cc``)
    * ``void_ratio`` (``e0``)
    * ``preconsolidation_stress_kpa``; omit only when the layer is normally
      consolidated, in which case it is taken equal to the initial effective
      stress
    * ``recompression_index`` (``Cs``) when the layer is overconsolidated

    A layer whose preconsolidation stress is below its current effective stress
    is under consolidation.  That condition is rejected rather than applying a
    formula whose loading history is unknown.

    Optional secondary compression uses ``secondary_compression_index`` plus
    ``consolidation_start_year`` and ``assessment_end_year`` (§4.4.7).
    """

    q = _num("q_kpa", q_kpa, minimum=0.0)
    B = _num("B_m", B_m, minimum=1e-9)
    L = _num("L_m", L_m, minimum=1e-9)
    if stress_distribution != "2v1":
        raise FoundationError("Only stress_distribution='2v1' is currently supported.")
    if allowable_total_mm in (None, ""):
        if foundation_type not in SETTLEMENT_LIMITS_MM:
            raise FoundationError(
                "foundation_type must be one of: "
                + ", ".join(sorted(SETTLEMENT_LIMITS_MM))
            )
        allowable_mm = SETTLEMENT_LIMITS_MM[foundation_type]
    else:
        allowable_mm = _num(
            "allowable_total_mm", allowable_total_mm, minimum=0.0
        )

    rows: list[dict[str, Any]] = []
    total_primary_m = 0.0
    total_secondary_m = 0.0
    depth_m = 0.0
    for index, layer in enumerate(layers, 1):
        if not isinstance(layer, Mapping):
            raise FoundationError("Each consolidation layer must be a mapping.")
        thickness = _num(
            f"consolidation layer {index} thickness_m",
            layer.get("thickness_m"),
            minimum=1e-9,
        )
        sigma0 = _num(
            f"consolidation layer {index} initial_effective_stress_kpa",
            layer.get("initial_effective_stress_kpa"),
            minimum=1e-12,
        )
        cc = _num(
            f"consolidation layer {index} compression_index",
            layer.get("compression_index"),
            minimum=1e-12,
        )
        e0 = _num(
            f"consolidation layer {index} void_ratio",
            layer.get("void_ratio"),
            minimum=1e-12,
        )
        sigma_c_raw = layer.get("preconsolidation_stress_kpa")
        sigma_c = (
            sigma0
            if sigma_c_raw in (None, "")
            else _num(
                f"consolidation layer {index} preconsolidation_stress_kpa",
                sigma_c_raw,
                minimum=1e-12,
            )
        )
        tolerance = max(1e-9, 1e-6 * sigma0)
        if sigma_c < sigma0 - tolerance:
            raise FoundationError(
                "consolidation layer %d is under consolidation "
                "(preconsolidation_stress_kpa %.3f < initial_effective_stress_kpa %.3f); "
                "provide loading history or use a separate staged-consolidation analysis."
                % (index, sigma_c, sigma0)
            )
        delta_sigma = _midpoint_stress_increment_2v1(
            q, B, L, depth_m, thickness
        )
        sigma_f = sigma0 + delta_sigma
        coefficient = thickness / (1.0 + e0)
        cs_raw = layer.get("recompression_index")

        if abs(sigma_c - sigma0) <= tolerance:
            state = "normally_consolidated"
            if sigma_f <= sigma0 + tolerance:
                primary_m = 0.0
            else:
                primary_m = cc * coefficient * math.log10(sigma_f / sigma0)
        else:
            state = "overconsolidated"
            if cs_raw in (None, ""):
                raise FoundationError(
                    "consolidation layer %d is overconsolidated; "
                    "recompression_index is required." % index
                )
            cs = _num(
                f"consolidation layer {index} recompression_index",
                cs_raw,
                minimum=1e-12,
            )
            if sigma_f <= sigma_c + tolerance:
                primary_m = cs * coefficient * math.log10(sigma_f / sigma0)
            else:
                primary_m = (
                    cs * coefficient * math.log10(sigma_c / sigma0)
                    + cc * coefficient * math.log10(sigma_f / sigma_c)
                )

        secondary_m = 0.0
        ca_raw = layer.get("secondary_compression_index")
        if ca_raw not in (None, ""):
            ca = _num(
                f"consolidation layer {index} secondary_compression_index",
                ca_raw,
                minimum=0.0,
            )
            t_start = _num(
                f"consolidation layer {index} consolidation_start_year",
                layer.get("consolidation_start_year"),
                minimum=1e-12,
            )
            t_end = _num(
                f"consolidation layer {index} assessment_end_year",
                layer.get("assessment_end_year"),
                minimum=1e-12,
            )
            if t_end < t_start - 1e-12:
                raise FoundationError(
                    "consolidation layer %d assessment_end_year must be "
                    ">= consolidation_start_year." % index
                )
            secondary_m = ca * thickness * math.log10(t_end / t_start)

        total_primary_m += primary_m
        total_secondary_m += secondary_m
        rows.append(
            {
                "layer": index,
                "depth_from_m": round(depth_m, 4),
                "depth_to_m": round(depth_m + thickness, 4),
                "thickness_m": round(thickness, 4),
                "consolidation_state": state,
                "initial_effective_stress_kpa": round(sigma0, 4),
                "preconsolidation_stress_kpa": round(sigma_c, 4),
                "final_effective_stress_kpa": round(sigma_f, 4),
                "stress_increment_kpa": round(delta_sigma, 4),
                "compression_index": round(cc, 6),
                "recompression_index": (
                    None if cs_raw in (None, "") else round(float(cs_raw), 6)
                ),
                "void_ratio": round(e0, 6),
                "primary_consolidation_mm": round(primary_m * 1000.0, 4),
                "secondary_compression_mm": round(secondary_m * 1000.0, 4),
            }
        )
        depth_m += thickness

    if not rows:
        raise FoundationError("At least one consolidation layer is required.")
    primary_mm = total_primary_m * 1000.0
    secondary_mm = total_secondary_m * 1000.0
    total_mm = primary_mm + secondary_mm
    return {
        "method": "layered one-dimensional consolidation",
        "q_kpa": round(q, 3),
        "B_m": round(B, 4),
        "L_m": round(L, 4),
        "foundation_type": foundation_type,
        "primary_consolidation_mm": round(primary_mm, 4),
        "secondary_compression_mm": round(secondary_mm, 4),
        "total_consolidation_mm": round(total_mm, 4),
        "allowable_total_mm": round(allowable_mm, 4),
        "ok": total_mm <= allowable_mm + 1e-9,
        "layers": rows,
        "codes": ["建築物基礎構造設計規範 §4.4.6、§4.4.7"],
        "notes": [
            "Primary consolidation uses Cc/Cs formulas from §4.4.6.",
            "Stress increments are evaluated at each layer midpoint using a 2:1 spread.",
            "Under-consolidated layers are rejected; staged loading and pore-pressure dissipation require a separate analysis.",
            "Secondary compression is included only when its coefficient and time interval are supplied.",
        ],
    }


def _solve_linear_system(
    matrix: list[list[float]], vector: list[float]
) -> list[float] | None:
    """Solve a small dense linear system with partial pivoting."""

    n = len(vector)
    aug = [list(matrix[i]) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        aug[col] = [value / divisor for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if abs(factor) <= 1e-15:
                continue
            aug[row] = [
                aug[row][j] - factor * aug[col][j] for j in range(n + 1)
            ]
    return [aug[i][n] for i in range(n)]


def _rigid_body_trend(
    points: list[dict[str, float]],
) -> dict[str, Any] | None:
    """Fit and remove a rigid-body settlement plane or line.

    At least three points are required so the remaining difference is not
    merely the rigid rotation that §4.5.4 requires designers to deduct.
    """

    n = len(points)
    if n < 3:
        return None
    mean_x = sum(p["x_m"] for p in points) / n
    mean_y = sum(p["y_m"] for p in points) / n
    mean_s = sum(p["settlement_mm"] for p in points) / n
    centered = [
        {
            "x": p["x_m"] - mean_x,
            "y": p["y_m"] - mean_y,
            "s": p["settlement_mm"] - mean_s,
        }
        for p in points
    ]
    span = max(
        max(abs(p["x"]) for p in centered),
        max(abs(p["y"]) for p in centered),
        1.0,
    )
    max_area_twice = 0.0
    for i in range(n - 2):
        ax, ay = centered[i]["x"], centered[i]["y"]
        for j in range(i + 1, n - 1):
            bx, by = centered[j]["x"], centered[j]["y"]
            for k in range(j + 1, n):
                cx, cy = centered[k]["x"], centered[k]["y"]
                area_twice = abs(
                    (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                )
                max_area_twice = max(max_area_twice, area_twice)
    noncollinear = max_area_twice > max(1e-12, 1e-10 * span * span)

    if noncollinear:
        sx = sum(p["x"] for p in centered)
        sy = sum(p["y"] for p in centered)
        sxx = sum(p["x"] * p["x"] for p in centered)
        sxy = sum(p["x"] * p["y"] for p in centered)
        syy = sum(p["y"] * p["y"] for p in centered)
        ss = sum(p["s"] for p in centered)
        sxs = sum(p["x"] * p["s"] for p in centered)
        sys = sum(p["y"] * p["s"] for p in centered)
        coefficients = _solve_linear_system(
            [
                [float(n), sx, sy],
                [sx, sxx, sxy],
                [sy, sxy, syy],
            ],
            [ss, sxs, sys],
        )
        if coefficients is None:
            return None
        residuals = [
            p["s"]
            - (
                coefficients[0]
                + coefficients[1] * p["x"]
                + coefficients[2] * p["y"]
            )
            for p in centered
        ]
        return {
            "model": "plane",
            "residuals_mm": residuals,
            "coefficients": {
                "offset_mm": coefficients[0],
                "mm_per_m_x": coefficients[1],
                "mm_per_m_y": coefficients[2],
            },
        }

    # Collinear supports: a straight chord is the rigid-body rotation.
    sxx = sum(p["x"] * p["x"] for p in centered)
    syy = sum(p["y"] * p["y"] for p in centered)
    sxy = sum(p["x"] * p["y"] for p in centered)
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    ux, uy = math.cos(theta), math.sin(theta)
    coordinates = [p["x"] * ux + p["y"] * uy for p in centered]
    mean_t = sum(coordinates) / n
    denominator = sum((t - mean_t) ** 2 for t in coordinates)
    if denominator <= 1e-18:
        return None
    slope = sum(
        (t - mean_t) * p["s"] for t, p in zip(coordinates, centered)
    ) / denominator
    intercept = sum(
        p["s"] - slope * (t - mean_t) for t, p in zip(coordinates, centered)
    ) / n
    residuals = [
        p["s"] - (intercept + slope * (t - mean_t))
        for t, p in zip(coordinates, centered)
    ]
    return {
        "model": "line",
        "residuals_mm": residuals,
        "coefficients": {
            "offset_mm": intercept,
            "mm_per_m_along_line": slope,
        },
    }


def angular_distortion(
    points: Iterable[Mapping[str, Any]],
    *,
    comparison_pairs: Iterable[Any] | None = None,
    limit: float = DEFAULT_ANGULAR_DISTORTION_LIMIT,
) -> dict[str, Any]:
    """Assess differential settlement and angular distortion between supports.

    ``settlement_mm`` is the total settlement at each support.  For three or
    more supports, a least-squares rigid-body plane is deducted (or a line for
    collinear supports) before calculating angular distortion, as required by
    §4.5.4.  With only two supports, the supplied difference is inseparable
    from rigid-body rotation and is reported without claiming an angular check.
    """

    ratio_limit = _num("limit", limit, minimum=1e-12)
    parsed: list[dict[str, float | str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(points, 1):
        if not isinstance(raw, Mapping):
            raise FoundationError("Each settlement point must be a mapping.")
        point_id = str(raw.get("id") or f"P{index}").strip()
        if not point_id or point_id in seen:
            raise FoundationError("settlement point ids must be unique and non-empty.")
        seen.add(point_id)
        parsed.append(
            {
                "id": point_id,
                "x_m": _num(f"{point_id} x_m", raw.get("x_m")),
                "y_m": _num(f"{point_id} y_m", raw.get("y_m")),
                "settlement_mm": _num(
                    f"{point_id} settlement_mm",
                    raw.get("settlement_mm"),
                ),
            }
        )
    if not parsed:
        raise FoundationError("At least one settlement point is required.")

    trend = _rigid_body_trend(parsed)  # type: ignore[arg-type]
    residuals = trend["residuals_mm"] if trend else None
    pair_indices: list[tuple[int, int]] = []
    by_id = {str(p["id"]): i for i, p in enumerate(parsed)}
    if comparison_pairs is None:
        pair_indices = [
            (i, j)
            for i in range(len(parsed))
            for j in range(i + 1, len(parsed))
        ]
    else:
        for item in comparison_pairs:
            if isinstance(item, Mapping):
                a, b = item.get("a"), item.get("b")
            else:
                try:
                    a, b = item
                except (TypeError, ValueError) as exc:
                    raise FoundationError(
                        "comparison_pairs entries must be ['A','B'] or {a,b}."
                    ) from exc
            a_id, b_id = str(a), str(b)
            if a_id not in by_id or b_id not in by_id or a_id == b_id:
                raise FoundationError(
                    "comparison_pairs contains an unknown or identical id: %s / %s"
                    % (a_id, b_id)
                )
            pair = tuple(sorted((by_id[a_id], by_id[b_id])))
            if pair not in pair_indices:
                pair_indices.append(pair)

    pair_rows: list[dict[str, Any]] = []
    max_adjusted: float | None = None
    for i, j in pair_indices:
        a, b = parsed[i], parsed[j]
        distance = math.hypot(
            float(b["x_m"]) - float(a["x_m"]),
            float(b["y_m"]) - float(a["y_m"]),
        )
        if distance <= 1e-12:
            raise FoundationError(
                "settlement points %s and %s have zero horizontal distance."
                % (a["id"], b["id"])
            )
        raw_difference = abs(
            float(a["settlement_mm"]) - float(b["settlement_mm"])
        )
        raw_ratio = raw_difference / (distance * 1000.0)
        adjusted_ratio = None
        adjusted_difference = None
        if residuals is not None:
            adjusted_difference = abs(
                float(residuals[i]) - float(residuals[j])
            )
            adjusted_ratio = adjusted_difference / (distance * 1000.0)
            max_adjusted = (
                adjusted_ratio
                if max_adjusted is None
                else max(max_adjusted, adjusted_ratio)
            )
        pair_rows.append(
            {
                "a": a["id"],
                "b": b["id"],
                "distance_m": round(distance, 4),
                "settlement_difference_mm": round(raw_difference, 4),
                "difference_over_distance": round(raw_ratio, 8),
                "rigid_body_adjusted_difference_mm": (
                    None
                    if adjusted_difference is None
                    else round(adjusted_difference, 4)
                ),
                "angular_distortion": (
                    None if adjusted_ratio is None else round(adjusted_ratio, 8)
                ),
            }
        )

    evaluated = residuals is not None and max_adjusted is not None
    max_ratio = max_adjusted if evaluated else None
    return {
        "method": "differential settlement after deducting rigid-body trend",
        "point_count": len(parsed),
        "rigid_body_model": None if trend is None else trend["model"],
        "rigid_body_coefficients": None if trend is None else trend["coefficients"],
        "evaluated": evaluated,
        "max_angular_distortion": (
            None if max_ratio is None else round(max_ratio, 8)
        ),
        "allowable_angular_distortion": round(ratio_limit, 8),
        "allowable_reciprocal": (
            None
            if ratio_limit <= 0
            else int(round(1.0 / ratio_limit))
        ),
        "ok": bool(evaluated and max_ratio <= ratio_limit + 1e-12),
        "pairs": pair_rows,
        "damage_reference": [
            {
                "ratio": round(float(row["ratio"]), 8),
                "reciprocal": int(round(1.0 / float(row["ratio"]))),
                "description": row["description"],
            }
            for row in ANGULAR_DISTORTION_DAMAGE_LEVELS
        ],
        "codes": ["建築物基礎構造設計規範 §4.5.4"],
        "notes": [
            "Angular distortion is calculated only after deducting a least-squares rigid-body line or plane.",
            "With fewer than three non-degenerate points, rigid rotation cannot be separated from structural distortion and no angular pass is claimed.",
            "If comparison_pairs is omitted, every support pair is screened; confirm which supports are actually adjacent for final design.",
        ],
    }


def settlement_assessment(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Assess immediate, consolidation, secondary and differential settlement.

    A top-level ``footings`` array is preferred.  A single-footing payload may
    omit that array and use the object itself.  Each footing may contain
    ``immediate_layers`` (alias ``layers``) and ``consolidation_layers``.
    """

    if not isinstance(payload, Mapping):
        raise FoundationError("settlement assessment payload must be a mapping.")
    raw_footings = payload.get("footings")
    if raw_footings in (None, ""):
        footings = [payload]
    elif isinstance(raw_footings, Iterable) and not isinstance(
        raw_footings, (str, bytes, Mapping)
    ):
        footings = list(raw_footings)
    else:
        raise FoundationError("footings must be an array.")
    if not footings:
        raise FoundationError("At least one footing is required.")

    default_type = str(
        payload.get("default_foundation_type", "rc_isolated_or_combined")
    )
    default_allowable = payload.get("allowable_total_mm")
    results: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(footings, 1):
        if not isinstance(raw, Mapping):
            raise FoundationError("Each footing must be a mapping.")
        footing_id = str(raw.get("id") or f"F{index}").strip()
        if not footing_id or footing_id in seen:
            raise FoundationError("footing ids must be unique and non-empty.")
        seen.add(footing_id)
        B = _num(f"{footing_id} B_m", raw.get("B_m"), minimum=1e-9)
        L = _num(f"{footing_id} L_m", raw.get("L_m"), minimum=1e-9)
        q_raw = raw.get("q_kpa")
        if q_raw in (None, "") and raw.get("P_kN") not in (None, ""):
            q = _num(f"{footing_id} P_kN", raw.get("P_kN")) / (B * L)
        else:
            q = _num(f"{footing_id} q_kpa", q_raw, minimum=0.0)
        foundation_type = str(raw.get("foundation_type", default_type))
        allowable = raw.get("allowable_total_mm", default_allowable)
        immediate_layers = raw.get("immediate_layers")
        if immediate_layers in (None, ""):
            immediate_layers = raw.get("layers")
        consolidation_layers = raw.get("consolidation_layers")
        if immediate_layers in (None, "") and consolidation_layers in (None, ""):
            raise FoundationError(
                "footing %s needs immediate_layers and/or consolidation_layers."
                % footing_id
            )

        immediate = None
        immediate_mm = 0.0
        if immediate_layers not in (None, ""):
            immediate = settlement_by_layers(
                q,
                B,
                L,
                immediate_layers,
                foundation_type=foundation_type,
                allowable_total_mm=allowable,
                subdivisions=int(raw.get("subdivisions", 20)),
            )
            immediate_mm = float(immediate["total_settlement_mm"])

        consolidation = None
        consolidation_mm = 0.0
        secondary_mm = 0.0
        if consolidation_layers not in (None, ""):
            consolidation = consolidation_by_layers(
                q,
                B,
                L,
                consolidation_layers,
                foundation_type=foundation_type,
                allowable_total_mm=allowable,
            )
            consolidation_mm = float(
                consolidation["primary_consolidation_mm"]
            )
            secondary_mm = float(
                consolidation["secondary_compression_mm"]
            )

        if allowable in (None, ""):
            if foundation_type not in SETTLEMENT_LIMITS_MM:
                raise FoundationError(
                    "footing %s foundation_type must be one of: %s"
                    % (footing_id, ", ".join(sorted(SETTLEMENT_LIMITS_MM)))
                )
            allowable_mm = SETTLEMENT_LIMITS_MM[foundation_type]
        else:
            allowable_mm = _num(
                f"{footing_id} allowable_total_mm",
                allowable,
                minimum=0.0,
            )
        total_mm = immediate_mm + consolidation_mm + secondary_mm
        results.append(
            {
                "id": footing_id,
                "x_m": _num(f"{footing_id} x_m", raw.get("x_m", 0.0)),
                "y_m": _num(f"{footing_id} y_m", raw.get("y_m", 0.0)),
                "q_kpa": round(q, 4),
                "B_m": B,
                "L_m": L,
                "foundation_type": foundation_type,
                "immediate_settlement_mm": round(immediate_mm, 4),
                "primary_consolidation_mm": round(consolidation_mm, 4),
                "secondary_compression_mm": round(secondary_mm, 4),
                "total_settlement_mm": round(total_mm, 4),
                "allowable_total_mm": round(allowable_mm, 4),
                "ok": total_mm <= allowable_mm + 1e-9,
                "immediate": immediate,
                "consolidation": consolidation,
            }
        )
        checks.append(
            {
                "item": "%s 總沉陷量（瞬時＋壓密＋次壓縮）" % footing_id,
                "value": round(total_mm, 4),
                "limit": round(allowable_mm, 4),
                "ok": total_mm <= allowable_mm + 1e-9,
                "unit": "mm",
                "relation": "le",
            }
        )

    angular = None
    angular_check_required = len(results) >= 2
    if angular_check_required:
        angular = angular_distortion(
            [
                {
                    "id": row["id"],
                    "x_m": row["x_m"],
                    "y_m": row["y_m"],
                    "settlement_mm": row["total_settlement_mm"],
                }
                for row in results
            ],
            comparison_pairs=payload.get("comparison_pairs"),
            limit=float(
                payload.get(
                    "angular_distortion_limit",
                    DEFAULT_ANGULAR_DISTORTION_LIMIT,
                )
            ),
        )
        checks.append(
            {
                "item": "最大角變量（已扣除剛體轉動）",
                "value": angular["max_angular_distortion"],
                "limit": angular["allowable_angular_distortion"],
                "ok": bool(angular["evaluated"] and angular["ok"]),
                "unit": "δ/L",
                "relation": "le",
            }
        )

    return {
        "engine": "settlement_assessment",
        "version": "1.0",
        "method": "layered immediate + 1D consolidation + rigid-body-adjusted angular distortion",
        "footings": results,
        "angular_distortion": angular,
        "checks": checks,
        "pass": all(bool(c["ok"]) for c in checks),
        "codes": [
            "建築物基礎構造設計規範 §4.4.2～4.4.7",
            "建築物基礎構造設計規範 §4.5.3～4.5.4",
        ],
        "notes": [
            "Service loads shall follow §4.4.2; live load reduction is not inferred by this module.",
            "Immediate settlement uses a layered 2:1 stress spread; consolidation uses midpoint stress increments.",
            "Differential settlement and angular distortion are screening results, not a soil-structure interaction analysis.",
            "Under-consolidated soils, lateral pile response, raft FEM and three-dimensional stiffness redistribution are outside this calculator.",
        ],
    }


def _settlement_for_pressure(
    q_kpa: float,
    B_m: float,
    L_m: float,
    settlement: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if settlement in (None, ""):
        return None
    if not isinstance(settlement, Mapping):
        raise FoundationError("settlement must be a mapping.")
    q = settlement.get("q_kpa")
    if q in (None, ""):
        q = q_kpa
    foundation_type = str(
        settlement.get("foundation_type", "rc_isolated_or_combined")
    )
    allowable = settlement.get("allowable_total_mm")
    immediate_layers = settlement.get("immediate_layers")
    if immediate_layers in (None, ""):
        immediate_layers = settlement.get("layers")
    consolidation_layers = settlement.get("consolidation_layers")
    if immediate_layers in (None, "") and consolidation_layers in (None, ""):
        raise FoundationError(
            "settlement requires layers/immediate_layers and/or consolidation_layers."
        )

    immediate = None
    immediate_mm = 0.0
    if immediate_layers not in (None, ""):
        immediate = settlement_by_layers(
            q,
            B_m,
            L_m,
            immediate_layers,
            foundation_type=foundation_type,
            allowable_total_mm=allowable,
            stress_distribution=str(
                settlement.get("stress_distribution", "2v1")
            ),
            subdivisions=int(settlement.get("subdivisions", 20)),
        )
        immediate_mm = float(immediate["total_settlement_mm"])

    consolidation = None
    consolidation_mm = 0.0
    secondary_mm = 0.0
    if consolidation_layers not in (None, ""):
        consolidation = consolidation_by_layers(
            q,
            B_m,
            L_m,
            consolidation_layers,
            foundation_type=foundation_type,
            allowable_total_mm=allowable,
            stress_distribution=str(
                settlement.get("stress_distribution", "2v1")
            ),
        )
        consolidation_mm = float(consolidation["primary_consolidation_mm"])
        secondary_mm = float(consolidation["secondary_compression_mm"])

    if allowable in (None, ""):
        if foundation_type not in SETTLEMENT_LIMITS_MM:
            raise FoundationError(
                "foundation_type must be one of: "
                + ", ".join(sorted(SETTLEMENT_LIMITS_MM))
            )
        allowable_mm = SETTLEMENT_LIMITS_MM[foundation_type]
    else:
        allowable_mm = _num(
            "allowable_total_mm", allowable, minimum=0.0
        )
    total_mm = immediate_mm + consolidation_mm + secondary_mm
    base = dict(immediate) if immediate is not None else {
        "method": "layered settlement",
        "q_kpa": round(float(q), 3),
        "B_m": round(B_m, 4),
        "L_m": round(L_m, 4),
        "foundation_type": foundation_type,
        "layers": [],
    }
    base.update(
        {
            "method": (
                "layered 2:1 immediate + one-dimensional consolidation"
                if immediate is not None and consolidation is not None
                else (
                    "one-dimensional consolidation"
                    if consolidation is not None
                    else "layered 2:1 immediate"
                )
            ),
            "immediate_settlement_mm": round(immediate_mm, 4),
            "primary_consolidation_mm": round(consolidation_mm, 4),
            "secondary_compression_mm": round(secondary_mm, 4),
            "total_settlement_mm": round(total_mm, 4),
            "allowable_total_mm": round(allowable_mm, 4),
            "ok": total_mm <= allowable_mm + 1e-9,
            "immediate": immediate,
            "consolidation": consolidation,
            "notes": [
                "Total settlement is immediate plus primary consolidation plus secondary compression.",
                "Consolidation uses §4.4.6 and secondary compression uses §4.4.7.",
                "Differential settlement and angular distortion require the separate settlement_assessment calculator.",
            ],
        }
    )
    return base


def _concrete_check(
    q_kpa: float,
    B_m: float,
    L_m: float,
    column_b_m: float,
    column_l_m: float,
    thickness_m: float,
    *,
    fc_mpa: float,
    fy_mpa: float,
    cover_mm: float,
    punching_factor: float,
) -> dict[str, Any]:
    d = thickness_m * 1000.0 - cover_mm - 10.0
    if d <= 0:
        return {"ok": False, "error": "footing effective depth <= 0"}
    q = max(0.0, q_kpa)
    ax = max(0.0, (B_m - column_b_m) / 2.0)
    ay = max(0.0, (L_m - column_l_m) / 2.0)
    # One-way action: pressure on the projection beyond d from the face.
    vx = q * L_m * max(0.0, ax - d / 1000.0)
    vy = q * B_m * max(0.0, ay - d / 1000.0)
    vc_x = 0.17 * math.sqrt(fc_mpa) * (L_m * 1000.0) * d / 1000.0 * 0.75
    vc_y = 0.17 * math.sqrt(fc_mpa) * (B_m * 1000.0) * d / 1000.0 * 0.75
    # Punching perimeter at d/2 from the column faces.
    bp = (column_b_m + d / 1000.0) * 1000.0
    lp = (column_l_m + d / 1000.0) * 1000.0
    b0 = 2.0 * (bp + lp)
    punching_force = q * max(
        0.0, B_m * L_m - (column_b_m + d / 1000.0) * (column_l_m + d / 1000.0)
    )
    punching_cap = punching_factor * math.sqrt(fc_mpa) * b0 * d / 1000.0 * 0.75
    mx = q * ax * ax / 2.0
    my = q * ay * ay / 2.0
    m_design = max(mx, my)
    flex = RC.flexure_design(
        m_design,
        b_mm=1000.0,
        h_mm=thickness_m * 1000.0,
        cc={"fc_mpa": fc_mpa, "fy_mpa": fy_mpa, "cover_mm": cover_mm},
    )
    shear_x = RC.shear_check(
        vx / max(L_m, 1e-9),
        b_mm=1000.0,
        h_mm=thickness_m * 1000.0,
        cc={"fc_mpa": fc_mpa, "fy_mpa": fy_mpa, "cover_mm": cover_mm},
    )
    shear_y = RC.shear_check(
        vy / max(B_m, 1e-9),
        b_mm=1000.0,
        h_mm=thickness_m * 1000.0,
        cc={"fc_mpa": fc_mpa, "fy_mpa": fy_mpa, "cover_mm": cover_mm},
    )
    return {
        "ok": bool(
            shear_x.get("ok")
            and shear_y.get("ok")
            and punching_force <= punching_cap
            and flex.get("ok")
        ),
        "d_mm": round(d, 1),
        "one_way_shear_x_kN": round(vx, 3),
        "one_way_shear_y_kN": round(vy, 3),
        "phiVc_x_kN": round(vc_x, 3),
        "phiVc_y_kN": round(vc_y, 3),
        "one_way_ok": bool(shear_x.get("ok") and shear_y.get("ok")),
        "punching_force_kN": round(punching_force, 3),
        "punching_capacity_kN": round(punching_cap, 3),
        "punching_ok": punching_force <= punching_cap,
        "punching_b0_mm": round(b0, 1),
        "flexure": flex,
        "flexure_ok": bool(flex.get("ok")),
        "flexure_M_kNm_per_m": round(m_design, 3),
        "shear_x": shear_x,
        "shear_y": shear_y,
    }


def analyse_isolated_footing(
    load: FootingLoads | Mapping[str, Any],
    *,
    B_m: float,
    L_m: float,
    thickness_m: float,
    column_b_m: float,
    column_l_m: float,
    q_allow_kpa: float = 200.0,
    fc_mpa: float = 28.0,
    fy_mpa: float = 420.0,
    cover_mm: float = 75.0,
    friction_coefficient: float = 0.5,
    settlement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(load, FootingLoads):
        load = FootingLoads(
            P_kN=_num("P_kN", load.get("P_kN")),
            Mx_kNm=_num("Mx_kNm", load.get("Mx_kNm", 0.0)),
            My_kNm=_num("My_kNm", load.get("My_kNm", 0.0)),
            Hx_kN=_num("Hx_kN", load.get("Hx_kN", 0.0)),
            Hy_kN=_num("Hy_kN", load.get("Hy_kN", 0.0)),
        )
    q = pressure_distribution(load.P_kN, load.Mx_kNm, load.My_kNm, B_m, L_m)
    B = _num("B_m", B_m, minimum=1e-6)
    L = _num("L_m", L_m, minimum=1e-6)
    t = _num("thickness_m", thickness_m, minimum=1e-6)
    qa = _num("q_allow_kpa", q_allow_kpa, minimum=0.0)
    conc = _concrete_check(
        q["q_max_kpa"],
        B,
        L,
        _num("column_b_m", column_b_m, minimum=1e-6),
        _num("column_l_m", column_l_m, minimum=1e-6),
        t,
        fc_mpa=_num("fc_mpa", fc_mpa, minimum=1e-6),
        fy_mpa=_num("fy_mpa", fy_mpa, minimum=1e-6),
        cover_mm=_num("cover_mm", cover_mm, minimum=0.0),
        punching_factor=0.33,
    )
    H = math.hypot(load.Hx_kN, load.Hy_kN)
    sliding_fs = (
        friction_coefficient * max(load.P_kN, 0.0) / H if H > 1e-9 else None
    )
    checks = [
        {
            "item": "最大基礎承載應力",
            "value": q["q_max_kpa"],
            "limit": qa,
            "ok": q["q_max_kpa"] <= qa,
            "unit": "kPa",
        },
        {
            "item": "基礎底面全面受壓（q_min ≥ 0）",
            "value": q["q_min_kpa"],
            "limit": 0.0,
            "ok": q["contact_full"],
            "unit": "kPa",
        },
    ]
    if sliding_fs is not None:
        checks.append(
            {
                "item": "基礎滑動 FS",
                "value": sliding_fs,
                "limit": 1.5,
                "ok": sliding_fs >= 1.5,
                "unit": "-",
            }
        )
    checks += [
        {
            "item": "單向剪力",
            "value": max(conc["one_way_shear_x_kN"], conc["one_way_shear_y_kN"]),
            "limit": min(conc["phiVc_x_kN"], conc["phiVc_y_kN"]),
            "ok": conc["one_way_ok"],
            "unit": "kN",
        },
        {
            "item": "沖剪",
            "value": conc["punching_force_kN"],
            "limit": conc["punching_capacity_kN"],
            "ok": conc["punching_ok"],
            "unit": "kN",
        },
        {
            "item": "基腳撓曲",
            "value": conc["flexure_M_kNm_per_m"],
            "limit": conc["flexure"].get("phiMn_kNm", 0.0),
            "ok": conc["flexure_ok"],
            "unit": "kN·m/m",
        },
    ]
    settlement_result = _settlement_for_pressure(
        q["q_average_kpa"], B, L, settlement
    )
    if settlement_result is not None:
        checks.append(
            {
                "item": "總沉陷量（分層 2:1 法）",
                "value": settlement_result["total_settlement_mm"],
                "limit": settlement_result["allowable_total_mm"],
                "ok": settlement_result["ok"],
                "unit": "mm",
                "relation": "le",
            }
        )
    return {
        "engine": "foundation_isolated",
        "version": "0.1",
        "geometry": {
            "B_m": B,
            "L_m": L,
            "thickness_m": t,
            "column_b_m": column_b_m,
            "column_l_m": column_l_m,
        },
        "load": {
            "P_kN": load.P_kN,
            "Mx_kNm": load.Mx_kNm,
            "My_kNm": load.My_kNm,
            "Hx_kN": load.Hx_kN,
            "Hy_kN": load.Hy_kN,
        },
        "pressure": q,
        "concrete": conc,
        "settlement": settlement_result,
        "checks": checks,
        "pass": all(c["ok"] for c in checks),
        "notes": [
            "Bearing pressure uses a rigid rectangular footing with q=P/A±M/S.",
            "Punching and one-way shear are preliminary RC checks; pile caps and seismic detailing require a full design.",
            "Allowable bearing must come from a geotechnical report, not this module's default.",
            "When settlement layers are supplied, immediate settlement uses a layered 2:1 stress spread; differential settlement is separate.",
        ],
    }


def size_isolated_footing(
    P_kN: float,
    Mx_kNm: float,
    My_kNm: float,
    *,
    q_allow_kpa: float = 200.0,
    column_b_m: float = 0.4,
    column_l_m: float = 0.4,
    min_side_m: float = 1.0,
    max_side_m: float = 8.0,
    thickness_options: Iterable[float] = (0.3, 0.4, 0.5, 0.6, 0.8, 1.0),
) -> dict[str, Any]:
    """Search the smallest square/rectangular footing that passes basic checks."""

    best = None
    for t in thickness_options:
        side = min_side_m
        while side <= max_side_m + 1e-9:
            B = round(side, 2)
            L = round(side, 2)
            result = analyse_isolated_footing(
                FootingLoads(P_kN, Mx_kNm, My_kNm),
                B_m=B,
                L_m=L,
                thickness_m=t,
                column_b_m=column_b_m,
                column_l_m=column_l_m,
                q_allow_kpa=q_allow_kpa,
            )
            if result["pass"]:
                best = result
                break
            side += 0.1
        if best:
            break
    if not best:
        return {
            "ok": False,
            "error": "No footing within the search limits passes all checks.",
        }
    return {"ok": True, **best}


def _combined_internal_forces(
    P_total: float,
    M_about_centroid: float,
    B_m: float,
    L_m: float,
    columns: list[tuple[float, float]],
) -> dict[str, Any]:
    A = B_m * L_m
    I = B_m * L_m**3 / 12.0
    # q(x) = P/A + M*(x-L/2)/I, positive upward.
    q = [P_total / A + M_about_centroid * (x - L_m / 2.0) / I for x in (0.0, L_m)]
    xs = sorted({0.0, L_m} | {x for x, _ in columns})
    max_v = max_m = 0.0
    for x in xs:
        v = 0.0
        # Integrate upward pressure from the left edge to x.
        v += (q[0] + (q[0] + (q[1] - q[0]) * x / L_m)) * x / 2.0 * B_m
        for cx, cp in columns:
            if cx <= x + 1e-12:
                v -= cp
        max_v = max(max_v, abs(v))
        m = 0.0
        # ∫0^x V(ξ)dξ, trapezoidal on a fine grid.
        n = 200
        for i in range(1, n + 1):
            x0 = x * (i - 1) / n
            x1 = x * i / n
            v0 = (q[0] + (q[0] + (q[1] - q[0]) * x0 / L_m)) * x0 / 2.0 * B_m
            v1 = (q[0] + (q[0] + (q[1] - q[0]) * x1 / L_m)) * x1 / 2.0 * B_m
            for cx, cp in columns:
                if cx <= x0 + 1e-12:
                    v0 -= cp
                if cx <= x1 + 1e-12:
                    v1 -= cp
            m += (v0 + v1) / 2.0 * (x1 - x0)
        max_m = max(max_m, abs(m))
    return {
        "q_left_kpa": q[0],
        "q_right_kpa": q[1],
        "max_shear_kN": max_v,
        "max_moment_kNm": max_m,
    }


def analyse_combined_footing(
    columns: Iterable[Mapping[str, Any]],
    *,
    B_m: float,
    L_m: float,
    thickness_m: float,
    q_allow_kpa: float = 200.0,
    column_b_m: float = 0.4,
    column_l_m: float = 0.4,
    fc_mpa: float = 28.0,
    fy_mpa: float = 420.0,
    settlement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rigid combined footing with column positions measured from the left edge."""

    cols = []
    for i, c in enumerate(columns):
        cols.append(
            (
                _num(f"column {i} x_m", c.get("x_m", c.get("position_m")), minimum=0.0),
                _num(f"column {i} P_kN", c.get("P_kN"), minimum=0.0),
                _num(f"column {i} M_kNm", c.get("M_kNm", 0.0)),
            )
        )
    if len(cols) < 2:
        raise FoundationError("A combined footing needs at least two columns.")
    B = _num("B_m", B_m, minimum=1e-6)
    L = _num("L_m", L_m, minimum=1e-6)
    t = _num("thickness_m", thickness_m, minimum=1e-6)
    P_total = sum(p for _, p, _ in cols)
    M_col = sum(m for _, _, m in cols)
    xbar = sum(x * p for x, p, _ in cols) / P_total if P_total > 1e-12 else 0.0
    M_centroid = sum(p * (x - L / 2.0) + m for x, p, m in cols)
    q = pressure_distribution(P_total, M_centroid, 0.0, B, L)
    internal = _combined_internal_forces(
        P_total, M_centroid, B, L, [(x, p) for x, p, _ in cols]
    )
    beam = RC.beam_design(
        internal["max_moment_kNm"] / B,
        internal["max_shear_kN"] / B,
        b_mm=1000.0,
        h_mm=t * 1000.0,
        fc_mpa=fc_mpa,
        fy_mpa=fy_mpa,
        cover_mm=75.0,
    )
    conc = _concrete_check(
        max(q["q_max_kpa"], 0.0),
        B,
        L,
        column_b_m,
        column_l_m,
        t,
        fc_mpa=fc_mpa,
        fy_mpa=fy_mpa,
        cover_mm=75.0,
        punching_factor=0.33,
    )
    checks = [
        {"item": "最大基礎承載應力", "value": q["q_max_kpa"], "limit": q_allow_kpa,
         "ok": q["q_max_kpa"] <= q_allow_kpa, "unit": "kPa"},
        {"item": "基礎底面全面受壓（q_min ≥ 0）", "value": q["q_min_kpa"], "limit": 0.0,
         "ok": q["contact_full"], "unit": "kPa"},
        {"item": "縱向撓曲", "value": beam["flexure"].get("Mu_kNm", 0.0),
         "limit": beam["flexure"].get("phiMn_kNm", 0.0),
         "ok": beam["flexure"].get("ok"), "unit": "kN·m/m"},
        {"item": "沖剪", "value": conc["punching_force_kN"],
         "limit": conc["punching_capacity_kN"], "ok": conc["punching_ok"], "unit": "kN"},
    ]
    settlement_result = _settlement_for_pressure(
        q["q_average_kpa"], B, L, settlement
    )
    if settlement_result is not None:
        checks.append(
            {
                "item": "總沉陷量（分層 2:1 法）",
                "value": settlement_result["total_settlement_mm"],
                "limit": settlement_result["allowable_total_mm"],
                "ok": settlement_result["ok"],
                "unit": "mm",
                "relation": "le",
            }
        )
    return {
        "engine": "foundation_combined",
        "version": "0.1",
        "columns": [
            {"x_m": x, "P_kN": p, "M_kNm": m} for x, p, m in cols
        ],
        "geometry": {"B_m": B, "L_m": L, "thickness_m": t},
        "resultant_x_m": round(xbar, 3),
        "pressure": q,
        "internal": {k: round(v, 3) for k, v in internal.items()},
        "beam_design": beam,
        "concrete": conc,
        "settlement": settlement_result,
        "checks": checks,
        "pass": all(c["ok"] for c in checks),
        "notes": [
            "Combined footing is treated as a rigid longitudinal strip; soil pressure is linear.",
            "Transverse reinforcement under each column and full 3D punching must be detailed separately.",
            "When settlement layers are supplied, immediate settlement uses a layered 2:1 stress spread; differential settlement is separate.",
        ],
    }


def pile_group_check(
    piles: Iterable[Mapping[str, Any]],
    *,
    P_kN: float,
    Mx_kNm: float = 0.0,
    My_kNm: float = 0.0,
    Q_allow_kN: float,
) -> dict[str, Any]:
    """Rigid pile-cap load distribution by axial stiffness (equal piles)."""

    positions = []
    for i, p in enumerate(piles):
        positions.append(
            (
                _num(f"pile {i} x_m", p.get("x_m"), minimum=-1e9),
                _num(f"pile {i} y_m", p.get("y_m"), minimum=-1e9),
            )
        )
    if not positions:
        raise FoundationError("pile list cannot be empty.")
    P = _num("P_kN", P_kN)
    Mx = _num("Mx_kNm", Mx_kNm)
    My = _num("My_kNm", My_kNm)
    Qa = _num("Q_allow_kN", Q_allow_kN, minimum=0.0)
    n = len(positions)
    xbar = sum(x for x, _ in positions) / n
    ybar = sum(y for _, y in positions) / n
    Iy = sum((x - xbar) ** 2 for x, _ in positions)
    Ix = sum((y - ybar) ** 2 for _, y in positions)
    loads = []
    for i, (x, y) in enumerate(positions, 1):
        force = P / n
        if Iy > 1e-12:
            force += My * (x - xbar) / Iy
        if Ix > 1e-12:
            force += Mx * (y - ybar) / Ix
        loads.append(
            {
                "pile": i,
                "x_m": x,
                "y_m": y,
                "P_kN": round(force, 3),
                "ok": force <= Qa,
            }
        )
    max_p = max(row["P_kN"] for row in loads)
    min_p = min(row["P_kN"] for row in loads)
    return {
        "engine": "pile_group",
        "version": "0.1",
        "n_piles": n,
        "P_kN": P,
        "Mx_kNm": Mx,
        "My_kNm": My,
        "Ix_m2": round(Ix, 4),
        "Iy_m2": round(Iy, 4),
        "max_pile_load_kN": round(max_p, 3),
        "min_pile_load_kN": round(min_p, 3),
        "Q_allow_kN": Qa,
        "checks": [
            {"item": "最大基樁軸力", "value": max_p, "limit": Qa,
             "ok": max_p <= Qa, "unit": "kN"},
            {"item": "最小基樁軸力（避免拉力）", "value": min_p, "limit": 0.0,
             "ok": min_p >= -1e-9, "unit": "kN"},
        ],
        "piles": loads,
        "pass": max_p <= Qa and min_p >= -1e-9,
        "notes": [
            "Pile loads assume equal axial stiffness and a rigid cap.",
            "Lateral pile capacity, group efficiency, settlement and uplift are not included.",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    lines = [f"基礎型式：{result['engine']}"]
    for c in result.get("checks", []):
        value = c.get("value")
        value_text = (
            "—"
            if value is None
            else (
                f"{float(value):.6f}"
                if abs(float(value)) < 0.01
                else f"{float(value):.3f}"
            )
        )
        limit = c.get("limit")
        limit_text = (
            "—"
            if limit is None
            else (
                f"{float(limit):.6f}"
                if abs(float(limit)) < 0.01
                else f"{float(limit):.3f}"
            )
        )
        lines.append(
            "  [%s] %s：%s / %s"
            % ("OK" if c["ok"] else "NG", c["item"], value_text, limit_text)
        )
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（獨立基腳、組合基腳、群樁、壓密沉陷）。"""
    from _selftest_util import Checker

    c = Checker("基礎與沉陷")
    iso = analyse_isolated_footing(
        {"P_kN": 1000.0, "Mx_kNm": 100.0, "My_kNm": 50.0},
        B_m=2.5, L_m=2.5, thickness_m=0.6, column_b_m=0.45, column_l_m=0.45,
        q_allow_kpa=250.0, fc_mpa=28.0, fy_mpa=420.0,
    )
    section_modulus = 2.5 ** 3 / 6.0
    c.close("獨立基腳 q_avg＝P/A", iso["pressure"]["q_average_kpa"], 1000.0 / 2.5 ** 2)
    c.close("獨立基腳 q_max＝P/A＋Mx/Sx＋My/Sy", iso["pressure"]["q_max_kpa"],
            160.0 + 150.0 / section_modulus)
    c.close("獨立基腳 q_min＝P/A－Mx/Sx－My/Sy", iso["pressure"]["q_min_kpa"],
            160.0 - 150.0 / section_modulus)
    d_mm = iso["concrete"]["d_mm"]
    b0_mm = 4.0 * (450.0 + d_mm)
    c.close("沖剪周長 b0＝4(c＋d)", iso["concrete"]["punching_b0_mm"], b0_mm, tol=1e-3)
    c.close("沖剪容量 φVc＝0.75·0.33√fc'·b0·d", iso["concrete"]["punching_capacity_kN"],
            0.75 * 0.33 * 28.0 ** 0.5 * b0_mm * d_mm / 1000.0, tol=1e-3)

    combined = analyse_combined_footing(
        [{"x_m": 0.5, "P_kN": 500.0}, {"x_m": 3.5, "P_kN": 700.0}],
        B_m=2.75, L_m=4.0, thickness_m=0.7, q_allow_kpa=200.0,
    )
    q_avg = 1200.0 / (2.75 * 4.0)
    e = 2.25 - 2.0
    c.close("組合基腳合力位置 x̄＝Σ(P·x)/ΣP", combined["resultant_x_m"],
            (500.0 * 0.5 + 700.0 * 3.5) / 1200.0)
    c.close("組合基腳左緣 q＝P/A·(1－6e/L)", combined["internal"]["q_left_kpa"],
            q_avg * (1.0 - 6.0 * e / 4.0), tol=1e-3)
    c.close("組合基腳右緣 q＝P/A·(1＋6e/L)", combined["internal"]["q_right_kpa"],
            q_avg * (1.0 + 6.0 * e / 4.0), tol=1e-3)
    c.close("組合基腳 q_max＝右緣 q（偏心沿 L 向）", combined["pressure"]["q_max_kpa"],
            q_avg * (1.0 + 6.0 * e / 4.0), tol=1e-3)
    c.close("組合基腳 q_min＝左緣 q（偏心沿 L 向）", combined["pressure"]["q_min_kpa"],
            q_avg * (1.0 - 6.0 * e / 4.0), tol=1e-3)

    piles = [{"x_m": x, "y_m": y} for y in (-1.0, 1.0) for x in (-1.0, 1.0)]
    group = pile_group_check(piles, P_kN=2000.0, Mx_kNm=400.0, Q_allow_kN=600.0)
    c.close("群樁最大樁載＝P/n＋Mx·y/Σy²", group["max_pile_load_kN"], 500.0 + 400.0 * 1.0 / 4.0)
    c.close("群樁最小樁載＝P/n－Mx·y/Σy²", group["min_pile_load_kN"], 500.0 - 400.0 * 1.0 / 4.0)

    footing = {
        "q_kpa": 130.0, "B_m": 2.2, "L_m": 2.2,
        "immediate_layers": [{"thickness_m": 2.0, "constrained_modulus_kpa": 15000.0}],
        "consolidation_layers": [{
            "thickness_m": 3.0, "initial_effective_stress_kpa": 80.0, "compression_index": 0.24,
            "recompression_index": 0.05, "preconsolidation_stress_kpa": 140.0, "void_ratio": 0.9,
            "secondary_compression_index": 0.002, "consolidation_start_year": 1.0,
            "assessment_end_year": 30.0,
        }],
    }
    settled = settlement_assessment({
        "default_foundation_type": "rc_isolated_or_combined",
        "angular_distortion_limit": 0.002,
        "footings": [dict(footing, id="F%d" % i, x_m=x, y_m=y)
                     for i, (x, y) in enumerate(((0.0, 0.0), (6.0, 0.0), (0.0, 6.0), (6.0, 6.0)))],
    })["footings"][0]
    delta = 130.0 * 2.2 ** 2 / (2.2 + 1.5) ** 2
    c.close("再壓縮沉陷＝Cr/(1+e)·H·log(σf/σ0)（2:1 法，mm）", settled["primary_consolidation_mm"],
            0.05 / 1.9 * 3000.0 * math.log10((80.0 + delta) / 80.0), tol=1e-3)
    c.close("次壓縮沉陷＝Cα·H·log(t2/t1)（mm）", settled["secondary_compression_mm"],
            0.002 * 3000.0 * math.log10(30.0), tol=1e-3)
    return c.run()


def main() -> None:
    """Command-line adapter for the three foundation analysis modes."""

    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="基礎承載、沖剪、剪力、樁帽與沉陷初步分析"
    )
    ap.add_argument("mode", choices=["isolated", "combined", "pile", "settlement"])
    ap.add_argument("case_json", help="JSON 輸入；各模式的鍵值見 docs\\設計計算工具索引.md")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with open(a.case_json, encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, Mapping):
        ap.error("case_json 必須是物件")
    if a.mode == "settlement":
        result = settlement_assessment(raw)
    elif a.mode == "isolated":
        load = raw.get("load") or raw
        geometry = raw.get("geometry") or raw
        result = analyse_isolated_footing(
            load,
            B_m=geometry.get("B_m", raw.get("B_m")),
            L_m=geometry.get("L_m", raw.get("L_m")),
            thickness_m=geometry.get("thickness_m", raw.get("thickness_m")),
            column_b_m=geometry.get("column_b_m", raw.get("column_b_m")),
            column_l_m=geometry.get("column_l_m", raw.get("column_l_m")),
            q_allow_kpa=float(raw.get("q_allow_kpa", 200.0)),
            fc_mpa=float(raw.get("fc_mpa", 28.0)),
            fy_mpa=float(raw.get("fy_mpa", 420.0)),
            cover_mm=float(raw.get("cover_mm", 75.0)),
            friction_coefficient=float(raw.get("friction_coefficient", 0.5)),
        )
    elif a.mode == "combined":
        columns = raw.get("columns")
        if not isinstance(columns, list):
            ap.error("combined 模式需要 columns 陣列")
        result = analyse_combined_footing(
            columns,
            B_m=raw.get("B_m"),
            L_m=raw.get("L_m"),
            thickness_m=raw.get("thickness_m"),
            q_allow_kpa=float(raw.get("q_allow_kpa", 200.0)),
            column_b_m=float(raw.get("column_b_m", 0.4)),
            column_l_m=float(raw.get("column_l_m", 0.4)),
            fc_mpa=float(raw.get("fc_mpa", 28.0)),
            fy_mpa=float(raw.get("fy_mpa", 420.0)),
        )
    else:
        piles = raw.get("piles")
        if not isinstance(piles, list):
            ap.error("pile 模式需要 piles 陣列")
        result = pile_group_check(
            piles,
            P_kN=raw.get("P_kN"),
            Mx_kNm=float(raw.get("Mx_kNm", 0.0)),
            My_kNm=float(raw.get("My_kNm", 0.0)),
            Q_allow_kN=raw.get("Q_allow_kN"),
        )
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if a.json
        else format_report(result)
    )
    raise SystemExit(0 if result.get("pass", False) else 1)


if __name__ == "__main__":
    main()

