#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""印刷頁碼 → PDF 頁碼 對照表工具。

背景
----
多份規範的 PDF 檔是「印刷版掃描／排版」，其 PDF 實體頁序與頁面上印的
「印刷頁碼」不一致（例：公路路線設計規範 PDF 第 44 頁，頁面印的是「3-17」；
公路排水設計規範 PDF 第 132 頁，頁面印的是「-110-」）。先前人工抓頁時因此
反覆抓錯頁（每一次 pending 條目的待核原因幾乎都是「目標式子在下一頁」）。

本工具的作法
------------
1. 逐頁取出該 PDF 的文字層（page_assets._page_texts）。
2. 在每頁文字的**開頭**與**結尾**各找一次「頁碼標記」token。
3. 把辨識到的印刷頁碼 → PDF 頁序建成索引，存成 JSON 快取。
4. 提供查詢：某規範的某印刷頁碼落在哪個 PDF 第幾頁。

頁碼 token 的樣式（依各規範不同，已用正規式一併涵蓋）
    3-17        3-17     10-17    4-151   5-19    18-18   9-1     7-11
    -110-       -110-    -65-     -20-    附錄-20
    A1-2        C-8      1-1      2-2
（純數字頁碼如「46」「313」只在前後文有線索時才認，避免把內文數字誤判為頁碼。）

用法
----
    python -E -P -X utf8 tools/regs/page_index.py build <src> [--part <章本>]
    python -E -P -X utf8 tools/regs/page_index.py show  <src> [--part <章本>]
    python -E -P -X utf8 tools/regs/page_index.py find  <src> <印刷頁碼> [--part <章本>]
    python -E -P -X utf8 tools/regs/page_index.py all

注意：--part 省略時會掃描此規範「所有章本 PDF」，索引以 "<章本stem>|<印刷頁碼>"
      為鍵，find 會在所有章本中搜尋並列出所有命中。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import page_assets as P  # noqa: E402
import regq  # noqa: E402

# 索引是可由 `build` 完全重建的機械產生物，依 AGENTS.md §1.1 放 _temp（可整批刪除）
CACHE_DIR = HERE.parents[1] / "_temp" / "regs_pages" / "_page_index"

# 頁碼樣式（依各規範排版不同，已逐一實測）：
#   「-110-」        公路排水設計規範（附錄頁，負號包圍）
#   「3-17」        公路路線設計規範（頁尾）
#   「道路工程設計篇2-1」  市區道路及附屬工程設計規範（頁尾，帶篇別前綴）
#   「17」          建築物耐風設計規範（頁尾，純數字）
#   「10-17」       鋼結構設計規範（頁尾）
#   「附錄-20」     部分規範附錄頁
#   「vi」          前言／目錄等前置頁的羅馬數字
LABEL_EXACT = [
    re.compile(r"^-\s*(\d{1,4})\s*-$"),          # -110-
    re.compile(r"^附錄\s*-\s*(\d{1,3})$"),        # 附錄-20
    re.compile(r"^(\d{1,2})-(\d{1,3})$"),         # 3-17 / 10-17 / 4-151
    re.compile(r"^([A-C]\d{0,2})-(\d{1,3})$"),   # A1-2 / C-8
]
# 整行以純數字或羅馬數字構成（頁尾單獨一行的頁碼）
LABEL_BARE_NUM = re.compile(r"^(\d{1,4})$")
LABEL_ROMAN = re.compile(r"^([ivxlcdm]{1,7})$")
# 帶篇別前綴的頁尾：「道路工程設計篇2-1」
LABEL_SUFFIX = re.compile(r".*?篇\s*(\d{1,2})-(\d{1,3})$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _label_from_text(txt: str):
    """從一頁的文字層取出印刷頁碼標記；取不到回 None。"""
    if not txt:
        return None
    t = _norm(txt)
    for seg, where in ((t[:60], "head"), (t[-60:], "tail")):
        for pat in LABEL_PATTERNS:
            m = pat.match(seg)
            if not m:
                continue
            g = m.groups()
            if len(g) == 2 and g[0] == "附錄":
                return f"附錄-{g[1]}"
            if len(g) == 2:
                return f"{g[0]}-{g[1]}"
            return f"-{g[0]}-"
    return None


def _label_from_words(words, height):
    """由「頁首/頁尾帶內」的字元拼出頁碼標記。

    兩個關鍵事實（實測）：
    1. 頁碼一定印在版面最上方或最下方 —— 所以只看頁首/頁尾帶。
    2. 頁碼在文字層常被拆成多個 token（'3'、'-'、'17' 三個 word），
       所以必須把同一橫列的 token 依 x 座標串接後再比對格式。
    （只看文字層前後字串會誤判：本文例頁面開頭是「3-17表3.8.1.2…」，
      內文的「3-8」「3-16」等數字會被誤認為頁碼。）
    """
    if not words:
        return None
    band = max(1.0, height * 0.12)
    # 收集頁首/頁尾帶內的 token，依 (行, x) 分組成橫列
    rows = {}
    for x0, y0, x1, y1, w, *_ in words:
        if not (y0 <= band or y1 >= height - band):
            continue
        key = round(y0 / 3.0)
        rows.setdefault(key, []).append((x0, w))
    lines = []
    for key in sorted(rows):
        toks = sorted(rows[key])
        lines.append((key, "".join(t for _, t in toks)))
    # 由最靠近頁緣者優先：頁尾（key 大）在前
    for _, line in sorted(lines, key=lambda t: -t[0]):
        s = _norm(line)
        for pat in LABEL_EXACT:
            m = pat.match(s)
            if not m:
                continue
            g = m.groups()
            if len(g) == 2 and g[0] == "附錄":
                return f"附錄-{g[1]}"
            if len(g) == 2:
                return f"{g[0]}-{g[1]}"
            return f"-{g[0]}-"
        m = LABEL_SUFFIX.match(s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = LABEL_BARE_NUM.match(s)
        if m:
            return f"#{m.group(1)}"
        m = LABEL_ROMAN.match(s)
        if m:
            return f"r{m.group(1)}"
    return None


def _pdfs(src: str):
    con = regq.connect()
    row = con.execute("SELECT file FROM src WHERE id=?", (src,)).fetchone()
    if not row:
        raise SystemExit(f"沒有規範代號 {src}")
    fname = row[0]
    have = P.part_pdfs(fname)
    if not have:
        base = P._bases(fname)
        for b in base:
            p = P.REG / (b + ".pdf")
            if p.exists():
                return [(b, p)]
        return []
    return sorted(have.items())


def build(src: str, part: str | None = None, refresh: bool = False):
    out = {}
    for stem, pdf in _pdfs(src):
        if part and part.lower() not in stem.lower():
            continue
        try:
            doc = P._open(str(pdf))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {stem}: 開檔失敗 {e}", file=sys.stderr)
            continue
        for i in range(len(doc)):
            pg = doc[i]
            lab = _label_from_words(pg.get_text("words"), pg.rect.height)
            if lab:
                out[f"{stem}|{lab}"] = i + 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{src}.json"
    old = {}
    if f.exists() and not refresh:
        old = json.loads(f.read_text(encoding="utf-8"))
    merged = dict(old)
    merged.update(out)
    f.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not out:
        print(f"  ! {src}: 索引 0 筆——此規範可能只有文字來源（無 PDF），或頁碼樣式不在 LABEL_PATTERNS 支援範圍", file=sys.stderr)
    return merged


def load(src: str):
    f = CACHE_DIR / f"{src}.json"
    if not f.exists():
        return build(src)
    return json.loads(f.read_text(encoding="utf-8"))


def find(src: str, label: str, part: str | None = None):
    idx = load(src)
    hits = []
    for k, v in idx.items():
        stem, lab = k.split("|", 1)
        if lab != label:
            continue
        if part and part.lower() not in stem.lower():
            continue
        hits.append((stem, v))
    return hits


def show(src: str, part: str | None = None):
    idx = load(src)
    rows = []
    for k, v in idx.items():
        stem, lab = k.split("|", 1)
        if part and part.lower() not in stem.lower():
            continue
        rows.append((stem, lab, v))
    rows.sort(key=lambda r: (r[0], r[2]))
    for stem, lab, v in rows:
        print(f"{stem:44s} 印刷頁 {lab:>10s}  →  PDF 第 {v} 頁")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    src = sys.argv[2]
    part = None
    args = sys.argv[3:]
    if "--part" in args:
        i = args.index("--part")
        part = args[i + 1] if i + 1 < len(args) else None
    if cmd == "build":
        idx = build(src, part, refresh=True)
        print(f"{src}: 索引 {len(idx)} 筆 → {CACHE_DIR / (src + '.json')}")
        if not idx:
            return 0
    elif cmd == "show":
        show(src, part)
    elif cmd == "find":
        if len(sys.argv) < 4:
            print("用法: find <src> <印刷頁碼>")
            return 1
        label = sys.argv[3]
        hits = find(src, label, part)
        if not hits:
            print(f"{src}: 找不到印刷頁碼 {label}")
            return 2
        for stem, v in hits:
            print(f"{src}  印刷頁 {label:>10s}  →  {stem}  PDF 第 {v} 頁")
    elif cmd == "all":
        for s in sys.argv[3:]:
            show(s)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
