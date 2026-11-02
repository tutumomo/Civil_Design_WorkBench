"""把 SolidCraft 命令目錄整理成分組摘要（供快速查表）"""
import json, collections, io

P = r"D:\公司案件.AI\docs\solidcraft_commands.txt"
raw = io.open(P, encoding="utf-8").read()
cmds = json.loads(raw)
print(f"命令總數 {len(cmds)}")
groups = collections.defaultdict(list)
for c in cmds:
    groups[c["id"].split(".")[0]].append(c)
for g in sorted(groups, key=lambda k: -len(groups[k])):
    print(f"\n=== {g} ({len(groups[g])}) ===")
    for c in groups[g]:
        ps = (c.get("params") or "").replace("\n", " ")
        print(f"  {c['id']:42s} | {c.get('label','')[:28]:28s} | {ps[:110]}")
