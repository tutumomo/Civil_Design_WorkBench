"""類別化數量模型：道路／擋土牆／排水溝的數量結構與派生規則。

為什麼需要它
------------
上一版 `quantities` 是固定的道路型五個鍵（L／W／A／t／V），檢查式是 `A = L×W`、`V = A×t`。
擋土牆的數量根本不是這個結構（每米斷面、混凝土體積、鋼筋、模板、排水孔、伸縮縫），
硬套道路公式會「看起來合格但完全錯」——這是本檔存在的原因。

設計
----
每個模型宣告三件事：
1. `required`：使用者必須自己填的鍵（設計輸入，不可由程式猜）
2. `derive`：可由其他鍵算出的鍵（含算式與容差）；算出來的會回寫，供 `qty_from` 引用
3. `notes`：規範依據與假設說明

算式用**受限 AST 求值**（只允許加減乘除次方、`ceil/floor/max/min/abs/round/sqrt/pi`），
不執行任意程式碼。

重要：`derive` 的容差用法
- 算式是「定義式」時（如 `concrete_volume_m3 = per_m × length`）→ tol=0 直接覆蓋
- 算式是「驗算式」時（如道路 `area_m2 = length × width`）→ tol=1.0，使用者填的值優先，
  只有在偏差超過容差時才報 error（因為實測面積不會剛好等於 L×W）
"""

import ast
import math

# 圖／數對帳用的實體斷面面積鍵名。集中定義，避免 qty_models 與
# dxf_takeoff 各寫一份字串而不一致。
DRAWN_SECTION_AREA_KEY = "drawn_section_area_m2"

_ALLOWED_FUNCS = {
    "ceil": math.ceil, "floor": math.floor, "max": max, "min": min,
    "abs": abs, "round": round, "sqrt": math.sqrt, "len": len,
    "pi": math.pi,
    # 邊坡用：斜坡長 = H/sinβ、水平投影 = H/tanβ
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "radians": math.radians, "degrees": math.degrees, "atan": math.atan,
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
    # 比較與三元：用於「依型別切換公式」（仍不允許屬性存取、索引、賦值、lambda）
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
    ast.And, ast.Or, ast.Not, ast.IfExp, ast.BoolOp,
)


def safe_eval(expr, namespace):
    """受限算式求值：只允許四則運算、次方與白名單函式。"""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"算式含不允許的語法：{type(node).__name__}（{expr}）")
        if isinstance(node, ast.Name) and node.id not in namespace and node.id not in _ALLOWED_FUNCS:
            raise ValueError(f"算式引用未定義變數 {node.id}（{expr}）")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise ValueError(f"算式呼叫不允許的函式（{expr}）")
    return eval(compile(tree, "<qty>", "eval"), {"__builtins__": {}}, {**_ALLOWED_FUNCS, **namespace})


# --------------------------------------------------------------------------- #
# 模型定義
# --------------------------------------------------------------------------- #
MODELS = {
    # ---- 邊坡（水保第 72、73 條）----
    # 數量只算「工程面」：坡面整地面積、坡面排水溝、植生、截水溝。
    # 穩定分析在 tools\design\slope_stability.py，不在此重複。
    "slope": {
        "label": "邊坡（坡面整地／植生／截排水）",
        "required": ["height_m", "slope_angle_deg", "length_m"],
        "defaults": {"bench_width_m": 0.0, "bench_count": 0.0,
                     "vegetation_ratio": 1.0,
                     "drain_spacing_m": 30.0, "excavation_work_m": 0.3},
        "derive": [
            {"key": "slope_face_m",
             "expr": "height_m / sin(radians(slope_angle_deg))",
             "verify_tol_pct": 0,
             "note": "坡面斜長 = H / sinβ"},
            {"key": "slope_area_m2",
             "expr": "slope_face_m * length_m",
             "verify_tol_pct": 0,
             "note": "坡面面積（整地／植生計價基準）"},
            {"key": "vegetation_area_m2",
             "expr": "slope_area_m2 * vegetation_ratio",
             "verify_tol_pct": 0},
            {"key": "horizontal_run_m",
             "expr": "height_m / tan(radians(slope_angle_deg))",
             "verify_tol_pct": 0,
             "note": "坡面水平投影長 = H / tanβ"},
            {"key": "surface_drain_m",
             "expr": "length_m * (bench_count + 1) + slope_face_m * 2",
             "verify_tol_pct": 0,
             "note": "坡頂／坡腳各一道 + 每平台一道 + 兩端斜向"},
            {"key": "bench_area_m2",
             "expr": "bench_width_m * length_m * bench_count",
             "verify_tol_pct": 0},
            {"key": "excavation_m3",
             "expr": "slope_face_m * length_m * excavation_work_m",
             "verify_tol_pct": 0,
             "note": "表層整地（剝皮）厚度 excavation_work_m"},
        ],
        # table 必須是含 "rows" 的物件（derive_report 會讀 tbl["rows"]），不是二維陣列
        "table": {
            "caption": "邊坡工程數量表",
            "rows": [
                {"label": "坡面斜長", "key": "slope_face_m", "unit": "m", "decimals": 2,
                 "basis": "H / sinβ = %.2f / sin(β)"},
                {"label": "坡面整地面積", "key": "slope_area_m2", "unit": "m2", "decimals": 2,
                 "basis": "斜長 × 坡長"},
                {"label": "植生面積", "key": "vegetation_area_m2", "unit": "m2", "decimals": 2,
                 "basis": "整地面積 × 植生比例"},
                {"label": "水平投影長", "key": "horizontal_run_m", "unit": "m", "decimals": 2,
                 "basis": "H / tanβ"},
                {"label": "坡面排水（含平台）", "key": "surface_drain_m", "unit": "m", "decimals": 2,
                 "basis": "坡長×(平台數+1) + 斜長×2"},
                {"label": "平台面積", "key": "bench_area_m2", "unit": "m2", "decimals": 2,
                 "basis": "平台寬 × 坡長 × 平台數"},
                {"label": "表層整地", "key": "excavation_m3", "unit": "m3", "decimals": 2,
                 "basis": "整地面積 × 剝皮厚度"},
            ],
            "note": "坡面斜長與水平投影由坡高與坡角換算；平台寬度為 0 時表示未設平台。",
        },
    },
    # ---------------------------------------------------------------- 道路
    "road": {
        "label": "道路／路面（線性鋪面）",
        "required": ["length_m", "width_avg_m", "area_m2", "thickness_cm", "volume_m3"],
        "derive": [
            {"key": "area_m2", "expr": "length_m * width_avg_m", "verify_tol_pct": 1.0,
             "note": "實測面積不一定剛好等於 L×W，故用驗算式"},
            {"key": "volume_m3", "expr": "area_m2 * thickness_cm / 100", "verify_tol_pct": 1.0},
        ],
        "table": {
            "caption": "工程數量表",
            "rows": [
                {"label": "全線長度 L", "key": "length_m", "unit": "m", "decimals": 2,
                 "basis": "沿設計中心線量測"},
                {"label": "平均寬度 W", "key": "width_avg_m", "unit": "m", "decimals": 2,
                 "basis": "逐斷面量測平均"},
                {"label": "鋪面面積 A", "key": "area_m2", "unit": "m²", "decimals": 1,
                 "basis": "設計中心線與左右邊界圍面積算"},
                {"label": "鋪築厚度 t", "key": "thickness_cm", "unit": "cm", "decimals": 1,
                 "basis": "設計指定"},
                {"label": "鋪築體積 V", "key": "volume_m3", "unit": "m³", "decimals": 2,
                 "basis": "V = A × t"},
            ],
            "note": "本表為設計數量，未含拌合損耗、鬆散係數、試驗段用量與預備數量。",
        },
        "notes": [
            "道路型：數量結構為 長度／寬度／面積／厚度／體積。",
            "面積與體積採「驗算」而非「定義」，因實測值有量測誤差。",
        ],
    },

    # ------------------------------------------------------------- 擋土牆
    "wall": {
        "label": "擋土牆（重力／半重力／懸臂／扶壁／錨定／加勁，每米斷面）",
        "required": ["length_m", "height_m"],
        "required_by_type": {
            "gravity": ["length_m", "height_m", "stem_thickness_m",
                        "base_width_m"],
            "semigravity": ["length_m", "height_m", "top_width_m",
                            "base_width_m", "base_thickness_m"],
            "cantilever": ["length_m", "height_m", "stem_thickness_m",
                           "base_width_m", "base_thickness_m"],
            "counterfort": ["length_m", "height_m", "stem_thickness_m",
                            "base_width_m", "base_thickness_m", "toe_length_m",
                            "counterfort_spacing_m", "counterfort_thickness_m",
                            "counterfort_top_width_m"],
            "anchored": ["length_m", "height_m", "wall_thickness_m",
                         "base_width_m", "base_thickness_m",
                         "anchor_depths_m", "horizontal_spacing_m"],
            "mse": ["length_m", "height_m", "face_panel_thickness_m",
                    "reinforcement_length_m", "vertical_spacing_m",
                    "long_term_strength_kN_per_m"],
        },
        "_wall_type_note": "wall_type：gravity／semigravity／cantilever／counterfort／"
                           "anchored／mse。斷面積與配筋依型別自動切換。",
        "derive": [
            # 斷面積（m²/m）
            #  gravity    ：梯形斷面 = (頂寬 + 底寬)/2 × 牆高        （T=頂寬、base_width=底寬）
            #  cantilever ：牆身 = T×H，另加底板 = base_width × base_thickness
            {"key": "section_area_m2", "expr":
                "(stem_thickness_m + base_width_m) / 2 * height_m"
                " if wall_type == 'gravity' else ("
                "base_width_m * base_thickness_m"
                " + top_width_m * (height_m - base_thickness_m)"
                " + 0.5 * (front_batter_ratio + back_batter_ratio)"
                " * (height_m - base_thickness_m) ** 2"
                " if wall_type == 'semigravity' else "
                "stem_thickness_m * height_m + base_width_m * base_thickness_m"
                " if wall_type == 'cantilever' else ("
                "base_width_m * base_thickness_m + stem_thickness_m * height_m"
                " + 0.5 * ((base_width_m - toe_length_m - stem_thickness_m)"
                " + counterfort_top_width_m) * height_m"
                " * counterfort_thickness_m / counterfort_spacing_m)"
                " if wall_type == 'counterfort' else ("
                "wall_thickness_m * (height_m - base_thickness_m)"
                " + base_width_m * base_thickness_m)"
                " if wall_type == 'anchored' else ("
                "face_panel_thickness_m * height_m"
                " if facing_type != 'segmented_block' else 0.0))",
             "verify_tol_pct": 0,
             "note": "gravity＝(T+B)/2×H；semigravity＝底板 B×d＋牆身 T×(H-d)"
                     "＋前後坡三角形；cantilever＝T×H＋B×BT；"
                     "counterfort＝底板＋牆板＋扶壁分攤；anchored＝牆面＋基腳；"
                     "mse＝RC 面版"},
            # 圖／數對帳用：S-01/S-02 畫的是「兩扶壁間」的實體斷面，
            # 不含扶壁分攤（扶壁以虛線表示）。混凝土體積仍用
            # section_area_m2（含扶壁），兩者差額在備註說明。
            {"key": DRAWN_SECTION_AREA_KEY, "expr":
                "section_area_m2 - 0.5 * ((base_width_m - toe_length_m - stem_thickness_m)"
                " + counterfort_top_width_m) * height_m * counterfort_thickness_m"
                " / counterfort_spacing_m"
                " if wall_type == 'counterfort' else section_area_m2",
             "verify_tol_pct": 0,
             "note": "扶壁式取兩扶壁間標準斷面；其餘牆型同 section_area_m2"},

            # 混凝土體積（扣排水孔）
            {"key": "concrete_volume_m3_per_m", "expr": "section_area_m2",
             "verify_tol_pct": 0, "note": "未扣排水孔；扣孔後另計"},
            {"key": "face_area_m2", "expr": "height_m * length_m",
             "verify_tol_pct": 0, "note": "牆面面積（露出面）"},
            {"key": "wall_thickness_eff_m", "expr":
                "stem_thickness_m if (wall_type == 'gravity' or wall_type == 'semigravity'"
                " or wall_type == 'cantilever' or wall_type == 'counterfort')"
                " else (wall_thickness_m if wall_type == 'anchored' else face_panel_thickness_m)",
             "verify_tol_pct": 0, "note": "排水孔深度用的牆體厚度"},
            {"key": "base_width_eff_m", "expr":
                "reinforcement_length_m if wall_type == 'mse' else base_width_m",
             "verify_tol_pct": 0, "note": "MSE 以加勁區長度作為計畫寬度"},
            {"key": "base_thickness_eff_m", "expr":
                "0.0 if wall_type == 'mse' else base_thickness_m",
             "verify_tol_pct": 0},
            {"key": "weep_hole_count", "expr": "ceil(face_area_m2 / 2)",
             "verify_tol_pct": 0,
             "note": "水土保持技術規範第121條：每 2 m² 牆面至少 1 孔"},
            {"key": "weep_area_m3", "expr":
                "weep_hole_count * pi * (weep_diameter_m / 2) ** 2 * wall_thickness_eff_m",
             "verify_tol_pct": 0, "note": "排水孔扣除體積（孔深＝牆厚）"},
            {"key": "concrete_volume_m3", "expr":
                "concrete_volume_m3_per_m * length_m - weep_area_m3",
             "verify_tol_pct": 0, "note": "淨混凝土體積"},
            {"key": "concrete_volume_m3_per_m_net", "expr":
                "concrete_volume_m3_per_m"
                " - (weep_hole_count / length_m) * pi * (weep_diameter_m / 2) ** 2 * wall_thickness_eff_m",
             "verify_tol_pct": 0,
             "note": "淨每米體積（已扣排水孔）—— 可直接與 3D 模型量測值對帳"},

            # 規範配置（可直接進數量表）
            {"key": "expansion_joint_count", "expr": "max(1, floor(length_m / 25))",
             "verify_tol_pct": 0,
             "note": "第121條：長度每 20~40 m 一處，取較嚴 25 m"},
            {"key": "counterfort_count", "expr":
                "ceil(length_m / counterfort_spacing_m) + 1"
                " if wall_type == 'counterfort' else 0",
             "verify_tol_pct": 0, "note": "扶壁道數（含兩端）"},
            {"key": "anchor_count", "expr":
                "(ceil(length_m / horizontal_spacing_m) + 1) * len(anchor_depths_m)"
                " if wall_type == 'anchored' else 0",
             "verify_tol_pct": 0, "note": "地錨支數＝每排支數×排數"},
            {"key": "anchor_drilling_m", "expr":
                "anchor_count * (free_length_m + bond_length_m)"
                " if wall_type == 'anchored' else 0",
             "verify_tol_pct": 0, "note": "地錨鑽孔總長（自由段＋錨碇段）"},
            {"key": "mse_layer_count", "expr":
                "floor((height_m - 0.001 - first_layer_m) / vertical_spacing_m) + 1"
                " if wall_type == 'mse' else 0",
             "verify_tol_pct": 0, "note": "加勁材層數"},
            {"key": "mse_reinforcement_area_m2", "expr":
                "mse_layer_count * reinforcement_length_m * length_m"
                " if wall_type == 'mse' else 0",
             "verify_tol_pct": 0, "note": "加勁材面積（舖設量）"},

            # 模板／開挖／背填
            {"key": "formwork_m2", "expr":
                "(0.0 if wall_type == 'mse' and facing_type == 'segmented_block' else ("
                "height_m * length_m if wall_type == 'mse' else "
                "height_m * length_m + 2 * section_area_m2 + "
                "2 * 0.5 * ((base_width_m - toe_length_m - stem_thickness_m)"
                " + counterfort_top_width_m) * height_m"
                " / counterfort_spacing_m * length_m))",
             "verify_tol_pct": 0,
             "note": "正面（貼土背不計）＋兩端斷面；扶壁另加兩側扶壁模板；"
                     "MSE 預鑄面版不計場鑄模板"},
            {"key": "template_per_meter", "expr": "formwork_m2 / length_m",
             "verify_tol_pct": 0, "note": "模板每延米"},
            {"key": "excavation_m3", "expr":
                "(reinforcement_length_m + 2 * excavation_work_m)"
                " * (height_m + excavation_depth_m) * length_m"
                " if wall_type == 'mse' else "
                "(base_width_m + 2 * excavation_work_m)"
                " * (base_thickness_m + excavation_depth_m) * length_m",
             "verify_tol_pct": 0,
             "note": "基礎開挖（含兩側工作面 0.3 m、超挖 0.1 m）；"
                     "MSE 以加勁區全寬與牆高估算"},
            {"key": "backfill_gravel_m3", "expr":
                "length_m * height_m * reinforcement_length_m"
                " if wall_type == 'mse' else "
                "length_m * height_m * backfill_thickness_m",
             "verify_tol_pct": 0,
             "note": "背填透水性材料（級配碎石）厚度 0.3 m；"
                     "MSE 表列加勁區填方體積"},

            # 鋼筋（以單位體積含鋼量估算，須以配筋圖覆核）
            {"key": "rebar_kg", "expr": "rebar_ratio_kg_m3 * concrete_volume_m3",
             "verify_tol_pct": 0,
             "note": "重力式擋土牆通常僅構造筋；含鋼量取假設值，須以配筋圖覆核"},
        ],
        "defaults": {
            "wall_type": "cantilever",
            "stem_thickness_m": 0.0,
            "base_width_m": 0.0,
            "base_thickness_m": 0.0,
            "top_width_m": 0.30,              # 半重力式牆頂寬
            "front_batter_ratio": 0.30,       # 半重力式牆面坡度 1:S1
            "back_batter_ratio": 0.0,         # 半重力式牆背坡度 1:S2
            "toe_projection_m": 0.50,         # 基腳前端突出
            "toe_soil_depth_m": 1.50,         # 牆趾處覆土深度
            "weep_diameter_m": 0.05,          # 第121條 直徑 >= 5 cm
            "backfill_thickness_m": 0.30,
            "excavation_work_m": 0.30,
            "excavation_depth_m": 0.10,
            "rebar_ratio_kg_m3": 40.0,        # 假設值，須以配筋圖覆核
            "toe_length_m": 1.00,
            "counterfort_spacing_m": 3.00,
            "counterfort_thickness_m": 0.40,
            "counterfort_top_width_m": 0.30,
            "front_soil_depth_m": 0.50,
            "wall_thickness_m": 0.40,
            "anchor_depths_m": [1.5, 3.5, 5.5],
            "horizontal_spacing_m": 2.50,
            "inclination_deg": 20.0,
            "face_panel_thickness_m": 0.20,
            "reinforcement_length_m": 4.20,
            "vertical_spacing_m": 0.60,
            "first_layer_m": 0.30,
            "long_term_strength_kN_per_m": 40.0,
            "coverage_ratio": 1.0,
            "embedment_m": 0.60,
            "facing_type": "precast_panel",
            "free_length_m": 7.00,
            "bond_length_m": 6.00,
        },
        "table": {
            "caption": "工程數量表（擋土牆，每米斷面 × 牆長）",
            "rows": [
                {"label": "牆型", "key": "wall_type", "unit": "", "decimals": None,
                 "basis": "gravity／semigravity／cantilever／counterfort／anchored／mse"},
                {"label": "牆長 L", "key": "length_m", "unit": "m", "decimals": 1,
                 "basis": "設計假設（配合伸縮縫分段）"},
                {"label": "牆高 H（有效高）", "key": "height_m", "unit": "m", "decimals": 2,
                 "basis": "斷面設計值；第118條有效高"},
                {"label": "牆身／面版厚 T", "key": "wall_thickness_eff_m", "unit": "m", "decimals": 2,
                 "basis": "斷面設計值；半重力式以 top_width_m 表示牆頂寬"},
                {"label": "底板寬／加勁長 BL", "key": "base_width_eff_m", "unit": "m", "decimals": 2,
                 "basis": "斷面設計值；MSE 為加勁材長度"},
                {"label": "底板厚 BT", "key": "base_thickness_eff_m", "unit": "m", "decimals": 2,
                 "basis": "斷面設計值"},
                {"label": "混凝土斷面積", "key": "section_area_m2", "unit": "m²/m", "decimals": 3,
                 "basis": "T×H + BL×BT"},
                {"label": "混凝土淨體積", "key": "concrete_volume_m3", "unit": "m³", "decimals": 2,
                 "basis": "斷面積×L，扣排水孔"},
                {"label": "鋼筋（設計，含搭接損耗）", "key": "rebar_kg_design",
                 "unit": "kg", "decimals": 1,
                 "basis": "配筋設計 kg/m × 牆長；牆體含 6% 搭接、錨定與損耗"},
                {"label": "鋼筋（每延米）", "key": "rebar_kg_per_m_design",
                 "unit": "kg/m", "decimals": 2,
                 "basis": "配筋設計值，已含 6% 搭接與損耗"},
                {"label": "模板", "key": "formwork_m2", "unit": "m²", "decimals": 2,
                 "basis": "正面＋頂面＋兩端；牆背貼土不計"},
                {"label": "模板（每延米）", "key": "template_per_meter",
                 "unit": "m²/m", "decimals": 2,
                 "basis": "模板總量 ÷ 牆長"},
                {"label": "基礎開挖", "key": "excavation_m3", "unit": "m³", "decimals": 2,
                 "basis": "含兩側工作面 0.3 m、超挖 0.1 m"},
                {"label": "背填級配碎石", "key": "backfill_gravel_m3", "unit": "m³", "decimals": 2,
                 "basis": "L×H×0.3 m（透水性材料）"},
                {"label": "排水孔 Ø5 cm", "key": "weep_hole_count", "unit": "孔", "decimals": 0,
                 "basis": "第121條：每 2 m² 牆面 1 孔"},
                {"label": "伸縮縫", "key": "expansion_joint_count", "unit": "處", "decimals": 0,
                 "basis": "第121條：每 20~40 m 一處（取 25 m）"},
                {"label": "扶壁道數", "key": "counterfort_count", "unit": "道", "decimals": 0,
                 "basis": "含兩端；中心距 × (n−1) + 端部", "show_if": {"wall_type": "counterfort"}},
                {"label": "地錨支數", "key": "anchor_count", "unit": "支", "decimals": 0,
                 "basis": "每排 (L/水平間距+1) 支 × 排數", "show_if": {"wall_type": "anchored"}},
                {"label": "地錨鑽孔長", "key": "anchor_drilling_m", "unit": "m", "decimals": 1,
                 "basis": "支數 ×（自由段＋錨碇段）", "show_if": {"wall_type": "anchored"}},
                {"label": "加勁材層數", "key": "mse_layer_count", "unit": "層", "decimals": 0,
                 "basis": "由牆高、第一層高程與層距推算", "show_if": {"wall_type": "mse"}},
                {"label": "加勁材面積", "key": "mse_reinforcement_area_m2", "unit": "m²", "decimals": 1,
                 "basis": "層數 × 加勁長 × 牆長", "show_if": {"wall_type": "mse"}},
            ],
            "note": "混凝土體積已扣排水孔；鋼筋為配筋設計值（重力式與半重力式為名目"
                    "構造鋼筋，其餘 RC 牆型為構材撓曲配筋），已含 6% 搭接損耗；"
                    "rebar_kg（含鋼量假設值）僅作交叉檢查，不進預算。",
        },
        "notes": [
            "擋土牆型：數量結構為「每米斷面 × 牆長」，並含排水孔、伸縮縫、模板、開挖、背填。",
            "排水孔與伸縮縫依水土保持技術規範第121條直接計算（不依賴土工參數）。",
            "模板假設牆背貼土不計模板；若牆背需雙面模板，formwork_m2 要改算式。",
            "MSE 的背填級配碎石欄位表列加勁區填方體積；RC 面版配筋只計面版，"
            "不含面版連接器與加勁材材料費。",
            "鋼筋量一律採 rebar_kg_design（rc_design.design_wall_rebar 依牆型分流）；"
            "rebar_kg 的含鋼量假設值只保留作交叉檢查，不得再進預算。",
        ],
    },

    # ------------------------------------------------------------- 箱涵
    "box_culvert": {
        "label": "箱涵（單孔／雙孔／三孔，每米斷面）",
        "required": ["length_m", "cell_count", "clear_width_m", "clear_height_m",
                     "wall_thickness_m", "top_slab_thickness_m",
                     "bottom_slab_thickness_m"],
        "defaults": {
            "interior_wall_thickness_m": 0.30,
            "cover_depth_m": 0.60,
            "excavation_work_m": 0.50,
            "excavation_depth_m": 0.30,
            "rebar_ratio_kg_m3": 90.0,
            # 內角 45° 加腋（倒角）邊長：過往標準圖 300×200 箱涵用 20 cm、
            # 400×300 用 30 cm。設 0 表示不做加腋。
            "inner_chamfer_m": 0.20,
            # 角隅補強筋（X 形交叉斜筋）：做法依標準圖 C110／C111。
            "corner_rebar": "D13",
            "corner_rebar_spacing_mm": 200,
        },
        "derive": [
            {"key": "outer_width_m", "expr":
                "2 * wall_thickness_m + cell_count * clear_width_m"
                " + (cell_count - 1) * interior_wall_thickness_m",
             "verify_tol_pct": 0,
             "note": "外寬＝外牆×2＋淨寬×孔數＋內隔牆×(孔數−1)"},
            {"key": "outer_height_m", "expr":
                "bottom_slab_thickness_m + clear_height_m + top_slab_thickness_m",
             "verify_tol_pct": 0,
             "note": "外高＝底板厚＋淨高＋頂版厚"},
            {"key": "concrete_area_m2", "expr":
                "outer_width_m * outer_height_m"
                " - cell_count * (clear_width_m * clear_height_m"
                " - 2 * inner_chamfer_m ** 2)",
             "verify_tol_pct": 0,
             "note": "精確斷面積＝外框矩形－各孔淨空矩形"
                     "（內角 45° 加腋每角扣 c²/2；不按桿件中心線相加）"},
            {"key": "concrete_volume_m3", "expr":
                "concrete_area_m2 * length_m",
             "verify_tol_pct": 0},
            {"key": "cell_clear_area_m2", "expr":
                "cell_count * clear_width_m * clear_height_m",
             "verify_tol_pct": 0},
            {"key": "soil_cover_volume_m3", "expr":
                "outer_width_m * cover_depth_m * length_m",
             "verify_tol_pct": 0,
             "note": "頂版以上覆土體積（不含路面結構）"},
            {"key": "formwork_m2", "expr":
                "cell_count * (2 * (clear_width_m - 2 * inner_chamfer_m)"
                " + 2 * (clear_height_m - 2 * inner_chamfer_m)"
                " + 4 * inner_chamfer_m * sqrt(2)) * length_m"
                " + 2 * concrete_area_m2",
             "verify_tol_pct": 0,
             "note": "頂版底面＋底板頂面＋牆內面＋內角加腋斜面，另加兩端斷面；"
                     "外側埋土面不計"},
            {"key": "excavation_m3", "expr":
                "(outer_width_m + 2 * excavation_work_m)"
                " * (outer_height_m + excavation_depth_m) * length_m",
             "verify_tol_pct": 0,
             "note": "箱涵基礎開挖（含兩側工作面與超挖）"},
            {"key": "base_area_m2", "expr": "outer_width_m * length_m",
             "verify_tol_pct": 0},
            {"key": "expansion_joint_count", "expr": "max(1, floor(length_m / 25))",
             "verify_tol_pct": 0,
             "note": "比照水土保持技術規範第121條伸縮縫間距；實際仍依結構配置調整"},
            {"key": "rebar_kg", "expr": "rebar_ratio_kg_m3 * concrete_volume_m3",
             "verify_tol_pct": 0,
             "note": "含鋼量假設值，須以箱涵構架配筋結果覆核"},
        ],
        "table": {
            "caption": "工程數量表（箱涵，每米斷面 × 涵長）",
            "rows": [
                {"label": "孔數", "key": "cell_count", "unit": "孔", "decimals": 0,
                 "basis": "1～3 孔共用同一構架模型"},
                {"label": "涵長", "key": "length_m", "unit": "m", "decimals": 1,
                 "basis": "沿水流方向之箱涵長度"},
                {"label": "每孔淨寬", "key": "clear_width_m", "unit": "m", "decimals": 2,
                 "basis": "設計淨寬"},
                {"label": "每孔淨高", "key": "clear_height_m", "unit": "m", "decimals": 2,
                 "basis": "設計淨高"},
                {"label": "外牆厚", "key": "wall_thickness_m", "unit": "m", "decimals": 2,
                 "basis": "設計值"},
                {"label": "內隔牆厚", "key": "interior_wall_thickness_m", "unit": "m", "decimals": 2,
                 "basis": "多孔箱涵共用牆"},
                {"label": "頂版厚", "key": "top_slab_thickness_m", "unit": "m", "decimals": 2,
                 "basis": "設計值"},
                {"label": "底板厚", "key": "bottom_slab_thickness_m", "unit": "m", "decimals": 2,
                 "basis": "設計值"},
                {"label": "外寬", "key": "outer_width_m", "unit": "m", "decimals": 2,
                 "basis": "外框矩形寬"},
                {"label": "外高", "key": "outer_height_m", "unit": "m", "decimals": 2,
                 "basis": "底板厚＋淨高＋頂版厚"},
                {"label": "混凝土斷面積", "key": "concrete_area_m2", "unit": "m²/m", "decimals": 3,
                 "basis": "外框矩形－孔洞矩形"},
                {"label": "混凝土體積", "key": "concrete_volume_m3", "unit": "m³", "decimals": 2,
                 "basis": "斷面積×涵長"},
                {"label": "模板", "key": "formwork_m2", "unit": "m²", "decimals": 2,
                 "basis": "頂版底面＋底板頂面＋牆內面＋兩端"},
                {"label": "內角 45° 加腋", "key": "inner_chamfer_m", "unit": "m",
                 "decimals": 2,
                 "basis": "內角倒角邊長；標準圖 300×200 用 0.20、400×300 用 0.30"},
                {"label": "基礎開挖", "key": "excavation_m3", "unit": "m³", "decimals": 2,
                 "basis": "含工作面與超挖"},
                {"label": "頂版覆土", "key": "soil_cover_volume_m3", "unit": "m³", "decimals": 2,
                 "basis": "外寬×覆土深×涵長"},
                {"label": "伸縮縫", "key": "expansion_joint_count", "unit": "處", "decimals": 0,
                 "basis": "每 25 m 一處（假設）"},
                {"label": "鋼筋（設計，含搭接損耗）", "key": "rebar_kg_design",
                 "unit": "kg", "decimals": 1,
                 "basis": "逐面構架配筋；損耗率見 rebar_loss_rate"},
            ],
            "note": "本表不含翼牆、擋土牆、基礎地盤改良、保護工與損耗；箱涵結構檢核另見 tools\\design\\box_culvert.py。",
        },
        "notes": [
            "箱涵以每米斷面的二維平面剛架分析，孔數只改變構架拓樸。",
            "混凝土量採外框減孔洞的精確公式，不得用桿件中心線長度相加。",
            "鋼筋含鋼量預設 90 kg/m³ 僅供交叉檢查；預算與報告均採"
            " rebar_kg_design（含 6% 搭接損耗）與 formwork_m2_design。",
        ],
    },

    # ------------------------------------------------------------- 排水溝
    "channel": {
        "label": "排水溝（U 型／矩型，每米斷面）",
        "required": ["length_m", "inner_width_m", "depth_m",
                     "wall_thickness_m", "base_thickness_m"],
        "derive": [
            {"key": "section_area_m2", "expr":
                "2 * wall_thickness_m * depth_m"
                " + base_thickness_m * (inner_width_m + 2 * wall_thickness_m)",
             "verify_tol_pct": 0, "note": "U 型溝：兩側溝壁 + 溝底"},
            {"key": "concrete_volume_m3_per_m", "expr": "section_area_m2",
             "verify_tol_pct": 0},
            {"key": "concrete_volume_m3", "expr": "concrete_volume_m3_per_m * length_m",
             "verify_tol_pct": 0},
            {"key": "formwork_m2", "expr":
                "2 * depth_m * length_m + inner_width_m * length_m",
             "verify_tol_pct": 0, "note": "溝內側兩壁 + 溝底（外側貼土不計）"},
            {"key": "excavation_m3", "expr":
                "(inner_width_m + 2 * wall_thickness_m + 2 * excavation_work_m)"
                " * (depth_m + base_thickness_m + excavation_depth_m) * length_m",
             "verify_tol_pct": 0},
            {"key": "expansion_joint_count", "expr": "max(1, floor(length_m / 25))",
             "verify_tol_pct": 0, "note": "比照第121條伸縮縫間距"},
            {"key": "cross_drain_count", "expr": "max(1, ceil(length_m / cross_drain_spacing_m))",
             "verify_tol_pct": 0,
             "note": "水保第78條二(一)：橫向排水以每 150 m 一處為原則"},
            {"key": "rebar_kg", "expr": "rebar_ratio_kg_m3 * concrete_volume_m3",
             "verify_tol_pct": 0, "note": "假設值（同擋土牆）"},
        ],
        "defaults": {
            "excavation_work_m": 0.30,
            "excavation_depth_m": 0.10,
            "rebar_ratio_kg_m3": 40.0,
            "cross_drain_spacing_m": 150.0,
        },
        "table": {
            "caption": "工程數量表（排水溝，每米斷面 × 溝長）",
            "rows": [
                {"label": "溝長 L", "key": "length_m", "unit": "m", "decimals": 1, "basis": "設計長度"},
                {"label": "內寬 B", "key": "inner_width_m", "unit": "m", "decimals": 2, "basis": "設計值"},
                {"label": "溝深 H", "key": "depth_m", "unit": "m", "decimals": 2, "basis": "設計值"},
                {"label": "溝壁厚", "key": "wall_thickness_m", "unit": "m", "decimals": 2, "basis": "設計值"},
                {"label": "溝底厚", "key": "base_thickness_m", "unit": "m", "decimals": 2, "basis": "設計值"},
                {"label": "混凝土斷面積", "key": "section_area_m2", "unit": "m²/m", "decimals": 3, "basis": "2×t×H + tb×(B+2t)"},
                {"label": "混凝土體積", "key": "concrete_volume_m3", "unit": "m³", "decimals": 2, "basis": "斷面積×L"},
                {"label": "模板", "key": "formwork_m2", "unit": "m²", "decimals": 2, "basis": "溝內側兩壁＋溝底"},
                {"label": "基礎開挖", "key": "excavation_m3", "unit": "m³", "decimals": 2, "basis": "含工作面"},
                {"label": "伸縮縫", "key": "expansion_joint_count", "unit": "處", "decimals": 0, "basis": "每 25 m 一處"},
                {"label": "橫向排水", "key": "cross_drain_count", "unit": "處", "decimals": 0, "basis": "每 150 m 一處（水保第78條二(一)）"},
                {"label": "鋼筋（估算）", "key": "rebar_kg", "unit": "kg", "decimals": 1, "basis": "含鋼量假設值"},
            ],
            "note": "本表未含損耗與預備數量。",
        },
        "notes": [
            "排水溝型：數量結構為「每米斷面 × 溝長」，含模板、開挖、伸縮縫、橫向排水。",
            "U 型溝斷面假設矩形內腔；若是標準 U 型溝（含斜角），section_area_m2 要改算式。",
        ],
    },
}


def get(model):
    m = MODELS.get(model)
    if not m:
        raise KeyError(f"未知的數量模型 {model!r}；可用：{', '.join(MODELS)}")
    return m


def derive_all(model, values):
    """回傳 (已補齊的 values, issues)。issues: [{level, msg}]"""
    m = get(model)
    out = dict(m.get("defaults") or {})
    supplied = dict(values or {})
    out.update(supplied)
    issues = []

    by_type = m.get("required_by_type") or {}
    required = by_type.get(str(out.get("wall_type") or "").strip().lower(),
                           m["required"])
    for k in required:
        if supplied.get(k) in (None, ""):
            issues.append({"level": "error",
                           "msg": f"quantities.{model} 缺少必要輸入 {k}"})

    evaluated = {}
    for rule in m["derive"]:
        key, expr = rule["key"], rule["expr"]
        try:
            v = safe_eval(expr, {**out, **evaluated})
        except Exception as ex:
            issues.append({"level": "error",
                           "msg": f"衍生量 {key} 計算失敗：{ex}"})
            continue
        tol = float(rule.get("verify_tol_pct") or 0)
        given = out.get(key)
        if tol > 0 and given not in (None, ""):
            try:
                diff = abs(float(given) - float(v)) / max(abs(float(v)), 1e-9) * 100
            except Exception:
                diff = None
            if diff is not None and diff > tol:
                issues.append({"level": "error",
                               "msg": f"{key}：宣告值 {given} 與算式 {expr} = {v:.4g} "
                                      f"差 {diff:.2f}% > 容差 {tol}%"})
            evaluated[key] = given            # 實測值優先
        else:
            evaluated[key] = round(float(v), 6) if isinstance(v, float) else v

    out.update(evaluated)
    return out, issues


def describe(model):
    """給文件／CLI 用的模型摘要。"""
    m = get(model)
    lines = [f"模型 {model}：{m['label']}",
             f"  必要輸入：{', '.join(m['required'])}"]
    for rule in m["derive"]:
        lines.append(f"  衍生 {rule['key']:28s} = {rule['expr']}")
    for n in m.get("notes") or []:
        lines.append(f"  · {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in MODELS:
        print(describe(sys.argv[1]))
    else:
        print("可用模型：")
        for k, v in MODELS.items():
            print(f"  {k:10s} {v['label']}")
        print("\n用法：python qty_models.py <model>")
