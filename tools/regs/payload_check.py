"""入庫前預檢（payload gate）：把「重複踩過三次的坑」在合併前擋下來。

檢查項目
  1. JSON 可解析；id 唯一（含跨既有 verified\\*.json 分片）
  2. 公式 expr / defs 可編譯（用 verified._compile）
  3. **conditions / warn_if 只引用 vars 已宣告的變數**（+ 允許 result / 內建函式常數）
     ← 這是曾三度造成 verified_selftest 以 NameError 崩潰的根因
  4. **測試期望值由引擎實算比對**（不再靠手算）：預設容差 1e-9（相對），不符即列印實算值
     --fix 可把期望值改寫為實算值（僅在公式本身已對過原文時使用）
  5. latex 疑似吃掉反斜線（例如 `rac{`、`ext{`、`frac` 前少了 \）與大括號不平衡
  6. 表格 rows/columns 齊備、values 的 key 不在 columns 內則警告

用法
  python -E -P -X utf8 tools\\regs\\payload_check.py <payload.json> [...]   # 檢查
  python -E -P -X utf8 tools\\regs\\payload_check.py <payload.json> --fix   # 順手修測試期望值
  python -E -P -X utf8 tools\\regs\\payload_check.py --library            # 全庫掃一遍
退出碼：0 = 全過；1 = 有問題（會列出）
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import verified as V  # noqa: E402

import re  # noqa: E402

BUILTIN_NAMES = set(V._FUNCS) | {"result", "True", "False", "None"}
# 控制序列被吃掉反斜線的痕跡（前面沒有反斜線才算錯）
LATEX_CMDS = ("frac", "tfrac", "dfrac", "sqrt", "text", "mathrm", "left", "right",
              "times", "cdot", "quad", "lambda", "theta", "alpha", "beta", "sigma",
              "gamma", "delta", "Delta", "Sigma", "Omega", "leq", "geq", "neq")
# 指令前面沒有反斜線、也不是別的字母尾巴 → 就是反斜線被吃掉
LATEX_LOST = re.compile(r"(?<!\\)(?<![A-Za-z])(" + "|".join(LATEX_CMDS) + r")\b")


def _entries(payload):
    if isinstance(payload, dict):
        for kind in ("formulas", "tables"):
            for e in payload.get(kind, []):
                yield kind.rstrip("s"), e
    else:
        for e in payload:
            yield ("formula" if "rows" not in e else "table"), e


def _names(expr: str) -> set[str]:
    tree = ast.parse(expr, mode="eval")
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def check_entry(kind: str, e: dict, seen_ids: dict, fix: bool) -> list[str]:
    bad: list[str] = []
    eid = e.get("id", "<no-id>")
    if eid in seen_ids:
        bad.append(f"{eid}: 重複 id（已存在於 {seen_ids[eid]}）")
    seen_ids[eid] = e.get("_file", "payload")

    if not e.get("title") or not e.get("src") or not e.get("clause") or not e.get("status"):
        bad.append(f"{eid}: 缺 title/src/clause/status")
    if e.get("status") == "pending" and "待核" not in (e.get("notes") or ""):
        bad.append(f"{eid}: status=pending 但 notes 未標【待核】")

    # latex 反斜線
    latex = e.get("latex") or ""
    lost = LATEX_LOST.search(latex)
    if lost:
        bad.append(f"{eid}: latex 疑吃掉反斜線（'{lost.group(0)}' 前無 \\）→ {latex[:60]}")
    if "\t" in latex or "\n" in latex:
        bad.append(f"{eid}: latex 含 TAB/換行字元（JSON 的 \\t、\\n 被當成跳脫字元）→ {latex[:60]!r}")
    if latex and latex.count("{") != latex.count("}"):
        bad.append(f"{eid}: latex 大括號不平衡")

    if kind == "table":
        if not e.get("rows") or not e.get("columns"):
            bad.append(f"{eid}: 表缺 rows/columns")
        else:
            cols = set(e["columns"])
            for r in e["rows"]:
                if isinstance(r, (list, tuple)):
                    continue
                if "key" not in r and "x" not in r:
                    bad.append(f"{eid}: 表列缺 key（或 stepdown/interp 之 x）")
                    break
                extra = set(r.get("values", {})) - cols if isinstance(r, dict) else set()
                if extra:
                    bad.append(f"{eid}: 表列 {r['key']} 有 columns 以外的欄位 {sorted(extra)[:3]}")
                    break
        return bad

    declared = set(e.get("vars", {}))
    declared |= {n for n, _ in e.get("defs", [])}
    for lk in e.get("lookups", []):
        declared |= set(lk.get("map", {}))
    for k in ("unit", "output", "vars", "expr", "latex"):
        if not e.get(k):
            bad.append(f"{eid}: 公式缺 {k}")

    # 3) conditions / warn_if 變數宣告
    for field in ("conditions", "warn_if"):
        for c in e.get(field, []):
            expr = c.get("expr", "")
            try:
                unknown = _names(expr) - declared - BUILTIN_NAMES
            except SyntaxError as exc:
                bad.append(f"{eid}: {field} 運算式語法錯 {exc}")
                continue
            if unknown:
                bad.append(f"{eid}: {field} 引用未宣告變數 {sorted(unknown)}（會讓 verified_selftest 以 NameError 崩潰）")

    # 2) expr / defs 可編譯
    for label, expr in [("expr", e.get("expr", ""))] + [(f"defs:{n}", x) for n, x in e.get("defs", [])]:
        try:
            V._compile(expr)
        except Exception as exc:
            bad.append(f"{eid}: {label} 不可編譯（{exc}）")
            continue
        unknown = _names(expr) - declared - BUILTIN_NAMES - {n for n, _ in e.get("defs", [])}
        if unknown and label == "expr":
            bad.append(f"{eid}: expr 引用未宣告變數 {sorted(unknown)}")

    # 4) 測試期望值由引擎實算
    tests = e.get("tests", [])
    if not tests:
        bad.append(f"{eid}: 沒有測試案例")
    defaults = {k: v.get("default", 0) for k, v in e.get("vars", {}).items()}
    for i, t in enumerate(tests):
        if t.get("out") is None and not t.get("xcheck"):
            bad.append(f"{eid}: 測試#{i} 沒有 out")
            continue
        if t.get("out") is None:
            continue
        env = dict(defaults, **t.get("in", {}))
        try:
            for lk in e.get("lookups", []):
                row = V.table(lk["table"], x=env[lk["x"]])["values"]
                for name, col in lk.get("map", {}).items():
                    env[name] = row[col]
            for name, dexp in e.get("defs", []):
                env[name] = V._eval(dexp, env)
            got = V._eval(e["expr"], env)
        except Exception as exc:
            bad.append(f"{eid}: 測試#{i} 無法計算（{exc}）")
            continue
        exp = float(t["out"])
        tol = float(t.get("tol", 1e-9))
        ok = abs(got - exp) <= tol * max(1.0, abs(exp))
        if not ok:
            if fix:
                t["out"] = got if abs(got) > 1e-30 else 0.0
                bad.append(f"{eid}: 測試#{i} 期望值已改寫 {exp!r} → {t['out']!r}（引擎實算）")
            else:
                bad.append(f"{eid}: 測試#{i} 期望 {exp!r} 但引擎實算 {got!r}（差 {abs(got - exp):.3g}；用 --fix 自動改寫）")
    return bad


def run(paths: list[Path], fix: bool, library: bool) -> int:
    problems: list[str] = []
    checked = 0
    if library:
        seen: dict[str, str] = {}
        touched = []
        for f in sorted((HERE / "verified").glob("*.json")):
            if f.name.startswith("_"):
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            n0 = len(problems)
            for kind, e in _entries(d):
                e["_file"] = f.name
                problems += check_entry(kind, e, seen, fix)   # 2026-11-02：--library 亦支援 --fix
                checked += 1
            if fix and len(problems) > n0:
                touched.append(d)
                f.write_text(json.dumps({k: v for k, v in d.items() if k != "_file"},
                                        ensure_ascii=False, indent=1) + chr(10), encoding="utf-8")
    else:
        seen = {}
        for f in sorted((HERE / "verified").glob("*.json")):
            if f.name.startswith("_"):
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            for _kind, e in _entries(d):
                seen.setdefault(e.get("id"), f.name)
        for p in paths:
            payload = json.loads(p.read_text(encoding="utf-8"))
            warn_existing_clauses([e for _k, e in _entries(payload)])
            for kind, e in _entries(payload):
                e.setdefault("_file", p.name)
                problems += check_entry(kind, e, seen, fix)
                checked += 1
            if fix:
                p.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    hard = [x for x in problems if "已改寫" not in x]
    soft = [x for x in problems if "已改寫" in x]
    for x in hard:
        print("FAIL", x)
    for x in soft:
        print("FIX ", x)
    print(f"checked {checked} entries, {len(hard)} problem(s), {len(soft)} auto-fixed")
    return 1 if hard else 0


def warn_existing_clauses(entries):
    """合併前提醒：payload 的條文若已有 verified 條目，先確認不是重複轉錄（2026-11-02 事故）。"""
    import verified as V
    seen, warn = set(), []
    for e in entries:
        key = (e.get("src"), str(e.get("clause")))
        if key in seen:
            continue
        seen.add(key)
        have = V.for_clause(key[0], key[1])
        if have:
            warn.append(f"WARN {e.get('id')}: {key[0]} {key[1]} 已有 {len(have)} 條 verified（{', '.join(x['id'] for x in have)}）——"
                        f"若本次是同一算式請勿重複建；若確為不同算式（如 (a)(b) 兩式）請忽略本訊息")
    for w in warn:
        print(w)
    return len(warn)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fix = "--fix" in sys.argv
    library = "--library" in sys.argv
    if not args and not library:
        print(__doc__)
        sys.exit(2)
    sys.exit(run([Path(a) for a in args], fix, library))


if __name__ == "__main__":
    main()
