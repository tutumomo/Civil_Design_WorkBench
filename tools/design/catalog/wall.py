"""擋土牆類計算器（懸臂／重力、疊砌、扶壁、加勁、錨定）的範例與欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

import json
from typing import Any, Mapping

from catalog._shared import DesignAPIError



_PASSIVE_RATIO_HINT = "1＝全 Rankine；牆身位移不足以發揮全被動時取小於 1"


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
        "fc_mpa": 21.0,
        "fy_mpa": 420,
        "cover_mm": 75,
        "stem_bar": "auto",
        "base_bar": "auto",
        "mass_wall_face_bar": "D13",
        "mass_wall_face_spacing_mm": 250,
        "mass_wall_base_bar": "D16",
        "mass_wall_base_spacing_mm": 200,
    }


def _wall_bar_choices(*, include_auto: bool = False, default: str = "D16"):
    """擋土牆配筋筋號下拉選單。"""
    out = []
    if include_auto:
        out.append({"value": "auto", "label": "自動選擇（依需求）"})
    for name in ("D10", "D13", "D16", "D19", "D22", "D25", "D29", "D32"):
        out.append({"value": name, "label": name + ("（預設）" if name == default else "")})
    return out


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
        # ---- 配筋設定（2026-11-04 新增：穩定分析同時輸出配筋）----
        "fc_mpa": {
            "type": "number",
            "step": 1,
            "label": "混凝土 fc′ (MPa)",
            "hint": "預設 21 MPa（≈210 kgf/cm²）；變更須重跑配筋檢核",
        },
        "fy_mpa": {
            "type": "select",
            "label": "鋼筋 fy (MPa)",
            "choices": [
                {"value": 280, "label": "SD280（280 MPa）"},
                {"value": 420, "label": "SD420（420 MPa，預設）"},
            ],
        },
        "cover_mm": {
            "type": "number",
            "step": 5,
            "label": "鋼筋保護層 (mm)",
            "hint": "擋土牆迎土面預設 75 mm；面版／排水溝 50 mm",
        },
        "stem_bar": {
            "type": "select",
            "label": "【懸臂式】牆身主筋",
            "choices": _wall_bar_choices(include_auto=True),
            "hint": "auto＝依撓曲需求自動選筋；指定筋號只改筋徑，間距仍由需求決定",
        },
        "base_bar": {
            "type": "select",
            "label": "【懸臂式】底板主筋（趾板／踵板）",
            "choices": _wall_bar_choices(include_auto=True),
        },
        "mass_wall_face_bar": {
            "type": "select",
            "label": "【重力式／半重力式】牆面構造筋",
            "choices": _wall_bar_choices(default="D13"),
        },
        "mass_wall_face_spacing_mm": {
            "type": "number",
            "step": 10,
            "label": "【重力式／半重力式】牆面筋間距 (mm)",
        },
        "mass_wall_base_bar": {
            "type": "select",
            "label": "【重力式／半重力式】底部縱筋",
            "choices": _wall_bar_choices(default="D16"),
        },
        "mass_wall_base_spacing_mm": {
            "type": "number",
            "step": 10,
            "label": "【重力式／半重力式】底部縱筋間距 (mm)",
        },
    }


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
        "facing_type": "precast_panel",
        "face_panel_thickness_m": 0.20,
        "panel_width_m": 1.50,
        "face_panel_cover_mm": 50.0,
        "connector_capacity_kN": 100.0,
        "connector_bearing_area_mm2": 20000.0,
        "connector_fs": 1.5,
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
        "facing_type": {
            "type": "select",
            "label": "面版種類",
            "choices": [
                {"value": "precast_panel", "label": "RC 預鑄面版（初步配筋）"},
                {"value": "cast_in_place", "label": "RC 場鑄面版（初步配筋）"},
                {"value": "segmental_block", "label": "塊狀面版（不配 RC 筋）"},
            ],
        },
        "face_panel_thickness_m": {"type": "number", "step": 0.01, "label": "面版厚 (m)",
                                   "hint": "RC 面版初步設計用；塊狀面版可忽略"},
        "panel_width_m": {"type": "number", "step": 0.1, "label": "面版單元寬度 (m)"},
        "face_panel_cover_mm": {"type": "number", "step": 5, "label": "面版保護層 (mm)"},
        "connector_capacity_kN": {
            "type": "number", "step": 1, "label": "面版連接器極限拉力 (kN)",
            "hint": "產品型錄或試驗值；留空則不做連接檢核",
        },
        "connector_bearing_area_mm2": {
            "type": "number", "step": 100, "label": "連接器承壓面積 (mm²)",
            "hint": "承壓鈑／垫片有效面積；留空則不做局部承壓檢核",
        },
        "connector_fs": {
            "type": "number", "step": 0.1, "label": "連接安全係數",
            "hint": "預設 1.5（FHWA 容許應力法）",
        },
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


_WALL_REBAR_KEYS = (
    "stem_bar",
    "base_bar",
    "mass_wall_face_bar",
    "mass_wall_face_spacing_mm",
    "mass_wall_base_bar",
    "mass_wall_base_spacing_mm",
)


def _wall_concrete(payload: Mapping[str, Any]) -> dict[str, Any]:
    """把 UI 的混凝土／鋼筋設定轉成 rc_design 的 cc 覆寫值。"""
    cc: dict[str, Any] = {}
    nested = payload.get("concrete")
    if isinstance(nested, Mapping):
        for key in ("fc_mpa", "fy_mpa", "cover_mm"):
            if nested.get(key) not in (None, ""):
                cc[key] = float(nested[key])
    for key in ("fc_mpa", "fy_mpa", "cover_mm"):
        if payload.get(key) not in (None, ""):
            cc[key] = float(payload[key])
    return cc


def _rebar_check(item, value, limit, unit, ok, *, relation="ge", decimals=3):
    return {
        "item": item,
        "value": round(float(value), decimals),
        "limit": round(float(limit), decimals),
        "unit": unit,
        "ok": bool(ok),
        "relation": relation,
    }


def _wall_rebar_checks(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把配筋設計轉成工作台檢核列（item/value/limit/unit/ok）。"""
    wt = str(design.get("wall_type") or "")
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        rho = float(mass.get("temperature_ratio") or 0.0)
        lim = float(mass.get("temperature_min") or 0.002)
        return [_rebar_check("牆面構造鋼筋比（ρ ≥ 0.002）", rho, lim, "-",
                             rho >= lim - 1e-9, decimals=4)]

    checks: list[dict[str, Any]] = []

    def add(prefix, member):
        main = member.get("main") or {}
        shear = member.get("shear") or {}
        crack = member.get("crack") or {}
        if main.get("phiMn_kNm") is not None:
            checks.append(_rebar_check(
                prefix + " 撓曲（φMn ≥ Mu）",
                main["phiMn_kNm"], main.get("Mu_kNm") or 0.0,
                "kN·m/m", main.get("ok")))
        if shear.get("phiVc_kN") is not None:
            checks.append(_rebar_check(
                prefix + " 剪力（φVc ≥ Vu）",
                shear["phiVc_kN"], shear.get("Vu_kN") or 0.0,
                "kN/m", shear.get("ok")))
        if crack.get("w_mm") is not None:
            checks.append(_rebar_check(
                prefix + " 裂縫寬度 ≤ 0.3 mm",
                crack["w_mm"], crack.get("limit_mm") or 0.3,
                "mm", crack.get("ok"), relation="le"))

    structural = design.get("structural") or {}
    stem = structural.get("stem") or {}
    if stem:
        add("牆身", stem)
    base = structural.get("base") or {}
    for member in base.get("members") or []:
        add(member.get("member") or "底板", member)
    return checks


def _wall_rebar_lines(design: Mapping[str, Any]) -> list[str]:
    """配筋設計的人看文字（接在穩定分析 summary 後）。"""
    def sp(value):
        try:
            return "%g" % float(value)
        except (TypeError, ValueError):
            return str(value or "-")

    wt = str(design.get("wall_type") or "")
    total = float(design.get("total_kg_per_m") or 0.0)
    rate = float(design.get("lap_allowance") or 0.0)
    if rate <= 0:
        import rc_design as RC
        rate = RC.LAP_ALLOWANCE
    lines = ["", "配筋設計（含 %.0f%% 搭接、錨定與損耗）：%.2f kg/m"
              % (rate * 100.0, total)]
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        lines.append(
            "  牆面 %s@%s 雙向＋底部縱筋 %s@%s；構造鋼筋比 %.4f（≥ %.4f）" % (
                mass.get("face_bar", "-"), sp(mass.get("face_spacing_mm")),
                mass.get("base_bar", "-"), sp(mass.get("base_spacing_mm")),
                float(mass.get("temperature_ratio") or 0.0),
                float(mass.get("temperature_min") or 0.002)))
        lines.append("  重力式／半重力式以自重穩定，牆身不設撓曲主筋")
        return lines

    structural = design.get("structural") or {}
    for label, member in (("牆身", structural.get("stem") or {}),):
        main = member.get("main") or {}
        if main.get("bar"):
            lines.append(
                "  [%s] %s撓曲：%s@%s mm（As=%.0f mm²/m）；φMn=%.1f ≥ Mu=%.1f kN·m/m" % (
                    "OK" if main.get("ok") else "NG", label,
                    main.get("bar"), sp(main.get("spacing_mm")),
                    main.get("As_prov_mm2") or 0.0,
                    main.get("phiMn_kNm") or 0.0, main.get("Mu_kNm") or 0.0))
        shear = member.get("shear") or {}
        if shear.get("phiVc_kN") is not None:
            lines.append(
                "  [%s] 牆身剪力：φVc=%.1f ≥ Vu=%.1f kN/m" % (
                    "OK" if shear.get("ok") else "NG",
                    shear["phiVc_kN"], shear.get("Vu_kN") or 0.0))
        crack = member.get("crack") or {}
        if crack.get("w_mm") is not None:
            lines.append(
                "  [%s] 牆身裂縫：w=%.3f mm（限 %.1f mm）" % (
                    "OK" if crack.get("ok") else "NG",
                    crack["w_mm"], crack.get("limit_mm") or 0.3))
    base = structural.get("base") or {}
    for member in base.get("members") or []:
        main = member.get("main") or {}
        if not main.get("bar"):
            continue
        lines.append(
            "  [%s] %s：%s@%s mm；φMn=%.1f ≥ Mu=%.1f kN·m/m" % (
                "OK" if member.get("ok") else "NG", member.get("member", "底板"),
                main.get("bar"), sp(main.get("spacing_mm")),
                main.get("phiMn_kNm") or 0.0, main.get("Mu_kNm") or 0.0))
    rows = (design.get("kg") or {}).get("rows") or []
    if rows:
        detail = "、".join("%s %.2f" % (r.get("item", ""), r.get("kg_per_m") or 0.0)
                          for r in rows)
        lines.append("  鋼筋量明細（kg/m）：" + detail)
    return lines


def _attach_wall_rebar(q, res, payload):
    """在穩定分析結果上附加配筋設計（重力／半重力／懸臂）。"""
    import rc_design as RC

    q2 = dict(q)
    for key in _WALL_REBAR_KEYS:
        if payload.get(key) not in (None, ""):
            q2[key] = payload[key]
    design = RC.design_wall_rebar(q2, res, _wall_concrete(payload))
    res["rebar"] = design
    res["rebar_summary"] = _wall_rebar_lines(design)
    res["checks"] = list(res.get("checks") or []) + _wall_rebar_checks(design)
    res["pass"] = bool(res.get("pass")) and bool(design.get("ok"))
    return res


def _run_wall(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import retaining_wall as RW

    q = payload.get("section") or payload.get("quantities", {}).get("values") or payload
    soil = payload.get("soil")
    seismic = payload.get("seismic")
    if payload.get("kh") is not None:
        seismic = {"kh": float(payload["kh"])}
    kh = float((seismic or {}).get("kh") or 0.0)
    if payload.get("size"):
        wall_type = str(q.get("wall_type") or "gravity").strip().lower()
        if wall_type not in ("gravity", "cantilever"):
            raise DesignAPIError("自動試算斷面目前支援重力式（gravity）或懸臂式（cantilever）；半重力式請手動微調斷面。")

        def _rebar_ok(cand, cand_res):
            import rc_design as RC
            q2 = dict(cand)
            for key in _WALL_REBAR_KEYS:
                if payload.get(key) not in (None, ""):
                    q2[key] = payload[key]
            return bool(RC.design_wall_rebar(q2, cand_res, _wall_concrete(payload)).get("ok"))

        best, tried = RW.size_section(
            float(q.get("height_m") or 3.0),
            soil=soil,
            wall_type=wall_type,
            kh=kh,
            toe_passive={
                k: q[k]
                for k in ("toe_soil_depth_m", "include_passive", "passive_ratio")
                if k in q
            },
            extra_check=_rebar_ok,
        )
        if best is None:
            raise DesignAPIError("搜尋 %d 組斷面仍無法全部通過，請檢查土壤承載力／摩擦角或降低牆高" % tried)
        res = dict(best["res"])
        res["sized_section"] = dict(best["q"])
        res["warnings"] = [
            "已依牆高自動反推合格最小斷面（搜尋 %d 組）：%s"
            % (tried, json.dumps(best["q"], ensure_ascii=False))
        ] + list(res.get("warnings") or [])
        return _attach_wall_rebar(best["q"], res, payload)
    res = RW.analyse(q, soil=soil, seismic=seismic)
    return _attach_wall_rebar(q, res, payload)


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


ENTRIES = [
    {
        "id": "wall_stability",
        "group": "擋土牆",
        "title": "擋土牆穩定與配筋（重力／半重力／懸臂）",
        "oral": ["擋土牆", "重力式", "懸臂式", "半重力式", "滑動", "傾倒", "配筋", "鋼筋"],
        "description": "重力式、懸臂式、半重力式的常時／地震穩定、合力位置與承載檢核；並依牆型分流完成配筋設計（懸臂式莖板＋底板撓曲、重力／半重力式名目構造鋼筋），輸出每延米鋼筋量。",
        "engine": "retaining_wall.py",
        "codes": ["水土保持技術規範 §119～121", "建築物基礎構造設計規範"],
        "limitations": "蛇籠、格籠、砌石、三明治式請用「疊式／砌石擋土牆」，扶壁式、加勁、錨定各有專用計算器；配筋為初步設計（未含施工詳圖、搭接位置與錨定長度詳算），土層參數須用鑽探值替換預設值。",
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
        "limitations": "RC 面版僅做單向版初步配筋；面版－加勁材連接與局部承壓須輸入產品容量才檢核；吊裝、複合滑動與整體圓弧滑動未檢核；F*、α 為保守預設值；未計靜水壓。",
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
    }
]

RUNNERS = {
    'wall_stability': _run_wall,
    'block_wall': _run_block_wall,
    'counterfort_wall': _run_counterfort,
    'mse_wall': _run_mse,
    'anchored_wall': _run_anchored,
}
