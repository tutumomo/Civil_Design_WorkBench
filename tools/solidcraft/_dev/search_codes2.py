import urllib.request, urllib.parse, re, ssl, json
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, data=None):
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
           "Accept-Language": "zh-TW,zh;q=0.9"}
    if data:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
        data = data.encode("utf-8")
    req = urllib.request.Request(url, headers=hdr, data=data)
    return urllib.request.urlopen(req, timeout=40, context=ctx).read().decode("utf-8", "replace")

def clean(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

# 內政部法規資料庫搜尋
try:
    h = fetch("https://glrs.moi.gov.tw/GLA/LawQuery.aspx?txtType=Html&txtWord=%E6%93%94%E5%9C%9F%E7%AF%89")
    c = clean(h)
    print("=== glrs 擋土牆搜尋")
    for kw in ["建築物基礎", "耐震", "擋土牆", "基礎工程"]:
        for m in re.finditer(kw, c):
            print("  ...", c[max(0,m.start()-120):m.start()+160])
            break
except Exception as e:
    print("glrs ERR", e)

print()
# Bing 精準查規範全名
for q in ["\"建築物基礎暨設計規範\" 擋土牆 傾覆 滑動 承重",
          "\"公路工程設計規範\" 擋土牆 穩定分析",
          "site:glrs.moi.gov.tw 建築物耐震設計規範"]:
    print("=" * 6, q)
    try:
        h = fetch("https://www.bing.com/search?q=" + urllib.parse.quote(q))
        for blk in re.findall(r"(<li class=\"b_algo\".*?</li>)", h, flags=re.S)[:6]:
            print("  *", clean(blk)[:320])
    except Exception as e:
        print("  ERR", e)
    print()
