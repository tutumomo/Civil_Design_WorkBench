"""Workflow helper for putting regulation formulas/tables into the verified library (see docs/規範公式圖表入庫SOP.md).

  coverage [--src ID] [--top N] [--out FILE]   which clauses still hold formulas/tables without a verified entry
  page <src> <clause|--page N> [--part P]      render the original PDF page(s) of a clause to _temp/regs_pages/look/
  scaffold <formula|table> <id> <src> <clause> print an empty entry to paste into tools/regs/verified/<src>.json
  lint                                         structural rules for every verified entry (also run by verified_selftest)
  locate [--out FILE]                         fill missing page numbers by searching the PDF
  classify [--out FILE]                       pending split: text-transcribable vs needs-the-page
  status [--out FILE]                          progress: flagged vs verified vs skipped per regulation
  find <src> <clause>                          list existing entries for that clause in every shard
  skip <src> <clause> "<reason>" --status covered|qualitative|out_of_scope|unrecognized
                                               record a clause needing no entry (pure text / cells pending)
  new-source <src>                             checklist + coverage for a newly added regulation
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import regq  # noqa: E402
import verified as V  # noqa: E402

TABLE_CAP = re.compile(r"^\s*表\s*[A-Z]?[\d.\-]+", re.M)
FORMULA = re.compile(r"式中|公式|[A-Za-zα-ωΑ-Ω][A-Za-z0-9_,]*\s*[=＝]\s*[\(（A-Za-z0-9α-ω√]|\.{3,}\s*\(\d+\)|\(\d+(?:\.\d+)*-\d+\)")
PUA = re.compile("[\uf000-\uf0ff]")
RULE = re.compile(r"[┌│└─]")


def figure_only(text):
    """Heuristic: a unit that is only a figure/diagram caption has nothing to transcribe as a formula or table.

    圖說類（含「圖 N-N」、文字很短、沒有數字表或式子）不列入可做待辦，避免 backlog 高估。
    """
    t = text.strip()
    if len(t) > 160:
        return False
    has_fig = ("圖" in t) and re.search(r"圖\s*[-－]?\s*\d", t) is not None
    few_numbers = len(re.findall(r"\d", t)) <= 6
    return has_fig and few_numbers


def kinds(text):
    k = set()
    if TABLE_CAP.search(text) or "┌" in text:
        k.add("table")
    if FORMULA.search(text) or PUA.search(text) or "───" in text:
        k.add("formula")
    return k


def priority_set(con):
    """(src, clause) pairs that topic cards cite as core/prereq: fix these first."""
    pri = set()
    for t in regq.load_topics():
        for key in ("core", "prereq"):
            for ref in t.get(key, []):
                pri.add((ref["src"], str(ref["clause"])))
    return pri


SKIPS = HERE / "verified" / "_skips.json"


def load_skips():
    """{(src, clause): item} - clauses already checked and deliberately not entered."""
    if not SKIPS.exists():
        return {}
    d = json.loads(SKIPS.read_text(encoding="utf-8"))
    return {(i["src"], str(i["clause"])): i for i in d.get("items", [])}


SKIP_STATUSES = {
    "covered": "已由 verified 條目涵蓋",
    "qualitative": "定性／無算式表（已人工讀過）",
    "out_of_scope": "非本工作區（原文有表／式，未轉換、未驗證）",
    "unrecognized": "有表／式但辨識失敗（排版破碎／表身未擷取）＝缺口",
}
_LEGACY = {"deferred": "unrecognized"}  # 舊 --status deferred 等同「辨識失敗」


def save_skip(src, clause, reason, status):
    status = _LEGACY.get(status, status)
    if status not in SKIP_STATUSES:
        raise ValueError(f"skip status 必須是 {sorted(SKIP_STATUSES)}（舊 no-content 已拆分，請明確選一類），收到 {status!r}")
    if len((reason or "").strip()) < 12:
        raise ValueError("skip 理由須 ≥12 字元，且須為實質理由")
    d = json.loads(SKIPS.read_text(encoding="utf-8")) if SKIPS.exists() else {"items": []}
    items = [i for i in d["items"] if not (i["src"] == src and str(i["clause"]) == str(clause))]
    items.append({"src": src, "clause": str(clause), "status": status, "reason": reason,
                  "date": __import__("datetime").date.today().isoformat(), "by": "agent"})
    items.sort(key=lambda i: (i["src"], i["clause"]))
    SKIPS.parent.mkdir(parents=True, exist_ok=True)
    SKIPS.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(items)


def remove_skip(src, clause):
    """條文已轉錄入庫後，把它從 _skips.json 移除（避免留下過時的 skip 紀錄）。"""
    d = json.loads(SKIPS.read_text(encoding="utf-8"))
    n0 = len(d["items"])
    d["items"] = [i for i in d["items"] if not (i["src"] == src and str(i["clause"]) == str(clause))]
    SKIPS.write_text(json.dumps(d, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8")
    return n0 - len(d["items"])


def find_entries(src, clause):
    """All verified entries for a src/clause across every shard file (prevents duplicate ids)."""
    out = []
    for f in sorted((HERE / "verified").glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for kind in ("formulas", "tables"):
            for e in d.get(kind, []):
                if e.get("src") != src:
                    continue
                c = str(e.get("clause", "")).strip()
                q = str(clause).strip()
                def _sec_match(cs, qs):
                    cs, qs = cs.strip(), qs.strip()
                    if cs == qs:
                        return True
                    # 母子條號：24.2.4.1 與 24.2.4.1.3 視為同一條（避免漏看已存在的父條目）
                    return cs.startswith(qs + ".") or qs.startswith(cs + ".")
                ok = c == q
                if not ok and "/" in q:
                    qp, qs = q.split("/", 1)
                    if "/" in c:
                        cp, cs = c.split("/", 1)
                        ok = cp.strip() == qp.strip() and _sec_match(cs, qs)
                elif not ok:
                    ok = _sec_match(c.split("/")[-1], q)
                if ok:
                    out.append((f.name, kind[:-1], e["id"], e.get("title", "")))
    return out


def cmd_find(src, clause):
    hits = find_entries(src, clause)
    if not hits:
        print("none - safe to add")
    for f, kind, eid, title in hits:
        print("%-22s %-6s %-34s %s" % (f, kind, eid, title[:40]))
    return 0


def status(out=None, current_only=False):
    """One-screen progress: per regulation, flagged clauses vs verified vs skipped.

    current_only=True 排除已被取代的版本（rc100、seis111 等），與 coverage --current-only 同口徑；
    這些版本依 SOP §4 不轉錄（只留作對照），不計入待辦以免誤導。
    """
    con = regq.connect()
    srcs = {r[0]: r[1] for r in con.execute("SELECT id, status FROM src")}
    files = {r[0]: r[1] for r in con.execute("SELECT id, file FROM src")}
    skips = load_skips()
    rows = con.execute("SELECT src, clause, text FROM unit").fetchall()
    superseded = sorted(s for s, v in srcs.items() if current_only and "取代" in v)
    per = {}
    for r in rows:
        if current_only and r["src"] in superseded:
            continue
        k = kinds(r["text"])
        if not k:
            continue
        d = per.setdefault(r["src"], {"flagged": 0, "done": 0, "covered": 0, "qualitative": 0, "out_of_scope": 0, "unrecognized": 0, "none": 0, "pending": 0})
        d["flagged"] += 1
        ents = V.for_clause(r["src"], r["clause"])
        if ents:
            d["done"] += 1
            # 已入庫但條目 status=pending（原文疑點／來源缺漏）→ 另計待核
            if any(e.get("status") == "pending" for e in ents):
                d["pending"] += 1
            continue
        it = skips.get((r["src"], str(r["clause"])))
        st = _LEGACY.get(it["status"], it["status"]) if it else "none"
        d[st if st in SKIP_STATUSES else "none"] += 1
    keys = ["flagged", "done", "covered", "qualitative", "out_of_scope", "unrecognized", "none", "pending"]
    tot = {k: 0 for k in keys}
    lines = ["# 規範入庫進度（自動產生）", "",
             "| 規範 | 版次 | 疑含公式表格 | 已入庫 | 其中待核 | 已涵蓋 | 定性 | 非本工作區(未轉換) | 辨識失敗(缺口) | 未決定 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s_, d in sorted(per.items(), key=lambda kv: -(kv[1]["unrecognized"] * 1000 + kv[1]["none"] * 1000 + kv[1]["out_of_scope"])):
        lines.append(f"| {s_} | {srcs.get(s_, '')} | {d['flagged']} | {d['done']} | {d['pending']} | {d['covered']} | {d['qualitative']} | {d['out_of_scope']} | {d['unrecognized']} | {d['none']} |")
        for k in keys:
            tot[k] += d[k]
    lines.append(f"| **合計** | | **{tot['flagged']}** | **{tot['done']}** | **{tot['pending']}** | **{tot['covered']}** | **{tot['qualitative']}** | **{tot['out_of_scope']}** | **{tot['unrecognized']}** | **{tot['none']}** |")
    F = max(tot["flagged"], 1)
    converted = tot["done"] + tot["covered"]
    decided = converted + tot["qualitative"] + tot["out_of_scope"]
    lines += ["",
              f"- **已轉換／已涵蓋**（可信賴取數）：{converted}/{tot['flagged']} = **{100.0 * converted / F:.1f}%**",
              f"- **其中待核**：{tot['pending']} 條已入庫但條目 `status=\"pending\"`（原文疑誤或來源缺漏，**查詢時顯示【待核】，不得當已驗證取數**）",
              f"- **已確認無需轉換**（定性，已讀過）：{tot['qualitative']}",
              f"- **有決定但原文未轉換**（非本工作區；查詢時會標警示）：{tot['out_of_scope']}",
              f"- **辨識失敗＝真缺口**：{tot['unrecognized']}；**未決定**：{tot['none']}",
              f"- 「有決定率」（含未轉換）：{decided + tot['unrecognized']}/{tot['flagged']} = {100.0 * (decided + tot['unrecognized']) / F:.1f}%——**這個數字不代表都轉換完了**，看上面前兩項。",
              "- 判準：每一條 flagged 條文都要有 verified 條目或 skip 紀錄；skip 分四類（見 SOP §2 步驟 7）。"]
    if superseded:
        lines.append(f"- 已排除（已被取代、依 SOP §4 不轉錄，僅留作對照）：{'、'.join(superseded)}")
    else:
        lines.append("- ⚠ 本表含已被取代版本（rc100、seis111）；判讀「還要做多少」請改用 `status --current-only`。")
    text = "\n".join(lines)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print("wrote", out)
    return text



def classify(out=None, b_out=None, sample=0):
    """Split pending clauses into A (text-transcribable) and B (typeset math / needs the page).

    Metric: on the clause page, count spans that are single-character or smaller than 8 pt.
    Typeset formulas put every glyph in its own span, so a high share means the page cannot
    be transcribed from the text layer and must be read visually.
    """
    import fitz
    import page_assets as P
    con = regq.connect()
    files = {r[0]: r[1] for r in con.execute("SELECT id, file FROM src")}
    skips = load_skips()
    pending = {}
    for r in con.execute("SELECT src, clause, page, text FROM unit"):
        if not kinds(r["text"]) or V.for_clause(r["src"], r["clause"]):
            continue
        if skips.get((r["src"], str(r["clause"]))):
            continue
        # 只挑「本條文字裡真的有算式或數值表」的條文；只寫「依公式X」的定性條文不列入
        txt = r["text"]
        has_eq = re.search(r"[=＝]\s*[A-Za-z0-9（(λπα-ωΑ-Ω]", txt) is not None
        has_tbl = re.search(r"表\s*[0-9A-Z][\w.\-]*", txt) is not None and len(re.findall(r"\d", txt)) > 12
        if not (has_eq or has_tbl):
            continue
        pending.setdefault(r["src"], []).append((r["clause"], r["page"]))

    stats = {}
    b_list = {}
    for src, items in pending.items():
        a = b = c = 0
        b_items = []
        docs = {}
        for clause, page in items:
            row = con.execute("SELECT part FROM unit WHERE src=? AND clause=? LIMIT 1", (src, str(clause))).fetchone()
            part = (row["part"] or "") if row else ""
            key = part
            if key not in docs:
                pdf = P.find_pdf(files.get(src, ""), part)
                if pdf is None and not part:
                    cand = P.part_pdfs(files.get(src, ""))
                    prefer = [v for k, v in cand.items() if "內文" in k or "本文" in k]
                    pdf = prefer[0] if prefer else (list(cand.values())[0] if cand else None)
                docs[key] = fitz.open(str(pdf)) if pdf else None
            doc = docs[key]
            if doc is None or not page or not (1 <= page <= len(doc)):
                c += 1
                continue
            d = doc[page - 1].get_text("dict")
            spans = [sp for blk in d.get("blocks", []) for ln in blk.get("lines", []) for sp in ln.get("spans", [])]
            if not spans:
                c += 1
                continue
            tiny = sum(1 for sp in spans if len(sp["text"].strip()) <= 1 or sp["size"] < 8)
            if tiny / max(len(spans), 1) > 0.45:
                b += 1
                b_items.append((str(clause), page))
            else:
                a += 1
        stats[src] = {"A": a, "B": b, "C": c}
        b_list[src] = b_items
        for dd in docs.values():
            if dd is not None:
                dd.close()

    tot = {"A": 0, "B": 0, "C": 0}
    lines = ["# 規範待辦分類（自動產生）", "",
             "| 規範 | 可直接文字轉錄(A) | 需看原頁(B) | 無頁碼/無PDF(C) | 合計 |",
             "|---|---:|---:|---:|---:|"]
    for src, st in sorted(stats.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(st.values())
        lines.append(f"| {src} | {st['A']} | {st['B']} | {st['C']} | {n} |")
        for k in tot:
            tot[k] += st[k]
    lines.append(f"| **合計** | **{tot['A']}** | **{tot['B']}** | **{tot['C']}** | **{sum(tot.values())}** |")
    lines += ["",
              "- **A**：頁面以正常文字排版，可用 page_table.py 逐格轉錄。",
              "- **B**：頁面含數學排版（每個字元獨立 span）或字級過小，文字層無法安全重建，**須看原頁或改用視覺工具**。",
              "- **C**：條文沒有頁碼或該規範無 PDF。",
              "- 判準門檻：單字元 span 或 <8 pt 的比例 > 45%（實測 p.398 表22.7.5.1 幾乎全是單字元 span）。"]
    text = "\n".join(lines)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print("wrote", out)
    return text



def next_batch(n=12, src=None, include_B=False):
    """List the next clauses to transcribe, with A/B page type (A = text layer usable).

    Page type is computed once per (src, part, page) and cached, so repeat calls are cheap.
    Sorted by topic-card priority (core/prereq) first, then by source and clause.
    """
    import fitz
    import page_assets as P
    cache_f = ROOT / "_temp" / "regs_pages" / "_spanstats.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    con = regq.connect()
    files = {r[0]: r[1] for r in con.execute("SELECT id, file FROM src")}
    status = {r[0]: r[1] for r in con.execute("SELECT id, status FROM src")}
    pri = priority_set(con)
    skips = load_skips()
    rows = con.execute("SELECT src, clause, title, page, part, text FROM unit" +
                       (" WHERE src=?" if src else ""), (src,) if src else ()).fetchall()
    docs = {}
    out = []
    for r in rows:
        if not kinds(r["text"]) or V.for_clause(r["src"], r["clause"]):
            continue
        if skips.get((r["src"], str(r["clause"]))):
            continue
        # 只挑「本條文字裡真的有算式或數值表」的條文；只寫「依公式X」的定性條文不列入
        txt = r["text"]
        has_eq = re.search(r"[=＝]\s*[A-Za-z0-9（(λπα-ωΑ-Ω]", txt) is not None
        has_tbl = re.search(r"表\s*[0-9A-Z][\w.\-]*", txt) is not None and len(re.findall(r"\d", txt)) > 12
        if not (has_eq or has_tbl):
            continue
        if "取代" in status.get(r["src"], ""):
            continue
        part = r["part"] or ""
        key = f'{r["src"]}|{part}|{r["page"]}'
        if key not in cache:
            if key.split("|")[2] in ("", "None"):
                cache[key] = "C"
            else:
                if (r["src"], part) not in docs:
                    pdf = P.find_pdf(files.get(r["src"], ""), part)
                    if pdf is None and not part:
                        cand = P.part_pdfs(files.get(r["src"], ""))
                        prefer = [v for k, v in cand.items() if "內文" in k or "本文" in k]
                        pdf = prefer[0] if prefer else (list(cand.values())[0] if cand else None)
                    docs[(r["src"], part)] = fitz.open(str(pdf)) if pdf else None
                doc = docs[(r["src"], part)]
                pg = int(r["page"])
                if doc is None or not (1 <= pg <= len(doc)):
                    cache[key] = "C"
                else:
                    d = doc[pg - 1].get_text("dict")
                    spans = [sp for blk in d.get("blocks", []) for ln in blk.get("lines", [])
                             for sp in ln.get("spans", [])]
                    if not spans:
                        cache[key] = "C"
                    else:
                        tiny = sum(1 for sp in spans if len(sp["text"].strip()) <= 1 or sp["size"] < 8)
                        cache[key] = "B" if tiny / len(spans) > 0.45 else "A"
        kind = cache[key]
        if kind == "C" or str(r["clause"]) == "0":
            continue
        if kind == "B" and not include_B:
            continue
        out.append((0 if (r["src"], str(r["clause"])) in pri else 1, r["src"], str(r["clause"]),
                    int(r["page"] or 0), kind, (r["title"] or "")[:30]))
    for dd in docs.values():
        if dd is not None:
            dd.close()
    cache_f.parent.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    out.sort()
    lines = [f"## 下一批（{'含 B' if include_B else '僅 A 類'}，共 {len(out)} 條）", "",
             "| 優先 | 規範 | 條號 | 頁 | 型 | 標題 |", "|---:|---|---|---:|---|---|"]
    for pr, sc, cl, pg, kd, ti in out[:n]:
        lines.append(f"| {pr} | {sc} | {cl} | {pg} | {kd} | {ti} |")
    return chr(10).join(lines)

def locate(out=None):
    """Fill missing unit.page by searching the source PDF for the clause heading text."""
    import fitz
    import page_assets as P
    con = regq.connect()
    files = {r[0]: r[1] for r in con.execute("SELECT id, file FROM src")}
    rows = con.execute("SELECT rowid, src, clause, title, text, page FROM unit WHERE page IS NULL OR page = 0").fetchall()
    by_src = {}
    for r in rows:
        by_src.setdefault(r["src"], []).append(r)
    fixed = {}
    for src, items in by_src.items():
        pdf = P.find_pdf(files.get(src, ""), "")
        if pdf is None:
            continue
        doc = fitz.open(str(pdf))
        pages = [doc[i].get_text() for i in range(len(doc))]
        n = 0
        for it in items:
            clause = str(it["clause"]).split("/")[-1].strip()
            probe = (it["text"] or "").strip()[:40]
            hit = 0
            if clause and len(clause) >= 3:
                for i, t in enumerate(pages):
                    if clause in t:
                        hit = i + 1
                        break
            if not hit and probe:
                for i, t in enumerate(pages):
                    if probe[:24] in t:
                        hit = i + 1
                        break
            if hit:
                con.execute("UPDATE unit SET page=? WHERE rowid=?", (hit, it["rowid"]))
                n += 1
        con.commit()
        doc.close()
        fixed[src] = (n, len(items))
    lines = ["# 頁碼回填結果", "", "| 規範 | 補到頁碼 | 待補 |", "|---|---:|---:|"]
    for src, (n, tot) in sorted(fixed.items(), key=lambda kv: -kv[1][0]):
        lines.append(f"| {src} | {n} | {tot - n} |")
    text = "\n".join(lines)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print("wrote", out)
    return text


def coverage(src=None, top=40, out=None, current_only=False):
    """Backlog of clauses holding formulas/tables without a verified entry.

    current_only=True skips superseded editions (rc100, seis111) — policy "現行版優先".
    """
    con = regq.connect()
    status = {r[0]: r[1] for r in con.execute("SELECT id, status FROM src")}
    pri = priority_set(con)
    skips = load_skips()
    skipped_by = {}
    rows = con.execute("SELECT src, clause, title, page, text FROM unit" + (" WHERE src=?" if src else ""), (src,) if src else ()).fetchall()
    per, backlog = {}, []
    fig_skip = 0
    for r in rows:
        k = kinds(r["text"])
        if not k:
            continue
        has = bool(V.for_clause(r["src"], r["clause"]))
        s = per.setdefault(r["src"], {"flagged": 0, "done": 0})
        s["flagged"] += 1
        s["done"] += has
        if not has and figure_only(r["text"]):
            fig_skip += 1
            s["flagged"] -= 1
            continue
        hit = skips.get((r["src"], str(r["clause"])))
        if not has and hit:
            skipped_by[r["src"]] = skipped_by.get(r["src"], 0) + 1
            s["flagged"] -= 1
            continue
        if not has:
            backlog.append({"src": r["src"], "clause": r["clause"], "title": r["title"], "page": r["page"],
                            "kinds": sorted(k), "priority": (r["src"], str(r["clause"])) in pri,
                            "len": len(r["text"])})
    backlog.sort(key=lambda b: (not b["priority"], -("formula" in b["kinds"]), b["src"], b["len"]))
    skipped = sorted(s for s, v in per.items() if current_only and "取代" in status.get(s, ""))
    if current_only:
        for s in skipped:
            per.pop(s, None)
        backlog = [b for b in backlog if b["src"] not in skipped]
    lines = ["# 規範公式／表格入庫待辦（自動產生）" + ("（現行版優先，已排除已被取代版本）" if current_only else ""), "",
             "| 規範 | 版次狀態 | 疑含公式表格的條文 | 已有已驗證條目 | 待辦 |", "|---|---|---|---:|---:|"]
    for s, v in sorted(per.items(), key=lambda kv: -(kv[1]["flagged"] - kv[1]["done"])):
        st = status.get(s, "")
        lines.append(f"| {s} | {st} | {v['flagged']} | {v['done']} | {v['flagged'] - v['done']} |")
    if skipped:
        lines += ["", f"已排除（已被取代）：{'、'.join(skipped)}"]
    if fig_skip:
        lines += ["", f"（另有 {fig_skip} 條屬圖說／圖註，無公式表格可轉錄，已自待辦排除）"]
    if skipped_by:
        tot = sum(skipped_by.values())
        detail = "、".join(f"{k} {v}" for k, v in sorted(skipped_by.items()))
        lines += ["", f"（另有 {tot} 條已人工判定不需入庫（純條文／儲存格待核），登錄於 @@tools/regs/verified/_skips.json@@，明細：{detail}）".replace("@@", chr(96))]
    lines += ["", f"## 優先（設計主題卡引用的核心／前置條文）", ""]
    for b in [b for b in backlog if b["priority"]][:top]:
        lines.append(f"- [{b['src']} {b['clause']}] {b['title'][:30]} p.{b['page']} {'/'.join(b['kinds'])}")
    lines += ["", f"## 其餘（前 {top} 筆）", ""]
    for b in [b for b in backlog if not b["priority"]][:top]:
        lines.append(f"- [{b['src']} {b['clause']}] {b['title'][:30]} p.{b['page']} {'/'.join(b['kinds'])}")
    text = "\n".join(lines)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    return text, per, backlog


def page(src, clause, part="", page_no=None):
    import page_assets as P
    con = regq.connect()
    fname = con.execute("SELECT file FROM src WHERE id=?", (src,)).fetchone()
    if not fname:
        sys.exit(f"沒有規範代號 {src}")
    pages = []
    if page_no:
        pdf = P.find_pdf(fname[0], part)
        pages = [(pdf, page_no)]
    else:
        for r in regq.get_clause(con, src, clause):
            pdf = P.find_pdf(fname[0], r["part"] or "")
            if not pdf:
                continue
            p0 = r["page"] or P.locate_page(pdf, r["text"])
            if p0:
                pages += [(pdf, p) for p in range(p0, p0 + 2)]
    if not pages:
        sys.exit("這份規範沒有 PDF（網頁來源）：直接對照網頁原文轉錄，並在 notes 寫明來源")
    outd = ROOT / "_temp" / "regs_pages" / "look"
    outd.mkdir(parents=True, exist_ok=True)
    for pdf, p in pages:
        f = outd / f"{src}_{str(clause).replace('/', '_')}_p{p}.png"
        f.write_bytes(P.page_png(pdf, p))
        print(f)


def scaffold(kind, eid, src, clause):
    if kind == "formula":
        e = {"id": eid, "title": "（填：公式名稱）", "src": src, "clause": clause, "page": None,
             "keywords": "（填：搜尋關鍵字）", "unit": "（輸出單位）", "output": "（輸出名）",
             "latex": "（照原頁圖）",
             "vars": {"x": {"desc": "（說明）", "unit": "（單位）", "min": None, "max": None}},
             "defs": [], "expr": "（python 運算式，僅限 + - * / ** 與 sqrt log10 log exp min max abs 等）",
             "conditions": [], "warn_if": [], "notes": "（單位系統、未收錄項、版次差異）",
             "tests": [{"in": {"x": 1}, "out": 0.0, "tol": 1e-9}],
             "status": "pending", "verified": {"method": "", "by": "", "date": ""}}
    else:
        e = {"id": eid, "title": "（填：表名）", "src": src, "clause": clause, "page": None, "kind": "lookup",
             "unit": "（單位）", "columns": ["欄1"], "rows": [{"key": "列1", "values": {"欄1": 0}}],
             "notes": "範圍值寫 [下限, 上限]", "status": "pending", "verified": {"method": "", "by": "", "date": ""}}
    print(json.dumps(e, ensure_ascii=False, indent=1))


def lint():
    """Structural rules for every verified entry, incl. cross-file duplicate ids."""
    problems = _lint_entries()
    seen = {}
    for f in sorted((HERE / "verified").glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in d.get("formulas", []) + d.get("tables", []):
            seen.setdefault(e.get("id"), []).append(f.name)
    for k, files in seen.items():
        if len(files) > 1:
            problems.append(f"重複 id {k}：出現在 {files}（同一條目只能有一個檔案）")

    return problems


def _lint_entries():
    """Rules every entry must satisfy. Returns list of problem strings."""
    bad = []
    f, t = V.load()
    ids = set(f) | set(t)
    con = regq.connect()
    for x in list(f.values()) + list(t.values()):
        i = x["id"]
        for k in ("title", "src", "clause", "status", "verified"):
            if not x.get(k):
                bad.append(f"{i}: 缺欄位 {k}")
        if x["status"] == "pending" and "待核" not in (x.get("notes") or ""):
            bad.append(f"{i}: status=pending 但 notes 未以【待核】說明疑點（SOP §2 步驟4）")
        if x["status"] == "verified":
            vv = x.get("verified") or {}
            if not (vv.get("method") and vv.get("by") and vv.get("date")):
                bad.append(f"{i}: status=verified 但 verified.method/by/date 不完整")
            # 例外：原文為 ODT/HTML 或無分頁之規範（頁碼不存在，不可捏造）
            #  swc_* 水保技術規範（章本轉出）、sewer* 下水道設計標準（條文式無頁）、
            #  btr* 建築技術規則（條文式）、airconst* 營建空污（條文式）、
            #  farmroad* 農路設計規範（附表為 .odt 檔，無分頁）
            #  pcc* 公共工程施工綱要規範（314 個 .odt/.doc 章本，無分頁）
            if not x.get("page") and not x["src"].startswith(
                    ("swc_", "sewer", "btr", "airconst", "farmroad", "pcc")):
                bad.append(f"{i}: PDF 規範的 verified 條目須填 page（原頁碼）")
        if not con.execute("SELECT 1 FROM src WHERE id=?", (x["src"],)).fetchone():
            bad.append(f"{i}: 規範代號 {x['src']} 不在索引")
        if x in f.values():
            for k in ("unit", "output", "vars", "expr", "latex"):
                if not x.get(k):
                    bad.append(f"{i}: 公式缺 {k}")
            if x["status"] == "verified" and not [c for c in x.get("tests", []) if c.get("out") is not None or c.get("xcheck")]:
                bad.append(f"{i}: verified 公式至少要有一個測試案例")
            for n, v in x.get("vars", {}).items():
                if not v.get("unit") or not v.get("desc"):
                    bad.append(f"{i}: 變數 {n} 缺 unit/desc")
            try:
                V._compile(x["expr"])
                for _, e in x.get("defs", []):
                    V._compile(e)
            except Exception as e:
                bad.append(f"{i}: 運算式不合法 {e}")
        else:
            if not x.get("rows") or not x.get("columns"):
                bad.append(f"{i}: 表缺 rows/columns")
    lf = V.DIR / "_links.json"
    if lf.exists():
        for calc, lst in json.loads(lf.read_text(encoding="utf-8")).items():
            for i in lst:
                if i not in ids:
                    bad.append(f"_links.json: {calc} 指向不存在的 {i}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage"); c.add_argument("--src"); c.add_argument("--current-only", action="store_true"); c.add_argument("--top", type=int, default=40); c.add_argument("--out")
    p = sub.add_parser("locate"); p.add_argument("--out", default="")
    p = sub.add_parser("classify"); p.add_argument("--out", default=""); p.add_argument("--b-out", default="")
    p = sub.add_parser("status"); p.add_argument("--out", default=""); p.add_argument("--current-only", action="store_true")
    p = sub.add_parser("next"); p.add_argument("-n", type=int, default=12); p.add_argument("--src"); p.add_argument("--include-b", action="store_true")
    p = sub.add_parser("find"); p.add_argument("src"); p.add_argument("clause")
    p = sub.add_parser("skip"); p.add_argument("src"); p.add_argument("clause"); p.add_argument("reason")
    p.add_argument("--status", required=True, choices=sorted(SKIP_STATUSES) + ["deferred"])
    p = sub.add_parser("page"); p.add_argument("src"); p.add_argument("clause", nargs="?", default=""); p.add_argument("--part", default=""); p.add_argument("--page", type=int)
    s = sub.add_parser("scaffold"); s.add_argument("kind", choices=["formula", "table"]); s.add_argument("id"); s.add_argument("src"); s.add_argument("clause")
    sub.add_parser("lint")
    n = sub.add_parser("new-source"); n.add_argument("src")
    a = ap.parse_args()
    if a.cmd == "coverage":
        text, _, _ = coverage(a.src, a.top, a.out, a.current_only)
        print(text)
    elif a.cmd == "locate":
        print(locate(a.out or None))
    elif a.cmd == "classify":
        print(classify(a.out or None, b_out=(getattr(a, "b_out", "") or None)))
    elif a.cmd == "status":
        print(status(a.out or None, current_only=getattr(a, "current_only", False)))
    elif a.cmd == "next":
        print(next_batch(a.n, a.src, a.include_b))
    elif a.cmd == "find":
        return cmd_find(a.src, a.clause)
    elif a.cmd == "skip":
        print("skips now:", save_skip(a.src, a.clause, a.reason, a.status))
    elif a.cmd == "page":
        page(a.src, a.clause, a.part, a.page)
    elif a.cmd == "scaffold":
        scaffold(a.kind, a.id, a.src, a.clause)
    elif a.cmd == "lint":
        bad = lint()
        print("\n".join(bad) or "lint ok")
        sys.exit(1 if bad else 0)
    elif a.cmd == "new-source":
        print(f"新規範 {a.src} 入庫檢查：\n 1 build_catalog.py META 已登錄、build_index.py 已重建\n 2 有 PDF → 跑 MinerU 草稿（SOP §3）\n 3 下列為待辦：")
        text, _, _ = coverage(a.src, 30)
        print(text)


if __name__ == "__main__":
    main()
