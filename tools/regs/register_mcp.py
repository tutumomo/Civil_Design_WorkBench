"""Register (or remove) the 規範查詢台 MCP server 「regs」 in the local AI clients' config files.

usage:
  register_mcp.py --dry-run     show what would change
  register_mcp.py               add 「regs」 to every client config that exists (backup first)
  register_mcp.py --remove      take it out again (backup first)

Each file is backed up as <file>.bak_regs_<timestamp> before writing. Only the 「regs」 entry is
touched; config contents (which can hold API keys) are never printed.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_paths import python_exe  # noqa: E402

PY = python_exe()
SERVER = str(Path(__file__).resolve().parent / "regs_server.py")
ARGS = ["-E", "-P", "-X", "utf8", SERVER, "--mcp"]
NAME = "regs"
H, APPDATA = Path.home(), Path(os.environ.get("APPDATA", ""))
CLAUDE_EXE = shutil.which("claude")

# client -> (config file, key holding the server table, entry)
JSON_CLIENTS = {
    "Claude Code": (H / ".claude.json", "mcpServers", {"type": "stdio", "command": PY, "args": ARGS, "env": {}}),
    "Claude Desktop": (APPDATA / "Claude" / "claude_desktop_config.json", "mcpServers", {"command": PY, "args": ARGS}),
    "Gemini CLI": (H / ".gemini" / "settings.json", "mcpServers", {"command": PY, "args": ARGS}),
    "Antigravity": (H / ".gemini" / "antigravity" / "mcp_config.json", "mcpServers", {"command": PY, "args": ARGS}),
    "OpenCode": (H / ".config" / "opencode" / "opencode.json", "mcp", {"type": "local", "command": [PY] + ARGS, "enabled": True}),
}
CODEX = H / ".codex" / "config.toml"
CODEX_BLOCK = (f"\n[mcp_servers.{NAME}]\n"
               f"command = '{PY}'\n"
               f"args = [{', '.join(f'{chr(39)}{x}{chr(39)}' for x in ARGS)}]\n"  # TOML literal strings: no escapes
               f"tool_timeout_sec = 60\n")
CODEX_RE = re.compile(rf"\n?^\[mcp_servers\.{NAME}\]\n(?:^(?!\[).*\n?)*", re.M)


def backup(p, stamp):
    b = p.with_name(p.name + f".bak_regs_{stamp}")
    shutil.copy2(p, b)
    return b


def write_like(p, raw, d):
    """Rewrite JSON keeping the file's own indent and line endings."""
    m = re.search(r"\n( +|\t+)\S", raw)
    indent = m.group(1) if m else 2
    text = json.dumps(d, ensure_ascii=False, indent=indent) + "\n"
    if "\r\n" in raw:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))


def claude_cli(remove, entry):
    """Claude Code rewrites ~/.claude.json while running, so let its own CLI make the change."""
    cmd = [CLAUDE_EXE, "mcp", "remove", "--scope", "user", NAME] if remove else \
          [CLAUDE_EXE, "mcp", "add-json", "--scope", "user", NAME, json.dumps(entry, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bad = 0

    for client, (p, key, entry) in JSON_CLIENTS.items():
        if not p.exists():
            print(f"- {client:15s} 沒有設定檔，略過")
            continue
        try:
            raw = p.read_text(encoding="utf-8-sig")
            d = json.loads(raw)
        except ValueError as e:
            print(f"! {client:15s} 設定檔不是合法 JSON，不動它（{e.__class__.__name__}）")
            bad += 1
            continue
        table = d.setdefault(key, {})
        has = NAME in table
        if a.remove and not has or not a.remove and has and table[NAME] == entry:
            print(f"= {client:15s} 已是目標狀態")
            continue
        act = "移除" if a.remove else ("更新" if has else "加入")
        if a.dry_run:
            print(f"? {client:15s} 將{act} {p}")
            continue
        b = backup(p, stamp)
        if client == "Claude Code" and CLAUDE_EXE:
            ok, msg = claude_cli(a.remove, entry)
            if not ok:
                print(f"! {client:15s} claude mcp 指令失敗：{msg[0]}")
                bad += 1
                continue
        else:
            if a.remove:
                del table[NAME]
            else:
                table[NAME] = entry
            write_like(p, raw, d)
        now = json.loads(p.read_text(encoding="utf-8-sig")).get(key, {})  # reopen check
        if (NAME in now) == a.remove:
            print(f"! {client:15s} 寫入後回讀不符")
            bad += 1
            continue
        print(f"+ {client:15s} 已{act}（備份 {b.name}）")

    if CODEX.exists():
        t = CODEX.read_text(encoding="utf-8")
        m = CODEX_RE.search(t)
        has, same = bool(m), bool(m) and m.group(0).strip() == CODEX_BLOCK.strip()
        act = "移除" if a.remove else ("更新" if has else "加入")
        if a.remove and not has or not a.remove and same:
            print(f"= {'Codex':15s} 已是目標狀態")
        elif a.dry_run:
            print(f"? {'Codex':15s} 將{act} {CODEX}")
        else:
            b = backup(CODEX, stamp)
            t = CODEX_RE.sub("\n", t).rstrip("\n") + "\n"
            if not a.remove:
                t += CODEX_BLOCK
            CODEX.write_text(t, encoding="utf-8")
            print(f"+ {'Codex':15s} 已{act}（備份 {b.name}）")
    else:
        print(f"- {'Codex':15s} 沒有設定檔，略過")
    print("完成。已開著的 AI 程式要重新啟動才會載入。" if not a.dry_run else "（試跑，未寫入）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
