r"""X5 逐式計算書工具自測（不需 OCSS 桌面程式；用假客戶端與磁碟上的模板盤點資料）。

驗證：輸入值內嵌（literal／prompt／choice 三種）、未知欄位報錯、
公式型案例來源、建置流程（假客戶端）、報告側的 `load_crosscheck` 讀檔。

Run:
    .venv/bin/python tools/selftest/ocss_calcbook_selftest.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/crosscheck", "tools/design", "tools/regs", "tools/report"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import ocss_calcbook as CB  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class FakeClient:
    """假 OCSS 客戶端：evaluate 回固定結果，專案操作只記錄。"""

    def __init__(self):
        self.saved_as = None
        self.newed = False
        self.sheets: list[dict] = []
        self.removed: list[str] = []

    def evaluate(self, source, values=None):
        return {"errorLines": 0, "lines": [], "uc": 0.5, "passes": True}

    def project(self):
        return {"sheets": list(self.sheets), "projectName": "x"}

    def project_new(self, force=False):
        self.newed = True
        self.sheets = []
        return {}

    def project_set_name(self, name):
        return {}

    def sheet_add_source(self, source, name=None):
        sid = "sid-%d" % (len(self.sheets) + 1)
        self.sheets.append({"id": sid, "name": name, "source": source})
        return {"id": sid}

    def sheet_evaluate(self, sid):
        return {"uc": 0.5, "passes": True}

    def project_save_as(self, path):
        self.saved_as = str(path)
        return {}

    def sheet_remove(self, sid):
        self.removed.append(sid)
        self.sheets = [s for s in self.sheets if s["id"] != sid]
        return {}


def main() -> int:
    print("[1] 輸入值內嵌")
    import ocss_template_check as TC

    src, inv = TC.load_template("tw-isolated-footing")
    baked = CB.bake_inputs(src, inv, {"fc_in": 28.0, "B_f": 2500.0, "D_f": 0.0})
    check("prompt 型：?{預設} 整段換掉", "?{28}" not in baked and "28.0" in baked)
    check("prompt 型：單位註記保留", "*(MPa)" in baked, baked[:200])
    check("prompt 型：不再出現 {預設}", "{28}" not in baked)

    src2, inv2 = TC.load_template("tw-backwater-profile")
    baked2 = CB.bake_inputs(src2, inv2, {"b_w": 0.4, "y_0": 0.62})
    check("literal 型：改寫那一行", "b_w = 0.4'" in baked2, baked2[:300])
    check("literal 型：其他常數不動", "n_m = 0.015'" in baked2)

    src3, inv3 = TC.load_template("tw-rc-beam")
    baked3 = CB.bake_inputs(src3, inv3, {"support_type": 1, "n_t": 5})
    check("choice 型：選單後補賦值", "support_type = 1" in baked3)
    check("choice 型：選單本體保留", "@select support_type" in baked3)
    check("choice 型：數字型輸入仍內嵌", "n_t = 5" in baked3)

    print("[2] 錯誤處理")
    try:
        CB.bake_inputs(src, inv, {"nope": 1})
        check("未知欄位報錯", False)
    except Exception as e:
        check("未知欄位報錯", "沒有輸入欄位" in str(e) or "模板" in str(e), str(e))

    print("[3] 公式型案例")
    src4, origin = CB._case_source({"type": "formula", "source": ["a = 1 m", "b = a"]})
    check("formula 型來源", "a = 1 m" in src4 and origin == "手寫公式鏈")

    print("[4] 建置流程（假客戶端）")
    client = FakeClient()
    with tempfile.TemporaryDirectory() as td:
        try:
            summary = CB.build(client, Path(td), project_name="測試", compare=False)
            ok = True
            detail = ""
        except CB.CalcbookError as e:
            ok, detail = False, str(e)
        check("建置完成", ok, detail)
        if ok:
            check("專案檔名正確",
                  summary["project_file"].endswith("測試_逐式計算書.ifccalculation"),
                  summary["project_file"])
            check("有案例", summary["case_count"] > 0,
                  str(summary["case_count"]))
            check("另存新檔有呼叫", client.saved_as is not None)
            check("結果 JSON 已產生",
                  (Path(td) / "測試_交叉驗算結果.json").is_file())

    print("[5] 報告側讀檔")
    from report_model import ReportModel

    with tempfile.TemporaryDirectory() as td:
        js = Path(td) / "cc.json"
        js.write_text(json.dumps({
            "project_file": "/tmp/x.ifccalculation",
            "case_count": 2, "item_count": 3, "failed": 1, "handled": 1,
            "results": [{
                "name": "案例一", "items": [
                    {"name": "項一", "ours": 1.0, "ocss": 1.0, "unit": "m",
                     "rel": 0.0, "status": "pass", "disposition": None},
                    {"name": "項二", "ours": 2.0, "ocss": 2.1, "unit": "kN",
                     "rel": 0.05, "status": "handled",
                     "disposition": {"kind": "explained", "reason": "模型不同"}},
                ],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        model = ReportModel.__new__(ReportModel)
        model.crosscheck = []
        model.crosscheck_meta = {}
        n = model.load_crosscheck(js)
        check("讀到 2 項", n == 2, str(n))
        check("處置理由保留",
              model.crosscheck[1]["reason"] == "模型不同", str(model.crosscheck[1]))
        check("meta 帶入", model.crosscheck_meta["case_count"] == 2)
        model2 = ReportModel.__new__(ReportModel)
        model2.crosscheck = []
        model2.crosscheck_meta = {}
        check("檔案不存在回 0", model2.load_crosscheck(Path(td) / "no.json") == 0)

    print()
    if FAILS:
        print("FAIL %d 項：%s" % (len(FAILS), "、".join(FAILS)))
        return 1
    print("全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
