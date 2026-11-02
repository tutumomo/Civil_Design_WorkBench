"""設計引擎 ``--selftest`` 的共用比對工具（僅測試用，不參與設計計算）。

每個引擎的手算對照都長成這樣::

    def selftest() -> int:
        from _selftest_util import Checker
        c = Checker("擋土牆穩定")
        c.close("Ka", r["Ka"], math.tan(math.radians(30.0 / 2)) ** 2)
        return c.run()

``close`` 用相對誤差比對，``true`` 檢查布林條件；任一項失敗時回傳 1。
"""

from __future__ import annotations


class Checker:
    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[bool, str]] = []

    def close(self, name: str, got: float, want: float, tol: float = 1e-6) -> None:
        got = float(got)
        want = float(want)
        ok = abs(got - want) <= tol * max(1.0, abs(want))
        self.rows.append((ok, "%s：%.6g（手算 %.6g）" % (name, got, want)))

    def true(self, name: str, condition: bool, detail: str = "") -> None:
        self.rows.append((bool(condition), name + ("；" + detail if detail else "")))

    def run(self) -> int:
        print("手算對照：%s" % self.title)
        for ok, message in self.rows:
            print("%s %s" % ("ok  " if ok else "FAIL", message))
        passed = sum(1 for ok, _ in self.rows if ok)
        print("\n%d/%d 通過" % (passed, len(self.rows)))
        return 0 if passed == len(self.rows) else 1
