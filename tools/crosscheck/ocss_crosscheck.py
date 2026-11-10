# -*- coding: utf-8 -*-
"""Open CalcSheet Studio 交叉驗算 CLI。

用途：把「本專案確定性引擎」與「OCSS 計算書」對同一個題目各算一次，比對數值與單位。
兩套算法彼此獨立，吻合度本身就是交付品質的證據；不吻合時先查單位，再查輸入。

子命令
------
    probe                     連線檢查、版本、模組清單（台灣 tw-* 與歐規分組）
    eval   --expr "..."       無狀態試算一段計算書（不碰專案），並檢查單位陷阱
    eval   --file x.cpd       同上，來源改成檔案
    checks [--only 關鍵字]    跑 tools/crosscheck/checks/*.json 的對照案例
    register-mcp [--apply]    把 MCP 連線寫進專案 .mcp.json（預設只預覽，token 不印出）

前提：OCSS 桌面程式必須開著（REST 橋接器隨 App 啟動）。未開啟時給出可讀的提示，
不會卡住；因此**不納入** `tools/selftest/regression.py` 的預設流程。

退出碼：0 成功／全部在容差內；1 至少一項不符或連線失敗；2 參數或資料錯誤。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[2]
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from ocss_client import OcssClient, OcssError, OcssUnavailable, result_value, unit_warnings  # noqa: E402

CHECKS_DIR = _HERE.parent / "checks"


def _out(msg: str = "") -> None:
    print(msg)


# --------------------------------------------------------------------- probe
def cmd_probe(c: OcssClient) -> int:
    info = c.require()
    _out(f"OCSS {info.get('version')}　{info.get('rest')}")
    _out(f"唯讀：{'是' if info.get('readOnly') else '否'}　暫停：{'是' if info.get('paused') else '否'}")
    mods = c.modules()
    tw = [m for m in mods if str(m.get("templateId", "")).startswith("tw-")]
    other = [m for m in mods if not str(m.get("templateId", "")).startswith("tw-")]
    _out(f"模組 {len(mods)} 個（台灣 {len(tw)}、其他 {len(other)}）")
    _out("")
    for m in tw:
        _out(f"  {str(m.get('templateId')).ljust(26)} {str(m.get('status', '')).ljust(12)} {m.get('name', '')}")
    if other:
        _out("  其他：" + "、".join(str(m.get("templateId")) for m in other))
    return 0


# ---------------------------------------------------------------------- eval
def _print_eval(b: dict) -> None:
    _out(f"errorLines={b.get('errorLines')}　truncated={b.get('truncated')}")
    for ln in b.get("lines", []):
        t = ln.get("type")
        if t == "assignment":
            _out(f"  {str(ln.get('name')).ljust(14)} = {ln.get('result')}"
                 f"   [{ln.get('unit') or '純數'}]")
        elif t == "text":
            _out(f"  。{ln.get('text') or ln.get('expression') or ''}")
        elif t == "heading":
            _out(f"  # {(ln.get('text') or ln.get('expression') or '').strip()}")
    if b.get("uc") is not None:
        _out(f"  UC = {b.get('uc')}　判定：{'合格' if b.get('passes') else '不合格'}")
    warns = unit_warnings(b)
    if warns:
        _out("")
        _out("⚠ 單位檢查：")
        for w in warns:
            _out("  · " + w)


def cmd_eval(c: OcssClient, source: str) -> int:
    c.require()
    b = c.evaluate(source)
    _print_eval(b)
    return 0 if not b.get("errorLines") else 1


# -------------------------------------------------------------------- checks
def _load_ref(spec: dict):
    """載入本專案引擎並呼叫；回傳（值, 單位）。"""
    mod_path = (ROOT / spec["module"]).resolve()
    if not mod_path.is_file():
        raise SystemExit(f"找不到對照引擎：{mod_path}")
    s = importlib.util.spec_from_file_location("_ref_" + mod_path.stem, mod_path)
    mod = importlib.util.module_from_spec(s)
    assert s and s.loader
    sys.path.insert(0, str(mod_path.parent))
    s.loader.exec_module(mod)
    fn = getattr(mod, spec["func"], None)
    if fn is None:
        raise SystemExit(f"{mod_path.name} 沒有函式 {spec['func']}")
    val = fn(**{k: v for k, v in (spec.get("args") or {}).items()})
    if isinstance(val, dict):
        val = val[spec["pick"]] if spec.get("pick") else next(iter(val.values()))
    if isinstance(val, (list, tuple)):
        val = val[0]
    return float(val), spec.get("unit")


def _compare(ref: float, got: float, tol: dict) -> tuple[bool, float, float]:
    diff = abs(got - ref)
    rel = diff / abs(ref) if ref else float("inf")
    ok = diff <= tol.get("abs", 0.0) or rel <= tol.get("rel", 0.0)
    return ok, diff, rel


def cmd_checks(c: OcssClient, only: str | None) -> int:
    c.require()
    files = sorted(CHECKS_DIR.glob("*.json"))
    if not files:
        _out(f"（{CHECKS_DIR} 內沒有對照案例）")
        return 2
    total = failed = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for chk in data.get("checks", []):
            total += 1
            name = chk.get("name") or f.stem
            if only and only not in name:
                total -= 1
                continue
            _out(f"\n■ {name}")
            ref_val, ref_unit = _load_ref(chk["reference"])
            b = c.evaluate(chk["ocss"]["source"])
            got_val, got_unit = result_value(b, chk["ocss"]["result"])
            if got_val is None:
                _out(f"  ✗ OCSS 未產生 {chk['ocss']['result']}（errorLines={b.get('errorLines')}）")
                for ln in b.get("lines", []):
                    if ln.get("error"):
                        _out(f"     {ln.get('name')}：{ln.get('error')}")
                failed += 1
                continue
            expect_unit = chk["ocss"].get("expect_unit")
            unit_ok = (expect_unit is None) or (got_unit == expect_unit)
            ok, diff, rel = _compare(ref_val, got_val, chk.get("tolerance") or {"rel": 1e-6})
            _out(f"  本專案 {chk['reference'].get('func')}()  = {ref_val!r} {ref_unit or ''}")
            _out(f"  OCSS   {chk['ocss']['result']:<16} = {got_val!r} {got_unit or ''}")
            _out(f"  差值 {diff:.3e}　相對 {rel:.3e}"
                 f"　容差 rel≤{(chk.get('tolerance') or {}).get('rel', 0)}"
                 f" abs≤{(chk.get('tolerance') or {}).get('abs', 0)}")
            if not unit_ok:
                _out(f"  ✗ 單位不符：預期 {expect_unit}，實得 {got_unit}")
            warns = unit_warnings(b)
            for w in warns:
                _out("  ⚠ " + w)
            if ok and unit_ok:
                _out("  ✓ 通過")
            else:
                _out("  ✗ 不通過" + ("" if unit_ok else "（單位）") + ("" if ok else "（數值）"))
                failed += 1
    _out(f"\n合計 {total} 項，通過 {total - failed}，失敗 {failed}")
    return 0 if failed == 0 else 1


# -------------------------------------------------------------- register-mcp
def cmd_register_mcp(c: OcssClient, apply: bool) -> int:
    """把 OCSS 的 MCP 連線寫進專案根目錄 `.mcp.json`（本機檔，已列入 .gitignore）。

    token 只從 preferences.json／環境變數讀入，**不印出**；預設只預覽，加 --apply 才寫檔，
    寫檔前先備份為 `.mcp.json.bak`，且只動 `open-calcsheet-studio` 這一筆，其餘伺服器原樣保留。
    不需要 OCSS 正在執行，但 token 要先存在（程式至少啟動並開啟 MCP 一次）。
    """
    if not c.token:
        _out("✗ 找不到 MCP token。請先啟動 Open CalcSheet Studio，並在設定中開啟 MCP／API 功能，")
        _out("  再重跑本指令（或以環境變數 OCSS_API_TOKEN 提供）。")
        return 1
    entry = {
        "type": "http",
        "url": f"http://127.0.0.1:{c.port}/mcp",
        "headers": {"Authorization": f"Bearer {c.token}"},
    }
    path = ROOT / ".mcp.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError:
        _out(f"✗ {path} 不是合法 JSON，為避免覆蓋，請先人工修復")
        return 2
    servers = data.setdefault("mcpServers", {})
    state = "更新" if "open-calcsheet-studio" in servers else "新增"
    shown = json.loads(json.dumps(entry))
    shown["headers"]["Authorization"] = "Bearer ****（已隱藏）"
    _out(f"將{state} {path} 的 mcpServers[\"open-calcsheet-studio\"]：")
    _out(json.dumps(shown, ensure_ascii=False, indent=2))
    if not apply:
        _out("\n（預覽；加 --apply 才寫檔）")
        return 0
    if path.is_file():
        bak = path.with_name(path.name + ".bak")
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    servers["open-calcsheet-studio"] = entry
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _out(f"✓ 已寫入 {path}（重啟 Claude Code 後生效；換埠或換 token 後需重跑）")
    return 0


# ----------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Open CalcSheet Studio 交叉驗算")
    ap.add_argument("--port", type=int, help="覆寫埠（預設讀 preferences，再退回 3879）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="連線檢查與模組清單")

    e = sub.add_parser("eval", help="無狀態試算一段計算書")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--expr", help="直接給計算書文字")
    g.add_argument("--file", help="從 .cpd／.txt 讀計算書（UTF-8）")

    k = sub.add_parser("checks", help="跑內建對照案例")
    k.add_argument("--only", help="只跑名稱含此關鍵字的案例")

    r = sub.add_parser("register-mcp", help="把 OCSS 的 MCP 連線寫進 .mcp.json（預設僅預覽）")
    r.add_argument("--apply", action="store_true", help="實際寫檔（先備份 .mcp.json.bak）")

    a = ap.parse_args(argv)
    c = OcssClient(port=a.port)
    try:
        if a.cmd == "register-mcp":
            return cmd_register_mcp(c, a.apply)
        if a.cmd == "probe":
            return cmd_probe(c)
        if a.cmd == "eval":
            src = a.expr if a.expr is not None else Path(a.file).read_text(encoding="utf-8")
            return cmd_eval(c, src)
        if a.cmd == "checks":
            return cmd_checks(c, a.only)
    except OcssUnavailable as ex:
        _out("✗ " + str(ex))
        return 1
    except OcssError as ex:
        _out(f"✗ OCSS 回應錯誤：{ex}")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
