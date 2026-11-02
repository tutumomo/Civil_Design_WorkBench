r"""邊坡穩定分析（水土保持技術規範第 72、73 條）。

為什麼要這個模組
----------------
業務範疇（AGENTS.md §1）是「道路、排水溝、擋土牆、**邊坡**」，但到目前為止只有前三類
有計算模組。邊坡沒有計算，就等於遇到邊坡案只能憑經驗給坡度 —— 那正是先前擋土牆
「斷面在數學上不成立」的同類問題。

條文依據
--------
**第 72 條（邊坡穩定）**：以水土保持處理使邊坡不致崩塌、地滑、土石流。

**第 73 條（邊坡穩定分析）**：規劃設計時應進行邊坡穩定分析，並達下表最小安全係數：

| 階段 | 平時 | 地震 | 暴雨 |
|---|---|---|---|
| 永久性 | **1.5** | **1.1** | **1.2** |
| 臨時性 | **1.2** | **1.0** | **1.1** |

分析方法
--------
1. **無限邊坡法**（`infinite_slope`）—— 滑動面平行坡面、深度遠小於坡長時適用。
   無凝聚性土壤（c=0）時可封閉解：**FS = tanφ / tanβ**，用來對帳。
2. **圓弧滑動．Fellenius 法**（`circular_fs`）—— 均質邊坡的整體穩定。
   FS = Σ(c·l + N·tanφ) / Σ T，N = W·cosα、T = W·sinα。
   切片法對「均質、無地下水壓」的邊坡足夠；Fellenius 略保守於 Bishop。
3. **最小安全係數**（`required_fs`）—— 查第 73 條表。

單位：長度 m、力 kN/m（每公尺坡長）、c kPa、φ 度、γ kN/m³。
"""

import math

# 第 73 條最小安全係數表
FS_TABLE = {
    "永久性": {"平時": 1.5, "地震": 1.1, "暴雨": 1.2},
    "臨時性": {"平時": 1.2, "地震": 1.0, "暴雨": 1.1},
}

DEFAULTS = {
    "unit_weight_kn_m3": 18.0,     # 一般土壤濕密度
    "unit_weight_sat_kn_m3": 20.0,  # 飽和密度
    "cohesion_kpa": 5.0,            # 假設值，須以鑽探報告替換
    "friction_deg": 28.0,           # 假設值
    "stage": "永久性",
    "condition": "平時",
}


def required_fs(stage="永久性", condition="平時"):
    """第 73 條：最小安全係數。"""
    if stage not in FS_TABLE:
        raise ValueError("stage 須為 %s" % list(FS_TABLE))
    if condition not in FS_TABLE[stage]:
        raise ValueError("condition 須為 %s" % list(FS_TABLE[stage]))
    return FS_TABLE[stage][condition]


def infinite_slope(c_kpa, phi_deg, gamma_kn_m3, beta_deg, depth_m,
                   groundwater_ratio=0.0, gamma_sat=None):
    """無限邊坡法。回傳 FS 與中間量。

    groundwater_ratio：地下水位高於滑動面之比例（0 = 無水、1 = 水位在地表）。
    有地下水時滑動面上之水壓 u = γw · z_w · cos²β。
    """
    phi = math.radians(phi_deg)
    beta = math.radians(beta_deg)
    if depth_m <= 0:
        raise ValueError("depth_m 必須為正")
    if not (0.0 <= beta < math.pi / 2):
        raise ValueError("坡角須在 0~90 度之間")
    gs = gamma_sat or (gamma_kn_m3 + 2.0)
    zw = groundwater_ratio * depth_m
    u = 9.81 * zw * math.cos(beta) ** 2                     # kPa
    # 正應力（有效）
    sigma = gamma_kn_m3 * depth_m * math.cos(beta) ** 2 - u
    tau = gamma_kn_m3 * depth_m * math.sin(beta) * math.cos(beta)
    if tau <= 0:
        raise ValueError("坡角過小或參數異常，剪應力為零")
    resist = c_kpa + max(sigma, 0.0) * math.tan(phi)
    return {"FS": round(resist / tau, 4), "sigma_kpa": round(sigma, 3),
            "tau_kpa": round(tau, 3), "u_kpa": round(u, 3),
            "method": "無限邊坡法"}


def _ground_y(x, H, tanb):
    """地表線：坡趾在原點，坡面 y=x·tanβ（0 ≤ x ≤ H/tanβ），坡頂平台 y=H（x ≥ H/tanβ），
    坡趾前方平地 y=0（x ≤ 0）。"""
    if x <= 0.0:
        return 0.0
    xc = H / tanb
    if x >= xc:
        return H
    return x * tanb


def _slice_geometry(H, beta_deg, xc, yc, R, n=40):
    """沿圓弧切 n 片，回傳每片 (b, l, α, h)。圓弧必須低於地表且與坡面相交才有效。"""
    tanb = math.tan(math.radians(beta_deg))
    if R <= 0:
        return None
    # 圓的最低點必須低於坡趾高度才有滑動體
    if yc - R > 0.05 * H:
        return None
    x_lo, x_hi = xc - R, xc + R
    # 取樣找「圓弧在地表以下」的連續區間
    N = 400
    inside = []
    for k in range(N + 1):
        x = x_lo + (x_hi - x_lo) * k / N
        dy = R ** 2 - (x - xc) ** 2
        if dy <= 0:
            continue
        yb = yc - math.sqrt(dy)
        if yb <= _ground_y(x, H, tanb) - 1e-6:
            inside.append(x)
    if len(inside) < 5:
        return None
    # 取最大連續段
    runs, cur = [], [inside[0]]
    for k in range(1, len(inside)):
        if inside[k] - inside[k - 1] <= 2.5 * (x_hi - x_lo) / N:
            cur.append(inside[k])
        else:
            runs.append(cur); cur = [inside[k]]
    runs.append(cur)
    seg = max(runs, key=len)
    # inside 是升冪（x_lo → x_hi）→ 最大 x 是 seg[-1]
    # 曾寫成 seg[0], seg[-1] → 跨度變負值，整族圓被判無效（找得到圓卻全部回 None）
    x_to, x_from = seg[0], seg[-1]
    if x_from - x_to < 0.2 * H:
        return None
    # 滑動體必須吃到坡面（否則只是平地淺滑，不代表邊坡破壞）
    xc_crest = H / tanb
    overlap = min(x_from, xc_crest) - max(x_to, 0.0)
    if overlap < 0.30 * H:
        return None
    b = (x_from - x_to) / n
    slices = []
    for i in range(n):
        xa = x_from - i * b
        xm = xa - b / 2.0
        dy = R ** 2 - (xm - xc) ** 2
        if dy <= 0:
            continue
        yb = yc - math.sqrt(dy)
        h = _ground_y(xm, H, tanb) - yb
        if h <= 1e-6:
            continue
        alpha = math.atan2(xm - xc, yc - yb)
        slices.append({"b": abs(b), "l": abs(b) / max(math.cos(alpha), 1e-6),
                       "alpha": alpha, "h": h, "xm": xm})
    return slices or None


def circular_fs(H, beta_deg, c_kpa, phi_deg, gamma_kn_m3,
                xc=None, yc=None, R=None, n=40, groundwater_ratio=0.0):
    """圓弧滑動（Fellenius 切片法），回傳 FS。未給圓心時自動搜尋最不利滑動圓。"""
    phi = math.radians(phi_deg)

    def fs_of(xc_, yc_, R_):
        sl = _slice_geometry(H, beta_deg, xc_, yc_, R_, n)
        if not sl:
            return None, None
        num = den = 0.0
        for s in sl:
            W = gamma_kn_m3 * s["b"] * s["h"]          # kN/m
            N = W * math.cos(s["alpha"])
            T = W * math.sin(s["alpha"])
            # 地下水：滑動面上之水壓 u = γw·z_w·cos²β（同無限邊坡法）
            u = 9.81 * (groundwater_ratio * s["h"]) * math.cos(
                math.radians(beta_deg)) ** 2
            N_eff = max(N - u * s["l"], 0.0)
            num += c_kpa * s["l"] + N_eff * math.tan(phi)
            den += T
        if den <= 1e-9:
            return None, None
        return num / den, sl

    if xc is not None and yc is not None and R is not None:
        fs, sl = fs_of(xc, yc, R)
        if fs is None:
            raise ValueError("指定之滑動圓與邊坡無交集")
        return {"FS": round(fs, 4), "method": "圓弧滑動（Fellenius）",
                "n_slices": len(sl), "xc": xc, "yc": yc, "R": R}

    # 自動搜尋最不利滑動圓：採「坡趾圓（toe circle）」族 ——
    # 圓弧固定通過坡趾 (0,0)，故 R = √(xc²+yc²)，只搜尋圓心 (xc,yc)。
    # 這樣圓弧必定切進坡面，不會出現浮在地表上方的無效圓。
    # 坡頂平台側的滑出點則隨圓心自動決定。
    best = None
    tanb = math.tan(math.radians(beta_deg))
    xc_crest = H / tanb
    for i in range(13):
        xci = xc_crest * (0.10 + 0.13 * i)         # 0.1 → 1.66×坡頂水平距離
        for j in range(11):
            yci = H * (0.8 + 0.22 * j)            # 0.8H → 3.0H
            Rj = math.hypot(xci, yci)             # 通過坡趾
            fs, sl = fs_of(xci, yci, Rj)
            if fs is None:
                continue
            if best is None or fs < best["FS"]:
                best = {"FS": round(fs, 4), "method": "圓弧滑動（Fellenius，坡趾圓）",
                        "n_slices": len(sl), "xc": round(xci, 3),
                        "yc": round(yci, 3), "R": round(Rj, 3)}
    if best is None:
        raise ValueError("自動搜尋找不到有效滑動圓，請檢查坡高與坡角")
    best["searched"] = True
    return best


def analyse(slope):
    """完整邊坡穩定分析。slope 為 case.json 的 quantities.values（model=slope）。

    必要：height_m、slope_angle_deg
    選用：cohesion_kpa、friction_deg、unit_weight_kn_m3、
          groundwater_ratio、stage、condition、slip_depth_m
    """
    H = float(slope["height_m"])
    beta = float(slope["slope_angle_deg"])
    c = float(slope.get("cohesion_kpa", DEFAULTS["cohesion_kpa"]))
    phi = float(slope.get("friction_deg", DEFAULTS["friction_deg"]))
    gam = float(slope.get("unit_weight_kn_m3", DEFAULTS["unit_weight_kn_m3"]))
    gw = float(slope.get("groundwater_ratio", 0.0) or 0.0)
    stage = slope.get("stage") or DEFAULTS["stage"]
    cond = slope.get("condition") or DEFAULTS["condition"]
    dep = float(slope.get("slip_depth_m", min(H, 2.0)) or min(H, 2.0))

    inf = infinite_slope(c, phi, gam, beta, dep, gw)
    arc = circular_fs(H, beta, c, phi, gam, groundwater_ratio=gw)
    need = required_fs(stage, cond)

    checks = [
        {"item": "無限邊坡法 FS ≥ 需求值", "value": inf["FS"], "required": need,
         "ok": inf["FS"] >= need, "unit": "FS"},
        {"item": "圓弧滑動 FS ≥ 需求值", "value": arc["FS"], "required": need,
         "ok": arc["FS"] >= need, "unit": "FS"},
    ]
    # 無凝聚性土壤的封閉解校核：FS = tanφ/tanβ
    if c <= 1e-9 and gw <= 1e-9:
        closed = math.tan(math.radians(phi)) / math.tan(math.radians(beta))
        checks.append({"item": "無凝聚性封閉解 tanφ/tanβ 核對",
                       "value": round(closed, 4), "required": None,
                       "limit": inf["FS"], "unit": "FS", "severity": "advisory",
                       "ok": abs(closed - inf["FS"]) <= 0.02})
    return {"height_m": H, "slope_angle_deg": beta,
            "cohesion_kpa": c, "friction_deg": phi, "unit_weight_kn_m3": gam,
            "groundwater_ratio": gw, "stage": stage, "condition": cond,
            "infinite": inf, "circular": arc,
            "FS_required": need, "checks": checks,
            "ok": all(x["ok"] for x in checks if x["required"] is not None)}


def max_stable_angle(height_m, c_kpa, phi_deg, gamma_kn_m3,
                     stage="永久性", condition="平時", gw=0.0):
    """反推「在該安全係數下容許的最大坡角」（度）。

    回傳 None 表示在 5°~85° 範圍內 FS 一直高於需求值（即坡角不是控制因素）。

    以**圓弧滑動法**二分求解。找不到有效滑動圓時一律視為**不穩定**（保守）。
    曾用無限邊坡法二分 → 陡坡時 τ→0 使 FS→∞，反算結果變成 89.5°（明顯錯誤）；
    也曾把圓弧法例外當成「安全」 → 同樣推到 89°。**例外的方向要往保守倒。**
    """
    need = required_fs(stage, condition)

    def stable(b):
        """以圓弧滑動判定。找不到有效滑動圓 → 視為不穩定（保守）。"""
        try:
            r = circular_fs(height_m, b, c_kpa, phi_deg, gamma_kn_m3,
                             groundwater_ratio=gw)
        except ValueError:
            return False
        return r["FS"] >= need

    lo, hi = 0.5, 85.0
    if not stable(lo):
        return 0.0
    # 先掃一遍看 FS 是否真的會掉到需求值以下。若不會，回傳 None 並註明 ——
    # 曾直接二分到「找不到滑動圓」的邊界，把搜索極限 73.3° 當成容許坡角（會誤導）。
    # 探測時只看「找得到滑動圓」的角度 —— 幾何無解不代表不穩定，不能拿來當反證。
    got = []
    for b in range(5, 86, 5):
        try:
            got.append(circular_fs(height_m, b, c_kpa, phi_deg,
                                   gamma_kn_m3, groundwater_ratio=gw)["FS"])
        except ValueError:
            continue
    if got and min(got) >= need:
        return None               # 可搜尋範圍內 FS 從未掉到需求值以下
    for _ in range(25):
        mid = (lo + hi) / 2.0
        if stable(mid):
            lo = mid
        else:
            hi = mid
    return round(lo, 2)


def format_report(r):
    L = ["邊坡穩定分析（水土保持技術規範第 72、73 條）", "",
         "  坡高 H=%.2f m、坡角 β=%.1f°、c=%.1f kPa、φ=%.1f°、γ=%.1f kN/m³"
         % (r["height_m"], r["slope_angle_deg"], r["cohesion_kpa"],
            r["friction_deg"], r["unit_weight_kn_m3"]),
         "  地下水位比例 %.2f、階段 %s、情況 %s → 最小安全係數要求 **%.1f**"
         % (r["groundwater_ratio"], r["stage"], r["condition"], r["FS_required"]),
         "",
         "  無限邊坡法：FS = %.3f（σ=%.2f kPa、τ=%.2f kPa、u=%.2f kPa）"
         % (r["infinite"]["FS"], r["infinite"]["sigma_kpa"],
            r["infinite"]["tau_kpa"], r["infinite"]["u_kpa"]),
         "  圓弧滑動（Fellenius）：FS = %.3f（%d 切片，圓心 (%.2f, %.2f)、R=%.2f）"
         % (r["circular"]["FS"], r["circular"]["n_slices"], r["circular"]["xc"],
            r["circular"]["yc"], r["circular"]["R"]),
         ""]
    for c in r["checks"]:
        if c["required"] is None:
            L.append("    %s：%s（不適用門檻）" % (c["item"], c["value"]))
        else:
            L.append("    %s：%.3f vs %.1f  %s"
                     % (c["item"], c["value"], c["required"],
                        "符合" if c["ok"] else "**不符**"))
    L.append("")
    L.append("  → 整體：%s" % ("全部通過 ✓" if r["ok"] else "有未通過項目 ✗"))
    return "\n".join(L)


def selftest():
    """手算對照（H=5 m、β=25°、φ=35°、γ=18、滑動面深 2 m）。"""
    from _selftest_util import Checker

    c = Checker("邊坡穩定（第 72、73 條）")
    beta = math.radians(25.0)
    phi = math.radians(35.0)
    z = 2.0
    sigma = 18.0 * z * math.cos(beta) ** 2
    tau = 18.0 * z * math.sin(beta) * math.cos(beta)
    r = analyse({"height_m": 5.0, "slope_angle_deg": 25.0, "cohesion_kpa": 0.0,
                 "friction_deg": 35.0, "unit_weight_kn_m3": 18.0})
    c.close("正應力 σ＝γz·cos²β", r["infinite"]["sigma_kpa"], sigma, tol=1e-3)
    c.close("剪應力 τ＝γz·sinβ·cosβ", r["infinite"]["tau_kpa"], tau, tol=1e-3)
    c.close("無凝聚性 FS＝tanφ/tanβ", r["infinite"]["FS"], math.tan(phi) / math.tan(beta), tol=1e-3)
    cohesive = infinite_slope(5.0, 35.0, 18.0, 25.0, z)
    c.close("凝聚性 FS＝(c＋σ·tanφ)/τ", cohesive["FS"], (5.0 + sigma * math.tan(phi)) / tau, tol=1e-3)
    wet = infinite_slope(0.0, 35.0, 18.0, 25.0, z, groundwater_ratio=0.5)
    u = 9.81 * 0.5 * z * math.cos(beta) ** 2
    c.close("孔隙水壓 u＝γw·zw·cos²β", wet["u_kpa"], u, tol=1e-3)
    c.close("含水 FS＝(σ－u)·tanφ/τ", wet["FS"], (sigma - u) * math.tan(phi) / tau, tol=1e-3)
    c.close("第 73 條 永久性平時 FS", required_fs("永久性", "平時"), 1.5)
    c.close("第 73 條 臨時性平時 FS", required_fs("臨時性", "平時"), 1.2)
    return c.run()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import argparse
    import json
    ap = argparse.ArgumentParser(description="邊坡穩定分析（水保第 72、73 條）")
    ap.add_argument("--height", type=float, required=True, help="坡高 m")
    ap.add_argument("--angle", type=float, required=True, help="坡角 度")
    ap.add_argument("--c", type=float, default=DEFAULTS["cohesion_kpa"])
    ap.add_argument("--phi", type=float, default=DEFAULTS["friction_deg"])
    ap.add_argument("--gamma", type=float, default=DEFAULTS["unit_weight_kn_m3"])
    ap.add_argument("--gw", type=float, default=0.0, help="地下水位比例 0~1")
    ap.add_argument("--stage", default="永久性", choices=list(FS_TABLE))
    ap.add_argument("--condition", default="平時",
                    choices=["平時", "地震", "暴雨"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyse({"height_m": a.height, "slope_angle_deg": a.angle,
                 "cohesion_kpa": a.c, "friction_deg": a.phi,
                 "unit_weight_kn_m3": a.gamma, "groundwater_ratio": a.gw,
                 "stage": a.stage, "condition": a.condition})
    print(format_report(r))
    if a.json:
        print()
        print(json.dumps(r, ensure_ascii=False, indent=1))
    raise SystemExit(0 if r["ok"] else 1)
