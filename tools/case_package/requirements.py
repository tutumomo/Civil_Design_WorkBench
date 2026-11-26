"""需求單（requirements）schema 與追溯矩陣。

為什麼需要這一段
----------------
目前 `civil-case/1` 只描述「做了什麼」（數量、預算工項、報告章節），
沒有描述「案子要求什麼」。兩者的差距沒有任何機制可以指出來：
需求單上的「不得淹水」「結構須可承受 HS20 車輛」這類條款，
沒有辦法追到哪一份圖、哪一段計算、哪一行預算去滿足它。

這裡定義 `requirements` 區塊（選填，沒有它時全案行為完全不變）：

    "requirements": {
      "source": "契約需求單 2026-11-xx",
      "items": [
        {
          "id": "R-01",
          "text": "擋土牆頂不得高出既有路緣 10 cm",
          "origin": "契約需求單 §3.2",
          "kind": "geometric",              # geometric|hydraulic|structural|quantity|drawing|other
          "mandatory": true,                # false = 建議事項，非強制
          "satisfied_by": [                 # 追溯：這條需求由誰滿足
            {"type": "calculation", "ref": "wall_system:section_area_m2"},
            {"type": "drawing",     "ref": "S-01_擋土牆標準斷面圖"},
            {"type": "boq_item",    "ref": "03"}
          ],
          "evidence": "牆頂高程與既有路緣高差 0.08 m，見 S-01 斷面圖",
          "status": "satisfied"             # satisfied|open|na（由工具判定後回寫）
        }
      ]
    }

追溯矩陣由 `trace()` 產生：逐條需求列出「需求 → 滿足它的項目 → 該項目是否
真的存在於案件檔」，對不上的需求標 `open`（缺證據）而不是假裝已滿足。

**誠實原則**：工具只驗「追溯鏈條是否指得到實際存在的東西」，
不驗「工程判斷是否正確」——那需要人簽核。
"""

from __future__ import annotations

import os
import re

#: 需求的種類（供報告與檢核分組用）。
KINDS = ("geometric", "hydraulic", "structural", "quantity", "drawing", "other")

#: 追溯目標的種類。
TARGET_TYPES = ("calculation", "drawing", "boq_item", "report_section", "note", "file")

#: 需求 id 的命名慣例：R-01、R-02…
REQ_ID_RE = re.compile(r"^R-\d{2,}$")


def _norm_case(case):
    """需求 id 大小寫不敏感比對（寫 r-01 也要能對上 R-01）。"""
    return str(case or "").strip().upper()


def _boq_item_nos(case):
    return {str(it.get("no", "")).strip()
            for it in ((case.get("boq") or {}).get("items") or [])
            if it.get("no") is not None}


def _drawing_files(case):
    """案件檔裡出現過的圖檔名（畫面圖、斷面圖、計算器出圖皆算）。"""
    out = set()
    for key in ("drawing", "section", "design"):
        node = case.get(key)
        if not isinstance(node, dict):
            continue
        for k, v in node.items():
            if isinstance(v, str) and v.lower().endswith((".dxf", ".dwg", ".pdf", ".png")):
                out.add(os.path.basename(v))
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.lower().endswith(
                            (".dxf", ".dwg", ".pdf", ".png")):
                        out.add(os.path.basename(item))
                    elif isinstance(item, dict):
                        for sv in item.values():
                            if isinstance(sv, str) and sv.lower().endswith(
                                    (".dxf", ".dwg", ".pdf", ".png")):
                                out.add(os.path.basename(sv))
    return out


def _report_sections(case):
    rep = case.get("report") or {}
    return set(k for k, v in rep.items() if isinstance(v, (dict, list)) and v)


def validate(case):
    """驗證 requirements 區塊的結構。回傳 [{level, msg}]。

    只擋「格式錯誤」與「追溯指不到東西」；需求是否真的滿足由人判斷，
    這裡不臆測。
    """
    out = []

    def err(m):
        out.append({"level": "error", "msg": m})

    def warn(m):
        out.append({"level": "warn", "msg": m})

    req = case.get("requirements")
    if req is None:
        return out                       # 選填區塊：沒有就完全不管
    if not isinstance(req, dict):
        err("requirements 必須是物件（含 source 與 items）")
        return out
    items = req.get("items")
    if not isinstance(items, list):
        err("requirements.items 必須是清單")
        return out

    seen = set()
    for i, it in enumerate(items):
        tag = "requirements.items[%d]" % i
        if not isinstance(it, dict):
            err("%s 必須是物件" % tag)
            continue
        rid = str(it.get("id") or "").strip()
        if not rid:
            err("%s 缺 id" % tag)
        elif not REQ_ID_RE.match(rid.upper()):
            warn("%s 的 id=%r 不符 R-01 命名慣例" % (tag, rid))
        elif rid.upper() in seen:
            err("需求 id 重複：%s" % rid)
        else:
            seen.add(rid.upper())
        if not str(it.get("text") or "").strip():
            err("%s（%s）缺 text（需求敘述）" % (tag, rid or "?"))
        kind = str(it.get("kind") or "").strip()
        if kind and kind not in KINDS:
            warn("%s（%s）的 kind=%r 不在 %s 內" % (tag, rid or "?", kind, list(KINDS)))
        sb = it.get("satisfied_by")
        if sb is not None and not isinstance(sb, list):
            err("%s（%s）的 satisfied_by 必須是清單" % (tag, rid or "?"))
        if isinstance(sb, list):
            for j, t in enumerate(sb):
                if not isinstance(t, dict):
                    err("%s（%s）.satisfied_by[%d] 必須是物件" % (tag, rid or "?", j))
                    continue
                tt = str(t.get("type") or "").strip()
                if tt not in TARGET_TYPES:
                    warn("%s（%s）.satisfied_by[%d] 的 type=%r 不在 %s 內"
                         % (tag, rid or "?", j, tt, list(TARGET_TYPES)))
                if not str(t.get("ref") or "").strip():
                    err("%s（%s）.satisfied_by[%d] 缺 ref" % (tag, rid or "?", j))
    return out


def trace(case):
    """產生追溯矩陣。

    回傳 {"source":…, "rows": [{id, text, origin, kind, mandatory, status,
                                 targets:[{type, ref, found, detail}], evidence}]}

    `status`：
      satisfied —— 每個追溯目標都指得到案件檔裡實際存在的東西，且有 evidence
      open      —— 有目標指不到（缺圖／缺工項／缺章節），或完全沒有追溯目標
      na        —— mandatory=false 且未填追溯（建議事項，不擋交件）
    """
    req = case.get("requirements") or {}
    items = req.get("items") or []
    boq_nos = _boq_item_nos(case)
    drawings = _drawing_files(case)
    rep_sections = _report_sections(case)

    rows = []
    for it in items:
        rid = str(it.get("id") or "").strip()
        targets = []
        missing = 0
        for t in (it.get("satisfied_by") or []):
            if not isinstance(t, dict):
                continue
            tt = str(t.get("type") or "").strip()
            ref = str(t.get("ref") or "").strip()
            found, detail = _resolve_target(case, tt, ref, boq_nos, drawings, rep_sections)
            if not found:
                missing += 1
            targets.append({"type": tt, "ref": ref, "found": found, "detail": detail})
        evidence = str(it.get("evidence") or "").strip()
        mandatory = it.get("mandatory", True)
        if not targets:
            status = "open" if mandatory else "na"
        elif missing:
            status = "open"
        elif not evidence:
            status = "open"
        else:
            status = "satisfied"
        rows.append({
            "id": rid, "text": str(it.get("text") or "").strip(),
            "origin": str(it.get("origin") or "").strip(),
            "kind": str(it.get("kind") or "").strip(),
            "mandatory": bool(mandatory),
            "status": status, "targets": targets, "evidence": evidence,
        })
    return {"source": str(req.get("source") or "").strip(), "rows": rows}


def _resolve_target(case, tt, ref, boq_nos, drawings, rep_sections):
    """追溯目標是否指得到案件檔裡實際存在的東西。"""
    if not ref:
        return False, "缺 ref"
    if tt == "boq_item":
        ok = ref.strip() in boq_nos
        return ok, ("工項 %s 存在" % ref) if ok else "預算書找不到工項編號 %s" % ref
    if tt == "drawing":
        base = os.path.basename(ref)
        ok = base in drawings or ref in drawings
        return ok, ("圖 %s 存在" % base) if ok else "案件檔找不到圖 %s" % base
    if tt == "report_section":
        ok = ref.strip() in rep_sections
        return ok, ("報告章節 %s 有內容" % ref) if ok else "報告找不到章節 %s" % ref
    if tt == "calculation":
        # 計算類追溯：檢查 `engine:key` 或單一 key 是否真的算得出來。
        ok, detail = _resolve_calculation(case, ref)
        return ok, detail
    if tt == "file":
        p = ref if os.path.isabs(ref) else os.path.join(_root(), ref)
        ok = os.path.exists(p)
        return ok, ("檔案存在：%s" % ref) if ok else "檔案不存在：%s" % ref
    if tt == "note":
        return True, "人工註記"
    return False, "未知的追溯類型 %r" % tt


def _resolve_calculation(case, ref):
    """`engine:key` 或 `key` 形式的計算追溯是否成立。"""
    if ":" in ref:
        engine, key = ref.split(":", 1)
    else:
        engine, key = None, ref
    model = (case.get("quantities") or {}).get("model")
    # 用「已派生的」數量值（case_core.quantity_context 會跑 qty_models 的
    # derive），不是只有原始輸入 —— 派生值（如 section_area_m2）才是
    # 真正對外承諾的量。
    values = _derived_values(case)
    # engine 段是「哪個引擎算的」；多數情況它等於 model，但允許寫
    # `wall_system:section_area_m2` 這種明確指名引擎的寫法。
    # 只要該鍵算得出來就算數，不因引擎名不同就判失敗。
    if key in values:
        return True, "數量模型含 %s" % key
    # 由設計引擎的結果取：能算出來就算成立。
    try:
        result = _engine_result(model, values, case)
    except Exception:
        result = None
    if isinstance(result, dict) and key in result:
        return True, "計算結果含 %s" % key
    return False, "算不出 %s（%s）" % (key, engine or model)


def _derived_values(case):
    """案件檔已派生的數量值（含 qty_models 的 derive 結果）。"""
    try:
        from case_core import quantity_context
        _model, _q, _iss = quantity_context(case)
        return dict(_q or {})
    except Exception:
        return dict((case.get("quantities") or {}).get("values") or {})


def _engine_result(model, values, case):
    if not model:
        return None
    calc_map = {
        "rc_beam": "rc_beam", "rc_column": "rc_column",
        "foundation_isolated": "foundation_isolated",
        "foundation_combined": "foundation_combined",
        "channel_cover": "channel_cover", "detention_basin": "detention_basin",
        "sediment_basin": "sediment_basin", "steel_column": "steel_column",
        "building_frame": "building_frame", "channel_profile": "channel_profile",
        "pile_group": "foundation_pile", "settlement": "settlement_assessment",
    }
    calc_id = calc_map.get(model)
    if not calc_id:
        return None
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    design_dir = os.path.join(os.path.dirname(here), "design")
    if design_dir not in sys.path:
        sys.path.insert(0, design_dir)
    import design_api as API
    env = API.run_calculation(calc_id, values)
    return (env or {}).get("result") or {}


def _root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def matrix_markdown(tr):
    """把追溯矩陣輸出成 Markdown 表格（報告附錄與交付清單用）。"""
    rows = tr.get("rows") or []
    L = []
    L.append("| 編號 | 需求 | 來源 | 追溯標的 | 證據 | 狀態 |")
    L.append("|---|---|---|---|---|---|")
    mark = {"satisfied": "已滿足", "open": "**未滿足**", "na": "不適用（建議事項）"}
    for r in rows:
        tg = "<br>".join("%s:%s%s" % (t["type"], t["ref"],
                                      "" if t["found"] else "（找不到）")
                         for t in r["targets"]) or "—"
        L.append("| %s | %s | %s | %s | %s | %s |"
                 % (r["id"], r["text"], r["origin"] or "—", tg,
                    r["evidence"] or "—", mark.get(r["status"], r["status"])))
    return "\n".join(L)
