"""Shared retaining-wall geometry.

Coordinate convention
---------------------
``x`` runs from the exposed toe (front) toward the retained soil (heel).
``y=0`` is the top of the footing for cantilever and semi-gravity walls.
For gravity walls there is no separate footing, so ``y=0`` is the base.

The module only defines geometry.  Earth pressure, stability, reinforcement,
quantities and drawings must consume the same geometry instead of rebuilding
their own polygons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, Sequence


Point = tuple[float, float]


class WallGeometryError(ValueError):
    """Raised when wall dimensions cannot form a valid section."""


def polygon_area_centroid(points: Sequence[Point]) -> tuple[float, float, float]:
    """Return ``(area, centroid_x, centroid_y)`` for a simple polygon.

    The returned area is positive regardless of point order.
    """

    if len(points) < 3:
        raise WallGeometryError("A wall polygon needs at least three points.")

    twice_area = 0.0
    cx6 = 0.0
    cy6 = 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx6 += (x0 + x1) * cross
        cy6 += (y0 + y1) * cross

    if abs(twice_area) < 1e-14:
        raise WallGeometryError("Wall polygon has zero area.")

    area = twice_area / 2.0
    return abs(area), cx6 / (3.0 * twice_area), cy6 / (3.0 * twice_area)


def _positive(name: str, value: Any, *, allow_zero: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise WallGeometryError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise WallGeometryError(f"{name} must be finite.")
    if v < 0.0 or (not allow_zero and v == 0.0):
        relation = "non-negative" if allow_zero else "positive"
        raise WallGeometryError(f"{name} must be {relation}; got {v}.")
    return v


@dataclass(frozen=True)
class WallComponent:
    """One material polygon inside or adjacent to a retaining wall."""

    name: str
    material: str
    points: tuple[Point, ...]
    area_m2_per_m: float = field(init=False)
    centroid_m: Point = field(init=False)

    def __post_init__(self) -> None:
        area, cx, cy = polygon_area_centroid(self.points)
        object.__setattr__(self, "area_m2_per_m", area)
        object.__setattr__(self, "centroid_m", (cx, cy))


@dataclass(frozen=True)
class WallGeometry:
    """Canonical section geometry for a retaining wall."""

    wall_type: str
    points: tuple[Point, ...]
    components: tuple[WallComponent, ...]
    key_points: Mapping[str, Point]
    height_m: float
    retained_height_m: float
    base_width_m: float
    base_thickness_m: float
    parameters: Mapping[str, float] = field(default_factory=dict)
    area_m2_per_m: float = field(init=False)
    centroid_m: Point = field(init=False)

    def __post_init__(self) -> None:
        area, cx, cy = polygon_area_centroid(self.points)
        object.__setattr__(self, "area_m2_per_m", area)
        object.__setattr__(self, "centroid_m", (cx, cy))

    def polygon(self) -> list[Point]:
        return list(self.points)

    def concrete_components(self) -> tuple[WallComponent, ...]:
        return tuple(c for c in self.components if c.material == "concrete")

    def soil_components(self) -> tuple[WallComponent, ...]:
        return tuple(c for c in self.components if c.material == "soil")

    def summary(self) -> dict[str, Any]:
        return {
            "wall_type": self.wall_type,
            "height_m": self.height_m,
            "retained_height_m": self.retained_height_m,
            "base_width_m": self.base_width_m,
            "base_thickness_m": self.base_thickness_m,
            "area_m2_per_m": self.area_m2_per_m,
            "centroid_m": self.centroid_m,
            "key_points": dict(self.key_points),
            "parameters": dict(self.parameters),
        }


def _as_mapping(values: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(values, Mapping):
        return values
    nested = getattr(values, "values", None)
    if isinstance(nested, Mapping):
        return nested
    raise WallGeometryError("Wall geometry input must be a mapping.")


def _gravity(q: Mapping[str, Any]) -> WallGeometry:
    H = _positive("height_m", q.get("height_m"))
    T = _positive("stem_thickness_m", q.get("stem_thickness_m"))
    BL = _positive("base_width_m", q.get("base_width_m"))
    if T >= BL:
        raise WallGeometryError("Gravity-wall top width must be smaller than base width.")

    # Back face is vertical at x=BL; the exposed face batters back toward it.
    points = ((0.0, 0.0), (BL, 0.0), (BL, H), (BL - T, H))
    comp = WallComponent("gravity_body", "concrete", points)
    return WallGeometry(
        wall_type="gravity",
        points=points,
        components=(comp,),
        key_points={
            "toe": (0.0, 0.0),
            "heel": (BL, 0.0),
            "top_front": (BL - T, H),
            "top_back": (BL, H),
        },
        height_m=H,
        retained_height_m=H,
        base_width_m=BL,
        base_thickness_m=0.0,
        parameters={"stem_thickness_m": T},
    )


def _cantilever(q: Mapping[str, Any]) -> WallGeometry:
    H = _positive("height_m", q.get("height_m"))
    T = _positive("stem_thickness_m", q.get("stem_thickness_m"))
    BL = _positive("base_width_m", q.get("base_width_m"))
    BT = _positive("base_thickness_m", q.get("base_thickness_m"))
    if T >= BL:
        raise WallGeometryError("Cantilever stem thickness must be smaller than base width.")

    base = ((0.0, -BT), (BL, -BT), (BL, 0.0), (0.0, 0.0))
    stem = ((0.0, 0.0), (T, 0.0), (T, H), (0.0, H))
    points = ((0.0, -BT), (BL, -BT), (BL, 0.0), (T, 0.0), (T, H), (0.0, H))
    return WallGeometry(
        wall_type="cantilever",
        points=points,
        components=(
            WallComponent("base_slab", "concrete", base),
            WallComponent("stem", "concrete", stem),
        ),
        key_points={
            "toe": (0.0, -BT),
            "heel": (BL, -BT),
            "stem_front_base": (0.0, 0.0),
            "stem_back_base": (T, 0.0),
            "top_front": (0.0, H),
            "top_back": (T, H),
        },
        height_m=H + BT,
        retained_height_m=H,
        base_width_m=BL,
        base_thickness_m=BT,
        parameters={"stem_thickness_m": T},
    )


def _semigravity(q: Mapping[str, Any]) -> WallGeometry:
    H = _positive("height_m", q.get("height_m"))
    BL = _positive("base_width_m", q.get("base_width_m"))
    BT = _positive("base_thickness_m", q.get("base_thickness_m"))
    top_width = _positive("top_width_m", q.get("top_width_m", q.get("stem_thickness_m", 0.0)))
    front_batter = _positive(
        "front_batter_ratio", q.get("front_batter_ratio", 0.0), allow_zero=True
    )
    toe_projection = _positive(
        "toe_projection_m", q.get("toe_projection_m", q.get("toe_projection", 0.0)),
        allow_zero=True,
    )
    back_batter = _positive(
        "back_batter_ratio", q.get("back_batter_ratio", 0.0), allow_zero=True
    )
    if BT >= H:
        raise WallGeometryError("Base thickness must be smaller than total wall height.")

    retained_height = H - BT
    front_offset = front_batter * retained_height
    back_offset = back_batter * retained_height
    stem_base_width = top_width + front_offset + back_offset
    back_x_base = toe_projection + stem_base_width
    back_x_top = back_x_base - back_offset
    front_x_top = back_x_top - top_width
    if back_x_base > BL + 1e-9:
        raise WallGeometryError("Wall stem extends beyond the base width.")
    if front_x_top <= toe_projection + 1e-9:
        raise WallGeometryError("Front batter leaves no valid stem at the top.")

    base = ((0.0, -BT), (BL, -BT), (BL, 0.0), (0.0, 0.0))
    stem_rectangle = (
        (back_x_base - top_width - back_offset, 0.0),
        (back_x_base, 0.0),
        (back_x_top, retained_height),
        (front_x_top, retained_height),
    )
    # The rectangular upper stem plus this triangle represent the battered face.
    stem_triangle = (
        (toe_projection, 0.0),
        (back_x_base - top_width - back_offset, 0.0),
        (front_x_top, retained_height),
    )
    points = (
        (0.0, -BT),
        (BL, -BT),
        (BL, 0.0),
        (back_x_base, 0.0),
        (back_x_top, retained_height),
        (front_x_top, retained_height),
        (toe_projection, 0.0),
        (0.0, 0.0),
    )

    components: list[WallComponent] = [
        WallComponent("base_slab", "concrete", base),
        WallComponent("stem_rectangle", "concrete", stem_rectangle),
        WallComponent("stem_front_triangle", "concrete", stem_triangle),
    ]

    toe_depth = _positive(
        "toe_soil_depth_m", q.get("toe_soil_depth_m", 0.0), allow_zero=True
    )
    if toe_depth > BT and toe_projection > 0.0:
        soil_height = toe_depth - BT
        toe_soil = (
            (0.0, 0.0),
            (toe_projection, 0.0),
            (toe_projection, soil_height),
            (0.0, soil_height),
        )
        components.append(WallComponent("toe_soil", "soil", toe_soil))

    return WallGeometry(
        wall_type="semigravity",
        points=points,
        components=tuple(components),
        key_points={
            "toe": (0.0, -BT),
            "heel": (BL, -BT),
            "stem_front_base": (toe_projection, 0.0),
            "stem_back_base": (back_x_base, 0.0),
            "top_front": (front_x_top, retained_height),
            "top_back": (back_x_top, retained_height),
        },
        height_m=H,
        retained_height_m=retained_height,
        base_width_m=BL,
        base_thickness_m=BT,
        parameters={
            "top_width_m": top_width,
            "front_batter_ratio": front_batter,
            "back_batter_ratio": back_batter,
            "toe_projection_m": toe_projection,
            "stem_base_width_m": stem_base_width,
            "heel_projection_m": BL - back_x_base,
            "retained_height_m": retained_height,
            "toe_soil_depth_m": toe_depth,
        },
    )


def _counterfort(q: Mapping[str, Any]) -> WallGeometry:
    """Typical cross-section between counterforts.

    The counterfort itself is a longitudinal stiffener and is shown as a
    dashed outline in S-01/S-02.  It is deliberately excluded from the
    closed concrete polygon so the drawing area remains equal to the
    per-metre quantity (base + wall panel).
    """

    H = _positive("height_m", q.get("height_m"))
    ts = _positive("stem_thickness_m", q.get("stem_thickness_m"))
    BL = _positive("base_width_m", q.get("base_width_m"))
    BT = _positive("base_thickness_m", q.get("base_thickness_m"))
    Lt = _positive("toe_length_m", q.get("toe_length_m", 0.0), allow_zero=True)
    S = _positive("counterfort_spacing_m", q.get("counterfort_spacing_m"))
    tc = _positive("counterfort_thickness_m", q.get("counterfort_thickness_m"))
    ctop = _positive("counterfort_top_width_m", q.get("counterfort_top_width_m", 0.0),
                     allow_zero=True)
    ds = _positive("front_soil_depth_m", q.get("front_soil_depth_m", 0.0),
                   allow_zero=True)
    if Lt + ts >= BL:
        raise WallGeometryError("Counterfort wall needs a positive heel length.")
    if tc >= S:
        raise WallGeometryError("Counterfort thickness must be smaller than spacing.")
    if ctop > BL - Lt - ts:
        raise WallGeometryError("Counterfort top width exceeds heel length.")

    base = ((0.0, -BT), (BL, -BT), (BL, 0.0), (0.0, 0.0))
    stem = ((Lt, 0.0), (Lt + ts, 0.0), (Lt + ts, H), (Lt, H))
    points = ((0.0, -BT), (BL, -BT), (BL, 0.0), (Lt + ts, 0.0),
              (Lt + ts, H), (Lt, H), (Lt, 0.0), (0.0, 0.0))
    return WallGeometry(
        wall_type="counterfort",
        points=points,
        components=(
            WallComponent("base_slab", "concrete", base),
            WallComponent("stem", "concrete", stem),
        ),
        key_points={
            "toe": (0.0, -BT),
            "heel": (BL, -BT),
            "stem_front_base": (Lt, 0.0),
            "stem_back_base": (Lt + ts, 0.0),
            "top_front": (Lt, H),
            "top_back": (Lt + ts, H),
        },
        height_m=H + BT,
        retained_height_m=H,
        base_width_m=BL,
        base_thickness_m=BT,
        parameters={
            "stem_thickness_m": ts,
            "toe_length_m": Lt,
            "heel_length_m": BL - Lt - ts,
            "counterfort_spacing_m": S,
            "counterfort_thickness_m": tc,
            "counterfort_top_width_m": ctop,
            "front_soil_depth_m": ds,
        },
    )


def _anchored(q: Mapping[str, Any]) -> WallGeometry:
    H = _positive("height_m", q.get("height_m"))
    t = _positive("wall_thickness_m", q.get("wall_thickness_m",
                                            q.get("stem_thickness_m")))
    BL = _positive("base_width_m", q.get("base_width_m", t))
    BT = _positive("base_thickness_m", q.get("base_thickness_m", 0.0),
                   allow_zero=True)
    if BT >= H:
        raise WallGeometryError("Base thickness must be smaller than wall height.")
    if BL < t:
        raise WallGeometryError("Base width must not be smaller than wall thickness.")
    hw = H - BT
    base = ((0.0, -BT), (BL, -BT), (BL, 0.0), (0.0, 0.0))
    wall = ((0.0, 0.0), (t, 0.0), (t, hw), (0.0, hw))
    points = ((0.0, -BT), (BL, -BT), (BL, 0.0), (t, 0.0), (t, hw),
              (0.0, hw), (0.0, 0.0))
    return WallGeometry(
        wall_type="anchored",
        points=points,
        components=(
            WallComponent("base_slab", "concrete", base),
            WallComponent("wall", "concrete", wall),
        ),
        key_points={
            "toe": (0.0, -BT),
            "heel": (BL, -BT),
            "wall_front_base": (0.0, 0.0),
            "wall_back_base": (t, 0.0),
            "top_front": (0.0, hw),
            "top_back": (t, hw),
        },
        height_m=H,
        retained_height_m=H,
        base_width_m=BL,
        base_thickness_m=BT,
        parameters={
            "wall_thickness_m": t,
            "front_soil_depth_m": float(q.get("front_soil_depth_m") or 0.0),
            "anchor_depths_m": q.get("anchor_depths_m") or [],
            "horizontal_spacing_m": float(q.get("horizontal_spacing_m") or 0.0),
            "inclination_deg": float(q.get("inclination_deg") or 0.0),
        },
    )


def _mse(q: Mapping[str, Any]) -> WallGeometry:
    H = _positive("height_m", q.get("height_m"))
    t = _positive("face_panel_thickness_m", q.get("face_panel_thickness_m", 0.20))
    L = _positive("reinforcement_length_m", q.get("reinforcement_length_m"))
    emb = _positive("embedment_m", q.get("embedment_m", 0.0), allow_zero=True)
    panel = ((0.0, 0.0), (t, 0.0), (t, H), (0.0, H))
    return WallGeometry(
        wall_type="mse",
        points=panel,
        components=(WallComponent("face_panel", "concrete", panel),),
        key_points={
            "toe": (0.0, 0.0),
            "heel": (t, 0.0),
            "top_front": (0.0, H),
            "top_back": (t, H),
            "reinforcement_end": (t + L, 0.0),
        },
        height_m=H,
        retained_height_m=H,
        base_width_m=L,
        base_thickness_m=0.0,
        parameters={
            "face_panel_thickness_m": t,
            "reinforcement_length_m": L,
            "embedment_m": emb,
            "vertical_spacing_m": float(q.get("vertical_spacing_m") or 0.6),
            "first_layer_m": float(q.get("first_layer_m") or 0.3),
            "facing_type": str(q.get("facing_type") or "precast_panel").lower(),
        },
    )


def parse(values: Mapping[str, Any] | Any) -> WallGeometry:
    """Build a validated wall geometry from case or quantity values."""

    q = _as_mapping(values)
    wall_type = str(q.get("wall_type", "cantilever")).strip().lower()
    if wall_type in {"gravity", "重力式"}:
        return _gravity(q)
    if wall_type in {"cantilever", "懸臂式"}:
        return _cantilever(q)
    if wall_type in {"semigravity", "semi_gravity", "半重力式"}:
        return _semigravity(q)
    if wall_type in {"counterfort", "扶壁式"}:
        return _counterfort(q)
    if wall_type in {"anchored", "錨定式"}:
        return _anchored(q)
    if wall_type in {"mse", "加勁式"}:
        return _mse(q)
    raise WallGeometryError(
        f"Unsupported wall_type={wall_type!r}; expected gravity, semigravity, "
        "cantilever, counterfort, anchored or mse."
    )


def component_weights(
    geometry: WallGeometry,
    *,
    concrete_unit_weight_kn_m3: float = 24.0,
    soil_unit_weight_kn_m3: float = 18.0,
) -> list[dict[str, Any]]:
    """Return component weight and first moments for stability calculations."""

    gamma_c = _positive("concrete_unit_weight_kn_m3", concrete_unit_weight_kn_m3)
    gamma_s = _positive("soil_unit_weight_kn_m3", soil_unit_weight_kn_m3)
    rows: list[dict[str, Any]] = []
    for comp in geometry.components:
        gamma = gamma_c if comp.material == "concrete" else gamma_s
        weight = comp.area_m2_per_m * gamma
        rows.append(
            {
                "name": comp.name,
                "material": comp.material,
                "area_m2_per_m": comp.area_m2_per_m,
                "centroid_m": comp.centroid_m,
                "weight_kn_per_m": weight,
                "mx_knm_per_m": weight * comp.centroid_m[0],
                "my_knm_per_m": weight * comp.centroid_m[1],
            }
        )
    return rows

