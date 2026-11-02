"""CadCraft Studio 本機 MCP（Streamable HTTP）最小客戶端。
token 不落地：由環境變數 CCS_TOKEN 提供（Studio Hub › Assistants 卡片複製）；埠號自動偵測 Studio 監聽埠，或 CCS_URL 指定。
用法：
  python ccs.py tools                       # 列出工具（含所屬視窗）
  python ccs.py call <tool> '<json args>'   # 呼叫工具，結果印 JSON
  python ccs.py describe <tool>             # 單一工具的參數 schema
"""
import os, sys, json, subprocess, urllib.request

def _url():
    if os.environ.get("CCS_URL"): return os.environ["CCS_URL"]
    ps = ("Get-NetTCPConnection -State Listen | ? { (Get-Process -Id $_.OwningProcess -EA 0).ProcessName -eq 'CadCraft Studio' }"
          " | select -First 1 -Expand LocalPort")
    port = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    if not port: raise SystemExit("找不到 CadCraft Studio 的助理伺服器：請開啟 Studio 並在 app 的 Settings › Assistants 打開助理連線")
    return f"http://127.0.0.1:{port}/mcp"


class Client:
    def __init__(self, token=None, url=None):
        self.url, self.token = url or _url(), token or os.environ.get("CCS_TOKEN")
        if not self.token: raise SystemExit("缺 CCS_TOKEN（Studio Hub › Assistants › Token › Copy）")
        self.sid, self.n = None, 0
        r = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "gongsi-ai", "version": "1"}})
        self.info = r
        self._rpc("notifications/initialized", None, notify=True)

    def _rpc(self, method, params, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None: msg["params"] = params
        if not notify: self.n += 1; msg["id"] = self.n
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "Authorization": "Bearer " + self.token, "MCP-Protocol-Version": "2025-06-18"}
        if self.sid: h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, json.dumps(msg).encode(), h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                self.sid = r.headers.get("Mcp-Session-Id") or self.sid
                body = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
        if notify or not body.strip(): return None
        if body.lstrip().startswith("event:") or body.lstrip().startswith("data:"):   # SSE
            body = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")][-1]
        d = json.loads(body)
        if "error" in d: raise RuntimeError(json.dumps(d["error"], ensure_ascii=False))
        return d["result"]

    def tools(self): return self._rpc("tools/list", {})["tools"]

    def call(self, name, args=None):
        r = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        out = []
        for c in r.get("content", []):
            if c.get("type") == "text":
                try: out.append(json.loads(c["text"]))
                except Exception: out.append(c["text"])
            else: out.append({k: (v if k != "data" else f"<{len(v)} bytes>") for k, v in c.items()})
        if r.get("structuredContent") is not None: out = [r["structuredContent"]]
        if r.get("isError"): raise RuntimeError(json.dumps(out, ensure_ascii=False)[:2000])
        return out[0] if len(out) == 1 else out


if __name__ == "__main__":
    c = Client(); cmd = sys.argv[1] if len(sys.argv) > 1 else "tools"
    if cmd == "tools":
        for t in c.tools(): print(t["name"], "—", (t.get("description") or "")[:150].replace("\n", " "))
    elif cmd == "describe":
        print(json.dumps([t for t in c.tools() if t["name"] == sys.argv[2]], ensure_ascii=False, indent=1))
    elif cmd == "call":
        print(json.dumps(c.call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}), ensure_ascii=False, indent=1))
