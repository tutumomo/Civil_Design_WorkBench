"""Verified formula / table library for agents (machine-readable, executable, with provenance).

Clause text in the index is for reading; agents must not pull numbers out of garbled text. Entries in
tools/regs/verified/*.json carry: source clause, LaTeX, executable expression, variables with units and
ranges, conditions, test cases, and a verification record. `evaluate()` runs the expression in a
restricted namespace and refuses inputs that violate the clause's stated conditions.

status: "verified"  = transcribed from the original text/page AND cross-checked (tests + design engine);
        "pending"   = transcribed but not yet cross-checked; evaluate() warns.
engineer_signed: null until a licensed engineer signs it off (kept separate on purpose).
"""
import ast
import json
import math
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIR = HERE / "verified"
_FUNCS = {"log10": math.log10, "log": math.log, "sqrt": math.sqrt, "exp": math.exp, "pi": math.pi,
          "sin": math.sin, "cos": math.cos, "tan": math.tan, "radians": math.radians, "atan": math.atan, "degrees": math.degrees, "tanh": math.tanh, "cosh": math.cosh, "sinh": math.sinh,
          "min": min, "max": max, "abs": abs, "interp": None, "floor": math.floor, "ceil": math.ceil}
_OK = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call, ast.Compare,
       ast.BoolOp, ast.IfExp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Mod,
       ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq, ast.And, ast.Or, ast.List, ast.Tuple)


def _interp(x, xs, ys):
    """Piecewise linear interpolation with end clamping (規範表多規定線性內插，且表邊界外取端值）。"""
    pts = list(zip(xs, ys))
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    return pts[-1][1]


_FUNCS["interp"] = _interp


class VerifiedError(ValueError):
    pass


def _compile(expr):
    tree = ast.parse(expr, mode="eval")
    for n in ast.walk(tree):
        if not isinstance(n, _OK):
            raise VerifiedError(f"運算式含不允許的語法：{type(n).__name__}")
        if isinstance(n, ast.Call) and not (isinstance(n.func, ast.Name) and n.func.id in _FUNCS):
            raise VerifiedError("運算式只允許呼叫 " + "、".join(k for k in _FUNCS if k != "pi"))
    return compile(tree, "<verified>", "eval")


def _eval(expr, env):
    return eval(_compile(expr), {"__builtins__": {}}, dict(_FUNCS, **env))


@lru_cache(maxsize=1)
def load():
    f, t = {}, {}
    for p in sorted(DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for x in d.get("formulas", []):
            x.setdefault("status", "pending")
            x.setdefault("engineer_signed", None)
            f[x["id"]] = x
        for x in d.get("tables", []):
            x.setdefault("status", "pending")
            x.setdefault("engineer_signed", None)
            t[x["id"]] = x
    return f, t


def _brief(x):
    return {k: x.get(k) for k in ("id", "title", "src", "clause", "page", "status", "engineer_signed")}


def for_clause(src, clause):
    """Entries restored for one clause (used to badge regs_clause output)."""
    f, t = load()
    c = str(clause)
    return ([dict(_brief(x), kind="formula") for x in f.values() if x["src"] == src and c in (x["clause"], x.get("index_clause"))]
            + [dict(_brief(x), kind="table") for x in t.values() if x["src"] == src and c in (x["clause"], x.get("index_clause"))])


def search(q):
    f, t = load()
    terms = [w for w in str(q).lower().split() if w]
    out = []
    for kind, d in (("formula", f), ("table", t)):
        for x in d.values():
            hay = " ".join([x["id"], x["title"], x.get("keywords", ""), x["src"], x["clause"]]).lower()
            if all(w in hay for w in terms):
                out.append(dict(_brief(x), kind=kind))
    return out


def evaluate(fid, inputs):
    f, _ = load()
    if fid not in f:
        raise VerifiedError(f"沒有這個公式 id：{fid}（用 regs_formula 的 query 搜尋）")
    x = f[fid]
    env, warns = {}, []
    for name, v in x["vars"].items():
        if name not in inputs:
            if "default" in v:
                env[name] = v["default"]
                warns.append(f"{name} 未給，採預設 {v['default']} {v.get('unit', '')}")
                continue
            raise VerifiedError(f"缺少輸入 {name}（{v.get('desc', '')}，單位 {v.get('unit', '')}）")
        try:
            env[name] = float(inputs[name])
        except (TypeError, ValueError):
            raise VerifiedError(f"{name} 必須是數字")
        lo, hi = v.get("min"), v.get("max")
        if lo is not None and env[name] < lo or hi is not None and env[name] > hi:
            raise VerifiedError(f"{name}={env[name]} 超出適用範圍 [{lo}, {hi}] {v.get('unit', '')}（{x['src']} {x['clause']}）")
    steps = {}
    try:
        for lk in x.get("lookups", []):
            row = table(lk["table"], x=env[lk["x"]])["values"]
            for name, col in lk["map"].items():
                env[name] = steps[name] = row[col]
        for name, e in x.get("defs", []):
            env[name] = steps[name] = _eval(e, env)
        for c in x.get("conditions", []):
            if not _eval(c["expr"], env):
                raise VerifiedError(f"不符適用條件：{c['msg']}（{x['src']} {x['clause']}）")
        val = _eval(x["expr"], env)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        if isinstance(e, VerifiedError):
            raise
        raise VerifiedError(f"輸入超出公式定義域，無法計算：{e}（{x['src']} {x['clause']}）")
    for c in x.get("warn_if", []):
        if _eval(c["expr"], dict(env, result=val)):
            warns.append(c["msg"])
    if x["status"] != "verified":
        warns.append("此公式尚未完成交叉驗證（status=pending），僅供參考")
    if x.get("engineer_signed") is None:
        warns.append("尚無技師簽認紀錄；正式出圖前須人工覆核原條文")
    return {"id": fid, "value": val, "unit": x.get("unit", ""), "output": x.get("output", "value"),
            "inputs": {k: env[k] for k in x["vars"]}, "steps": steps, "warnings": warns,
            "source": {"src": x["src"], "clause": x["clause"], "page": x.get("page")},
            "status": x["status"], "latex": x.get("latex", ""), "notes": x.get("notes", "")}


def table(tid, row=None, col=None, x=None):
    _, t = load()
    if tid not in t:
        raise VerifiedError(f"沒有這個表 id：{tid}")
    tb = t[tid]
    meta = {"id": tid, "title": tb["title"], "unit": tb.get("unit", ""), "status": tb["status"],
            "source": {"src": tb["src"], "clause": tb["clause"], "page": tb.get("page")},
            "notes": tb.get("notes", ""), "engineer_signed": tb["engineer_signed"]}
    if tb["kind"] == "stepdown":
        if x is None:
            return dict(meta, columns=tb["columns"], rows=tb["rows"])
        xs = [r["x"] for r in tb["rows"]]
        if x < xs[0]:
            raise VerifiedError(f"x={x} 小於表範圍下限 {xs[0]}（{tb['src']} {tb['clause']}）")
        hit = [r for r in tb["rows"] if r["x"] <= x][-1]
        return dict(meta, x=x, row_x=hit["x"], values=hit["values"], method="階梯取不大於 x 之最近一列（保守，不內插）")
    if tb["kind"] == "interp":
        if x is None:
            return dict(meta, columns=tb["columns"], rows=tb["rows"])
        xs = [r[0] for r in tb["rows"]]
        if not xs[0] <= x <= xs[-1]:
            raise VerifiedError(f"x={x} 超出表範圍 [{xs[0]}, {xs[-1]}]，不外插（{tb['src']} {tb['clause']}）")
        for a, b in zip(tb["rows"], tb["rows"][1:]):
            if a[0] <= x <= b[0]:
                k = 0 if b[0] == a[0] else (x - a[0]) / (b[0] - a[0])
                return dict(meta, x=x, value=a[1] + k * (b[1] - a[1]), method="線性內插")
    if row is None:
        return dict(meta, columns=tb["columns"], rows=tb["rows"])
    hit = [r for r in tb["rows"] if r["key"] == row]
    if not hit:
        raise VerifiedError(f"表中沒有列「{row}」；可用：{'、'.join(r['key'] for r in tb['rows'])}")
    vals = hit[0]["values"]
    if col is None:
        return dict(meta, row=row, values=vals)
    if col not in vals:
        raise VerifiedError(f"表中沒有欄「{col}」；可用：{'、'.join(vals)}")
    return dict(meta, row=row, col=col, value=vals[col])


def format_text(r):
    """Plain text for MCP replies."""
    if "steps" in r:
        s = [f"{r['id']} = {r['value']:.6g} {r['unit']}  [{r['status']}]",
             f"來源：{r['source']['src']} {r['source']['clause']}" + (f" p.{r['source']['page']}" if r['source']['page'] else ""),
             "輸入：" + json.dumps(r["inputs"], ensure_ascii=False)]
        if r["steps"]:
            s.append("中間值：" + json.dumps({k: round(v, 6) for k, v in r["steps"].items()}, ensure_ascii=False))
        s += ["⚠ " + w for w in r["warnings"]]
        return "\n".join(s)
    return json.dumps(r, ensure_ascii=False, indent=1)


def references_for(calc_id):
    """Verified entries a design calculator relies on (shown in every design_run result)."""
    f = DIR / "_links.json"
    ids = json.loads(f.read_text(encoding="utf-8")).get(calc_id, []) if f.exists() else []
    fm, tb = load()
    out = []
    for i in ids:
        x = fm.get(i) or tb.get(i)
        if x:
            out.append({"id": i, "kind": "formula" if i in fm else "table", "title": x["title"], "src": x["src"],
                        "clause": x["clause"], "page": x.get("page"), "status": x["status"],
                        "engineer_signed": x.get("engineer_signed")})
    return out
