# -*- coding: utf-8 -*-
r"""X6　上游載重模組 → `building_frame` 建議值。

本專案沒有地震力、風力、靜活載重的第二套算法（`tools/design/` 只做剛架分析），
但 OCSS 有三個對應的台灣模組：

===================  ==========================  ==========================
模組                 規範                        產出
===================  ==========================  ==========================
`tw-seismic-load`    建築物耐震設計規範 seis113  V、V/W、頂層與一樓橫力
`tw-wind-load`       建築物耐風設計規範 wind103 q(h)、各層風力、V_w、M_w
`tw-dead-live-loads` 建築技術規則建築構造編       D、L、L_red、L_col、U
===================  ==========================  ==========================

用法原則（計畫書 X6）
--------------------
* **只帶入建議值並標明來源**，不自動覆寫使用者輸入。
* 這三個模組本專案沒有第二套算法可核，結果**須由技師確認**後才可進交付。

單位換算（OCSS 用 kgf/m²、tf）
-----------------------------
* 1 kgf/m² = 9.80665/1000 kN/m²
* 1 tf（公噸力）= 9.80665 kN

CLI
---
    python tools/crosscheck/ocss_load_suggest.py suggest --file spec.json \
        [--out out/<案名>/<案名>_載重建議.json]
    python tools/crosscheck/ocss_load_suggest.py merge --file payload.json \
        [--suggest <建議檔>] [--out <合併後的 payload>]

`spec.json` 格式見 `SPEC_EXAMPLE`；`merge` 只補使用者**未填**的欄位，
使用者已填的值一律保留，並在輸出裡標明來源。

需 OCSS 桌面程式開著（無 headless 模式）。本模組不進 `run_all.py` 預設流程；
框架自測用假客戶端（`tools/selftest/ocss_load_suggest_selftest.py`）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT / "tools" / "design"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

KGFM2_TO_KN_M2 = 9.80665 / 1000.0
TF_TO_KN = 9.80665

# 範例輸入（可直接改；數值皆為模板預設值）
SPEC_EXAMPLE = {
    "_note": "上游載重模組輸入。storey_weight_tf 為『每層地震有效重量』"
             "（含靜載重、活動隔間 ≥ 75 kg/m²；倉庫書庫加 1/4 活載重）。",
    "seismic": {
        "S_DS": 0.80, "S_D1": 0.45,
        "n_st": 8, "h_st": 3.5, "W_st": 450,
        "sys": 2, "R_duct": 4.8, "alpha_y": 1.5, "taipei": 0,
    },
    "wind": {
        "V_10": 40.0, "K_zt": 1.0, "GCp": 1.3,
        "n_st": 8, "h_st": 3.5, "B_w": 20,
    },
    "dead_live": {
        "t_s": 0.15, "gam_c": 2400, "w_fin": 100, "w_oth": 60,
        "cat": 1, "L_in": 200, "roof": 1, "A_t": 30, "crowd": 0,
    },
}

# 模組 → 建議欄位對應表。每筆 = (欄位, 取值變數, 換算係數, 來源說明, 備註)
_SUGGEST_SPEC = {
    "tw-dead-live-loads": {
        "title": "靜載重與活載重（建築技術規則建築構造編）",
        "items": [
            ("loads.dead_area_kn_m2", "D", KGFM2_TO_KN_M2,
             "tw-dead-live-loads｜D = 樓版自重 + 面層 + 天花管線隔間",
             "單位 kgf/m² → kN/m²。含樓版自重；梁柱自重由 building_frame 另計，勿重複。"),
            ("loads.live_area_kn_m2", "L", KGFM2_TO_KN_M2,
             "tw-dead-live-loads｜L = 設計活載重（未折減）",
             "單位 kgf/m² → kN/m²。梁端可用折減後 L_red、柱基礎用 L_col，"
             "building_frame 只接受單一值，取未折減 L 較保守。"),
            ("loads.live_reduced_kn_m2", "L_red", KGFM2_TO_KN_M2,
             "tw-dead-live-loads｜L_red = 折減後活載重（第 25 條）",
             "參考值：building_frame 無欄位可帶，僅供技師核對。"),
            ("loads.live_column_kn_m2", "L_col", KGFM2_TO_KN_M2,
             "tw-dead-live-loads｜L_col = 柱與基礎用活載重（第 25 條）",
             "參考值：building_frame 無欄位可帶，僅供技師核對。"),
        ],
    },
    "tw-seismic-load": {
        "title": "地震力（建築物耐震設計規範 seis113）",
        "items": [
            ("loads.base_shear_kn", "V", TF_TO_KN,
             "tw-seismic-load｜V = I/(1.4α_y)·(S_aD/F_u)_m·W（式 2-1～2-3）",
             "單位 tf → kN。W 由使用者給的每層地震有效重量決定；"
             "building_frame 另以自身樓層重量分配橫力，兩者可能不一致，"
             "故另附 base_shear_coefficient 供對照。"),
            ("loads.base_shear_coefficient", "V_W", 1.0,
             "tw-seismic-load｜V/W = 最小設計水平總橫力除以地震有效重量",
             "無因次。若採用此係數，building_frame 會以自己的總重量乘上它，"
             "與 OCSS 的 W 口徑不同，屬近似。"),
            ("loads.seismic_top_force_kn", "F_top", TF_TO_KN,
             "tw-seismic-load｜F_n = F_t + (V − F_t)·w_n·h_n/Σw_i·h_i（式 2-15）",
             "單位 tf → kN。等重等高規則建築下的頂層橫力。"),
            ("loads.seismic_base_force_kn", "F_bot", TF_TO_KN,
             "tw-seismic-load｜F_1 = (V − F_t)·w_1·h_1/Σw_i·h_i（式 2-15）",
             "單位 tf → kN。等重等高規則建築下的一樓橫力。"),
        ],
    },
    "tw-wind-load": {
        "title": "風力（建築物耐風設計規範 wind103full）",
        "items": [
            ("loads.wind_base_shear_kn", "V_w", TF_TO_KN,
             "tw-wind-load｜V_w = ΣF_i（各層風力合計，式 2.6、2.7）",
             "單位 tf → kN。building_frame 以 include_wind=true 帶入。"),
            ("loads.wind_overturning_moment_knm", "M_w", TF_TO_KN,
             "tw-wind-load｜M_w = ΣF_i·z_i（基底傾倒力矩）",
             "單位 tf·m → kN·m。building_frame 不直接用此值，僅供對照。"),
            ("loads.wind_roof_pressure_kgf_m2", "q_h", 1.0,
             "tw-wind-load｜q(h) = 0.06·K(h)·Kzt·(I·V10)^2（式 2.6）",
             "單位 kgf/m²。屋頂高度風速壓。"),
        ],
    },
}

_TPL_INPUT_KEY = {
    "tw-seismic-load": "seismic",
    "tw-wind-load": "wind",
    "tw-dead-live-loads": "dead_live",
}


class LoadSuggestError(RuntimeError):
    """規格或 OCSS 端有問題（環境錯誤另由 ocss_client 拋出）。"""


# --------------------------------------------------------------------- 核心
def _spec_for(spec: dict, tpl: str) -> dict:
    key = _TPL_INPUT_KEY[tpl]
    block = spec.get(key)
    if block is None:
        raise LoadSuggestError("spec 缺 %r 區塊（%s 需要它）" % (key, tpl))
    if not isinstance(block, dict):
        raise LoadSuggestError("spec 的 %r 必須是物件" % key)
    return block


def suggest(client, spec: dict) -> dict:
    """跑三個上游模組，回傳建議值清單（含來源）。不寫入任何使用者資料。"""
    import ocss_template_check as TC

    out = {"suggestions": [], "warnings": [], "inputs": {}}
    for tpl, block in _SUGGEST_SPEC.items():
        src, inv = TC.load_template(tpl)
        inputs = _spec_for(spec, tpl)
        try:
            src, values = TC.apply_inputs(src, inv, inputs)
        except TC.TemplateCheckError as e:
            raise LoadSuggestError("%s 灌值失敗：%s" % (tpl, e)) from None
        ev = client.evaluate(src, values=values or None)
        if ev.get("errorLines"):
            raise LoadSuggestError("%s 計算有錯誤行（%s）；請檢查輸入是否在有效範圍"
                                   % (tpl, ev.get("errorLines")))
        out["inputs"][tpl] = inputs
        for field, var, factor, source, note in block["items"]:
            val = None
            for ln in ev.get("lines", []):
                if ln.get("name") == var and ln.get("type") in ("assignment", "value", "input"):
                    val = ln.get("value")
            if not isinstance(val, (int, float)):
                raise LoadSuggestError("%s 沒有數值輸出 %s" % (tpl, var))
            out["suggestions"].append({
                "field": field,
                "value": float(val) * factor,
                "raw": {"var": var, "value": float(val)},
                "source": source,
                "note": note,
                "template": tpl,
                "group": block["title"],
            })
    out["warnings"].append(
        "本專案無地震力／風力／靜活載重的第二套算法可交叉驗算，"
        "以下數值為 OCSS 單一來源之建議值，須由技師確認後方可採用。")
    out["warnings"].append(
        "模板假設：規則建築、各層等重等高、矩形平面（風力迎風面加背風面）；"
        "臺北盆地工址（taipei=1）模板不支援。")
    return out


# `building_frame` 引擎（BuildingLoads）實際接受的欄位；其餘建議值僅供技師核對，
# 不寫進 payload（引擎會忽略未知鍵，但塞無效欄位會讓 payload 看起來像有效輸入）。
#
# 地震力只帶入**絕對值** `base_shear_kn`（OCSS 依地震有效重量 W 算出的設計基底剪力）；
# 不帶入 V/W 係數——那個係數的分母是 OCSS 的 W 口徑，與 building_frame 自身
# 算出的總重量不同，engine 會用自己的重量乘上它，量級會錯。
_ENGINE_LOAD_FIELDS = (
    "dead_area_kn_m2", "live_area_kn_m2",
    "base_shear_kn",
    "include_wind", "wind_base_shear_kn",
)


def merge_loads(payload: dict, suggestions: list[dict], inputs: dict | None = None) -> dict:
    """把建議值併進 `building_frame` payload：**只補使用者未填的欄位**。

    回傳 {"payload": 新 payload, "applied": [...], "kept": [...], "reference": [...],
    "checks": [...]}。`inputs` 是 suggest() 帶回的各模組輸入，用來檢查
    上游假設（樓層數／樓高）與 payload 的幾何是否一致。
    """
    loads = dict(payload.get("loads") or {})
    applied, kept, reference = [], [], []
    for s in suggestions:
        field = s["field"]
        if not field.startswith("loads."):
            continue
        key = field.split(".", 1)[1]
        if key not in _ENGINE_LOAD_FIELDS:
            reference.append({"field": field, "value": s["value"], "source": s["source"],
                              "note": s.get("note", "")})
            continue
        if key in loads and loads[key] is not None:
            kept.append({"field": field, "user_value": loads[key],
                         "suggested_value": s["value"], "source": s["source"]})
            continue
        loads[key] = s["value"]
        applied.append({"field": field, "value": s["value"], "source": s["source"]})
    if "wind_base_shear_kn" in loads and "include_wind" not in loads:
        loads["include_wind"] = True
        applied.append({"field": "loads.include_wind", "value": True,
                        "source": "本工具：帶入風力時必須開啟風力載重案例"})
    new_payload = dict(payload)
    new_payload["loads"] = loads
    checks = _consistency_checks(payload, inputs or {})
    return {"payload": new_payload, "applied": applied, "kept": kept,
            "reference": reference, "checks": checks}


def _consistency_checks(payload: dict, inputs: dict) -> list[dict]:
    """上游模組的建築假設 vs payload 幾何——不一致要講出來，不要靜默帶入。"""
    out: list[dict] = []
    geom = payload.get("geometry") or {}
    heights = [float(h) for h in (geom.get("storey_heights_m") or [])]
    for tpl in ("tw-seismic-load", "tw-wind-load"):
        blk = inputs.get(tpl) or {}
        n_st, h_st = blk.get("n_st"), blk.get("h_st")
        if n_st is None or h_st is None:
            continue
        if heights:
            if int(n_st) != len(heights):
                out.append({"level": "warn", "template": tpl,
                            "message": "上游假設樓層數 %s 與 payload 的 %d 層不一致"
                                       % (n_st, len(heights))})
            elif any(abs(float(h) - float(h_st)) > 1e-6 for h in heights):
                out.append({"level": "warn", "template": tpl,
                            "message": "上游假設等樓高 %s m，payload 各層樓高 %s 不等高"
                                       % (h_st, [round(h, 3) for h in heights])})
        out.append({"level": "note", "template": tpl,
                    "message": "地震有效重量 W 與基底剪力 V 的口徑是上游模組自訂的；"
                               "building_frame 以自己的樓層重量分配橫力，兩者口徑不同，"
                               "須由技師確認"})
    return out


# --------------------------------------------------------------------- CLI
def _load_json(path: str | None, inline: str | None):
    if inline:
        return json.loads(inline)
    if not path:
        raise SystemExit("需要 --file 或 --json")
    p = Path(path)
    if not p.is_file():
        raise SystemExit("找不到檔案：%s" % path)
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OCSS 上游載重模組 → building_frame 建議值")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("suggest", help="產生建議值")
    p1.add_argument("--file", help="輸入規格 JSON")
    p1.add_argument("--json", dest="inline", help="輸入規格 JSON（直接字串）")
    p1.add_argument("--example", action="store_true", help="用內建範例規格")
    p1.add_argument("--out", help="輸出 JSON（預設印到 stdout）")

    p2 = sub.add_parser("merge", help="把建議值併進 building_frame payload")
    p2.add_argument("--file", help="building_frame payload JSON")
    p2.add_argument("--json", dest="inline", help="building_frame payload JSON（字串）")
    p2.add_argument("--suggest", help="suggest 產出的建議檔")
    p2.add_argument("--out", help="輸出 JSON（預設印到 stdout）")

    args = ap.parse_args(argv)

    if args.cmd == "suggest":
        spec = SPEC_EXAMPLE if args.example else _load_json(args.file, args.inline)
        from ocss_client import OcssClient
        client = OcssClient()
        client.require()
        res = suggest(client, spec)
        txt = json.dumps(res, ensure_ascii=False, indent=2)
        if args.out:
            outp = Path(args.out)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(txt + "\n", encoding="utf-8")
            print("已寫 %s（%d 項建議）" % (outp, len(res["suggestions"])))
        else:
            print(txt)
        return 0

    payload = _load_json(args.file, args.inline)
    if args.suggest:
        res = json.loads(Path(args.suggest).read_text(encoding="utf-8"))
    else:
        from ocss_client import OcssClient
        client = OcssClient()
        client.require()
        res = suggest(client, SPEC_EXAMPLE)
    merged = merge_loads(payload, res["suggestions"], res.get("inputs"))
    merged["warnings"] = res.get("warnings", [])
    txt = json.dumps(merged, ensure_ascii=False, indent=2)
    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(txt + "\n", encoding="utf-8")
        print("已寫 %s（帶入 %d 項、保留使用者輸入 %d 項、參考 %d 項）"
              % (outp, len(merged["applied"]), len(merged["kept"]),
                 len(merged["reference"])))
        for c in merged["checks"]:
            if c["level"] == "warn":
                print("  ⚠ %s" % c["message"])
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
