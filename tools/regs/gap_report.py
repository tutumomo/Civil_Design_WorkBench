"""缺口待辦清單產生器（2026-11-02）。

把 `verified/_skips.json` 中 status=unrecognized（＝有表／式但尚未轉錄，真缺口）
整理成一份可讀、可排序的待辦清單，並標出「與工作台計算器的相關度」作為優先序。

用法：
    python tools/regs/gap_report.py --out docs/規範入庫_待補缺口清單.md
    python tools/regs/gap_report.py            # 只印到螢幕
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import regq  # noqa: E402
import regs_vtool as T  # noqa: E402
import verified as V  # noqa: E402

SKIPS = HERE / "verified" / "_skips.json"

# 與工作台的相關度：決定補庫順序（工作台有計算器、或案件常用的排前面）
PRIORITY = {
    "urbanroad113": ("高", "工作台有道路幾何相關產出（道路案常用）；市區道路橫斷面、視距、超高"),
    "hwroute115": ("高", "同上，公路路線幾何；公路案常用"),
    "hwslope104": ("高", "工作台 slope_stability 僅圓弧滑動，岩石邊坡缺口直接影響安全性判斷"),
    "found112": ("高", "工作台有 6 個基礎計算器；基礎規範條文直接對應"),
    "rc112": ("高", "工作台 rc_beam／rc_column／rc_design；混凝土規範條文直接對應"),
    "hwdrain107": ("高", "公路排水設計規範：工作台有 channel_hydraulics／culvert_hydraulics，剩附錄的洪水量、管涵荷重、推移載等公式"),
    "hwconst112": ("中", "施工規範的檢驗頻率／材料表；寫品管計畫與預算時會用到"),
    "flexpave91": ("中", "工作台無鋪面厚度設計計算器，但道路案會引用"),
    "wind103full": ("中", "工作台無風力計算器；招牌、圍籬、施工臨時構造會用到"),
    "seis113": ("中", "耐震；擋土牆地震工況與建築物耐震都會引用"),
    "btr_design": ("中", "建築技術規則設計施工編；山坡地開發、建築案常用"),
    "hwbridge": ("低", "橋梁專章；本工作區以小型土木（道路／排水／擋土牆／邊坡／箱涵）為主"),
    "hwbridge104": ("低", "橋梁 RC 專章；同上"),
    "steel99": ("低", "鋼結構；工作台無鋼構計算器，僅鋼構案人工引用"),
    "btr_struct": ("低", "建築構造編；工作台已有 RC／基礎計算器，重疊部分已入庫"),
    "btr_equip": ("低", "建築設備編；非本工作區範疇"),
    "btr_general": ("低", "建築技術規則總則；非設計計算"),
    "sewer_std": ("低", "下水道標準的污水處理廠章節；非本工作區"),
}
ORDER = {"高": 0, "中": 1, "低": 2}


def load_gaps():
    """以 unit 為單位掃描（與 regs_vtool.status 同口徑），只留 flagged 且 skip=unrecognized。"""
    d = json.loads(SKIPS.read_text(encoding="utf-8"))
    skips = {(i["src"], str(i["clause"])): i for i in d.get("items", [])}
    con = regq.connect()
    srcs = regq.sources(con)
    sup = {k for k, v in srcs.items() if "取代" in (v.get("status") or "")}
    agg = {}
    for r in con.execute("SELECT src, clause, page, text FROM unit"):
        sid, clause = r["src"], str(r["clause"])
        if sid in sup or not T.kinds(r["text"]):
            continue
        it = skips.get((sid, clause))
        if not it or it.get("status") != "unrecognized":
            continue
        if V.for_clause(sid, clause):
            continue
        g = agg.setdefault((sid, clause), {
            "src": sid, "name": srcs.get(sid, {}).get("name", sid), "clause": clause, "pages": [],
            "flagged": 0, "max_len": 0,
            "reason": (it.get("reason") or "").strip(),
            "partial": bool(it.get("partial")), "relevance": it.get("relevance") or "in"})
        g["flagged"] += 1
        if r["page"]:
            g["pages"].append(r["page"])
        g["max_len"] = max(g["max_len"], len(r["text"] or ""))
    for g in agg.values():
        g["pages"] = sorted(set(g["pages"]))
    return list(agg.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    gaps = load_gaps()
    by_src = collections.defaultdict(list)
    for g in gaps:
        by_src[g["src"]].append(g)

    today = datetime.date.today().isoformat()
    tot_flagged = sum(g["flagged"] for g in gaps)
    L = [
        "# 規範入庫：待補缺口清單（真缺口＝有表／式但尚未轉錄）",
        "",
        f"> 自動產生於 {today}，指令：`python tools\\regs\\gap_report.py --out docs\\規範入庫_待補缺口清單.md`",
        "> 資料來源：`tools/regs/verified/_skips.json` 中 `status=\"unrecognized\"` 的條文（不含 `qualitative`／`out_of_scope`／`covered`）。",
        "",
        f"- **缺口條號：{len(gaps)} 條；flagged 單元：{tot_flagged} 個**（與 `docs\規範入庫進度.md` 的「辨識失敗」欄同一套統計邏輯，數字應完全相同）",
        "- **這一類不是「沒內容」，也不是「用不到」**——是原文確定有表格或公式、但排版破碎或表身未隨條文擷取，因此還沒轉成已驗證條目。查詢時會顯示【未入庫｜辨識失敗】與【可信度：低】。",
        "- 另有 **B 類排版公式 630 條**（每字元一 span 的數學排版）依使用者指示列為以後待辦，見 `docs\\規範入庫_B類待辦.md`，**不在本清單內**。",
        "",
        "## 優先序建議",
        "",
        "| 優先 | 規範 | 缺口條號 | 理由 |",
        "|---|---|---:|---|",
    ]
    rank = []
    for sid, lst in by_src.items():
        p, why = PRIORITY.get(sid, ("中", "未分類"))
        rank.append((ORDER[p], -len(lst), sid, p, why, lst))
    rank.sort()
    for _, _, sid, p, why, lst in rank:
        L.append(f"| {p} | `{sid}` | {len(lst)} | {why} |")

    L += ["", "---", ""]
    for _, _, sid, p, why, lst in rank:
        name = lst[0]["name"]
        L += [
            f"## `{sid}`　{name}（{len(lst)} 條，優先度：{p}）",
            "",
            f"> {why}",
            "",
            "| 條號 | 頁碼 | flagged 單元 | 原文長度 | 未轉錄原因（原始紀錄） |",
            "|---|---|---:|---:|---|",
        ]
        for g in sorted(lst, key=lambda x: [int(t) if t.isdigit() else 0 for t in x["clause"].replace("-", ".").split(".")]):
            pg = "、".join(f"p.{p_}" for p_ in g["pages"]) or "—"
            reason = g["reason"].replace("|", "／")[:150]
            flag = "（部分入庫）" if g["partial"] else ""
            L.append(f"| `{g['clause']}`{flag} | {pg} | {g['flagged']} | {g['max_len']} | {reason} |")
        L.append("")

    # 已結案：該規範仍有 flagged 單元，但已無 unrecognized 缺口
    con = regq.connect()
    srcs = regq.sources(con)
    sup = {k for k, v in srcs.items() if "取代" in (v.get("status") or "")}
    flagged_by_src = collections.Counter()
    for r in con.execute("SELECT src, text FROM unit"):
        if r["src"] in sup or not T.kinds(r["text"]):
            continue
        flagged_by_src[r["src"]] += 1
    gap_srcs = {g["src"] for g in gaps}
    closed = [(s, n) for s, n in flagged_by_src.items() if s not in gap_srcs]
    L += ["## 已結案（flagged 單元全部有 verified 或非缺口 skip）", "",
          "| 規範 | flagged 單元 |", "|---|---:|"]
    for s, n in sorted(closed, key=lambda x: -x[1]):
        L.append(f"| `{s}`（{srcs[s]['name']}） | {n} |")
    L.append("")

    L += [
        "---",
        "",
        "## 補完後的驗收（照 SOP §3 六道閘門）",
        "",
        "```bat",
        "python tools\\regs\\payload_check.py <payload.json> --fix",
        "python tools\\regs\\merge_shard.py <payload.json> tools\\regs\\verified\\<src>_<n>.json",
        "python tools\\regs\\payload_check.py --library",
        "python tools\\regs\\regs_vtool.py lint",
        "python tools\\regs\\verified_selftest.py",
        "python tools\\regs\\regq_selftest.py",
        "python tools\\regs\\design_conformance.py --out _temp\\design_conformance.md",
        "python tools\\selftest\\regression.py",
        "```",
        "",
        "補完一批後：`regs_vtool.remove_skip(src, clause)` 移除 skip，再重跑本清單。",
        "",
        "",
    ]
    text = "\n".join(L)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"written {a.out}：{len(gaps)} 條 / {tot_flagged} flagged 單元")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
