r"""預算書計算核心回歸測試：必須完全重現公司真實預算書的每一個數字。

真實來源：`103.崙背鄉草湖村河川便道改善工程\01.設計預算書圖\...預算書.xlsx`
（5 工作表：封面／總表／詳細表／單價分析表／數量計算）

執行：
    set PYTHONIOENCODING=utf-8
    C:\\Python312\\python.exe D:\\公司案件.AI\\tools\\boq\\selftest\\selftest_rules.py

退出碼 0 = 全部對上。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import boq_rules as R  # noqa: E402

CASE = os.path.join(HERE, "崙背鄉草湖村河川便道改善工程.json")

# 原檔實測值（逐格取自 詳細表 / 總表）
EXPECT = {
    "direct": 690800,      # 小計A
    "quality": 4140,       # 二 工程品質管制費
    "safety": 3450,        # 三 職業安全衛生管理費
    "insurance": 4140,     # 四 營造綜合保險費
    "profit": 47851,       # 五 承包商利潤及管理費
    "tax": 37519,          # 六 營業稅
    "contract": 787900,    # 發包工程費(壹)合計
    "agency_mgmt": 26118,  # 貳.一 主辦機關工程管理費
    "air": 2418,           # 貳.二 空氣污染防制費
    "supervision": 65998,  # 貳.三 設計監造費
    "indirect": 94534,     # 間接工程費小計
    "total": 882434,       # 總計
}

ITEM_EXPECT = [  # (項目, 單價, 複價)
    ("01", 2500.0, 2500),
    ("02", 2500.0, 2500),
    ("03", 4000.0, 4000),
    ("04", 100.0, 160000),
    ("05", 300.0, 480000),
    ("06", 41800.0, 41800),
]


def main():
    case = json.load(open(CASE, encoding="utf-8"))
    calc = R.compute(case["items"], case.get("rates"))

    bad = []
    for k, want in EXPECT.items():
        got = calc[k]
        flag = "OK " if abs(got - want) < 0.5 else "FAIL"
        if flag == "FAIL":
            bad.append(f"{k}: got {got} want {want}")
        print(f"  [{flag}] {k:12s} {R.fmt(got):>12s}  期望 {R.fmt(want):>12s}")

    print()
    for (no, price, amount), it in zip(ITEM_EXPECT, calc["items"]):
        ok_p = abs(it["price"] - price) < 0.01
        ok_a = abs(it["amount"] - amount) < 0.5
        flag = "OK " if (ok_p and ok_a) else "FAIL"
        if flag == "FAIL":
            bad.append(f"{no} 單價/複價 {it['price']}/{it['amount']} want {price}/{amount}")
        print(f"  [{flag}] {no} {it['name'][:22]:24s} 單價 {R.fmt(it['price'], 2):>10s} "
              f"複價 {R.fmt(it['amount']):>10s}")

    print()
    if bad:
        print("回歸失敗：")
        for b in bad:
            print("  -", b)
        sys.exit(1)
    print(f"回歸通過：{len(EXPECT)} 個費率值 + {len(ITEM_EXPECT)} 個品項全部與真實預算書一致，"
          f"總計 {R.fmt(calc['total'])} 元")


if __name__ == "__main__":
    main()
