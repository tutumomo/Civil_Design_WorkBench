r"""單價來源稽核：逐項標示預算書的單價是「查證過的營建物價」還是「假設值」。

為什麼要這個模組
----------------
預算書最容易出問題的地方不是算術，是**單價** —— 而單價往往混了兩種東西：
從營建物價資料庫抄來的（有來源、有期別、有地區），以及自己填的（沒有來源）。

兩者混在同一張詳細表裡、印出來一模一樣，讀的人看不出哪一項可信。
本模組逐項比對 `tools\boq\prices\` 的價格庫，標出：

  · `物價庫` —— 代碼對上，價格取自營建物價（附期別、地區、稅別）
  · `假設值` —— 沒有對應資料，價格是填的

輸出 Markdown 稽核表，並給出「查證覆蓋率」。
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PRICE_DIR = os.path.join(HERE, "prices")


def load_prices(price_dir=None):
    """載入全部價格庫，回傳 {code: {…item…, _lib: 檔名}}。"""
    d = price_dir or PRICE_DIR
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        except Exception:
            continue
        for it in data.get("items") or []:
            code = str(it.get("code") or "").strip()
            if not code:
                continue
            rec = dict(it)
            rec["_lib"] = fn
            rec["_publish"] = (data.get("source") or {}).get("publish_date")
            rec["_tax"] = (data.get("source") or {}).get("tax")
            rec["_region"] = (data.get("source") or {}).get("region_used")
            out[code] = rec
    return out


def audit(items, region="中部"):
    """逐項稽核。items 為預算書工項（含 code / name / unit / price）。"""
    lib = load_prices()
    rows = []
    for it in items:
        code = str(it.get("code") or "").strip()
        price = it.get("price")
        rec = lib.get(code) if code else None
        if rec is None and not code:
            # 沒有資源代碼時，用名稱前 8 字比對（價格庫名稱含更細的規格）
            nm = str(it.get("name") or "")[:8]
            if nm:
                for lc, lr in lib.items():
                    if nm and nm in str(lr.get("name") or ""):
                        rec = lr
                        break
        if rec:
            lp = (rec.get("prices") or {}).get(region)
            same = (lp is not None and price is not None
                    and abs(float(lp) - float(price)) < 1e-6)
            rows.append({
                "no": it.get("no"), "name": it.get("name"), "unit": it.get("unit"),
                "price": price, "source": "物價庫",
                "lib_price": lp, "match": same,
                "ref": "%s（%s%s，%s）" % (rec["_lib"], rec.get("code"),
                                        "，中部" if region else "",
                                        rec.get("_publish") or "期別未載"),
            })
        else:
            rows.append({
                "no": it.get("no"), "name": it.get("name"), "unit": it.get("unit"),
                "price": price, "source": "假設值",
                "lib_price": None, "match": None, "ref": it.get("note") or "—",
            })
    sourced = [r for r in rows if r["source"] == "物價庫"]
    mismatched = [r for r in sourced if r["match"] is False]
    return {"rows": rows, "region": region,
            "n_total": len(rows), "n_sourced": len(sourced),
            "n_assumed": len(rows) - len(sourced),
            "coverage_pct": (100.0 * len(sourced) / len(rows)) if rows else 0.0,
            "mismatched": mismatched}


def format_markdown(res, title="單價來源稽核"):
    L = ["# %s" % title, ""]
    L.append("比對 `tools\\boq\\prices\\` 的價格庫（%s地區）。" % res["region"])
    L.append("")
    L.append("| 項次 | 工項 | 單位 | 單價 | 來源 | 價格庫值 | 依據 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in res["rows"]:
        mark = ("✅" if r["source"] == "物價庫" and r["match"]
                else ("⚠ 不符" if r["match"] is False else "❌ 假設"))
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["no"] or "", r["name"], r["unit"],
            "%.0f" % r["price"] if isinstance(r["price"], (int, float)) else r["price"],
            mark, "%.0f" % r["lib_price"] if r["lib_price"] is not None else "—",
            r["ref"]))
    L.append("")
    L.append("**查證覆蓋率 %.1f%%**（%d／%d 項取自營建物價，%d 項為假設值）"
             % (res["coverage_pct"], res["n_sourced"], res["n_total"], res["n_assumed"]))
    if res["mismatched"]:
        L.append("")
        L.append("⚠ 有 %d 項代碼對上但價格與價格庫不一致，須確認：%s"
                 % (len(res["mismatched"]),
                    "、".join(r["no"] or r["name"] for r in res["mismatched"])))
    L.append("")
    L.append("> 假設值不必然是錯的，但它**沒有查證**。正式預算前應逐項詢價或補進價格庫。")
    return "\n".join(L)


def audit_case(case_path):
    import sys
    HERE2 = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(HERE2), "case_package"))
    import case_core as CC
    case = CC.load(case_path)
    items = (case.get("boq") or {}).get("items") or []
    return audit(items)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="單價來源稽核")
    ap.add_argument("case", help="案件 JSON")
    ap.add_argument("--out", help="輸出 Markdown 路徑")
    ap.add_argument("--region", default="中部")
    a = ap.parse_args()
    res = audit_case(a.case)
    md = format_markdown(res, title="單價來源稽核 — %s" %
                         os.path.basename(os.path.dirname(os.path.abspath(a.case))))
    print(md)
    if a.out:
        open(a.out, "w", encoding="utf-8", newline="\n").write(md)
        print("\n已輸出 %s" % a.out)
