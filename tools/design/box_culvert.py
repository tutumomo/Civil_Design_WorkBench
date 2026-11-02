"""Parameterized single-, double- and triple-cell box-culvert design.

The structural model is a 2D plane frame per metre of culvert length.  The
number of cells changes the node/member topology only; material, soil, water,
traffic and RC checks are shared by all cell counts.

Hydraulics reports the full-flow Manning capacity as an upper bound and checks
the normal depth plus minimum freeboard at the design flow.  When
``inlet_type`` is given it also runs the 公路排水設計規範 §6.2 inlet/outlet
control check (附錄 N/O), takes the larger headwater of the two and compares it
with the allowable headwater.  Wing walls are only checked for the geometry
values the caller supplies; scour depth is never estimated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import earth_pressure as EP
import frame_analysis as FA
import rc_design as RC
import culvert_hydraulics as CH


class BoxCulvertError(ValueError):
    """Raised for invalid culvert geometry or loads."""


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise BoxCulvertError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise BoxCulvertError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise BoxCulvertError(f"{name} must be >= {minimum}; got {v}.")
    return v


@dataclass(frozen=True)
class BoxCulvertSection:
    cell_count: int
    clear_width_m: float
    clear_height_m: float
    wall_thickness_m: float
    top_slab_thickness_m: float
    bottom_slab_thickness_m: float
    interior_wall_thickness_m: float
    length_m: float = 20.0
    cover_depth_m: float = 0.6
    concrete_unit_weight_kn_m3: float = 24.0
    E_kn_m2: float = 23_000_000.0
    fc_mpa: float = 28.0
    fy_mpa: float = 420.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | Any) -> "BoxCulvertSection":
        if not isinstance(data, Mapping):
            data = getattr(data, "values", data)
        if not isinstance(data, Mapping):
            raise BoxCulvertError("Culvert section input must be a mapping.")
        n = int(data.get("cell_count", 1))
        if n not in (1, 2, 3):
            raise BoxCulvertError("cell_count must be 1, 2 or 3.")
        wall = _num("wall_thickness_m", data.get("wall_thickness_m"), minimum=1e-6)
        return cls(
            cell_count=n,
            clear_width_m=_num("clear_width_m", data.get("clear_width_m"), minimum=1e-6),
            clear_height_m=_num("clear_height_m", data.get("clear_height_m"), minimum=1e-6),
            wall_thickness_m=wall,
            top_slab_thickness_m=_num(
                "top_slab_thickness_m", data.get("top_slab_thickness_m"), minimum=1e-6
            ),
            bottom_slab_thickness_m=_num(
                "bottom_slab_thickness_m",
                data.get("bottom_slab_thickness_m"),
                minimum=1e-6,
            ),
            interior_wall_thickness_m=_num(
                "interior_wall_thickness_m",
                data.get("interior_wall_thickness_m", wall),
                minimum=1e-6,
            ),
            length_m=_num("length_m", data.get("length_m", 20.0), minimum=1e-6),
            cover_depth_m=_num(
                "cover_depth_m", data.get("cover_depth_m", 0.6), minimum=0.0
            ),
            concrete_unit_weight_kn_m3=_num(
                "concrete_unit_weight_kn_m3",
                data.get("concrete_unit_weight_kn_m3", 24.0),
                minimum=1e-6,
            ),
            E_kn_m2=_num("E_kn_m2", data.get("E_kn_m2", 23_000_000.0), minimum=1e-6),
            fc_mpa=_num("fc_mpa", data.get("fc_mpa", 28.0), minimum=1e-6),
            fy_mpa=_num("fy_mpa", data.get("fy_mpa", 420.0), minimum=1e-6),
        )

    @property
    def outer_width_m(self) -> float:
        return (
            self.wall_thickness_m
            + self.cell_count * self.clear_width_m
            + (self.cell_count - 1) * self.interior_wall_thickness_m
            + self.wall_thickness_m
        )

    @property
    def outer_height_m(self) -> float:
        return (
            self.bottom_slab_thickness_m
            + self.clear_height_m
            + self.top_slab_thickness_m
        )

    @property
    def wall_centers_x_m(self) -> list[float]:
        centers = [self.wall_thickness_m / 2.0]
        for cell in range(self.cell_count):
            left_t = self.wall_thickness_m if cell == 0 else self.interior_wall_thickness_m
            right_t = (
                self.wall_thickness_m
                if cell == self.cell_count - 1
                else self.interior_wall_thickness_m
            )
            centers.append(centers[-1] + left_t / 2.0 + self.clear_width_m + right_t / 2.0)
        return centers

    @property
    def bottom_center_y_m(self) -> float:
        return self.bottom_slab_thickness_m / 2.0

    @property
    def top_center_y_m(self) -> float:
        return (
            self.bottom_slab_thickness_m
            + self.clear_height_m
            + self.top_slab_thickness_m / 2.0
        )

    def thickness_for(self, role: str) -> float:
        if role == "top":
            return self.top_slab_thickness_m
        if role == "bottom":
            return self.bottom_slab_thickness_m
        if role == "interior":
            return self.interior_wall_thickness_m
        return self.wall_thickness_m

    def as_dict(self) -> dict[str, float]:
        return {
            "cell_count": self.cell_count,
            "clear_width_m": self.clear_width_m,
            "clear_height_m": self.clear_height_m,
            "wall_thickness_m": self.wall_thickness_m,
            "interior_wall_thickness_m": self.interior_wall_thickness_m,
            "top_slab_thickness_m": self.top_slab_thickness_m,
            "bottom_slab_thickness_m": self.bottom_slab_thickness_m,
            "outer_width_m": self.outer_width_m,
            "outer_height_m": self.outer_height_m,
            "length_m": self.length_m,
            "cover_depth_m": self.cover_depth_m,
        }


@dataclass(frozen=True)
class BoxCulvertLoads:
    soil_unit_weight_kn_m3: float = 18.0
    soil_phi_deg: float = 30.0
    surcharge_kpa: float = 0.0
    traffic_load_kpa: float = 10.0
    groundwater_depth_m: float | None = None
    internal_water_depth_m: float = 0.0
    seismic_kh: float = 0.0
    load_factor: float = 1.7


@dataclass
class BoxCulvertMember:
    id: str
    role: str
    i: str
    j: str
    thickness_m: float
    frame_member: Mapping[str, Any]


@dataclass
class BoxCulvertFrame:
    section: BoxCulvertSection
    loads: BoxCulvertLoads
    nodes: list[dict[str, Any]]
    members: list[BoxCulvertMember]
    top_load_kn_m2: float
    bottom_reaction_kn_m2: float


def _lateral_pressure_at_depth(
    depth_m: float,
    *,
    gamma_kn_m3: float,
    phi_deg: float,
    surcharge_kpa: float,
    groundwater_depth_m: float | None,
    seismic_kh: float = 0.0,
) -> float:
    if seismic_kh > 0.0:
        ka = EP.coulomb_active_coefficient(
            phi_deg,
            wall_friction_deg=0.0,
            kh=seismic_kh,
        )
    else:
        ka = EP.rankine_active_coefficient(phi_deg)
    if groundwater_depth_m is None:
        zw = depth_m + 1.0
    else:
        zw = max(0.0, float(groundwater_depth_m))
    above = min(depth_m, zw)
    below = max(0.0, depth_m - zw)
    gamma_eff = gamma_kn_m3 - EP.GAMMA_WATER
    sigma = surcharge_kpa + gamma_kn_m3 * above + gamma_eff * below
    water = EP.GAMMA_WATER * below
    return ka * max(0.0, sigma) + water


def build_frame(section: BoxCulvertSection, loads: BoxCulvertLoads) -> BoxCulvertFrame:
    """Build a closed 2D frame and balanced gravity load case."""

    xs = section.wall_centers_x_m
    yb = section.bottom_center_y_m
    yt = section.top_center_y_m
    nodes: list[dict[str, Any]] = []
    node_ids: dict[tuple[int, str], str] = {}
    for ix, x in enumerate(xs):
        for level, y in (("b", yb), ("t", yt)):
            nid = f"{level}{ix}"
            node_ids[(ix, level)] = nid
            nodes.append({"id": nid, "x": x, "y": y})
    # Minimal support removes the three rigid-body modes.  Balanced gravity and
    # lateral loads leave only a small numerical reaction at this node.
    nodes[0]["restraint"] = (True, True, True)

    members: list[BoxCulvertMember] = []

    def add_member(mid: str, role: str, ni: str, nj: str, thickness: float) -> None:
        members.append(
            BoxCulvertMember(
                id=mid,
                role=role,
                i=ni,
                j=nj,
                thickness_m=thickness,
                frame_member={
                    "id": mid,
                    "i": ni,
                    "j": nj,
                    "E_kn_m2": section.E_kn_m2,
                    "area_m2": thickness,  # 1 m out-of-plane width
                    "inertia_m4": thickness**3 / 12.0,
                },
            )
        )

    # Horizontal slab segments, one per clear cell.
    for i in range(section.cell_count):
        add_member(f"T{i}", "top", node_ids[(i, "t")], node_ids[(i + 1, "t")],
                   section.top_slab_thickness_m)
        add_member(f"B{i}", "bottom", node_ids[(i, "b")], node_ids[(i + 1, "b")],
                   section.bottom_slab_thickness_m)

    # Vertical wall segments at every wall centerline.
    for i in range(len(xs)):
        role = "wall" if i in (0, len(xs) - 1) else "interior"
        add_member(f"V{i}", role, node_ids[(i, "b")], node_ids[(i, "t")],
                   section.thickness_for(role))

    top_load = (
        loads.soil_unit_weight_kn_m3 * section.cover_depth_m
        + loads.surcharge_kpa
        + loads.traffic_load_kpa
    )
    horizontal_length = sum(
        abs(section.wall_centers_x_m[i + 1] - section.wall_centers_x_m[i])
        for i in range(section.cell_count)
    )
    self_weight_total = 0.0
    member_loads: dict[str, dict[str, float]] = {}
    for m in members:
        self_w = section.concrete_unit_weight_kn_m3 * m.thickness_m
        self_weight_total += self_w * (
            horizontal_length / section.cell_count
            if m.role in ("top", "bottom")
            else (yt - yb)
        )
        member_loads[m.id] = {"wy": -self_w}

    total_down = top_load * horizontal_length + self_weight_total
    bottom_length = horizontal_length
    bottom_reaction = total_down / bottom_length
    for m in members:
        if m.role == "top":
            member_loads[m.id]["wy"] -= top_load
        elif m.role == "bottom":
            member_loads[m.id]["wy"] += bottom_reaction

    # External lateral soil pressure at the wall centrelines.  Positive x
    # pushes from left to right.
    depth_top = section.cover_depth_m + section.top_slab_thickness_m / 2.0
    depth_bottom = (
        section.cover_depth_m
        + section.outer_height_m
        - section.bottom_slab_thickness_m / 2.0
    )
    p_top = _lateral_pressure_at_depth(
        depth_top,
        gamma_kn_m3=loads.soil_unit_weight_kn_m3,
        phi_deg=loads.soil_phi_deg,
        surcharge_kpa=loads.surcharge_kpa + loads.traffic_load_kpa,
        groundwater_depth_m=loads.groundwater_depth_m,
        seismic_kh=loads.seismic_kh,
    )
    p_bottom = _lateral_pressure_at_depth(
        depth_bottom,
        gamma_kn_m3=loads.soil_unit_weight_kn_m3,
        phi_deg=loads.soil_phi_deg,
        surcharge_kpa=loads.surcharge_kpa + loads.traffic_load_kpa,
        groundwater_depth_m=loads.groundwater_depth_m,
        seismic_kh=loads.seismic_kh,
    )
    for m in members:
        if m.role == "wall" and m.id == "V0":
            member_loads[m.id]["wx_i"] = p_bottom
            member_loads[m.id]["wx_j"] = p_top
        elif m.role == "wall" and m.id == f"V{len(xs) - 1}":
            member_loads[m.id]["wx_i"] = -p_bottom
            member_loads[m.id]["wx_j"] = -p_top

    # Internal hydrostatic pressure on side walls, when water is specified.
    # ``internal_water_depth_m`` is measured upward from the bottom slab.
    if loads.internal_water_depth_m > 0.0:
        wi = min(float(loads.internal_water_depth_m), section.clear_height_m)
        p_iw_bottom = EP.GAMMA_WATER * wi
        p_iw_top = max(0.0, EP.GAMMA_WATER * (wi - section.clear_height_m))
        member_loads["V0"]["wx_i"] = (
            member_loads["V0"].get("wx_i", 0.0) - p_iw_bottom
        )
        member_loads["V0"]["wx_j"] = (
            member_loads["V0"].get("wx_j", 0.0) - p_iw_top
        )
        member_loads[f"V{len(xs) - 1}"]["wx_i"] = (
            member_loads[f"V{len(xs) - 1}"].get("wx_i", 0.0) + p_iw_bottom
        )
        member_loads[f"V{len(xs) - 1}"]["wx_j"] = (
            member_loads[f"V{len(xs) - 1}"].get("wx_j", 0.0) + p_iw_top
        )

    # Attach merged load dictionaries to the actual members that will be
    # passed to the frame solver.  Keeping a separate ``frame_members`` list
    # here previously made the analysis run with zero member loads.
    for m in members:
        fm = dict(m.frame_member)
        fm["loads"] = dict(member_loads[m.id])
        m.frame_member = fm

    return BoxCulvertFrame(
        section=section,
        loads=loads,
        nodes=nodes,
        members=members,
        top_load_kn_m2=top_load,
        bottom_reaction_kn_m2=bottom_reaction,
    )


def _manning_flow_depth(
    section: BoxCulvertSection,
    depth_m: float,
    slope: float,
    manning_n: float,
) -> dict[str, float]:
    depth = min(max(0.0, depth_m), section.clear_height_m)
    area = section.cell_count * section.clear_width_m * depth
    wetted = section.cell_count * (section.clear_width_m + 2.0 * depth)
    if area <= 0.0 or wetted <= 0.0:
        return {
            "depth_m": 0.0,
            "flow_area_m2": 0.0,
            "wetted_perimeter_m": 0.0,
            "hydraulic_radius_m": 0.0,
            "velocity_m_s": 0.0,
            "flow_m3s": 0.0,
            "froude": 0.0,
        }
    radius = area / wetted
    flow = (1.0 / manning_n) * area * radius ** (2.0 / 3.0) * math.sqrt(slope)
    velocity = flow / area
    # Hydraulic depth for a row of equal rectangular cells is the water depth.
    froude = velocity / math.sqrt(9.81 * max(depth, 1e-12))
    return {
        "depth_m": depth,
        "flow_area_m2": area,
        "wetted_perimeter_m": wetted,
        "hydraulic_radius_m": radius,
        "velocity_m_s": velocity,
        "flow_m3s": flow,
        "froude": froude,
    }


def hydraulic_capacity(
    section: BoxCulvertSection,
    slope: float,
    manning_n: float = 0.014,
    *,
    design_flow_m3s: float = 0.0,
    freeboard_min_m: float = 0.20,
) -> dict[str, Any]:
    """Normal-depth hydraulics for the clear rectangular cells.

    The full-flow capacity is still reported as an upper bound, but the design
    check uses the normal depth corresponding to the design flow.  Inlet and
    outlet control are outside this preliminary module.
    """

    S = _num("slope", slope, minimum=0.0)
    n = _num("manning_n", manning_n, minimum=1e-9)
    q_design = _num("design_flow_m3s", design_flow_m3s, minimum=0.0)
    freeboard = _num("freeboard_min_m", freeboard_min_m, minimum=0.0)
    full = _manning_flow_depth(section, section.clear_height_m, S, n)
    capacity = full["flow_m3s"]

    if q_design <= 0.0 or S <= 0.0:
        normal = _manning_flow_depth(section, 0.0, S, n)
        depth_ok = True
    elif q_design >= capacity:
        normal = full
        depth_ok = q_design <= capacity and normal["depth_m"] + freeboard <= (
            section.clear_height_m + 1e-12
        )
    else:
        lo, hi = 0.0, section.clear_height_m
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if _manning_flow_depth(section, mid, S, n)["flow_m3s"] < q_design:
                lo = mid
            else:
                hi = mid
        normal = _manning_flow_depth(section, 0.5 * (lo + hi), S, n)
        depth_ok = normal["depth_m"] + freeboard <= section.clear_height_m + 1e-12

    capacity_ok = q_design <= capacity + 1e-12
    return {
        "design_flow_m3s": q_design,
        "freeboard_min_m": freeboard,
        "normal_depth_m": normal["depth_m"],
        "flow_area_m2": normal["flow_area_m2"],
        "wetted_perimeter_m": normal["wetted_perimeter_m"],
        "hydraulic_radius_m": normal["hydraulic_radius_m"],
        "velocity_m_s": normal["velocity_m_s"],
        "froude": normal["froude"],
        "full_flow_area_m2": full["flow_area_m2"],
        "full_flow_wetted_perimeter_m": full["wetted_perimeter_m"],
        "hydraulic_radius_full_m": full["hydraulic_radius_m"],
        "capacity_m3s": capacity,
        "capacity_ok": capacity_ok,
        "freeboard_ok": depth_ok,
        "ok": capacity_ok and depth_ok,
        "method": (
            "Manning normal depth for clear rectangular cells; "
            "full-flow capacity is an upper bound; inlet/outlet control not included"
        ),
    }


def _design_member(
    section: BoxCulvertSection,
    member: BoxCulvertMember,
    result: FA.MemberResult,
    load_factor: float,
) -> dict[str, Any]:
    thickness = section.thickness_for(member.role)
    M = abs(result.max_abs_moment_knm)
    V = max(abs(result.shear_end_kn[0]), abs(result.shear_end_kn[1]))
    Mu = load_factor * M
    Vu = load_factor * V
    concrete = {
        "fc_mpa": section.fc_mpa,
        "fy_mpa": section.fy_mpa,
        "cover_mm": 50.0,
    }
    flex = RC.flexure_design(Mu, b_mm=1000.0, h_mm=thickness * 1000.0, cc=concrete)
    shear = RC.beam_shear_design(
        Vu,
        b_mm=1000.0,
        h_mm=thickness * 1000.0,
        main_bar=flex.get("bar", "D16"),
        cc=concrete,
    )
    shear["note"] = (
        "每 1 m 版／牆寬度的兩肢閉合箍筋初步配置；"
        "角隅、施工縫與三維剪力傳遞另計。"
    )
    crack = (
        RC.crack_width(
            flex.get("As_prov_mm2", 0.0),
            spacing_mm=flex.get("spacing_mm", 200.0),
            h_mm=thickness * 1000.0,
            cc=concrete,
            M_service_kNm=M,
        )
        if flex.get("ok")
        else {"ok": False, "w_mm": None, "limit_mm": 0.3}
    )
    axial_i, axial_j = result.axial_end_kn
    # In the frame sign convention, compression at both ends is negative.
    axial_compression = axial_i <= 0.0 and axial_j <= 0.0
    P_service = max(abs(axial_i), abs(axial_j))
    Pu = load_factor * P_service
    axial_flexure = None
    if axial_compression:
        bar_dia = RC.REBAR_SIZES.get(flex.get("bar", "D16"), (15.9, 199.0))[0]
        d1 = float(concrete["cover_mm"]) + 10.0 + bar_dia / 2.0
        d2 = thickness * 1000.0 - d1
        As_layer = float(flex.get("As_prov_mm2", 0.0)) / 2.0
        axial_flexure = RC.column_interaction_capacity(
            Pu,
            b_mm=1000.0,
            h_mm=thickness * 1000.0,
            layer_areas=[(As_layer, d1), (As_layer, d2)],
            fc_mpa=section.fc_mpa,
            fy_mpa=section.fy_mpa,
        )
        axial_flexure["Mu_kNm"] = Mu
        axial_flexure["ok"] = bool(
            axial_flexure.get("ok")
            and axial_flexure.get("phiMn_available_kNm", 0.0) >= Mu
        )
    else:
        axial_flexure = {
            "ok": False,
            "reason": "構材出現軸拉力；本版尚未完成拉力＋彎矩互制檢核",
            "Mu_kNm": Mu,
            "phiMn_available_kNm": 0.0,
        }
    return {
        "member": member.id,
        "role": member.role,
        "thickness_m": thickness,
        "M_service_kNm": round(M, 3),
        "Mu_kNm": round(Mu, 3),
        "V_service_kN": round(V, 3),
        "Vu_kN": round(Vu, 3),
        "flexure": flex,
        "shear": shear,
        "crack": crack,
        "axial_service_kN": round(P_service, 3),
        "Pu_kN": round(Pu, 3),
        "axial_flexure": axial_flexure,
        "ok": bool(
            flex.get("ok")
            and shear.get("ok")
            and crack.get("ok")
            and axial_flexure.get("ok")
        ),
    }


def analyse(
    section_input: Mapping[str, Any] | BoxCulvertSection,
    *,
    design_flow_m3s: float = 0.0,
    slope: float = 0.005,
    manning_n: float = 0.014,
    soil_unit_weight_kn_m3: float = 18.0,
    soil_phi_deg: float = 30.0,
    surcharge_kpa: float = 0.0,
    traffic_load_kpa: float = 10.0,
    groundwater_depth_m: float | None = None,
    internal_water_depth_m: float = 0.0,
    load_factor: float = 1.7,
    seismic_kh: float = 0.0,
    freeboard_min_m: float = 0.20,
    allowable_bearing_kpa: float | None = None,
    inlet_type: str | None = None,
    tailwater_depth_m: float = 0.0,
    allowable_headwater_m: float | None = None,
    entrance_loss_ke: float | None = None,
    hw_d_limit: float = CH.HW_D_LIMIT_DEFAULT,
    outlet_velocity_limit_m_s: float | None = None,
    headworks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run structural frame analysis and the hydraulic capacity check.

    Inlet/outlet control is added when ``inlet_type`` (or ``headworks``) is
    supplied; otherwise the result only carries the Manning normal-depth check.
    """

    section = (
        section_input
        if isinstance(section_input, BoxCulvertSection)
        else BoxCulvertSection.from_mapping(section_input)
    )
    loads = BoxCulvertLoads(
        soil_unit_weight_kn_m3=soil_unit_weight_kn_m3,
        soil_phi_deg=soil_phi_deg,
        surcharge_kpa=surcharge_kpa,
        traffic_load_kpa=traffic_load_kpa,
        groundwater_depth_m=groundwater_depth_m,
        internal_water_depth_m=internal_water_depth_m,
        seismic_kh=seismic_kh,
        load_factor=load_factor,
    )
    built = build_frame(section, loads)
    result = FA.FrameModel(built.nodes, [m.frame_member for m in built.members]).solve()

    member_results = [
        _design_member(section, m, result.members[m.id], load_factor)
        for m in built.members
    ]
    hydraulic = hydraulic_capacity(
        section,
        slope,
        manning_n,
        design_flow_m3s=design_flow_m3s,
        freeboard_min_m=freeboard_min_m,
    )
    control: dict[str, Any] | None = None
    warnings: list[str] = []
    if design_flow_m3s > 0.0 and (inlet_type or headworks):
        control = CH.analyse(
            design_flow_m3s=design_flow_m3s,
            clear_width_m=section.clear_width_m,
            clear_height_m=section.clear_height_m,
            cell_count=section.cell_count,
            length_m=section.length_m,
            slope=slope,
            manning_n=manning_n,
            inlet_type=inlet_type or "wingwall_30_75",
            entrance_loss_ke=entrance_loss_ke,
            tailwater_depth_m=tailwater_depth_m,
            allowable_headwater_m=allowable_headwater_m,
            hw_d_limit=hw_d_limit,
            outlet_velocity_limit_m_s=outlet_velocity_limit_m_s,
            headworks=headworks,
        )
        warnings.extend(control.get("warnings", []))
    elif design_flow_m3s > 0.0:
        warnings.append(
            "未指定進口型式，僅做曼寧正常水深檢核；"
            "公路排水設計規範 §6.2 要求進口／出口控制都要算（見 culvert_hydraulics.py）。"
        )
    # Exact gross concrete area = outer rectangle minus clear cell voids.
    concrete_area = (
        section.outer_width_m * section.outer_height_m
        - section.cell_count * section.clear_width_m * section.clear_height_m
    )
    self_weight_kn_m = concrete_area * section.concrete_unit_weight_kn_m3
    checks: list[dict[str, Any]] = [
        {
            "item": "水力容量",
            "value": design_flow_m3s,
            "limit": hydraulic["capacity_m3s"],
            "ok": hydraulic["capacity_ok"],
            "unit": "m3/s",
            "relation": "le",
        },
        {
            "item": "正常水深＋出水高",
            "value": hydraulic["normal_depth_m"] + hydraulic["freeboard_min_m"],
            "limit": section.clear_height_m,
            "ok": hydraulic["freeboard_ok"],
            "unit": "m",
            "relation": "le",
        },
    ]
    checks += [
        {
            "item": "%s %s 撓曲" % (m["member"], m["role"]),
            "value": m["Mu_kNm"],
            "limit": m["flexure"].get("phiMn_kNm", 0.0),
            "ok": bool(m["flexure"].get("ok")),
            "unit": "kN·m/m",
            "relation": "le",
        }
        for m in member_results
    ]
    checks += [
        {
            "item": "%s %s 軸彎互制" % (m["member"], m["role"]),
            "value": m["Mu_kNm"],
            "limit": (m["axial_flexure"].get("phiMn_available_kNm") or 0.0),
            "ok": bool(m["axial_flexure"].get("ok")),
            "unit": "kN·m/m",
            "relation": "le",
        }
        for m in member_results
    ]
    checks += [
        {
            "item": "%s %s 剪力" % (m["member"], m["role"]),
            "value": m["Vu_kN"],
            "limit": m["shear"].get("phiVn_kN", 0.0),
            "ok": bool(m["shear"].get("ok")),
            "unit": "kN/m",
            "relation": "le",
        }
        for m in member_results
    ]
    if control is not None:
        checks += control["checks"]

    uplift_kn_m = 0.0
    buoyancy_fs: float | None = None
    if groundwater_depth_m is not None:
        external_bottom_depth = section.cover_depth_m + section.outer_height_m
        water_head_above_base = max(
            0.0, external_bottom_depth - float(groundwater_depth_m)
        )
        uplift_kn_m = EP.GAMMA_WATER * water_head_above_base * section.outer_width_m
        if uplift_kn_m > 1e-9:
            buoyancy_fs = self_weight_kn_m / uplift_kn_m
            checks.append(
                {
                    "item": "空箱抗浮（自重／上浮力）",
                    "value": buoyancy_fs,
                    "limit": 1.2,
                    "ok": buoyancy_fs >= 1.2,
                    "unit": "-",
                    "relation": "ge",
                }
            )

    if allowable_bearing_kpa is not None:
        q_allow = _num("allowable_bearing_kpa", allowable_bearing_kpa, minimum=0.0)
        service_vertical = (
            self_weight_kn_m
            + (
                loads.soil_unit_weight_kn_m3 * section.cover_depth_m
                + loads.surcharge_kpa
                + loads.traffic_load_kpa
            )
            * section.outer_width_m
        )
        q_avg = service_vertical / section.outer_width_m
        checks.append(
            {
                "item": "基礎平均承載應力",
                "value": q_avg,
                "limit": q_allow,
                "ok": q_avg <= q_allow,
                "unit": "kPa",
                "relation": "le",
            }
        )
    else:
        q_avg = None

    return {
        "engine": "box_culvert",
        "version": "0.3",
        "section": section.as_dict(),
        "loads": {
            "top_load_kn_m2": built.top_load_kn_m2,
            "bottom_reaction_kn_m2": built.bottom_reaction_kn_m2,
            "surcharge_kpa": surcharge_kpa,
            "traffic_load_kpa": traffic_load_kpa,
            "seismic_kh": seismic_kh,
        },
        "hydraulic": hydraulic,
        "control": control,
        "frame": result.as_dict(),
        "members": member_results,
        "checks": checks,
        "quantities": {
            "concrete_area_m2_per_m": concrete_area,
            "concrete_volume_m3": concrete_area * section.length_m,
            "clear_volume_m3_per_m": (
                section.cell_count * section.clear_width_m * section.clear_height_m
            ),
            "total_width_m": section.outer_width_m,
            "total_height_m": section.outer_height_m,
            "self_weight_kn_m": self_weight_kn_m,
            "uplift_kn_m": uplift_kn_m,
            "buoyancy_fs": buoyancy_fs,
            "average_bearing_kpa": q_avg,
        },
        "pass": all(c["ok"] for c in checks),
        "warnings": warnings,
        "basis": [
            "公路排水設計規範第 6 章（涵洞型式、水力）",
            "公路排水設計規範 §6.2、附錄 N／O（進口、出口控制與表 O-1 Ke）",
            "公路橋梁設計規範箱涵載重與 RC 章節",
            "建築物混凝土結構設計規範撓曲、剪力與裂縫",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    s = result["section"]
    lines = [
        "箱涵 %d 孔 %0.2f m × %0.2f m，外寬 %0.2f m、外高 %0.2f m"
        % (s["cell_count"], s["clear_width_m"], s["clear_height_m"],
           s["outer_width_m"], s["outer_height_m"]),
        "設計流量 %.3f m³/s、正常水深 %.3f m；全滿容量 %.3f m³/s（上限）"
        % (
            result["hydraulic"]["design_flow_m3s"],
            result["hydraulic"]["normal_depth_m"],
            result["hydraulic"]["capacity_m3s"],
        ),
        "混凝土量 %.2f m³（每米 %.3f m²/m）"
        % (result["quantities"]["concrete_volume_m3"],
           result["quantities"]["concrete_area_m2_per_m"]),
    ]
    for check in result["checks"]:
        mark = "OK" if check["ok"] else "NG"
        limit = check.get("limit")
        relation = check.get("relation")
        unit = check.get("unit", "")
        if isinstance(limit, (int, float)):
            if relation == "ge":
                criterion = "≥ %.3f" % limit
            else:
                criterion = "≤ %.3f" % limit
            lines.append("  [%s] %s：%.3f %s（%s %s）" % (
                mark, check["item"], check["value"], unit, criterion, unit
            ))
        else:
            lines.append("  [%s] %s：%.3f %s" % (
                mark, check["item"], check["value"], unit
            ))
    control = result.get("control")
    if control:
        lines.append("— 進口／出口控制（公路排水設計規範 §6.2）—")
        # Checks are already listed above; only the narrative lines go here.
        lines.extend(
            "  " + line
            for line in CH.format_report(control).splitlines()
            if not line.strip().startswith("[")
        )
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（三孔 3.0×2.5 m、覆土 0.6 m、Q=5 m³/s、S=0.5%、n=0.014）。"""
    from _selftest_util import Checker

    c = Checker("箱涵（三孔）")
    section = {"cell_count": 3, "clear_width_m": 3.0, "clear_height_m": 2.5,
               "wall_thickness_m": 0.35, "interior_wall_thickness_m": 0.30,
               "top_slab_thickness_m": 0.40, "bottom_slab_thickness_m": 0.45,
               "cover_depth_m": 0.6, "length_m": 20.0}
    r = analyse(section, design_flow_m3s=5.0, slope=0.005, manning_n=0.014,
                soil_unit_weight_kn_m3=18.0, traffic_load_kpa=10.0)
    s, h = r["section"], r["hydraulic"]
    c.close("外寬＝3×3.0＋2×0.35＋2×0.30", s["outer_width_m"], 10.3)
    c.close("外高＝2.5＋0.40＋0.45", s["outer_height_m"], 3.35)
    c.close("頂版載重＝γ·覆土＋交通載重", r["loads"]["top_load_kn_m2"], 18.0 * 0.6 + 10.0, tol=1e-4)
    area = 3 * 3.0 * 2.5
    wetted = 3 * (3.0 + 2.0 * 2.5)
    c.close("滿流面積", h["full_flow_area_m2"], area)
    c.close("滿流濕周（三孔各底寬＋兩側壁）", h["full_flow_wetted_perimeter_m"], wetted)
    c.close("滿流 Manning 容量", h["capacity_m3s"],
            area * (area / wetted) ** (2.0 / 3.0) * 0.005 ** 0.5 / 0.014, tol=1e-3)
    y = h["normal_depth_m"]
    a_y = 9.0 * y
    r_y = a_y / (9.0 + 6.0 * y)
    c.close("正常水深代回 Manning 得 Q", a_y * r_y ** (2.0 / 3.0) * 0.005 ** 0.5 / 0.014, 5.0, tol=1e-3)
    c.close("流速 V＝Q/A", h["velocity_m_s"], 5.0 / a_y, tol=1e-3)
    return c.run()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(description="箱涵水力與 RC 構架初步分析")
    ap.add_argument("--cell-count", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--clear-width", type=float, required=True)
    ap.add_argument("--clear-height", type=float, required=True)
    ap.add_argument("--wall", type=float, default=0.35)
    ap.add_argument("--top", type=float, default=0.40)
    ap.add_argument("--bottom", type=float, default=0.45)
    ap.add_argument("--cover", type=float, default=0.60)
    ap.add_argument("--length", type=float, default=20.0)
    ap.add_argument("--design-q", type=float, default=0.0)
    ap.add_argument("--slope", type=float, default=0.005)
    ap.add_argument("--manning", type=float, default=0.014)
    ap.add_argument("--freeboard", type=float, default=0.20,
                    help="正常水深以外的最小出水高 m")
    ap.add_argument("--groundwater", type=float, default=None,
                    help="地下水位在地表下深度 m；省略表示無地下水")
    ap.add_argument("--internal-water", type=float, default=0.0,
                    help="箱涵內水深 m（由底板頂起算）")
    ap.add_argument("--kh", type=float, default=0.0, help="水平地震係數")
    ap.add_argument("--bearing-allow", type=float, default=None,
                    help="基礎容許承載力 kPa")
    ap.add_argument("--inlet", default=None, choices=sorted(CH.INLET_TYPES),
                    help="進口型式；省略則不做進口／出口控制")
    ap.add_argument("--tw", type=float, default=0.0, help="下游水深 m（涵底起算）")
    ap.add_argument("--hw-allow", type=float, default=None,
                    help="最高容許上游水深 m")
    ap.add_argument("--ke", type=float, default=None, help="自訂進口損失係數 Ke")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyse(
        {
            "cell_count": a.cell_count,
            "clear_width_m": a.clear_width,
            "clear_height_m": a.clear_height,
            "wall_thickness_m": a.wall,
            "top_slab_thickness_m": a.top,
            "bottom_slab_thickness_m": a.bottom,
            "cover_depth_m": a.cover,
            "length_m": a.length,
        },
        design_flow_m3s=a.design_q,
        slope=a.slope,
        manning_n=a.manning,
        freeboard_min_m=a.freeboard,
        groundwater_depth_m=a.groundwater,
        internal_water_depth_m=a.internal_water,
        seismic_kh=a.kh,
        allowable_bearing_kpa=a.bearing_allow,
        inlet_type=a.inlet,
        tailwater_depth_m=a.tw,
        allowable_headwater_m=a.hw_allow,
        entrance_loss_ke=a.ke,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else format_report(r))
    raise SystemExit(0 if r["pass"] else 1)

