r"""需求單（requirements）與追溯矩陣自測（item 5）。

為什麼需要這一支
----------------
`civil-case/1` 過去只描述「做了什麼」，沒有描述「案子要求什麼」，
需求與交付物之間的落差沒有任何機制可以指出來。

這一支驗四件事：
  1. requirements 是**選填**區塊：沒有它時全案行為完全不變（既有 12 個案例不受影響）。
  2. 格式錯誤（缺 id／缺 text／id 重複／satisfied_by 非清單）會被擋。
  3. 追溯鏈條指不到實際存在的東西時，強制需求會被擋（error），建議事項只 warn。
  4. 追溯矩陣能正確標出「已滿足／未滿足／不適用」三態。

Run:
    .venv/bin/python tools/selftest/requirements_selftest.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/case_package", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import case_core as CC  # noqa: E402
import requirements as RQ  # noqa: E402

FAILS: list[str] = []
BASE = ROOT / "cases" / "擋土牆3m懸臂式" / "case.json"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _base():
    return copy.deepcopy(json.loads(BASE.read_text(encoding="utf-8")))


def _errors(case):
    return [i["msg"] for i in CC.consistency(case) if i["level"] == "error"]


def main() -> int:
    print("[1] requirements 是選填：沒有它時行為不變")
    base = _base()
    check("無 requirements 不報錯", not RQ.validate(base))
    tr = RQ.trace(base)
    check("無 requirements 追溯為空", tr["rows"] == [])

    print("[2] 格式錯誤被擋")
    bad = _base()
    bad["requirements"] = {"items": [
        {"text": "缺 id"},
        {"id": "R-01", "text": ""},
        {"id": "R-01", "text": "id 重複"},
        {"id": "R-02", "text": "ok", "satisfied_by": "不是清單"},
    ]}
    msgs = " ".join(i["msg"] for i in RQ.validate(bad))
    check("缺 id 被擋", "缺 id" in msgs, msgs[:160])
    check("缺 text 被擋", "缺 text" in msgs, msgs[:160])
    check("id 重複被擋", "重複" in msgs, msgs[:160])
    check("satisfied_by 非清單被擋", "必須是清單" in msgs, msgs[:160])

    print("[3] 追溯鏈條指不到 → 強制需求被擋")
    case = _base()
    case["requirements"] = {
        "source": "測試",
        "items": [{
            "id": "R-01", "text": "須提供排水孔配置圖", "origin": "§1",
            "kind": "drawing", "mandatory": True,
            "satisfied_by": [{"type": "drawing", "ref": "不存在的圖.dxf"}],
            "evidence": "有證據但圖不存在",
        }],
    }
    errs = " ".join(_errors(case))
    check("強制需求指不到 → error", "尚未滿足" in errs, errs[:200])

    case2 = copy.deepcopy(case)
    case2["requirements"]["items"][0]["mandatory"] = False
    errs2 = " ".join(_errors(case2))
    check("建議事項不擋交件", "尚未滿足" not in errs2, errs2[:200])

    print("[4] 缺 evidence 也不算已滿足")
    case3 = _base()
    case3["requirements"] = {
        "source": "測試",
        "items": [{
            "id": "R-01", "text": "牆頂高程限制", "mandatory": True,
            "satisfied_by": [{"type": "boq_item", "ref": "03"}],
        }],
    }
    errs3 = " ".join(_errors(case3))
    check("缺 evidence → error", "尚未滿足" in errs3, errs3[:200])

    print("[5] 可追溯的需求判為已滿足")
    case4 = _base()
    case4["requirements"] = {
        "source": "測試",
        "items": [{
            "id": "R-01", "text": "牆身混凝土量須與數量表一致", "mandatory": True,
            "satisfied_by": [{"type": "calculation", "ref": "section_area_m2"},
                             {"type": "boq_item", "ref": "03"}],
            "evidence": "數量表與 S-01 斷面積乘長度相符",
        }],
    }
    tr4 = RQ.trace(case4)
    check("狀態為 satisfied", tr4["rows"][0]["status"] == "satisfied",
          str(tr4["rows"][0]))
    check("兩個追溯標的都找得到",
          all(t["found"] for t in tr4["rows"][0]["targets"]),
          str(tr4["rows"][0]["targets"]))
    md = RQ.matrix_markdown(tr4)
    check("Markdown 有表格", md.startswith("|") and "已滿足" in md, md[:120])

    print("[6] 派生報告含追溯矩陣")
    rep = CC.derive_report(case4)
    req = rep.get("requirements") or {}
    check("report.requirements 有 items", bool(req.get("items")))
    check("report.requirements 有 markdown", bool(req.get("markdown")))

    print("")
    if FAILS:
        print("[失敗] %d 項" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("[完成] 需求單與追溯矩陣自測全數通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
