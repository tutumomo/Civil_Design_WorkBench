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

import json
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
        "steel_column", "building_frame", "foundation_pile", "settlement_assessment",
    "box_culvert", "channel_hydraulics", "slope_stability", "block_wall",
}
EXPECTED_NOT_APPLICABLE = {"hydrology"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _gi_sel(x):
    x = float(x)
    return "%d" % round(x) if abs(x - round(x)) < 1e-9 else "%.1f" % x


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

        print("[2i] 鋼柱柱腳詳圖：平面／立面幾何與圖上數字＝計算結果（D8，DG2）")
        if "steel_column" in DS.CAPABILITIES:
            sys.path.insert(0, str(ROOT / "tools" / "steel_base_section"))
            import make_steel_base as SB
            ex = rows["steel_column"]["example"]
            res = DS.generate("steel_column", ex, publish=False)
            run = API.run_calculation("steel_column", ex)["result"]
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            msp = doc.modelspace()
            lay_ = SB.layout(ex, run)
            txt = _texts(res)

            def rects(layer, upper):
                # 平面在 y > -1、立面在 y < -1（立面整體下移），用 -1 m 分界
                out = []
                for e in msp.query('LWPOLYLINE[layer=="%s"]' % layer):
                    pts = list(e.vertices_in_wcs())
                    ys = [p[1] for p in pts]
                    if (max(ys) > -1.0) == upper:
                        xs = [p[0] for p in pts]
                        out.append((max(xs) - min(xs), max(ys) - min(ys), min(ys), max(ys)))
                return out

            plate = rects("31_基板", True)
            check("平面基板 = B×N",
                  len(plate) == 1 and abs(plate[0][0] - lay_["B"]) < 1e-6
                  and abs(plate[0][1] - lay_["N"]) < 1e-6, str(plate))
            ped = rects("32_承台混凝土", True)
            check("平面承台 = 承台 B×N",
                  len(ped) == 1 and abs(ped[0][0] - lay_["ped_B"]) < 1e-6
                  and abs(ped[0][1] - lay_["ped_N"]) < 1e-6, str(ped))
            st = []
            for e in msp.query('LWPOLYLINE[layer=="30_鋼構材"]'):
                pts = list(e.vertices_in_wcs())
                if max(p[1] for p in pts) > -1.0:
                    st.append(pts)
            w = max(p[0] for pts in st for p in pts) - min(p[0] for pts in st for p in pts)
            hh = max(p[1] for pts in st for p in pts) - min(p[1] for pts in st for p in pts)
            check("平面 H 型鋼 = h×b", abs(w - lay_["b"]) < 1e-6 and abs(hh - lay_["h"]) < 1e-6,
                  "%.3f×%.3f" % (hh, w))
            holes = {(round(c.dxf.center.x, 6), round(c.dxf.center.y, 6))
                     for c in msp.query('CIRCLE[layer=="40_錨栓"]')}
            want = {(round(x, 6), round(y, 6)) for x, y in lay_["positions"]}
            check("錨栓孔位＝結果 %d 個" % lay_["n_anchor"], holes == want, str(holes ^ want))
            check("錨栓孔徑＝結果 Ø%s" % _gi_sel(lay_["d_mm"]),
                  all(abs(c.dxf.radius * 2000 - lay_["d_mm"]) < 1e-6
                      for c in msp.query('CIRCLE[layer=="40_錨栓"]')))
            rods = [e for e in msp.query('LINE[layer=="40_錨栓"]')
                    if abs(e.dxf.start.x - e.dxf.end.x) < 1e-9]
            want_len = lay_["embed"] + lay_["grout"] + lay_["t"]    # 由基板頂算到埋深底
            check("立面錨栓長＝埋深＋基板厚（由板頂起算）",
                  bool(rods) and all(abs(abs(e.dxf.start.y - e.dxf.end.y) - want_len) < 1e-6 for e in rods),
                  "%d 支，%.3f m" % (len(rods), abs(rods[0].dxf.start.y - rods[0].dxf.end.y) if rods else 0.0))
            pede = rects("32_承台混凝土", False)
            check("立面承台深度＝埋深＋%s mm" % _gi_sel(SB.PED_EXTRA_M * 1000),
                  len(pede) == 1 and abs(pede[0][1] - (lay_["embed"] + SB.PED_EXTRA_M)) < 1e-6, str(pede))
            check("摘要含錨栓型式與埋深",
                  ("%d-" % lay_["n_anchor"]) in txt and ("埋深 hef" in txt)
                  and (_gi_sel(lay_["embed_mm"]) in txt))
            check("腹板方向板厚參考值揭露（＞板厚）", "腹板方向（參考）" in txt and "＞ 板厚" in txt)
            check("承台高度未提供已揭露", "承台高度計算結果未提供" in txt)
            check("圖上有平面圖與立面圖標題", "平面圖" in txt and "立面圖" in txt)
            if lay_["edge_edge"] is not None:
                check("錨栓至板邊距離＝檢核結果",
                      (_gi_sel(lay_["edge_edge"]) in txt) and (_gi_sel(lay_["edge_limit"]) in txt))
            # 有灌漿層時：基板底與承台頂的距離＝灌漿厚度
            ex2 = json.loads(json.dumps(ex))
            ex2["base_plate"]["grout_above_concrete"] = 0.05
            ex2["base_plate"]["support_condition"] = "grout_pad"
            res2 = DS.generate("steel_column", ex2, publish=False)
            doc2 = ezdxf.readfile(next(f["path"] for f in res2["files"] if f["kind"] == "dxf"))
            m2 = doc2.modelspace()
            grout = [e for e in m2.query('LWPOLYLINE[layer=="34_灌漿層"]')]
            check("灌漿高出混凝土面時畫出灌漿層", len(grout) == 1)

            ped_top = [p[1] for e in m2.query('LWPOLYLINE[layer=="32_承台混凝土"]')
                       for p in e.vertices_in_wcs() if p[1] < -1.0]
            plate_bot = [p[1] for e in m2.query('LWPOLYLINE[layer=="31_基板"]')
                         for p in e.vertices_in_wcs() if p[1] < -1.0]
            check("灌漿層厚＝輸入 0.05 m",
                  bool(ped_top) and bool(plate_bot)
                  and abs(min(plate_bot) - max(ped_top) - 0.05) < 1e-6)
            # 柱斷面大於基板 → 拒絕出圖
            ex3 = json.loads(json.dumps(ex))
            ex3["column"]["section"]["h_mm"] = 900.0
            try:
                DS.generate("steel_column", ex3, publish=False)
                check("柱斷面大於基板時拒絕出圖", False, "竟然出了圖")
            except DS.SectionError:
                check("柱斷面大於基板時拒絕出圖", True)

        print("[2j] 構架立面圖：線架幾何與構材配筋表＝計算結果（D9，DG2）")
        if "building_frame" in DS.CAPABILITIES:
            sys.path.insert(0, str(ROOT / "tools" / "frame_section"))
            import make_frame as MF
            ex = rows["building_frame"]["example"]
            res = DS.generate("building_frame", ex, publish=False)
            run = API.run_calculation("building_frame", ex)["result"]
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            msp = doc.modelspace()
            geo = MF.frame_geo(run)
            txt = _texts(res)
            n_bay = len(geo["grid"]) - 1
            n_sto = len(geo["storey_heights"])

            check("構材數＝引擎：梁 %d、柱 %d" % (len(geo["beams"]), len(geo["columns"])),
                  len(geo["beams"]) == n_bay * n_sto and len(geo["columns"]) == len(geo["grid"]) * n_sto)
            check("構材編號與引擎 members 完全一致",
                  {b["member"] for b in geo["beams"]} | {c["member"] for c in geo["columns"]}
                  == {m["member"] for m in run["members"]},
                  str({b["member"] for b in geo["beams"]} ^
                      {m["member"] for m in run["members"] if m["kind"] == "beam"}))
            # 梁矩形：柱面之間、梁頂＝該層樓層高、梁深＝斷面深
            ok = True
            for b in geo["beams"]:
                lv, ix = b["level"], b["bay"]
                ok = ok and abs(b["x0"] - (geo["grid"][ix] + geo["col_w"] / 2.0)) < 1e-9 \
                    and abs(b["x1"] - (geo["grid"][ix + 1] - geo["col_w"] / 2.0)) < 1e-9 \
                    and abs(b["y_top"] - geo["elevs"][lv]) < 1e-9 \
                    and abs((b["y_top"] - b["y_bot"]) - geo["beam_d"]) < 1e-9
            check("梁矩形＝柱面之間×梁深、梁頂＝樓層高", ok)
            ok = all(abs((c["y1"] - c["y0"]) - geo["storey_heights"][c["level"] - 1]) < 1e-9
                     and abs(c["x"] - geo["grid"][c["axis"]]) < 1e-9 for c in geo["columns"])
            check("柱矩形＝樓層高、位於軸線上", ok)
            # 圖面折線：每支構材一個封閉矩形，四角＝geo
            for layer, items in (("31_梁", geo["beams"]), ("30_柱", geo["columns"])):
                got = []
                for e in msp.query('LWPOLYLINE[layer=="%s"]' % layer):
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    got.append((round(min(p[0] for p in pts), 6), round(max(p[0] for p in pts), 6),
                                round(min(p[1] for p in pts), 6), round(max(p[1] for p in pts), 6)))
                want = []
                for it in items:
                    if layer == "31_梁":
                        want.append((round(it["x0"], 6), round(it["x1"], 6),
                                     round(it["y_bot"], 6), round(it["y_top"], 6)))
                    else:
                        want.append((round(it["x"] - geo["col_w"] / 2.0, 6),
                                     round(it["x"] + geo["col_w"] / 2.0, 6),
                                     round(it["y0"], 6), round(it["y1"], 6)))
                check("%s 有 %d 個矩形且與結果一致" % (layer, len(items)),
                      sorted(got) == sorted(want), "%d/%d" % (len(got), len(want)))
            check("每支構材的編號都標在圖上",
                  all(m["member"] in txt for m in run["members"]))
            check("軸線圈數＝軸線數，標 X1…Xn",
                  len(msp.query('CIRCLE[layer=="34_軸線"]')) == len(geo["grid"])
                  and all("X%d" % (i + 1) in txt for i in range(len(geo["grid"]))))
            check("尺寸標註數＝層高＋跨徑＋總寬＋總高",
                  len(msp.query("DIMENSION")) == n_sto + n_bay + 2,
                  str(len(msp.query("DIMENSION"))))
            # 構材配筋表＝designs[] 逐列引用
            rows_s = MF.schedule_rows(run)
            des = {d["member"]: d for d in run["designs"]}
            check("配筋表列數＝構材數", len(rows_s) == len(run["members"]))
            b0 = des["B1_0"]["flexure"]
            c0 = des["C1_0"]["chosen"]
            row_b = next(r for r in rows_s if r["id"] == "B1_0")
            row_c = next(r for r in rows_s if r["id"] == "C1_0")
            check("梁主筋＝引擎 bar@spacing",
                  row_b["main"] == "%s@%d" % (b0["bar"], b0["spacing_mm"]), row_b["main"])
            check("梁箍筋＝引擎 shear",
                  row_b["stirrup"] == "%s@%d %d肢" % (
                      des["B1_0"]["shear"]["bar"], des["B1_0"]["shear"]["spacing_mm"],
                      des["B1_0"]["shear"]["legs"]), row_b["stirrup"])
            check("柱主筋＝引擎 chosen 支數×筋號（每面支數）",
                  row_c["main"] == "%d-%s（%d/面）" % (c0["bars_total"], c0["bar"],
                                                      c0["bars_per_face"]), row_c["main"])
            check("梁利用率取撓曲與剪力較大者",
                  abs(float(row_b["util"]) - max(b0["utilization"],
                                                 des["B1_0"]["shear"]["utilization"])) < 5e-4)
            check("斷面欄＝引擎 b×h（cm）",
                  row_b["section"] == "%d×%d" % (round(b0["b_mm"] / 10), round(b0["h_mm"] / 10))
                  and row_c["section"] == "%d×%d" % (round(des["C1_0"]["b_mm"] / 10),
                                                     round(des["C1_0"]["h_mm"] / 10)))
            check("摘要引用靜載重合計與層間位移比",
                  ("%.0f kN" % run["loads"]["total_dead_weight_kn"]) in txt
                  and ("%.5f" % max(d["max_storey_drift_ratio"] for d in run["drift"])) in txt)
            check("每米寬選筋的慣例已揭露（每米／mm²/m）", "每米寬" in txt and "mm²/m" in txt)
            check("分張限制寫在說明欄", "尚未實作自動分張" in txt)
            H = MF.pick_scale(geo)
            check("自動比例放得進 A3 可繪區且不粗於 1:%d" % MF.MAX_SHEET_SCALE,
                  H <= MF.MAX_SHEET_SCALE
                  and MF.content_size(geo)[0] * 1000.0 / H <= 183.0
                  and MF.content_size(geo)[1] * 1000.0 / H <= 249.45, "1:%d" % H)
            # 分張守門：跨度拉到 40 跨 12 m 必須明確拒絕，不得偷偷縮比例
            wide = {"grid": [12.0 * i for i in range(41)],
                    "elevs": geo["elevs"], "storey_heights": geo["storey_heights"]}
            try:
                MF.pick_scale(wide)
                check("跨數過多時明確拒絕（未實作分張）", False, "竟然挑了比例 %d" % MF.pick_scale(wide))
            except SystemExit as se:
                check("跨數過多時明確拒絕（未實作分張）", "分張" in str(se), str(se))

        print("[2k] 樁位配置圖／基腳沉陷配置圖：平面位置與圖上數字＝計算結果（D10，DG2）")
        for cid, mod in (("foundation_pile", "make_foundation_plan"),
                         ("settlement_assessment", "make_foundation_plan")):
            if cid not in DS.CAPABILITIES:
                continue
            sys.path.insert(0, str(ROOT / "tools" / "foundation_plan"))
            import importlib
            FP = importlib.import_module(mod)
            ex = rows[cid]["example"]
            res = DS.generate(cid, ex, publish=False)
            run = API.run_calculation(cid, ex)["result"]
            doc = ezdxf.readfile(next(f["path"] for f in res["files"] if f["kind"] == "dxf"))
            msp = doc.modelspace()
            txt = _texts(res)

            if cid == "foundation_pile":
                geo = FP.pile_geo(run)
                check("FP-1 樁符號數＝結果 n_piles",
                      len(msp.query('CIRCLE[layer=="30_樁位"]')) == run["n_piles"])
                centres = {(round(c.dxf.center.x, 6), round(c.dxf.center.y, 6))
                           for c in msp.query('CIRCLE[layer=="30_樁位"]')}
                want = {(round(p["x_m"], 6), round(p["y_m"], 6)) for p in run["piles"]}
                check("FP-1 樁位＝結果 (x_m, y_m)", centres == want, str(centres ^ want))
                check("FP-1 每樁標號與軸力都在圖上",
                      all(("P%d %.0f kN" % (p["pile"], p["P_kN"])) in txt for p in run["piles"]))
                check("FP-1 摘要引用 P／Mx／My／Ix／Iy／Q_allow",
                      ("%.0f kN" % run["P_kN"]) in txt
                      and ("%.1f kN" % run["Q_allow_kN"]) in txt
                      and ("%.3f／%.3f m²" % (run["Ix_m2"], run["Iy_m2"])) in txt)
                # 說明文字在紙面上會折行，比對前先去掉換行
                flat = txt.replace("\n", "")
                check("FP-1 未畫樁徑（圖上只有符號，說明揭露不代表樁徑）",
                      "圓的大小不代表實際樁徑" in flat and "不得作為樁帽配筋圖使用" in flat)
                check("FP-1 樁群形心十字在 (0,0)",
                      any(abs(e.dxf.start.x - e.dxf.end.x) < 1e-9
                          and abs(e.dxf.start.x) < 1e-9
                          and abs(e.dxf.start.y + e.dxf.end.y) < 1e-9
                          for e in msp.query('LINE[layer=="31_標記"]')))
                # 拉力樁：把 P 改大讓最小樁軸力變負，圖上必須標「拉力」
                ex2 = json.loads(json.dumps(ex))
                ex2["P_kN"] = -100.0
                res2 = DS.generate("foundation_pile", ex2, publish=False)
                run2 = API.run_calculation("foundation_pile", ex2)["result"]
                check("FP-1 出現拉力樁時圖上標「拉力」",
                      any(p["P_kN"] < 0 for p in run2["piles"]) and "拉力" in _texts(res2))
            else:
                geo = FP.footing_geo(run)
                rects = []
                for e in msp.query('LWPOLYLINE[layer=="30_基腳"]'):
                    pts = list(e.vertices_in_wcs())
                    rects.append((round(min(p[0] for p in pts), 6), round(min(p[1] for p in pts), 6),
                                  round(max(p[0] for p in pts), 6), round(max(p[1] for p in pts), 6)))
                want = [(round(f["x0"], 6), round(f["y0"], 6),
                         round(f["x1"], 6), round(f["y1"], 6)) for f in geo["footings"]]
                check("FS-1 基腳矩形＝結果中心±B/L", sorted(rects) == sorted(want))
                check("FS-1 每座基腳的編號與總沉陷都在圖上",
                      all(f["id"] in txt and ("%.1f mm" % f["total_settlement_mm"]) in txt
                          for f in run["footings"]))
                ad = run["angular_distortion"]
                check("FS-1 摘要的最大角變量＝結果（含倒數）",
                      ("%.6f" % ad["max_angular_distortion"]) in txt
                      and ("1/%s" % format(int(round(1.0 / ad["max_angular_distortion"])), ",")) in txt)
                check("FS-1 角變量表列出所有相鄰配對",
                      all(("%s–%s" % (p["a"], p["b"])) in txt for p in ad["pairs"]),
                      str([("%s–%s" % (p["a"], p["b"])) for p in ad["pairs"]]))
                check("FS-1 說明揭露基腳埋深／高程未由計算器決定",
                      "基腳埋深" in txt and "未由計算器決定" in txt)
                # 超限：把沉陷放大到超過容許值，圖上必須標「超限」
                ex2 = json.loads(json.dumps(ex))
                ex2["footings"][0]["q_kpa"] = 600.0
                res2 = DS.generate("settlement_assessment", ex2, publish=False)
                run2 = API.run_calculation("settlement_assessment", ex2)["result"]
                ng = [f for f in run2["footings"] if not f["ok"]]
                check("FS-1 總沉陷超限時圖上標「超限」",
                      bool(ng) and "超限" in _texts(res2), "%d 座" % len(ng))
            H = FP.pick_scale(geo)
            w, h = FP.content_size(geo, H)
            check("%s 自動比例放得進 A3 可繪區（1:%d）" % (cid, H),
                  H <= FP.MAX_SHEET_SCALE and w * 1000.0 / H <= 183.0
                  and h * 1000.0 / H <= 249.45)
            wide = {"bbox": (0.0, 0.0, 400.0, 400.0), "xs": [0.0, 400.0], "ys": [0.0, 400.0]}
            try:
                FP.pick_scale(wide)
                check("%s 範圍過大時明確拒絕（未實作分張）" % cid, False, "竟然挑了比例")
            except SystemExit as se:
                check("%s 範圍過大時明確拒絕（未實作分張）" % cid, "分張" in str(se))

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
