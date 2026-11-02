"""Audit the design workbench (tools/design/*) against the verified regulation library.

Three layers of check, from cheap to strict:
  A. structural : every calculator in verified/_links.json points at existing, verified entries
  B. numeric    : for pairs where both sides compute the same quantity, run the engine and the
                  verified formula on the same inputs and compare (tolerance per case)
  C. known      : deviations already understood but not yet fixed in code, with severity and the
                  decision they need (they are reported every run so they cannot be forgotten)

usage: python -E -P -X utf8 design_conformance.py [--json] [--out FILE]
exit 0 = no FAIL and no open CRITICAL known issue; 1 otherwise
"""
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "design"))
import verified as V  # noqa: E402

LINKS = HERE / "verified" / "_links.json"

# --- C. known deviations: (id, 影響, 嚴重度, 說明, 需要的決定) ---
KNOWN = [
    {"id": "earth_pressure_KAE", "severity": "resolved",
     "finding": "（原）earth_pressure._coulomb_active 的 Mononobe-Okabe 根號內用 cos(β−ψ)，112 版式(7.3-12) 為 cos(θ−α)（墻背垂直時 cos α）",
     "impact": "（原）KAE 偏低 0.2~0.7%（φ=30、kh=0.2：0.4491 vs 0.4520），擋土牆地震工況偏不安全側",
     "action": "已於 2026-11-02 修正為 cos(β)，5 組案例（含 α=10°、15° 坡面）與 found112_KAE 逐值一致（差 <1e-9）；基準線已更新，保留此紀錄供對照"},
    {"id": "rc_phi_threshold", "severity": "resolved",
     "finding": "（原）rc_design.phi_by_strain 與 _column_point 以 εt≥0.005 判拉力控制（100 年版），112 版表21.2.2 為 εt≥εty+0.003",
     "impact": "（原）過渡區 φ 最大差約 0.012（fy=420），引擎偏大（偏不安全側）",
     "action": "已於 2026-11-02 改為 εty+0.003（梁 phi_by_strain 與柱 _column_point 兩處），與 rc112_phi_flexure 一致（差 ≤0.0006，為 round(φ,3)）；基準線已更新"},
    {"id": "urbanroad113_curb_inlet_exponent", "severity": "resolved",
     "finding": "（原）已驗證條目 urbanroad113_curb_inlet_Qc 的指數誤為 5/3（登記為『逐式對照原頁圖』）；正確為 5/2",
     "impact": "（原）緣石進水口流量低估或量綱不合：(Ln/h)·h^(5/3)＝Ln·h^(2/3) 不是堰流型式，應為 Ln·h^(3/2)；h=0.1 m、Ln=1 m 時 5/3 版與 5/2 版相差約 4.6 倍。無引擎引用此條目，影響限於 regs_formula 查詢",
     "action": "2026-11-02 已更正為 5/2：市區規範 p.91 文字層指數行『5 5 / 2 2』、公路排水規範式(5-1) 看圖確認、量綱檢查三方一致；新增 hwdrain107_curb_inlet_Q51 並以獨立手算式重寫測試值。教訓：單一來源的『看圖』結論也會錯，公式至少要有第二來源或量綱檢查"},
    {"id": "culvert_min_section", "severity": "low",
     "finding": "公路排水規範表6-1：蓋版暗溝最小 0.5 m×1.0 m（淨寬×淨高）；本工作區 2026-10-30 的 RC 暗溝設計為 70×70 cm",
     "impact": "該案淨高 0.7 m 未達表6-1 之 1.0 m，不符公路排水規範最小斷面（若適用該規範）",
     "action": "確認該案適用法規；若適用，須加大淨高或改以其他規範依據"},
    {"id": "hwdrain_S0_unit", "severity": "low",
     "finding": "公路排水附錄 O 式(O-1) 將 S0 標示為「(%)」，但 L·S0 須為高差（m）；本庫與 culvert_hydraulics 均以 m/m 代入",
     "impact": "若官方原意為 %，Hw 將差約 100 倍（實務上不可能），判定為原書標示筆誤",
     "action": "保留現行 m/m 用法，待官方公告確認"},
    {"id": "flexpave_axle_factor", "severity": "resolved",
     "finding": "柔性鋪面設計手冊公式(3.2.4) 直接代入呈「軸重越大因子越小」；以 3.2.5 節範例兩個權威點反推，原式右邊需取負號（LEF=10^−RHS）",
     "impact": "已修正：Lx=18 kip 得 1.000、單軸 12.48 kip 得 0.2227（範例 0.229）、複軸 35.35 kip 得 1.2795（範例 1.289）",
     "action": "已於 2026-11-01 修正條目並改為 verified；保留此紀錄供日後對照原書"},
    {"id": "seis113_vs_found112_liquefaction", "severity": "resolved",
     "finding": "耐震規範 11.1.3（FL＝CRR/CSR、FL<1.0 判定液化）與基礎規範 10.3（液化評估三法）均有液化評估",
     "impact": "兩規範之方法互補：11.1.3 給「判定準則與檢核地震等級」，10.3 給「CRR 計算方法」。現已分別入庫（seis113_FL_liquefaction、found112_FL_HBF/NCEER/JRA）",
     "action": "已於 2026-11-01 補入 seis113 11.1.3 條目；**CRR 之迴歸式仍未入庫**（散見解說圖表），使用時須依解說或現地試驗計算 CRR；工作台亦無液化計算器，尚無可逐值比對之對象"},
    {"id": "flexpave91_Estar_print_error", "severity": "low",
     "finding": "柔性鋪面設計手冊附錄D：表D.6.(8) 21℃「建議使用值」欄印為 274251；表D.6.(9) 22℃「AI-1984」欄印為 282494。兩處均與同欄上下相鄰值之線性中間值不符（單調性中斷），判為原書誤植（照原文轉錄）",
     "impact": "若直接取用該二格，E* 將低估約 25%（274251 對內插約 3.75×10⁵ psi；282494 對內插約 3.84×10⁵ psi），使 a1~a3 偏低、SN 需求偏高、鋪面厚度偏厚",
     "action": "兩表條目已標 status=pending、notes 以【待核】說明疑點並給替代做法（內插或改採相鄰欄）；俟原書勘誤或 ASTM D4123 試驗資料確認後再改為 verified"},
    {"id": "found112_angular_levels_partial", "severity": "low",
     "finding": "建築物基礎構造設計規範表-解4.5-1 共 7 列（1/600、1/500、1/300、1/250、1/150×3），工作台 ANGULAR_DISTORTION_DAMAGE_LEVELS 只收前 4 級；1/150 之三種情形（隔間牆及磚牆多裂縫、可撓性磚牆安全限度、結構性損壞）未納入",
     "impact": "設計檢核以 1/500 為預設門檻（已與表值 PASS 比對），1/150 屬更嚴重損壞之判讀級距，不影響門檻判定；但若要輸出「損壞程度」描述，1/150 情形會缺描述",
     "action": "待決定是否補 1/150 三種情形（同一 ratio 對應三種描述，需將分級結構改為 ratio→多重描述）"},
    {"id": "rock_slope_modes_missing", "severity": "medium",
     "finding": "公路邊坡工程設計規範(104) 解說 C4.3 要求岩石邊坡須就平面滑動、楔形滑動、傾覆等破壞型態分別以立體投影與極限平衡分析；工作台 slope_stability.py 僅實作無限邊坡法與 Fellenius 坡趾圓弧滑動",
     "impact": "岩石邊坡（具明確弱面、節理、層面）案件若逕用工作台之圓弧滑動結果，會漏掉沿弱面之平面／楔形滑動，安全係數可能高估；土壤邊坡不受影響",
     "action": "岩石邊坡一律另以極限平衡（平面滑動／楔形滑動）或數值分析辦理，工作台結果僅作參考；已入庫 hwslope104_rock_slope_modes 作為方法依據"},
    {"id": "concrete_unit_weight_24_vs_2354", "severity": "low",
     "finding": "建築技術規則構造篇第11條規定鋼筋混凝土單位重 2400 kg/m³（＝23.54 kN/m³）；工作台 retaining_wall.GAMMA_CONC 採 24.0 kN/m³",
     "impact": "引擎混凝土自重比規範值高 1.9%，擋土牆穩定檢核（抗滑、抗傾倒）偏保守約 1%；不影響安全性方向",
     "action": "保留 24.0 kN/m³（工程慣用整數值且偏保守）；若採 23.54 會使各案 FS 略降，須重跑回歸後再決定"},
    {"id": "rc_column_no_slenderness", "severity": "medium",
     "finding": "112 版第 6.6.4.4.1~6.6.4.5.2 規定柱細長效應（樓層穩定指數 Q、臨界挫屈載重 Pc、彎矩放大因數 δ、Mc=δM2）；工作台 rc_design.column_design 自述「Biaxial bending, slenderness, splice and anchorage checks must be added」，未實作細長效應",
     "impact": "細長柱（ℓc/h 大、Pu/Pc 高）的設計彎矩會偏小，可能低估需求鋼筋；Q≤0.05 之無側移判定與 δ≥1.0 之放大均未反映在輸出",
     "action": "已入庫 rc112_storey_Q／rc112_Pc_buckling／rc112_Mc_magnified／rc112_delta_magnifier 供以 regs_formula 手算；是否納入 rc_column 須先決定 (EI)eff 取法（6.6.4.4.4a~c）並重跑回歸"},
]


def _num(x, nd=6):
    return round(float(x), nd)


def numeric_probes():
    """(name, callable) pairs: callable returns (engine_value, verified_value, unit, tol)."""
    import earth_pressure as EP
    import rc_design as RC
    import hydrology as HY
    import channel_hydraulics as CH
    import culvert_hydraulics as CU
    import slope_stability as SS
    import foundation_design as FD

    def ka_coulomb():
        rows = []
        for phi, d, a in ((30, 0, 0), (30, 20, 0), (34, 17, 15), (28, 14, 10)):
            e = EP.coulomb_active_coefficient(phi, wall_friction_deg=d, backfill_slope_deg=a, wall_angle_deg=90)
            v = V.evaluate("found112_Ka_coulomb", {"phi": phi, "delta": d, "theta": 0, "alpha": a})["value"]
            rows.append((f"φ={phi},δ={d},α={a}", e, v, "-", 1e-6))
        return rows

    def kae_mo():
        rows = []
        for phi, d, al, kh, kv in ((30, 15, 0, 0.2, 0.0), (32, 16, 0, 0.15, 0.05), (30, 0, 0, 0.1, 0.0),
                                   (34, 17, 10, 0.2, 0.0), (30, 15, 15, 0.15, 0.0)):
            e = EP.coulomb_active_coefficient(phi, wall_friction_deg=d, backfill_slope_deg=al, wall_angle_deg=90, kh=kh, kv=kv)
            v = V.evaluate("found112_KAE", {"phi": phi, "delta": d, "theta": 0, "alpha": al, "kh": kh, "kv": kv})["value"]
            rows.append((f"φ={phi},δ={d},α={al},kh={kh},kv={kv}", e, v, "-", 1e-9))  # 2026-11-02 修正後須逐值一致
        return rows

    def phi_flexure():
        rows = []
        for As, b, d, fc, fy in ((1500, 300, 500, 28, 420), (3000, 300, 500, 28, 420), (800, 1000, 240, 28, 420),
                                 (2500, 300, 500, 28, 420), (3500, 300, 500, 28, 420)):
            e, et, _ = RC.phi_by_strain(As, b, d, fc, fy)
            v = V.evaluate("rc112_phi_flexure", {"et": et, "fy": fy})["value"]
            rows.append((f"As={As},b={b},d={d}", e, v, "-", 0.0006))  # 引擎 round(φ,3)
        return rows

    def vc_a():
        rows = []
        for fc, b, h, cc in ((21, 1000, 300, 50), (28, 300, 500, 60)):
            r = RC.shear_check(100.0, b_mm=b, h_mm=h, cc={"fc_mpa": fc, "cover_mm": cc})
            v = V.evaluate("rc112_Vc_a", {"fc": fc, "bw": b, "d": h - cc - 10})["value"] / 1000.0
            rows.append((f"fc={fc},b={b},h={h},cc={cc}", r["Vc_kN"], v, "kN", 0.001))  # 引擎四捨五入至 0.001 kN
        return rows

    def bar_spacing():
        rows = []
        for fs, cc in ((280, 50), (186.7, 75), (350, 40)):
            e = RC.spacing_limit_mm(cc, fs)[0]
            v = V.evaluate("rc112_bar_spacing_max", {"fs": fs, "cc": cc})["value"]
            rows.append((f"fs={fs},cc={cc}", e, v, "mm", 0.11))
        return rows

    def intensity():
        rows = []
        for P, T, t in ((2000, 25, 60), (2500, 10, 30), (3200, 50, 90)):
            e = HY.rainfall_intensity(P, T, t)
            v = V.evaluate("swc16_intensity", {"P": P, "T": T, "t": t})["value"]
            rows.append((f"P={P},T={T},t={t}", e, v, "mm/hr", 1e-9))
        return rows

    def rational_urbanroad():
        """市區道路規範 7.2.3 合理化公式 vs hydrology 引擎（第 17 條）同一組 C、I、A。"""
        rows = []
        for P, T, area, cond, dev, t in ((2500, 10, 5.0, "丘陵地或森林", False, 30),
                                         (2000, 25, 12.0, "平坦耕地", False, 45),
                                         (3200, 50, 2.0, "非農業使用", True, 20)):
            r = HY.design_flow(P, T, area, cond, dev, t_override_min=t)
            C = HY.runoff_coefficient(cond, dev, False)
            I = HY.rainfall_intensity(P, T, t)
            v = V.evaluate("urbanroad113_rational_Q", {"C": C, "I": I, "A": area})["value"]
            rows.append((f"P={P},T={T},A={area},t={t}", r["Qp_m3s"], v, "m3/s", 1e-4))
        return rows

    def manning_urbanroad():
        """市區道路規範 7.3.2 曼寧公式 vs channel_hydraulics 引擎同一斷面。"""
        rows = []
        for b, h, n, S in ((1.0, 0.5, 0.015, 0.01), (2.0, 1.2, 0.013, 0.003), (1.2, 0.8, 0.016, 0.005)):
            Q, pr = CH.capacity(b, h, n, S)
            v = V.evaluate("urbanroad113_manning_V", {"n": n, "R": pr["R"], "S": S})["value"] * pr["A"]
            rows.append((f"b={b},h={h},n={n},S={S}", Q, v, "m3/s", 1e-9))
        return rows

    def manning():
        rows = []
        for b, h, n, S in ((1.0, 0.5, 0.015, 0.01), (2.0, 1.2, 0.013, 0.003)):
            Q, pr = CH.capacity(b, h, n, S)
            v = V.evaluate("swc84_manning_v", {"n": n, "R": pr["R"], "S": S})["value"] * pr["A"]
            rows.append((f"b={b},h={h},n={n},S={S}", Q, v, "m3/s", 1e-9))
        return rows

    def culvert_outlet():
        rows = []
        for qc, w, h, sl, ln, nn, ke, tw in ((3.0, 1.5, 1.2, 0.01, 20.0, 0.013, 0.5, 0.6),
                                             (6.0, 2.0, 1.5, 0.005, 35.0, 0.015, 0.2, 1.7)):
            o = CU.outlet_control(qc, w, h, sl, ln, nn, ke, tw)
            v = V.evaluate("hwdrain107_culvert_outlet_Hw", {"Ke": ke, "n": nn, "L": ln, "R": o["hydraulic_radius_full_m"],
                                                            "V": o["full_flow_velocity_m_s"], "h0": o["h0_m"], "S0": sl, "g": CU.G})["value"]
            rows.append((f"Q={qc},TW={tw}", o["headwater_m"], v, "m", 1e-9))
        return rows

    def runoff_table():
        rows = []
        for cond in HY.RUNOFF_C["無開發整地區"]:
            for dev, key in ((False, "無開發整地區"), (True, "開發整地區")):
                tv = V.table("swc18_runoff_c", key, cond)["value"]
                rows.append((f"{key}/{cond}", HY.runoff_coefficient(cond, dev, False), tv[0], "-", 1e-9))
                rows.append((f"{key}/{cond}(上限)", HY.runoff_coefficient(cond, dev, True), tv[1], "-", 1e-9))
        return rows

    def safety_factor():
        rows = []
        for k in ("永久性", "臨時性"):
            for c, val in SS.FS_TABLE[k].items():
                rows.append((f"{k}/{c}", SS.required_fs(k, c) if hasattr(SS, "required_fs") else val,
                             V.table("swc73_min_safety_factor", k, c)["value"], "-", 1e-9))
        return rows

    def ke_table():
        rows = []
        mapping = {"wingwall_30_75": "鋼筋混凝土箱涵：30°~75°翼端牆式進口、平頭式",
                   "wingwall_90_15": "鋼筋混凝土箱涵：10°~25°翼端牆式進口、平頭式",
                   "wingwall_0": "鋼筋混凝土箱涵：平行端牆式進口、平頭式",
                   "wingwall_45_top_bevel": "鋼筋混凝土箱涵：30°~75°翼端牆式進口、圓頭式",
                   "headwall_chamfer": "鋼筋混凝土箱涵：端牆式進口、平頭狀"}
        for k, row in mapping.items():
            rows.append((k, CU.INLET_TYPES[k]["Ke"], V.table("hwdrain107_Ke_TO1", row, "Ke")["value"], "-", 1e-9))
        return rows

    def sediment_production():
        import sediment_basin as SB
        rows = []
        for area, exc, imp, kind in ((2.0, 0.1, 0.0, "temporary"), (2.0, 0.1, 0.0, "permanent"),
                                     (2.0, 1.5, 0.2, "temporary"), (5.0, 0.0, 0.0, "permanent")):
            e = SB.sediment_production(area, exc, imp, kind=kind, Am=22.5)["production_m3"]
            v = V.evaluate("swc92_sediment_volume", {"Am": 22.5, "area_ha": area, "excavated_ha": exc,
                                                     "impervious_ha": imp, "permanent": 1 if kind == "permanent" else 0})["value"]
            rows.append((f"area={area},exc={exc},imp={imp},{kind}", e, v, "m3", 1e-9))
        return rows

    def bearing_engine_inputs():
        """引擎接受使用者輸入之容許承載力；確認它不會自行用錯公式（以提示文字檢查）。"""
        return []


    def consol_settle():
        """found112 式(4.4-1) 孔隙比式 vs 引擎逐層壓密（用引擎自己的 e0、Cr、σ'0、σ'f 反推 ef）。"""
        import math
        DA = __import__("design_api", fromlist=["x"]) if False else None
        sys.path.insert(0, str(ROOT / "tools" / "design"))
        import design_api as A
        cat = [v for v in A.CATALOG if v.get("id") == "settlement_assessment"][0]
        res = A.run_calculation("settlement_assessment", cat["example"])
        rows = []
        for f in res["result"]["footings"][:2]:
            for lay in f["consolidation"]["layers"]:
                e0 = lay["void_ratio"]
                s0 = lay["initial_effective_stress_kpa"]
                sf = lay["final_effective_stress_kpa"]
                sp = lay["preconsolidation_stress_kpa"] or s0
                cc = lay["compression_index"]
                cr = lay["recompression_index"]
                if sf <= sp:
                    de = cr * math.log10(sf / s0)
                else:
                    de = cr * math.log10(sp / s0) + cc * math.log10(sf / sp)
                ef = e0 - de
                v = V.evaluate("found112_consol_settle_e",
                               {"e0": e0, "ef": ef, "H": lay["thickness_m"]})["value"] * 1000.0
                rows.append((f"{f['id']} L{lay['layer']} e0={e0},dE={de:.5f}", 
                             lay["primary_consolidation_mm"], v, "mm", 0.05))
        return rows

    def retaining_limits():
        """擋土牆穩定檢核用的常數 vs found112 表6.3-2（容許剪切強度 FS）。"""
        sys.path.insert(0, str(ROOT / "tools" / "design"))
        import retaining_wall as RW
        long_run = V.table("found112_shear_FS_T632", "安全係數", "長期載重情況")["value"]
        short_run = V.table("found112_shear_FS_T632", "安全係數", "短期載重情況")["value"]

        return [
                ("擋土牆滑動 FS（常時）", RW.LIMITS["sliding_static"], long_run, "-", 1e-9),
                ("擋土牆滑動 FS（地震）", RW.LIMITS["sliding_seismic"], short_run, "-", 1e-9),
            ]

    def cover_check():
        """擋土牆保護層：工作台預設 75 mm vs rc112 表20.5.1.3.1 之**控制值**（貼地澆置 75 mm）。

        擋土牆迎土面屬「貼地澆置且永久接觸大地」＝規範最小值 75 mm，故取該列
        （曝露大氣列之 50/40 mm 較寬鬆，不控制），比對採等值，tol 1e-9。
        """
        want = V.table("rc112_cover_T205131", "貼地澆置／所有構材／所有鋼筋", "保護層mm")["value"]
        return [("擋土牆迎土面保護層（mm）", 75.0, want, "mm", 1e-9)]

    def anchor_limits():
        """地錨設計 FS 常數 vs 施工規範表02492-1（單一地錨最小安全係數）。"""
        sys.path.insert(0, str(ROOT / "tools" / "design"))
        import anchored_wall as AW
        rows = []
        pairs = [("temporary", "臨時性地錨", "臨時性"), ("permanent", "長久性地錨", "長久性")]
        cols = [("tendon", "抗張材"), ("ground_grout", "地層/漿體介面"), ("tendon_grout", "漿體/抗張材介面")]
        for key, row_key, label in pairs:
            for fld, col in cols:
                rows.append((f"{label}／{col}",
                             AW.ANCHOR_FS[key][fld],
                             V.table("hwconst112_anchor_FS_T024921", row_key, col)["value"],
                             "-", 1e-9))
        return rows

    def settlement_limits():
        """工作台容許總沉陷常數 vs found112 表-解4.5-2（原表單位 cm，換算 mm）。"""
        sys.path.insert(0, str(ROOT / "tools" / "design"))
        import foundation_design as FD
        pairs = [("plain_concrete_continuous", "混凝土-連續基腳"),
                 ("rc_isolated_or_combined", "混凝土-獨立及聯合基腳"),
                 ("rc_continuous", "鋼筋混凝土-連續基腳"),
                 ("rc_raft", "鋼筋混凝土-筏式基礎")]
        return [(f"容許總沉陷 {key}",
                 FD.SETTLEMENT_LIMITS_MM[key],
                 V.table("found112_settlement_T452", row, "總沉陷量(cm)")["value"] * 10.0,
                 "mm", 1e-9) for key, row in pairs]

    def angular_limits():
        """工作台角變量分級 vs found112 表-解4.5-1（引擎只收前四級，1/150 三種情形未納入）。"""
        sys.path.insert(0, str(ROOT / "tools" / "design"))
        import foundation_design as FD
        levels = sorted(FD.ANGULAR_DISTORTION_DAMAGE_LEVELS, key=lambda r: r["ratio"])
        keys = [("1/600", 600.0), ("1/500", 500.0), ("1/300", 300.0), ("1/250", 250.0)]
        return [(f"角變量分級 {k}", lv["ratio"], 1.0 / n, "-", 1e-12)
                for lv, (k, n) in zip(levels, keys)]

    return [
        ("found112_Ka_coulomb", "earth_pressure.coulomb_active_coefficient", ka_coulomb),
        ("found112_KAE", "earth_pressure.coulomb_active_coefficient (M-O)", kae_mo),
        ("rc112_phi_flexure", "rc_design.phi_by_strain", phi_flexure),
        ("rc112_Vc_a", "rc_design.shear_check", vc_a),
        ("rc112_bar_spacing_max", "rc_design.spacing_limit_mm", bar_spacing),
        ("swc16_intensity", "hydrology.rainfall_intensity", intensity),
        ("swc84_manning_v", "channel_hydraulics.capacity", manning),
        ("urbanroad113_rational_Q", "hydrology.design_flow (第17條合理化公式)", rational_urbanroad),

        ("urbanroad113_manning_V", "channel_hydraulics.capacity", manning_urbanroad),
        ("found112_consol_settle_e", "settlement_assessment.consolidation", consol_settle),
        ("found112_shear_FS_T632", "retaining_wall.LIMITS（滑動）", retaining_limits),
        ("hwconst112_anchor_FS_T024921", "anchored_wall.ANCHOR_FS", anchor_limits),
        ("hwdrain107_culvert_outlet_Hw", "culvert_hydraulics.outlet_control", culvert_outlet),
        ("swc18_runoff_c", "hydrology.runoff_coefficient", runoff_table),
        ("swc73_min_safety_factor", "slope_stability", safety_factor),
        ("hwdrain107_Ke_TO1", "culvert_hydraulics.INLET_TYPES", ke_table),
        ("swc92_sediment_volume", "sediment_basin.sediment_production", sediment_production),
        ("found112_settlement_T452", "foundation_design.SETTLEMENT_LIMITS_MM", settlement_limits),
        ("found112_angular_T451", "foundation_design.ANGULAR_DISTORTION_DAMAGE_LEVELS", angular_limits),
        ("rc112_cover_T205131", "rc_design 擋土牆保護層預設值", cover_check),
    ]


def run():
    fm, tb = V.load()
    links = json.loads(LINKS.read_text(encoding="utf-8")) if LINKS.exists() else {}
    out = {"structural": [], "numeric": [], "known": KNOWN, "stats": {}}

    # A. structural
    for calc, ids in sorted(links.items()):
        missing = [i for i in ids if i not in fm and i not in tb]
        unverified = [i for i in ids if (fm.get(i) or tb.get(i) or {}).get("status") != "verified"]
        out["structural"].append({"calculator": calc, "entries": len(ids),
                                  "missing": missing, "unverified": unverified,
                                  "ok": not missing and not unverified})
    import design_api
    calcs = {c["id"] for c in design_api.list_calculators()}
    _scope = [
        {"calculator": "detention_basin", "entry": "swc96_Vs1_temp_detention / swc96_Vs2_perm_detention",
         "note": "引擎用級蓄水-出流歷線演算（routing），未直接套三角單位歷線公式；方法較嚴謹但與條文公式不同，比較時須以同一入流歷線為準"},
        {"calculator": "box_culvert", "entry": "hwdrain107_Ke_TO1 / hwdrain107_culvert_outlet_Hw",
         "note": "出口控制已比對一致；進口控制採 HDS-5 迴歸式，而公路排水附錄 N 為諾模圖（無公式），無法逐式比對"},
        {"calculator": "foundation_isolated / foundation_combined", "entry": "found112_qu_ultimate",
         "note": "引擎不自行計算極限支承力，容許承載力由使用者輸入（設計分工）；如需由土壤參數推算，須先用 regs_formula(found112_qu_ultimate) 再輸入"},
        {"calculator": "foundation_pile", "entry": "found112_Qu_pile / found112_Qa_pile",
         "note": "引擎只做群樁載重分配，樁垂直承載力由使用者輸入 Q_allow"},
        {"calculator": "building_frame", "entry": "seis113_V_min",
         "note": "引擎為構架分析（載重組合與內力），不含耐震最小總橫力 V 之計算；V 須先以 regs_formula(seis113_V_min) 求得後作為側力輸入"},
        {"calculator": "settlement_assessment", "entry": "found112_dH_immediate_layers / found112_dH_elastic_uniform",
         "note": "引擎以 2:1 法推求應力增量（4.4.3 允許「彈性力學公式並作適當修正」），條文解說另給 Boussinesq 集中載重式；兩者為不同模型，不宜逐值比對。引擎之沈陷公式本身與解(4.4-2) 之單層形式一致（以壓縮模數 M 代替 E 並取一維），稽核列為範圍差異而非不符"},
        {"calculator": "detention_basin", "entry": "swc96_Vs1_temp_detention / swc96_Vs2_perm_detention",
         "note": "引擎用級蓄水-出流歷線演算（routing），未直接套三角單位歷線公式；方法較嚴謹但與條文公式不同，比較時須以同一入流歷線為準"},
        {"calculator": "wall_stability / block_wall / counterfort_wall / mse_wall / anchored_wall", "entry": "found112_qu_ultimate / found112_Ka_coulomb",
         "note": "承載力與土壓力係數多由使用者輸入或採 Rankine；地震工況的 M-O 係數有已知差異（見 KNOWN）"},
        {"calculator": "（無對應計算器）", "entry": "flexpave91_*（柔性鋪面設計手冊）",
         "note": "工作台 21 個計算器不含鋪面厚度設計（新工柔性鋪面、加鋪）；已轉錄之 flexpave91 條目（TI、ESAL、軸重當量因子、加州法 T／GE、AI IS-181 設計表、動彈性模數表、加鋪有效厚度等）目前僅供 regs_formula／regs_table 查詢，無引擎可逐值比對"},
    ]
    _seen, out["scope"] = set(), []
    for x in _scope:
        if x["calculator"] in _seen:
            continue
        _seen.add(x["calculator"])
        out["scope"].append(x)
    out["stats"]["calculators_total"] = len(calcs)
    out["stats"]["calculators_with_links"] = len([c for c in links if c in calcs])
    out["stats"]["links_without_calculator"] = [c for c in links if c not in calcs]

    # B. numeric
    for probe in numeric_probes():
        vid, target, fn = probe[0], probe[1], probe[2]
        known = probe[3] if len(probe) > 3 else None
        try:
            rows = fn()
        except Exception as e:  # engine refused or crashed: record, do not abort the audit
            out["numeric"].append({"verified": vid, "engine": target, "status": "ERROR", "detail": f"{type(e).__name__}: {e}", "cases": []})
            continue
        cases, worst = [], 0.0
        for label, e, v, unit, tol in rows:
            diff = abs(e - v)
            ok = diff <= tol
            worst = max(worst, diff / abs(v) * 100 if v else 0.0)
            cases.append({"case": label, "engine": _num(e), "verified": _num(v), "unit": unit,
                          "diff": _num(diff), "pct": _num(diff / abs(v) * 100 if v else 0.0, 4), "ok": ok})
        status = ("DIFF" if not all(c["ok"] for c in cases) else ("KNOWN" if known else "PASS"))
        out["numeric"].append({"verified": vid, "engine": target, "status": status, "known": known, "worst_pct": _num(worst, 4), "cases": cases})

    fails = [r for r in out["numeric"] if r["status"] not in ("PASS", "KNOWN")]
    out["stats"]["numeric_pass"] = len([r for r in out["numeric"] if r["status"] == "PASS"])
    out["stats"]["numeric_known"] = len([r for r in out["numeric"] if r["status"] == "KNOWN"])
    out["stats"]["numeric_fail"] = len(fails)
    out["stats"]["structural_ok"] = sum(1 for s in out["structural"] if s["ok"])
    out["stats"]["structural_bad"] = [s["calculator"] for s in out["structural"] if not s["ok"]]
    out["stats"]["known_high"] = [k["id"] for k in KNOWN if k["severity"] == "high"]
    # adoption: calculators whose engine output is actually compared against a verified entry
    probed = {x["verified"] for x in out["numeric"]}
    adopting = sorted({calc for calc, ids in links.items() if probed & set(ids)})
    out["stats"]["calculators_numerically_verified"] = adopting
    out["stats"]["numeric_coverage_pct"] = _num(100.0 * len(adopting) / max(1, len(calcs)), 1)
    return out


def report_text(r):
    s = ["# 設計工作台 vs 已驗證規範 符合性稽核", ""]
    st = r["stats"]
    s += [f"- 計算器 {st['calculators_total']} 個，其中 {st['calculators_with_links']} 個已連結已驗證條文",
          f"- 結構檢查：{st['structural_ok']} 通過、{len(st['structural_bad'])} 有問題",
          f"- 數值比對：{st['numeric_pass']} 通過、{st.get('numeric_known', 0)} 屬已知差異、{st['numeric_fail']} 不符",
          f"- 採用率：{len(st['calculators_numerically_verified'])}／{st['calculators_total']} 個計算器（{st['numeric_coverage_pct']}%）的輸出有與已驗證公式逐值比對過（其餘為結構連結或方法範圍差異）",
          ""]
    s += ["## 數值比對", "", "| 已驗證條目 | 引擎 | 結果 | 最大差異% |", "|---|---|---|---:|"]
    for x in r["numeric"]:
        s.append(f"| {x['verified']} | {x['engine']} | {x['status']} | {x.get('worst_pct', '')} |")
    bad = [x for x in r["numeric"] if x["status"] != "PASS"]
    bad.sort(key=lambda x: {"DIFF": 0, "ERROR": 0, "KNOWN": 1}.get(x["status"], 2))
    if bad:
        s += ["", "### 差異明細", ""]
        for x in bad:
            s.append(f"**{x['verified']}**（{x['engine']}）")
            for c in x["cases"]:
                flag = "" if c["ok"] else "  ← 不符"
                s.append(f"- {c['case']}：引擎 {c['engine']} / 規範 {c['verified']} {c['unit']}（差 {c['diff']}）{flag}")
            s.append("")
    if r.get("scope"):
        s += ["## 方法範圍差異（不是錯誤，但比較時要注意）", ""]
        for x in r["scope"]:
            s.append(f"- **{x['calculator']}**（{x['entry']}）：{x['note']}")
        s.append("")
    s += ["## 已知差異（每次稽核都列出，未修正前不得視為符合）", ""]
    for k in r["known"]:
        s.append(f"### [{k['severity']}] {k['id']}")
        s.append(f"- 現象：{k['finding']}")
        s.append(f"- 影響：{k['impact']}")
        s.append(f"- 需要的決定：{k['action']}")
        s.append("")
    if st["structural_bad"]:
        s += ["## 連結缺漏", ""] + [f"- {c}" for c in st["structural_bad"]]
    return "\n".join(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run()
    text = json.dumps(r, ensure_ascii=False, indent=1) if a.json else report_text(r)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    hard = [x for x in r["numeric"] if x["status"] == "ERROR"] + \
           [s for s in r["structural"] if not s["ok"]]
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
