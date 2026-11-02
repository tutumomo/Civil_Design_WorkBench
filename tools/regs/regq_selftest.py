"""Self-test for the code lookup: topic table integrity + fixed exam questions.

Fails (exit 1) when a topics.json reference no longer exists in the index, or when an exam
question does not return the clause it must return. Run after build_index.py / editing topics.

usage: python -E -P -X utf8 regq_selftest.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regq  # noqa: E402
import regs_server  # noqa: E402

# Exam questions live in exams.json so new topics can add one without editing code.
#   exam:  [query, "topic"|"search", [[src, clause], ...], note]
#   route: [spoken sentence, topic it must route to, other topics it must also list ...]
EXAMS = Path(os.environ.get("REGS_EXAMS") or (Path(__file__).resolve().parent / "exams.json"))
_lib = json.loads(EXAMS.read_text(encoding="utf-8"))
EXAM = [(q, mode, [tuple(r) for r in must], note) for q, mode, must, note in _lib["exam"]]
ROUTE = [tuple(x) for x in _lib["route"]]


def mcp_checks(con):
    """The MCP door must answer the same way the CLI does (protocol run in-process)."""
    def call(method, params=None, mid=1):
        return regs_server.mcp_handle(con, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def tool(name, args):
        r = call("tools/call", {"name": name, "arguments": args})["result"]
        return r["isError"], r["content"][0]["text"]

    tool_names = {
        t["name"] for t in call("tools/list")["result"]["tools"]
    }
    required_tools = {
        "regs_ask", "regs_search", "regs_clause", "regs_list",
        "design_list", "design_show", "design_run", "regs_formula", "regs_table",
    }
    checks = [
        ("initialize", call("initialize", {"protocolVersion": "2025-06-18"})["result"]["protocolVersion"] == "2025-06-18"),
        ("tools/list required regs/design tools", required_tools <= tool_names),
        ("notification gets no reply", regs_server.mcp_handle(con, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None),
        ("unknown method -> error", "error" in call("nope/nope")),
    ]
    err, text = tool("regs_ask", {"query": "我要設計一個沉砂池"})
    checks.append(("regs_ask 沉砂池 card", not err and "第 93 條" in text and "第 12 條" in text))
    err, text = tool("regs_ask", {"query": "鋼筋續接長度"})
    checks.append(("regs_ask spoken search", not err and "25.5.2.1" in text))
    err, text = tool("regs_clause", {"code_id": "swc_tech", "clause": "93"})
    checks.append(("regs_clause", not err and "一點五公尺至三點五公尺" in text))
    err, text = tool("regs_formula", {"id": "swc17_rational_qp", "inputs": {"C": 0.9, "I": 100, "A": 36}})
    checks.append(("regs_formula compute", not err and "= 9" in text and "swc_tech 17" in text))
    err, text = tool("regs_formula", {"id": "swc19_t1_overland", "inputs": {"l": 400, "v": 0.4}})
    checks.append(("regs_formula rejects out-of-range", err))
    err, text = tool("regs_table", {"id": "swc73_min_safety_factor", "row": "永久性", "col": "地震"})
    checks.append(("regs_table value", not err and "1.1" in text))
    err, text = tool("regs_clause", {"code_id": "swc_tech", "clause": "16"})
    checks.append(("regs_clause points at verified formula", not err and "regs_formula(id=swc16_intensity)" in text))
    err, text = tool("regs_clause", {"code_id": "swc_tech", "clause": "37"})
    checks.append(("regs_clause low-confidence notice", not err and "可信度：低" in text))
    # 2026-11-02 未入庫條文警示：skip 的條文查得到原文，但必須標明「未轉換、未驗證」
    err, text = tool("regs_clause", {"code_id": "btr_design", "clause": "116-3"})
    checks.append(("regs_clause skip(out_of_scope) warning", not err and "未入庫｜非本工作區" in text and "可信度：低" in text))
    err, text = tool("regs_clause", {"code_id": "found112", "clause": "8.8.4"})
    checks.append(("regs_clause verified clause has no skip warning", not err and "未入庫" not in text))
    err, text = tool("regs_search", {"terms": "照度"})
    checks.append(("regs_search tags skipped clauses", not err and "【未入庫·非本工作區】" in text))
    err, text = tool("regs_clause", {"code_id": "swc_tech", "clause": "9999"})
    checks.append(("regs_clause missing -> isError", err))
    err, text = tool("design_list", {})
    checks.append(
        (
            "design_list includes settlement assessment",
            not err
            and "wall_stability" in text
            and "rc_column" in text
            and "settlement_assessment" in text,
        )
    )
    err, text = tool("design_show", {"calculator": "slope_stability"})
    checks.append(
        (
            "design_show exposes corrected example",
            not err and '"friction_deg": 35.0' in text,
        )
    )
    err, text = tool(
        "design_run",
        {
            "calculator": "rc_beam",
            "payload": {
                "Mu_kNm": 180.0,
                "Vu_kN": 120.0,
                "b_mm": 350.0,
                "h_mm": 750.0,
            },
            "persist": False,
        },
    )
    try:
        design_result = json.loads(text)
    except ValueError:
        design_result = {}
    checks.append(
        (
            "design_run rc_beam with stirrup",
            not err
            and design_result.get("ok") is True
            and any(
                c.get("item") == "剪力（含箍筋）"
                for c in design_result.get("checks", [])
            ),
        )
    )
    # 2026-11-02 規範查詢台三階段優化（Step 1~3）後端與前端契約檢核
    cd17 = regs_server.clause_data(con, "swc_tech", "17")
    checks.append((
        "clause_data prev/next + verified detail",
        bool(cd17)
        and cd17.get("prev_clause", {}).get("clause") == "16"
        and cd17.get("next_clause", {}).get("clause") == "18"
        and bool(cd17.get("verified"))
        and "latex" in cd17["verified"][0]
        and "vars" in cd17["verified"][0],
    ))
    dh93 = regs_server.direct_clause_hits(con, "水保 93")
    checks.append((
        "direct_clause_hits 水保 93 -> swc_tech 93",
        bool(dh93) and dh93[0]["src"] == "swc_tech" and dh93[0]["clause"] == "93",
    ))
    bs = regs_server.browse_source_data(con, "swc_tech", n=10)
    checks.append((
        "browse_source_data swc_tech",
        bs.get("browse_src") == "swc_tech" and bs.get("total", 0) > 100 and len(bs.get("hits", [])) == 10,
    ))
    tdata = regs_server.topics_data()
    checks.append((
        "topics_data includes core_count and tools",
        len(tdata) >= 29 and "core_count" in tdata[0] and "tools" in tdata[0],
    ))
    web_html = (Path(__file__).resolve().parent / "regs_web.html").read_text(encoding="utf-8")
    checks.append((
        "regs_web.html Step 1-3 UI markers present",
        all(
            marker in web_html
            for marker in (
                "buildVerifiedPanelHtml",
                "notes-hero",
                "dCopyCite",
                "TOPIC_GROUPS",
                "topicsearch",
                "src-filter-bar",
                "TOOL_TO_CALCS",
                "civil-regs-basket",
                "basketModal",
            )
        ),
    ))
    bad = 0
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} mcp: {name}")
        bad += not ok
    return bad


def main():
    con = regq.connect()
    topics = regq.load_topics()
    bad = 0
    names = set()
    for t in topics:
        for a in [t["name"]] + t.get("aliases", []):
            if a in names:
                print(f"FAIL alias used twice: {a}")
                bad += 1
            names.add(a)
        for key in ("core", "prereq"):
            for ref in t.get(key, []):
                if not regq.get_clause(con, ref["src"], ref["clause"]):
                    print(f"FAIL {t['name']}: {ref['src']} {ref['clause']} not in index")
                    bad += 1
    print(f"topics: {len(topics)}, refs checked")
    for sid, alias, needle in (
        ("farmroad108", "附表二", "農路二級設計規範"),
        ("airconst110", "附表二", "圍籬高度規定"),
    ):
        rows = regq.get_clause(con, sid, alias)
        ok = bool(rows) and needle in "".join(r["text"] for r in rows)
        print(f"{'ok  ' if ok else 'FAIL'} {sid} {alias} -> {needle}")
        bad += not ok
    for q, mode, must, note in EXAM:
        if mode == "topic":
            t = regq.find_topic(q, topics)
            got = {(r["src"], r["clause"]) for k in ("core", "prereq") for r in (t or {}).get(k, [])}
            label = t["name"] if t else "（無主題）"
        else:
            hits, _ = regq.search(con, [q], n=10, per=10)
            got = {(r["src"], r["clause"]) for _, _, r in hits}
            label = f"top {len(hits)}"
        miss = [m for m in must if m not in got]
        print(f"{'FAIL' if miss else 'ok  '} {q:10s} [{mode}] -> {label}" + (f"  missing {miss}" if miss else ""))
        bad += bool(miss)
    for q, want, *also in ROUTE:
        found = [t["name"] for t in regq.match_topics(q, topics)]
        got = found[0] if found else "（無主題）"
        ok = got == want and all(x in found[1:] for x in also)
        print(f"{'ok  ' if ok else 'FAIL'} {q:10s} [route] -> {' / '.join(found) or got}" + ("" if ok else f"  want {want} {also}"))
        bad += not ok
    bad += mcp_checks(con)
    print(f"{len(EXAM)} exam questions + {len(ROUTE)} routing questions, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
