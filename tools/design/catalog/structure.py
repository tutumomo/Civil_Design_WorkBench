"""建築、基礎、鋼構與路側溝加蓋計算器的範例與欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

from typing import Any, Mapping

from catalog._shared import _num


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

    if payload.get("size"):
        p2 = dict(payload)
        geo = dict(payload.get("geometry") or {})
        geo["slab_thickness_mm"] = None
        p2["geometry"] = geo
        p2["slab"] = {"main_bar": "", "main_spacing_mm": 0.0, "dist_bar": "", "dist_spacing_mm": 0.0}
        res = dict(CC.analyse(p2))
        sized = {
            "geometry.slab_thickness_mm": (res.get("geometry") or {}).get("slab_thickness_mm", 250.0),
            "slab.main_bar": "",
            "slab.main_spacing_mm": 0.0,
            "slab.dist_bar": "",
            "slab.dist_spacing_mm": 0.0,
        }
        res["sized_section"] = sized
        res["warnings"] = [
            "已自動搜尋最小合格版厚與配筋：版厚 %.0f mm"
            % float(sized["geometry.slab_thickness_mm"] or 250.0)
        ] + list(res.get("warnings") or [])
        return res
    return CC.analyse(payload)


ENTRIES = [
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
    }
]

RUNNERS = {
    'channel_cover': _run_channel_cover,
    'building_frame': _run_building,
    'foundation_isolated': lambda p: _run_foundation(p, "isolated"),
    'foundation_combined': lambda p: _run_foundation(p, "combined"),
    'foundation_pile': lambda p: _run_foundation(p, "pile"),
    'settlement_assessment': _run_settlement_assessment,
    'rc_beam': _run_rc_beam,
    'rc_column': _run_rc_column,
    'steel_column': _run_steel_column,
}
