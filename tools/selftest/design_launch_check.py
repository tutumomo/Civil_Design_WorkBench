r"""上架檢核：確認一個設計計算器真的「上架」了，而不只是引擎跑得動。

檢查八道關卡（對應 docs\設計計算器上架SOP.md）：
  G0 目錄與 RUNNERS 一致（全域）
  G1 引擎檔案存在且可編譯
  G2 CATALOG 中介資料齊全（group／title／oral／description／engine／codes／limitations）
  G3 範例可執行且 ok=True
  G4 checks／summary 形狀可用（不足視為 WARN）
  G5 已驗證條文連結解得開且全部 verified
  G6 example 的字串葉節點有 select 規則或列在自由文字白名單
  G7 規範查詢主題卡（topics.json）列了這支引擎
  G8 工作台欄位標籤、文件提及、引擎自帶 --selftest（WARN）

Run:
    python -E -P -X utf8 tools/selftest/design_launch_check.py steel_column
    python -E -P -X utf8 tools/selftest/design_launch_check.py --all
    ... --json
"""

from __future__ import annotations

import argparse
import json
import py_compile
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/regs", "tools/design", "tools/selftest"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

import design_api as API  # noqa: E402
import design_workbench_selftest as WBS  # noqa: E402


META_FIELDS = ("group", "title", "oral", "description", "engine", "codes", "limitations")
WORKBENCH = ROOT / "tools" / "design" / "workbench_web.html"
REGS_WEB = ROOT / "tools" / "regs" / "regs_web.html"
TOPICS = ROOT / "tools" / "regs" / "topics.json"
LINKS = ROOT / "tools" / "regs" / "verified" / "_links.json"
DOCS = ROOT / "docs"


class Report:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.fail_count = 0
        self.warn_count = 0

    def add(self, level: str, gate: str, name: str, detail: str = "") -> None:
        self.rows.append({"level": level, "gate": gate, "name": name, "detail": detail})
        if level == "FAIL":
            self.fail_count += 1
        elif level == "WARN":
            self.warn_count += 1

    def ok(self, gate: str, name: str, detail: str = "") -> None:
        self.add("ok", gate, name, detail)

    def fail(self, gate: str, name: str, detail: str = "") -> None:
        self.add("FAIL", gate, name, detail)

    def warn_row(self, gate: str, name: str, detail: str = "") -> None:
        self.add("WARN", gate, name, detail)


def _walk_example(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            rows += _walk_example(value, prefix + "." + key if prefix else key)
    elif isinstance(node, list):
        for value in node:
            rows += _walk_example(value, prefix + "[]")
    else:
        rows.append((prefix, node))
    return rows


def _rule_for(rules: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    if path in rules:
        return rules[path]
    return rules.get(path.split(".")[-1]) or {}


def _example_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _example_keys(value)
    elif isinstance(node, list):
        for value in node:
            keys |= _example_keys(value)
    return keys


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def check_global(report: Report, catalog: list[dict[str, Any]]) -> None:
    ids = [row["id"] for row in catalog]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        report.fail("G0", "目錄 id 唯一", "重複：%s" % "、".join(dup))
    else:
        report.ok("G0", "目錄 id 唯一", "%d 個" % len(ids))

    if set(ids) == set(API.RUNNERS):
        report.ok("G0", "CATALOG 與 RUNNERS 一致", "%d 個計算器" % len(ids))
    else:
        only_cat = sorted(set(ids) - set(API.RUNNERS))
        only_run = sorted(set(API.RUNNERS) - set(ids))
        report.fail(
            "G0",
            "CATALOG 與 RUNNERS 一致",
            "只在目錄：%s；只在 RUNNERS：%s" % (only_cat or "無", only_run or "無"),
        )

    # 檢查 topics.json 所有主題都已掛入 regs_web.html 的 TOPIC_GROUPS
    topics = _load_json(TOPICS, {}).get("topics", [])
    regs_html = REGS_WEB.read_text(encoding="utf-8") if REGS_WEB.is_file() else ""
    unclassified_topics = [
        str(t.get("name"))
        for t in topics
        if t.get("name") and ('"%s"' % t.get("name")) not in regs_html
    ]
    if unclassified_topics:
        report.warn_row(
            "G0",
            "規範查詢台 TOPIC_GROUPS 主題分組",
            "未分組（將落入「其他工程」）：%s" % "、".join(unclassified_topics),
        )
    else:
        report.ok("G0", "規範查詢台 TOPIC_GROUPS 主題分組", "%d 個主題皆已歸類" % len(topics))


def check_calculator(calc: Mapping[str, Any], report: Report) -> None:
    calc_id = calc["id"]
    engine_rel = str(calc.get("engine") or "")
    engine_path = ROOT / "tools" / "design" / engine_rel

    # G1 引擎
    if not engine_rel or not engine_path.is_file():
        report.fail("G1", "引擎檔案", "%s 不存在" % engine_rel)
    else:
        try:
            py_compile.compile(str(engine_path), doraise=True)
            report.ok("G1", "引擎可編譯", engine_rel)
        except Exception as exc:  # pragma: no cover - 檔案壞掉才會走到
            report.fail("G1", "引擎可編譯", "%s：%s" % (engine_rel, exc))

    # G2 中介資料
    missing = [key for key in META_FIELDS if not calc.get(key)]
    example = calc.get("example")
    if not isinstance(example, dict) or not example:
        missing.append("example")
    if missing:
        report.fail("G2", "目錄中介資料", "缺：%s" % "、".join(missing))
    else:
        report.ok("G2", "目錄中介資料", "%s／%s" % (calc["group"], engine_rel))

    if not isinstance(example, dict) or not example:
        return

    # G3 範例可執行
    envelope = API.run_calculation(calc_id, example, persist=False)
    if not envelope.get("ok"):
        report.fail(
            "G3",
            "範例可執行且通過",
            str(envelope.get("error") or "未通過（檢查 checks）"),
        )
        return
    checks = envelope.get("checks") or []
    report.ok("G3", "範例可執行且通過", "%d 項檢核" % len(checks))

    # G4 輸出形狀
    summary = str(envelope.get("summary") or "")
    if len(summary) < 30:
        report.warn_row("G4", "summary 內容", "只有 %d 字" % len(summary))
    else:
        report.ok("G4", "summary 內容", "%d 字" % len(summary))
    if not checks:
        report.warn_row("G4", "檢核列", "無 checks（純計算值型）")
    else:
        bad_item = [c.get("item") for c in checks if not c.get("item")]
        bad_unit = [c.get("item") for c in checks if not c.get("unit")]
        bad_limit = [
            c.get("item")
            for c in checks
            if c.get("limit") is None
            and c.get("required") is None
            and c.get("severity") != "advisory"
        ]
        bad_ok = [c.get("item") for c in checks if not isinstance(c.get("ok"), bool)]
        if bad_item or bad_ok:
            report.fail(
                "G4",
                "檢核列欄位",
                "缺 item：%s；ok 非布林：%s" % (bad_item or "無", bad_ok or "無"),
            )
        elif bad_unit or bad_limit:
            report.warn_row(
                "G4",
                "檢核列欄位",
                "缺 unit：%s；缺 limit：%s" % (bad_unit or "無", bad_limit or "無"),
            )
        else:
            report.ok("G4", "檢核列欄位", "%d 列皆有 item/value/limit/unit/ok" % len(checks))

    # G5 條文連結
    links = _load_json(LINKS, {})
    link_ids = links.get(calc_id) or []
    refs = envelope.get("references") or []
    if link_ids:
        if len(refs) < len(link_ids):
            report.fail(
                "G5",
                "已驗證條文連結",
                "宣告 %d 條、實際解得 %d 條" % (len(link_ids), len(refs)),
            )
        else:
            bad = [r.get("id") for r in refs if r.get("status") != "verified"]
            if bad:
                report.fail("G5", "已驗證條文連結", "非 verified：%s" % "、".join(map(str, bad)))
            else:
                report.ok("G5", "已驗證條文連結", "%d 條全部 verified" % len(refs))
    elif refs:
        report.warn_row("G5", "已驗證條文連結", "有 %d 條 references 但未登記於 _links.json" % len(refs))
    else:
        report.warn_row("G5", "已驗證條文連結", "無 _links.json 條目")

    # G6 列舉欄位
    rules = calc.get("field_rules") or {}
    allowed = WBS.FREE_TEXT_FIELDS.get(calc_id, set())
    uncovered: list[str] = []
    for path, value in _walk_example(example):
        if not isinstance(value, str) or path in allowed:
            continue
        if (_rule_for(rules, path) or {}).get("type") != "select":
            uncovered.append(path)
    if uncovered:
        report.fail("G6", "列舉欄位用下拉", "自由文字：%s" % "、".join(uncovered))
    else:
        report.ok("G6", "列舉欄位用下拉", "%d 個字串欄位皆有規則" % len([1 for _, v in _walk_example(example) if isinstance(v, str)]))

    # G7 規範查詢主題卡與深連結
    topics = _load_json(TOPICS, {}).get("topics", [])
    needle = ("tools\\design\\" + engine_rel).replace("/", "\\").lower()
    hits = [
        t.get("name")
        for t in topics
        if any(
            str(tool).replace("/", "\\").lower() == needle
            for tool in (t.get("tools") or [])
        )
    ]
    if hits:
        report.ok("G7", "規範查詢主題卡", "、".join(str(h) for h in hits))
    else:
        report.fail("G7", "規範查詢主題卡", "%s 未被任何 topics.json 主題卡引用" % engine_rel)

    regs_html = REGS_WEB.read_text(encoding="utf-8") if REGS_WEB.is_file() else ""
    escaped_needle = ("tools\\\\design\\\\" + engine_rel).replace("/", "\\\\")
    if (f'id: "{calc_id}"' in regs_html or f"id:'{calc_id}'" in regs_html) and escaped_needle in regs_html:
        report.ok("G7", "規範查詢台 TOOL_TO_CALCS 深連結", f"/design?calc={calc_id}")
    else:
        report.fail(
            "G7",
            "規範查詢台 TOOL_TO_CALCS 深連結",
            f"regs_web.html 的 TOOL_TO_CALCS 未掛載 {escaped_needle} -> {calc_id}",
        )

    # G8 週邊（WARN）
    html = WORKBENCH.read_text(encoding="utf-8") if WORKBENCH.is_file() else ""
    labelled = {k for k in _example_keys(example) if ("%s:" % k) in html}
    rule_labels = {
        str(path).split(".")[-1]
        for path, rule in rules.items()
        if isinstance(rule, Mapping) and rule.get("label")
    }
    missing_labels = sorted(k for k in _example_keys(example) if k not in labelled | rule_labels)
    if missing_labels:
        report.warn_row("G8", "工作台欄位標籤", "未見：%s" % "、".join(missing_labels))
    else:
        report.ok("G8", "工作台欄位標籤", "全部欄位有中文標籤")

    if (f"{calc_id}:" in html or f'"{calc_id}":' in html) and "SCENARIO_PRESETS" in html:
        report.ok("G8", "工作台 SVG 示意圖與情境範本", f"{calc_id} 已定義")
    else:
        report.warn_row("G8", "工作台 SVG 示意圖與情境範本", f"workbench_web.html 未見 {calc_id} 專屬示意圖或範本")

    docs_hit = []
    if DOCS.is_dir():
        for doc in DOCS.glob("*.md"):
            try:
                if calc_id in doc.read_text(encoding="utf-8"):
                    docs_hit.append(doc.name)
            except Exception:
                continue
    if docs_hit:
        report.ok("G8", "文件提及計算器 id", "、".join(docs_hit[:4]))
    else:
        report.warn_row("G8", "文件提及計算器 id", "docs\\*.md 未出現 %s" % calc_id)

    engine_src = engine_path.read_text(encoding="utf-8") if engine_path.is_file() else ""
    if "--selftest" in engine_src:
        report.ok("G8", "引擎自帶 --selftest")
    else:
        report.warn_row("G8", "引擎自帶 --selftest", "無手算自測入口")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="設計計算器上架檢核")
    parser.add_argument("calculators", nargs="*", help="計算器 id；留空等同 --all")
    parser.add_argument("--all", action="store_true", help="檢查全部計算器")
    parser.add_argument("--json", action="store_true", help="輸出 JSON")
    args = parser.parse_args(argv)

    catalog = API.list_calculators()
    by_id = {row["id"]: row for row in catalog}
    if args.calculators:
        unknown = [c for c in args.calculators if c not in by_id]
        if unknown:
            print("未知計算器：%s" % "、".join(unknown))
            return 2
        targets = [by_id[c] for c in args.calculators]
    else:
        targets = catalog

    global_report = Report()
    check_global(global_report, catalog)

    reports: dict[str, Report] = {}
    for calc in targets:
        report = Report()
        check_calculator(calc, report)
        reports[calc["id"]] = report

    if args.json:
        print(json.dumps(
            {
                "global": global_report.rows,
                "calculators": {k: v.rows for k, v in reports.items()},
                "fail": global_report.fail_count + sum(r.fail_count for r in reports.values()),
                "warn": global_report.warn_count + sum(r.warn_count for r in reports.values()),
            },
            ensure_ascii=False,
            indent=1,
        ))
    else:
        print("上架檢核（%d 個計算器）" % len(targets))
        print("─ 全域")
        for row in global_report.rows:
            print("  [%-4s] %s %s%s" % (
                row["level"], row["gate"], row["name"],
                "：" + row["detail"] if row["detail"] else ""))
        for calc_id, report in reports.items():
            print("─ %s" % calc_id)
            for row in report.rows:
                print("  [%-4s] %s %s%s" % (
                    row["level"], row["gate"], row["name"],
                    "：" + row["detail"] if row["detail"] else ""))
        total_fail = global_report.fail_count + sum(r.fail_count for r in reports.values())
        total_warn = global_report.warn_count + sum(r.warn_count for r in reports.values())
        print()
        if total_fail:
            print("✗ 上架未完成：%d 項 FAIL、%d 項 WARN" % (total_fail, total_warn))
            for calc_id, report in reports.items():
                if report.fail_count:
                    print("  · %s：%d 項 FAIL" % (calc_id, report.fail_count))
        else:
            print("✓ 上架完成：0 FAIL、%d 項 WARN" % total_warn)

    return 1 if (global_report.fail_count + sum(r.fail_count for r in reports.values())) else 0


if __name__ == "__main__":
    raise SystemExit(main())
