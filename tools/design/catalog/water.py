"""排水與水文類計算器（排水溝、水面線、排水網路、滯洪池、水文、沉砂）的範例與欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

from typing import Any


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
