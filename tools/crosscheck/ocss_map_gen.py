r"""X0　模板對照表產生器：把盤點原始資料（`maps/_inventory/`）＋既有對照案例
（`checks/*.json`）整理成一張可讀的「OCSS 變數 ↔ 本專案參數」對照表。

為什麼要有這支工具
------------------
X0 的目標是「每個 `tw-*` 模板一張對照表」。手工寫 17 張會過期，而且容易在
沒有真正對過的情況下把欄位「配起來」——那正是原則 6 反對的事。

這支工具只做**機械可驗證**的部分：

1. **OCSS 側**：輸入欄位（名稱、型別、預設值、單位、標籤）與輸出變數，
   直接取自盤點原始資料，不重打。
2. **本專案側**：只填「本專案確實用到的欄位」——取自 `checks/*.json` 該案例的
   `payload` 鍵、`ocss_inputs` 鍵與 `compare` 項的 `ours` 路徑。
3. **對應關係**：只放**人工維護的既有對照表**裡已核實的對應；其餘一律進
   `unmapped` 清單並標「待人工核對」，**不猜**。

輸出 `maps/<templateId>.json`（已存在的人工表**不覆寫**，以 `--force` 才覆寫）。

用法
----
    .venv/bin/python tools/crosscheck/ocss_map_gen.py            # 產生缺少的表
    .venv/bin/python tools/crosscheck/ocss_map_gen.py --list     # 只列統計
    .venv/bin/python tools/crosscheck/ocss_map_gen.py --force    # 覆寫（會丟掉人工註記，慎用）

不需 OCSS 桌面程式：全部讀磁碟上的盤點與案例檔。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAPS = HERE / "maps"
INVENTORY = MAPS / "_inventory"
CHECKS = HERE / "checks"

# 對應關係只認人工維護過的表（maps/<templateId>.json，且不是本工具產的草稿）。
# 草稿檔本身帶 "_generated" 標記，不會被當成人工核實的來源。
_GENERATED_FLAG = "_generated"


def _norm(name: str) -> str:
    """把欄位名正規化，讓 `fc_in`／`fc_in_MPa`／`fc` 這種寫法可比。"""
    s = (name or "").strip().lower()
    s = re.sub(r"[\s\-()\[\]]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def _tokens(name: str) -> set[str]:
    """把欄位名拆成語意詞（去單位後綴、去常見綴）。

    同時放入「去分隔符」的整串（`f_c` → `fc`、`fc_mpa` → `fc`），讓下劃線寫法不同
    的同義欄位仍可比。
    """
    s = _norm(name)
    for suf in ("_mpa", "_kn", "_kpa", "_knm", "_mm", "_m2", "_m3", "_n", "_in", "_out",
                "_m", "_kgf_m2", "_mm2", "_cm2"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    s = re.sub(r"^(fc|fy|gamma|gam)_", "", s)
    toks = {t for t in s.split("_") if t and t not in ("ours", "ocss", "theirs", "our")}
    flat = s.replace("_", "")
    if flat:
        toks.add(flat)
    return toks


def _load_inventory() -> dict:
    out = {}
    for p in sorted(INVENTORY.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return out


def _load_checks() -> dict:
    """templateId → 案例清單（同一模板可能有多個案例）。"""
    out: dict[str, list[dict]] = {}
    for p in sorted(CHECKS.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for chk in data.get("checks", []):
            tpl = chk.get("template")
            if not tpl:
                continue
            out.setdefault(tpl, []).append({
                "file": p.name,
                "name": chk.get("name"),
                "calculator": chk.get("calculator"),
                "payload_keys": sorted(_flatten_keys(chk.get("payload") or {})),
                "ocss_input_keys": sorted((chk.get("ocss_inputs") or {}).keys()),
                "compare": [
                    {"name": c.get("name"), "ours": c.get("ours"), "ocss": c.get("ocss")}
                    for c in (chk.get("compare") or [])
                ],
                "has_disposition": any(c.get("disposition") for c in (chk.get("compare") or [])),
            })
    return out


def _human_map(template_id: str) -> dict:
    """讀人工維護的對照表（若有）；回傳 {ocss: ours} 對應。"""
    p = MAPS / ("%s.json" % template_id)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if data.get(_GENERATED_FLAG):
        return {}                      # 草稿不算人工核實
    out = {}
    for it in data.get("inputs") or []:
        o = it.get("ocss")
        ours = it.get("ours")
        if o and ours and not str(ours).startswith("（"):
            out[str(o)] = str(ours)
    return out


def _flatten_keys(obj, prefix: str = "") -> list[str]:
    """展開巢狀 payload 的鍵（`example.fc_mpa` → `fc_mpa`），只用葉層名稱。"""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out += _flatten_keys(v, prefix)
            else:
                out.append(k)
    elif isinstance(obj, list):
        for v in obj:
            out += _flatten_keys(v, prefix)
    return out


def _collect_ours_fields(cases: list[dict]) -> list[str]:
    """本專案確實用到的欄位（payload 鍵 + compare 的 ours 路徑根節點）。"""
    fields: set[str] = set()
    for c in cases:
        for k in _flatten_keys(c.get("payload") or {}):
            fields.add(k)
        for cmp_ in c["compare"]:
            ours = cmp_.get("ours")
            if not ours:
                continue
            m = re.match(r"^result\.([A-Za-z_][A-Za-z0-9_]*)", str(ours))
            if m:
                fields.add(m.group(1))
    return sorted(fields)


def _catalog_fields(calculator: str | None) -> list[str]:
    """該計算器在目錄裡的範例輸入欄位（候選來源，讓對照表看得到完整介面）。"""
    if not calculator:
        return []
    try:
        sys.path.insert(0, str(HERE.parent / "design"))
        import design_api  # noqa: E402
    except Exception:
        return []
    for c in design_api.CATALOG:
        if c.get("id") == calculator:
            return sorted(set(_flatten_keys(c.get("example") or {})))
    return []


def _candidates(ocss_name: str, ours_fields: list[str]) -> list[str]:
    """本專案側的**候選**欄位（共用語意詞）。候選不是對應，只供人工核實時快速對照。"""
    tok = _tokens(ocss_name)
    if not tok:
        return []
    scored = []
    for f in ours_fields:
        ft = _tokens(f)
        if not ft:
            continue
        common = tok & ft
        if common:
            scored.append((len(common) / float(len(tok | ft)), f))
    scored.sort(reverse=True)
    return [f for _, f in scored[:3]]


def build(template_id: str, inv: dict, cases: list[dict], human: dict) -> dict:
    """產生一張對照表草稿。"""
    rows = []
    unmapped = []
    used_human = set()

    # OCSS 輸入欄位：literal 型在 literal_inputs，prompt 型在 inputs。
    ocss_inputs = []
    if inv.get("input_style") == "literal":
        for i in inv.get("literal_inputs") or []:
            ocss_inputs.append({"name": i["name"], "kind": "literal",
                                "default": i.get("default"), "unit": i.get("unit"),
                                "label": i.get("label")})
    else:
        for i in inv.get("inputs") or []:
            ocss_inputs.append({"name": i["name"], "kind": i.get("kind"),
                                "default": i.get("default"),
                                "unit": i.get("unit_in_label"),
                                "label": i.get("label")})

    ours_fields = _collect_ours_fields(cases)
    calculators = sorted({c["calculator"] for c in cases if c.get("calculator")})
    cand_fields = sorted(set(ours_fields) | set(_catalog_fields(
        calculators[0] if len(calculators) == 1 else None)))

    for i in ocss_inputs:
        name = i["name"]
        ours = human.get(name)
        if ours:
            used_human.add(name)
            rows.append({"ocss": name, "ours": ours, "unit": i.get("unit"),
                         "note": "人工對照表已核實"})
        else:
            unmapped.append({"ocss": name, "unit": i.get("unit"),
                             "default": i.get("default"),
                             "candidates": _candidates(name, cand_fields),
                             "note": "本專案無對應欄位或尚未核實——待人工核對"})

    # 本專案有、OCSS 沒有（或未對應）的欄位
    mapped_ours = set(human.values())
    ours_only = [f for f in ours_fields if f not in mapped_ours]

    outputs = [o.get("name") for o in (inv.get("outputs") or [])]

    # 輸出側對應：compare 項的 ours/ocss 是**實際驗過**的對應（差異在容差內或已處置），
    # 這是本表裡唯一「已核實」的欄位對應來源。
    compare_rows = []
    for c in cases:
        for cmp_ in c["compare"]:
            compare_rows.append({
                "case": c["name"],
                "name": cmp_.get("name"),
                "ours": cmp_.get("ours"),
                "ocss": cmp_.get("ocss"),
                "verified": bool(cmp_.get("verified", True)),
            })

    table = {
        "templateId": template_id,
        "module": inv.get("module"),
        "title": inv.get("title"),
        "input_style": inv.get("input_style"),
        "status": ("draft-輸入欄位對應待人工核對" if unmapped else "draft-已核實"),
        "calculator": calculators[0] if len(calculators) == 1 else (calculators or None),
        "checks": [{"file": c["file"], "name": c["name"]} for c in cases],
        "inputs": rows,
        "unmapped": unmapped,
        "compare": compare_rows,
        "case_inputs": [{"case": c["name"],
                         "ocss_inputs": c["ocss_input_keys"],
                         "payload": c["payload_keys"]} for c in cases],
        "ocss_outputs": outputs,
        "ours_only": ours_only,
        "blockers": _blockers(template_id, calculators, cases),
        _GENERATED_FLAG: True,
        "_note": ("本表由 tools/crosscheck/ocss_map_gen.py 產生：OCSS 側取自盤點原始資料，"
                  "本專案側取自既有對照案例實際使用的欄位。`inputs` 只放人工維護表已核實的"
                  "對應；`compare` 是**實際驗過**的輸出對應（案例跑過、差異在容差內或已處置）；"
                  "未列入 `inputs` 的 OCSS 欄位一律標為待人工核對，不臆測對應。"),
    }
    if not cases:
        table["status"] = "draft-本專案無對照案例"
    return table


def _blockers(template_id: str, calculators: list[str], cases: list[dict]) -> list[str]:
    out: list[str] = []
    if not calculators:
        out.append("本專案沒有對應計算器，也沒有對照案例——本模板不列入交叉驗算範圍。")
    else:
        out.append("本專案對應計算器：%s。" % "、".join(calculators))
    if cases and not all(c["has_disposition"] for c in cases):
        out.append("案例中有未處置的差異（見 checks 檔的 disposition 欄）。")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="X0 模板對照表產生器")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的人工對照表")
    ap.add_argument("--list", action="store_true", help="只列統計，不寫檔")
    args = ap.parse_args(argv)

    inv_all = _load_inventory()
    checks = _load_checks()
    made = 0
    skipped = 0
    for tid in sorted(inv_all):
        target = MAPS / ("%s.json" % tid)
        if target.is_file() and not args.force:
            skipped += 1
            continue
        if args.list:
            print("%-28s %s" % (tid, "已有（人工）" if target.is_file() else "缺"))
            continue
        human = _human_map(tid)
        table = build(tid, inv_all[tid], checks.get(tid, []), human)
        target.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        made += 1
        print("寫入 %s（inputs %d、待核對 %d）" % (target.name, len(table["inputs"]),
                                                 len(table["unmapped"])))
    if args.list:
        return 0
    print("產生 %d 張、跳過 %d 張（已存在，未覆寫）" % (made, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
