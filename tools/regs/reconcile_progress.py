"""對帳「已決定 vs 待處理」：每份規範的 flagged 條文是否都有 verified 條目或 skip 紀錄。

用來回答「還有多少沒做」，而不是看單一的「已處理率」。四個桶互斥：

* **verified**：已有已驗證條目
* **qualitative**：已讀過，確認沒有可參數化的算式或數值表
* **covered**：內容已併入他條
* **out_of_scope**：原文有表／式，但判斷非本工作區用途（**未轉換**）
* **unrecognized**：有內容但無法辨識（＝真缺口，應為 0）
* **NONE**：完全沒有決定（＝待處理）

範例::

    python tools/regs/reconcile_progress.py                 # 全庫總表
    python tools/regs/reconcile_progress.py --src rc112     # 單一規範
    python tools/regs/reconcile_progress.py --only-missing  # 只列還沒有決定的條號
    python tools/regs/reconcile_progress.py --json --save _temp/recon.json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import regq  # noqa: E402
import verified as V  # noqa: E402
import regs_vtool as T  # noqa: E402
from project_paths import temp_dir  # noqa: E402

STATUSES = ["verified", "qualitative", "covered", "out_of_scope", "unrecognized", "NONE"]


def build(src: str | None = None, current_only: bool = True,
          list_status: str | None = None) -> tuple[dict, list]:
    """回傳 ({src: Counter}, 未決清單)。

    「flagged」的定義與 `regs_vtool.status` 一致：文字層有表格標題、公式或方框線
    （`T.kinds(text)` 非空），不是全部條文。否則分母會變成上萬筆而失去意義。
    """
    con = regq.connect()
    f, t = V.load()
    covered = collections.defaultdict(set)
    for x in list(f.values()) + list(t.values()):
        covered[x["src"]].add(str(x["clause"]))
        if x.get("index_clause"):
            covered[x["src"]].add(str(x["index_clause"]))

    skip_file = HERE / "verified" / "_skips.json"
    skips = json.loads(skip_file.read_text(encoding="utf-8"))["items"] if skip_file.exists() else []
    skipd = collections.defaultdict(dict)
    for i in skips:
        skipd[i["src"]][str(i["clause"])] = i

    superseded = set()
    if current_only:
        for r in con.execute("SELECT id, status FROM src"):
            if r["status"] and "取代" in str(r["status"]):
                superseded.add(r["id"])

    rows = con.execute("SELECT src, clause, text FROM unit").fetchall()
    per = collections.defaultdict(collections.Counter)
    missing = []
    for r in rows:
        s, c = r["src"], str(r["clause"])
        if s in superseded:
            continue
        if not T.kinds(r["text"] or ""):
            continue
        if c in covered.get(s, ()):
            per[s]["verified"] += 1
        else:
            st = skipd.get(s, {}).get(c, {}).get("status", "NONE")
            per[s][st] += 1
            if st == "NONE":
                missing.append({"src": s, "clause": c, "status": st})
            elif list_status and st == list_status:
                missing.append({"src": s, "clause": c, "status": st})
    return per, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="對帳已驗證／已決定／待處理的條文數")
    ap.add_argument("--src", help="只看某份規範")
    ap.add_argument("--all-sources", action="store_true",
                    help="包含已被取代的舊版規範（預設只算現行版）")
    ap.add_argument("--only-missing", action="store_true", help="只列出還沒有任何決定的條號")
    ap.add_argument("--list-status", choices=["qualitative", "covered", "out_of_scope", "unrecognized"],
                    help="列出某個 skip 狀態的條號（例如 out_of_scope，用來重產待辦清單）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", help="另存 JSON")
    a = ap.parse_args(argv)

    per, missing = build(a.src, current_only=not a.all_sources, list_status=a.list_status)
    total = collections.Counter()
    for s, row in per.items():
        for k, v in row.items():
            total[k] += v

    if a.json:
        data = {"per_source": {s: dict(c) for s, c in per.items()},
                "total": dict(total), "missing": missing}
        if a.save:
            p = Path(a.save)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0

    if a.only_missing or a.list_status:
        label = a.list_status or "尚無決定"
        print(f"{label} 條文：{len(missing)} 筆")
        cur = None
        for m in missing:
            if m["src"] != cur:
                cur = m["src"]
                print(f"  [{cur}]")
            print(f"    {m['clause']}")
        return 0 if not missing else 1

    head = f"{'規範':<16}" + "".join(f"{h[:9]:>10}" for h in STATUSES) + f"{'合計':>8}"
    print(head)
    print("-" * len(head))
    for s in sorted(per, key=lambda x: -sum(per[x].values())):
        row = per[s]
        print(f"{s:<16}" + "".join(f"{row.get(k, 0):10d}" for k in STATUSES) + f"{sum(row.values()):8d}")
    print("-" * len(head))
    print(f"{'合計':<16}" + "".join(f"{total.get(k, 0):10d}" for k in STATUSES) + f"{sum(total.values()):8d}")

    done = total.get("verified", 0) + total.get("covered", 0)
    alln = sum(total.values()) or 1
    print(f"\n已轉換／已涵蓋：{done}/{alln} = {done / alln:.1%}")
    print(f"真缺口（unrecognized）：{total.get('unrecognized', 0)}；待處理（NONE）：{total.get('NONE', 0)}")
    if missing:
        print(f"※ 有 {len(missing)} 筆沒有決定，用 --only-missing 列出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
