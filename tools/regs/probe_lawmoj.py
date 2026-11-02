"""Print the title / latest amendment date of law.moj.gov.tw pcodes, or search by keyword.

usage: probe_lawmoj.py PCODE [PCODE ...]      | probe_lawmoj.py --kw 關鍵字
"""
import html
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def get(url):
    r = subprocess.run(["curl.exe", "-4", "-sS", "-L", "-A", UA, url], capture_output=True)
    return r.stdout.decode("utf-8", "replace")


if sys.argv[1] == "--kw":
    from urllib.parse import quote
    t = get("https://law.moj.gov.tw/Law/LawSearchResult.aspx?ty=ONEBAR&kw=" + quote(sys.argv[2]))
    for m in re.finditer(r'href="[^"]*pcode=([A-Z0-9]+)[^"]*"[^>]*>(.*?)</a>', t, re.S):
        print(m.group(1), re.sub(r"<[^>]+>|\s+", "", html.unescape(m.group(2))))
    sys.exit()

for pc in sys.argv[1:]:
    t = get(f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pc}")
    name = re.search(r'id="hlLawName"[^>]*>(.*?)<', t, re.S)
    date = re.search(r'id="trLNNDate".*?<td[^>]*>(.*?)</td>', t, re.S)
    print(pc, name.group(1).strip() if name else "?", "|",
          re.sub(r"<[^>]+>|\s+", " ", date.group(1)).strip() if date else "?", "| len", len(t))
