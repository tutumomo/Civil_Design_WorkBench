r"""X6 上游載重模組建議值工具自測（不需 OCSS 桌面程式；模板灌值用磁碟上的盤點資料，
數值計算以假客戶端取代）。

驗證：spec 缺區塊報錯、模板灌值可用、三個模組的建議欄位與單位換算、
`merge_loads` 只補未填欄位（使用者已填的不覆寫）、參考值不寫進 payload、
帶入風力時自動開 `include_wind`。

Run:
    .venv/bin/python tools/selftest/ocss_load_suggest_selftest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/crosscheck", "tools/design", "tools/regs"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import ocss_load_suggest as LS  # noqa: E402
import ocss_template_check as TC  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def raises(fn) -> bool:
    try:
        fn()
    except LS.LoadSuggestError:
        return True
    return False


class FakeClient:
    """evaluate() 回傳預先排好的變數值（不真的算）。"""

    def __init__(self, values: dict, error_lines: int = 0):
        self.values = values
        self.error_lines = error_lines
        self.calls: list[dict] = []

    def evaluate(self, source, values=None):
        self.calls.append({"source": source, "values": values})
        if self.error_lines:
            return {"errorLines": self.error_lines, "lines": []}
        lines = [{"type": "assignment", "name": k, "value": v, "unit": None}
                 for k, v in self.values.items()]
        return {"errorLines": 0, "lines": lines, "uc": None, "passes": None}


def main() -> int:
    print("[1] spec 與模板灌值")
    check("spec 缺區塊報錯", raises(lambda: LS.suggest(FakeClient({}), {"seismic": {}})))
    for tpl, key in LS._TPL_INPUT_KEY.items():
        spec = {key: LS.SPEC_EXAMPLE[key]}
        src, inv = TC.load_template(tpl)
        try:
            TC.apply_inputs(src, inv, spec[key])
            ok = True
            detail = ""
        except TC.TemplateCheckError as e:
            ok, detail = False, str(e)
        check("範例 spec 可灌進 %s" % tpl, ok, detail)

    print("[2] 建議值與單位換算")
    vals = {"D": 520.0, "L": 200.0, "L_red": 172.8, "L_col": 172.8,
            "V": 256.2385958208479, "V_W": 0.0711773877280133,
            "F_top": 68.82870263524083, "F_bot": 6.693210470914537,
            "V_w": 78.04348894009601, "M_w": 1331.2612431367381,
            "q_h": 130.73405222771802}
    client = FakeClient(vals)
    res = LS.suggest(client, LS.SPEC_EXAMPLE)
    got = {s["field"]: s["value"] for s in res["suggestions"]}
    check("三個模組都有建議值", len(res["suggestions"]) == 11, str(len(res["suggestions"])))
    check("kgf/m² → kN/m² 換算正確",
          abs(got["loads.dead_area_kn_m2"] - 520.0 * 9.80665 / 1000.0) < 1e-9,
          str(got.get("loads.dead_area_kn_m2")))
    check("tf → kN 換算正確",
          abs(got["loads.base_shear_kn"] - 256.2385958208479 * 9.80665) < 1e-6,
          str(got.get("loads.base_shear_kn")))
    check("無因次 V/W 不換算",
          abs(got["loads.base_shear_coefficient"] - 0.0711773877280133) < 1e-12)
    check("每項都有來源說明",
          all(s["source"] for s in res["suggestions"]))
    check("警告提到須技師確認",
          any("技師" in w for w in res["warnings"]), str(res["warnings"]))
    check("OCSS 報錯行時拋例外",
          raises(lambda: LS.suggest(FakeClient({}, error_lines=2), LS.SPEC_EXAMPLE)))

    print("[3] merge：只補未填欄位")
    payload = {"geometry": {"x_grid_m": [0.0, 6.0], "storey_heights_m": [3.5, 3.5, 3.5]},
               "loads": {"dead_area_kn_m2": 5.0}}
    merged = LS.merge_loads(payload, res["suggestions"], res["inputs"])
    loads = merged["payload"]["loads"]
    check("使用者已填的值不覆寫", loads["dead_area_kn_m2"] == 5.0, str(loads))
    check("未填的欄位被帶入", "live_area_kn_m2" in loads and "base_shear_kn" in loads)
    check("不帶入 V/W 係數（口徑不同）", "base_shear_coefficient" not in loads, str(loads))
    check("帶入風力時自動開 include_wind", loads.get("include_wind") is True, str(loads))
    check("參考值不寫進 payload", "live_reduced_kn_m2" not in loads, str(loads))
    check("參考值另列", len(merged["reference"]) == 7, str(len(merged["reference"])))
    check("使用者已填者列入 kept", len(merged["kept"]) == 1, str(merged["kept"]))
    check("原始 payload 未被就地改動", payload["loads"] == {"dead_area_kn_m2": 5.0})
    warns = [c for c in merged["checks"] if c["level"] == "warn"]
    check("樓層數不一致會提出警告", any("樓層數" in c["message"] for c in warns),
          str(merged["checks"]))
    merged2 = LS.merge_loads(
        {"geometry": {"storey_heights_m": [3.5] * 8}}, res["suggestions"], res["inputs"])
    check("樓層數一致時無樓層數警告",
          not any("樓層數" in c["message"] for c in merged2["checks"]))

    print("[4] 對 building_frame 引擎可跑")
    import design_api as D
    ex = next(r["example"] for r in D.list_calculators() if r["id"] == "building_frame")
    ex = json.loads(json.dumps(ex))
    ex["loads"] = {k: v for k, v in merged["payload"]["loads"].items()
                   if k in ("dead_area_kn_m2", "live_area_kn_m2",
                            "base_shear_kn", "include_wind", "wind_base_shear_kn")}
    run = D.run_calculation("building_frame", ex)
    # 只要求「引擎沒有因輸入／計算失敗而中止」；ok=False 是設計判定 NG（正常）。
    check("引擎接受帶入後的 payload（無 error）",
          run.get("error") is None and run.get("result") is not None,
          json.dumps(run)[:300])

    print()
    if FAILS:
        print("FAIL %d 項：%s" % (len(FAILS), "、".join(FAILS)))
        return 1
    print("全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
