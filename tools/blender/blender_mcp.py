"""Blender MCP 伺服器（stdio）——把本機 MSIX 版 Blender 接成 MCP 工具。

啟動方式（給 MCP 客戶端登記用）：
    <python> D:\\Civil_Design_WorkBench\\tools\\blender\\blender_mcp.py

環境變數（全部可省略）：
    CIVIL_AI_ROOT            專案根目錄（預設由檔案位置推導）
    CIVIL_AI_BLENDER         可攜版 blender.exe 路徑（沒有 MSIX 時使用）
    CIVIL_AI_BLENDER_APPID   封裝 AppId（預設 BLENDER）
    CIVIL_AI_BLENDER_PACKAGE 封裝名稱樣式（預設 *Blender*）

工具：
    blender_info        安裝／版本／引擎探測
    blender_run_python  在 Blender 背景跑一段 bpy Python
    blender_render      建場景或開 .blend 後渲染靜態圖
    blender_convert     3D 格式互轉（obj/fbx/stl/ply/gltf/glb/usd/abc）
    blender_selftest    端到端自檢（版本→建模→渲染→成品檢查）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import blender_runner as br  # noqa: E402

# ---- MCP SDK 相容層（mcp 1.x: FastMCP / mcp 2.x: MCPServer）---------------
try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server  # type: ignore

except Exception:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

_ALLOWED_KW = set(__import__("inspect").signature(_Server.__init__).parameters)


def _mk(**kw):
    """只傳入當前 SDK 版本支援的建構參數（1.x 沒有 version）。"""
    return _Server(**{k: v for k, v in kw.items() if k in _ALLOWED_KW})


INSTRUCTIONS = """\
Blender（本機 Microsoft Store／MSIX 版）的背景執行介面。

重點行為：
- 全部在背景（-b）執行，不會跳出 GUI，也不會干擾你開著的 Blender。
- 每次呼叫會建立一個工作目錄（_temp/blender/<時間>_<名稱>/），內含
  user_script.py、bootstrap.py、blender.log、result.json，失敗時可直接追。
- 回傳固定欄位：ok、error、traceback、log_tail、result、artifacts、wall_s。

典型用法：
  1. blender_info(probe=true)        先確認版本與引擎
  2. blender_run_python(script=...)  建模型／量測／匯出
  3. blender_render(output_path=...) 出靜態圖（可接 2 的建場腳本）

座標與單位約定（與土木專案一致）：1 Blender unit = 1 公尺，Z 軸向上。
相對輸出路徑以專案根目錄為基準，交付成品請寫到 out/ 下。
"""

mcp = _mk(name="blender", instructions=INSTRUCTIONS, version="1.0.0")


@mcp.tool()
def blender_info(probe: bool = False) -> dict:
    """探測 Blender 安裝方式（MSIX 封裝／可攜版）、版本，以及可用的渲染引擎。

    probe=true 會真的啟動一次 Blender 讀取版本、binary 路徑、引擎清單與已啟用 add-on。
    """
    return br.info(probe=bool(probe))


@mcp.tool()
def blender_run_python(
    script: str,
    blend_file: str | None = None,
    args: dict | None = None,
    timeout_s: float = 300,
    job_name: str | None = None,
) -> dict:
    """在背景 Blender 執行一段 bpy Python，回傳結構化結果。

    - script：Python 原始碼。可設定 `RESULT = {...}` 回傳任意 JSON 資料，
      以及 `ARTIFACTS = [路徑...]` 標記產出的檔案（會在結果中檢查是否存在）。
    - blend_file：先開啟既有 .blend；省略則用 --factory-startup 空場景。
    - args：透過 `ARGS` 變數傳入的參數 dict（適合樣板化腳本）。
    單位約定：1 unit = 1 m、Z 軸向上。
    """
    return br.run_python(
        script,
        job_name=job_name,
        blend_file=blend_file,
        args=args or {},
        timeout_s=float(timeout_s),
    )


@mcp.tool()
def blender_render(
    output_path: str,
    script: str | None = None,
    blend_file: str | None = None,
    engine: str = "CYCLES",
    samples: int = 64,
    resolution: list[int] | None = None,
    camera: str | None = None,
    frame: int | None = None,
    transparent: bool = False,
    keep_scene: bool = False,
    timeout_s: float = 900,
) -> dict:
    """渲染一張靜態圖並回傳成品路徑。

    - output_path：PNG/JPG 路徑；相對路徑以專案根目錄為基準（建議 out/...）。
    - script：可選的建場腳本（燈光、材質、相機都由它決定）。
    - camera：相機物件名稱（省略則用場景既有 scene.camera）。
    - engine：CYCLES（擬真，CPU 可用）或 BLENDER_EEVEE（快）。
    成品檔名必須帶副檔名；回傳 result.bytes 大於 0 才算真的出圖。
    """
    res = resolution or [1920, 1080]
    return br.render(
        output_path,
        script=script,
        blend_file=blend_file,
        engine=engine,
        samples=int(samples),
        resolution=[int(res[0]), int(res[1])],
        camera=camera,
        frame=frame,
        transparent=bool(transparent),
        keep_scene=bool(keep_scene),
        timeout_s=float(timeout_s),
    )


@mcp.tool()
def blender_convert(input_path: str, output_path: str, timeout_s: float = 300) -> dict:
    """3D 模型格式互轉：obj / fbx / stl / ply / gltf / glb / usd / usda / usdc / abc。

    適合把 SolidCraft、CAD 或其他工具產出的模型轉成可交付或可再編輯的格式；
    回傳物件數與三角面數，可用來對帳模型是否被正確讀入。
    """
    return br.convert(input_path, output_path, timeout_s=float(timeout_s))


@mcp.tool()
def blender_selftest() -> dict:
    """端到端自檢：探測版本 → 建一顆立方體 → Cycles 低取樣渲染 → 檢查成品。

    回傳 checks 陣列（每項 passed 布林）與整體驗證結論；換電腦或升級後先跑這支。
    """
    checks: list[dict] = []
    info = br.info(probe=True)
    checks.append({"check": "install_found", "passed": info.get("blender", {}).get("mode") != "missing",
                   "detail": info.get("blender", {}).get("mode")})
    probe = info.get("probe") or {}
    checks.append({"check": "launch_and_read_version", "passed": bool(probe.get("version")),
                   "detail": probe.get("version")})

    out = br.TEMP / "blender" / "selftest.png"
    res = br.render(
        str(out),
        script=(
            "import bpy, math\n"
            "bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,1))\n"
            "bpy.ops.object.camera_add(location=(6,-6,5))\n"
            "cam = bpy.context.object\n"
            "c = cam.constraints.new('TRACK_TO')\n"
            "c.target = bpy.data.objects['Cube']\n"
            "bpy.context.scene.camera = cam\n"
            "bpy.ops.object.light_add(type='SUN', location=(4,-4,8))\n"
            "bpy.context.object.data.energy = 5\n"
        ),
        engine="CYCLES",
        samples=8,
        resolution=[320, 240],
        camera=None,
        timeout_s=300,
        job_name="selftest",
    )
    checks.append({"check": "render_ok", "passed": bool(res.get("ok")), "detail": res.get("error")})
    bytes_out = ((res.get("result") or {}).get("bytes")) or -1
    checks.append({"check": "output_non_empty", "passed": bool(bytes_out and bytes_out > 1024),
                   "detail": f"{bytes_out} bytes"})

    return {
        "ok": all(c["passed"] for c in checks),
        "checks": checks,
        "sample_output": str(out) if bytes_out and bytes_out > 1024 else None,
        "info": info.get("blender"),
        "runner": {"jobs_dir": str(br.JOBS_DIR), "python": sys.version.split()[0]},
    }


def main() -> None:
    json.dumps  # 保持 import 使用痕跡；供部分客戶端載入
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    mcp.run()


if __name__ == "__main__":
    main()
