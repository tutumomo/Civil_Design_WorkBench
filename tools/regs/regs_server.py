"""Design-code lookup server: one query core (regq.py), two front doors.

usage:
  regs_server.py --web [--port 8765] [--host 127.0.0.1]   web page for people  -> http://127.0.0.1:8765/
  regs_server.py --mcp                                     MCP server (stdio) for AI agents
  /design                                                   design-calculation workbench

Both doors call the same regq functions, so a person and an agent asking the same question get
the same clauses. The design workbench calls design_api.py and saves calculation records under
out/design_workbench/runs. Regulation indexes and topics.json remain read-only.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regq  # noqa: E402
import page_assets  # noqa: E402
import verified  # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = HERE / "regs_web.html"
ROOT = HERE.parent.parent
DESIGN_PAGE = ROOT / "tools" / "design" / "workbench_web.html"
sys.path.insert(0, str(ROOT / "tools" / "design"))
sys.path.insert(0, str(ROOT / "tools" / "crosscheck"))
VERSION = "1.1"


# ---------- shared query layer (plain data) ----------

def _next_page(con, sid):
    def f(r):
        x = con.execute("SELECT page FROM unit WHERE src=? AND part=? AND rowid>? AND page IS NOT NULL ORDER BY rowid LIMIT 1",
                        (sid, r["part"] or "", r["rowid"])).fetchone()
        return x[0] if x else None
    return f


def _neighbor_clauses(con, sid, norm_clause):
    s = regq.sources(con).get(sid)
    if not s:
        return None, None
    rows = con.execute(
        "SELECT clause, title, part, page FROM unit WHERE src=? GROUP BY clause ORDER BY MIN(rowid)",
        (sid,),
    ).fetchall()
    clauses = [r["clause"] for r in rows]
    if norm_clause not in clauses:
        return None, None
    idx = clauses.index(norm_clause)
    prev_c = {"clause": rows[idx - 1]["clause"], "label": regq.label(s, rows[idx - 1])} if idx > 0 else None
    next_c = {"clause": rows[idx + 1]["clause"], "label": regq.label(s, rows[idx + 1])} if idx + 1 < len(rows) else None
    return prev_c, next_c


def clause_data(con, sid, clause):
    s = regq.sources(con).get(sid)
    rows = regq.get_clause(con, sid, clause) if s else []
    if not rows:
        return None
    norm_c = rows[0]["clause"]
    fname = con.execute("SELECT file FROM src WHERE id=?", (sid,)).fetchone()[0]
    assets = page_assets.clause_assets(fname, rows, _next_page(con, sid))
    fml = page_assets.formula_list(sid, norm_c)
    prev_c, next_c = _neighbor_clauses(con, sid, norm_c)
    return {"src": sid, "code": s["name"], "status": s["status"], "clause": norm_c,
            "prev_clause": prev_c, "next_clause": next_c,
            "verified": verified.for_clause(sid, norm_c),
            "skip": regq.skip_info(sid, norm_c),
            "formulas": [{"i": i, "tex": f["tex"]} for i, f in enumerate(fml)],
            "parts": [{"label": regq.label(s, r), "where": regq.where(s, r), "path": r["path"], "text": r["text"],
                       "blocks": page_assets.split_blocks(r["text"], sid, norm_c),
                       "part": r["part"] or "", "pdf_pages": a["pages"] if a else []}
                      for r, a in zip(rows, assets)]}


_DIRECT_ALIASES = {
    "水保": ["swc_tech", "swc_handbook", "swc_audit"],
    "水土保持": ["swc_tech", "swc_handbook"],
    "混凝土": ["rc112", "rc100"],
    "rc": ["rc112", "rc100"],
    "下水道": ["sewer_std", "sewer_handbook"],
    "公路排水": ["hw_drain"],
    "基礎": ["found112", "found90"],
    "農路": ["farmroad108"],
    "橋梁": ["bridge_lrfd", "bridge_seis"],
    "耐震": ["bldg_seis111", "bridge_seis"],
    "鋼構": ["steel_lrfd", "steel_asd"],
    "空污": ["airconst110"],
}


def direct_clause_hits(con, q, include_old=False, src_filter=""):
    import re as _re
    qn = regq.norm(str(q or "")).strip()
    if not qn:
        return []
    m = _re.match(
        r"^(?:(?P<prefix>[A-Za-z0-9_一-鿿]+?)\s*)?"
        r"(?:第\s*(?P<num1>\d+(?:-\d+)?)\s*[條點]|§\s*(?P<num2>\d+(?:\.\d+)+|\d+(?:-\d+)?)|(?P<att>(?:附件|附表)[-－]?[一二三四五六七八九十\d]+)|(?P<num3>\d+(?:\.\d+)+|\d+(?:-\d+)?))$",
        qn,
    )
    if not m:
        return []
    prefix = (m.group("prefix") or "").strip().lower()
    raw_tok = m.group("num1") or m.group("num2") or m.group("att") or m.group("num3")
    if not raw_tok:
        return []
    src_map = regq.sources(con)
    cand_sids = []
    if src_filter and src_filter in src_map:
        cand_sids = [src_filter]
    elif prefix:
        for k, sids in _DIRECT_ALIASES.items():
            if k in prefix or prefix in k:
                for sid in sids:
                    if sid in src_map and sid not in cand_sids:
                        cand_sids.append(sid)
        for sid, s in src_map.items():
            if prefix == sid.lower() or prefix in s["name"].lower():
                if sid not in cand_sids:
                    cand_sids.append(sid)
    else:
        for sid in ("swc_tech", "rc112", "sewer_std", "found112", "hw_drain", "farmroad108", "bldg_seis111", "steel_lrfd"):
            if sid in src_map:
                cand_sids.append(sid)
        for sid in src_map:
            if sid not in cand_sids:
                cand_sids.append(sid)

    out = []
    for sid in cand_sids:
        s = src_map[sid]
        if not include_old and not src_filter and s["status"] not in regq.CURRENT:
            continue
        rows = regq.get_clause(con, sid, raw_tok)
        if rows:
            body = " ".join(r["text"] for r in rows)[:260]
            out.append(regq.ref_row(s, rows[0], {"note": "🎯 條號精準直達"}, body=body))
            if len(out) >= 4:
                break
    return out


def browse_source_data(con, sid, n=60):
    s = regq.sources(con).get(sid)
    if not s:
        return {"terms": [sid], "total": 0, "hits": [], "browse_src": sid}
    all_rows = con.execute(
        "SELECT rowid, * FROM unit WHERE src=? GROUP BY clause ORDER BY MIN(rowid)",
        (sid,),
    ).fetchall()
    hits = [
        dict(regq.ref_row(s, r, {}), matched=1, snippet=regq.snippet(r["text"], [], 140))
        for r in all_rows[:n]
        if r["text"].strip() not in ("刪除", "")
    ]
    return {
        "terms": [s["name"]],
        "total": len(all_rows),
        "hits": hits,
        "browse_src": sid,
        "browse_code": s["name"],
        "browse_status": s["status"],
    }


def search_data(con, q, include_old=False, n=15, per=3, src_filter=""):
    if src_filter and not str(q or "").strip():
        return browse_source_data(con, src_filter, max(n, 60))
    src = regq.sources(con)
    direct = direct_clause_hits(con, q, include_old, src_filter)
    raw_n = 200 if src_filter else n
    raw_per = 100 if src_filter else per
    hits, total, terms = regq.smart_search(con, q, include_old or bool(src_filter), raw_n, raw_per)
    if src_filter:
        hits = [(m, sc, r) for m, sc, r in hits if r["src"] == src_filter]
        total = len(hits)
        hits = hits[:n]
    return {
        "terms": terms,
        "total": total,
        "src_filter": src_filter,
        "direct_hits": direct,
        "hits": [
            dict(regq.ref_row(src[r["src"]], r, {}), matched=m, snippet=regq.snippet(r["text"], terms))
            for m, sc, r in hits
        ],
    }


def ask_data(con, q, include_old=False, n=15, per=3, src_filter=""):
    """Topic card when the sentence names a topic, else keyword search."""
    if src_filter and not str(q or "").strip():
        return dict(browse_source_data(con, src_filter, 60), type="search", query=src_filter)
    direct = direct_clause_hits(con, q, include_old, src_filter)
    if not src_filter:
        found = regq.match_topics(q, regq.load_topics())
        if found:
            return {
                "type": "card",
                "query": q,
                "direct_hits": direct,
                "card": regq.card_data(con, found[0], include_old, n, per, also=found[1:]),
            }
    return dict(search_data(con, q, include_old, n, per, src_filter), type="search", query=q)


def topics_data():
    return [
        {
            "name": t["name"],
            "aliases": t.get("aliases", []),
            "scope": t.get("scope", ""),
            "core_count": len(t.get("core", [])),
            "prereq_count": len(t.get("prereq", [])),
            "tools": t.get("tools", []),
        }
        for t in regq.load_topics()
    ]


def sources_data(con):
    rows = con.execute("SELECT s.*, COUNT(u.rowid) AS units FROM src s LEFT JOIN unit u ON u.src = s.id "
                       "GROUP BY s.id ORDER BY s.category, s.id")
    return [{k: r[k] for k in ("id", "name", "authority", "version", "category", "status", "kind", "units")}
            for r in rows]


# ---------- text rendering for agents ----------

def search_text(d):
    if not d["hits"]:
        return f"「{' '.join(d['terms'])}」沒有命中。試試同義詞，或用 regs_list 看主題與規範代號。"
    out = [f"「{' '.join(d['terms'])}」共 {d['total']} 筆，列前 {len(d['hits'])} 筆："]
    for h in d["hits"]:
        tag = f"【{h['skip']['tag']}】" if h.get("skip") else ""
        out.append(f"- [{h['src']} {h['clause']}] {tag}{h['code']} {h['label']} {h['where']}\n    {h['snippet']}")
    out.append("\n全文用 regs_clause(code_id, clause)。")
    return "\n".join(out)


def clause_text(d):
    head = clause_notice(d)
    return (head + chr(10) * 2 if head else "") + _clause_text(d)


def clause_notice(d):
    v = verified.for_clause(d["src"], d["clause"])
    if v:
        sk = d.get("skip")
        if sk and sk.get("status") == "partial":
            return (sk["warn"] + chr(10) * 2
                    + "【已驗證資料可用】已轉錄部分請改用："
                    + "；".join(f"{'regs_formula' if x['kind'] == 'formula' else 'regs_table'}(id={x['id']})" for x in v)
                    + "。**未轉錄部分不得以純文字表式推測。**")
        return ("【已驗證資料可用】本條有結構化公式／表格，計算請改用："
                + "；".join(f"{'regs_formula' if x['kind'] == 'formula' else 'regs_table'}(id={x['id']})" for x in v)
                + "。下方純文字的公式與表格可能亂碼，不得直接取數。")
    txt = " ".join(p["text"] for p in d["parts"])
    messy = (any(ch in txt for ch in "┌│└─") or any(0xF000 <= ord(ch) <= 0xF0FF for ch in txt)
             or " ───" in txt or "式中" in txt)
    sk = d.get("skip")
    low = ("【可信度：低】本條含公式或表格，純文字抽取可能亂碼或錯位，尚無已驗證版本。"
           "引用數值前須回原 PDF／原頁圖核對，不得直接用於設計。")
    if sk:
        # 未轉換／辨識失敗：一律低可信；定性／已涵蓋：只在文字層有表式特徵時才加低可信
        if sk["status"] in ("out_of_scope", "unrecognized"):
            return "【可信度：低】" + sk["warn"]
        return sk["warn"] + (chr(10) + low if messy else "")
    if messy:
        return low
    return ""


def _clause_text(d):
    out = []
    for p in d["parts"]:
        out.append(f"{d['code']}［{d['status']}］ {p['label']} {p['where']}\n{p['path']}\n\n{p['text']}")
    return "\n\n".join(out)


def list_text(con):
    out = ["## 設計主題（regs_ask 用主題名或口語句即可）"]
    out += [f"- {t['name']}：{'、'.join(t['aliases'])}" for t in topics_data()]
    out.append("\n## 規範代號（regs_clause 的 code_id）")
    out += [f"- {s['id']}：{s['name']}［{s['status']}］{s['category']}，{s['units']} 條" for s in sources_data(con)]
    return "\n".join(out)


# ---------- MCP (stdio, JSON-RPC 2.0, newline-delimited) ----------

MCP_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

MCP_TOOLS = [
    {"name": "regs_ask",
     "description": "查台灣土木／水保／建築設計規範。給設計主題或口語句（例：「設計一個沉砂池」「擋土牆基礎承載力」），"
                    "回傳設計依據卡：核心條文（含原文摘錄）、前置計算條文、本工作區可用工具、注意數值；"
                    "沒有對到主題時改做關鍵字搜尋。設計任何構造物或引用規範前先呼叫。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "設計主題或口語問句"},
         "include_superseded": {"type": "boolean", "description": "含已被取代的舊版規範（預設否）"}},
         "required": ["query"]}},
    {"name": "regs_search",
     "description": "以關鍵字搜尋 34 部規範共 13,068 個條文／點次／附件單元（命中詞越多、命中標題者排越前）。多個詞用空白分隔。",
     "inputSchema": {"type": "object", "properties": {
         "terms": {"type": "string", "description": "關鍵字，空白分隔，例：「泥砂生產量 USLE」"},
         "include_superseded": {"type": "boolean"},
         "max_hits": {"type": "integer", "description": "最多幾筆（預設 15）"},
         "per_code": {"type": "integer", "description": "每部規範最多幾筆（預設 3）"}},
         "required": ["terms"]}},
    {"name": "regs_clause",
     "description": "取單一條文全文。code_id 為規範代號（如 swc_tech、sewer_std、rc112），"
                    "clause 為條號（法規如 93、159-1；PDF 規範如 7.3.4；施工規範如 02742/1.2；"
                    "農路點次如 11；附表／附件如「附件-2」或「附表二」）。",
     "inputSchema": {"type": "object", "properties": {
         "code_id": {"type": "string"}, "clause": {"type": "string"}},
         "required": ["code_id", "clause"]}},
    {"name": "regs_formula",
     "description": "取「已驗證」的規範公式並直接計算（來源條文、單位、適用範圍、條件檢核、測試案例皆已建檔）。"
                    "引用規範公式做計算時一律用本工具，不要從 regs_clause 的亂碼文字抄數字或自行心算。"
                    "只給 query（關鍵字）→ 列出符合的公式；給 id → 回傳公式定義（變數、單位、範圍）；"
                    "給 id＋inputs → 計算並回傳數值、中間值、警示。status 非 verified 或無技師簽認會在警示說明。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "關鍵字，例：曼寧、降雨強度、滯洪量"},
         "id": {"type": "string", "description": "公式 id，例：swc16_intensity"},
         "inputs": {"type": "object", "description": "變數名→數值，單位依公式定義"}}}},
    {"name": "regs_table",
     "description": "取「已驗證」的規範表格數值（逕流係數、最小安全係數、容許流速、φ 等），結構化、帶單位與出處。"
                    "給 query → 列出符合的表；給 id → 整表；id＋row（＋col）→ 單一數值；內插表可給 x。範圍值為 [下限, 上限]。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "id": {"type": "string"}, "row": {"type": "string"},
         "col": {"type": "string"}, "x": {"type": "number"}}}},
    {"name": "regs_list",
     "description": "列出所有設計主題（含同義詞）與規範代號、名稱、版次狀態。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "design_list",
     "description": "列出本機土木／水保／結構設計計算器（擋土牆、箱涵、排水、滯洪池、"
                    "建築樑柱、基礎、RC、水文、沉砂池、邊坡）。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "design_show",
     "description": "顯示單一設計計算器的用途、輸入 JSON 範例、規範依據與已知限制。",
     "inputSchema": {"type": "object", "properties": {
         "calculator": {"type": "string", "description": "design_list 回傳的計算器 id"}},
         "required": ["calculator"]}},
    {"name": "design_run",
     "description": "執行一個設計計算器。先 design_show 取得輸入範例，再傳完整 payload；"
                    "回傳共同檢核表、摘要、限制與可追溯 JSON 紀錄。計算公式只在 "
                    "tools/design 引擎內執行，智能體不得自行心算替代。",
     "inputSchema": {"type": "object", "properties": {
         "calculator": {"type": "string", "description": "design_list 回傳的計算器 id"},
         "payload": {"type": "object", "description": "該計算器的 JSON 輸入"},
         "persist": {"type": "boolean", "description": "是否保存到 out/design_workbench/runs（預設是）"}},
         "required": ["calculator", "payload"]}},
]

MCP_INSTRUCTIONS = ("台灣土木／水保／建築設計規範查詢（本機索引，唯讀）。設計構造物前先用 regs_ask 取得依據卡，"
                    "引用條文前用 regs_clause 讀全文。需要數值設計時先用 design_list／design_show，"
                    "再以 design_run 呼叫確定性引擎；不可用聊天文字取代計算。"
                    "規範公式與表格數值一律用 regs_formula／regs_table（已驗證、帶單位與適用條件）；regs_clause 純文字的公式表格可能亂碼，"
                    "標示【可信度：低】者不得直接取數，須回原 PDF 核對。")


def mcp_call(con, name, a):
    old = bool(a.get("include_superseded"))
    if name == "regs_ask":
        q = str(a.get("query", "")).strip()
        if not q:
            raise ValueError("query 不可空白")
        found = regq.match_topics(q, regq.load_topics())
        if found:
            return regq.card(con, found[0], old, 15, 3, also=found[1:])
        return search_text(search_data(con, q, old))
    if name == "regs_search":
        terms = str(a.get("terms", "")).strip()
        if not terms:
            raise ValueError("terms 不可空白")
        return search_text(search_data(con, terms, old, int(a.get("max_hits") or 15), int(a.get("per_code") or 3)))
    if name == "regs_clause":
        d = clause_data(con, str(a.get("code_id", "")), str(a.get("clause", "")))
        if not d:
            raise ValueError(f"找不到 {a.get('code_id')} {a.get('clause')}；用 regs_search 找條號，或 regs_list 看代號")
        return clause_text(d)
    if name == "regs_formula":
        fid, q = str(a.get("id", "")).strip(), str(a.get("query", "")).strip()
        if fid and isinstance(a.get("inputs"), dict):
            return verified.format_text(verified.evaluate(fid, a["inputs"]))
        if fid:
            f, _ = verified.load()
            if fid not in f:
                raise ValueError(f"沒有公式 {fid}；用 query 搜尋")
            x = f[fid]
            return json.dumps({k: x.get(k) for k in ("id", "title", "src", "clause", "page", "latex", "vars", "defs", "expr", "unit",
                                                     "conditions", "notes", "status", "engineer_signed")}, ensure_ascii=False, indent=1)
        hits = [h for h in verified.search(q) if h["kind"] == "formula"] if q else \
            [dict(verified._brief(x), kind="formula") for x in verified.load()[0].values()]
        return chr(10).join(f"- {h['id']}｜{h['title']}｜{h['src']} {h['clause']}｜{h['status']}" for h in hits) or "沒有符合的已驗證公式（可改用 regs_clause 讀原文，但數值須回原頁圖核對）"
    if name == "regs_table":
        tid, q = str(a.get("id", "")).strip(), str(a.get("query", "")).strip()
        if tid:
            return verified.format_text(verified.table(tid, a.get("row"), a.get("col"), a.get("x")))
        hits = [h for h in verified.search(q) if h["kind"] == "table"] if q else \
            [dict(verified._brief(x), kind="table") for x in verified.load()[1].values()]
        return chr(10).join(f"- {h['id']}｜{h['title']}｜{h['src']} {h['clause']}｜{h['status']}" for h in hits) or "沒有符合的已驗證表格"
    if name == "regs_list":
        return list_text(con)
    if name == "design_list":
        import design_api
        rows = design_api.list_calculators()
        out = ["## 設計計算器（design_run 的 calculator）"]
        out += [
            f"- {r['id']}｜{r['group']}｜{r['title']}：{r['description']}"
            for r in rows
        ]
        return "\n".join(out)
    if name == "design_show":
        import design_api
        calc = str(a.get("calculator", "")).strip()
        rows = {r["id"]: r for r in design_api.list_calculators()}
        if calc not in rows:
            raise ValueError(f"未知計算器：{calc}")
        return json.dumps(rows[calc], ensure_ascii=False, indent=2)
    if name == "design_run":
        import design_api
        calc = str(a.get("calculator", "")).strip()
        payload = a.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload 必須是 JSON 物件")
        result = design_api.run_calculation(
            calc, payload, persist=bool(a.get("persist", True))
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    raise KeyError(name)


def mcp_handle(con, msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification (e.g. notifications/initialized): no reply
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        result = {"protocolVersion": want if want in MCP_PROTOCOLS else MCP_PROTOCOLS[0],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "regs", "version": VERSION},
                  "instructions": MCP_INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": MCP_TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in MCP_TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            text, err = mcp_call(con, name, params.get("arguments") or {}), False
        except Exception as e:  # tool errors go back to the model, not as protocol errors
            text, err = f"錯誤：{e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def run_mcp():
    con = regq.connect()
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (mcp_handle(con, m) for m in batch) if r is not None]
            reply = (replies if isinstance(msg, list) else replies[0]) if replies else None
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()


# ---------- web ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "regs/" + VERSION

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send(self, code, body, ctype, cache="no-store"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _is_local(self) -> bool:
        """本機來源？交叉驗算會驅動 OCSS 桌面程式，只讓本機請求進來。"""
        host = (self.client_address[0] if self.client_address else "") or ""
        if host in ("127.0.0.1", "::1", "localhost"):
            return True
        return host.startswith("127.")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        old = q.get("all") in ("1", "true")
        if u.path in ("/", "/index.html"):
            return self.send(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if u.path in ("/design", "/design/"):
            return self.send(200, DESIGN_PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        # 自帶的前端資產（KaTeX、自託管字型）；檔案內容固定，允許瀏覽器快取一週
        for vdir in ("katex", "fonts"):
            prefix = f"/vendor/{vdir}/"
            if not u.path.startswith(prefix):
                continue
            base = (HERE / "vendor" / vdir).resolve()
            f = (base / u.path[len(prefix):]).resolve()
            if not f.is_relative_to(base) or not f.is_file():
                return self.json({"error": "not found"}, 404)
            ct = {".js": "text/javascript", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2",
                  ".txt": "text/plain; charset=utf-8"}.get(f.suffix, "application/octet-stream")
            return self.send(200, f.read_bytes(), ct, cache="public, max-age=604800")
        if u.path == "/api/pageauto":
            return self.json(page_assets.auto_page(q.get("src", ""), q.get("part", ""), int(q.get("page", "0"))) or {})
        con = regq.connect()  # one connection per request: sqlite objects are not shared across threads
        try:
            if u.path == "/api/design/catalog":
                import design_api
                return self.json({"calculators": design_api.list_calculators()})
            if u.path == "/api/design/section/capabilities":
                import design_api
                import design_section
                ids = [r["id"] for r in design_api.list_calculators()]
                return self.json({"capabilities": design_section.capability_map(ids)})
            if u.path == "/api/design/crosscheck/capabilities":
                import design_api
                import ocss_live
                ids = [r["id"] for r in design_api.list_calculators()]
                return self.json({"capabilities": ocss_live.capability_map(ids)})
            if u.path == "/api/design/crosscheck/status":
                import ocss_live
                st = ocss_live.status()
                st["local"] = self._is_local()   # 遠端連線看得到狀態，但不能驅動 OCSS
                return self.json(st)
            if u.path == "/api/design/section/file":
                import design_section
                rel = (q.get("path") or "").strip()
                f = os.path.abspath(os.path.join(design_section._out_root(), rel))
                root = os.path.abspath(design_section._out_root())
                if not f.startswith(root + os.sep) or not os.path.isfile(f):
                    return self.json({"error": "not found"}, 404)
                ctype = {
                    ".pdf": "application/pdf",
                    ".dwg": "application/acad",
                    ".dxf": "image/vnd.dxf",
                    ".png": "image/png",
                }.get(os.path.splitext(f)[1].lower(), "application/octet-stream")
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), ctype)
            if u.path == "/api/design/health":
                import design_api
                return self.json({"ok": True, "version": VERSION,
                                  "calculators": len(design_api.list_calculators())})
            if u.path == "/api/topics":
                return self.json(topics_data())
            if u.path == "/api/sources":
                return self.json(sources_data(con))
            if u.path == "/api/ask":
                text = q.get("q", "").strip()
                sf = q.get("src", "").strip()
                return self.json(ask_data(con, text, old, src_filter=sf) if (text or sf) else {"type": "empty"})
            if u.path == "/api/search":
                sf = q.get("src", "").strip()
                return self.json(dict(search_data(con, q.get("q", ""), old, int(q.get("n", 30)),
                                                  int(q.get("per", 5)), src_filter=sf), type="search", query=q.get("q", "")))
            if u.path in ("/api/pageimg", "/api/pagetables"):
                row = con.execute("SELECT file FROM src WHERE id=?", (q.get("src", ""),)).fetchone()
                pdf = page_assets.find_pdf(row[0], q.get("part", "")) if row else None
                if not pdf:
                    return self.json({"error": "no pdf"}, 404)
                pg = int(q.get("page", "0"))
                if u.path == "/api/pagetables":
                    return self.json(page_assets.pdf_tables(pdf, pg))
                png = page_assets.page_png(pdf, pg)
                return self.send(200, png, "image/png") if png else self.json({"error": "bad page"}, 404)
            if u.path == "/api/formula":
                png = page_assets.formula_png(q.get("src", ""), q.get("clause", ""), int(q.get("i", "0")))
                return self.send(200, png, "image/png") if png else self.json({"error": "not found"}, 404)
            if u.path == "/api/verified":
                return self.json(verified.for_clause(q.get("src", ""), q.get("clause", "")))
            if u.path == "/api/clause":
                d = clause_data(con, q.get("src", ""), q.get("clause", ""))
                return self.json(d) if d else self.json({"error": "not found"}, 404)
            return self.json({"error": "not found"}, 404)
        except Exception as e:
            return self.json({"error": str(e)}, 500)
        finally:
            con.close()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/design/run", "/api/design/section",
                          "/api/design/crosscheck", "/api/design/crosscheck/open"):
            return self.json({"error": "not found"}, 404)
        if u.path.startswith("/api/design/crosscheck") and not self._is_local():
            return self.json({"error": "交叉驗算只接受本機請求"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                return self.json({"error": "invalid content length"}, 413)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            calc = str(body.get("calculator", "")).strip()
            payload = body.get("payload")
            if not isinstance(payload, dict):
                return self.json({"error": "payload 必須是 JSON 物件"}, 400)
            if u.path == "/api/design/crosscheck":
                import ocss_live
                return self.json(ocss_live.run(calc, payload))
            if u.path == "/api/design/crosscheck/open":
                import ocss_live
                return self.json(ocss_live.open_sheet(calc, payload))
            if u.path == "/api/design/section":
                import design_section
                try:
                    res = design_section.generate(
                        calc, payload,
                        unit=str(body.get("unit", "m")),
                        scale=body.get("scale", "auto"),
                        project=str(body.get("project", "") or ""),
                        drafter=str(body.get("drafter", "") or ""),
                        publish=bool(body.get("publish", True)),
                    )
                except design_section.SectionError as ex:
                    return self.json({"ok": False, "error": str(ex)}, 400)
                return self.json(res)
            import design_api
            return self.json(
                design_api.run_calculation(
                    calc, payload, persist=bool(body.get("persist", True))
                )
            )
        except Exception as e:
            return self.json({"error": str(e)}, 500)


def run_web(host, port):
    regq.connect().close()  # fail early if the index is missing
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"規範查詢台：http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/  （Ctrl+C 結束）", flush=True)
    print(f"工程設計工作台：http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/design", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--web", action="store_true")
    g.add_argument("--mcp", action="store_true")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to let other computers on the LAN connect")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.mcp:
        run_mcp()
    else:
        run_web(a.host, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
