from pathlib import Path
import os
import sys
# -*- coding: utf-8 -*-
"""批次把「公司土木工程常用元件」的 DWG 轉成 DXF，供盤點解析。
輸出名以序號命名（避開中文路徑問題），對照表寫 manifest.json。
"""
import json, os, sys, traceback

R = str(Path(__file__).resolve().parents[1])
SRC = os.environ.get("CIVIL_AI_STD_BLOCKS")
if not SRC:
    sys.exit("請設定 CIVIL_AI_STD_BLOCKS 指向公司標準元件 DWG 資料夾（不隨 repo 附）")
OUT = os.path.join(R, "_ref", "components_dxf")
sys.path.insert(0, os.path.join(R, "tools", "acad"))
import acc

files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".dwg"))
os.makedirs(OUT, exist_ok=True)
manifest = []
for i, name in enumerate(files, 1):
    key = "C%03d" % i
    dst = os.path.join(OUT, key + ".dxf")
    rec = {"key": key, "file": name}
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        rec["status"] = "skip"
    else:
        try:
            acc.to_dxf(os.path.join(SRC, name), dst)
            rec["status"] = "ok" if os.path.exists(dst) and os.path.getsize(dst) > 1000 else "empty"
        except BaseException as ex:
            rec["status"] = "fail"
            rec["error"] = str(ex)[:300]
    rec["size"] = os.path.getsize(dst) if os.path.exists(dst) else 0
    manifest.append(rec)
    print("%s %-6s %s" % (key, rec["status"], name), flush=True)
    json.dump(manifest, open(os.path.join(R, "_ref", "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
print("DONE", len(manifest))
