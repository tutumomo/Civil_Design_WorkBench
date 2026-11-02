"""PDF 頁面裁圖／分段渲染（供人工或子代理讀原頁圖）。

規範的公式與表格在文字層常常錯亂（分數線、合併儲存格、上下標消失），最後還是得看
原頁圖。本工具負責產生「看得清楚的圖」：預設 300 dpi，可只裁一小塊，也可把一頁切成
上下數段（段與段重疊，避免公式被切斷）。

範例::

    # 整頁切成上下兩段（重疊 8%），給子代理讀
    python tools/regs/page_crop.py "<pdf>" 17 --bands 2 --dpi 260 --out _temp/crops/p17

    # 只裁某個局部（座標為 PDF point，原點左上，與 PyMuPDF 相同）
    python tools/regs/page_crop.py "<pdf>" 118 --clip 0 500 595 842 --dpi 400 -o eq.png

    # 一次處理多頁
    python tools/regs/page_crop.py "<pdf>" 20-24 --bands 2 --out _temp/crops/

輸出檔名格式：`<out>_p<頁>_<段>.png`（`--out` 給目錄時自動建立）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from project_paths import temp_dir  # noqa: E402
except Exception:  # pragma: no cover - 直接執行時的退路
    def temp_dir(*p, create=True):
        d = Path(__file__).resolve().parents[2] / "_temp"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _open_pdf(path: Path):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("需要 PyMuPDF：pip install pymupdf（或 pip install -r requirements.txt）")
    if not path.is_file():
        sys.exit(f"找不到 PDF：{path}")
    return fitz.open(str(path))


def parse_pages(spec: str, total: int) -> list[int]:
    """`17` / `17,18` / `20-24` / `all` → 1-based 頁碼清單。"""
    spec = spec.strip()
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
    ap = argparse.ArgumentParser(description="PDF 頁面裁圖／分段渲染（260~420 dpi 供讀公式與表格）")
    ap.add_argument("pdf", help="PDF 路徑")
    ap.add_argument("pages", help="頁碼：17 / 17,18 / 20-24 / all（1-based，PDF 檔序）")
    ap.add_argument("--clip", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                    help="裁切矩形（PDF point，原點左上）；與 --bands 互斥")
    ap.add_argument("--bands", type=int, default=0,
                    help="把每頁縱切成 N 段（常用 2；段間自動重疊）")
    ap.add_argument("--overlap", type=float, default=0.08, help="分段重疊比例（預設 0.08）")
    ap.add_argument("--dpi", type=float, default=300.0, help="解析度（公式建議 260~420，預設 300）")
    ap.add_argument("--out", "-o", required=True, help="輸出檔（單頁單段）或目錄（多頁／多段）")
    ap.add_argument("--quiet", action="store_true", help="只印檔名")
    a = ap.parse_args(argv)

    doc = _open_pdf(Path(a.pdf))
    pages = parse_pages(a.pages, len(doc))
    bands = a.bands if a.bands and a.bands > 0 else 0
    multi = len(pages) > 1 or bands > 1
    out = Path(a.out)
    if multi:
        out.mkdir(parents=True, exist_ok=True)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)

    made = 0
    for p in pages:
        pg = doc[p - 1]
        w, h = pg.rect.width, pg.rect.height
        if a.clip:
            rects = [("clip", tuple(a.clip))]
        elif bands:
            step = h / bands
            ov = step * max(0.0, min(0.45, a.overlap))
            rects = []
            for i in range(bands):
                y0 = max(0.0, i * step - (ov if i else 0))
                y1 = min(h, (i + 1) * step + (ov if i < bands - 1 else 0))
                tag = ("top", "mid", "bot")[i] if bands == 3 else f"b{i + 1}"
                if bands == 2:
                    tag = ("top", "bot")[i]
                rects.append((tag, (0.0, y0, w, y1)))
        else:
            rects = [("full", (0.0, 0.0, w, h))]

        for tag, (x0, y0, x1, y1) in rects:
            import fitz
            pix = pg.get_pixmap(dpi=int(a.dpi), clip=fitz.Rect(x0, y0, x1, y1))
            name = out / f"{out.stem or out.name}_p{p}_{tag}.png" if multi else out
            if multi and not str(name).lower().endswith(".png"):
                name = name.with_suffix(".png")
            pix.save(str(name))
            made += 1
            if not a.quiet:
                print(f"{name}  {pix.width} x {pix.height}  ({tag})")
    if a.quiet:
        print(f"{made} 張 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
