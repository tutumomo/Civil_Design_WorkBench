r"""template 型交叉驗算框架自測（X1）：不需要 OCSS 桌面程式（以假客戶端取代）。

驗證：灌值改寫（prompt／literal 兩種）、未知欄位報錯、路徑取值、容差與倒數、
差異處置規則（無處置＝失敗、處置須三選一且附理由）、模板雜湊檢查。

Run:
    .venv/bin/python tools/selftest/ocss_template_check_selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/crosscheck", "tools/design", "tools/regs"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import ocss_template_check as TC  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def raises(fn) -> bool:
    try:
        fn()
    except TC.TemplateCheckError:
        return True
    return False


class FakeClient:
    """evaluate() 回傳固定的 OCSS 結果。"""

    def __init__(self, lines, uc_values=None):
        self.lines, self.uc_values = lines, uc_values or {}

    def evaluate(self, source, values=None):
        return {"lines": self.lines, "ucValues": self.uc_values, "uc": 0.5,
                "passes": True, "errorLines": 0}


def main() -> int:
    inv = {"templateId": "t", "inputs": [{"name": "H"}], "literal_inputs": [{"name": "B"}]}
    src = "H = ?{5.0}', x\nB = 0.60'm <i>寬</i>\n"
    print("[1] 灌值")
    s2, vals = TC.apply_inputs(src, inv, {"H": 6.0, "B": 1.25})
    check("prompt 型進 values", vals == {"H": 6.0})
    check("literal 型改寫 source 該行", "B = 1.25'm" in s2 and "B = 0.60" not in s2, s2)
    check("prompt 型不改 source", "?{5.0}" in s2)
    check("未知欄位報錯", raises(lambda: TC.apply_inputs(src, inv, {"Z": 1})))
    check("literal 行不存在報錯",
          raises(lambda: TC.apply_inputs("nothing", inv, {"B": 1})))

    print("[2] 取值")
    run = {"result": {"Ka": 0.3, "geometry": {"H": 5.0}, "checks": [
        {"item": "滑動（常時）", "value": 2.0}]}, "checks": []}
    check("點號巢狀", TC.get_ours(run, "result.geometry.H")[0] == 5.0)
    check("check: 以字串比對 item", TC.get_ours(run, "check:滑動")[0] == 2.0)
    check("路徑不存在報錯", raises(lambda: TC.get_ours(run, "result.nope")))
    ev = {"lines": [{"type": "assignment", "name": "a", "value": 1.0, "unit": "m"},
                    {"type": "assignment", "name": "a", "value": 2.0, "unit": "m"}],
          "ucValues": {"UC_sl": 0.5}}
    check("var: 取最後一次賦值", TC.get_ocss(ev, "var:a") == (2.0, "m"))
    check("uc: 取 ucValues", TC.get_ocss(ev, "uc:UC_sl")[0] == 0.5)
    check("OCSS 缺變數報錯", raises(lambda: TC.get_ocss(ev, "var:zzz")))

    print("[3] 容差與處置")
    import design_api as D  # noqa: F401  (run_case 內部會用)
    base = {"calculator": "hydrology", "payload": {"example": True},
            "template": "tw-retaining-wall", "ocss_inputs": {}}
    # 借用 hydrology 的範例結果當「本專案」數值：取 result 中任一數值欄位
    ours_run = D.run_calculation("hydrology", next(
        r["example"] for r in D.list_calculators() if r["id"] == "hydrology"))
    path, val = next((("result." + k), v) for k, v in ours_run["result"].items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool) and v)
    out: list[str] = []

    def run_one(theirs, **kw):
        out.clear()
        cmp_ = {"name": "x", "ours": path, "ocss": "var:v", "tol": {"rel": 0.01}}
        cmp_.update(kw)
        client = FakeClient([{"type": "assignment", "name": "v", "value": theirs}])
        return TC.run_case(client, dict(base, compare=[cmp_]), emit=out.append)

    r = run_one(val)
    check("相同值通過", r == {"total": 1, "failed": 0, "handled": 0})
    r = run_one(val * 1.005)
    check("容差內通過", r["failed"] == 0)
    r = run_one(val * 1.5)
    check("超差且無處置＝失敗", r["failed"] == 1 and r["handled"] == 0)
    r = run_one(val * 1.5, disposition={"kind": "explained", "reason": "定義不同"})
    check("超差有處置＝已處置，不算失敗但計數", r["failed"] == 0 and r["handled"] == 1)
    r = run_one(val * 1.5, disposition={"kind": "explained", "reason": " "})
    check("處置沒寫理由＝失敗", r["failed"] == 1)
    r = run_one(val * 1.5, disposition={"kind": "放寬容差", "reason": "x"})
    check("處置種類不在三選一＝失敗", r["failed"] == 1)
    r = run_one(1.0 / val, reciprocal=True)
    check("reciprocal 取倒數", r["failed"] == 0)

    print("[4] 模板雜湊")
    check("缺盤點資料報錯", raises(lambda: TC.load_template("tw-不存在")))
    src_t, inv_t = TC.load_template("tw-retaining-wall")
    check("真實模板可載入且有 prompt 輸入", bool(inv_t["inputs"]) and "H_wall" in src_t)

    print()
    if FAILS:
        print("✗ 失敗 %d 項：%s" % (len(FAILS), "；".join(FAILS)))
        return 1
    print("✓ template 型交叉驗算框架自測全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
