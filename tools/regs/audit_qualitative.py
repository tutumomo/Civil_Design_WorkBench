"""稽核「定性（qualitative）」判定：把可能藏著公式或數值表的條文揪出來。

背景：本專案把每條法規條文分流成 verified（已轉錄）／qualitative（確無算式或表）／
covered／out_of_scope。過去多次發現 qualitative 這桶不可信——2026-11-02 實測 204 條
低分段裡還有 46 條公式、21 張表。原因是「行內未編號公式」在短條文裡密度不高，被
啟發式規則判成沒內容。

**打分只決定閱讀順序，不能當成「無內容」的結論**：分數低的一定要真的讀過。

範例::

    # 列出所有 qualitative 條文，依可疑度排序（前 40 筆）
    python tools/regs/audit_qualitative.py

    # 只看某份規範、門檻 5 分以下、輸出 JSON
    python tools/regs/audit_qualitative.py --src rc112 --max-score 5 --json

    # 把清單存下來，逐條讀完再回報
    python tools/regs/audit_qualitative.py --save _temp/audit.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import regq  # noqa: E402
import verified as V  # noqa: E402
from project_paths import temp_dir  # noqa: E402

#: 式號樣式：(8-13)、(9.4-1)、式7.5-2 …（含全形括號）
TAG = re.compile(r"[（(]\s*[A-Za-z]?\d+(?:\.\d+)*\s*[-－]\s*\d+[a-zA-Z]?\s*[)）]|式\s*[（(]?\d")
OPS = re.compile(r"[=＝≤≥≦≧<>]")
NUM = re.compile(r"\d+\.\d+")
TBL = re.compile(r"表\s*[0-9A-Z][0-9A-Za-z\-.]*")


def score(txt: str) -> tuple[float, dict]:
    tags = len(set(TAG.findall(txt)))
    ops = len(OPS.findall(txt))
    nums = len(NUM.findall(txt))
    tabs = len(set(TBL.findall(txt)))
    s = tags * 5 + min(ops, 20) + min(nums, 20) * 0.5 + tabs * 2
    return s, {"tags": tags, "ops": ops, "nums": nums, "tables": tabs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="稽核 qualitative 判定（依可疑度排序）")
    ap.add_argument("--src", help="只看某份規範代號")
    ap.add_argument("--min-score", type=float, default=None, help="只列出分數 ≥ 此值者")
    ap.add_argument("--max-score", type=float, default=None, help="只列出分數 < 此值者（找漏網之魚）")
    ap.add_argument("--limit", type=int, default=40, help="列出筆數（預設 40；0＝全部）")
    ap.add_argument("--text-width", type=int, default=60, help="顯示條文前 n 字")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--save", help="另存 JSON 清單")
    a = ap.parse_args(argv)

    con = regq.connect()
    f, t = V.load()
    covered = collections.defaultdict(set)
    for x in list(f.values()) + list(t.values()):
        covered[x["src"]].add(str(x["clause"]))
        if x.get("index_clause"):
            covered[x["src"]].add(str(x["index_clause"]))

    sk = json.loads((HERE / "verified" / "_skips.json").read_text(encoding="utf-8"))["items"]
    rows = []
    for i in sk:
        if i["status"] != "qualitative":
            continue
        src, clause = i["src"], str(i["clause"])
        if a.src and src != a.src:
            continue
        if clause in covered.get(src, ()):
            continue
        got = con.execute("SELECT text FROM unit WHERE src=? AND clause=?", (src, clause)).fetchall()
        txt = " ".join(unicodedata.normalize("NFKC", r["text"]) for r in got)
        txt = " ".join(txt.split())
        s, detail = score(txt)
        if a.min_score is not None and s < a.min_score:
            continue
        if a.max_score is not None and s >= a.max_score:
            continue
        rows.append({"src": src, "clause": clause, "score": round(s, 1),
                     "len": len(txt), **detail, "reason": i.get("reason", ""),
                     "text": txt})
    rows.sort(key=lambda r: -r["score"])

    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已存 {len(rows)} 筆 → {p}", file=sys.stderr)

    per = collections.Counter(r["src"] for r in rows)
    print(f"qualitative 且尚無 verified 條目：{len(rows)} 筆"
          + (f"（{', '.join(f'{k} {v}' for k, v in per.most_common())}）" if per else ""))
    print("提示：分數只反映『公式訊號密度』，行內未編號公式（2R+T≧64、D=146√(Q/V)）會偏低分，")
    print("      所以低分段仍必須逐條讀過才能判定 qualitative。\n")

    shown = rows if a.limit in (0, None) else rows[:a.limit]
    if a.json:
        print(json.dumps(shown, ensure_ascii=False, indent=1))
        return 0
    print(f"{'分數':>6} {'式':>3} {'運算':>4} {'表':>3} {'小數':>4}  {'src':<14} {'clause':<14} 條文前 {a.text_width} 字")
    for r in shown:
        head = r["text"][:a.text_width].replace("\n", " ")
        print(f"{r['score']:6.1f} {r['tags']:3d} {r['ops']:4d} {r['tables']:3d} {r['nums']:4d}  "
              f"{r['src']:<14} {r['clause']:<14} {head}")
    if len(rows) > len(shown):
        print(f"\n（另有 {len(rows) - len(shown)} 筆未顯示，用 --limit 0 全部列出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
