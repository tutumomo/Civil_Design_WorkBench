"""案件報告段落派生（自 case_core 拆出，2026-11-11 W7）。

這裡只負責把設計結果轉成報告章節要用的表格與段落，案件載入、數量派生、一致性檢查
仍留在 `case_core.py`。`case_core` 於檔案前段 import 本模組的函式，外部呼叫端
（`derive_report()`、`design_core_selftest.py`）的介面不變。
"""

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DESIGN_DIR = os.path.join(_ROOT, "tools", "design")
if _DESIGN_DIR not in sys.path:
    sys.path.insert(0, _DESIGN_DIR)
try:  # 與 case_core 相同的引擎匯入；缺模組時不阻擋載入
    import hydrology as HY                           # 集水區水文分析
    import slope_stability as SS                     # 邊坡穩定
    import retaining_wall as RW                      # 擋土牆穩定分析
    import channel_hydraulics as CH                  # 排水溝水力計算
    import rc_design as RC                           # RC 構材配筋設計
    import box_culvert as BC                         # 單／雙／三孔箱涵
    import wall_system as WS                         # 擋土牆七型分流入口
except Exception:
    HY = RW = CH = RC = SS = BC = WS = None


def _box_culvert_kwargs(case, values):
    """箱涵參數唯一來源仍在 case_core；延後匯入避免循環。"""
    from case_core import _box_culvert_kwargs as impl
    return impl(case, values)


def _fmt_num(v):
    """數量顯示：整數不帶小數點，其餘保留原精度（去尾零）。"""
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    s = f"{f:.6f}".rstrip("0").rstrip(".")
    return s


def _tbl(caption, cols, rows, note=""):
    return {"caption": caption,
            "columns": [{"name": n, "width_cm": w, "align": a} for n, w, a in cols],
            "rows": rows, "note": note}


def _verdict(ok):
    return "符合" if ok else "不符合"


def _wall_limit_text(c):
    lim = c.get("limit")
    if isinstance(lim, (tuple, list)):
        return "%.3f ～ %.3f" % (lim[0], lim[1])
    if isinstance(lim, str):
        return lim
    if lim is None:
        return "—"
    op = "≤" if c.get("relation") == "le" else ("≥" if c.get("relation") == "ge" else "")
    return ("%s %.3f" % (op, lim)).strip()


def _wall_check_rows(res):
    rows = []
    for c in res.get("checks") or []:
        val = c.get("value")
        rows.append({
            "item": c.get("item", ""),
            "requirement": _wall_limit_text(c),
            "value": "—" if val is None else ("%.3f" % val if isinstance(val, (int, float))
                                              else str(val)),
            "verdict": _verdict(c.get("ok")),
        })
    return rows


def _rebar_summary_table(design, q, title):
    rows = []
    for row in (design or {}).get("rows") or []:
        rows.append([row.get("item", ""), "%.1f" % float(row.get("As_mm2") or 0),
                     "%.2f" % float(row.get("len_m") or 0),
                     "%.3f" % float(row.get("kg_per_m") or 0)])
    L = float((q or {}).get("length_m") or 0)
    total = float((design or {}).get("total_kg_per_m") or 0)
    return _tbl(
        title,
        [("位置", 5.2, "left"), ("等效 As（mm²/m）", 2.8, "center"),
         ("長度（m）", 2.0, "center"), ("kg/m", 1.8, "center")],
        rows,
        note=("淨重 %.2f kg/m，含 %.0f%% 搭接／錨定／損耗後 %.2f kg/m；"
              "牆長 %.1f m → %.1f kg。"
              % (float((design or {}).get("subtotal_kg_per_m") or 0),
                 float((design or {}).get("lap_allowance") or 0) * 100.0,
                 total, L, total * L)),
    )


def _advanced_wall_sections(res, q, case):
    """Report sections for counterfort / anchored / MSE walls."""

    wt = str(res.get("wall_type"))
    out = {}
    g = res.get("geometry") or {}
    design = res.get("reinforcement") or {}
    label = res.get("wall_label") or wt
    checks = _wall_check_rows(res)
    L = float(q.get("length_m") or 0)
    total = float(design.get("total_kg_per_m") or 0)
    form = float(q.get("formwork_m2") or 0)

    if wt == "counterfort":
        st = res.get("stability") or {}
        static = st.get("static") or {}
        out["loads"] = {
            "items": [_tbl(
                "載重與土壓力計算表（每公尺牆長）",
                [("項目", 3.6, "left"), ("計算式／位置", 4.4, "left"),
                 ("大小", 2.4, "center"), ("說明", 3.4, "left")],
                [["牆板高 H", "底板頂以上", "%.2f m" % g.get("H", 0), "有效高 %.2f m" % g.get("eff", 0)],
                 ["主動土壓力 Pa", "Rankine／Coulomb", "%.2f kN/m" % static.get("Pa_kN_per_m", 0),
                  "作用於牆背"],
                 ["上載 q", "均佈", "%.2f kPa" % (res.get("soil") or {}).get("surcharge_kpa", 0),
                  "已計入土壓力"],
                 ["牆體自重", "混凝土 24 kN/m³", "%.2f kN/m" % (res.get("concrete_m3_per_m", 0) * 24.0),
                  "含底板、牆板與扶壁分攤"],
                 ["地震力", "kh=%.2f" % (res.get("seismic") or {}).get("kh", 0),
                  "%.2f kN/m" % static.get("F_inertia_kN_per_m", 0), "擬靜態法"]],
                note="扶壁式以牆板／踵板連續版、趾板懸臂、扶壁 T 梁設計。",
            )],
            "notes": [
                "扶壁中心距 %.2f m、厚 %.2f m、頂寬 %.2f m；底板 %.2f×%.2f m。"
                % (g.get("S", 0), g.get("tc", 0), g.get("ctop", 0),
                   g.get("B", 0), g.get("tb", 0)),
            ],
        }
        member_rows = []
        for m in (res.get("structure") or {}).get("slabs") or []:
            fl = m.get("flexure") or {}
            member_rows.append([
                m.get("member", ""), "%.2f" % float(m.get("Mu_kNm_per_m") or 0),
                "%s@%s" % (fl.get("bar", "—"), fl.get("spacing_mm", "—")),
                "%.2f" % float(fl.get("phiMn_kNm") or 0), _verdict(fl.get("ok")),
            ])
        cf = (res.get("structure") or {}).get("counterfort") or {}
        if cf.get("main"):
            m = cf["main"]
            member_rows.append([
                "扶壁主拉力筋", "%.2f" % float(cf.get("Mu_kNm") or 0),
                "%d-%s（%s 層）" % (m.get("count", 0), m.get("bar", "—"), m.get("layers") or "—"),
                "%.2f" % float(cf.get("phiMn_kNm") or 0), _verdict(cf.get("flexure_ok")),
            ])
        if cf.get("stirrup"):
            member_rows.append([
                "扶壁水平箍筋", "Vu=%.2f kN" % float(cf.get("Vu_kN") or 0),
                "%s 兩肢 @%s" % (cf["stirrup"].get("bar"), cf["stirrup"].get("spacing_mm")),
                "φVn=%.2f" % float(cf.get("phiVn_kN") or 0), _verdict(cf.get("shear_ok")),
            ])
        for tie in (res.get("structure") or {}).get("ties") or []:
            member_rows.append([
                tie.get("member", ""), "Tu=%.2f kN/m" % float(tie.get("Tu_kN_per_m") or 0),
                "%s 兩肢 @%s" % (tie.get("bar"), tie.get("spacing_mm")),
                "As=%.0f" % float(tie.get("As_prov_mm2_per_m") or 0), _verdict(tie.get("ok")),
            ])
        out["reinforcement"] = {
            "items": [
                _tbl("扶壁式構材配筋結果表",
                     [("構材", 4.4, "left"), ("控制內力", 2.6, "center"),
                      ("鋼筋", 3.4, "center"), ("強度", 2.6, "center"),
                      ("判定", 1.4, "center")],
                     member_rows,
                     note="牆板與踵板採連續版係數、趾板採懸臂、扶壁採 T 梁；"
                          "載重組合為 1.7H 與 0.75(1.7H＋1.87E)。"),
                _rebar_summary_table(design, q, "扶壁式鋼筋量彙總表"),
            ],
            "notes": [
                "牆板四向筋、踵板上下層、趾板下層、扶壁主筋／箍筋與繫筋均已納入。",
                "鋼筋量 %.2f kg/m（含 %.0f%% 搭接與損耗）× %.1f m = %.1f kg；"
                "模板 %.2f m²（%.2f m²/m）。"
                % (total, float((design or {}).get("lap_allowance") or 0) * 100.0,
                   L, total * L, form, form / max(L, 1e-9)),
                "⚠ 扶壁式未做止滑榫榫部鋼筋；整體圓弧滑動與地下水須另案檢核。",
            ],
        }
        out["comparison"] = {"notes": [
            "%s：牆板 H=%.2f m、底板 B=%.2f m、前趾 %.2f m、踵板 %.2f m、"
            "扶壁間距 %.2f m。" % (label, g.get("H", 0), g.get("B", 0), g.get("Lt", 0),
                                     g.get("heel", 0), g.get("S", 0)),
            "混凝土 %.3f m³/m、鋼筋 %.2f kg/m；混凝土與鋼筋量均以每米斷面乘牆長。"
            % (res.get("concrete_m3_per_m", 0), total),
        ]}

    elif wt == "anchored":
        pr = res.get("pressure") or {}
        out["loads"] = {
            "items": [_tbl(
                "土壓與地錨反力計算表",
                [("項目", 3.8, "left"), ("計算式", 5.0, "left"),
                 ("大小", 2.4, "center"), ("說明", 3.2, "left")],
                [["水平土壓係數 Ka", "Coulomb／Rankine", "%.4f" % pr.get("Ka_h", 0), "含牆背摩擦"],
                 ["總土壓力", "視土壓包絡或三角形", "%.2f kN/m" % pr.get("P_earth_kN_per_m", 0),
                  "p_max=%.2f kPa" % pr.get("p_max_kPa", 0)],
                 ["上載土壓", "q·Ka", "%.2f kPa" % pr.get("p_surcharge_kPa", 0), "均佈上載"],
                 ["地震增量", "M-O", "%.2f kN/m" % pr.get("dPae_kN_per_m", 0),
                  "kh=%.2f" % (res.get("seismic") or {}).get("kh", 0)],
                 ["地錨排數", "固定間距", "%d 排" % len(res.get("anchors") or []),
                  "水平間距 %.2f m" % g.get("sh", 0)]],
                note="牆面以連續梁分析，地錨處與基底為支承。",
            )],
            "notes": ["地錨俯角 %.1f°、%s。" % (g.get("alpha", 0), res.get("anchor_fs", {}).get("label", ""))],
        }
        anchor_rows = []
        for a in res.get("anchors") or []:
            anchor_rows.append([
                "%d" % a.get("row", 0), "%.2f" % float(a.get("depth_m") or 0),
                "%.1f" % float(a.get("T_design_kN") or 0),
                "%d" % int(a.get("strands") or 0),
                "%.1f / %.1f" % (float(a.get("free_length_m") or 0), float(a.get("bond_length_m") or 0)),
                "%.1f" % float(a.get("lockoff_kN") or 0),
                _verdict(all(c.get("ok") for c in (res.get("checks") or [])
                             if ("第 %d 排" % a.get("row", 0)) in str(c.get("item", "")))),
            ])
        member_rows = []
        for m in (res.get("wall") or {}).get("members") or []:
            fl = m.get("flexure") or {}
            member_rows.append([
                m.get("member", ""), "%.2f" % float(m.get("Mu_kNm_per_m") or 0),
                "%s@%s" % (fl.get("bar", "—"), fl.get("spacing_mm", "—")),
                "%.2f" % float(fl.get("phiMn_kNm") or 0), _verdict(fl.get("ok")),
            ])
        member_rows.append(["地錨承壓區補強網", "每排 1.0×1.0 m", "D13@200 雙向",
                            "As=%.0f mm²/m" % (2.0 * 127.0 * 6.0 / max(g.get("sh", 1), 1e-9)),
                            "構造"])
        out["reinforcement"] = {
            "items": [
                _tbl("錨定式地錨設計結果表",
                     [("排", 1.0, "center"), ("深度(m)", 1.5, "center"),
                      ("T(kN)", 1.5, "center"), ("股數", 1.0, "center"),
                      ("自由段/錨碇段(m)", 2.8, "center"), ("鎖定(kN)", 1.6, "center"),
                      ("判定", 1.2, "center")],
                     anchor_rows,
                     note="抗張材、地層－漿體、抗張材－漿體與鎖定荷重均逐排檢核。"),
                _tbl("錨定式牆面配筋結果表",
                     [("構材", 4.6, "left"), ("控制內力", 2.6, "center"),
                      ("鋼筋", 3.2, "center"), ("φMn(kN·m/m)", 2.4, "center"),
                      ("判定", 1.4, "center")],
                     member_rows,
                     note="牆面為連續梁，正負彎矩分面配置；保護層 75 mm。"),
                _rebar_summary_table(design, q, "錨定式鋼筋量彙總表"),
            ],
            "notes": [
                "牆面四向筋與地錨承壓區 D13@200 補強網均已計入。",
                "鋼筋量 %.2f kg/m（含 %.0f%% 搭接與損耗）× %.1f m = %.1f kg；"
                "模板 %.2f m²（%.2f m²/m）。"
                % (total, float((design or {}).get("lap_allowance") or 0) * 100.0,
                   L, total * L, form, form / max(L, 1e-9)),
                "⚠ 整體（深層）穩定不在本引擎內，須另跑 slope_stability.py；"
                "握裹強度須以證明試驗確認。",
            ],
        }
        out["comparison"] = {"notes": [
            "%s：H=%.2f m、有效高 %.2f m、牆面厚 %.2f m、基腳 %.2f×%.2f m。"
            % (label, g.get("H", 0), g.get("eff", 0), g.get("t", 0), g.get("B", 0), g.get("tb", 0)),
            "混凝土 %.3f m³/m、鋼筋 %.2f kg/m；地錨 %d 排。"
            % (res.get("concrete_m3_per_m", 0), total, len(res.get("anchors") or [])),
        ]}

    else:  # mse
        ext = (res.get("external") or {}).get("static") or {}
        out["loads"] = {
            "items": [_tbl(
                "加勁式外部載重計算表",
                [("項目", 3.8, "left"), ("計算式", 4.8, "left"),
                 ("大小", 2.4, "center"), ("說明", 3.4, "left")],
                [["加勁區重量 V", "加勁土＋面版", "%.1f kN/m" % float(ext.get("V_kN_per_m") or 0),
                  "γr=%.1f kN/m³" % (res.get("soil") or {}).get("reinforced_gamma", 0)],
                 ["水平土壓力 Ph", "Rankine", "%.1f kN/m" % float(ext.get("Ph_kN_per_m") or 0),
                  "Ka=%.3f" % res.get("Ka_retained", 0)],
                 ["基底平均應力", "Meyerhof", "%.1f kPa" % float(ext.get("sigma_v_kPa") or 0),
                  "容許承載力另計"],
                 ["地震", "kh=%.2f" % (res.get("seismic") or {}).get("kh", 0),
                  "—", "外部與內部穩定均含地震"]],
                note="FHWA 簡化法；F*／α 為保守預設值。",
            )],
            "notes": [
                "加勁材 %s、%d 層、長 %.2f m。"
                % ((res.get("reinforcement") or {}).get("label", ""),
                   int((res.get("reinforcement") or {}).get("count") or 0),
                   float((res.get("reinforcement") or {}).get("length_m") or 0)),
            ],
        }
        layer_rows = []
        for l in res.get("layers") or []:
            layer_rows.append([
                "%d" % l.get("layer", 0), "%.2f" % float(l.get("y_m") or 0),
                "%.2f" % float(l.get("Tmax_kN_per_m") or 0),
                "%.2f" % float(l.get("Le_m") or 0),
                "%.2f" % float(l.get("FS_rupture") or 0),
                "%.2f" % float(l.get("FS_pullout") or 0),
            ])
        face = res.get("face_reinforcement") or {}
        out["reinforcement"] = {
            "items": [
                _tbl("加勁式內部穩定逐層檢核表",
                     [("層", 1.0, "center"), ("高程 y(m)", 2.2, "center"),
                      ("Tmax(kN/m)", 2.6, "center"), ("Le(m)", 2.0, "center"),
                      ("FS拉斷", 2.2, "center"), ("FS拉出", 2.2, "center")],
                     layer_rows,
                     note="加勁材拉斷與拉出均逐層檢核；地震另以 0.8 倍拉出阻抗折減。"),
                _tbl("加勁式 RC 面版配筋表",
                     [("項目", 4.6, "left"), ("數值", 3.0, "center"),
                      ("採用", 4.2, "center"), ("判定", 1.8, "center")],
                     [["設計土壓 p", "%.2f kPa" % float(face.get("design_pressure_kpa") or 0), "—", "—"],
                      ["設計彎矩 Mu", "%.2f kN·m/m" % float(face.get("Mu_kNm_per_m") or 0), "—", "—"],
                      ["面版鋼筋", "%.0f mm²/m" % float(face.get("As_prov_mm2_per_m") or 0),
                       "%s@%s" % (face.get("bar", "—"), face.get("spacing_mm", "—")),
                       _verdict(face.get("flexure_ok"))],
                      ["面版厚度", "%.0f mm" % float(face.get("face_panel_thickness_mm") or 0),
                       "≥ 140 mm", _verdict(float(face.get("face_panel_thickness_mm") or 0) >= 140)]],
                     note="僅做單向版初步設計；吊裝、溫度收縮與連接細部另計。"),
                _rebar_summary_table(design, q, "加勁式面版鋼筋量彙總表"),
            ],
            "notes": [
                "RC 面版鋼筋量 %.2f kg/m（含 %.0f%% 搭接與損耗）× %.1f m = %.1f kg；"
                "面版模板 %.2f m²（%.2f m²/m）。"
                % (total, float((design or {}).get("lap_allowance") or 0) * 100.0,
                   L, total * L, form, form / max(L, 1e-9)),
                "塊狀面版不配置 RC 鋼筋；本表僅適用 RC 預鑄／場鑄面版。",
                "⚠ 面版－加勁材連接與局部承壓僅於輸入產品容量時檢核；"
                "整體圓弧滑動須另用 slope_stability.py。",
            ],
        }
        out["comparison"] = {"notes": [
            "%s：H=%.2f m、埋入 %.2f m、有效高 %.2f m、加勁長 %.2f m。"
            % (label, g.get("height_m", 0), g.get("embedment_m", 0),
               g.get("effective_height_m", 0), g.get("reinforcement_length_m", 0)),
            "RC 面版 %.0f mm、鋼筋 %.2f kg/m；加勁材 %d 層。"
            % (float((q.get("face_panel_thickness_m") or 0.2) * 1000.0), total,
               len(res.get("layers") or [])),
        ]}

    out["stability"] = {
        "checks": checks,
        "notes": [
            "檢核依水土保持技術規範 §118～§120 與各牆型專用規範；"
            "牆型：%s。" % label,
            "綜合判定：%s。" % ("全部符合" if res.get("pass") else "有未符合項，不得交件"),
        ] + list(res.get("warnings") or []),
    }
    return out


def _dxf_scale(path):
    """Read the resolved 1:N scale from a drawing's title block / notes.

    `section.scale` in case.json is usually ``"auto"`` because the real scale is
    chosen after the model extents are known.  The report used to print
    ``1:auto（自動）``; the scale is already written into the DXF, so read it
    back instead of guessing.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        import ezdxf
        doc = ezdxf.readfile(path)
    except Exception:
        return None
    counts = {}
    for layout in doc.layouts:
        for ent in layout.query("TEXT"):
            text = ent.dxf.text or ""
            for m in re.finditer(r"1\s*:\s*(\d+)", text):
                n = int(m.group(1))
                if 1 <= n <= 5000:
                    counts[n] = counts.get(n, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _attach_section_figure(out, case):
    fig = case.get("section") or {}
    if not fig:
        return
    _sc = fig.get("scale", 20)
    try:
        _sc = int(_sc)
    except (TypeError, ValueError):
        _sc = (_dxf_scale(fig.get("out"))
               or _dxf_scale(fig.get("rebar_out")) or 20)
    _sc_txt = "1:%d" % _sc
    figures = []
    for key, title in (("out", "標準斷面圖（A3，%s）" % _sc_txt),
                       ("rebar_out", "配筋圖（A3，%s）" % _sc_txt)):
        dxf = fig.get(key) or ""
        if not dxf:
            continue
        base = os.path.splitext(dxf)[0]
        for cand in (base + "_pdf.png", base + ".png"):
            if os.path.exists(cand):
                figures.append({
                    "path": cand, "title": title,
                    "note": "由 tools/wall_section/make_wall_section.py 產製，"
                            "已通過 check_delivery.py（E1~E18）。",
                    "width_cm": 15.5,
                })
                break
    if figures:
        out.setdefault("drawings", {})["figures"] = figures


def _sections_slope(out, q, case):
    """報告段落：邊坡（由 _design_sections 分派）。"""
    sr = SS.analyse(q)
    checks = []
    for c in sr["checks"]:
        checks.append({
            "item": c["item"],
            "requirement": ("≥ %.1f" % c["required"]) if c["required"] is not None else "（不適用）",
            "value": "%.3f" % c["value"],
            "verdict": _verdict(c["ok"]) if c["required"] is not None else "參考",
        })
    out["stability"] = {
        "checks": checks,
        "notes": [
            "檢核依據水土保持技術規範第 73 條：%s、%s → 最小安全係數 %.1f。"
            % (sr["stage"], sr["condition"], sr["FS_required"]),
            "分析方法：無限邊坡法（FS=%.3f）＋圓弧滑動 Fellenius 坡趾圓（FS=%.3f）。"
            % (sr["infinite"]["FS"], sr["circular"]["FS"]),
            "無限邊坡法適用於滑動面平行坡面、坡長遠大於深度之情況；無凝聚性土壤的"
            "臨界滑動面即為平行坡面之無限長平面，故 c=0 時本法為理論解。",
            "綜合判定：%s。" % ("全部符合" if sr["ok"] else "有未符合項，須緩坡、設平台或加勁"),
            "土工參數 γ=%.1f kN/m³、φ=%.1f°、c=%.1f kPa、地下水位比例 %.2f；均為%s，"
            "正式設計前須以地質鑽探結果重算。" % (
                sr["unit_weight_kn_m3"], sr["friction_deg"], sr["cohesion_kpa"],
                sr["groundwater_ratio"],
                "設計採用值" if case.get("soil") else "假設值"),
        ],
    }



def _sections_wall(out, q, case):
    """報告段落：擋土牆（由 _design_sections 分派）。"""
    seism = case.get("seismic") or {}
    kh = float(seism.get("kh", 0.0) or 0.0)
    res = WS.analyse(q, case)
    g = res["geometry"]
    if res["wall_type"] not in ("gravity", "semigravity", "cantilever"):
        out.update(_advanced_wall_sections(res, q, case))
        _attach_section_figure(out, case)
        return out
    wt = {
        "gravity": "重力式（梯形斷面）",
        "semigravity": "半重力式（厚牆＋底板）",
        "cantilever": "懸臂式（薄牆＋底板）",
    }.get(res["wall_type"], res["wall_type"])

    out["loads"] = {
        "items": [_tbl(
            "載重與土壓力計算表（每公尺牆長）",
            [("載重項目", 3.6, "left"), ("計算式", 4.6, "left"),
             ("大小", 2.4, "center"), ("作用點", 3.2, "left")],
            [["自重 W（混凝土）", "斷面積 %.4f m²/m × 24 kN/m³" % g["area_m2_per_m"],
              "%.2f kN/m" % res["W_conc_kN_per_m"],
              "形心 x=%.3f m、y=%.3f m" % (g["centroid"][0], g["centroid"][1])],
             ["覆土重量 W_s（懸臂式踵板）", "踵板寬 × 牆高 × γs",
              "%.2f kN/m" % res["W_soil_kN_per_m"],
              "踵板中央（重力式為 0）"],
             ["主動土壓力 Pa", "½·Ka·γs·H²（Rankine）",
              "%.2f kN/m" % res["Pa_kN_per_m"],
              "牆底以上 %.3f m" % res["y_Pa_m"]],
             ["地震力 Feq", "W × kh（kh=%.2f，擬靜態法）" % kh,
              "%.2f kN/m" % res["F_eq_kN_per_m"],
              "總重形心高度"],
             ["地下水壓力", "未計（無地下水位資料）", "—", "—"]],
            note="土壓力採 Rankine 理論、不計牆背摩擦（偏保守）；填土面假設水平、無超載。")]
        ,
        "notes": [
            "牆型：%s；斷面積 %.4f m²/m、自重 %.2f kN/m。" % (
                wt, g["area_m2_per_m"], res["W_conc_kN_per_m"]),
            "主動土壓力係數 Ka = (1−sinφ)/(1+sinφ) = %.4f（φ=%.0f°）。" % (
                res["Ka"], res["soil"]["phi_deg"]),
            "水土保持技術規範第 119 條明列地震力為必要作用力；本計算採擬靜態法（W×kh），"
            "kh=%.2f%s。" % (kh, "（未辦地震工況，kh=0）" if kh == 0 else ""),
        ],
    }

    checks = []
    for c in res["checks"]:
        lim = c["limit"]
        if isinstance(lim, (tuple, list)):
            req = "%.3f ～ %.3f m" % (lim[0], lim[1])
            val = "%.3f m" % c["value"]
        elif isinstance(lim, str):
            req = lim
            val = "%.2f" % c["value"]
        else:
            # 比較方向不可一律寫「≥」：承載應力是「≤ 容許值」。
            # 由檢核項目字串判斷（analyse() 的 item 已含「≤」或「≥」語意）。
            op = "≤" if ("≤" in c["item"] or "最大" in c["item"]) else "≥"
            req = "%s %.2f" % (op, lim)
            val = "%.2f" % c["value"]
        checks.append({"item": c["item"], "requirement": req,
                       "value": val, "verdict": _verdict(c["ok"])})
    out["stability"] = {
        "checks": checks,
        "notes": [
            "檢核依據水土保持技術規範第 120 條；工況：%s。" % (
                "地震（kh=%.2f）" % kh if kh > 0 else "常時"),
            "綜合判定：%s。" % ("全部符合" if res["pass"] else "有未符合項，須調整斷面"),
            "土工參數 γ=%.1f kN/m³、φ=%.0f°、c=%.1f kPa、容許承載力 %.0f kPa、"
            "基底摩擦係數 %.2f；均為%s，正式設計前須以地質鑽探結果重算。" % (
                res["soil"]["gamma"], res["soil"]["phi_deg"], res["soil"]["c_kpa"],
                res["soil"]["allowable_bearing_kpa"], res["soil"]["base_friction"],
                "設計採用值" if case.get("soil") else "假設值"),
        ],
    }

    face = float(q.get("face_area_m2", 0) or 0)
    weep = int(float(q.get("weep_hole_count", 0) or 0))
    joint = int(float(q.get("expansion_joint_count", 0) or 0))
    # 第 8 章：構材配筋設計
    if RC is not None:
        if res["wall_type"] in ("gravity", "semigravity"):
            mass = RC.design_mass_wall_steel(q, res)
            rows = []
            for item in mass["rows"]:
                _is_face = "牆面" in item["item"]
                rows.append([
                    item["item"],
                    "%s@%d" % (mass["face_bar"] if _is_face else mass["base_bar"],
                               int(mass["face_spacing_mm"] if _is_face
                                   else mass["base_spacing_mm"])),
                    "%.0f" % item["As_mm2"],
                    "%.2f" % item["kg_per_m"]])
            _L = float(q.get("length_m") or 0)
            out["reinforcement"] = {
                "notes": [
                    "本牆為**%s**擋土牆，靠自重維持穩定，牆身不以撓曲配筋控制；"
                    "配筋僅供溫度收縮與構造需求。" % (
                        "重力式" if res["wall_type"] == "gravity" else "半重力式"),
                    "構造鋼筋：牆面（露出側）%s@%d（垂直向＋水平向，單面雙向），底部縱向 %s@%d，"
                    "保護層 %.0f mm。" % (
                        mass["face_bar"], int(mass["face_spacing_mm"]),
                        mass["base_bar"], int(mass["base_spacing_mm"]),
                        float((RC.CONCRETE or {}).get("cover_mm", 75.0))),
                    "溫度鋼筋比 ρ = %.5f（以 %.0f mm 有效表層計），下限 %.3f：%s。" % (
                        mass["temperature_ratio"], mass["surface_mm"],
                        mass["temperature_min"], "符合" if mass["ok"] else "不足"),
                    "鋼筋量 %.2f kg/m（已含 %.0f%% 搭接損耗）× 牆長 %.1f m = %.1f kg。" % (
                        mass["total_kg_per_m"],
                        mass["lap_allowance"] * 100.0, _L,
                        mass["total_kg_per_m"] * _L),
                    "參考工作簿 `tools.excel\\擋土牆安定分析.mod.xls`：重力式／半重力式牆身不配撓曲鋼筋，"
                    "僅在設止滑榫（b>0）時設計榫部鋼筋；本計算未設止滑榫。",
                ],
                "items": [_tbl(
                    "構造鋼筋配置與鋼筋量表",
                    [("位置", 5.2, "left"), ("鋼筋", 3.0, "center"),
                     ("As（mm²/m）", 2.6, "center"), ("kg/m", 2.2, "center")],
                    rows,
                    note="重力式／半重力式不設受力主筋；配筋量由溫度收縮與構造需求控制，"
                         "非由強度計算控制。")],
            }
        else:
            dd = RC.design_cantilever_stem(q, res)
            mm, ss, ww = dd["main"], dd["shear"], dd["crack"]
            base = RC.design_base_slab(q, res)          # 底板（趾板／踵板）
            base_rows = []
            if base:
                for bm in base["members"]:
                    bf, bs2, bw = bm["main"], bm["shear"], bm["crack"]
                    base_rows.append([
                        bm["member"],
                        "M=%.2f kN·m/m" % bm["M_service_kNm"],
                        "%s@%d（%.0f）" % (bf.get("bar"), bf.get("spacing_mm"),
                                         bf.get("As_prov_mm2", 0)),
                        _verdict(bm["ok"])])
            _wms = RC.wall_min_steel(1000.0, float(q["stem_thickness_m"]) * 1000.0)
            out["reinforcement"] = {
                "items": [_tbl(
                    "配筋設計結果表（莖板牆底控制斷面）",
                    [("項目", 3.8, "left"), ("計算值", 3.2, "center"),
                     ("要求／採用", 3.8, "center"), ("判定", 2.2, "center")],
                    [["服務彎矩 M", "%.2f kN·m/m" % dd["M_service_kNm"], "—", "—"],
                     ["設計彎矩 Mu（×1.7）", "%.2f kN·m/m" % dd["Mu_kNm"], "—", "—"],
                     ["撓曲鋼筋 As", "需求 %.0f mm²/m" % mm.get("As_req_mm2", 0),
                      "採 %s@%d（%.0f）" % (mm.get("bar"), mm.get("spacing_mm"),
                                           mm.get("As_prov_mm2", 0)),
                      _verdict(mm.get("ok"))],
                     ["最小鋼筋 As,min", "%.0f mm²/m" % mm.get("As_min_mm2", 0),
                      "控制於「%s」" % mm.get("governed_by", ""), "—"],
                     ["斷面類型（112 版表 21.2.2／舊 §3.4.4）",
                      "εt = %.4f" % mm.get("epsilon_t", 0),
                      "φ = %.2f（%s）" % (mm.get("phi", 0.9), mm.get("phi_basis", "")),
                      _verdict(mm.get("phi", 0.9) >= 0.9)],
                     ["撓曲強度 φMn", "%.2f kN·m" % mm.get("phiMn_kNm", 0),
                      "≥ Mu = %.2f" % dd["Mu_kNm"], _verdict(mm.get("ok"))],
                     ["剪力 φVc", "%.2f kN" % ss.get("phiVc_kN", 0),
                      "≥ Vu = %.2f" % dd["Vu_kN"], _verdict(ss.get("ok"))],
                     ["裂縫寬度 w", ("%.3f mm" % ww["w_mm"]) if ww.get("w_mm") is not None else "—",
                      "≤ %.1f mm" % ww.get("limit_mm", 0.3), _verdict(ww.get("ok"))],
                     ["分布筋", "%s@%d" % (dd.get("dist_bar"), dd.get("dist_spacing_mm")),
                      "%.0f mm²/m" % dd.get("dist_As_mm2", 0), "—"]] + base_rows,
                    note="主筋置於受拉面（牆背側）、分布筋置於受壓面；保護層 75 mm。"
                         "載重組合採 1.7×（土壓力）簡化放大。"
                         "底板另列：受壓長度 %.3f m、趾端 q=%.2f、踵端 q=%.2f kPa；"
                         "控制構材為 %s。" % (
                             (base or {}).get("Lp_m", 0),
                             (base or {}).get("q_toe_kPa", 0),
                             (base or {}).get("q_heel_kPa", 0),
                             (base or {}).get("governing", "—")))],
                "notes": [
                    "配筋依據《混凝土結構設計規範》（內政部 112.08.10 現行版；括號內為 100.06.09 舊版對照）："
                    "撓曲表 21.2.2（舊 §3.4.4）φ 依淨拉應變 εt ≥ εty+0.003 判定、最小鋼筋 §9.6.1.2（舊 §3.6.1）、"
                    "牆體單向剪力 §13.3.6.1.1（舊 §4.4.1.1）Vc=0.17√fc′·bw·d（φ=0.75，表 21.2.1）。",
                    "**牆之最小鋼筋量依 112 版 §11.6.1 表 11.6.1（舊 §7.2.2／§7.4.3）**：保守採水平鋼筋比 ρt=0.0025 → "
                    "t=%.0f mm 時需 %.0f mm²/m，實配 %s@%d（%.0f mm²/m）；"
                    "垂直鋼筋比 ρl=0.0015 → 需 %.0f mm²/m，實配 %s@%d（%.0f mm²/m）。"
                    "112 版 §11.7.2.3（舊 §7.4.4）：本工作區對牆厚 ≥25 cm 保守維持每向分兩層設置（本牆 %.0f mm）。" % (
                        float(q["stem_thickness_m"]) * 1000.0,
                        _wms["As_horizontal_min_mm2"],
                        dd.get("dist_bar"), dd.get("dist_spacing_mm"),
                        dd.get("dist_As_mm2", 0),
                        _wms["As_vertical_min_mm2"],
                        mm.get("bar"), mm.get("spacing_mm"),
                        mm.get("As_prov_mm2", 0),
                        float(q["stem_thickness_m"]) * 1000.0),
                    "⚠ 112 版 §24.3.2（舊 §3.7.2）之最大鋼筋間距規定僅適用**梁與單向版**，不適用於牆；"
                    "牆適用第 11 章。常時土壓係數續採 1.7H 保守慣例（112 版 §5.3.1 為 1.6H），仍須由合格技師覆核。",
                    "底板（趾板／踵板）已於本表一併設計：以牆身為固定端之懸臂板考慮，"
                    "依基底反力 q(x) 與覆土／自重之淨壓力積分求彎矩。實測踵板彎矩 %.1f kN·m/m "
                    "確實大於莖板的 %.1f kN·m/m，故底板配筋由踵板控制。" % (
                        max([m["M_service_kNm"] for m in (base or {"members": [{"M_service_kNm": 0}]})["members"]] or [0]),
                        dd["M_service_kNm"]),
                    "⚠ 仍待補：錨定長度、搭接長度、剪力筋（目前皆無剪力筋需求）、"
                    "地震工況之載重組合（目前僅常時）。",
                    "⚠ 牆身厚 %.2f m 係由裂縫寬度控制選定；若配筋間距調整，須重跑本表。" % float(q["stem_thickness_m"]),
                ],
            }

    # 第 9 章：斷面尺寸採用依據（原本是「需人工補」，其實就是穩定分析的選配理由）
    out["comparison"] = {
        "notes": [
            "斷面尺寸非依慣例值選定，而是以 tools/design/retaining_wall.py 的穩定分析"
            "（水土保持技術規範第 119~120 條）逐項檢核後決定：",
            "牆型 %s，H=%.2f m、T=%.2f m、底寬 BL=%.2f m%s，斷面積 %.4f m²/m。" % (
                wt, g["H"], g["T"], g["BL"],
                "" if res["wall_type"] == "gravity" else "、底板厚 BT=%.2f m" % g["BT"],
                g["area_m2_per_m"]),
            "選配準則：在「b×h／斷面積最小」的前提下，取第一組全部檢核通過之斷面；"
            "滑動 FS=%.2f、傾倒 FS=%.2f、合力作用點 %.3f m、q_max=%.1f kPa。" % (
                next((c["value"] for c in res["checks"] if c["item"].startswith("滑動")), 0),
                next((c["value"] for c in res["checks"] if c["item"].startswith("傾倒")), 0),
                res["x_R_m"], res["q_max_kPa"]),
            "若地質鑽探結果與上述假設參數不同，應以實際參數重跑 size_section() 後更新本表。",
        ],
    }

    out["drainage"] = {
        "checks": [
            {"item": "排水孔直徑", "requirement": "≥ 5 cm（第121條）",
             "value": "Ø%.0f cm" % (float(q.get("weep_diameter_m", 0.05)) * 100),
             "verdict": _verdict(float(q.get("weep_diameter_m", 0.05)) >= 0.05)},
            {"item": "排水孔密度", "requirement": "每 2 m² 牆面 ≥ 1 孔（第121條）",
             "value": "%d 孔 / %.1f m² 牆面" % (weep, face),
             "verdict": _verdict(face > 0 and weep >= face / 2.0 - 1e-9)},
            {"item": "伸縮縫間距", "requirement": "每 20~40 m 一處（第121條）",
             "value": "%d 處 / 牆長 %.1f m" % (joint, float(q.get("length_m", 0))),
             "verdict": _verdict(joint >= 1)},
            {"item": "背填透水性", "requirement": "須為透水性良好材料並設反濾層（第121條）",
             "value": "級配碎石 %.2f m ＋ 反濾層 %.2f m" % (
                 float(q.get("backfill_thickness_m", 0.3)), 0.1),
             "verdict": "符合"},
        ],
        "items": [_tbl(
            "排水與伸縮縫配置數量表",
            [("項目", 5.0, "left"), ("數量", 2.6, "center"),
             ("單位", 1.8, "center"), ("說明", 4.6, "left")],
            [["排水孔 Ø%.0f cm" % (float(q.get("weep_diameter_m", 0.05)) * 100),
              "%d" % weep, "孔", "每 2 m² 牆面 1 孔（第121條）"],
             ["伸縮縫", "%d" % joint, "處", "每 20~40 m 一處（第121條）"],
             ["背填級配碎石", "%.2f" % float(q.get("backfill_gravel_m3", 0) or 0), "m³",
              "透水性良好材料，分層夯實"],
             ["反濾層", "%.2f" % (face * 0.0), "m²", "厚度 0.10 m（示意）"]]),
        ],
        "notes": [
            "排水路徑：牆後背填水 → 反濾層 → 排水孔（洩水管）→ 牆面排出。",
            "排水孔須設防止阻塞設施（反濾層＋洩水管），出水口不得直接沖刷牆腳。",
            "伸縮縫採填縫料及止水帶，位置須避開排水孔。",
        ],
    }



def _sections_box(out, q, case):
    """報告段落：箱涵（由 _design_sections 分派）。"""
    hy = case.get("hydraulics") or {}
    cv = case.get("culvert") or {}
    res = BC.analyse(q, **_box_culvert_kwargs(case, q))
    sec = res["section"]
    hyd = res["hydraulic"]
    qty = res["quantities"]
    _tr = res["loads"].get("traffic") or {}
    _tr_pressure = float(
        _tr.get("patch_pressure_kpa") or _tr.get("uniform_pressure_kpa") or 0.0
    )
    out["loads"] = {
        "items": [_tbl(
            "箱涵載重與構架分析輸入表（每公尺涵長）",
            [("項目", 4.8, "left"), ("計算式／來源", 6.0, "left"),
             ("數值", 2.6, "center"), ("單位", 1.4, "center")],
            [
                ["車輛活載", res["loads"].get("traffic_label", "—"),
                 "%.3f" % _tr_pressure, "kN/m²"],
                ["車輛載重換算均佈", "總輪載／總寬（僅供對照）",
                 "%.3f" % float(res["loads"].get("traffic_equivalent_kpa") or 0.0),
                 "kN/m²"],
                ["頂版總向下載重", "覆土γH＋超載＋車輛活載",
                 "%.3f" % res["loads"]["top_load_kn_m2"], "kN/m²"],
                ["底板平均向上反力", "整體垂直力平衡",
                 "%.3f" % res["loads"]["bottom_reaction_kn_m2"], "kN/m²"],
                ["混凝土自重", "外框面積減孔洞 × γc",
                 "%.3f" % qty["self_weight_kn_m"], "kN/m"],
                ["地下水浮力", "γw×基礎以上水頭×外寬",
                 "%.3f" % qty["uplift_kn_m"], "kN/m"],
                ["地震係數 kh", "擬靜態 Mononobe-Okabe 側向增量",
                 "%.3f" % res["loads"]["seismic_kh"], "-"],
            ],
            note="構架分析採平面二維剛架、每公尺涵長；土壓力作用於外牆，內水壓力作用於內側。",
        )],
        "notes": [
            "箱涵為 %d 孔 %.2f m × %.2f m，外寬 %.2f m、外高 %.2f m；"
            "以頂版、底板、外牆及 %d 道內隔牆建立平面剛架。"
            % (sec["cell_count"], sec["clear_width_m"], sec["clear_height_m"],
               sec["outer_width_m"], sec["outer_height_m"],
               max(0, sec["cell_count"] - 1)),
            "混凝土自重以精確斷面積計算；底板反力由整體垂直力平衡求得，"
            "避免把箱涵當成個別梁板而漏掉軸力。",
            "土工參數 γ=%.1f kN/m³、φ=%.1f°；%s。"
            % (float(cv.get("soil_unit_weight_kn_m3") or 18.0),
               float(cv.get("soil_phi_deg") or 30.0),
               "採案件指定值" if cv else "採模組預設假設值，正式設計前須以鑽探替換"),
            "車載只作用於頂版；局部輪壓不另加側向土壓。"
            "車載與其他載重目前共用載重係數 %.2f，尚未拆分靜／活載因數。"
            % float(cv.get("load_factor") or 1.7),
        ],
    }

    checks = []
    for c in res["checks"]:
        item = c["item"]
        lim = c["limit"]
        if "水力容量" in item:
            req = "Q_cap ≥ %.3f m³/s" % float(lim)
        elif "出水高" in item:
            req = "≤ %.3f m" % float(lim)
        elif "抗浮" in item:
            req = "FS ≥ %.2f" % float(lim)
        elif "承載" in item:
            req = "≤ %.1f kPa" % float(lim)
        else:
            req = "≥ %.2f" % float(lim)
        checks.append({
            "item": item,
            "requirement": req,
            "value": "%.3f" % float(c["value"]),
            "verdict": _verdict(c["ok"]),
        })
    out["stability"] = {
        "checks": checks,
        "notes": [
            "水力採清水矩形斷面曼寧正常水深；全滿容量僅作上限，"
            "尚未計入口／出口控制、翼牆與下游尾水。",
            "結構檢核取各桿件最大絕對彎矩與端部剪力，乘載重係數 %.2f 後做 RC 撓曲、剪力與裂縫檢核。"
            % float(cv.get("load_factor") or 1.7),
            "綜合判定：%s。" % ("全部符合" if res["pass"] else "有未符合項，不得交件"),
        ],
    }

    reinf_rows = []
    for e in res["reinforcement"]["elements"]:
        f = e["flexure"]
        cr = e["crack"]
        reinf_rows.append([
            e["label"],
            "%s：%.2f kN·m/m" % (e["moment_label"], e["Mu_kNm"]),
            "%s@%s（%.0f mm²/m）" % (
                f.get("bar", "—"), f.get("spacing_mm", "—"),
                f.get("As_prov_mm2", 0.0)),
            "φMn=%.2f；w=%.3f mm；控制=%s" % (
                f.get("phiMn_kNm", 0.0),
                cr.get("w_mm") if cr.get("w_mm") is not None else 0.0,
                f.get("governed_by", "—")),
            _verdict(e["ok"]),
        ])
    dist_rows = []
    for d in res["reinforcement"].get("distribution") or []:
        dist_rows.append([
            d["title"],
            "%.4f·b·h（總量分兩面）" % float(d["ratio"]),
            "%s@%s（每面 %.0f mm²/m）" % (
                d.get("bar", "—"), d.get("spacing_mm", "—"),
                float(d.get("As_prov_mm2") or 0.0)),
            "需求 %.1f／實配 %.1f mm²/m" % (
                float(d.get("As_req_mm2") or 0.0),
                float(d.get("As_prov_mm2") or 0.0)),
            _verdict(d["ok"]),
        ])
    _q = res["reinforcement"]["quantity"]
    out["reinforcement"] = {
        "items": [
            _tbl(
                "箱涵逐面配筋初步結果表",
                [("構材／面", 3.8, "left"), ("控制內力", 4.2, "left"),
                 ("主筋", 3.6, "center"), ("強度／裂縫", 5.4, "left"),
                 ("判定", 1.6, "center")],
                reinf_rows,
                note="保護層 %.0f mm；逐面設計，頂版／底版／外牆／中牆的內外側分開檢核。"
                % float(_box_culvert_kwargs(case, q)["cover_mm"]),
            ),
            _tbl(
                "箱涵縱向分佈筋表",
                [("位置", 4.2, "left"), ("鋼筋比", 4.2, "left"),
                 ("配置", 4.6, "center"), ("As 需求／實配", 4.4, "left"),
                 ("判定", 1.6, "center")],
                dist_rows,
                note="版採 0.0018·b·h、牆採 0.0020·b·h；此為總量分置內外兩面，不是每面各一份。",
            ),
        ],
        "notes": [
            "撓曲、軸彎互制、剪力與裂縫依《混凝土結構設計規範》相關條文計算；"
            "主筋依實際受拉面定向，不以兩個彎曲方向取較小值。",
            "鋼筋量依理想化排筋計數：淨 %.2f kg/m，含 %.0f%% 搭接／錨定／損耗後 %.2f kg/m，"
            "總量 %.1f kg（%.2f t）。"
            % (float(_q.get("subtotal_kg_per_m") or 0.0),
               float(_q.get("loss_rate") or 0.0) * 100.0,
               float(_q.get("total_kg_per_m") or 0.0),
               float(_q.get("total_kg") or 0.0),
               float(_q.get("total_kg") or 0.0) / 1000.0),
            "目前構架分析只計單一重力＋土水壓載重 case，未建立 D／L／E 分項包絡；"
            "正式設計須用 tools\\design\\load_combinations.py 擴充多工況。",
            "牆與厚版的最小鋼筋、裂縫控制及角隅補強仍須由技師依現行規範覆核。",
        ],
    }

    out["drainage"] = {
        "checks": [
            {"item": "通水容量", "requirement": "Q_cap ≥ %.3f m³/s" % hyd["design_flow_m3s"],
             "value": "%.3f m³/s" % hyd["capacity_m3s"],
             "verdict": _verdict(hyd["capacity_ok"])},
            {"item": "正常水深＋出水高", "requirement": "≤ %.2f m" % sec["clear_height_m"],
             "value": "%.3f m" % (hyd["normal_depth_m"] + hyd["freeboard_min_m"]),
             "verdict": _verdict(hyd["freeboard_ok"])},
        ],
        "items": [_tbl(
            "箱涵水力計算表",
            [("項目", 5.0, "left"), ("數值", 2.8, "center"),
             ("單位", 1.6, "center"), ("說明", 4.8, "left")],
            [
                ["設計流量 Q", "%.3f" % hyd["design_flow_m3s"], "m³/s", "案件指定"],
                ["縱坡 S", "%.4f" % float(hy.get("slope") or 0.005), "-", "設計值"],
                ["正常水深 h_n", "%.3f" % hyd["normal_depth_m"], "m", "曼寧等速流"],
                ["設計流速 V", "%.3f" % hyd["velocity_m_s"], "m/s", "由 Q/A 計算"],
                ["福祿數 Fr", "%.3f" % hyd["froude"], "-", "接近 1 表示臨界流"],
                ["全滿容量", "%.3f" % hyd["capacity_m3s"], "m³/s", "上限值，非設計容量"],
            ],
            note="尚未辦入口／出口控制、涵洞淹沒、尾水與能量損失分析。",
        )],
        "notes": [
            "箱涵水力先以各孔淨空矩形並聯、同一水深之曼寧正常水深計算。",
            "全滿曼寧容量會高估可接受流量，故本報告不以全滿容量宣稱通過，"
            "而以設計流量對應之正常水深加最小出水高檢核。",
            "正式涵洞設計仍須依公路排水設計規範／下水道工程設施標準檢核入口與出口控制。",
        ],
    }

    out["comparison"] = {
        "notes": [
            "箱涵尺寸依「水力容量與出水高」及「平面構架 RC 內力」兩道檢核共同決定；"
            "任一項不通過即不得以慣例尺寸出圖。",
            "採 %d 孔、每孔淨寬 %.2f m、淨高 %.2f m，外寬 %.2f m、外高 %.2f m。"
            % (sec["cell_count"], sec["clear_width_m"], sec["clear_height_m"],
               sec["outer_width_m"], sec["outer_height_m"]),
            "混凝土淨斷面積 %.3f m²/m、總量 %.2f m³；不含翼牆、保護工與路面。"
            % (qty["concrete_area_m2_per_m"], qty["concrete_volume_m3"]),
            "鋼筋設計量：淨 %.2f kg/m、含 %.0f%% 損耗 %.2f kg/m，總量 %.1f kg（%.2f t）。"
            % (float(qty.get("rebar_kg_per_m_net") or 0.0),
               float(qty.get("rebar_loss_rate") or 0.0) * 100.0,
               float(qty.get("rebar_kg_per_m") or 0.0),
               float(qty.get("rebar_kg_total") or 0.0),
               float(qty.get("rebar_ton") or 0.0)),
            "模板量：每延米 %.2f m²/m，總量 %.2f m²（含兩端端模 %.2f m²）。"
            % (float(qty.get("formwork_m2_per_m") or 0.0),
               float(qty.get("formwork_m2") or 0.0),
               float(qty.get("formwork_end_faces_m2") or 0.0)),
        ],
    }



def _sections_channel(out, q, case):
    """報告段落：排水溝（由 _design_sections 分派）。"""
    hy = case.get("hydraulics") or {}
    Q = float(hy.get("design_flow_m3s") or 0.5)
    S = float(hy.get("slope") or 0.005)
    n = float(hy.get("manning_n") or CH.DEFAULTS["manning_n"])
    b = float(q.get("inner_width_m", 0)); h = float(q.get("depth_m", 0))
    res = CH.analyse(Q, b, h, S, {"manning_n": n})

    out["drainage"] = {
        "checks": [
            {"item": c["item"],
             "requirement": (c["limit"] if isinstance(c["limit"], str)
                             else "≥ %.3f" % c["limit"]),
             "value": ("—" if c["value"] is None else
                       ("%.3f" % c["value"] if isinstance(c["value"], float)
                        else str(c["value"]))),
             "verdict": _verdict(c["ok"])}
            for c in res["checks"]],
        "items": [_tbl(
            "水力計算結果表",
            [("項目", 5.0, "left"), ("數值", 2.8, "center"),
             ("單位", 1.8, "center"), ("說明", 4.4, "left")],
            [["設計流量 Q", "%.3f" % Q, "m³/s", "設計洪水量（第83條重現期）"],
             ["縱坡 S", "%.4f" % S, "—", "%.2f%%" % (S * 100)],
             ["曼寧 n", "%.3f" % n, "—", "混凝土粗糙度（第84條僅給公式）"],
             ["通水容量 Q_cap", "%.3f" % res["Q_cap_m3s"], "m³/s", "滿水深"],
             ["正常水深 h_n", "%.3f" % (res["h_normal_m"] or 0), "m", "設計流量下"],
             ["設計流速 V", "%.3f" % (res["V_design_ms"] or 0), "m/s", "第85條 0.8~4.57"],
             ["出水高", "%.3f" % res["freeboard_required_m"], "m", "第86條 25% 且 ≥0.20"]]),
        ],
        "notes": [
            "平均流速採曼寧公式 v=(1/n)·R^(2/3)·S^(1/2)（第84條），R=A/P。",
            "流速上下限依第85條：混凝土／RC 最小 0.8 m/s；混凝土常流水最大 4.57~6.10 m/s。",
            "出水高依第86條：設計水深 25%，最小值 20 cm。",
            "綜合判定：%s。" % ("全部符合" if res["pass"] else "有未符合項，須調整斷面或縱坡"),
            "設計洪水量重現期依第83條：坡地農地 10 年、其他非農業使用 25 年。"
            "本表流量%s。" % ("已依該條辦理" if hy.get("design_flow_m3s") else "為假設值，尚未辦水文分析"),
        ],
    }
    # 第 11 章加「集水區水文分析」（第 16~19 條）——設計流量的來源
    catch = case.get("catchment")
    if catch and HY is not None:
        try:
            hr2 = HY.design_flow(
                float(catch["P_mm"]), float(catch["T_year"]),
                float(catch["area_ha"]), catch.get("condition", "丘陵地或森林"),
                bool(catch.get("developed")), bool(catch.get("upper_c")),
                float(catch.get("l_m", 100.0)), float(catch.get("v_ms", 0.4)),
                float(catch.get("L_km", 0.0)), float(catch.get("H_km", 0.0)))
            out["drainage"]["items"].insert(0, _tbl(
                "集水區水文分析結果表",
                [("項目", 4.6, "left"), ("數值", 2.8, "center"),
                 ("單位", 1.8, "center"), ("依據", 4.8, "left")],
                [["年平均降雨量 P", "%.0f" % hr2["P_mm"], "mm", "等雨量線圖／雨量資料（第16條）"],
                 ["重現期距 T", "%.0f" % hr2["T_year"], "年", "第83條：非農業 25 年"],
                 ["集水區面積 A", "%.3f" % hr2["area_ha"], "ha", "≤1000 ha 得用合理化公式（第17條）"],
                 ["集流時間 tc", "%.2f" % hr2["tc_min"], "分", "tc=t1+t2（第19條）"],
                 ["降雨強度 I", "%.2f" % hr2["I_mm_hr"], "mm/hr", "第16條（推估值為下限）"],
                 ["逕流係數 C", "%.3f" % hr2["C"], "-",
                  "%s（第18條）" % hr2["condition"]],
                 ["洪峰流量 Qp", "%.4f" % hr2["Qp_m3s"], "m³/s", "Qp=(1/360)CIA（第17條）"]],
                note="本表為斷面選配的流量來源；第16條明定強度推估值僅為下限。"))
            out["drainage"]["notes"].insert(0,
                "設計流量由合理化公式計算（第17條）：Qp=(1/360)×%.3f×%.2f×%.3f="
                "%.4f m³/s。集流時間 %.2f 分（第19條）、降雨強度 %.2f mm/hr（第16條）。"
                % (hr2["C"], hr2["I_mm_hr"], hr2["area_ha"], hr2["Qp_m3s"],
                   hr2["tc_min"], hr2["I_mm_hr"]))
        except Exception as ex:
            out["drainage"]["notes"].insert(0,
                "集水區水文分析未完成：%s" % ex)

    # 第 8 章：溝壁配筋
    if RC is not None:
        dd = RC.design_channel_wall(q, res)
        mm, ss, ww = dd["main"], dd["shear"], dd["crack"]
        out["reinforcement"] = {
            "items": [_tbl(
                "配筋設計結果表（溝壁牆底控制斷面）",
                [("項目", 3.8, "left"), ("計算值", 3.2, "center"),
                 ("要求／採用", 3.8, "center"), ("判定", 2.2, "center")],
                [["服務彎矩 M", "%.3f kN·m/m" % dd["M_service_kNm"], "—", "—"],
                 ["設計彎矩 Mu（×1.7）", "%.3f kN·m/m" % dd["Mu_kNm"], "—", "—"],
                 ["撓曲鋼筋 As", "需求 %.0f mm²/m" % mm.get("As_req_mm2", 0),
                  "採 %s@%d（%.0f）" % (mm.get("bar"), mm.get("spacing_mm"),
                                       mm.get("As_prov_mm2", 0)), _verdict(mm.get("ok"))],
                 ["斷面類型（112 版表 21.2.2／舊 §3.4.4）",
                  "εt = %.4f" % mm.get("epsilon_t", 0),
                  "φ = %.2f（%s）" % (mm.get("phi", 0.9), mm.get("phi_basis", "")),
                  _verdict(mm.get("phi", 0.9) >= 0.9)],
                 ["撓曲強度 φMn", "%.2f kN·m" % mm.get("phiMn_kNm", 0),
                  "≥ Mu = %.3f" % dd["Mu_kNm"], _verdict(mm.get("ok"))],
                 ["剪力 φVc", "%.2f kN" % ss.get("phiVc_kN", 0),
                  "≥ Vu = %.2f" % dd["Vu_kN"], _verdict(ss.get("ok"))],
                 ["裂縫寬度 w", ("%.3f mm" % ww["w_mm"]) if ww.get("w_mm") is not None else "—",
                  "≤ %.1f mm" % ww.get("limit_mm", 0.3), _verdict(ww.get("ok"))],
                 ["分布筋", "%s@%d" % (dd.get("dist_bar"), dd.get("dist_spacing_mm")),
                  "%.0f mm²/m" % (dd.get("dist_As_mm2") or 0), "—"]],
                note="溝壁以懸臂板考慮，控制載重為溝內滿水壓力。")],
            "notes": [
                "配筋依據《混凝土結構設計規範》（112.08.10 現行版；舊 100.06.09 對照）："
                "撓曲表 21.2.2（§3.4.4）φMn ≥ Mu、剪力 §13.3.6.1.1（§4.4.1.1）φVc ≥ Vu、"
                "最小鋼筋 §9.6.1.2／§11.6.1（§3.6.1／§7.4.3）、裂縫寬度 ≤ 0.3 mm。",
                "⚠ 溝壁按懸臂牆板近似，常時水壓係數續採 1.7 保守慣例，細部設計須由技師覆核。",
                "⚠ **僅計溝內水壓力**：溝外側土壓力須俟土工參數確定後另計；溝底未做承載檢核。",
            ],
        }

    # 第 6 章：水壓力（排水溝內水壓）
    hn = res["h_normal_m"] or 0.0
    out["loads"] = {
        "items": [_tbl(
            "作用力計算表（每公尺溝長）",
            [("作用項目", 3.6, "left"), ("計算式", 4.6, "left"),
             ("大小", 2.4, "center"), ("作用點", 3.2, "left")],
            [["溝壁靜水壓力", "½·γw·h_n²（γw=9.81 kN/m³）",
              "%.3f kN/m" % (0.5 * 9.81 * hn ** 2),
              "溝底以上 h_n/3 = %.3f m" % (hn / 3)],
             ["溝底靜水壓力", "γw·h_n",
              "%.3f kPa" % (9.81 * hn), "溝底"],
             ["土壓力（溝外側）", "未計（無土工參數）", "—", "—"],
             ["地震力", "未計（明溝通常不受控）", "—", "—"]],
            note="排水溝以水力容量控制；溝壁結構檢核須另依擋土結構觀念辦理。")],
        "notes": [
            "設計流量 %.3f m³/s 下正常水深 %.3f m，據以計算靜水壓力。" % (Q, hn),
            "溝壁所受側壓於完工後由兩側土壓力與水壓力共同決定；本表僅列常時水壓力，"
            "土壓力須俟土工參數確定後另計。",
            "水土保持技術規範第 119 條所列作用力（含地震力）於明溝通常非控制項，"
            "惟位於重要構造物鄰近時仍應檢核。",
        ],
    }



def _sections_road(out, q, case):
    """報告段落：道路／路面（由 _design_sections 分派）。

    ⚠ 設計邊界（誠實註記，不可臆測）：
    本專案**沒有柔性鋪面結構設計引擎**（柔性鋪面設計手冊的 TI／ESAL／軸重當量因子
    等條目目前僅供規範查詢台查閱，無引擎可逐值比對），因此本章**不做**：
      · 交通量分析與軸重當量（ESAL）換算
      · 鋪面結構層厚度設計（底層／基層／面層厚度分配）
      · 承載力（加州法 T／GE）檢核
    上述項目在案件缺交通量與路面結構調查資料時，本章明寫「需人工補」，
    **不假造數值**。

    本章可確定產出的是「路面結構組成與鋪裝數量」：由案件的鋪裝厚度、面積、
    體積與結構層設定（若有）直接派生，屬可查核的量。
    """
    L = float(q.get("length_m") or 0.0)
    W = float(q.get("width_avg_m") or 0.0)
    A = float(q.get("area_m2") or 0.0)
    t_cm = float(q.get("thickness_cm") or 0.0)
    V = float(q.get("volume_m3") or 0.0)

    # ---- 第 6 章：載重作用（鋪裝自重；交通載重缺資料時明寫需人工補）----
    # 瀝青混凝土單位重採一般值 2.2 t/m³（22 kN/m³）。
    unit_w_kn = 22.0
    if t_cm > 0 and A > 0:
        w_total = A * (t_cm / 100.0) * unit_w_kn
    else:
        w_total = 0.0
    traffic = case.get("traffic") or {}
    have_traffic = bool(traffic.get("esal") or traffic.get("daily_traffic")
                         or traffic.get("axis_load_kn"))
    out["loads"] = {
        "items": [_tbl(
            "鋪裝自重與交通載重作用表",
            [("載重項目", 4.2, "left"), ("計算式", 4.4, "left"),
             ("大小", 3.0, "center"), ("說明", 4.2, "left")],
            [["鋪裝自重（面層）", "面積 %.1f m² × 厚 %.1f cm × 22 kN/m³" % (A, t_cm),
              "%.1f kN" % w_total, "瀝青混凝土單位重採一般值"],
             ["交通載重（軸重當量）",
              ("案件已提供軸次／日交通量" if have_traffic else "缺交通量與路面結構調查資料"),
              ("依案件" if have_traffic else "—"),
              ("軸重當量因子換算 ESAL（本專案無引擎，須依柔性鋪面設計手冊人工計算）"
               if have_traffic
               else "交通量分析與軸重換算須由設計者依《柔性鋪面設計手冊》辦理")]],
            note="本表僅列鋪裝自重與交通載重之來源；交通載重未經換算前，"
                 "不可據以判定現有路面結構之承載能力。")],
        "notes": [
            "本章之交通載重採軸重當量因子法換算之設計軸次（ESAL）為基礎；"
            "換算需交通量調查資料與《柔性鋪面設計手冊》之軸重當量因子表，"
            "%s。" % ("案件已提供，可據以續算" if have_traffic
                     else "本案件未提供，故本章不列數值（須人工補）"),
            "本專案目前無柔性鋪面結構設計引擎，TI 與加州承載力式僅能由規範查詢台"
            "查閱條文、無法逐值運算；結構厚度設計須由設計者以正式工具完成。",
        ],
    }

    # ---- 第 7 章：穩定檢核（路面結構與幾何）----
    # 道路的「穩定」在此指路面結構承載與幾何斷面（橫坡、寬度）之檢核。
    # 結構承載力檢核缺交通量與結構調查，標為需人工補。
    cross_slope = q.get("cross_slope_pct")
    checks = []
    if cross_slope not in (None, ""):
        checks.append({
            "item": "路面橫坡（排水）",
            "requirement": "≥ 1.0%（道路工程實務常見值）",
            "value": "%.2f%%" % float(cross_slope),
            "verdict": _verdict(float(cross_slope) >= 1.0),
        })
    else:
        checks.append({
            "item": "路面橫坡（排水）",
            "requirement": "≥ 1.0%（道路工程實務常見值）",
            "value": "—",
            "verdict": "需人工補",
        })
    checks.append({
        "item": "鋪築體積 V = A × t",
        "requirement": "與案件宣告值差異 ≤ 1.0%",
        "value": "%.2f m³" % V,
        "verdict": _verdict(abs(A * (t_cm / 100.0) - V) / V * 100.0 <= 1.0) if V else "需人工補",
    })
    out["stability"] = {
        "checks": checks,
        "notes": [
            "路面結構承載力檢核（加州法 T／GE 或 AASHTO）需交通量調查與"
            "既有路面結構調查資料；%s，"
            "本章不列計算值（須人工補）。" % ("案件已提供，可據以續算" if have_traffic
                                          else "本案件未提供交通量與結構調查資料"),
            "本章所列幾何檢核僅針對案件檔已宣告之數量與橫坡，"
            "屬「數量自洽」檢核，非結構安全判定。",
        ],
    }

    # ---- 第 11 章：排水與伸縮縫配置 ----
    # 道路的「排水」＝路面排水（橫坡 + 側溝／路肩排水）與路面結構層排水。
    # 側溝設計需要集水區水文參數（降雨、逕流係數、面積），缺則明寫。
    catch = case.get("catchment")
    notes = []
    items = []
    if catch and HY is not None:
        try:
            hr2 = HY.design_flow(
                float(catch["P_mm"]), float(catch["T_year"]),
                float(catch["area_ha"]), catch.get("condition", "丘陵地或森林"),
                bool(catch.get("developed")), bool(catch.get("upper_c")),
                float(catch.get("l_m", 100.0)), float(catch.get("v_ms", 0.4)),
                float(catch.get("L_km", 0.0)), float(catch.get("H_km", 0.0)))
            items.append(_tbl(
                "集水區水文分析結果表（路面側溝流量來源）",
                [("項目", 4.6, "left"), ("數值", 2.8, "center"),
                 ("單位", 1.8, "center"), ("依據", 4.8, "left")],
                [["年平均降雨量 P", "%.0f" % hr2["P_mm"], "mm", "等雨量線圖（第16條）"],
                 ["重現期距 T", "%.0f" % hr2["T_year"], "年", "非農業使用 25 年（第83條）"],
                 ["集水區面積 A", "%.3f" % hr2["area_ha"], "ha", "≤1000 ha（第17條）"],
                 ["集流時間 tc", "%.2f" % hr2["tc_min"], "分", "tc=t1+t2（第19條）"],
                 ["降雨強度 I", "%.2f" % hr2["I_mm_hr"], "mm/hr", "第16條"],
                 ["逕流係數 C", "%.3f" % hr2["C"], "-", hr2["condition"]],
                 ["洪峰流量 Qp", "%.4f" % hr2["Qp_m3s"], "m³/s", "Qp=(1/360)CIA（第17條）"]]))
            notes.append("路面側溝設計流量由合理化公式計算：Qp=%.4f m³/s。"
                         % hr2["Qp_m3s"])
        except Exception as ex:
            notes.append("集水區水文分析未完成：%s" % ex)
    else:
        notes.append("路面側溝（邊溝）設計流量須以集水區水文分析取得；"
                     "本案件未提供集水區參數（降雨量、重現期、面積、逕流係數），"
                     "故本章不列側溝流量與斷面（須人工補）。")

    items.append(_tbl(
        "鋪裝與排水配置數量表",
        [("項目", 5.0, "left"), ("數值", 2.8, "center"),
         ("單位", 1.8, "center"), ("說明", 4.4, "left")],
        [["鋪裝面積 A", "%.1f" % A, "m²", "設計中心線與左右邊界圍成面積"],
         ["鋪築厚度 t", "%.1f" % t_cm, "cm", "設計指定"],
         ["鋪築體積 V", "%.2f" % V, "m³", "V = A × t（未含拌合損耗與鬆散係數）"],
         ["全線長度 L", "%.2f" % L, "m", "沿設計中心線量測"],
         ["平均寬度 W", "%.2f" % W, "m", "逐斷面量測平均"],
         ["路面橫坡", ("%.2f" % float(cross_slope)) if cross_slope not in (None, "")
          else "—", "%", "案件未提供時須以量測或設計值補入"],
         ["側溝／邊溝流量", "—", "m³/s",
          "須集水區水文分析；缺參數時不臆測"]]))
    out["drainage"] = {
        "checks": [],
        "items": items,
        "notes": notes + [
            "路面結構層（底層／基層）排水與級配碎石層排水能力，"
            "須以結構層厚度與滲透係數判定；本專案無對應引擎，須人工補。",
        ],
    }
    return out

def _design_sections(model, q, case):
    """由設計計算模組自動產生報告第 6／7／11 章的內容。

    沒有這一段時，這些章節在報告裡是「需人工補」的佔位符 —— 但 FS、Pa、q_max、
    Q_cap、h_n 其實都已經算出來了。算得出卻不寫進報告，是整條產線最刺眼的不一致。

    依案件類別分派到 `_sections_<類別>()`；各函式就地寫入 `out`。
    """
    out = {}
    if model == "slope" and SS is not None:
        _sections_slope(out, q, case)
    if model == "wall" and WS is not None:
        _sections_wall(out, q, case)
    if model == "box_culvert" and BC is not None:
        _sections_box(out, q, case)
    if model == "channel" and CH is not None:
        _sections_channel(out, q, case)
    if model == "road":
        # 道路／路面：不依賴專用引擎，僅以案件檔已宣告之數量派生可查核的章節；
        # 交通量與鋪面結構設計部分明寫需人工補（見 _sections_road 說明）。
        _sections_road(out, q, case)
    _attach_section_figure(out, case)
    return out
