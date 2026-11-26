r"""圖／數對帳自測（item 3）：每個可出圖模型的 DXF 都必須對得上數量模型。

為什麼需要這一支
----------------
`tools/takeoff/dxf_takeoff.py` 原本只會對「擋土牆／箱涵」做斷面積對帳，
其餘可出圖模型一律落進 fallback，印「無法對帳」就結束 —— 也就是說
21 個可出圖計算器裡有 13 個**從來沒有被對帳過**。

這一支把每個模型都跑一次：出 DXF → 量圖 → 對數量 → 必須相符。
預期值全部由**計算引擎結果**推導（不是手抄常數），所以引擎改了這裡會跟著抓。

判定分三態，與 `dxf_takeoff` 的退出碼一致：
  0 ＝ 相符；1 ＝ 超過容差（對不上）；2 ＝ 未對帳（不適用／缺輸入）。
「未對帳」不可當成「相符」。

Run:
    .venv/bin/python tools/selftest/takeoff_reconcile_selftest.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/design", "tools/takeoff", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import design_api as API  # noqa: E402
import design_section as DS  # noqa: E402
import dxf_takeoff as T  # noqa: E402

FAILS: list[str] = []

#: 必須對得上帳的模型（case model 名 → 計算器 id）。
#: 這裡刻意不含 drainage_network：它是示意圖，圖上長度不是實距，
#: 規格裡已明寫「不適用數量對帳」。
RECONCILE_MODELS = {
    "rc_beam": "rc_beam",
    "rc_column": "rc_column",
    "foundation_isolated": "foundation_isolated",
    "foundation_combined": "foundation_combined",
    "channel_cover": "channel_cover",
    "detention_basin": "detention_basin",
    "sediment_basin": "sediment_basin",
    "steel_column": "steel_column",
    "building_frame": "building_frame",
    "channel_profile": "channel_profile",
    "pile_group": "foundation_pile",
    "settlement": "settlement_assessment",
}

TOL_PCT = 0.5


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _run_takeoff(dxf, cpath):
    p = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "takeoff" / "dxf_takeoff.py"),
         str(dxf), "--case", str(cpath), "--tol", str(TOL_PCT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    detail = next((l.strip() for l in (p.stdout or "").splitlines()
                   if l.strip().startswith("→")), "")
    return p.returncode, detail or (p.stdout or p.stderr or "")[-300:]


def main() -> int:
    cat = {c["id"]: c for c in API.CATALOG}
    tmp = Path(tempfile.mkdtemp(prefix="takeoff_reconcile_"))

    print("[1] 每個可出圖模型都有對帳規格")
    for model in RECONCILE_MODELS:
        check("規格存在：%s" % model, model in T.RECONCILE_SPECS)
    check("排水網路明示不適用",
          T.RECONCILE_SPECS.get("drainage_network", {}).get("kind") == "na")

    print("[2] 出 DXF → 量圖 → 對數量（每一個都要相符）")
    for model, calc_id in RECONCILE_MODELS.items():
        ex = (cat.get(calc_id) or {}).get("example")
        if not ex:
            check("%s 有範例輸入" % calc_id, False, "CATALOG 無 example")
            continue
        try:
            res = DS.generate(calc_id, ex, publish=False, out_dir=str(tmp / calc_id))
        except Exception as ex2:  # noqa: BLE001
            check("%s 出圖成功" % calc_id, False, str(ex2))
            continue
        dxf = next((f["path"] for f in res.get("files", []) if f["path"].endswith(".dxf")), None)
        if not dxf:
            check("%s 產出 DXF" % calc_id, False)
            continue

        case = {"schema": "civil-case/1", "title": calc_id,
                "quantities": {"model": model, "values": ex}}
        cpath = tmp / (calc_id + "_case.json")
        cpath.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")

        rc, detail = _run_takeoff(dxf, cpath)
        check("%s 對帳相符" % calc_id, rc == 0, detail)

    print("[3] 「未對帳」不可被當成「相符」（退出碼 2）")
    ex = (cat.get("drainage_network") or {}).get("example")
    if ex:
        res = DS.generate("drainage_network", ex, publish=False, out_dir=str(tmp / "nw"))
        dxf = next((f["path"] for f in res.get("files", []) if f["path"].endswith(".dxf")), None)
        case = {"schema": "civil-case/1", "title": "nw",
                "quantities": {"model": "drainage_network", "values": ex}}
        cpath = tmp / "nw_case.json"
        cpath.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        rc, detail = _run_takeoff(dxf, cpath)
        check("排水網路回未對帳（exit 2）", rc == 2, "實際 exit=%d" % rc)

    print("[4] 邊坡：坡面斜長語意對帳（原本是假對帳，一律印無法對帳）")
    ex = (cat.get("slope_stability") or {}).get("example")
    if ex:
        res = DS.generate("slope_stability", ex, publish=False, out_dir=str(tmp / "slope"))
        dxf = next((f["path"] for f in res.get("files", []) if f["path"].endswith(".dxf")), None)
        case = {"schema": "civil-case/1", "title": "slope",
                "quantities": {"model": "slope", "values": ex}}
        cpath = tmp / "slope_case.json"
        cpath.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        rc, detail = _run_takeoff(dxf, cpath)
        check("邊坡對帳相符", rc == 0, detail)

    print("")
    if FAILS:
        print("[失敗] %d 項" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("[完成] 圖／數對帳自測全數通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
