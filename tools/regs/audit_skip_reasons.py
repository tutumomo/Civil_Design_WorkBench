"""稽核 skip 理由的品質：找出「沒告訴你條文實際寫了什麼」的空泛理由。

背景：skip 理由若寫成「同上型」「純條文：僅規定原則／構造要求」，日後沒有人能判斷
當初讀了什麼、有沒有漏掉公式。2026-11-02 清理 qualitative 時，204 條裡有 46 條其實
含公式、21 條含數值表，就是這種理由造成的。

預設行為**只列出問題，不自動改寫**——因為機器分類會把「章首、符號表與目錄頁」誤判成
「符號定義」，把好的人工判讀蓋成更差的模板文字。正確做法是列出清單，逐條讀過後由人
（或智能體）寫入引用原文的理由。

範例::

    # 列出所有空泛理由（依規範彙總）
    python tools/regs/audit_skip_reasons.py

    # 只看某份規範，並顯示理由全文
    python tools/regs/audit_skip_reasons.py --src rc112 --show

    # 明確要模板草稿（仍建議人工改寫後再 --apply）
    python tools/regs/audit_skip_reasons.py --generate --dry-run --limit 5
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
import regs_vtool as T  # noqa: E402

#: 空泛理由的樣態：沒有引用原文、沒有具體內容描述
WEAK = re.compile(
    r"同上型|僅規定原則|無算式可轉錄|無算式或數值表$|^純條文|^定性條文：?$"
    r"|^(無|略|待補|TODO)|定性規定$"
)


def is_weak(reason: str) -> bool:
    r = (reason or "").strip()
    if len(r) < 12:
        return True
    if "「" in r:          # 已引用原文者視為具體
        return False
    return bool(WEAK.search(r))


def quote(txt: str, n: int = 46) -> str:
    s = re.sub(r"^[\s\-—0-9A-Za-z.()（）、]+", "", txt)
    return re.sub(r"\s+", "", s)[:n]


def draft(src: str, clause: str, txt: str) -> str:
    """產生模板草稿（僅供人工改寫起點，不建議直接套用）。"""
    if not txt:
        return f"條文文字層為空（僅節名或純標題頁），無內容可轉錄。"
    if len(txt) < 40:
        return f"文字層僅有「{quote(txt)}」等節名或殘句（{len(txt)} 字），無可轉錄之算式或數值表。"
    return (f"條文內容為「{quote(txt)}…」（{len(txt)} 字）；逐字確認後補上：這條在講什麼、"
            f"為什麼沒有可參數化的算式或數值表。")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="稽核 skip 理由品質（預設只列清單，不自動改寫）")
    ap.add_argument("--src", help="只看某份規範")
    ap.add_argument("--status", default="all",
                    help="qualitative／covered／out_of_scope／all（預設 all）")
    ap.add_argument("--show", action="store_true", help="顯示理由全文")
    ap.add_argument("--limit", type=int, default=40, help="列出筆數（0＝全部）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", help="另存 JSON 清單")
    ap.add_argument("--generate", action="store_true",
                    help="輸出模板草稿（警告：機器分類不可靠，僅作改寫起點）")
    ap.add_argument("--apply", action="store_true",
                    help="配合 --generate 寫回 _skips.json（強烈建議先 --dry-run 看過）")
    ap.add_argument("--dry-run", action="store_true", help="即使 --apply 也只顯示")
    a = ap.parse_args(argv)

    con = regq.connect()
    f, t = V.load()
    covered = set()
    for x in list(f.values()) + list(t.values()):
        covered.add((x["src"], str(x["clause"])))
        if x.get("index_clause"):
            covered.add((x["src"], str(x["index_clause"])))

    skip_file = HERE / "verified" / "_skips.json"
    items = json.loads(skip_file.read_text(encoding="utf-8"))["items"]

    weak = []
    for it in items:
        src, clause = it["src"], str(it["clause"])
        if a.src and src != a.src:
            continue
        if a.status != "all" and it.get("status") != a.status:
            continue
        if (src, clause) in covered:
            continue
        if not is_weak(it.get("reason", "")):
            continue
        got = con.execute("SELECT text FROM unit WHERE src=? AND clause=?", (src, clause)).fetchall()
        txt = " ".join(unicodedata.normalize("NFKC", r["text"]) for r in got)
        txt = " ".join(txt.split()).strip()
        weak.append({"src": src, "clause": clause, "status": it.get("status"),
                     "reason": it.get("reason", ""), "len": len(txt),
                     "head": txt[:80], "draft": draft(src, clause, txt)})

    per = collections.Counter(w["src"] for w in weak)
    if a.json:
        out = weak
        if a.save:
            p = Path(a.save)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print(f"空泛理由：{len(weak)} 筆" + (f"（{', '.join(f'{k} {v}' for k, v in per.most_common())}）" if per else ""))
    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(weak, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"清單已存 {p}")

    shown = weak if a.limit in (0, None) else weak[:a.limit]
    for w in shown:
        print(f"\n[{w['src']} {w['clause']}]  {w['status']}  ({w['len']} 字)")
        print(f"  理由：{w['reason'][:120]}")
        if a.show:
            print(f"  原文：{w['head']}")
        if a.generate:
            print(f"  草稿：{w['draft']}")
    if len(weak) > len(shown):
        print(f"\n（另有 {len(weak) - len(shown)} 筆未顯示，用 --limit 0）")

    if a.generate and a.apply and not a.dry_run:
        for w in weak:
            T.save_skip(w["src"], w["clause"], w["draft"], w["status"] or "qualitative")
        print(f"\n已套用 {len(weak)} 筆模板草稿（請再跑 regs_vtool.py lint；"
              "並建議人工逐條改成真正的內容描述）")
    elif a.generate:
        print(f"\n（{len(weak)} 筆草稿僅顯示，未寫檔）")
    else:
        print("\n提示：本工具預設不改寫。逐條讀過原文後，用 regs_vtool.save_skip 寫入"
              "「條文內容為『…』…屬某某規定，無可參數化之算式或數值表」這種可驗證的理由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
