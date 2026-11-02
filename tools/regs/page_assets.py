"""Page images, PDF table extraction, box-drawing tables and hand-restored formulas for the regs web UI.

Text extracted from PDFs loses formulas (stacked fractions, big brackets) and merges table cells.
Three layers cover that, from most to least reliable:
  1. original page image  (PyMuPDF render of the source PDF page; works for every PDF-backed source)
  2. PDF table -> HTML    (PyMuPDF find_tables; cells holding formula glyphs are replaced by a warning)
  3. formulas.json        (hand-restored LaTeX for sources that only exist as web text, drawn by matplotlib)
Box-drawing tables (┌─┬─┐) from web text are converted to HTML as well.

Everything is rendered on demand and cached under _temp\\regs_pages (safe to delete).
"""
import hashlib
import html
import json
import re
import threading
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REG = ROOT / "data" / "法規"
CACHE = ROOT / "_temp" / "regs_pages"
FORMULAS = HERE / "formulas.json"
DPI = 110

_lock = threading.Lock()  # PyMuPDF documents are not thread-safe

# bracket / brace pieces from the Symbol font: a cell containing them is a typeset formula
PIECE = re.compile("[\uf0e6-\uf0fb]")


# ---------- locate the source PDF ----------

def _bases(file_name):
    base = re.sub(r"\.txt$", "", file_name)
    out = []
    while True:
        out.append(base)
        nb = re.sub(r"_全文(_NFKC)?$", "", base)
        if nb == base:
            break
        base = nb
    return out


def part_pdfs(file_name):
    """All PDFs of a source that is split into parts, as {stem: path}."""
    out = {}
    for base in _bases(file_name):
        d = REG / base
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix.lower() == ".pdf":
                    out.setdefault(f.stem, f)
    return out


@lru_cache(maxsize=None)
def find_pdf(file_name, part):
    """Resolve (source text file, part pdf name) to the PDF path, or None.

    NOTE 2026-11-01: Path.rglob("第五章 基礎") silently returns nothing when the
    name contains a space (Path.glob does match it), which made --part fail on
    every multi-chapter regulation. Never search parts with rglob/glob on the raw
    name: enumerate the PDFs and compare stems. A missing part returns None so the
    caller can fail loudly instead of silently falling back to the wrong PDF.
    """
    if part:
        part = str(part).strip()
        if part.lower().endswith(".pdf"):
            part = part[:-4]
    if not part:
        for base in _bases(file_name):
            p = REG / (base + ".pdf")
            if p.exists():
                return p
        return None
    have = part_pdfs(file_name)
    if not have:
        return None
    if part in have:
        return have[part]
    low = part.lower()
    for stem, f in have.items():
        if stem.lower() == low:
            return f
    for stem, f in have.items():
        if low in stem.lower():
            return f
    return None


@lru_cache(maxsize=16)
def _open(path):
    import fitz
    return fitz.open(str(path))


def page_count(pdf):
    with _lock:
        return len(_open(str(pdf)))


# ---------- page image ----------

def page_png(pdf, page):
    """PNG bytes of a 1-based page; cached on disk."""
    key = hashlib.md5(f"{pdf}|{page}|{DPI}".encode("utf-8")).hexdigest()
    f = CACHE / "img" / f"{key}.png"
    if f.exists():
        return f.read_bytes()
    with _lock:
        doc = _open(str(pdf))
        if not 1 <= page <= len(doc):
            return None
        data = doc[page - 1].get_pixmap(dpi=DPI).tobytes("png")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return data


# ---------- PDF tables -> HTML ----------

def _clean(t):
    from build_index import clean
    return clean(t)


def pdf_tables(pdf, page):
    """[{html, formula}] for tables PyMuPDF finds on the page; formula=True when a cell was withheld."""
    key = hashlib.md5(f"{pdf}|{page}|t".encode("utf-8")).hexdigest()
    f = CACHE / "tbl" / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    out = []
    with _lock:
        doc = _open(str(pdf))
        if 1 <= page <= len(doc):
            for t in doc[page - 1].find_tables().tables:
                rows, flagged = t.extract(), False
                h = ["<table>"]
                for r, row in enumerate(rows):
                    tag = "th" if r == 0 else "td"
                    cells = []
                    for c in row:
                        c = c or ""
                        if PIECE.search(c):
                            flagged = True
                            cells.append(f'<{tag} class="warn">⚠ 此格含公式，請看原頁圖</{tag}>')
                        else:
                            cells.append(f"<{tag}>{html.escape(_clean(c).replace(chr(10), ' ')).strip()}</{tag}>")
                    h.append("<tr>" + "".join(cells) + "</tr>")
                h.append("</table>")
                out.append({"html": "".join(h), "formula": flagged})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------- box-drawing tables (web text) ----------

def _join(parts):
    s = ""
    for p in parts:
        if s and s[-1].isascii() and p[0].isascii() and s[-1].isalnum() and p[0].isalnum():
            s += " "
        s += p
    return s


def _box_to_html(lines):
    rows, cur = [], []
    for ln in lines:
        s = ln.strip()
        if s[:1] in "┌├└":
            if cur:
                rows.append(cur)
            cur = []
        elif s.startswith("│"):
            cur.append([c.strip() for c in s.strip("│").split("│")])
    if cur:
        rows.append(cur)
    grid = []
    for blk in rows:
        n = len(blk[0])
        if any(len(r) != n for r in blk):
            return None
        grid.append([_join([r[i] for r in blk if r[i]]) for i in range(n)])
    if not grid or any(len(r) != len(grid[0]) for r in grid):
        return None
    h = ["<table>"]
    for i, row in enumerate(grid):
        tag = "th" if i == 0 else "td"
        h.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in row) + "</tr>")
    h.append("</table>")
    return "".join(h)


@lru_cache(maxsize=1)
def _manual_tables():
    f = HERE / "tables.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def split_blocks(text, src=None, clause=None):
    """Split clause text into [{t:'text',v} | {t:'table',html,raw}] turning box-drawing tables into HTML."""
    manual = list(_manual_tables().get(src, {}).get(str(clause), [])) if src else []
    lines, blocks, buf, i = text.split("\n"), [], [], 0
    while i < len(lines):
        if lines[i].strip().startswith("┌"):
            j = i
            while j < len(lines) and not lines[j].strip().startswith("└"):
                j += 1
            raw = lines[i:j + 1]
            h = manual.pop(0) if manual else _box_to_html(raw)
            if h:
                if buf:
                    blocks.append({"t": "text", "v": "\n".join(buf)})
                    buf = []
                blocks.append({"t": "table", "html": h, "raw": "\n".join(raw)})
                i = j + 1
                continue
        buf.append(lines[i])
        i += 1
    if buf:
        blocks.append({"t": "text", "v": "\n".join(buf)})
    return blocks


# ---------- hand-restored formulas ----------

@lru_cache(maxsize=1)
def _formulas():
    if FORMULAS.exists():
        return json.loads(FORMULAS.read_text(encoding="utf-8"))
    return {}


def formula_list(src, clause):
    return _formulas().get(src, {}).get(str(clause), [])


def formula_png(src, clause, idx):
    items = formula_list(src, clause)
    if not 0 <= idx < len(items):
        return None
    tex = items[idx]["tex"]
    key = hashlib.md5(tex.encode("utf-8")).hexdigest()
    f = CACHE / "fml" / f"{key}.png"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            fig = plt.figure(figsize=(0.1, 0.1))
            fig.text(0, 0, f"${tex}$", fontsize=18)
            fig.savefig(f, dpi=140, bbox_inches="tight", pad_inches=0.12)
            plt.close(fig)
    return f.read_bytes()


# ---------- find the page of units that carry no page marker (e.g. rc100) ----------

@lru_cache(maxsize=4)
def _page_texts(pdf):
    with _lock:
        doc = _open(str(pdf))
        return [re.sub(r"\s+", "", _clean(pg.get_text())) for pg in doc]


def locate_page(pdf, text):
    """First page whose text contains the opening of the clause body, or None."""
    body = re.sub(r"\s+", "", _clean(text))
    for n in (24, 16, 10):
        key = body[:n]
        if len(key) < 8:
            return None
        hits = [i + 1 for i, t in enumerate(_page_texts(str(pdf))) if key in t]
        if hits:
            return hits[0]
    return None


# ---------- per-clause asset summary ----------

def clause_assets(src_file, rows, next_page_of):
    """For each row (dict with part/page) return the PDF pages to offer, or [] when no PDF exists."""
    out = []
    for r in rows:
        pdf = find_pdf(src_file, r["part"] or "")
        if not pdf:
            out.append(None)
            continue
        p0 = r["page"] or locate_page(pdf, r["text"])
        if not p0:
            out.append(None)
            continue
        nxt = next_page_of(r) if r["page"] else p0 + 1
        last = max(p0, min(nxt or p0, p0 + 3))
        n = page_count(pdf)
        out.append({"pages": [p for p in range(p0, last + 1) if p <= n]})
    return out


# ---------- MinerU auto-recognition drafts (see mineru_import.py) ----------

_auto_cache = {}


def auto_page(src, part, page):
    """{html, warn} draft for one PDF page, or None."""
    f = HERE / "auto" / f"{src}.json"
    if not f.exists():
        return None
    m = f.stat().st_mtime
    if _auto_cache.get(src, (0, None))[0] != m:
        _auto_cache[src] = (m, json.loads(f.read_text(encoding="utf-8")))
    return _auto_cache[src][1].get(f"{part or ''}|{page}")
