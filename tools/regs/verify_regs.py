"""Print the opening text of each fetched code so its title / edition can be eyeballed.

usage: verify_regs.py [ID ...] [--n CHARS] [--grep REGEX]
"""
import json
import re
import sys
import os
from pathlib import Path

OUT = Path(os.environ.get("CIVIL_AI_REGS_DIR")
           or (Path(__file__).resolve().parents[2] / "data" / "法規"))
args = sys.argv[1:]
n = 260
grep = None
if "--n" in args:
    i = args.index("--n"); n = int(args[i + 1]); del args[i:i + 2]
if "--grep" in args:
    i = args.index("--grep"); grep = re.compile(args[i + 1]); del args[i:i + 2]
man = json.loads((OUT / "_regs_manifest.json").read_text(encoding="utf-8"))
for sid, rec in man.items():
    if args and sid not in args:
        continue
    txt = OUT / rec.get("files", {}).get("text", "")
    if not txt.is_file():
        print("==", sid, "NO TEXT"); continue
    t = txt.read_text(encoding="utf-8")
    print("==", sid, rec["name"])
    if grep:
        for m in list(grep.finditer(t))[:6]:
            print("   ...", re.sub(r"\s+", " ", t[max(0, m.start() - 60):m.end() + 80]))
    else:
        print("  ", re.sub(r"\s+", " ", t[:n]))
