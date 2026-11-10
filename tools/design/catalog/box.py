"""箱涵計算器的範例與欄位規則。

自 `design_api.py` 原樣搬出，內容未改。
"""

from typing import Any, Mapping

from catalog._shared import _num


def _example_box_culvert() -> dict[str, Any]:
    return {
        "cell_count": 3,
        "clear_width_m": 3.0,
        "clear_height_m": 2.5,
        "wall_thickness_m": 0.35,
        "interior_wall_thickness_m": 0.30,
        "top_slab_thickness_m": 0.40,
        "bottom_slab_thickness_m": 0.45,
        "cover_mm": 50.0,
        "cover_depth_m": 0.60,
        "length_m": 20.0,
        "inner_chamfer_m": 0.20,
        "corner_rebar": "D13",
        "corner_rebar_spacing_mm": 200,
        "traffic_type": "h20_s16",
        "traffic_lanes": 4,
        "crack_limit_mm": 0.30,
        "bar_preference": "auto",
        "distribution_bar": "D13",
        "rebar_loss_rate": 0.06,
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
        import box_culvert as BC

        choices = [
            {"value": key, "label": spec["label"]}
            for key, spec in CH.INLET_TYPES.items()
        ]
    except Exception:  # pragma: no cover - 只在引擎匯入失敗時退化
        choices = [{"value": "wingwall_30_75", "label": "翼牆張角 30°～75°"}]
        BC = None
    traffic_choices = (
        [
            {"value": key, "label": spec["label"]}
            for key, spec in BC.TRAFFIC_TYPES.items()
        ]
        if BC is not None
        else [
            {"value": "none", "label": "無車載（僅土壓／上載）"},
            {"value": "h20", "label": "H-20（後輪 7.25 t、衝擊 30%）"},
            {"value": "h20_s16", "label": "H-20 S-16（P=7.3 t、依車道數）"},
            {"value": "trailer_40t", "label": "40T 拖車（後輪 8 t）"},
            {"value": "custom", "label": "自訂均佈車載（kPa）"},
        ]
    )
    return {
        "inner_chamfer_m": {
            "type": "number",
            "label": "內角 45° 加腋邊長（m）",
            "step": 0.05,
            "min": 0,
            "max": 1.0,
            "hint": "內角倒角（加腋）邊長，45° 斜面；過往標準圖 300×200 箱涵用 20 cm、"
                    "400×300 用 30 cm。不得大於牆厚／中牆厚／淨高的一半；"
                    "設 0 表示不做加腋。",
        },
        "corner_rebar": {
            "type": "select",
            "label": "角隅補強筋",
            "choices": [
                {"value": "D10", "label": "D10"},
                {"value": "D13", "label": "D13"},
                {"value": "D16", "label": "D16"},
                {"value": "D19", "label": "D19"},
            ],
            "hint": "內角加腋處之角隅補強筋（X 形交叉斜筋）筋號；"
                    "做法依標準圖 C110／C111。屬構造筋，不參與構架分析。",
        },
        "corner_rebar_spacing_mm": {
            "type": "number",
            "label": "角隅補強筋間距 (mm)",
            "step": 10,
            "min": 0,
            "max": 500,
            "hint": "每個內角沿涵長方向的 X 形交叉斜筋間距；"
                    "標準圖 C110／C111 用 200 mm。設 0 表示不設角隅補強筋。",
        },
        "traffic_type": {
            "type": "select",
            "label": "車載標準",
            "choices": traffic_choices,
            "hint": (
                "H-20：後輪 7.25 t、衝擊 30%，依傳佈面積換算均佈；"
                "H-20 S-16：P=7.3 t、依車道數換算；40T 拖車：後輪 8 t、"
                "E=1.2+0.06s，以頂版局部輪壓施加。"
            ),
        },
        "traffic_lanes": {
            "type": "number",
            "label": "H-20 S-16 車道數",
            "step": 1,
            "min": 1,
            "max": 4,
            "hint": "僅 H-20 S-16 使用；1～4 車道，三／四車道依工作簿乘 0.9／0.75。",
        },
        "traffic_load_kpa": {
            "type": "number",
            "label": "自訂均佈車載（kPa）",
            "step": 0.1,
            "min": 0,
            "hint": "僅 traffic_type=custom 時使用；勿再與 H-20／40T 重複相加。",
        },
        "traffic_impact_factor": {
            "type": "number",
            "label": "自訂衝擊係數 i（0～0.5）",
            "step": 0.01,
            "min": 0,
            "max": 0.5,
            "hint": "留空＝依車型標準（H-20／40T 0.30；H-20 S-16 低覆土 0.20～0.30）。",
        },
        "rebar_loss_rate": {
            "type": "number",
            "label": "鋼筋損耗率（含搭接）",
            "step": 0.01,
            "min": 0,
            "max": 0.5,
            "hint": "預設 0.06（6%）；僅影響數量，不影響配筋檢核。",
        },
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
        "cover_mm": {
            "type": "number",
            "label": "主筋保護層（mm）",
            "step": 5,
            "min": 25,
            "max": 100,
            "hint": (
                "頂版／底版／牆採同一保護層；迎土面常用 50～75 mm。"
                "保護層會同時影響有效深度、裂縫寬度與最大鋼筋間距。"
            ),
        },
        "crack_limit_mm": {
            "type": "number",
            "label": "裂縫寬度上限（mm）",
            "step": 0.05,
            "min": 0.10,
            "max": 0.40,
            "hint": "一般室外 RC 構材 0.30 mm；腐蝕環境或特殊要求可加嚴至 0.20 mm。",
        },
        "bar_preference": {
            "type": "select",
            "label": "主筋選筋偏好",
            "choices": [
                {"value": "auto", "label": "自動（D16 起，必要時加大）"},
                {"value": "fine", "label": "細筋密排（D13 起）"},
                {"value": "coarse", "label": "粗筋少排（D19 起）"},
            ],
            "hint": "各受拉面仍會依所需 As、最大間距與裂縫控制自動選筋。",
        },
        "distribution_bar": {
            "type": "select",
            "label": "縱向分佈筋筋號",
            "choices": [
                {"value": "D13", "label": "D13"},
                {"value": "D16", "label": "D16"},
            ],
            "hint": "版採 0.0018·b·h、牆採 0.0020·b·h，分置內外兩面。",
        },
    }


def _run_box(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import box_culvert as BC

    section = payload.get("section") or payload
    params = payload.get("analysis") or {}
    section_params = section if isinstance(section, Mapping) else {}
    traffic_type = payload.get("traffic_type") or section_params.get("traffic_type")
    traffic_load_kpa = float(
        payload.get("traffic_load_kpa", section_params.get("traffic_load_kpa", 0.0))
        or 0.0
    )
    traffic_lanes = int(
        payload.get("traffic_lanes", section_params.get("traffic_lanes", 4)) or 4
    )
    impact_raw = payload.get(
        "traffic_impact_factor", section_params.get("traffic_impact_factor")
    )
    impact = (
        float(impact_raw)
        if impact_raw not in (None, "")
        else None
    )
    loss_raw = payload.get(
        "rebar_loss_rate", section_params.get("rebar_loss_rate")
    )
    rebar_loss_rate = float(loss_raw) if loss_raw not in (None, "") else BC.REBAR_LOSS_RATE
    return BC.analyse(
        section,
        design_flow_m3s=float(payload.get("design_flow_m3s", params.get("design_flow_m3s", 0.0)) or 0.0),
        slope=float(payload.get("slope", params.get("slope", 0.005)) or 0.005),
        manning_n=float(payload.get("manning_n", params.get("manning_n", 0.014)) or 0.014),
        soil_unit_weight_kn_m3=float(payload.get("soil_unit_weight_kn_m3", 18.0)),
        soil_phi_deg=float(payload.get("soil_phi_deg", 30.0)),
        surcharge_kpa=float(payload.get("surcharge_kpa", 0.0)),
        traffic_load_kpa=traffic_load_kpa,
        traffic_type=traffic_type,
        traffic_lanes=traffic_lanes,
        traffic_impact_factor=impact,
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
        cover_mm=payload.get("cover_mm"),
        crack_limit_mm=float(payload.get("crack_limit_mm", 0.3) or 0.3),
        bar_preference=str(payload.get("bar_preference", "auto") or "auto"),
        distribution_bar=str(payload.get("distribution_bar", "D13") or "D13"),
        rebar_loss_rate=rebar_loss_rate,
    )


ENTRIES = [
    {
        "id": "box_culvert",
        "group": "箱涵",
        "title": "單孔／雙孔／三孔箱涵",
        "oral": ["箱涵", "單孔", "雙孔", "三孔", "涵洞", "覆土", "出水高", "進口控制", "出口控制", "頭水"],
        "description": "參數化箱涵平面剛架、土水壓與 H-20／H-20 S-16／40T 拖車車載、內外側逐面配筋（正負彎矩包絡）、縱向分佈筋、裂縫與鋼筋量概估、撓曲／剪力／軸彎互制、浮力，以及附錄 N／O 進口／出口控制水理。",
        "engine": "box_culvert.py",
        "codes": ["公路排水設計規範", "公路橋梁設計規範", "水土保持技術規範 §87", "建築物混凝土結構設計規範"],
        "limitations": "翼牆與端牆只檢核有輸入的幾何值（§6.5），不檢核沖刷深度；低水頭出口控制未做迴水曲線；配筋已做內外側分層、縱向分佈筋與內角加腋處之角隅補強筋（X 形交叉斜筋，構造筋），但仍未計施工階段、開口補強、錨定／搭接長度細節與正式配筋詳圖；車載與其他載重共用 load_factor，未拆分靜載／活載因數。",
        "field_rules": _box_culvert_field_rules(),
        "example": _example_box_culvert(),
    }
]

RUNNERS = {
    'box_culvert': _run_box,
}
