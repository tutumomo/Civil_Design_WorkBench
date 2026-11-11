"""排水與水文類計算器（排水溝、水面線、排水網路、滯洪池、水文、沉砂）的範例與欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

from typing import Any, Mapping

from catalog._shared import _num


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
        },
        "wall_thickness_m": {
            "type": "number", "step": 0.05, "label": "溝壁厚 (m，出圖用)",
            "hint": "只供「產生設計圖」使用，不影響水力計算；未填則圖面採 0.15 m（水保最小構造厚度）並於說明欄標「假設值」。",
        },
        "base_thickness_m": {
            "type": "number", "step": 0.05, "label": "底板厚 (m，出圖用)",
            "hint": "同上；未填則圖面採 0.15 m 並標「假設值」。",
        },
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


def _run_channel(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_hydraulics as CH

    params = {
        "manning_n": _num(payload, "manning_n", 0.014),
        "freeboard_min_m": _num(payload, "freeboard_min_m", 0.20),
    }
    if payload.get("size"):
        best, tried = CH.size_channel(
            _num(payload, "design_flow_m3s"),
            _num(payload, "slope"),
            params,
        )
        if best is None:
            raise DesignAPIError("搜尋 %d 組 U 型溝斷面仍無法全部通過，請檢查設計流量或縱坡（流速限制 0.8~4.57 m/s）" % tried)
        res = dict(best["res"])
        sized = {"inner_width_m": best["b"], "depth_m": best["h"]}
        res["sized_section"] = sized
        res["warnings"] = [
            "已依設計流量自動反推最小合格斷面（搜尋 %d 組）：內寬 b=%.2f m、溝深 h=%.2f m"
            % (tried, best["b"], best["h"])
        ] + list(res.get("warnings") or [])
        return res
    return CH.analyse(
        _num(payload, "design_flow_m3s"),
        _num(payload, "inner_width_m"),
        _num(payload, "depth_m"),
        _num(payload, "slope"),
        params,
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


ENTRIES = [
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
    }
]

RUNNERS = {
    'channel_hydraulics': _run_channel,
    'channel_profile': _run_channel_profile,
    'drainage_network': _run_network,
    'detention_basin': _run_basin,
    'hydrology': _run_hydrology,
    'sediment_basin': _run_sediment,
}
