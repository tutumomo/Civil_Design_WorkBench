import urllib.request, urllib.parse, re, ssl, json
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    return urllib.request.urlopen(req, timeout=30, context=ctx).read().decode("utf-8", "replace")

def clean(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

queries = [
    "擋土牆 設計規範 內政部 建築物基礎暨設計規範 擋土牆",
    "公路工程設計規範 擋土牆 重力式 懸臂式 穩定 檢核",
    "建築物耐震設計規範 擋土牆 水平地震力",
]
for q in queries:
    print("=" * 8, q)
    try:
        h = fetch("https://www.bing.com/search?q=" + urllib.parse.quote(q))
        c = clean(h)
        # 取搜尋結果摘要區
        m = re.findall(r"(<li class=\"b_algo\".*?</li>)", h, flags=re.S)
        if m:
            for blk in m[:6]:
                t = clean(blk)
                print("  *", t[:340])
        else:
            print("  ", c[:1600])
    except Exception as e:
        print("  ERR", e)
    print()
