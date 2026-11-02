"""Split every fetched code / regulation into clause units and store them in a SQLite index.

Laws (law.moj / law.moa text) are split on 「第 N 條」; technical codes extracted from PDF are
split on numbered section headings (e.g. 「3.4.5 超高漸變長度」). Each unit keeps source id,
edition status, clause number, title, chapter path, page and text, so regq.py can answer
「沉砂池要看哪幾條」 with citations.

usage: python -E -P -X utf8 build_index.py
"""
import collections
import json
import re
import sqlite3
import sys
import unicodedata
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_catalog import EXTRA, META  # noqa: E402  (status / category per source id)

REG = Path(os.environ.get("CIVIL_AI_REGS_DIR")
           or (Path(__file__).resolve().parents[2] / "data" / "法規"))
DB = REG / "_regs_index.sqlite"

# PDFs set in the Symbol font put Greek letters / math signs in the private-use area U+F0xx
SYMBOL = dict(zip("abcdefghijklmnopqrstuvwxyzDFGLPQSW",
                  "αβχδεφγηιϕκλμνοπθρστυϖωξψζΔΦΓΛΠΘΣΩ"))
SYMBOL.update({chr(0xB3): "≥", chr(0xA3): "≤", chr(0xB4): "×", chr(0xD6): "√", chr(0xB1): "±",
               chr(0xB0): "°", chr(0xA5): "∞", chr(0xB9): "≠", chr(0xBB): "≈", chr(0xA2): "′"})

CN_NUM = "〇一二三四五六七八九十百"


def clean(t):
    def sym(m):
        c = chr(ord(m.group(0)) - 0xF000)
        return SYMBOL.get(c, c if c.isprintable() else "")
    t = re.sub("[\uf020-\uf0ff]", sym, t)
    return unicodedata.normalize("NFKC", t)


def cn_int(s):
    """Convert a conventional Chinese numeral such as 十一／二十五 to int."""
    digits = {c: i for i, c in enumerate("〇一二三四五六七八九")}
    units = {"十": 10, "百": 100}
    total, current = 0, 0
    for ch in s:
        if ch in digits:
            current = digits[ch]
        elif ch in units:
            total += (current or 1) * units[ch]
            current = 0
        else:
            raise ValueError(f"not a Chinese numeral: {s}")
    return total + current


def law_units(text):
    """Split law text on 「第 N 條」 lines; keep 章/節 headings as the path."""
    units, path, cur = [], {}, None
    appendix_no = 0
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##### "):
            appendix_no += 1
            title = s[6:].strip()
            cur = {"clause": f"附件-{appendix_no}", "title": title,
                   "path": "附件", "page": None, "part": "", "lines": []}
            units.append(cur)
            continue
        m = re.fullmatch(r"第\s*([" + CN_NUM + r"0-9]+)\s*(編|章|節|款)\s*(.*)", s)
        if m and len(s) < 40:
            lvl = "編章節款".index(m.group(2))
            path = {k: v for k, v in path.items() if k < lvl}
            path[lvl] = re.sub(r"\s+", "", f"第{m.group(1)}{m.group(2)}") + " " + m.group(3).strip()
            continue
        m = re.fullmatch(r"(?:本條文有附件\s*)?第\s*(\d+(?:-\d+)?)\s*條(?:\s*[（(](.{1,40})[）)])?", s)
        if m:
            title = m.group(2) or ""
            # law.moj marks clauses whose tables / formulas live only in an attached file
            attach = "無法完整呈現" in title
            cur = {"clause": m.group(1), "title": "" if attach else title,
                   "path": " > ".join(path[k] for k in sorted(path)),
                   "page": None, "part": "",
                   "lines": ["［本條有表格或公式僅見於附件檔，數值請查原條文附件］"] if attach else []}
            units.append(cur)
            continue
        if cur is not None:
            if not cur["lines"] and not cur["title"]:
                t = re.fullmatch(r"[（(](.{1,40})[）)]", s)
                if t:
                    cur["title"] = t.group(1)
                    continue
            if s or cur["lines"]:
                cur["lines"].append(s)
    return units


def point_units(text):
    """Split point-numbered regulations such as 農路設計規範 on 「一、二、…」.

    `##### attachment` headings become separate appendix units so table text does
    not pollute the last numbered point.
    """
    units, cur = [], None
    appendix_no = 0
    in_appendix = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##### "):
            in_appendix = True
            appendix_no += 1
            title = s[6:].strip()
            cur = {"clause": f"附件-{appendix_no}", "title": title,
                   "path": "附表／附圖", "page": None, "part": "", "lines": []}
            units.append(cur)
            continue
        m = None if in_appendix else re.match(r"^([" + CN_NUM + r"]+)、\s*(.*)$", s)
        if m:
            n = cn_int(m.group(1))
            rest = m.group(2).strip()
            title = rest.split("：", 1)[0][:40] if rest else f"第 {n} 點"
            cur = {"clause": str(n), "title": title, "path": "",
                   "page": None, "part": "", "lines": [rest] if rest else []}
            units.append(cur)
            continue
        if cur is not None and (s or cur["lines"]):
            cur["lines"].append(s)
    return units


HEAD = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,4})\.?(?:\s+(.*))?")
TOC = re.compile(r"\.{4,}|…{2,}|‧{3,}|·{3,}|\s\d+\s*-\s*\d+$")
CSI = re.compile(r"第\s*(\d{5})\s*章")
STARTS_TEXT = re.compile(r"[\u4e00-\u9fffA-Za-z（(]")


def lis(keys):
    """Indices of a longest strictly increasing subsequence of comparable keys."""
    import bisect
    tails, tail_idx, prev = [], [], [None] * len(keys)
    for i, k in enumerate(keys):
        j = bisect.bisect_left(tails, k)
        if j == len(tails):
            tails.append(k)
            tail_idx.append(i)
        else:
            tails[j], tail_idx[j] = k, i
        prev[i] = tail_idx[j - 1] if j else None
    out, i = [], tail_idx[-1] if tail_idx else None
    while i is not None:
        out.append(i)
        i = prev[i]
    return out[::-1]


# 「附錄A 臺灣地區洪水量推算經驗公式」 etc. on a line of its own: appendices must not be swallowed by the
# last numbered clause before them (e.g. 公路排水 §9.7 once held the whole of 附錄 A…)
APPX = re.compile(r"附錄[　 ]*([A-Z]|[一二三四五六七八九十]+|\d+)[　 ]*([^。，；;]{0,40})")
APPX_REF = re.compile(r"^(之|所|及|與|或|中|的|第|規定|依|按|參|詳|說明了?|如|內)")


def appx_head(s):
    m = APPX.fullmatch(s)
    if not m or TOC.search(s) or APPX_REF.match(m.group(2).strip()):
        return None
    return m.group(1), m.group(2).strip()


def code_units(text):
    """Split PDF-extracted code text on numbered section headings, tracking page and part file.

    Body lines such as 「1.5 公尺」 look like headings too, so candidates are collected per group
    (part file / 第NNNNN章) and only the longest increasing run of section numbers is kept.
    """
    lines, page, part, group = [], None, "", 0
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##### "):
            part, group = s[6:], group + 1
            lines.append(("part", s[6:], page, group))
            continue
        m = re.fullmatch(r"=== p\.(\d+) ===", s)
        if m:
            page = int(m.group(1))
            continue
        if CSI.fullmatch(s):
            group += 1
            lines.append(("csi", CSI.fullmatch(s).group(1), page, group))
            continue
        if s:
            lines.append(("text", s, page, group))

    # heading candidates: number + text on one line, or a bare number with its title on the next line
    cand = []
    for i, (kind, s, _, g) in enumerate(lines):
        if kind != "text" or TOC.search(s):
            continue
        m = HEAD.fullmatch(s)
        if not m:
            continue
        num, rest = m.group(1), (m.group(2) or "").strip()
        # a single-level number (「1.」) only counts with its trailing dot; bare 「98」 is table data
        if "." not in num and s[len(num):len(num) + 1] != ".":
            continue
        if not rest:
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if not (nxt and nxt[0] == "text" and STARTS_TEXT.match(nxt[1]) and len(nxt[1]) <= 40):
                continue
            title, inline = nxt[1], False
        elif STARTS_TEXT.match(rest):
            title, inline = rest, True
        else:
            continue
        cand.append((g, tuple(int(x) for x in num.split(".")), i, num, title, inline))
    heads = {}
    for g in {c[0] for c in cand}:
        cs = [c for c in cand if c[0] == g]
        for k in lis([c[1] for c in cs]):
            heads[cs[k][2]] = cs[k]

    units, titles, csi, csi_title = [], {}, "", ""
    cur = {"clause": "0", "title": "（前言／目錄）", "path": "", "page": 1, "part": "", "lines": []}
    units.append(cur)
    skip = set()
    for i, (kind, s, pg, g) in enumerate(lines):
        if i in skip:
            continue
        if kind == "part":
            part, titles, csi, csi_title = s, {}, "", ""
            cur = {"clause": "0", "title": "（前言）", "path": "", "page": pg, "part": part, "lines": []}
            units.append(cur)
            continue
        if kind == "csi":
            csi, titles = s, {}
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            csi_title = nxt[1] if nxt and nxt[0] == "text" and len(nxt[1]) <= 40 else ""
            if csi_title:
                skip.add(i + 1)
            cur = {"clause": f"{csi}章", "title": csi_title, "path": "", "page": pg, "part": part, "lines": []}
            units.append(cur)
            continue
        h = heads.get(i)
        if h:
            _, _, _, num, rest, inline = h
            if not inline:
                skip.add(i + 1)
            title = re.split(r"[，。：:；;]", rest)[0][:40].strip()
            titles[num] = title
            parents = [".".join(num.split(".")[:k]) for k in range(1, num.count(".") + 1)]
            path = " > ".join(([f"第{csi}章 {csi_title}"] if csi else [])
                              + [f"{p} {titles[p]}" for p in parents if p in titles])
            cur = {"clause": f"{csi}/{num}" if csi else num, "title": title, "path": path, "page": pg,
                   "part": part, "lines": [(pg, rest)] if inline and len(rest) > len(title) else []}
            units.append(cur)
            continue
        a = appx_head(s) if kind == "text" else None
        if a and cur["clause"] != f"附錄{a[0]}":
            cur = {"clause": f"附錄{a[0]}", "title": a[1], "path": f"附錄{a[0]}", "page": pg,
                   "part": part, "lines": [(pg, s)]}
            units.append(cur)
            continue
        cur["lines"].append((pg, s))
    # table-of-contents entries (「附錄一 …」 on the contents page) become tiny appendix units: drop them
    # when the same appendix reappears later, so only the real appendix body is indexed
    later = collections.Counter(u["clause"] for u in units if u["clause"].startswith("附錄"))
    units = [u for u in units
             if not (u["clause"].startswith("附錄") and later[u["clause"]] > 1
                     and len("".join(x[1] for x in u["lines"])) < 60)]
    return chunk([u for u in units if u["lines"] or u["clause"] != "0"])


def chunk(units, limit=6000):
    """Split oversized units (appendices, unnumbered tables) at page breaks so hits keep a page."""
    out = []
    for u in units:
        parts, buf, size = [], [], 0
        for pg, s in u["lines"]:
            if size > limit and buf and pg != buf[-1][0]:
                parts.append(buf)
                buf, size = [], 0
            buf.append((pg, s))
            size += len(s)
        parts.append(buf)
        for k, p in enumerate(parts):
            v = dict(u, lines=[s for _, s in p])
            if k:
                v.update(title=f"{u['title']}（續）", page=p[0][0] if p else u["page"])
            out.append(v)
    return out


def sources():
    man = json.loads((REG / "_regs_manifest.json").read_text(encoding="utf-8"))
    man.update({k: dict(v, id=k) for k, v in EXTRA.items()})
    for sid, r in man.items():
        f = r.get("files", {}).get("text")
        if f and (REG / f).exists():
            yield sid, r, REG / f


def main():
    con = sqlite3.connect(DB)
    # Rebuild in one transaction instead of deleting the database file. This keeps
    # running read-only MCP/web servers from locking the index on Windows.
    con.execute("BEGIN IMMEDIATE")
    for sql in (
        "DROP TABLE IF EXISTS unit",
        "DROP TABLE IF EXISTS src",
        """CREATE TABLE src(id TEXT PRIMARY KEY, name TEXT, authority TEXT, version TEXT, category TEXT,
                            status TEXT, kind TEXT, file TEXT, units INT)""",
        """CREATE TABLE unit(rowid INTEGER PRIMARY KEY, src TEXT, clause TEXT, title TEXT, path TEXT,
                             page INT, part TEXT, text TEXT)""",
        "CREATE INDEX unit_src ON unit(src, clause)",
    ):
        con.execute(sql)
    total = 0
    for sid, r, f in sources():
        text = clean(f.read_text(encoding="utf-8"))
        nfkc = f.with_name(f.name.replace("_全文.txt", "_全文_NFKC.txt"))
        if not nfkc.exists():
            nfkc.write_text(unicodedata.normalize("NFKC", f.read_text(encoding="utf-8")), encoding="utf-8")
        source_kind = r.get("kind") or ("law" if r.get("type") == "html" or sid == "swc_tech" else "code")
        splitter = r.get("splitter") or ("point" if sid == "farmroad108" else "law")
        is_law = source_kind in ("law", "law_point")
        if source_kind == "law_point" or splitter == "point":
            units = point_units(text)
            source_kind = "law_point"
        elif is_law:
            units = law_units(text)
        else:
            units = code_units(text)
        if sid not in META:
            raise SystemExit(f"{sid} 尚未在 build_catalog.py 的 META 登錄。\n"
                             f'加一行："{sid}": ("類別（水保／道路／排水／邊坡／鋪面／交通／施工／橋梁／建築結構／建築法規）, '
                             f'"現行", "備註")')
        cat, status, _ = META[sid]
        con.execute("INSERT INTO src VALUES(?,?,?,?,?,?,?,?,?)",
                    (sid, r["name"], r.get("authority", ""), r.get("version") or r.get("amended", ""),
                     cat, status, source_kind, f.name, len(units)))
        con.executemany("INSERT INTO unit(src,clause,title,path,page,part,text) VALUES(?,?,?,?,?,?,?)",
                        [(sid, u["clause"], u["title"], u["path"], u["page"], u["part"],
                          "\n".join(u["lines"]).strip()) for u in units])
        total += len(units)
        print(f"{sid:14s} {'law ' if is_law else 'code'} {len(units):5d} units  {r['name']}")
    con.commit()
    con.close()
    print(f"{total} units -> {DB}")


if __name__ == "__main__":
    main()
