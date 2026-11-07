"""`wordcraft-cli` 的 macOS 實作（走控制通道）。

對應 Windows 版 `wordcraft-cli.exe` 的用法（本專案 `tools/report/make_report.py` 會用到）：

    wordcraft-cli convert <來源.docx> <目的.docx|.pdf> [--update-fields]

`--update-fields` 會在轉檔前跑一次「更新功能變數」（目錄、頁碼、TOC），
這是 Windows 版 `wordcraft-cli convert --update-fields` 的同一件事。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from artcraft_cli.channel import App, ControlError  # noqa: E402


def cmd_convert(args) -> int:
    src = Path(args.src)
    dst = Path(args.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with App("wordcraft") as app:
        app.execute("file.open", {"path": str(src)})
        if args.update_fields:
            app.execute("references.updateFields", {"all": True})
        if dst.suffix.lower() == ".pdf":
            app.execute("file.exportPdf", {"path": str(dst)})
        else:
            app.execute("file.saveAs", {"path": str(dst)})
    if not dst.is_file():
        raise SystemExit(f"轉檔失敗：沒有產生 {dst}")
    print(f"{src.name} → {dst.name}（{dst.stat().st_size:,} B）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wordcraft-cli", description="WordCraft CLI（macOS 控制通道實作）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("convert", help="docx ↔ docx／pdf")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--update-fields", dest="update_fields", action="store_true")
    p.set_defaults(func=cmd_convert)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ControlError as exc:
        print(f"wordcraft-cli：{exc}", file=sys.stderr)
        sys.exit(2)
