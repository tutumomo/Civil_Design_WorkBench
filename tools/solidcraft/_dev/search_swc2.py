import urllib.request, urllib.parse, re, ssl, http.cookiejar

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj),
                                 urllib.request.HTTPSHandler(context=ctx))
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
       "Accept-Language": "zh-TW,zh;q=0.9"}

def get(url):
    return op.open(urllib.request.Request(url, headers=HDR), timeout=45).read().decode("utf-8", "replace")

def clean(x):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", x, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t\xa0]+", " ", t)

base = "https://law.moa.gov.tw/"
# 先開首頁拿 session
get(base)
for path in ["LawContent.aspx?id=FL014521",
             "LawContent.aspx?id=FL014521&kw=%E6%B0%B4%E5%9C%9F%E4%BF%9D%E6%8C%81%E6%8A%80%E8%A1%93%E8%A6%8F%E7%AF%84"]:
    try:
        b = get(urllib.parse.urljoin(base, path))
    except Exception as e:
        print("ERR", path, e); continue
    c = clean(b)
    print("=" * 10, path, "len", len(c))
    print(c[:700])
    print()
    if len(c) > 3000:
        open(r"D:\公司案件.AI\tools\solidcraft\_dev\swc_full.txt", "w", encoding="utf-8").write(c)
        print("saved.")
        break
