"""Print stripped text (keeping <a href>) of an HTML file around a marker (probe helper).

usage: dump_section.py <file> <marker> [length]
"""
import html
import re
import sys

path, marker = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
t = open(path, encoding="utf-8", errors="replace").read()
i = t.find(marker)
if i < 0:
    sys.exit(f"marker not found: {marker}")
s = t[i:i + n]
s = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>', r" [\1] ", s)
s = re.sub(r"<[^>]+>", " ", s)
print(re.sub(r"\s+", " ", html.unescape(s)))
