"""`gridcraft-cli` 的 macOS 實作（走控制通道）。

對應 Windows 版 `gridcraft-cli.exe` 的三個子指令（本專案 `tools/boq/boq_build.py` 會用到）：

    gridcraft-cli run --script <腳本.jsonl> [--quiet]   依序執行腳本裡的指令
    gridcraft-cli eval "<公式>" --in <活頁簿.xlsx>         求值並印出結果
    gridcraft-cli check <活頁簿.xlsx>                      錯誤檢查（公式錯誤 → exit 1）

腳本格式（`boq_build.py` 的 `Cmd` 類別產生）：每行一條 `指令=JSON參數`，
例如 `file.new={}`、`range.setValues={"range":"A1","values":[[1,2]]}`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from artcraft_cli.channel import App, ControlError  # noqa: E402


def parse_script(path: str) -> list[tuple[str, dict]]:
    """把 `指令=JSON` 的腳本逐行解析成 (command, params)。"""
    out: list[tuple[str, dict]] = []
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"腳本第 {lineno} 行格式錯誤（應為 指令=JSON）：{raw[:80]}")
        cid, _, blob = line.partition("=")
        blob = blob.strip()
        try:
            params = json.loads(blob) if blob else {}
        except json.JSONDecodeError as exc:
            raise SystemExit(f"腳本第 {lineno} 行 JSON 解析失敗：{exc}") from exc
        out.append((cid.strip(), params))
    return out


def cmd_run(args) -> int:
    steps = parse_script(args.script)
    with App("gridcraft") as app:
        for i, (cid, params) in enumerate(steps, 1):
            try:
                app.execute(cid, params)
            except ControlError as exc:
                print(f"[{i}/{len(steps)}] {cid} 失敗：{exc}", file=sys.stderr)
                return 1
            if not args.quiet:
                print(f"[{i}/{len(steps)}] {cid} ok")
    return 0


def cmd_eval(args) -> int:
    with App("gridcraft") as app:
        if args.infile:
            app.execute("file.open", {"path": args.infile})
        params = {"formula": args.formula}
        if args.cell:
            params["cell"] = args.cell
        try:
            r = app.call("engine.execute", {"command": "formulas.evaluate", "params": params})
        except ControlError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if not r.get("ok"):
            print(f"求值失敗：{r.get('error')}", file=sys.stderr)
            return 1
        result = r.get("result")
        value = result.get("value") if isinstance(result, dict) else result
        print(value if value is not None else "")
    return 0


def cmd_check(args) -> int:
    with App("gridcraft") as app:
        if args.infile:
            app.execute("file.open", {"path": args.infile})
        try:
            errs = app.execute("formulas.errorChecking", {})
        except ControlError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        cells = []
        if isinstance(errs, dict):
            cells = errs.get("cells") or errs.get("errors") or []
        elif isinstance(errs, list):
            cells = errs
        if cells:
            print(f"發現 {len(cells)} 個公式錯誤：")
            for c in cells[:20]:
                print("  ", json.dumps(c, ensure_ascii=False)[:200])
            return 1
        print("check：未發現公式錯誤")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gridcraft-cli", description="GridCraft CLI（macOS 控制通道實作）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="執行腳本")
    p.add_argument("--script", required=True)
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("eval", help="求值")
    p.add_argument("formula")
    p.add_argument("--in", dest="infile")
    p.add_argument("--cell")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("check", help="公式錯誤檢查")
    p.add_argument("infile", nargs="?")
    p.set_defaults(func=cmd_check)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ControlError as exc:
        print(f"gridcraft-cli：{exc}", file=sys.stderr)
        sys.exit(2)
