"""Build a self-contained Cloudflare Worker / Pages bundle for both front doors:
  - `/`        -> 規範查詢台 (`tools/regs/regs_web.html`)
  - `/design`  -> 工程設計工作台 (`tools/design/workbench_web.html`)

Usage:
    C:\\Python312\\python.exe -E -P -X utf8 tools/design/build_cloudflare.py [--out DIR]

The generated bundle in `_temp/cloudflare_deploy` includes:
  - `public/index.html` (規範查詢台 UI - `regs_web.html`)
  - `public/design/index.html` (工程設計工作台 UI - `workbench_web.html`)
  - `public/vendor/katex/*` (KaTeX math rendering assets)
  - `public/vendor/fonts/*` (self-hosted Noto Sans TC / IBM Plex Mono, SIL OFL 1.1)
  - `public/api/regs/*` (topics, sources, 29 pre-built topic cards, 64 clause buckets, search index, formula PNGs)
  - `public/api/design/catalog.json`, `health.json`, `verified_entries.json`, `py_bundle.json`
  - `worker.js` & `wrangler.toml`
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (HERE, ROOT / "tools" / "regs", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import design_api  # noqa: E402
import page_assets  # noqa: E402
import regq  # noqa: E402
import regs_server  # noqa: E402
import verified  # noqa: E402
from project_paths import temp_dir  # noqa: E402


def fnv1a_bucket(key: str, num_buckets: int = 64) -> int:
    h = 2166136261
    for ch in key:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h % num_buckets


WORKER_JS = """let _topicsCache = null;
let _searchCache = null;
let _fmlIndexCache = null;

function fnv1aBucket(key, numBuckets = 64) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h % numBuckets;
}

function norm(s) {
  return String(s || "").normalize("NFKC");
}

function normalizeClauseId(clause) {
  let c = norm(clause).trim().replace(/\\s+/g, "");
  const cnNum = {"一":"1","二":"2","三":"3","四":"4","五":"5","六":"6","七":"7","八":"8","九":"9","十":"10"};
  let m = c.match(/^(?:附件|附表)[-－]?(.+)$/);
  if (m) {
    const tok = m[1];
    return "附件-" + (cnNum[tok] || tok);
  }
  m = c.match(/^第?(\\d+(?:-\\d+)?)(?:條|點)?$/);
  if (m) return m[1];
  return c;
}

function matchTopics(q, topics) {
  q = norm(q).trim();
  for (const t of topics) {
    const aliases = t.aliases || [];
    if (q === t.name || aliases.includes(q)) return [t];
  }
  const scored = [];
  for (const t of topics) {
    const words = [t.name, ...(t.aliases || [])];
    let maxLen = 0;
    for (const w of words) {
      if (w.length >= 2 && q.includes(w) && w.length > maxLen) maxLen = w.length;
    }
    if (maxLen > 0) scored.push([maxLen, t]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.map(x => x[1]);
}

function makeSnippet(text, terms, width = 160) {
  const t = String(text || "").replace(/\\s+/g, " ");
  let pos = -1;
  for (const x of terms) {
    const idx = t.indexOf(norm(x));
    if (idx >= 0 && (pos < 0 || idx < pos)) pos = idx;
  }
  if (pos < 0) pos = 0;
  const a = Math.max(0, pos - Math.floor(width / 3));
  return (a > 0 ? "…" : "") + t.slice(a, a + width) + (a + width < t.length ? "…" : "");
}

const DIRECT_ALIASES = {
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
  "空污": ["airconst110"]
};

function directClauseHits(idxData, q, includeOld = false, srcFilter = "") {
  const qn = norm(q).trim();
  if (!qn) return [];
  const m = qn.match(/^(?:([A-Za-z0-9_\\u4e00-\\u9fff]+?)\\s*)?(?:第\\s*(\\d+(?:-\\d+)?)\\s*[條點]|§\\s*(\\d+(?:\\.\\d+)+|\\d+(?:-\\d+)?)|((?:附件|附表)[-－]?[一二三四五六七八九十\\d]+)|(\\d+(?:\\.\\d+)+|\\d+(?:-\\d+)?))$/);
  if (!m) return [];
  const prefix = (m[1] || "").trim().toLowerCase();
  const rawTok = m[2] || m[3] || m[4] || m[5];
  if (!rawTok) return [];
  const normC = normalizeClauseId(rawTok);
  const srcs = idxData.srcs || {};
  const rows = idxData.rows || [];
  const candSids = [];
  if (srcFilter && srcs[srcFilter]) {
    candSids.push(srcFilter);
  } else if (prefix) {
    for (const [k, sids] of Object.entries(DIRECT_ALIASES)) {
      if (k.includes(prefix) || prefix.includes(k)) {
        for (const sid of sids) if (srcs[sid] && !candSids.includes(sid)) candSids.push(sid);
      }
    }
    for (const [sid, s] of Object.entries(srcs)) {
      if (prefix === sid.toLowerCase() || (s.name || "").toLowerCase().includes(prefix)) {
        if (!candSids.includes(sid)) candSids.push(sid);
      }
    }
  } else {
    for (const sid of ["swc_tech", "rc112", "sewer_std", "found112", "hw_drain", "farmroad108", "bldg_seis111", "steel_lrfd"]) {
      if (srcs[sid]) candSids.push(sid);
    }
    for (const sid of Object.keys(srcs)) {
      if (!candSids.includes(sid)) candSids.push(sid);
    }
  }
  const out = [];
  for (const sid of candSids) {
    const s = srcs[sid];
    if (!s) continue;
    if (!includeOld && !srcFilter && String(s.status || "").startsWith("已被取代")) continue;
    const hitRow = rows.find(r => r[0] === sid && r[1] === normC);
    if (hitRow) {
      out.push({
        src: sid,
        code: s.name,
        status: s.status,
        clause: hitRow[1],
        label: hitRow[5],
        where: hitRow[4],
        path: hitRow[3],
        note: "🎯 條號精準直達",
        body: hitRow[6] || "",
        messy: !!hitRow[9],
        formulas: hitRow[10] || 0,
        table_html: "",
        skip: hitRow[8] || null
      });
      if (out.length >= 4) break;
    }
  }
  return out;
}

function browseSourceOnIndex(idxData, sid, n = 60) {
  const srcs = idxData.srcs || {};
  const s = srcs[sid];
  if (!s) return { terms: [sid], total: 0, hits: [], browse_src: sid };
  const rows = (idxData.rows || []).filter(r => r[0] === sid);
  const hits = rows.slice(0, n).map(r => ({
    src: sid,
    code: s.name,
    status: s.status,
    clause: r[1],
    label: r[5],
    where: r[4],
    path: r[3],
    note: "",
    body: null,
    messy: !!r[9],
    formulas: r[10] || 0,
    table_html: "",
    skip: r[8] || null,
    matched: 1,
    snippet: makeSnippet(r[6], [], 140)
  }));
  return {
    terms: [s.name],
    total: rows.length,
    hits,
    browse_src: sid,
    browse_code: s.name,
    browse_status: s.status
  };
}

function runSearchOnIndex(idxData, rawTerms, includeOld = false, n = 15, per = 3, srcFilter = "") {
  const terms = rawTerms.map(t => norm(t).trim()).filter(Boolean);
  if (!terms.length) return { hits: [], total: 0, terms: [] };
  const srcs = idxData.srcs || {};
  const rows = idxData.rows || [];
  const matchedRows = [];
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    // r: [src, clause, title, path, where, label, text, isCurrent, skip, messy, formulas]
    if (srcFilter && r[0] !== srcFilter) continue;
    if (!includeOld && !srcFilter && !r[7]) continue;
    const title = r[2] || "";
    const path = r[3] || "";
    const text = r[6] || "";
    let matched = 0;
    let score = 0;
    for (const t of terms) {
      const ti = title.includes(t) ? 1 : 0;
      const pa = path.includes(t) ? 1 : 0;
      let c = 0;
      let pos = text.indexOf(t);
      while (pos !== -1 && c < 5) {
        c++;
        pos = text.indexOf(t, pos + Math.max(1, t.length));
      }
      if (c > 0 || ti || pa) matched += 1;
      score += 10 * ti + 3 * pa + c;
    }
    if (matched > 0) {
      matchedRows.push([matched, score, r]);
    }
  }
  matchedRows.sort((a, b) => (b[0] - a[0]) || (b[1] - a[1]));
  const out = [];
  const countBySrc = {};
  const effPer = srcFilter ? 100 : per;
  for (const [m, sc, r] of matchedRows) {
    const sid = r[0];
    if ((countBySrc[sid] || 0) >= effPer) continue;
    countBySrc[sid] = (countBySrc[sid] || 0) + 1;
    const s = srcs[sid] || { name: sid, status: "現行" };
    out.push({
      src: sid,
      code: s.name,
      status: s.status,
      clause: r[1],
      label: r[5],
      where: r[4],
      path: r[3],
      note: "",
      body: null,
      messy: !!r[9],
      formulas: r[10] || 0,
      table_html: "",
      skip: r[8] || null,
      matched: m,
      snippet: makeSnippet(r[6], terms)
    });
    if (out.length >= n) break;
  }
  return { terms, total: matchedRows.length, hits: out };
}

const FILLER_RE = /我要|我想|請問|幫我|如何|怎麼|怎樣|應該|需要|設計|一個|多少|規定|規範|條文|要做|要|的|是|嗎|呢|？|\\?|，|,|。/g;

function smartSearch(idxData, q, includeOld = false, n = 15, per = 3, srcFilter = "") {
  if (srcFilter && !String(q || "").trim()) {
    return browseSourceOnIndex(idxData, srcFilter, Math.max(n, 60));
  }
  const direct = directClauseHits(idxData, q, includeOld, srcFilter);
  const terms = String(q || "").trim().split(/\\s+/).filter(Boolean);
  let res = runSearchOnIndex(idxData, terms, includeOld, n, per, srcFilter);
  if (res.total > 0 || terms.length > 1) return { ...res, src_filter: srcFilter, direct_hits: direct };
  const chunks = norm(q).split(FILLER_RE).map(c => c.trim()).filter(c => c.length >= 2);
  if (chunks.length && chunks.join(" ") !== terms.join(" ")) {
    res = runSearchOnIndex(idxData, chunks, includeOld, n, per, srcFilter);
    if (res.total > 0) return { ...res, src_filter: srcFilter, direct_hits: direct };
  }
  const grams = [];
  const seen = new Set();
  for (const c of (chunks.length ? chunks : terms)) {
    for (let i = 0; i < c.length - 1; i++) {
      const g = c.slice(i, i + 2);
      if (!seen.has(g)) { seen.add(g); grams.push(g); }
    }
  }
  if (grams.length) {
    res = runSearchOnIndex(idxData, grams, includeOld, n, per, srcFilter);
  }
  return { ...res, src_filter: srcFilter, direct_hits: direct };
}

function jsonResp(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

async function fetchAssetJson(env, reqUrl, assetPath) {
  const res = await env.ASSETS.fetch(new Request(new URL(assetPath, reqUrl)));
  if (!res.ok) return null;
  return await res.json();
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // 1. Design Workbench API
    if (path === "/api/design/catalog" || path === "/api/design/catalog/") {
      return env.ASSETS.fetch(new Request(new URL("/api/design/catalog.json", request.url), request));
    }
    if (path === "/api/design/health" || path === "/api/design/health/") {
      return env.ASSETS.fetch(new Request(new URL("/api/design/health.json", request.url), request));
    }

    // 2. Regulation Lookup API (/api/topics, /api/sources, /api/ask, /api/search, /api/clause, /api/formula, /api/page*)
    if (path === "/api/topics") {
      return env.ASSETS.fetch(new Request(new URL("/api/regs/topics.json", request.url), request));
    }
    if (path === "/api/sources") {
      return env.ASSETS.fetch(new Request(new URL("/api/regs/sources.json", request.url), request));
    }
    if (path === "/api/pageauto") {
      return jsonResp({});
    }
    if (path === "/api/pagetables") {
      return jsonResp([]);
    }
    if (path === "/api/formula") {
      const src = url.searchParams.get("src") || "";
      const clause = url.searchParams.get("clause") || "";
      const idx = url.searchParams.get("i") || "0";
      if (!_fmlIndexCache) {
        _fmlIndexCache = (await fetchAssetJson(env, request.url, "/api/regs/formulas/index.json")) || {};
      }
      const fname = _fmlIndexCache[`${src}:${clause}:${idx}`];
      if (!fname) return jsonResp({ error: "not found" }, 404);
      return env.ASSETS.fetch(new Request(new URL(`/api/regs/formulas/${fname}`, request.url), request));
    }
    if (path === "/api/clause") {
      const src = url.searchParams.get("src") || "";
      const rawClause = url.searchParams.get("clause") || "";
      const normC = normalizeClauseId(rawClause);
      const key = `${src}:${normC}`;
      const b = fnv1aBucket(key, 64);
      const bName = String(b).padStart(2, "0");
      const bucketData = await fetchAssetJson(env, request.url, `/api/regs/clauses/b${bName}.json`);
      if (bucketData && bucketData[key]) {
        return jsonResp(bucketData[key]);
      }
      return jsonResp({ error: "not found" }, 404);
    }
    if (path === "/api/ask") {
      const q = (url.searchParams.get("q") || "").trim();
      const srcFilter = (url.searchParams.get("src") || "").trim();
      const includeOld = ["1", "true"].includes(url.searchParams.get("all") || "");
      if (!q && !srcFilter) return jsonResp({ type: "empty" });
      if (!_searchCache) {
        _searchCache = (await fetchAssetJson(env, request.url, "/api/regs/search_index.json")) || { srcs: {}, rows: [] };
      }
      if (!srcFilter && q) {
        if (!_topicsCache) {
          _topicsCache = (await fetchAssetJson(env, request.url, "/api/regs/topics.json")) || [];
        }
        const found = matchTopics(q, _topicsCache);
        if (found.length > 0) {
          const tIdx = found[0].idx;
          const allFlag = includeOld ? "1" : "0";
          const cardData = await fetchAssetJson(env, request.url, `/api/regs/cards/c_${tIdx}_${allFlag}.json`);
          if (cardData && cardData.card) {
            cardData.query = q;
            cardData.direct_hits = directClauseHits(_searchCache, q, includeOld, "");
            cardData.card.also = found.slice(1).map(x => x.name);
            return jsonResp(cardData);
          }
        }
      }
      const sres = smartSearch(_searchCache, q, includeOld, 15, 3, srcFilter);
      return jsonResp({ ...sres, type: "search", query: q || srcFilter });
    }
    if (path === "/api/search") {
      const q = (url.searchParams.get("q") || "").trim();
      const srcFilter = (url.searchParams.get("src") || "").trim();
      const includeOld = ["1", "true"].includes(url.searchParams.get("all") || "");
      const n = parseInt(url.searchParams.get("n") || "30", 10) || 30;
      const per = parseInt(url.searchParams.get("per") || "5", 10) || 5;
      if (!_searchCache) {
        _searchCache = (await fetchAssetJson(env, request.url, "/api/regs/search_index.json")) || { srcs: {}, rows: [] };
      }
      const sres = smartSearch(_searchCache, q, includeOld, n, per, srcFilter);
      return jsonResp({ ...sres, type: "search", query: q || srcFilter });
    }

    // 3. Page routes: `/` -> 規範查詢台 (`public/index.html`), `/design` -> 工程設計工作台 (`public/design/index.html`)
    if (path === "/design" || path === "/design/") {
      return env.ASSETS.fetch(new Request(new URL("/design/index.html" + url.search, request.url), request));
    }
    if (path === "/" || path === "/index.html") {
      return env.ASSETS.fetch(new Request(new URL("/index.html" + url.search, request.url), request));
    }
    return env.ASSETS.fetch(request);
  }
};
"""


def build_regs_assets(pub: Path) -> dict[str, int]:
    regs_dir = pub / "api" / "regs"
    cards_dir = regs_dir / "cards"
    clauses_dir = regs_dir / "clauses"
    fml_dir = regs_dir / "formulas"
    for d in (regs_dir, cards_dir, clauses_dir, fml_dir):
        d.mkdir(parents=True, exist_ok=True)

    con = regq.connect()
    try:
        # 1. topics.json (with idx for card file lookup) & sources.json
        raw_topics = regq.load_topics()
        topics_out = [
            {
                "idx": idx,
                "name": t["name"],
                "aliases": t.get("aliases", []),
                "scope": t.get("scope", ""),
                "core_count": len(t.get("core", [])),
                "prereq_count": len(t.get("prereq", [])),
                "tools": t.get("tools", []),
            }
            for idx, t in enumerate(raw_topics)
        ]
        (regs_dir / "topics.json").write_text(
            json.dumps(topics_out, ensure_ascii=False), encoding="utf-8"
        )

        srcs_list = regs_server.sources_data(con)
        (regs_dir / "sources.json").write_text(
            json.dumps(srcs_list, ensure_ascii=False), encoding="utf-8"
        )

        # 2. Pre-build all 29 topic cards (for include_old=False and True)
        for idx, t in enumerate(raw_topics):
            for all_flag, inc_old in (("0", False), ("1", True)):
                cdata = {
                    "type": "card",
                    "query": t["name"],
                    "card": regq.card_data(con, t, inc_old, 15, 3, also=()),
                }
                (cards_dir / f"c_{idx}_{all_flag}.json").write_text(
                    json.dumps(cdata, ensure_ascii=False), encoding="utf-8"
                )

        # 3. Pre-render hand-restored formula PNGs (from tools/regs/formulas.json)
        fml_map: dict[str, str] = {}
        f_counter = 0
        for sid, cl_dict in page_assets._formulas().items():
            for cl_id, items in cl_dict.items():
                for i in range(len(items)):
                    png_bytes = page_assets.formula_png(sid, cl_id, i)
                    if png_bytes:
                        fname = f"f_{f_counter}.png"
                        f_counter += 1
                        (fml_dir / fname).write_bytes(png_bytes)
                        fml_map[f"{sid}:{cl_id}:{i}"] = fname
        (fml_dir / "index.json").write_text(
            json.dumps(fml_map, ensure_ascii=False), encoding="utf-8"
        )

        # 4. Pre-build 64 clause buckets + deduplicated search_index.json
        srcs = regq.sources(con)
        by_src_clause: dict[tuple[str, str], list] = {}
        ordered_clauses_by_src: dict[str, list[tuple[str, str]]] = {}
        search_rows = []
        seen_search = set()

        for r in con.execute("SELECT rowid, * FROM unit ORDER BY rowid"):
            sid = r["src"]
            cl = r["clause"]
            if (sid, cl) not in by_src_clause:
                by_src_clause[(sid, cl)] = []
                s_obj = srcs.get(sid)
                if s_obj:
                    ordered_clauses_by_src.setdefault(sid, []).append((cl, regq.label(s_obj, r)))
            by_src_clause[(sid, cl)].append(r)

            txt = r["text"].strip()
            if txt in ("刪除", ""):
                continue
            dedup_key = (sid, cl, r["text"][:200])
            if dedup_key in seen_search:
                continue
            seen_search.add(dedup_key)
            s = srcs[sid]
            messy = bool(regq._MESSY.search(r["text"]))
            fml_cnt = len(page_assets.formula_list(sid, cl))
            search_rows.append([
                sid,
                cl,
                r["title"],
                r["path"],
                regq.where(s, r),
                regq.label(s, r),
                r["text"][:180],
                1 if s["status"] in regq.CURRENT else 0,
                regq.skip_info(sid, cl),
                1 if messy else 0,
                fml_cnt,
            ])

        neighbor_map: dict[tuple[str, str], tuple[dict | None, dict | None]] = {}
        for sid, cl_list in ordered_clauses_by_src.items():
            for i_c, (cl_id, _lbl) in enumerate(cl_list):
                prev_c = {"clause": cl_list[i_c - 1][0], "label": cl_list[i_c - 1][1]} if i_c > 0 else None
                next_c = {"clause": cl_list[i_c + 1][0], "label": cl_list[i_c + 1][1]} if i_c + 1 < len(cl_list) else None
                neighbor_map[(sid, cl_id)] = (prev_c, next_c)

        buckets: list[dict[str, dict]] = [{} for _ in range(64)]
        for (sid, cl), rows in by_src_clause.items():
            s = srcs.get(sid)
            if not s or not rows:
                continue
            first_part = rows[0]["part"]
            part_rows = [r for r in rows if r["part"] == first_part]
            fml = page_assets.formula_list(sid, cl)
            prev_c, next_c = neighbor_map.get((sid, cl), (None, None))
            key = f"{sid}:{cl}"
            b_idx = fnv1a_bucket(key, 64)
            buckets[b_idx][key] = {
                "src": sid,
                "code": s["name"],
                "status": s["status"],
                "clause": cl,
                "prev_clause": prev_c,
                "next_clause": next_c,
                "verified": verified.for_clause(sid, cl),
                "skip": regq.skip_info(sid, cl),
                "formulas": [{"i": i, "tex": f["tex"]} for i, f in enumerate(fml)],
                "parts": [
                    {
                        "label": regq.label(s, r),
                        "where": regq.where(s, r),
                        "path": r["path"],
                        "text": r["text"],
                        "blocks": page_assets.split_blocks(r["text"], sid, cl),
                        "part": r["part"] or "",
                        "pdf_pages": [],
                    }
                    for r in part_rows
                ],
            }

        for b_idx, b_data in enumerate(buckets):
            (clauses_dir / f"b{b_idx:02d}.json").write_text(
                json.dumps(b_data, ensure_ascii=False), encoding="utf-8"
            )

        search_index_payload = {
            "srcs": {k: {"name": v["name"], "status": v["status"]} for k, v in srcs.items()},
            "rows": search_rows,
        }
        (regs_dir / "search_index.json").write_text(
            json.dumps(search_index_payload, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "topics": len(topics_out),
            "sources": len(srcs_list),
            "clauses": len(by_src_clause),
            "search_rows": len(search_rows),
            "formula_pngs": f_counter,
        }
    finally:
        con.close()


def build_bundle(out_dir: Path) -> dict[str, int]:
    pub = out_dir / "public"
    if pub.exists():
        shutil.rmtree(pub)
    (pub / "design").mkdir(parents=True, exist_ok=True)
    (pub / "api" / "design").mkdir(parents=True, exist_ok=True)

    # 1. Copy regs_web.html to public/index.html (`/`) and workbench_web.html to public/design/index.html (`/design`)
    regs_html = (ROOT / "tools" / "regs" / "regs_web.html").read_text(encoding="utf-8")
    design_html = (HERE / "workbench_web.html").read_text(encoding="utf-8")
    (pub / "index.html").write_text(regs_html, encoding="utf-8")
    (pub / "design" / "index.html").write_text(design_html, encoding="utf-8")

    # 1b. Copy vendor assets (KaTeX, self-hosted fonts) to public/vendor/<name>
    for vdir in ("katex", "fonts"):
        vsrc = ROOT / "tools" / "regs" / "vendor" / vdir
        if vsrc.exists():
            shutil.copytree(vsrc, pub / "vendor" / vdir, dirs_exist_ok=True)

    # 2. Build Regulation Lookup static data & buckets
    regs_stats = build_regs_assets(pub)

    # 3. Write catalog.json & health.json for Design Workbench
    calculators = design_api.list_calculators()
    catalog_payload = {
        "schema": "civil-design-catalog/1",
        "count": len(calculators),
        "calculators": calculators,
    }
    (pub / "api" / "design" / "catalog.json").write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    health_payload = {
        "ok": True,
        "calculators": len(calculators),
        "mode": "cloudflare-edge-pyodide",
    }
    (pub / "api" / "design" / "health.json").write_text(
        json.dumps(health_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4. Write verified_entries.json
    fm, tb = verified.load()
    entries = []
    for k, v in fm.items():
        entries.append({
            "id": k, "kind": "formula", "title": v.get("title", ""),
            "src": v.get("src", ""), "clause": v.get("clause", ""),
            "page": v.get("page"), "status": v.get("status", ""),
            "unit": v.get("unit", ""), "expr": v.get("expr", ""),
            "latex": v.get("latex", ""), "vars": v.get("vars", {}),
            "notes": v.get("notes", ""),
        })
    for k, v in tb.items():
        entries.append({
            "id": k, "kind": "table", "title": v.get("title", ""),
            "src": v.get("src", ""), "clause": v.get("clause", ""),
            "page": v.get("page"), "status": v.get("status", ""),
            "unit": v.get("unit", ""), "expr": "",
            "latex": "", "notes": v.get("notes", ""),
        })
    (pub / "api" / "design" / "verified_entries.json").write_text(
        json.dumps({"count": len(entries), "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )

    # 5. Bundle Python files for Pyodide WebAssembly execution
    files_map: dict[str, str] = {}
    files_map["tools/project_paths.py"] = (ROOT / "tools" / "project_paths.py").read_text(encoding="utf-8")
    for py_file in sorted(HERE.glob("*.py")):
        if py_file.name == "build_cloudflare.py":
            continue
        files_map[f"tools/design/{py_file.name}"] = py_file.read_text(encoding="utf-8")
    files_map["tools/regs/verified.py"] = (ROOT / "tools" / "regs" / "verified.py").read_text(encoding="utf-8")
    v_dir = ROOT / "tools" / "regs" / "verified"
    for jf in sorted(v_dir.glob("*.json")):
        files_map[f"tools/regs/verified/{jf.name}"] = jf.read_text(encoding="utf-8")

    (pub / "api" / "design" / "py_bundle.json").write_text(
        json.dumps({"files": files_map}, ensure_ascii=False),
        encoding="utf-8",
    )

    # 6. Write worker.js & wrangler.toml
    (out_dir / "worker.js").write_text(WORKER_JS, encoding="utf-8")
    wrangler_toml = """name = "civil-design-workbench"
account_id = "e2c04af8447f8efcbf6ca597d6d3ad36"
main = "worker.js"
compatibility_date = "2024-11-01"

[assets]
directory = "./public"
binding = "ASSETS"
"""
    (out_dir / "wrangler.toml").write_text(wrangler_toml, encoding="utf-8")
    return {
        "calculators": len(calculators),
        "bundled_files": len(files_map),
        "verified_entries": len(entries),
        **regs_stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Cloudflare deployment bundle for Engineering Design Workbench & Regulation Lookup")
    ap.add_argument("--out", default=None, help="Output directory (defaults to _temp/cloudflare_deploy)")
    args = ap.parse_args()
    out_dir = Path(args.out) if args.out else (temp_dir("cloudflare_deploy"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = build_bundle(out_dir)
    print(f"Built Cloudflare bundle in {out_dir}")
    print(f"  calculators      : {stats['calculators']}")
    print(f"  bundled py/json  : {stats['bundled_files']}")
    print(f"  verified entries : {stats['verified_entries']}")
    print(f"  regs topics      : {stats['topics']}")
    print(f"  regs sources     : {stats['sources']}")
    print(f"  regs clauses     : {stats['clauses']} (64 buckets)")
    print(f"  regs search rows : {stats['search_rows']}")
    print(f"  formula pngs     : {stats['formula_pngs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
