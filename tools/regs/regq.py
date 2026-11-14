"""Look up design-code clauses: topic cards (e.g. 沉砂池) or free keyword search.

usage:
  regq.py 沉砂池                    topic card if 沉砂池 is a topic / alias, else keyword search
  regq.py 泥砂生產量 USLE --search   keyword search only (any term; more terms matched ranks higher)
  regq.py --clause swc_tech 93      full text of one clause
  regq.py --topics                  list topics
options: --all (include superseded editions)  --n N (max hits)  --per N (max hits per code)  --json
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("CIVIL_AI_REGS_DB")
           or (Path(__file__).resolve().parents[2] / "data" / "法規" / "_regs_index.sqlite"))
TOPICS = Path(os.environ.get("REGS_TOPICS") or HERE / "topics.json")
CURRENT = ("現行", "需再核版次")


def norm(s):
    return unicodedata.normalize("NFKC", s)


def connect():
    if not DB.exists():
        sys.exit(f"index not found: {DB}\nrun tools\\regs\\build_index.py first")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def load_topics():
    return json.loads(TOPICS.read_text(encoding="utf-8"))["topics"]


def find_topic(q, topics):
    found = match_topics(q, topics)
    return found[0] if found else None


def match_topics(q, topics):
    """Topics mentioned in q, best first: exact name/alias, then longest name/alias found in the sentence."""
    q = norm(q).strip()
    for t in topics:
        if q == t["name"] or q in t.get("aliases", []):
            return [t]
    # partial: 「設計一個集水井」 -> 集水井與人孔; 「排水溝要做跌水」 -> 排水溝, 跌水與消能
    scored = []
    for t in topics:
        n = max((len(w) for w in [t["name"]] + t.get("aliases", []) if len(w) >= 2 and w in q), default=0)
        if n:
            scored.append((n, t))
    scored.sort(key=lambda x: -x[0])  # stable: equal length keeps topics.json order
    return [t for _, t in scored]


def sources(con):
    return {r["id"]: dict(r) for r in con.execute("SELECT * FROM src")}


def search(con, terms, include_old=False, n=15, per=3, exclude=()):
    """Rank units by distinct terms matched, then title / path / body hits."""
    terms = [norm(t) for t in terms if t.strip()]
    src = sources(con)
    like = " OR ".join("(title LIKE ? OR path LIKE ? OR text LIKE ?)" for _ in terms)
    args = [a for t in terms for a in (f"%{t}%",) * 3]
    hits, seen = [], set()
    for r in con.execute(f"SELECT rowid, * FROM unit WHERE {like}", args):
        s = src[r["src"]]
        if not include_old and s["status"] not in CURRENT:
            continue
        if (r["src"], r["clause"]) in exclude or r["text"].strip() in ("刪除", ""):
            continue
        key = (r["src"], r["clause"], r["text"][:200])  # same section repeated in a merged PDF
        if key in seen:
            continue
        seen.add(key)
        matched, score = 0, 0
        for t in terms:
            c = r["text"].count(t)
            ti, pa = t in r["title"], t in r["path"]
            if c or ti or pa:
                matched += 1
            score += 10 * ti + 3 * pa + min(c, 5)
        hits.append((matched, score, r))
    hits.sort(key=lambda h: (-h[0], -h[1]))
    out, count = [], {}
    for m, sc, r in hits:
        if count.get(r["src"], 0) >= per:
            continue
        count[r["src"]] = count.get(r["src"], 0) + 1
        out.append((m, sc, r))
        if len(out) >= n:
            break
    return out, len(hits)


FILLER = re.compile(r"我要|我想|請問|幫我|如何|怎麼|怎樣|應該|需要|設計|一個|多少|規定|規範|條文|要做|要|的|是|嗎|呢|？|\?|，|,|。")


def smart_search(con, q, include_old=False, n=15, per=3):
    """Keyword search for a spoken sentence: as typed -> filler words removed -> 2-char words."""
    terms = q.split()
    hits, total = search(con, terms, include_old, n, per)
    has_long_cjk = bool(re.search(r"[一-鿿]{4,}", norm(q)))
    if total and (len(terms) > 1 or total >= 3 or not has_long_cjk):
        return hits, total, terms
    chunks = [c for c in FILLER.split(norm(q)) if len(c) >= 2]
    if chunks and chunks != terms:
        ch_hits, ch_total = search(con, chunks, include_old, n, per)
        if ch_total and (ch_total >= 3 or not any(re.search(r"[一-鿿]{4,}", c) for c in chunks)):
            return ch_hits, ch_total, chunks
        if ch_total > total:
            hits, total = ch_hits, ch_total
    grams = list(dict.fromkeys(
        c[i:i + 2] for c in chunks
        if total == 0 or re.search(r"[一-鿿]{4,}", c)
        for i in range(len(c) - 1)
    ))
    if grams:
        ghits, gtotal = search(con, grams, include_old, n, per)
        if hits and gtotal > total:
            # 精確片語僅命中極少（<3 筆）時，保留精確命中於前，補入二元拆詞召回結果
            seen = {(r["src"], r["clause"], r["rowid"]) for _, _, r in hits}
            merged = list(hits)
            cnt = {}
            for _, _, r in merged:
                cnt[r["src"]] = cnt.get(r["src"], 0) + 1
            for m, sc, r in ghits:
                k = (r["src"], r["clause"], r["rowid"])
                if k in seen or cnt.get(r["src"], 0) >= per:
                    continue
                seen.add(k)
                cnt[r["src"]] = cnt.get(r["src"], 0) + 1
                merged.append((m, sc, r))
                if len(merged) >= n:
                    break
            return merged, gtotal, grams
        return ghits, gtotal, grams
    return hits, total, terms


def get_clause(con, sid, clause):
    """All chunks of one clause, from the first part file only (merged PDFs repeat sections)."""
    c = norm(str(clause)).strip()
    c = re.sub(r"\s+", "", c)
    cn_num = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    m = re.fullmatch(r"(?:附件|附表)[-－]?(.+)", c)
    if m:
        token = m.group(1)
        c = f"附件-{cn_num.get(token, token)}"
    else:
        m = re.fullmatch(r"第?(\d+(?:-\d+)?)(?:條|點)?", c)
        if m:
            c = m.group(1)
    rows = con.execute("SELECT rowid, * FROM unit WHERE src=? AND clause=? ORDER BY rowid",
                       (sid, c)).fetchall()
    return [r for r in rows if r["part"] == rows[0]["part"]] if rows else rows


def snippet(text, terms, width=160):
    t = re.sub(r"\s+", " ", text)
    pos = min([i for i in (t.find(norm(x)) for x in terms) if i >= 0] or [0])
    a = max(0, pos - width // 3)
    return ("…" if a else "") + t[a:a + width] + ("…" if a + width < len(t) else "")


def where(s, r):
    loc = f"p.{r['page']}" if r["page"] else ""
    if r["part"]:
        loc = f"{r['part']} {loc}".strip()
    return loc


def label(s, r):
    c = r["clause"]
    if c.startswith("附件-"):
        c = "附件 " + c.split("-", 1)[1]
    elif s["kind"] == "law_point":
        c = f"第 {c} 點"
    elif s["kind"] == "law":
        c = f"第 {c} 條"
    else:
        c = f"§{c}"
    return f"{c}（{r['title']}）" if r["title"] else c


_MESSY = re.compile("[┌│└├─-]")


# ---- 未入庫條文警示（2026-11-02）：被 skip 的條文查得到原文，但數值「未轉換、未驗證」，必須明講 ----
SKIPS_PATH = HERE / "verified" / "_skips.json"
_SKIPS = {"mtime": None, "d": {}}
SKIP_TAG = {
    "covered": "已涵蓋於他條",
    "qualitative": "定性條文",
    "out_of_scope": "未入庫·非本工作區",
    "unrecognized": "未入庫·辨識失敗",
}
SKIP_WARN = {
    "covered": "【已由已驗證條目涵蓋】本條內容已併入其他已驗證條目，請依理由指向的條目取數：",
    "qualitative": "【定性條文】本條經人工讀過，判定無可計算的算式或數值表：",
    "out_of_scope": "【未入庫｜非本工作區】本條原文含表格或公式，但**未轉換成結構化資料、數值未經驗證**，不得直接取數；下方純文字的表式可能錯位亂碼，須回原 PDF／原頁圖核對。判定理由：",
    "unrecognized": "【未入庫｜辨識失敗】本條含表格或公式，但排版破碎或表身未擷取，**尚未轉錄、數值未經驗證**，不得取數，須回原 PDF／原頁圖。紀錄：",
}


def skip_info(sid, clause):
    """被 skip 且沒有 verified 條目的條文 -> {status, tag, warn, reason}；否則 None。"""
    try:
        m = SKIPS_PATH.stat().st_mtime
        if _SKIPS["mtime"] != m:
            d = json.loads(SKIPS_PATH.read_text(encoding="utf-8"))
            _SKIPS.update(mtime=m, d={(i["src"], str(i["clause"])): i for i in d.get("items", [])})
        it = _SKIPS["d"].get((sid, str(clause)))
        if not it:
            return None
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))  # python -P 啟動時腳本目錄不在 sys.path
        import verified
        if verified.for_clause(sid, clause):
            # 部分入庫：條文有一部分已轉錄、其餘仍未轉（例：附錄F.1 已入庫、F.2 未轉）
            if it.get("partial"):
                return {"status": "partial", "tag": "部分入庫", "reason": it.get("reason", ""),
                        "warn": "【部分入庫】本條僅部分內容已轉錄成結構化資料，其餘**未轉換、未驗證**：" + it.get("reason", "")}
            return None
        st = {"deferred": "unrecognized", "no-content": "qualitative"}.get(it["status"], it["status"])
        return {"status": st, "tag": SKIP_TAG.get(st, st), "reason": it.get("reason", ""),
                "warn": SKIP_WARN.get(st, "") + it.get("reason", "")}
    except Exception as exc:
        return {"status": "unrecognized", "tag": "狀態查詢失敗", "reason": repr(exc),
                "warn": "【警示】無法確認本條的入庫狀態（" + repr(exc) + "），請視為未驗證。"}


def ref_row(s, r, ref, body=None):
    d = {"src": r["src"], "code": s["name"], "status": s["status"], "clause": r["clause"],
         "label": label(s, r), "where": where(s, r), "path": r["path"], "note": ref.get("note", ""),
         "body": body, "messy": False, "formulas": 0, "table_html": "",
         "skip": skip_info(r["src"], r["clause"])}
    try:  # formula / table restoration is optional: the CLI and MCP keep working without it
        text = r["text"]
        d["messy"] = bool(_MESSY.search(text))
        import page_assets
        d["formulas"] = len(page_assets.formula_list(r["src"], r["clause"]))
        if d["messy"]:
            tb = [b for b in page_assets.split_blocks(text, r["src"], r["clause"]) if b["t"] == "table"]
            d["table_html"] = tb[0]["html"] if tb else ""
    except Exception:
        pass
    return d


def card_data(con, t, include_old=False, n=15, per=3, also=()):
    """Topic card as plain data (shared by the CLI, the web page and the MCP server)."""
    src = sources(con)
    shown = set()
    d = {"name": t["name"], "aliases": t.get("aliases", []), "scope": t.get("scope", ""),
         "also": [x["name"] for x in also], "core": [], "prereq": [], "missing": [],
         "tools": t.get("tools", []), "notes": t.get("notes", [])}
    for key in ("core", "prereq"):
        for ref in t.get(key, []):
            sid, clause = ref["src"], ref["clause"]
            shown.add((sid, clause))
            s = src.get(sid)
            rows = get_clause(con, sid, clause)
            if not s or not rows:
                d["missing"].append(f"{sid} {clause}")
                continue
            body = re.sub(r"\s+", " ", "\n".join(x["text"] for x in rows)) if key == "core" else None
            d[key].append(ref_row(s, rows[0], ref, body))
    words = [t["name"]] + t.get("aliases", [])
    hits, total = search(con, words, include_old, n, per, exclude=shown)
    d["others_total"] = total
    d["others"] = [dict(ref_row(src[r["src"]], r, {}), snippet=snippet(r["text"], words, 90)) for m, sc, r in hits]
    return d


def card(con, t, include_old, n, per, also=()):
    d = card_data(con, t, include_old, n, per, also)
    out = [f"# {d['name']}｜設計依據卡"]
    if d["aliases"]:
        out.append(f"同義詞：{'、'.join(d['aliases'])}")
    if d["scope"]:
        out.append(f"適用：{d['scope']}")
    if d["also"]:
        out.append(f"這句話也提到：{'、'.join(d['also'])}（各有自己的卡，`regq.py <主題名>`）")
    for sec, key in (("核心條文", "core"), ("前置計算／相關規定", "prereq")):
        if not d[key]:
            continue
        out.append(f"\n## {sec}")
        for x in d[key]:
            tag = "" if x["status"] == "現行" else f"［{x['status']}］"
            note = f" —— {x['note']}" if x["note"] else ""
            sk = f"【{x['skip']['tag']}】" if x.get("skip") else ""
            out.append(f"- {tag}{sk}**{x['code']}** {x['label']} {x['where']}{note}")
            if x["body"] is not None:
                out.append(f"  > {x['body'][:260]}{'…' if len(x['body']) > 260 else ''}")
    out += [f"- ⚠ 找不到 {m}（主題表需修正）" for m in d["missing"]]
    if d["tools"]:
        out.append("\n## 本工作區可用工具")
        out += [f"- `{x}`" for x in d["tools"]]
    if d["notes"]:
        out.append("\n## 注意")
        out += [f"- {x}" for x in d["notes"]]
    if d["others"]:
        out.append(f"\n## 其他提到的條文（關鍵字搜尋，共 {d['others_total']} 筆，列前 {len(d['others'])} 筆）")
        out += [f"- {('【' + x['skip']['tag'] + '】') if x.get('skip') else ''}{x['code']} {x['label']} {x['where']}：{x['snippet']}" for x in d["others"]]
    out.append("\n全文：`regq.py --clause <ID> <條號>`；版次與狀態見 docs\\法規庫總目錄.md")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("q", nargs="*")
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--clause", nargs=2, metavar=("ID", "CLAUSE"))
    ap.add_argument("--topics", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--per", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    con = connect()
    if a.topics:
        for t in load_topics():
            print(f"{t['name']:8s} {'、'.join(t.get('aliases', []))}")
        return 0
    if a.clause:
        s = sources(con).get(a.clause[0])
        rows = get_clause(con, *a.clause)
        if not s or not rows:
            print("not found", a.clause)
            return 1
        _sk = skip_info(a.clause[0], rows[0]["clause"])
        if _sk:
            print(_sk["warn"] + chr(10))
        for r in rows:
            print(f"{s['name']}［{s['status']}］ {label(s, r)} {where(s, r)}\n{r['path']}\n\n{r['text']}\n")
        return 0
    if not a.q:
        ap.print_help()
        return 1
    found = [] if a.search else match_topics(" ".join(a.q), load_topics())
    t = found[0] if found else None
    if t and not a.json:
        print(card(con, t, a.all, a.n, a.per, also=found[1:]))
        return 0
    if t:
        terms = t["aliases"] + [t["name"]]
        hits, total = search(con, terms, a.all, a.n, a.per)
    else:
        hits, total, terms = smart_search(con, " ".join(a.q), a.all, a.n, a.per)
    src = sources(con)
    if a.json:
        print(json.dumps({"topic": t, "total": total, "hits": [
            {"src": r["src"], "code": src[r["src"]]["name"], "status": src[r["src"]]["status"],
             "clause": r["clause"], "title": r["title"], "path": r["path"], "page": r["page"],
             "part": r["part"], "terms_matched": m, "score": sc, "snippet": snippet(r["text"], terms),
             "skip": skip_info(r["src"], r["clause"])}
            for m, sc, r in hits]}, ensure_ascii=False, indent=1))
        return 0
    print(f"「{' '.join(a.q)}」共 {total} 筆，列前 {len(hits)} 筆（每份規範最多 {a.per} 筆）")
    for m, sc, r in hits:
        s = src[r["src"]]
        _sk = skip_info(r["src"], r["clause"])
        print(f"- [{m}/{len(terms)}] {('【' + _sk['tag'] + '】') if _sk else ''}{s['name']} {label(s, r)} {where(s, r)}\n    {snippet(r['text'], terms)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
