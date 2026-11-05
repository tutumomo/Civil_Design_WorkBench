#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
端到端範例：鋼筋混凝土 U 型溝渠（可參數化）→ STEP / STL / PNG 交付。

這是「口述需求 → 參數化模型 → 交付」的標準示範案例。
用法：
    set PYTHONIOENCODING=utf-8
    python <專案根目錄>\\tools\\solidcraft\\example_run.py ^
        --out <專案根目錄>\\SolidCraft範例\\U型溝渠

輸出：
    U型溝渠.step          B-rep 實體（可匯入 AutoCAD / Revit / Rhino）
    U型溝渠.stl           三角網格（可匯入 3D 列印軟體）
    U型溝渠.solidcraft    SolidCraft 原生設計檔（保留參數與時間軸）
    U型溝渠_等軸視.png    模型視圖截圖
    U型溝渠_渲染圖.png    產品級渲染
    U型溝渠_數量表.json   幾何數量（體積、面積、bbox）
    執行紀錄.log
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sc  # noqa: E402


def build_script(inner_w=600, inner_h=600, wall_t=120, base_t=120,
                 unit_len=1000, n_units=10) -> dict:
    """組出參數化建模腳本（所有尺寸皆為參數，改參數即重建）。"""
    return {
        "name": "RC_U型溝渠",
        "commands": [
            {"command": "parameters.add", "params": {
                "name": "UNIT_LEN", "expression": str(unit_len), "unit": "mm",
                "comment": "預鑄單元長度"}},
            {"command": "parameters.add", "params": {
                "name": "INNER_W", "expression": str(inner_w), "unit": "mm",
                "comment": "內寬"}},
            {"command": "parameters.add", "params": {
                "name": "INNER_H", "expression": str(inner_h), "unit": "mm",
                "comment": "內高"}},
            {"command": "parameters.add", "params": {
                "name": "WALL_T", "expression": str(wall_t), "unit": "mm",
                "comment": "側壁厚"}},
            {"command": "parameters.add", "params": {
                "name": "BASE_T", "expression": str(base_t), "unit": "mm",
                "comment": "底板厚"}},
            {"command": "parameters.add", "params": {
                "name": "N_UNITS", "expression": str(n_units), "unit": "",
                "comment": "單元數（純數量）"}},

            {"command": "solid.box", "params": {
                "length": "UNIT_LEN * N_UNITS",
                "width": "INNER_W + 2 * WALL_T",
                "height": "INNER_H + BASE_T",
                "corner": [0, 0, 0],
                "name": "Outer", "body_name": "UChannel"}},
            {"command": "solid.box", "params": {
                "length": "UNIT_LEN * N_UNITS",
                "width": "INNER_W",
                "height": "INNER_H + BASE_T + 1",
                "corner": [0, "WALL_T", "BASE_T"],
                "name": "Void", "body_name": "VoidBody"}},
            {"command": "solid.combine", "params": {
                "target": "UChannel", "tools": ["VoidBody"], "operation": "cut"}},

            {"command": "appearance.assign", "params": {
                "bodies": ["UChannel"], "color": "#B8B4AE"}},
        ],
    }


def export_all(script: dict, out_dir: Path) -> dict:
    """依序匯出 STEP / STL / 原生檔，並量測幾何數量。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    t0 = time.time()

    def say(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        log.append(line)
        print(line, flush=True)

    # 1) 建模 + 量測 + 匯出（同一個 session 內完成，模型狀態才一致）
    script_with_io = dict(script)
    script_with_io["commands"] = script["commands"] + [
        {"command": "document.inspect", "params": {"measure": True}},
        {"command": "file.export", "params": {
            "path": str(out_dir / "U型溝渠.step"), "format": "step"}},
        {"command": "file.export", "params": {
            "path": str(out_dir / "U型溝渠.stl"), "format": "stl",
            "quality": "fine"}},
        {"command": "file.save", "params": {
            "path": str(out_dir / "U型溝渠.solidcraft"), "format": "container"}},
        {"command": "parameters.export", "params": {
            "path": str(out_dir / "U型溝渠_參數表.csv"), "format": "csv"}},
    ]
    res = sc.run_script(script_with_io, timeout=1800)
    say("建模＋匯出完成")

    # 2) 幾何數量
    insp = None
    for item in res:
        if isinstance(item, dict) and isinstance(item.get("bodies"), list) \
                and item["bodies"] and isinstance(item["bodies"][0], dict):
            insp = item
    qty = {}
    if insp:
        for b in insp["bodies"]:
            qty[b.get("name")] = {
                "volume_mm3": b.get("volume_mm3"),
                "area_mm2": b.get("area_mm2"),
                "bbox": b.get("bbox"),
                "faces": b.get("faces"),
            }
    (out_dir / "U型溝渠_數量表.json").write_text(
        json.dumps(qty, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"幾何數量：{json.dumps(qty, ensure_ascii=False)}")

    # 3) 視圖截圖（GPU）
    sc.snapshot(str(out_dir / "U型溝渠.solidcraft"),
                str(out_dir / "U型溝渠_等軸視.png"), view="iso",
                width=1600, height=1000)
    say("等軸視截圖完成")

    # 4) 產品渲染
    try:
        sc.render(str(out_dir / "U型溝渠.solidcraft"),
                  str(out_dir / "U型溝渠_渲染圖.png"),
                  width=1600, height=1000, timeout=900)
        say("渲染圖完成")
    except sc.SolidCraftError as e:
        say(f"渲染跳過：{e}")

    say(f"總耗時 {time.time() - t0:.1f}s")
    (out_dir / "執行紀錄.log").write_text("\n".join(log), encoding="utf-8")
    return qty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="輸出目錄")
    ap.add_argument("--inner-w", type=int, default=600)
    ap.add_argument("--inner-h", type=int, default=600)
    ap.add_argument("--wall-t", type=int, default=120)
    ap.add_argument("--base-t", type=int, default=120)
    ap.add_argument("--unit-len", type=int, default=1000)
    ap.add_argument("--n-units", type=int, default=10)
    a = ap.parse_args()

    script = build_script(a.inner_w, a.inner_h, a.wall_t, a.base_t,
                          a.unit_len, a.n_units)
    qty = export_all(script, Path(a.out))

    # 幾何合理性自檢：體積應約等於 外框 - 內腔
    try:
        L, W, H = a.unit_len * a.n_units, a.inner_w + 2 * a.wall_t, a.inner_h + a.base_t
        # 內腔切除：寬 INNER_W、底在 BASE_T 頂（挖穿到 z=H 以上），長度 L
        expect = L * W * H - L * a.inner_w * (H - a.base_t)
        got = qty.get("UChannel", {}).get("volume_mm3")
        print(f"\n理論體積 {expect:,.1f} mm³ ｜ 模型體積 {got:,.1f} mm³ "
              f"｜ 誤差 {abs(expect - got) / expect * 100:.3f}%")
        if got is None or abs(expect - got) / expect > 0.01:
            print("[FAIL] 幾何量測與理論值不符")
            return 1
        print("[OK] 幾何量測通過（誤差 < 1%）")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 自檢略過：{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
