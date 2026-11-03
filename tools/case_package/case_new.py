r"""從零建立新案件的骨架（`case.json`），不必手抄一份 400 行的 JSON。

為什麼要這個模組
----------------
`case.json`（`civil-case/1`）是三大交付的唯一來源，但它有 project／quantities／
boq／report 四大段、幾十個欄位。目前開新案的做法是「複製既有案件再改」——
那會把上一個案件的工程名稱、座標、數量、注意事項一起帶進來，很容易漏改。

本模組依模型（road／wall／channel）產生**最小但可跑**的骨架：
  · `quantities.values` 只填必要輸入（其餘由 `qty_models` 的 defaults 補）
  · `boq.items` 依類別產生對應工項（數量用 `qty_from` 綁模型衍生值）
  · `report` 只給最低限度，其餘由 `case_core.derive_report()` 補齊
  · 所有 `_note` 明確標示「哪些數字是範例、開案前必須改」

產出後立刻跑 `case_core.consistency()` 自檢，0 error 才算成功。

用法
----
    python tools\case_package\case_new.py wall --name 擋土牆4m重力式 ^
        --height 4.0 --stem 0.45 --base 2.6 --length 30
    python tools\case_package\case_new.py channel --name 排水溝U型B06 ^
        --inner-width 0.6 --depth 1.0 --length 80
    python tools\case_package\case_new.py road --name AC刨鋪3cm ^
        --length 120 --width 5.0 --thickness 3
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "case_package"))


def _base(model, name, category):
    return {
        "schema": "civil-case/1",
        "_note": ("本檔由 tools\\case_package\\case_new.py 產生（骨架）。"
                  "標「範例」的數字必須改成實際設計值；數量由 qty_models 派生，"
                  "只需改 quantities.values 的輸入，boq／report 會自動跟隨。"),
        "project": {
            "name": name,
            "full_name": "%s（請改為正式工程名稱）" % name,
            "category": category,
            "client": "（委託單位待填）",
            "designer": "（設計者待填）",
            "contractor": "",
            "agency": "（主辦機關待填）",
            "date": "（日期待填，如 114.10.28）",
            # location 是物件（derive_boq 會取 .desc），不是字串
            "location": {"county": "（縣市）", "town": "（鄉鎮市區）",
                         "village": "（村里）", "section": "（地段）",
                         "desc": "（地點描述，會印在預算書封面）"},
            "crs": {"name": "TWD97 TM2 二度分帶", "epsg": "EPSG:3826", "unit": "公尺"},
            "coords": [],
            "report_title": "設計報告書",
            "report_subtitle": "%s" % category,
        },
        "quantities": {"model": model, "values": {}, "notes": []},
        "boq": {"items": []},
        "report": {},
    }


def _boq(items):
    out = []
    for i, it in enumerate(items, 1):
        it = dict(it)
        it["no"] = "%02d" % i
        out.append(it)
    return out


def build_road(name, length, width, thickness):
    case = _base("road", name, "道路")
    area = round(length * width, 2)
    vol = round(area * thickness / 100.0, 2)
    case["quantities"]["values"] = {
        "length_m": length, "width_avg_m": width,
        "area_m2": area, "thickness_cm": thickness, "volume_m3": vol,
        "tolerance_pct": 1.0,
    }
    case["quantities"]["notes"] = [
        "長度／寬度為**範例值**（L=%.1f m、W=%.2f m）。若為實測成果，"
        "應由 `AC刨鋪5cm工程\\model\\road_edges_meta.json` 的實測邊線重新量測，"
        "並用 `tools\\takeoff\\paving_extent.py` 產生刨鋪範圍對帳。" % (length, width),
        "面積 A = L × W、體積 V = A × t，consistency() 會驗這兩式。",
    ]
    case["boq"]["items"] = _boq([
        {"name": "施工測量及放樣", "unit": "式", "qty": 1, "price": 4000.0,
         "note": "假設值，須詢價"},
        {"name": "瀝青混凝土面層刨除，厚%dcm（未含運費）" % thickness,
         "unit": "M2", "qty_from": "area_m2", "code": "0296140032", "price": 75.0,
         "note": "營建物價 11405 中部（刨除 5cm）；厚度不同須改代碼"},
        {"name": "瀝青黏層，快凝油溶瀝青 RC-70", "unit": "M2",
         "qty_from": "area_m2", "code": "0274711002", "price": 42.0,
         "note": "營建物價 11405 中部"},
        {"name": "瀝青混凝土舖面（第1類型密級配，粗粒料19.0mm，AC-10）",
         "unit": "T", "qty_from": "volume_m3", "code": "02742132A5", "price": 4500.0,
         "note": "營建物價 11405 中部；本項以體積（m³）計，須確認與噸數換算"},
        {"name": "標線復舊", "unit": "式", "qty": 1, "price": 8000.0,
         "note": "假設值，須詢價"},
        {"name": "交通維持及安全設施", "unit": "式", "qty": 1, "price": 15000.0,
         "note": "假設值，須詢價"},
        {"name": "機具進出場費", "unit": "式", "qty": 1, "price": 41800.0,
         "note": "經驗值"},
    ])
    return case


def build_wall(name, length, height, stem, base, base_t, wall_type,
               top_width=None, front_batter=0.30, back_batter=0.0,
               toe_projection=0.50, toe_soil_depth=1.50):
    case = _base("wall", name, "擋土牆")
    case["quantities"]["values"] = {
        "length_m": length, "height_m": height,
        "stem_thickness_m": stem, "base_width_m": base,
        "base_thickness_m": (0.0 if wall_type == "gravity" else base_t),
        "wall_type": wall_type,
    }
    if wall_type == "semigravity":
        case["quantities"]["values"].update({
            "top_width_m": top_width if top_width is not None else stem,
            "front_batter_ratio": front_batter,
            "back_batter_ratio": back_batter,
            "toe_projection_m": toe_projection,
            "toe_soil_depth_m": toe_soil_depth,
        })
    case["quantities"]["notes"] = [
        "尺寸為**範例值**：H=%.2f m、T=%.2f m、底寬=%.2f m、底板厚=%.2f m。"
        "正式設計前須用 `tools\\design\\retaining_wall.py` 的 `size_section()` 選配，"
        "並用 `tools\\design\\rc_design.py` 檢核裂縫。" % (
            height, stem, base, 0.0 if wall_type == "gravity" else base_t),
        "重力式為梯形斷面；半重力式為底板＋牆身＋前後坡；懸臂式為薄牆＋底板。"
        "斷面積會依 wall_type 自動切換。",
        "土工參數（γ、φ、c、容許承載力）未填 → 設計計算會用假設值，須補 `soil` 段。",
    ]
    case["boq"]["items"] = _boq([
        {"name": "擋土牆基礎開挖（含兩側工作面）", "unit": "m3",
         "qty_from": "excavation_m3", "price": 320.0, "note": "假設值，須詢價"},
        {"name": "結構用混凝土 fc'=210 kgf/cm2（含澆置）", "unit": "m3",
         "qty_from": "concrete_volume_m3", "price": 3200.0, "note": "假設值，須詢價"},
        {"name": "鋼筋及加工組立", "unit": "kg",
         "qty_from": "rebar_kg", "price": 32.0,
         "note": "假設值；數量為「含鋼量假設值×體積」，正式預算須以配筋設計值或詢價確認"},
        {"name": "模板（牆身與底板）", "unit": "m2",
         "qty_from": "formwork_m2", "price": 480.0, "note": "假設值，須詢價"},
        {"name": "背填級配碎石（分層夯實）", "unit": "m3",
         "qty_from": "backfill_gravel_m3", "price": 850.0, "note": "假設值，須詢價"},
        {"name": "排水孔（Ø5cm，含洩水管）", "unit": "孔",
         "qty_from": "weep_hole_count", "price": 350.0, "note": "假設值，須詢價"},
        {"name": "伸縮縫（填縫料及止水帶）", "unit": "處",
         "qty_from": "expansion_joint_count", "price": 3500.0, "note": "假設值，須詢價"},
        {"name": "施工測量及放樣", "unit": "式", "qty": 1, "price": 4000.0,
         "note": "假設值"},
        {"name": "機具進出場費", "unit": "式", "qty": 1, "price": 41800.0,
         "note": "經驗值"},
    ])
    return case


def build_channel(name, length, inner_w, depth, wall_t, base_t):
    case = _base("channel", name, "排水溝")
    case["quantities"]["values"] = {
        "length_m": length, "inner_width_m": inner_w, "depth_m": depth,
        "wall_thickness_m": wall_t, "base_thickness_m": base_t,
    }
    case["hydraulics"] = {
        "design_flow_m3s": 0.5, "slope": 0.005, "manning_n": 0.014,
        "_note": ("設計流量 0.5 m³/s 為**範例值**。正式設計須用 "
                  "`tools\\design\\hydrology.py`（水保第 16~19 條）由集水區面積、"
                  "重現期、降雨強度算出，並填 `catchment` 段。"),
    }
    case["catchment"] = {
        "P_mm": 2000, "T_year": 25, "area_ha": 2.0,
        "condition": "丘陵地或森林", "developed": False, "upper_c": False,
        "l_m": 100.0, "v_ms": 0.4, "L_km": 0.0, "H_km": 0.0,
        "_note": "集水區參數為**範例值**，須依現地條件改；P 應由等雨量線圖或鄰近雨量站查定。",
    }
    case["quantities"]["notes"] = [
        "尺寸為**範例值**：內寬 %.2f m、溝深 %.2f m、壁厚 %.2f m、底厚 %.2f m。"
        "正式設計前須用 `tools\\design\\channel_hydraulics.py` 的 `size_channel()` 選配。"
        % (inner_w, depth, wall_t, base_t),
        "設計流量由 `hydraulics`／`catchment` 決定；第 83 條重現期：坡地農地 10 年、其他非農業 25 年。",
        "排水溝檢核 8 項（容量／出水高／流速上下限／福祿數／邊溝坡度／側溝寬／側溝深）。",
    ]
    case["boq"]["items"] = _boq([
        {"name": "施工測量及放樣", "unit": "式", "qty": 1, "price": 4000.0,
         "note": "經驗值"},
        {"name": "排水溝基礎開挖（含兩側工作面）", "unit": "m3",
         "qty_from": "excavation_m3", "price": 320.0, "note": "假設值，須詢價"},
        {"name": "結構用混凝土 fc'=210 kgf/cm2（含澆置）", "unit": "m3",
         "qty_from": "concrete_volume_m3", "price": 3200.0, "note": "假設值，須詢價"},
        {"name": "鋼筋及加工組立", "unit": "kg",
         "qty_from": "rebar_kg", "price": 32.0,
         "note": "假設值；正式預算須以配筋設計值或詢價確認"},
        {"name": "模板（溝內側）", "unit": "m2",
         "qty_from": "formwork_m2", "price": 480.0, "note": "假設值，須詢價"},
        {"name": "伸縮縫（填縫料及止水帶）", "unit": "處",
         "qty_from": "expansion_joint_count", "price": 3500.0, "note": "假設值"},
        {"name": "橫向排水設施（含出口保護及消能）", "unit": "處",
         "qty_from": "cross_drain_count", "price": 12000.0,
         "note": "水保第78條二(一) 每 150 m 一處；假設值"},
        {"name": "機具進出場費", "unit": "式", "qty": 1, "price": 41800.0,
         "note": "經驗值"},
    ])
    return case


def build_box_culvert(name, length, cell_count, clear_w, clear_h, wall_t,
                      top_t, bottom_t, interior_t, cover):
    case = _base("box_culvert", name, "箱涵")
    case["quantities"]["values"] = {
        "length_m": length,
        "cell_count": cell_count,
        "clear_width_m": clear_w,
        "clear_height_m": clear_h,
        "wall_thickness_m": wall_t,
        "interior_wall_thickness_m": interior_t,
        "top_slab_thickness_m": top_t,
        "bottom_slab_thickness_m": bottom_t,
        "cover_depth_m": cover,
    }
    case["hydraulics"] = {
        "design_flow_m3s": 1.0,
        "slope": 0.005,
        "manning_n": 0.014,
        "freeboard_min_m": 0.20,
        "_note": ("設計流量 1.0 m³/s 為**範例值**。正式設計須以 "
                  "`tools\\design\\hydrology.py` 由集水區條件計算，"
                  "或由排水網路分析提供。"),
    }
    case["culvert"] = {
        "soil_unit_weight_kn_m3": 18.0,
        "soil_phi_deg": 30.0,
        "surcharge_kpa": 0.0,
        # 一定要指定車載重型式：只給 traffic_load_kpa 會被當成 custom 定值，
        # 看似有活載、其實不是 H-20／40T 的輪載換算（本專案曾因此漏計車載重）。
        "traffic_type": "h20",
        "traffic_load_kpa": 0.0,
        "traffic_lanes": 4,
        "groundwater_depth_m": None,
        "internal_water_depth_m": 0.0,
        "load_factor": 1.7,
        "_note": ("土工與車載重參數為**假設值**，須依鑽探、道路等級與實際覆土替換；"
                  "traffic_type 可選 h20／h20_s16／trailer_40t／none／custom。"),
    }
    case["quantities"]["notes"] = [
        "箱涵尺寸為**範例值**：%d 孔 %.2f m × %.2f m、涵長 %.1f m、覆土 %.2f m。"
        "正式設計前須用 `tools\\design\\box_culvert.py` 完成水力與平面構架檢核。"
        % (cell_count, clear_w, clear_h, length, cover),
        "混凝土量採外框矩形減孔洞；數量表不含翼牆、保護工與路面結構。",
        "鋼筋量採構架配筋設計值（含 6% 搭接與損耗），模板量含內壁、頂版底面、"
        "底板頂面與兩端斷面。",
        "設計流量與土工參數目前為假設值，未完成前不得當作正式設計。",
    ]
    case["boq"]["items"] = _boq([
        {"name": "施工測量及放樣", "unit": "式", "qty": 1, "price": 4000.0,
         "note": "經驗值"},
        {"name": "箱涵基礎開挖（含兩側工作面）", "unit": "m3",
         "qty_from": "excavation_m3", "price": 320.0, "note": "假設值，須詢價"},
        {"name": "結構用混凝土 fc'=280 kgf/cm2（含澆置）", "unit": "m3",
         "qty_from": "concrete_volume_m3", "price": 3500.0, "note": "假設值，須詢價"},
        {"name": "鋼筋及加工組立", "unit": "kg",
         "qty_from": "rebar_kg_design", "price": 32.0,
         "note": "採構架配筋設計值（含 6% 搭接與損耗）；單價為假設值，須詢價"},
        {"name": "模板（箱涵內壁、頂版底面及底板頂面）", "unit": "m2",
         "qty_from": "formwork_m2", "price": 520.0, "note": "假設值，須詢價"},
        {"name": "頂版覆土回填及夯實", "unit": "m3",
         "qty_from": "soil_cover_volume_m3", "price": 420.0, "note": "假設值，須詢價"},
        {"name": "伸縮縫（填縫料及止水帶）", "unit": "處",
         "qty_from": "expansion_joint_count", "price": 4500.0, "note": "假設值"},
        {"name": "機具進出場費", "unit": "式", "qty": 1, "price": 41800.0,
         "note": "經驗值"},
    ])
    return case


def build_slope(name, length, height, angle):
    case = _base("slope", name, "邊坡")
    case["quantities"]["values"] = {
        "height_m": height, "slope_angle_deg": angle, "length_m": length,
        "bench_width_m": 0.0, "bench_count": 0.0, "vegetation_ratio": 1.0,
        "drain_spacing_m": 30.0, "excavation_work_m": 0.3,
    }
    case["quantities"]["notes"] = [
        "尺寸為**範例值**：坡高 %.2f m、坡角 %.1f°、坡長 %.1f m。"
        "正式設計前須用 `tools\\design\\slope_stability.py` 檢核，並以 "
        "`max_stable_angle()` 反算容許坡角。" % (height, angle, length),
        "土工參數（γ、φ、c、地下水位）未填 → 穩定分析會用假設值，須補 `soil` 段。",
        "坡高超過 5 m 依水保第 78 條應設計階段式邊坡及縱、橫向排水 → 填 bench_width_m／bench_count。",
    ]
    case["boq"]["items"] = _boq([
        {"name": "施工測量及放樣", "unit": "式", "qty": 1, "price": 4000.0,
         "note": "經驗值"},
        {"name": "坡面整地（含表土剝除）", "unit": "m3",
         "qty_from": "excavation_m3", "price": 180.0, "note": "假設值，須詢價"},
        {"name": "坡面植生（撒播／舖植）", "unit": "m2",
         "qty_from": "vegetation_area_m2", "price": 120.0, "note": "假設值，須詢價"},
        {"name": "坡面排水溝（含平台排水）", "unit": "m",
         "qty_from": "surface_drain_m", "price": 850.0, "note": "假設值，須詢價"},
        {"name": "機具進出場費", "unit": "式", "qty": 1, "price": 41800.0,
         "note": "經驗值"},
    ])
    return case


def main():
    ap = argparse.ArgumentParser(description="建立新案件骨架（case.json）")
    ap.add_argument("model", choices=["road", "wall", "channel", "box_culvert", "slope"])
    ap.add_argument("--name", required=True, help="案名（也是資料夾名）")
    ap.add_argument("--length", type=float, required=True, help="長度 m")
    # road
    ap.add_argument("--width", type=float, default=5.0, help="road：平均寬度 m")
    ap.add_argument("--thickness", type=float, default=5.0, help="road：厚度 cm")
    # wall
    ap.add_argument("--height", type=float, default=3.0, help="wall：牆高 m")
    ap.add_argument("--stem", type=float, default=0.35, help="wall：牆身厚 m")
    ap.add_argument("--base", type=float, default=1.95, help="wall：底寬 m")
    ap.add_argument("--base-thickness", type=float, default=0.36, help="wall：底板厚 m")
    ap.add_argument("--wall-type", default="cantilever",
                    choices=["gravity", "semigravity", "cantilever"])
    ap.add_argument("--top-width", type=float, default=None,
                    help="wall：半重力式牆頂寬 m（預設同 --stem）")
    ap.add_argument("--front-batter", type=float, default=0.30,
                    help="wall：半重力式牆面坡度 1:S1")
    ap.add_argument("--back-batter", type=float, default=0.0,
                    help="wall：半重力式牆背坡度 1:S2")
    ap.add_argument("--toe-projection", type=float, default=0.50,
                    help="wall：半重力式基腳前端突出 m")
    ap.add_argument("--toe-soil-depth", type=float, default=1.50,
                    help="wall：半重力式牆趾覆土深度 m")
    # channel
    ap.add_argument("--inner-width", type=float, default=0.5, help="channel：內寬 m")
    ap.add_argument("--depth", type=float, default=0.9, help="channel：溝深 m")
    ap.add_argument("--wall-thickness", type=float, default=None,
                    help="channel：壁厚 m（預設 0.15）／box_culvert：外牆厚 m（預設 0.35）")
    ap.add_argument("--base-thickness-c", type=float, default=0.15, help="channel：底厚 m")
    # box culvert
    ap.add_argument("--cell-count", type=int, default=1, choices=[1, 2, 3],
                    help="box_culvert：孔數")
    ap.add_argument("--clear-width", type=float, default=3.0,
                    help="box_culvert：每孔淨寬 m")
    ap.add_argument("--clear-height", type=float, default=2.5,
                    help="box_culvert：每孔淨高 m")
    ap.add_argument("--top-thickness", type=float, default=0.40,
                    help="box_culvert：頂版厚 m")
    ap.add_argument("--bottom-thickness", type=float, default=0.45,
                    help="box_culvert：底板厚 m")
    ap.add_argument("--interior-thickness", type=float, default=0.30,
                    help="box_culvert：內隔牆厚 m")
    ap.add_argument("--cover", type=float, default=0.60,
                    help="box_culvert：頂版覆土深 m")
    # slope
    ap.add_argument("--angle", type=float, default=30.0, help="slope：坡角 度")
    ap.add_argument("--out-root", default=os.path.join(ROOT, "cases"))
    ap.add_argument("--force", action="store_true", help="覆寫既有 case.json")
    a = ap.parse_args()

    if a.model == "road":
        case = build_road(a.name, a.length, a.width, a.thickness)
    elif a.model == "wall":
        case = build_wall(a.name, a.length, a.height, a.stem, a.base,
                          a.base_thickness, a.wall_type,
                          top_width=a.top_width,
                          front_batter=a.front_batter,
                          back_batter=a.back_batter,
                          toe_projection=a.toe_projection,
                          toe_soil_depth=a.toe_soil_depth)
    elif a.model == "channel":
        case = build_channel(a.name, a.length, a.inner_width, a.depth,
                             a.wall_thickness if a.wall_thickness is not None else 0.15,
                             a.base_thickness_c)
    elif a.model == "box_culvert":
        # 排水溝壁厚預設 0.15 m，但箱涵外牆沿用 0.15 m 會使剪力容量為 0；
        # 兩個模型的預設值必須分開，不能共用同一個 argparse default。
        wall_t = a.wall_thickness if a.wall_thickness is not None else 0.35
        case = build_box_culvert(
            a.name, a.length, a.cell_count, a.clear_width, a.clear_height,
            wall_t, a.top_thickness, a.bottom_thickness,
            a.interior_thickness, a.cover,
        )
    else:
        case = build_slope(a.name, a.length, a.height, a.angle)

    # 依模型自動加斷面圖設定，建完即可直接跑全軸
    if a.model in ("wall", "channel", "slope"):
        _fn = {"wall": "S-01_擋土牆標準斷面圖.dxf",
               "channel": "D-01_排水溝標準斷面圖.dxf",
               "slope": "E-01_邊坡標準斷面圖.dxf"}[a.model]
        case["section"] = {"scale": "auto", "out": "cases/%s/%s" % (a.name, _fn)}

    d = os.path.join(a.out_root, a.name)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "case.json")
    if os.path.exists(p) and not a.force:
        raise SystemExit("已存在 %s；要覆寫請加 --force" % p)
    json.dump(case, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已建立 %s" % p)

    import case_core as CC
    issues = CC.consistency(case)
    errs = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    print("一致性自檢：%d error / %d warn" % (len(errs), len(warns)))
    for i in issues:
        print("  [%s] %s" % (i["level"], i["msg"]))
    if errs:
        raise SystemExit(1)
    print("\n下一步：")
    print("  1. 改 quantities.values 的輸入（目前是範例值）")
    print("  2. python tools\\case_package\\case_package.py cases\\%s\\case.json" % a.name)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
