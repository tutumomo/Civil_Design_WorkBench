"""Self-test: 已驗證規範表格在前端的渲染（"[object Object]" 缺陷的守門）。

背景：已驗證表格的列有三種形狀——``{"key": 列名, "values": {欄: 值}}``（lookup）、
``{"x": 數值, "values": {欄: 值}}``（stepdown）、``[值, 值, …]``（interp）。
前端若把整個列物件直接丟進 ``esc()``，就會顯示 "[object Object]"（2026-11-11 使用者回報）。

本測試做兩件事：
  1. Python 端：``tools/regs/verified.py::table_grid`` 對每一張表都要產生欄數一致的格線，
     且格內不得再出現 dict／list 物件。
  2. JS 端：真的用 node 執行 ``tools/regs/regs_web.html`` 裡的 ``verifiedGrid()``／``verifiedCell()``，
     對全部已驗證表格跑一次渲染，輸出不得含 "[object Object]"。

需要 node（沒有就整支跳過，不算失敗）；其餘部分只用 Python。

usage: python tools/selftest/regs_table_render_selftest.py   (exit 0 = 通過)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "regs"))
import verified as V  # noqa: E402

WEB = ROOT / "tools" / "regs" / "regs_web.html"


def main():
    bad = 0

    def chk(name, ok, extra=""):
        nonlocal bad
        print(f"{'ok  ' if ok else 'FAIL'} {name} {extra}")
        bad += not ok

    f, t = V.load()
    chk("已載入已驗證條目", bool(t), f"{len(f)} 公式 / {len(t)} 表")

    # 1. Python 端：格線欄數一致、格內為純量
    mismatch = []
    objcells = []
    for x in t.values():
        g = V.table_grid(x)
        if g["columns"] and not g["rows"]:
            mismatch.append(f"{x['id']}（有欄位但沒列）")
            continue
        for r in g["rows"]:
            if len(r) != len(g["columns"]):
                mismatch.append(f"{x['id']}（欄數 {len(g['columns'])} vs {len(r)}）")
            for c in r:
                if isinstance(c, (dict, list)):
                    objcells.append(f"{x['id']} → {c!r}")
    chk("每列欄數與表頭一致", not mismatch, "；".join(mismatch[:5]))
    chk("格內不再有 dict/list 物件", not objcells, "；".join(objcells[:5]))

    # lookup / stepdown / interp 三種形狀都要有對應欄
    by_kind = {}
    for x in t.values():
        g = V.table_grid(x)
        by_kind.setdefault(x.get("kind"), []).append((x, g))
    for kind in ("lookup", "stepdown", "interp"):
        items = by_kind.get(kind) or []
        chk(f"{kind} 表存在且已正規化", bool(items), f"{len(items)} 張")
        for x, g in items[:1]:
            chk(f"{kind} 表欄名非空", all(str(c) for c in g["columns"]), str(g["columns"])[:80])

    # 使用者回報的那張表（最小出水高度）必須有可讀的格線
    hit = [e for e in V.for_clause("urbanroad113", "7.3.4") if e["kind"] == "table"]
    chk("urbanroad113 §7.3.4 有已驗證表", bool(hit), f"{len(hit)} 張")
    fb = next((e for e in hit if e["id"].endswith("min_freeboard_T732")), None)
    chk("最小出水高度表格線正確",
        fb is not None and fb["grid"]["columns"][-1] == "最小出水高度(公分)"
        and any(r[0].startswith("設計水深≦60") and r[-1] == 15 for r in fb["grid"]["rows"]),
        json.dumps(fb["grid"], ensure_ascii=False) if fb else "")
    chk("for_clause 產出含 grid 欄位", all("grid" in e for e in hit))

    # 2. JS 端：真的跑 regs_web.html 的 verifiedGrid()
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        print("skip  JS 渲染測試（找不到 node）")
    else:
        html = WEB.read_text(encoding="utf-8")
        fns = {}
        for name in ("verifiedCell", "verifiedGrid"):
            m = re.search(rf"function {name}\s*\([^)]*\)\s*\{{", html)
            if not m:
                chk(f"regs_web.html 有 {name}()", False)
                continue
            start = m.start()
            depth = 0
            i = html.index("{", m.end() - 1)
            for j in range(i, len(html)):
                if html[j] == "{":
                    depth += 1
                elif html[j] == "}":
                    depth -= 1
                    if depth == 0:
                        fns[name] = html[start:j + 1]
                        break
            chk(f"regs_web.html 有 {name}()", name in fns)

        payload = {x["id"]: {"columns": x.get("columns", []), "rows": x.get("rows", []),
                             "grid": V.table_grid(x)} for x in t.values()}
        script = "\n".join(fns.values()) + """
const payload = JSON.parse(require("fs").readFileSync(process.argv[2], "utf-8"));
let bad = [];
for (const [id, v] of Object.entries(payload)) {
  const g = verifiedGrid(v);
  if (!g.columns.length || !g.rows.length) { bad.push(id + "：空格線"); continue; }
  for (const r of g.rows) {
    if (r.length !== g.columns.length) bad.push(id + "：欄數不符");
    for (const c of r) {
      const s = String(c);
      if (s.includes("[object Object]")) bad.push(id + "：[object Object]");
    }
  }
}
console.log(JSON.stringify(bad));
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "check.js"
            p.write_text(script, encoding="utf-8")
            data = Path(td) / "payload.json"
            data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([node, str(p), str(data)],
                               capture_output=True, text=True)
        if r.returncode != 0:
            chk("node 執行 verifiedGrid()", False, r.stderr.strip()[:300])
        else:
            try:
                badjs = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception as e:  # noqa: BLE001
                badjs = [f"解析失敗：{e}｜{r.stdout[:200]}"]
            chk("前端渲染全部已驗證表格無 [object Object]、欄數一致", not badjs, "；".join(badjs[:5]))

    print(f"{len(f)} 公式, {len(t)} 表, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
