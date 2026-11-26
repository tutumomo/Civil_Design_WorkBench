"""把所有本機 MCP 伺服器一次註冊到各 AI 客戶端（可 --dry-run、可只做某幾台）。

存在理由：這台機器同時裝了 Claude Code、Claude Desktop、Gemini CLI、Antigravity、
OpenCode、Codex、VS Code，加上本專案的 `.mcp.json`；每個客戶端的設定檔格式、
鍵名與伺服器命名慣例都不同，手改必然漏掉某一個。這支程式把它們收斂成一份清單。

用法：
    python tools/mcp/register_all.py --dry-run            看會改哪些檔（不寫入）
    python tools/mcp/register_all.py                      寫入（每個檔先備份）
    python tools/mcp/register_all.py --apply              同上（明確表態）
    python tools/mcp/register_all.py --only blender regs  只處理指定伺服器
    python tools/mcp/register_all.py --verify             註冊後逐台啟動並列出工具數

設計原則：
- 只動本清單列出的伺服器條目，其他伺服器原封不動。
- 每個被修改的檔案先備份成 `<檔名>.bak_mcp_<時間戳>`。
- 寫回時沿用原檔的縮排與換行格式（JSON）。
- 內容含 API key 也不印出來，只報「有幾個伺服器」。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", ""))
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

sys.path.insert(0, str(ROOT / "tools"))
try:
    from project_paths import ingetrazo_mcp, opencadstudio_exe, python_exe  # noqa: E402
except Exception:  # noqa: BLE001
    def python_exe() -> str:
        return sys.executable

    def ingetrazo_mcp() -> str | None:
        return None

    def opencadstudio_exe() -> str | None:
        return None

# ---------------------------------------------------------------- 伺服器清單
AUTOCAD_EXE = HOME / "mcp" / "autocad-mcp-pro" / ".venv" / "Scripts" / "autocad-mcp.exe"
ARTCRAFT_PY = HOME / "mcp" / "artcraft-gateway" / ".venv" / "Scripts" / "python.exe"
ARTCRAFT_SERVER = HOME / "mcp" / "artcraft-gateway" / "server.py"
ARTCRAFT_ROOT = Path(r"C:\Program\ArtCraft")


def _py_args(script: Path) -> list[str]:
    return ["-E", "-P", "-X", "utf8", str(script)]


def python_candidates() -> list[str]:
    """可用的 Python：環境變數 → 本專案 venv → Orkas 內建 → 系統。"""
    cands = [
        os.environ.get("CIVIL_AI_PYTHON", ""),
        python_exe(),
        str(ROOT / "tools" / "mcp" / ".venv" / "Scripts" / "python.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) /
            r"Programs\orkas\resources\runtime\python\win32-x64\python\python.exe"),
        shutil.which("python") or "",
    ]
    return [c for c in cands if c]


def pick_python() -> str:
    """挑第一個真的 import 得到 mcp 的 Python（blender／regs 伺服器要靠它）。"""
    for exe in python_candidates():
        if not Path(exe).is_file():
            continue
        try:
            r = subprocess.run([exe, "-c", "import mcp, sys; print(sys.version.split()[0])"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return exe
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("找不到裝有 mcp 套件的 Python，請先 pip install mcp")


#: 需要「裝有 mcp 套件的 Python」才能跑的伺服器；`--only` 沒選到它們時不必找 Python
PY_SERVERS = ("regs", "blender")


def build_servers(only: list[str] | None = None) -> dict[str, dict]:
    need_py = not only or any(x in PY_SERVERS for x in only)
    py = pick_python() if need_py else "<未選用：不需 Python>"
    iz_exe = ingetrazo_mcp() or "ingetrazo-mcp"
    iz_base = re.split(r"[\\/]", iz_exe)[-1].lower()  # 跨平台取檔名（Windows 路徑在 POSIX 不會被拆）
    servers: dict[str, dict] = {
        "regs": {
            "command": py,
            "args": _py_args(ROOT / "tools" / "regs" / "regs_server.py") + ["--mcp"],
            "env": {"CIVIL_AI_ROOT": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        },
        "blender": {
            "command": py,
            "args": _py_args(ROOT / "tools" / "blender" / "blender_mcp.py"),
            "env": {"CIVIL_AI_ROOT": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        },
        "autocad": {
            "command": str(AUTOCAD_EXE),
            "args": [],
            "env": {
                "AUTOCAD_MCP_BACKEND": "ezdxf",
                "ALLOWED_PATHS": str(ROOT),
                "TOOL_PROFILE": "full",
                "PYTHONIOENCODING": "utf-8",
            },
        },
        "artcraft": {
            "command": str(ARTCRAFT_PY),
            "args": [str(ARTCRAFT_SERVER)],
            "env": {
                "ARTCRAFT_ROOT": str(ARTCRAFT_ROOT),
                "ARTCRAFT_WORK_DIR": str(ROOT / "out"),
                "PYTHONIOENCODING": "utf-8",
            },
        },
        "ingetrazo": {
            # 只是 stdio → 127.0.0.1:4763 的橋；GUI 開著＋AI Bridge 啟動才能用。
            "command": iz_exe,
            "args": [] if iz_base.startswith("ingetrazo-mcp") else ["--mcp"],
            "env": {"PYTHONIOENCODING": "utf-8"},
        },
        "opencadstudio": {
            # stdio 橋，連到「執行中」的 Open CAD Studio 視窗（不需 token）；GUI 沒開就沒有工具。
            # 2026-11-26 起改採上游版，執行檔一律經 project_paths 解析（只認上游版）。
            "command": opencadstudio_exe() or "opencadstudio",
            "args": ["--mcp"],
            "env": {},
        },
    }
    return servers


# ---------------------------------------------------------------- 客戶端轉接
# (顯示名, 路徑, 伺服器表鍵, 是否加 type/stdio, 額外欄位)
JSON_CLIENTS = [
    ("Claude Code（使用者）", HOME / ".claude.json", "mcpServers", True, {}),
    ("Claude Desktop", APPDATA / "Claude" / "claude_desktop_config.json", "mcpServers", False, {}),
    ("Gemini CLI", HOME / ".gemini" / "settings.json", "mcpServers", False, {}),
    ("Antigravity", HOME / ".gemini" / "antigravity" / "mcp_config.json", "mcpServers", False, {}),
    ("OpenCode", HOME / ".config" / "opencode" / "opencode.json", "mcp", None, {}),
    ("VS Code（本專案）", ROOT / ".vscode" / "mcp.json", "servers", False, {"__vscode_inputs": True}),
    ("本專案 .mcp.json", ROOT / ".mcp.json", "mcpServers", False, {}),
]
CODEX = HOME / ".codex" / "config.toml"


def entry_for(client_flavour, spec: dict) -> dict:
    """把統一規格轉成該客戶端的條目形狀。"""
    if client_flavour == "opencode":
        return {"type": "local", "command": [spec["command"]] + list(spec["args"]),
                "enabled": True, "environment": spec.get("env", {})}
    entry: dict = {"command": spec["command"], "args": list(spec["args"])}
    if spec.get("env"):
        entry["env"] = dict(spec["env"])
    if spec.get("type_stdio"):
        entry["type"] = "stdio"
    return entry


def backup(p: Path) -> Path:
    b = p.with_name(p.name + f".bak_mcp_{STAMP}")
    shutil.copy2(p, b)
    return b


def write_json_like(p: Path, raw: str, data: dict) -> None:
    m = re.search(r"\n([ \t]+)\S", raw)
    indent = m.group(1) if m else 2
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    if "\r\n" in raw:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))


def register_json(name: str, p: Path, key: str, type_stdio: bool, opts: dict,
                  servers: dict[str, dict], apply: bool) -> dict:
    if not p.is_file():
        return {"client": name, "path": str(p), "status": "skip（檔案不存在）"}
    raw = p.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"client": name, "path": str(p), "status": f"skip（JSON 解析失敗：{exc}）"}

    table = data.setdefault(key, {})
    changed = []
    for sname, spec in servers.items():
        spec = dict(spec, type_stdio=type_stdio)
        if opts.get("__vscode_inputs"):
            new = {"type": "stdio", "command": spec["command"], "args": list(spec["args"])}
            if spec.get("env"):
                new["env"] = dict(spec["env"])
        else:
            new = entry_for("opencode" if key == "mcp" else "default", spec)
        if table.get(sname) != new:
            table[sname] = new
            changed.append(sname)

    if not changed:
        return {"client": name, "path": str(p), "status": "已是目標狀態"}
    if apply:
        b = backup(p)
        write_json_like(p, raw, data)
        return {"client": name, "path": str(p), "status": "updated", "changed": changed,
                "backup": b.name, "total": len(table)}
    return {"client": name, "path": str(p), "status": "dry-run", "changed": changed, "total": len(table)}


def toml_block(sname: str, spec: dict) -> str:
    q = chr(39)
    args = ", ".join(f"{q}{a}{q}" for a in spec["args"])
    lines = [f"[mcp_servers.{sname}]",
             f"command = {q}{spec['command']}{q}",
             f"args = [{args}]"]
    if spec.get("env"):
        lines.append(f"\n[mcp_servers.{sname}.env]")
        for k, v in spec["env"].items():
            lines.append(f"{k} = {q}{v}{q}")
    return "\n".join(lines) + "\n"


def replace_toml_section(text: str, name: str, block: str) -> str:
    """換掉 `[mcp_servers.<name>]` 及其子表（含 .env），其他段落原樣保留。"""
    lines = text.splitlines(keepends=True)
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"[mcp_servers.{name}]":
            start = idx
            break
    new_lines = block.splitlines(keepends=True)
    if start is None:
        tail = "" if text.endswith("\n") else "\n"
        return text + tail + "\n" + block
    end = start + 1
    while end < len(lines):
        head = lines[end].strip()
        if head.startswith("[") and not head.startswith(f"[mcp_servers.{name}"):
            break
        end += 1
    return "".join(lines[:start] + new_lines + lines[end:])


def register_codex(servers: dict[str, dict], apply: bool) -> dict:
    if not CODEX.is_file():
        return {"client": "Codex", "path": str(CODEX), "status": "skip（檔案不存在）"}
    raw = CODEX.read_text(encoding="utf-8")
    text = raw
    changed = []
    for sname, spec in servers.items():
        new = replace_toml_section(text, sname, toml_block(sname, spec))
        if new != text:
            text = new
            changed.append(sname)
    if not changed:
        return {"client": "Codex", "path": str(CODEX), "status": "已是目標狀態"}
    if apply:
        b = backup(CODEX)
        CODEX.write_text(text, encoding="utf-8")
        return {"client": "Codex", "path": str(CODEX), "status": "updated",
                "changed": changed, "backup": b.name}
    return {"client": "Codex", "path": str(CODEX), "status": "dry-run", "changed": changed}


def enable_project_servers(servers: dict[str, dict], apply: bool) -> dict:
    """Claude Code 專案層：把 .mcp.json 內的伺服器列入已啟用、並清掉停用名單。"""
    p = ROOT / ".claude" / "settings.local.json"
    if not p.is_file():
        return {"client": "Claude Code（專案）", "path": str(p), "status": "skip（檔案不存在）"}
    raw = p.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    # 用聯集：`--only ingetrazo` 不可把其他已啟用的伺服器一併關掉。
    names = sorted(set(data.get("enabledMcpjsonServers") or []) | set(servers))
    before = (sorted(data.get("enabledMcpjsonServers") or []), list(data.get("disabledMcpjsonServers") or []))
    data["enabledMcpjsonServers"] = names
    data["disabledMcpjsonServers"] = [x for x in (data.get("disabledMcpjsonServers") or [])
                                      if x not in names]
    if before == (names, data["disabledMcpjsonServers"]):
        return {"client": "Claude Code（專案）", "path": str(p), "status": "已是目標狀態"}
    if apply:
        b = backup(p)
        write_json_like(p, raw, data)
        return {"client": "Claude Code（專案）", "path": str(p), "status": "updated",
                "enabled": names, "disabled": data["disabledMcpjsonServers"], "backup": b.name}
    return {"client": "Claude Code（專案）", "path": str(p), "status": "dry-run",
            "enabled": names, "disabled": data["disabledMcpjsonServers"]}


# ---------------------------------------------------------------- 驗證
def verify(servers: dict[str, dict], idle: float = 90.0) -> list[dict]:
    """逐台啟動伺服器：initialize → tools/list，回報工具數與前幾個名稱。"""
    probe = Path(__file__).resolve().parent / "mcp_probe.py"
    results = []
    for sname, spec in servers.items():
        cmd = [spec["command"]] + list(spec["args"])
        env = {**os.environ, **spec.get("env", {})}
        try:
            r = subprocess.run([sys.executable, str(probe), sname, str(idle)] + cmd,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=idle + 60)
            payload = json.loads(r.stdout.strip() or "{}")
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        results.append({**payload, "server": sname})
    return results


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="一次註冊本專案全部 MCP 伺服器")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會做什麼")
    ap.add_argument("--apply", action="store_true",
                    help="實際寫入（本來就是預設；保留給文件與腳本明確表態）")
    ap.add_argument("--only", nargs="*", default=None, help="只處理指定伺服器")
    ap.add_argument("--verify", action="store_true", help="註冊後逐台啟動驗證")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args()
    apply = not a.dry_run

    servers = build_servers(a.only)
    if a.only:
        unknown = [x for x in a.only if x not in servers]
        if unknown:
            print("未知伺服器：", ", ".join(unknown), "（可用：", ", ".join(servers), "）")
            return 2
        servers = {k: servers[k] for k in a.only}

    report = [register_json(name, p, key, bool(type_stdio), opts, servers, apply)
              for name, p, key, type_stdio, opts in JSON_CLIENTS]
    report.append(register_codex(servers, apply))
    report.append(enable_project_servers(servers, apply))

    if a.verify:
        report.append({"client": "verify", "results": verify(servers)})

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"{'＝' * 62}\nMCP 註冊{'（試跑，未寫入）' if not apply else ''}\n{'＝' * 62}")
    for row in report:
        if row.get("client") == "verify":
            print("\n啟動驗證：")
            for v in row["results"]:
                mark = "OK  " if v.get("ok") else "FAIL"
                tools = v.get("tools") or []
                extra = "" if v.get("ok") else f"  <- {v.get('error')}"
                print(f"  [{mark}] {v['server']:<9} tools={len(tools)} "
                      f"{', '.join(tools[:6])}{extra}")
            continue
        detail = ""
        if row.get("changed"):
            detail = "  變更：" + ", ".join(row["changed"])
        elif row.get("enabled") is not None:
            detail = f"  啟用：{', '.join(row['enabled'])}；停用：{row.get('disabled') or '無'}"
        print(f"  {row['status']:<14} {row['client']:<20} {row['path']}{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
