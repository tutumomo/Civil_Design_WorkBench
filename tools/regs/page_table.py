"""Read a regulation page as a coordinate grid (no human eyes needed).

  grid <src> <clause|--page N> [--part P] [--ocr] [--y A:B] [--png]

Prints every text row with its y (pt, top-down); cells are split at the page's own
vertical rules so a table can be transcribed cell by cell.
--ocr also runs Windows built-in OCR on the same rendered page (layout cross-check
only: OCR mangles digits, never take numbers from it).
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))


def load_pdf(src, clause, part, page_no):
    import page_assets as P
    import regq
    con = regq.connect()
    row = con.execute("SELECT file FROM src WHERE id=?", (src,)).fetchone()
    if not row:
        sys.exit("no such src: " + src)
    pdf = P.find_pdf(row[0], part)
    if pdf is None and not part:
        cand = P.part_pdfs(row[0])
        prefer = [v for k, v in cand.items() if "基準" in k or "內文" in k or "本文" in k]
        pdf = prefer[0] if prefer else (list(cand.values())[0] if cand else None)
    if pdf is None and part:
        have = P.part_pdfs(row[0])
        sys.exit("part not found: %r; available: %s" % (part, sorted(have)))
    if pdf is None:
        sys.exit("no PDF for %s (web-only source) - transcribe from the web text" % src)
    if page_no:
        return P, pdf, [page_no]
    pages = []
    for r in regq.get_clause(con, src, clause):
        pdf = P.find_pdf(row[0], r["part"] or "")
        if not pdf:
            continue
        p0 = r["page"] or P.locate_page(pdf, r["text"])
        if p0:
            pages.append(p0)
    return P, pdf, pages


def v_rules(page):
    xs = []
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) < 1.2 and abs(p1.y - p2.y) > 6:
                    xs.append(round(p1.x, 1))
            elif item[0] == "re":
                r = item[1]
                if r.width < 3 and r.height > 6:
                    xs.append(round(r.x0, 1))
    out = []
    for x in sorted(set(xs)):
        if out and x - out[-1] < 2.0:
            continue
        out.append(x)
    return out


def rows_of(page):
    buckets = defaultdict(list)
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        buckets[round((y0 + y1) / 2 / 3.0)].append((x0, x1, text))
    return [(k * 3.0, sorted(buckets[k])) for k in sorted(buckets)]


def fmt_row(words, cuts):
    if not cuts:
        return " ".join(t for _, _, t in words)
    cells = defaultdict(list)
    for x0, x1, text in words:
        idx = 0
        while idx < len(cuts) and (x0 + x1) / 2 > cuts[idx]:
            idx += 1
        cells[idx].append((x0, text))
    parts = []
    for i in sorted(cells):
        parts.append(" ".join(t for _, t in sorted(cells[i])))
    return " | ".join(parts)


def math_lines(page):
    """Rebuild lines with superscripts/subscripts marked, using span size and baseline."""
    out = []
    d = page.get_text("dict")
    for blk in d.get("blocks", []):
        for ln in blk.get("lines", []):
            spans = [sp for sp in ln.get("spans", []) if sp.get("text", "").strip()]
            if not spans:
                continue
            sizes = {}
            for sp in spans:
                sizes[round(sp["size"], 1)] = sizes.get(round(sp["size"], 1), 0) + len(sp["text"])
            base_size = max(sizes, key=sizes.get)
            base_y = None
            for sp in spans:
                if round(sp["size"], 1) == base_size:
                    base_y = sp["origin"][1]
                    break
            parts = []
            for sp in spans:
                t = sp["text"]
                sz = round(sp["size"], 1)
                y = sp["origin"][1]
                if base_y is None or (abs(y - base_y) < 1.2 and sz >= base_size - 0.3):
                    parts.append(t)
                elif y < base_y - 1.2 and sz <= base_size + 0.2:
                    parts.append("^{" + t.strip() + "}")
                elif y > base_y + 1.2 and sz <= base_size + 0.2:
                    parts.append("_{" + t.strip() + "}")
                else:
                    parts.append(t)
            out.append((round(ln["bbox"][1], 1), "".join(parts)))
    out.sort(key=lambda r: r[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("clause", nargs="?", default="")
    ap.add_argument("--part", default="")
    ap.add_argument("--page", type=int)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--y", default="")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--math", action="store_true", help="rebuild lines with ^{}/_{} marks")
    a = ap.parse_args()
    P, pdf, pages = load_pdf(a.src, a.clause, a.part, a.page)
    if not pages:
        sys.exit("page not found")
    import fitz
    doc = fitz.open(str(pdf))
    for p in pages:
        page = doc[p - 1]
        print("=== %s p.%d  %.0f x %.0f pt ===" % (Path(str(pdf)).name, p, page.rect.width, page.rect.height))
        cuts = v_rules(page)
        print("vertical rules x =", cuts)
        ylo, yhi = 0.0, 1e9
        if a.y:
            ylo, yhi = [float(t) for t in a.y.split(":")]
        if a.math:
            for y, line in math_lines(page):
                if not (ylo <= y <= yhi):
                    continue
                print("%6.1f  %s" % (y, line))
            continue
        for y, words in rows_of(page):
            if not (ylo <= y <= yhi):
                continue
            print("%6.1f  %s" % (y, fmt_row(words, cuts)))
        look = ROOT / "_temp" / "regs_pages" / "look"
        if a.png:
            look.mkdir(parents=True, exist_ok=True)
            f = look / ("%s_%s_p%d.png" % (a.src, (a.clause or "pg").replace("/", "_"), p))
            f.write_bytes(P.page_png(pdf, p))
            print("png:", f)
        if a.ocr:
            look.mkdir(parents=True, exist_ok=True)
            png = look / ("ocr_%s_p%d.png" % (a.src, p))
            png.write_bytes(P.page_png(pdf, p))
            ps = ROOT / "_temp" / "ocr" / "ocr.ps1"
            if ps.exists():
                import subprocess
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                    "-File", str(ps), str(png)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                print("--- OCR (layout only) ---")
                print((r.stdout or "").strip()[:2500])


if __name__ == "__main__":
    main()
