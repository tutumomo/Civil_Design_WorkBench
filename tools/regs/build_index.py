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
    part_csi, part_csi_done = "", False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##### "):
            part, group = s[6:], group + 1
            m_pcsi = re.match(r"^(\d{5})_", part)
            part_csi = m_pcsi.group(1) if m_pcsi else ""
            part_csi_done = False
            lines.append(("part", s[6:], page, group))
            continue
        m = re.fullmatch(r"=== p\.(\d+) ===", s)
        if m:
            page = int(m.group(1))
            continue
        m_csi = CSI.fullmatch(s)
        if m_csi:
            if part_csi:
                if m_csi.group(1) == part_csi and not part_csi_done:
                    part_csi_done = True
                    group += 1
                    lines.append(("csi", m_csi.group(1), page, group))
                    continue
            else:
                group += 1
                lines.append(("csi", m_csi.group(1), page, group))
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


BARRIER_HEAD = re.compile(r"^(A?)(\d{3,4})((?:\.\d{1,3})*)[\s　]*(.*)$")
BARRIER_CHAPTER = re.compile(r"^第([" + CN_NUM + r"]+)章[\s　]*(.*)$")
BARRIER_APPENDIX = re.compile(r"^附錄\s*(\d+)[\s　]*(.*)$")
BARRIER_PUNCT = re.compile(r"^[）)。，、；：﹚)」』】.,;:]")
# 目錄點線：這部規範用 ⋯（U+22EF），通用 TOC 樣式沒有它，必須另立
BARRIER_TOC = re.compile(r"⋯|…{2,}|\.{4,}|‧{3,}|·{3,}")


def barrier_units(text):
    """Split 《建築物無障礙設施設計規範》 on 3–4 位數字條號（101、203.2.2、1005.2、A102.2.1）。

    `code_units()` 只適用「章.節.小節」點號式代碼（如 3.4.5），這部規範的條號是
    章＋流水號（第 2 章為 201～207）、章內重新起算，故另立切分器（manifest 記
    `splitter: "barrier"`）。三種 PDF 斷行陷阱與解法：

    1. 跨條參照被拆行（「但適用本規範」／次行「202.4者，其地面坡度…」）：條號用最長
       嚴格遞增子序列（`lis()`）挑，不遞增者落選，內容留在原條。
    2. 圖號引用與真條文同號（真條文「206.4.2」＋後文「206.4.2）。」）：編號後只接
       標點者不視為標題。
    3. 目錄頁同號（p.2～p.7，點線為 ⋯ U+22EF）：含點線的行整段丟棄（連目錄頁本身）。
    4. `BARRIER_HEAD` 必須是 `\\d{3,4}`，`\\d{3}` 會把 1005.2 截成 100。

    條號前綴 `A` 為附錄（`附錄1 基本尺寸` 之後的 A101…），與正文分組各自跑 LIS。
    """
    lines = [ln.strip() for ln in text.splitlines()]
    toc_end = max([i for i, s in enumerate(lines) if BARRIER_TOC.search(s)] or [-1])
    if any(s.startswith("目錄") for s in lines[:toc_end + 1]):
        lines[:toc_end + 1] = [""] * (toc_end + 1)  # 目錄頁整段作廢

    raw, page = [], None
    for s in lines:
        m = re.fullmatch(r"=== p\.(\d+) ===", s)
        if m:
            page = int(m.group(1))
            continue
        if not s or BARRIER_TOC.search(s) or re.fullmatch(r"\d{1,3}", s):
            continue
        raw.append((page, s))

    def head_at(i, chap):
        """Candidate heading at raw[i], or None. `chap` is the current chapter number."""
        s = raw[i][1]
        m = BARRIER_HEAD.fullmatch(s)
        if not m:
            return None
        prefix, num, dots, rest = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        n = int(num)
        if dots:
            if not rest or BARRIER_PUNCT.match(rest):
                return None
            key = tuple(int(x) for x in (num + dots).split("."))
            if prefix:
                if not 1 <= key[0] % 100 <= 99:
                    return None
            elif key[0] // 100 != chap:
                return None
        else:
            # 章級條號（101、1005、A101）後面接空格；內文換行後殘留的「120公分…」不可誤判
            if not rest or s[len(prefix) + len(num):len(prefix) + len(num) + 1] not in (" ", "　"):
                return None
            if not 1 <= n % 100 <= 99 or (not prefix and n // 100 != chap):
                return None
            key = (n,)
        return {"group": None, "key": key, "code": prefix + num + dots, "rest": rest}

    cand, chap, group = [], None, 0
    for i in range(len(raw)):
        s = raw[i][1]
        m = BARRIER_CHAPTER.fullmatch(s)
        if m:
            chap, group = cn_int(m.group(1)), group + 1
            continue
        m = BARRIER_APPENDIX.fullmatch(s)
        if m and m.group(2).strip() and STARTS_TEXT.match(m.group(2).strip()):
            chap, group = None, group + 1
            continue
        h = head_at(i, chap)
        if h:
            h["group"] = group
            h["i"] = i
            cand.append(h)

    heads = {}
    for g in {c["group"] for c in cand}:
        cs = [c for c in cand if c["group"] == g]
        for k in lis([c["key"] for c in cs]):
            heads[cs[k]["i"]] = cs[k]

    units, cur, chap, chap_title, group = [], None, None, "", 0
    for i, (pg, s) in enumerate(raw):
        m = BARRIER_CHAPTER.fullmatch(s)
        if m:
            chap, group = cn_int(m.group(1)), group + 1
            title = chap_title = m.group(2).strip()
            cur = {"clause": f"第{chap}章", "title": title, "path": f"第{chap}章 {title}",
                   "page": pg, "part": "", "lines": []}
            units.append(cur)
            continue
        m = BARRIER_APPENDIX.fullmatch(s)
        if m and m.group(2).strip() and STARTS_TEXT.match(m.group(2).strip()):
            chap, group = None, group + 1
            title = chap_title = m.group(2).strip()
            cur = {"clause": f"附錄{m.group(1)}", "title": title, "path": f"附錄{m.group(1)} {title}",
                   "page": pg, "part": "", "lines": []}
            units.append(cur)
            continue
        h = heads.get(i)
        if h:
            title = re.split(r"[：，。：；;,:]", h["rest"])[0][:40].strip()
            cur = {"clause": h["code"], "title": title,
                   "path": f"第{chap}章 {chap_title}" if chap else chap_title,
                   "page": pg, "part": "", "lines": [(pg, h["rest"])]}
            units.append(cur)
            continue
        if cur is not None:
            cur["lines"].append((pg, s))
    return chunk([u for u in units if u["lines"]])


BRIDGE_HEAD = re.compile(r"([1-9]\d?(?:\.\d{1,2}){1,4})\.?(?:\s+(.*))?")
BRIDGE_CHEAD = re.compile(r"(C[1-9]\d?(?:\.\d{1,2}){1,4})\.?(?:\s+(.*))?")
BRIDGE_TAB_FIG = re.compile(r"^((?:表|圖)[C]?\d+-\d+(?:\s*\([a-zA-Z\d]+\))?)\s+(.*)")


def bridge_seis_units(text):
    """Split 《公路橋梁耐震設計規範》 into 規範本文 (1.1~8.7), 解說 (C1.1~C8.7), 參考文獻, 附表與附圖."""
    pages = []
    for p in text.split("=== p."):
        if not p.strip():
            continue
        pno, body = p.split(" ===", 1)
        pages.append((int(pno), body))

    units = []
    cur = {"clause": "0", "title": "（前言／目錄）", "path": "", "page": 1, "part": "", "lines": []}
    units.append(cur)

    for pno, body in pages:
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        for ln in lines:
            if TOC.search(ln):
                cur["lines"].append((pno, ln))
                continue
            if 21 <= pno <= 70:
                m = BRIDGE_HEAD.match(ln)
                if m:
                    num = m.group(1)
                    rest = (m.group(2) or "").strip()
                    if rest and len(rest) <= 40 and not rest.endswith(("。", "：", "，", "；")):
                        cur = {"clause": num, "title": rest, "path": f"規範本文 > {num} {rest}",
                               "page": pno, "part": "規範本文", "lines": [(pno, ln)]}
                        units.append(cur)
                        continue
            elif 71 <= pno <= 148:
                m = BRIDGE_CHEAD.match(ln)
                if m:
                    num = m.group(1)
                    rest = (m.group(2) or "").strip()
                    if rest and len(rest) <= 40 and not rest.endswith(("。", "：", "，", "；")):
                        cur = {"clause": num, "title": rest, "path": f"規範解說 > {num} {rest}",
                               "page": pno, "part": "規範解說", "lines": [(pno, ln)]}
                        units.append(cur)
                        continue
            elif 149 <= pno <= 150:
                if ln == "參考文獻" and cur["clause"] != "參考文獻":
                    cur = {"clause": "參考文獻", "title": "參考文獻", "path": "參考文獻",
                           "page": pno, "part": "參考文獻", "lines": [(pno, ln)]}
                    units.append(cur)
                    continue
            elif pno >= 151:
                m = BRIDGE_TAB_FIG.match(ln)
                if m:
                    tf_id = m.group(1).replace(" ", "")
                    tf_title = m.group(2).strip()[:40]
                    cur = {"clause": tf_id, "title": tf_title, "path": f"附錄圖表 > {tf_id} {tf_title}",
                           "page": pno, "part": "附錄圖表", "lines": [(pno, ln)]}
                    units.append(cur)
                    continue
            cur["lines"].append((pno, ln))

    return chunk([u for u in units if u["lines"] or u["clause"] != "0"])


WOOD110_SECTIONS = [
    ("9.2", "木構造建築物防火規劃基本原則", re.compile(r"^9\.2\s+木構造建築物防火規劃基本原則")),
    ("9.3", "木構造系統防火設計", re.compile(r"^9\.3\s+木構造系統防火設計")),
    ("9.3.1", "框組壁式系統", re.compile(r"^9\.3\.1\s*框組壁式系統")),
    ("9.3.2", "樑柱構架系統", re.compile(r"^9\.3\.2\s*[梁樑]柱構架系統")),
    ("9.3.3", "原木層疊系統", re.compile(r"^9\.3\.3\s*原木層疊系統")),
    ("9.3.4", "其他系統", re.compile(r"^9\.3\.4\s*其他系統")),
    ("附錄六", "國外常用木構造牆壁、樓地板和屋頂系統", re.compile(r"第九[·．\.]三點附[錄錄][六六]")),
    ("附錄七", "特殊耐火級石膏板耐火性能試驗特定要求", re.compile(r"第九[·．\.]三點附[錄錄]七")),
]


def wood110_units(text):
    """Split 《木構造建築物設計及施工技術規範》110.01.26 修正對照表 into 9.2, 9.3, 附錄六, 附錄七."""
    lines = []
    for p in text.split("=== p."):
        if not p.strip():
            continue
        pno, body = p.split(" ===", 1)
        for ln in body.splitlines():
            s = ln.strip()
            if s:
                lines.append((int(pno), s))

    units = []
    cur = {"clause": "0", "title": "（令函）", "path": "令函", "page": 1, "part": "", "lines": []}
    units.append(cur)

    for pno, ln in lines:
        matched = None
        for cid, ctitle, pat in WOOD110_SECTIONS:
            if pat.search(ln):
                matched = (cid, ctitle)
                break
        if matched:
            cid, ctitle = matched
            cur = {"clause": cid, "title": ctitle, "path": f"第九章防火修正 > {cid} {ctitle}",
                   "page": pno, "part": "修正規定", "lines": [(pno, ln)]}
            units.append(cur)
        else:
            cur["lines"].append((pno, ln))

    return chunk([u for u in units if u["lines"] or u["clause"] != "0"])


def src100_units(text):
    """Split 《鋼骨鋼筋混凝土構造設計規範與解說》 by chapter PDF part and C.x(.y) headings."""
    lines, page, part, chap = [], None, "", None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##### "):
            part = s[6:]
            m_p = re.match(r"^(\d{2})_", part)
            chap = int(m_p.group(1)) if m_p and 1 <= int(m_p.group(1)) <= 10 else None
            lines.append(("part", part, page, chap))
            continue
        m = re.fullmatch(r"=== p\.(\d+) ===", s)
        if m:
            page = int(m.group(1))
            continue
        if s:
            lines.append(("text", s, page, chap))

    # Each chapter 01..10 accepts only `{chap}.x...` headings; ignore bare 1./2./3. list bullets
    cand = []
    for i, (kind, s, _, ch) in enumerate(lines):
        if kind != "text" or ch is None:
            continue
        m = re.fullmatch(rf"({ch}\.\d+(?:\.\d+)*)\s+([一-鿿A-Za-z（(].*)", s)
        if not m:
            continue
        num, rest = m.group(1), m.group(2).strip()
        if rest.endswith(("。", "；", "，")) or len(rest) > 50:
            continue
        cand.append((ch, tuple(int(x) for x in num.split(".")), i, num, rest))
    heads = {}
    for ch in {c[0] for c in cand}:
        cs = [c for c in cand if c[0] == ch]
        for k in lis([c[1] for c in cs]):
            heads[cs[k][2]] = cs[k]

    units, titles = [], {}
    cur = None
    for i, (kind, s, pg, ch) in enumerate(lines):
        if kind == "part":
            titles = {}
            if s.startswith("11_"):
                cur = {"clause": "參考文獻", "title": "參考文獻", "path": "參考文獻",
                       "page": pg or 1, "part": s, "lines": []}
            elif s.startswith("12_"):
                cur = {"clause": "符號說明", "title": "符號說明", "path": "符號說明",
                       "page": pg or 1, "part": s, "lines": []}
            else:
                cur = {"clause": f"第{ch}章" if ch else "0", "title": s, "path": "",
                       "page": pg or 1, "part": s, "lines": []}
            units.append(cur)
            continue
        h = heads.get(i)
        if h:
            _, _, _, num, rest = h
            title = re.split(r"[，。：:；;]", rest)[0][:40].strip()
            titles[num] = title
            parents = [".".join(num.split(".")[:k]) for k in range(1, num.count(".") + 1)]
            path = " > ".join(f"{p} {titles[p]}" for p in parents if p in titles)
            cur = {"clause": num, "title": title, "path": path, "page": pg,
                   "part": part, "lines": []}
            units.append(cur)
            continue
        if cur is not None:
            # 過濾 PDF 粗體重複渲染的同標題行
            if cur["lines"] and cur["lines"][-1][1] == s and len(s) <= 30:
                continue
            cur["lines"].append((pg, s))
    return chunk([u for u in units if u["lines"] or not u["clause"].startswith("第")])


def concrete_const110_units(text):
    """Split 《結構混凝土施工規範》 by chapter (1..19) + 附錄甲/乙, allowing no-space headings in ch.10-19."""
    raw = []
    page = 1
    started = False
    for ln in text.splitlines():
        s = ln.strip()
        m = re.fullmatch(r"=== p\.(\d+) ===", s)
        if m:
            page = int(m.group(1))
            continue
        if not s:
            continue
        if not started:
            if re.fullmatch(r"1\s+第\s*一\s*章\s+總\s*則", s):
                started = True
            else:
                continue
        raw.append((page, s))

    CHAP_LINE = re.compile(r"^(\d{1,2})\s+第\s*[一二三四五六七八九十百]+\s*章\s+(.+)$")
    APPX_LINE = re.compile(r"^(附錄[甲乙])\s+(.+)$")
    RUN_HDR = re.compile(r"^(?:第\s*[一二三四五六七八九十百]+\s*章\s+.+|\d{1,2}-\d{1,2}|附錄[甲乙]\s+.+)$")

    chap_groups = []
    chap = None
    seen_appx = set()
    tagged = []  # (kind, data, pg, s)
    for pg, s in raw:
        mc = CHAP_LINE.fullmatch(s)
        if mc:
            chap = int(mc.group(1))
            ctitle = re.sub(r"\s+", " ", mc.group(2)).strip()
            tagged.append(("chap", (chap, ctitle), pg, s))
            continue
        ma = APPX_LINE.fullmatch(s)
        if ma and ma.group(1) not in seen_appx:
            seen_appx.add(ma.group(1))
            chap = None
            tagged.append(("appx", (ma.group(1), re.sub(r"\s+", " ", ma.group(2)).strip()), pg, s))
            continue
        if RUN_HDR.fullmatch(s):
            continue
        tagged.append(("text", chap, pg, s))

    cand = []
    for i, (kind, data, pg, s) in enumerate(tagged):
        if kind != "text" or data is None:
            continue
        ch = data
        m = re.fullmatch(rf"({ch}\.\d+(?:\.\d+)*)\s*([^\d.].*)", s)
        if not m or TOC.search(s):
            continue
        num, rest = m.group(1), m.group(2).strip()
        if not STARTS_TEXT.match(rest) or rest.startswith(("節", "％", "%", "mm", "cm", "kg", "之")):
            continue
        # 單點項（10.1）後若為完整句尾且很長，多為條文交叉參照而非標題
        if num.count(".") == 1 and len(rest) > 45 and rest.endswith("。"):
            continue
        cand.append((ch, tuple(int(x) for x in num.split(".")), i, num, rest))

    heads = {}
    for ch in {c[0] for c in cand}:
        cs = [c for c in cand if c[0] == ch]
        for k in lis([c[1] for c in cs]):
            heads[cs[k][2]] = cs[k]

    units, titles, cur_chap_path = [], {}, ""
    cur = None
    for i, (kind, data, pg, s) in enumerate(tagged):
        if kind == "chap":
            ch, ctitle = data
            titles = {}
            cur_chap_path = f"第{ch}章 {ctitle}"
            cur = {"clause": f"第{ch}章", "title": ctitle, "path": cur_chap_path,
                   "page": pg, "part": "", "lines": []}
            units.append(cur)
            continue
        if kind == "appx":
            aid, atitle = data
            cur_chap_path = f"{aid} {atitle}"
            cur = {"clause": aid, "title": atitle, "path": cur_chap_path,
                   "page": pg, "part": "", "lines": []}
            units.append(cur)
            continue
        h = heads.get(i)
        if h:
            _, _, _, num, rest = h
            title = re.split(r"[，。：:；;]", rest)[0][:40].strip()
            titles[num] = title
            parents = [".".join(num.split(".")[:k]) for k in range(1, num.count(".") + 1)]
            path = " > ".join([cur_chap_path] + [f"{p} {titles[p]}" for p in parents if p in titles])
            cur = {"clause": num, "title": title, "path": path, "page": pg, "part": "",
                   "lines": [(pg, rest)] if len(rest) > len(title) else []}
            units.append(cur)
            continue
        if cur is not None:
            cur["lines"].append((pg, s))
    return chunk([u for u in units if u["lines"] or u["clause"].startswith("附錄")])


def rainwater109_units(text):
    """Split 《雨水下水道設計指南》 by 篇 (I/II/III/IV) and 章, matching Y.Z(.W) only within 章 Y."""
    CN_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}
    PART_RE = re.compile(r"^第([一二三四])篇\s+(.+)$")
    CHAP_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s+(.+)$")
    PG_CODE = re.compile(r"^(?:I|II|III|IV)\s*-\s*\d+$")

    pages = []
    for p in text.split("=== p.")[1:]:
        pno, body = p.split(" ===", 1)
        pn = int(pno)
        if pn < 22:  # p.1~21 為封面與目錄
            continue
        pages.append((pn, [ln.strip() for ln in body.splitlines() if ln.strip()]))

    part_no, part_name, chap_no, chap_name = 1, "", None, ""
    raw = []  # (part_no, part_name, chap_no, chap_name, pg, s)
    for pn, lns in pages:
        # 第二篇（p.133~176）為掃描圖檔，無文字層
        if 133 <= pn <= 176:
            if pn == 133:
                raw.append((2, "抽水站設計", 0, "（掃描影像）", pn,
                            "［第二篇 抽水站設計（p.133～176）為掃描影像，無文字層，數值與條文須查原 PDF］"))
            continue
        idx = 0
        # 略過每頁頁首的「第X篇」「第Y章」「I-15」重複頁眉
        while idx < min(4, len(lns)):
            s = lns[idx]
            mp = PART_RE.fullmatch(s)
            if mp:
                new_p = CN_MAP[mp.group(1)]
                if new_p != part_no:
                    part_no, part_name, chap_no, chap_name = new_p, mp.group(2).strip(), None, ""
                else:
                    part_name = mp.group(2).strip()
                idx += 1
                continue
            mc = CHAP_RE.fullmatch(s)
            if mc:
                chap_no = CN_MAP.get(mc.group(1))
                chap_name = re.sub(r"\s+", " ", mc.group(2)).strip()
                idx += 1
                continue
            if PG_CODE.fullmatch(s):
                idx += 1
                continue
            break
        for s in lns[idx:]:
            mc = CHAP_RE.fullmatch(s)
            if mc and len(s) < 40:
                chap_no = CN_MAP.get(mc.group(1))
                chap_name = re.sub(r"\s+", " ", mc.group(2)).strip()
                continue
            raw.append((part_no, part_name, chap_no, chap_name, pn, s))

    cand = []
    for i, (pno, _, ch, _, _, s) in enumerate(raw):
        if not ch:
            continue
        m = re.fullmatch(rf"({ch}\.\d+(?:\.\d+)*)\s+([一-鿿A-Za-z（(].*)", s)
        if not m or TOC.search(s):
            continue
        num, rest = m.group(1), m.group(2).strip()
        if len(rest) > 45 and rest.endswith("。"):
            continue
        cand.append(((pno, ch), tuple(int(x) for x in num.split(".")), i, num, rest))

    heads = {}
    for g in {c[0] for c in cand}:
        cs = [c for c in cand if c[0] == g]
        for k in lis([c[1] for c in cs]):
            heads[cs[k][2]] = cs[k]

    units, titles = [], {}
    cur = None
    last_group = None
    for i, (pno, pname, ch, cname, pg, s) in enumerate(raw):
        grp = (pno, ch)
        if grp != last_group:
            last_group = grp
            titles = {}
            if pno == 2:
                units.append({"clause": "II-0", "title": "抽水站設計（掃描影像）",
                              "path": "第二篇 抽水站設計", "page": pg, "part": "第二篇",
                              "lines": [(pg, s)]})
                cur = None
                continue
            cur = {"clause": f"{ROMAN[pno]}-{ch or 0}", "title": cname or pname,
                   "path": f"第{pno}篇 {pname}" + (f" > 第{ch}章 {cname}" if ch else ""),
                   "page": pg, "part": f"第{pno}篇", "lines": []}
            units.append(cur)
        h = heads.get(i)
        if h:
            _, _, _, num, rest = h
            title = re.split(r"[，。：:；;]", rest)[0][:40].strip()
            titles[num] = title
            parents = [".".join(num.split(".")[:k]) for k in range(1, num.count(".") + 1)]
            pstr = f"第{pno}篇 {pname} > 第{ch}章 {cname}"
            if parents:
                pstr += " > " + " > ".join(f"{p} {titles[p]}" for p in parents if p in titles)
            cur = {"clause": f"{ROMAN[pno]}-{num}", "title": title, "path": pstr,
                   "page": pg, "part": f"第{pno}篇",
                   "lines": [(pg, rest)] if len(rest) > len(title) else []}
            units.append(cur)
            continue
        if cur is not None:
            cur["lines"].append((pg, s))
    return chunk([u for u in units if u["lines"]])


def sewer105_units(text):
    """Split 《污水下水道工程設計指針與解說》 on X-Y-ZZ section codes + 第一篇 總則一二三."""
    PART_RE = re.compile(r"^第([一二])篇(?:\s+(.*))?$")
    CHAP_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s*(.*)$")
    SEC_RE = re.compile(r"^第\s*(\d+)\s*節\s*(.*)$")
    CODE_RE = re.compile(r"^(\d{1,2}-\d{1,2}-\d{2})\s+(.+?)(?:\s*\(原則\d+\))?\s*$")
    CN_ITEM = re.compile(r"^([一二三四五六七八九十]+)、\s*(.*)$")

    pages = []
    for p in text.split("=== p.")[1:]:
        pno, body = p.split(" ===", 1)
        pn = int(pno)
        if pn < 18:  # p.1~17 為封面與目錄
            continue
        lns = [ln.strip() for ln in body.splitlines() if ln.strip()]
        # 第一行為書內頁碼純數字時略過
        if lns and re.fullmatch(r"\d{1,3}", lns[0]):
            lns = lns[1:]
        pages.append((pn, lns))

    units = []
    p_lbl, c_lbl, s_lbl = "第一篇 總則", "", ""
    cur = None
    in_part1 = True

    def cur_path():
        return " > ".join(x for x in (p_lbl, c_lbl, s_lbl) if x)

    for pn, lns in pages:
        i = 0
        while i < len(lns):
            s = lns[i]
            mp = PART_RE.fullmatch(s)
            if mp:
                if mp.group(1) == "一":
                    in_part1 = True
                    nxt = lns[i + 1] if not mp.group(2) and i + 1 < len(lns) else mp.group(2) or ""
                    p_lbl = f"第一篇 {nxt}".strip()
                    if not mp.group(2) and nxt:
                        i += 1
                else:
                    in_part1 = False
                    nxt = lns[i + 1] if not mp.group(2) and i + 1 < len(lns) else mp.group(2) or ""
                    p_lbl = f"第二篇 {nxt}".strip()
                    if not mp.group(2) and nxt:
                        i += 1
                i += 1
                continue
            mc = CHAP_RE.fullmatch(s)
            if mc and len(s) < 40:
                c_lbl = re.sub(r"\s+", " ", s)
                s_lbl = ""
                i += 1
                continue
            ms = SEC_RE.fullmatch(s)
            if ms and len(s) < 40:
                s_lbl = re.sub(r"\s+", " ", s)
                i += 1
                continue
            if in_part1:
                mi = CN_ITEM.match(s)
                if mi:
                    n = cn_int(mi.group(1))
                    rest = mi.group(2).strip()
                    if not rest and i + 1 < len(lns):
                        rest = lns[i + 1]
                        i += 1
                    cur = {"clause": f"總則-{n}", "title": rest[:40], "path": cur_path(),
                           "page": pn, "part": "第一篇", "lines": [(pn, rest)]}
                    units.append(cur)
                    i += 1
                    continue
            else:
                mk = CODE_RE.fullmatch(s)
                if mk:
                    code, title = mk.group(1), mk.group(2).strip()[:40]
                    cur = {"clause": code, "title": title, "path": cur_path(),
                           "page": pn, "part": c_lbl, "lines": [(pn, s)]}
                    units.append(cur)
                    i += 1
                    continue
            if cur is not None:
                cur["lines"].append((pn, s))
            i += 1
    return chunk([u for u in units if u["lines"]])


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
        if splitter == "barrier":
            units = barrier_units(text)
            source_kind = "code"
        elif splitter == "bridge_seis":
            units = bridge_seis_units(text)
            source_kind = "code"
        elif splitter == "wood110":
            units = wood110_units(text)
            source_kind = "code"
        elif sid == "src100" or splitter == "src100":
            units = src100_units(text)
            source_kind = "code"
        elif sid == "concrete_const110" or splitter == "concrete_const110":
            units = concrete_const110_units(text)
            source_kind = "code"
        elif sid == "rainwater109" or splitter == "rainwater109":
            units = rainwater109_units(text)
            source_kind = "code"
        elif sid == "sewer105" or splitter == "sewer105":
            units = sewer105_units(text)
            source_kind = "code"
        elif source_kind == "law_point" or splitter == "point":
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
