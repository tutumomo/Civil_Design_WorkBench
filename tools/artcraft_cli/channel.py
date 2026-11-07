"""ArtCraft 控制通道客戶端（macOS／Linux 沒有 `*-cli` 時的替代路徑）。

背景（踩坑紀錄 §AM）：
    Windows 上 ArtCraft 會隨附 `cadcraft-cli.exe`／`gridcraft-cli.exe`／`wordcraft-cli.exe`
    等 headless CLI；**macOS 的 `/Applications/<App>.app` 內只有 GUI 可執行檔，沒有 `-cli`**，
    直接執行 `CADCraft convert a.dxf b.dwg` 會直接開 GUI 視窗然後結束，指令根本沒跑。

    macOS 上 ArtCraft 改走 **JSON-lines 控制通道**：以 `--control <port>` 啟動 App，
    再對 `127.0.0.1:<port>` 逐行送 JSON。這個模組把兩者接起來，讓本專案既有的
    `tools/acad/acc.py`（cadcraft-cli convert／run）、`tools/boq/boq_build.py`
    （gridcraft-cli run／eval／check）、`tools/report/make_report.py`
    （wordcraft-cli convert）在 macOS 上照樣運作。

三個 App 的認證方式不同（實測 2026-11-07）：
    * CADCraft  : 每個請求 body 帶 `token`；token 檔 `~/.cache/cadcraft-control-<port>.token`
    * GridCraft : 連線後先送一次 `{"id":0,"method":"auth","params":{"token":...}}`；
                  token 檔 `~/.cache/gridcraft/control-<port>.token`
    * WordCraft : 每個請求 body 帶 `key`；
                  key 檔 `~/Library/Application Support/WordCraft/control-key.local-<port>`

用法（一般人不會直接呼叫，是給 `tools/artcraft_cli/bin/*-cli` 殼層用）::

    from artcraft_cli.channel import App
    with App("gridcraft") as app:
        print(app.call("engine.commands", {"search": "file"}))
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

#: App key → (顯示名稱, /Applications 內的 App 名)
APPS = {
    "cadcraft": "CADCraft",
    "gridcraft": "GridCraft",
    "wordcraft": "WordCraft",
}

#: 需要先送 auth 握手（其餘是每個請求帶 token／key）
TOKEN_AUTH = {"gridcraft"}


class ControlError(RuntimeError):
    """控制通道錯誤（連不上、未授權、App 回覆失敗）。"""


def app_binary(app: str) -> Path:
    """App 的 macOS 執行檔路徑。"""
    name = APPS.get(app, app.capitalize())
    return Path(f"/Applications/{name}.app/Contents/MacOS/{name}")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def find_token(app: str, port: int) -> str | None:
    """找 App 啟動時寫下的控制通道憑證（token 或 key）。

    各 App 寫法不同：
        `~/.cache/<app>/control-<port>.token`（GridCraft）
        `~/.cache/<app>-control-<port>.token`（CADCraft）
        `~/Library/Application Support/<App>/control-key.local-<port>`（WordCraft）
    """
    home = Path.home()
    name = APPS.get(app, app.capitalize())
    cands = [
        home / ".cache" / app / f"control-{port}.token",
        home / ".cache" / f"{app}-control-{port}.token",
        home / "Library" / "Application Support" / name / f"control-key.local-{port}",
    ]
    for p in cands:
        if p.is_file():
            try:
                v = p.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if v:
                return v
    return None


def _connect(port: int, timeout: float = 2.0) -> socket.socket | None:
    try:
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError:
        return None


def running_control_port(app: str) -> int | None:
    """已有一個帶控制通道的 App 實例在跑時，回傳它的 port（單例 App 不可重複開）。"""
    name = APPS.get(app, app.capitalize())
    pids = subprocess.run(["pgrep", "-f", f"/Applications/{name}.app/Contents/MacOS/{name}"],
                          capture_output=True, text=True).stdout.split()
    for pid in pids:
        if not pid.strip().isdigit():
            continue
        out = subprocess.run(["lsof", "-nP", "-p", pid.strip(), "-iTCP", "-sTCP:LISTEN"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "127.0.0.1:" in line:
                port = line.rsplit(":", 1)[-1].split()[0]
                if port.isdigit():
                    return int(port)
    return None


class App:
    """一個 App 的控制通道連線（context manager）。"""

    def __init__(self, app: str, port: int | None = None, wait: float = 40.0,
                 keep: bool = False, log_dir: Path | None = None):
        self.app = app
        self.port = port or _free_port()
        self.wait = wait
        self.keep = keep
        self.log_dir = log_dir
        self.proc: subprocess.Popen | None = None
        self.sock: socket.socket | None = None
        self.f = None
        self._id = 0
        self.token: str | None = None
        self.auth_field: str | None = None   # "token" 或 "key"

    # ------------------------------------------------------------------ 生命週期
    def __enter__(self) -> "App":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> "App":
        binary = app_binary(self.app)
        if not binary.is_file():
            raise ControlError(f"{binary} 不存在（{APPS.get(self.app)} 未安裝）")
        existing = running_control_port(self.app)
        if existing:
            self.port = existing
        else:
            log_dir = self.log_dir or Path(tempfile_dir()) / "artcraft_cli"
            log_dir.mkdir(parents=True, exist_ok=True)
            logf = open(log_dir / f"{self.app}-{self.port}.log", "w", encoding="utf-8")
            self.proc = subprocess.Popen([str(binary), "--control", str(self.port)],
                                         stdout=logf, stderr=subprocess.STDOUT)
        deadline = time.time() + self.wait
        sock = None
        while time.time() < deadline:
            time.sleep(0.3)
            sock = _connect(self.port)
            if sock:
                break
            if self.proc and self.proc.poll() is not None:
                raise ControlError(f"{self.app} 啟動即結束（rc={self.proc.returncode}），"
                                   f"見 {self.app}-{self.port}.log")
        if not sock:
            self.close()
            raise ControlError(f"{self.app} 控制通道在 {self.wait:.0f} 秒內沒有起來")
        self.sock = sock
        self.sock.settimeout(180)
        self.f = sock.makefile("rwb")
        self._setup_auth()
        return self

    def _setup_auth(self) -> None:
        """取得憑證並完成必要的握手。"""
        token = find_token(self.app, self.port)
        if self.app in TOKEN_AUTH:
            if not token:
                raise ControlError(f"{self.app} 需要 token 卻找不到 "
                                   f"（~/.cache/{self.app}/control-{self.port}.token）")
            self.auth_field = None
            r = self.call("auth", {"token": token}, raw_id=0)
            if not r.get("ok"):
                raise ControlError(f"{self.app} auth 失敗：{r.get('error')}")
        elif self.app == "wordcraft":
            if not token:
                raise ControlError("WordCraft 需要 control key 卻找不到"
                                   "（~/Library/Application Support/WordCraft/）")
            self.auth_field = "key"
            self.token = token
        else:  # cadcraft：每個請求帶 token
            self.auth_field = "token"
            self.token = token

    def close(self) -> None:
        try:
            if self.f:
                self.f.close()
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.f = self.sock = None
        if self.proc and not self.keep:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    # ------------------------------------------------------------------ 呼叫
    def call(self, method: str, params: dict | None = None, raw_id: int | None = None) -> dict:
        """送一個請求，回傳 App 的完整回覆 dict。"""
        if self.f is None:
            raise ControlError("尚未連線")
        self._id = raw_id if raw_id is not None else self._id + 1
        req: dict = {"id": self._id, "method": method}
        if params is not None:
            req["params"] = params
        if self.auth_field and self.token:
            req[self.auth_field] = self.token
        self.f.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise ControlError("控制通道被 App 關閉")
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ControlError(f"非 JSON 回覆：{line[:200]!r}") from exc

    def execute(self, command: str, params: dict | None = None) -> dict:
        """執行一條引擎指令（engine.execute）。失敗即丟出。"""
        r = self.call("engine.execute", {"command": command, "params": params or {}})
        if not r.get("ok"):
            raise ControlError(f"{command} 失敗：{r.get('error')}")
        return r.get("result")


def tempfile_dir() -> str:
    """暫存目錄（AGENTS.md §1.1：機械產物放 _temp）。"""
    root = os.environ.get("CIVIL_AI_ROOT")
    if root:
        p = Path(root) / "_temp" / "artcraft_cli"
    else:
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "tools" / "project_paths.py").is_file():
                p = parent / "_temp" / "artcraft_cli"
                break
        else:
            p = Path.home() / ".cache" / "civil-artcraft-cli"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)
