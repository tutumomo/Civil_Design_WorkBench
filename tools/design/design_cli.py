"""Command-line front door for all civil-design calculation engines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from design_api import DesignAPIError, list_calculators, run_calculation


def _read_json(path: str | None) -> dict:
    if not path or path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesignAPIError("JSON 格式錯誤：%s" % exc) from exc
    if not isinstance(data, dict):
        raise DesignAPIError("輸入必須是 JSON 物件")
    return data


def _catalog_row(calc_id: str) -> dict:
    for item in list_calculators():
        if item["id"] == calc_id:
            return item
    raise DesignAPIError("未知計算器：%s" % calc_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="土木／結構設計計算統一入口（JSON API 的命令列版）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有計算器")

    show = sub.add_parser("show", help="顯示單一計算器的輸入範例與限制")
    show.add_argument("calculator")

    run = sub.add_parser("run", help="執行計算")
    run.add_argument("calculator")
    run.add_argument("input", nargs="?", help="JSON 檔；省略或 - 表示從 stdin 讀取")
    run.add_argument("--format", choices=("text", "json"), default="text")
    run.add_argument("--no-persist", action="store_true", help="不寫入 out/design_workbench/runs")

    args = parser.parse_args()
    try:
        if args.command == "list":
            rows = list_calculators()
            for row in rows:
                print("%-24s %-8s %s" % (row["id"], row["group"], row["title"]))
            print("\n共 %d 個計算器。用 `show <id>` 看輸入範例。" % len(rows))
            return
        if args.command == "show":
            print(json.dumps(_catalog_row(args.calculator), ensure_ascii=False, indent=2))
            return
        payload = _read_json(args.input)
        result = run_calculation(
            args.calculator,
            payload,
            persist=not args.no_persist,
        )
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["summary"])
            if result.get("saved_to"):
                print("\n紀錄：%s" % result["saved_to"])
            if result.get("error"):
                print("\n錯誤：%s" % result["error"])
        raise SystemExit(0 if result.get("ok") else 1)
    except (DesignAPIError, FileNotFoundError) as exc:
        print("錯誤：%s" % exc, file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

