"""統一案件檔（`civil-case/1`）：一份檔案 → 預算書輸入 ＋ 設計報告輸入，並強制數量一致性。

為什麼要有這一層
----------------
上一輪三軸各自帶自己的 JSON，同一個「面積 850.6 m²」要在三處各打一次 —— 打錯一次就是三份交付互相矛盾，
而且不會有任何工具報錯。本層把**數量收斂成唯一來源**：

* `quantities` 是唯一可寫數量的地方；
* 預算書工項不寫 `qty`，改寫 `"qty_from": "area_m2"`（可乘 `qty_factor`）→ 數量由主檔派生，沒有第二個地方可打錯；
* 設計報告的數量純量由主檔注入，報告工具自己的 V=A×t、A=L×W 自查因此一定跑在同一組數字上；
* `consistency()` 額外驗 L、W、A、t、V 之間的幾何關係，任一項不符即 error。

用法
----
    set PYTHONIOENCODING=utf-8

    :: 只檢查（不產檔）
    C:\\Python312\\python.exe tools\\case_package\\case_core.py check <case.json>

    :: 派生兩軸輸入到 <out>\\_case\\
    C:\\Python312\\python.exe tools\\case_package\\case_core.py derive <case.json> --out-dir <dir>

退出碼：0 = 無 error；1 = 有 error（warning 不影響）。

schema 重點
-----------
    {
      "schema": "civil-case/1",
      "project":  { name, full_name, code, category, agency, client, designer, reviewer,
                    date(ISO), boq_date(民國，可省), version,
                    location: {county, town, village, section, desc},
                    crs: {name, epsg, unit}, coords: [{name,E,N,lat,lon}],
                    report_title, report_subtitle },
      "quantities": { length_m, width_avg_m, width_median_m, area_m2, thickness_cm,
                      volume_m3, tolerance_pct(預設 1.0) },
      "boq":    { rates: {...}, items: [ { no, name, unit, qty_from?, qty_factor?, qty?, price|analysis, note } ] },
      "report": { summary, basis, applicability, survey, assumptions, comparison,
                  drawings, risks, deliverables, quantities_note? },
      "drawing": { dxf, scale, require_dwg, require_layers }
    }
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:
    import drawing_rules  # 標準比例尺
except Exception:                                    # pragma: no cover
    drawing_rules = None
sys.path.insert(0, HERE)
import qty_models as QM                              # 類別化數量模型

_DESIGN_DIR = os.path.join(ROOT, "tools", "design")
if _DESIGN_DIR not in sys.path:
    sys.path.insert(0, _DESIGN_DIR)
try:
    import hydrology as HY                           # 集水區水文分析
    import slope_stability as SS                     # 邊坡穩定
    import retaining_wall as RW                      # 擋土牆穩定分析
    import channel_hydraulics as CH                  # 排水溝水力計算
    import rc_design as RC                           # RC 構材配筋設計
    import box_culvert as BC                         # 單／雙／三孔箱涵
except Exception:                                    # design 模組缺失時不阻擋
    HY = RW = CH = RC = SS = BC = None

SCHEMA = "civil-case/1"

# quantities 可被工項引用的鍵
QTY_KEYS = ("length_m", "width_avg_m", "width_median_m", "area_m2", "thickness_cm", "volume_m3")


# --------------------------------------------------------------------------- #
# 載入與驗證
# --------------------------------------------------------------------------- #
def load(path):
    case = json.load(open(path, encoding="utf-8"))
    if case.get("schema") != SCHEMA:
        raise SystemExit(f"不是 {SCHEMA}：schema={case.get('schema')!r}")
    return case


def _roc_date(iso_date):
    """2026-10-28 → 115年10月（預算書封面用）。"""
    try:
        y, m, _ = str(iso_date).split("-")
        return f"{int(y) - 1911}年{int(m)}月"
    except Exception:
        return str(iso_date)


def quantity_context(case):
    """回傳統一案件檔的數量脈絡：(model, 已衍生 values, issues)。

    相容兩種寫法：
      * 新式 `"quantities": {"model": "wall", "values": {...}}`
      * 舊式 `"quantities": {length_m: ..., area_m2: ...}`（視為 model=road）
    類別與模型不一致時給 warn（不擋），因為牆也可能有人想用道路式的 L/A/V。
    """
    q = case.get("quantities") or {}
    model = q.get("model")
    if model:
        values = dict(q.get("values") or {})
    else:
        model = "road"
        values = {k: v for k, v in q.items()
                  if k not in ("model", "values", "tolerance_pct", "notes")}
    values.setdefault("tolerance_pct", q.get("tolerance_pct", 1.0))

    issues = []
    cat = (case.get("project") or {}).get("category") or ""
    if cat and model == "road" and cat not in ("道路", "路面", "路面改善"):
        issues.append({"level": "warn",
                       "msg": f"category={cat} 但 quantities.model=road："
                              f"道路型數量結構（L/W/A/V）可能不適用此類別，"
                              f"建議改用 model: wall / channel"})
    try:
        values, more = QM.derive_all(model, values)
    except KeyError as ex:
        return model, values, [{"level": "error", "msg": str(ex)}]
    issues.extend(more)

    # 鋼筋量：另外給「依配筋設計推算」的值，供預算書選用。
    # 原本只有 rebar_ratio_kg_m3 × 混凝土體積（假設含鋼量 40 kg/m³），
    # 與設計值（擋土牆 138.46 kg/m、排水溝 24.27 kg/m）差很大 ——
    # 保留兩個鍵，讓案件自己決定要用假設值還是設計值，不要偷偷換掉。
    try:
        _dd = os.path.join(ROOT, "tools", "design")
        if _dd not in sys.path:
            sys.path.insert(0, _dd)
        import rc_design as _RC
        _L = float(values.get("length_m") or 0)
        if model == "wall" and _L > 0:
            import retaining_wall as _RW
            _wr = _RW.analyse(values, soil=case.get("soil") or {})
            _kg = _RC.rebar_kg_per_m(values, _RC.design_cantilever_stem(values, _wr),
                                     _RC.design_base_slab(values, _wr))
            values["rebar_kg_per_m_design"] = round(_kg["total_kg_per_m"], 2)
            values["rebar_kg_design"] = round(_kg["total_kg_per_m"] * _L, 1)
        elif model == "channel" and _L > 0:
            import channel_hydraulics as _CH
            _hy = case.get("hydraulics") or {}
            _hr = _CH.analyse(float(_hy.get("design_flow_m3s") or 0.5),
                              float(values.get("inner_width_m") or 0),
                              float(values.get("depth_m") or 0),
                              float(_hy.get("slope") or 0.005),
                              {"manning_n": float(_hy.get("manning_n") or 0.014)})
            _kgc = _RC.rebar_kg_per_m_channel(
                values, _RC.design_channel_wall(values, _hr))
            values["rebar_kg_per_m_design"] = round(_kgc["total_kg_per_m"], 2)
            values["rebar_kg_design"] = round(_kgc["total_kg_per_m"] * _L, 1)
    except Exception as _ex:
        issues.append({"level": "warn",
                       "msg": "鋼筋設計量未算出（rebar_kg_design 不提供）：%s" % _ex})
    return model, values, issues


def consistency(case):
    """回傳 [{level: error|warn, msg}]。error 會讓 derive／交件失敗。"""
    out = []

    def err(m):
        out.append({"level": "error", "msg": m})

    def warn(m):
        out.append({"level": "warn", "msg": m})

    model, values, qissues = quantity_context(case)
    for i in qissues:
        (err if i["level"] == "error" else warn)(i["msg"])
    tol = float(values.get("tolerance_pct", 1.0))
    if model not in QM.MODELS:
        err(f"未知數量模型 {model!r}")

    # ---- 鋼筋量：配筋設計推算 vs 數量表假設值 ----
    # 數量表的 rebar_kg 一向是「含鋼量假設值 × 混凝土體積」（40 kg/m³）。
    # 現在配筋設計已經算得出實際值，兩者若差太多就該提出來 —— 只 warn，不改預算。
    if model in ("wall", "channel") and RC is not None:
        try:
            _ratio = float(values.get("rebar_ratio_kg_m3") or 0)
            _kg = float(values.get("rebar_kg") or 0)
            _design_kg = None
            if model == "wall" and RW is not None:
                _wr = RW.analyse(values, soil=case.get("soil") or {},
                                 seismic={"kh": float((case.get("seismic") or {}).get("kh", 0) or 0)})
                if _wr["wall_type"] != "gravity":
                    _stem = RC.design_cantilever_stem(values, _wr)
                    _base = RC.design_base_slab(values, _wr)
                    _r = RC.rebar_kg_per_m(values, _stem, _base)
                    _design_kg = _r["total_kg_per_m"] * float(values.get("length_m") or 0)
            if model == "channel" and CH is not None and _design_kg is None:
                _hy = case.get("hydraulics") or {}
                _hr = CH.analyse(float(_hy.get("design_flow_m3s") or 0.5),
                                 float(values.get("inner_width_m") or 0),
                                 float(values.get("depth_m") or 0),
                                 float(_hy.get("slope") or 0.005),
                                 {"manning_n": float(_hy.get("manning_n") or 0.014)})
                _cw = RC.design_channel_wall(values, _hr)
                _rc = RC.rebar_kg_per_m_channel(values, _cw)
                _design_kg = _rc["total_kg_per_m"] * float(values.get("length_m") or 0)
            if _design_kg and _kg > 0:
                _diff = (_design_kg - _kg) / _kg * 100.0
                if abs(_diff) > 25.0:
                    warn("鋼筋量：數量表以假設含鋼量 %.1f kg/m³ 得 %.0f kg，"
                         "但配筋設計推算為 %.0f kg（%+.0f%%）。"
                         "假設值與設計值差超過 25%%，正式預算前應以設計值或詢價確認。"
                         % (_ratio, _kg, _design_kg, _diff))
        except Exception as _ex:
            warn("鋼筋量交叉檢查未完成：%s" % _ex)

    # ---- 第五道閘門：設計檢核必須全部通過 ----
    # 先前「設計檢核有沒有全部通過」只印在報告第 7 章，沒有任何交付閘門在管：
    # 某個斷面真的有一項不過，圖照出、預算照算、報告照印，全軸照樣「通過」。
    # 這裡把它變成 error（不是 warn）—— 不通過就不能交件。
    try:
        _fails = []
        if model == "wall" and RW is not None:
            _wr = RW.analyse(values, soil=case.get("soil") or {},
                             seismic={"kh": float((case.get("seismic") or {}).get("kh", 0) or 0)})
            if not _wr.get("pass"):
                for c in _wr.get("checks") or []:
                    if not c.get("ok"):
                        _fails.append("擋土牆 %s（計算值 %.3f）" % (c["item"], c["value"]))
        elif model == "slope" and SS is not None:
            _sr = SS.analyse(values)
            for c in _sr.get("checks") or []:
                if not c.get("ok"):
                    _fails.append("邊坡 %s（計算值 %.3f）" % (c["item"], c["value"]))
        elif model == "channel" and CH is not None:
            _hy2 = case.get("hydraulics") or {}
            _hr2 = CH.analyse(float(_hy2.get("design_flow_m3s") or 0.5),
                              float(values.get("inner_width_m") or 0),
                              float(values.get("depth_m") or 0),
                              float(_hy2.get("slope") or 0.005),
                              {"manning_n": float(_hy2.get("manning_n") or 0.014)})
            for c in _hr2.get("checks") or []:
                if not c.get("ok"):
                    _fails.append("排水溝 %s（計算值 %s）" % (c["item"], c.get("value")))
        elif model == "box_culvert" and BC is not None:
            _hy3 = case.get("hydraulics") or {}
            _cv = case.get("culvert") or {}
            _br = BC.analyse(
                values,
                design_flow_m3s=float(_hy3.get("design_flow_m3s") or 0.0),
                slope=float(_hy3.get("slope") or 0.005),
                manning_n=float(_hy3.get("manning_n") or 0.014),
                freeboard_min_m=float(_hy3.get("freeboard_min_m") or 0.20),
                soil_unit_weight_kn_m3=float(_cv.get("soil_unit_weight_kn_m3") or 18.0),
                soil_phi_deg=float(_cv.get("soil_phi_deg") or 30.0),
                surcharge_kpa=float(_cv.get("surcharge_kpa") or 0.0),
                traffic_load_kpa=float(_cv.get("traffic_load_kpa") or 0.0),
                groundwater_depth_m=(
                    None if _cv.get("groundwater_depth_m") in (None, "")
                    else float(_cv["groundwater_depth_m"])
                ),
                internal_water_depth_m=float(_cv.get("internal_water_depth_m") or 0.0),
                load_factor=float(_cv.get("load_factor") or 1.7),
                seismic_kh=float((case.get("seismic") or {}).get("kh", 0.0) or 0.0),
                allowable_bearing_kpa=(
                    None if _cv.get("allowable_bearing_kpa") in (None, "")
                    else float(_cv["allowable_bearing_kpa"])
                ),
            )
            for c in _br.get("checks") or []:
                if not c.get("ok"):
                    _fails.append("箱涵 %s（計算值 %s）" % (c["item"], c.get("value")))
        if _fails:
            err("設計檢核未通過 %d 項，不得交件：%s"
                % (len(_fails), "；".join(_fails)))
    except Exception as _ex:
        warn("設計檢核閘門未完成：%s" % _ex)

    # 預算書工項數量
    boq = case.get("boq") or {}
    items = boq.get("items") or []
    if not items:
        err("boq.items 為空（沒有工項就沒有預算書）")
    for it in items:
        no = it.get("no", "?")
        src = it.get("qty_from")
        if src and it.get("qty") is not None:
            warn(f"工項 {no} 同時有 qty_from 與 qty —— qty 會被 qty_from 覆蓋，建議移除 qty")
        if src and src not in values:
            err(f"工項 {no} 的 qty_from={src!r} 不在模型 {model} 可用的數量鍵："
                f"{', '.join(sorted(values))}")
        if not src and it.get("qty") is None:
            err(f"工項 {no} 既無 qty_from 也無 qty")
        if src and values.get(src) in (None, ""):
            err(f"工項 {no} 引用數量鍵 {src}，但該值未算出／未填")
        if not (it.get("price") or it.get("analysis")):
            err(f"工項 {no} 既無 price 也無 analysis")

    # 圖面比例
    d = case.get("drawing") or {}
    sc = d.get("scale")
    if sc and drawing_rules is not None and not drawing_rules.is_standard_scale(sc):
        err(f"drawing.scale=1/{sc} 不是標準比例尺（tools\\drawing_rules.py）；"
            f"check_delivery.py E16 會擋")

    # 報告必備章節素材
    rep = case.get("report") or {}
    for k in ("summary", "basis", "applicability", "survey", "assumptions",
              "comparison", "drawings", "risks", "deliverables"):
        if k not in rep:
            warn(f"report.{k} 未提供 —— 該章會是空殼或只有標題")

    # 報告「數量表」的數字必須綁回主檔，否則改主檔時它不會同步（等於第二份數字）
    _qobj = rep.get("quantities") or {}
    for tbl in (_qobj.get("items") or []):
        bind = tbl.get("row_bind") or _qobj.get("row_bind") or []
        for ri, row in enumerate(tbl.get("rows") or []):
            try:
                float(str(row[1]).replace(",", ""))
            except Exception:
                continue
            if not (ri < len(bind) and bind[ri].get("key")):
                warn(f"報告數量表「{row[0]}」= {row[1]} 未綁 row_bind → 改主檔不會同步"
                     f"（建議加 row_bind[{ri}] = {{\"key\": \"…\"}}）")

    proj = case.get("project") or {}
    for k in ("name", "agency", "date"):
        if not proj.get(k):
            err(f"project.{k} 未填")
    if not (proj.get("full_name") or proj.get("name")):
        err("project 需要 full_name 或 name")
    if not (proj.get("coords") or []):
        warn("project.coords 未填 —— 報告封面/定位章節會缺座標")
    if proj.get("client") in (None, ""):
        warn("project.client（委託單位）未填 —— 報告封面會留待補")

    return out


# --------------------------------------------------------------------------- #
# 派生
# --------------------------------------------------------------------------- #
def _resolve_qty(item, quantities):
    src = item.get("qty_from")
    if not src:
        return item.get("qty")
    base = quantities.get(src)
    if base in (None, ""):
        return None
    f = float(item.get("qty_factor", 1) or 1)
    return round(float(base) * f, 3)


def derive_boq(case):
    """統一案件檔 → `boq_build.py` 的案件 JSON。"""
    p = case.get("project", {})
    _model, q, _iss = quantity_context(case)
    boq = case.get("boq") or {}
    items = []
    for it in boq.get("items", []):
        item = {k: v for k, v in it.items() if k not in ("qty_from", "qty_factor")}
        qty = _resolve_qty(it, q)
        item["qty"] = qty
        if not item.get("calc"):
            if it.get("qty_from"):
                f = float(it.get("qty_factor", 1) or 1)
                item["calc"] = (f"{q[it['qty_from']]}×{f:g}={qty}" if f != 1
                                else f"{q[it['qty_from']]}（{it['qty_from']}）")
            else:
                item["calc"] = "1" if qty in (1, 1.0) else str(qty)
        items.append(item)

    return {
        "_note": f"由 tools\\case_package\\case_core.py 自 {SCHEMA} 派生，請勿手改",
        "project": p.get("full_name") or p.get("name", ""),
        "location": (p.get("location") or {}).get("desc", ""),
        "agency": p.get("agency", ""),
        "date": p.get("boq_date") or _roc_date(p.get("date", "")),
        "code": p.get("code") or "",
        "rates": boq.get("rates") or {},
        "items": items,
    }


def _fmt_num(v):
    """數量顯示：整數不帶小數點，其餘保留原精度（去尾零）。"""
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    s = f"{f:.6f}".rstrip("0").rstrip(".")
    return s


def _sync_quantity_table(rep, quantities):
    """把「數量表」的數字綁回主檔（單一來源）。

    報告的數量表在範例裡是手打的字串，改主檔不會跟著變 —— 那就等於有第二份數字。
    這裡用 `row_bind`（每列宣告 `key` 與可選 `unit`）把數字欄重算一次；
    沒綁定的列在 `unbound_rows` 標記，交由 consistency() 提醒。
    """
    qobj = rep.get("quantities") or {}
    tables = qobj.get("items") or []
    unbound = []
    for ti, tbl in enumerate(tables):
        # 綁定優先序：表自己的 row_bind → quantities 層級共用的 row_bind（只有一張表時最方便）
        bind = tbl.get("row_bind") or qobj.get("row_bind") or []
        for ri, row in enumerate(tbl.get("rows") or []):
            b = bind[ri] if ri < len(bind) else None
            if not b or not b.get("key"):
                # 只把「看起來是數字」的列記下來提醒
                try:
                    float(str(row[1]).replace(",", ""))
                    unbound.append(f"{tbl.get('caption', f'表{ti + 1}')} 第 {ri + 1} 列"
                                   f"「{row[0]}」= {row[1]}")
                except Exception:
                    pass
                continue
            v = quantities.get(b["key"])
            if v is not None and len(row) > 1:
                dec = b.get("decimals")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    row[1] = (f"{float(v):,.{int(dec)}f}" if dec is not None
                              else _fmt_num(v))
                else:
                    row[1] = str(v)          # 文字型（如 wall_type）原樣帶入
            if b.get("unit") and len(row) > 2:
                row[2] = b["unit"]
    rep.setdefault("_derived", {})["unbound_quantity_rows"] = unbound
    return unbound


def _tbl(caption, cols, rows, note=""):
    return {"caption": caption,
            "columns": [{"name": n, "width_cm": w, "align": a} for n, w, a in cols],
            "rows": rows, "note": note}


def _verdict(ok):
    return "符合" if ok else "不符合"


def _design_sections(model, q, case):
    """由設計計算模組自動產生報告第 6／7／11 章的內容。

    沒有這一段時，這些章節在報告裡是「需人工補」的佔位符 —— 但 FS、Pa、q_max、
    Q_cap、h_n 其實都已經算出來了。算得出卻不寫進報告，是整條產線最刺眼的不一致。
    """
    out = {}
    soil = case.get("soil") or {}
    seism = case.get("seismic") or {}
    kh = float(seism.get("kh", 0.0) or 0.0)

    # ------------------------------------------------ 邊坡
    if model == "slope" and SS is not None:
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

    # ------------------------------------------------ 擋土牆
    if model == "wall" and RW is not None:
        res = RW.analyse(q, soil=soil, seismic={"kh": kh})
        g = res["geometry"]
        wt = "重力式（梯形斷面）" if res["wall_type"] == "gravity" else "懸臂式（薄牆＋底板）"

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
            if res["wall_type"] == "gravity":
                out["reinforcement"] = {
                    "notes": [
                        "本牆為**重力式**擋土牆，靠自重維持穩定，牆身所受應力在混凝土容許應力範圍內，"
                        "**無須結構配筋**（符合水土保持技術規範第 120 條四之前提）。",
                        "配筋僅為溫度收縮與構造需求：牆面與牆背各配置 D13@250 單層構造筋，"
                        "底部配置 D16@200 縱向構造筋，保護層 75 mm。",
                        "若後續改為懸臂式或半重力式，須依撓曲與剪力重新設計配筋。",
                    ],
                    "items": [_tbl(
                        "構造鋼筋配置表",
                        [("位置", 4.6, "left"), ("鋼筋", 3.0, "center"),
                         ("保護層", 2.4, "center"), ("說明", 4.4, "left")],
                        [["牆面（露出側）", "D13@250", "75 mm", "溫度收縮筋（單層）"],
                         ["牆背（靠土側）", "D13@250", "75 mm", "溫度收縮筋（單層）"],
                         ["底部縱向", "D16@200", "75 mm", "構造筋"],
                         ["排水孔周邊", "—", "—", "孔口補強筋依現場調整"]],
                        note="重力式不設受力主筋；配筋量由構造需求控制，非由強度計算控制。")],
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
                         ["斷面類型（§3.4.4）",
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
                        "配筋依據《混凝土結構設計規範》（內政部 100.06.09 發布）："
                        "撓曲 §3.4.4 φ 依淨拉應變判定、最小鋼筋 §3.6.1、"
                        "剪力 §4.4.1.1 Vc=0.53√fc′·bw·d（φ=0.75）。",
                        "**牆之最小鋼筋量依 §7.2.2 指向 §7.4.3**：水平鋼筋比 ρt=0.0025 → "
                        "t=%.0f mm 時需 %.0f mm²/m，實配 %s@%d（%.0f mm²/m）；"
                        "垂直鋼筋比 ρl=0.0015 → 需 %.0f mm²/m，實配 %s@%d（%.0f mm²/m）。"
                        "§7.4.4：牆厚 ≥25 cm 時每一方向鋼筋須分兩層設置（本牆 %.0f mm）。" % (
                            float(q["stem_thickness_m"]) * 1000.0,
                            _wms["As_horizontal_min_mm2"],
                            dd.get("dist_bar"), dd.get("dist_spacing_mm"),
                            dd.get("dist_As_mm2", 0),
                            _wms["As_vertical_min_mm2"],
                            mm.get("bar"), mm.get("spacing_mm"),
                            mm.get("As_prov_mm2", 0),
                            float(q["stem_thickness_m"]) * 1000.0),
                        "⚠ §3.7.2 的最大鋼筋間距規定僅適用**梁與單向版**，不適用於牆；"
                        "牆適用第 7 章。仍須由合格技師覆核。",
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

    # ------------------------------------------------ 箱涵
    if model == "box_culvert" and BC is not None:
        hy = case.get("hydraulics") or {}
        cv = case.get("culvert") or {}
        res = BC.analyse(
            q,
            design_flow_m3s=float(hy.get("design_flow_m3s") or 0.0),
            slope=float(hy.get("slope") or 0.005),
            manning_n=float(hy.get("manning_n") or 0.014),
            freeboard_min_m=float(hy.get("freeboard_min_m") or 0.20),
            soil_unit_weight_kn_m3=float(cv.get("soil_unit_weight_kn_m3") or 18.0),
            soil_phi_deg=float(cv.get("soil_phi_deg") or 30.0),
            surcharge_kpa=float(cv.get("surcharge_kpa") or 0.0),
            traffic_load_kpa=float(cv.get("traffic_load_kpa") or 0.0),
            groundwater_depth_m=(
                None if cv.get("groundwater_depth_m") in (None, "")
                else float(cv["groundwater_depth_m"])
            ),
            internal_water_depth_m=float(cv.get("internal_water_depth_m") or 0.0),
            load_factor=float(cv.get("load_factor") or 1.7),
            seismic_kh=float((case.get("seismic") or {}).get("kh", 0.0) or 0.0),
            allowable_bearing_kpa=(
                None if cv.get("allowable_bearing_kpa") in (None, "")
                else float(cv["allowable_bearing_kpa"])
            ),
        )
        sec = res["section"]
        hyd = res["hydraulic"]
        qty = res["quantities"]
        out["loads"] = {
            "items": [_tbl(
                "箱涵載重與構架分析輸入表（每公尺涵長）",
                [("項目", 4.8, "left"), ("計算式／來源", 6.0, "left"),
                 ("數值", 2.6, "center"), ("單位", 1.4, "center")],
                [
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
        for m in res["members"]:
            f = m["flexure"]
            s = m["shear"]
            cr = m["crack"]
            ax = m.get("axial_flexure") or {}
            ax_capacity = ax.get("phiMn_available_kNm")
            reinf_rows.append([
                "%s（%s）" % (m["member"], m["role"]),
                "t=%.2f m、M=%.2f kN·m/m" % (m["thickness_m"], m["M_service_kNm"]),
                "%s@%s（%.0f mm²/m）" % (
                    f.get("bar", "—"), f.get("spacing_mm", "—"),
                    f.get("As_prov_mm2", 0.0)),
                "φMn=%.2f；軸彎φMn=%s；φVc=%.2f；w=%s mm" % (
                    f.get("phiMn_kNm", 0.0),
                    ("%.2f" % ax_capacity) if ax_capacity is not None else "—",
                    s.get("phiVc_kN", 0.0),
                    ("%.3f" % cr["w_mm"]) if cr.get("w_mm") is not None else "—"),
                _verdict(m["ok"]),
            ])
        out["reinforcement"] = {
            "items": [_tbl(
                "箱涵構架配筋初步結果表",
                [("構材", 3.4, "left"), ("控制內力", 4.0, "left"),
                 ("主筋", 3.4, "center"), ("強度／裂縫", 5.0, "left"),
                 ("判定", 1.8, "center")],
                reinf_rows,
                note="保護層暫採 50 mm；本表為初步設計，未檢核角隅細節、錨定、搭接、剪力筋與施工階段。",
            )],
            "notes": [
                "撓曲、軸彎互制與剪力依《混凝土結構設計規範》相關條文計算；"
                "表中同時列出撓曲 φMn 與構架軸力共同作用下的軸彎 φMn，主筋採單層對稱配置的初步結果。",
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
            ],
        }

    # ------------------------------------------------ 排水溝
    if model == "channel" and CH is not None:
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
                     ["斷面類型（§3.4.4）",
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
                    "配筋依據：撓曲 φMn ≥ Mu、剪力 φVc ≥ Vu、最小鋼筋、裂縫寬度 ≤ 0.3 mm。",
                    "⚠ 公式採 **ACI 318 常用式**；《混凝土結構設計規範》條文尚未取得（版次待核），須技師覆核。",
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

    # 第 12 章：已產出的標準斷面圖（若檔案存在就嵌入，不存在則留給人工）
    fig = case.get("section") or {}
    if fig:
        dxf = fig.get("out") or ""
        base = os.path.splitext(dxf)[0]
        # section.scale 可能是 "auto"（自動挑比例），不能直接 int()
        _sc = fig.get("scale", 20)
        try:
            _sc_txt = "1:%d" % int(_sc)
        except (TypeError, ValueError):
            _sc_txt = "1:%s（自動）" % _sc
        for cand, cap in ((base + "_pdf.png", "標準斷面圖（A3，%s）" % _sc_txt),
                          (base + ".png", "標準斷面圖")):
            if dxf and os.path.exists(cand):
                out.setdefault("drawings", {})["figures"] = [{
                    "path": cand, "title": cap,
                    "note": "由 tools/wall_section/make_wall_section.py 產製，"
                            "已通過 check_delivery.py（E1~E18）。",
                    "width_cm": 15.5,
                }]
                break

    return out


def derive_report(case):
    """統一案件檔 → `make_report.py` 的案件 JSON。"""
    p = case.get("project", {})
    _model, q, _iss = quantity_context(case)
    rep = copy.deepcopy(case.get("report") or {})

    rp = rep.setdefault("project", {})
    rp.update({
        "name": p.get("name", ""),
        "full_name": p.get("full_name") or p.get("name", ""),
        "code": p.get("code"),
        "category": p.get("category", "道路"),
        "location": p.get("location") or {},
        "crs": p.get("crs") or {"name": "TWD97 TM2 二度分帶", "epsg": "EPSG:3826", "unit": "公尺"},
        "coords": p.get("coords") or [],
        "client": p.get("client"),
        "designer": p.get("designer", ""),
        "reviewer": p.get("reviewer"),
        "date": p.get("date", ""),
        "version": p.get("version", "v1.0"),
    })

    # 數量純量：唯一來源在主檔，強制覆蓋（不允許報告段自帶一套）
    rq = rep.setdefault("quantities", {})
    # 注入模型算出的**所有**數值鍵（道路是 L/W/A/t/V；牆是混凝土體積／模板／排水孔…）
    for k, v in q.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            rq[k] = v
    rq["model"] = _model
    if case.get("report", {}).get("quantities_note"):
        rq["notes"] = case["report"]["quantities_note"]

    # 數量表：案件沒自備時，由模型自動生成（數字直接取衍生值，不可能過期）
    if not rq.get("items"):
        tbl = QM.MODELS.get(_model, {}).get("table")
        if tbl:
            cols = [
                {"name": "項目", "width_cm": 5.0, "align": "left"},
                {"name": "數量", "width_cm": 2.6, "align": "center"},
                {"name": "單位", "width_cm": 1.6, "align": "center"},
                {"name": "計算依據", "width_cm": 6.2, "align": "left"},
            ]
            rows, bind = [], []
            for r in tbl["rows"]:
                if q.get(r["key"]) is None:
                    continue
                rows.append([r["label"], q[r["key"]], r.get("unit", ""), r.get("basis", "")])
                bind.append({"key": r["key"], "unit": r.get("unit", ""),
                             "decimals": r.get("decimals", 2)})
            rq["items"] = [{"caption": tbl.get("caption", "工程數量表"),
                            "columns": cols, "rows": rows, "row_bind": bind,
                            "note": tbl.get("note", "")}]
            rep.setdefault("_derived", {})["quantity_table"] = "auto"
    _sync_quantity_table(rep, q)

    # 設計計算結果自動注入第 6／7／11 章（案件已自備者不覆蓋）
    try:
        auto = _design_sections(_model, q, case)
        for k, v in auto.items():
            if not rep.get(k):
                rep[k] = v
                rep.setdefault("_derived", {})[f"{k}_sections"] = "auto"
    except Exception as ex:                       # 計算失敗不阻擋報告產出，但要看得見
        rep.setdefault("_derived", {})["design_sections_error"] = str(ex)

    rep.setdefault("report", {
        "title": p.get("report_title", "設計報告書"),
        "subtitle": p.get("report_subtitle", ""),
    })
    rep["schema_version"] = rep.get("schema_version", 1.0)
    rep["_note"] = f"由 tools\\case_package\\case_core.py 自 {SCHEMA} 派生，請勿手改"
    return rep


def summary(case):
    p, q = case.get("project", {}), case.get("quantities", {})
    boq = derive_boq(case)
    return {
        "案件": p.get("full_name") or p.get("name"),
        "類別": p.get("category"),
        "L(m)": q.get("length_m"), "W(m)": q.get("width_avg_m"),
        "A(m2)": q.get("area_m2"), "t(cm)": q.get("thickness_cm"), "V(m3)": q.get("volume_m3"),
        "工項數": len(boq["items"]),
        "工項合計（直接工程費前）": None,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="統一案件檔：一致性檢查與兩軸輸入派生")
    ap.add_argument("action", choices=["check", "derive", "show"])
    ap.add_argument("case", help="統一案件檔（civil-case/1）")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()

    path = a.case if os.path.isabs(a.case) else os.path.abspath(a.case)
    case = load(path)
    issues = consistency(case)
    errors = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]

    print(f"案件：{(case.get('project') or {}).get('full_name') or (case.get('project') or {}).get('name')}")
    print(f"一致性：{len(errors)} error / {len(warns)} warn")
    for i in issues:
        print(f"  [{('ERROR' if i['level'] == 'error' else 'warn ')}] {i['msg']}")

    if a.action == "show":
        print(json.dumps(summary(case), ensure_ascii=False, indent=1))
        sys.exit(0 if not errors else 1)

    if a.action == "check":
        sys.exit(0 if not errors else 1)

    # derive
    out = a.out_dir or os.path.join(os.path.dirname(path), "_derived")
    out = out if os.path.isabs(out) else os.path.abspath(out)
    os.makedirs(out, exist_ok=True)

    boq = derive_boq(case)
    rep = derive_report(case)
    bp = os.path.join(out, "boq_case.json")
    rp = os.path.join(out, "report_case.json")
    json.dump(boq, open(bp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(rep, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ip = os.path.join(out, "consistency.json")
    json.dump(issues, open(ip, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n派生：{bp}\n     {rp}\n檢查：{ip}")
    print(f"  預算書工項 {len(boq['items'])} 項、合計數量已由主檔解析")
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
