"""工程預算書計算核心（費率模型）— 依 `103.崙背鄉草湖村河川便道改善工程` 實際預算書之公式重建。

公式來源（實測 `預算書.xlsx` 的 詳細表 公式欄）：
  A(小計A)   = 直接工程費 = Σ(數量×單價)
  品質管制   = ROUND(A*0.006, -1)
  職安衛生   = ROUND(A*0.005, -1)
  保險       = ROUND(A*0.006, -1)
  利潤管理   = ROUND(A*0.07 ,  0) + adj_profit      # 參考案 adj_profit = -505（人工微調）
  營業稅     = ROUND((A+品質+職安+保險+利潤)*0.05, 0)
  發包工程費 = A + 品質 + 職安 + 保險 + 利潤 + 稅
  機關管理   = ROUND((發包-稅-保險)*0.035, 0)
  空氣污染   = ROUND(發包*0.003, 0) + adj_air        # 參考案 adj_air = +54（人工微調）
  設計監造   = ROUND((發包-稅-利潤-保險)*0.105*0.9, 0)
  直接小計/間接小計/總計 = 對應加總

已驗證：以參考案 A=690,800、adj_profit=-505、adj_air=54 代入，逐項與原檔完全一致，
總計 = 882,434（見 `_selftest/selftest_rules.py`）。

所有數值計算一律採 **Excel ROUND 語意（四捨五入、進位遠離零）**，不可用 Python 內建 round（銀行家捨入）。
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- 預設費率（可被案件 JSON 覆寫）----
DEFAULT_RATES = {
    "quality": 0.006,          # 工程品質管制費 ≈ A×0.6%
    "safety": 0.005,           # 職業安全衛生管理費 ≈ A×0.5%
    "insurance": 0.006,        # 營造綜合保險費 ≈ A×0.6%
    "profit": 0.07,            # 承包商利潤及管理費 ≈ A×7%
    "tax": 0.05,               # 營業稅 5%
    "agency_mgmt": 0.035,      # 主辦機關工程管理費（500 萬元以下 3.5%）
    "air": 0.003,              # 空氣污染防制費 ≈ 發包工程費×0.3%
    "supervision": 0.105,      # 設計監造費（500 萬元以下 10.5%）
    "supervision_factor": 0.9, # ×0.9
    "adj_profit": 0.0,         # 利潤人工調整額（元）
    "adj_air": 0.0,            # 空污人工調整額（元）
}


def xround(x, n=0):
    """Excel ROUND：四捨五入、進位遠離零。n 可為負（-1 = 進位到 10 位）。"""
    if x is None:
        return 0.0
    d = Decimal(repr(float(x)))
    q = Decimal(1).scaleb(-n)          # n=-1 → Decimal('1E+1')
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def item_unit_price(analysis, explicit_price=None, basis=1):
    """單價＝（單價分析表工料複價合計）÷ basis；若給 explicit_price 則直接採用。

    `basis`（分析基準數量）對應單價分析表標題的「單位：100 M2」這種寫法：
    工料數量是「每 100 M2」的用量，合計 30,000，則每 M2 單價 = 30,000 / 100 = 300。
    參考案 04／05 兩項即為 basis=100，其餘為 basis=1。
    """
    if explicit_price is not None:
        return float(explicit_price)
    total = 0.0
    for row in analysis or []:
        total += float(row.get("qty", 0)) * float(row.get("price", 0))
    b = float(basis or 1)
    if b <= 0:
        b = 1.0
    return xround(total / b, 2)


def compute(items, rates=None):
    """回傳完整計算結果 dict（含逐項與費率層）。

    items: [{"no","name","unit","qty","price"?, "analysis"?, "note"?}, ...]
    """
    r = dict(DEFAULT_RATES)
    r.update(rates or {})

    rows = []
    for it in items:
        qty = float(it.get("qty", 0))
        up = item_unit_price(it.get("analysis"), it.get("price"), it.get("basis", 1))
        rows.append({
            **it,
            "qty": qty,
            "price": up,
            "amount": xround(qty * up, 0),
            "has_analysis": bool(it.get("analysis")),
            "basis": float(it.get("basis", 1) or 1),
            "analysis_sum": xround(sum(float(g.get("qty", 0)) * float(g.get("price", 0))
                                       for g in (it.get("analysis") or [])), 2),
        })

    A = sum(row["amount"] for row in rows)                 # 小計A＝直接工程費

    quality = xround(A * r["quality"], -1)
    safety = xround(A * r["safety"], -1)
    insurance = xround(A * r["insurance"], -1)
    profit = xround(A * r["profit"], 0) + float(r["adj_profit"])
    tax = xround((A + quality + safety + insurance + profit) * r["tax"], 0)

    contract = A + quality + safety + insurance + profit + tax      # 發包工程費

    agency_mgmt = xround((contract - tax - insurance) * r["agency_mgmt"], 0)
    air = xround(contract * r["air"], 0) + float(r["adj_air"])
    supervision = xround((contract - tax - profit - insurance)
                         * r["supervision"] * r["supervision_factor"], 0)

    indirect = agency_mgmt + air + supervision
    total = contract + indirect

    return {
        "items": rows,
        "rates": r,
        "direct": A,
        "quality": quality,
        "safety": safety,
        "insurance": insurance,
        "profit": profit,
        "tax": tax,
        "contract": contract,
        "agency_mgmt": agency_mgmt,
        "air": air,
        "supervision": supervision,
        "indirect": indirect,
        "total": total,
    }


def fmt(n, nd=0):
    """千分位字串（給報告／console 用）。"""
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n)):,}"
    return f"{n:,.{nd}f}"
