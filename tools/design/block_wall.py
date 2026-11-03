"""疊式與砌石擋土牆穩定分析（水土保持技術規範 §118～120）。

涵蓋：
- gabion      蛇籠（箱籠）擋土牆：總有效高 ≤ 4 m（§118 六(一)）
- crib        格籠擋土牆：每層有效高 ≤ 3 m、總有效高 ≤ 6 m（§118 六(二)）
- masonry_wet 漿砌石擋土牆：有效高 ≤ 4 m、牆面緩於 1:0.3、任一石往上高 ≤ 6.5 倍長徑（§118 七）
- masonry_dry 乾砌石擋土牆：同上，但 ≤ 5 倍長徑
- sandwich    三明治式擋土牆：牆面漿砌石塊／混凝土塊、中間澆置混凝土、背面填砌卵石或透水材料
              （公路工程施工規範 3.6）；有效高 開挖坡面 ≤ 4 m、填方坡面 ≤ 2 m（§118 一）

做法（與重力式相同的剛體檢核，但每一層界面都要檢核）：
1. 牆體以由下而上的「段」表示，每段前緣、後緣可為線性（砌石牆有坡度），
   疊式牆則為一層一層的矩形（可前階或後階）。
2. 在每個檢核高程取上方牆體為自由體，於上方牆體最後緣設「虛擬鉛直牆背」，
   虛擬牆背與實際牆背之間的土重併入自由體（與懸臂式踵板覆土相同觀念）。
3. 虛擬牆背上的土壓用 Coulomb（δ 預設 = 填土坡角 β，等同 Rankine 斜填土），
   地震用 Mononobe-Okabe 增量（作用於 0.6h），慣性力 = kh ×（牆重＋楔形土重）。
4. 檢核：滑動、傾倒、合力作用點（土層 1/3、岩盤 1/2 中段），基底另檢核承載。
   §120 的安全係數門檻與 retaining_wall.LIMITS 共用。

假設與限制（會寫進結果的 warnings）：
- 牆趾被動土壓力依 passive 設定計入（僅底面抗滑，層間界面不計）；回填土黏著力不計（保守）。
- 疊式牆視為透水，不計牆後靜水壓；牆後有地下水時須另行檢核。
- 牆背不可「懸在填土上」（後緣不可往上越來越後退）；整體傾斜的蛇籠牆尚未支援。
- 蛇籠網線、格籠構件本身的強度不在此檢核。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import earth_pressure as EP  # noqa: E402
import rc_design as RC  # noqa: E402
from retaining_wall import LIMITS  # noqa: E402


class BlockWallError(ValueError):
    """Invalid block / masonry wall input."""


# 依 §118 整理；unit_weight 與 interface_friction 為常用假設值，須依材料試驗修正。
BLOCK_WALL_SPECS: dict[str, dict[str, Any]] = {
    "gabion": {
        "label": "蛇籠（箱籠）擋土牆",
        "max_effective_height_m": 4.0,
        "max_layer_height_m": None,
        "basis": "水土保持技術規範 §118 六(一)：總有效高 4 m 以下為原則",
        "unit_weight_kn_m3": 18.0,   # 石料 26 kN/m³ ×（1－孔隙率 0.30）
        "interface_friction": 0.70,  # 籠與籠之間
        "layout": "layers",
    },
    "crib": {
        "label": "格籠擋土牆",
        "max_effective_height_m": 6.0,
        "max_layer_height_m": 3.0,
        "basis": "水土保持技術規範 §118 六(二)：每層有效高 3 m 以下、總有效高 6 m 以下為原則",
        "unit_weight_kn_m3": 18.0,   # 構件＋格內填石的等值單位重
        "interface_friction": 0.60,
        "layout": "layers",
    },
    "masonry_wet": {
        "label": "漿砌石擋土牆",
        "max_effective_height_m": 4.0,
        "max_layer_height_m": None,
        "basis": "水土保持技術規範 §118 七：有效高 4 m 以下、牆面緩於 1:0.3、任一石往上高 ≤ 6.5 倍長徑",
        "unit_weight_kn_m3": 23.0,
        "interface_friction": 0.70,
        "layout": "masonry",
        "stone_height_factor": 6.5,
        "min_front_batter": 0.30,
    },
    "masonry_dry": {
        "label": "乾砌石擋土牆",
        "max_effective_height_m": 4.0,
        "max_layer_height_m": None,
        "basis": "水土保持技術規範 §118 七：有效高 4 m 以下、牆面緩於 1:0.3、任一石往上高 ≤ 5 倍長徑",
        "unit_weight_kn_m3": 20.0,
        "interface_friction": 0.60,
        "layout": "masonry",
        "stone_height_factor": 5.0,
        "min_front_batter": 0.30,
    },
    "sandwich": {
        "label": "三明治式擋土牆",
        "max_effective_height_m": 4.0,
        "max_by_site": {"cut": 4.0, "fill": 2.0},
        "max_layer_height_m": None,
        "basis": "水土保持技術規範 §118 一：位於開挖坡面者有效高 4 m 以下、位於填方坡面者 2 m 以下為原則",
        "unit_weight_kn_m3": 23.0,   # 面層漿砌石／混凝土塊＋中間混凝土的等值單位重
        "interface_friction": 0.70,  # 分層澆置施工縫
        "layout": "masonry",
    },
}

MIN_MASONRY_FRONT_BATTER = 0.30  # §118 七：牆面坡度以緩於 1:0.3 為原則
TOL = 1e-9


def _f(data: Mapping[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value in (None, ""):
        if default is None:
            raise BlockWallError("缺少參數 %s" % key)
        value = default
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BlockWallError("參數 %s 必須是數字" % key) from exc
    if not math.isfinite(out):
        raise BlockWallError("參數 %s 必須是有限數字" % key)
    return out


# --------------------------------------------------------------------------
# 幾何：段（segment）＝ y0..y1 之間前緣 xf、後緣 xb 皆為線性；x 由基底前趾起算
# --------------------------------------------------------------------------

def _segment(y0, y1, xf0, xf1, xb0, xb1, layer=None):
    if y1 - y0 <= TOL:
        raise BlockWallError("每一段的高度必須大於 0")
    if xb0 - xf0 <= TOL or xb1 - xf1 <= TOL:
        raise BlockWallError("牆厚必須大於 0（後緣必須在前緣之後）")
    return {"y0": y0, "y1": y1, "xf0": xf0, "xf1": xf1, "xb0": xb0, "xb1": xb1,
            "layer": layer}


def _at(seg, y):
    t = (y - seg["y0"]) / (seg["y1"] - seg["y0"])
    return (seg["xf0"] + (seg["xf1"] - seg["xf0"]) * t,
            seg["xb0"] + (seg["xb1"] - seg["xb0"]) * t)


def _simpson(fn, a, b):
    # 被積函數至多二次，Simpson 為精確解
    return (b - a) / 6.0 * (fn(a) + 4.0 * fn(0.5 * (a + b)) + fn(b))


def _layers_geometry(q: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """疊式牆：layers 由下而上；未給則由 course_count 等參數產生。"""

    layers = q.get("layers")
    if not layers:
        n = int(_f(q, "course_count", 3))
        h = _f(q, "course_height_m", 1.0)
        b0 = _f(q, "base_width_m", 2.0)
        dec = _f(q, "width_decrement_m", 0.5)
        side = str(q.get("step_side") or "front").lower()
        if n < 1:
            raise BlockWallError("course_count 至少為 1")
        if side not in ("front", "back"):
            raise BlockWallError("step_side 只能是 front（前階、背面鉛直）或 back（後階、牆面鉛直）")
        layers = []
        for i in range(n):
            width = b0 - dec * i
            offset = dec * i if side == "front" else 0.0
            layers.append({"height_m": h, "width_m": width, "offset_m": offset})
    segs = []
    clean = []
    y = 0.0
    for i, row in enumerate(layers):
        if not isinstance(row, Mapping):
            raise BlockWallError("layers 每一筆必須是物件")
        h = _f(row, "height_m")
        w = _f(row, "width_m")
        off = _f(row, "offset_m", 0.0)
        if h <= 0 or w <= 0:
            raise BlockWallError("第 %d 層的高、寬必須大於 0" % (i + 1))
        segs.append(_segment(y, y + h, off, off, off + w, off + w, layer=i + 1))
        clean.append({"layer": i + 1, "y0_m": round(y, 4), "height_m": h,
                      "width_m": w, "offset_m": off})
        y += h
    return segs, clean


def _masonry_geometry(q: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    H = _f(q, "height_m")
    top = _f(q, "top_width_m")
    nf = _f(q, "front_batter_ratio", MIN_MASONRY_FRONT_BATTER)
    nb = _f(q, "back_batter_ratio", 0.0)
    if H <= 0 or top <= 0:
        raise BlockWallError("砌石牆高與頂寬必須大於 0")
    if nf < 0:
        raise BlockWallError("front_batter_ratio 不可為負")
    if nb < 0:
        raise BlockWallError(
            "back_batter_ratio 為負代表牆背懸在填土上（前傾牆），目前尚未支援；"
            "請改用 0（背面鉛直）或正值（底部較寬）。")
    xb_top = nf * H + top

    def xf(y):
        return nf * y

    def xb(y):
        return xb_top + nb * (H - y)

    # 依砌石層（若有）切段，讓每一層界面都被檢核；否則每 0.5 m 一段
    courses = q.get("stone_courses") or []
    if courses:
        cuts = [0.0]
        acc = 0.0
        for row in courses:
            acc += _f(row, "height_m")
            cuts.append(acc)
        if abs(acc - H) > 1e-6:
            raise BlockWallError("stone_courses 高度合計 %.3f m ≠ 牆高 %.3f m" % (acc, H))
        cuts[-1] = H
    else:
        n = max(1, int(math.ceil(H / 0.5 - 1e-9)))
        cuts = [H * i / n for i in range(n + 1)]
    segs = []
    clean = []
    for i in range(len(cuts) - 1):
        y0, y1 = cuts[i], cuts[i + 1]
        segs.append(_segment(y0, y1, xf(y0), xf(y1), xb(y0), xb(y1), layer=i + 1))
        clean.append({"layer": i + 1, "y0_m": round(y0, 4), "height_m": round(y1 - y0, 4),
                      "width_bottom_m": round(xb(y0) - xf(y0), 4),
                      "width_top_m": round(xb(y1) - xf(y1), 4)})
    return segs, clean


# --------------------------------------------------------------------------
# 自由體
# --------------------------------------------------------------------------

def _free_body(segs, yk, x_v, gamma_wall, gamma_soil, beta_deg):
    """回傳 yk 以上牆體＋楔形土的重量與形心。"""

    W = Mx = My = 0.0
    Ws = Msx = Msy = 0.0
    for s in segs:
        if s["y1"] <= yk + TOL:
            continue
        a = max(s["y0"], yk)
        b = s["y1"]

        def width(y, s=s):
            f, k = _at(s, y)
            return k - f

        def mx(y, s=s):
            f, k = _at(s, y)
            return 0.5 * (k * k - f * f)

        def soil_w(y, s=s):
            return max(0.0, x_v - _at(s, y)[1])

        def soil_mx(y, s=s):
            k = _at(s, y)[1]
            return 0.5 * max(0.0, x_v * x_v - k * k)

        W += gamma_wall * _simpson(width, a, b)
        Mx += gamma_wall * _simpson(mx, a, b)
        My += gamma_wall * _simpson(lambda y, w=width: y * w(y), a, b)
        Ws += gamma_soil * _simpson(soil_w, a, b)
        Msx += gamma_soil * _simpson(soil_mx, a, b)
        Msy += gamma_soil * _simpson(lambda y, w=soil_w: y * w(y), a, b)

    # 牆頂以上的斜填土三角形（由頂部後緣起坡至虛擬牆背）
    top = segs[-1]
    H = top["y1"]
    xb_top = top["xb1"]
    d = max(0.0, x_v - xb_top)
    rise = d * math.tan(math.radians(beta_deg))
    if d > TOL and rise > TOL:
        At = 0.5 * d * rise
        Ws += gamma_soil * At
        Msx += gamma_soil * At * (xb_top + 2.0 * d / 3.0)
        Msy += gamma_soil * At * (H + rise / 3.0)
    return {
        "W_wall": W, "x_wall": Mx / W if W > 0 else 0.0, "y_wall": My / W if W > 0 else 0.0,
        "W_soil": Ws, "x_soil": Msx / Ws if Ws > 0 else 0.0, "y_soil": Msy / Ws if Ws > 0 else 0.0,
        "rise": rise,
    }


def _edges_at(segs, yk):
    """檢核高程正上方那一段的前、後緣。"""

    for s in segs:
        if s["y0"] - TOL <= yk < s["y1"] - TOL:
            return _at(s, max(yk, s["y0"]))
    raise BlockWallError("找不到 %.3f m 以上的牆段" % yk)


def _interface(segs, yk, *, is_base, soil, seismic, gamma_wall, mu, frac, passive_kn=0.0):
    H = segs[-1]["y1"]
    above = [s for s in segs if s["y1"] > yk + TOL]
    x_v = max(max(s["xb0"], s["xb1"]) for s in above)  # 虛擬鉛直牆背
    xf_k, xb_k = _edges_at(segs, yk)
    beta = float(soil["backfill_slope_deg"])
    gamma_s = float(soil["gamma"])
    fb = _free_body(segs, yk, x_v, gamma_wall, gamma_s, beta)
    h = (H - yk) + fb["rise"]

    phi = float(soil["phi_deg"])
    delta = beta if soil.get("wall_friction_deg") in (None, "") else float(soil["wall_friction_deg"])
    q = float(soil["surcharge_kpa"])
    kh = float(seismic["kh"])
    Ka = EP.coulomb_active_coefficient(phi, wall_friction_deg=delta, backfill_slope_deg=beta)
    cd, sd = math.cos(math.radians(delta)), math.sin(math.radians(delta))
    P_soil = 0.5 * Ka * gamma_s * h * h
    P_q = Ka * q * h
    Ph = (P_soil + P_q) * cd
    Pv = (P_soil + P_q) * sd
    Mo = P_soil * cd * (h / 3.0) + P_q * cd * (h / 2.0)

    Kae = None
    dPh = dPv = F_eq = 0.0
    if kh > 0:
        Kae = EP.coulomb_active_coefficient(phi, wall_friction_deg=delta,
                                            backfill_slope_deg=beta, kh=kh)
        dP = max(0.0, (Kae - Ka) * (0.5 * gamma_s * h * h + q * h))
        dPh, dPv = dP * cd, dP * sd
        Mo += dPh * 0.6 * h
        F_eq = kh * (fb["W_wall"] + fb["W_soil"])
        Mo += kh * (fb["W_wall"] * (fb["y_wall"] - yk) + fb["W_soil"] * (fb["y_soil"] - yk))

    N = fb["W_wall"] + fb["W_soil"] + Pv + dPv
    T = Ph + dPh + F_eq
    Mr = (fb["W_wall"] * (fb["x_wall"] - xf_k) + fb["W_soil"] * (fb["x_soil"] - xf_k)
          + (Pv + dPv) * (x_v - xf_k))
    B = xb_k - xf_k
    FS_s = (mu * N + passive_kn) / T if T > 0 else float("inf")
    FS_o = Mr / Mo if Mo > 0 else float("inf")
    x_R = (Mr - Mo) / N if N > 0 else 0.0
    e = B / 2.0 - x_R
    x_lo, x_hi = B * (0.5 - frac / 2.0), B * (0.5 + frac / 2.0)
    if abs(e) <= B / 6.0:
        q_max = N / B * (1 + 6 * abs(e) / B)
        q_min = N / B * (1 - 6 * abs(e) / B)
    else:
        Lp = 3.0 * (B / 2.0 - abs(e))
        q_max = 2.0 * N / Lp if Lp > 0 else float("inf")
        q_min = 0.0
    return {
        "level_m": round(yk, 4),
        "is_base": is_base,
        "width_m": round(B, 4),
        "retained_height_m": round(h, 4),
        "Ka": round(Ka, 5),
        "Kae": None if Kae is None else round(Kae, 5),
        "W_wall_kN_per_m": round(fb["W_wall"], 3),
        "W_soil_kN_per_m": round(fb["W_soil"], 3),
        "Ph_kN_per_m": round(Ph, 3),
        "Pv_kN_per_m": round(Pv, 3),
        "dPae_h_kN_per_m": round(dPh, 3),
        "F_eq_kN_per_m": round(F_eq, 3),
        "N_kN_per_m": round(N, 3),
        "T_kN_per_m": round(T, 3),
        "Pp_kN_per_m": round(passive_kn, 3),
        "M_resist_kNm": round(Mr, 3),
        "M_over_kNm": round(Mo, 3),
        "friction": mu,
        "FS_sliding": FS_s,
        "FS_overturning": FS_o,
        "x_R_m": round(x_R, 4),
        "e_m": round(e, 4),
        "middle_range_m": (round(x_lo, 4), round(x_hi, 4)),
        "resultant_ok": (x_lo - 0.0005 * B) <= x_R <= (x_hi + 0.0005 * B),
        "q_max_kPa": round(q_max, 2) if math.isfinite(q_max) else q_max,
        "q_min_kPa": round(q_min, 2),
    }


# --------------------------------------------------------------------------
# 公開入口
# --------------------------------------------------------------------------

def applicability(wall_type, segs, layers, q, embedment):
    """§118 適用範圍檢核；違反者 raise，回傳 (有效高, 說明列)。"""

    spec = BLOCK_WALL_SPECS[wall_type]
    H = segs[-1]["y1"]
    eff = H - embedment
    notes = []
    max_eff = spec["max_effective_height_m"]
    if spec.get("max_by_site"):
        site = str(q.get("site_condition") or "").strip().lower()
        if site not in spec["max_by_site"]:
            raise BlockWallError("%s須指定 site_condition：cut（開挖坡面）或 fill（填方坡面）" % spec["label"])
        max_eff = spec["max_by_site"][site]
    if embedment < 0:
        raise BlockWallError("埋入深度不可為負")
    if eff <= 0:
        raise BlockWallError("埋入深度 %.2f m 不可大於等於牆總高 %.2f m" % (embedment, H))
    if eff > max_eff + 1e-9:
        raise BlockWallError(
            "%s有效高（露出地面）%.2f m 超過適用上限 %.1f m（%s）。"
            % (spec["label"], eff, max_eff, spec["basis"]))
    notes.append("有效高（露出地面）%.2f m ≤ %.1f m" % (eff, max_eff))
    if spec.get("max_layer_height_m"):
        lim = spec["max_layer_height_m"]
        for row in layers:
            exposed = row["height_m"] - max(0.0, min(row["height_m"], embedment - row["y0_m"]))
            if exposed > lim + 1e-9:
                raise BlockWallError(
                    "%s第 %d 層有效高 %.2f m 超過每層上限 %.1f m（%s）。"
                    % (spec["label"], row["layer"], exposed, lim, spec["basis"]))
        notes.append("每層有效高 ≤ %.1f m" % lim)
    if spec.get("min_front_batter"):
        nf = _f(q, "front_batter_ratio", MIN_MASONRY_FRONT_BATTER)
        if nf + 1e-9 < MIN_MASONRY_FRONT_BATTER:
            raise BlockWallError(
                "砌石牆面坡度 1:%.2f 陡於 1:%.1f（%s）。" % (nf, MIN_MASONRY_FRONT_BATTER, spec["basis"]))
        notes.append("牆面坡度 1:%.2f 不陡於 1:%.1f" % (nf, MIN_MASONRY_FRONT_BATTER))
    return eff, notes


def _stone_checks(wall_type, q, H):
    spec = BLOCK_WALL_SPECS[wall_type]
    k = spec["stone_height_factor"]
    courses = q.get("stone_courses") or []
    checks = []
    if courses:
        y = 0.0
        prev = None
        for i, row in enumerate(courses):
            L = _f(row, "stone_length_m")
            above = H - y
            checks.append({
                "item": "第 %d 層砌石往上高度 ≤ %.1f × 長徑（§118 七）" % (i + 1, k),
                "value": above, "limit": k * L, "ok": above <= k * L + 1e-9,
                "unit": "m", "relation": "le"})
            if prev is not None and L > prev + 1e-9:
                checks.append({
                    "item": "第 %d 層石材長徑須向上縮減（§118 七）" % (i + 1),
                    "value": L, "limit": prev, "ok": False, "unit": "m", "relation": "le"})
            prev = L
            y += _f(row, "height_m")
    else:
        L = _f(q, "stone_length_m", 0.0)
        if L <= 0:
            raise BlockWallError("砌石牆須提供 stone_length_m（底層石材長徑，牆厚方向）或 stone_courses")
        checks.append({
            "item": "底層砌石往上高度 ≤ %.1f × 長徑（§118 七）" % k,
            "value": H, "limit": k * L, "ok": H <= k * L + 1e-9,
            "unit": "m", "relation": "le"})
    return checks


def analyse(q: Mapping[str, Any], soil: Mapping[str, Any] | None = None,
            seismic: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """疊式／砌石擋土牆常時或地震工況穩定分析。"""

    wall_type = str(q.get("wall_type") or "").strip().lower()
    spec = BLOCK_WALL_SPECS.get(wall_type)
    if spec is None:
        raise BlockWallError("不支援的牆型：%s；可用 %s" % (
            wall_type or "（空白）", "、".join(BLOCK_WALL_SPECS)))
    soil = dict({
        "gamma": 18.0,
        "phi_deg": 30.0,
        "c_kpa": 0.0,
        "backfill_slope_deg": 0.0,
        "wall_friction_deg": None,
        "surcharge_kpa": 0.0,
        "allowable_bearing_kpa": 200.0,
        "base_friction": 0.5,
        "foundation": "soil",
    }, **(soil or {}))
    seismic = dict({"kh": 0.0}, **(seismic or {}))
    kh = float(seismic["kh"])
    if kh < 0:
        raise BlockWallError("kh 不可為負")

    if spec["layout"] == "layers":
        segs, layers = _layers_geometry(q)
    else:
        segs, layers = _masonry_geometry(q)
    H = segs[-1]["y1"]
    embedment = _f(q, "embedment_m", 0.0)
    eff, applicability_notes = applicability(wall_type, segs, layers, q, embedment)

    # 牆背不可懸在填土上、上層不可懸空
    for s in segs:
        if s["xb1"] > s["xb0"] + 1e-9:
            raise BlockWallError("第 %s 段牆背往上後退（懸在填土上），目前尚未支援此幾何" % s["layer"])
    for a, b in zip(segs, segs[1:]):
        if b["xb0"] > a["xb1"] + 1e-9:
            raise BlockWallError("第 %s 層後緣超出下層，牆背懸在填土上，目前尚未支援" % b["layer"])
        if b["xf0"] < a["xf1"] - 1e-9:
            raise BlockWallError("第 %s 層前緣超出下層（懸空），請檢查 offset／width" % b["layer"])

    gamma_wall = _f(q, "unit_weight_kn_m3", spec["unit_weight_kn_m3"])
    mu_i = _f(q, "interface_friction", spec["interface_friction"])
    mu_b = float(soil["base_friction"])
    base_frac = 0.5 if soil["foundation"] == "rock" else 1.0 / 3.0
    passive = EP.toe_passive_resistance(
        depth_m=embedment, gamma_kn_m3=float(soil["gamma"]), phi_deg=float(soil["phi_deg"]),
        **EP.passive_options(q, soil, default_include=False, default_ratio=1.0))

    levels = sorted({round(s["y0"], 9) for s in segs})
    interfaces = []
    for yk in levels:
        is_base = yk <= TOL
        interfaces.append(_interface(
            segs, yk, is_base=is_base, soil=soil, seismic=seismic,
            gamma_wall=gamma_wall, mu=mu_b if is_base else mu_i,
            frac=base_frac if is_base else 1.0 / 3.0,
            passive_kn=passive["Pp_kN_per_m"] if is_base else 0.0))

    case = "地震" if kh > 0 else "常時"
    s_lim = LIMITS["sliding_seismic"] if kh > 0 else LIMITS["sliding_static"]
    o_lim = LIMITS["overturning_seismic"] if kh > 0 else LIMITS["overturning_static"]
    checks = []
    for it in interfaces:
        where = "基底" if it["is_base"] else "%.2f m 層間" % it["level_m"]
        checks.append({"item": "%s滑動（%s）" % (where, case), "value": it["FS_sliding"],
                       "limit": s_lim, "ok": it["FS_sliding"] >= s_lim, "unit": "FS"})
        checks.append({"item": "%s傾倒（%s）" % (where, case), "value": it["FS_overturning"],
                       "limit": o_lim, "ok": it["FS_overturning"] >= o_lim, "unit": "FS"})
        frac_txt = "1/2" if (it["is_base"] and base_frac == 0.5) else "1/3"
        checks.append({"item": "%s合力作用點（%s 中段）" % (where, frac_txt), "value": it["x_R_m"],
                       "limit": list(it["middle_range_m"]), "ok": it["resultant_ok"], "unit": "m"})
    base = interfaces[0]
    q_a = float(soil["allowable_bearing_kpa"])
    q_ult = float(soil.get("ultimate_bearing_kpa") or 3.0 * q_a)
    q_max = base["q_max_kPa"]
    FS_b = q_ult / q_max if q_max and q_max > 0 else float("inf")
    checks.append({"item": "基礎承載（FS＝q_ult/q_max）", "value": FS_b, "limit": LIMITS["bearing"],
                   "ok": FS_b >= LIMITS["bearing"] and q_max <= q_a, "unit": "FS", "relation": "ge"})
    checks.append({"item": "基底最大應力 ≤ 容許承載力", "value": q_max, "limit": q_a,
                   "ok": q_max <= q_a, "unit": "kPa", "relation": "le"})
    if spec.get("stone_height_factor"):
        checks.extend(_stone_checks(wall_type, q, H))

    warnings = [
        "回填土黏著力未計（保守）。",
        "疊式／砌石牆視為透水，未計牆後靜水壓；有地下水或排水不良時須另行檢核。",
        "單位重 %.1f kN/m³、層間摩擦係數 %.2f 為假設值，須依材料與現場條件修正。" % (gamma_wall, mu_i),
    ]
    warnings += EP.passive_warnings(passive, kh > 0)
    if float(soil.get("c_kpa") or 0) > 0:
        warnings.append("輸入的回填土黏著力 c 已忽略（保守）。")
    if wall_type == "gabion":
        warnings.append("蛇籠石料以中徑 22～35 cm 塊（卵）石為原則（施工章蛇籠規定）；網線強度未檢核。")
    if wall_type == "crib":
        warnings.append("格籠構件（縱橫材）強度與格內填料流失未檢核。")
    if wall_type == "sandwich":
        warnings.append("背面填砌卵石／透水層視為背填土（不計入牆體重量），並假設其排水良好、不計靜水壓；"
                        "牆體以面層＋中間混凝土的等值單位重計，材料容許應力（§120 四）未檢核。")

    area = sum(_simpson(lambda y, s=s: _at(s, y)[1] - _at(s, y)[0], s["y0"], s["y1"]) for s in segs)
    out = {
        "wall_type": wall_type,
        "wall_label": spec["label"],
        "geometry": {
            "total_height_m": round(H, 4),
            "embedment_m": embedment,
            "effective_height_m": round(eff, 4),
            "base_width_m": round(segs[0]["xb0"] - segs[0]["xf0"], 4),
            "area_m2_per_m": round(area, 4),
            "layers": layers,
        },
        "applicability": {"basis": spec["basis"], "notes": applicability_notes},
        "materials": {"unit_weight_kn_m3": gamma_wall, "interface_friction": mu_i,
                      "base_friction": mu_b},
        "soil": soil,
        "seismic": {"kh": kh},
        "passive": passive,
        "interfaces": interfaces,
        "checks": checks,
        "warnings": warnings,
        "pass": all(c["ok"] for c in checks),
    }
    out["reinforcement"] = RC.design_block_wall_steel(q, out)
    out["rebar_kg_per_m"] = 0.0
    return out


def format_report(res: Mapping[str, Any]) -> str:
    g = res["geometry"]
    lines = [
        "%s：總高 %.2f m、埋入 %.2f m、有效高 %.2f m、底寬 %.2f m、斷面積 %.3f m²/m"
        % (res["wall_label"], g["total_height_m"], g["embedment_m"], g["effective_height_m"],
           g["base_width_m"], g["area_m2_per_m"]),
        "適用範圍：%s" % "；".join(res["applicability"]["notes"]),
        "材料：單位重 %.1f kN/m³、層間 μ=%.2f、基底 μ=%.2f；kh=%.2f"
        % (res["materials"]["unit_weight_kn_m3"], res["materials"]["interface_friction"],
           res["materials"]["base_friction"], res["seismic"]["kh"]),
        "RC 鋼筋：不適用（疊砌／砌石牆，鋼筋量 0 kg/m）",
        "",
    ]
    for it in res["interfaces"]:
        lines.append(
            "%s：寬 %.2f m、h=%.2f m、Ka=%.3f、N=%.1f kN/m、T=%.1f kN/m、FS滑=%.2f、FS倒=%.2f、x_R=%.3f m"
            % ("基底" if it["is_base"] else "%.2f m 層間" % it["level_m"], it["width_m"],
               it["retained_height_m"], it["Ka"], it["N_kN_per_m"], it["T_kN_per_m"],
               it["FS_sliding"], it["FS_overturning"], it["x_R_m"]))
    passive_line = EP.passive_summary(res.get("passive") or {})
    if passive_line:
        lines.append(passive_line)
    lines.append("")
    for c in res["checks"]:
        lim = c["limit"]
        lim_txt = "%.3f~%.3f" % tuple(lim) if isinstance(lim, (list, tuple)) else "%.3f" % lim
        lines.append("  [%s] %s：%.3f / 要求 %s" % ("OK" if c["ok"] else "NG", c["item"], c["value"], lim_txt))
    lines.append("")
    lines.append("綜合判定：%s" % ("全部通過" if res["pass"] else "未通過，須調整斷面"))
    return "\n".join(lines)


def selftest() -> int:
    """手算對照（蛇籠 3 層、有效高 2.5 m，每項可獨立驗算）。"""
    from _selftest_util import Checker

    c = Checker("疊砌式擋土牆（蛇籠 3 層）")
    q = {"wall_type": "gabion", "course_count": 3, "course_height_m": 1.0,
         "base_width_m": 2.5, "width_decrement_m": 0.5, "step_side": "front",
         "embedment_m": 0.5}
    soil = {"gamma": 18.0, "phi_deg": 30.0, "backfill_slope_deg": 0.0,
            "surcharge_kpa": 0.0, "allowable_bearing_kpa": 200.0,
            "base_friction": 0.6, "foundation": "soil"}
    r = analyse(q, soil=soil, seismic={"kh": 0.0})
    g = r["geometry"]
    i0 = r["interfaces"][0]
    c.close("主動土壓力係數 Ka", i0["Ka"],
            math.tan(math.radians(45.0 - 30.0 / 2)) ** 2, tol=1e-4)
    c.close("牆體重量", i0["W_wall_kN_per_m"],
            g["area_m2_per_m"] * r["materials"]["unit_weight_kn_m3"], tol=1e-4)
    c.close("主動土壓力 Ph", i0["Ph_kN_per_m"],
            0.5 * i0["Ka"] * 18.0 * g["total_height_m"] ** 2, tol=1e-4)
    c.close("基底抗滑 FS", i0["FS_sliding"],
            i0["N_kN_per_m"] * i0["friction"] / i0["T_kN_per_m"], tol=1e-4)
    c.close("基底抗傾倒 FS", i0["FS_overturning"],
            i0["M_resist_kNm"] / i0["M_over_kNm"], tol=1e-4)
    c.close("最大承壓 q", i0["q_max_kPa"],
            i0["N_kN_per_m"] / g["base_width_m"]
            * (1.0 + 6.0 * i0["e_m"] / g["base_width_m"]), tol=1e-4)
    with_passive = analyse({**q, "include_passive": True}, soil=soil, seismic={"kh": 0.0})
    ip = with_passive["interfaces"][0]
    c.close("牆趾被動土壓力 Pp", ip["Pp_kN_per_m"], 0.5 * 3.0 * 18.0 * 0.5 ** 2, tol=1e-3)
    c.close("計入 Pp 後基底抗滑 FS", ip["FS_sliding"],
            (i0["N_kN_per_m"] * i0["friction"] + 6.75) / i0["T_kN_per_m"], tol=1e-3)
    c.close("Pp 不影響層間抗滑 FS", with_passive["interfaces"][1]["FS_sliding"],
            r["interfaces"][1]["FS_sliding"])
    return c.run()


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    ap = argparse.ArgumentParser(description="疊式（蛇籠／格籠）與砌石擋土牆穩定分析")
    ap.add_argument("json", help="輸入 JSON 檔（含 section、soil、kh）")
    args = ap.parse_args()
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    seismic = {"kh": float(data.get("kh", 0.0))}
    res = analyse(data.get("section") or data, soil=data.get("soil"), seismic=seismic)
    print(format_report(res))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
