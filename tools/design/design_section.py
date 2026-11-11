"""工程設計工作台「設計圖」產線：計算結果 → 標準斷面圖／配筋圖（DXF／DWG／PDF）。

定位
----
工作台計算完一個構造物之後，下一步就是**設計圖**。本模組負責把
「計算器的輸入（payload）」轉成統一案件檔（`civil-case/1`），再交給既有的
確定性出圖工具：

* `tools\\box_section\\make_box_section.py` → 箱涵 S-01 斷面圖／S-02 配筋圖
* `tools\\wall_section\\make_wall_section.py` → 擋土牆 S-01／S-02、排水溝 D-01／D-02、邊坡 E-01

**不重造出圖邏輯**：斷面幾何、配筋、圖框、字型、尺寸樣式與品管閘門
（E1~E18）全部沿用既有工具，本模組只做「案件組裝＋呼叫＋檔案回傳」。

圖面單位
--------
模型空間**永遠是公尺**（AGENTS.md §2：公制公尺、$INSUNITS=6）。
「圖面單位（M／cm）」只改**圖面標註單位**：

* m  → 尺寸樣式 `dimlfac=1.0`、小數 2 位、字尾「m」
* cm → 尺寸樣式 `dimlfac=100`、小數 0 位、字尾「cm」，右欄尺寸表與說明同步換單位

用法
----
    from design_section import capability, build_case, generate
    cap = capability("box_culvert")          # 該計算器能否出圖、可用單位與比例
    res = generate("box_culvert", payload, unit="cm", scale="auto")
    res["files"]                              # DXF／DWG／PDF 檔案清單
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from typing import Any, Mapping

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, os.path.join(ROOT, "tools"),
           os.path.join(ROOT, "tools", "case_package")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drawing_rules as DR                    # noqa: E402


class SectionError(Exception):
    """出圖失敗（輸入不足、比例不合法、工具回報錯誤…）。"""


# --------------------------------------------------------------------------- #
# 產出位置
# --------------------------------------------------------------------------- #
def _out_root() -> str:
    """交付物落點：`out\\design_sections\\`（AGENTS.md §1.1：交付物一律進 out）。"""
    try:
        from project_paths import out_dir

        return str(out_dir("design_sections"))
    except Exception:
        return os.path.join(ROOT, "out", "design_sections")


def _temp_root() -> str:
    """暫存案件檔落點：`_temp\\design_sections\\`。"""
    try:
        from project_paths import temp_dir

        return str(temp_dir("design_sections"))
    except Exception:
        return os.path.join(ROOT, "_temp", "design_sections")


# --------------------------------------------------------------------------- #
# 能力表：哪些計算器能出圖、對應哪支工具與檔名
# --------------------------------------------------------------------------- #
CAPABILITIES: dict[str, dict[str, Any]] = {
    "box_culvert": {
        "title": "箱涵標準斷面圖（S-01）＋配筋圖（S-02）",
        "tool": "box_section",
        "model": "box_culvert",
        "sheets": [
            {"suffix": "S-01_箱涵標準斷面圖", "rebar": False},
            {"suffix": "S-02_箱涵配筋圖", "rebar": True},
        ],
    },
    "wall_stability": {
        "title": "擋土牆標準斷面圖（S-01）＋配筋圖（S-02）",
        "tool": "wall_section",
        "model": "wall",
        "sheets": [
            {"suffix": "S-01_擋土牆標準斷面圖", "rebar": False},
            {"suffix": "S-02_擋土牆配筋圖", "rebar": True},
        ],
    },
    "rc_beam": {
        "title": "RC 梁斷面配筋圖（B-01）",
        "tool": "rc_section",
        "model": "rc_beam",
        "sheets": [
            {"suffix": "B-01_RC梁斷面配筋圖", "rebar": False},
        ],
    },
    "rc_column": {
        "title": "RC 柱斷面配筋圖（CL-1）",
        "tool": "rc_section",
        "model": "rc_column",
        "sheets": [
            {"suffix": "CL-1_RC柱斷面配筋圖", "rebar": False},
        ],
    },
    "foundation_isolated": {
        "title": "獨立基腳平面＋剖面配筋圖（F-1）",
        "tool": "foundation_section",
        "model": "foundation_isolated",
        "sheets": [{"suffix": "F-1_獨立基腳配筋圖", "rebar": False}],
    },
    "foundation_combined": {
        "title": "聯合基腳平面＋剖面配筋圖（F-2）",
        "tool": "foundation_section",
        "model": "foundation_combined",
        "sheets": [{"suffix": "F-2_聯合基腳配筋圖", "rebar": False}],
    },
    "detention_basin": {
        "title": "滯洪池平面＋縱剖面圖（P-1）",
        "tool": "basin_section",
        "model": "detention_basin",
        "sheets": [{"suffix": "P-1_滯洪池平面剖面圖", "rebar": False}],
    },
    "sediment_basin": {
        "title": "沉砂池平面＋縱剖面圖（P-2）",
        "tool": "basin_section",
        "model": "sediment_basin",
        "sheets": [{"suffix": "P-2_沉砂池平面剖面圖", "rebar": False}],
    },
    "channel_cover": {
        "title": "溝蓋版斷面＋配筋／植筋詳圖（C-01）",
        "tool": "channel_cover",
        "model": "channel_cover",
        "sheets": [
            {"suffix": "C-01_溝蓋版詳圖", "rebar": False},
        ],
    },
    "channel_profile": {
        "title": "水面線縱斷面圖（L-1，縱橫異比例）",
        "tool": "profile_section",
        "model": "channel_profile",
        "sheets": [
            {"suffix": "L-1_水面線縱斷面圖", "rebar": False},
        ],
    },
    "steel_column": {
        "title": "鋼柱柱腳詳圖（SC-1）",
        "tool": "steel_base_section",
        "model": "steel_column",
        "sheets": [
            {"suffix": "SC-1_鋼柱柱腳詳圖", "rebar": False},
        ],
    },
    "building_frame": {
        "title": "構架立面圖＋構材配筋表（FR-1）",
        "tool": "frame_section",
        "model": "building_frame",
        "sheets": [
            {"suffix": "FR-1_構架立面圖", "rebar": False},
        ],
    },
    "foundation_pile": {
        "title": "樁位配置圖（FP-1）",
        "tool": "foundation_plan",
        "model": "pile_group",
        "sheets": [
            {"suffix": "FP-1_樁位配置圖", "rebar": False},
        ],
    },
    "settlement_assessment": {
        "title": "基腳沉陷配置圖（FS-1）",
        "tool": "foundation_plan",
        "model": "settlement",
        "sheets": [
            {"suffix": "FS-1_基腳沉陷配置圖", "rebar": False},
        ],
    },
    "drainage_network": {
        "title": "排水網路示意圖（NW-1，非比例）",
        "tool": "network_section",
        "model": "drainage_network",
        "sheets": [
            {"suffix": "NW-1_排水網路示意圖", "rebar": False},
        ],
    },
    "block_wall": {
        "title": "疊式／砌石擋土牆標準斷面圖（S-01）",
        "tool": "wall_section",
        "model": "block_wall",
        "sheets": [
            {"suffix": "S-01_疊式砌石擋土牆標準斷面圖", "rebar": False},
        ],
    },
    "counterfort_wall": {
        "title": "扶壁式擋土牆標準斷面圖（S-01）＋配筋圖（S-02）",
        "tool": "wall_section",
        "model": "wall",
        "wall_type": "counterfort",
        "sheets": [
            {"suffix": "S-01_扶壁式擋土牆標準斷面圖", "rebar": False},
            {"suffix": "S-02_扶壁式擋土牆配筋圖", "rebar": True},
        ],
    },
    "mse_wall": {
        "title": "加勁式擋土牆 RC 面版斷面圖（S-01）＋配筋圖（S-02）",
        "tool": "wall_section",
        "model": "wall",
        "wall_type": "mse",
        "sheets": [
            {"suffix": "S-01_加勁式擋土牆標準斷面圖", "rebar": False},
            {"suffix": "S-02_加勁式擋土牆配筋圖", "rebar": True},
        ],
    },
    "anchored_wall": {
        "title": "錨定式擋土牆標準斷面圖（S-01）＋配筋圖（S-02）",
        "tool": "wall_section",
        "model": "wall",
        "wall_type": "anchored",
        "sheets": [
            {"suffix": "S-01_錨定式擋土牆標準斷面圖", "rebar": False},
            {"suffix": "S-02_錨定式擋土牆配筋圖", "rebar": True},
        ],
    },
    "channel_hydraulics": {
        "title": "排水溝標準斷面圖（D-01）＋配筋圖（D-02）",
        "tool": "wall_section",
        "model": "channel",
        "sheets": [
            {"suffix": "D-01_排水溝標準斷面圖", "rebar": False},
            {"suffix": "D-02_排水溝配筋圖", "rebar": True},
        ],
    },
    "slope_stability": {
        "title": "邊坡標準斷面圖（E-01）",
        "tool": "wall_section",
        "model": "slope",
        "sheets": [
            {"suffix": "E-01_邊坡標準斷面圖", "rebar": False},
        ],
    },
}


# 明確表態「不適用」：計算器沒有任何幾何可畫，不是漏做。附理由，會顯示在前端。
NOT_APPLICABLE: dict[str, str] = {
    "hydrology": "水文分析的輸入與輸出沒有幾何（只有降雨強度、逕流係數、流量），沒有東西可畫成設計圖。",
}

# 三態：supported（可出圖）／not_applicable（不適用，附理由）／not_implemented（尚未提供）
STATUSES = ("supported", "not_applicable", "not_implemented")


def status_of(calc_id: str) -> str:
    if calc_id in CAPABILITIES:
        return "supported"
    if calc_id in NOT_APPLICABLE:
        return "not_applicable"
    return "not_implemented"


def capability(calc_id: str) -> dict[str, Any]:
    """回報某計算器能否出圖，以及可選的圖面單位與比例。

    `status` 為三態之一；`supported` 保留給舊前端（等同 status == "supported"）。
    """
    spec = CAPABILITIES.get(calc_id)
    scales = [s for s in DR.STANDARD_SCALES if s <= 250]
    status = status_of(calc_id)
    return {
        "calculator": calc_id,
        "status": status,
        "reason": NOT_APPLICABLE.get(calc_id, ""),
        "supported": status == "supported",
        "title": (spec or {}).get("title", ""),
        "sheets": [s["suffix"] for s in (spec or {}).get("sheets", [])],
        "units": [
            {"value": "m", "label": "M（公尺）"},
            {"value": "cm", "label": "cm（公分）"},
        ],
        "scales": [{"value": "auto", "label": "自動（依斷面外廓選最小比例）"}] + [
            {"value": s, "label": "1:%d" % s} for s in scales
        ],
        "unit_note": "模型空間一律為公尺；圖面單位只改標註與右欄尺寸表的顯示單位。",
    }


def capability_map(calc_ids: list[str] | None = None) -> dict[str, Any]:
    """所有計算器的出圖能力。`calc_ids` 給定時涵蓋整份目錄（含未實作與不適用）。"""
    ids = list(calc_ids) if calc_ids is not None else list(CAPABILITIES)
    return {cid: capability(cid) for cid in ids}


# --------------------------------------------------------------------------- #
# 案件組裝：payload → civil-case/1
# --------------------------------------------------------------------------- #
def _get(src: Mapping[str, Any], key: str, default: Any = None) -> Any:
    v = src.get(key)
    return default if v in (None, "") else v


def _num(src: Mapping[str, Any], key: str, default: float | None = None) -> float | None:
    v = _get(src, key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _pick_values(src: Mapping[str, Any], keys: list[str],
                 defaults: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """挑出案件數量需要的欄位；缺者用預設值並回報清單。"""
    out: dict[str, Any] = {}
    missing: list[str] = []
    for k in keys:
        v = _get(src, k)
        if v is None:
            if k in defaults:
                out[k] = defaults[k]
                missing.append("%s=%s" % (k, defaults[k]))
            continue
        out[k] = v
    return out, missing


def _wall_values(payload: Mapping[str, Any],
                 wall_type: str = "") -> tuple[dict[str, Any], list[str]]:
    """擋土牆族（重力／半重力／懸臂／扶壁／錨定／加勁）→ 數量模型輸入。"""
    # 專屬計算器（counterfort_wall／mse_wall／anchored_wall）的 payload 沒有
    # wall_type 欄位，由能力表指定；wall_stability 才從 payload 讀。
    wt = str(wall_type or _get(payload, "wall_type", "cantilever")).strip().lower()
    common = [
        "height_m", "stem_thickness_m", "base_width_m", "base_thickness_m",
        "top_width_m", "toe_length_m", "counterfort_spacing_m",
        "counterfort_thickness_m", "counterfort_top_width_m",
        "wall_thickness_m", "anchor_depths_m", "horizontal_spacing_m",
        "face_panel_thickness_m", "reinforcement_length_m",
        "vertical_spacing_m", "long_term_strength_kN_per_m",
        "first_layer_m", "embedment_m", "facing_type",
        "front_soil_depth_m", "toe_soil_depth_m",
        "front_batter_ratio", "back_batter_ratio", "toe_projection_m",
        "inclination_deg", "free_length_m", "bond_length_m",
    ]
    defaults = {
        "length_m": 20.0,
        "weep_diameter_m": 0.05,
        "backfill_thickness_m": 0.30,
        "rebar_ratio_kg_m3": 40.0,
        "excavation_work_m": 0.30,
        "excavation_depth_m": 0.30,
        "cross_drain_spacing_m": 30.0,
    }
    values, missing = _pick_values(payload, common, defaults)
    values["wall_type"] = wt
    values["length_m"] = _num(payload, "length_m", defaults["length_m"])
    values["weep_diameter_m"] = _num(payload, "weep_diameter_m",
                                     defaults["weep_diameter_m"])
    values["backfill_thickness_m"] = _num(payload, "backfill_thickness_m",
                                          defaults["backfill_thickness_m"])
    values["rebar_ratio_kg_m3"] = _num(payload, "rebar_ratio_kg_m3",
                                       defaults["rebar_ratio_kg_m3"])
    need = {
        "gravity": ["height_m", "stem_thickness_m", "base_width_m"],
        "semigravity": ["height_m", "top_width_m", "base_width_m",
                        "base_thickness_m"],
        "cantilever": ["height_m", "stem_thickness_m", "base_width_m",
                       "base_thickness_m"],
        "counterfort": ["height_m", "stem_thickness_m", "base_width_m",
                        "base_thickness_m", "toe_length_m",
                        "counterfort_spacing_m", "counterfort_thickness_m",
                        "counterfort_top_width_m"],
        "anchored": ["height_m", "wall_thickness_m", "base_width_m",
                     "base_thickness_m", "anchor_depths_m",
                     "horizontal_spacing_m"],
        "mse": ["height_m", "face_panel_thickness_m", "reinforcement_length_m",
                "vertical_spacing_m", "long_term_strength_kN_per_m"],
    }.get(wt, [])
    lack = [k for k in need if _get(payload, k) is None]
    if lack:
        raise SectionError(
            "擋土牆（%s）出圖缺少必要尺寸：%s。請先於計算畫面補齊後再出圖。"
            % (wt, "、".join(lack)))
    return values, missing


def _box_values(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    keys = [
        "length_m", "cell_count", "clear_width_m", "clear_height_m",
        "wall_thickness_m", "interior_wall_thickness_m", "top_slab_thickness_m",
        "bottom_slab_thickness_m", "cover_depth_m", "inner_chamfer_m",
        "corner_rebar", "corner_rebar_spacing_mm", "rebar_loss_rate",
    ]
    defaults = {
        "length_m": 20.0,
        "interior_wall_thickness_m": 0.30,
        "cover_depth_m": 0.60,
        "inner_chamfer_m": 0.20,
        "corner_rebar": "D13",
        "corner_rebar_spacing_mm": 200.0,
        "rebar_loss_rate": 0.06,
        "excavation_work_m": 0.30,
        "excavation_depth_m": 0.30,
    }
    values, missing = _pick_values(payload, keys, defaults)
    lack = [k for k in ("cell_count", "clear_width_m", "clear_height_m",
                        "wall_thickness_m", "top_slab_thickness_m",
                        "bottom_slab_thickness_m")
            if _get(payload, k) is None]
    if lack:
        raise SectionError(
            "箱涵出圖缺少必要尺寸：%s。請先於計算畫面補齊後再出圖。"
            % "、".join(lack))
    values["length_m"] = _num(payload, "length_m", defaults["length_m"])
    values["rebar_loss_rate"] = _num(payload, "rebar_loss_rate",
                                     defaults["rebar_loss_rate"])
    return values, missing


def _channel_values(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    keys = ["length_m", "inner_width_m", "depth_m", "wall_thickness_m",
            "base_thickness_m", "excavation_work_m", "excavation_depth_m"]
    defaults = {
        "length_m": 100.0,
        # 水保規範最小構造厚度 15 cm（排水溝壁與底板）
        "wall_thickness_m": 0.15,
        "base_thickness_m": 0.15,
        "excavation_work_m": 0.30,
        "excavation_depth_m": 0.30,
        "cross_drain_spacing_m": 30.0,
        "rebar_ratio_kg_m3": 40.0,
    }
    values, missing = _pick_values(payload, keys, defaults)
    lack = [k for k in ("inner_width_m", "depth_m")
            if _get(payload, k) is None]
    if lack:
        raise SectionError(
            "排水溝出圖缺少必要尺寸：%s。請先於計算畫面補齊後再出圖。"
            % "、".join(lack))
    values["length_m"] = _num(payload, "length_m", defaults["length_m"])
    values["wall_thickness_m"] = _num(payload, "wall_thickness_m",
                                      defaults["wall_thickness_m"])
    values["base_thickness_m"] = _num(payload, "base_thickness_m",
                                      defaults["base_thickness_m"])
    values["rebar_ratio_kg_m3"] = _num(payload, "rebar_ratio_kg_m3", 40.0)
    return values, missing


def _slope_values(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    keys = ["height_m", "slope_angle_deg", "length_m", "bench_width_m",
            "bench_count", "vegetation_ratio", "drain_spacing_m",
            "excavation_work_m"]
    defaults = {
        "length_m": 40.0,
        "bench_width_m": 0.0,
        "bench_count": 0,
        "vegetation_ratio": 1.0,
        "drain_spacing_m": 30.0,
        "excavation_work_m": 0.30,
    }
    values, missing = _pick_values(payload, keys, defaults)
    lack = [k for k in ("height_m", "slope_angle_deg")
            if _get(payload, k) is None]
    if lack:
        raise SectionError(
            "邊坡出圖缺少必要尺寸：%s。請先於計算畫面補齊後再出圖。"
            % "、".join(lack))
    values["length_m"] = _num(payload, "length_m", defaults["length_m"])
    values["bench_width_m"] = _num(payload, "bench_width_m", 0.0)
    values["bench_count"] = _num(payload, "bench_count", 0)
    return values, missing


def _block_values(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """疊式／砌石牆：幾何由 block_wall 引擎依這些輸入推導，這裡只把輸入原樣帶過去。"""
    skip = {"soil", "kh", "seismic"}
    values = {k: v for k, v in dict(payload).items() if k not in skip}
    wt = str(values.get("wall_type") or "").strip().lower()
    if not wt:
        raise SectionError("疊式／砌石牆出圖缺少 wall_type。")
    values["wall_type"] = wt
    return values, []


def build_case(calc_id: str, payload: Mapping[str, Any],
               *, project: str = "") -> dict[str, Any]:
    """把計算器輸入組成統一案件檔（`civil-case/1`）。

    回傳 `{"case": ..., "defaults_used": [...], "notes": [...]}`。
    """
    spec = CAPABILITIES.get(calc_id)
    if spec is None:
        raise SectionError("計算器 %s 目前不支援出圖。" % calc_id)
    payload = payload or {}
    model = spec["model"]
    if model == "wall":
        values, missing = _wall_values(payload, spec.get("wall_type", ""))
    elif model == "box_culvert":
        values, missing = _box_values(payload)
    elif model == "channel":
        values, missing = _channel_values(payload)
    elif model == "slope":
        values, missing = _slope_values(payload)
    elif model == "block_wall":
        values, missing = _block_values(payload)
    elif model in ("rc_beam", "rc_column", "foundation_isolated", "foundation_combined",
                   "detention_basin", "sediment_basin", "channel_profile", "steel_column",
                   "building_frame", "pile_group", "settlement", "drainage_network"):
        values, missing = dict(payload), []
    elif model == "channel_cover":
        values, missing = dict(payload), []     # 整份計算器輸入原樣交給引擎，圖上數值取自結果
    else:                                          # pragma: no cover - 防呆
        raise SectionError("未知的出圖模型 %s。" % model)

    name = project or ("%s設計圖" % calc_id)
    case: dict[str, Any] = {
        "schema": "civil-case/1",
        "case_id": "workbench_%s" % calc_id,
        "title": name,
        "project": {
            "name": name,
            "full_name": name,
            "category": calc_id,
        },
        "quantities": {
            "model": model,
            "values": values,
            "assumed": list(missing),      # D12：採預設值的出圖尺寸（圖面標「假設值」）
            "notes": ["由工程設計工作台試算結果自動組裝（%s）。" % calc_id],
        },
        "soil": dict(payload.get("soil") or {}),
        "seismic": {"kh": _num(payload, "kh", 0.0) or 0.0},
    }
    concrete = {}
    for k in ("fc_mpa", "fy_mpa", "cover_mm"):
        v = _get(payload, k)
        if v is not None:
            concrete[k] = float(v)
    if concrete:
        case["concrete"] = concrete

    if model == "box_culvert":
        case["hydraulics"] = {
            "design_flow_m3s": _num(payload, "design_flow_m3s", 0.0),
            "slope": _num(payload, "slope", 0.005),
            "manning_n": _num(payload, "manning_n", 0.014),
            "freeboard_min_m": _num(payload, "freeboard_min_m", 0.20),
        }
        case["culvert"] = {
            "cover_mm": _num(payload, "cover_mm", 50.0),
            "crack_limit_mm": _num(payload, "crack_limit_mm", 0.30),
            "bar_preference": str(_get(payload, "bar_preference", "auto")),
            "distribution_bar": str(_get(payload, "distribution_bar", "D13")),
            "traffic_type": _get(payload, "traffic_type"),
            "traffic_load_kpa": _num(payload, "traffic_load_kpa", 0.0),
            "traffic_lanes": int(_num(payload, "traffic_lanes", 4) or 4),
            "traffic_impact_factor": _num(payload, "traffic_impact_factor"),
            "soil_unit_weight_kn_m3": _num(payload, "soil_unit_weight_kn_m3", 18.0),
            "soil_phi_deg": _num(payload, "soil_phi_deg", 30.0),
            "surcharge_kpa": _num(payload, "surcharge_kpa", 0.0),
            "groundwater_depth_m": _num(payload, "groundwater_depth_m"),
            "internal_water_depth_m": _num(payload, "internal_water_depth_m", 0.0),
            "load_factor": _num(payload, "load_factor", 1.7),
        }
        for k in ("inlet_type", "tailwater_depth_m", "allowable_headwater_m"):
            v = _get(payload, k)
            if v is not None:
                case["culvert"][k] = v
    elif model == "channel":
        case["hydraulics"] = {
            "design_flow_m3s": _num(payload, "design_flow_m3s", 0.0),
            "slope": _num(payload, "slope", 0.005),
            "manning_n": _num(payload, "manning_n", 0.014),
            "freeboard_min_m": _num(payload, "freeboard_min_m", 0.20),
        }

    notes = []
    if missing:
        notes.append("出圖採用預設值（計算器未輸入）：%s。" % "、".join(missing))
    return {"case": case, "defaults_used": missing, "notes": notes}


# --------------------------------------------------------------------------- #
# 出圖
# --------------------------------------------------------------------------- #
def _python_exe() -> str:
    try:
        from project_paths import python_exe

        return python_exe()
    except Exception:
        return sys.executable


def _tool_path(tool: str) -> str:
    if tool == "steel_base_section":
        return os.path.join(ROOT, "tools", "steel_base_section", "make_steel_base.py")
    if tool == "profile_section":
        return os.path.join(ROOT, "tools", "profile_section", "make_profile.py")
    if tool == "frame_section":
        return os.path.join(ROOT, "tools", "frame_section", "make_frame.py")
    if tool == "foundation_plan":
        return os.path.join(ROOT, "tools", "foundation_plan", "make_foundation_plan.py")
    if tool == "network_section":
        return os.path.join(ROOT, "tools", "network_section", "make_network.py")
    if tool == "basin_section":
        return os.path.join(ROOT, "tools", "basin_section", "make_basin.py")
    if tool == "foundation_section":
        return os.path.join(ROOT, "tools", "foundation_section", "make_foundation.py")
    if tool == "rc_section":
        return os.path.join(ROOT, "tools", "rc_section", "make_rc_section.py")
    if tool == "channel_cover":
        return os.path.join(ROOT, "tools", "channel_cover", "make_channel_cover.py")
    if tool == "box_section":
        return os.path.join(ROOT, "tools", "box_section", "make_box_section.py")
    return os.path.join(ROOT, "tools", "wall_section", "make_wall_section.py")


def _run(cmd: list[str], log_path: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                              env=env, cwd=ROOT)
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        return proc.returncode, fh.read()


def _resolve_scale(log: str, fallback: int = 20) -> int:
    """由工具輸出抓實際比例：先找「比例尺 1:NN」，再退回任何獨立的「1:NN」。

    出圖工具的比例訊息格式不一（有的寫「比例尺 1:20」、有的只寫「1:20」），
    先前只認前者，導致沒有那幾個字的工具在 API／_drawing_meta.json 一律回報 20。
    """
    text = log or ""
    m = re.search(r"比例尺?\s*[:：]?\s*1\s*[:：/]\s*(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![\d.])1\s*[:：]\s*(\d{1,5})(?![\d.])", text)
    return int(m.group(1)) if m else fallback


def _publish(dxf: str) -> tuple[dict[str, str], str]:
    """DXF → DWG＋PDF（經 tools/acad/acc.py，預設後端 OpenCADStudio，退路 accoreconsole／CADCraft）。失敗不致命，只回報。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "acad"))
        from acc import publish

        return publish(dxf, pdf=True), ""
    except Exception as ex:
        return {}, "DWG／PDF 轉檔未完成：%s" % ex


def generate(calc_id: str, payload: Mapping[str, Any], *,
             unit: str = "m", scale: str | int = "auto",
             project: str = "", drafter: str = "",
             publish: bool = True) -> dict[str, Any]:
    """出圖並回傳檔案清單。

    回傳 `{"ok": bool, "files": [...], "case_path": ..., "out_dir": ...,
    "scale": 實際比例, "unit": ..., "notes": [...]}`。
    """
    spec = CAPABILITIES.get(calc_id)
    if spec is None:
        raise SectionError("計算器 %s 目前不支援出圖。" % calc_id)
    unit = str(unit or "m").strip().lower()
    if unit not in ("m", "cm"):
        raise SectionError("圖面單位只支援 m 或 cm（收到 %s）。" % unit)

    built = build_case(calc_id, payload, project=project)
    case = built["case"]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(_out_root(), calc_id, stamp)
    os.makedirs(out_dir, exist_ok=True)
    temp_dir = os.path.join(_temp_root(), calc_id, stamp)
    os.makedirs(temp_dir, exist_ok=True)
    case_path = os.path.join(temp_dir, "case.json")
    with open(case_path, "w", encoding="utf-8") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)

    tool = _tool_path(spec["tool"])
    files: list[dict[str, Any]] = []
    notes = list(built["notes"])
    used_scale = None
    for sheet in spec["sheets"]:
        out_dxf = os.path.join(out_dir, sheet["suffix"] + ".dxf")
        cmd = [_python_exe(), "-E", "-P", "-X", "utf8", tool, case_path,
               "--scale", str(scale), "--unit", unit, "--out", out_dxf]
        if drafter:
            cmd += ["--drafter", str(drafter)]
        if sheet.get("rebar"):
            cmd.append("--rebar")
        code, log = _run(cmd, os.path.join(temp_dir,
                                           sheet["suffix"] + "_log.txt"))
        if used_scale is None:
            used_scale = _resolve_scale(log)
        if code != 0 or not os.path.exists(out_dxf):
            tail = "\n".join((log or "").strip().splitlines()[-12:])
            raise SectionError("%s 出圖失敗（exit %d）：\n%s"
                               % (sheet["suffix"], code, tail))
        files.append({"name": os.path.basename(out_dxf), "path": out_dxf,
                      "kind": "dxf"})
        if publish:
            res, warn = _publish(out_dxf)
            if warn:
                notes.append(warn)
            for ext, path in res.items():
                files.append({"name": os.path.basename(path), "path": path,
                              "kind": ext.strip(".")})

    # 給前端下載用的相對路徑（相對 out/design_sections，避免外洩絕對路徑）
    root = os.path.abspath(_out_root())
    for f in files:
        try:
            f["rel"] = os.path.relpath(os.path.abspath(f["path"]), root
                                       ).replace(os.sep, "/")
        except ValueError:
            f["rel"] = ""

    meta = {
        "calculator": calc_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "unit": unit,
        "scale": used_scale,
        "files": [f["path"] for f in files],
        "case": case,
        "notes": notes,
    }
    with open(os.path.join(out_dir, "_drawing_meta.json"), "w",
              encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "calculator": calc_id,
        "title": spec["title"],
        "unit": unit,
        "scale": used_scale,
        "out_dir": out_dir,
        "case_path": case_path,
        "files": files,
        "notes": notes,
        "defaults_used": built["defaults_used"],
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="工作台「設計圖」產線（JSON 介面）")
    ap.add_argument("calculator")
    ap.add_argument("payload", help="計算器輸入 JSON 檔")
    ap.add_argument("--unit", default="m", choices=["m", "cm"])
    ap.add_argument("--scale", default="auto")
    ap.add_argument("--project", default="")
    ap.add_argument("--drafter", default="", help="標題欄繪圖者（預設 Claude（AI））")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    with open(a.payload, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    try:
        res = generate(a.calculator, payload, unit=a.unit, scale=a.scale,
                       project=a.project, drafter=a.drafter,
                       publish=not a.no_publish)
    except SectionError as ex:
        print("NG %s" % ex)
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
