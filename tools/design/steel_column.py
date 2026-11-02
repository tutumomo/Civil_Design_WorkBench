r"""鋼構柱、柱腳基板與基礎螺栓檢核（鋼構造建築物鋼結構設計技術規範 steel99）。

為什麼要這個模組
----------------
柱腳是鋼構最容易出事的地方：一根柱子斷了會是連續倒塌，但柱腳的問題（錨栓拉破混凝土、
基板太薄、摩擦力被高估）通常藏在圖面角落。本模組把三件事串成一條可追溯的計算：

1. 柱斷面：軸壓容量、撓曲容量、梁柱互制（§6.2／§6.3、§7.2、§8.2）。
2. 柱腳基板：混凝土承壓（§10.9）、基板厚度（懸臂法，見限制）。
3. 基礎螺栓：拉力群（剛性基板＋彈性錨栓＋混凝土剛性壓塊）、鋼材容量（§10.3）、
   混凝土 45° 應力錐拉破（§10.10.2）、剪力（摩擦／錨栓／剪力榫）、拉剪互制（表10.3-3）。

條文依據（data\法規\鋼構造建築物鋼結構設計技術規範_990916_全文.txt）
--------------------------------------------------------------------
§4.4 長細比（KL/r ≤ 200）、§4.5 斷面分類（表4.5-1）、§6.2／§6.3 軸壓容量、
§7.2 撓曲（式7.2-1、7.2.1、7.2.2）、§8.2 梁柱互制（式8.2-1～8.2-3、(8.2-1a)(8.2-1b)、
(8.2-2)）、§10.3 螺栓（表10.3-1、表10.3-2、表10.3-3）、§10.9 柱基與混凝土間之承壓、
§10.10 錨栓與埋置物（式10.10-1、圖C10.10-1 應力錐）。

設計法：ASD＝(一) 容許應力設計法；LRFD＝(二) 極限設計法。全案擇一，兩套不可混用。

數值來源紀律
------------
鋼構數值一律走 tools\regs\verified.py 的已驗證公式／表（steel99_*），不在本檔抄數字；
僅兩類數值是本檔自算：(a) 幾何（斷面性質、J、Cw、應力錐投影面積），
(b) 規範條文已明列但尚未入已驗證庫者（ASD 表10.3-2 之容許應力、表10.3-3 之互制式），
這兩類在輸出中會標明出處並附提醒。

必須自己決定的輸入（程式不代猜）
--------------------------------
1. 有效長度係數 K（§4.8 構架穩定）：側移構架不可圖省事取 1.0。
2. 柱腳假定（固接／鉸接）：程式只檢核傳入的力量，不判定剛接或鉸接。
3. 剪力傳遞路徑（摩擦／錨栓／剪力榫）：三者只能擇一為主，程式不疊加。
4. 基板厚度依 AISC Design Guide 1 懸臂法（我國規範未給公式），屬工程慣用方法。

限制
----
* 只做露出式柱腳、澆置前預埋錨栓；埋入式柱腳、後置錨栓、特殊預埋件不在本模組。
* 基板厚度採簡化懸臂法（單一控制懸臂），不等同 AISC DG1 完整參數化流程。
* 雙向彎矩採彈性錨栓群法並附提醒，須人工覆核。
* 未做柱腹板剪力、柱端局部壓碎、焊道、灌漿、錨頭疲勞、埋入式細部。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REGS_DIR = ROOT / "tools" / "regs"
if str(REGS_DIR) not in sys.path:
    sys.path.insert(0, str(REGS_DIR))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import verified as V
except Exception as exc:  # pragma: no cover - 依賴缺失時直接報錯，不做無聲替代
    raise ImportError(
        "steel_column 需要已驗證公式庫 tools/regs/verified.py（%s）" % exc
    ) from exc


class SteelColumnError(ValueError):
    """Raised for invalid steel-column inputs."""


# ── 單位換算 ────────────────────────────────────────────────────────────────
TF_PER_MPA = 0.0101972          # 1 MPa = 0.0101972 tf/cm²
KN_PER_TF = 9.80665             # 1 tf = 9.80665 kN
G_MPA = 206000.0                # 鋼材彈性模數（steel99 取 2100 tf/cm² ≈ 206 GPa）
G_TF = 810.0                    # 鋼材剪力模數（810 tf/cm²）

# 混凝土抗拉標稱應力（§10.10.2 解說）：LRFD 用 1.06√f'c、ASD 用 0.53√f'c（kgf/cm²）
CONE_NOMINAL_TENSION_LRFD = 1.06
CONE_ALLOW_TENSION_ASD = 0.53
PHI_CONCRETE_CONE = 0.75

# 螺栓材質（§10.10.1 解說）：基礎螺栓的標稱抗拉強度 tf/cm²
# ASD 表10.3-2（(一) 版 p.16）之容許應力為轉錄值，尚未入已驗證庫，輸出會附提醒。
BOLT_GRADES: dict[str, dict[str, Any]] = {
    "A307": {
        "label": "ASTM A307 基礎螺栓（一般無預力）",
        "Fu_tf_cm2": 4.20,
        "asd_Ft": 1.40,
        "asd_Fv": 0.70,
        "lrfd_row": "A307 螺栓",
    },
    "F10T": {
        "label": "CNS 11328 F10T／S10T 高強度螺栓",
        "Fu_tf_cm2": 10.00,
        "asd_Ft": 3.62,
        "asd_Fv": 1.87,
        "asd_Fv_no_thread": 2.68,
        "lrfd_row": "F10T(S10T) 螺栓、螺紋在剪力平面",
        "lrfd_row_no_thread": "F10T(S10T) 螺栓、螺紋不在剪力平面",
    },
    "F1554-36": {
        "label": "ASTM F1554 級 36（Gr.36）",
        "Fu_tf_cm2": 2.52,
        "asd_Ft": None,
        "asd_Fv": None,
    },
    "F1554-55": {
        "label": "ASTM F1554 級 55（Gr.55）",
        "Fu_tf_cm2": 3.85,
        "asd_Ft": None,
        "asd_Fv": None,
    },
    "F1554-105": {
        "label": "ASTM F1554 級 105（Gr.105）",
        "Fu_tf_cm2": 7.35,
        "asd_Ft": None,
        "asd_Fv": None,
    },
    "B2246-3.6": {
        "label": "CNS 4426 B2246 基礎螺栓 3.6 級",
        "Fu_tf_cm2": 3.00,
        "Fy_tf_cm2": 1.80,
        "asd_Ft": None,
        "asd_Fv": None,
    },
}


# ── 小工具 ──────────────────────────────────────────────────────────────────
def _num(data: Mapping[str, Any], key: str, default: Any = None, *, minimum: float | None = None) -> float:
    if key not in data or data[key] is None or data[key] == "":
        if default is None:
            raise SteelColumnError("缺少參數 %s" % key)
        value = float(default)
    else:
        try:
            value = float(data[key])
        except (TypeError, ValueError) as exc:
            raise SteelColumnError("參數 %s 必須是數字" % key) from exc
    if not math.isfinite(value):
        raise SteelColumnError("參數 %s 必須是有限值" % key)
    if minimum is not None and value < minimum:
        raise SteelColumnError("參數 %s 不得小於 %g（目前 %g）" % (key, minimum, value))
    return value


def _clean_notes(text: str) -> str:
    """去掉表內註記標記（例：3.15[a] → 3.15）。"""
    return re.sub(r"\[[a-z]\]|\[[a-z],[a-z]\]", "", str(text)).strip()


def _parse_nominal_stress(text: str, *, Fu: float | None = None) -> float | None:
    """把表列字串（例如 3.15[a]、0.75Fu[a][c]）轉成數值。"""
    body = _clean_notes(text)
    if not body:
        return None
    if "Fu" in body:
        if Fu is None:
            return None
        m = re.fullmatch(r"([\d.]+)\s*\*?\s*Fu", body)
        if not m:
            return None
        return float(m.group(1)) * Fu
    try:
        return float(body)
    except ValueError:
        return None


class _Refs:
    """已驗證公式／表的呼叫紀錄（含出處與提醒）。"""

    def __init__(self) -> None:
        self.used: list[dict[str, str]] = []
        self.warnings: list[str] = []

    def formula(self, fid: str, inputs: Mapping[str, float]) -> float:
        return float(self.formula_full(fid, inputs)["value"])

    def formula_full(self, fid: str, inputs: Mapping[str, float]) -> Mapping[str, Any]:
        result = V.evaluate(fid, dict(inputs))
        self.used.append(
            {
                "id": fid,
                "src": result["source"]["src"],
                "clause": result["source"]["clause"],
                "page": str(result["source"].get("page") or ""),
                "status": result["status"],
            }
        )
        for message in result.get("warnings") or []:
            if "尚無技師簽認" in message:
                continue
            if message not in self.warnings:
                self.warnings.append("%s：%s" % (fid, message))
        return result

    def table(self, tid: str, row: str, col: str | None = None) -> Any:
        result = V.table(tid, row, col)
        self.used.append(
            {
                "id": tid,
                "src": result["source"]["src"],
                "clause": result["source"]["clause"],
                "page": str(result["source"].get("page") or ""),
                "status": result["status"],
            }
        )
        return result


# ── 斷面性質 ────────────────────────────────────────────────────────────────
def section_properties(section: Mapping[str, Any]) -> dict[str, Any]:
    """由尺寸算 H 型鋼斷面性質（忽略填角，屬理想化斷面）；或直接取使用者輸入的斷面性質。"""
    props: dict[str, Any] = {}
    if section.get("Ag_cm2") is not None:
        need = ("Ag_cm2", "Ix_cm4", "Iy_cm4", "Sx_cm3", "Sy_cm3")
        missing = [k for k in need if section.get(k) is None]
        if missing:
            raise SteelColumnError("指定斷面性質時缺少：%s" % "、".join(missing))
        props.update({k: float(section[k]) for k in need})
        props["Zx_cm3"] = float(section.get("Zx_cm3") or 0.0) or None
        props["Zy_cm3"] = float(section.get("Zy_cm3") or 0.0) or None
        for key in ("h_mm", "b_mm", "tw_mm", "tf_mm"):
            props[key] = float(section.get(key) or 0.0) or None
    else:
        h = _num(section, "h_mm", minimum=1.0)
        b = _num(section, "b_mm", minimum=1.0)
        tw = _num(section, "tw_mm", minimum=0.1)
        tf = _num(section, "tf_mm", minimum=0.1)
        if 2 * tf >= h:
            raise SteelColumnError("翼板厚度過大：2tf 必須小於斷面全深 h")
        hw = h - 2.0 * tf
        props.update(
            {
                "h_mm": h,
                "b_mm": b,
                "tw_mm": tw,
                "tf_mm": tf,
                "Ag_cm2": (2.0 * b * tf + hw * tw) / 100.0,
                "Ix_cm4": (b * h ** 3 - (b - tw) * hw ** 3) / 12.0 / 1.0e4,
                "Iy_cm4": (2.0 * (tf * b ** 3 / 12.0) + hw * tw ** 3 / 12.0) / 1.0e4,
            }
        )
        props["Sx_cm3"] = props["Ix_cm4"] / (h / 20.0)
        props["Sy_cm3"] = props["Iy_cm4"] / (b / 20.0)
        props["Zx_cm3"] = (b * tf * (h - tf) + tw * hw ** 2 / 4.0) / 1000.0
        props["Zy_cm3"] = (2.0 * (tf * b ** 2 / 4.0) + hw * tw ** 2 / 4.0) / 1000.0

    props["rx_cm"] = math.sqrt(props["Ix_cm4"] / props["Ag_cm2"])
    props["ry_cm"] = math.sqrt(props["Iy_cm4"] / props["Ag_cm2"])
    # 扭轉常數 J（薄壁近似）與翹曲常數 Cw（雙對稱 I 型）
    if props.get("h_mm") and props.get("b_mm") and props.get("tw_mm") and props.get("tf_mm"):
        h, b = props["h_mm"], props["b_mm"]
        tw, tf = props["tw_mm"], props["tf_mm"]
        hw = max(h - 2.0 * tf, 0.0)
        props["J_cm4"] = (2.0 * b * tf ** 3 + hw * tw ** 3) / 3.0 / 1.0e4
        props["Cw_cm6"] = props["Iy_cm4"] * ((h - tf) / 10.0) ** 2
    else:
        props["J_cm4"] = float(section.get("J_cm4") or 0.0) or None
        props["Cw_cm6"] = float(section.get("Cw_cm6") or 0.0) or None
    return props


# ── 柱斷面檢核 ──────────────────────────────────────────────────────────────
def classify_section(props: Mapping[str, Any], fy_tf: float, refs: _Refs) -> dict[str, Any]:
    """寬厚比與斷面分類（表4.5-1）；分類僅供對照，不作為通過與否的判斷依據。"""
    info: dict[str, Any] = {"fy_tf_cm2": fy_tf, "notes": []}
    b_mm = props.get("b_mm")
    tf_mm = props.get("tf_mm")
    h_mm = props.get("h_mm")
    tw_mm = props.get("tw_mm")
    ratios = []
    if b_mm and tf_mm:
        ratios.append({"element": "翼板 b/2t（無加勁）", "lambda": (b_mm / 2.0) / tf_mm})
    if h_mm and tw_mm and tf_mm:
        hw = max(h_mm - 2.0 * tf_mm, 0.0)
        ratios.append({"element": "腹板 h/tw（加勁）", "lambda": hw / tw_mm})
    info["ratios"] = ratios
    try:
        table = refs.table("steel99_wide_thickness_T451", "壓力I型翼板")
        info["table_ref"] = "steel99 表4.5-1（%s）" % table["source"]["clause"]
        info["flange_limits"] = table["values"]
        web = refs.table("steel99_wide_thickness_T451", "撓曲加壓力腹板")
        info["web_limits"] = web["values"]
    except Exception as exc:  # pragma: no cover - 表格缺列時不中斷計算
        info["notes"].append("讀取表4.5-1 失敗：%s" % exc)
    info["notes"].append(
        "斷面分類（塑性／結實／半結實／細長）須依表4.5-1 人工確認；"
        "本模組只列出寬厚比供對照，不以分類判定通過與否。"
    )
    return info


def axial_capacity(method: str, props: Mapping[str, Any], fy_tf: float, e_tf: float,
                   klr: float, refs: _Refs) -> dict[str, Any]:
    """軸壓容量：ASD 用 §6.3 之 Fa；LRFD 用 §6.2 之 φcPn。"""
    ag_cm2 = props["Ag_cm2"]
    if method == "asd":
        fa_tf = refs.formula("steel99_Fa_asd", {"Fy": fy_tf, "E": e_tf, "klr": klr})
        pa_tf = fa_tf * ag_cm2
        return {
            "method": "asd",
            "klr": klr,
            "Fa_tf_cm2": fa_tf,
            "Fa_mpa": fa_tf / TF_PER_MPA,
            "Pa_tf": pa_tf,
            "Pa_kN": pa_tf * KN_PER_TF,
            "capacity_tf": pa_tf,
            "capacity_kN": pa_tf * KN_PER_TF,
            "code": "steel99 §6.3（式6.3-1、6.3-2）",
            "formula": "steel99_Fa_asd",
        }
    phi_pn_tf = refs.formula(
        "steel99_Fcr_lrfd", {"Fy": fy_tf, "E": e_tf, "klr": klr, "Ag": ag_cm2}
    )
    return {
        "method": "lrfd",
        "klr": klr,
        "phiPn_tf": phi_pn_tf,
        "phiPn_kN": phi_pn_tf * KN_PER_TF,
        "capacity_tf": phi_pn_tf,
        "capacity_kN": phi_pn_tf * KN_PER_TF,
        "code": "steel99 第六(二)章（式6.2-1～6.2-4，φc=0.85）",
        "formula": "steel99_Fcr_lrfd",
    }


def bending_capacity(method: str, props: Mapping[str, Any], fy_tf: float, e_tf: float,
                     lb_cm: float, m1_over_m2: float, cantilever: bool,
                     rolled: bool, refs: _Refs) -> dict[str, Any]:
    """強軸彎曲容量：ASD 用 §7.2.1（Fb=0.66Fy，Lb ≤ Lc）；LRFD 用 §7.2.2（Mp、Mn）。"""
    out: dict[str, Any] = {"Lb_cm": lb_cm}
    if method == "asd":
        fb_tf = refs.formula("steel99_Fb_compact", {"Fy": fy_tf})
        out.update(
            {
                "Fb_tf_cm2": fb_tf,
                "Fb_mpa": fb_tf / TF_PER_MPA,
                "code": "steel99 §7.2.1（式7.2-1）",
                "formula": "steel99_Fb_compact",
            }
        )
        try:
            lc_cm = refs.formula(
                "steel99_Lc",
                {
                    "bf": props["b_mm"] / 10.0,
                    "d": props["h_mm"] / 10.0,
                    "Af": props["b_mm"] * props["tf_mm"] / 100.0,
                    "Fy": fy_tf,
                },
            )
            out["Lc_cm"] = lc_cm
            out["Lb_le_Lc"] = lb_cm <= lc_cm
            out["formula"] = "steel99_Fb_compact + steel99_Lc"
            if lb_cm > lc_cm:
                out["needs_manual_ltb"] = True
                out["note"] = (
                    "Lb > Lc：§7.2.1 之 Fb=0.66Fy 不適用，須依 §7.2.3 判定或加設側撐；本模組不自行推定。"
                )
        except Exception as exc:
            out["Lc_cm"] = None
            out["Lb_le_Lc"] = None
            out["needs_manual_ltb"] = True
            out["note"] = "讀取 Lc 失敗（%s），須人工確認側向支撐。" % exc
        return out

    z_cm3 = props.get("Zx_cm3")
    if not z_cm3:
        raise SteelColumnError("LRFD 彎曲需要塑性模數 Zx_cm3（請於 section 輸入或提供斷面尺寸）")
    mp = refs.formula("steel99_Mp", {"Fy": fy_tf, "Z": z_cm3})
    out.update({"Mp_tf_cm": mp, "Mp_kNm": mp * KN_PER_TF / 100.0})
    cb_value = refs.formula(
        "steel99_Cb", {"M1": m1_over_m2, "M2": 1.0, "cantilever": 1.0 if cantilever else 0.0}
    )
    out["Cb"] = cb_value
    lp = refs.formula("steel99_Lp_I", {"ry": props["ry_cm"], "Fyf": fy_tf})
    out["Lp_cm"] = lp
    fr_tf = 0.70 if rolled else 1.16
    fl_tf = max(fy_tf - fr_tf, 0.5)
    out["FL_tf_cm2"] = fl_tf
    out["Fr_tf_cm2"] = fr_tf
    if lb_cm <= lp:
        out.update({"Mn_tf_cm": mp, "Mn_kNm": mp * KN_PER_TF / 100.0, "regime": "Lb ≤ Lp（塑性）",
                    "formula": "steel99_Mp + steel99_Lp_I"})
        return out
    j_cm4 = props.get("J_cm4")
    cw_cm6 = props.get("Cw_cm6")
    if not j_cm4 or not cw_cm6:
        out.update(
            {
                "Mn_tf_cm": None,
                "needs_manual_ltb": True,
                "note": "Lb > Lp 需 J 與 Cw 計算 Lr；請提供斷面尺寸（可自動算 J、Cw）或輸入 Zx、J、Cw。",
            }
        )
        return out
    lr_res = refs.formula_full(
        "steel99_Lr_I",
        {
            "ry": props["ry_cm"],
            "Sx": props["Sx_cm3"],
            "E": e_tf,
            "G": G_TF,
            "J": j_cm4,
            "A": props["Ag_cm2"],
            "Iy": props["Iy_cm4"],
            "Cw": cw_cm6,
            "FL": fl_tf,
        },
    )
    lr_cm = float(lr_res["value"])
    mr = float(lr_res["steps"]["Mr"])
    out["Lr_cm"] = lr_cm
    out["Mr_tf_cm"] = mr
    if lb_cm > lr_cm:
        out.update(
            {
                "Mn_tf_cm": None,
                "needs_manual_ltb": True,
                "note": "Lb > Lr：屬彈性側向扭轉挫屈，須依 §7.2.3 判定；本模組不自行推定。",
            }
        )
        return out
    mn = refs.formula(
        "steel99_Mn_lateral",
        {"Cb": cb_value, "Mp": mp, "Mr": mr, "Lb": lb_cm, "Lp": lp, "Lr": lr_cm},
    )
    out.update(
        {
            "Mn_tf_cm": mn,
            "Mn_kNm": mn * KN_PER_TF / 100.0,
            "regime": "Lp < Lb ≤ Lr（彈性側扭）",
            "formula": "steel99_Mp + steel99_Lp_I + steel99_Lr_I + steel99_Mn_lateral",
        }
    )
    return out


def beam_column_interaction(method: str, props: Mapping[str, Any], fy_tf: float, e_tf: float,
                             axial: Mapping[str, Any], bending: Mapping[str, Any],
                             p_tf: float, mx_tf_cm: float, my_tf_cm: float,
                             cm_x: float, cm_y: float, klr_x: float, klr_y: float,
                             refs: _Refs) -> dict[str, Any]:
    """梁柱互制：ASD 用 §8.2 (一) 版；LRFD 用 §8.2 (二) 版式(8.2-1a)(8.2-1b)。"""
    out: dict[str, Any] = {"method": method}
    if method == "asd":
        fa = p_tf / props["Ag_cm2"]
        fbx = mx_tf_cm / props["Sx_cm3"]
        fby = my_tf_cm / props["Sy_cm3"]
        fb_x_tf = bending.get("Fb_tf_cm2")
        if not fb_x_tf:
            raise SteelColumnError("ASD 互制需要 Fb")
        fb_y_tf = fb_x_tf  # 雙對稱 I 型弱軸：採同一容許撓曲應力
        fa_over = fa / axial["Fa_tf_cm2"] if axial.get("Fa_tf_cm2") else 0.0
        lb_cm = bending.get("Lb_cm") or 0.0
        # F'e = 12π²E / [23(KLb/rb)²]：強軸彎曲（fbx）取弱軸挫屈（r_y），
        # 弱軸彎曲（fby）取強軸挫屈（r_x），rb 與對應之 KL/r 須一致。
        fe_x = 12.0 * math.pi ** 2 * e_tf / (23.0 * klr_y ** 2) if klr_y else None
        fe_y = 12.0 * math.pi ** 2 * e_tf / (23.0 * klr_x ** 2) if klr_x else None
        ratios = []
        if fa_over <= 0.15:
            ratio = fa_over + fbx / fb_x_tf + fby / fb_y_tf
            out["equation"] = "式(8.2-3)（fa/Fa ≤ 0.15 之簡化式）"
            ratios.append({"eq": "8.2-3", "ratio": ratio})
        else:
            term_x = cm_x * fbx / ((1.0 - fa / fe_x) * fb_x_tf) if fe_x else 0.0
            term_y = cm_y * fby / ((1.0 - fa / fe_y) * fb_y_tf) if fe_y else 0.0
            ratio1 = fa_over + term_x + term_y
            ratio2 = fa / (0.6 * fy_tf) + fbx / fb_x_tf + fby / fb_y_tf
            out["equation"] = "式(8.2-1)、(8.2-2)"
            ratios.append({"eq": "8.2-1", "ratio": ratio1})
            ratios.append({"eq": "8.2-2", "ratio": ratio2})
        out.update(
            {
                "fa_tf_cm2": fa,
                "fbx_tf_cm2": fbx,
                "fby_tf_cm2": fby,
                "Fb_x_tf_cm2": fb_x_tf,
                "Fb_y_tf_cm2": fb_y_tf,
                "fa_over_Fa": fa_over,
                "Fex_tf_cm2": fe_x,
                "Fey_tf_cm2": fe_y,
                "Cm_x": cm_x,
                "Cm_y": cm_y,
                "klr_x": klr_x,
                "klr_y": klr_y,
                "Fex_note": "F'e = 12π²E/[23(KL/r)²]，強軸彎曲取弱軸挫屈、弱軸彎曲取強軸挫屈",
            }
        )
        out["ratios"] = ratios
        out["ratio"] = max(r["ratio"] for r in ratios)
        out["code"] = "steel99 §8.2（(一) 版）"
        return out

    phi_pn = axial["capacity_tf"]
    mn_x = bending.get("Mn_tf_cm")
    if not mn_x:
        out.update({"ratio": None, "needs_manual": True,
                    "note": "彎曲容量未確定（見 bending.note），無法做 §8.2 互制。"})
        return out
    phi_b_mnx = 0.90 * mn_x
    phi_b_mny = 0.90 * mn_x  # 弱軸採同一斷面之彎曲容量（保守，須人工確認）
    ratio = refs.formula(
        "steel99_PnM_interaction",
        {
            "Pu": p_tf,
            "phiPn": phi_pn,
            "Mux": mx_tf_cm,
            "phiMnx": phi_b_mnx,
            "Muy": my_tf_cm,
            "phiMny": phi_b_mny,
        },
    )
    out.update(
        {
            "ratio": ratio,
            "equation": "式(8.2-1a)/(8.2-1b)",
            "phiPn_tf": phi_pn,
            "phiMnx_tf_cm": phi_b_mnx,
            "phiMny_tf_cm": phi_b_mny,
            "code": "steel99 §8.2（(二) 版，φc=0.85、φb=0.90）",
            "formula": "steel99_PnM_interaction",
        }
    )
    return out


# ── 柱腳基板 ────────────────────────────────────────────────────────────────
def base_plate_bearing(method: str, plate_b_m: float, plate_n_m: float, fc_mpa: float,
                       pedestal_b_m: float | None, pedestal_n_m: float | None,
                       refs: _Refs) -> dict[str, Any]:
    """混凝土承壓（§10.9）：A1 基板承壓面積、A2 支承面上之最大同形面積。"""
    a1_cm2 = plate_b_m * plate_n_m * 1.0e4
    if pedestal_b_m and pedestal_n_m:
        a2_cm2 = min(pedestal_b_m * pedestal_n_m * 1.0e4, 4.0 * a1_cm2)
        a2_source = "墩座頂面積（受 A2/A1 ≤ 4 限制）"
    else:
        a2_cm2 = a1_cm2
        a2_source = "未填墩座尺寸，A2 暫取 A1（無圍束效益，保守）"
    out: dict[str, Any] = {
        "A1_cm2": a1_cm2,
        "A2_cm2": a2_cm2,
        "A2_source": a2_source,
        "fc_mpa": fc_mpa,
    }
    if method == "asd":
        ratio = min(math.sqrt(a2_cm2 / a1_cm2), 2.0)
        fp_mpa = 0.35 * fc_mpa * ratio
        out.update(
            {
                "allowable_mpa": fp_mpa,
                "allowable_kPa": fp_mpa * 1000.0,
                "capacity_kN": fp_mpa * a1_cm2 / 10.0,
                "code": "steel99 §10.9（(一) 版：Fp = 0.35fc′√(A2/A1) ≤ 0.7fc′）",
            }
        )
        return out
    phi_pp_kgf = refs.formula(
        "steel99_concrete_bearing_Pp",
        {"fc": fc_mpa * 10.1972, "A1": a1_cm2, "A2": a2_cm2},
    )
    out.update(
        {
            "allowable_mpa": None,
            "capacity_kN": phi_pp_kgf / 100.0 * KN_PER_TF,
            "code": "steel99 §10.9（(二) 版：φcPp = 0.6×0.85fc′A1√(A2/A1)，φc=0.6）",
            "formula": "steel99_concrete_bearing_Pp",
        }
    )
    return out


def base_plate_thickness(method: str, plate_b_m: float, plate_n_m: float, props: Mapping[str, Any],
                         q_flange_kpa: float, q_web_kpa: float, fy_mpa: float,
                         corrosion_mm: float) -> dict[str, Any]:
    """基板厚度：柱端外伸懸臂法（AISC Design Guide 1 簡化版，我國規範未給公式）。

    取單位板寬之懸臂：載重 q（N/mm²）、懸臂長 l（mm），根部彎矩 m = q·l²/2（N·mm／mm），
    斷面模數 W = t²/6（mm³／mm），故
        ASD  t = √(6m/Fb)，Fb = 0.75Fy
        LRFD t = √(6m/(φbFy))，φb = 0.90（載重已含載重組合係數）

    翼板方向（B 方向）之外伸懸臂以此法檢核；腹板方向（N 方向）因翼板與腹板形成 T 形
    剛架作用，純懸臂法嚴重偏保守，僅列為參考，須依 AISC DG1 之 T 形梁／加勁板法檢核。
    """
    b_mm = props.get("b_mm")
    tw_mm = props.get("tw_mm")
    tf_mm = props.get("tf_mm")
    if not b_mm or not tw_mm or not tf_mm:
        return {"ok": False, "note": "未提供斷面尺寸，無法計算基板厚度需求"}
    l_flange_mm = max(plate_b_m * 1000.0 - b_mm, 0.0) / 2.0
    l_web_mm = max(plate_n_m * 1000.0 - tw_mm, 0.0) / 2.0
    if l_flange_mm <= 0 and l_web_mm <= 0:
        return {"ok": False, "note": "基板尺寸未大於柱斷面，無法計算懸臂長度"}
    q_flange_n_mm2 = q_flange_kpa / 1000.0  # kPa → N/mm²
    q_web_n_mm2 = q_web_kpa / 1000.0
    m_flange = q_flange_n_mm2 * (l_flange_mm ** 2) / 2.0  # N·mm／mm
    m_web = q_web_n_mm2 * (l_web_mm ** 2) / 2.0  # N·mm／mm
    if method == "asd":
        fb_mpa = 0.75 * fy_mpa
        t_flange = math.sqrt(6.0 * m_flange / fb_mpa) if fb_mpa > 0 else None
        t_web = math.sqrt(6.0 * m_web / fb_mpa) if fb_mpa > 0 else None
        basis = "ASD：t = √(6m/Fb)，Fb = 0.75Fy"
    else:
        t_flange = math.sqrt(6.0 * m_flange / (0.90 * fy_mpa)) if fy_mpa > 0 else None
        t_web = math.sqrt(6.0 * m_web / (0.90 * fy_mpa)) if fy_mpa > 0 else None
        basis = "LRFD：t = √(6m/(φbFy))，φb = 0.90（載重已含載重組合係數）"
    return {
        "cantilever_flange_mm": l_flange_mm,
        "cantilever_web_mm": l_web_mm,
        "q_flange_n_mm2": q_flange_n_mm2,
        "q_web_n_mm2": q_web_n_mm2,
        "m_flange_N_mm": m_flange,
        "m_web_N_mm": m_web,
        "required_thickness_flange_mm": t_flange,
        "required_thickness_web_mm": t_web,
        "required_thickness_mm": t_flange,
        "basis": basis,
        "corrosion_allowance_mm": corrosion_mm,
        "note": "翼板方向以單位板寬懸臂法檢核；腹板方向之純懸臂值因未考慮翼板之 T 形梁作用"
                "而偏保守，僅供參考，須依 AISC DG1 之 T 形梁／加勁板法檢核。"
                "懸臂法屬工程慣用方法（非我國鋼構造規範條文）。",
    }


# ── 錨栓群 ──────────────────────────────────────────────────────────────────
def _anchor_group_elastic(positions: Sequence[Mapping[str, float]], p_kn: float,
                           mx_knm: float, my_knm: float) -> dict[str, Any]:
    """彈性錨栓群法（SEAOC Method 1／AISC DG1）：求各錨栓拉力。

        T_i = Mx·y_i/Σy² + My·x_i/Σx² − P/n（一般情形以 2×2 聯立求解）

    假設：基板為剛體、錨栓為彈性、混凝土承受軸力 P 並均勻分佈於全板面積；
    負值表示該錨栓受壓（不需拉力容量），故取 0。
    """
    n = len(positions)
    if n == 0:
        raise SteelColumnError("錨栓位置不得為空")
    xs = [float(p["x_m"]) for p in positions]
    ys = [float(p["y_m"]) for p in positions]
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    det = sxx * syy - sxy * sxy
    p_share = float(p_kn) / n
    if abs(det) > 1e-12:
        # 一般情形：以剛體旋轉相容（δ_i ∝ θx·y_i + θy·x_i）聯立求解
        tensions = []
        for x, y in zip(xs, ys):
            m = ((sxx * mx_knm - my_knm * sxy) * y + (syy * my_knm - sxy * mx_knm) * x) / det
            tensions.append(max(m - p_share, 0.0))
        model = "彈性錨栓群法（SEAOC／AISC DG1，2×2 聯立解）"
    else:
        # 退化（錨栓共線或只有一排）：退化成單軸式
        tensions = []
        if syy > 1e-12:
            for y in ys:
                tensions.append(max(mx_knm * y / syy - p_share, 0.0))
            model = "彈性錨栓群法（單軸，Σxy = 0 之退化情形）"
        elif sxx > 1e-12:
            for x in xs:
                tensions.append(max(my_knm * x / sxx - p_share, 0.0))
            model = "彈性錨栓群法（單軸，Σxy = 0 之退化情形）"
        else:
            raise SteelColumnError("錨栓位置退化（Σx²、Σy² 皆為 0），無法計算錨栓群")
    return {
        "model": model,
        "tensions_kn": tensions,
        "total_tension_kn": sum(tensions),
        "sum_x2": sxx,
        "sum_y2": syy,
        "sum_xy": sxy,
        "axial_share_per_anchor_kn": p_share,
        "note": "錨栓拉力以彈性錨栓群法求得（混凝土視為承受軸力 P 並均勻分佈）；"
                "柱腳實際可能因揚起而僅局部接觸，錨栓剛度與混凝土握裹未計，須人工覆核。",
    }


def _contact_pressure(p_kn: float, moment_knm: float, plate_len_m: float,
                      plate_width_m: float) -> dict[str, Any]:
    """全板線性接觸壓力 q = P/A + M/S（用於揚起判定與峰值承壓檢核）。

    壓力沿彎曲方向線性變化：q_max 在受壓側、q_min 在受拉側；
    q_min < 0 表示該側將離開混凝土（柱腳揚起／搖滾）。
    """
    area = plate_len_m * plate_width_m
    s_mod = plate_width_m * plate_len_m ** 2 / 6.0
    q_mean = float(p_kn) / area if area > 0 else 0.0
    q_edge = abs(float(moment_knm)) * (plate_len_m / 2.0) / s_mod if s_mod > 0 else 0.0
    return {
        "area_m2": area,
        "section_modulus_m3": s_mod,
        "q_mean_kpa": q_mean,
        "q_max_kpa": q_mean + q_edge,
        "q_min_kpa": q_mean - q_edge,
        "uplift": (q_mean - q_edge) < 0.0,
        "note": "全板線性壓力分佈 q = P/A + M/S；揚起側之接觸壓力實為零，本值僅供判定。",
    }


def cone_projected_area(positions: Sequence[Mapping[str, float]], hef_m: float,
                        footprint: tuple[float, float] | None,
                        step_m: float = 0.01) -> dict[str, Any]:
    """45° 應力錐在混凝土面上的投影聯集面積（mm 網格積分，約 ±2%）。"""
    if not positions:
        return {"area_cm2": 0.0, "method": "無錨栓"}
    xs = [float(p["x_m"]) for p in positions]
    ys = [float(p["y_m"]) for p in positions]
    min_x, max_x = min(xs) - hef_m, max(xs) + hef_m
    min_y, max_y = min(ys) - hef_m, max(ys) + hef_m
    if footprint:
        min_x = max(min_x, -footprint[0] / 2.0)
        max_x = min(max_x, footprint[0] / 2.0)
        min_y = max(min_y, -footprint[1] / 2.0)
        max_y = min(max_y, footprint[1] / 2.0)
    if max_x <= min_x or max_y <= min_y:
        return {"area_cm2": 0.0, "method": "應力錐完全被混凝土邊界截斷"}
    nx = max(int((max_x - min_x) / step_m) + 1, 1)
    ny = max(int((max_y - min_y) / step_m) + 1, 1)
    dx = (max_x - min_x) / nx
    dy = (max_y - min_y) / ny
    inside = 0
    for i in range(nx):
        px = min_x + (i + 0.5) * dx
        for j in range(ny):
            py = min_y + (j + 0.5) * dy
            for pos in positions:
                if (px - float(pos["x_m"])) ** 2 + (py - float(pos["y_m"])) ** 2 <= hef_m ** 2:
                    inside += 1
                    break
    area_cm2 = inside * dx * dy * 1.0e4
    return {
        "area_cm2": area_cm2,
        "method": "45° 應力錐聯集（%g mm 網格積分，約 ±2%%）" % (step_m * 1000.0),
        "grid": {"nx": nx, "ny": ny, "dx_m": dx, "dy_m": dy},
    }


def anchor_capacity(method: str, grade: str, fu_tf: float, threads_in_shear_plane: bool,
                    ab_cm2: float, refs: _Refs) -> dict[str, Any]:
    """錨栓鋼材容量：LRFD 用表10.3-2 標稱強度×φ；ASD 用表10.3-2（(一) 版）容許應力。"""
    spec = BOLT_GRADES.get(grade)
    if spec is None:
        raise SteelColumnError("不支援的錨栓材質：%s（可用：%s）" % (grade, "、".join(BOLT_GRADES)))
    out: dict[str, Any] = {"grade": grade, "label": spec["label"], "Ab_cm2": ab_cm2}
    if method == "lrfd":
        row = spec.get("lrfd_row")
        if grade == "F10T" and not threads_in_shear_plane:
            row = spec.get("lrfd_row_no_thread")
        if row:
            table = refs.table("steel99_bolt_strength_T1032", row)
            nominal_t = _parse_nominal_stress(table["values"]["拉力強度Fnt"], Fu=fu_tf)
            nominal_v = _parse_nominal_stress(table["values"]["承壓式剪力強度Fnv"], Fu=fu_tf)
            source = "steel99 表10.3-2（(二) 版，標稱強度；設計值 = φ×表值，φ=0.75）"
        else:
            nominal_t = 0.75 * fu_tf
            nominal_v = (0.40 if threads_in_shear_plane else 0.50) * fu_tf
            source = "steel99 §10.3.3 式(C10.3-1)：Rn = 0.75Ab·Fu；螺牙桿件剪力 0.40Fu／0.50Fu"
        phi = 0.75
        out.update(
            {
                "nominal_tension_tf_cm2": nominal_t,
                "nominal_shear_tf_cm2": nominal_v,
                "design_tension_tf_cm2": phi * nominal_t,
                "design_shear_tf_cm2": phi * nominal_v,
                "tension_capacity_kN": phi * nominal_t * ab_cm2 * KN_PER_TF,
                "shear_capacity_kN": phi * nominal_v * ab_cm2 * KN_PER_TF,
                "source": source,
                "transcribed": False,
            }
        )
        return out

    asd_t = spec.get("asd_Ft")
    asd_v = spec.get("asd_Fv")
    if grade == "F10T" and not threads_in_shear_plane:
        asd_v = spec.get("asd_Fv_no_thread")
    if asd_t is None:
        asd_t = 0.33 * fu_tf
    if asd_v is None:
        asd_v = 0.17 * fu_tf
    out.update(
        {
            "allowable_tension_tf_cm2": asd_t,
            "allowable_shear_tf_cm2": asd_v,
            "tension_capacity_kN": asd_t * ab_cm2 * KN_PER_TF,
            "shear_capacity_kN": asd_v * ab_cm2 * KN_PER_TF,
            "source": "steel99 表10.3-2（(一) 版，容許應力；未入已驗證庫之轉錄值）",
            "transcribed": True,
        }
    )
    return out


def interaction_tension_limit(method: str, grade: str, refs: _Refs) -> dict[str, Any]:
    """拉剪互制（表10.3-3）：回傳 fv → Ft 的函數說明。"""
    if method == "lrfd":
        return {
            "form": "（LRFD）採橢圓互制：(ft/Ft)² + (fv/Fv)² ≤ 1.0（解說圖C10.3-4 之包絡）",
            "source": "steel99 §10.3.4 解說（表10.3-3 為其保守線性化）",
            "elliptical": True,
        }
    row = "A307" if grade == "A307" else ("F10T-in" if grade == "F10T" else None)
    if row is None:
        return {
            "form": "螺牙桿件：ft ≤ 0.33Fu 且 fv ≤ 0.17Fu（表10.3-3 無此材質之列，"
                    "採保守之橢圓互制）",
            "source": "steel99 表10.3-2／表10.3-3",
            "elliptical": True,
        }
    table = refs.table("steel99_bolt_tension_T1033", row)
    column = "螺紋在剪力平面" if row in ("A307", "F10T-in") else "螺紋不在剪力平面"
    text = str(table["values"][column]).split("（")[0].strip()
    return {"form": text, "source": "steel99 表10.3-3", "elliptical": False, "text": text}


def evaluate_interaction(ft_tf: float, fv_tf: float, ft_allow_tf: float,
                          fv_allow_tf: float, form: Mapping[str, Any]) -> dict[str, Any]:
    """以拉剪互制式判定（ft 與 fv 為實際應力）。"""
    if form.get("elliptical"):
        if ft_allow_tf <= 0 or fv_allow_tf <= 0:
            return {"ratio": None, "ok": False, "note": "互制式缺容量值"}
        ratio = math.sqrt((ft_tf / ft_allow_tf) ** 2 + (fv_tf / fv_allow_tf) ** 2)
        return {"ratio": ratio, "ok": ratio <= 1.0, "note": form.get("form")}
    text = str(form.get("text") or "")
    compact = text.replace(" ", "")
    m = re.match(r"^([\d.]+)−([\d.]+)fv(?:≤([\d.]+))?$", compact)
    if m:
        a = float(m.group(1))
        b = float(m.group(2))
        cap = float(m.group(3)) if m.group(3) else None
        limit = min(a - b * fv_tf, cap if cap is not None else a)
        return {"ratio": (ft_tf / limit) if limit > 0 else None, "ok": ft_tf <= limit,
                "limit_tf_cm2": limit, "note": "表10.3-3：%s" % text}
    m = re.match(r"^√\[\(([\d.]+)\)²−([\d.]+)fv²\]$", compact)
    if m:
        a = float(m.group(1))
        b = float(m.group(2))
        inside = a ** 2 - b * fv_tf ** 2
        limit = math.sqrt(inside) if inside > 0 else 0.0
        return {"ratio": (ft_tf / limit) if limit > 0 else None,
                "ok": inside > 0 and ft_tf <= limit,
                "limit_tf_cm2": limit, "note": "表10.3-3：%s" % text}
    return {"ratio": None, "ok": False,
            "note": "互制式無法自動解析：%s（須人工查表10.3-3）" % text}
# ── 主流程 ────────────────────────────────────────────────────────────────────
# 1 MPa = 10.1972 tf/cm²（= 1000 kgf/cm²）；1 kN·m = 10.1972 tf·cm（兩者同係數）
KNM_TO_TF_CM = 10.1972

# 柱腳支承情況與摩擦係數（§10.10.2 與圖C10.10-4）
FRICTION_CASES: dict[str, dict[str, Any]] = {
    "grout_embedded": {"label": "埋置於灌漿內（接觸面埋深大於板厚）", "mu": 0.9},
    "flush": {"label": "接觸面與混凝土表面齊平", "mu": 0.7},
    "grout_pad": {"label": "支承於外灌漿襯墊（接觸面高於混凝土表面）", "mu": 0.55},
}

SHEAR_PATHS: dict[str, str] = {
    "friction": "摩擦（V = μP，(一)版另乘 0.5）",
    "anchors": "錨栓直接抗剪",
    "shear_lug": "剪力榫（僅列檢核提示，須另設計）",
}


def _add_check(checks: list[dict[str, Any]], item: str, value: Any, limit: Any, ok: Any,
               unit: str, relation: str = "le", severity: str | None = None,
               note: str | None = None, code: str | None = None) -> None:
    row: dict[str, Any] = {
        "item": item,
        "value": value,
        "limit": limit,
        "ok": bool(ok) if ok is not None else False,
        "unit": unit,
        "relation": relation,
    }
    if severity:
        row["severity"] = severity
    if note:
        row["note"] = note
    if code:
        row["code"] = code
    checks.append(row)


def analyse(payload: Mapping[str, Any]) -> dict[str, Any]:
    """鋼構柱＋柱腳基板＋基礎螺栓聯合檢核。

    回傳結構：schema／design_method／section／column／base_plate／anchors／
    checks／warnings／references／pass。
    """
    refs = _Refs()
    warnings: list[str] = []

    method = str(payload.get("design_method") or "asd").strip().lower()
    if method not in ("asd", "lrfd"):
        raise SteelColumnError("design_method 必須是 asd（容許應力設計法）或 lrfd（極限設計法）")
    column = payload.get("column") or {}
    base_plate = payload.get("base_plate") or {}
    anchors_in = payload.get("anchors") or {}
    for name, node in (("column", column), ("base_plate", base_plate), ("anchors", anchors_in)):
        if not isinstance(node, Mapping):
            raise SteelColumnError("%s 必須是 JSON 物件" % name)

    # ── 1. 柱斷面與材料 ───────────────────────────────────────────────────
    section_in = column.get("section") or {}
    if not isinstance(section_in, Mapping):
        raise SteelColumnError("column.section 必須是 JSON 物件")
    props = section_properties(section_in)
    fy_mpa = _num(column, "fy_mpa", 245.0, minimum=1.0)
    fu_mpa = _num(column, "Fu_mpa", 400.0, minimum=1.0)
    e_mpa = _num(column, "E_mpa", G_MPA, minimum=10000.0)
    fy_tf = fy_mpa * TF_PER_MPA
    fu_tf = fu_mpa * TF_PER_MPA
    e_tf = e_mpa * TF_PER_MPA
    rolled = bool(column.get("rolled", True))
    cantilever = bool(column.get("cantilever", False))
    length_m = _num(column, "length_m", 3.0, minimum=0.1)
    kx = _num(column, "Kx", 1.0, minimum=0.05)
    ky = _num(column, "Ky", 1.0, minimum=0.05)
    lb_m = _num(column, "Lb_m", length_m, minimum=0.0)
    lb_y_m = _num(column, "Lb_y_m", length_m, minimum=0.0)
    p_kn = _num(column, "axial_P_kN", 0.0)
    mx_knm = _num(column, "moment_Mx_kNm", 0.0)
    my_knm = _num(column, "moment_My_kNm", 0.0)
    vx_kn = abs(_num(column, "shear_Vx_kN", 0.0))
    vy_kn = abs(_num(column, "shear_Vy_kN", 0.0))
    cm_x = _num(column, "Cm_x", 0.85, minimum=0.0)
    cm_y = _num(column, "Cm_y", 0.85, minimum=0.0)
    m1_m2 = _num(column, "M1_over_M2", 1.0, minimum=0.0)

    klr_x = kx * length_m * 100.0 / props["rx_cm"]
    klr_y = ky * length_m * 100.0 / props["ry_cm"]
    klr = max(klr_x, klr_y)

    classification = classify_section(props, fy_tf, refs)

    # ── 2. 柱軸壓／撓曲／梁柱互制 ──────────────────────────────────────────
    axial = axial_capacity(method, props, fy_tf, e_tf, klr, refs)
    tension_capacity_tf: float | None = None
    tension_note: str | None = None
    if p_kn < 0:
        if method == "lrfd":
            tension_capacity_tf = refs.formula(
                "steel99_Pn_tension_yield", {"Fy": fy_tf, "Ag": props["Ag_cm2"]})
        else:
            tension_capacity_tf = 0.66 * fy_tf * props["Ag_cm2"]
            tension_note = "ASD 受拉容量採 0.66Fy·Ag（尚未入已驗證庫之轉錄值），須人工覆核。"
            warnings.append(tension_note)
    bending = bending_capacity(
        method, props, fy_tf, e_tf, lb_m * 100.0, m1_m2, cantilever, rolled, refs)
    p_tf = max(p_kn, 0.0) / KN_PER_TF
    mx_tf_cm = abs(mx_knm) * KNM_TO_TF_CM
    my_tf_cm = abs(my_knm) * KNM_TO_TF_CM
    interaction = beam_column_interaction(
        method, props, fy_tf, e_tf, axial, bending, p_tf, mx_tf_cm, my_tf_cm,
        cm_x, cm_y, klr_x, klr_y, refs)

    # ── 3. 柱腳基板 ───────────────────────────────────────────────────────
    plate_b = _num(base_plate, "plate_B_m", 0.50, minimum=0.05)
    plate_n = _num(base_plate, "plate_N_m", 0.55, minimum=0.05)
    plate_t = _num(base_plate, "plate_t_mm", 32.0, minimum=0.1)
    fc_mpa = _num(base_plate, "fc_mpa", 28.0, minimum=1.0)
    pedestal_b = base_plate.get("pedestal_B_m")
    pedestal_n = base_plate.get("pedestal_N_m")
    pedestal_b = float(pedestal_b) if pedestal_b else None
    pedestal_n = float(pedestal_n) if pedestal_n else None
    corrosion_mm = _num(base_plate, "corrosion_allowance_mm", 0.0, minimum=0.0)
    grout_above = _num(base_plate, "grout_above_concrete", 0.0, minimum=0.0)
    support = str(base_plate.get("support_condition") or "grout_embedded")
    if support not in FRICTION_CASES:
        raise SteelColumnError(
            "base_plate.support_condition 必須是 %s" % "／".join(FRICTION_CASES))
    mu = FRICTION_CASES[support]["mu"]
    bearing = base_plate_bearing(method, plate_b, plate_n, fc_mpa, pedestal_b, pedestal_n, refs)

    # ── 4. 基礎螺栓 ───────────────────────────────────────────────────────
    positions_raw = anchors_in.get("positions") or []
    if not isinstance(positions_raw, (list, tuple)) or not positions_raw:
        raise SteelColumnError("anchors.positions 至少須有一組錨栓座標（x_m、y_m）")
    positions: list[dict[str, float]] = []
    for idx, item in enumerate(positions_raw):
        if not isinstance(item, Mapping):
            raise SteelColumnError("anchors.positions[%d] 必須是 JSON 物件" % idx)
        positions.append({"x_m": _num(item, "x_m"), "y_m": _num(item, "y_m")})
    dia_mm = _num(anchors_in, "diameter_mm", 32.0, minimum=6.0)
    grade = str(anchors_in.get("grade") or "A307")
    if grade not in BOLT_GRADES:
        raise SteelColumnError(
            "不支援的錨栓材質 %s（可用：%s）" % (grade, "、".join(BOLT_GRADES)))
    embed_mm = _num(anchors_in, "embedment_mm", 600.0, minimum=10.0)
    threads_in_shear = bool(anchors_in.get("threads_in_shear_plane", True))
    shear_path = str(anchors_in.get("shear_path") or "friction")
    if shear_path not in SHEAR_PATHS:
        raise SteelColumnError(
            "anchors.shear_path 必須是 %s" % "／".join(SHEAR_PATHS))
    ab_cm2 = math.pi * (dia_mm / 10.0) ** 2 / 4.0
    anchor_fu_tf = float(BOLT_GRADES[grade]["Fu_tf_cm2"])
    anchor_cap = anchor_capacity(method, grade, anchor_fu_tf, threads_in_shear, ab_cm2, refs)

    group = _anchor_group_elastic(positions, max(p_kn, 0.0), abs(mx_knm), abs(my_knm))
    tensions = list(group["tensions_kn"])
    t_total = sum(tensions)
    t_max = max(tensions) if tensions else 0.0

    contact_x = _contact_pressure(max(p_kn, 0.0), abs(mx_knm), plate_b, plate_n)
    contact_y = _contact_pressure(max(p_kn, 0.0), abs(my_knm), plate_n, plate_b)
    q_allow_kpa = (0.35 * fc_mpa if method == "asd" else 0.6 * 0.85 * fc_mpa) * 1000.0

    # 混凝土 45° 應力錐投影面積（受墩座外緣截斷）
    hef_m = embed_mm / 1000.0
    footprint = (pedestal_b, pedestal_n) if (pedestal_b and pedestal_n) else (plate_b, plate_n)
    cone = cone_projected_area(positions, hef_m, footprint)
    fc_tf = fc_mpa * TF_PER_MPA
    at_cm2 = ab_cm2 * len(positions)
    if method == "asd":
        cone_stress_tf = CONE_ALLOW_TENSION_ASD * math.sqrt(fc_tf)
        cone_capacity_tf = cone_stress_tf * cone["area_cm2"]
        cone_demand_tf = anchor_cap["allowable_tension_tf_cm2"] * at_cm2
        cone_basis = "steel99 §10.10.2（(一) 版：0.53√f′c × 有效投影面積 ≥ 錨栓容許拉應力 × At）"
    else:
        cone_stress_tf = CONE_NOMINAL_TENSION_LRFD * math.sqrt(fc_tf)
        cone_capacity_tf = PHI_CONCRETE_CONE * cone_stress_tf * cone["area_cm2"]
        cone_demand_tf = anchor_fu_tf * at_cm2
        cone_basis = "steel99 §10.10.2（(二) 版：φ=0.75×1.06√f′c × 有效投影面積 ≥ Fu × At）"

    # ── 5. 剪力傳遞 ───────────────────────────────────────────────────────
    v_total = math.hypot(vx_kn, vy_kn)
    shear_info: dict[str, Any] = {"path": shear_path, "description": SHEAR_PATHS[shear_path],
                                  "V_total_kN": v_total}
    if shear_path == "friction":
        if method == "lrfd":
            v_allow_tf = refs.formula("steel99_embed_friction_V", {"mu": mu, "P": p_tf})
            v_allow_kn = v_allow_tf * KN_PER_TF
            shear_info["formula"] = "steel99_embed_friction_V"
            shear_info["note"] = "V = μP（(二) 版式10.10-1，μ = %.2f）" % mu
        else:
            v_allow_kn = 0.5 * mu * max(p_kn, 0.0)
            shear_info["note"] = "V = 0.5μP（(一) 版式10.10-1，μ = %.2f）" % mu
    elif shear_path == "anchors":
        v_allow_kn = anchor_cap["shear_capacity_kN"] * len(positions)
        shear_info["note"] = "錨栓直接抗剪：V ≤ Σ(φFnv·Ab)（各錨栓平均分配，實際應考慮偏心）"
    else:
        v_allow_kn = None
        shear_info["note"] = "剪力榫：僅提示，剪力榫本身須另設計與檢核"
    shear_info["capacity_kN"] = v_allow_kn

    # ── 6. 基板厚度 ───────────────────────────────────────────────────────
    q_peak = max(contact_x["q_max_kpa"], contact_y["q_max_kpa"])
    plate_thk = base_plate_thickness(
        method, plate_b, plate_n, props,
        contact_x["q_mean_kpa"], q_peak, fy_mpa, corrosion_mm)

    # ── 7. 檢核項目 ───────────────────────────────────────────────────────
    checks: list[dict[str, Any]] = []
    method_label = "ASD（容許應力設計法，(一) 版）" if method == "asd" else "LRFD（極限設計法，(二) 版）"

    if p_kn >= 0:
        _add_check(checks, "柱軸壓容量（%s）" % axial["code"], p_kn, axial["capacity_kN"],
                   p_kn <= axial["capacity_kN"], "kN", "le")
    else:
        cap_kn = (tension_capacity_tf or 0.0) * KN_PER_TF
        _add_check(checks, "柱受拉容量", abs(p_kn), cap_kn, abs(p_kn) <= cap_kn, "kN", "le",
                   note=tension_note)

    if method == "asd":
        moment_cap_knm = (bending.get("Fb_tf_cm2") or 0.0) * props["Sx_cm3"] / KNM_TO_TF_CM
        _add_check(checks, "強軸撓曲容許應力（§7.2.1）", abs(mx_knm), moment_cap_knm,
                   abs(mx_knm) <= moment_cap_knm, "kN·m", "le",
                   note=bending.get("note"))
    else:
        moment_cap_knm = (bending.get("Mn_tf_cm") or 0.0) * 0.90 / KNM_TO_TF_CM
        _add_check(checks, "強軸撓曲設計強度（§7.2.2，φb=0.90）", abs(mx_knm), moment_cap_knm,
                   abs(mx_knm) <= moment_cap_knm, "kN·m", "le",
                   note=bending.get("note"))

    ratio = interaction.get("ratio")
    _add_check(checks, "梁柱互制（%s）" % interaction.get("equation", "§8.2"), ratio, 1.0,
               ratio is not None and ratio <= 1.0, "-", "le",
               note=interaction.get("note"))

    if p_kn > 0:
        _add_check(checks, "受壓構材長細比 KL/r（§4.4）", klr, 200.0,
                   klr <= 200.0, "-", "le",
                   note="KLx/rx = %.1f、KLy/ry = %.1f" % (klr_x, klr_y))

    # 柱腳混凝土承壓（§10.9）：需求取柱腳反力 C = P + ΣT（錨栓上拉會加重混凝土承壓）
    compression_kn = max(p_kn, 0.0) + t_total
    _add_check(checks, "柱腳混凝土承壓（§10.9）", compression_kn, bearing["capacity_kN"],
               compression_kn <= bearing["capacity_kN"], "kN", "le",
               note="需求 C = P + ΣT = %.1f kN；%s" % (compression_kn, bearing["code"]))

    _add_check(checks, "基板下接觸壓力（q = P/A + M/S）", q_peak, q_allow_kpa,
               q_peak <= q_allow_kpa, "kPa", "le",
               severity="advisory",
               note="容許接觸壓力取 §10.9 全面積支承之值；揚起時此值為線性分佈之外插，"
                    "實際接觸壓力須另以柱腳細部檢核")

    if contact_x["uplift"] or contact_y["uplift"]:
        warnings.append(
            "柱腳接觸壓力分佈於揚起側為負值（Mx 側 q_min = %.1f kPa、My 側 q_min = %.1f kPa）："
            "柱腳將產生揚起／搖滾，須確認柱腳可旋轉（鉸接）或採固定柱腳設計。"
            % (contact_x["q_min_kpa"], contact_y["q_min_kpa"]))

    _add_check(checks, "單支錨栓最大拉力（%s）" % anchor_cap["source"], t_max,
               anchor_cap["tension_capacity_kN"], t_max <= anchor_cap["tension_capacity_kN"],
               "kN", "le", note="錨栓 %s、Ab = %.3f cm²" % (grade, ab_cm2))

    _add_check(checks, "錨栓群合計拉力 vs 混凝土 45° 應力錐", cone_demand_tf,
               cone_capacity_tf, cone_demand_tf <= cone_capacity_tf, "tf", "le",
               note="%s；有效投影面積 %.0f cm²（%s）"
                    % (cone_basis, cone["area_cm2"], cone["method"]))

    if shear_path == "shear_lug":
        _add_check(checks, "剪力傳遞路徑（剪力榫）", v_total, None, True, "kN", "le",
                   severity="advisory", note=shear_info["note"])
    else:
        _add_check(checks, "剪力傳遞（%s）" % shear_path, v_total, v_allow_kn,
                   v_allow_kn is not None and v_total <= v_allow_kn, "kN", "le",
                   note=shear_info["note"])

    # 拉剪互制（表10.3-3）：以最大拉力錨栓為準
    form = interaction_tension_limit(method, grade, refs)
    n_anchor = len(positions)
    v_per_anchor = v_total / n_anchor if n_anchor else 0.0
    ft_tf = (t_max / ab_cm2) / KN_PER_TF if ab_cm2 else 0.0
    fv_tf = (v_per_anchor / ab_cm2) / KN_PER_TF if ab_cm2 else 0.0
    if method == "lrfd":
        ft_allow = anchor_cap["design_tension_tf_cm2"]
        fv_allow = anchor_cap["design_shear_tf_cm2"]
    else:
        ft_allow = anchor_cap["allowable_tension_tf_cm2"]
        fv_allow = anchor_cap["allowable_shear_tf_cm2"]
    inter = evaluate_interaction(ft_tf, fv_tf, ft_allow, fv_allow, form)
    _add_check(checks, "錨栓拉剪互制（%s）" % form.get("source", "§10.3.4"),
               inter.get("ratio"), 1.0, bool(inter.get("ok")), "-", "le",
               note=inter.get("note"))

    if plate_thk.get("required_thickness_mm"):
        available = plate_t - corrosion_mm
        _add_check(checks, "基板厚度（翼板方向懸臂法）", available,
                   plate_thk["required_thickness_flange_mm"],
                   available >= plate_thk["required_thickness_flange_mm"], "mm", "ge",
                   note="%s；%s" % (plate_thk["basis"], plate_thk["note"]))
        _add_check(checks, "基板厚度（腹板方向懸臂值，參考）", available,
                   plate_thk.get("required_thickness_web_mm"),
                   available >= (plate_thk.get("required_thickness_web_mm") or 0.0),
                   "mm", "ge", severity="advisory",
                   note="腹板方向須依 AISC DG1 之 T 形梁／加勁板法檢核，純懸臂值僅供參考")
    else:
        _add_check(checks, "基板厚度（懸臂法）", plate_t, None, False, "mm", "ge",
                   severity="advisory", note=plate_thk.get("note"))

    # 錨栓邊距與埋深（提示性）
    edge_min = min(
        min(plate_b / 2.0 - abs(pos["x_m"]), plate_n / 2.0 - abs(pos["y_m"]))
        for pos in positions
    )
    _add_check(checks, "錨栓至基板邊緣最小距離", edge_min * 1000.0, 1.5 * dia_mm,
               edge_min * 1000.0 >= 1.5 * dia_mm, "mm", "ge", severity="advisory",
               note="1.5db 為工程慣用值，非本規範條文")
    _add_check(checks, "錨栓埋入深度", embed_mm, 5.0 * dia_mm,
               embed_mm >= 5.0 * dia_mm, "mm", "ge", severity="advisory",
               note="5da 為工程慣用值，非本規範條文；實際須以握裹與拉破檢核")

    # 預拉力（表10.3-1，資訊）
    preload_info: dict[str, Any] = {}
    try:
        key = "M%d" % int(round(dia_mm))
        table = refs.table("steel99_bolt_preload_T1031", key)
        preload_tf = float(str(table["values"]["預拉力t"]).replace("[", "").replace("]", ""))
        preload_info = {"size": key, "preload_t": preload_tf,
                        "preload_kN": preload_tf * KN_PER_TF,
                        "source": "steel99 表10.3-1"}
    except Exception:
        preload_info = {"note": "表10.3-1 無此直徑之預拉力（僅 F10T/S10T 有規定）"}

    passed = all(
        bool(c.get("ok")) for c in checks if c.get("severity") != "advisory"
    )
    warnings.extend(refs.warnings)
    if anchor_cap.get("transcribed"):
        warnings.append(
            "ASD 之錨栓容許應力取自表10.3-2（(一) 版）之轉錄值，尚未入已驗證公式庫，須人工覆核。")
    warnings.append(
        "基板厚度採 AISC DG1 簡化懸臂法、錨栓拉力採彈性錨栓群法（SEAOC／AISC DG1），"
        "均非我國鋼構造規範之明文公式；正式設計須由設計技師覆核。")

    return {
        "schema": "civil-steel-column/1",
        "design_method": method,
        "design_method_label": method_label,
        "section": {
            "h_mm": props.get("h_mm"),
            "b_mm": props.get("b_mm"),
            "tw_mm": props.get("tw_mm"),
            "tf_mm": props.get("tf_mm"),
            "Ag_cm2": props["Ag_cm2"],
            "Ix_cm4": props["Ix_cm4"],
            "Iy_cm4": props["Iy_cm4"],
            "Sx_cm3": props["Sx_cm3"],
            "Sy_cm3": props["Sy_cm3"],
            "Zx_cm3": props.get("Zx_cm3"),
            "rx_cm": props["rx_cm"],
            "ry_cm": props["ry_cm"],
            "J_cm4": props.get("J_cm4"),
            "Cw_cm6": props.get("Cw_cm6"),
            "classification": classification,
        },
        "column": {
            "fy_mpa": fy_mpa,
            "Fu_mpa": fu_mpa,
            "E_mpa": e_mpa,
            "rolled": rolled,
            "cantilever": cantilever,
            "length_m": length_m,
            "Kx": kx,
            "Ky": ky,
            "Lb_m": lb_m,
            "Lb_y_m": lb_y_m,
            "klr_x": klr_x,
            "klr_y": klr_y,
            "klr": klr,
            "axial_P_kN": p_kn,
            "moment_Mx_kNm": mx_knm,
            "moment_My_kNm": my_knm,
            "shear_Vx_kN": vx_kn,
            "shear_Vy_kN": vy_kn,
            "Cm_x": cm_x,
            "Cm_y": cm_y,
            "M1_over_M2": m1_m2,
            "axial": axial,
            "bending": bending,
            "interaction": interaction,
            "tension_capacity_kN": (tension_capacity_tf * KN_PER_TF)
            if tension_capacity_tf is not None else None,
        },
        "base_plate": {
            "plate_B_m": plate_b,
            "plate_N_m": plate_n,
            "plate_t_mm": plate_t,
            "fc_mpa": fc_mpa,
            "pedestal_B_m": pedestal_b,
            "pedestal_N_m": pedestal_n,
            "support_condition": support,
            "friction_mu": mu,
            "grout_above_concrete": grout_above,
            "corrosion_allowance_mm": corrosion_mm,
            "bearing": bearing,
            "compression_demand_kN": compression_kn,
            "contact_pressure_x": contact_x,
            "contact_pressure_y": contact_y,
            "thickness": plate_thk,
        },
        "anchors": {
            "grade": grade,
            "grade_label": BOLT_GRADES[grade]["label"],
            "diameter_mm": dia_mm,
            "Ab_cm2": ab_cm2,
            "embedment_mm": embed_mm,
            "threads_in_shear_plane": threads_in_shear,
            "shear_path": shear_path,
            "positions": positions,
            "capacity": anchor_cap,
            "group": group,
            "tensions_kn": tensions,
            "total_tension_kn": t_total,
            "max_tension_kn": t_max,
            "cone": cone,
            "cone_capacity_tf": cone_capacity_tf,
            "cone_demand_tf": cone_demand_tf,
            "cone_basis": cone_basis,
            "shear": shear_info,
            "interaction": inter,
            "preload": preload_info,
        },
        "checks": checks,
        "warnings": warnings,
        "references": refs.used,
        "pass": passed,
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return ("%%.%df" % digits) % value
    return str(value)


def format_report(result: Mapping[str, Any]) -> str:
    """人讀摘要（工作台與 CLI 共用）。"""
    sec = result.get("section") or {}
    col = result.get("column") or {}
    base = result.get("base_plate") or {}
    anc = result.get("anchors") or {}
    lines: list[str] = []
    lines.append("鋼構柱與基礎螺栓檢核（%s）" % result.get("design_method_label", ""))
    lines.append(
        "斷面：Ag = %s cm²、Ix = %s cm⁴、rx = %s cm、ry = %s cm"
        % (_fmt(sec.get("Ag_cm2")), _fmt(sec.get("Ix_cm4"), 1), _fmt(sec.get("rx_cm")),
           _fmt(sec.get("ry_cm"))))
    lines.append(
        "載重：P = %s kN、Mx = %s kN·m、My = %s kN·m、V = %s kN；L = %s m、Kx = %s、Ky = %s"
        % (_fmt(col.get("axial_P_kN")), _fmt(col.get("moment_Mx_kNm")), _fmt(col.get("moment_My_kNm")),
           _fmt((anc.get("shear") or {}).get("V_total_kN")), _fmt(col.get("length_m")),
           _fmt(col.get("Kx")), _fmt(col.get("Ky"))))
    lines.append(
        "柱腳：基板 %s × %s m × %s mm、fc′ = %s MPa、%s（μ = %s）"
        % (_fmt(base.get("plate_B_m")), _fmt(base.get("plate_N_m")), _fmt(base.get("plate_t_mm")),
           _fmt(base.get("fc_mpa")),
           (FRICTION_CASES.get(str(base.get("support_condition"))) or {}).get("label", ""),
           _fmt(base.get("friction_mu"))))
    lines.append(
        "錨栓：%s 支 M%s、埋深 %s mm、剪力路徑 %s"
        % (len(anc.get("positions") or []), _fmt(anc.get("diameter_mm"), 0),
           _fmt(anc.get("embedment_mm"), 0), (anc.get("shear") or {}).get("description", "")))
    lines.append("檢核結果：")
    for check in result.get("checks") or []:
        tag = "OK" if check.get("ok") else "NG"
        if check.get("severity") == "advisory":
            tag = "參考"
        lines.append(
            "  [%s] %s：%s（限 %s %s）"
            % (tag, check.get("item", ""), _fmt(check.get("value")),
               _fmt(check.get("limit")), check.get("unit", "")))
        if check.get("note"):
            lines.append("         註：%s" % check["note"])
    group = anc.get("group") or {}
    if group.get("tensions_kn"):
        lines.append("各錨栓拉力 (kN)：%s"
                     % "、".join(_fmt(t) for t in group["tensions_kn"]))
    lines.append("整體判定：%s" % ("通過" if result.get("pass") else "未通過"))
    warnings = result.get("warnings") or []
    if warnings:
        lines.append("提醒：")
        for message in warnings:
            lines.append("  - %s" % message)
    return "\n".join(lines)


def example_payload(method: str = "lrfd") -> dict[str, Any]:
    """工作台／文件用之範例輸入。"""
    return {
        "design_method": method,
        "column": {
            "section": {"h_mm": 400.0, "b_mm": 300.0, "tw_mm": 13.0, "tf_mm": 22.0},
            "fy_mpa": 245.0,
            "Fu_mpa": 400.0,
            "E_mpa": 206000.0,
            "rolled": True,
            "length_m": 3.0,
            "Kx": 1.0,
            "Ky": 1.0,
            "Lb_m": 3.0,
            "Lb_y_m": 3.0,
            "axial_P_kN": 700.0,
            "moment_Mx_kNm": 280.0,
            "moment_My_kNm": 0.0,
            "shear_Vx_kN": 30.0,
            "shear_Vy_kN": 0.0,
            "Cm_x": 0.85,
            "Cm_y": 0.85,
            "M1_over_M2": 1.0,
            "cantilever": False,
        },
        "base_plate": {
            "plate_B_m": 0.50,
            "plate_N_m": 0.55,
            "plate_t_mm": 32.0,
            "fc_mpa": 28.0,
            "pedestal_B_m": 0.80,
            "pedestal_N_m": 0.85,
            "support_condition": "grout_embedded",
            "grout_above_concrete": 0.0,
            "corrosion_allowance_mm": 0.0,
        },
        "anchors": {
            "positions": [
                {"x_m": -0.19, "y_m": -0.21},
                {"x_m": -0.09, "y_m": -0.21},
                {"x_m": 0.09, "y_m": -0.21},
                {"x_m": 0.19, "y_m": -0.21},
                {"x_m": -0.19, "y_m": 0.21},
                {"x_m": -0.09, "y_m": 0.21},
                {"x_m": 0.09, "y_m": 0.21},
                {"x_m": 0.19, "y_m": 0.21},
            ],
            "diameter_mm": 32.0,
            "grade": "A307",
            "embedment_mm": 900.0,
            "threads_in_shear_plane": True,
            "shear_path": "friction",
        },
    }


# ── 手算對照測試 ─────────────────────────────────────────────────────────────
def selftest() -> dict[str, Any]:
    """手算對照測試：斷面性質、§6.3、§10.9、表10.3-2／10.3-3、應力錐、錨栓群、端到端。"""
    cases: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        cases.append({"name": name, "ok": bool(ok), "detail": detail})

    refs = _Refs()

    # 1. 斷面性質（H400×300×13×22）
    props = section_properties({"h_mm": 400.0, "b_mm": 300.0, "tw_mm": 13.0, "tf_mm": 22.0})
    ok = (abs(props["Ag_cm2"] - 178.28) < 1e-6
          and abs(props["Ix_cm4"] - 52092.7451) < 1e-2
          and abs(props["Iy_cm4"] - 9906.5172) < 1e-2
          and abs(props["Sx_cm3"] - 2604.6373) < 1e-3)
    record("斷面性質 Ag/Ix/Iy/Sx 手算對照", ok,
           "Ag=%.4f（手算 178.28）、Ix=%.4f（手算 52092.7451）、Iy=%.4f（手算 9906.5172）、"
           "Sx=%.4f（手算 2604.6373）"
           % (props["Ag_cm2"], props["Ix_cm4"], props["Iy_cm4"], props["Sx_cm3"]))

    # 2. §6.3 Fa（ASD）：Fy=245 MPa、E=206000 MPa、KL/r=60
    fa = refs.formula("steel99_Fa_asd",
                      {"Fy": 245.0 * TF_PER_MPA, "E": 206000.0 * TF_PER_MPA, "klr": 60.0})
    cc = math.sqrt(2.0 * math.pi ** 2 * (206000.0 * TF_PER_MPA) / (245.0 * TF_PER_MPA))
    ratio = 60.0 / cc
    fa_hand = ((1.0 - 60.0 ** 2 / (2.0 * cc ** 2)) * (245.0 * TF_PER_MPA)
               / (5.0 / 3.0 + 3.0 / 8.0 * ratio - 1.0 / 8.0 * ratio ** 3))
    record("§6.3 容許壓應力 Fa 手算對照", abs(fa - fa_hand) < 1e-9,
           "Fa = %.6f（手算 %.6f tf/cm² = %.3f MPa）" % (fa, fa_hand, fa / TF_PER_MPA))

    # 3. §10.9 混凝土承壓（LRFD）：fc=28 MPa、A1=50×55 cm、A2=80×85 cm
    bearing = base_plate_bearing("lrfd", 0.50, 0.55, 28.0, 0.80, 0.85, refs)
    hand_kgf = (0.6 * 0.85 * (28.0 * 10.1972) * (0.50 * 0.55 * 1e4)
                * min(math.sqrt((0.80 * 0.85 * 1e4) / (0.50 * 0.55 * 1e4)), 2.0))
    got_kgf = bearing["capacity_kN"] / KN_PER_TF * 100.0
    record("§10.9 混凝土承壓 φcPp 手算對照", abs(got_kgf - hand_kgf) < 1.0,
           "φcPp = %.1f kgf（手算 %.1f kgf）＝ %.1f kN"
           % (got_kgf, hand_kgf, bearing["capacity_kN"]))

    # 4. 表10.3-2：A307 極限設計法拉力容量 0.75 × 3.15 × Ab（M32 → Ab = 8.04248 cm²）
    ab32 = math.pi * 3.2 ** 2 / 4.0
    cap = anchor_capacity("lrfd", "A307", 4.20, True, ab32, refs)
    hand_tf = 0.75 * 3.15 * ab32
    record("表10.3-2 A307 拉力容量手算對照",
           abs(cap["design_tension_tf_cm2"] * ab32 - hand_tf) < 1e-9
           and abs(cap["tension_capacity_kN"] - hand_tf * KN_PER_TF) < 1e-6,
           "φFnt·Ab = %.4f tf（手算 %.4f tf）= %.2f kN"
           % (cap["design_tension_tf_cm2"] * ab32, hand_tf, cap["tension_capacity_kN"]))

    # 5. 表10.3-3：A307 之拉剪互制 ft ≤ 1.82 − 1.80fv（且 ≤ 1.40）
    form = interaction_tension_limit("asd", "A307", refs)
    inter = evaluate_interaction(0.80, 0.30, 1.40, 0.70, form)
    record("表10.3-3 A307 拉剪互制手算對照",
           abs((inter.get("limit_tf_cm2") or 0.0) - 1.28) < 1e-9,
           "fv=0.30 → 限值 = 1.82 − 1.80×0.30 = 1.28 tf/cm²（程式 %.4f）"
           % (inter.get("limit_tf_cm2") or 0.0))

    # 6. 單支錨栓 45° 應力錐投影面積 π·hef²（hef = 0.6 m）
    cone1 = cone_projected_area([{"x_m": 0.0, "y_m": 0.0}], 0.60, None)
    hand_area = math.pi * 0.60 ** 2 * 1e4
    record("45° 應力錐投影面積手算對照",
           abs(cone1["area_cm2"] - hand_area) / hand_area < 0.03,
           "單支 %.1f cm²（手算 π·0.6² = %.1f cm²）" % (cone1["area_cm2"], hand_area))

    # 7. 群組聯集面積小於各支相加（0.6 m 間距兩支）
    cone2 = cone_projected_area(
        [{"x_m": 0.0, "y_m": 0.0}, {"x_m": 0.60, "y_m": 0.0}], 0.60, None)
    record("應力錐群組聯集 < 各支相加", cone2["area_cm2"] < 2 * hand_area,
           "群組 %.1f cm² < 2×%.1f = %.1f cm²" % (cone2["area_cm2"], hand_area, 2 * hand_area))

    # 8. 彈性錨栓群法手算對照：M=280 kN·m、P=700 kN、4 支 ±0.19/±0.21
    positions = [{"x_m": -0.19, "y_m": -0.21}, {"x_m": 0.19, "y_m": -0.21},
                 {"x_m": -0.19, "y_m": 0.21}, {"x_m": 0.19, "y_m": 0.21}]
    grp = _anchor_group_elastic(positions, 700.0, 280.0, 0.0)
    syy = 4 * 0.21 ** 2
    hand_t = max(280.0 * 0.21 / syy - 700.0 / 4.0, 0.0)
    record("彈性錨栓群法手算對照",
           abs(max(grp["tensions_kn"]) - hand_t) < 1e-9,
           "T_max = %.4f kN（手算 280×0.21/%.4f − 700/4 = %.4f kN）"
           % (max(grp["tensions_kn"]), syy, hand_t))

    # 9. 全板線性接觸壓力：q = P/A + M/S
    contact = _contact_pressure(700.0, 280.0, 0.50, 0.55)
    hand_qmax = 700.0 / (0.50 * 0.55) + 280.0 * (0.55 / 2.0) / (0.50 * 0.55 ** 2 / 6.0)
    record("全板接觸壓力 q = P/A + M/S 手算對照", abs(contact["q_max_kpa"] - hand_qmax) < 1e-9,
           "q_max = %.2f kPa（手算 %.2f kPa）、q_min = %.2f kPa、揚起 = %s"
           % (contact["q_max_kpa"], hand_qmax, contact["q_min_kpa"], contact["uplift"]))

    # 10. 端到端（ASD 與 LRFD）
    for method in ("asd", "lrfd"):
        payload = example_payload(method)
        try:
            res = analyse(payload)
            failed = [c["item"] for c in res["checks"]
                      if c.get("severity") != "advisory" and not c.get("ok")]
            record("端到端案例（%s）可執行且檢核齊全" % method,
                   not failed and res["pass"],
                   "pass = %s；%d 項檢核；未通過：%s"
                   % (res["pass"], len(res["checks"]), "、".join(failed) if failed else "無"))
        except Exception as exc:  # pragma: no cover - 測試失敗時回報
            record("端到端案例（%s）" % method, False, "例外：%s" % exc)

    failures = [c for c in cases if not c["ok"]]
    return {
        "ok": not failures,
        "total": len(cases),
        "failed": len(failures),
        "cases": cases,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="鋼構柱、柱腳基板與基礎螺栓檢核（steel99 鋼構造建築物鋼結構設計技術規範）")
    parser.add_argument("payload_json", nargs="?", help="輸入 JSON 檔；省略則跑內建範例")
    parser.add_argument("--selftest", action="store_true", help="執行手算對照測試")
    parser.add_argument("--method", choices=("asd", "lrfd"), default="lrfd", help="內建範例之設計法")
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出結果")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.selftest:
        report = selftest()
        for case in report["cases"]:
            print(("ok   " if case["ok"] else "FAIL ") + case["name"])
            print("     " + case["detail"])
        print("\n%d/%d 通過" % (report["total"] - report["failed"], report["total"]))
        return 0 if report["ok"] else 1

    if args.payload_json:
        payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
    else:
        payload = example_payload(args.method)
    result = analyse(payload)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
