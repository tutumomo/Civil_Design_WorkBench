"""RC 構材配筋設計（擋土牆莖板／排水溝溝壁／矩形梁，每公尺長或單梁）。

規範依據說明（112.08.10 現行版與 100.06.09 舊版已逐條對帳）
----------------------------------------------------------
本工作區**已取得**《水土保持技術規範》全文，但該規範第 120 條四僅要求
「牆身所受各種應力，必須在各種材料容許應力範圍內」，**未規定配筋計算式**。
配筋設計依《混凝土結構設計規範》（內政部 **112.08.10 現行版**，ACI 318-19
體系），並保留 **100.06.09 舊版**條號對照以利舊案稽核；以下核心算式均已與
`tools/regs/verified/rc112*.json` 對帳完成（計算結果與回歸基準維持不變）：

  - 強度折減因數 φ：112 版 **§21.2.1／表 21.2.2**（對應 100 版 §2.3.2／§3.4.4）
      撓曲依淨拉應變 εt 判定（`εt ≥ εty + 0.003` → **0.90**）；剪力 **0.75** ✓
  - 受撓構材最少鋼筋量：112 版 **§9.6.1.2**（梁，對應 100 版 §3.6.1 式 3-3／3-4）
      `As,min ≥ max(0.25√fc′/fy, 1.4/fy)·bw·d` ✓
  - 單向版／收縮與溫度鋼筋：112 版 **§7.6.1.1／§24.4.3.2**（對應 100 版 §7.12）
      `0.0018·Ag` ✓
  - 單向剪力 Vc：
      懸臂擋土牆（寬厚比 ≥ 2.5）：112 版 **§13.3.6.1.1**（對應 100 版 §4.4.1.1）
      梁（配置 ≥ Av,min 時）：112 版 **表 22.5.5.1 式(a)**（對應 100 版 §4.4.1.1）
      `Vc = 0.17·λ·√fc′·bw·d`（MPa，即 0.53·λ·√fc′·bw·d kgf/cm²）✓
  - 牆最少分布鋼筋比與雙層規定：112 版 **§11.6.1 表 11.6.1／§11.7.2.3**
      （對應 100 版 §7.2.2／§7.4.2～7.4.4）；本模組續採較保守之 `ρl=0.0015`、
      `ρt=0.0025` 及 `t ≥ 250 mm` 雙層配筋（完全符合 112 版規定）✓
  - 梁與單向版裂縫控制最大鋼筋間距：112 版 **§24.3.2 表 24.3.2／§24.3.2.1**
      （對應 100 版 §3.7.2 式 3-6）✓
  - 載重放大係數：工作區擋土牆／溝壁常時土壓與水壓續採保守慣例 `1.7H`
      （112 版 §5.3.1 表 5.3.1 為 `1.6H`，現行算式偏保守約 6%）

**注意**：本模組負責構材斷面初步設計；錨定／搭接長度、地震載重組合與施工詳圖
仍須由技師覆核現行條文。

採用的公式（單位：kN、m、mm²、MPa）
----------------------------------
彎矩設計（矩形斷面，單筋）：
    Mn = As·fy·(d − a/2)，a = As·fy/(0.85·fc'·b)
    設計強度 φMn ≥ Mu，φ 依 112 版表 21.2.2 由淨拉應變 εt 判定
剪力：
    Vc = 0.17·λ·√fc'·b·d（λ=1 常重混凝土），φ = 0.75（112 版表 21.2.1）
    矩形梁垂直閉合箍筋（112 版 §9.6.3／§9.7.6／§22.5）：
        Vs = Av·fyt·d/s（§22.5.8.5.3）
        Vu/φ ≤ Vc + Vs
        Av/s ≥ max(0.062√fc'·bw/fyt, 0.35·bw/fyt)（§9.6.3.4）
        s ≤ d/2 且 ≤ 600 mm；高剪力時減半（表 9.7.6.2.2）；Vs ≤ 0.66√fc'·bw·d（§22.5.1.2）
最小鋼筋：
    As,min = 取下列較大者：
      ① 0.0018·b·h  —— 單向版與溫度收縮鋼筋（112 版 §7.6.1.1／§24.4.3.2，舊 §7.12）
      ② 1.4·b·d/fy  —— 受撓構材最小鋼筋（112 版 §9.6.1.2／舊 §3.6.1 式(3-4) 之 SI 換算：
                        原式 14·bw·d/fy（kgf/cm²），14 kgf/cm² ≈ 1.4 MPa）
裂縫控制（Gergely-Lutz 簡式）：
    w = 2.2·β·fs·(dc·A)^(1/3) / (Es·1000)，fs 優先依服務彎矩反算，上限 0.6·fy
    w ≤ 0.3 mm（一般室外構材）
"""

import math
import sys

# ---- 材料預設值（可被案件覆寫）----
CONCRETE = {
    "fc_mpa": 21.0,        # fc' = 210 kgf/cm² ≈ 20.6 MPa，取 21
    "fy_mpa": 420.0,       # SD420
    "Es_mpa": 200000.0,
    "cover_mm": 75.0,      # 擋土牆迎土面保護層
    "phi_flexure": 0.9,
    "phi_shear": 0.75,
    "crack_limit_mm": 0.3,
}

REBAR_SIZES = {          # 標稱直徑 mm → 單根斷面積 mm²
    "D10": (9.53, 71.0), "D13": (12.7, 127.0), "D16": (15.9, 199.0),
    "D19": (19.1, 287.0), "D22": (22.2, 387.0), "D25": (25.4, 507.0),
    "D29": (28.7, 647.0), "D32": (31.8, 794.0),
}


def _bar_area(name):
    return REBAR_SIZES[name][1]


def _pick_bars(
    As_req_mm2_per_m,
    cover_mm=75.0,
    h_mm=None,
    prefer=("D16", "D19", "D22", "D25", "D13"),
    max_spacing_mm=300.0,
):
    """在每公尺寬度內選筋：回傳 (筋號, 間距 mm, 實際 As mm²/m)。"""
    cap = max(50.0, min(300.0, float(max_spacing_mm)))
    for name in prefer:
        ab = _bar_area(name)
        # 每公尺根數 = 1000 / spacing；As = 1000/spacing × ab
        spacing = math.floor(1000.0 * ab / max(As_req_mm2_per_m, 1e-9) / 10.0) * 10
        spacing = max(50, min(spacing, cap))          # 實務間距 5~30 cm
        As = 1000.0 / spacing * ab
        if As >= As_req_mm2_per_m * 0.999:
            return name, int(spacing), As
    name = prefer[0]
    ab = _bar_area(name)
    spacing = 50
    return name, spacing, 1000.0 / spacing * ab


def _single_pref(value):
    """把 UI 的單一筋號（或 auto）轉成 flexure_design 需要的 tuple。"""
    v = str(value or "").strip()
    if not v or v.lower() == "auto" or v not in REBAR_SIZES:
        return None
    return (v,)


def select_bars(
    As_req_mm2_per_m,
    h_mm,
    cover_mm=50.0,
    *,
    prefer=("D16", "D19", "D22", "D25", "D13"),
    max_spacing_mm=300.0,
):
    """依所需 As 選筋，回傳筋號／間距／實配 As。

    供非撓曲控制之配筋（縱向分佈筋、溫度鋼筋）使用；不會套用樑式
    As,min，因此可指定比 `flexure_design()` 更低的分佈筋量。
    """
    req = max(0.0, float(As_req_mm2_per_m))
    prefer = tuple(p for p in prefer if p in REBAR_SIZES) or (
        "D16", "D19", "D22", "D25", "D13"
    )
    name, spacing, As = _pick_bars(
        req,
        float(cover_mm),
        float(h_mm),
        prefer=prefer,
        max_spacing_mm=max_spacing_mm,
    )
    return {
        "bar": name,
        "spacing_mm": int(spacing),
        "As_prov_mm2": round(As, 1),
        "As_req_mm2": round(req, 1),
        "ok": As >= req - 1e-6,
    }


def phi_by_strain(As_mm2, b_mm, d_mm, fc_mpa, fy_mpa, es_mpa=None):
    """依 112 年版表21.2.2：由最外受拉鋼筋淨拉應變 εt 決定撓曲強度折減因數 φ。

    拉力控制斷面（εt ≥ εty+0.003）    → φ = 0.90
    壓力控制斷面（εt ≤ εty = fy/Es）  → φ = 0.65（非螺箍）
    過渡斷面（εty < εt < εty+0.003）  → φ 由 0.65 線性內插至 0.90

    2026-11-02 由 100 年版的「εt ≥ 0.005」改為 112 版的「εt ≥ εty+0.003」（與已驗證條目
    rc112_phi_flexure 一致）。fy=420 MPa 時 εty 取 fy/Es＝0.0021（條文允許 0.002，此處略保守）。
    先前程式一律取 φ=0.90 —— 對厚牆、低鋼筋量的斷面會偏不安全。
    """
    Es = es_mpa or CONCRETE["Es_mpa"]
    a = As_mm2 * fy_mpa / (0.85 * fc_mpa * b_mm)
    beta1 = 0.85 if fc_mpa <= 28.0 else max(0.65, 0.85 - 0.05 * (fc_mpa - 28.0) / 7.0)
    c_na = a / beta1                       # 中和軸深度
    if c_na <= 0:
        return 0.90, 0.05, "拉力控制"
    et = 0.003 * (d_mm - c_na) / c_na      # 淨拉應變
    ety = fy_mpa / Es
    if et >= ety + 0.003:
        return 0.90, et, "拉力控制（εt ≥ εty+0.003）"
    if et <= ety:
        return 0.65, et, "壓力控制（εt ≤ εty）"
    phi = 0.65 + 0.25 * (et - ety) / 0.003
    return round(phi, 3), et, "過渡（φ 內插）"


def spacing_limit_mm(cc_mm, fs_mpa):
    """112 年版 §24.3.2 表 24.3.2（舊 100 年版 §3.7.2 式 3-6）：受撓裂縫控制之鋼筋最大中心距。

        s ≤ 380·(280/fs) − 2.5·cc   且   s ≤ 300·(280/fs)      （fs、280 為 MPa；cc 為 mm）

    112 版 §24.3.2／§24.3.2.1（及 100 版 §3.7.2）均以直接限制最大鋼筋間距取代前版 z 值規定。
    fs 為使用載重下之鋼筋應力，**亦可用 (2/3)fy 替代**（112 版 §24.3.2.1）。用 (2/3)fy 較保守。

    驗算（對照條文範例）：fy=4,200 kgf/cm² [420 MPa]、保護層 50 mm、採 (2/3)fy=280 MPa：
        s ≤ 380·(280/280) − 2.5×50 = 255 mm，且 ≤ 300 mm → 取 255 mm ✓
    """
    if fs_mpa <= 0 or cc_mm < 0:
        raise ValueError("fs 必須為正、cc 不得為負")
    s1 = 380.0 * (280.0 / fs_mpa) - 2.5 * cc_mm
    s2 = 300.0 * (280.0 / fs_mpa)
    return round(min(s1, s2), 1), round(s1, 1), round(s2, 1)


def flexure_design(
    Mu_kNm_per_m,
    b_mm=1000.0,
    h_mm=250.0,
    cc=None,
    *,
    As_required_min_mm2=None,
    max_spacing_mm=None,
    bar_prefer=None,
):
    """單筋矩形斷面撓曲設計（每公尺）。回傳 dict。"""
    c = dict(CONCRETE, **(cc or {}))
    fc, fy = c["fc_mpa"], c["fy_mpa"]
    d = h_mm - c["cover_mm"] - 10.0                   # 有效深度（保守扣半個主筋徑）
    if d <= 0:
        return {"ok": False, "error": "有效深度 d ≤ 0，斷面太薄"}

    Mu = Mu_kNm_per_m * 1e6                          # N·mm per m
    phi = c["phi_flexure"]

    # 求解 As：Mn = As·fy·(d − a/2)，a = As·fy/(0.85·fc·b)
    # 令 R = Mu/(φ·b·d²)，ρ = (0.85fc/fy)·(1 − √(1 − 2R/(0.85fc)))
    R = Mu / (phi * b_mm * d * d)                    # MPa
    disc = 1.0 - 2.0 * R / (0.85 * fc)
    if disc < 0:
        return {"ok": False, "error": "斷面不足（R 超過單筋上限），須加大斷面或改雙筋"}
    rho = (0.85 * fc / fy) * (1.0 - math.sqrt(disc))
    As_req = rho * b_mm * d

    # 最小鋼筋（取兩式較大）
    As_min1 = 0.0018 * b_mm * h_mm
    As_min2 = 1.4 * b_mm * d / fy
    As_min = max(As_min1, As_min2)

    # 最大鋼筋（避免超筋，ρmax = 0.75ρb 的簡化）
    rho_b = 0.85 * fc * 0.85 / fy * (87000.0 / (87000.0 + fy))   # 常用 β1=0.85 近似
    As_max = 0.75 * rho_b * b_mm * d

    As_design = max(As_req, As_min)
    if As_required_min_mm2 is not None:
        As_design = max(As_design, float(As_required_min_mm2))
    prefer = (
        tuple(bar_prefer)
        if bar_prefer
        else ("D16", "D19", "D22", "D25", "D13")
    )
    prefer = tuple(p for p in prefer if p in REBAR_SIZES) or (
        "D16", "D19", "D22", "D25", "D13"
    )
    name, spacing, As_prov = _pick_bars(
        As_design,
        c["cover_mm"],
        h_mm,
        prefer=prefer,
        max_spacing_mm=(
            300.0 if max_spacing_mm is None else float(max_spacing_mm)
        ),
    )

    a = As_prov * fy / (0.85 * fc * b_mm)
    Mn = As_prov * fy * (d - a / 2) / 1e6            # kN·m
    # 112 版表 21.2.2（舊 §2.3.2／§3.4.4）：φ 依實際配置鋼筋量之淨拉應變判定（不再一律 0.90）
    phi_chk, et, phi_basis = phi_by_strain(As_prov, b_mm, d, fc, fy,
                                          c.get("Es_mpa"))
    phi = phi_chk
    phiMn = phi * Mn

    # 112 版 §24.3.2／§24.3.2.1（舊 §3.7.2）裂縫控制：最大鋼筋中心距。
    # fs 取使用載重下之應力（本模組以 Mu/1.7 回推服務彎矩），
    # 條文亦允許以 (2/3)fy 保守替代 —— 兩者都算出來供比對。
    Ms = Mu_kNm_per_m / 1.7
    fs_service = Ms * 1e6 / max(As_prov * 0.9 * d, 1e-9) if As_prov > 0 else 0.0
    # 零彎矩或最小鋼筋控制時，服務應力會算成 0。此時仍須配置裂縫控制
    # 鋼筋，依 112 版 §24.3.2.1（舊 §3.7.2）允許的 (2/3)fy 保守值計算最大間距。
    if fs_service <= 0.0:
        fs_service = (2.0 / 3.0) * fy
    s_max, s_1, s_2 = spacing_limit_mm(c.get("cover_mm", 75.0), fs_service)
    s_max_cons, _, _ = spacing_limit_mm(c.get("cover_mm", 75.0), 280.0)

    return {
        "ok": phiMn >= Mu_kNm_per_m,
        "b_mm": b_mm, "h_mm": h_mm, "d_mm": round(d, 1),
        "Mu_kNm": round(Mu_kNm_per_m, 3),
        "phi": phi, "epsilon_t": round(et, 5), "phi_basis": phi_basis,
        # 112 版 §24.3.2（舊 §3.7.2）裂縫控制（最大鋼筋間距）
        "fs_service_mpa": round(fs_service, 1),
        "spacing_max_mm": s_max, "spacing_max_by_1": s_1, "spacing_max_by_2": s_2,
        "spacing_ok": spacing <= s_max,
        "spacing_max_conservative_mm": s_max_cons,
        "spacing_ok_conservative": spacing <= s_max_cons,
        "R_MPa": round(R, 4),
        "As_req_mm2": round(As_req, 1),
        "As_min_mm2": round(As_min, 1),
        "As_max_mm2": round(As_max, 1),
        "As_design_mm2": round(As_design, 1),
        "governed_by": (
            "裂縫控制"
            if As_required_min_mm2 is not None
            and float(As_required_min_mm2) >= max(As_req, As_min)
            else ("最小鋼筋" if As_min > As_req else "撓曲強度")
        ),
        "bar": name, "spacing_mm": spacing, "As_prov_mm2": round(As_prov, 1),
        "phiMn_kNm": round(phiMn, 3),
        "utilization": round(Mu_kNm_per_m / phiMn, 3) if phiMn > 0 else None,
    }


def shear_check(Vu_kN_per_m, b_mm=1000.0, h_mm=250.0, cc=None):
    """混凝土剪力強度檢核（無剪力筋，擋土牆／薄壁常用）。"""
    c = dict(CONCRETE, **(cc or {}))
    fc = c["fc_mpa"]
    d = h_mm - c["cover_mm"] - 10.0
    Vc = 0.17 * math.sqrt(fc) * b_mm * d / 1000.0    # kN per m
    phiVc = c["phi_shear"] * Vc
    return {
        "ok": phiVc >= Vu_kN_per_m,
        "Vu_kN": round(Vu_kN_per_m, 3),
        "Vc_kN": round(Vc, 3),
        "phiVc_kN": round(phiVc, 3),
        "utilization": round(Vu_kN_per_m / phiVc, 3) if phiVc > 0 else None,
    }


def beam_shear_design(
    Vu_kN,
    b_mm=300.0,
    h_mm=600.0,
    *,
    main_bar="D22",
    cc=None,
    stirrup_options=("D10", "D13"),
    legs=2,
):
    """矩形梁垂直箍筋初步設計。

    依《混凝土結構設計規範》112.08.10 現行版（括號內為 100.06.09 舊版條號對照）：
      - Vc = 0.17√fc′·bw·d（SI，112 版表 22.5.5.1 式 a／舊 §4.4.1.1）
      - φ = 0.75（112 版表 21.2.1／舊 §2.3.2）
      - Vs = Av·fyt·d/s（112 版 §22.5.8.5.3／舊 §4.6.7.2 式 4-15）
      - Vu/φ ≤ Vc + Vs
      - Vu > φVc/2 時配置最少剪力筋（100 版 §4.6.6.1；註：112 版 §9.6.3.1
        對 h > 25 cm 等一般梁改以 Vu > 0.265φλ√fc′·bw·d 為門檻，本函式留待細部設計覆核）
      - Av,min/s = max(0.062√fc′·bw/fyt, 0.35·bw/fyt)
        （112 版 §9.6.3.4／舊 §4.6.6.3）
      - s ≤ d/2 且 ≤ 60 cm；Vs 大於 1.06√fc′·bw·d（kgf/cm² 版，即 0.33√fc′·bw·d MPa）時減半
        （112 版表 9.7.6.2.2／舊 §4.6.5.1、§4.6.5.3）
      - Vs ≤ 2.12√fc′·bw·d（kgf/cm² 版，即 0.66√fc′·bw·d MPa，112 版 §22.5.1.2／舊 §4.6.7.9）
      - fyt 上限：100 版 §4.6.2 為 4,200 kgf/cm²（約 412 MPa）；112 版表 20.2.2.4(a) 為 4,200 [420 MPa]，
        本模組保守採 412 MPa

    本函式只做規則梁腹垂直兩肢箍筋；耐震圍束、扭力、接頭與錨定另計。
    """
    c = dict(CONCRETE, **(cc or {}))
    fc = float(c["fc_mpa"])
    # 112 版表 20.2.2.4(a) 上限 420 MPa（100 版 §4.6.2 為 4,200 kgf/cm² ≈ 412 MPa，保守續採 412 MPa）
    fyt = min(float(c["fy_mpa"]), 412.0)
    phi = float(c["phi_shear"])
    cover = float(c["cover_mm"])
    Vu = float(Vu_kN)
    b = float(b_mm)
    h = float(h_mm)
    if min(Vu, b, h, fc, fyt) < 0.0:
        raise ValueError("剪力、斷面與材料參數不得為負值")
    if h <= cover + 20.0:
        return {
            "ok": False,
            "error": "梁深不足以配置主筋與箍筋",
            "Vu_kN": round(Vu, 3),
            "b_mm": b,
            "h_mm": h,
        }

    main_dia = REBAR_SIZES.get(
        str(main_bar), REBAR_SIZES["D22"]
    )[0]
    candidates = []
    for name in stirrup_options:
        if name not in REBAR_SIZES:
            continue
        tie_dia, tie_area = REBAR_SIZES[name]
        d = h - cover - tie_dia - main_dia / 2.0
        if d <= 0.0:
            continue
        Vc = 0.17 * math.sqrt(fc) * b * d / 1000.0
        phiVc = phi * Vc
        Vs_req = max(0.0, Vu / phi - Vc)
        Vs_max = 2.12 * 0.313 * math.sqrt(fc) * b * d / 1000.0
        high_shear_threshold = 1.06 * 0.313 * math.sqrt(fc) * b * d / 1000.0
        if Vs_req > Vs_max + 1e-9:
            candidates.append(
                {
                    "ok": False,
                    "bar": name,
                    "error": "斷面不足：所需 Vs 超過 112 版 §22.5.1.2（舊 §4.6.7.9）上限",
                    "d_mm": round(d, 1),
                    "Vc_kN": round(Vc, 3),
                    "phiVc_kN": round(phiVc, 3),
                    "Vs_req_kN": round(Vs_req, 3),
                    "Vs_max_kN": round(Vs_max, 3),
                }
            )
            continue

        Av = legs * tie_area
        av_s_strength = (
            Vs_req * 1000.0 / (fyt * d) if Vs_req > 1e-12 else 0.0
        )
        av_s_min = max(
            0.062 * math.sqrt(fc) * b / fyt,
            0.35 * b / fyt,
        )
        minimum_required = Vu > phiVc / 2.0
        av_s_required = max(
            av_s_strength, av_s_min if minimum_required else 0.0
        )
        max_spacing = min(d / 2.0, 600.0)
        if Vs_req > high_shear_threshold:
            max_spacing = min(d / 4.0, 300.0)

        if av_s_required > 1e-12:
            spacing_strength = Av / av_s_required
        else:
            spacing_strength = max_spacing
        spacing = min(max_spacing, spacing_strength)
        spacing = math.floor(spacing / 10.0) * 10.0
        if spacing < 50.0:
            candidates.append(
                {
                    "ok": False,
                    "bar": name,
                    "error": "所需箍筋間距小於 50 mm；請加大梁斷面或改用較大箍筋",
                    "d_mm": round(d, 1),
                    "Av_mm2": round(Av, 1),
                    "required_spacing_mm": round(spacing_strength, 1),
                    "max_spacing_mm": round(max_spacing, 1),
                }
            )
            continue

        Vs_prov = Av * fyt * d / spacing / 1000.0
        phiVn = phi * (Vc + Vs_prov)
        spacing_ok = spacing <= max_spacing + 1e-9
        Av_s_prov = Av / spacing
        minimum_ok = (not minimum_required) or (
            Av_s_prov >= av_s_min - 1e-12
        )
        section_ok = Vs_prov <= Vs_max + 1e-9
        ok = (
            phiVn >= Vu
            and spacing_ok
            and minimum_ok
            and section_ok
        )
        candidates.append(
            {
                "ok": ok,
                "bar": name,
                "legs": legs,
                "area_per_bar_mm2": round(tie_area, 1),
                "Av_mm2": round(Av, 1),
                "spacing_mm": int(spacing),
                "max_spacing_mm": round(max_spacing, 1),
                "d_mm": round(d, 1),
                "Vu_kN": round(Vu, 3),
                "Vc_kN": round(Vc, 3),
                "phiVc_kN": round(phiVc, 3),
                "Vs_req_kN": round(Vs_req, 3),
                "Vs_prov_kN": round(Vs_prov, 3),
                "Vs_max_kN": round(Vs_max, 3),
                "phiVn_kN": round(phiVn, 3),
                "utilization": round(Vu / phiVn, 3) if phiVn > 0 else None,
                "Av_s_req_mm2_per_mm": round(av_s_required, 5),
                "Av_s_min_mm2_per_mm": round(av_s_min, 5),
                "Av_s_prov_mm2_per_mm": round(Av_s_prov, 5),
                "minimum_required": minimum_required,
                "minimum_ok": minimum_ok,
                "spacing_ok": spacing_ok,
                "section_ok": section_ok,
            }
        )

    feasible = [row for row in candidates if row.get("ok")]
    if feasible:
        # Prefer the smaller bar that can develop the demand; if several work,
        # prefer the larger spacing for constructability.
        chosen = sorted(
            feasible,
            key=lambda row: (
                REBAR_SIZES[row["bar"]][0],
                -row.get("spacing_mm", 0),
            ),
        )[0]
    elif candidates:
        chosen = candidates[0]
    else:
        chosen = {
            "ok": False,
            "error": "沒有可用的箍筋筋號",
        }
    out = dict(chosen)
    out.update(
        {
            "Vu_kN": round(Vu, 3),
            "b_mm": b,
            "h_mm": h,
            "fc_mpa": fc,
            "fyt_mpa": fyt,
            "phi_shear": phi,
            "main_bar": str(main_bar),
            "stirrup": {
                "bar": chosen.get("bar"),
                "legs": legs,
                "spacing_mm": chosen.get("spacing_mm"),
                "max_spacing_mm": chosen.get("max_spacing_mm"),
            },
            "basis": (
                "混凝土結構設計規範 112.08.10 版 表 21.2.1、§9.6.3.1／§9.6.3.4、"
                "表 9.7.6.2.2、表 20.2.2.4(a)、§22.5.1.2、表 22.5.5.1、§22.5.8.5.3"
                "（對應 100.06.09 版 §2.3.2、§4.4.1.1、§4.6.2～§4.6.7.9）"
            ),
            "note": (
                "初步規則梁箍筋設計；耐震圍束、扭力、梁柱接頭、"
                "彎鉤錨定與施工可行性仍須技師覆核。"
            ),
            "candidates": candidates,
        }
    )
    return out


def crack_width(As_prov_mm2, b_mm=1000.0, h_mm=250.0, spacing_mm=200.0, cc=None,
                M_service_kNm=None):
    """Gergely-Lutz 裂縫寬度估算（mm）。

    fs 優先由**服務載重**反算（fs = M/(As·0.9d)，較真實）；
    未給服務載重時才退回 0.6fy（保守上限）。先前一律用 0.6fy，
    會把本來合格的配筋判成不合格。
    """
    c = dict(CONCRETE, **(cc or {}))
    fy, Es = c["fy_mpa"], c["Es_mpa"]
    cover = c["cover_mm"]
    d = h_mm - cover - 10.0
    if M_service_kNm is not None and As_prov_mm2 > 0:
        fs = min(M_service_kNm * 1e6 / (As_prov_mm2 * 0.9 * d), 0.6 * fy)
    else:
        fs = 0.6 * fy
    dc = cover + 10.0                                # 最外層主筋中心至受拉面
    n = max(1.0, 1000.0 / spacing_mm)                # 每公尺根數
    A = 2 * dc * (1000.0 / n) / 1000.0               # 每根筋之包圍混凝土面積（×1000 換算）
    A_mm2 = 2 * dc * (1000.0 / n)
    beta = 1.2                                      # 底層受撓（保守）
    w = 2.2 * beta * fs * (dc * A_mm2) ** (1.0 / 3.0) / (Es * 1000.0) * 1000.0
    return {"w_mm": round(w, 4), "fs_MPa": round(fs, 1), "dc_mm": round(dc, 1),
            "ok": w <= c["crack_limit_mm"], "limit_mm": c["crack_limit_mm"]}


# --------------------------------------------------------------------------- #
# 擋土牆莖板
# --------------------------------------------------------------------------- #
def wall_min_steel(b_mm, t_mm):
    """112 版 §11.6.1 表 11.6.1／§11.7.2.3（舊 100 版 §7.4.2～7.4.4）：牆之最少鋼筋量（mm²/m）。

    112.08.10 現行版第 11 章「牆」與 100.06.09 舊版對照：
      - 垂直鋼筋比 ρl：112 版表 11.6.1 場鑄 ≤D16 且 fy≥420 時為 0.0012，其餘 0.0015
        （舊 §7.4.2 一律 0.0015）。本模組保守續採 ρl = 0.0015。
      - 水平鋼筋比 ρt：112 版表 11.6.1 場鑄 ≤D16 且 fy≥420 時為 0.0020，其餘 0.0025
        （舊 §7.4.3 一律 0.0025）。本模組保守續採 ρt = 0.0025。
      - 雙層配置：112 版 §11.7.2.3 對 t > 25 cm 規定分兩層（並新增懸臂擋土牆與單層樓
        地下室牆例外）；為兼顧施工與兩側防裂，本模組仍保守採 t ≥ 25 cm 分兩層設置（同舊 §7.4.4）。

    ⚠ 先前本模組曾把分布筋誤用溫度收縮筋 0.0018·b·t·0.5（= 315 mm²/m），遠低於規範要求；
      §24.3.2（舊 §3.7.2）最大鋼筋間距只管**梁與單向版**，不適用於牆。
    """
    return {
        "As_vertical_min_mm2": round(0.0015 * b_mm * t_mm, 1),
        "As_horizontal_min_mm2": round(0.0025 * b_mm * t_mm, 1),
        "two_layers_required": t_mm >= 250.0,
        "basis": "112 版 §11.6.1 表 11.6.1（保守採 ρl=0.0015、ρt=0.0025）／§11.7.2.3 t≥25cm 分兩層（對應 100 版 §7.4.2～7.4.4）",
    }


# 重力式／半重力式的名目構造鋼筋（非強度控制）
MASS_WALL_FACE_BAR = "D13"
MASS_WALL_FACE_SPACING_MM = 250.0
MASS_WALL_BASE_BAR = "D16"
MASS_WALL_BASE_SPACING_MM = 200.0
MASS_WALL_TEMPERATURE_RATIO = 0.002


def design_mass_wall_steel(q, wall_res=None, cc=None):
    """重力式／半重力式擋土牆的名目構造鋼筋（不是撓曲配筋）。

    為什麼不套懸臂公式
    ------------------
    重力式靠自重穩定，牆身屬大體積混凝土；半重力式的牆身厚度由頂寬與
    牆面坡度決定（可達 1 m 以上），撓曲需求極小。兩者若套用懸臂式的
    莖板／底板配筋，會產生不存在的鋼筋量（實測重力式 3 m 被算出
    66.8 kg/m）。工作簿 `擋土牆安定分析.mod.xls` 的重力式工作表也只在
    止滑榫（b>0）才設計受力鋼筋。

    本函式只提供**溫度收縮與構造鋼筋**：
      牆面（露出側）D13@250（垂直向＋水平向，單面雙向）
      底部縱向 D16@200（沿牆長、分佈於底寬）
    並以 250 mm 有效表層換算溫度鋼筋比，確認為 0.002 以上。

    ⚠ 計量單位：`As` 是「每公尺排筋方向的鋼筋面積」（mm²/m）。
      垂直筋的長度 = 牆高 H；水平筋的長度 = 牆高 H（沿高度共有 H/間距 層，
      每層 1 m）；底部縱筋的長度 = 底寬 BL。三者不可一律乘 1.0 m ——
      先前版本把水平筋與底部筋都乘 1.0，分別少算 H 倍與 BL 倍。
    """
    c = dict(CONCRETE, **(cc or {}))
    H = float(q["height_m"])
    BL = float(q["base_width_m"])
    face_bar = str(q.get("mass_wall_face_bar") or MASS_WALL_FACE_BAR)
    face_sp = float(q.get("mass_wall_face_spacing_mm") or MASS_WALL_FACE_SPACING_MM)
    base_bar = str(q.get("mass_wall_base_bar") or MASS_WALL_BASE_BAR)
    base_sp = float(q.get("mass_wall_base_spacing_mm") or MASS_WALL_BASE_SPACING_MM)
    surface_mm = float(q.get("mass_wall_surface_mm") or 250.0)
    if face_bar not in REBAR_SIZES or base_bar not in REBAR_SIZES:
        raise ValueError("mass_wall_face_bar／base_bar 必須是 %s" %
                         "、".join(sorted(REBAR_SIZES)))
    if face_sp <= 0 or base_sp <= 0:
        raise ValueError("構造鋼筋間距必須大於 0")

    As_face = _bar_area(face_bar) * 1000.0 / face_sp
    As_base = _bar_area(base_bar) * 1000.0 / base_sp
    rho = As_face / (1000.0 * surface_mm)

    rows = [
        ("牆面（露出側）垂直構造筋", As_face, H),
        ("牆面（露出側）水平構造筋", As_face, H),
        ("底部縱向構造筋", As_base, BL),
    ]
    detail = [{"item": n, "As_mm2": round(a, 1), "len_m": round(l, 3),
               "kg_per_m": round(_kg(a, l), 3)} for n, a, l in rows]
    sub = sum(_kg(a, l) for n, a, l in rows)
    total = sub * (1.0 + LAP_ALLOWANCE)
    return {
        "structural_rebar": False,
        "face_bar": face_bar, "face_spacing_mm": face_sp,
        "base_bar": base_bar, "base_spacing_mm": base_sp,
        "As_face_mm2_per_m": round(As_face, 1),
        "As_base_mm2_per_m": round(As_base, 1),
        "temperature_ratio": round(rho, 5),
        "temperature_min": MASS_WALL_TEMPERATURE_RATIO,
        "surface_mm": surface_mm,
        "rows": detail,
        "subtotal_kg_per_m": round(sub, 3),
        "total_kg_per_m": round(total, 3),
        "lap_allowance": LAP_ALLOWANCE,
        "ok": rho >= MASS_WALL_TEMPERATURE_RATIO,
        "note": ("重力式／半重力式不設撓曲主筋；本表為牆面（露出側）單面雙向"
                 "溫度收縮與構造鋼筋＋底部縱筋，止滑榫另依實際設置情形設計。"),
    }


def _rebar_mass(rows, *, note, applicable=True, basis=""):
    """把 (位置, 等效 As mm²/m, 長度 m) 彙總成每公尺牆長的鋼筋量。"""
    detail = []
    for name, area, length in rows:
        area = max(0.0, float(area or 0.0))
        length = max(0.0, float(length or 0.0))
        detail.append({
            "item": name,
            "As_mm2": round(area, 1),
            "len_m": round(length, 3),
            "kg_per_m": round(_kg(area, length), 3),
        })
    subtotal = sum(r["kg_per_m"] for r in detail)
    total = subtotal * (1.0 + LAP_ALLOWANCE) if applicable else 0.0
    return {
        "applicable": bool(applicable),
        "rows": detail,
        "subtotal_kg_per_m": round(subtotal, 3),
        "total_kg_per_m": round(total, 3),
        "lap_allowance": LAP_ALLOWANCE,
        "ok": True,
        "basis": basis,
        "note": note,
    }


def _max_member_steel(members, *tokens):
    values = []
    for member in members or []:
        name = str(member.get("member") or "")
        if all(token in name for token in tokens):
            values.append(float((member.get("flexure") or {}).get("As_prov_mm2") or 0.0))
    return max(values) if values else 0.0


def design_counterfort_wall_steel(q, wall_res, cc=None):
    """扶壁式擋土牆每公尺牆長的鋼筋量（牆板、底板、扶壁、繫筋）。"""
    g = wall_res["geometry"]
    st = wall_res.get("structure") or {}
    slabs = st.get("slabs") or []
    H = float(g["H"])
    ts = float(g["ts"])
    tb = float(g["tb"])
    heel = float(g["heel"])
    toe = float(g["Lt"])
    tc = float(g["tc"])
    ctop = float(g["ctop"])
    S = float(g["S"])
    c = dict(CONCRETE, **(cc or {}))
    cover = float(c["cover_mm"])

    rows = [
        ("牆板背面鉛直筋", _max_member_steel(slabs, "牆板", "鉛直負彎矩"), H),
        ("牆板前面鉛直筋", _max_member_steel(slabs, "牆板", "鉛直正彎矩"), H),
        ("牆板背面水平筋", _max_member_steel(slabs, "牆板", "水平負彎矩"), H),
        ("牆板前面水平筋", _max_member_steel(slabs, "牆板", "水平正彎矩"), H),
        ("踵板上層筋", _max_member_steel(slabs, "踵板負彎矩"), heel),
        ("踵板下層筋", _max_member_steel(slabs, "踵板正彎矩"), heel),
        ("趾板下層筋", _max_member_steel(slabs, "趾板"), toe),
    ]

    cf = st.get("counterfort") or {}
    main = cf.get("main") or {}
    if main.get("bar") and main.get("count"):
        bar = str(main["bar"])
        count = int(main["count"])
        diagonal = math.hypot(H, heel - ctop)
        rows.append(("扶壁主拉力筋（%d-%s／支）" % (count, bar),
                     count * _bar_area(bar) / S, diagonal))

    stirrup = cf.get("stirrup") or {}
    if stirrup.get("bar") and stirrup.get("spacing_mm"):
        bar = str(stirrup["bar"])
        spacing = float(stirrup["spacing_mm"]) / 1000.0
        diagonal = math.hypot(H, heel - ctop)
        n_ties = math.ceil(diagonal / max(spacing, 1e-9)) + 1
        width = max(tc - 2.0 * cover / 1000.0, 0.10)
        depth = max(float(cf.get("d_mm") or 0.0) / 1000.0 - 2.0 * cover / 1000.0, 0.10)
        tie_length = 2.0 * (width + depth) + 0.30
        rows.append(("扶壁水平箍筋（%s 兩肢 @%d）" % (bar, int(stirrup["spacing_mm"])),
                     n_ties * _bar_area(bar) / S, tie_length))

    tie_lengths = {
        "牆板": ts + 0.60,
        "踵板": tb + 0.60,
    }
    for tie in st.get("ties") or []:
        name = str(tie.get("member") or "")
        length = tie_lengths.get("牆板" if "牆板" in name else "踵板", 1.0)
        rows.append(("%s（%s 兩肢 @%d）" % (name, tie.get("bar"), int(tie.get("spacing_mm") or 0)),
                     float(tie.get("As_prov_mm2_per_m") or 0.0), length))

    out = _rebar_mass(
        rows,
        note=("依扶壁式引擎之牆板三帶彎矩、踵板連續版、趾板懸臂、扶壁 T 梁與繫筋設計彙總；"
              "箍筋與繫筋長度採矩形圍束與 0.6 m 錨定長度之保守估列，施工詳圖仍須依實際彎鉤調整。"),
        basis="混凝土結構設計規範 112.08.10 版 表 21.2.2、§9.6.1.2、§13.3.6.1.1（對應 100 版 §3.4.4、§3.6.1、§4.4.1.1）；常時土壓採 1.7H 保守慣例",
    )
    out["ok"] = bool(wall_res.get("pass")) and all(
        bool((m.get("flexure") or {}).get("ok")) for m in slabs
    )
    return out


def design_anchored_wall_steel(q, wall_res, cc=None):
    """錨定式擋土牆每公尺牆長的牆面、基腳鋼筋與地錨承壓區補強。"""
    members = (wall_res.get("wall") or {}).get("members") or []
    g = wall_res["geometry"]
    H = float(g["H"])
    B = float(g["B"])
    tb = float(g["tb"])
    sh = float(g["sh"])
    n_anchor_rows = len(wall_res.get("anchors") or [])
    c = dict(CONCRETE, **(cc or {}))
    rows = [
        ("牆面鉛直筋（背面，地錨處）",
         _max_member_steel(members, "牆面鉛直筋", "背面"), H),
        ("牆面鉛直筋（正面，跨中）",
         _max_member_steel(members, "牆面鉛直筋", "正面"), H),
        ("牆面水平筋（背面，地錨處）",
         _max_member_steel(members, "牆面水平筋", "背面"), H),
        ("牆面水平筋（正面，跨中）",
         _max_member_steel(members, "牆面水平筋", "正面"), H),
    ]
    mesh_side_m = 1.00
    mesh_spacing_m = 0.20
    n_bars = int(math.ceil(mesh_side_m / mesh_spacing_m)) + 1
    mesh_as = _bar_area("D13") * 2.0 * n_bars / max(sh, 1e-9)
    rows.append(("地錨承壓區補強網（正面 D13@200 雙向，1.0×1.0 m）",
                 mesh_as, float(n_anchor_rows)))

    # 基腳是牆面的支承，不能只畫在圖上卻不計鋼筋。依最小鋼筋量配置
    # 上下兩層橫向筋（長度＝基腳寬）與縱向分布筋（沿牆長 1 m）。
    as_min = 0.0018 * 1000.0 * tb * 1000.0
    base_bar, base_sp, base_as = _pick_bars(
        as_min, c["cover_mm"], tb * 1000.0, prefer=("D16", "D13")
    )
    rows += [
        ("基腳底層橫向筋", base_as, B),
        ("基腳頂層橫向筋", base_as, B),
        ("基腳縱向分布筋（上下層）", 2.0 * base_as * B, 1.0),
    ]

    out = _rebar_mass(
        rows,
        note=("牆面四向筋取自連續梁撓曲設計；基腳以最小鋼筋配置上下層橫向筋與"
              "縱向分布筋；地錨承壓區以每排 1.0×1.0 m、D13@200 單面雙向補強網估列，"
              "未含錨頭鋼鈑、螺旋筋與施工架。"),
        basis="公路邊坡工程設計規範第六章、混凝土結構設計規範 112.08.10 版（對應 100 版）；常時土壓採 1.7H 保守慣例",
    )
    out["base_rebar"] = {
        "bar": base_bar,
        "spacing_mm": int(base_sp),
        "As_prov_mm2_per_m": round(base_as, 1),
        "basis": "基腳最小鋼筋 0.0018bh；上下層橫向筋＋縱向分布筋",
    }
    out["ok"] = bool(wall_res.get("pass")) and all(
        bool((m.get("flexure") or {}).get("ok")) for m in members
    )
    return out


def design_mse_face_steel(q, wall_res, cc=None):
    """加勁式擋土牆 RC 面版初步配筋（每公尺牆長）。"""
    facing = str(q.get("facing_type") or q.get("face_panel_type") or "precast_panel").lower()
    if facing in ("segmental_block", "block", "none", "不配筋"):
        return _rebar_mass(
            [],
            applicable=False,
            note="所選面版為塊狀面版或不配置 RC 鋼筋；面版連接強度仍須另行檢核。",
            basis="水土保持技術規範 §118 六(三)",
        )

    g = wall_res["geometry"]
    H = float(g["height_m"])
    thickness = float(q.get("face_panel_thickness_m") or 0.20)
    panel_width = float(q.get("panel_width_m") or 1.50)
    layer_spacing = float(q.get("vertical_spacing_m") or 0.60)
    span = max(panel_width, layer_spacing)
    gamma_r = float((wall_res.get("soil") or {}).get("reinforced_gamma") or 19.0)
    qs = float((wall_res.get("soil") or {}).get("surcharge_kpa") or 0.0)
    ka = float(wall_res.get("Ka_retained") or 0.333)
    p = ka * (gamma_r * H + qs)
    Mu = 1.7 * p * span ** 2 / 8.0

    panel_cc = dict(CONCRETE, **(cc or {}))
    panel_cc["cover_mm"] = float(q.get("face_panel_cover_mm") or 50.0)
    flex = flexure_design(
        Mu,
        b_mm=1000.0,
        h_mm=thickness * 1000.0,
        cc=panel_cc,
        bar_prefer=("D13", "D16"),
    )
    as_min = 0.0018 * 1000.0 * thickness * 1000.0
    bar, spacing, as_prov = _pick_bars(
        max(float(flex.get("As_prov_mm2") or 0.0), as_min),
        panel_cc["cover_mm"],
        thickness * 1000.0,
        prefer=("D13", "D16"),
    )
    rows = [
        ("面版水平筋（單層）", as_prov, H),
        ("面版豎向筋（單層）", as_prov, H),
    ]
    out = _rebar_mass(
        rows,
        note=("面版採 %.0f mm 厚 RC 預鑄／場鑄面版，以 %.2f m 跨度、底部土壓 %.2f kPa "
              "作單向版初步設計；面版－加勁材連接、吊裝與溫度收縮細節仍須另計。"
              % (thickness * 1000.0, span, p)),
        basis="水土保持技術規範 §118 六(三)、混凝土結構設計規範 112.08.10 版（對應 100 版）",
    )
    out.update({
        "facing_type": facing,
        "face_panel_thickness_mm": round(thickness * 1000.0, 1),
        "panel_width_m": round(panel_width, 3),
        "design_pressure_kpa": round(p, 3),
        "Mu_kNm_per_m": round(Mu, 3),
        "bar": bar,
        "spacing_mm": int(spacing),
        "As_prov_mm2_per_m": round(as_prov, 1),
        "flexure_ok": bool(flex.get("ok")),
    })
    out["ok"] = bool(wall_res.get("pass")) and bool(flex.get("ok")) and thickness >= 0.14
    return out


BLOCK_WALL_TYPES = ("gabion", "crib", "masonry_wet", "masonry_dry", "sandwich")


def design_block_wall_steel(q, wall_res=None, cc=None):
    """疊砌／砌石牆不配置 RC 鋼筋，鋼筋量明確為零。"""
    wt = str((wall_res or {}).get("wall_type") or q.get("wall_type") or "").lower()
    return _rebar_mass(
        [],
        applicable=False,
        note=("%s 為疊砌式或加勁式非 RC 牆體，不配置 RC 鋼筋；"
              "蛇籠網線、格籠構件或面版連接件之材料規格另依標準圖檢核。" % wt),
        basis="水土保持技術規範 §118 六～八",
    )


def design_wall_rebar(q, wall_res, cc=None):
    """依牆型分流的配筋設計唯一入口。

    回傳 ``total_kg_per_m`` 供數量、預算、報告共用，避免各處自行判斷
    wall_type 而出現「報告說無須配筋、預算卻算懸臂鋼筋」的矛盾。
    """
    wt = str((wall_res or {}).get("wall_type") or q.get("wall_type") or "").lower()
    if wt in ("gravity", "semigravity"):
        mass = design_mass_wall_steel(q, wall_res, cc)
        return {"wall_type": wt, "structural": None, "mass": mass,
                "total_kg_per_m": mass["total_kg_per_m"], "ok": mass["ok"]}
    if wt == "cantilever":
        stem = design_cantilever_stem(q, wall_res, cc)
        base = design_base_slab(q, wall_res, cc)
        kg = rebar_kg_per_m(q, stem, base)
        ok = bool(stem.get("ok"))
        if base:
            ok = ok and all(m.get("ok") for m in base.get("members") or [])
        return {"wall_type": wt, "structural": {"stem": stem, "base": base},
                "mass": None, "kg": kg, "total_kg_per_m": kg["total_kg_per_m"],
                "ok": ok}
    if wt == "counterfort":
        steel = design_counterfort_wall_steel(q, wall_res, cc)
        return {"wall_type": wt, "structural": steel, "mass": None,
                "total_kg_per_m": steel["total_kg_per_m"], "ok": steel["ok"]}
    if wt == "anchored":
        steel = design_anchored_wall_steel(q, wall_res, cc)
        return {"wall_type": wt, "structural": steel, "mass": None,
                "total_kg_per_m": steel["total_kg_per_m"], "ok": steel["ok"]}
    if wt == "mse":
        steel = design_mse_face_steel(q, wall_res, cc)
        return {"wall_type": wt, "structural": steel, "mass": None,
                "total_kg_per_m": steel["total_kg_per_m"], "ok": steel["ok"]}
    if wt in BLOCK_WALL_TYPES:
        steel = design_block_wall_steel(q, wall_res, cc)
        return {"wall_type": wt, "structural": steel, "mass": None,
                "total_kg_per_m": 0.0, "ok": True}
    raise ValueError(
        "擋土牆配筋尚未支援 wall_type=%r（支援 gravity／semigravity／cantilever／"
        "counterfort／anchored／mse／gabion／crib／masonry_wet／masonry_dry／sandwich）" % wt)


def design_cantilever_stem(q, wall_res, cc=None):
    """懸臂式擋土牆莖板配筋（牆底為控制斷面）。

    土壓力三角形分佈：牆底彎矩 M = Pa·(H/3)（對牆底取力矩，每公尺牆長）
    另計牆頂集中載重時可再擴充。
    """
    c = dict(CONCRETE, **(cc or {}))
    H = float(q["height_m"])
    T = float(q["stem_thickness_m"])
    Pa = float(wall_res["Pa_kN_per_m"])
    y_Pa = float(wall_res["y_Pa_m"])

    M_stem = Pa * y_Pa                              # kN·m/m（牆底）
    V_stem = Pa                                     # kN/m（牆底剪力）

    # 載重放大（工作載重 → 設計強度，採 1.4D+1.7L 之簡化，土壓力視為 L）
    Mu = 1.7 * M_stem
    Vu = 1.7 * V_stem

    flex = flexure_design(Mu, b_mm=1000.0, h_mm=T * 1000.0, cc=c,
                          bar_prefer=_single_pref(q.get("stem_bar")))
    shr = shear_check(Vu, b_mm=1000.0, h_mm=T * 1000.0, cc=c)
    if flex.get("ok"):
        cw = crack_width(flex["As_prov_mm2"], spacing_mm=flex["spacing_mm"],
                         h_mm=T * 1000.0, cc=c, M_service_kNm=M_stem)
    else:
        cw = {"ok": False, "w_mm": None}

    # 水平鋼筋：112 版 §11.6.1 表 11.6.1（舊 §7.4.3）要求 ρt=0.0025（保守值），且不小於主筋 1/3。
    # ⚠ 先前誤用溫度收縮筋 0.0018·b·t·0.5（=315），僅為規範要求的 36%。
    _wm = wall_min_steel(1000.0, T * 1000.0)
    As_dist = max(_wm["As_horizontal_min_mm2"],
                  flex.get("As_prov_mm2", 0) / 3.0)
    dist_name, dist_sp, As_dist_prov = _pick_bars(As_dist, c["cover_mm"],
                                                  prefer=("D13", "D10"))

    return {
        "member": "懸臂式擋土牆莖板（牆底控制斷面）",
        "M_service_kNm": round(M_stem, 3), "Mu_kNm": round(Mu, 3),
        "V_service_kN": round(V_stem, 3), "Vu_kN": round(Vu, 3),
        "thickness_mm": round(T * 1000.0, 1),
        "main": flex, "shear": shr, "crack": cw,
        "dist_bar": dist_name, "dist_spacing_mm": dist_sp,
        "dist_As_mm2": round(As_dist_prov, 1),
        "ok": bool(flex.get("ok") and shr.get("ok") and cw.get("ok")),
        "note": "主筋置於受拉面（牆背側）；分布筋置於受壓面。載重組合採 1.7×(土壓力) 簡化放大。",
    }


def design_channel_wall(q, hy_res, cc=None):
    """排水溝溝壁配筋（矩形內腔，單側壁以懸臂板考慮）。

    控制載重：溝內滿水 + 溝外側土壓力（無土工參數時僅計水壓力，並標明）。
    """
    c = dict(CONCRETE, **(cc or {}))
    H = float(q["depth_m"])
    t = float(q["wall_thickness_m"])
    h_n = float(hy_res.get("h_normal_m") or H)
    gW = 9.81

    # 溝內水壓力（三角形）：M = γw·h³/6（對牆底）
    M_water = gW * h_n ** 3 / 6.0
    V_water = 0.5 * gW * h_n ** 2

    Mu = 1.7 * M_water
    Vu = 1.7 * V_water

    flex = flexure_design(Mu, b_mm=1000.0, h_mm=t * 1000.0, cc=c)
    shr = shear_check(Vu, b_mm=1000.0, h_mm=t * 1000.0, cc=c)
    if flex.get("ok"):
        cw = crack_width(flex["As_prov_mm2"], spacing_mm=flex["spacing_mm"],
                         h_mm=t * 1000.0, cc=c, M_service_kNm=M_water)
    else:
        cw = {"ok": False, "w_mm": None}

    # 溝壁水平筋：比照 112 版 §11.6.1（舊 §7.4.3）ρt=0.0025（牆式構材保守採同一下限），且 ≥ 主筋 1/3
    _wm = wall_min_steel(1000.0, t * 1000.0)
    As_dist = max(_wm["As_horizontal_min_mm2"],
                  flex.get("As_prov_mm2", 0) / 3.0)
    dist_name, dist_sp, As_dist_prov = _pick_bars(As_dist, c["cover_mm"],
                                                  prefer=("D13", "D10"))

    return {
        "member": "排水溝溝壁（牆底控制斷面）",
        "M_service_kNm": round(M_water, 3), "Mu_kNm": round(Mu, 3),
        "V_service_kN": round(V_water, 3), "Vu_kN": round(Vu, 3),
        "thickness_mm": round(t * 1000.0, 1),
        "main": flex, "shear": shr, "crack": cw,
        "dist_bar": dist_name, "dist_spacing_mm": dist_sp,
        "dist_As_mm2": round(As_dist_prov, 1),
        "ok": bool(flex.get("ok") and shr.get("ok") and cw.get("ok")),
        "note": "僅計溝內水壓力；溝外側土壓力須俟土工參數確定後另計（目前無資料）。"
                "溝底以構造筋配置，未做承載檢核。",
    }


STEEL_DENSITY = 7850.0        # kg/m³
# 搭接、錨定與損耗率：**全專案 RC 鋼筋一律 6%（含搭接）**。
# 2026-11-04 使用者指示：擋土牆、排水溝與箱涵的鋼筋損耗率一致採 6%，
# 先前把擋土牆／排水溝另切 12% 屬未經授權的分家，已撤除。
LAP_ALLOWANCE = 0.06


def _kg(As_mm2_per_m, bar_len_m):
    """As［mm²/m 排筋方向］× 鋼筋長［m］→ kg/m（每公尺牆長）。

    ⚠ 這裡是先前寫錯的地方：`As_mm2 × 7850` 得到的是「每公尺**鋼筋長**的 kg」，
    不是「每公尺**牆長**的 kg」。垂直筋的長度是牆高、不是 1 m ——
    漏乘鋼筋長度會讓估計偏低到 1/3（實測 32 kg/m vs 正確 108 kg/m）。
    """
    return As_mm2_per_m * 1e-6 * bar_len_m * STEEL_DENSITY


def rebar_kg_per_m(q, design_stem, design_base=None):
    """由配筋設計推算每公尺牆長的鋼筋量（kg/m），含搭接損耗。

    計入的鋼筋（雙面雙向的 RC 牆標準配置）：
      牆身：背側垂直主筋（長 = 牆高）、面側水平分布筋（長 = 1 m）、
            另一面之兩向筋（保守以主筋＋分布筋、長 = 牆高計）
      底板：踵板頂／底、趾板頂／底 各一層縱向筋（長 = 1 m）
            底板橫向分布筋（長 = 板寬，兩層）

    ※ 本案配筋設計只給「一向/面」的 As，故以雙面雙向保守補足。
      正式設計應逐面列出，本函式屆時可改為逐面加總。
    """
    H = float(q["height_m"])
    T = float(q["stem_thickness_m"])
    BL = float(q["base_width_m"])
    BT = float(q["base_thickness_m"])
    As_main = float((design_stem.get("main") or {}).get("As_prov_mm2") or 0)
    As_dist = float(design_stem.get("dist_As_mm2") or 0)
    rows = [("牆身垂直主筋（全高）", As_main, H),
            ("牆身水平分布筋（沿牆長）", As_dist, 1.0),
            ("牆身另一面之兩向筋（保守）", As_main + As_dist, H)]
    if design_base:
        memb = design_base.get("members") or []
        if len(memb) >= 2:
            As_heel = float((memb[0].get("main") or {}).get("As_prov_mm2") or 0)
            As_toe = float((memb[1].get("main") or {}).get("As_prov_mm2") or 0)
            heel_w = max(BL - T, 0.0)
            rows += [("踵板上層筋（縱向）", As_heel, 1.0),
                     ("踵板下層筋（縱向）", As_heel, 1.0),
                     ("趾板上層筋（縱向）", As_toe, 1.0),
                     ("趾板下層筋（縱向）", As_toe, 1.0),
                     ("底板橫向分布筋（兩層）", As_dist, heel_w * 2.0)]
    rows = [(n, a, l, _kg(a, l)) for n, a, l in rows]
    sub = sum(r[3] for r in rows)
    total = sub * (1 + LAP_ALLOWANCE)
    return {"rows": [{"item": n, "As_mm2": round(a, 1), "len_m": round(l, 3),
                      "kg_per_m": round(v, 3)} for n, a, l, v in rows],
            "subtotal_kg_per_m": round(sub, 3),
            "total_kg_per_m": round(total, 3),
            "lap_allowance": LAP_ALLOWANCE}


def rebar_kg_per_m_channel(q, design_channel):
    """排水溝每公尺溝長的鋼筋量（kg/m），含搭接損耗。

    U 型溝的鋼筋組成：
      溝壁垂直主筋（2 壁，長 = 溝深 H）
      溝壁水平分布筋（2 壁，沿溝長方向 1 m）
      溝底橫向筋（跨外寬 W）
      溝底縱向分布筋（沿溝長方向 1 m）

    同樣注意單位：`As[mm²/m] × 7850` 只是「每公尺**鋼筋長**」的 kg，
    必須再乘該類鋼筋的實際長度。
    """
    B = float(q["inner_width_m"]); H = float(q["depth_m"])
    t = float(q["wall_thickness_m"]); tb = float(q["base_thickness_m"])
    W = B + 2.0 * t
    As_main = float((design_channel.get("main") or {}).get("As_prov_mm2") or 0)
    As_dist = float(design_channel.get("dist_As_mm2") or 0)
    rows = [("溝壁垂直主筋（2 壁，全高）", 2 * As_main, H),
            ("溝壁水平分布筋（2 壁，沿溝長）", 2 * As_dist, 1.0),
            ("溝底橫向筋（跨外寬）", As_dist, W),
            ("溝底縱向分布筋（沿溝長）", As_dist, 1.0)]
    rows = [(n, a, l, _kg(a, l)) for n, a, l in rows]
    sub = sum(r[3] for r in rows)
    total = sub * (1 + LAP_ALLOWANCE)
    return {"rows": [{"item": n, "As_mm2": round(a, 1), "len_m": round(l, 3),
                      "kg_per_m": round(v, 3)} for n, a, l, v in rows],
            "subtotal_kg_per_m": round(sub, 3),
            "total_kg_per_m": round(total, 3),
            "lap_allowance": LAP_ALLOWANCE}


def est_rebar_kg(design, length_m, faces=2, extra_ratio=0.06):
    """【舊】僅供回溯比對；**有單位錯誤**（未乘鋼筋長度），請改用 rebar_kg_per_m()。"""
    total = 0.0
    d = design.get("main") or {}
    if d.get("As_prov_mm2"):
        total += d["As_prov_mm2"] * 1e-6 * STEEL_DENSITY
    if design.get("dist_As_mm2"):
        total += design["dist_As_mm2"] * 1e-6 * STEEL_DENSITY * faces
    return round(total * length_m * (1 + extra_ratio), 1)


def format_report(d):
    L = [f"構材：{d['member']}（斷面厚 {d['thickness_mm']:.0f} mm）",
         f"  服務載重 M={d['M_service_kNm']:.3f} kN·m/m、V={d['V_service_kN']:.3f} kN/m",
         f"  設計載重 Mu={d['Mu_kNm']:.3f} kN·m/m、Vu={d['Vu_kN']:.3f} kN/m（×1.7）"]
    m, s, w = d.get("main") or {}, d.get("shear") or {}, d.get("crack") or {}
    if m.get("error"):
        L.append(f"  [NG] 撓曲設計失敗：{m['error']}")
    else:
        L.append("  [%s] 撓曲：As_req=%.0f、As_min=%.0f → 採 %s@%d（As=%.0f mm²/m）"
                 "  φMn=%.2f kN·m ≥ Mu=%.2f（使用率 %.1f%%）" % (
                     "OK" if m["ok"] else "NG", m["As_req_mm2"], m["As_min_mm2"],
                     m["bar"], m["spacing_mm"], m["As_prov_mm2"],
                     m["phiMn_kNm"], m["Mu_kNm"], (m["utilization"] or 0) * 100))
    L.append("  [%s] 剪力：φVc=%.2f kN ≥ Vu=%.2f（使用率 %.1f%%）" % (
        "OK" if s.get("ok") else "NG", s.get("phiVc_kN", 0), s.get("Vu_kN", 0),
        (s.get("utilization") or 0) * 100))
    if w.get("w_mm") is not None:
        L.append("  [%s] 裂縫寬度 w=%.3f mm（限 %.1f mm）" % (
            "OK" if w["ok"] else "NG", w["w_mm"], w["limit_mm"]))
    L.append(f"  分布筋：{d.get('dist_bar')}@{d.get('dist_spacing_mm')}（As={d.get('dist_As_mm2')} mm²/m）")
    L.append(f"  {d.get('note','')}")
    L.append("  依據《混凝土結構設計規範》（內政部 112.08.10 現行版／100.06.09 對照）："
             "φ 撓曲 表 21.2.2（舊 §2.3.2／§3.4.4）、剪力 表 21.2.1 0.75；"
             "As,min §9.6.1.2／§7.6.1.1（舊 §3.6.1／§7.12）；"
             "Vc §13.3.6.1.1／表 22.5.5.1（舊 §4.4.1.1）；"
             "牆最小筋比 §11.6.1（舊 §7.4.2～7.4.3）。設計結果仍須技師覆核。")
    return "\n".join(L)


if __name__ == "__main__" and "--selftest" not in sys.argv:
    import json
    import os
    import sys
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "tools", "case_package"))
    import case_core as CC
    import retaining_wall as RW
    import channel_hydraulics as CH

    if len(sys.argv) < 2:
        print("用法：python rc_design.py <case.json>")
        raise SystemExit(2)
    case = CC.load(sys.argv[1])
    model, q, _ = CC.quantity_context(case)
    if model == "wall":
        wr = RW.analyse(q, soil=case.get("soil") or {}, seismic={"kh": 0.0})
        wd = design_wall_rebar(q, wr)
        print("牆型：%s；配筋量 %.2f kg/m（含 %.0f%% 搭接、錨定與損耗）"
              % (wd["wall_type"], wd["total_kg_per_m"],
                 LAP_ALLOWANCE * 100.0))
        steel = wd.get("structural") or wd.get("mass") or {}
        for row in steel.get("rows") or []:
            is_face = "牆面" in row["item"]
            bar = steel.get("face_bar") if is_face else steel.get("base_bar")
            spacing = steel.get("face_spacing_mm") if is_face else steel.get("base_spacing_mm")
            if not bar:
                bar, spacing = steel.get("bar", ""), steel.get("spacing_mm", "")
            print("  %-36s %s@%-4s As=%8.1f mm²/m  %8.3f kg/m"
                  % (row["item"], bar, spacing,
                     row["As_mm2"], row["kg_per_m"]))
        print()
        print(json.dumps({"wall_type": wd["wall_type"],
                          "total_kg_per_m": wd["total_kg_per_m"],
                          "ok": wd["ok"]}, ensure_ascii=False))
        raise SystemExit(0 if wd["ok"] else 1)
    elif model == "channel":
        hy = case.get("hydraulics") or {}
        hr = CH.analyse(float(hy.get("design_flow_m3s") or 0.5),
                        float(q["inner_width_m"]), float(q["depth_m"]),
                        float(hy.get("slope") or 0.005),
                        {"manning_n": float(hy.get("manning_n") or 0.014)})
        d = design_channel_wall(q, hr)
    else:
        raise SystemExit("rc_design 只支援 wall／channel")
    print(format_report(d))
    print()
    print(json.dumps({k: d[k] for k in ("member", "ok", "Mu_kNm", "Vu_kN")}, ensure_ascii=False))
    raise SystemExit(0 if d["ok"] else 1)

# --------------------------------------------------------------------------- #
# 懸臂式擋土牆底板（趾板／踵板）
# --------------------------------------------------------------------------- #
def design_base_slab(q, wall_res, cc=None):
    """懸臂式擋土牆底板配筋（趾板與踵板，各自以牆身為固定端之懸臂板考慮）。

    力學模型
    --------
    踵板（x = T ~ BL，上方覆土）：
        向下 w = γs·H + γc·BT
        向上 q(x)（基底反力）
        淨值 w_net(x) = (γs·H + γc·BT) − q(x)
    趾板（x = 0 ~ T）：
        向下僅底板自重 γc·BT，向上 q(x)
        淨值 w_net(x) = q(x) − γc·BT

    q(x) 由 retaining_wall.analyse() 的 q_max／q_min 與偏心距重建：
      · 合力在底寬 1/3 內（|e| ≤ BL/6）→ 梯形分佈，q_min 可能為 0 或正值
      · |e| > BL/6 → 部分受壓，受壓長度 Lp = 3·(BL/2 − |e|)，三角形分佈

    彎矩以「自由端往固定端積分」求得：
        V(x) = ∫ w_net dξ ，M(x) = ∫ w_net·(ξ − x) dξ
    """
    c = dict(CONCRETE, **(cc or {}))
    H = float(q["height_m"]); T = float(q["stem_thickness_m"])
    BL = float(q["base_width_m"]); BT = float(q["base_thickness_m"])
    if BT <= 0:
        return None                              # 重力式無獨立底板

    gamma_s = float((wall_res.get("soil") or {}).get("gamma", 18.0))
    q_max = float(wall_res["q_max_kPa"])
    x_R = float(wall_res["x_R_m"])
    e = BL / 2.0 - x_R

    # 受壓長度與 q(x) 的線性式
    if abs(e) <= BL / 6.0 + 1e-9:
        Lp = BL
        q_heel = float(wall_res.get("q_min_kPa") or 0.0)
    else:
        Lp = 3.0 * (BL / 2.0 - abs(e))
        q_heel = 0.0
    q_toe = q_max

    # 偏心方向：e>0 表示合力偏向趾端 → q_max 在 x=0（趾端）、遞減到踵端
    def qx(x):
        if Lp <= 0:
            return 0.0
        xx = min(max(x, 0.0), Lp)
        return q_toe + (q_heel - q_toe) * (xx / Lp)

    gC = 24.0
    w_down_heel = gamma_s * H + gC * BT          # kPa
    w_down_toe = gC * BT

    def w_heel(x):
        return w_down_heel - qx(x)

    def w_toe(x):
        return qx(x) - w_down_toe

    def integrate(f, a, b, n=2000):
        """Simpson 積分。"""
        if b <= a:
            return 0.0
        h = (b - a) / n
        tot = f(a) + f(b)
        for i in range(1, n):
            tot += (4 if i % 2 else 2) * f(a + i * h)
        return tot * h / 3.0

    # 固定端（x = T）之內力
    V_heel = integrate(w_heel, T, BL)
    M_heel = integrate(lambda x: w_heel(x) * (x - T), T, BL)
    V_toe = integrate(w_toe, 0.0, T)
    M_toe = integrate(lambda x: w_toe(x) * (T - x), 0.0, T)

    out = {"BT_mm": BT * 1000.0, "Lp_m": round(Lp, 4), "e_m": round(e, 4),
           "q_toe_kPa": round(q_toe, 2), "q_heel_kPa": round(q_heel, 2),
           "w_down_heel_kPa": round(w_down_heel, 2), "w_down_toe_kPa": round(w_down_toe, 2),
           "members": []}

    for name, M_s, V_s in (("踵板（上方覆土區）", abs(M_heel), abs(V_heel)),
                           ("趾板（前趾區）", abs(M_toe), abs(V_toe))):
        Mu, Vu = 1.7 * M_s, 1.7 * V_s
        flex = flexure_design(Mu, b_mm=1000.0, h_mm=BT * 1000.0, cc=c,
                              bar_prefer=_single_pref(q.get("base_bar")))
        shr = shear_check(Vu, b_mm=1000.0, h_mm=BT * 1000.0, cc=c)
        if flex.get("ok"):
            cw = crack_width(flex["As_prov_mm2"], spacing_mm=flex["spacing_mm"],
                             h_mm=BT * 1000.0, cc=c, M_service_kNm=M_s)
        else:
            cw = {"ok": False, "w_mm": None}
        out["members"].append({
            "member": name, "M_service_kNm": round(M_s, 3), "Mu_kNm": round(Mu, 3),
            "V_service_kN": round(V_s, 3), "Vu_kN": round(Vu, 3),
            "main": flex, "shear": shr, "crack": cw,
            "ok": bool(flex.get("ok") and shr.get("ok") and cw.get("ok")),
        })

    out["governing"] = max(out["members"], key=lambda m: m["M_service_kNm"])["member"]
    out["ok"] = all(m["ok"] for m in out["members"])
    out["note"] = ("底板以牆身為固定端之懸臂板設計；踵板控制斷面通常在牆背處。"
                   "上層鋼筋依各板淨壓力方向配置，下層為分布筋。")
    return out


# --------------------------------------------------------------------------- #
# 建築樑柱：矩形柱軸彎互制與樑配筋入口
# --------------------------------------------------------------------------- #
def _beta1(fc_mpa):
    return 0.85 if fc_mpa <= 28.0 else max(0.65, 0.85 - 0.05 * (fc_mpa - 28.0) / 7.0)


def _column_point(c_mm, b_mm, h_mm, layer_areas, fc_mpa, fy_mpa, Es_mpa):
    """One nominal (Pn, Mn) point from rectangular-section strain compatibility."""

    c = max(float(c_mm), 1e-9)
    beta1 = _beta1(fc_mpa)
    a = min(beta1 * c, h_mm)
    Cc = 0.85 * fc_mpa * b_mm * a / 1000.0             # kN
    Pn = Cc
    Mn = Cc * (h_mm / 2.0 - a / 2.0) / 1000.0          # kN·m
    eps_cu = 0.003
    et = 0.0
    for area, d in layer_areas:
        strain = eps_cu * (c - d) / c                   # compression positive
        stress = max(-fy_mpa, min(fy_mpa, Es_mpa * strain))
        if strain > 0.0 and d <= a:
            stress -= 0.85 * fc_mpa                    # displaced concrete
        force = area * stress / 1000.0                 # kN
        Pn += force
        Mn += force * (h_mm / 2.0 - d) / 1000.0
        et = max(et, -strain)
    # §2.3.2: tied column compression-controlled 0.65, tension-controlled 0.90.
    # 112 版表21.2.2：拉力控制界限為 εty+0.003（舊 100 年版為 0.005）
    ety = fy_mpa / Es_mpa
    if et >= ety + 0.003:
        phi = 0.90
    elif et <= ety:
        phi = 0.65
    else:
        phi = 0.65 + 0.25 * (et - ety) / 0.003
    return {
        "c_mm": c,
        "Pn_kN": Pn,
        "Mn_kNm": Mn,
        "phi": phi,
        "phiPn_kN": phi * Pn,
        "phiMn_kNm": phi * abs(Mn),
        "epsilon_t": et,
    }


def column_interaction_curve(
    b_mm=400.0,
    h_mm=400.0,
    *,
    layer_areas=None,
    fc_mpa=28.0,
    fy_mpa=420.0,
    Es_mpa=200000.0,
    points=120,
):
    """Return a uniaxial P-M interaction curve for a rectangular tied column.

    ``layer_areas`` is ``[(As_mm2, distance_from_compression_face_mm), ...]``.
    If omitted, four equal corner bars are assumed with As,total estimated from
    the caller separately by :func:`column_design`.
    """

    if not layer_areas:
        raise ValueError("layer_areas must contain at least one steel layer")
    clean = [(float(area), float(d)) for area, d in layer_areas]
    if any(area <= 0.0 for area, _ in clean):
        raise ValueError("Each steel layer area must be positive")
    if any(d <= 0.0 or d >= h_mm for _, d in clean):
        raise ValueError("Steel layer depth must be inside the section")

    As = sum(area for area, _ in clean)
    Ag = b_mm * h_mm
    P0 = (0.85 * fc_mpa * (Ag - As) + fy_mpa * As) / 1000.0
    curve = [
        {
            "c_mm": math.inf,
            "Pn_kN": P0,
            "Mn_kNm": 0.0,
            "phi": 0.65,
            "phiPn_kN": 0.65 * P0,
            "phiMn_kNm": 0.0,
            "epsilon_t": 0.0,
        }
    ]
    # Log spacing captures the steep part near the compression-controlled
    # region and still reaches very small neutral axes for low axial loads.
    lo, hi = max(h_mm * 0.002, 0.5), h_mm * 20.0
    for i in range(points):
        ratio = i / (points - 1) if points > 1 else 1.0
        c = lo * (hi / lo) ** ratio
        curve.append(
            _column_point(c, b_mm, h_mm, clean, fc_mpa, fy_mpa, Es_mpa)
        )
    curve.sort(key=lambda p: p["phiPn_kN"], reverse=True)
    return {
        "b_mm": b_mm,
        "h_mm": h_mm,
        "As_mm2": round(As, 1),
        "P0_kN": round(P0, 3),
        "phiP0_kN": round(0.65 * P0, 3),
        "curve": curve,
    }


def column_interaction_capacity(
    Pu_kN,
    b_mm=400.0,
    h_mm=400.0,
    *,
    layer_areas=None,
    fc_mpa=28.0,
    fy_mpa=420.0,
    Es_mpa=200000.0,
):
    """Return available φMn at a specified factored axial load Pu."""

    curve = column_interaction_curve(
        b_mm,
        h_mm,
        layer_areas=layer_areas,
        fc_mpa=fc_mpa,
        fy_mpa=fy_mpa,
        Es_mpa=Es_mpa,
    )["curve"]
    Pu = float(Pu_kN)
    if Pu > curve[0]["phiPn_kN"] + 1e-9:
        return {
            "ok": False,
            "phiMn_available_kNm": 0.0,
            "governing_Pn_kN": curve[0]["phiPn_kN"],
            "reason": "軸力超過最大設計軸壓強度",
        }
    if Pu < curve[-1]["phiPn_kN"]:
        # Tension-controlled tail: report the last computed point.
        p = curve[-1]
        return {
            "ok": False,
            "phiMn_available_kNm": p["phiMn_kNm"],
            "governing_Pn_kN": p["phiPn_kN"],
            "reason": "需求軸拉力超出本初步壓力側互制曲線範圍",
        }
    for upper, lower in zip(curve, curve[1:]):
        if upper["phiPn_kN"] + 1e-9 >= Pu >= lower["phiPn_kN"] - 1e-9:
            dp = upper["phiPn_kN"] - lower["phiPn_kN"]
            t = 0.0 if abs(dp) < 1e-12 else (upper["phiPn_kN"] - Pu) / dp
            capacity = upper["phiMn_kNm"] + t * (
                lower["phiMn_kNm"] - upper["phiMn_kNm"]
            )
            return {
                "ok": True,
                "phiMn_available_kNm": round(capacity, 3),
                "governing_Pn_kN": round(Pu, 3),
            }
    raise ValueError("Unable to interpolate the column interaction curve")


def column_design(
    Pu_kN,
    Mu_kNm,
    b_mm=400.0,
    h_mm=400.0,
    *,
    fc_mpa=28.0,
    fy_mpa=420.0,
    cover_mm=40.0,
    bars_per_face=None,
    bar_sizes=("D16", "D19", "D22", "D25", "D29", "D32"),
    min_ratio=0.01,
    max_ratio=0.08,
):
    """Preliminary symmetric two-face column design under uniaxial bending.

    This is a design aid for a rectangular tied column with longitudinal bars
    concentrated at two opposite faces.  Biaxial bending, slenderness, splice
    and anchorage checks must be added before issuing construction drawings.
    """

    Pu, Mu = float(Pu_kN), abs(float(Mu_kNm))
    Ag = b_mm * h_mm
    As_min = min_ratio * Ag
    As_max = max_ratio * Ag
    candidates = []
    face_counts = bars_per_face or range(2, 9)
    for name in bar_sizes:
        dia, area = REBAR_SIZES[name]
        for n_face in face_counts:
            As = 2 * n_face * area
            if As < As_min - 1e-9 or As > As_max + 1e-9:
                continue
            d1 = cover_mm + 10.0 + dia / 2.0
            d2 = h_mm - d1
            if d2 <= d1:
                continue
            layers = [(n_face * area, d1), (n_face * area, d2)]
            cap = column_interaction_capacity(
                Pu,
                b_mm,
                h_mm,
                layer_areas=layers,
                fc_mpa=fc_mpa,
                fy_mpa=fy_mpa,
            )
            clear_width = b_mm - 2.0 * cover_mm - n_face * dia
            spacing = clear_width / max(1, n_face - 1) + dia
            min_spacing = max(1.5 * dia, 25.0)
            ok = cap["ok"] and cap["phiMn_available_kNm"] >= Mu and spacing >= min_spacing
            candidates.append(
                {
                    "bar": name,
                    "bars_per_face": n_face,
                    "bars_total": 2 * n_face,
                    "As_mm2": round(As, 1),
                    "ratio": round(As / Ag, 5),
                    "phiMn_available_kNm": cap["phiMn_available_kNm"],
                    "utilization": (
                        round(Mu / cap["phiMn_available_kNm"], 3)
                        if cap["phiMn_available_kNm"] > 0
                        else None
                    ),
                    "centre_spacing_mm": round(spacing, 1),
                    "min_spacing_mm": round(min_spacing, 1),
                    "spacing_ok": spacing >= min_spacing,
                    "ok": ok,
                    "reason": cap.get("reason"),
                }
            )
    if not candidates:
        return {
            "ok": False,
            "error": "No bar arrangement satisfies 1%～8% longitudinal steel.",
            "As_min_mm2": round(As_min, 1),
            "As_max_mm2": round(As_max, 1),
            "candidates": [],
        }
    candidates.sort(key=lambda c: (not c["ok"], c["As_mm2"]))
    chosen = candidates[0]
    long_dia = REBAR_SIZES[chosen["bar"]][0]
    tie_dia = 9.53  # D10
    tie_spacing = math.floor(
        min(16.0 * long_dia, 48.0 * tie_dia, min(b_mm, h_mm)) / 10.0
    ) * 10.0
    tie_spacing = max(50.0, tie_spacing)
    return {
        "ok": bool(chosen["ok"]),
        "Pu_kN": Pu,
        "Mu_kNm": Mu,
        "b_mm": b_mm,
        "h_mm": h_mm,
        "As_min_mm2": round(As_min, 1),
        "As_max_mm2": round(As_max, 1),
        "chosen": chosen,
        "ties": {
            "bar": "D10",
            "spacing_mm": tie_spacing,
            "rule": "min(16db longitudinal, 48db tie, least section dimension); preliminary",
        },
        "governing": "軸彎互制" if chosen["phiMn_available_kNm"] < Mu * 1.2 else "構造配置",
        "candidates": candidates[:8],
    }


def beam_design(
    Mu_kNm,
    Vu_kN,
    b_mm=300.0,
    h_mm=600.0,
    *,
    M_service_kNm=None,
    fc_mpa=28.0,
    fy_mpa=420.0,
    cover_mm=40.0,
):
    """One-stop preliminary RC beam flexure, stirrup shear and crack design."""

    cc = {
        "fc_mpa": fc_mpa,
        "fy_mpa": fy_mpa,
        "cover_mm": cover_mm,
    }
    service_moment = (
        float(M_service_kNm) if M_service_kNm is not None else Mu_kNm / 1.7
    )
    flex = flexure_design(Mu_kNm, b_mm=b_mm, h_mm=h_mm, cc=cc)
    crack = (
        crack_width(
            flex.get("As_prov_mm2", 0.0),
            b_mm=b_mm,
            h_mm=h_mm,
            spacing_mm=flex.get("spacing_mm", 200.0),
            cc=cc,
            M_service_kNm=service_moment,
        )
        if flex.get("ok")
        else {"ok": False, "w_mm": None, "limit_mm": 0.3}
    )
    crack_iterations = []
    # 強度所需鋼筋不一定是裂縫控制所需鋼筋。每次略增 As 後重新選筋，
    # 直到裂縫寬度滿足或達到迭代上限。
    for _ in range(5):
        if flex.get("ok") and crack.get("ok"):
            break
        if not flex.get("ok") or crack.get("w_mm") in (None, 0):
            break
        limit = float(crack.get("limit_mm", 0.3))
        ratio = max(1.05, 1.12 * (float(crack["w_mm"]) / limit) ** 0.75)
        required_as = float(flex.get("As_prov_mm2", 0.0)) * ratio
        crack_iterations.append(
            {
                "previous_As_mm2": flex.get("As_prov_mm2"),
                "previous_w_mm": crack.get("w_mm"),
                "required_As_mm2": round(required_as, 1),
            }
        )
        flex = flexure_design(
            Mu_kNm,
            b_mm=b_mm,
            h_mm=h_mm,
            cc=cc,
            As_required_min_mm2=required_as,
        )
        crack = (
            crack_width(
                flex.get("As_prov_mm2", 0.0),
                b_mm=b_mm,
                h_mm=h_mm,
                spacing_mm=flex.get("spacing_mm", 200.0),
                cc=cc,
                M_service_kNm=service_moment,
            )
            if flex.get("ok")
            else {"ok": False, "w_mm": None, "limit_mm": 0.3}
        )
    shear = beam_shear_design(
        Vu_kN,
        b_mm=b_mm,
        h_mm=h_mm,
        main_bar=flex.get("bar", "D22"),
        cc=cc,
    )
    return {
        "ok": bool(flex.get("ok") and shear.get("ok") and crack.get("ok")),
        "flexure": flex,
        "shear": shear,
        "crack": crack,
        "crack_iterations": crack_iterations,
    }


def selftest():
    """手算對照（梁 350×750、柱 450×450，fc'=28 MPa、fy=420 MPa）。"""
    from _selftest_util import Checker

    c = Checker("RC 梁與柱")
    beam = beam_design(180.0, 120.0, b_mm=350.0, h_mm=750.0, fc_mpa=28.0, fy_mpa=420.0)
    flex, shear = beam["flexure"], beam["shear"]
    b, d = flex["b_mm"], flex["d_mm"]
    rn = 180e6 / (0.9 * b * d ** 2)
    rho = 0.85 * 28.0 / 420.0 * (1.0 - (1.0 - 2.0 * rn / (0.85 * 28.0)) ** 0.5)
    c.close("撓曲阻抗 Rn＝Mu/(φbd²)", flex["R_MPa"], rn, tol=1e-3)
    c.close("需求鋼筋 As＝ρbd", flex["As_req_mm2"], rho * b * d, tol=1e-3)
    c.close("最小鋼筋 As,min＝max(0.25√fc'/fy, 1.4/fy)·b·d", flex["As_min_mm2"],
            max(0.25 * 28.0 ** 0.5 / 420.0, 1.4 / 420.0) * b * d, tol=1e-3)
    a = flex["As_prov_mm2"] * 420.0 / (0.85 * 28.0 * b)
    c.close("撓曲容量 φMn＝0.9·As·fy·(d－a/2)", flex["phiMn_kNm"],
            0.9 * flex["As_prov_mm2"] * 420.0 * (d - a / 2.0) / 1e6, tol=1e-3)
    vc = 0.17 * 28.0 ** 0.5 * b * shear["d_mm"] / 1000.0
    c.close("混凝土剪力 Vc＝0.17√fc'·b·d", shear["Vc_kN"], vc, tol=1e-3)
    c.close("φVc＝0.75·Vc", shear["phiVc_kN"], 0.75 * vc, tol=1e-3)

    column = column_design(1600.0, 280.0, b_mm=450.0, h_mm=450.0, fc_mpa=28.0, fy_mpa=420.0)
    gross = 450.0 ** 2
    chosen = column["chosen"]
    c.close("柱最小鋼筋＝1%·Ag", column["As_min_mm2"], 0.01 * gross)
    c.close("柱最大鋼筋＝8%·Ag", column["As_max_mm2"], 0.08 * gross)
    c.close("柱鋼筋比 ρ＝As/Ag", chosen["ratio"], chosen["As_mm2"] / gross, tol=1e-4)
    c.close("柱利用率＝Mu/φMn", chosen["utilization"], 280.0 / chosen["phiMn_available_kNm"], tol=1e-3)
    return c.run()


if __name__ == "__main__" and "--selftest" in sys.argv:
    raise SystemExit(selftest())
