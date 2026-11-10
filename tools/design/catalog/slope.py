"""邊坡計算器的欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

from typing import Any


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
