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
    "wall_stability", "counterfort_wall", "mse_wall", "anchored_wall", "channel_cover",
    "box_culvert", "channel_hydraulics", "slope_stability", "block_wall",
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

        print("[2b] 疊式／砌石牆五型：圖面斷面積＝引擎 area_m2_per_m（D2）")
        if "block_wall" in DS.CAPABILITIES:
            import block_wall as BW
            from catalog.wall import _block_wall_defaults
            from ezdxf.math import area as _area
            ex = rows["block_wall"]["example"]
            geo = ("course_count", "course_height_m", "base_width_m", "width_decrement_m",
                   "step_side", "height_m", "top_width_m", "front_batter_ratio",
                   "back_batter_ratio", "stone_length_m", "embedment_m")
            for wt, d in _block_wall_defaults().items():
                p = {k: v for k, v in ex.items() if k not in geo}
                p.update(d, wall_type=wt)
                try:
                    res = DS.generate("block_wall", p, publish=False)
                except Exception:  # noqa: BLE001
                    check("block_wall[%s] 出圖" % wt, False,
                          traceback.format_exc().strip().splitlines()[-1])
                    continue
                dxf = next(f["path"] for f in res["files"] if f["kind"] == "dxf")
                doc = ezdxf.readfile(dxf)
                drawn = sum(abs(_area(list(e.vertices_in_wcs()))) for e in
                            doc.modelspace().query('LWPOLYLINE[layer=="30_擋土牆混凝土"]'))
                want = BW.analyse(p, p.get("soil"), {"kh": p.get("kh", 0.0)}
                                  )["geometry"]["area_m2_per_m"]
                check("block_wall[%s] 斷面積 %.4f＝%.4f" % (wt, drawn, want),
                      abs(drawn - want) <= 1e-3 * max(want, 1e-9))

        print("[2c] 排水溝／邊坡尺寸來源（D12）：輸入取代預設；預設者標「假設值」")

        def _texts(res):
            dxf = next(f["path"] for f in res["files"] if f["kind"] == "dxf")
            d = ezdxf.readfile(dxf)
            out = []
            for lay in d.layouts:
                out += [getattr(e.dxf, "text", "") for e in lay.query("TEXT")]
                out += [e.plain_text() for e in lay.query("MTEXT")]
            return "\n".join(out)

        cx = dict(rows["channel_hydraulics"]["example"])
        r0 = DS.generate("channel_hydraulics", cx, publish=False)
        check("channel 未填厚度→說明欄有「假設值」", "假設值" in _texts(r0)
              and "wall_thickness_m" in _texts(r0))
        check("channel 未填厚度→defaults_used 列出",
              any(x.startswith("wall_thickness_m") for x in r0["defaults_used"]))
        cx.update(wall_thickness_m=0.25, base_thickness_m=0.30)
        r1 = DS.generate("channel_hydraulics", cx, publish=False)
        check("channel 填厚度→不再列為假設值",
              not any(x.startswith(("wall_thickness_m", "base_thickness_m"))
                      for x in r1["defaults_used"]))
        q1 = r1["case"] if "case" in r1 else None
        import json as _j
        c1 = _j.load(open(r1["case_path"], encoding="utf-8"))["quantities"]["values"]
        check("channel 厚度原值進案件", c1["wall_thickness_m"] == 0.25
              and c1["base_thickness_m"] == 0.30)
        sx = dict(rows["slope_stability"]["example"], bench_width_m=1.5, bench_count=1)
        r2 = DS.generate("slope_stability", sx, publish=False)
        c2 = _j.load(open(r2["case_path"], encoding="utf-8"))["quantities"]["values"]
        check("slope 平台寬／數原值進案件",
              c2["bench_width_m"] == 1.5 and c2["bench_count"] == 1)
        check("slope 填平台→defaults_used 不含平台",
              not any(x.startswith("bench_") for x in r2["defaults_used"]))

        print("[2d] 溝蓋詳圖：圖上數字＝計算結果（D3，DG2）")
        if "channel_cover" in DS.CAPABILITIES:
            import re as _re
            ex = rows["channel_cover"]["example"]
            res = DS.generate("channel_cover", ex, publish=False)
            run = API.run_calculation("channel_cover", ex)["result"]
            txt = _texts(res)
            dxf = next(f["path"] for f in res["files"] if f["kind"] == "dxf")
            doc = ezdxf.readfile(dxf)
            s_, a_ = run["slab"], run["anchors"]
            g_ = lambda v: "%d" % round(float(v))
            want = [
                "%s@%s" % (s_["main"]["bar"], g_(s_["main"]["spacing_mm"])),
                "%s@%s" % (s_["distribution"]["bar"], g_(s_["distribution"]["spacing_mm"])),
                "%s@%s" % (s_["top"]["bar"], g_(s_["top"]["spacing_mm"])),
                "%s@%s" % (a_["bar"], g_(a_["spacing_mm"])),
                "埋深 %s" % g_(a_["embedment_mm"]),
                "%%%%c%s" % g_(a_["hole_diameter_mm"]),
                "邊距 %s" % g_(a_["edge_mm"]),
                "保護層 %s" % g_(run["geometry"]["cover_mm"]),
            ]
            for w in want:
                check("溝蓋圖含標註「%s」" % w, w in txt)
            # 圖上所有 Dxx@yyy 標註都必須在計算結果內（不得有結果以外的配筋）
            allowed = {"%s@%s" % (b["bar"], g_(b["spacing_mm"]))
                       for b in (s_["main"], s_["distribution"], s_["top"])}
            allowed.add("%s@%s" % (a_["bar"], g_(a_["spacing_mm"])))
            seen = set(_re.findall(r"D\d+@\d+", txt))
            check("圖上配筋標註皆可追溯到結果", seen <= allowed, str(seen - allowed))
            # 幾何：蓋版面積＝總寬×版厚；植筋中心距溝壁外側面＝結果邊距
            slab_a = sum(abs(_area(list(e.vertices_in_wcs()))) for e in
                         doc.modelspace().query('LWPOLYLINE[layer=="30_溝蓋混凝土"]'))
            want_a = run["geometry"]["total_width_m"] * run["geometry"]["slab_thickness_mm"] / 1000.0
            check("蓋版斷面積 %.4f＝%.4f" % (slab_a, want_a), abs(slab_a - want_a) < 1e-6)
            xs = sorted(v[0] for e in doc.modelspace().query('LWPOLYLINE[layer=="41_植筋"]')
                        for v in e.vertices_in_wcs())
            check("植筋位置：左壁植筋中心距外側面＝邊距",
                  abs(min(xs) + (a_["hole_diameter_mm"] / 2000.0) - a_["edge_mm"] / 1000.0) < 1e-6)
            # 點數：分佈筋圓點間距＝結果間距
            circles = sorted(e.dxf.center.x for e in
                             doc.modelspace().query('CIRCLE[layer=="40_鋼筋"]')
                             if abs(e.dxf.radius * 2000 - s_["distribution"]["db_mm"]) < 1e-6)
            gaps = {round((b - a) * 1000) for a, b in zip(circles, circles[1:])}
            check("分佈筋點間距＝結果間距", gaps == {round(s_["distribution"]["spacing_mm"])}, str(gaps))

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
