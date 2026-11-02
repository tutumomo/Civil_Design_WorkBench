"""List candidate attachment links in downloaded HTML pages (probe helper)."""
import html
import re
import sys

for path in sys.argv[1:]:
    t = open(path, encoding="utf-8", errors="replace").read()
    ti = re.search(r"<title>(.*?)</title>", t, re.S)
    print("==", path, ti.group(1).strip() if ti else "")
    for m in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
        h, x = html.unescape(m.group(1)), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if re.search(r"(pdf|\.doc|\.odt|download|filesys|attach|file)", h, re.I):
            print(h, "|", re.sub(r"\s+", " ", x)[:90])
