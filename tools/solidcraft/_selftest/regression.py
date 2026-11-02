#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SolidCraft 工具鏈回歸驗證：確認所有產出可重現、幾何量測通過。"""
import subprocess, sys, json, os
import os
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from project_paths import solidcraft_cli  # noqa: E402

CLI = solidcraft_cli() or ""
BUILD = str(Path(__file__).resolve().parents[1] / "sc_build.py")
PY = sys.executable

CASES = [
    ("U型溝", str(Path(__file__).resolve().parents[1] / "examples" / "U型溝.json"),
     ["--param", "B=400 mm"], 104000000, "560x1000x400"),
    ("擋土牆", str(Path(__file__).resolve().parents[1] / "examples" / "擋土牆.json"),
     [], 1978527378.44, "2000x600x3400"),
    ("沉頭孔平板", str(Path(__file__).resolve().parents[1] / "examples" / "沉頭孔平板.json"),
     [], None, None),
]

OUT = Path(__file__).resolve().parent / "regression"
fails = []
for name, script, params, vol, bbox in CASES:
    out = OUT / name
    cmd = [PY, BUILD, script, "--out-dir", str(out), "--name", name,
           "--expect-volume", str(vol), "--tol", "0.01"] if vol else \
          [PY, BUILD, script, "--out-dir", str(out), "--name", name]
    if bbox:
        cmd += ["--expect-bbox", bbox]
    cmd += params
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p.returncode == 0
    print(f"[{'OK ' if ok else 'FAIL'}] {name}  rc={p.returncode}")
    if not ok:
        fails.append(name)
        print(p.stdout[-1500:])
        print(p.stderr[-800:])

# 重開既有設計檔確認可繼續編輯（參數化回溯）
design = OUT / "擋土牆" / "擋土牆.solidcraft"
probe = OUT / "reopen_probe.json"
if design.exists():
    # 改一個參數再重建，證明設計檔保留參數與特徵樹
    probe.write_text(json.dumps({"commands": [
        {"command": "parameters.change", "params": {"name": "H", "expression": "3500 mm"}},
        {"command": "document.inspect", "params": {"measure": True}},
    ]}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([CLI, "run", "--in", str(design), str(probe),
                        "--json-out", str(OUT / "reopen.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p.returncode == 0
    print(f"[{'OK ' if ok else 'FAIL'}] 重開設計檔並改參數重建  rc={p.returncode}")
    if not ok:
        fails.append("reopen")
        print(p.stderr[-800:])
    else:
        M = json.loads((OUT / "reopen.json").read_text(encoding="utf-8"))
        # run --in 產出的 json-out 是量測物件本體（bodies 在頂層）
        if isinstance(M, dict) and M.get("bodies"):
            insp = M
        else:
            insp = None
            for it in M:
                if isinstance(it, dict) and isinstance(it.get("bodies"), list) \
                        and it["bodies"] and isinstance(it["bodies"][0], dict):
                    insp = it
        if not insp:
            fails.append("reopen_parse")
            print("      [FAIL] 無法解析重建結果")
        else:
            b = insp["bodies"][0]
            h = b["bbox"]["max"][2]
            print(f"      改 H=3500 mm 後外框高 = {h:.1f} mm（預期 3500）、"
                  f"體積 = {b['volume_mm3']:,.0f} mm³、面 {b['faces']}")
            if abs(h - 3500) > 1:
                fails.append("reopen_value")
                print("      [FAIL] 重建後高度不符")

print("\n=== 回歸結果 ===")
print("全部通過" if not fails else f"失敗：{fails}")
sys.exit(0 if not fails else 1)
