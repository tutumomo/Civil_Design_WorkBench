#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
參數化變體驗證：同一支腳本改參數 → 模型自動重建 → 數量同步變化。

驗證「口述需求只改尺寸」這個核心命題：不需要重畫模型，
只需改參數表就能產出另一個規格的交付。
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc  # noqa: E402
from example_run import build_script  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "out" / "solidcraft_examples" / "U_channel_variants"

VARIANTS = [
    ("內寬600_壁厚120_10單元", dict(inner_w=600, wall_t=120, n_units=10)),
    ("內寬800_壁厚150_12單元", dict(inner_w=800, wall_t=150, n_units=12)),
    ("內寬400_壁厚100_6單元", dict(inner_w=400, wall_t=100, n_units=6)),
]


def volume_of(script: dict) -> tuple[float, dict]:
    s = dict(script)
    s["commands"] = script["commands"] + [
        {"command": "document.inspect", "params": {"measure": True}}]
    res = sc.run_script(s, timeout=600)
    insp = None
    for it in res:
        if isinstance(it, dict) and isinstance(it.get("bodies"), list) \
                and it["bodies"] and isinstance(it["bodies"][0], dict):
            insp = it
    b = insp["bodies"][0]
    return b["volume_mm3"], b


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    ok = True
    for label, kw in VARIANTS:
        script = build_script(**kw)
        vol, b = volume_of(script)
        L = kw["unit_len"] if "unit_len" in kw else 1000
        L = kw.get("unit_len", 1000) * kw["n_units"]
        W = kw["inner_w"] + 2 * kw["wall_t"]
        H = kw.get("inner_h", 600) + kw.get("base_t", 120)
        expect = L * W * H - L * kw["inner_w"] * (H - kw.get("base_t", 120))
        err = abs(expect - vol) / expect * 100
        rows.append({
            "變體": label,
            "長度mm": L, "外寬mm": W, "外高mm": H,
            "模型體積mm3": round(vol, 1),
            "理論體積mm3": round(expect, 1),
            "誤差%": round(err, 4),
            "面數": b.get("faces"),
        })
        print(f"{label}: 模型 {vol:,.0f} / 理論 {expect:,.0f} / 誤差 {err:.4f}%")
        if err > 1.0:
            ok = False
            print("  [FAIL] 誤差 > 1%")

    # 匯出各變體 STEP
    for label, kw in VARIANTS:
        script = build_script(**kw)
        s = dict(script)
        s["commands"] = script["commands"] + [
            {"command": "file.export", "params": {
                "path": str(OUT / f"{label}.step"), "format": "step"}}]
        sc.run_script(s, timeout=600)
        print(f"{label}.step 匯出完成")

    # 變體等軸視
    for label, kw in VARIANTS:
        script = build_script(**kw)
        s = dict(script)
        s["commands"] = script["commands"] + [
            {"command": "file.save", "params": {
                "path": str(OUT / f"{label}.solidcraft"), "format": "container"}}]
        sc.run_script(s, timeout=600)
        sc.snapshot(str(OUT / f"{label}.solidcraft"),
                    str(OUT / f"{label}.png"), view="iso", width=1400, height=900)
        print(f"{label}.png 完成")

    (OUT / "參數化變體對照.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(rows, ensure_ascii=False, indent=2))
    print("[OK] 全部變體通過" if ok else "[FAIL] 有變體誤差過大")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
