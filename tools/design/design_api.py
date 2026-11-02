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


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RUN_DIR = ROOT / "out" / "design_workbench" / "runs"


class DesignAPIError(ValueError):
    """Invalid calculator id or input payload."""


def _example_retaining_wall() -> dict[str, Any]:
    return {
        "wall_type": "cantilever",
        "height_m": 3.0,
        "stem_thickness_m": 0.35,
        "base_width_m": 1.95,
        "base_thickness_m": 0.36,
        "toe_soil_depth_m": 0.60,
        "include_passive": True,
        "passive_ratio": 1.0,
        "soil": {
            "gamma": 18.0,
            "phi_deg": 30.0,
            "c_kpa": 0.0,
            "allowable_bearing_kpa": 200.0,
        },
    }


_PASSIVE_RATIO_HINT = "1＝全 Rankine；牆身位移不足以發揮全被動時取小於 1"


def _passive_field_rules(ratio_hint: str = _PASSIVE_RATIO_HINT) -> dict[str, Any]:
    """Shared labels for the toe passive-pressure switches of the five wall calculators."""

    return {
        "include_passive": {"label": "計入牆趾被動土壓力（只計入抗滑）"},
        "passive_ratio": {
            "type": "number",
            "step": 0.05,
            "label": "被動土壓折減比 (0～1)",
            "hint": ratio_hint,
        },
    }


def _wall_field_rules() -> dict[str, Any]:
    import retaining_wall as RW

    section_defaults = {
        "gravity": {
            "stem_thickness_m": 0.45,
            "base_width_m": 1.80,
            "base_thickness_m": 0.0,
            "toe_soil_depth_m": 0.60,
        },
        "semigravity": {
            "top_width_m": 0.30,
            "base_width_m": 2.50,
            "base_thickness_m": 0.80,
            "front_batter_ratio": 0.30,
            "toe_projection_m": 0.50,
            "toe_soil_depth_m": 1.50,
        },
        "cantilever": {
            "stem_thickness_m": 0.35,
            "base_width_m": 1.95,
            "base_thickness_m": 0.36,
            "toe_soil_depth_m": 0.60,
        },
    }
    choices = [
        {
            "value": key,
            "label": "%s（有效高 ≤ %.1f m）"
            % (spec["label"], spec["max_height_m"]),
            "defaults": section_defaults[key],
        }
        for key, spec in RW.WALL_TYPE_SPECS.items()
    ]
    limits = {
        key: {
            "max": spec["max_height_m"],
            "basis": spec["basis"],
        }
        for key, spec in RW.WALL_TYPE_SPECS.items()
    }
    # Semigravity input is total wall height; the code limit is the exposed
    # effective height, so the working limit is 4.0 m + base thickness.
    limits["semigravity"]["input_offset_by"] = "base_thickness_m"
    return {
        **_passive_field_rules(),
        "toe_soil_depth_m": {
            "type": "number",
            "step": 0.1,
            "label": "牆趾覆土深 D (m)",
            "hint": "自基底底面算起；Pp＝½KpγD²，覆土須分層夯實且不得移除",
        },
        "wall_type": {
            "type": "select",
            "choices": choices,
            "on_change": "rerender",
            "clear_on_change": [
                "stem_thickness_m",
                "base_width_m",
                "base_thickness_m",
                "top_width_m",
                "front_batter_ratio",
                "back_batter_ratio",
                "toe_projection_m",
                "toe_soil_depth_m",
            ],
        },
        "height_m": {
            "type": "number",
            "step": 0.1,
            "label": "牆高 (m)",
            "max_by": "wall_type",
            "limits": limits,
        },
    }


_BLOCK_WALL_SECTION_KEYS = [
    "course_count",
    "course_height_m",
    "base_width_m",
    "width_decrement_m",
    "step_side",
    "height_m",
    "top_width_m",
    "front_batter_ratio",
    "back_batter_ratio",
    "stone_length_m",
    "stone_courses",
    "layers",
    "unit_weight_kn_m3",
    "interface_friction",
    "site_condition",
]


def _block_wall_defaults() -> dict[str, dict[str, Any]]:
    stepped = {
        "course_count": 3,
        "course_height_m": 1.0,
        "base_width_m": 2.5,
        "width_decrement_m": 0.5,
        "step_side": "front",
        "embedment_m": 0.5,
    }
    masonry = {
        "height_m": 3.0,
        "top_width_m": 0.5,
        "front_batter_ratio": 0.3,
        "back_batter_ratio": 0.2,
        "stone_length_m": 0.5,
        "embedment_m": 0.5,
    }
    return {
        "gabion": dict(stepped),
        "crib": dict(stepped, course_count=2, course_height_m=2.0, base_width_m=3.0,
                     width_decrement_m=0.8),
        "masonry_wet": dict(masonry),
        "masonry_dry": dict(masonry, stone_length_m=0.6),
        "sandwich": {
            "height_m": 3.0,
            "top_width_m": 0.5,
            "front_batter_ratio": 0.3,
            "back_batter_ratio": 0.0,
            "site_condition": "cut",
            "embedment_m": 0.5,
        },
    }


def _example_block_wall() -> dict[str, Any]:
    return {
        "wall_type": "gabion",
        **_block_wall_defaults()["gabion"],
        "include_passive": True,
        "passive_ratio": 1.0,
        "soil": {
            "gamma": 18.0,
            "phi_deg": 30.0,
            "backfill_slope_deg": 0.0,
            "surcharge_kpa": 0.0,
            "allowable_bearing_kpa": 200.0,
            "base_friction": 0.6,
            "foundation": "soil",
        },
        "kh": 0.0,
    }


def _block_wall_field_rules() -> dict[str, Any]:
    import block_wall as BW

    defaults = _block_wall_defaults()
    choices = []
    for key, spec in BW.BLOCK_WALL_SPECS.items():
        extra = ""
        if spec.get("max_layer_height_m"):
            extra = "、每層 ≤ %.1f m" % spec["max_layer_height_m"]
        if spec.get("max_by_site"):
            extra = "；填方坡面 ≤ %.1f m" % spec["max_by_site"]["fill"]
        choices.append({
            "value": key,
            "label": "%s（有效高 ≤ %.1f m%s）" % (spec["label"], spec["max_effective_height_m"], extra),
            "defaults": defaults[key],
        })
    masonry_limits = {
        key: {
            "max": spec["max_effective_height_m"],
            "basis": spec["basis"],
            "input_offset_by": "embedment_m",
            "offset_label": "埋入深度",
        }
        for key, spec in BW.BLOCK_WALL_SPECS.items()
        if spec["layout"] == "masonry"
    }
    for key, spec in BW.BLOCK_WALL_SPECS.items():
        if spec.get("max_by_site"):
            masonry_limits[key] = {
                "max_by": "site_condition",
                "limits": {
                    site: dict(masonry_limits[key], max=limit)
                    for site, limit in spec["max_by_site"].items()
                },
            }
    crib = BW.BLOCK_WALL_SPECS["crib"]
    return {
        "wall_type": {
            "type": "select",
            "label": "牆型",
            "choices": choices,
            "on_change": "rerender",
            "clear_on_change": _BLOCK_WALL_SECTION_KEYS + ["embedment_m"],
        },
        "step_side": {
            "type": "select",
            "label": "階梯側",
            "choices": [
                {"value": "front", "label": "前階（牆面成階、背面鉛直）"},
                {"value": "back", "label": "後階（牆面鉛直、背面成階）"},
            ],
        },
        "foundation": {
            "type": "select",
            "label": "基礎類型",
            "choices": [
                {"value": "soil", "label": "土層（合力須在 1/3 中段）"},
                {"value": "rock", "label": "岩盤（合力須在 1/2 中段）"},
            ],
        },
        "site_condition": {
            "type": "select",
            "label": "設置位置",
            "choices": [
                {"value": "cut", "label": "開挖坡面（有效高 ≤ 4.0 m）"},
                {"value": "fill", "label": "填方坡面（有效高 ≤ 2.0 m）"},
            ],
        },
        "course_count": {"type": "number", "step": 1, "label": "層數（籠數）",
                         "hint": "總高＝層數×每層高；有效高＝總高－埋入深度，由後端依 §118 檢核"},
        "course_height_m": {
            "type": "number", "step": 0.1, "label": "每層高 (m)",
            "max_by": "wall_type",
            "limits": {"crib": {"max": crib["max_layer_height_m"], "basis": crib["basis"]}},
            "hint": "蛇籠常用 0.5 或 1.0 m",
        },
        "base_width_m": {"type": "number", "step": 0.1, "label": "底層寬 (m)"},
        "width_decrement_m": {"type": "number", "step": 0.1, "label": "每層縮減寬 (m)"},
        "embedment_m": {"type": "number", "step": 0.1, "label": "埋入深度 (m)",
                        "hint": "§118：有效高指露出地面之高度；亦為牆趾被動土壓力的深度 D"},
        **_passive_field_rules(),
        "height_m": {
            "type": "number", "step": 0.1, "label": "牆總高 (m)",
            "max_by": "wall_type", "limits": masonry_limits,
        },
        "top_width_m": {"type": "number", "step": 0.05, "label": "頂寬 (m)"},
        "front_batter_ratio": {"type": "number", "step": 0.05, "label": "牆面坡度 1:n 的 n",
                               "hint": "§118 七：緩於 1:0.3，n ≥ 0.3"},
        "back_batter_ratio": {"type": "number", "step": 0.05, "label": "背面坡度 1:n 的 n",
                              "hint": "0＝背面鉛直；正值＝底部往後加寬"},
        "stone_length_m": {"type": "number", "step": 0.05, "label": "底層石材長徑 (m)",
                           "hint": "牆厚方向；乾砌 ×5、漿砌 ×6.5 須 ≥ 牆高"},
        "backfill_slope_deg": {"type": "number", "step": 1, "label": "背填土坡角 β (°)"},
        "surcharge_kpa": {"type": "number", "step": 1, "label": "上載 q (kPa)"},
    }


def _example_counterfort_wall() -> dict[str, Any]:
    return {
        "height_m": 8.0,
        "stem_thickness_m": 0.30,
        "base_width_m": 6.6,
        "base_thickness_m": 0.60,
        "toe_length_m": 1.98,
        "counterfort_spacing_m": 3.0,
        "counterfort_thickness_m": 0.40,
        "counterfort_top_width_m": 0.30,
        "front_soil_depth_m": 1.0,
        "include_passive": True,
        "passive_ratio": 1.0,
        "soil": {
            "gamma": 18.0,
            "phi_deg": 30.0,
            "backfill_slope_deg": 0.0,
            "surcharge_kpa": 0.0,
            "allowable_bearing_kpa": 300.0,
            "base_friction": 0.6,
            "foundation": "soil",
        },
        "concrete": {"fc_mpa": 21.0, "fy_mpa": 420.0, "cover_mm": 75.0},
        "kh": 0.15,
        "size": False,
    }


def _counterfort_field_rules() -> dict[str, Any]:
    import counterfort_wall as CW

    return {
        "height_m": {
            "type": "number", "step": 0.1, "label": "牆板高 (m)",
            "limit": {
                "max": CW.SPEC["max_effective_height_m"],
                "basis": CW.SPEC["basis"],
                "input_offset_by": "front_soil_depth_m",
                "offset_label": "前趾覆土深",
            },
        },
        "stem_thickness_m": {"type": "number", "step": 0.05, "label": "牆板厚 (m)"},
        "base_width_m": {"type": "number", "step": 0.1, "label": "底板寬 (m)"},
        "base_thickness_m": {"type": "number", "step": 0.05, "label": "底板厚 (m)"},
        "toe_length_m": {"type": "number", "step": 0.05, "label": "前趾長 (m)"},
        "counterfort_spacing_m": {"type": "number", "step": 0.1, "label": "扶壁中心距 (m)",
                                  "hint": "常用 0.3～0.6 倍牆高（約 2.5～3.5 m）"},
        "counterfort_thickness_m": {"type": "number", "step": 0.05, "label": "扶壁厚 (m)"},
        "counterfort_top_width_m": {"type": "number", "step": 0.05, "label": "扶壁頂寬 (m)",
                                    "hint": "0＝三角形扶壁"},
        "front_soil_depth_m": {"type": "number", "step": 0.1, "label": "前趾覆土深 (m)",
                               "hint": "§118：有效高＝牆板高－前趾覆土深；被動土壓力深度 D＝覆土深＋底板厚"},
        **_passive_field_rules(),
        "foundation": {
            "type": "select",
            "label": "基礎類型",
            "choices": [
                {"value": "soil", "label": "土層（合力須在 1/3 中段）"},
                {"value": "rock", "label": "岩盤（合力須在 1/2 中段）"},
            ],
        },
        "backfill_slope_deg": {"type": "number", "step": 1, "label": "背填土坡角 β (°)"},
        "surcharge_kpa": {"type": "number", "step": 1, "label": "上載 q (kPa)"},
        "size": {"label": "依牆高自動反推斷面（忽略上面的斷面尺寸）"},
    }


def _example_mse_wall() -> dict[str, Any]:
    return {
        "height_m": 6.0,
        "embedment_m": 0.6,
        "reinforcement_type": "geogrid",
        "reinforcement_length_m": 5.4,
        "vertical_spacing_m": 0.6,
        "first_layer_m": 0.3,
        "long_term_strength_kN_per_m": 40.0,
        "coverage_ratio": 1.0,
        "include_passive": False,
        "passive_ratio": 1.0,
        "soil": {
            "reinforced_gamma": 19.0,
            "reinforced_phi_deg": 34.0,
            "retained_gamma": 18.0,
            "retained_phi_deg": 30.0,
            "foundation_phi_deg": 30.0,
            "foundation_gamma": 18.0,
            "backfill_slope_deg": 0.0,
            "surcharge_kpa": 10.0,
            "allowable_bearing_kpa": 300.0,
            "foundation": "soil",
        },
        "kh": 0.15,
    }


def _mse_field_rules() -> dict[str, Any]:
    import mse_wall as MW

    return {
        "height_m": {
            "type": "number", "step": 0.1, "label": "牆高 (m)",
            "limit": {
                "max": MW.SPEC["max_effective_height_m"],
                "basis": MW.SPEC["basis"],
                "input_offset_by": "embedment_m",
                "offset_label": "埋入深度",
            },
        },
        "embedment_m": {"type": "number", "step": 0.1, "label": "埋入深度 (m)",
                        "hint": "§118：有效高＝牆高－埋入深度；亦為牆趾被動土壓力的深度 D"},
        **_passive_field_rules("FHWA 簡化法外部滑動通常不計被動土壓力，故預設不勾選"),
        "foundation_gamma": {"type": "number", "step": 0.5, "label": "牆趾覆土單位重 γ (kN/m³)"},
        "reinforcement_type": {
            "type": "select",
            "label": "加勁材種類",
            "choices": [{"value": k, "label": v["label"]} for k, v in MW.REINFORCEMENT_TYPES.items()],
        },
        "reinforcement_length_m": {"type": "number", "step": 0.1, "label": "加勁長度 L (m)",
                                   "hint": "FHWA：L ≥ 0.7H 且 ≥ 2.4 m"},
        "vertical_spacing_m": {"type": "number", "step": 0.05, "label": "垂直間距 Sv (m)",
                               "hint": "一般 0.3～0.8 m；> 1.0 m 會被擋下"},
        "first_layer_m": {"type": "number", "step": 0.05, "label": "最下層高程 (m)"},
        "long_term_strength_kN_per_m": {"type": "number", "step": 1, "label": "長期設計強度 Tal (kN/m)",
                                        "hint": "已扣潛變、施工損傷、耐久性折減"},
        "coverage_ratio": {"type": "number", "step": 0.05, "label": "覆蓋率 Rc",
                           "hint": "滿鋪＝1.0；條帶＝帶寬／水平間距"},
        "foundation": {
            "type": "select",
            "label": "基礎類型",
            "choices": [
                {"value": "soil", "label": "土層（e ≤ L/6）"},
                {"value": "rock", "label": "岩盤（e ≤ L/4）"},
            ],
        },
        "surcharge_kpa": {"type": "number", "step": 1, "label": "上載 q (kPa)"},
        "backfill_slope_deg": {"type": "number", "step": 1, "label": "背填土坡角 β (°)"},
    }


def _example_anchored_wall() -> dict[str, Any]:
    return {
        "height_m": 7.0,
        "wall_thickness_m": 0.40,
        "base_width_m": 1.2,
        "base_thickness_m": 0.5,
        "front_soil_depth_m": 1.0,
        "anchor_depths_m": [1.5, 3.5, 5.5],
        "horizontal_spacing_m": 2.5,
        "inclination_deg": 20.0,
        "service": "permanent",
        "strand_type": "12.7",
        "strands": 4,
        "free_length_m": 7.0,
        "bond_length_m": 6.0,
        "drill_diameter_mm": 135.0,
        "bearing_plate_m": 0.30,
        "lockoff_factor": 1.15,
        "pressure_distribution": "apparent",
        "soil": {
            "gamma": 19.0,
            "phi_deg": 30.0,
            "backfill_slope_deg": 0.0,
            "surcharge_kpa": 10.0,
            "allowable_bearing_kpa": 300.0,
            "base_friction": 0.55,
            "bond_strength_kpa": 400.0,
            "tendon_bond_mpa": 2.0,
            "include_passive": True,
            "passive_ratio": 0.5,
        },
        "kh": 0.15,
    }


def _anchored_field_rules() -> dict[str, Any]:
    import anchored_wall as AW

    return {
        "height_m": {"type": "number", "step": 0.1, "label": "牆高 H (m)",
                     "hint": "§118 八未訂高度上限；適用岩層破碎、節理發達、崩塌或地滑地區"},
        "wall_thickness_m": {"type": "number", "step": 0.05, "label": "牆面厚 (m)"},
        "base_width_m": {"type": "number", "step": 0.1, "label": "基腳寬 (m)"},
        "base_thickness_m": {"type": "number", "step": 0.05, "label": "基腳厚 (m)"},
        "front_soil_depth_m": {"type": "number", "step": 0.1, "label": "牆前覆土深 (m)",
                               "hint": "有效高＝牆高－覆土深；亦為牆趾被動土壓力的深度 D（自基底起算）"},
        "anchor_depths_m": {"label": "各排地錨深度 (m，自牆頂)",
                            "hint": "逗號分隔，例 1.5, 3.5, 5.5；至少一排"},
        "horizontal_spacing_m": {"type": "number", "step": 0.1, "label": "地錨水平間距 (m)",
                                 "hint": "< 1.5 m 須檢討群錨效應"},
        "inclination_deg": {"type": "number", "step": 1, "label": "地錨俯角 α (°)",
                            "hint": "常用 10～45°"},
        "service": {
            "type": "select",
            "label": "地錨類別",
            "choices": [
                {"value": k, "label": "%s：FS %.1f／%.1f／%.1f" % (v["label"], v["tendon"], v["ground_grout"],
                                                                v["tendon_grout"])}
                for k, v in AW.ANCHOR_FS.items()
            ],
        },
        "strand_type": {
            "type": "select",
            "label": "鋼絞線規格",
            "choices": [{"value": k, "label": "%s（Pu %.0f kN／股）" % (v["label"], v["Pu_kN"])}
                        for k, v in AW.STRANDS.items()],
        },
        "strands": {"type": "number", "step": 1, "label": "每支股數"},
        "free_length_m": {"type": "number", "step": 0.5, "label": "自由段長 (m)",
                          "hint": "公路邊坡 C6.7：須穿過滑動面，原則 ≥ 4 m"},
        "bond_length_m": {"type": "number", "step": 0.5, "label": "錨碇段長 (m)",
                          "hint": "C6.7：≥ 3 m，一般 3～10 m"},
        "drill_diameter_mm": {"type": "number", "step": 5, "label": "鑽孔徑 (mm)"},
        "bearing_plate_m": {"type": "number", "step": 0.05, "label": "承壓鈑邊長 (m)"},
        "lockoff_factor": {"type": "number", "step": 0.05, "label": "鎖定荷重／設計荷重",
                           "hint": "C6.11：通常 1.10～1.20"},
        "pressure_distribution": {
            "type": "select",
            "label": "土壓分佈",
            "choices": [
                {"value": "apparent", "label": "FHWA 視土壓包絡（梯形，總力 0.65KaγH²）"},
                {"value": "triangular", "label": "三角形 Rankine（剛性牆面、岩盤）"},
            ],
        },
        "bond_strength_kpa": {
            "type": "number_with_presets",
            "label": "地層-漿體極限握裹 τ (kPa)",
            "step": 10,
            "hint": "參考值，須以證明試驗確認（公路邊坡 C6.4、C6.7）",
            "choices": AW.BOND_PRESETS,
        },
        "tendon_bond_mpa": {"type": "number", "step": 0.1, "label": "抗張材-漿體極限握裹 (MPa)",
                            "hint": "水泥漿常用 2.0；特殊材料須試驗"},
        **_passive_field_rules("預設 0.5：地錨牆位移小，只取一半被動抵抗"),
        "surcharge_kpa": {"type": "number", "step": 1, "label": "上載 q (kPa)"},
        "backfill_slope_deg": {"type": "number", "step": 1, "label": "背填土坡角 β (°)"},
    }


def _example_box_culvert() -> dict[str, Any]:
    return {
        "cell_count": 3,
        "clear_width_m": 3.0,
        "clear_height_m": 2.5,
        "wall_thickness_m": 0.35,
        "interior_wall_thickness_m": 0.30,
        "top_slab_thickness_m": 0.40,
        "bottom_slab_thickness_m": 0.45,
        "cover_depth_m": 0.60,
        "length_m": 20.0,
        "design_flow_m3s": 5.0,
        "slope": 0.005,
        "manning_n": 0.014,
        "inlet_type": "wingwall_30_75",
        "tailwater_depth_m": 1.0,
        "allowable_headwater_m": 3.0,
    }


def _box_culvert_field_rules() -> dict[str, Any]:
    try:
        import culvert_hydraulics as CH

        choices = [
            {"value": key, "label": spec["label"]}
            for key, spec in CH.INLET_TYPES.items()
        ]
    except Exception:  # pragma: no cover - 只在引擎匯入失敗時退化
        choices = [{"value": "wingwall_30_75", "label": "翼牆張角 30°～75°"}]
    return {
        "inlet_type": {
            "type": "select",
            "label": "進口型式（決定 Ke 與進口控制曲線）",
            "choices": choices,
            "hint": (
                "公路排水設計規範附錄 N（HDS-5 2005）。選 30°～75° 翼牆時 Ke=0.4、"
                "90°/15° 時 0.5、平行翼牆 0.7、斜切邊 0.2（表 O-1）。"
            ),
        },
        "tailwater_depth_m": {
            "type": "number",
            "label": "下游水深 TW（涵底起算）",
            "step": 0.05,
            "hint": "§6.2.2：TW 高過涵頂取 TW，否則取 max(TW, (dc+D)/2)。",
        },
        "allowable_headwater_m": {
            "type": "number",
            "label": "最高容許上游水深 HW",
            "step": 0.05,
            "hint": "§6.2.1 第1項。由路堤容許浸水高度與上游迴水影響決定，不是規範定值。",
        },
        "manning_n": {
            "type": "number",
            "label": "曼寧 n",
            "step": 0.001,
            "hint": "RC 箱涵常用 0.012～0.015；出水口摩擦損失與正常水深共用此值。",
        },
        "cell_count": {
            "type": "select",
            "label": "孔數",
            "choices": [
                {"value": 1, "label": "單孔"},
                {"value": 2, "label": "雙孔"},
                {"value": 3, "label": "三孔"},
            ],
            "hint": "公路排水設計規範 §6；多孔箱涵以內牆分隔。",
        },
    }


def _example_channel() -> dict[str, Any]:
    return {
        "design_flow_m3s": 0.3937,
        "inner_width_m": 0.40,
        "depth_m": 0.90,
        "slope": 0.005,
        "manning_n": 0.014,
    }


def _example_channel_profile() -> dict[str, Any]:
    return {
        "design_flow_m3s": 0.3937,
        "bottom_width_m": 0.40,
        "side_slope_h_v": 0.0,
        "slope": 0.005,
        "manning_n": 0.014,
        "reach_length_m": 100.0,
        "step_m": 20.0,
        "control_depth_m": 0.62,
        "channel_depth_m": 0.90,
        "freeboard_min_m": 0.20,
        "velocity_min_m_s": 0.8,
        "velocity_max_m_s": 12.0,
    }


def _example_network() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "A", "inflow_m3s": 1.0},
            {"id": "B", "inflow_m3s": 0.5},
            {"id": "C"},
        ],
        "links": [
            {
                "id": "L1",
                "from": "A",
                "to": "C",
                "type": "channel",
                "inner_width_m": 1.0,
                "depth_m": 1.0,
                "slope": 0.004,
                "manning_n": 0.014,
            },
            {
                "id": "L2",
                "from": "B",
                "to": "C",
                "type": "fixed",
                "capacity_m3s": 2.0,
            },
        ],
    }


def _example_basin() -> dict[str, Any]:
    return {
        "basin": {
            "bottom_length_m": 10.0,
            "bottom_width_m": 10.0,
            "side_slope_h_v": 2.0,
            "max_stage_m": 2.0,
            "stage_step_m": 0.10,
            "dam_crest_m": 2.0,
            "freeboard_min_m": 0.20,
        },
        "outlet": {
            "orifice": {
                "diameter_m": 0.20,
                "invert_m": 0.0,
                "discharge_coefficient": 0.62,
            }
        },
        "inflow": {
            "peak_m3s": 1.0,
            "time_to_peak_min": 5.0,
            "duration_min": 10.0,
            "time_step_min": 1.0,
        },
        "allowable_outflow_m3s": 1.0,
    }


def _example_building() -> dict[str, Any]:
    return {
        "geometry": {
            "x_grid_m": [0.0, 6.0, 12.0],
            "storey_heights_m": [3.5, 3.5, 3.5],
            "beam_width_mm": 300.0,
            "beam_depth_mm": 650.0,
            "column_width_mm": 450.0,
            "column_depth_mm": 450.0,
            "support": "fixed",
        },
        "loads": {
            "dead_area_kn_m2": 5.0,
            "live_area_kn_m2": 2.0,
            "base_shear_coefficient": 0.12,
        },
    }


def _building_field_rules() -> dict[str, Any]:
    return {
        "geometry.support": {
            "type": "select",
            "label": "柱腳支承條件",
            "choices": [
                {"value": "fixed", "label": "固接（剛性基礎，一般基腳／筏基）"},
                {"value": "pinned", "label": "鉸接（容許轉動，需另行檢核）"},
            ],
            "hint": "支承條件會改變側移與柱底彎矩；只有 fixed／pinned 兩種，引擎不接受其他字串。",
        },
    }


def _example_footing(kind: str) -> dict[str, Any]:
    settlement = {
        "foundation_type": "rc_isolated_or_combined",
        "layers": [
            {
                "thickness_m": 2.0,
                "elastic_modulus_kpa": 12000.0,
                "poisson_ratio": 0.30,
            },
            {
                "thickness_m": 4.0,
                "constrained_modulus_kpa": 18000.0,
            },
        ],
    }
    if kind == "combined":
        return {
            "columns": [
                {"x_m": 0.5, "P_kN": 500.0},
                {"x_m": 3.5, "P_kN": 700.0},
            ],
            "B_m": 2.75,
            "L_m": 4.0,
            "thickness_m": 0.70,
            "q_allow_kpa": 200.0,
            "settlement": settlement,
        }
    if kind == "pile":
        return {
            "piles": [
                {"x_m": -1.0, "y_m": -1.0},
                {"x_m": 1.0, "y_m": -1.0},
                {"x_m": -1.0, "y_m": 1.0},
                {"x_m": 1.0, "y_m": 1.0},
            ],
            "P_kN": 2000.0,
            "Mx_kNm": 0.0,
            "My_kNm": 0.0,
            "Q_allow_kN": 600.0,
        }
    return {
        "load": {"P_kN": 1000.0, "Mx_kNm": 100.0, "My_kNm": 50.0},
        "geometry": {
            "B_m": 2.5,
            "L_m": 2.5,
            "thickness_m": 0.60,
            "column_b_m": 0.45,
            "column_l_m": 0.45,
        },
        "q_allow_kpa": 300.0,
        "settlement": settlement,
    }


def _example_settlement_assessment() -> dict[str, Any]:
    settlement_layers = {
        "immediate_layers": [
            {
                "thickness_m": 2.0,
                "constrained_modulus_kpa": 15000.0,
            },
            {
                "thickness_m": 3.0,
                "constrained_modulus_kpa": 20000.0,
            },
        ],
        "consolidation_layers": [
            {
                "thickness_m": 3.0,
                "initial_effective_stress_kpa": 80.0,
                "compression_index": 0.24,
                "recompression_index": 0.05,
                "preconsolidation_stress_kpa": 140.0,
                "void_ratio": 0.90,
                "secondary_compression_index": 0.002,
                "consolidation_start_year": 1.0,
                "assessment_end_year": 30.0,
            }
        ],
    }
    footings = []
    for footing_id, x_m, y_m, q_kpa in (
        ("F1", 0.0, 0.0, 130.0),
        ("F2", 6.0, 0.0, 145.0),
        ("F3", 0.0, 6.0, 160.0),
        ("F4", 6.0, 6.0, 150.0),
    ):
        footings.append(
            {
                "id": footing_id,
                "x_m": x_m,
                "y_m": y_m,
                "q_kpa": q_kpa,
                "B_m": 2.2,
                "L_m": 2.2,
                **{
                    key: [dict(row) for row in value]
                    for key, value in settlement_layers.items()
                },
            }
        )
    return {
        "default_foundation_type": "rc_isolated_or_combined",
        "angular_distortion_limit": 0.002,
        "footings": footings,
    }


def _foundation_type_choices() -> list[dict[str, Any]]:
    import foundation_design as FD

    labels = {
        "plain_concrete_continuous": "混凝土連續基腳",
        "rc_isolated_or_combined": "RC 獨立／聯合基腳",
        "rc_continuous": "RC 連續基腳",
        "rc_raft": "RC 筏式基礎",
    }
    return [
        {
            "value": key,
            "label": "%s（總沉陷上限 %g mm）" % (labels.get(key, key), limit),
        }
        for key, limit in FD.SETTLEMENT_LIMITS_MM.items()
    ]


def _foundation_type_rule(label: str = "基礎型式") -> dict[str, Any]:
    return {
        "type": "select",
        "label": label,
        "choices": _foundation_type_choices(),
        "hint": (
            "建築物基礎構造設計規範 §4.5.4：總沉陷容許值依基礎型式而定；"
            "逐棟未指定時採預設值。"
        ),
    }


def _foundation_field_rules() -> dict[str, Any]:
    return {
        "foundation_type": _foundation_type_rule(),
        "settlement.foundation_type": _foundation_type_rule(),
        "settlement.layers[].thickness_m": {
            "type": "number",
            "step": 0.1,
            "label": "土層厚 (m)",
        },
        "settlement.layers[].elastic_modulus_kpa": {
            "type": "number",
            "step": 500.0,
            "label": "彈性模數 E (kPa)",
        },
        "settlement.layers[].constrained_modulus_kpa": {
            "type": "number",
            "step": 500.0,
            "label": "受圍束壓縮模數 (kPa)",
        },
        "settlement.layers[].poisson_ratio": {
            "type": "number",
            "step": 0.01,
            "label": "柏松比 ν",
        },
    }


def _settlement_field_rules() -> dict[str, Any]:
    rules = _foundation_field_rules()
    rules["default_foundation_type"] = _foundation_type_rule(
        "預設基礎型式（未逐棟指定時採用）"
    )
    rules["footings[].foundation_type"] = _foundation_type_rule(
        "基礎型式（逐棟，可留空）"
    )
    rules["angular_distortion_limit"] = {
        "type": "number",
        "step": 0.0001,
        "label": "角變量上限 δ/L",
        "hint": "預設 0.002＝1/500（§4.5.4 裂縫安全限度）",
    }
    return rules


def _channel_field_rules() -> dict[str, Any]:
    # 水保技術規範 §84 只規定曼寧公式，未固定 n 值；§85 則以材料區分
    # 容許流速。這裡提供常用材料範圍作輸入輔助，數值仍可自由修改。
    return {
        "manning_n": {
            "type": "number_with_presets",
            "label": "曼寧粗糙係數 n",
            "step": 0.001,
            "hint": (
                "水保技術規範 §84 僅規定曼寧公式，未固定 n 值；"
                "下拉選單是材料常用範圍，選取後仍可直接輸入自訂 n。"
            ),
            "choices": [
                {
                    "value": 0.014,
                    "label": "混凝土／RC（常用 0.013～0.016）",
                },
                {
                    "value": 0.011,
                    "label": "塑膠／HDPE 管（常用 0.010～0.013）",
                },
                {
                    "value": 0.014,
                    "label": "漿砌塊卵石（抹面，常用 0.014～0.018）",
                },
                {
                    "value": 0.025,
                    "label": "漿砌塊卵石（未抹面，常用 0.020～0.030）",
                },
                {
                    "value": 0.030,
                    "label": "乾砌塊卵石（常用 0.025～0.035）",
                },
                {
                    "value": 0.035,
                    "label": "草溝／土溝（常用 0.025～0.080）",
                },
            ],
        }
    }


def _channel_profile_field_rules() -> dict[str, Any]:
    rules = _channel_field_rules()
    rules["bottom_width_m"] = {
        "type": "number",
        "label": "渠底寬 (m)",
        "step": 0.05,
        "hint": "矩形溝側坡填 0；梯形溝另填側坡 H:V。",
    }
    rules["control_depth_m"] = {
        "type": "number",
        "label": "下游控制水深 (m)",
        "step": 0.01,
        "hint": "留空＝下游自由出流，取臨界水深；已知下游水位（如匯流處）就填實測水深。",
    }
    rules["reach_length_m"] = {
        "type": "number",
        "label": "演算長度 (m)",
        "step": 1.0,
        "hint": "由下游控制斷面往上游算的長度。",
    }
    return rules


def _hydrology_field_rules() -> dict[str, Any]:
    import hydrology as HY

    conditions = [
        {"value": key, "label": key}
        for key in HY.RUNOFF_C["無開發整地區"]
    ]
    area_types = [
        {
            "value": key,
            "label": "%s（漫地流長度 ≤ %g m）" % (key, limit),
        }
        for key, limit in HY.SLOPE_LIMITS.items()
    ]
    return {
        "P_mm": {
            "type": "number",
            "step": 10.0,
            "label": "年平均降雨量 P (mm)",
            "hint": "水土保持技術規範 §16；應採當地測站值（台中一帶約 1,700～2,200 mm）。",
        },
        "return_period_yr": {
            "type": "number",
            "step": 1.0,
            "label": "重現期 T (年)",
            "hint": "第17條；一般小型工程 25 年，重要設施得提高。",
        },
        "area_ha": {
            "type": "number",
            "step": 0.01,
            "label": "集水區面積 A (ha)",
            "hint": "超過 1,000 ha 者第17條規定須採單位歷線分析。",
        },
        "condition": {
            "type": "select",
            "label": "地表條件（§18 逕流係數表）",
            "choices": conditions,
            "hint": "第18條只有這五類；勾選「開發整地區」後改用開發整地區係數。",
        },
        "developed": {
            "label": "開發整地區（整地後）",
            "hint": "第18條；未勾選時採無開發整地區係數。",
        },
        "upper_c": {
            "label": "逕流係數取上限（保守）",
            "hint": "未勾選時取表中下限。",
        },
        "area_type": {
            "type": "select",
            "label": "漫地流範圍",
            "choices": area_types,
            "hint": "第19條：開發坡面 100 m、集水區 300 m；超過部分併入流下時間。",
        },
        "l_m": {
            "type": "number",
            "step": 1.0,
            "label": "漫地流長度 l (m)",
            "hint": "不得超過所選漫地流範圍的上限。",
        },
        "v_ms": {
            "type": "number",
            "step": 0.01,
            "label": "漫地流流速 v (m/s)",
            "hint": "第19條規定 0.3～0.6 m/s。",
        },
        "L_km": {
            "type": "number",
            "step": 0.01,
            "label": "溪流長度 L (km)",
            "hint": "有天然河段才填；0＝只有漫地流。",
        },
        "H_km": {
            "type": "number",
            "step": 0.01,
            "label": "溪流高程差 H (km)",
            "hint": "芮哈公式 W = 72·(H/L)^0.6。",
        },
    }


def _sediment_field_rules() -> dict[str, Any]:
    return {
        "kind": {
            "type": "select",
            "label": "沉砂池性質",
            "choices": [
                {"value": "temporary", "label": "臨時性（§93 容量再 ×1.5）"},
                {"value": "permanent", "label": "永久性"},
            ],
            "hint": "第92條臨時性打 1/2 並套下限，第93條再乘 1.5。",
        },
        "area_ha": {"type": "number", "step": 0.01, "label": "集水區面積 (ha)"},
        "excavated_ha": {
            "type": "number",
            "step": 0.01,
            "label": "開挖整地面積 (ha)",
            "hint": "無開挖整地填 0。",
        },
        "impervious_ha": {
            "type": "number",
            "step": 0.01,
            "label": "不透水面積 (ha)",
        },
        "years": {
            "type": "number",
            "step": 0.5,
            "label": "年期 (年)",
            "hint": "第92條未定年期，報告須寫明採用值。",
        },
        "Am": {
            "type": "number",
            "step": 1.0,
            "label": "土壤流失量 Am (t/ha/yr)",
            "hint": "未填時採引擎預設；應以當地 USLE 參數計算。",
        },
        "depth_m": {
            "type": "number",
            "step": 0.1,
            "label": "池深 (m)",
            "hint": "第93條 1.5～3.5 m。",
        },
    }


def _slope_field_rules() -> dict[str, Any]:
    return {
        "stage": {
            "type": "select",
            "label": "設計階段",
            "choices": [
                {"value": "永久性", "label": "永久性（平時 1.5／地震 1.1／暴雨 1.2）"},
                {"value": "臨時性", "label": "臨時性（平時 1.2／地震 1.0／暴雨 1.1）"},
            ],
            "hint": "水土保持技術規範 §73 最小安全係數表。",
        },
        "condition": {
            "type": "select",
            "label": "工況",
            "choices": [
                {"value": "平時", "label": "平時"},
                {"value": "地震", "label": "地震"},
                {"value": "暴雨", "label": "暴雨"},
            ],
            "hint": "需求 FS 依設計階段與工況查表。",
        },
        "height_m": {"type": "number", "step": 0.1, "label": "坡高 H (m)"},
        "slope_angle_deg": {
            "type": "number",
            "step": 0.5,
            "label": "坡角 β (°)",
            "hint": "水平面起算。",
        },
        "cohesion_kpa": {
            "type": "number",
            "step": 0.5,
            "label": "凝聚力 c (kPa)",
            "hint": "須以鑽探報告替換；無凝聚性土壤填 0。",
        },
        "friction_deg": {
            "type": "number",
            "step": 0.5,
            "label": "內摩擦角 φ (°)",
            "hint": "須以鑽探報告替換。",
        },
        "unit_weight_kn_m3": {
            "type": "number",
            "step": 0.5,
            "label": "土壤單位重 γ (kN/m³)",
        },
    }


def _network_field_rules() -> dict[str, Any]:
    rules = _channel_field_rules()
    rules.update(
        {
            "nodes[].id": {"label": "節點編號"},
            "nodes[].inflow_m3s": {
                "type": "number",
                "step": 0.01,
                "label": "節點入流 (m³/s)",
            },
            "links[].id": {"label": "連線編號"},
            "links[].from": {"label": "上游節點"},
            "links[].to": {"label": "下游節點"},
            "links[].type": {
                "type": "select",
                "label": "連線型式",
                "choices": [
                    {"value": "channel", "label": "明渠（內寬＋溝深＋縱坡）"},
                    {"value": "pipe", "label": "圓管（直徑＋最大滿水深比）"},
                    {"value": "box", "label": "箱涵（淨寬＋淨高＋版厚）"},
                    {"value": "fixed", "label": "指定容量（直接輸入容量）"},
                ],
                "hint": "依型式填對應欄位；新增列後請補齊該型式所需數值。",
            },
            "links[].inner_width_m": {
                "type": "number",
                "step": 0.05,
                "label": "內寬 (m)",
            },
            "links[].depth_m": {"type": "number", "step": 0.05, "label": "溝深 (m)"},
            "links[].slope": {"type": "number", "step": 0.0001, "label": "縱坡 S"},
            "links[].diameter_m": {
                "type": "number",
                "step": 0.05,
                "label": "管徑 (m)",
            },
            "links[].max_fill_ratio": {
                "type": "number",
                "step": 0.05,
                "label": "最大滿水深比",
                "hint": "須小於 1.0，常用 0.75。",
            },
            "links[].cell_count": {
                "type": "select",
                "label": "箱涵孔數",
                "choices": [
                    {"value": 1, "label": "單孔"},
                    {"value": 2, "label": "雙孔"},
                    {"value": 3, "label": "三孔"},
                ],
            },
            "links[].clear_width_m": {
                "type": "number",
                "step": 0.05,
                "label": "箱涵淨寬 (m)",
            },
            "links[].clear_height_m": {
                "type": "number",
                "step": 0.05,
                "label": "箱涵淨高 (m)",
            },
            "links[].wall_thickness_m": {
                "type": "number",
                "step": 0.05,
                "label": "外牆厚 (m)",
            },
            "links[].interior_wall_thickness_m": {
                "type": "number",
                "step": 0.05,
                "label": "內牆厚 (m)",
            },
            "links[].top_slab_thickness_m": {
                "type": "number",
                "step": 0.05,
                "label": "頂版厚 (m)",
            },
            "links[].bottom_slab_thickness_m": {
                "type": "number",
                "step": 0.05,
                "label": "底版厚 (m)",
            },
            "links[].capacity_m3s": {
                "type": "number",
                "step": 0.1,
                "label": "指定容量 (m³/s)",
            },
        }
    )
    return rules


def _example_channel_cover() -> dict[str, Any]:
    import channel_cover as CC

    return CC.example_payload()


def _channel_cover_field_rules() -> dict[str, Any]:
    rules: dict[str, Any] = {
        "geometry": {"label": "幾何"},
        "materials": {"label": "材料"},
        "loads": {"label": "載重"},
        "slab": {"label": "配筋指定（空白＝自動）"},
        "connection": {"label": "植筋連接"},
        "geometry.clear_width_m": {
            "type": "number", "step": 0.05, "label": "淨溝寬 (m)",
            "hint": "溝壁內側淨寬；本案例 0.60 m",
        },
        "geometry.wall_thickness_m": {
            "type": "number", "step": 0.05, "label": "溝壁厚 (m)",
            "hint": "兩側各 0.20 m；植筋邊距由此決定",
        },
        "geometry.slab_thickness_mm": {
            "type": "number", "step": 25.0, "label": "溝蓋版厚 (mm)",
            "hint": "留空＝由 200 mm 起自動搜尋至 400 mm",
        },
        "geometry.cover_mm": {
            "type": "number", "step": 5.0, "label": "鋼筋保護層 (mm)",
            "hint": "橋梁規範表 7.2：橋板頂層 50 mm；本工具頂底同取 50 mm",
        },
        "geometry.bearing_length_min_mm": {
            "type": "number", "step": 5.0, "label": "最小支承長度 (mm)",
            "hint": "版端擱在溝壁頂的長度下限，預設 75 mm",
        },
        "materials.slab_fc_mpa": {
            "type": "number", "step": 1.0, "label": "溝蓋 fc′ (MPa)",
            "hint": "280 kgf/cm² ≈ 27.5 MPa；本工具預設 28 MPa",
        },
        "materials.wall_fc_mpa": {
            "type": "number", "step": 1.0, "label": "既有溝壁 fc′ (MPa)",
            "hint": "未知時取 21 MPa（約 210 kgf/cm²），須鑽心或回彈確認",
        },
        "materials.fy_mpa": {
            "type": "number", "step": 10.0, "label": "鋼筋 fy (MPa)",
        },
        "materials.unit_weight_kn_m3": {
            "type": "number", "step": 0.5, "label": "混凝土單位重 (kN/m³)",
        },
        "loads.live_load_factor": {
            "type": "number", "step": 0.01, "label": "活載重因數 β",
            "hint": "一般 1.67；依公路橋梁規範 4.3.2，特定橋面板情況得用 1.0",
        },
        "loads.wearing_surface_kpa": {
            "type": "number", "step": 0.5, "label": "磨耗層／鋪面 (kPa)",
            "hint": "溝蓋上若有 AC，22 kN/m³ × 厚度；無則 0",
        },
        "loads.uplift_factor": {
            "type": "number", "step": 0.01, "label": "抗掀比例（輪載倍數）",
            "hint": "非規範明文；預設 0.10，僅供植筋抗掀配置",
        },
        "loads.horizontal_force_kN_m": {
            "type": "number", "step": 1.0, "label": "水平力（溫度／制動）(kN/m)",
            "hint": "垂直剪力由承壓傳遞；此值才由植筋抗剪",
        },
        "connection.fixity_ratio": {
            "type": "number", "step": 0.05, "label": "部分固接負彎矩比",
            "hint": "僅 model=partial_fixity 時使用；0.5 表示負彎矩取正彎矩 50%",
        },
        "connection.spacing_mm": {
            "type": "number", "step": 25.0, "label": "植筋間距 (mm)",
            "hint": "每側沿溝方向；不得小於 6db",
        },
        "connection.embedment_mm": {
            "type": "number", "step": 10.0, "label": "植筋埋深 hef (mm)",
            "hint": "預設 min(15db, 200 mm)；不得超過溝壁厚度",
        },
        "connection.tau_cr_kgf_cm2": {
            "type": "number", "step": 1.0, "label": "開裂 τcr (kgf/cm²)",
            "hint": "表17.6.5.2.5 室外乾燥至飽和＝14；室內乾燥＝21",
        },
        "connection.tau_uncr_kgf_cm2": {
            "type": "number", "step": 1.0, "label": "未開裂 τuncr (kgf/cm²)",
            "hint": "表17.6.5.2.5 室外＝45；室內＝70",
        },
    }
    rules.update(
        {
            "loads.vehicle": {
                "type": "select",
                "label": "車載標準",
                "choices": [
                    {"value": "hs20", "label": "HS20-44（後輪 7,300 kgf）"},
                    {"value": "hs20_1_25", "label": "HS20-44 × 1.25（省市重要道路／重型貨車）"},
                ],
            },
            "loads.deck_beta_1_0": {
                "type": "boolean",
                "label": "橋面板 β 用 1.0（公路橋梁規範 4.3.2）",
            },
            "connection.model": {
                "type": "select",
                "label": "溝蓋支承模型",
                "choices": [
                    {"value": "simple", "label": "簡支版（建議；植筋只抗掀與水平力）"},
                    {"value": "partial_fixity", "label": "部分固接（負彎矩由頂筋與植筋承擔）"},
                ],
            },
            "connection.bar": {
                "type": "select",
                "label": "植筋直徑",
                "choices": [
                    {"value": "D13", "label": "D13（邊距需求 78 mm）"},
                    {"value": "D16", "label": "D16（邊距需求 96 mm；20 cm 壁厚的上限）"},
                ],
            },
            "connection.cracked": {
                "type": "boolean",
                "label": "採開裂混凝土 τcr（保守；未勾選則用 τuncr）",
            },
            "connection.surface_condition": {
                "type": "select",
                "label": "新舊混凝土界面",
                "choices": [
                    {"value": "roughened", "label": "打毛至約 6 mm（μ＝1.0）"},
                    {"value": "smooth", "label": "未打毛（μ＝0.6）"},
                ],
            },
            "slab.main_bar": {
                "type": "select",
                "label": "主筋號數",
                "choices": [
                    {"value": "", "label": "自動設計"},
                    {"value": "D13", "label": "D13"},
                    {"value": "D16", "label": "D16"},
                    {"value": "D19", "label": "D19"},
                    {"value": "D22", "label": "D22"},
                    {"value": "D25", "label": "D25"},
                    {"value": "D29", "label": "D29"},
                ],
            },
            "slab.main_spacing_mm": {
                "type": "number", "step": 5.0, "label": "主筋間距 (mm)",
                "hint": "0＝自動；指定號數時須同時填間距（db+25～3h／450 mm）",
            },
            "slab.dist_bar": {
                "type": "select",
                "label": "分佈筋（副筋）號數",
                "choices": [
                    {"value": "", "label": "自動設計"},
                    {"value": "D10", "label": "D10"},
                    {"value": "D13", "label": "D13"},
                    {"value": "D16", "label": "D16"},
                    {"value": "D19", "label": "D19"},
                    {"value": "D22", "label": "D22"},
                    {"value": "D25", "label": "D25"},
                    {"value": "D29", "label": "D29"},
                ],
            },
            "slab.dist_spacing_mm": {
                "type": "number", "step": 5.0, "label": "分佈筋間距 (mm)",
                "hint": "0＝自動；指定號數時須同時填間距",
            },
        }
    )
    return rules


def _example_steel_column() -> dict[str, Any]:
    import steel_column as SC

    return SC.example_payload("lrfd")


def _steel_column_field_rules() -> dict[str, Any]:
    import steel_column as SC

    numeric_labels = {
        "column.section.h_mm": "斷面高 h (mm)",
        "column.section.b_mm": "斷面寬 b (mm)",
        "column.section.tw_mm": "腹板厚 tw (mm)",
        "column.section.tf_mm": "翼板厚 tf (mm)",
        "column.fy_mpa": "鋼材屈服強度 fy (MPa)",
        "column.Fu_mpa": "鋼材極限強度 Fu (MPa)",
        "column.E_mpa": "鋼材彈性模數 E (MPa)",
        "column.length_m": "柱長 L (m)",
        "column.Kx": "有效長度係數 Kx（強軸）",
        "column.Ky": "有效長度係數 Ky（弱軸）",
        "column.Lb_m": "側向支撐間距 Lb（強軸彎曲） (m)",
        "column.Lb_y_m": "側向支撐間距 Lby（弱軸彎曲） (m)",
        "column.axial_P_kN": "軸力 P (kN，壓為正、拉為負)",
        "column.moment_Mx_kNm": "彎矩 Mx (kN·m)",
        "column.moment_My_kNm": "彎矩 My (kN·m)",
        "column.shear_Vx_kN": "剪力 Vx (kN)",
        "column.shear_Vy_kN": "剪力 Vy (kN)",
        "column.Cm_x": "Cm 係數（強軸）",
        "column.Cm_y": "Cm 係數（弱軸）",
        "column.M1_over_M2": "M1/M2 側向彎曲放大係數",
        "base_plate.plate_B_m": "基板長 B (m)",
        "base_plate.plate_N_m": "基板寬 N (m)",
        "base_plate.plate_t_mm": "基板厚 t (mm)",
        "base_plate.fc_mpa": "混凝土抗壓強度 fc′ (MPa)",
        "base_plate.pedestal_B_m": "承台長 (m)",
        "base_plate.pedestal_N_m": "承台寬 (m)",
        "base_plate.grout_above_concrete": "灌漿高出混凝土面 (m)",
        "base_plate.corrosion_allowance_mm": "腐蝕余裕 (mm)",
        "anchors.diameter_mm": "錨栓直徑 (mm)",
        "anchors.embedment_mm": "錨栓埋深 hef (mm)",
    }
    boolean_labels = {
        "column.rolled": "H 型鋼（軋製成型，取消勾選則依箱型／實腹板計算）",
        "column.cantilever": "懸臂柱（端部無側向支撐，Cb 取懸臂值）",
        "anchors.threads_in_shear_plane": "螺紋在剪力平面內",
    }
    rules: dict[str, Any] = {
        path: {"type": "number", "label": label}
        for path, label in numeric_labels.items()
    }
    for path, label in boolean_labels.items():
        rules[path] = {"type": "boolean", "label": label}
    rules.update({
        "design_method": {
            "type": "select",
            "label": "設計法（全案擇一）",
            "choices": [
                {"value": "lrfd", "label": "極限設計法（(二) 版，LRFD）"},
                {"value": "asd", "label": "容許應力設計法（(一) 版，ASD）"},
            ],
            "on_change": "rerender",
        },
        "base_plate.support_condition": {
            "type": "select",
            "label": "柱腳支承情況（決定摩擦係數 μ）",
            "choices": [
                {"value": key, "label": "%s（μ = %.2f）" % (spec["label"], spec["mu"])}
                for key, spec in SC.FRICTION_CASES.items()
            ],
        },
        "anchors.grade": {
            "type": "select",
            "label": "錨栓材質",
            "choices": [
                {
                    "value": key,
                    "label": spec["label"]
                    + ("" if spec.get("asd_Ft") else "（(一) 版表 10.3-2 無容許應力，僅供 (二) 版使用）"),
                }
                for key, spec in SC.BOLT_GRADES.items()
            ],
        },
        "anchors.shear_path": {
            "type": "select",
            "label": "剪力傳遞路徑（三者擇一）",
            "choices": [
                {"value": key, "label": value}
                for key, value in SC.SHEAR_PATHS.items()
            ],
        },
    })
    return rules


CATALOG: list[dict[str, Any]] = [
    {
        "id": "wall_stability",
        "group": "擋土牆",
        "title": "擋土牆穩定分析",
        "oral": ["擋土牆", "重力式", "懸臂式", "半重力式", "滑動", "傾倒"],
        "description": "重力式、懸臂式、半重力式的常時／地震穩定、合力位置與承載檢核。",
        "engine": "retaining_wall.py",
        "codes": ["水土保持技術規範 §119～121", "建築物基礎構造設計規範"],
        "limitations": "蛇籠、格籠、砌石、三明治式請用「疊式／砌石擋土牆」，扶壁式、加勁、錨定各有專用計算器；土層參數須用鑽探值替換預設值。",
        "field_rules": _wall_field_rules(),
        "example": _example_retaining_wall(),
    },
    {
        "id": "block_wall",
        "group": "擋土牆",
        "title": "疊式／砌石擋土牆",
        "oral": ["蛇籠", "箱籠", "格籠", "砌石", "漿砌", "乾砌", "卵石牆", "疊式擋土牆"],
        "description": "蛇籠（箱籠）、格籠、漿砌／乾砌石擋土牆；逐層界面與基底的滑動、傾倒、合力位置，基底承載，以及 §118 有效高、每層高、牆面坡度與石材長徑限制。",
        "engine": "block_wall.py",
        "codes": ["水土保持技術規範 §118～121"],
        "limitations": "牆趾抵抗力是否計入依「計入牆趾被動土壓力」設定，只計入抗滑；背填黏著力未計；視為透水牆不計靜水壓；網線、格籠構件強度未檢核；整體傾斜蛇籠與牆背懸於填土上的幾何尚未支援。",
        "field_rules": _block_wall_field_rules(),
        "example": _example_block_wall(),
    },
    {
        "id": "counterfort_wall",
        "group": "擋土牆",
        "title": "扶壁式擋土牆",
        "oral": ["扶壁", "扶壁式", "高擋土牆", "counterfort"],
        "description": "扶壁式擋土牆常時／地震穩定、合力位置與承載；牆板與踵板以扶壁為支承之連續版、趾板懸臂、扶壁 T 梁拉力筋與箍筋、牆板／踵板繫筋；可依牆高反推斷面。",
        "engine": "counterfort_wall.py",
        "codes": ["水土保持技術規範 §118 五、§119～121", "混凝土結構設計規範（100.06.09 版）"],
        "limitations": "牆板／踵板採連續版係數與 Huntington 簡化，非雙向版精算；牆趾抵抗力是否計入依「計入牆趾被動土壓力」設定，只計入抗滑；黏著力與地下水未計；載重組合採 100 年版慣例。",
        "field_rules": _counterfort_field_rules(),
        "example": _example_counterfort_wall(),
    },
    {
        "id": "mse_wall",
        "group": "擋土牆",
        "title": "加勁擋土牆",
        "oral": ["加勁", "加勁擋土牆", "加勁土壤", "土工格網", "格網", "MSE", "鋼條帶"],
        "description": "加勁土壤構造物外部穩定（滑動、傾倒、偏心、Meyerhof 承載，含地震）與逐層內部穩定（拉斷、拉出、錨定長度，含地震）；FHWA 簡化法。",
        "engine": "mse_wall.py",
        "codes": ["水土保持技術規範 §118 六(三)、§119～120", "FHWA-NHI-10-024"],
        "limitations": "面版、連接強度、複合滑動與整體圓弧滑動未檢核；F*、α 為保守預設值；未計靜水壓。",
        "field_rules": _mse_field_rules(),
        "example": _example_mse_wall(),
    },
    {
        "id": "anchored_wall",
        "group": "擋土牆",
        "title": "錨定擋土牆",
        "oral": ["錨定", "錨定擋土牆", "地錨", "背拉", "地錨擋土牆", "岩錨", "anchor"],
        "description": "地錨背拉 RC 牆面：視土壓包絡或三角形土壓、牆面連續梁支點反力；每排地錨抗張材、錨碇段長、自由段長、鎖定荷重、承壓鈑壓應力與沖剪；基底滑動與承載；牆面雙向配筋。",
        "engine": "anchored_wall.py",
        "codes": ["水土保持技術規範 §118 八、§119～120", "公路邊坡工程設計規範（104.12）第六章",
                  "混凝土結構設計規範（100.06.09 版）", "FHWA GEC-4"],
        "limitations": "整體（深層）穩定未檢核，須另做邊坡穩定分析；握裹強度須證明試驗確認；牆面為連續梁＋p·sh²/10 近似；黏土包絡、地下水與黏著力未計。",
        "field_rules": _anchored_field_rules(),
        "example": _example_anchored_wall(),
    },
    {
        "id": "box_culvert",
        "group": "箱涵",
        "title": "單孔／雙孔／三孔箱涵",
        "oral": ["箱涵", "單孔", "雙孔", "三孔", "涵洞", "覆土", "出水高", "進口控制", "出口控制", "頭水"],
        "description": "參數化箱涵平面剛架、土水壓與活載、RC 撓曲／剪力／軸彎互制、浮力，以及附錄 N／O 進口／出口控制水理。",
        "engine": "box_culvert.py",
        "codes": ["公路排水設計規範", "公路橋梁設計規範", "水土保持技術規範 §87", "建築物混凝土結構設計規範"],
        "limitations": "翼牆與端牆只檢核有輸入的幾何值（§6.5），不檢核沖刷深度；低水頭出口控制未做迴水曲線；尚無三維角隅、施工階段與正式配筋詳圖。",
        "field_rules": _box_culvert_field_rules(),
        "example": _example_box_culvert(),
    },
    {
        "id": "channel_hydraulics",
        "group": "排水系統",
        "title": "排水溝水力檢核／選配",
        "oral": ["排水溝", "渠道", "曼寧", "流速", "出水高", "通水容量"],
        "description": "矩形明渠正常水深、容量、流速、福祿數、出水高與最小斷面選配。",
        "engine": "channel_hydraulics.py",
        "codes": ["水土保持技術規範 §78", "水土保持技術規範 §83～86"],
        "limitations": "穩定等速流；迴水、漸變水面線、跌水消能與連接井損失需另案分析。",
        "field_rules": _channel_field_rules(),
        "example": _example_channel(),
    },
    {
        "id": "channel_profile",
        "group": "排水系統",
        "title": "排水溝水面線（迴水）",
        "oral": ["水面線", "迴水", "漸變水面線", "標準步法", "M1", "M2", "S2", "出水高檢核"],
        "description": "矩形／梯形渠道標準步法水面線：自由出流或指定下游控制水深，逐段向上游演算水深、流速、福祿數與剖面型態，並檢核出水高與容許流速。",
        "engine": "channel_profile.py",
        "codes": ["水土保持技術規範 §84～86", "公路排水設計規範第四章"],
        "limitations": "一維緩變流；不處理水躍、橋涵束縮、側流入流、彎道二次流與分段糙度變化；超臨界段僅供參考。",
        "field_rules": _channel_profile_field_rules(),
        "example": _example_channel_profile(),
    },
    {
        "id": "channel_cover",
        "group": "排水系統",
        "title": "RC 路側溝加蓋（溝蓋版＋植筋）",
        "oral": [
            "溝蓋", "加蓋", "暗溝", "路側溝加蓋", "溝蓋板", "明溝加蓋", "植筋",
            "溝蓋配筋", "溝蓋載重",
        ],
        "description": (
            "既有 RC 明溝加蓋：HS20-44 後輪載重（可乘重型貨車係數 1.25）下，"
            "溝蓋版撓曲、剪力、裂縫、撓度，溝壁頂承壓，以及黏結式植筋拉力、"
            "剪力與拉剪互制。"
        ),
        "engine": "channel_cover.py",
        "codes": [
            "公路橋梁設計規範（98.12 初版；104.04.13／109.01.03 修訂）§3.7.6、§4.3、§7.1.5、§9",
            "建築物混凝土結構設計規範（112.08.10）§17.6.5、§17.7、§17.9、§22.9",
            "公路工程施工規範（112.02.22）§01525 施工縫及植筋",
        ],
        "limitations": (
            "只做簡支版正彎矩，不把 20 cm 溝壁當固接支承；植筋拉力需求採抗掀名義比例"
            "（非規範明文）。未檢核既有溝壁側向穩定、基礎承載、疲勞、溫度與地震；"
            "植筋膠須有黏結式錨栓評估準則（ACI 355.4）認證並以產品資料覆核。"
        ),
        "field_rules": _channel_cover_field_rules(),
        "example": _example_channel_cover(),
    },
    {
        "id": "drainage_network",
        "group": "排水系統",
        "title": "排水網路流量分配",
        "oral": ["排水系統", "排水網路", "匯流", "分流", "管渠", "容量"],
        "description": "節點—連線網路、指定或容量權重分流、渠道／圓管／箱涵／指定容量檢核。",
        "engine": "drainage_network.py",
        "codes": ["水土保持技術規範 §82～87", "公路排水設計規範", "下水道工程設施標準"],
        "limitations": "目前為穩定尖峰流量平衡；尚無儲蓄、時間延遲、迴水與漸變水面線。",
        "field_rules": _network_field_rules(),
        "example": _example_network(),
    },
    {
        "id": "detention_basin",
        "group": "滯洪池",
        "title": "滯洪池調洪演算",
        "oral": ["滯洪池", "滯洪", "調洪", "Modified Puls", "容許出流", "溢洪道"],
        "description": "水位—面積—蓄水曲線、孔口／堰出流、Modified Puls 演算、最高水位與出水高。",
        "engine": "detention_basin.py",
        "codes": ["水土保持技術規範 §94～97", "水土保持技術規範 §160、§166"],
        "limitations": "孔口以中心水頭計算，水位低於孔口中心時出流以 0 計；尚無多峰雨型、閘門操作、下游迴水、池堤穩定與緊急溢洪道完整設計。",
        "example": _example_basin(),
        "field_rules": {
            "outlet.orifice.invert_m": {
                "label": "孔底高程 (m)",
                "hint": "自池底起算；孔口中心取孔底＋孔徑/2，以中心水頭計算出流",
            },
        },
    },
    {
        "id": "building_frame",
        "group": "建築結構",
        "title": "建築 RC 平面剛架",
        "oral": ["樑", "柱", "樑柱", "建築構架", "樓層", "地震", "層間位移"],
        "description": "規則 2D RC 剛架、靜載／活載／等值靜力地震、內力包絡、樑柱初步配筋與層間位移。",
        "engine": "building_frame.py",
        "codes": ["建築技術規則建築構造編", "建築物耐震設計規範", "建築物混凝土結構設計規範"],
        "limitations": "代表性 2D 平面、單軸彎矩；未計 3D 扭轉、雙向彎矩、二階效應、接頭剪力與錨定。",
        "field_rules": _building_field_rules(),
        "example": _example_building(),
    },
    {
        "id": "foundation_isolated",
        "group": "建築基礎",
        "title": "獨立基腳",
        "oral": ["獨立基腳", "基腳", "基礎承載", "沖剪", "柱腳", "淺基礎"],
        "description": "矩形獨立基腳承載應力、全面受壓、滑動、單向剪力、沖剪、撓曲與可選分層沉陷檢核。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範 §4", "建築物混凝土結構設計規範"],
        "limitations": "沉陷須提供土層參數；可分層 2:1 法估算瞬時沉陷，選填 consolidation_layers 時可加算壓密與次壓縮。單一基腳不計算差異沉陷或角變量，請另用 settlement_assessment；液化與土壤—結構互制未計。",
        "field_rules": _foundation_field_rules(),
        "example": _example_footing("isolated"),
    },
    {
        "id": "foundation_combined",
        "group": "建築基礎",
        "title": "聯合基腳",
        "oral": ["聯合基腳", "兩柱基礎", "合併基腳", "條形基礎"],
        "description": "剛性聯合基腳線性基底反力、縱向撓曲、沖剪、柱載重分配與可選分層沉陷檢核。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範 §4", "建築物混凝土結構設計規範"],
        "limitations": "縱向條帶分析；沉陷須提供土層，可算分層瞬時、壓密與次壓縮總沉陷。橫向柱下局部分析、三維沖剪、差異沉陷與角變量須另用 settlement_assessment；土壤—結構互制未計。",
        "field_rules": _foundation_field_rules(),
        "example": _example_footing("combined"),
    },
    {
        "id": "foundation_pile",
        "group": "建築基礎",
        "title": "樁帽／樁群載重分配",
        "oral": ["樁帽", "樁群", "基樁", "樁基礎", "軸力分配"],
        "description": "等軸勁度與剛性樁帽假設下的樁群軸力分配、最大樁壓與拉力檢查。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範"],
        "limitations": "未做側向樁、群樁效率、沉陷、上浮與完整樁帽配筋。",
        "example": _example_footing("pile"),
    },
    {
        "id": "settlement_assessment",
        "group": "建築基礎",
        "title": "沉陷與角變量評估",
        "oral": [
            "沉陷",
            "壓密沉陷",
            "次壓縮",
            "差異沉陷",
            "角變量",
            "基礎變形",
            "相鄰柱沉陷",
        ],
        "description": "分層瞬時沉陷、單向度壓密、次壓縮、總沉陷，以及扣除剛體轉動後的多基礎差異沉陷與角變量。",
        "engine": "foundation_design.py",
        "codes": [
            "建築物基礎構造設計規範 §4.4.2～4.4.7",
            "建築物基礎構造設計規範 §4.5.3～4.5.4",
        ],
        "limitations": "地層採分層 2:1 應力擴散；差異沉陷為幾何篩檢，未做土壤—結構互制、筏基有限元、側向樁或三維勁度重分配。",
        "field_rules": _settlement_field_rules(),
        "example": _example_settlement_assessment(),
    },
    {
        "id": "hydrology",
        "group": "水文",
        "title": "集水區設計流量",
        "oral": ["水文", "降雨強度", "合理化公式", "逕流係數", "集流時間", "設計流量"],
        "description": "水土保持技術規範第 16～19 條降雨強度、逕流係數、集流時間與合理化公式。",
        "engine": "hydrology.py",
        "codes": ["水土保持技術規範 §16～19"],
        "limitations": "降雨與土地利用參數必須用當地資料；第 16 條公式推估值是下限。",
        "field_rules": _hydrology_field_rules(),
        "example": {
            "P_mm": 2000.0,
            "return_period_yr": 25.0,
            "area_ha": 2.0,
            "condition": "丘陵地或森林",
            "developed": False,
            "upper_c": False,
            "area_type": "集水區",
            "l_m": 100.0,
            "v_ms": 0.4,
            "L_km": 0.0,
            "H_km": 0.0,
        },
    },
    {
        "id": "sediment_basin",
        "group": "水保設施",
        "title": "沉砂池容量",
        "oral": ["沉砂池", "泥砂生產量", "USLE", "土壤流失", "沉砂"],
        "description": "USLE、泥砂生產量、容量下限、深度與可選池壁／出水口／溢流檢核。",
        "engine": "sediment_basin.py",
        "codes": ["水土保持技術規範 §35、§92～93", "下水道工程設施標準 §12"],
        "limitations": "結構與出水口為初步檢核；未計池外土壓、地震、滲流、阻塞與消能。",
        "field_rules": _sediment_field_rules(),
        "example": {
            "area_ha": 2.0,
            "excavated_ha": 1.2,
            "impervious_ha": 0.2,
            "kind": "temporary",
            "years": 1.0,
            "Am": 40.0,
            "depth_m": 2.0,
        },
    },
    {
        "id": "slope_stability",
        "group": "邊坡",
        "title": "邊坡穩定分析",
        "oral": ["邊坡", "坡角", "無限邊坡", "圓弧滑動", "安全係數"],
        "description": "無限邊坡法、Fellenius 坡趾圓與容許坡角反算，依永久／臨時與工況查最小 FS。",
        "engine": "slope_stability.py",
        "codes": ["水土保持技術規範 §72～73"],
        "limitations": "均質土層與坡趾圓家族；分層土、軟弱夾層與滲流網須另行分析。",
        "field_rules": _slope_field_rules(),
        "example": {
            "height_m": 5.0,
            "slope_angle_deg": 25.0,
            "cohesion_kpa": 0.0,
            "unit_weight_kn_m3": 18.0,
            "stage": "永久性",
            "condition": "平時",
            "friction_deg": 35.0,
        },
    },
    {
        "id": "rc_beam",
        "group": "RC 構材",
        "title": "RC 梁斷面配筋",
        "oral": ["梁配筋", "樑配筋", "撓曲", "剪力", "裂縫"],
        "description": "矩形梁撓曲、最小鋼筋、剪力與裂縫控制，輸出建議筋號與間距。",
        "engine": "rc_design.py",
        "codes": ["建築物混凝土結構設計規範"],
        "limitations": "單筋矩形梁、常重混凝土；未計扭力、疲勞、耐震塑鉸與接頭細節。",
        "example": {
            "Mu_kNm": 180.0,
            "Vu_kN": 120.0,
            "b_mm": 350.0,
            "h_mm": 750.0,
            "fc_mpa": 28.0,
            "fy_mpa": 420.0,
        },
    },
    {
        "id": "rc_column",
        "group": "RC 構材",
        "title": "RC 柱軸彎互制",
        "oral": ["柱配筋", "軸彎互制", "柱設計", "軸力", "彎矩"],
        "description": "矩形柱軸力—彎矩互制曲線與鋼筋配置初步選筋。",
        "engine": "rc_design.py",
        "codes": ["建築物混凝土結構設計規範"],
        "limitations": "單軸彎矩、對稱鋼筋配置；雙向彎矩、二階效應、剪力與耐震圍束須另做。",
        "example": {
            "Pu_kN": 1600.0,
            "Mu_kNm": 280.0,
            "b_mm": 450.0,
            "h_mm": 450.0,
            "fc_mpa": 28.0,
            "fy_mpa": 420.0,
        },
    },
    {
        "id": "steel_column",
        "group": "鋼結構",
        "title": "鋼構柱、柱腳基板與基礎螺栓",
        "oral": [
            "鋼柱",
            "柱腳",
            "基板",
            "基礎螺栓",
            "錨栓",
            "鋼構設計",
        ],
        "description": (
            "H 型鋼柱軸壓、撓曲與梁柱互制檢核，柱腳混凝土承壓、基板厚度、"
            "基礎錨栓群拉力、剪力傳遞與拉剪互制聯合檢核。"
        ),
        "engine": "steel_column.py",
        "codes": ["建築物鋼結構設計技術規範（99.09.16）"],
        "limitations": (
            "只做露出式柱腳與澆置前預埋錨栓；埋入式柱腳、後置錨栓與特殊預埋件不在本模組。"
            "基板厚度採簡化懸臂法，雙向彎矩採彈性錨栓群法，"
            "未做柱腹板剪力、焊道、灌漿與埋入式細部，須人工覆核。"
        ),
        "field_rules": _steel_column_field_rules(),
        "example": _example_steel_column(),
    },
]


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


def _num(data: Mapping[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value in (None, ""):
        if default is None:
            raise DesignAPIError(f"缺少參數 {key}")
        return float(default)
    return float(value)


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


def _run_wall(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import retaining_wall as RW

    q = payload.get("section") or payload.get("quantities", {}).get("values") or payload
    soil = payload.get("soil")
    seismic = payload.get("seismic")
    if payload.get("kh") is not None:
        seismic = {"kh": float(payload["kh"])}
    return RW.analyse(q, soil=soil, seismic=seismic)


def _run_block_wall(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import block_wall as BW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh"}
    }
    seismic = payload.get("seismic")
    if payload.get("kh") is not None:
        seismic = {"kh": float(payload["kh"])}
    return BW.analyse(q, soil=payload.get("soil"), seismic=seismic)


def _run_counterfort(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import counterfort_wall as CW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh", "concrete", "size"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    if payload.get("size"):
        out = CW.size_section(
            float(q["height_m"]), payload.get("soil"), kh, payload.get("concrete"),
            front_soil_depth_m=float(q.get("front_soil_depth_m") or 0.0),
            counterfort_spacing_m=q.get("counterfort_spacing_m"),
            include_passive=q.get("include_passive"),
            passive_ratio=q.get("passive_ratio"),
        )
        if not out["found"]:
            raise DesignAPIError("搜尋 %d 組斷面仍無法全部通過，請檢查土壤參數或改用其他牆型" % out["tried"])
        res = dict(out["result"])
        res["sized_section"] = out["section"]
        res["warnings"] = ["已依牆高自動反推斷面（搜尋 %d 組）：%s"
                           % (out["tried"], json.dumps(out["section"], ensure_ascii=False))] + list(res["warnings"])
        return res
    return CW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh}, concrete=payload.get("concrete"))


def _run_mse(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import mse_wall as MW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    return MW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh})


def _run_anchored(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import anchored_wall as AW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh", "concrete"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    return AW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh}, concrete=payload.get("concrete"))


def _run_box(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import box_culvert as BC

    section = payload.get("section") or payload
    params = payload.get("analysis") or {}
    return BC.analyse(
        section,
        design_flow_m3s=float(payload.get("design_flow_m3s", params.get("design_flow_m3s", 0.0)) or 0.0),
        slope=float(payload.get("slope", params.get("slope", 0.005)) or 0.005),
        manning_n=float(payload.get("manning_n", params.get("manning_n", 0.014)) or 0.014),
        soil_unit_weight_kn_m3=float(payload.get("soil_unit_weight_kn_m3", 18.0)),
        soil_phi_deg=float(payload.get("soil_phi_deg", 30.0)),
        surcharge_kpa=float(payload.get("surcharge_kpa", 0.0)),
        traffic_load_kpa=float(payload.get("traffic_load_kpa", 10.0)),
        groundwater_depth_m=payload.get("groundwater_depth_m"),
        internal_water_depth_m=float(payload.get("internal_water_depth_m", 0.0)),
        load_factor=float(payload.get("load_factor", 1.7)),
        seismic_kh=float(payload.get("seismic_kh", 0.0)),
        freeboard_min_m=float(payload.get("freeboard_min_m", 0.20)),
        allowable_bearing_kpa=payload.get("allowable_bearing_kpa"),
        inlet_type=payload.get("inlet_type") or None,
        tailwater_depth_m=float(payload.get("tailwater_depth_m", 0.0) or 0.0),
        allowable_headwater_m=payload.get("allowable_headwater_m"),
        entrance_loss_ke=payload.get("entrance_loss_ke"),
        hw_d_limit=float(payload.get("hw_d_limit", 1.5) or 1.5),
        outlet_velocity_limit_m_s=payload.get("outlet_velocity_limit_m_s"),
    )


def _run_channel(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_hydraulics as CH

    return CH.analyse(
        _num(payload, "design_flow_m3s"),
        _num(payload, "inner_width_m"),
        _num(payload, "depth_m"),
        _num(payload, "slope"),
        {
            "manning_n": _num(payload, "manning_n", 0.014),
            "freeboard_min_m": _num(payload, "freeboard_min_m", 0.20),
        },
    )


def _run_channel_profile(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_profile as CP

    width = payload.get("bottom_width_m", payload.get("inner_width_m"))
    depth = payload.get("channel_depth_m", payload.get("depth_m"))
    return CP.analyse(
        design_flow_m3s=_num(payload, "design_flow_m3s"),
        bottom_width_m=float(width) if width not in (None, "") else _num(payload, "bottom_width_m"),
        side_slope_h_v=_num(payload, "side_slope_h_v", 0.0),
        slope=_num(payload, "slope"),
        manning_n=_num(payload, "manning_n", 0.014),
        reach_length_m=_num(payload, "reach_length_m"),
        step_m=_num(payload, "step_m", 10.0),
        control_depth_m=payload.get("control_depth_m"),
        channel_depth_m=depth if depth not in (None, "") else None,
        freeboard_min_m=_num(payload, "freeboard_min_m", 0.20),
        minor_loss_coefficient=_num(payload, "minor_loss_coefficient", 0.0),
        velocity_min_m_s=_num(payload, "velocity_min_m_s", 0.0),
        velocity_max_m_s=payload.get("velocity_max_m_s"),
    )


def _run_network(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import drainage_network as DN

    return DN.analyse(payload)


def _run_basin(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import detention_basin as DB

    return DB.analyse(payload)


def _run_building(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import building_frame as BF

    geometry = payload.get("geometry") or payload
    loads = payload.get("loads") or {}
    return BF.analyse(geometry, loads)


def _run_foundation(payload: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    import foundation_design as FD

    geometry = payload.get("geometry") or payload
    load = payload.get("load") or payload
    common = {
        "q_allow_kpa": float(payload.get("q_allow_kpa", 200.0)),
        "fc_mpa": float(payload.get("fc_mpa", 28.0)),
        "fy_mpa": float(payload.get("fy_mpa", 420.0)),
    }
    if kind == "isolated":
        return FD.analyse_isolated_footing(
            load,
            B_m=float(geometry.get("B_m")),
            L_m=float(geometry.get("L_m")),
            thickness_m=float(geometry.get("thickness_m")),
            column_b_m=float(geometry.get("column_b_m")),
            column_l_m=float(geometry.get("column_l_m")),
            cover_mm=float(payload.get("cover_mm", 75.0)),
            friction_coefficient=float(payload.get("friction_coefficient", 0.5)),
            settlement=payload.get("settlement"),
            **common,
        )
    if kind == "combined":
        return FD.analyse_combined_footing(
            payload.get("columns") or [],
            B_m=float(payload.get("B_m")),
            L_m=float(payload.get("L_m")),
            thickness_m=float(payload.get("thickness_m")),
            column_b_m=float(payload.get("column_b_m", 0.4)),
            column_l_m=float(payload.get("column_l_m", 0.4)),
            settlement=payload.get("settlement"),
            **common,
        )
    return FD.pile_group_check(
        payload.get("piles") or [],
        P_kN=float(payload.get("P_kN")),
        Mx_kNm=float(payload.get("Mx_kNm", 0.0)),
        My_kNm=float(payload.get("My_kNm", 0.0)),
        Q_allow_kN=float(payload.get("Q_allow_kN")),
    )


def _run_hydrology(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import hydrology as HY

    return HY.design_flow(
        _num(payload, "P_mm"),
        _num(payload, "return_period_yr"),
        _num(payload, "area_ha"),
        str(payload.get("condition", "丘陵地或森林")),
        developed=bool(payload.get("developed", False)),
        upper_c=bool(payload.get("upper_c", False)),
        l_m=_num(payload, "l_m", 100.0),
        v_ms=_num(payload, "v_ms", 0.4),
        L_km=_num(payload, "L_km", 0.0),
        H_km=_num(payload, "H_km", 0.0),
        area_type=str(payload.get("area_type", "集水區")),
        t_override_min=payload.get("t_override_min"),
    )


def _run_sediment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import sediment_basin as SB

    result = SB.analyse(
        _num(payload, "area_ha"),
        excavated_ha=_num(payload, "excavated_ha", 0.0),
        impervious_ha=_num(payload, "impervious_ha", 0.0),
        kind=str(payload.get("kind", "temporary")),
        years=_num(payload, "years", 1.0),
        depth=payload.get("depth_m"),
        side_ratio=_num(payload, "side_ratio", 1.5),
        Am=payload.get("Am"),
        Rm=payload.get("Rm"),
        Km=payload.get("Km"),
        LS=payload.get("LS"),
        C=payload.get("C"),
        P=payload.get("P"),
    )
    if payload.get("structure"):
        s = payload["structure"]
        result["structure"] = SB.structural_design(
            result,
            wall_t_m=float(s.get("wall_t_m", 0.25)),
            base_t_m=float(s.get("base_t_m", 0.25)),
            water_level_m=s.get("water_level_m"),
            groundwater_head_m=float(s.get("groundwater_head_m", 0.0)),
        )
    if payload.get("outlet"):
        o = payload["outlet"]
        result["outlet"] = SB.outlet_and_overflow_design(
            _num(o, "design_q_m3s"),
            _num(o, "outlet_head_m"),
            outlet_d_m=o.get("outlet_d_m"),
            overflow_head_m=o.get("overflow_head_m"),
            overflow_length_m=o.get("overflow_length_m"),
        )
    return result


def _run_slope(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import slope_stability as SS

    return SS.analyse(payload)


def _run_rc_beam(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import rc_design as RC

    return RC.beam_design(
        _num(payload, "Mu_kNm"),
        _num(payload, "Vu_kN"),
        b_mm=_num(payload, "b_mm", 300.0),
        h_mm=_num(payload, "h_mm", 600.0),
        M_service_kNm=payload.get("M_service_kNm"),
        fc_mpa=_num(payload, "fc_mpa", 28.0),
        fy_mpa=_num(payload, "fy_mpa", 420.0),
        cover_mm=_num(payload, "cover_mm", 40.0),
    )


def _run_rc_column(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import rc_design as RC

    return RC.column_design(
        _num(payload, "Pu_kN"),
        _num(payload, "Mu_kNm"),
        b_mm=_num(payload, "b_mm", 400.0),
        h_mm=_num(payload, "h_mm", 400.0),
        fc_mpa=_num(payload, "fc_mpa", 28.0),
        fy_mpa=_num(payload, "fy_mpa", 420.0),
        cover_mm=_num(payload, "cover_mm", 40.0),
    )


def _run_settlement_assessment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import foundation_design as FD

    return FD.settlement_assessment(payload)


def _run_steel_column(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import steel_column as SC

    return SC.analyse(payload)


def _run_channel_cover(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_cover as CC

    return CC.analyse(payload)


RUNNERS: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
    "wall_stability": _run_wall,
    "block_wall": _run_block_wall,
    "counterfort_wall": _run_counterfort,
    "mse_wall": _run_mse,
    "anchored_wall": _run_anchored,
    "box_culvert": _run_box,
    "channel_hydraulics": _run_channel,
    "channel_profile": _run_channel_profile,
    "drainage_network": _run_network,
    "detention_basin": _run_basin,
    "building_frame": _run_building,
    "foundation_isolated": lambda p: _run_foundation(p, "isolated"),
    "foundation_combined": lambda p: _run_foundation(p, "combined"),
    "foundation_pile": lambda p: _run_foundation(p, "pile"),
    "settlement_assessment": _run_settlement_assessment,
    "hydrology": _run_hydrology,
    "sediment_basin": _run_sediment,
    "slope_stability": _run_slope,
    "rc_beam": _run_rc_beam,
    "rc_column": _run_rc_column,
    "steel_column": _run_steel_column,
    "channel_cover": _run_channel_cover,
}


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

