"""Turn MinerU middle_json output into per-page auto-recognition drafts for the regs web UI.

MinerU (basic tier, run from the venv under _temp/mineru_test) turns a PDF page into blocks: text with inline
LaTeX, display equations and HTML tables.  Its output has real errors (14,000 read as 14.000, units
changed), so this importer never feeds the clause index.  It writes tools/regs/auto/<src>.json:
    {"<part>|<page>": {"html": "...", "warn": ["numbers not in the PDF text layer", ...]}}
The UI shows it collapsed under the original page image, labelled 「自動辨識草稿（未核對）」.

usage: python -E -P -X utf8 mineru_import.py <src id> <middle_json> [<part pdf name>]
"""
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "auto"
SKIP = {"page_number", "header", "footer", "aside_text"}
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _inline(items):
    out = []
    for x in items:
        t = x.get("type")
        c = x.get("content", "")
        if t == "equation_inline":
            out.append(f"${html.escape(c)}$")
        else:
            out.append(html.escape(str(c)))
    return "".join(out)


def _block(b, nums):
    t, c = b.get("type"), b.get("content")
    if t in SKIP:
        return ""
    if t in ("table", "image", "chart", "code", "algorithm"):
        parts = []
        for x in c if isinstance(c, list) else []:
            parts.append(_block(x, nums))
        return f'<div class="mu-{t}">' + "".join(parts) + "</div>" if any(parts) else ""
    if t == "table_body":
        c = re.sub(r"<eq>(.*?)</eq>", lambda m: "$" + html.escape(html.unescape(m.group(1))) + "$", c or "", flags=re.S)
        nums.append(re.sub(r"<[^>]+>", " ", c))
        return c
    if t == "image_body" or t == "chart_body":
        return '<div class="mu-note">［圖形，請看原頁圖］</div>'
    if t == "equation":
        s = c if isinstance(c, str) else _inline(c or [])
        nums.append(s)
        return f'<div class="mu-eq">$${html.escape(s)}$$</div>' if isinstance(c, str) else f"<p>{s}</p>"
    if isinstance(c, list):
        s = _inline(c)
        nums.append(re.sub(r"<[^>]+>", " ", s))
    else:
        s = html.escape(str(c or ""))
        nums.append(s)
    if not s.strip():
        return ""
    tag = "h4" if t in ("paragraph_title", "doc_title", "title") else "p"
    return f"<{tag}>{s}</{tag}>"


def _numbers(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d)\s+(?=[\d.,])|(?<=[.,])\s+(?=\d)", "", text)
    return {m.group(0).strip(",") for m in NUM.finditer(text)}


def build(src, jpath, part=""):
    from page_assets import find_pdf, _page_texts
    import sqlite3
    con = sqlite3.connect(HERE.parent.parent / "data" / "法規" / "_regs_index.sqlite")
    fname = con.execute("SELECT file FROM src WHERE id=?", (src,)).fetchone()[0]
    pdf = find_pdf(fname, part)
    ptexts = _page_texts(str(pdf))
    d = json.load(open(jpath, encoding="utf-8"))
    res = {}
    for p in d["pages"]:
        pg = p["page_idx"] + 1
        nums = []
        body = "".join(_block(b, nums) for b in p.get("blocks", []))
        if not body.strip():
            continue
        ref = re.sub(r"\s+", "", ptexts[pg - 1]) if pg <= len(ptexts) else ""
        bad = sorted(n for n in _numbers(" ".join(nums)) if len(n) > 1 and n not in ref)
        warn = []
        if bad:
            warn.append("下列數字無法在 PDF 文字層核對（可能辨識錯誤，例如千分位被讀成小數點）：" + "、".join(bad[:10]))
        res[f"{part}|{pg}"] = {"html": body, "warn": warn}
    OUT.mkdir(exist_ok=True)
    f = OUT / f"{src}.json"
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    old.update(res)
    f.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    return len(res), sum(1 for v in res.values() if v["warn"])


if __name__ == "__main__":
    n, w = build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    print(f"{sys.argv[1]}: {n} pages, {w} with number warnings")
