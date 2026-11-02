"""Detention-basin routing by the Modified Puls storage-indication method.

This module is deliberately separate from ``sediment_basin.py``:

* sediment basin: stores eroded soil volume;
* detention basin: temporarily stores runoff to reduce a peak discharge.

Inputs may describe a rectangular/trapezoidal basin or an explicit
stage-area table.  Outlets are rated by orifice and/or broad-crested weir;
the emergency spillway is checked separately.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Sequence


class DetentionBasinError(ValueError):
    """Raised for invalid basin, inflow or outlet data."""


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise DetentionBasinError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise DetentionBasinError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise DetentionBasinError(f"{name} must be >= {minimum}; got {v}.")
    return v


def stage_storage_from_area(
    stages_m: Sequence[float],
    areas_m2: Sequence[float],
) -> list[dict[str, float]]:
    """Integrate a stage-area curve by the trapezoidal rule."""

    if len(stages_m) != len(areas_m2) or len(stages_m) < 2:
        raise DetentionBasinError("stages_m and areas_m2 need at least two equal-length values.")
    stages = [_num("stage_m", s) for s in stages_m]
    areas = [_num("area_m2", a, minimum=0.0) for a in areas_m2]
    if any(b <= a for a, b in zip(stages, stages[1:])):
        raise DetentionBasinError("stages_m must be strictly increasing.")
    rows = [{"stage_m": stages[0], "area_m2": areas[0], "storage_m3": 0.0}]
    volume = 0.0
    for i in range(1, len(stages)):
        volume += 0.5 * (areas[i - 1] + areas[i]) * (stages[i] - stages[i - 1])
        rows.append(
            {"stage_m": stages[i], "area_m2": areas[i], "storage_m3": volume}
        )
    return rows


def trapezoidal_basin_table(
    *,
    bottom_length_m: float,
    bottom_width_m: float,
    side_slope_h_v: float,
    max_stage_m: float,
    step_m: float = 0.10,
) -> list[dict[str, float]]:
    """Stage-area-storage table for a rectangular bottom with sloping sides."""

    L0 = _num("bottom_length_m", bottom_length_m, minimum=1e-9)
    B0 = _num("bottom_width_m", bottom_width_m, minimum=1e-9)
    z = _num("side_slope_h_v", side_slope_h_v, minimum=0.0)
    top = _num("max_stage_m", max_stage_m, minimum=1e-9)
    step = _num("step_m", step_m, minimum=1e-9)
    n = max(1, int(math.ceil(top / step)))
    stages = [top * i / n for i in range(n + 1)]
    rows = []
    for y in stages:
        area = (B0 + 2.0 * z * y) * (L0 + 2.0 * z * y)
        # Exact integral of the quadratic area-height curve.
        volume = (
            B0 * L0 * y
            + z * (B0 + L0) * y * y
            + (4.0 / 3.0) * z * z * y**3
        )
        rows.append({"stage_m": y, "area_m2": area, "storage_m3": volume})
    return rows


def orifice_flow(
    head_m: float,
    *,
    area_m2: float,
    discharge_coefficient: float = 0.62,
) -> float:
    h = _num("head_m", head_m, minimum=0.0)
    area = _num("area_m2", area_m2, minimum=0.0)
    cd = _num("discharge_coefficient", discharge_coefficient, minimum=0.0)
    return cd * area * math.sqrt(2.0 * 9.81 * h) if h > 0.0 else 0.0


def weir_flow(
    head_m: float,
    *,
    length_m: float,
    coefficient: float = 1.84,
) -> float:
    h = _num("head_m", head_m, minimum=0.0)
    length = _num("length_m", length_m, minimum=0.0)
    cw = _num("coefficient", coefficient, minimum=0.0)
    return cw * length * h ** 1.5 if h > 0.0 else 0.0


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + t * (ys[hi] - ys[lo])


def _given(mapping: Mapping[str, Any], key: str) -> bool:
    return mapping.get(key) not in (None, "")


def _orifice_center(orifice: Mapping[str, Any], area_m2: float) -> float:
    """Orifice centre stage: ``center_m``, or ``invert_m`` plus half the opening."""

    if _given(orifice, "center_m") and _given(orifice, "invert_m"):
        raise DetentionBasinError("Give orifice center_m or invert_m, not both.")
    if _given(orifice, "invert_m"):
        diameter = math.sqrt(4.0 * area_m2 / math.pi)
        return _num("orifice invert_m", orifice["invert_m"]) + diameter / 2.0
    return _num("orifice center_m", orifice.get("center_m", 0.0))


def _orifice_cd(orifice: Mapping[str, Any]) -> float:
    if _given(orifice, "Cd") and _given(orifice, "discharge_coefficient"):
        raise DetentionBasinError("Give orifice Cd or discharge_coefficient, not both.")
    key = "discharge_coefficient" if _given(orifice, "discharge_coefficient") else "Cd"
    value = orifice[key] if _given(orifice, key) else 0.62
    return _num(f"orifice {key}", value, minimum=1e-9)


def _outlet_rate(
    stage_m: float,
    stage_curve: Sequence[float],
    outlet: Mapping[str, Any],
) -> float:
    total = 0.0
    orifice = outlet.get("orifice")
    if orifice:
        diameter = _num("orifice diameter_m", orifice.get("diameter_m", 0.0), minimum=0.0)
        area = (
            _num("orifice area_m2", orifice["area_m2"], minimum=0.0)
            if orifice.get("area_m2") not in (None, "")
            else math.pi * diameter * diameter / 4.0
        )
        center = _orifice_center(orifice, area)
        count = int(orifice.get("count", 1) or 1)
        total += count * orifice_flow(
            max(0.0, stage_m - center),
            area_m2=area,
            discharge_coefficient=_orifice_cd(orifice),
        )
    weir = outlet.get("weir")
    if weir:
        crest = _num("weir crest_m", weir.get("crest_m", 0.0))
        length = _num("weir length_m", weir.get("length_m", 0.0), minimum=0.0)
        total += weir_flow(
            max(0.0, stage_m - crest),
            length_m=length,
            coefficient=float(weir.get("Cw", 1.84) or 1.84),
        )
    return total


def _normalise_inflow(
    inflow: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[list[float], list[float], float]:
    if isinstance(inflow, Sequence) and not isinstance(inflow, (str, bytes, Mapping)):
        rows = list(inflow)
        if len(rows) < 2:
            raise DetentionBasinError("Inflow hydrograph needs at least two rows.")
        times = [_num("time_min", r.get("time_min")) for r in rows]
        flows = [_num("flow_m3s", r.get("flow_m3s"), minimum=0.0) for r in rows]
        step = times[1] - times[0]
    else:
        if not isinstance(inflow, Mapping):
            raise DetentionBasinError("inflow must be a hydrograph mapping or row list.")
        if inflow.get("time_min") and inflow.get("flow_m3s"):
            times = [_num("time_min", v) for v in inflow["time_min"]]
            flows = [
                _num("flow_m3s", v, minimum=0.0) for v in inflow["flow_m3s"]
            ]
            if len(times) != len(flows):
                raise DetentionBasinError("Inflow time and flow arrays must have equal length.")
            step = _num("time_step_min", inflow.get("time_step_min", times[1] - times[0]), minimum=1e-9)
        else:
            peak = _num("peak_m3s", inflow.get("peak_m3s"), minimum=0.0)
            duration = _num(
                "duration_min", inflow.get("duration_min"), minimum=1e-9
            )
            time_to_peak = _num(
                "time_to_peak_min",
                inflow.get("time_to_peak_min", duration / 3.0),
                minimum=1e-9,
            )
            if time_to_peak >= duration:
                raise DetentionBasinError("time_to_peak_min must be less than duration_min.")
            step = _num("time_step_min", inflow.get("time_step_min", 1.0), minimum=1e-9)
            n = max(1, int(math.ceil(duration / step)))
            times = [duration * i / n for i in range(n + 1)]
            flows = [
                0.0
                if t <= 0.0
                else peak * t / time_to_peak
                if t <= time_to_peak
                else peak * (duration - t) / (duration - time_to_peak)
                for t in times
            ]
    if any(t < 0.0 for t in times):
        raise DetentionBasinError("Inflow times cannot be negative.")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise DetentionBasinError("Inflow times must be strictly increasing.")
    return times, flows, step


def analyse(data: Mapping[str, Any]) -> dict[str, Any]:
    """Run stage-storage-outlet routing and return maxima and checks."""

    if not isinstance(data, Mapping):
        raise DetentionBasinError("detention-basin input must be a mapping.")
    basin = data.get("basin") or {}
    outlet = data.get("outlet") or {}
    if basin.get("stage_area_table"):
        rows = []
        for r in basin["stage_area_table"]:
            rows.append(
                {
                    "stage_m": _num("stage_m", r.get("stage_m")),
                    "area_m2": _num("area_m2", r.get("area_m2"), minimum=0.0),
                }
            )
        curve = stage_storage_from_area(
            [r["stage_m"] for r in rows], [r["area_m2"] for r in rows]
        )
    else:
        curve = trapezoidal_basin_table(
            bottom_length_m=_num("bottom_length_m", basin.get("bottom_length_m"), minimum=1e-9),
            bottom_width_m=_num("bottom_width_m", basin.get("bottom_width_m"), minimum=1e-9),
            side_slope_h_v=_num("side_slope_h_v", basin.get("side_slope_h_v", 0.0), minimum=0.0),
            max_stage_m=_num("max_stage_m", basin.get("max_stage_m"), minimum=1e-9),
            step_m=_num("stage_step_m", basin.get("stage_step_m", 0.10), minimum=1e-9),
        )
    stages = [r["stage_m"] for r in curve]
    storages = [r["storage_m3"] for r in curve]
    areas = [r["area_m2"] for r in curve]
    times, inflows, step_min = _normalise_inflow(data.get("inflow"))
    dt = step_min * 60.0
    initial_stage = _num("initial_stage_m", basin.get("initial_stage_m", 0.0), minimum=0.0)
    if initial_stage > stages[-1] + 1e-9:
        raise DetentionBasinError("initial_stage_m exceeds the stage-area table.")
    initial_storage = _interp(initial_stage, stages, storages)
    initial_out = _outlet_rate(initial_stage, stages, outlet)

    # The storage indication R=2S/dt+O is monotonic if both S and O increase.
    indication = [2.0 * s / dt + _outlet_rate(y, stages, outlet) for y, s in zip(stages, storages)]
    if any(b < a - 1e-9 for a, b in zip(indication, indication[1:])):
        raise DetentionBasinError("Storage-indication curve is not monotonic.")

    stage_j = initial_stage
    storage_j = initial_storage
    out_j = initial_out
    peak_out = out_j
    peak_out_t = times[0]
    max_stage = stage_j
    max_storage = storage_j
    rows = [
        {
            "time_min": times[0],
            "inflow_m3s": inflows[0],
            "outflow_m3s": out_j,
            "stage_m": stage_j,
            "storage_m3": storage_j,
        }
    ]
    for j in range(1, len(times)):
        rhs = (
            inflows[j - 1]
            + inflows[j]
            + 2.0 * storage_j / dt
            - out_j
        )
        if rhs > indication[-1] + 1e-6:
            raise DetentionBasinError(
                "Routing water level exceeds the supplied stage-area table; "
                "extend max_stage_m or reduce the inflow."
            )
        stage_next = _interp(rhs, indication, stages)
        storage_next = _interp(stage_next, stages, storages)
        out_next = _outlet_rate(stage_next, stages, outlet)
        if out_next > peak_out:
            peak_out, peak_out_t = out_next, times[j]
        max_stage = max(max_stage, stage_next)
        max_storage = max(max_storage, storage_next)
        rows.append(
            {
                "time_min": times[j],
                "inflow_m3s": inflows[j],
                "outflow_m3s": out_next,
                "stage_m": stage_next,
                "storage_m3": storage_next,
            }
        )
        stage_j, storage_j, out_j = stage_next, storage_next, out_next

    peak_in = max(inflows)
    attenuation = 1.0 - peak_out / peak_in if peak_in > 1e-12 else 0.0
    checks = []
    allowable_out = data.get("allowable_outflow_m3s")
    if allowable_out not in (None, ""):
        allowable = _num("allowable_outflow_m3s", allowable_out, minimum=0.0)
        checks.append(
            {
                "item": "尖峰放流量",
                "value": peak_out,
                "limit": allowable,
                "ok": peak_out <= allowable + 1e-9,
                "unit": "m3/s",
            }
        )
    dam_crest = basin.get("dam_crest_m")
    freeboard_min = _num("freeboard_min_m", basin.get("freeboard_min_m", 0.0), minimum=0.0)
    if dam_crest not in (None, ""):
        crest = _num("dam_crest_m", dam_crest)
        limit_stage = crest - freeboard_min
        checks.append(
            {
                "item": "最高水位＋出水高",
                "value": max_stage + freeboard_min,
                "limit": crest,
                "ok": max_stage + freeboard_min <= crest + 1e-9,
                "unit": "m",
            }
        )
        emergency = outlet.get("emergency_spillway")
        if emergency:
            spill_crest = _num("spillway crest_m", emergency.get("crest_m"))
            spill_width = _num("spillway width_m", emergency.get("width_m"), minimum=0.0)
            spill_q = weir_flow(
                max(0.0, max_stage - spill_crest),
                length_m=spill_width,
                coefficient=float(emergency.get("Cw", 1.84) or 1.84),
            )
            checks.append(
                {
                    "item": "緊急溢洪道通過流量",
                    "value": spill_q,
                    "limit": peak_in,
                    "ok": spill_q >= peak_in,
                    "unit": "m3/s",
                }
            )

    if not checks:
        checks.append(
            {
                "item": "調洪演算完成（未指定容許出流或壩頂）",
                "value": max_stage,
                "limit": stages[-1],
                "ok": max_stage <= stages[-1] + 1e-9,
                "unit": "m",
            }
        )

    return {
        "engine": "detention_basin",
        "version": "0.1",
        "method": "Modified Puls storage indication",
        "stage_area_storage": curve,
        "hydrograph": {
            "time_min": times,
            "inflow_m3s": inflows,
            "routing": rows,
        },
        "peak_inflow_m3s": peak_in,
        "peak_outflow_m3s": round(peak_out, 6),
        "peak_outflow_time_min": peak_out_t,
        "peak_attenuation": round(attenuation, 6),
        "max_stage_m": round(max_stage, 6),
        "max_storage_m3": round(max_storage, 6),
        "initial_stage_m": initial_stage,
        "final_stage_m": round(stage_j, 6),
        "inflow_volume_m3": round(
            sum(
                0.5 * (inflows[i - 1] + inflows[i]) * (times[i] - times[i - 1]) * 60.0
                for i in range(1, len(times))
            ),
            3,
        ),
        "checks": checks,
        "pass": all(c["ok"] for c in checks),
        "warnings": [
            w
            for w in (
                "本模組不是沉砂池；泥砂容量須另用 sediment_basin.py。",
                "未計入上游開發時序、多峰雨型、閘門操作、尾水淹沒與下游河道迴水。",
                "孔口與堰係數為常用工程值，非規範強制值。",
                "緊急溢洪道只做尖峰通過量檢核，未做池堤溢頂與下游消能分析。",
            )
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    lines = [
        "滯洪池 Modified Puls 調洪演算",
        "  尖峰入流 %.3f m³/s → 尖峰出流 %.3f m³/s（削減 %.1f%%）"
        % (
            result["peak_inflow_m3s"],
            result["peak_outflow_m3s"],
            result["peak_attenuation"] * 100.0,
        ),
        "  最高水位 %.3f m、最大蓄水 %.1f m³、期末水位 %.3f m"
        % (
            result["max_stage_m"],
            result["max_storage_m3"],
            result["final_stage_m"],
        ),
    ]
    for c in result["checks"]:
        lines.append(
            "  [%s] %s：%.4f %s（限 %s）"
            % (
                "OK" if c["ok"] else "NG",
                c["item"],
                c["value"],
                c["unit"],
                c["limit"],
            )
        )
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（底 10×10 m、邊坡 1:2、φ0.2 m 孔口、三角形入流歷線）。"""
    from _selftest_util import Checker

    c = Checker("滯洪池調洪演算")
    r = analyse({
        "basin": {"bottom_length_m": 10.0, "bottom_width_m": 10.0, "side_slope_h_v": 2.0,
                  "max_stage_m": 2.0, "stage_step_m": 0.1, "dam_crest_m": 2.0,
                  "freeboard_min_m": 0.2},
        "outlet": {"orifice": {"diameter_m": 0.2, "Cd": 0.62}},
        "inflow": {"peak_m3s": 1.0, "time_to_peak_min": 5.0, "duration_min": 10.0,
                   "time_step_min": 1.0},
        "allowable_outflow_m3s": 1.0,
    })
    row = next(x for x in r["stage_area_storage"] if abs(x["stage_m"] - 1.0) < 1e-9)
    c.close("水深 1 m 水面積＝(10＋2×2×1)²", row["area_m2"], 14.0 ** 2, tol=1e-4)
    c.close("水深 1 m 儲水量＝∫(10＋4h)²dh", row["storage_m3"],
            (14.0 ** 3 - 10.0 ** 3) / 12.0, tol=1e-3)
    c.close("入流體積＝½·Qp·T", r["inflow_volume_m3"], 0.5 * 1.0 * 600.0, tol=1e-3)
    area = math.pi * 0.2 ** 2 / 4.0
    c.close("尖峰出流＝Cd·A·√(2g·h)", r["peak_outflow_m3s"],
            0.62 * area * math.sqrt(2.0 * 9.81 * r["max_stage_m"]), tol=1e-3)
    c.close("削峰率＝1－Qout/Qin", r["peak_attenuation"], 1.0 - r["peak_outflow_m3s"], tol=1e-5)
    c.true("最大儲水量不超過入流體積", r["max_storage_m3"] <= r["inflow_volume_m3"])
    return c.run()


def main() -> None:
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(description="滯洪池 Modified Puls 調洪演算")
    ap.add_argument("case_json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    data = json.load(open(a.case_json, encoding="utf-8"))
    result = analyse(data)
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if a.json
        else format_report(result)
    )
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()

