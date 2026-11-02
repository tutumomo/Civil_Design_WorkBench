#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SolidCraft CLI 包裝：口述需求 -> 參數化 3D 模型 -> 匯出/渲染 -> 交付。

用法（CLI 層級）：
    python sc.py commands                      # 列出全部命令
    python sc.py exec <command> <json_params>  # 執行單一命令
    python sc.py run <script.json>             # 執行腳本（帶結果）
    python sc.py snapshot <script|design> --out shot.png
    python sc.py render   <script|design> --out image.png

本模組的重點是把「PowerShell 寫檔會變 UTF-16」與「中文路徑」這些坑封裝掉，
讓呼叫端只需要傳 Python dict/list。

設計原則（踩坑紀錄化）：
  - 絕不用 shell 重導向寫 JSON 結果，一律 subprocess + text/encoding='utf-8'。
  - 執行失敗時保留 stderr 原文（SolidCraft 的錯誤訊息格式為
    "error: step N (<command>): <reason>"），這是排查的第一手線索。
  - 參數表與腳本用 ensure_ascii=False 寫出，方便人眼檢查。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_paths import solidcraft_cli  # noqa: E402
from typing import Any, Iterable, Sequence

CLI = solidcraft_cli() or ""


# ---------------------------------------------------------------- 低階執行

def _cli_path() -> str:
    if not Path(CLI).exists():
        raise FileNotFoundError(
            f"找不到 SolidCraft CLI：{CLI}\n"
            "請確認已安裝 SolidCraft（預設 C:\\Program Files\\SolidCraft\\）。"
        )
    return CLI


def run_cli(args: Sequence[str], timeout: int = 900) -> tuple[int, str, str]:
    """執行 solidcraft-cli，回傳 (returncode, stdout, stderr)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [_cli_path(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def write_json(path: str | os.PathLike, obj: Any) -> Path:
    """以 UTF-8 寫 JSON（不用 shell 重導向，避免 UTF-16/BOM）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_json(path: str | os.PathLike) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 高階 API

def exec_command(command: str, params: dict | None = None, timeout: int = 900) -> Any:
    """執行單一命令並解析 JSON 回傳；失敗時拋 SolidCraftError。"""
    params = params or {}
    rc, out, err = run_cli(["exec", command, json.dumps(params, ensure_ascii=False)], timeout)
    if rc != 0:
        raise SolidCraftError(f"{command} 失敗：{err.strip() or out.strip()}")
    return _parse_json(out)


def run_script(script: dict | str, results: bool = True, timeout: int = 1800,
               json_out: str | os.PathLike | None = None) -> Any:
    """執行腳本。script 可為 dict（自動暫存）或 json 路徑。回傳結果 list。"""
    if isinstance(script, dict):
        tmp = Path(os.environ.get("TEMP", ".")) / "solidcraft_run_tmp.json"
        write_json(tmp, script)
        script_path = str(tmp)
    else:
        script_path = str(script)

    args = ["run", script_path]
    if results:
        args.append("--results")
    if json_out:
        args += ["--json-out", str(json_out)]

    rc, out, err = run_cli(args, timeout)
    if rc != 0:
        raise SolidCraftError(f"腳本執行失敗：{err.strip() or out.strip()}")
    if json_out and Path(json_out).exists():
        return read_json(json_out)
    return _parse_json(out) if out.strip() else []


def snapshot(source: str, out_png: str, view: str = "iso", width: int = 1600,
             height: int = 1000, camera: dict | None = None,
             bodies: Iterable[str] = (), timeout: int = 600) -> Path:
    """產生視窗截圖（GPU 渲染的模型視圖），用於成果附圖。"""
    args = ["snapshot", source, "--out", out_png, "--view", view,
            "--width", str(width), "--height", str(height)]
    if camera:
        args += ["--camera", json.dumps(camera)]
    for b in bodies:
        args += ["--body", b]
    rc, out, err = run_cli(args, timeout)
    if rc != 0:
        raise SolidCraftError(f"snapshot 失敗：{err.strip() or out.strip()}")
    return Path(out_png)


def render(source: str, out_png: str, width: int = 1600, height: int = 1000,
           setup: str | None = None, timeout: int = 1200, **opts: Any) -> Path:
    """產品級渲染（CPU raytrace / raster），用於成果主視圖。"""
    args = ["render", source, "--out", out_png,
            "--width", str(width), "--height", str(height),
            "--timeout", str(timeout)]
    if Path(out_png).exists():
        args.append("--overwrite")
    if setup:
        args += ["--setup", setup]
    for k, v in opts.items():
        if v is None:
            continue
        flag = "--" + k.replace("_", "-")
        if isinstance(v, bool):
            if v:
                args.append(flag)
        else:
            args += [flag, str(v)]
    rc, out, err = run_cli(args, timeout + 120)
    if rc != 0:
        raise SolidCraftError(f"render 失敗：{err.strip() or out.strip()}")
    return Path(out_png)


def export(source: str, out_path: str, fmt: str | None = None,
           quality: str | None = None, timeout: int = 900) -> Path:
    """匯出 STEP/STL/OBJ/3MF 等（走 file.export 命令）。"""
    params: dict[str, Any] = {"path": out_path}
    if fmt:
        params["format"] = fmt
    if quality:
        params["quality"] = quality
    # 直接用 exec 不可靠（設計需在同一次 session 內有內容），改以腳本包裝
    script = {"name": "export", "commands": [
        {"command": "file.export", "params": params},
    ]}
    # 若來源是 .solidcraft/.step，用 --in 載入後再執行
    if Path(source).suffix.lower() in (".solidcraft", ".step", ".stl", ".3mf", ".obj"):
        rc, out, err = run_cli(
            ["run", "--in", str(source), "--results",
             "--json-out", str(Path(out_path).with_suffix(".export.json"))],
            timeout)
        if rc != 0:
            raise SolidCraftError(f"export 失敗：{err.strip() or out.strip()}")
        return Path(out_path)
    run_script(script, timeout=timeout)
    return Path(out_path)


def commands() -> list[dict]:
    """回傳全部命令目錄（list of dict）。"""
    rc, out, err = run_cli(["commands"], timeout=300)
    if rc != 0:
        raise SolidCraftError(f"commands 失敗：{err.strip() or out.strip()}")
    return json.loads(out)


def command_catalog_text(path: str) -> Path:
    """把命令目錄落盤成可 grep 的純文字（每筆一區塊）。"""
    cat = commands()
    lines = []
    for c in cat:
        lines.append(f"== {c.get('id')} | {c.get('label')} | icon={c.get('icon')} panel={c.get('panel')}")
        lines.append(f"   params: {c.get('params', '')}")
        lines.append("")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 輔助

class SolidCraftError(RuntimeError):
    pass


def _parse_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # CLI 有時在 JSON 前後夾帶雜訊，取第一段完整 JSON
        i, j = text.find("{"), text.rfind("}")
        i2, j2 = text.find("["), text.rfind("]")
        starts = [k for k in (i, i2) if k >= 0]
        ends = [k for k in (j, j2) if k >= 0]
        if starts and ends and max(ends) > min(starts):
            s, e = min(starts), max(ends)
            return json.loads(text[s:e + 1])
        raise SolidCraftError(f"無法解析 CLI 輸出：{text[:400]}")


def _cli() -> None:
    """CLI 入口：python sc.py <subcommand> ..."""
    if len(sys.argv) < 2:
        print(__doc__)
        return
    sub = sys.argv[1]
    if sub == "commands":
        cat = commands()
        for c in cat:
            print(f"{c.get('id')}\t{c.get('label')}")
    elif sub == "exec":
        cmd = sys.argv[2]
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(exec_command(cmd, params), ensure_ascii=False, indent=2))
    elif sub == "run":
        print(json.dumps(run_script(sys.argv[2]), ensure_ascii=False, indent=2))
    elif sub == "snapshot":
        print(snapshot(sys.argv[2], sys.argv[3],
                       view=sys.argv[4] if len(sys.argv) > 4 else "iso"))
    elif sub == "render":
        print(render(sys.argv[2], sys.argv[3]))
    else:
        print(f"未知子命令：{sub}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
