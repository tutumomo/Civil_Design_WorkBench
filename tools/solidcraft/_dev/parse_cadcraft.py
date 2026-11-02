import json, re
p = r"C:\Users\tutumomo\.minimax\v2\sessions\2026\10\26\04-37-59-909-session_bXZzX2IwZGNhOTU3NmVjZDQxNTQ5MzQ0YzE2ZGY0NGUwYzI5\reports\tool-outputs\07d2d6788d5a47d6232ac943-b171a813a696885479e7e4d0de7deb116e2c1b1fb2de1679b99865cfcbc90a19.readable.v1.jsonl"
txt = ""
for line in open(p, encoding="utf-8"):
    try:
        o = json.loads(line)
    except Exception:
        continue
    txt += o.get("text", "")
d = json.JSONDecoder()
idx = 0
objs = []
while idx < len(txt):
    # find next {
    s = txt.find("{", idx)
    if s < 0:
        break
    try:
        obj, end = d.raw_decode(txt[s:])
        objs.append(obj)
        idx = s + end
    except Exception:
        idx = s + 1
print("objects:", len(objs))
cmds = None
for o in objs:
    if isinstance(o, dict) and isinstance(o.get("commands"), list):
        cmds = o["commands"]
        break
    if isinstance(o, list) and o and isinstance(o[0], dict) and "id" in o[0]:
        cmds = o
        break
if cmds is None:
    # last resort: regex
    ids = re.findall(r'"id"\s*:\s*"([^"]+)"', txt)
    print("regex ids:", len(set(ids)))
    for i in sorted(set(ids)):
        print(i)
else:
    print("count:", len(cmds))
    for c in cmds:
        if isinstance(c, dict):
            print(c.get("id"), "|", c.get("label") or c.get("title") or c.get("name") or "")
