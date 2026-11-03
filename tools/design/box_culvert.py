"""Parameterized single-, double- and triple-cell box-culvert design.

The structural model is a 2D plane frame per metre of culvert length.  The
number of cells changes the node/member topology only; material, soil, water,
traffic and RC checks are shared by all cell counts.

Reinforcement layout follows the legacy design workbooks kept in
``tools.excel``:

* ``箱涵(單孔).xls`` / ``箱涵(雙孔、三孔).xls``: top slab, bottom slab and
  side wall are designed face-by-face for the positive/negative moment
  envelopes; interior walls get both faces plus longitudinal steel.
* ``箱涵(單孔、雙孔、四孔).xls`` / ``箱涵(單孔、雙孔).xls``: multi-cell
  topology and member grouping.
* ``排水箱涵設計(單).xls``: hydraulic design basis.

Vehicle loads are selected with ``traffic_type`` and follow the workbook
formulas: H-20 (rear wheel 7.25 t, 30% impact, wheel-patch area), H-20 S-16
(P=7.3 t, cover-depth/lane-width formula), and 40T trailer (rear wheel 8 t,
E=1.2+0.06s).  The 40T and low-cover H-20 S-16 cases are applied as partial
top-slab patches rather than smeared over the whole slab.

The workbooks use ASD (AASHO 1983 / RC Designer's Handbook).  This engine keeps
their *layout logic* (which face is in tension, distribution steel, bar
schedule) but re-designs the bars with the current LRFD/RC module, so bar
sizes and spacings are not copied verbatim from the spreadsheets.

Hydraulics reports the full-flow Manning capacity as an upper bound and checks
the normal depth plus minimum freeboard at the design flow.  When
``inlet_type`` is given it also runs the 公路排水設計規範 §6.2 inlet/outlet
control check (附錄 N/O), takes the larger headwater of the two and compares it
with the allowable headwater.  Wing walls are only checked for the geometry
values the caller supplies; scour depth is never estimated.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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


TONF_TO_KN = 9.80665

# 箱涵鋼筋數量損耗（含搭接、錨定與裁剪），依使用者指定採 6%。
# 註：rc_design.LAP_ALLOWANCE = 12% 仍供擋土牆／排水溝使用，勿一併改動。
REBAR_LOSS_RATE = 0.06


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
class BoxCulvertTraffic:
    """車輛載重（依 tools.excel 的 H-20／H-20 S-16／40T 拖車公式）。"""

    standard: str = "none"
    label: str = "無車載"
    uniform_pressure_kpa: float = 0.0
    patch_pressure_kpa: float = 0.0
    patch_width_m: float = 0.0
    patch_member_index: int | None = None
    impact_factor: float = 0.0
    wheel_load_kn: float = 0.0
    lanes: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def with_patch_member(self, index: int) -> "BoxCulvertTraffic":
        return replace(self, patch_member_index=index)

    def as_dict(self) -> dict[str, Any]:
        return {
            "standard": self.standard,
            "label": self.label,
            "uniform_pressure_kpa": round(self.uniform_pressure_kpa, 3),
            "patch_pressure_kpa": round(self.patch_pressure_kpa, 3),
            "patch_width_m": round(self.patch_width_m, 3),
            "patch_member_index": self.patch_member_index,
            "impact_factor": round(self.impact_factor, 4),
            "wheel_load_kn": round(self.wheel_load_kn, 3),
            "lanes": self.lanes,
            "details": dict(self.details),
        }


TRAFFIC_TYPES: dict[str, dict[str, Any]] = {
    "none": {"label": "無車載（僅土壓／上載）"},
    "h20": {"label": "H-20（後輪 7.25 t、衝擊 30%）"},
    "h20_s16": {"label": "H-20 S-16（P=7.3 t、依車道數）"},
    "trailer_40t": {"label": "40T 拖車（後輪 8 t、E=1.2+0.06s）"},
    "custom": {"label": "自訂均佈車載（kPa）"},
}


def _traffic_key(value: Any) -> str:
    key = str(value or "h20").strip().lower().replace("-", "_")
    aliases = {
        "": "h20",
        "無": "none",
        "無車載": "none",
        "no": "none",
        "off": "none",
        "h_20": "h20",
        "h20s16": "h20_s16",
        "h20_s_16": "h20_s16",
        "hs20": "h20",
        "hs_20": "h20",
        "h20_s16": "h20_s16",
        "拖車": "trailer_40t",
        "40t": "trailer_40t",
        "trailer": "trailer_40t",
        "40t拖車": "trailer_40t",
        "自訂": "custom",
        "custom_kpa": "custom",
    }
    key = aliases.get(key, key)
    if key not in TRAFFIC_TYPES:
        raise BoxCulvertError(
            "traffic_type 必須是 %s 之一。" % "、".join(TRAFFIC_TYPES)
        )
    return key


def resolve_traffic_load(
    section: "BoxCulvertSection",
    traffic_type: Any = "h20",
    *,
    traffic_load_kpa: float = 0.0,
    traffic_lanes: int = 4,
    traffic_impact_factor: float | None = None,
) -> BoxCulvertTraffic:
    """依工作簿公式換算車輛載重。

    H-20 與 H-20 S-16 在工作簿中換算為頂版平均均佈載重；40T 拖車及
    H-20 S-16 的低覆土（Hc<=0.6 m）則保留輪重分佈寬度 E，以頂版局部
    均佈載重施加（單位仍為 kPa，積分後等於每公尺涵長之輪載）。
    """

    key = _traffic_key(traffic_type)
    cover = max(0.0, float(section.cover_depth_m))
    if traffic_impact_factor is not None:
        impact_override = _num(
            "traffic_impact_factor", traffic_impact_factor, minimum=0.0
        )
        if impact_override > 0.5:
            raise BoxCulvertError("traffic_impact_factor 不得大於 0.5。")
    else:
        impact_override = None

    if key == "none":
        return BoxCulvertTraffic(
            standard="none",
            label=TRAFFIC_TYPES["none"]["label"],
            details={
                "note": "未指定車載重；僅計土壓、上載與結構自重。",
            },
        )

    if key == "custom":
        pressure = _num("traffic_load_kpa", traffic_load_kpa, minimum=0.0)
        return BoxCulvertTraffic(
            standard="custom",
            label=TRAFFIC_TYPES["custom"]["label"],
            uniform_pressure_kpa=pressure,
            details={
                "basis": "由使用者直接指定之均佈車載重。",
                "traffic_load_kpa": pressure,
            },
        )

    if key == "h20":
        # 箱涵(單孔、雙孔、四孔).xls：後輪 7.25 t、衝擊 30%，
        # 每輪傳佈面積=(1.065+0.707Hc)*3.30 m²；工作簿再除以該面積。
        wheel_t = 7.25
        impact = 0.30 if impact_override is None else impact_override
        area_m2 = (1.065 + 0.707 * cover) * 3.30
        pressure_t_m2 = wheel_t * (1.0 + impact) / max(area_m2, 1e-9)
        pressure_kpa = pressure_t_m2 * TONF_TO_KN
        return BoxCulvertTraffic(
            standard="h20",
            label=TRAFFIC_TYPES["h20"]["label"],
            uniform_pressure_kpa=pressure_kpa,
            impact_factor=impact,
            wheel_load_kn=wheel_t * TONF_TO_KN,
            lanes=1,
            details={
                "method": "H-20 後輪傳佈面積法",
                "wheel_load_t": wheel_t,
                "distribution_area_m2": round(area_m2, 4),
                "pressure_t_m2": round(pressure_t_m2, 4),
                "formula": "p = 7.25(1+i)/[(1.065+0.707Hc)×3.30]",
                "basis": "箱涵(單孔、雙孔、四孔).xls",
            },
        )

    if key == "h20_s16":
        # 箱涵(雙孔、三孔).xls：P=7.3 t；L=(1+3/4)Hc，
        # Hc>2.43 m 再加 4.25 m；多車道另加 1.8n+1.2(n-1)，
        # 三、四車道分別乘 0.9、0.75。
        wheel_t = 7.3
        lanes = int(traffic_lanes if traffic_lanes is not None else 4)
        if lanes < 1 or lanes > 4:
            raise BoxCulvertError("traffic_lanes 必須是 1～4（依工作簿車道表）。")
        L = 1.75 * cover if cover <= 2.43 else 1.75 * cover + 4.25
        if cover <= 1.03:
            lanes_used = 1
            W = 1.75 * cover
            lane_factor = 1.0
            pressure_t_m2 = (lanes_used * 4.0 * wheel_t) / max(L * W, 1e-9)
            method = "H-20 S-16 單軸（Hc<=1.03 m）"
        else:
            lanes_used = lanes
            raw_w = 1.75 + cover + 1.8 * lanes + 1.2 * (lanes - 1)
            lane_factor = {1: 1.0, 2: 1.0, 3: 0.9, 4: 0.75}[lanes]
            W = raw_w * lane_factor
            pressure_t_m2 = (lanes * 4.0 * wheel_t) / max(L * W, 1e-9)
            method = "H-20 S-16 多車道（Hc>1.03 m）"

        if cover <= 0.6:
            # 低覆土時工作簿保留輪重分佈寬度 E（Hc<=0.6 m），
            # 以局部均佈載重施加，避免把線載重誤當成整片均佈。
            E = min(1.2 + 0.06 * section.clear_width_m, 2.13)
            impact = (0.2 if cover >= 0.3 else 0.3) if impact_override is None else impact_override
            patch_t_m2 = wheel_t * (1.0 + impact) / max(E, 1e-9)
            return BoxCulvertTraffic(
                standard="h20_s16",
                label=TRAFFIC_TYPES["h20_s16"]["label"],
                patch_pressure_kpa=patch_t_m2 * TONF_TO_KN,
                patch_width_m=E,
                impact_factor=impact,
                wheel_load_kn=wheel_t * TONF_TO_KN,
                lanes=lanes_used,
                details={
                    "method": method + "；低覆土局部輪載",
                    "wheel_load_t": wheel_t,
                    "L_m": round(L, 4),
                    "W_m": round(W, 4),
                    "E_m": round(E, 4),
                    "lanes_note": "Hc<=1.03 m 依工作簿採單軸，輸入車道數不另乘。",
                    "pressure_t_m2": round(patch_t_m2, 4),
                    "formula": "Pwh = P(1+i)/E；E=min(1.2+0.06s, 2.13)",
                    "basis": "箱涵(雙孔、三孔).xls",
                },
            )
        return BoxCulvertTraffic(
            standard="h20_s16",
            label=TRAFFIC_TYPES["h20_s16"]["label"],
            uniform_pressure_kpa=pressure_t_m2 * TONF_TO_KN,
            impact_factor=0.0,
            wheel_load_kn=wheel_t * TONF_TO_KN,
            lanes=lanes_used,
            details={
                "method": method,
                "wheel_load_t": wheel_t,
                "L_m": round(L, 4),
                "W_m": round(W, 4),
                "lane_factor": lane_factor,
                "pressure_t_m2": round(pressure_t_m2, 4),
                "formula": "WL=n×4P/(L×W(n))",
                "basis": "箱涵(雙孔、三孔).xls",
            },
        )

    # trailer_40t
    total_t = 40.0
    rear_ratio = 0.4
    p_t = total_t * rear_ratio / 2.0
    E = min(1.2 + 0.06 * section.clear_width_m, 2.1)
    impact = 0.30 if impact_override is None else impact_override
    patch_t_m2 = p_t * (1.0 + impact) / max(E, 1e-9)
    return BoxCulvertTraffic(
        standard="trailer_40t",
        label=TRAFFIC_TYPES["trailer_40t"]["label"],
        patch_pressure_kpa=patch_t_m2 * TONF_TO_KN,
        patch_width_m=E,
        impact_factor=impact,
        wheel_load_kn=p_t * TONF_TO_KN,
        lanes=1,
        details={
            "method": "40T 拖車後輪局部輪載",
            "wheel_load_t": p_t,
            "total_weight_t": total_t,
            "rear_load_ratio": rear_ratio,
            "E_m": round(E, 4),
            "pressure_t_m2": round(patch_t_m2, 4),
            "formula": "Pwh = p(1+i)/E；E=min(1.2+0.06s, 2.1)",
            "basis": "箱涵(單孔、雙孔).xls",
        },
    )


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
    cover_mm: float = 50.0

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
            cover_mm=_num("cover_mm", data.get("cover_mm", 50.0), minimum=0.0),
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
            "cover_mm": self.cover_mm,
        }


@dataclass(frozen=True)
class BoxCulvertLoads:
    soil_unit_weight_kn_m3: float = 18.0
    soil_phi_deg: float = 30.0
    surcharge_kpa: float = 0.0
    traffic_load_kpa: float = 0.0
    traffic: BoxCulvertTraffic = field(default_factory=BoxCulvertTraffic)
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
    traffic_patch_total_kn_m: float = 0.0


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

    traffic = loads.traffic
    # 保留舊 API 的 traffic_load_kpa：若沒有指定 traffic 物件，才把它視為
    # 自訂均佈車載重。
    traffic_uniform = traffic.uniform_pressure_kpa
    if traffic.standard == "none" and loads.traffic_load_kpa > 0.0:
        traffic_uniform = loads.traffic_load_kpa
    top_load = (
        loads.soil_unit_weight_kn_m3 * section.cover_depth_m
        + loads.surcharge_kpa
        + traffic_uniform
    )
    horizontal_length = sum(
        abs(section.wall_centers_x_m[i + 1] - section.wall_centers_x_m[i])
        for i in range(section.cell_count)
    )
    self_weight_total = 0.0
    traffic_patch_total = 0.0
    member_loads: dict[str, dict[str, float]] = {}
    node_pos = {n["id"]: n for n in nodes}
    patch_index = 0 if traffic.patch_member_index is None else traffic.patch_member_index
    for m in members:
        self_w = section.concrete_unit_weight_kn_m3 * m.thickness_m
        self_weight_total += self_w * (
            horizontal_length / section.cell_count
            if m.role in ("top", "bottom")
            else (yt - yb)
        )
        member_loads[m.id] = {"wy": -self_w}
        if (
            m.role == "top"
            and traffic.patch_pressure_kpa > 0.0
            and traffic.patch_width_m > 0.0
            and m.id == f"T{patch_index}"
        ):
            ni = node_pos[m.i]
            nj = node_pos[m.j]
            member_length = abs(float(nj["x"]) - float(ni["x"]))
            patch_width = min(float(traffic.patch_width_m), member_length)
            if patch_width > 0.0:
                start = 0.5 * (1.0 - patch_width / member_length)
                end = 0.5 * (1.0 + patch_width / member_length)
                member_loads[m.id]["wy_patch"] = -traffic.patch_pressure_kpa
                member_loads[m.id]["wy_patch_start"] = start
                member_loads[m.id]["wy_patch_end"] = end
                traffic_patch_total += traffic.patch_pressure_kpa * patch_width

    total_down = top_load * horizontal_length + self_weight_total + traffic_patch_total
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
        surcharge_kpa=loads.surcharge_kpa + traffic_uniform,
        groundwater_depth_m=loads.groundwater_depth_m,
        seismic_kh=loads.seismic_kh,
    )
    p_bottom = _lateral_pressure_at_depth(
        depth_bottom,
        gamma_kn_m3=loads.soil_unit_weight_kn_m3,
        phi_deg=loads.soil_phi_deg,
        surcharge_kpa=loads.surcharge_kpa + traffic_uniform,
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
        traffic_patch_total_kn_m=traffic_patch_total,
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
    crack_limit_mm: float = 0.3,
    bar_prefer: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    thickness = section.thickness_for(member.role)
    M = abs(result.max_abs_moment_knm)
    V = max(abs(result.shear_end_kn[0]), abs(result.shear_end_kn[1]))
    Mu = load_factor * M
    Vu = load_factor * V
    concrete = {
        "fc_mpa": section.fc_mpa,
        "fy_mpa": section.fy_mpa,
        "cover_mm": section.cover_mm,
        "crack_limit_mm": crack_limit_mm,
    }
    flex, crack = _flexure_with_crack(
        Mu,
        M,
        thickness * 1000.0,
        concrete,
        crack_limit_mm,
        bar_prefer or BAR_PREFERENCE_SETS["auto"],
    )
    shear = RC.beam_shear_design(
        Vu,
        b_mm=1000.0,
        h_mm=thickness * 1000.0,
        main_bar=flex.get("bar", "D16"),
        cc=concrete,
    )
    # 箱涵版／牆通常不配剪力筋：Vu ≤ φVc 時混凝土容量已足，不必硬配箍筋。
    if shear.get("phiVc_kN") is not None and Vu <= float(shear["phiVc_kN"]) + 1e-9:
        shear = {
            "ok": True,
            "required": False,
            "Vu_kN": round(Vu, 3),
            "Vc_kN": shear.get("Vc_kN"),
            "phiVc_kN": shear.get("phiVc_kN"),
            "phiVn_kN": shear.get("phiVc_kN"),
            "note": "Vu ≤ φVc，混凝土剪力容量已足，無須配置剪力箍筋。",
        }
    else:
        shear["required"] = True
        shear["note"] = (
            "每 1 m 版／牆寬度的兩肢閉合箍筋初步配置；"
            "角隅、施工縫與三維剪力傳遞另計。"
        )
    pos_m, pos_x = max(
        ((Mv, x) for x, Mv in (result.moment_diagram_knm or []) if Mv > 0.0),
        default=(0.0, 0.0),
    )
    neg_m, neg_x = max(
        ((-Mv, x) for x, Mv in (result.moment_diagram_knm or []) if Mv < 0.0),
        default=(0.0, 0.0),
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
        "M_positive_kNm": round(pos_m, 3),
        "M_positive_position_m": round(pos_x, 3),
        "M_negative_kNm": round(neg_m, 3),
        "M_negative_position_m": round(neg_x, 3),
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
            and flex.get("spacing_ok", True)
            and shear.get("ok")
            and crack.get("ok")
            and axial_flexure.get("ok")
        ),
    }


BAR_PREFERENCE_SETS: dict[str, tuple[str, ...]] = {
    "auto": ("D16", "D19", "D22", "D25", "D13"),
    "fine": ("D13", "D16", "D19", "D22", "D25"),
    "coarse": ("D19", "D22", "D25", "D16", "D13"),
}


def _bar_preference(value: Any) -> tuple[str, ...]:
    key = str(value or "auto").strip().lower()
    aliases = {
        "自動": "auto", "default": "auto",
        "細筋": "fine", "密排": "fine", "小號": "fine",
        "粗筋": "coarse", "大號": "coarse",
    }
    return BAR_PREFERENCE_SETS.get(aliases.get(key, key), BAR_PREFERENCE_SETS["auto"])


def _flexure_with_crack(
    Mu_kNm_per_m: float,
    M_service_kNm_per_m: float,
    h_mm: float,
    concrete: Mapping[str, Any],
    crack_limit_mm: float,
    bar_prefer: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """撓曲＋最大間距＋裂縫三重迭代選筋。

    先依強度選筋；若 §3.7.2 最大間距不足則加密；若裂縫超過上限，
    依 Gergely-Lutz 的 w ∝ 1/As 關係放大所需 As 後重選，直到同時合格
    或達 6 次上限。回傳 ``(flexure, crack)``。
    """

    flex: dict[str, Any] = {}
    crack: dict[str, Any] = {}
    As_extra: float | None = None
    for _attempt in range(6):
        flex = RC.flexure_design(
            Mu_kNm_per_m,
            b_mm=1000.0,
            h_mm=h_mm,
            cc=concrete,
            As_required_min_mm2=As_extra,
            bar_prefer=bar_prefer,
        )
        for _ in range(3):
            if flex.get("error") or flex.get("spacing_ok", True):
                break
            flex = RC.flexure_design(
                Mu_kNm_per_m,
                b_mm=1000.0,
                h_mm=h_mm,
                cc=concrete,
                As_required_min_mm2=As_extra,
                max_spacing_mm=flex.get("spacing_max_mm"),
                bar_prefer=bar_prefer,
            )
        if flex.get("error"):
            crack = {
                "ok": False,
                "w_mm": None,
                "limit_mm": crack_limit_mm,
                "error": flex.get("error"),
            }
            break
        crack = RC.crack_width(
            flex.get("As_prov_mm2", 0.0),
            spacing_mm=flex.get("spacing_mm", 200.0),
            h_mm=h_mm,
            cc=concrete,
            M_service_kNm=M_service_kNm_per_m,
        )
        if crack.get("ok"):
            break
        ratio = max(
            1.05,
            float(crack.get("w_mm") or 0.0)
            / max(crack_limit_mm, 1e-9)
            * 1.05,
        )
        As_extra = max(
            float(As_extra or 0.0),
            float(flex.get("As_prov_mm2") or 0.0) * ratio,
        )
    return flex, crack


def _moment_envelope(result: FA.MemberResult) -> tuple[tuple[float, float], tuple[float, float]]:
    """回傳 (最大正彎矩, 位置)、(最大負彎矩絕對值, 位置)。"""
    diagram = result.moment_diagram_knm or [
        (0.0, result.moment_end_knm[0]),
        (result.length_m, result.moment_end_knm[1]),
    ]
    pos_m, pos_x = max(
        ((M, x) for x, M in diagram if M > 0.0),
        default=(0.0, 0.0),
    )
    neg_m, neg_x = max(
        ((-M, x) for x, M in diagram if M < 0.0),
        default=(0.0, 0.0),
    )
    return (float(pos_m), float(pos_x)), (float(neg_m), float(neg_x))


def _design_face(
    section: BoxCulvertSection,
    *,
    member_ids: list[str],
    key: str,
    title: str,
    face: str,
    face_label: str,
    thickness_m: float,
    M_service_kNm: float,
    moment_label: str,
    load_factor: float,
    crack_limit_mm: float,
    bar_prefer: tuple[str, ...],
) -> dict[str, Any]:
    """設計單一受拉面（每 1 m 寬）並回傳配筋、裂縫與檢核結果。"""

    M = max(0.0, float(M_service_kNm))
    Mu = load_factor * M
    h_mm = thickness_m * 1000.0
    concrete = {
        "fc_mpa": section.fc_mpa,
        "fy_mpa": section.fy_mpa,
        "cover_mm": section.cover_mm,
        "crack_limit_mm": crack_limit_mm,
    }
    flex, crack = _flexure_with_crack(
        Mu, M, h_mm, concrete, crack_limit_mm, bar_prefer
    )

    flexure_ok = bool(
        flex.get("ok")
        and flex.get("spacing_ok", True)
        and not flex.get("error")
    )
    return {
        "key": key,
        "title": title,
        "face": face,
        "face_label": face_label,
        "label": "%s%s" % (title, face_label),
        "member_ids": member_ids,
        "thickness_m": round(thickness_m, 4),
        "M_service_kNm": round(M, 3),
        "moment_label": moment_label,
        "Mu_kNm": round(Mu, 3),
        "flexure": flex,
        "crack": crack,
        "flexure_ok": flexure_ok,
        "spacing_ok": bool(flex.get("spacing_ok", True)),
        "ok": bool(flexure_ok and crack.get("ok")),
    }


def _bar_unit_weight_kg_m(bar: str) -> float:
    dia, area = RC.REBAR_SIZES.get(bar, RC.REBAR_SIZES["D16"])
    return area * 1e-6 * RC.STEEL_DENSITY


def _steel_quantity(
    section: BoxCulvertSection,
    elements: list[dict[str, Any]],
    distribution: list[dict[str, Any]],
    loss_rate: float = REBAR_LOSS_RATE,
) -> dict[str, Any]:
    """依排筋概估鋼筋量（含搭接、錨定與損耗，預設 6%）。"""

    L = section.length_m
    n_cells = section.cell_count
    rows: list[dict[str, Any]] = []

    for e in elements:
        flex = e.get("flexure") or {}
        bar = flex.get("bar")
        spacing = flex.get("spacing_mm")
        if not bar or not spacing:
            continue
        spacing = float(spacing)
        spacing_m = spacing / 1000.0
        if e["key"] in ("top_slab", "bottom_slab"):
            count = math.ceil(L / spacing_m)
            bar_len = section.outer_width_m
            arrangement = "橫向主筋"
        elif e["key"] == "exterior_wall":
            count = math.ceil(L / spacing_m) * 2
            bar_len = section.outer_height_m
            arrangement = "垂直主筋（兩側外牆）"
        else:
            count = math.ceil(L / spacing_m) * max(0, n_cells - 1)
            bar_len = section.outer_height_m
            arrangement = "垂直主筋（中間牆）"
        kg = count * bar_len * _bar_unit_weight_kg_m(bar)
        rows.append(
            {
                "item": e["label"],
                "arrangement": arrangement,
                "bar": bar,
                "spacing_mm": int(spacing),
                "count": int(count),
                "length_m": round(bar_len, 3),
                "kg": round(kg, 2),
            }
        )

    for d in distribution:
        bar = d.get("bar")
        spacing = d.get("spacing_mm")
        if not bar or not spacing:
            continue
        spacing = float(spacing)
        spacing_m = spacing / 1000.0
        if d["key"] in ("top_slab", "bottom_slab"):
            count = math.ceil(section.outer_width_m / spacing_m) * 2
            bar_len = L
            arrangement = "縱向分佈筋（兩面）"
        elif d["key"] == "exterior_wall":
            count = math.ceil(section.outer_height_m / spacing_m) * 2 * 2
            bar_len = L
            arrangement = "縱向分佈筋（兩面×兩側牆）"
        else:
            count = math.ceil(section.outer_height_m / spacing_m) * 2 * max(
                0, n_cells - 1
            )
            bar_len = L
            arrangement = "縱向分佈筋（兩面×中間牆）"
        kg = count * bar_len * _bar_unit_weight_kg_m(bar)
        rows.append(
            {
                "item": d["title"],
                "arrangement": arrangement,
                "bar": bar,
                "spacing_mm": int(spacing),
                "count": int(count),
                "length_m": round(bar_len, 3),
                "kg": round(kg, 2),
            }
        )

    subtotal = sum(row["kg"] for row in rows)
    total = subtotal * (1.0 + loss_rate)
    return {
        "rows": rows,
        "subtotal_kg": round(subtotal, 1),
        "subtotal_kg_per_m": round(subtotal / L, 2),
        "loss_rate": loss_rate,
        "total_kg": round(total, 1),
        "total_kg_per_m": round(total / L, 2),
        "lap_allowance": loss_rate,
        "basis": (
            "依理想化排筋計數（主筋長度取構材外寬／外高、分佈筋取涵長），"
            "含 {:.0f}% 搭接、錨定與損耗；未含角隅補強、開口補強與施工縫。"
        ).format(loss_rate * 100.0),
    }


def _formwork_quantity(section: BoxCulvertSection) -> dict[str, Any]:
    """每延米模板量（只計涵內側；外側貼土面不計，另加兩端端模）。"""

    n = section.cell_count
    b = section.clear_width_m
    h = section.clear_height_m
    l = section.length_m
    soffit = n * b
    base_top = n * b
    wall_faces = 2.0 * n * h
    per_m = soffit + base_top + wall_faces
    concrete_area = (
        section.outer_width_m * section.outer_height_m - n * b * h
    )
    end_faces = 2.0 * concrete_area
    return {
        "per_m": round(per_m, 3),
        "total": round(per_m * l + end_faces, 2),
        "end_faces_m2": round(end_faces, 2),
        "breakdown_per_m": {
            "top_slab_soffit_m2_per_m": round(soffit, 3),
            "bottom_slab_top_m2_per_m": round(base_top, 3),
            "wall_inner_faces_m2_per_m": round(wall_faces, 3),
        },
        "basis": (
            "每延米＝頂版底面 nB＋底板頂面 nB＋牆內面 2nH；"
            "外側貼土面不計，另加兩端斷面端模 2A。"
        ),
    }


def _design_reinforcement(
    section: BoxCulvertSection,
    built: BoxCulvertFrame,
    frame_result: FA.FrameResult,
    *,
    load_factor: float,
    crack_limit_mm: float,
    bar_prefer: tuple[str, ...],
    distribution_bar: str,
    rebar_loss_rate: float = REBAR_LOSS_RATE,
) -> dict[str, Any]:
    """逐面（內側／外側）配筋、縱向分佈筋與鋼筋量概估。"""

    group_defs = [
        ("top_slab", "頂版", section.top_slab_thickness_m),
        ("bottom_slab", "底版", section.bottom_slab_thickness_m),
        ("exterior_wall", "外側牆", section.wall_thickness_m),
        ("interior_wall", "中間牆", section.interior_wall_thickness_m),
    ]
    groups: dict[str, dict[str, Any]] = {
        key: {
            "key": key,
            "title": title,
            "thickness_m": thickness,
            "M_outer": 0.0,
            "M_inner": 0.0,
            "M_A": 0.0,
            "M_B": 0.0,
            "P_service_kN": 0.0,
            "members": [],
        }
        for key, title, thickness in group_defs
    }

    for member in built.members:
        res = frame_result.members[member.id]
        (pos_m, _), (neg_m, _) = _moment_envelope(res)
        P = max(abs(res.axial_end_kn[0]), abs(res.axial_end_kn[1]))
        if member.role == "top":
            g = groups["top_slab"]
            g["M_inner"] = max(g["M_inner"], pos_m)
            g["M_outer"] = max(g["M_outer"], neg_m)
        elif member.role == "bottom":
            g = groups["bottom_slab"]
            g["M_outer"] = max(g["M_outer"], pos_m)
            g["M_inner"] = max(g["M_inner"], neg_m)
        elif member.role == "wall":
            g = groups["exterior_wall"]
            index = int(member.id[1:])
            if index == 0:
                # V0：局部 +y 指向左側（背土面）
                g["M_outer"] = max(g["M_outer"], neg_m)
                g["M_inner"] = max(g["M_inner"], pos_m)
            else:
                # 最右側牆：局部 -y 指向右側（背土面）
                g["M_outer"] = max(g["M_outer"], pos_m)
                g["M_inner"] = max(g["M_inner"], neg_m)
        elif member.role == "interior":
            g = groups["interior_wall"]
            g["M_A"] = max(g["M_A"], neg_m)
            g["M_B"] = max(g["M_B"], pos_m)
        else:
            continue
        g["P_service_kN"] = max(g["P_service_kN"], P)
        g["members"].append(member.id)

    elements: list[dict[str, Any]] = []
    for key, title, thickness in group_defs:
        g = groups[key]
        if not g["members"]:
            continue
        if key == "top_slab":
            specs = [
                ("outer", "外側（覆土側）", g["M_outer"], "負彎矩（支承處）"),
                ("inner", "內側（涵內側）", g["M_inner"], "正彎矩（跨中）"),
            ]
        elif key == "bottom_slab":
            specs = [
                ("outer", "外側（基礎土側）", g["M_outer"], "正彎矩（支承處）"),
                ("inner", "內側（涵內側）", g["M_inner"], "負彎矩（跨中）"),
            ]
        elif key == "exterior_wall":
            specs = [
                ("outer", "外側（背土側）", g["M_outer"], "支承處彎矩"),
                ("inner", "內側（涵內側）", g["M_inner"], "牆中彎矩"),
            ]
        else:
            specs = [
                ("A", "左面（涵內側）", g["M_A"], "負彎矩面"),
                ("B", "右面（涵內側）", g["M_B"], "正彎矩面"),
            ]
        for face, face_label, M, moment_label in specs:
            elements.append(
                _design_face(
                    section,
                    member_ids=list(g["members"]),
                    key=key,
                    title=title,
                    face=face,
                    face_label=face_label,
                    thickness_m=thickness,
                    M_service_kNm=M,
                    moment_label=moment_label,
                    load_factor=load_factor,
                    crack_limit_mm=crack_limit_mm,
                    bar_prefer=bar_prefer,
                )
            )

    # 縱向分佈筋（每面）：版採 0.0018·b·h，牆採 0.0020·b·h，分置兩面。
    dist_specs = [
        ("top_slab", "頂版縱向分佈筋", section.top_slab_thickness_m, 0.0018),
        ("bottom_slab", "底版縱向分佈筋", section.bottom_slab_thickness_m, 0.0018),
        ("exterior_wall", "外側牆縱向分佈筋", section.wall_thickness_m, 0.0020),
        ("interior_wall", "中間牆縱向分佈筋", section.interior_wall_thickness_m, 0.0020),
    ]
    distribution: list[dict[str, Any]] = []
    for key, title, thickness, ratio in dist_specs:
        if not groups[key]["members"]:
            continue
        As_total = ratio * 1000.0 * thickness * 1000.0
        As_face = As_total / 2.0
        picked = RC.select_bars(
            As_face,
            thickness * 1000.0,
            section.cover_mm,
            prefer=(distribution_bar, "D16", "D13"),
            max_spacing_mm=300.0,
        )
        distribution.append(
            {
                "key": key,
                "title": title,
                "ratio": ratio,
                "As_total_req_mm2": round(As_total, 1),
                "As_req_mm2": round(As_face, 1),
                "bar": picked["bar"],
                "spacing_mm": picked["spacing_mm"],
                "As_prov_mm2": picked["As_prov_mm2"],
                "ok": bool(picked["ok"]),
                "note": "每面配置；總量 = 兩面合計",
            }
        )

    # 軸彎互制：依實際受拉面建立互制曲線。
    #
    # 斷面上下（或左右）配筋不同時，兩個彎曲方向的容量也不同；若不分方向
    # 取較小值，會把「受拉面在配筋較多側」的工況誤判為 NG。這裡先找出
    # 彎矩最大的面，再以該面為受拉面、另一面為壓力面建立 layer_areas。
    axial_checks: list[dict[str, Any]] = []
    for key, title, thickness in group_defs:
        g = groups[key]
        pair = [e for e in elements if e["key"] == key]
        if len(pair) < 2:
            continue
        by_face = {e["face"]: e for e in pair}
        if len(by_face) < 2:
            continue
        governing = max(pair, key=lambda e: float(e.get("Mu_kNm") or 0.0))
        faces = list(by_face)
        tension_face = governing["face"]
        compression_face = next(f for f in faces if f != tension_face)
        tension = by_face[tension_face]
        compression = by_face[compression_face]
        f_t = tension.get("flexure") or {}
        f_c = compression.get("flexure") or {}
        if not f_t.get("bar") or not f_c.get("bar"):
            continue
        h_mm = thickness * 1000.0
        d_t_bar = RC.REBAR_SIZES.get(f_t["bar"], RC.REBAR_SIZES["D16"])[0]
        d_c_bar = RC.REBAR_SIZES.get(f_c["bar"], RC.REBAR_SIZES["D16"])[0]
        d_t = section.cover_mm + 10.0 + d_t_bar / 2.0
        d_c = section.cover_mm + 10.0 + d_c_bar / 2.0
        As_t = float(f_t.get("As_prov_mm2") or 0.0)
        As_c = float(f_c.get("As_prov_mm2") or 0.0)
        # layer_areas 的距離是由「壓力面」量起。壓力面鋼筋距壓力面 d_c；
        # 受拉面鋼筋距壓力面 h - d_t。
        layers = [(As_c, d_c), (As_t, h_mm - d_t)]
        Pu = load_factor * float(g["P_service_kN"])
        Mu = float(governing.get("Mu_kNm") or 0.0)
        cap = RC.column_interaction_capacity(
            Pu,
            b_mm=1000.0,
            h_mm=h_mm,
            layer_areas=layers,
            fc_mpa=section.fc_mpa,
            fy_mpa=section.fy_mpa,
        )
        phiMn = float(cap.get("phiMn_available_kNm") or 0.0)
        axial_checks.append(
            {
                "key": key,
                "title": title,
                "Pu_kN": round(Pu, 3),
                "Mu_kNm": round(Mu, 3),
                "phiMn_available_kNm": round(phiMn, 3),
                "ok": bool(cap.get("ok") and phiMn >= Mu),
                "tension_face": tension_face,
                "governs": "%s 受拉" % tension.get("face_label", tension_face),
            }
        )

    quantity = _steel_quantity(
        section, elements, distribution, loss_rate=rebar_loss_rate
    )
    return {
        "cover_mm": section.cover_mm,
        "length_m": section.length_m,
        "crack_limit_mm": crack_limit_mm,
        "bar_preference": list(bar_prefer),
        "distribution_bar": distribution_bar,
        "elements": elements,
        "distribution": distribution,
        "axial_flexure": axial_checks,
        "quantity": quantity,
        "summary": {
            "governing_Mu_kNm": round(
                max((e["Mu_kNm"] for e in elements), default=0.0), 3
            ),
            "governing_face": max(
                elements, key=lambda e: e["Mu_kNm"], default={}
            ).get("label", ""),
            "max_crack_mm": round(
                max((e["crack"].get("w_mm") or 0.0 for e in elements), default=0.0),
                4,
            ),
            "total_kg_per_m": quantity["total_kg_per_m"],
            "total_kg": quantity["total_kg"],
        },
    }


def _format_reinforcement(rep: Mapping[str, Any]) -> str:
    lines = [
        "",
        "— 鋼筋配筋設計（每 1 m 寬，保護層 %.0f mm、裂縫上限 %.2f mm）—"
        % (rep.get("cover_mm", 50.0), rep.get("crack_limit_mm", 0.3)),
    ]
    for e in rep.get("elements") or []:
        flex = e.get("flexure") or {}
        crack = e.get("crack") or {}
        mark = "OK" if e.get("ok") else "NG"
        governed = flex.get("governed_by") or ""
        lines.append(
            "  [%s] %-22s M=%.1f kN·m/m（%s）→ %s@%s mm，As=%.0f mm²/m（%s），φMn=%.1f，w=%.3f mm"
            % (
                mark,
                e.get("label", ""),
                float(e.get("Mu_kNm") or 0.0),
                e.get("moment_label", ""),
                flex.get("bar", "-"),
                flex.get("spacing_mm", "-"),
                float(flex.get("As_prov_mm2") or 0.0),
                governed,
                float(flex.get("phiMn_kNm") or 0.0),
                float(crack.get("w_mm") or 0.0),
            )
        )
    if rep.get("distribution"):
        lines.append("  縱向分佈筋（每面）：")
        for d in rep["distribution"]:
            lines.append(
                "    %s %s@%s mm，As=%.0f mm²/m（需求 %.0f，%s）"
                % (
                    d["title"],
                    d["bar"],
                    d["spacing_mm"],
                    float(d["As_prov_mm2"]),
                    float(d["As_req_mm2"]),
                    "OK" if d["ok"] else "NG",
                )
            )
    q = rep.get("quantity") or {}
    lines.append(
        "  鋼筋量概估：%.1f kg/m × %.1f m = %.2f t"
        "（含 %.0f%% 搭接、錨定與損耗；淨 %.1f kg/m）"
        % (
            float(q.get("total_kg_per_m") or 0.0),
            float(rep.get("length_m") or 0.0) or (
                float(q.get("total_kg") or 0.0)
                / max(float(q.get("total_kg_per_m") or 0.0), 1e-9)
            ),
            float(q.get("total_kg") or 0.0) / 1000.0,
            float(q.get("lap_allowance") or 0.0) * 100.0,
            float(q.get("subtotal_kg_per_m") or 0.0),
        )
    )
    return "\n".join(lines)


def _envelope_results(results: list[FA.FrameResult]) -> FA.FrameResult:
    """取多個車輛輪位載重工况的構材內力包絡。"""

    if not results:
        raise BoxCulvertError("至少要有一個框架分析結果。")
    first = results[0]
    members: dict[str, FA.MemberResult] = {}
    for member_id, base in first.members.items():
        cases = [r.members[member_id] for r in results]
        governing = max(cases, key=lambda item: item.max_abs_moment_knm)
        x_values: list[float] = []
        if base.moment_diagram_knm:
            x_values = [point[0] for point in base.moment_diagram_knm]
        diagram: list[tuple[float, float]] = []
        for index, x in enumerate(x_values):
            values = [
                case.moment_diagram_knm[index][1]
                for case in cases
                if index < len(case.moment_diagram_knm)
            ]
            if not values:
                continue
            diagram.append((x, max(values)))
            diagram.append((x, min(values)))
        if not diagram:
            diagram = list(base.moment_diagram_knm)
        max_point = max(diagram, key=lambda point: abs(point[1]))

        def extreme(values: list[float]) -> float:
            return max(values, key=abs)

        members[member_id] = FA.MemberResult(
            id=base.id,
            i=base.i,
            j=base.j,
            length_m=base.length_m,
            local_displacements=governing.local_displacements,
            local_end_forces=governing.local_end_forces,
            axial_end_kn=(
                extreme([case.axial_end_kn[0] for case in cases]),
                extreme([case.axial_end_kn[1] for case in cases]),
            ),
            shear_end_kn=(
                extreme([case.shear_end_kn[0] for case in cases]),
                extreme([case.shear_end_kn[1] for case in cases]),
            ),
            moment_end_knm=(
                extreme([case.moment_end_knm[0] for case in cases]),
                extreme([case.moment_end_knm[1] for case in cases]),
            ),
            max_abs_moment_knm=abs(max_point[1]),
            max_moment_position_m=max_point[0],
            moment_diagram_knm=diagram,
        )
    return FA.FrameResult(
        displacements=first.displacements,
        reactions=first.reactions,
        members=members,
        applied_load_vector=first.applied_load_vector,
    )


def analyse(
    section_input: Mapping[str, Any] | BoxCulvertSection,
    *,
    design_flow_m3s: float = 0.0,
    slope: float = 0.005,
    manning_n: float = 0.014,
    soil_unit_weight_kn_m3: float = 18.0,
    soil_phi_deg: float = 30.0,
    surcharge_kpa: float = 0.0,
    traffic_load_kpa: float = 0.0,
    traffic_type: str | None = None,
    traffic_lanes: int = 4,
    traffic_impact_factor: float | None = None,
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
    cover_mm: float | None = None,
    crack_limit_mm: float = 0.3,
    bar_preference: str = "auto",
    distribution_bar: str = "D13",
    rebar_loss_rate: float = REBAR_LOSS_RATE,
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
    if cover_mm is not None:
        section = replace(section, cover_mm=_num("cover_mm", cover_mm, minimum=0.0))
    crack_limit_mm = _num("crack_limit_mm", crack_limit_mm, minimum=1e-6)
    rebar_loss_rate = _num(
        "rebar_loss_rate", rebar_loss_rate, minimum=0.0
    )
    if rebar_loss_rate > 0.5:
        raise BoxCulvertError("rebar_loss_rate 不得大於 0.5（50%）。")
    bar_prefer = _bar_preference(bar_preference)
    distribution_bar = str(distribution_bar or "D13")
    if distribution_bar not in RC.REBAR_SIZES:
        distribution_bar = "D13"
    if traffic_type is None:
        traffic_type = "custom" if traffic_load_kpa > 0.0 else "h20"
    traffic = resolve_traffic_load(
        section,
        traffic_type,
        traffic_load_kpa=traffic_load_kpa,
        traffic_lanes=traffic_lanes,
        traffic_impact_factor=traffic_impact_factor,
    )
    loads = BoxCulvertLoads(
        soil_unit_weight_kn_m3=soil_unit_weight_kn_m3,
        soil_phi_deg=soil_phi_deg,
        surcharge_kpa=surcharge_kpa,
        traffic_load_kpa=traffic_load_kpa,
        traffic=traffic,
        groundwater_depth_m=groundwater_depth_m,
        internal_water_depth_m=internal_water_depth_m,
        seismic_kh=seismic_kh,
        load_factor=load_factor,
    )
    load_cases = [loads]
    if traffic.patch_pressure_kpa > 0.0 and traffic.patch_width_m > 0.0:
        # 40T 拖車或低覆土 H-20 S-16：逐孔頂版移動輪位，取構材內力包絡。
        load_cases = [
            replace(loads, traffic=traffic.with_patch_member(i))
            for i in range(section.cell_count)
        ]
    built_cases = [build_frame(section, case) for case in load_cases]
    frame_results = [
        FA.FrameModel(built.nodes, [m.frame_member for m in built.members]).solve()
        for built in built_cases
    ]
    built = built_cases[0]
    result = (
        _envelope_results(frame_results)
        if len(frame_results) > 1
        else frame_results[0]
    )

    member_results = [
        _design_member(
            section,
            m,
            result.members[m.id],
            load_factor,
            crack_limit_mm=crack_limit_mm,
            bar_prefer=bar_prefer,
        )
        for m in built.members
    ]
    reinforcement = _design_reinforcement(
        section,
        built,
        result,
        load_factor=load_factor,
        crack_limit_mm=crack_limit_mm,
        bar_prefer=bar_prefer,
        distribution_bar=distribution_bar,
        rebar_loss_rate=rebar_loss_rate,
    )
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
    if traffic.standard == "none":
        warnings.append(
            "未指定車載重：目前只計土壓、上載與結構自重；"
            "道路箱涵請選 H-20、H-20 S-16 或 40T 拖車，勿以空白代表無車載。"
        )
    else:
        warnings.append(
            "車載重採用「%s」：%s。"
            % (
                traffic.label,
                "已換算為頂版均佈載重"
                if traffic.uniform_pressure_kpa > 0.0
                else "以 %.2f m 輪重分佈寬度作用於頂版，並逐孔移動求內力包絡"
                % traffic.patch_width_m,
            )
        )
    if traffic.patch_pressure_kpa > 0.0:
        warnings.append(
            "局部輪載只在頂版，不另計側向土壓；工作簿把 Pwh 當頂版整片均佈"
            "（較保守），本程式以同強度局部輪壓逐孔移動取包絡。若要完全復刻"
            "工作簿，可改用 custom 並輸入該整片均佈值（kPa）。"
        )
    warnings.append(
        "配筋已依彎矩正負包絡分離內側／外側面設計，另加縱向分佈筋與鋼筋量概估；"
        "角隅補強、施工縫、開口補強、錨定／搭接長度細節與正式配筋詳圖仍需技師覆核。"
    )
    warnings.append(
        "鋼筋量含 %.0f%% 搭接、錨定與損耗；模板量只計涵內側（頂版底面、"
        "底板頂面、牆內面）與兩端端模，外側貼土面及施工縫不計。"
        % (rebar_loss_rate * 100.0)
    )
    warnings.append(
        "保護層採單一 cover_mm；底版貼地澆置依 112 年版表 20.5.1.3.1 宜 75 mm，"
        "採 50 mm 時須確認實際暴露條件與業主規定。"
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
            "item": "%s 配筋撓曲" % e["label"],
            "value": e["Mu_kNm"],
            "limit": e["flexure"].get("phiMn_kNm", 0.0),
            "ok": bool(e["flexure_ok"]),
            "unit": "kN·m/m",
            "relation": "le",
        }
        for e in reinforcement["elements"]
    ]
    checks += [
        {
            "item": "%s 裂縫寬度" % e["label"],
            "value": e["crack"].get("w_mm") or 0.0,
            "limit": crack_limit_mm,
            "ok": bool(e["crack"].get("ok")),
            "unit": "mm",
            "relation": "le",
        }
        for e in reinforcement["elements"]
    ]
    checks += [
        {
            "item": "%s（每面）" % d["title"],
            "value": d["As_prov_mm2"],
            "limit": d["As_req_mm2"],
            "ok": bool(d["ok"]),
            "unit": "mm²/m",
            "relation": "ge",
        }
        for d in reinforcement["distribution"]
    ]
    checks += [
        {
            "item": "%s 軸彎互制" % a["title"],
            "value": a["Mu_kNm"],
            "limit": a["phiMn_available_kNm"],
            "ok": bool(a["ok"]),
            "unit": "kN·m/m",
            "relation": "le",
        }
        for a in reinforcement["axial_flexure"]
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
                + traffic.uniform_pressure_kpa
            )
            * section.outer_width_m
            + built.traffic_patch_total_kn_m
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

    top_width_m = sum(
        abs(section.wall_centers_x_m[i + 1] - section.wall_centers_x_m[i])
        for i in range(section.cell_count)
    )
    traffic_equiv_kpa = (
        traffic.uniform_pressure_kpa
        + built.traffic_patch_total_kn_m / max(top_width_m, 1e-9)
    )
    formwork = _formwork_quantity(section)

    return {
        "engine": "box_culvert",
        "version": "0.5",
        "section": section.as_dict(),
        "loads": {
            "top_load_kn_m2": built.top_load_kn_m2,
            "bottom_reaction_kn_m2": built.bottom_reaction_kn_m2,
            "surcharge_kpa": surcharge_kpa,
            "traffic_load_kpa": traffic.uniform_pressure_kpa,
            "traffic_equivalent_kpa": traffic_equiv_kpa,
            "traffic_patch_total_kn_m": built.traffic_patch_total_kn_m,
            "traffic_type": traffic.standard,
            "traffic_label": traffic.label,
            "traffic": traffic.as_dict(),
            "seismic_kh": seismic_kh,
        },
        "hydraulic": hydraulic,
        "control": control,
        "frame": result.as_dict(),
        "members": member_results,
        "reinforcement": reinforcement,
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
            "rebar_kg_per_m": reinforcement["quantity"]["total_kg_per_m"],
            "rebar_kg_total": reinforcement["quantity"]["total_kg"],
            "rebar_ton": round(reinforcement["quantity"]["total_kg"] / 1000.0, 3),
            "rebar_kg_per_m_net": reinforcement["quantity"]["subtotal_kg_per_m"],
            "rebar_loss_rate": rebar_loss_rate,
            "rebar_kg_per_m3": round(
                reinforcement["quantity"]["total_kg"] / max(concrete_area * section.length_m, 1e-9),
                1,
            ),
            "formwork_m2_per_m": formwork["per_m"],
            "formwork_m2": formwork["total"],
            "formwork_end_faces_m2": formwork["end_faces_m2"],
            "formwork_breakdown": formwork["breakdown_per_m"],
            "formwork_basis": formwork["basis"],
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
        "混凝土量 %.2f m³（每延米 %.3f m³/m）"
        % (result["quantities"]["concrete_volume_m3"],
           result["quantities"]["concrete_area_m2_per_m"]),
        "每延米數量：鋼筋 %.1f kg/m（含 %.0f%% 損耗，淨 %.1f kg/m）、模板 %.2f m²/m"
        % (
            result["quantities"]["rebar_kg_per_m"],
            float(result["quantities"].get("rebar_loss_rate", REBAR_LOSS_RATE)) * 100.0,
            result["quantities"]["rebar_kg_per_m_net"],
            result["quantities"]["formwork_m2_per_m"],
        ),
        "總數量：鋼筋 %.2f t、模板 %.2f m²（含兩端端模 %.2f m²）"
        % (
            result["quantities"]["rebar_ton"],
            result["quantities"]["formwork_m2"],
            result["quantities"]["formwork_end_faces_m2"],
        ),
        "車載重 %s：換算均佈 %.2f kPa（局部輪壓 %.2f kPa／分佈寬 %.2f m）"
        % (
            result["loads"].get("traffic_label", "未指定"),
            float(result["loads"].get("traffic_equivalent_kpa") or 0.0),
            float((result["loads"].get("traffic") or {}).get("patch_pressure_kpa") or 0.0),
            float((result["loads"].get("traffic") or {}).get("patch_width_m") or 0.0),
        ),
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
    if result.get("reinforcement"):
        lines.append(_format_reinforcement(result["reinforcement"]))
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
    traffic_section = BoxCulvertSection.from_mapping(
        {**section, "clear_width_m": 2.9, "cover_depth_m": 2.0}
    )
    h20s16 = resolve_traffic_load(
        traffic_section, "h20_s16", traffic_lanes=4
    )
    c.close(
        "H-20 S-16 四車道換算均佈（3.0581 t/m²）",
        h20s16.uniform_pressure_kpa / TONF_TO_KN,
        3.0581,
        tol=1e-3,
    )
    h20_section = BoxCulvertSection.from_mapping(
        {**section, "clear_width_m": 3.0, "cover_depth_m": 0.0}
    )
    h20 = resolve_traffic_load(h20_section, "h20")
    c.close(
        "H-20 後輪均佈（2.680 t/m²）",
        h20.uniform_pressure_kpa / TONF_TO_KN,
        2.680,
        tol=1e-3,
    )
    trailer_section = BoxCulvertSection.from_mapping(
        {**section, "cell_count": 1, "clear_width_m": 4.0, "cover_depth_m": 0.0}
    )
    trailer = resolve_traffic_load(trailer_section, "trailer_40t")
    c.close("40T 拖車 E=1.2+0.06×4.0", trailer.patch_width_m, 1.44, tol=1e-9)
    c.close(
        "40T 拖車局部輪壓（7.2222 t/m²）",
        trailer.patch_pressure_kpa / TONF_TO_KN,
        7.2222,
        tol=1e-3,
    )
    qty = r["quantities"]
    rq = r["reinforcement"]["quantity"]
    c.close("鋼筋損耗率 6%", qty["rebar_loss_rate"] * 100.0, 6.0, tol=1e-9)
    c.close(
        "鋼筋總量＝淨量×(1+6%)",
        rq["total_kg"],
        rq["subtotal_kg"] * 1.06,
        tol=0.2,
    )
    c.close(
        "模板每延米＝2n(B+H)",
        qty["formwork_m2_per_m"],
        2.0 * 3.0 * (3.0 + 2.5),
        tol=1e-9,
    )
    c.close(
        "模板總量＝每延米×L＋兩端端模",
        qty["formwork_m2"],
        qty["formwork_m2_per_m"] * 20.0 + qty["formwork_end_faces_m2"],
        tol=0.02,
    )
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
    ap.add_argument("--traffic", default="h20", choices=sorted(TRAFFIC_TYPES),
                    help="車載標準（none／h20／h20_s16／trailer_40t／custom）")
    ap.add_argument("--traffic-load-kpa", type=float, default=0.0,
                    help="自訂均佈車載 kPa（僅 --traffic custom）")
    ap.add_argument("--traffic-lanes", type=int, default=4,
                    help="H-20 S-16 車道數 1～4")
    ap.add_argument("--impact", type=float, default=None,
                    help="自訂衝擊係數；省略依車型標準")
    ap.add_argument("--rebar-loss", type=float, default=REBAR_LOSS_RATE,
                    help="鋼筋損耗率（含搭接）；預設 0.06")
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
        traffic_type=a.traffic,
        traffic_load_kpa=a.traffic_load_kpa,
        traffic_lanes=a.traffic_lanes,
        traffic_impact_factor=a.impact,
        allowable_bearing_kpa=a.bearing_allow,
        inlet_type=a.inlet,
        tailwater_depth_m=a.tw,
        allowable_headwater_m=a.hw_allow,
        entrance_loss_ke=a.ke,
        rebar_loss_rate=a.rebar_loss,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else format_report(r))
    raise SystemExit(0 if r["pass"] else 1)

