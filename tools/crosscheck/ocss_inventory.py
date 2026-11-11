r"""OCSS 模板欄位盤點（X0）：讀出每個 `tw-*` 模板的輸入欄位與輸出變數，存成 JSON。

做法
----
對每個模板 `sheet_add` → 讀 `inputs`（名稱、標籤、預設值、單位）與 `source`
→ `sheet_remove`（一律 finally 移除，成功或失敗都不留工作表）；
輸出變數則以無狀態的 `evaluate(source)` 取得（不碰專案）。

**會短暫改動 OCSS 專案**（原則 7）：開始前專案必須沒有任何工作表，否則拒絕執行；
結束時再次確認工作表數回到 0。

產出：`tools/crosscheck/maps/_inventory/<templateId>.json`（盤點原始資料，可重跑）。
對照表（OCSS 變數 ↔ 本專案參數）另放 `tools/crosscheck/maps/<templateId>.json`，由人工維護。

用法
----
    .venv/bin/python tools/crosscheck/ocss_inventory.py            # 全部 tw-*
    .venv/bin/python tools/crosscheck/ocss_inventory.py tw-rc-beam tw-box-culvert
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ocss_client as C  # noqa: E402

OUT = HERE / "maps" / "_inventory"
_UNIT_TAIL = re.compile(r"[（(]([^（）()]*)[）)]\s*$")
# 「字面常數」型輸入：`B_chan = 0.60'm <i>說明</i>`。這類欄位 REST 的 values 蓋不掉，
# 必須改寫 source 該行（X1 的灌值方式）。
_LITERAL = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"'(?P<unit>[^\s<]*)\s*(?:<i>(?P<label>.*?)</i>)?",
    re.M)


def _unit_from_label(label: str) -> str:
    m = _UNIT_TAIL.search(label or "")
    return m.group(1).strip() if m else ""


def inventory(c: "C.OcssClient", template_id: str) -> dict:
    sid = c.sheet_add(template_id)["id"]
    try:
        sheet = c.sheet(sid)
    finally:
        c.sheet_remove(sid)
    src = sheet.get("source", "")
    ev = c.evaluate(src)
    inputs = []
    for i in sheet.get("inputs", []):
        inputs.append({
            "name": i["name"],
            "label": i.get("label", ""),
            "unit_in_label": _unit_from_label(i.get("label", "")),
            "default": i.get("default"),
            "kind": i.get("kind"),
            "options": i.get("options"),
        })
    literal = []
    for m in _LITERAL.finditer(src):
        literal.append({"name": m["name"], "default": m["val"], "unit": m["unit"],
                        "label": re.sub(r"<[^>]+>", "", m["label"] or "")})
    lit_names = {x["name"] for x in literal}
    outputs = []
    for ln in ev.get("lines", []):
        if ln.get("type") in ("assignment", "value") and ln.get("name") \
                and ln["name"] not in lit_names:
            outputs.append({"name": ln["name"], "unit": ln.get("unit", ""),
                            "value_at_default": ln.get("value")})
    return {
        "templateId": template_id,
        "source_sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
        "_source": src,
        "module": sheet.get("module"),
        "title": ev.get("title"),
        "input_style": ("prompt" if inputs else "literal" if literal else "none"),
        "inputs": inputs,
        "literal_inputs": literal,
        "outputs": outputs,
        "ucValues_at_default": ev.get("ucValues"),
        "uc_at_default": ev.get("uc"),
        "passes_at_default": ev.get("passes"),
        "errorLines": ev.get("errorLines"),
        "unit_warnings": C.unit_warnings(ev),
    }


def main(argv: list[str]) -> int:
    c = C.OcssClient()
    c.require()
    if c.sheets():
        print("✗ OCSS 專案已有工作表，拒絕執行（原則 7：不動使用者的專案）。請開空白專案。")
        return 2
    ids = argv or [m["templateId"] for m in c.modules()
                   if str(m.get("templateId", "")).startswith("tw-")]
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for tid in ids:
        try:
            inv = inventory(c, tid)
        except Exception as ex:  # noqa: BLE001
            print("✗ %-28s %s" % (tid, ex))
            bad += 1
            continue
        # 模板原始碼另存 .cpd，讓 template 型交叉驗算不必動專案就能取得（X1）。
        (OUT / (tid + ".cpd")).write_text(inv.pop("_source"), encoding="utf-8")
        (OUT / (tid + ".json")).write_text(
            json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
        print("✓ %-28s %-7s 輸入 %2d／輸出變數 %3d／UC %d%s" % (
            tid, inv["input_style"], len(inv["inputs"]) or len(inv["literal_inputs"]),
            len(inv["outputs"]),
            len(inv["ucValues_at_default"] or {}),
            "　⚠單位 %s" % inv["unit_warnings"] if inv["unit_warnings"] else ""))
    left = len(c.sheets())
    print("結束：專案工作表 %d 張（應為 0）" % left)
    return 1 if bad or left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
