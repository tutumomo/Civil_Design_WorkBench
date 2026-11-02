"""Steady-state drainage-network flow accumulation and link capacity checks.

The network is a directed acyclic graph from upstream to downstream.  Local
catchment inflows are added at nodes; nodal flow is routed through outgoing
links either by specified split fractions or in proportion to link capacity.
Each link may be a rectangular channel, a circular culvert or a box culvert.

This first version checks steady peak capacity and normal-depth hydraulics.  It
does not yet solve a gradually varied water-surface profile or backwater.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import box_culvert as BC
import channel_hydraulics as CH


class DrainageNetworkError(ValueError):
    """Raised for invalid topology or hydraulic geometry."""


def _num(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise DrainageNetworkError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise DrainageNetworkError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise DrainageNetworkError(f"{name} must be >= {minimum}; got {v}.")
    return v


def _box_section(link: Mapping[str, Any]) -> BC.BoxCulvertSection:
    return BC.BoxCulvertSection.from_mapping(
        {
            "cell_count": int(link.get("cell_count", 1)),
            "clear_width_m": link.get("clear_width_m"),
            "clear_height_m": link.get("clear_height_m"),
            "wall_thickness_m": link.get("wall_thickness_m", 0.35),
            "interior_wall_thickness_m": link.get("interior_wall_thickness_m", 0.30),
            "top_slab_thickness_m": link.get("top_slab_thickness_m", 0.40),
            "bottom_slab_thickness_m": link.get("bottom_slab_thickness_m", 0.45),
            "cover_depth_m": link.get("cover_depth_m", 0.60),
            "length_m": link.get("length_m", 20.0),
        }
    )


def link_capacity(link: Mapping[str, Any]) -> dict[str, Any]:
    """Return full/limiting capacity, independent of routed design flow."""

    kind = str(link.get("type", "channel")).lower()
    slope = _num("slope", link.get("slope", 0.005), minimum=0.0)
    n = _num("manning_n", link.get("manning_n", CH.DEFAULTS["manning_n"]), minimum=1e-9)
    if kind in ("channel", "open_channel", "ditch"):
        b = _num("inner_width_m", link.get("inner_width_m"), minimum=1e-6)
        h = _num("depth_m", link.get("depth_m"), minimum=1e-6)
        qcap, props = CH.capacity(b, h, n, slope)
        return {
            "type": "channel",
            "capacity_m3s": qcap,
            "geometry": {"inner_width_m": b, "depth_m": h, "slope": slope},
            "full_flow_area_m2": props["A"],
            "full_flow_velocity_m_s": qcap / props["A"] if props["A"] > 0 else 0.0,
        }
    if kind in ("pipe", "culvert", "circular_culvert"):
        D = _num("diameter_m", link.get("diameter_m"), minimum=1e-6)
        ratio = _num(
            "max_fill_ratio", link.get("max_fill_ratio", 0.75), minimum=1e-6
        )
        if ratio >= 1.0:
            raise DrainageNetworkError("max_fill_ratio must be less than 1.0.")
        h = ratio * D
        theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * h / D)))
        A = D * D / 8.0 * (theta - math.sin(theta))
        P = D * theta / 2.0
        R = A / P if P > 0 else 0.0
        qcap = (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)
        return {
            "type": "pipe",
            "capacity_m3s": qcap,
            "geometry": {"diameter_m": D, "max_fill_ratio": ratio, "slope": slope},
            "full_flow_area_m2": A,
            "full_flow_velocity_m_s": qcap / A if A > 0 else 0.0,
        }
    if kind in ("box", "box_culvert"):
        section = _box_section(link)
        h = BC.hydraulic_capacity(section, slope, n, design_flow_m3s=0.0)
        return {
            "type": "box_culvert",
            "capacity_m3s": h["capacity_m3s"],
            "geometry": section.as_dict() | {"slope": slope},
            "full_flow_area_m2": h["full_flow_area_m2"],
            "full_flow_velocity_m_s": (
                h["capacity_m3s"] / h["full_flow_area_m2"]
                if h["full_flow_area_m2"] > 0
                else 0.0
            ),
        }
    if kind in ("fixed", "user_capacity"):
        qcap = _num("capacity_m3s", link.get("capacity_m3s"), minimum=0.0)
        return {
            "type": "fixed",
            "capacity_m3s": qcap,
            "geometry": {},
            "full_flow_area_m2": None,
            "full_flow_velocity_m_s": None,
        }
    raise DrainageNetworkError(f"Unknown drainage link type: {kind!r}")


def _analyse_link(link: Mapping[str, Any], flow_m3s: float) -> dict[str, Any]:
    kind = str(link.get("type", "channel")).lower()
    slope = float(link.get("slope", 0.005))
    n = float(link.get("manning_n", CH.DEFAULTS["manning_n"]))
    if kind in ("channel", "open_channel", "ditch"):
        res = CH.analyse(
            flow_m3s,
            float(link["inner_width_m"]),
            float(link["depth_m"]),
            slope,
            {"manning_n": n, **{k: v for k, v in (link.get("hydraulic_params") or {}).items()}},
        )
        return {
            "ok": res["pass"],
            "hydraulic": res,
            "normal_depth_m": res["h_normal_m"],
            "velocity_m_s": res["V_design_ms"],
            "froude": next(
                (c["value"] for c in res["checks"] if c["item"].startswith("福祿數")),
                None,
            ),
            "checks": res["checks"],
        }
    if kind in ("pipe", "culvert", "circular_culvert"):
        res = CH.check_culvert(
            flow_m3s,
            float(link["diameter_m"]),
            n,
            slope,
            link.get("hydraulic_params"),
        )
        return {
            "ok": bool(res.get("ok")),
            "hydraulic": res,
            "normal_depth_m": None,
            "velocity_m_s": None,
            "froude": None,
            "checks": [
                {
                    "item": "涵管容量（第87條不滿流）",
                    "value": flow_m3s,
                    "limit": res.get("Q_cap_m3s", 0.0),
                    "ok": bool(res.get("ok")),
                    "unit": "m3/s",
                }
            ],
        }
    if kind in ("box", "box_culvert"):
        section = _box_section(link)
        res = BC.hydraulic_capacity(
            section,
            slope,
            n,
            design_flow_m3s=flow_m3s,
            freeboard_min_m=float(link.get("freeboard_min_m", 0.20)),
        )
        return {
            "ok": bool(res["ok"]),
            "hydraulic": res,
            "normal_depth_m": res["normal_depth_m"],
            "velocity_m_s": res["velocity_m_s"],
            "froude": res["froude"],
            "checks": [
                {
                    "item": "箱涵正常水深＋出水高",
                    "value": res["normal_depth_m"] + res["freeboard_min_m"],
                    "limit": section.clear_height_m,
                    "ok": res["ok"],
                    "unit": "m",
                }
            ],
        }
    if kind in ("fixed", "user_capacity"):
        cap = _num("capacity_m3s", link.get("capacity_m3s"), minimum=0.0)
        return {
            "ok": flow_m3s <= cap + 1e-12,
            "hydraulic": {"capacity_m3s": cap},
            "normal_depth_m": None,
            "velocity_m_s": None,
            "froude": None,
            "checks": [
                {
                    "item": "指定容量",
                    "value": flow_m3s,
                    "limit": cap,
                    "ok": flow_m3s <= cap + 1e-12,
                    "unit": "m3/s",
                }
            ],
        }
    raise DrainageNetworkError(f"Unknown drainage link type: {kind!r}")


def analyse(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise DrainageNetworkError("drainage-network input must be a mapping.")
    node_inputs = data.get("nodes") or []
    link_inputs = data.get("links") or []
    if not node_inputs:
        raise DrainageNetworkError("At least one node is required.")
    nodes: dict[str, dict[str, Any]] = {}
    for raw in node_inputs:
        nid = str(raw.get("id", "")).strip()
        if not nid:
            raise DrainageNetworkError("Every node needs an id.")
        if nid in nodes:
            raise DrainageNetworkError(f"Duplicate node id {nid!r}.")
        nodes[nid] = {
            "id": nid,
            "inflow_m3s": _num(
                "node inflow_m3s", raw.get("inflow_m3s", raw.get("local_inflow_m3s", 0.0)), minimum=0.0
            ),
            "elevation_m": (
                None if raw.get("elevation_m") in (None, "")
                else _num("node elevation_m", raw["elevation_m"])
            ),
        }
    links: dict[str, dict[str, Any]] = {}
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {nid: 0 for nid in nodes}
    for raw in link_inputs:
        lid = str(raw.get("id", "")).strip()
        if not lid:
            raise DrainageNetworkError("Every link needs an id.")
        if lid in links:
            raise DrainageNetworkError(f"Duplicate link id {lid!r}.")
        source, target = str(raw.get("from", "")).strip(), str(raw.get("to", "")).strip()
        if source not in nodes or target not in nodes:
            raise DrainageNetworkError(
                f"Link {lid} references unknown node ({source!r} -> {target!r})."
            )
        cap = link_capacity(raw)
        links[lid] = {
            "id": lid,
            "from": source,
            "to": target,
            "input": dict(raw),
            "capacity": cap,
        }
        outgoing[source].append(lid)
        indegree[target] += 1

    # Kahn topological sort, preserving input order.
    queue = [nid for nid in nodes if indegree[nid] == 0]
    order: list[str] = []
    mutable_indegree = dict(indegree)
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for lid in outgoing.get(nid, []):
            target = links[lid]["to"]
            mutable_indegree[target] -= 1
            if mutable_indegree[target] == 0:
                queue.append(target)
    if len(order) != len(nodes):
        raise DrainageNetworkError("Drainage network contains a cycle.")

    incoming_flow = {nid: 0.0 for nid in nodes}
    link_flows: dict[str, float] = {}
    node_rows: list[dict[str, Any]] = []
    for nid in order:
        available = nodes[nid]["inflow_m3s"] + incoming_flow[nid]
        out_ids = outgoing.get(nid, [])
        if not out_ids:
            if available > 1e-12:
                node_rows.append(
                    {
                        "id": nid,
                        "local_inflow_m3s": nodes[nid]["inflow_m3s"],
                        "incoming_m3s": incoming_flow[nid],
                        "outgoing_m3s": available,
                        "terminal_outfall": True,
                    }
                )
            continue
        fractions = [links[lid]["input"].get("split_fraction") for lid in out_ids]
        if any(f is not None for f in fractions):
            if any(f is None for f in fractions):
                raise DrainageNetworkError(
                    f"Node {nid}: specify split_fraction on all or none of its outgoing links."
                )
            frac = [_num("split_fraction", f, minimum=0.0) for f in fractions]
            if abs(sum(frac) - 1.0) > 1e-6:
                raise DrainageNetworkError(
                    f"Node {nid}: outgoing split fractions must sum to 1.0."
                )
        else:
            weights = [max(links[lid]["capacity"]["capacity_m3s"], 0.0) for lid in out_ids]
            total_w = sum(weights)
            frac = (
                [w / total_w for w in weights]
                if total_w > 0.0
                else [1.0 / len(out_ids)] * len(out_ids)
            )
        node_out = 0.0
        for lid, f in zip(out_ids, frac):
            flow = available * f
            link_flows[lid] = flow
            incoming_flow[links[lid]["to"]] += flow
            node_out += flow
        node_rows.append(
            {
                "id": nid,
                "local_inflow_m3s": nodes[nid]["inflow_m3s"],
                "incoming_m3s": incoming_flow[nid],
                "outgoing_m3s": node_out,
                "terminal_outfall": False,
            }
        )

    link_rows = []
    checks = []
    for lid, info in links.items():
        flow = link_flows.get(lid, 0.0)
        cap = info["capacity"]
        result = _analyse_link(info["input"], flow)
        ratio = flow / cap["capacity_m3s"] if cap["capacity_m3s"] > 0 else math.inf
        capacity_ok = flow <= cap["capacity_m3s"] + 1e-9
        ok = bool(result["ok"]) and capacity_ok
        link_rows.append(
            {
                "id": lid,
                "from": info["from"],
                "to": info["to"],
                "type": cap["type"],
                "flow_m3s": round(flow, 6),
                "capacity_m3s": round(cap["capacity_m3s"], 6),
                "capacity_ratio": round(ratio, 4) if math.isfinite(ratio) else None,
                "normal_depth_m": result["normal_depth_m"],
                "velocity_m_s": result["velocity_m_s"],
                "froude": result["froude"],
                "ok": ok,
                "checks": result["checks"],
            }
        )
        checks.append(
            {
                "item": f"排水路 {lid}（{info['from']}→{info['to']}）容量",
                "value": flow,
                "limit": cap["capacity_m3s"],
                "unit": "m3/s",
                "ok": capacity_ok,
                "relation": "le",
            }
        )
        for subcheck in result.get("checks") or []:
            if not isinstance(subcheck, Mapping):
                continue
            child = dict(subcheck)
            child["item"] = f"排水路 {lid}：{child.get('item', '水力檢核')}"
            if child.get("limit") is None and child.get("required") is not None:
                child["limit"] = child["required"]
                child["relation"] = "ge"
            checks.append(child)
    terminal_outflow = sum(
        row["outgoing_m3s"] for row in node_rows if row["terminal_outfall"]
    )
    total_inflow = sum(n["inflow_m3s"] for n in nodes.values())
    balance_error = terminal_outflow - total_inflow if link_rows else -total_inflow
    return {
        "engine": "drainage_network",
        "version": "0.1",
        "nodes": node_rows,
        "links": link_rows,
        "total_local_inflow_m3s": round(total_inflow, 6),
        "terminal_outflow_m3s": round(terminal_outflow, 6),
        "flow_balance_error_m3s": round(balance_error, 9),
        "checks": checks,
        "pass": all(
            bool(c.get("ok"))
            for c in checks
            if c.get("severity") != "advisory"
        ),
        "warnings": [
            "Steady peak-flow routing only; storage and time lag are not included.",
            "Normal-depth capacity only; gradually varied flow, backwater and inlet/outlet control are not yet included.",
            "Link capacity does not include debris blockage, sediment deposition or outlet scour.",
        ],
    }


def format_report(result: Mapping[str, Any]) -> str:
    lines = [
        "排水網路：%d 節點、%d 渠段；總入流 %.3f m³/s"
        % (
            len(result["nodes"]),
            len(result["links"]),
            result["total_local_inflow_m3s"],
        )
    ]
    for link in result["links"]:
        failures = [
            str(c.get("item"))
            for c in link.get("checks") or []
            if not c.get("ok")
        ]
        lines.append(
            "  [%s] %-8s %s → %s  Q=%.3f / %.3f m³/s（%.1f%%）%s"
            % (
                "OK" if link["ok"] else "NG",
                link["id"],
                link["from"],
                link["to"],
                link["flow_m3s"],
                link["capacity_m3s"],
                (link["capacity_ratio"] or 0.0) * 100.0,
                (
                    "；未過：" + "、".join(failures)
                    if failures
                    else ""
                ),
            )
        )
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（A→C 矩形溝、B→C 固定容量，C 為出口）。"""
    from _selftest_util import Checker

    c = Checker("排水網路")
    width, depth, slope, n = 1.0, 1.0, 0.004, 0.014
    r = analyse({
        "nodes": [{"id": "A", "inflow_m3s": 1.0}, {"id": "B", "inflow_m3s": 0.5}, {"id": "C"}],
        "links": [
            {"id": "L1", "from": "A", "to": "C", "type": "channel", "inner_width_m": width,
             "depth_m": depth, "slope": slope, "manning_n": n},
            {"id": "L2", "from": "B", "to": "C", "type": "fixed", "capacity_m3s": 2.0},
        ],
    })
    l1 = r["links"][0]
    area = width * depth
    radius = area / (width + 2.0 * depth)
    capacity = area * radius ** (2.0 / 3.0) * slope ** 0.5 / n
    c.close("節點連續：出口流量＝入流合計", r["terminal_outflow_m3s"], 1.0 + 0.5)
    c.close("流量平衡誤差", r["flow_balance_error_m3s"], 0.0)
    c.close("L1 Manning 容量", l1["capacity_m3s"], capacity, tol=1e-4)
    c.close("L1 容量比 Q/Qcap", l1["capacity_ratio"], 1.0 / capacity, tol=1e-3)
    y = l1["normal_depth_m"]
    a_y = width * y
    r_y = a_y / (width + 2.0 * y)
    c.close("L1 正常水深代回 Manning 得 Q", a_y * r_y ** (2.0 / 3.0) * slope ** 0.5 / n, 1.0, tol=1e-3)
    c.close("L1 流速 V＝Q/A", l1["velocity_m_s"], 1.0 / a_y, tol=1e-3)
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json

    ap = argparse.ArgumentParser(description="排水網路流量分配與容量檢核")
    ap.add_argument("case_json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    result = analyse(json.load(open(a.case_json, encoding="utf-8")))
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if a.json
        else format_report(result)
    )
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()

