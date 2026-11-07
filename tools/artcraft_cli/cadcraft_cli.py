"""`cadcraft-cli` 的 macOS 實作（走控制通道）。

對應 Windows 版 `cadcraft-cli.exe` 的用法（本專案 `tools/acad/acc.py`、
`tools/a3_sheet/make_a3_sheet.py` 會用到）：

    cadcraft-cli convert <來源.dxf|.dwg> <目的.dwg|.dxf>   轉檔（DWG 以 2018 版輸出）
    cadcraft-cli run <圖.dxf> --cmd "<指令>"                開圖後執行一條 CADCraft 指令

`--cmd` 的內容是 CADCraft 的指令字串，可帶 JSON 參數，例如
`plot {"path":"/tmp/a.pdf","layout":"斷面圖","landscape":true}`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from artcraft_cli.channel import App, ControlError  # noqa: E402

#: DXF → DWG 時固定輸出版本（AGENTS.md §2：交件 DWG 須為 AutoCAD 2018 格式）
DWG_VERSION = 2018


def cmd_convert(args) -> int:
    src = Path(args.src)
    dst = Path(args.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    ext = dst.suffix.lower()
    with App("cadcraft") as app:
        app.execute("open", {"path": str(src)})
        if ext == ".dwg":
            app.execute("saveas", {"path": str(dst), "version": DWG_VERSION})
        else:
            app.execute("export", {"path": str(dst), "format": ext.lstrip(".")})
    if not dst.is_file():
        raise SystemExit(f"轉檔失敗：沒有產生 {dst}")
    print(f"{src.name} → {dst.name}（{dst.stat().st_size:,} B）")
    return 0


def cmd_run(args) -> int:
    src = Path(args.src)
    with App("cadcraft") as app:
        app.execute("open", {"path": str(src)})
        cmd = args.cmd
        if cmd.startswith("plot "):          # plot 是引擎指令，走 engine.execute
            blob = cmd[len("plot "):].strip()
            try:
                params = json.loads(blob) if blob.startswith("{") else {}
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--cmd 的 JSON 參數解析失敗：{exc}") from exc
            app.execute("plot", params)
        else:
            r = app.call("cmdline.input", {"text": cmd})
            if not r.get("ok"):
                print(f"指令執行失敗：{r.get('error')}", file=sys.stderr)
                return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cadcraft-cli", description="CADCraft CLI（macOS 控制通道實作）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("convert", help="DXF／DWG 轉檔")
    p.add_argument("src")
    p.add_argument("dst")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("run", help="開圖並執行指令")
    p.add_argument("src")
    p.add_argument("--cmd", required=True)
    p.set_defaults(func=cmd_run)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ControlError as exc:
        print(f"cadcraft-cli：{exc}", file=sys.stderr)
        sys.exit(2)
