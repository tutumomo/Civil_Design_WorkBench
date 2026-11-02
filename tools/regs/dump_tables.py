"""用 PyMuPDF 的表格結構還原表格，輸出骨架（欄位數、合併格、內容）。

為什麼需要：規範表格常有「表頭跨欄」與「格內上下堆疊多列」。純文字擷取會把堆疊列壓成
一串數字、把合併格拆散，於是你知道有幾個數，卻不知道哪個數屬於哪一欄。本工具先印出
`find_tables()` 的骨架（幾欄幾列、哪些格是空的＝合併格），再讓你帶著這份骨架去核原頁圖。

經驗（§Z.8）：**`find_tables()` 只給骨架、原頁圖定歸屬**——純看 API 會錯欄，純看圖會漏列。

範例::

    # 印出某頁所有表格的骨架
    python tools/regs/dump_tables.py "<pdf>" 22

    # 一次看多頁、順便抓表格標題（表02741-2 這種）
    python tools/regs/dump_tables.py "<pdf>" 22-24 --captions

    # 存成 JSON（交給後續腳本或子代理）
    python tools/regs/dump_tables.py "<pdf>" 22 --save _temp/tables.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def parse_pages(spec: str, total: int) -> list[int]:
    if spec.lower() in ("all", "*"):
        return list(range(1, total + 1))
    out: list[int] = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(tok))
    bad = [p for p in out if p < 1 or p > total]
    if bad:
        sys.exit(f"頁碼超出範圍：{bad}（此 PDF 共 {total} 頁）")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用 PyMuPDF find_tables 還原表格骨架")
    ap.add_argument("pdf", help="PDF 路徑")
    ap.add_argument("pages", help="頁碼：22 / 22-24 / all（1-based，PDF 檔序）")
    ap.add_argument("--captions", action="store_true", help="同時抓頁面上的「表xxxx-x」標題")
    ap.add_argument("--width", type=int, default=18, help="每格顯示寬度（預設 18）")
    ap.add_argument("--max-rows", type=int, default=40, help="每張表最多顯示列數")
    ap.add_argument("--save", help="另存 JSON（原始 extract 結果）")
    ap.add_argument("--json", action="store_true", help="直接輸出 JSON")
    a = ap.parse_args(argv)

    try:
        import fitz
    except ImportError:
        sys.exit("需要 PyMuPDF：pip install pymupdf")
    p = Path(a.pdf)
    if not p.is_file():
        sys.exit(f"找不到 PDF：{p}")

    doc = fitz.open(str(p))
    pages = parse_pages(a.pages, len(doc))
    saved: dict = {}
    report = []

    for pno in pages:
        pg = doc[pno - 1]
        txt = unicodedata.normalize("NFKC", pg.get_text())
        caps = re.findall(r"表\s*[0-9A-Z][0-9A-Za-z\-.]*[^\n]{0,26}", txt) if a.captions else []
        try:
            tabs = pg.find_tables()
        except Exception as e:  # 舊版 PyMuPDF 沒有 find_tables
            sys.exit(f"此 PyMuPDF 版本不支援 find_tables（需 ≥1.23）：{e}")

        entry = {"page": pno, "captions": [c.strip() for c in caps], "tables": []}
        if not a.json:
            print(f"\n=== PDF 第 {pno} 頁：{len(tabs.tables)} 張表"
                  + (f"　標題：{entry['captions']}" if entry["captions"] else ""))
        for k, t in enumerate(tabs.tables):
            rows = t.extract()
            ncol = max((len(r) for r in rows), default=0)
            merged = sum(1 for r in rows for c in r if c is None or str(c).strip() == "")
            entry["tables"].append({"index": k, "bbox": [round(v) for v in t.bbox],
                                    "rows": len(rows), "cols": ncol, "raw": rows})
            saved[f"p{pno}_t{k}"] = rows
            if a.json:
                continue
            print(f"  表{k}: bbox={[round(v) for v in t.bbox]}  {len(rows)} 列 × {ncol} 欄"
                  f"　空/合併格 {merged} 個")
            for ri, r in enumerate(rows[: a.max_rows]):
                cells = []
                for c in r:
                    if c is None:
                        cells.append("（合併）")
                    else:
                        cells.append(re.sub(r"\s+", "|", str(c))[: a.width])
                print(f"    r{ri:<2} " + " | ".join(cells))
            if len(rows) > a.max_rows:
                print(f"    …（另有 {len(rows) - a.max_rows} 列，用 --max-rows 調整）")
        report.append(entry)

    if a.save:
        sp = Path(a.save)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        if not a.json:
            print(f"\n原始表格資料 → {sp}")

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))

    if not a.json:
        print("\n提醒：空字串格＝合併儲存格；欄位歸屬仍須回 260 dpi 原頁圖確認"
              "（見 docs/踩坑紀錄.md §Z.8）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
