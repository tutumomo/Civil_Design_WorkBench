"""Retaining-wall analysis dispatcher.

The design workbench has one engine per wall type.  Quantity take-off,
reports, drawings and regression tests must not decide the wall type on
their own: doing so was how gravity walls once received cantilever
reinforcement.  This module is the single dispatch point.
"""

from __future__ import annotations

from typing import Any, Mapping


STANDARD_TYPES = ("gravity", "semigravity", "cantilever")
RC_TYPES = STANDARD_TYPES + ("counterfort", "anchored", "mse")

WALL_LABELS = {
    "gravity": "重力式（梯形斷面）",
    "semigravity": "半重力式（厚牆＋底板）",
    "cantilever": "懸臂式（薄牆＋底板）",
    "counterfort": "扶壁式（牆板＋底板＋扶壁）",
    "anchored": "錨定式（RC 牆面＋地錨）",
    "mse": "加勁式（RC 面版＋加勁材）",
}


def wall_type(values: Mapping[str, Any] | Any) -> str:
    q = values if isinstance(values, Mapping) else getattr(values, "values", {})
    return str((q or {}).get("wall_type") or "cantilever").strip().lower()


def analyse(values: Mapping[str, Any] | Any, case: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run the engine that matches ``values.wall_type``.

    ``case`` supplies project-level soil, seismic and concrete sections.
    All engines return the same core keys (``wall_type``, ``geometry``,
    ``checks``, ``warnings``, ``pass`` and ``rebar_kg_per_m``).
    """

    case = case or {}
    q = values if isinstance(values, Mapping) else getattr(values, "values", {})
    q = dict(q or {})
    wt = wall_type(q)
    soil = case.get("soil") or {}
    kh = float((case.get("seismic") or {}).get("kh", 0) or 0)
    concrete = case.get("concrete")

    if wt in STANDARD_TYPES:
        import retaining_wall as RW

        return RW.analyse(q, soil=soil, seismic={"kh": kh})
    if wt == "counterfort":
        import counterfort_wall as CW

        return CW.analyse(q, soil=soil, seismic={"kh": kh}, concrete=concrete)
    if wt == "anchored":
        import anchored_wall as AW

        return AW.analyse(q, soil=soil, seismic={"kh": kh}, concrete=concrete)
    if wt == "mse":
        import mse_wall as MW

        return MW.analyse(q, soil=soil, seismic={"kh": kh})
    raise ValueError(
        "擋土牆分析尚未支援 wall_type=%r（支援 %s）"
        % (wt, "／".join(RC_TYPES))
    )


def rebar_design(values: Mapping[str, Any] | Any, result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the type-dispatched reinforcement design."""

    import rc_design as RC

    q = values if isinstance(values, Mapping) else getattr(values, "values", {})
    return RC.design_wall_rebar(dict(q or {}), result, cc=None)


def analyse_with_rebar(values: Mapping[str, Any] | Any,
                       case: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    res = analyse(values, case)
    return res, rebar_design(values, res)


def spacing_candidates(values: Mapping[str, Any] | Any,
                       result: Mapping[str, Any],
                       design: Mapping[str, Any] | None = None) -> list[int]:
    """Spacings that an S-02 drawing is expected to contain.

    This is intentionally conservative: it lists only spacings that are
    actually drawn as a repeated row/column, not every derived bar group.
    """

    wt = wall_type(values)
    design = design or rebar_design(values, result)
    out: set[int] = set()
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        out.update(int(round(mass[k])) for k in ("face_spacing_mm", "base_spacing_mm")
                   if mass.get(k))
    elif wt == "cantilever":
        stem = (design.get("structural") or {}).get("stem") or {}
        out.add(int(round((stem.get("main") or {}).get("spacing_mm") or 0)))
        base = (design.get("structural") or {}).get("base") or {}
        for member in (base.get("members") or [])[:1]:
            out.add(int(round((member.get("main") or {}).get("spacing_mm") or 0)))
    elif wt == "counterfort":
        slabs = (result.get("structure") or {}).get("slabs") or []
        wall_sp = [int(round((m.get("flexure") or {}).get("spacing_mm") or 0))
                   for m in slabs
                   if "牆板" in str(m.get("member") or "")
                   and "鉛直" in str(m.get("member") or "")]
        if wall_sp:
            out.add(min(wall_sp))
        heel_sp = [int(round((m.get("flexure") or {}).get("spacing_mm") or 0))
                   for m in slabs
                   if ("踵板" in str(m.get("member") or "")
                       or "趾板" in str(m.get("member") or ""))]
        if heel_sp:
            out.add(min(heel_sp))
    elif wt == "anchored":
        members = (result.get("wall") or {}).get("members") or []
        sp = [int(round((m.get("flexure") or {}).get("spacing_mm") or 0))
              for m in members if "鉛直" in str(m.get("member") or "")]
        if sp:
            out.add(min(sp))
        base = ((design.get("structural") or {}).get("base_rebar") or {})
        if base.get("spacing_mm"):
            out.add(int(round(base["spacing_mm"])))
    elif wt == "mse":
        face = result.get("face_reinforcement") or {}
        if face.get("spacing_mm"):
            out.add(int(round(face["spacing_mm"])))
    return sorted(v for v in out if v > 0)
