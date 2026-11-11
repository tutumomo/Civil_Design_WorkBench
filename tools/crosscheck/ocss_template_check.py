# -*- coding: utf-8 -*-
r"""template 型交叉驗算（X1）：本專案引擎 ↔ OCSS `tw-*` 模板。

`checks/*.json` 的 `type: "template"` 案例，格式::

    {
      "type": "template",
      "name": "懸臂牆土壓（對 tw-retaining-wall）",
      "calculator": "wall_stability",
      "payload": {...}                       # 完整輸入；或 {"example": true, "patch": {...}}
      "template": "tw-retaining-wall",
      "ocss_inputs": {"H_wall": 5.0, ...},   # 灌進模板的輸入（字面值）
      "compare": [
        {"name": "Ka", "ours": "result.Ka", "ocss": "var:Ka", "tol": {"rel": 0.01},
         "disposition": {"kind": "explained", "reason": "..."}}   # 僅在有差異時才需要
      ]
    }

路徑語法
--------
ours（對 `civil-design-run/1` 信封）：
  * `result.Ka`、`result.geometry.H`      — 點號巢狀取值
  * `check:滑動`                           — `checks[]` 中 item 含此字串者的 `value`
ocss：
  * `var:Ka`                               — 計算書中該變數（取最後一次賦值）的數值與單位
  * `uc:UC_sl`                             — `ucValues` 中的值
  * 比較項可加 `"reciprocal": true`（取 OCSS 值的倒數，用於 UC → FS）
  * 比較項可加 `"scale": 1000`（本專案值乘上此倍數後再比，用於兩邊單位不同，例 m ↔ mm）

灌值方式（盤點發現的兩種輸入型態，見 `ocss_inventory.py`）
  * `prompt` 型：`evaluate(source, values=…)`
  * `literal` 型：改寫 source 內 `名稱 = 數字` 那一行（`values` 對它無效）
  模板原始碼來自 `maps/_inventory/<模板>.cpd`（盤點時存下），完全不動 OCSS 專案；
  模板升版後請重跑 `ocss_inventory.py` 並檢查 `source_sha256`。

formula 型（X4，無對應模板者）
  `"type": "formula"`，以 `"source"`（字串或逐行陣列）取代 `template`／`ocss_inputs`；
  其餘（payload、compare、disposition）與 template 型完全相同。公式一律無因次化書寫，
  避開分數次方與單位不收斂兩個陷阱。

差異處置（工作計劃書原則 6）
  差異超過容差時，必須在該比較項寫 `disposition`：
  `{"kind": "engine_fixed"|"template_issue"|"explained", "reason": "…"}`，
  三選一且 `reason` 不可空。沒有處置的差異＝失敗；**不得用放寬容差代替處置**。
  已處置者仍會列出並計數，不會被吞掉。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INV = HERE / "maps" / "_inventory"
DISPOSITIONS = ("engine_fixed", "template_issue", "explained")

for _p in (str(ROOT / "tools" / "design"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TemplateCheckError(Exception):
    """案例本身有問題（非數值差異）：找不到模板、欄位名不存在、路徑取不到值…"""


# --------------------------------------------------------------- 模板與灌值
def load_template(template_id: str) -> tuple[str, dict]:
    src_p, inv_p = INV / (template_id + ".cpd"), INV / (template_id + ".json")
    if not src_p.is_file() or not inv_p.is_file():
        raise TemplateCheckError(
            "沒有 %s 的盤點資料；先跑 ocss_inventory.py %s" % (template_id, template_id))
    src = src_p.read_text(encoding="utf-8")
    inv = json.loads(inv_p.read_text(encoding="utf-8"))
    if inv.get("source_sha256") and \
            hashlib.sha256(src.encode("utf-8")).hexdigest() != inv["source_sha256"]:
        raise TemplateCheckError("%s 的 .cpd 與盤點紀錄雜湊不符，請重跑盤點" % template_id)
    return src, inv


def _fmt(v) -> str:
    return repr(float(v)) if not isinstance(v, str) else v


def apply_inputs(src: str, inv: dict, inputs: dict) -> tuple[str, dict]:
    """回傳（改寫後的 source, 要給 evaluate 的 values）。未知欄位名一律報錯。"""
    prompt = {i["name"] for i in inv.get("inputs", [])}
    literal = {i["name"] for i in inv.get("literal_inputs", [])}
    values: dict = {}
    for name, v in inputs.items():
        if name in prompt:
            values[name] = v
        elif name in literal:
            pat = re.compile(r"^(%s\s*=\s*)[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?=')"
                             % re.escape(name), re.M)
            src, n = pat.subn(lambda m: m.group(1) + _fmt(v), src, count=1)
            if n != 1:
                raise TemplateCheckError("無法改寫 %s：source 中找不到字面常數行" % name)
        else:
            raise TemplateCheckError(
                "模板 %s 沒有輸入欄位 %s（prompt：%s；literal：%s）"
                % (inv.get("templateId"), name, sorted(prompt)[:8], sorted(literal)[:8]))
    return src, values


# --------------------------------------------------------------- 取值
def _walk(obj, path: str):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise TemplateCheckError("路徑 %s 在 %s 處取不到" % (path, part))
    return cur


def get_ours(run: dict, spec: str) -> tuple[float, str]:
    if spec.startswith("check:"):
        key = spec[6:]
        for c in (run.get("result") or {}).get("checks", []) + run.get("checks", []):
            if key in str(c.get("item", "")):
                return float(c["value"]), str(c.get("unit", ""))
        raise TemplateCheckError("本專案 checks 沒有含 %r 的項目" % key)
    v = _walk(run, spec)
    if not isinstance(v, (int, float)):
        raise TemplateCheckError("%s 不是數值：%r" % (spec, v))
    return float(v), ""


def get_ocss(ev: dict, spec: str) -> tuple[float, str]:
    kind, _, name = spec.partition(":")
    if kind == "uc":
        v = (ev.get("ucValues") or {}).get(name)
        if v is None:
            raise TemplateCheckError("OCSS ucValues 沒有 %s" % name)
        return float(v), ""
    if kind == "var":
        hit = None
        for ln in ev.get("lines", []):
            if ln.get("name") == name and ln.get("type") in ("assignment", "value", "input"):
                hit = ln
        if hit is None or not isinstance(hit.get("value"), (int, float)):
            raise TemplateCheckError("OCSS 沒有數值變數 %s（errorLines=%s）"
                                     % (name, ev.get("errorLines")))
        return float(hit["value"]), str(hit.get("unit") or "")
    raise TemplateCheckError("ocss 路徑須為 var:／uc: 開頭：%s" % spec)


# --------------------------------------------------------------- 執行
def _payload(case: dict):
    import design_api as D

    p = case["payload"]
    if isinstance(p, dict) and p.get("example"):
        base = next(r["example"] for r in D.list_calculators()
                    if r["id"] == case["calculator"])
        merged = json.loads(json.dumps(base))
        _deep_update(merged, p.get("patch") or {})
        return merged
    return p


def _deep_update(dst: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def run_case(client, case: dict, emit=print) -> dict:
    """跑一個 template 案例。回傳 {total, failed, handled}。"""
    import design_api as D
    from ocss_client import unit_warnings

    if case.get("type") == "formula":
        # X4：無模板者，OCSS 端為手寫公式鏈（inline source），比對與處置規則同 template 型。
        src = case.get("source")
        if isinstance(src, list):
            src = "\n".join(src) + "\n"
        if not src:
            raise TemplateCheckError("formula 型案例缺 source")
        values = dict(case.get("ocss_values") or {})
    else:
        src, inv = load_template(case["template"])
        src, values = apply_inputs(src, inv, case.get("ocss_inputs") or {})
    run = D.run_calculation(case["calculator"], _payload(case))
    ev = client.evaluate(src, values=values or None)
    if ev.get("errorLines"):
        raise TemplateCheckError("OCSS 計算有錯誤行：%s" % ev.get("errorLines"))
    emit("  本專案 ok=%s　OCSS UC=%s 判定=%s" % (run.get("ok"), ev.get("uc"), ev.get("passes")))
    total = failed = handled = 0
    items: list[dict] = []
    for cmp_ in case["compare"]:
        total += 1
        ours, ou = get_ours(run, cmp_["ours"])
        theirs, tu = get_ocss(ev, cmp_["ocss"])
        if cmp_.get("scale"):                      # 兩邊單位不同時先換算（例：m → mm）
            ours *= float(cmp_["scale"])
            ou = ""
        if cmp_.get("reciprocal"):
            theirs = 1.0 / theirs if theirs else float("inf")
        diff = abs(ours - theirs)
        rel = diff / abs(theirs) if theirs else float("inf")
        tol = cmp_.get("tol") or {"rel": 0.01}
        within = diff <= tol.get("abs", 0.0) or rel <= tol.get("rel", 0.0)
        line = "  %-22s 本專案 %-12.6g OCSS %-12.6g %s　差 %.3g%%" % (
            cmp_["name"], ours, theirs, (tu or ou or "").ljust(6), rel * 100)
        item = {
            "name": cmp_["name"],
            "ours": ours, "ocss": theirs,
            "unit": tu or ou or "",
            "diff": diff, "rel": rel,
            "tol": tol,
            "status": "pass" if within else "fail",
            "disposition": None,
        }
        if within:
            emit("  ✓" + line[1:])
            items.append(item)
            continue
        disp = cmp_.get("disposition") or {}
        if disp.get("kind") in DISPOSITIONS and str(disp.get("reason", "")).strip():
            handled += 1
            emit("  △" + line[1:] + "　已處置[%s]：%s" % (disp["kind"], disp["reason"]))
            item["status"] = "handled"
            item["disposition"] = disp
        else:
            failed += 1
            emit("  ✗" + line[1:] + "　未處置的差異（容差 %s）" % tol)
        items.append(item)
    for w in unit_warnings(ev):
        emit("  ⚠ " + w)
    return {"total": total, "failed": failed, "handled": handled, "items": items}
