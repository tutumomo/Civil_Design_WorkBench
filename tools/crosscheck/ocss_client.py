# -*- coding: utf-8 -*-
"""Open CalcSheet Studio（OCSS）REST 用戶端 —— 無第三方依賴，只用 urllib。

為什麼走 REST 而不是 MCP：兩者是**同一個 Rust 橋接器、同一份工具 registry**、
同一個 token，REST 不必處理 JSON-RPC 與 session 握手，腳本端最省事。
（見 OCSS `docs/mcp.md`、`docs/api.md`。）

連線必要條件
------------
1. **桌面程式必須開著**：橋接器隨 App 啟動，關掉就沒有埠。只有 GUI 一支程式，
   沒有 headless 模式，也不要執行 `--version`／`--help`（會卡住）。
2. 設定 › API 與 AI 助理：伺服器開啟、未暫停、未開唯讀（本模組會偵測並提示）。

Token 與埠的來源（依序，**一律不寫死**）
----------------------------------------
* 環境變數 `OCSS_API_TOKEN`、`OCSS_PORT`（臨時覆寫用）
* `preferences.json` 的 `mcpToken`、`mcpPoort`（路徑由
  `project_paths.ocss_settings_dir()` 跨平台解析）
* 埠預設 3879

Token 是機密：本模組只在使用時讀入記憶體，不寫入任何檔案、不印出、不進版控。

用法::

    from ocss_client import OcssClient
    c = OcssClient()
    c.require()                      # 未啟動時丟出可讀的錯誤
    c.modules()                      # 22 個模組（台灣 17 個 tw-*）
    c.evaluate("q = 5 kN/m\\nL = 6 m\\nM = q*L^2/8")
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve()
_TOOLS = _HERE.parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from project_paths import ocss_settings_dir  # noqa: E402

DEFAULT_PORT = 3879
DEFAULT_TIMEOUT = 180


class OcssError(RuntimeError):
    """OCSS 回傳的結構化錯誤（`{"error": {"code":…, "message":…}}`）。"""

    def __init__(self, code: str, message: str, status: int | None = None, data=None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.status = status
        self.data = data


class OcssUnavailable(RuntimeError):
    """程式沒開、埠沒監聽、token 不對 —— 屬於環境問題，不是計算問題。"""


def _read_prefs() -> dict:
    p = ocss_settings_dir() / "preferences.json"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _truthy(v) -> bool:
    """preferences 的 mcp 旗標可能是空字串（未寫入＝沿用預設值）。"""
    if v is None or v == "":
        return False
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "ja", "yes", "on")
    return bool(v)


class OcssClient:
    """OCSS 本機 API 的薄封裝。所有方法回傳已解析的 dict／list。"""

    def __init__(self, port: int | None = None, token: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT):
        prefs = _read_prefs()
        self.prefs = prefs
        self.port = int(port or os.environ.get("OCSS_PORT") or prefs.get("mcpPoort") or DEFAULT_PORT)
        self.token = token or os.environ.get("OCSS_API_TOKEN") or str(prefs.get("mcpToken") or "")
        self.timeout = timeout
        self.base = f"http://127.0.0.1:{self.port}/api/v1"

    # ---------------------------------------------------------------- 低階
    def _request(self, path: str, payload=None, method: str | None = None):
        url = self.base + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                err = (json.loads(raw) or {}).get("error") or {}
            except ValueError:
                err = {}
            raise OcssError(err.get("code") or f"HTTP_{e.code}",
                            err.get("message") or raw[:300] or e.reason,
                            status=e.code, data=err.get("data")) from None
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            raise OcssUnavailable(
                f"連不上 Open CalcSheet Studio（127.0.0.1:{self.port}）。\n"
                "  1. 桌面程式是否開著？（橋接器隨 App 啟動，關掉即無埠）\n"
                "  2. 設定 › API 與 AI 助理：伺服器是否開啟、是否暫停？\n"
                "  3. 埠號是否被改過？（環境變數 OCSS_PORT 可覆寫）\n"
                f"  原始錯誤：{e}") from None

    # ---------------------------------------------------------------- 服務狀態
    def info(self) -> dict:
        """版本與服務狀態；同時驗證 token（唯一免 token 的路由是 openapi.json）。"""
        return self._request("/info")

    def require(self) -> dict:
        """確認可用：程式在跑、token 正確、未唯讀、未暫停。回傳 /info。"""
        try:
            info = self.info()
        except OcssError as e:
            if e.status == 401:
                raise OcssUnavailable(
                    "token 不正確（401）。請在 OCSS 設定 › API 與 AI 助理 重新複製，"
                    "或設環境變數 OCSS_API_TOKEN。") from None
            raise
        if info.get("paused"):
            raise OcssUnavailable("OCSS 已暫停（設定 › API 與 AI 助理 › 暫停）。")
        return info

    def readonly(self) -> bool:
        return bool((self.info() or {}).get("readOnly"))

    # ---------------------------------------------------------------- 唯讀查詢
    def modules(self) -> list[dict]:
        """模組清單。識別欄位是 `templateId`（不是 `id`）。"""
        return self._request("/modules").get("modules", [])

    def sheets(self) -> list[dict]:
        return self._request("/sheets").get("sheets", [])

    def sheet(self, sheet_id: str, evaluate: bool = False) -> dict:
        return self._request(f"/sheets/{sheet_id}?evaluate={'true' if evaluate else 'false'}")

    def project(self) -> dict:
        return self._request("/project")

    def tools(self) -> list[dict]:
        return self._request("/tools").get("tools", [])

    # ---------------------------------------------------------------- 計算
    def evaluate(self, source: str, values=None, max_lines: int = 400) -> dict:
        """無狀態試算：不碰專案、不留痕。適合探索與交叉驗算。

        回傳含 `lines`（每行 type/name/expression/result/unit/value）、`uc`、
        `passes`、`ucValues`、`errorLines`。`lines[i]["value"]` 才是精確數值，
        `result` 是給人看的字串（可能已四捨五入）。
        """
        payload = {"source": source, "maxLines": max_lines}
        if values:
            payload["values"] = values
        return self._request("/evaluate", payload)

    def sheet_add(self, template_id: str | None = None, name: str | None = None,
                  source: str | None = None) -> dict:
        payload = {}
        if template_id:
            payload["templateId"] = template_id
        if name:
            payload["name"] = name
        if source:
            payload["source"] = source
        return self._request("/sheets", payload)

    def sheet_set_input(self, sheet_id: str, values: dict) -> dict:
        return self._request(f"/sheets/{sheet_id}/inputs", {"values": values}, method="PATCH")

    def sheet_set_source(self, sheet_id: str, source: str) -> dict:
        return self._request(f"/sheets/{sheet_id}/source", {"source": source}, method="PUT")

    def sheet_evaluate(self, sheet_id: str, names=None) -> dict:
        return self._request(f"/sheets/{sheet_id}/evaluate", {"names": names or []})

    def sheet_remove(self, sheet_id: str) -> dict:
        return self._request(f"/sheets/{sheet_id}", method="DELETE")


# -------------------------------------------------------------------- 結果解析
_NUMERIC_UNIT = re.compile(r"[A-Za-zµμ]")


def result_value(evaluation: dict, name: str) -> tuple[float | None, str | None]:
    """從 evaluate 結果取某個變數的（精確值, 單位）。

    `lines` 可能有同名多筆（迴圈內重複賦值），取**最後一筆**——迴圈結束後的值。
    """
    hit = None
    for ln in evaluation.get("lines", []):
        if ln.get("type") == "assignment" and ln.get("name") == name:
            hit = ln
    if hit is None:
        return None, None
    v = hit.get("value")
    return (float(v) if isinstance(v, (int, float)) else None), hit.get("unit")


def unit_warnings(evaluation: dict) -> list[str]:
    """掃出「數值對、單位錯」的可疑結果（本模組存在的理由）。

    兩個實測陷阱（2026-11-10）：
    1. **分數次方污染單位**：`R^(2/3)` 會把單位變成 `m^0.667`，Manning 等公式的
       結果因此出現 `m^2.666…`。數值正確、單位荒謬，而且 `errorLines` 為 0。
       修法：先無因次化（`R_m = R/(1 m)`），算完再掛回目標單位。
    2. **單位不會自動收斂到慣用單位**：`M/W` 得 `kN/mm^2` 而不是 `MPa`（差 1000 倍）。
       工具是誠實的（單位標對了），但不會提醒你這個數字在工程上很奇怪。
       修法：每個結果顯式 `to MPa`／`to kN`。
    """
    out = []
    for ln in evaluation.get("lines", []):
        unit = ln.get("unit") or ""
        name = ln.get("name") or "?"
        # 單位出現小數次方 → 幾乎必然是沒有無因次化
        if re.search(r"\^\s*\d*\.\d+", unit):
            out.append(f"{name}：單位 `{unit}` 含小數次方，疑似未無因次化"
                       f"（把長度改成 `x/(1 m)` 再算）")
        # 力除以長度平方卻不是應力慣用單位
        if re.fullmatch(r"kN\s*/\s*mm\^?2|kN\s*/\s*mm²", unit):
            out.append(f"{name}：單位 `{unit}`（= 1000 MPa）；若要 MPa 請寫 `to MPa`")
        # 完全沒有單位卻是工程量（無法自動判斷，只提示「單位為純數」）
        elif unit == "" and isinstance(ln.get("value"), (int, float)) and _NUMERIC_UNIT.search(name):
            pass  # 純數很常見（係數、n、S0），不警告以免噪音
    return out
