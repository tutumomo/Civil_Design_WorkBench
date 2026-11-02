"""Named strength and service load combinations for linear structural models.

The module does not guess which load cases exist in a project.  Callers supply
the available case names (``D``, ``L``, ``E`` ...) and the function returns only
the applicable combinations.  This avoids silently treating a missing wind or
seismic case as zero.

Default strength combinations follow the common reinforced-concrete ultimate
strength set used in Taiwan practice.  They are calculation defaults, not a
substitute for the load combinations named in the governing project code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


class LoadCombinationError(ValueError):
    """Raised when a load combination cannot be formed."""


@dataclass(frozen=True)
class Combination:
    id: str
    label: str
    factors: Mapping[str, float]
    kind: str = "strength"
    basis: str = ""

    def applies_to(self, available: Iterable[str]) -> bool:
        names = set(available)
        required = {k for k, v in self.factors.items() if abs(float(v)) > 0.0}
        return required <= names

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "factors": dict(self.factors),
            "kind": self.kind,
            "basis": self.basis,
        }


DEFAULT_STRENGTH = (
    Combination("U1", "1.4D", {"D": 1.4}, basis="dead load only"),
    Combination(
        "U2", "1.2D + 1.6L", {"D": 1.2, "L": 1.6}, basis="gravity live load"
    ),
    Combination(
        "U3",
        "1.2D + 1.0L + 1.0E",
        {"D": 1.2, "L": 1.0, "E": 1.0},
        basis="seismic",
    ),
    Combination(
        "U4",
        "0.9D + 1.0E",
        {"D": 0.9, "E": 1.0},
        basis="seismic uplift / reversal",
    ),
    Combination(
        "U5",
        "1.2D + 1.0W + 1.0L",
        {"D": 1.2, "W": 1.0, "L": 1.0},
        basis="wind",
    ),
    Combination(
        "U6",
        "0.9D + 1.0W",
        {"D": 0.9, "W": 1.0},
        basis="wind uplift / reversal",
    ),
)

DEFAULT_SERVICE = (
    Combination("S1", "1.0D + 1.0L", {"D": 1.0, "L": 1.0}, kind="service"),
    Combination("S2", "1.0D + 1.0L + 1.0E", {"D": 1.0, "L": 1.0, "E": 1.0}, kind="service"),
    Combination("S3", "1.0D + 1.0W", {"D": 1.0, "W": 1.0}, kind="service"),
)

GENERAL_STRENGTH = DEFAULT_STRENGTH + (
    Combination("U7", "1.2D + 1.6S", {"D": 1.2, "S": 1.6}, basis="soil"),
    Combination("U8", "1.2D + 1.2F", {"D": 1.2, "F": 1.2}, basis="fluid"),
    Combination(
        "U9", "1.2D + 1.6L + 1.2S", {"D": 1.2, "L": 1.6, "S": 1.2}, basis="soil + live"
    ),
    Combination("U10", "0.9D + 1.0F", {"D": 0.9, "F": 1.0}, basis="flotation"),
)


def _finite_factor(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise LoadCombinationError("Combination factors must be numeric.") from exc
    if not math.isfinite(v):
        raise LoadCombinationError("Combination factors must be finite.")
    return v


def combinations(
    available_cases: Iterable[str],
    *,
    profile: str = "strength",
    include_service: bool = False,
    custom: Iterable[Combination | Mapping[str, Any]] | None = None,
) -> list[Combination]:
    """Return combinations for which every required load case is available."""

    names = {str(n) for n in available_cases}
    if custom is None:
        if profile == "strength":
            pool = DEFAULT_STRENGTH
        elif profile == "general":
            pool = GENERAL_STRENGTH
        elif profile == "service":
            pool = DEFAULT_SERVICE
            include_service = False
        else:
            raise LoadCombinationError(
                "profile must be strength, general or service."
            )
    else:
        pool_list: list[Combination] = []
        for i, item in enumerate(custom, 1):
            if isinstance(item, Combination):
                pool_list.append(item)
                continue
            if not isinstance(item, Mapping):
                raise LoadCombinationError("custom combinations must be mappings.")
            factors = item.get("factors")
            if not isinstance(factors, Mapping):
                raise LoadCombinationError("custom combination needs a factors mapping.")
            pool_list.append(
                Combination(
                    str(item.get("id") or f"C{i}"),
                    str(item.get("label") or item.get("id") or f"C{i}"),
                    {str(k): _finite_factor(v) for k, v in factors.items()},
                    str(item.get("kind") or "strength"),
                    str(item.get("basis") or "project-defined"),
                )
            )
        pool = tuple(pool_list)

    out = [c for c in pool if c.applies_to(names)]
    if include_service:
        for c in DEFAULT_SERVICE:
            if c.applies_to(names) and all(x.id != c.id for x in out):
                out.append(c)
    if not out:
        raise LoadCombinationError(
            "No load combination applies to the supplied cases: %s"
            % ", ".join(sorted(names))
        )
    return out


def combined_scalar(
    load_values: Mapping[str, float], combination: Combination
) -> float:
    """Apply one combination to scalar load-case values."""

    total = 0.0
    for case, factor in combination.factors.items():
        if case not in load_values:
            raise LoadCombinationError(
                f"Load combination {combination.id} needs case {case!r}."
            )
        total += _finite_factor(factor) * _finite_factor(load_values[case])
    return total


def envelope(
    values_by_combination: Mapping[str, Iterable[float]],
    *,
    positive: bool = True,
) -> dict[str, dict[str, float | str]]:
    """Return controlling maximum or minimum for each value index.

    ``values_by_combination`` maps a combination id to one or more comparable
    scalar responses (for example member end moments).  The same index is
    compared across combinations.
    """

    if not values_by_combination:
        raise LoadCombinationError("No combination results were supplied.")
    rows = {cid: [float(v) for v in vals] for cid, vals in values_by_combination.items()}
    n = len(next(iter(rows.values())))
    if any(len(v) != n for v in rows.values()):
        raise LoadCombinationError("All combination result vectors must have equal length.")
    out: dict[str, dict[str, float | str]] = {}
    for i in range(n):
        key = "max" if positive else "min"
        cid = max(rows, key=lambda c: rows[c][i]) if positive else min(
            rows, key=lambda c: rows[c][i]
        )
        out[str(i)] = {"value": rows[cid][i], "combination": cid, "mode": key}
    return out


def describe(items: Iterable[Combination]) -> str:
    lines = []
    for c in items:
        factors = " + ".join(
            f"{v:g}{k}"
            for k, v in c.factors.items()
            if abs(float(v)) > 0.0
        )
        lines.append(f"{c.id:>4s}  {c.label:<28s}  {c.kind:<8s}  {c.basis}")
        lines.append(f"      factors: {factors or '(all zero)'}")
    return "\n".join(lines)

