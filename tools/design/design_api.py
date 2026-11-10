"""Stable JSON API for the civil-design calculation engines.

The individual engines remain independent command-line tools.  This module is
the common contract used by the workbench, agent integrations and tests.
It deliberately does not reimplement any formula: every calculation is
dispatched to the reviewed engine under ``tools/design``.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping


from catalog.wall import _BLOCK_WALL_SECTION_KEYS, _PASSIVE_RATIO_HINT  # noqa: F401  （外部仍以 design_api 取用）
from catalog.wall import (
    _example_retaining_wall,
    _wall_bar_choices,
    _passive_field_rules,
    _wall_field_rules,
    _block_wall_defaults,
    _example_block_wall,
    _block_wall_field_rules,
    _example_counterfort_wall,
    _counterfort_field_rules,
    _example_mse_wall,
    _mse_field_rules,
    _example_anchored_wall,
    _anchored_field_rules,
)
from catalog.box import (
    _example_box_culvert,
    _box_culvert_field_rules,
)
from catalog.water import (
    _example_channel,
    _example_channel_profile,
    _example_network,
    _example_basin,
    _channel_field_rules,
    _channel_profile_field_rules,
    _hydrology_field_rules,
    _sediment_field_rules,
    _network_field_rules,
)
from catalog.structure import (
    _example_building,
    _building_field_rules,
    _example_footing,
    _example_settlement_assessment,
    _foundation_type_choices,
    _foundation_type_rule,
    _foundation_field_rules,
    _settlement_field_rules,
    _example_channel_cover,
    _channel_cover_field_rules,
    _example_steel_column,
    _steel_column_field_rules,
)
from catalog.slope import (
    _slope_field_rules,
)
from catalog.wall import ENTRIES as _WALL_ENTRIES, RUNNERS as _WALL_RUNNERS
from catalog.box import ENTRIES as _BOX_ENTRIES, RUNNERS as _BOX_RUNNERS
from catalog.water import ENTRIES as _WATER_ENTRIES, RUNNERS as _WATER_RUNNERS
from catalog.structure import ENTRIES as _STRUCTURE_ENTRIES, RUNNERS as _STRUCTURE_RUNNERS
from catalog.slope import ENTRIES as _SLOPE_ENTRIES, RUNNERS as _SLOPE_RUNNERS


_ENTRIES = (_WALL_ENTRIES + _BOX_ENTRIES + _WATER_ENTRIES + _STRUCTURE_ENTRIES + _SLOPE_ENTRIES)
_BY_ID = {e["id"]: e for e in _ENTRIES}
_RUN = {}
for _part in (_WALL_RUNNERS, _BOX_RUNNERS, _WATER_RUNNERS, _STRUCTURE_RUNNERS, _SLOPE_RUNNERS):
    _RUN.update(_part)

CATALOG_ORDER = (
    'wall_stability',
    'block_wall',
    'counterfort_wall',
    'mse_wall',
    'anchored_wall',
    'box_culvert',
    'channel_hydraulics',
    'channel_profile',
    'channel_cover',
    'drainage_network',
    'detention_basin',
    'building_frame',
    'foundation_isolated',
    'foundation_combined',
    'foundation_pile',
    'settlement_assessment',
    'hydrology',
    'sediment_basin',
    'slope_stability',
    'rc_beam',
    'rc_column',
    'steel_column',
)

CATALOG: list[dict[str, Any]] = [_BY_ID[i] for i in CATALOG_ORDER]
RUNNERS: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
    i: _RUN[i] for i in CATALOG_ORDER
}
from catalog.wall import (
    _wall_concrete,
    _rebar_check,
    _wall_rebar_checks,
    _wall_rebar_lines,
    _attach_wall_rebar,
    _run_wall,
    _run_block_wall,
    _run_counterfort,
    _run_mse,
    _run_anchored,
)
from catalog.water import (
    _run_channel,
    _run_channel_profile,
    _run_network,
    _run_basin,
    _run_hydrology,
    _run_sediment,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RUN_DIR = ROOT / "out" / "design_workbench" / "runs"


class DesignAPIError(ValueError):
    """Invalid calculator id or input payload."""


















































































def _catalog_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in CATALOG}


def list_calculators() -> list[dict[str, Any]]:
    """Return JSON-safe calculator metadata without implementation objects."""

    return [
        {
            "id": item["id"],
            "group": item["group"],
            "title": item["title"],
            "oral": item["oral"],
            "description": item["description"],
            "engine": item["engine"],
            "codes": item["codes"],
            "limitations": item["limitations"],
            "field_rules": item.get("field_rules", {}),
            "example": item["example"],
        }
        for item in CATALOG
    ]


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DesignAPIError(f"{name} 必須是 JSON 物件")
    return value




def _checks_from_common(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("checks")
    if isinstance(raw, list):
        checks = [dict(x) for x in raw if isinstance(x, Mapping)]
        for check in checks:
            if check.get("limit") is None and check.get("required") is not None:
                check["limit"] = check["required"]
                check["relation"] = "ge"
        return checks

    checks: list[dict[str, Any]] = []
    for design in result.get("designs") or []:
        if not isinstance(design, Mapping):
            continue
        if design.get("kind") == "beam":
            cap = (design.get("flexure") or {}).get("phiMn_kNm")
            item = "%s 梁撓曲" % design.get("member", "")
        else:
            cap = (design.get("chosen") or {}).get("phiMn_available_kNm")
            item = "%s 柱軸彎" % design.get("member", "")
        checks.append(
            {
                "item": item,
                "value": design.get("Mu_kNm"),
                "limit": cap,
                "ok": bool(design.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
    for drift in result.get("drift") or []:
        if isinstance(drift, Mapping):
            checks.append(
                {
                    "item": "第 %s 層層間位移比" % drift.get("storey", ""),
                    "value": drift.get("max_storey_drift_ratio"),
                    "limit": drift.get("limit"),
                    "ok": bool(drift.get("ok")),
                    "unit": "-",
                    "relation": "le",
                }
            )
    return checks


def _checks_from_rc(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    flex = value.get("flexure") or {}
    if flex:
        checks.append(
            {
                "item": "撓曲",
                "value": flex.get("Mu_kNm"),
                "limit": flex.get("phiMn_kNm"),
                "ok": bool(flex.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
    shear = value.get("shear") or {}
    if shear:
        checks.append(
            {
                "item": (
                    "剪力（含箍筋）"
                    if shear.get("stirrup")
                    else "混凝土剪力"
                ),
                "value": shear.get("Vu_kN"),
                "limit": shear.get(
                    "phiVn_kN", shear.get("phiVc_kN")
                ),
                "ok": bool(shear.get("ok")),
                "unit": "kN",
                "relation": "le",
            }
        )
    crack = value.get("crack") or {}
    if crack and crack.get("w_mm") is not None:
        checks.append(
            {
                "item": "裂縫寬度",
                "value": crack.get("w_mm"),
                "limit": crack.get("limit_mm"),
                "ok": bool(crack.get("ok")),
                "unit": "mm",
                "relation": "le",
            }
        )
    chosen = value.get("chosen") or {}
    if chosen:
        checks.append(
            {
                "item": "柱軸彎互制",
                "value": value.get("Mu_kNm"),
                "limit": chosen.get("phiMn_available_kNm"),
                "ok": bool(chosen.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
        if chosen.get("spacing_ok") is not None:
            checks.append(
                {
                    "item": "柱縱向鋼筋淨間距",
                    "value": chosen.get("centre_spacing_mm"),
                    "limit": chosen.get("min_spacing_mm"),
                    "ok": bool(chosen.get("spacing_ok")),
                    "unit": "mm",
                    "relation": "ge",
                }
            )
    return checks


def _format_fallback(calculator: str, result: Mapping[str, Any]) -> str:
    if calculator == "rc_beam":
        flex = result.get("flexure") or {}
        shear = result.get("shear") or {}
        crack = result.get("crack") or {}
        stirrup = shear.get("stirrup") or {}
        return "\n".join(
            [
                "RC 梁斷面：%s × %s mm"
                % (flex.get("b_mm", "-"), flex.get("h_mm", "-")),
                "  [%s] 撓曲：%s@%s mm，φMn = %s kN·m（Mu = %s）"
                % (
                    "OK" if flex.get("ok") else "NG",
                    flex.get("bar", "-"),
                    flex.get("spacing_mm", "-"),
                    flex.get("phiMn_kNm", "-"),
                    flex.get("Mu_kNm", "-"),
                ),
                "  [%s] 剪力：%s@%s mm 兩肢箍，φVn = %s kN（Vu = %s）"
                % (
                    "OK" if shear.get("ok") else "NG",
                    stirrup.get("bar", "-"),
                    stirrup.get("spacing_mm", "-"),
                    shear.get("phiVn_kN", "-"),
                    shear.get("Vu_kN", "-"),
                ),
                "  [%s] 裂縫：%s mm（限 %s mm）"
                % (
                    "OK" if crack.get("ok") else "NG",
                    crack.get("w_mm", "-"),
                    crack.get("limit_mm", "-"),
                ),
                "依據《混凝土結構設計規範》100.06.09 版；仍須技師覆核。",
            ]
        )
    if calculator == "rc_column":
        chosen = result.get("chosen") or {}
        ties = result.get("ties") or {}
        return "\n".join(
            [
                "RC 柱：%s × %s mm，Pu = %s kN、Mu = %s kN·m"
                % (
                    result.get("b_mm", "-"),
                    result.get("h_mm", "-"),
                    result.get("Pu_kN", "-"),
                    result.get("Mu_kNm", "-"),
                ),
                "  [%s] 軸彎互制：%s 根 %s（As = %s mm²），"
                "φMn = %s kN·m"
                % (
                    "OK" if chosen.get("ok") else "NG",
                    chosen.get("bars_total", "-"),
                    chosen.get("bar", "-"),
                    chosen.get("As_mm2", "-"),
                    chosen.get("phiMn_available_kNm", "-"),
                ),
                "  柱箍筋初步：%s@%s mm"
                % (ties.get("bar", "-"), ties.get("spacing_mm", "-")),
                "依據《混凝土結構設計規範》100.06.09 版；"
                "耐震圍束與接頭另計，仍須技師覆核。",
            ]
        )
    lines = ["計算器：%s" % calculator]
    checks = _checks_from_common(result)
    for check in checks:
        lines.append(
            "  [%s] %s：%s（限 %s %s）"
            % (
                "OK" if check.get("ok") else "NG",
                check.get("item", ""),
                check.get("value"),
                check.get("limit"),
                check.get("unit", ""),
            )
        )
    return "\n".join(lines)
























































def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _format_report(calc_id: str, result: Mapping[str, Any]) -> str:
    # 引擎模組自帶 format_report 者直接使用（新計算器只要在 CATALOG 填 engine 即可）；
    # rc_design.format_report 是給擋土牆莖板用的，梁／柱走 fallback。
    calc = _catalog_map().get(calc_id) or {}
    engine = str(calc.get("engine") or "")
    if engine.endswith(".py") and calc_id not in {"rc_beam", "rc_column"}:
        try:
            import importlib

            module = importlib.import_module(Path(engine).stem)
            if callable(getattr(module, "format_report", None)):
                return str(module.format_report(result))
        except Exception:
            pass
    return _format_fallback(calc_id, result)


def _pick_checks(calc_id: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    if calc_id in {"rc_beam", "rc_column"}:
        return _checks_from_rc(result)
    return _checks_from_common(result)


def _verified_refs(calc_id):
    """Verified clause entries (tools/regs/verified) this calculator relies on; never breaks a run."""
    try:
        import sys
        regs = str(ROOT / "tools" / "regs")
        if regs not in sys.path:
            sys.path.insert(0, regs)
        import verified
        return verified.references_for(calc_id)
    except Exception:
        return []


def run_calculation(
    calc_id: str,
    payload: Mapping[str, Any] | None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Run one calculator and return the common workbench envelope."""

    calc = _catalog_map().get(calc_id)
    if calc is None:
        raise DesignAPIError("未知計算器：%s" % calc_id)
    data = _require_mapping(payload or {}, "payload")
    runner = RUNNERS.get(calc_id)
    if runner is None:
        raise DesignAPIError("計算器尚未接線：%s" % calc_id)

    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        result = runner(data)
    except Exception as exc:
        return {
            "schema": "civil-design-run/1",
            "calculator": calc_id,
            "title": calc["title"],
            "engine": calc["engine"],
            "ok": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "summary": "輸入或計算失敗，請修正參數後重跑。\n%s" % exc,
            "checks": [],
            "warnings": [calc.get("limitations", "")],
            "codes": calc.get("codes", []),
            "generated_at": generated,
            "result": None,
            "saved_to": None,
        }

    checks = _pick_checks(calc_id, result)
    explicit = result.get("pass", result.get("ok"))
    ok = bool(explicit) if explicit is not None else all(
        bool(c.get("ok")) for c in checks
        if c.get("severity") != "advisory"
    )
    warnings = []
    for key in ("warnings", "limitations", "notes"):
        value = result.get(key)
        if isinstance(value, list):
            warnings.extend(str(v) for v in value)
        elif value:
            warnings.append(str(value))
    if calc.get("limitations") and calc["limitations"] not in warnings:
        warnings.append(calc["limitations"])

    envelope = {
        "schema": "civil-design-run/1",
        "calculator": calc_id,
        "title": calc["title"],
        "engine": calc["engine"],
        "ok": ok,
        "summary": _format_report(calc_id, result),
        "checks": _json_safe(checks),
        "warnings": warnings,
        "codes": calc.get("codes", []),
        "references": _verified_refs(calc_id),
        "generated_at": generated,
        "result": _json_safe(result),
        "saved_to": None,
    }
    if persist:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = RUN_DIR / ("%s_%s.json" % (stamp, re.sub(r"[^A-Za-z0-9_-]+", "_", calc_id)))
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            envelope["saved_to"] = str(path.relative_to(ROOT))
        except ValueError:
            envelope["saved_to"] = str(path)
    return envelope

