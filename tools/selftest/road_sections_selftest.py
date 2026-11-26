r"""道路設計章節自測（item 4）：道路案的報告第 6／7／11 章必須有內容。

為什麼需要這一支
----------------
道路案（category=道路）過去的第 6／7／11 章在報告裡是「需人工補」佔位符：
`report_sections._design_sections()` 只分派 slope／wall／box_culvert／channel，
road 沒有分支。算得出的數量（鋪裝面積、厚度、體積、橫坡）明明在案件檔裡，
卻沒有人把它們寫進報告。

這一支驗三件事：
  1. 道路案能產出第 6／7／11 章，且章節適用（不是佔位符）。
  2. 缺交通量／集水區參數時**明寫需人工補**，不臆測數值。
  3. `intro_by_category`／`hint_by_category` 機制有效：
     道路案不該出現「排水孔直徑 ≥5 cm」這種牆的文案，其他類別也不受影響。

Run:
    .venv/bin/python tools/selftest/road_sections_selftest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/case_package", "tools/report", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import case_core as CC  # noqa: E402
import chapters as CH  # noqa: E402
from report_model import ReportModel  # noqa: E402

FAILS: list[str] = []
ROAD_CASE = ROOT / "cases" / "AC刨鋪5cm工程" / "case.json"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("[1] 道路案可產出第 6／7／11 章")
    case = CC.load(str(ROAD_CASE))
    rep = CC.derive_report(case)
    derived = rep.get("_derived") or {}
    check("derive_report 無錯誤", derived.get("design_sections_error") is None,
          str(derived.get("design_sections_error")))
    for key in ("loads", "stability", "drainage"):
        v = rep.get(key)
        has = isinstance(v, dict) and bool(v.get("items") or v.get("checks"))
        check("第 %s 章有內容" % key, has)
    check("模型為 road", (rep.get("quantities") or {}).get("model") == "road")

    print("[2] 缺交通量／集水區參數時誠實標需人工補（不臆測）")
    loads_notes = " ".join(rep["loads"].get("notes") or [])
    check("載重章說明缺交通量", "須人工補" in loads_notes, loads_notes[:120])
    drain_notes = " ".join(rep["drainage"].get("notes") or [])
    check("排水章說明缺集水區參數", "須人工補" in drain_notes, drain_notes[:120])
    # 不可出現捏造的流量數值（設計流量欄位必為「—」）
    rows = rep["drainage"]["items"][-1]["rows"]
    side = [r for r in rows if "側溝" in str(r[0])]
    check("側溝流量未臆測", bool(side) and str(side[0][1]).strip() == "—",
          str(side))

    print("[3] intro_by_category 機制：道路案不該出現牆的文案")
    model = ReportModel.load(ROAD_CASE, None)
    tpl = json.loads((ROOT / "templates" / "report" / "chapters.json")
                     .read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in tpl["chapters"]}
    for cid in ("loads", "stability", "drainage"):
        chap = by_id[cid]
        alt = CH._pick_for_category(chap.get("intro_by_category"), model)
        check("%s 有道路版 intro" % cid, alt is not None and bool(str(alt).strip()))
        check("%s 預設 intro 仍是原版" % cid, bool(chap.get("intro")))

    # 其他類別不應誤用道路文案
    for cid in ("loads", "stability", "drainage"):
        chap = by_id[cid]
        alt = CH._pick_for_category(chap.get("intro_by_category"), model)
        default = chap.get("intro")
        check("%s 道路版與預設不同" % cid, alt != default)

    print("[4] 非道路類別仍走原 intro（回歸）")
    wall_case = ROOT / "cases" / "擋土牆3m懸臂式" / "case.json"
    if wall_case.exists():
        wmodel = ReportModel.load(wall_case, None)
        wrep = CC.derive_report(CC.load(str(wall_case)))
        check("擋土牆仍有第 6 章", isinstance(wrep.get("loads"), dict)
              and bool(wrep["loads"].get("items")))
        check("擋土牆無 design_sections_error",
              (wrep.get("_derived") or {}).get("design_sections_error") is None)
        for cid in ("loads", "stability", "drainage"):
            alt = CH._pick_for_category(by_id[cid].get("intro_by_category"), wmodel)
            check("擋土牆不套道路 intro（%s）" % cid, alt is None)

    print("")
    if FAILS:
        print("[失敗] %d 項" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("[完成] 道路設計章節自測全數通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
