import re
p = str(Path(__file__).resolve().parent / "swc_full.txt")
c = open(p, encoding="utf-8").read()
lines = [x.strip() for x in c.split("\n")]
lines = [x for x in lines if x]

def show(a, b, label):
    print("#" * 6, label)
    for i in range(a, min(b, len(lines))):
        t = lines[i].replace("&nbsp;", " ").replace("&amp;", "&")
        t = re.sub(r"\s{2,}", " ", t)
        print(f"[{i}] {t}")
    print()

show(1155, 1215, "第二二節 擋土牆")
show(570, 600, "護坡/擋土牆 種類（前段）")
show(640, 660, "坡面保護")
show(835, 850, "邊坡排水及植生放寬")
show(1415, 1430, "背填要求")
