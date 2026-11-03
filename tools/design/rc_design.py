"""RC 構材配筋設計（擋土牆莖板／排水溝溝壁，每公尺長）。

⚠ 規範依據說明（重要，必讀）
--------------------------
本工作區**已取得**《水土保持技術規範》全文，但該規範第 120 條四僅要求
「牆身所受各種應力，必須在各種材料容許應力範圍內」，**未規定配筋計算式**。
配筋設計須依《混凝土結構設計規範》；本工作區已取得 **100.06.09 版**與
現行 **112.08.10 版**。程式條號目前仍依 100.06.09 版對帳，ACI 318-19
重編後的新舊條號對照待補，因此仍須由技師覆核現行條文。

條文依據已對帳（2026-10-28）——《混凝土結構設計規範》內政部 **100.06.09 發布**
（依建築技術規則建築構造編第 332 條第 4 項訂定）：

  §2.3.2    強度折減因數 φ：拉（撓曲）力控制 **0.90**、剪力與扭力 **0.75**
            → 與本模組 `phi_flexure`／`phi_shear` 一致 ✓
  §3.6.1    受撓構材最少鋼筋量 As,min ≥ (0.8√fc′/fy)·bw·d 式(3-3)
                                       亦 ≥ (14/fy)·bw·d 式(3-4)
            → 本模組以 SI 換算採 1.4·b·d/fy（14 kgf/cm² ≈ 1.4 MPa）✓
  §4.4.1.1  僅受剪力及撓曲之構材 Vc = 0.53√fc′·bw·d 式(4-3)
            → SI 換算 0.17√fc′，與本模組一致 ✓

⚠ 已取得 **100.06.09 版**（161 頁，全文存於 `data\法規\混凝土結構設計規範_1000609_全文.txt`）
與 **112.08.10 版**；目前程式的條號引用與手算測試仍以 100 年版對帳，
新舊條號對照與 112 年版數值差異須再核。
**不得**把本模組結果當成已依規範完成之配筋設計。

採用的公式（單位：kN、m、mm²、MPa）
----------------------------------
彎矩設計（矩形斷面，單筋）：
    Mn = As·fy·(d − a/2)，a = As·fy/(0.85·fc'·b)
    設計強度 φMn ≥ Mu，φ = 0.9（撓曲）
剪力：
    Vc = 0.17·λ·√fc'·b·d（λ=1 常重混凝土），φ = 0.75
    矩形梁垂直閉合箍筋：
        Vs = Av·fyt·d/s
        Vu/φ ≤ Vc + Vs
        Av/s ≥ max(0.062√fc'·bw/fyt, 0.35·bw/fyt)（需要最少剪力筋時）
        s ≤ d/2 且 ≤ 600 mm；高剪力時減半；Vs ≤ 2.12√fc'·bw·d
最小鋼筋：
    As,min = 取下列較大者：
      ① 0.0018·b·h  —— 溫度與收縮鋼筋（§7.12，fy=420 MPa 時）
      ② 1.4·b·d/fy  —— 受撓構材最小鋼筋（§3.6.1 式(3-4) 的 SI 換算：
                        原式 14·bw·d/fy（kgf/cm²），14 kgf/cm² ≈ 1.4 MPa）
裂縫控制（Gergely-Lutz 簡式）：
    w = 2.2·β·fs·(dc·A)^(1/3) / (Es·1000)，fs 取 0.6·fy（保守）
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
    """§3.7.2 式(3-6)：受撓裂縫控制之鋼筋最大中心距。

        s ≤ 380·(280/fs) − 2.5·cc   且   s ≤ 300·(280/fs)      （fs、280 為 MPa；cc 為 mm）

    本規範（100.06.09 版）已**以最大鋼筋間距取代前版規範的 z 值（裂縫寬度）規定**，
    見 §3.7.2 解說：「本節以直接限制最大鋼筋間距，取代前版規範 z 值之規定」。

    fs 為使用載重下之鋼筋應力，**亦可用 (2/3)fy 替代**。用 (2/3)fy 較保守。

    驗算（對照 §3.7.2 解說）：fy=4,200 kgf/cm²、保護層 5 cm、採 (2/3)fy：
        s ≤ 380·(2800/2800) − 2.5×50 = 255 mm，且 ≤ 300 mm → 取 255 mm
        條文解說寫「最大鋼筋間距為 25cm」→ 相符 ✓
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
    # §2.3.2／§3.4.4：φ 依實際配置鋼筋量之淨拉應變判定（不再一律 0.90）
    phi_chk, et, phi_basis = phi_by_strain(As_prov, b_mm, d, fc, fy,
                                          c.get("Es_mpa"))
    phi = phi_chk
    phiMn = phi * Mn

    # §3.7.2 裂縫控制：最大鋼筋中心距。fs 取使用載重下之應力（本模組以 Mu/1.7 回推服務彎矩），
    # 條文亦允許以 (2/3)fy 保守替代 —— 兩者都算出來供比對。
    Ms = Mu_kNm_per_m / 1.7
    fs_service = Ms * 1e6 / max(As_prov * 0.9 * d, 1e-9) if As_prov > 0 else 0.0
    # 零彎矩或最小鋼筋控制時，服務應力會算成 0。此時仍須配置裂縫控制
    # 鋼筋，依 §3.7.2 允許的 (2/3)fy 保守值計算最大間距。
    if fs_service <= 0.0:
        fs_service = (2.0 / 3.0) * fy
    s_max, s_1, s_2 = spacing_limit_mm(c.get("cover_mm", 75.0), fs_service)
    s_max_cons, _, _ = spacing_limit_mm(c.get("cover_mm", 75.0), 280.0)

    return {
        "ok": phiMn >= Mu_kNm_per_m,
        "b_mm": b_mm, "h_mm": h_mm, "d_mm": round(d, 1),
        "Mu_kNm": round(Mu_kNm_per_m, 3),
        "phi": phi, "epsilon_t": round(et, 5), "phi_basis": phi_basis,
        # §3.7.2 裂縫控制（最大鋼筋間距）
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

    依《混凝土結構設計規範》100.06.09 版第 4.6 節：
      - Vc = 0.17√fc′·bw·d（SI，§4.4.1.1）
      - φ = 0.75（§2.3.2）
      - Vs = Av·fyt·d/s（§4.6.7.2，式 4-15）
      - Vu/φ ≤ Vc + Vs
      - Vu > φVc/2 時配置最少剪力筋（§4.6.6.1）
      - Av,min/s = max(0.062√fc′·bw/fyt, 0.35·bw/fyt)
        （§4.6.6.3，式 4-13／4-14 的 SI 換算）
      - s ≤ d/2 且 ≤ 60 cm；Vs 大於 1.06√fc′·bw·d 時減半
        （§4.6.5.1、§4.6.5.3）
      - Vs ≤ 2.12√fc′·bw·d（§4.6.7.9）
      - fyt 不得大於 4,200 kgf/cm²（約 412 MPa，§4.6.2）

    本函式只做規則梁腹垂直兩肢箍筋；耐震圍束、扭力、接頭與錨定另計。
    """
    c = dict(CONCRETE, **(cc or {}))
    fc = float(c["fc_mpa"])
    # §4.6.2：剪力筋降伏強度上限 4,200 kgf/cm² ≈ 412 MPa。
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
                    "error": "斷面不足：所需 Vs 超過 §4.6.7.9 上限",
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
                "混凝土結構設計規範 §2.3.2、§4.4.1.1、§4.6.2、"
                "§4.6.5.1、§4.6.5.3、§4.6.6.1、§4.6.6.3、"
                "§4.6.7.2、§4.6.7.9（100.06.09 版）"
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
    """§7.4.2／§7.4.3：牆之最少鋼筋量（每公尺牆長，mm²/m）。

    規範（100.06.09 版）第 7 章「牆」：
      §7.4.2  垂直鋼筋比 ρl = 0.0015（對牆水平總斷面積）
      §7.4.3  水平鋼筋比 ρt = 0.0025（對牆垂直總斷面積）
      §7.4.4  牆厚 ≥ 25 cm 時，每一方向鋼筋須分兩層設置

    且 §7.2.2 明定：「懸臂式擋土牆應按第三章中有關撓曲之規定設計，
    其**最少水平鋼筋量按第 7.4.3 節**之規定」。

    ⚠ 先前本模組把「分布筋」當成溫度收縮筋取 0.0018·b·t·0.5（= 315 mm²/m），
      遠低於 §7 .4.3 要求的 875 mm²/m（t=350 mm 時）→ 水平筋不足。
      §3.7.2 的「最大鋼筋間距」只管**梁與單向版**，不適用於牆；牆適用本章。
    """
    return {
        "As_vertical_min_mm2": round(0.0015 * b_mm * t_mm, 1),
        "As_horizontal_min_mm2": round(0.0025 * b_mm * t_mm, 1),
        "two_layers_required": t_mm >= 250.0,
        "basis": "§7.4.2 ρl=0.0015、§7.4.3 ρt=0.0025、§7.4.4 t≥25cm 分兩層",
    }


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

    flex = flexure_design(Mu, b_mm=1000.0, h_mm=T * 1000.0, cc=c)
    shr = shear_check(Vu, b_mm=1000.0, h_mm=T * 1000.0, cc=c)
    if flex.get("ok"):
        cw = crack_width(flex["As_prov_mm2"], spacing_mm=flex["spacing_mm"],
                         h_mm=T * 1000.0, cc=c, M_service_kNm=M_stem)
    else:
        cw = {"ok": False, "w_mm": None}

    # 水平鋼筋：§7.4.3 要求 ρt=0.0025（對牆垂直總斷面積），且不小於主筋 1/3。
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

    # 溝壁水平筋：比照 §7.4.3 ρt=0.0025（牆式構材保守採同一下限），且 ≥ 主筋 1/3
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
LAP_ALLOWANCE = 0.12          # 搭接、錨定與損耗


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


def est_rebar_kg(design, length_m, faces=2, extra_ratio=0.12):
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
    L.append("  依據《混凝土結構設計規範》（內政部 100.06.09 發布）："
             "φ 撓曲 §2.3.2 0.90／剪力 0.75；As,min §3.6.1；Vc §4.4.1.1。"
             "⚠ 現行 112.08.10 版已取得，但新舊條號對照待補；仍須技師覆核。")
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
        if wr["wall_type"] == "gravity":
            print("重力式擋土牆：屬質量混凝土，無須結構配筋（僅構造筋）。")
            print("  → 報告第 8 章應說明：重力式靠自重穩定，配筋僅為溫度／收縮與構造需求。")
            raise SystemExit(0)
        d = design_cantilever_stem(q, wr)
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
        flex = flexure_design(Mu, b_mm=1000.0, h_mm=BT * 1000.0, cc=c)
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
