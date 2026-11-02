import urllib.request, urllib.parse, re, ssl, json, time, http.cookiejar

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj),
                                 urllib.request.HTTPSHandler(context=ctx))
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
       "Accept-Language": "zh-TW,zh;q=0.9"}

def get(url):
    return op.open(urllib.request.Request(url, headers=HDR), timeout=40).read().decode("utf-8", "replace")

def clean(x):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", x, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

url = "https://law.moa.gov.tw/LawQuery.aspx"
h = get(url)
d = {}
for m in re.finditer(r"<input[^>]*type=\"hidden\"[^>]*>", h):
    tag = m.group(0)
    n = re.search(r"name=\"([^\"]+)\"", tag); v = re.search(r"value=\"([^\"]*)\"", tag)
    if n: d[n.group(1)] = v.group(1) if v else ""
d["ctl00$cp_content$txtKW"] = "水土保持技術規範"
d["ctl00$cp_content$btnQuery"] = "查詢"
req = urllib.request.Request(url, data=urllib.parse.urlencode(d).encode("utf-8"),
                             headers={**HDR, "Content-Type": "application/x-www-form-urlencoded"})
res = op.open(req, timeout=45).read().decode("utf-8", "replace")
open(r"D:\公司案件.AI\tools\solidcraft\_dev\moa_list.html", "w", encoding="utf-8").write(res)

i = res.find("水土保持技術規範")
print("=== raw context")
print(res[max(0, i-1500):i+400])
