import json, sys
d = json.load(open(r"D:\公司案件.AI\docs\_sc_test\script2_stdout.json", encoding="utf-8"))
insp = [x for x in d if isinstance(x, dict) and "bodies" in x and isinstance(x.get("bodies"), list) and x.get("bodies") and isinstance(x["bodies"][0], dict)]
for k, snap in enumerate(insp):
    print("--- inspect", k)
    for b in snap["bodies"]:
        print("  ", b.get("name"), "vol=", b.get("volume_mm3"), "faces=", b.get("faces"), "visible=", b.get("visible"))
