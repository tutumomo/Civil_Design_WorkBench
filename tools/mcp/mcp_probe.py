"""單一 MCP 伺服器的 stdio 探測器：啟動 → initialize → tools/list → 收工。

用法：
    python tools/mcp/mcp_probe.py <名稱> <閒置逾時秒> <command> [args...]

輸出（stdout 一行 JSON）：
    {"ok": true, "server": {...}, "tools": ["a","b"], "count": 2, "stderr_tail": [...]}

用途：註冊完之後證明「真的接得起來」，而不是只看設定檔寫對了。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time


def probe(name: str, idle_s: float, cmd: list[str]) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, bufsize=0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "name": name, "error": f"無法啟動：{type(exc).__name__}: {exc}"}

    inbox: list[dict] = []
    errs: list[str] = []

    def pump_out():
        for raw in iter(proc.stdout.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                inbox.append(json.loads(line.decode("utf-8", "replace")))
            except Exception:  # noqa: BLE001
                continue

    def pump_err():
        for raw in iter(proc.stderr.readline, b""):
            errs.append(raw.decode("utf-8", "replace").rstrip())

    threading.Thread(target=pump_out, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()

    def send(obj):
        proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def await_id(mid, timeout):
        end = time.time() + timeout
        while time.time() < end:
            for msg in list(inbox):
                if msg.get("id") == mid:
                    inbox.remove(msg)
                    return msg
            if proc.poll() is not None:
                return None
            time.sleep(0.05)
        return None

    result: dict = {"ok": False, "name": name}
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "civil-probe", "version": "1.0"}}})
        init = await_id(1, idle_s)
        if not init or "result" not in init:
            result["error"] = "initialize 無回應（程序可能立即結束或不是 MCP 伺服器）"
            return result
        result["server_info"] = (init["result"] or {}).get("serverInfo")
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = await_id(2, idle_s)
        if not listed:
            result["error"] = "tools/list 無回應"
            return result
        if "error" in listed:
            result["error"] = f"tools/list error: {listed['error']}"
            return result
        tools = [t.get("name") for t in (listed["result"] or {}).get("tools", [])]
        result.update({"ok": True, "tools": tools, "count": len(tools)})
        return result
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        result["stderr_tail"] = [e for e in errs if e.strip()][-4:]
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(2)
    nm, idle = sys.argv[1], float(sys.argv[2])
    probe(nm, idle, sys.argv[3:])
