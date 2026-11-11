r"""設計圖產線自測（D0）：不需 CAD 後端，只出 DXF。

檢查
----
1. 三態表態：`CATALOG` 每個計算器都落在 supported／not_applicable／not_implemented 之一；
   `CAPABILITIES` 與 `NOT_APPLICABLE` 不得有不在目錄裡的 id，也不得重複表態；
   not_applicable 必須附理由。
   釘住基準：下面 `EXPECTED_SUPPORTED`／`EXPECTED_NOT_APPLICABLE` 是「目前的表態」，
   誤刪能力表、或新增出圖能力卻忘了同步，都會在這裡失敗。新增出圖能力時，
   在同一個 commit 把 id 加進 EXPECTED_SUPPORTED。
2. 每個 supported 計算器以 `CATALOG` 範例跑 `generate(publish=False)`：
   張數與檔名符合 `sheets`、DXF 可重讀、`$INSUNITS=6`、`$MEASUREMENT=1`、`TOMO` 字型樣式存在。
3. 標題欄繪圖者可由 `drafter` 帶下去（D13）。
4. 未實作／不適用的計算器呼叫 `generate()` 必須明確報錯，不得出圖。

輸出一律寫到暫存目錄，不碰 `out/`。

Run:
    .venv/bin/python tools/selftest/design_section_selftest.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/design", "tools/regs", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import ezdxf  # noqa: E402

import design_api as API  # noqa: E402
import design_section as DS  # noqa: E402

FAILS: list[str] = []

EXPECTED_SUPPORTED = {
    "wall_stability", "counterfort_wall", "mse_wall", "anchored_wall",
    "box_culvert", "channel_hydraulics", "slope_stability",
}
EXPECTED_NOT_APPLICABLE = {"hydrology"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _dxf_ok(path: str) -> tuple[bool, str]:
    try:
        doc = ezdxf.readfile(path)
    except Exception as ex:  # noqa: BLE001
        return False, "無法重讀：%s" % ex
    if int(doc.header.get("$INSUNITS", 0)) != 6:
        return False, "$INSUNITS=%s（應為 6）" % doc.header.get("$INSUNITS")
    if int(doc.header.get("$MEASUREMENT", 0)) != 1:
        return False, "$MEASUREMENT=%s（應為 1）" % doc.header.get("$MEASUREMENT")
    if "TOMO" not in [s.dxf.name for s in doc.styles]:
        return False, "缺 TOMO 文字樣式"
    return True, ""


def main() -> int:
    rows = {r["id"]: r for r in API.list_calculators()}
    ids = list(rows)

    print("[1] 三態表態")
    stray = [i for i in list(DS.CAPABILITIES) + list(DS.NOT_APPLICABLE) if i not in rows]
    check("CAPABILITIES／NOT_APPLICABLE 的 id 都在目錄內", not stray, str(stray))
    both = sorted(set(DS.CAPABILITIES) & set(DS.NOT_APPLICABLE))
    check("沒有同時登錄為可出圖與不適用", not both, str(both))
    check("不適用皆附理由", all(DS.NOT_APPLICABLE.values()))
    caps = DS.capability_map(ids)
    check("capability_map 涵蓋整份目錄", set(caps) == set(ids))
    check("每個計算器狀態皆為三態之一",
          all(c["status"] in DS.STATUSES for c in caps.values()))
    check("supported 旗標與 status 一致",
          all(c["supported"] == (c["status"] == "supported") for c in caps.values()))
    check("可出圖清單與基準一致（EXPECTED_SUPPORTED）",
          {i for i in ids if caps[i]["status"] == "supported"} == EXPECTED_SUPPORTED,
          "現況 %s" % sorted(i for i in ids if caps[i]["status"] == "supported"))
    check("不適用清單與基準一致（EXPECTED_NOT_APPLICABLE）",
          {i for i in ids if caps[i]["status"] == "not_applicable"} == EXPECTED_NOT_APPLICABLE)
    summary = {s: [i for i in ids if caps[i]["status"] == s] for s in DS.STATUSES}
    print("    可出圖 %d／不適用 %d／未實作 %d"
          % tuple(len(summary[s]) for s in DS.STATUSES))

    print("[2] supported 計算器出 DXF（範例）")
    with tempfile.TemporaryDirectory(prefix="design_section_selftest_") as tmp:
        DS._out_root = lambda: os.path.join(tmp, "out")          # type: ignore[assignment]
        DS._temp_root = lambda: os.path.join(tmp, "temp")        # type: ignore[assignment]
        for cid in summary["supported"]:
            spec = DS.CAPABILITIES[cid]
            try:
                res = DS.generate(cid, rows[cid]["example"], unit="m",
                                  scale="auto", publish=False)
            except Exception:  # noqa: BLE001
                check("%s 出圖" % cid, False, traceback.format_exc().strip().splitlines()[-1])
                continue
            dxfs = [f for f in res["files"] if f["kind"] == "dxf"]
            want = [s["suffix"] + ".dxf" for s in spec["sheets"]]
            check("%s 張數與檔名符合 sheets" % cid,
                  sorted(f["name"] for f in dxfs) == sorted(want),
                  "%s ≠ %s" % ([f["name"] for f in dxfs], want))
            for f in dxfs:
                ok, why = _dxf_ok(f["path"])
                check("%s %s 合乎 DXF 基本規定" % (cid, f["name"]), ok, why)

        print("[3] 繪圖者可帶入標題欄（D13）")
        for cid in ("wall_stability", "box_culvert"):
            if cid not in DS.CAPABILITIES:
                continue
            res = DS.generate(cid, rows[cid]["example"], publish=False,
                              drafter="自測繪圖者")
            found = False
            for f in res["files"]:
                if f["kind"] != "dxf":
                    continue
                doc = ezdxf.readfile(f["path"])
                for lay in doc.layouts:
                    if any(getattr(e.dxf, "text", "") == "自測繪圖者"
                           for e in lay.query("TEXT")):
                        found = True
                if found:
                    break
            check("%s 標題欄出現指定繪圖者" % cid, found)

        print("[4] 非 supported 必須明確拒絕")
        for cid in summary["not_applicable"] + summary["not_implemented"][:1]:
            try:
                DS.generate(cid, rows[cid]["example"], publish=False)
                check("%s 拒絕出圖" % cid, False, "竟然出了圖")
            except DS.SectionError:
                check("%s 拒絕出圖" % cid, True)
            except Exception as ex:  # noqa: BLE001
                check("%s 拒絕出圖（SectionError）" % cid, False, type(ex).__name__)

    print()
    if FAILS:
        print("✗ 失敗 %d 項：%s" % (len(FAILS), "；".join(FAILS)))
        return 1
    print("✓ 設計圖產線自測全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
