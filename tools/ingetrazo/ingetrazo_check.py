"""IngeTrazo MCP 橋接檢查：exe 在不在、橋開不開、五支工具在不在、文件讀不讀得到。

用法：
    python tools/ingetrazo/ingetrazo_check.py            # 只檢查 exe／port／tools/list
    python tools/ingetrazo/ingetrazo_check.py --call     # 另外實際呼叫 query_model（需 GUI＋橋）

離開碼：0＝工具清單正常（--call 時連線呼叫也成功）；1＝有問題。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from project_paths import ingetrazo_home, ingetrazo_mcp  # noqa: E402

EXPECTED = ["run_python", "query_model", "screenshot", "undo", "redo"]
PROBE = TOOLS_DIR / "mcp" / "mcp_probe.py"
HOST = os.environ.get("INGETRAZO_AI_HOST", "").strip() or "127.0.0.1"
PORT = int(os.environ.get("INGETRAZO_AI_PORT", "4763"))


def bridge_listening(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def probe_tools(exe: str, idle: float = 30.0) -> dict:
    """用既有的 mcp_probe.py 做 initialize＋tools/list（不碰橋）。"""
    r = subprocess.run([sys.executable, str(PROBE), "ingetrazo", str(idle), exe],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=idle + 60)
    try:
        return json.loads(r.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": f"mcp_probe 輸出無法解析：{r.stdout[-300:]}"}


class Client:
    """最小 stdio JSON-RPC 客戶端（只為檢查而寫，不進產線）。"""

    def __init__(self, exe: str):
        self.proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.inbox: list[dict] = []
        self.errs: list[str] = []
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()

    def _out(self):
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.strip()
            if line:
                try:
                    self.inbox.append(json.loads(line.decode("utf-8", "replace")))
                except json.JSONDecodeError:
                    pass

    def _err(self):
        for raw in iter(self.proc.stderr.readline, b""):
            self.errs.append(raw.decode("utf-8", "replace").rstrip())

    def send(self, obj: dict):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def wait(self, mid: int, timeout: float) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            for msg in list(self.inbox):
                if msg.get("id") == mid:
                    self.inbox.remove(msg)
                    return msg
            if self.proc.poll() is not None:
                return None
            time.sleep(0.05)
        return None

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def call_query_model(exe: str) -> dict:
    c = Client(exe)
    try:
        c.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "ingetrazo-check", "version": "1.0"}}})
        if not c.wait(1, 30):
            return {"ok": False, "error": "initialize 無回應"}
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        c.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "query_model", "arguments": {}}})
        msg = c.wait(2, 180)
        if not msg:
            return {"ok": False, "error": "query_model 無回應（橋沒開？）"}
        if "error" in msg:
            return {"ok": False, "error": msg["error"]}
        res = msg.get("result") or {}
        text = "".join(p.get("text", "") for p in res.get("content") or []
                       if isinstance(p, dict) and p.get("type") == "text")
        return {"ok": not res.get("isError"), "text": text[:1200],
                "stderr_tail": [e for e in c.errs if e.strip()][-3:]}
    finally:
        c.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="檢查 IngeTrazo 的 MCP 橋接")
    ap.add_argument("--call", action="store_true", help="實際呼叫 query_model（需 GUI＋AI Bridge）")
    a = ap.parse_args(argv)

    home, exe = ingetrazo_home(), ingetrazo_mcp()
    print(f"IngeTrazo 安裝 : {home or '—（找不到；設定 INGETRAZO_HOME）'}")
    print(f"MCP 伺服器    : {exe or '—（找不到；設定 INGETRAZO_MCP）'}")
    if not exe or not Path(exe).is_file():
        print("結果          : FAIL（沒有 ingetrazo-mcp，先確認安裝路徑）")
        return 1

    listening = bridge_listening()
    print(f"AI Bridge     : {HOST}:{PORT} → {'listening' if listening else '未監聽'}"
          f"{'' if listening else '（開 IngeTrazo → 開文件 → 擴充功能 ▸ AI Bridge (MCP)）'}")

    probe = probe_tools(exe)
    tools = probe.get("tools") or []
    print(f"tools/list    : {'OK' if probe.get('ok') else 'FAIL'}  {len(tools)} 支"
          f"{'：' + ', '.join(tools) if tools else ''}")
    if not probe.get("ok"):
        print(f"  錯誤        : {probe.get('error')}")
        return 1
    missing = [t for t in EXPECTED if t not in tools]
    if missing:
        print(f"  缺少工具    : {', '.join(missing)}（版本可能不同，請核對本指引 §4.1）")

    if a.call:
        if not listening:
            print("query_model   : SKIP（橋未監聽，無法呼叫）")
            return 1
        res = call_query_model(exe)
        print(f"query_model   : {'OK' if res.get('ok') else 'FAIL'}")
        if res.get("text"):
            print("  " + res["text"].replace("\n", "\n  ")[:1200])
        if res.get("error"):
            print(f"  錯誤        : {res['error']}")
        if not res.get("ok"):
            return 1

    print("結果          : OK（橋接伺服器可用；實際建模前仍需 GUI 開文件並啟動 AI Bridge）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
