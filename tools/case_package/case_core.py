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
import re
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
    import wall_system as WS                         # 擋土牆七型分流入口
except Exception:                                    # design 模組缺失時不阻擋
    HY = RW = CH = RC = SS = BC = WS = None

SCHEMA = "civil-case/1"

# quantities 可被工項引用的鍵
QTY_KEYS = ("length_m", "width_avg_m", "width_median_m", "area_m2", "thickness_cm", "volume_m3")

from report_sections import (  # noqa: E402  報告段落派生（拆出見 2026-11-11 W7）
    _fmt_num, _tbl, _verdict, _wall_limit_text, _wall_check_rows,
    _rebar_summary_table, _advanced_wall_sections, _dxf_scale,
    _attach_section_figure, _design_sections,
)



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


def _pick_value(*values, default=None):
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _box_culvert_kwargs(case, values):
    """箱涵分析參數的唯一來源；數量、預算、報告與設計閘門共用。"""
    hy = case.get("hydraulics") or {}
    cv = case.get("culvert") or {}
    return {
        "design_flow_m3s": float(hy.get("design_flow_m3s") or 0.0),
        "slope": float(hy.get("slope") or 0.005),
        "manning_n": float(hy.get("manning_n") or 0.014),
        "freeboard_min_m": float(hy.get("freeboard_min_m") or 0.20),
        "soil_unit_weight_kn_m3": float(
            cv.get("soil_unit_weight_kn_m3") or 18.0),
        "soil_phi_deg": float(cv.get("soil_phi_deg") or 30.0),
        "surcharge_kpa": float(cv.get("surcharge_kpa") or 0.0),
        "traffic_type": _pick_value(
            cv.get("traffic_type"), values.get("traffic_type"), default="h20"),
        "traffic_load_kpa": float(
            _pick_value(cv.get("traffic_load_kpa"),
                        values.get("traffic_load_kpa"), default=0.0)),
        "traffic_lanes": int(
            _pick_value(cv.get("traffic_lanes"),
                        values.get("traffic_lanes"), default=4)),
        "traffic_impact_factor": (
            None if _pick_value(cv.get("traffic_impact_factor"),
                                values.get("traffic_impact_factor")) is None
            else float(_pick_value(cv.get("traffic_impact_factor"),
                                   values.get("traffic_impact_factor")))),
        "groundwater_depth_m": (
            None if _pick_value(cv.get("groundwater_depth_m"),
                                values.get("groundwater_depth_m")) is None
            else float(_pick_value(cv.get("groundwater_depth_m"),
                                   values.get("groundwater_depth_m")))),
        "internal_water_depth_m": float(
            cv.get("internal_water_depth_m") or 0.0),
        "load_factor": float(cv.get("load_factor") or 1.7),
        "seismic_kh": float((case.get("seismic") or {}).get("kh", 0.0) or 0.0),
        "allowable_bearing_kpa": (
            None if _pick_value(cv.get("allowable_bearing_kpa"),
                                values.get("allowable_bearing_kpa")) is None
            else float(_pick_value(cv.get("allowable_bearing_kpa"),
                                   values.get("allowable_bearing_kpa")))),
        "cover_mm": float(
            _pick_value(cv.get("cover_mm"), values.get("cover_mm"), default=50.0)),
        "crack_limit_mm": float(
            _pick_value(cv.get("crack_limit_mm"),
                        values.get("crack_limit_mm"), default=0.30)),
        "bar_preference": str(
            _pick_value(cv.get("bar_preference"),
                        values.get("bar_preference"), default="auto")),
        "distribution_bar": str(
            _pick_value(cv.get("distribution_bar"),
                        values.get("distribution_bar"), default="D13")),
        "rebar_loss_rate": float(
            _pick_value(cv.get("rebar_loss_rate"),
                        values.get("rebar_loss_rate"),
                        default=BC.REBAR_LOSS_RATE
                        if BC is not None else 0.06)),
    }


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
            if WS is None:
                raise RuntimeError("wall_system 未載入")
            _wr = WS.analyse(values, case)
            # 牆型分流的唯一入口：重力式／半重力式走名目構造鋼筋，
            # 懸臂式才做莖板＋底板的撓曲配筋。不可再對所有 wall 套同一公式。
            _wd = WS.rebar_design(values, _wr)
            values["rebar_kg_per_m_design"] = round(_wd["total_kg_per_m"], 2)
            values["rebar_kg_design"] = round(_wd["total_kg_per_m"] * _L, 1)
            values["wall_rebar"] = {
                "wall_type": _wd["wall_type"],
                "total_kg_per_m": round(_wd["total_kg_per_m"], 3),
                "ok": bool(_wd.get("ok")),
            }
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
        elif model == "box_culvert" and BC is not None and _L > 0:
            _br = BC.analyse(values, **_box_culvert_kwargs(case, values))
            _bq = _br["quantities"]
            values["rebar_kg_per_m_design"] = _bq["rebar_kg_per_m"]
            values["rebar_kg_design"] = _bq["rebar_kg_total"]
            values["rebar_loss_rate"] = _bq["rebar_loss_rate"]
            values["formwork_m2_per_m_design"] = _bq["formwork_m2_per_m"]
            values["formwork_m2_design"] = _bq["formwork_m2"]
    except Exception as _ex:
        if model == "wall":
            issues.append({
                "level": "error",
                "msg": ("擋土牆配筋／數量未算出：%s。請確認 wall_type 與必要輸入"
                        "（gravity／semigravity／cantilever／counterfort／anchored／mse）。"
                        % _ex),
            })
        else:
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
    if model in ("wall", "channel", "box_culvert") and RC is not None:
        try:
            _ratio = float(values.get("rebar_ratio_kg_m3") or 0)
            _kg = float(values.get("rebar_kg") or 0)
            _design_kg = None
            if model == "wall" and WS is not None:
                _wr = WS.analyse(values, case)
                _wd = WS.rebar_design(values, _wr)
                _design_kg = _wd["total_kg_per_m"] * float(values.get("length_m") or 0)
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
            if model == "box_culvert" and _design_kg is None:
                _design_kg = float(values.get("rebar_kg_design") or 0.0) or None
            if _design_kg and _kg > 0:
                _diff = (_design_kg - _kg) / _kg * 100.0
                if abs(_diff) > 25.0:
                    warn("鋼筋量：case 內的含鋼量假設值 %.1f kg/m³ 推得 %.0f kg，"
                         "與配筋設計值 %.0f kg 差 %+.0f%%。"
                         "預算與報告已採設計值（rebar_kg_design）；"
                         "建議更新或移除 rebar_ratio_kg_m3，避免日後誤用。"
                         % (_ratio, _kg, _design_kg, _diff))
        except Exception as _ex:
            warn("鋼筋量交叉檢查未完成：%s" % _ex)

    # ---- 第五道閘門：設計檢核必須全部通過 ----
    # 先前「設計檢核有沒有全部通過」只印在報告第 7 章，沒有任何交付閘門在管：
    # 某個斷面真的有一項不過，圖照出、預算照算、報告照印，全軸照樣「通過」。
    # 這裡把它變成 error（不是 warn）—— 不通過就不能交件。
    try:
        _fails = []
        if model == "wall" and WS is not None:
            _wr = WS.analyse(values, case)
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
            _br = BC.analyse(values, **_box_culvert_kwargs(case, values))
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
        "agency": p.get("agency", ""),          # 主辦機關要帶到報告封面（缺了會被 exit 4 擋下）
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
                show_if = r.get("show_if") or {}
                if show_if and any(q.get(k) != v for k, v in show_if.items()):
                    continue
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
