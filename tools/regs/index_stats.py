"""Sanity report on _regs_index.sqlite: missing article numbers (laws), oversized units (codes).

usage: python -E -P -X utf8 index_stats.py [SRC ...] [--big N]
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

DB = str(Path(os.environ.get("CIVIL_AI_REGS_DB")
           or (Path(__file__).resolve().parents[2] / "data" / "法規" / "_regs_index.sqlite")))
args = sys.argv[1:]
big = 0
if "--big" in args:
    i = args.index("--big")
    big = int(args[i + 1])
    del args[i:i + 2]
con = sqlite3.connect(DB)
for sid, kind, name in con.execute("SELECT id, kind, name FROM src ORDER BY id"):
    if args and sid not in args:
        continue
    rows = con.execute("SELECT clause, title, page, part, length(text) FROM unit WHERE src=?", (sid,)).fetchall()
    sizes = sorted((r[4] for r in rows), reverse=True)
    line = f"{sid:14s} {len(rows):5d} units  max={sizes[0] if sizes else 0:,}  total={sum(sizes):,}"
    if kind == "law":
        nums = set()
        for r in rows:                      # 條號可能不是純數字（附錄、章節頁）
            head = str(r[0]).split("-")[0]
            if head.isdigit():
                nums.add(int(head))
        miss = [n for n in range(1, max(nums) + 1) if n not in nums] if nums else []
        line += f"  articles 1..{max(nums) if nums else 0}  missing={miss[:15]}{'…' if len(miss) > 15 else ''}"
    print(line)
    if big:
        for r in sorted(rows, key=lambda r: -r[4])[:big]:
            print(f"    {r[0]:10s} p{r[2]} {r[4]:7,}  {r[1][:30]}  [{r[3][:40]}]")
