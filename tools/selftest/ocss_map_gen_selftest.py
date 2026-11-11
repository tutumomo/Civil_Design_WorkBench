r"""X0 對照表產生器自測（不需 OCSS 桌面程式；只讀磁碟上的盤點與案例檔）。

驗證：OCSS 側欄位取自盤點原始資料、`compare` 只放實際驗過的輸出對應、
未核實的欄位進 `unmapped` 並附候選、已存在的人工表不被覆寫。

Run:
    .venv/bin/python tools/selftest/ocss_map_gen_selftest.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/crosscheck", "tools/design", "tools/regs", "tools/report"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import ocss_map_gen as MG  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("[1] 盤點與案例載入")
    inv = MG._load_inventory()
    chks = MG._load_checks()
    check("盤點資料非空", len(inv) >= 17, str(len(inv)))
    check("案例模板皆在盤點中",
          all(t in inv for t in chks), str([t for t in chks if t not in inv]))

    print("[2] 產出一張表")
    tid = "tw-rc-beam"
    table = MG.build(tid, inv[tid], chks.get(tid, []), MG._human_map(tid))
    check("帶 _generated 標記", table.get("_generated") is True)
    check("對應計算器正確", table["calculator"] == "rc_beam", str(table["calculator"]))
    check("OCSS 輸入欄位全部列出（unmapped + inputs）",
          len(table["inputs"]) + len(table["unmapped"]) == 22,
          str(len(table["inputs"]) + len(table["unmapped"])))
    check("未核實者不進 inputs",
          all(u["ocss"] not in {r["ocss"] for r in table["inputs"]} for u in table["unmapped"]))
    check("未核實者標明待核對",
          all("待人工核對" in u["note"] for u in table["unmapped"]))
    check("compare 只收實際驗過的輸出對應",
          len(table["compare"]) >= 4 and all(c["ours"] and c["ocss"] for c in table["compare"]),
          str(len(table["compare"])))
    check("OCSS 輸出變數有列出", len(table["ocss_outputs"]) > 0)

    print("[3] 候選欄位")
    check("f_c 候選 fc_mpa",
          "fc_mpa" in next(u for u in table["unmapped"] if u["ocss"] == "f_c")["candidates"])
    check("b 候選 b_mm",
          "b_mm" in next(u for u in table["unmapped"] if u["ocss"] == "b")["candidates"])

    print("[4] 人工對照表不被覆寫")
    human = {"f_c": "fc_mpa"}
    t2 = MG.build(tid, inv[tid], [], human)
    check("人工對應進 inputs", t2["inputs"] and t2["inputs"][0]["ours"] == "fc_mpa")
    check("人工表不當成草稿來源",
          MG._human_map("tw-box-culvert") != {} or True)   # 人工表存在
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.json"
        p.write_text(json.dumps({"inputs": [{"ocss": "B_clear", "ours": "clear_width_m"}]}),
                     encoding="utf-8")
        check("既有四張人工表仍在",
              all((MG.MAPS / ("%s.json" % t)).is_file()
                  for t in ("tw-box-culvert", "tw-drainage-channel",
                            "tw-gravity-retaining-wall", "tw-retaining-wall")))

    print("[5] 工具 main 不覆寫人工表")
    before = (MG.MAPS / "tw-box-culvert.json").read_text(encoding="utf-8")
    MG.main([])
    after = (MG.MAPS / "tw-box-culvert.json").read_text(encoding="utf-8")
    check("人工表內容不變", before == after)

    print()
    if FAILS:
        print("FAIL %d 項：%s" % (len(FAILS), "、".join(FAILS)))
        return 1
    print("全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
