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
    "wall_stability", "counterfort_wall", "mse_wall", "anchored_wall", "channel_cover", "rc_beam", "rc_column",
        "foundation_isolated", "foundation_combined", "detention_basin", "sediment_basin", "channel_profile",
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

        print("[2e] RC 梁／柱斷面：圖上數字＝計算結果（D4，DG2）")
        if "rc_beam" in DS.CAPABILITIES and "rc_column" in DS.CAPABILITIES:
            import re as _re2
            for cid in ("rc_beam", "rc_column"):
                ex = rows[cid]["example"]
                res = DS.generate(cid, ex, publish=False)
                run = API.run_calculation(cid, ex)["result"]
                txt = _texts(res)
                doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
                # 外圈（半徑＝db/2）才算主筋，內圈半徑 0.45× 排除
                bar = (run["flexure"]["bar"] if cid == "rc_beam" else run["chosen"]["bar"])
                sys.path.insert(0, str(ROOT / "tools" / "rc_section"))
                import make_rc_section as RS
                db = RS.BAR_DIA[bar]
                outer = [e for e in doc.modelspace().query('CIRCLE[layer=="40_鋼筋"]')
                         if abs(e.dxf.radius * 2000 - db) < 1e-6]
                if cid == "rc_beam":
                    n_want = max(2, -(-int(run["flexure"]["As_design_mm2"] * 1000) // (RS.BAR_AREA[bar] * 1000)))
                    tie = run["shear"]["stirrup"]
                    want_tie = "%s@%d" % (tie["bar"], round(tie["spacing_mm"]))
                else:
                    n_want = int(run["chosen"]["bars_total"])
                    tie = run["ties"]
                    want_tie = "%s@%d" % (tie["bar"], round(tie["spacing_mm"]))
                check("%s 主筋圓點數＝%d" % (cid, n_want), len(outer) == n_want, str(len(outer)))
                check("%s 圖上含箍筋標註「%s」" % (cid, want_tie), want_tie in txt)
                check("%s 圖上含主筋標註「%d-%s」" % (cid, n_want, bar), "%d-%s" % (n_want, bar) in txt)
                check("%s 保護層採預設時標「假設值」" % cid, "假設值" in txt and "保護層" in txt)
                seen = set(_re2.findall(r"D\d+@\d+", txt))
                check("%s 箍筋標註皆可追溯到結果" % cid, seen <= {want_tie}, str(seen))
                if cid == "rc_column":
                    xs = sorted({round(e.dxf.center.x * 1000, 3) for e in outer})
                    gaps = {round(b - a, 1) for a, b in zip(xs, xs[1:])}
                    check("rc_column 主筋橫向間距＝引擎 centre_spacing",
                          gaps == {round(run["chosen"]["centre_spacing_mm"], 1)}, str(gaps))

        print("[2f] 基腳圖：圖上數字＝計算結果（D5，DG2）")
        if "foundation_isolated" in DS.CAPABILITIES:
            import re as _re3
            sys.path.insert(0, str(ROOT / "tools" / "foundation_section"))
            import make_foundation as MF
            for cid in ("foundation_isolated", "foundation_combined"):
                ex = rows[cid]["example"]
                res = DS.generate(cid, ex, publish=False)
                run = API.run_calculation(cid, ex)["result"]
                txt = _texts(res)
                doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
                fl = run["concrete"]["flexure"]
                want = "%s@%d" % (fl["bar"], round(fl["spacing_mm"]))
                check("%s 圖上含底筋標註「%s」" % (cid, want), want in txt)
                allowed = {want}
                if cid == "foundation_combined":
                    bf = run["beam_design"]["flexure"]
                    lw = "%s@%d" % (bf["bar"], round(bf["spacing_mm"]))
                    allowed.add(lw)
                    st = run["beam_design"]["shear"]["stirrup"]
                    allowed.add("%s@%d" % (st["bar"], round(st["spacing_mm"])))
                    check("%s 圖上含縱向底筋「%s」" % (cid, lw), lw in txt)
                seen = set(_re3.findall(r"D\d+@\d+", txt))
                check("%s 配筋標註皆可追溯到結果" % cid, seen <= allowed, str(seen - allowed))
                check("%s 保護層預設標「假設值」" % cid, "假設值" in txt)
                gm = run["geometry"]
                conc = sum(abs(_area(list(e.vertices_in_wcs()))) for e in
                           doc.modelspace().query('LWPOLYLINE[layer=="30_基腳混凝土"]'))
                want_a = gm["B_m"] * gm["L_m"] + (gm["B_m"] if cid == "foundation_isolated" else gm["B_m"]) * 0 \
                    + (gm["B_m"] if cid == "foundation_isolated" else gm["L_m"]) * gm["thickness_m"]
                check("%s 平面＋剖面混凝土面積 %.4f＝%.4f" % (cid, conc, want_a), abs(conc - want_a) < 1e-6)
                db = MF.BAR_DIA[fl["bar"]]
                dots = sorted(e.dxf.center.x for e in doc.modelspace().query('CIRCLE[layer=="40_鋼筋"]')
                              if abs(e.dxf.radius * 2000 - db) < 1e-6)
                gaps = {round((b - a) * 1000) for a, b in zip(dots, dots[1:])}
                check("%s 剖面點間距＝結果間距" % cid, gaps == {round(fl["spacing_mm"])}, str(gaps))

        print("[2g] 滯洪池／沉砂池圖：圖上數字＝計算結果（D6，DG2）")
        if "detention_basin" in DS.CAPABILITIES:
            sys.path.insert(0, str(ROOT / "tools" / "basin_section"))
            import make_basin as MB
            ex = rows["detention_basin"]["example"]
            res = DS.generate("detention_basin", ex, publish=False)
            run = API.run_calculation("detention_basin", ex)["result"]
            txt = _texts(res)
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            lay_ = MB.layout("detention_basin", run, ex)
            for t_, _e in MB.levels(lay_):
                check("滯洪池圖含高程標註「%s」" % t_.replace("%%c", "Ø"), t_ in txt or t_.replace("%%c", "Ø") in txt)
            check("計算最高水位＝結果 %.2f" % run["max_stage_m"], ("%+.2f" % run["max_stage_m"]) in txt)
            ys = sorted({round(v[1], 6) for e in doc.modelspace().query('LWPOLYLINE[layer=="30_池體輪廓"]')
                         for v in e.vertices_in_wcs()})
            sb = min(ys)
            check("剖面壩頂高＝輸入 %.2f" % lay_["crest"],
                  any(abs((y - sb) - lay_["crest"]) < 1e-6 for y in ys))
            wl = [e for e in doc.modelspace().query('LINE[layer=="33_水位"]')]
            check("水位線高＝結果最高水位", len(wl) == 1 and abs(wl[0].dxf.start.y - sb - run["max_stage_m"]) < 1e-6)
            Wp = lay_["Lb"] + 2 * lay_["z"] * lay_["crest"]
            xs = [v[0] for e in doc.modelspace().query('LWPOLYLINE[layer=="30_池體輪廓"]') for v in e.vertices_in_wcs()]
            check("池頂寬＝池底＋2·z·壩高", abs(max(xs) - Wp) < 1e-6 or abs((max(xs) - min(xs)) - Wp) < 1e-6)
        if "sediment_basin" in DS.CAPABILITIES:
            ex = rows["sediment_basin"]["example"]
            res = DS.generate("sediment_basin", ex, publish=False)
            run = API.run_calculation("sediment_basin", ex)["result"]
            txt = _texts(res)
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            check("沉砂池圖含「容量 %d m3」" % round(run["capacity_m3"]), "容量 %d m3" % round(run["capacity_m3"]) in txt)
            check("沉砂池圖註明池壁結構另行設計", "池壁結構另行設計" in txt)
            plan = [e for e in doc.modelspace().query('LWPOLYLINE[layer=="30_池體輪廓"]') if e.closed]
            a_ = abs(_area(list(plan[0].vertices_in_wcs())))
            check("平面面積＝長×寬＝引擎池底面積",
                  abs(a_ - run["length_m"] * run["width_m"]) < 1e-6 and abs(a_ - run["footprint_m2"]) < 1e-3)

        print("[2h] 水面線縱斷面圖：縱橫異比例、圖上數字＝計算結果（D7，DG2）")
        if "channel_profile" in DS.CAPABILITIES:
            sys.path.insert(0, str(ROOT / "tools" / "profile_section"))
            import make_profile as MP
            ex = rows["channel_profile"]["example"]
            res = DS.generate("channel_profile", ex, publish=False)
            run = API.run_calculation("channel_profile", ex)["result"]
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            msp = doc.modelspace()
            crest = MP.channel_depth(ex, run)
            lines, short, fb = MP.build_lines(run, crest)
            reach = max(x for x, _ in lines["bed"])
            lo, hi = MP.elevation_range(lines)
            H, V = MP.pick_scales(reach, hi - lo)
            k = H / float(V)
            check("縱向必須誇大（V < H）且不超過上限",
                  V < H and k <= MP.MAX_EXAGGERATION + 1e-9, "H=%d V=%d" % (H, V))
            txt = _texts(res)
            check("圖上同時標出橫向與縱向比例",
                  ("橫向 1:%d" % H) in txt and ("縱向 1:%d" % V) in txt)
            check("垂直誇大倍數寫在圖上", ("垂直誇大 %s 倍" % MP._ktext(k)) in txt)
            check("圖上沒有 DIMENSION（縱橫異比例自動量測會錯）",
                  len(msp.query("DIMENSION")) == 0)
            for key, layer in (("bed", "30_溝底線"), ("top", "31_溝頂線"), ("ws", "33_水面線"),
                               ("norm", "34_正常水深線"), ("crit", "35_臨界水深線")):
                pl = msp.query('LWPOLYLINE[layer=="%s"]' % layer)
                ok = False
                if len(pl) == 1:
                    pts = [(p[0], p[1]) for p in pl[0].get_points("xy")]
                    ok = len(pts) == len(lines[key]) and all(
                        abs(px - x) < 1e-6 and abs(py - y * k) < 1e-6
                        for (px, py), (x, y) in zip(pts, lines[key]))
                check("%s 折點＝結果（高程×%s）" % (layer, MP._ktext(k)), ok)
            check("溝頂線＝溝底＋溝深",
                  all(abs((ty - by) - crest) < 1e-9
                      for (_, by), (_, ty) in zip(lines["bed"], lines["top"])))
            dy_norm = [ny - by for (_, by), (_, ny) in zip(lines["bed"], lines["norm"])]
            dy_crit = [cy - by for (_, by), (_, cy) in zip(lines["bed"], lines["crit"])]
            check("正常／臨界水深線＝結果水深",
                  all(abs(d - run["normal_depth_m"]) < 1e-9 for d in dy_norm)
                  and all(abs(d - run["critical_depth_m"]) < 1e-9 for d in dy_crit),
                  "%.4f/%.4f" % (dy_norm[0], dy_crit[0]))
            labels = {e.dxf.text for e in msp.query('TEXT[layer=="42_尺寸"]')}
            check("每個樁號都標在圖上",
                  all(("%g" % s["chainage_m"]) in labels for s in run["stations"]))
            step = MP.tick_step(hi - lo, V)
            ticks = sorted({float(t) for t in labels if t.count(".") == 1 and t.replace(".", "").isdigit()})
            check("高程刻度皆為 %.2f 的整數倍且落在範圍內" % step,
                  bool(ticks) and all(abs((t / step) - round(t / step)) < 1e-9 and lo - 1e-9 <= t <= hi + 1e-9
                                      for t in ticks), str(ticks))
            # 出水高不足：改淺溝深，必須標出區段且樁號與結果一致
            ex2 = dict(ex)
            ex2["channel_depth_m"] = 0.78
            res2 = DS.generate("channel_profile", ex2, publish=False)
            run2 = API.run_calculation("channel_profile", ex2)["result"]
            _l2, short2, _f2 = MP.build_lines(run2, 0.78)
            txt2 = _texts(res2)
            check("出水高不足時圖上標「出水高不足區段」", short2 and "出水高不足區段" in txt2)
            check("出水高不足樁號與結果一致（摘要把樁號列全）",
                  all(("%g m" % c) in txt2 for c in short2), str(short2))

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
