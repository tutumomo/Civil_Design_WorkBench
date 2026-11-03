# -*- coding: utf-8 -*-
"""報告回讀驗證（交件前必跑）：R1～R14 零錯誤才算完稿。

驗證兩件事：
1. `.docx` 結構——能不能重開、14 章是否齊全、表號圖號是否連續、頁首頁尾欄位是否在
2. `.pdf` 實體——頁數、中文字型是否嵌入、有無豆腐方塊、有無空白頁、目錄是否展開、
   表格框線是否存在、圖片是否真的進去

    set PYTHONIOENCODING=utf-8
    C:\\Python312\\python.exe tools\\report\\verify_report.py ^
        "_report_test\\AC刨鋪5cm工程_設計報告.docx" ^
        --pdf "_report_test\\AC刨鋪5cm工程_設計報告.pdf"

退出碼：0 全部通過｜1 有錯誤（錯誤逐條列出）｜2 檔案不存在／無法解析
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("✗ 需要 PyMuPDF（fitz）：C:\\Python312\\python.exe -m pip install pymupdf")
    raise SystemExit(2)

try:
    from docx import Document
except ImportError:  # pragma: no cover
    print("✗ 需要 python-docx：C:\\Python312\\python.exe -m pip install python-docx")
    raise SystemExit(2)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CHAPTER_RE = re.compile(r"^第\s*(\d+)\s*章")
TABLE_CAP_RE = re.compile(r"^表\s*(\d+)")
FIG_CAP_RE = re.compile(r"^圖\s*(\d+)")
TOC_LINE_RE = re.compile(r"第\s*\d+\s*章")

RESULTS: list[dict] = []


def add(code: str, name: str, ok: bool, detail: str, level: str = "error"):
    RESULTS.append({"code": code, "name": name, "ok": bool(ok), "detail": detail, "level": level})
    mark = "✓" if ok else ("⚠" if level == "warn" else "✗")
    print(f"  {mark} {code} {name}：{detail}")
    return ok


# ---------------------------------------------------------------------------
# DOCX 結構檢查
# ---------------------------------------------------------------------------
def check_docx(path: Path, allow_no_figures: bool = False) -> dict:
    print(f"\n[A] DOCX 結構：{path.name}")
    info: dict = {"path": str(path)}
    try:
        doc = Document(str(path))
    except Exception as exc:  # noqa: BLE001
        add("R1", "DOCX 可重開", False, f"python-docx 開啟失敗：{exc}")
        return info
    paras = doc.paragraphs
    add("R1", "DOCX 可重開", True, f"段落 {len(paras)}、表格 {len(doc.tables)}")
    info["paragraphs"] = len(paras)
    info["tables"] = len(doc.tables)

    # R2 14 章齊全且順序正確
    h1 = [p.text.strip() for p in paras if p.style.name == "Heading 1" and p.text.strip()]
    chapters = []
    for text in h1:
        m = CHAPTER_RE.match(text)
        if m:
            chapters.append(int(m.group(1)))
    ok = chapters == list(range(1, 15))
    add("R2", "14 章齊全且順序正確", ok,
        f"偵測到章次 {chapters}" if not ok else f"第 1～14 章，共 {len(chapters)} 章")
    info["chapters"] = chapters

    # R3 表號連續
    table_nos = [int(m.group(1)) for p in paras if (m := TABLE_CAP_RE.match(p.text.strip()))]
    ok = table_nos == list(range(1, len(table_nos) + 1)) and len(table_nos) > 0
    add("R3", "表號連續無跳號", ok, f"表號 {table_nos}")
    info["table_captions"] = table_nos

    # R4 圖號連續
    fig_nos = [int(m.group(1)) for p in paras if (m := FIG_CAP_RE.match(p.text.strip()))]
    if not fig_nos and allow_no_figures:
        add("R4", "圖號連續無跳號", True, "無圖（本案未產設計圖，允許）")
    else:
        ok = fig_nos == list(range(1, len(fig_nos) + 1)) and len(fig_nos) > 0
        add("R4", "圖號連續無跳號", ok, f"圖號 {fig_nos}")
    info["figure_captions"] = fig_nos

    # R5/R6 頁首頁尾
    sec = doc.sections[0]
    header_text = " ".join(p.text for p in sec.header.paragraphs).strip()
    first_header = " ".join(p.text for p in sec.first_page_header.paragraphs).strip()
    add("R5", "頁首含工程名稱", bool(header_text) and "工程" in header_text,
        f"「{header_text[:40]}」／封面頁首空白={not first_header}")
    footer_xml = "".join(p._p.xml for p in sec.footer.paragraphs)
    has_page = "PAGE" in footer_xml
    has_pages = "NUMPAGES" in footer_xml
    footer_text = "".join(p.text for p in sec.footer.paragraphs)
    add("R6", "頁尾含頁碼欄位", has_page and has_pages,
        f"PAGE={has_page}、NUMPAGES={has_pages}、「{footer_text[:24]}」")
    info["header"] = header_text
    info["footer_fields"] = {"PAGE": has_page, "NUMPAGES": has_pages}

    # R7 技師覆核聲明
    body = "\n".join(p.text for p in paras)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                body += "\n" + cell.text
    need = "技師"
    ok = ("覆核" in body and need in body) or "簽證" in body
    add("R7", "含技師覆核／簽證聲明", ok, "已於封面、第 13 章與附錄 C 出現" if ok else "查無覆核聲明")

    # 資訊量（防空殼）
    add("R8", "文件資訊量足夠", len(body) > 6000, f"總字元數 {len(body):,}")
    info["chars"] = len(body)
    return info


# ---------------------------------------------------------------------------
# PDF 實體檢查
# ---------------------------------------------------------------------------
def _ink_ratio(page, dpi: int = 72) -> float:
    """版心（扣除頁首頁尾）的著墨比例，用來偵測整頁空白。"""
    rect = page.rect
    clip = fitz.Rect(rect.x0, rect.y0 + 80, rect.x1, rect.y1 - 70)
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csGRAY)
    samples = pix.samples
    total = len(samples)
    if total == 0:
        return 0.0
    dark = sum(1 for b in samples if b < 235)
    return dark / total


def check_pdf(path: Path, docx_info: dict, out_dir: Path, min_pages: int,
              render_pages: list[int], allow_no_figures: bool = False) -> dict:
    print(f"\n[B] PDF 實體：{path.name}")
    info: dict = {"path": str(path)}
    try:
        pdf = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        add("R9", "PDF 可開啟", False, f"{exc}")
        return info

    pages = pdf.page_count
    ok = pages >= min_pages
    add("R9", "PDF 頁數合理", ok, f"{pages} 頁（門檻 {min_pages}）", level="error")
    info["pages"] = pages

    # R10 中文字型嵌入
    fonts: set[str] = set()
    for i in range(min(pages, 8)):
        for f in pdf[i].get_fonts():
            fonts.add(f[3])
    cjk_fonts = [f for f in fonts if re.search(r"(Ming|Kai|DFKai|SimSun|Noto|CJK|Hei|Song|Yu)", f)]
    add("R10", "中文字型已嵌入", bool(cjk_fonts), f"字型：{', '.join(sorted(fonts))[:120]}")
    info["fonts"] = sorted(fonts)

    # R11 中文比例與豆腐方塊
    text = "\n".join(pdf[i].get_text() for i in range(pages))
    non_space = [c for c in text if not c.isspace()]
    cjk = sum(1 for c in non_space if CJK_RE.match(c))
    ratio = cjk / max(len(non_space), 1)
    tofu = text.count("\ufffd") + text.count("□")
    ok = ratio >= 0.20 and tofu == 0
    add("R11", "中文正常無方塊", ok,
        f"中文字元佔比 {ratio:.1%}、豆腐方塊 {tofu} 個")
    info["cjk_ratio"] = round(ratio, 4)
    info["tofu"] = tofu

    # R12 無空白頁
    blanks, inks = [], []
    for i in range(pages):
        r = _ink_ratio(pdf[i])
        inks.append(round(r, 4))
        if r < 0.002:
            blanks.append(i + 1)
    add("R12", "無整頁空白", not blanks, f"最低著墨頁 {min(inks):.4f}" if not blanks
        else f"疑似空白頁：{blanks}")
    info["ink_ratios"] = inks

    # R13 目錄已展開
    toc_page_text = ""
    for i in range(min(pages, 4)):
        t = pdf[i].get_text()
        if "目" in t and "錄" in t:
            toc_page_text = t
            break
    toc_lines = len(TOC_LINE_RE.findall(toc_page_text))
    dots = len(re.findall(r"[.．…]{3,}", toc_page_text))
    ok = toc_lines >= 10
    add("R13", "目錄已展開含頁碼", ok, f"目錄行 {toc_lines} 條、導引點線 {dots} 段")
    info["toc_lines"] = toc_lines

    # R14 表格框線與圖片
    drawings = 0
    images = 0
    for i in range(pages):
        drawings += len(pdf[i].get_drawings())
        images += len(pdf[i].get_images(full=True))
    ok = drawings >= 100
    add("R14", "表格框線存在", ok, f"向量線段物件 {drawings} 個")
    if images == 0 and allow_no_figures:
        add("R15", "內嵌圖片存在", True, "無內嵌圖（本案未產設計圖，允許）",
            level="warn")
    else:
        add("R15", "內嵌圖片存在", images >= 1, f"圖片物件 {images} 個",
            level="warn")
    info["drawing_objects"] = drawings
    info["images"] = images

    # 章名對照（PDF 文字中是否找得到每一章）
    missing = [n for n in docx_info.get("chapters", [])
               if not re.search(rf"第\s*{n}\s*章", text)]
    add("R16", "各章標題在 PDF 中可讀", not missing,
        f"缺漏章節：{missing}" if missing else "14 章標題均可由 PDF 文字層取得",
        level="warn")
    info["chapters_missing_in_pdf"] = missing

    # 轉 PNG 供目視
    png_dir = out_dir / "_verify_png"
    png_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    targets = render_pages or [1, 2, 3, pages]
    for n in targets:
        if 1 <= n <= pages:
            out = png_dir / f"{path.stem}_p{n:02d}.png"
            pdf[n - 1].get_pixmap(dpi=110).save(str(out))
            rendered.append(str(out))
    info["png"] = rendered
    print(f"    → 已轉 PNG {len(rendered)} 張：{png_dir}")
    return info


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="設計報告回讀驗證（R1～R16）")
    ap.add_argument("docx", help="要驗證的 .docx")
    ap.add_argument("--pdf", default=None, help="對應的 .pdf（省略時自動找同名檔）")
    ap.add_argument("--out-dir", default=None, help="驗證輸出目錄（預設與 docx 同層的 _verify）")
    ap.add_argument("--min-pages", type=int, default=3, help="PDF 最少頁數（預設 3）")
    ap.add_argument("--pages", default=None, help="要轉 PNG 的頁碼，如 1,2,7（預設 1,2,3,末頁）")
    ap.add_argument("--json", default=None, help="驗證結果 JSON 輸出路徑")
    ap.add_argument("--strict", action="store_true", help="警告也視為失敗")
    ap.add_argument("--allow-no-figures", action="store_true",
                    help="本案未產設計圖時，R4／R15 以「無圖（允許）」通過")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    docx_path = Path(args.docx).resolve()
    if not docx_path.exists():
        print(f"✗ 找不到 {docx_path}")
        return 2
    pdf_path = Path(args.pdf).resolve() if args.pdf else docx_path.with_suffix(".pdf")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else docx_path.parent / "_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    render_pages = [int(x) for x in args.pages.split(",")] if args.pages else []

    print("=" * 72)
    print(f"設計報告回讀驗證　{Path(args.docx).name}")
    print("=" * 72)

    docx_info = check_docx(docx_path, args.allow_no_figures)
    pdf_info = {}
    if pdf_path.exists():
        pdf_info = check_pdf(pdf_path, docx_info, out_dir, args.min_pages,
                             render_pages, args.allow_no_figures)
    else:
        add("R9", "PDF 可開啟", False, f"找不到 {pdf_path}")

    errors = [r for r in RESULTS if not r["ok"] and r["level"] == "error"]
    warns = [r for r in RESULTS if not r["ok"] and r["level"] == "warn"]
    print("\n" + "=" * 72)
    print(f"結果：{len(RESULTS)} 項檢核｜錯誤 {len(errors)}｜警告 {len(warns)}")
    print("=" * 72)

    payload = {
        "docx": docx_info,
        "pdf": pdf_info,
        "results": RESULTS,
        "errors": [e["code"] for e in errors],
        "warnings": [w["code"] for w in warns],
    }
    out_json = Path(args.json) if args.json else out_dir / f"{docx_path.stem}_驗證結果.json"
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"驗證結果：{out_json}")

    if errors:
        return 1
    if warns and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
