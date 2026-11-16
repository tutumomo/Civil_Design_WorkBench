# -*- coding: utf-8 -*-
r"""工作台即時交叉驗算：把使用者「當下這組參數」灌進 OCSS 模板再算一次，逐項比對。

與 `ocss_crosscheck.py checks`（批次對照）的差別
------------------------------------------------
批次對照跑的是 `checks/*.json` 裡**固定的一組參數**，證明「公式對得上」；
本模組跑的是工作台上**任意一組參數**，所以每個計算器都要多寫三樣東西：

1. **參數對應**（`inputs`）：本專案引擎實際採用的值 → 模板輸入。值一律取自引擎回傳的
   結果（含預設值），不另外維護一套預設邏輯。
2. **對齊說明**（`alignment`）：為了讓兩邊比的是同一個東西而歸零／固定了哪些模板輸入，
   原樣回給畫面，使用者看得到。
3. **逐項適用條件**（`compare`）：某些參數組合下某一項不可比（例：設計流量超過滿流容量時，
   模板把水深固定成 1.05H 當溢流記號）。這類項目標 `skipped` 並寫明原因，
   **不比、也不算吻合**。

比對與差異處置規則沿用 `ocss_template_check.compare_one()`，批次與即時是同一份判定。

為什麼容差帶絕對值
------------------
本專案引擎回傳的是**四捨五入後**的數字（例：`Q_cap_m3s` 取 4 位小數），任意參數下
小數值的相對誤差會被捨入放大（0.0500 ↔ 0.04996 相對差 0.08%，但只差半個末位）。
所以每項的 `abs` 取「該欄位末位的一半」，這是回報精度，不是放寬容差；
超出末位的差異仍然會被判為差異。

不做的事
--------
* 不信任前端傳來的計算結果：伺服器端用同一組參數重跑引擎（`persist=False`，不寫 `out/`）。
* 不動 OCSS 專案：只用無狀態的 `evaluate`。
* 不回傳 OCSS 的整體 UC／合格判定：那包含沒對齊的部分（例：基腳自重被歸零、配筋用模板
  預設），拿來當結論會誤導。
* 不回傳 token，也不回傳 OCSS 的原始回應。

用法::

    python tools/crosscheck/ocss_live.py --list
    python tools/crosscheck/ocss_live.py channel_hydraulics            # 用計算器範例參數
    python tools/crosscheck/ocss_live.py steel_column --payload p.json
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT / "tools" / "design"), str(ROOT / "tools"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ocss_template_check as T  # noqa: E402

SCHEMA = "civil-ocss-live/1"

# OCSS 一次只處理一個請求；工作台是多執行緒伺服器，這裡排隊避免互相逾時。
_LOCK = threading.Lock()
LOCK_WAIT_S = 90
EVAL_TIMEOUT_S = 120


class NotApplicable(Exception):
    """這組參數不在可對照的範圍內（不是錯誤，是「這題 OCSS 模板算的不是同一件事」）。"""


# ============================================================ 小工具
def _lit(v) -> str:
    """literal 型模板的字面常數：固定小數寫法，避免 `1e-05` 這種模板語法不一定認得的形式。"""
    s = "%.12f" % float(v)
    s = s.rstrip("0").rstrip(".")
    return s or "0"


def _num(d, key, default=None):
    v = (d or {}).get(key)
    if v in (None, ""):
        if default is None:
            raise NotApplicable("缺少參數 %s" % key)
        return float(default)
    return float(v)


def _tol(rel: float, abs_: float = 0.0) -> dict:
    return {"rel": rel, "abs": abs_}


def _ocss_value(ev: dict, name: str):
    """取 OCSS 某變數的數值；沒有就回 None（不丟錯，用來判斷模板有沒有算到這一段）。"""
    try:
        return T.get_ocss(ev, "var:" + name)[0]
    except T.TemplateCheckError:
        return None


# ============================================================ 排水溝水理
def _channel_inputs(payload: dict, res: dict) -> tuple[dict, list[str]]:
    q, b, h, s, n = (float(res[k]) for k in ("Q_design", "b", "h_total", "S", "manning_n"))
    if min(q, b, h, s, n) <= 0:
        raise NotApplicable("設計流量、內寬、溝深、縱坡與曼寧 n 都必須大於 0")
    fb_min = _num(payload, "freeboard_min_m", 0.20)
    inputs = {
        "use_rational": "0", "Q_direct": _lit(q),
        "B_chan": _lit(b), "H_chan": _lit(h), "z_side": "0",
        "S_chan": _lit(s), "n_manning": _lit(n), "fb_min": _lit(fb_min),
    }
    notes = [
        "流量改用直接輸入（use_rational = 0），不經模板內的合理化公式。",
        "側坡 z = 0（矩形 U 型溝）。",
        "模板的側壁結構檢核沿用模板預設值，不列入比對（本計算器只算水理）。",
    ]
    if res.get("sized_section"):
        notes.insert(0, "斷面取本專案自動反推的結果：內寬 %s m、溝深 %s m。" % (_lit(b), _lit(h)))
    return inputs, notes


def _channel_compare(payload: dict, res: dict, ev: dict) -> list[dict]:
    overflow = None
    q_d, q_cap = _ocss_value(ev, "Q_design"), _ocss_value(ev, "Q_cap")
    if q_d is not None and q_cap is not None and q_d > q_cap:
        overflow = ("設計流量超過滿流容量：OCSS 模板此時把水深固定為 1.05H 當溢流記號，"
                    "不是實際的正常水深，這一項不可比。")
    elif res.get("h_normal_m") is None:
        overflow = "本專案在 1.5 倍溝深內找不到正常水深（斷面容量不足），這一項不可比。"
    out = [
        {"name": "滿流通水量 Q_cap", "unit": "m³/s", "ours": "result.Q_cap_m3s",
         "ocss": "var:Q_cap", "tol": _tol(1e-3, 5.1e-5)},
        {"name": "滿流流速 V_full", "unit": "m/s", "ours": "result.V_full_ms",
         "ocss": "var:V_full", "tol": _tol(1e-3, 5.1e-4)},
        {"name": "正常水深 h_n", "unit": "m", "ours": "result.h_normal_m",
         "ocss": "var:d_n", "tol": _tol(5e-3, 5.1e-5)},
        {"name": "設計流速 V", "unit": "m/s", "ours": "result.V_design_ms",
         "ocss": "var:V_design", "tol": _tol(5e-3, 5.1e-4)},
        {"name": "福祿數 Fr", "unit": "-", "ours": "check:福祿數",
         "ocss": "var:Fr_num", "tol": _tol(5e-3, 1e-9)},
        {"name": "所需出水高 fb_req", "unit": "m", "ours": "result.freeboard_required_m",
         "ocss": "var:fb_req", "tol": _tol(1e-3, 5.1e-4)},
    ]
    if overflow:
        for c in out[2:]:
            c["skip"] = overflow
    return out


# ============================================================ 獨立基腳
def _footing_inputs(payload: dict, res: dict) -> tuple[dict, list[str]]:
    geo, load = res["geometry"], res["load"]
    p = float(load["P_kN"])
    fc = float(payload.get("fc_mpa", 28.0))
    fy = float(payload.get("fy_mpa", 420.0))
    cover = float(payload.get("cover_mm", 75.0))
    qa = float(payload.get("q_allow_kpa", 200.0))
    mu = float(payload.get("friction_coefficient", 0.5))
    b_m, l_m = float(geo["B_m"]), float(geo["L_m"])
    t_mm = float(geo["thickness_m"]) * 1000.0
    cb, cl = float(geo["column_b_m"]), float(geo["column_l_m"])
    # OCSS 模板的輸入防護（ok_all_input）在 Python 端先做，失敗時才不會拿到一句
    # 「模板沒有產生結果」而不知���是哪個條件擋下來的。
    if not 17.0 <= fc <= 70.0:
        raise NotApplicable("f'c = %g MPa 超出 OCSS 模板可算範圍（17～70 MPa）。" % fc)
    if not 280.0 <= fy <= 550.0:
        raise NotApplicable("fy = %g MPa 超出 OCSS 模板可算範圍（280～550 MPa）。" % fy)
    if b_m <= cb or l_m <= cl:
        raise NotApplicable("基腳必須大於柱（%g×%g m 對柱 %g×%g m），"
                            "否則 OCSS 模板的基底承壓區算不出來。" % (b_m, l_m, cb, cl))
    if t_mm < 200.0:
        raise NotApplicable("基腳厚度 %g mm 小於 OCSS 模板下限 200 mm。" % t_mm)
    if cover < 50.0:
        raise NotApplicable("保護層 %g mm 小於 OCSS 模板下限 50 mm。" % cover)
    if t_mm - cover - 25.4 <= 100.0:
        raise NotApplicable("有效深度 %g mm 不足（厚度 − 保護層 − 鋼筋直徑 25.4 mm 須大於 100 mm）。"
                            % (t_mm - cover - 25.4))
    if p <= 0:
        raise NotApplicable("OCSS 模板只處理受壓基腳（柱軸力 P 須大於 0）。")
    if qa <= 0:
        raise NotApplicable("容許支承力 qa 須大於 0。")
    inputs = {
        "fc_in": fc, "fy_in": fy,
        "gamma_c": 0, "gamma_s": 0, "D_f": 0,
        "cover": cover,
        "B_f": b_m * 1000.0, "L_f": l_m * 1000.0, "h_f": t_mm,
        "c_1": cb * 1000.0, "c_2": cl * 1000.0,
        "P_serv": p,
        "Mx_serv": abs(float(load["Mx_kNm"])), "My_serv": abs(float(load["My_kNm"])),
        "Hx_serv": 0, "Hy_serv": 0,
        "P_u": p,
        "M_ux": abs(float(load["Mx_kNm"])), "M_uy": abs(float(load["My_kNm"])),
        "q_a_in": qa, "mu_base": mu,
    }
    notes = [
        "基腳自重與覆土重歸零（γc = γs = 0、Df = 0）：本專案的基底壓力只計柱傳來的 "
        "P、Mx、My；不對齊的話比的是兩個不同的載重模型，不是公式。",
        "模板的因數化載重（Pu、Mux、Muy）直接填服務載重、水平力填 0：本計算器沒有分開輸入，"
        "所以剪力、沖剪、撓曲與抗滑不列入比對。",
        "配筋沿用模板預設（雙向 D25 × 11 支），不列入比對。",
        "兩邊都是全斷面線性分佈 q = P/A ± M/S；基底局部脫離（q_min < 0）時兩邊都不做應力重分配。",
    ]
    return inputs, notes


def _footing_compare(payload: dict, res: dict, ev: dict) -> list[dict]:
    t = _tol(1e-6, 1e-9)
    return [
        {"name": "基底面積 A", "ours": "result.pressure.area_m2", "ocss": "var:Area_f", "tol": t},
        {"name": "基底平均壓力 q_avg", "ours": "result.pressure.q_average_kpa",
         "ocss": "var:q_avg_serv", "tol": t},
        {"name": "最大基底壓力 q_max", "ours": "result.pressure.q_max_kpa",
         "ocss": "var:q_max_serv", "tol": t},
        {"name": "最小基底壓力 q_min", "ours": "result.pressure.q_min_kpa",
         "ocss": "var:q_min_serv", "tol": t},
        {"name": "偏心距 e_x", "ours": "result.pressure.e_x_m", "ocss": "var:e_x",
         "scale": 1000, "tol": t},
        {"name": "偏心距 e_y", "ours": "result.pressure.e_y_m", "ocss": "var:e_y",
         "scale": 1000, "tol": t},
    ]


# ============================================================ 鋼柱柱腳
# OCSS 模板內建的 CNS 1490 H 型鋼表（id: (h, b) mm）。柱構材不比；這裡只用來挑一個能讓
# 模板「基板須大於柱斷面」防護通過、且最接近使用者斷面的規格。
_OCSS_H_SECTIONS = {
    1: (100, 100), 2: (125, 125), 3: (150, 150), 4: (175, 175), 5: (200, 200),
    6: (250, 250), 7: (300, 300), 8: (350, 350), 9: (400, 400), 10: (200, 100),
    11: (250, 125), 12: (300, 150), 13: (350, 175), 14: (400, 200), 15: (450, 200),
    16: (500, 200), 17: (600, 200), 18: (700, 300), 19: (800, 300), 20: (900, 300),
}
_ANCHOR_GRADE = {"A307": 1, "F10T": 2}          # 其餘走模板的「螺牙桿件」＝3（Fu 固定 400 MPa）
_KGF_PER_MPA = 10.1972                           # 與 steel_column.base_plate_bearing 同一個換算


def _rect4(positions) -> tuple[float, float] | None:
    """錨栓是否為「以原點為中心的 4 支矩形」；是則回傳（x 向間距, y 向間距）m。"""
    if len(positions) != 4:
        return None
    xs = sorted({round(float(p["x_m"]), 9) for p in positions})
    ys = sorted({round(float(p["y_m"]), 9) for p in positions})
    if len(xs) != 2 or len(ys) != 2 or xs[1] <= 0 or ys[1] <= 0:
        return None
    if abs(xs[0] + xs[1]) > 1e-9 or abs(ys[0] + ys[1]) > 1e-9:
        return None
    got = {(round(float(p["x_m"]), 9), round(float(p["y_m"]), 9)) for p in positions}
    if got != {(x, y) for x in xs for y in ys}:
        return None
    return xs[1] - xs[0], ys[1] - ys[0]


def _steel_inputs(payload: dict, res: dict) -> tuple[dict, list[str]]:
    if res.get("design_method") != "lrfd":
        raise NotApplicable(
            "OCSS 模板的容許應力設計法（ASD）只檢核純軸壓柱構材，不算柱腳基板與錨栓；"
            "改用 LRFD 才有可對照的項目。")
    col, bp, an, sec = res["column"], res["base_plate"], res["anchors"], res["section"]
    p = float(col["axial_P_kN"])
    if p < 0:
        raise NotApplicable("OCSS 模板以受壓柱腳為對象（軸力以受壓為正），受拉柱不可比。")
    b_p, n_p = float(bp["plate_B_m"]) * 1000.0, float(bp["plate_N_m"]) * 1000.0
    fit = [(abs(h - float(sec["h_mm"])) + abs(b - float(sec["b_mm"])), i)
           for i, (h, b) in _OCSS_H_SECTIONS.items() if b < b_p and h < n_p]
    if not fit:
        raise NotApplicable("基板小於 OCSS 內建型鋼表的最小斷面（100×100），模板無法表示。")
    sec_id = min(fit)[1]
    positions = an["positions"]
    rect = _rect4(positions)
    if rect:
        b_x, b_y = rect
    else:
        b_x = max(float(q["x_m"]) for q in positions) - min(float(q["x_m"]) for q in positions)
        b_y = max(float(q["y_m"]) for q in positions) - min(float(q["y_m"]) for q in positions)
        if b_x <= 0 or b_y <= 0:
            raise NotApplicable("錨栓排成一直線：OCSS 模板固定假設 4 支矩形配置，無法表示。")
    grade = str(an["grade"])
    ped_b = float(bp["pedestal_B_m"]) * 1000.0 if bp.get("pedestal_B_m") else b_p
    ped_n = float(bp["pedestal_N_m"]) * 1000.0 if bp.get("pedestal_N_m") else n_p
    inputs = {
        "design_method": 1,
        "f_y_in": float(col["fy_mpa"]), "f_y_bp_in": float(col["fy_mpa"]),
        "fc_in": float(bp["fc_mpa"]) * _KGF_PER_MPA,
        "anchor_grade": _ANCHOR_GRADE.get(grade, 3),
        "shear_mode": 2 if an.get("shear_path") == "anchors" else 1,
        "L_col": float(col["length_m"]), "K_x": float(col["Kx"]), "K_y": float(col["Ky"]),
        "L_b": float(col["Lb_m"]), "C_b": 1.0,
        "P_u": p,
        "M_ux": abs(float(col["moment_Mx_kNm"])), "M_uy": abs(float(col["moment_My_kNm"])),
        "V_u": (float(col["shear_Vx_kN"]) ** 2 + float(col["shear_Vy_kN"]) ** 2) ** 0.5,
        "B_p": b_p, "N_p": n_p, "t_p": float(bp["plate_t_mm"]),
        "B_ped": ped_b, "N_ped": ped_n,
        "d_b": float(an["diameter_mm"]),
        "b_x": b_x * 1000.0, "b_y": b_y * 1000.0,
        "h_ef": float(an["embedment_mm"]),
        "section_id": sec_id,
    }
    h_s, b_s = _OCSS_H_SECTIONS[sec_id]
    notes = [
        "柱構材不比：OCSS 的斷面取自內建 CNS 型鋼表（本次選 RH %d×%d，只為讓「基板須大於柱斷面」"
        "的輸入防護通過），與本專案的自訂斷面 H%g×%g 不是同一支柱。"
        % (h_s, b_s, float(sec["h_mm"]), float(sec["b_mm"])),
        "混凝土強度換算成模板單位：f'c = %g MPa × 10.1972 = %.2f kgf/cm²。"
        % (float(bp["fc_mpa"]), inputs["fc_in"]),
        "彎矩取絕對值（兩邊都以絕對值求最大角隅壓力與最大錨栓拉力）。",
        "剪力傳遞、基板厚度與錨栓 45° 應力錐不列入比對（兩邊的截斷與摩擦假設不同）。",
    ]
    if float(sec["h_mm"]) >= n_p or float(sec["b_mm"]) >= b_p:
        notes.append("注意：本專案的柱斷面大於基板尺寸，模板那側是用內建型鋼表通過防護的，"
                     "比對到的基板項目仍成立，但這樣的柱腳本身不合理，請回頭檢查基板尺寸。")
    if not bp.get("pedestal_B_m") or not bp.get("pedestal_N_m"):
        notes.append("未填墩座尺寸：兩邊都取 A2 = A1（無圍束效益）。")
    return inputs, notes


def _steel_compare(payload: dict, res: dict, ev: dict) -> list[dict]:
    col, an = res["column"], res["anchors"]
    mx, my = abs(float(col["moment_Mx_kNm"])), abs(float(col["moment_My_kNm"]))
    grade = str(an["grade"])
    bp = "result.base_plate."
    if mx > 0 and my > 0:
        q_side, q_skip = "contact_pressure_x", (
            "雙向彎矩同時存在：OCSS 把兩向疊加成角隅壓力（P/A ± Mx/Sx ± My/Sy），"
            "本專案分向各報一組（P/A ± M/S），不是同一個量，這一項不可比。")
    else:
        q_side, q_skip = ("contact_pressure_y" if my > 0 else "contact_pressure_x"), None
    out = [
        {"name": "基板承壓面積 A1", "ours": bp + "bearing.A1_cm2", "ocss": "var:A1",
         "tol": _tol(1e-9, 1e-9)},
        {"name": "圍束面積 A2", "ours": bp + "bearing.A2_cm2", "ocss": "var:A2",
         "tol": _tol(1e-9, 1e-9)},
        {"name": "混凝土承壓設計強度 φPp", "ours": bp + "bearing.capacity_kN",
         "ocss": "var:phiP_p", "tol": _tol(1e-3)},
        {"name": "基板最大接觸壓力 q_max", "ours": bp + q_side + ".q_max_kpa",
         "ocss": "var:q_max", "scale": 0.001, "tol": _tol(1e-6, 1e-9), "skip": q_skip},
        {"name": "基板最小接觸壓力 q_min", "ours": bp + q_side + ".q_min_kpa",
         "ocss": "var:q_min", "scale": 0.001, "tol": _tol(1e-6, 1e-9), "skip": q_skip},
        {"name": "單支錨栓最大拉力 T", "ours": "result.anchors.max_tension_kn",
         "ocss": "var:T_bolt", "tol": _tol(1e-3, 1e-6)},
        {"name": "錨栓拉力設計強度 φRn,t", "ours": "result.anchors.capacity.tension_capacity_kN",
         "ocss": "var:phiRn_t", "tol": _tol(1e-3)},
    ]
    if _rect4(an["positions"]) is None:
        out[5]["skip"] = ("錨栓不是「以柱心為中心的 4 支矩形」（本次 %d 支）：OCSS 模板固定用 "
                          "T = Mx/(2·by) + My/(2·bx) − Pu/4，本專案用彈性錨栓群法逐支求解，"
                          "支數或位置不同時不是同一個算式。" % len(an["positions"]))
    if grade not in _ANCHOR_GRADE:
        out[6]["skip"] = ("OCSS 模板沒有 %s 這個等級；它的「螺牙桿件」固定 Fu = 400 MPa，"
                          "與本專案採用的 Fu = %.2f tf/cm² 不同，強度不可比。"
                          % (grade, float(an["capacity"]["nominal_tension_tf_cm2"]) / 0.75))
    return out


# ============================================================ 登記表
SPECS: dict[str, dict] = {
    "channel_hydraulics": {
        "template": "tw-drainage-channel",
        "label": "排水溝水理",
        "scope": "滿流通水量與流速、正常水深、設計流速、福祿數、所需出水高",
        "probe": "Q_cap",
        "limits": ["設計流量、內寬、溝深、縱坡、曼寧 n 皆須大於 0"],
        "inputs": _channel_inputs,
        "compare": _channel_compare,
    },
    "foundation_isolated": {
        "template": "tw-isolated-footing",
        "label": "獨立基腳基底壓力",
        "scope": "基底面積、平均／最大／最小基底壓力、雙向偏心距",
        "probe": "Area_f",
        "limits": [
            "f'c 須在 17～70 MPa、fy 須在 280～550 MPa",
            "基腳須大於柱（B > 柱寬、L > 柱長）、厚度 ≥ 200 mm、保護層 ≥ 50 mm",
            "柱軸力 P 與容許支承力 qa 須大於 0",
            "有效深度須大於 100 mm（厚度 − 保護層 − 模板預設鋼筋 D25 的直徑）",
        ],
        "inputs": _footing_inputs,
        "compare": _footing_compare,
    },
    "steel_column": {
        "template": "tw-steel-column",
        "label": "鋼柱柱腳基板與錨栓",
        "scope": "基板承壓面積與圍束面積、混凝土承壓設計強度、基板接觸壓力、"
                 "單支錨栓最大拉力與拉力設計強度",
        "probe": "A1",
        "limits": [
            "僅 LRFD（模板的 ASD 不算柱腳）",
            "鋼材 Fy 須在 2.0～4.55 tf/cm²（約 196～446 MPa）",
            "混凝土 f'c 須在 140～560 kgf/cm²（約 13.7～54.9 MPa）",
            "基板須大於柱斷面、墩座不得小於基板",
            "錨栓直徑 ≥ 16 mm、埋深與間距大於 0",
        ],
        "inputs": _steel_inputs,
        "compare": _steel_compare,
    },
}


def _offline_cases() -> dict[str, int]:
    """`checks/*.json` 裡各計算器的批次對照案例數（只讀磁碟，不連 OCSS）。"""
    out: dict[str, int] = {}
    for p in sorted((HERE / "checks").glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in (data.get("checks") or []) if isinstance(data, dict) else []:
            cid = c.get("calculator") if isinstance(c, dict) else None
            if cid:
                out[cid] = out.get(cid, 0) + 1
    return out


def capability_map(ids) -> dict[str, dict]:
    """各計算器能不能即時交叉驗算（三態，不連 OCSS）。

    * `supported`    — 可以用任意參數即時驗算。
    * `offline_only` — 已有批次對照案例（固定參數），尚未開放任意參數的即時驗算。
    * `none`         — 尚無 OCSS 對照。
    """
    offline = _offline_cases()
    out: dict[str, dict] = {}
    for cid in ids:
        spec = SPECS.get(cid)
        if spec:
            out[cid] = {
                "status": "supported", "supported": True,
                "template": spec["template"], "label": spec["label"],
                "scope": spec["scope"], "limits": list(spec["limits"]),
            }
        elif offline.get(cid):
            out[cid] = {
                "status": "offline_only", "supported": False,
                "offline_cases": offline[cid],
                "reason": "已有 %d 個固定參數的批次對照案例，尚未開放任意參數的即時驗算。"
                          % offline[cid],
            }
        else:
            out[cid] = {"status": "none", "supported": False,
                        "reason": "尚無 Open CalcSheet Studio 對照。"}
    return out


# ============================================================ OCSS 狀態
def status(client=None) -> dict:
    """OCSS 現在能不能用。不回傳 token；忙線時不排隊，直接回報忙線。"""
    from ocss_client import OcssClient, OcssError, OcssUnavailable

    if not _LOCK.acquire(blocking=False):
        return {"available": True, "busy": True, "message": "正在進行另一筆交叉驗算。"}
    try:
        info = (client or OcssClient(timeout=4)).require()
    except OcssUnavailable as e:
        return {"available": False, "message": str(e)}
    except OcssError as e:
        return {"available": False, "message": "Open CalcSheet Studio 回報錯誤：%s" % e.message}
    finally:
        _LOCK.release()
    return {"available": True, "busy": False, "version": info.get("version"),
            "edition": info.get("edition")}


# ============================================================ 執行
def _base(calc_id: str, spec: dict | None) -> dict:
    return {
        "schema": SCHEMA, "calculator": calc_id,
        "template": spec["template"] if spec else None,
        "label": spec["label"] if spec else None,
        "status": None, "verdict": None, "message": "",
        "items": [], "counts": {"total": 0, "passed": 0, "handled": 0, "failed": 0, "skipped": 0},
        "alignment": [], "limits": list(spec["limits"]) if spec else [],
        "ocss_inputs": {}, "unit_warnings": [], "ours_ok": None, "ocss_version": None,
    }


def run(calc_id: str, payload: dict | None, client=None) -> dict:
    """用同一組參數讓本專案引擎與 OCSS 各算一次並逐項比對。

    `status`：
      * `ok`             — 兩邊都算完，看 `verdict` 與 `items`
      * `not_supported`  — 這個計算器沒有開放即時驗算
      * `not_applicable` — 這組參數不在可對照範圍（`message` 說明原因）
      * `unavailable`    — OCSS 沒開／token 不對／暫停
      * `engine_error`   — 本專案引擎對這組參數算不出結果
      * `error`          — OCSS 計算出錯或對照表與模板不一致

    `verdict`（僅 `status == "ok"`）：`match`（比到的項目全部吻合）／`handled`（有差異但都已
    寫處置說明）／`diff`（有未處置的差異）／`nothing_compared`（這組參數下沒有可比的項目）。
    """
    import design_api as D
    from ocss_client import OcssClient, OcssError, OcssUnavailable, unit_warnings

    t0 = time.time()
    spec = SPECS.get(calc_id)
    out = _base(calc_id, spec)

    def done(status_, message=""):
        out["status"], out["message"] = status_, message
        out["elapsed_s"] = round(time.time() - t0, 2)
        return out

    if spec is None:
        return done("not_supported", "這個計算器尚未開放即時交叉驗算。")

    env = D.run_calculation(calc_id, payload or {}, persist=False)
    res = env.get("result")
    if not isinstance(res, dict):
        return done("engine_error", "本專案引擎對這組參數算不出結果，請先修正參數：%s"
                    % (env.get("error") or ""))
    out["ours_ok"] = bool(env.get("ok"))

    try:
        inputs, out["alignment"] = spec["inputs"](payload or {}, res)
        src, inv = T.load_template(spec["template"])
        src, values = T.apply_inputs(src, inv, inputs)
    except NotApplicable as e:
        return done("not_applicable", str(e))
    except T.TemplateCheckError as e:
        return done("error", "對照表與 OCSS 模板不一致：%s" % e)
    except (KeyError, TypeError, ValueError) as e:
        return done("error", "本專案結果缺少對照所需的欄位：%s" % e)
    out["ocss_inputs"] = inputs

    client = client or OcssClient(timeout=EVAL_TIMEOUT_S)
    if not _LOCK.acquire(timeout=LOCK_WAIT_S):
        return done("unavailable", "Open CalcSheet Studio 正忙於另一筆驗算，請稍後再試。")
    try:
        info = client.require()
        ev = client.evaluate(src, values=values or None)
    except OcssUnavailable as e:
        return done("unavailable", str(e))
    except OcssError as e:
        return done("error", "Open CalcSheet Studio 回報錯誤：%s" % e.message)
    finally:
        _LOCK.release()
    out["ocss_version"] = info.get("version")

    if ev.get("errorLines"):
        return done("error", "Open CalcSheet Studio 計算有 %s 行錯誤，結果不可用。"
                    % ev.get("errorLines"))
    if _ocss_value(ev, spec["probe"]) is None:
        return done("not_applicable",
                    "這組參數沒有通過 OCSS 模板的輸入防護，模板沒有產生結果。"
                    "模板的適用範圍見下方。")

    counts = out["counts"]
    try:
        for cmp_ in spec["compare"](payload or {}, res, ev):
            counts["total"] += 1
            if cmp_.get("skip"):
                counts["skipped"] += 1
                out["items"].append({"name": cmp_["name"], "status": "skipped",
                                     "reason": cmp_["skip"], "unit": cmp_.get("unit", "")})
                continue
            item = T.compare_one(env, ev, cmp_)
            if cmp_.get("unit"):
                item["unit"] = cmp_["unit"]
            if not (item["rel"] == item["rel"] and item["rel"] != float("inf")):
                # OCSS 側為 0 時相對差無定義（兩個都是 0 也不算差異）；給 null，
                # 避免把 Infinity 塞進 JSON（瀏覽器端 JSON.parse 會拒收）。
                item["rel"] = None
            key = {"pass": "passed", "handled": "handled", "fail": "failed"}[item["status"]]
            counts[key] += 1
            out["items"].append(item)
    except T.TemplateCheckError as e:
        return done("error", "取值失敗（對照表與模板或引擎輸出不一致）：%s" % e)

    out["unit_warnings"] = unit_warnings(ev)
    if counts["failed"]:
        out["verdict"] = "diff"
    elif counts["handled"]:
        out["verdict"] = "handled"
    elif counts["passed"]:
        out["verdict"] = "match"
    else:
        out["verdict"] = "nothing_compared"
    return done("ok")


# ============================================================ CLI
def _print(r: dict) -> None:
    print("%s ↔ %s　狀態 %s　結論 %s　%s s" % (
        r["calculator"], r["template"], r["status"], r["verdict"], r.get("elapsed_s")))
    if r["message"]:
        print("  " + r["message"].replace("\n", "\n  "))
    for it in r["items"]:
        if it["status"] == "skipped":
            print("  －%-24s 不比：%s" % (it["name"], it["reason"]))
            continue
        mark = {"pass": "✓", "handled": "△", "fail": "✗"}[it["status"]]
        rel = it.get("rel")
        diff_txt = ("差 %.3g%%" % (rel * 100)) if rel is not None else "差 %.3g" % it["diff"]
        print("  %s %-24s 本專案 %-13.7g OCSS %-13.7g %-6s %s" % (
            mark, it["name"], it["ours"], it["ocss"], it["unit"], diff_txt))
    for n in r["alignment"]:
        print("  ※ " + n)
    for w in r["unit_warnings"]:
        print("  ⚠ " + w)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工作台即時交叉驗算（本專案引擎 ↔ OCSS 模板）")
    ap.add_argument("calculator", nargs="?", help="計算器 id")
    ap.add_argument("--payload", help="參數 JSON 檔；省略則用計算器範例參數")
    ap.add_argument("--list", action="store_true", help="列出各計算器的即時驗算能力")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args(argv)

    import design_api as D

    if a.list or not a.calculator:
        caps = capability_map([c["id"] for c in D.list_calculators()])
        for cid, c in caps.items():
            print("%-22s %-13s %s" % (cid, c["status"], c.get("scope") or c.get("reason")))
        return 0
    if a.payload:
        payload = json.loads(Path(a.payload).read_text(encoding="utf-8"))
    else:
        payload = next(c["example"] for c in D.list_calculators() if c["id"] == a.calculator)
    r = run(a.calculator, payload)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        _print(r)
    return 0 if r["status"] == "ok" and r["verdict"] in ("match", "handled") else 1


if __name__ == "__main__":
    sys.exit(main())
