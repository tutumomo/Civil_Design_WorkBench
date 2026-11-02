"""在規範 PDF 中依關鍵字定位頁碼（不再用猜的）。

規範的「條文起頁」與「表／式實際所在頁」經常不同，整本 PDF 的檔序也不等於印刷頁碼。
本工具用文字層關鍵字掃全部頁面，回報命中頁，可再交給 `page_crop.py` 裁圖。

範例::

    # 在某份規範的所有 PDF 裡找「表5.7」出現在第幾頁
    python tools/regs/locate_pages.py hwbridge "表5.7"

    # 指定分章 PDF 與多個關鍵字（任一命中即算）
    python tools/regs/locate_pages.py hwbridge "(9-1)" "9-1)" --part "第九章 鋼結構"

    # 直接給 PDF 檔
    python tools/regs/locate_pages.py --pdf "data/法規/xxx.pdf" "熱彎" "最小曲率半徑"
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from project_paths import REGS_DIR, temp_dir  # noqa: E402
import regq  # noqa: E402  （同目錄；無索引時 _pdfs 會退回檔名搜尋）


def _pdfs(src: str | None, part: str | None, pdf: str | None) -> list[Path]:
    if pdf:
        p = Path(pdf)
        if not p.is_file():
            sys.exit(f"找不到 PDF：{p}")
        return [p]
    if not src:
        sys.exit("請給 src（規範代號）或 --pdf")

    # 索引的 part 欄位存的是 PDF 檔名（分章規範會有很多個），用它去 data/法規 底下找實體檔
    names: list[str] = []
    try:
        con = regq.connect()
        rows = con.execute(
            "SELECT DISTINCT part FROM unit WHERE src=? AND part IS NOT NULL AND part<>''",
            (src,)).fetchall()
        names = [str(r["part"]) for r in rows]
    except Exception as e:  # 沒有索引時退回檔名搜尋
        print(f"（讀索引失敗，改用檔名搜尋）{e}", file=sys.stderr)

    cands: list[Path] = []
    for nm in names:
        if part and part.lower() not in nm.lower():
            continue
        cands += [p for p in REGS_DIR.rglob(nm) if p.is_file()]
    if not cands:  # 退路：data/法規 底下檔名或資料夾名含 src 的 PDF
        for d in sorted(REGS_DIR.glob(f"**/{src}*")):
            if d.is_dir():
                cands += sorted(d.rglob("*.pdf"))
            elif d.suffix.lower() == ".pdf":
                cands.append(d)
        if part:
            low = part.lower()
            cands = [c for c in cands if low in c.stem.lower()]

    seen, out = set(), []
    for c in cands:
        k = str(c.resolve())
        if k not in seen:
            seen.add(k)
            out.append(c)
    if not out:
        sys.exit(f"找不到 PDF：src={src!r} part={part!r}（索引的 part 欄位與 data/法規 底下的檔名對不上）")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用文字層關鍵字定位規範 PDF 的頁碼")
    ap.add_argument("src", nargs="?", help="規範代號（如 hwbridge、rc112）")
    ap.add_argument("keywords", nargs="*", help="關鍵字（任一命中即列出該頁）")
    ap.add_argument("--pdf", help="直接指定 PDF 檔（不給 src 時使用）")
    ap.add_argument("--part", help="只掃檔名含此字串的 PDF（分章規範用）")
    ap.add_argument("--context", type=int, default=60, help="命中處前後字數（預設 60）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（給腳本用）")
    ap.add_argument("--save", help="把結果另存 JSON（預設不存）")
    a = ap.parse_args(argv)

    if not a.keywords:
        sys.exit("請至少給一個關鍵字")

    try:
        import fitz
    except ImportError:
        sys.exit("需要 PyMuPDF：pip install pymupdf")

    results = []
    for pdf in _pdfs(a.src, a.part, a.pdf):
        doc = fitz.open(str(pdf))
        for i, pg in enumerate(doc):
            raw = pg.get_text()
            txt = unicodedata.normalize("NFKC", raw)
            flat = " ".join(txt.split())
            hits = [k for k in a.keywords if unicodedata.normalize("NFKC", k) in flat]
            if not hits:
                continue
            ctx = ""
            if a.context > 0:
                first = unicodedata.normalize("NFKC", hits[0])
                pos = flat.find(first)
                s = max(0, pos - a.context)
                ctx = flat[s:pos + len(first) + a.context]
            results.append({"pdf": str(pdf), "pdf_name": pdf.name,
                            "page": i + 1, "hits": hits, "context": ctx})
        doc.close()

    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0 if results else 1

    if not results:
        print("（0 命中）請確認關鍵字與文字層一致（PDF 可能是掃描件，需 --ocr 或直接裁圖）")
        return 1
    cur = None
    for r in results:
        if r["pdf"] != cur:
            cur = r["pdf"]
            print(f"\n=== {r['pdf_name']}")
        print(f"  p{r['page']:<4} {r['hits']}  …{r['context']}…")
    print(f"\n共 {len(results)} 頁命中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
