"""regs MCP 傳輸層煙測：真的把 tools/regs/regs_server.py --mcp 拉起來，走 stdio JSON-RPC 打一輪。

用途：確認「AI 客戶端看得到的那一面」是活的。regq_selftest.py 測的是工具函式本身
（直接呼叫 mcp_call），本檔測的是 stdio 傳輸、initialize 握手、tools/list 與 tools/call
這條真正會被 Claude Code／Codex／DeepSeek Harness 走的路徑；換 Python、換 venv、
改 sys.path 或伺服器啟動就掛掉時，只有這支會紅。

用法：
  .venv/bin/python tools/regs/mcp_smoke.py            # 人看的輸出，全過 exit 0
  .venv/bin/python tools/regs/mcp_smoke.py --json     # 機器讀的 JSON（給其他腳本呼叫）
  .venv/bin/python tools/regs/mcp_smoke.py --help     # 這份說明

檢查項目（任一失敗即 exit 1）：
  1. initialize 回 protocolVersion，serverInfo.name 為 regs
  2. ping 有回空結果
  3. tools/list 含 9 個工具：regs_ask／regs_search／regs_clause／regs_formula／regs_table／
     regs_list／design_list／design_show／design_run
  4. tools/call regs_list 回得出主題（非錯誤）
  5. tools/call design_list 至少列出 20 個計算器
  6. tools/call design_show 對 sediment_basin 回得出輸入範例

退出碼：0 全過；1 有檢查失敗；2 伺服器起不來或超時。
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SERVER = HERE / "regs_server.py"
EXPECTED = ["regs_ask", "regs_search", "regs_clause", "regs_formula", "regs_table",
            "regs_list", "design_list", "design_show", "design_run"]
PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
TIMEOUT = 30.0


class Rpc:
    def __init__(self, python: str):
        env = dict(os.environ, CIVIL_AI_ROOT=str(ROOT), PYTHONIOENCODING="utf-8")
        self.p = subprocess.Popen(
            [python, "-X", "utf8", str(SERVER), "--mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env=env,
        )
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.p.stdout, selectors.EVENT_READ)
        self.n = 0

    def send(self, method: str, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        return None if notify else self.n

    def read(self, want_id: int):
        if not self.sel.select(TIMEOUT):
            raise TimeoutError(f"等 {TIMEOUT:.0f} 秒沒有回應（id={want_id}）")
        line = self.p.stdout.readline()
        if not line:
            err = (self.p.stderr.read() or "").strip().splitlines()[-3:]
            raise RuntimeError("伺服器提前結束：" + " / ".join(err))
        obj = json.loads(line)
        if obj.get("id") != want_id:
            raise RuntimeError(f"回應 id 不符：期望 {want_id}，收到 {obj.get('id')}")
        if "error" in obj:
            raise RuntimeError(f"JSON-RPC 錯誤：{obj['error']}")
        return obj["result"]

    def call(self, name: str, args: dict | None = None) -> tuple[str, bool]:
        mid = self.send("tools/call", {"name": name, "arguments": args or {}})
        res = self.read(mid)
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        return text, bool(res.get("isError"))

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def run(python: str) -> dict:
    rpc = Rpc(python)
    checks, info = [], {}
    try:
        mid = rpc.send("initialize", {"protocolVersion": PROTOCOLS[0], "capabilities": {},
                                      "clientInfo": {"name": "mcp_smoke", "version": "1"}})
        init = rpc.read(mid)
        info["protocolVersion"] = init.get("protocolVersion")
        info["server"] = init.get("serverInfo", {})
        checks.append(("initialize 握手", init.get("protocolVersion") in PROTOCOLS
                       and info["server"].get("name") == "regs",
                       f"{info['protocolVersion']} / {info['server'].get('name')} {info['server'].get('version')}"))

        rpc.send("notifications/initialized", {}, notify=True)

        mid = rpc.send("ping")
        checks.append(("ping", isinstance(rpc.read(mid), dict), ""))

        mid = rpc.send("tools/list")
        tools = [t["name"] for t in rpc.read(mid)["tools"]]
        info["tools"] = tools
        missing = [t for t in EXPECTED if t not in tools]
        checks.append((f"tools/list 9 個工具（實際 {len(tools)}）", not missing,
                       "缺：" + "、".join(missing) if missing else "、".join(tools)))

        text, err = rpc.call("regs_list")
        checks.append(("regs_list 有主題", (not err) and len(text) > 100, f"{len(text)} 字"))

        text, err = rpc.call("design_list")
        n = sum(1 for ln in text.splitlines() if ln.startswith("- "))
        checks.append((f"design_list 計算器數（{n}）", (not err) and n >= 20, ""))

        text, err = rpc.call("design_show", {"calculator": "sediment_basin"})
        ok = (not err) and '"example"' in text
        checks.append(("design_show sediment_basin", ok, "有 example" if ok else text[:80]))
        info["design_calculators"] = n
    finally:
        rpc.close()
    return {"ok": all(c[1] for c in checks), "checks": checks, "info": info}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", default=sys.executable, help="用來啟動伺服的解譯器（預設＝執行本檔的那一個）")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出（給其他腳本或 CI 讀）")
    a = ap.parse_args()

    try:
        rep = run(a.python)
    except Exception as e:  # 起不來／超時：與「檢查失敗」分開，退出碼 2
        print(("MCP 煙測無法完成：" + str(e)) if not a.json else
              json.dumps({"ok": False, "fatal": str(e)}, ensure_ascii=False))
        return 2

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"regs MCP 煙測（{a.python}）")
        for name, ok, note in rep["checks"]:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {note}" if note else ""))
        print("結果：" + ("全部通過" if rep["ok"] else "有檢查失敗"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
