"""Equivalent-static analysis for small regular reinforced-concrete frames.

The module generates a 2D frame from orthogonal grids and storey heights,
applies dead, live and lateral load cases, runs the shared direct-stiffness
engine, forms load combinations, envelopes member actions, and performs
preliminary beam/column RC checks.

Scope and limitations
---------------------
* One representative 2D frame, not a full 3D torsional building model.
* Equivalent-static lateral forces.  Code-specific seismic base shear,
  accidental torsion, regularity and drift limits remain project inputs.
* Columns are checked for uniaxial bending about the frame plane.  Biaxial
  bending and second-order/slenderness effects require a full building model.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import frame_analysis as FA
import load_combinations as LC
import rc_design as RC


class BuildingFrameError(ValueError):
    """Raised for invalid building-frame geometry or loads."""


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise BuildingFrameError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise BuildingFrameError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise BuildingFrameError(f"{name} must be >= {minimum}; got {v}.")
    return v


@dataclass(frozen=True)
class BuildingGeometry:
    x_grid_m: tuple[float, ...]
    storey_heights_m: tuple[float, ...]
    beam_width_mm: float = 300.0
    beam_depth_mm: float = 600.0
    column_width_mm: float = 400.0
    column_depth_mm: float = 400.0
    E_kn_m2: float = 23_000_000.0
    fc_mpa: float = 28.0
    fy_mpa: float = 420.0
    concrete_unit_weight_kn_m3: float = 24.0
    support: str = "fixed"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BuildingGeometry":
        if not isinstance(data, Mapping):
            raise BuildingFrameError("geometry must be a mapping.")
        xs = tuple(_num("x_grid_m", v) for v in data.get("x_grid_m", ()))
        hs = tuple(
            _num("storey_heights_m", v, minimum=1e-6)
            for v in data.get("storey_heights_m", ())
        )
        if len(xs) < 2:
            raise BuildingFrameError("x_grid_m needs at least two grid lines.")
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise BuildingFrameError("x_grid_m must be strictly increasing.")
        if not hs:
            raise BuildingFrameError("storey_heights_m cannot be empty.")
        support = str(data.get("support", "fixed")).lower()
        if support not in ("fixed", "pinned"):
            raise BuildingFrameError("support must be fixed or pinned.")
        return cls(
            x_grid_m=xs,
            storey_heights_m=hs,
            beam_width_mm=_num(
                "beam_width_mm", data.get("beam_width_mm", 300.0), minimum=1.0
            ),
            beam_depth_mm=_num(
                "beam_depth_mm", data.get("beam_depth_mm", 600.0), minimum=1.0
            ),
            column_width_mm=_num(
                "column_width_mm", data.get("column_width_mm", 400.0), minimum=1.0
            ),
            column_depth_mm=_num(
                "column_depth_mm", data.get("column_depth_mm", 400.0), minimum=1.0
            ),
            E_kn_m2=_num("E_kn_m2", data.get("E_kn_m2", 23_000_000.0), minimum=1e-6),
            fc_mpa=_num("fc_mpa", data.get("fc_mpa", 28.0), minimum=1e-6),
            fy_mpa=_num("fy_mpa", data.get("fy_mpa", 420.0), minimum=1e-6),
            concrete_unit_weight_kn_m3=_num(
                "concrete_unit_weight_kn_m3",
                data.get("concrete_unit_weight_kn_m3", 24.0),
                minimum=1e-6,
            ),
            support=support,
        )

    @property
    def elevations(self) -> tuple[float, ...]:
        values = [0.0]
        for h in self.storey_heights_m:
            values.append(values[-1] + h)
        return tuple(values)

    @property
    def plan_width_m(self) -> float:
        return self.x_grid_m[-1] - self.x_grid_m[0]

    @property
    def beam_tributary_width_m(self) -> float:
        return sum(b - a for a, b in zip(self.x_grid_m, self.x_grid_m[1:])) / (
            len(self.x_grid_m) - 1
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "x_grid_m": list(self.x_grid_m),
            "storey_heights_m": list(self.storey_heights_m),
            "elevations_m": list(self.elevations),
            "beam_mm": [self.beam_width_mm, self.beam_depth_mm],
            "column_mm": [self.column_width_mm, self.column_depth_mm],
            "support": self.support,
        }


@dataclass(frozen=True)
class BuildingLoads:
    dead_area_kn_m2: float = 5.0
    live_area_kn_m2: float = 2.0
    base_shear_coefficient: float = 0.0
    base_shear_kn: float | None = None
    lateral_forces_kn: tuple[float, ...] = ()
    drift_limit_ratio: float = 0.005
    include_wind: bool = False
    wind_base_shear_kn: float | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "BuildingLoads":
        data = data or {}
        if not isinstance(data, Mapping):
            raise BuildingFrameError("loads must be a mapping.")
        lateral = tuple(
            _num("lateral_forces_kn", v) for v in data.get("lateral_forces_kn", ())
        )
        return cls(
            dead_area_kn_m2=_num(
                "dead_area_kn_m2", data.get("dead_area_kn_m2", 5.0), minimum=0.0
            ),
            live_area_kn_m2=_num(
                "live_area_kn_m2", data.get("live_area_kn_m2", 2.0), minimum=0.0
            ),
            base_shear_coefficient=_num(
                "base_shear_coefficient",
                data.get("base_shear_coefficient", 0.0),
                minimum=0.0,
            ),
            base_shear_kn=(
                None
                if data.get("base_shear_kn") in (None, "")
                else _num("base_shear_kn", data["base_shear_kn"], minimum=0.0)
            ),
            lateral_forces_kn=lateral,
            drift_limit_ratio=_num(
                "drift_limit_ratio",
                data.get("drift_limit_ratio", 0.005),
                minimum=1e-9,
            ),
            include_wind=bool(data.get("include_wind", False)),
            wind_base_shear_kn=(
                None
                if data.get("wind_base_shear_kn") in (None, "")
                else _num("wind_base_shear_kn", data["wind_base_shear_kn"], minimum=0.0)
            ),
        )


def _member(
    member_id: str,
    i: str,
    j: str,
    kind: str,
    width_mm: float,
    depth_mm: float,
    E_kn_m2: float,
    loads: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    b, h = width_mm / 1000.0, depth_mm / 1000.0
    return {
        "id": member_id,
        "i": i,
        "j": j,
        "kind": kind,
        "width_mm": width_mm,
        "depth_mm": depth_mm,
        "E_kn_m2": E_kn_m2,
        "area_m2": b * h,
        "inertia_m4": b * h**3 / 12.0,
        "loads": dict(loads or {}),
    }


def generate_frame(
    geometry: BuildingGeometry, loads: BuildingLoads
) -> dict[str, Any]:
    """Generate nodes, members and D/L/E(W) base load cases."""

    elevations = geometry.elevations
    nodes: list[dict[str, Any]] = []
    node_ids: dict[tuple[int, int], str] = {}
    for level, y in enumerate(elevations):
        for ix, x in enumerate(geometry.x_grid_m):
            nid = f"N{level}_{ix}"
            node_ids[(level, ix)] = nid
            node: dict[str, Any] = {"id": nid, "x": x, "y": y}
            if level == 0:
                node["restraint"] = (
                    (True, True, True)
                    if geometry.support == "fixed"
                    else (True, True, False)
                )
            nodes.append(node)

    beams: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    for level in range(1, len(elevations)):
        for ix in range(len(geometry.x_grid_m) - 1):
            beams.append(
                _member(
                    f"B{level}_{ix}",
                    node_ids[(level, ix)],
                    node_ids[(level, ix + 1)],
                    "beam",
                    geometry.beam_width_mm,
                    geometry.beam_depth_mm,
                    geometry.E_kn_m2,
                )
            )
    for level in range(1, len(elevations)):
        for ix in range(len(geometry.x_grid_m)):
            columns.append(
                _member(
                    f"C{level}_{ix}",
                    node_ids[(level - 1, ix)],
                    node_ids[(level, ix)],
                    "column",
                    geometry.column_width_mm,
                    geometry.column_depth_mm,
                    geometry.E_kn_m2,
                )
            )

    tributary = geometry.beam_tributary_width_m
    beam_sw = (
        geometry.concrete_unit_weight_kn_m3
        * geometry.beam_width_mm
        * geometry.beam_depth_mm
        / 1_000_000.0
    )
    col_sw = (
        geometry.concrete_unit_weight_kn_m3
        * geometry.column_width_mm
        * geometry.column_depth_mm
        / 1_000_000.0
    )
    dead_beam_q = loads.dead_area_kn_m2 * tributary + beam_sw
    live_beam_q = loads.live_area_kn_m2 * tributary

    case_member_loads: dict[str, dict[str, dict[str, float]]] = {
        "D": {}, "L": {}, "E": {}, "W": {}
    }
    for m in beams:
        case_member_loads["D"][m["id"]] = {"wy": -dead_beam_q}
        case_member_loads["L"][m["id"]] = {"wy": -live_beam_q}
    for m in columns:
        case_member_loads["D"][m["id"]] = {"wy": -col_sw}

    # Storey weights for automatic equivalent-static lateral distribution.
    span = geometry.plan_width_m
    storey_weights = []
    for level in range(1, len(elevations)):
        weight = dead_beam_q * span
        weight += col_sw * geometry.storey_heights_m[level - 1] / 2.0 * len(
            geometry.x_grid_m
        )
        if level < len(elevations) - 1:
            weight += col_sw * geometry.storey_heights_m[level] / 2.0 * len(
                geometry.x_grid_m
            )
        storey_weights.append(weight)
    total_weight = sum(storey_weights)

    def distribute_force(total_force: float) -> list[float]:
        denom = sum(
            weight * elevations[level]
            for level, weight in enumerate(storey_weights, start=1)
        )
        if denom <= 0.0:
            return [0.0] * len(storey_weights)
        return [
            total_force * weight * elevations[level] / denom
            for level, weight in enumerate(storey_weights, start=1)
        ]

    if loads.lateral_forces_kn:
        if len(loads.lateral_forces_kn) != len(storey_weights):
            raise BuildingFrameError(
                "lateral_forces_kn must have one value per storey."
            )
        seismic_forces = list(loads.lateral_forces_kn)
    else:
        base_shear = (
            loads.base_shear_kn
            if loads.base_shear_kn is not None
            else loads.base_shear_coefficient * total_weight
        )
        seismic_forces = distribute_force(base_shear)
    case_nodal_loads: dict[str, dict[str, tuple[float, float, float]]] = {
        "D": {}, "L": {}, "E": {}, "W": {}
    }
    for level, force in enumerate(seismic_forces, start=1):
        # One force is shared by all columns of the representative frame.
        for ix in range(len(geometry.x_grid_m)):
            case_nodal_loads["E"][node_ids[(level, ix)]] = (
                force / len(geometry.x_grid_m),
                0.0,
                0.0,
            )
    if loads.include_wind:
        wind_total = loads.wind_base_shear_kn or 0.0
        for level, force in enumerate(distribute_force(wind_total), start=1):
            for ix in range(len(geometry.x_grid_m)):
                previous = case_nodal_loads["W"].get(node_ids[(level, ix)], (0.0, 0.0, 0.0))
                case_nodal_loads["W"][node_ids[(level, ix)]] = (
                    previous[0] + force / len(geometry.x_grid_m),
                    previous[1],
                    previous[2],
                )
    # Do not pass an empty E or W case to the combination generator.
    if not seismic_forces or all(abs(v) < 1e-12 for v in seismic_forces):
        case_nodal_loads.pop("E", None)
        case_member_loads.pop("E", None)
    if not loads.include_wind:
        case_nodal_loads.pop("W", None)
        case_member_loads.pop("W", None)

    return {
        "nodes": nodes,
        "members": beams + columns,
        "member_load_cases": case_member_loads,
        "nodal_load_cases": case_nodal_loads,
        "storey_weights_kn": storey_weights,
        "total_dead_weight_kn": total_weight,
        "beam_dead_line_load_kn_m": dead_beam_q,
        "beam_live_line_load_kn_m": live_beam_q,
    }


def _compose_case(
    base_nodes: Iterable[Mapping[str, Any]],
    base_members: Iterable[Mapping[str, Any]],
    nodal_cases: Mapping[str, Mapping[str, tuple[float, float, float]]],
    member_cases: Mapping[str, Mapping[str, Mapping[str, float]]],
    factors: Mapping[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [dict(n) for n in base_nodes]
    node_by_id = {str(n["id"]): n for n in nodes}
    for case, factor in factors.items():
        if abs(factor) < 1e-15:
            continue
        for nid, load in nodal_cases.get(case, {}).items():
            node = node_by_id[nid]
            node["fx"] = float(node.get("fx", 0.0)) + factor * load[0]
            node["fy"] = float(node.get("fy", 0.0)) + factor * load[1]
            node["mz"] = float(node.get("mz", 0.0)) + factor * load[2]
    members = [dict(m) for m in base_members]
    member_by_id = {str(m["id"]): m for m in members}
    for case, factor in factors.items():
        if abs(factor) < 1e-15:
            continue
        for mid, loads in member_cases.get(case, {}).items():
            target = member_by_id[mid]
            merged = dict(target.get("loads") or {})
            for key, value in loads.items():
                merged[key] = float(merged.get(key, 0.0)) + factor * float(value)
            target["loads"] = merged
    return nodes, members


def analyse(
    geometry_input: Mapping[str, Any] | BuildingGeometry,
    loads_input: Mapping[str, Any] | BuildingLoads | None = None,
    *,
    custom_combinations: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyse a regular 2D RC frame and return envelopes and preliminary checks."""

    geometry = (
        geometry_input
        if isinstance(geometry_input, BuildingGeometry)
        else BuildingGeometry.from_mapping(geometry_input)
    )
    loads = (
        loads_input
        if isinstance(loads_input, BuildingLoads)
        else BuildingLoads.from_mapping(loads_input)
    )
    built = generate_frame(geometry, loads)
    cases = list(built["nodal_load_cases"].keys())
    custom = list(custom_combinations) if custom_combinations is not None else None
    combos = LC.combinations(
        cases,
        profile="general",
        include_service=True,
        custom=custom,
    )

    results: dict[str, FA.FrameResult] = {}
    for combo in combos:
        nodes, members = _compose_case(
            built["nodes"],
            built["members"],
            built["nodal_load_cases"],
            built["member_load_cases"],
            combo.factors,
        )
        results[combo.id] = FA.FrameModel(nodes, members).solve()

    strength = [c for c in combos if c.kind == "strength"]
    service = [c for c in combos if c.kind == "service"]
    member_rows: list[dict[str, Any]] = []
    member_designs: list[dict[str, Any]] = []
    for base_member in built["members"]:
        mid = base_member["id"]
        strength_results = [
            (c, results[c.id].members[mid]) for c in strength
        ]
        service_results = [
            (c, results[c.id].members[mid]) for c in service
        ]
        combo_m, mr_m = max(
            strength_results, key=lambda item: item[1].max_abs_moment_knm
        )
        combo_v, mr_v = max(
            strength_results,
            key=lambda item: max(abs(x) for x in item[1].shear_end_kn),
        )
        combo_p, mr_p = min(
            strength_results,
            key=lambda item: min(item[1].axial_end_kn),
        )
        service_m = max(
            (abs(r.max_abs_moment_knm) for _, r in service_results),
            default=abs(mr_m.max_abs_moment_knm) / 1.4,
        )
        Mu = mr_m.max_abs_moment_knm
        Vu = max(abs(x) for x in mr_v.shear_end_kn)
        P_end = min(mr_p.axial_end_kn)
        Pu = max(0.0, -P_end)
        if base_member["kind"] == "beam":
            design = RC.beam_design(
                Mu,
                Vu,
                b_mm=base_member["width_mm"],
                h_mm=base_member["depth_mm"],
                M_service_kNm=service_m,
                fc_mpa=geometry.fc_mpa,
                fy_mpa=geometry.fy_mpa,
                cover_mm=40.0,
            )
            design["kind"] = "beam"
        else:
            design = RC.column_design(
                Pu,
                Mu,
                b_mm=base_member["width_mm"],
                h_mm=base_member["depth_mm"],
                fc_mpa=geometry.fc_mpa,
                fy_mpa=geometry.fy_mpa,
                cover_mm=40.0,
            )
            design["kind"] = "column"
        design.update(
            {
                "member": mid,
                "Mu_kNm": round(Mu, 3),
                "Vu_kN": round(Vu, 3),
                "Pu_kN": round(Pu, 3),
                "M_combination": combo_m.id,
                "V_combination": combo_v.id,
                "P_combination": combo_p.id,
            }
        )
        member_designs.append(design)
        member_rows.append(
            {
                "member": mid,
                "kind": base_member["kind"],
                "M_service_kNm": round(service_m, 3),
                "Mu_kNm": round(Mu, 3),
                "Vu_kN": round(Vu, 3),
                "Pu_kN": round(Pu, 3),
                "control": "%s / %s / %s" % (combo_m.id, combo_v.id, combo_p.id),
                "ok": bool(design.get("ok")),
            }
        )

    # Storey drifts from horizontal displacement differences.
    drift_rows = []
    elevations = geometry.elevations
    for combo in combos:
        if combo.kind != "strength":
            continue
        max_drift = 0.0
        max_level = 0
        for level in range(1, len(elevations)):
            height = elevations[level] - elevations[level - 1]
            for ix in range(len(geometry.x_grid_m)):
                lower = results[combo.id].displacements[f"N{level - 1}_{ix}"][0]
                upper = results[combo.id].displacements[f"N{level}_{ix}"][0]
                drift = abs(upper - lower) / height
                if drift > max_drift:
                    max_drift, max_level = drift, level
        drift_rows.append(
            {
                "combination": combo.id,
                "max_storey_drift_ratio": round(max_drift, 6),
                "storey": max_level,
                "limit": loads.drift_limit_ratio,
                "ok": max_drift <= loads.drift_limit_ratio,
            }
        )

    checks: list[dict[str, Any]] = []
    for design in member_designs:
        member = design["member"]
        if design["kind"] == "beam":
            flex = design.get("flexure") or {}
            shear = design.get("shear") or {}
            crack = design.get("crack") or {}
            checks.extend(
                [
                    {
                        "item": "%s 梁撓曲" % member,
                        "value": flex.get("Mu_kNm"),
                        "limit": flex.get("phiMn_kNm"),
                        "unit": "kN·m",
                        "ok": bool(flex.get("ok")),
                        "relation": "le",
                    },
                    {
                        "item": "%s 梁剪力（含箍筋）" % member,
                        "value": shear.get("Vu_kN"),
                        "limit": shear.get("phiVn_kN"),
                        "unit": "kN",
                        "ok": bool(shear.get("ok")),
                        "relation": "le",
                    },
                    {
                        "item": "%s 梁裂縫寬度" % member,
                        "value": crack.get("w_mm"),
                        "limit": crack.get("limit_mm"),
                        "unit": "mm",
                        "ok": bool(crack.get("ok")),
                        "relation": "le",
                    },
                ]
            )
        else:
            chosen = design.get("chosen") or {}
            checks.append(
                {
                    "item": "%s 柱軸彎互制" % member,
                    "value": design.get("Mu_kNm"),
                    "limit": chosen.get("phiMn_available_kNm"),
                    "unit": "kN·m",
                    "ok": bool(chosen.get("ok")),
                    "relation": "le",
                }
            )
            if chosen.get("spacing_ok") is not None:
                checks.append(
                    {
                        "item": "%s 柱縱向鋼筋淨間距" % member,
                        "value": chosen.get("centre_spacing_mm"),
                        "limit": chosen.get("min_spacing_mm"),
                        "unit": "mm",
                        "ok": bool(chosen.get("spacing_ok")),
                        "relation": "ge",
                    }
                )
    governing_drift = max(
        drift_rows, key=lambda r: r["max_storey_drift_ratio"], default=None
    )
    if governing_drift:
        checks.append(
            {
                "item": "最大層間位移比",
                "value": governing_drift["max_storey_drift_ratio"],
                "limit": loads.drift_limit_ratio,
                "unit": "-",
                "ok": governing_drift["ok"],
            }
        )
    return {
        "engine": "building_frame",
        "version": "0.1",
        "geometry": geometry.as_dict(),
        "loads": {
            "dead_area_kn_m2": loads.dead_area_kn_m2,
            "live_area_kn_m2": loads.live_area_kn_m2,
            "beam_dead_line_load_kn_m": built["beam_dead_line_load_kn_m"],
            "beam_live_line_load_kn_m": built["beam_live_line_load_kn_m"],
            "storey_weights_kn": built["storey_weights_kn"],
            "total_dead_weight_kn": built["total_dead_weight_kn"],
        },
        "combinations": [c.as_dict() for c in combos],
        "members": member_rows,
        "designs": member_designs,
        "drift": drift_rows,
        "checks": checks,
        "pass": all(bool(c["ok"]) for c in checks),
        "limitations": [
            "2D representative frame; no 3D torsion or bidirectional seismic input.",
            "Columns checked for uniaxial bending only.",
            "Second-order/slenderness, joint shear, anchorage and development are not yet included.",
            "Lateral forces are equivalent static; base shear and distribution must follow the governing code.",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    g = result["geometry"]
    lines = [
        "建築 RC 平面剛架：%d 跨、%d 層"
        % (len(g["x_grid_m"]) - 1, len(g["storey_heights_m"])),
        "全寬 %.2f m、總高 %.2f m；最大層間位移比 %.5f（限 %.5f）"
        % (
            g["x_grid_m"][-1] - g["x_grid_m"][0],
            g["elevations_m"][-1],
            max((r["max_storey_drift_ratio"] for r in result["drift"]), default=0.0),
            result["drift"][0]["limit"] if result["drift"] else 0.0,
        ),
    ]
    for d in result["designs"]:
        if d["kind"] == "beam":
            f = d["flexure"]
            desc = "%s@%s" % (f.get("bar"), f.get("spacing_mm"))
            cap = f.get("phiMn_kNm", 0.0)
            shear = d.get("shear") or {}
            stirrup = shear.get("stirrup") or {}
            detail = "箍筋 %s@%s；裂縫 %.3f mm" % (
                stirrup.get("bar", "-"),
                stirrup.get("spacing_mm", "-"),
                (d.get("crack") or {}).get("w_mm") or 0.0,
            )
        else:
            chosen = d.get("chosen", {})
            desc = "%d-%s" % (chosen.get("bars_total", 0), chosen.get("bar", ""))
            cap = chosen.get("phiMn_available_kNm", 0.0)
            detail = "柱箍筋 %s@%s" % (
                (d.get("ties") or {}).get("bar", "-"),
                (d.get("ties") or {}).get("spacing_mm", "-"),
            )
        lines.append(
            "  [%s] %-7s Mu=%.1f kN·m、Vu=%.1f kN、Pu=%.1f kN、%s"
            "（容量 %.1f；%s）"
            % (
                "OK" if d.get("ok") else "NG",
                d["member"],
                d.get("Mu_kNm", 0.0),
                d.get("Vu_kN", 0.0),
                d.get("Pu_kN", 0.0),
                desc,
                cap,
                detail,
            )
        )
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（兩跨 6 m、三層 3.5 m、梁 300×650、柱 450×450）。"""
    from _selftest_util import Checker

    c = Checker("建築 RC 平面剛架")
    r = analyse(
        {"x_grid_m": [0.0, 6.0, 12.0], "storey_heights_m": [3.5, 3.5, 3.5],
         "beam_width_mm": 300.0, "beam_depth_mm": 650.0, "column_width_mm": 450.0,
         "column_depth_mm": 450.0, "support": "fixed"},
        {"dead_area_kn_m2": 5.0, "live_area_kn_m2": 2.0, "base_shear_coefficient": 0.12},
    )
    gamma_c = 24.0
    beam_dead = 5.0 * 6.0 + gamma_c * 0.30 * 0.65
    column_storey = 3 * gamma_c * 0.45 ** 2 * 3.5
    loads = r["loads"]
    c.close("梁靜載線載重＝樓板＋梁自重", loads["beam_dead_line_load_kn_m"], beam_dead, tol=1e-4)
    c.close("梁活載線載重", loads["beam_live_line_load_kn_m"], 2.0 * 6.0, tol=1e-4)
    c.close("一般樓層重＝梁＋整層柱", loads["storey_weights_kn"][0],
            12.0 * beam_dead + column_storey, tol=1e-3)
    c.close("屋頂層重＝梁＋半層柱", loads["storey_weights_kn"][2],
            12.0 * beam_dead + 0.5 * column_storey, tol=1e-3)
    c.close("總靜載重", loads["total_dead_weight_kn"],
            3 * 12.0 * beam_dead + 2.5 * column_storey, tol=1e-3)
    beam = next(d for d in r["designs"] if d.get("kind") == "beam")
    flex = beam["flexure"]
    fc_mpa, fy_mpa = 28.0, 420.0
    a = flex["As_prov_mm2"] * fy_mpa / (0.85 * fc_mpa * flex["b_mm"])
    c.close("梁 φMn＝φ·As·fy·(d－a/2)", flex["phiMn_kNm"],
            flex["phi"] * flex["As_prov_mm2"] * fy_mpa * (flex["d_mm"] - a / 2.0) / 1e6,
            tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse

    ap = argparse.ArgumentParser(description="小型 RC 建築平面剛架分析")
    ap.add_argument("case_json", nargs="?", help="含 geometry／loads 的 JSON")
    ap.add_argument("--x-grid", help="例如 0,6,12")
    ap.add_argument("--storeys", help="例如 3.5,3.5")
    ap.add_argument("--dead", type=float, default=5.0, help="樓板靜載重 kN/m²")
    ap.add_argument("--live", type=float, default=2.0, help="樓板活載重 kN/m²")
    ap.add_argument("--base-shear-coeff", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.case_json:
        data = json.load(open(a.case_json, encoding="utf-8"))
    else:
        if not a.x_grid or not a.storeys:
            ap.error("provide case_json or both --x-grid and --storeys")
        data = {
            "geometry": {
                "x_grid_m": [float(v) for v in a.x_grid.split(",")],
                "storey_heights_m": [float(v) for v in a.storeys.split(",")],
            },
            "loads": {
                "dead_area_kn_m2": a.dead,
                "live_area_kn_m2": a.live,
                "base_shear_coefficient": a.base_shear_coeff,
            },
        }
    result = analyse(data.get("geometry", {}), data.get("loads", {}))
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if a.json
        else format_report(result)
    )
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()

