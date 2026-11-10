"""Blender 執行核心（Windows／MSIX 商店版相容）。

存在理由：本機 Blender 是 Microsoft Store（MSIX）封裝，`blender.exe` 直接呼叫會被
拒絕（存取被拒），必須經 `Invoke-CommandInDesktopPackage` 以封裝身分啟動；而該 API
**不回傳 stdout**、也不等待結束。因此本模組用「工作目錄 + 結果檔 + 輪詢」的方式把
Blender 變成可呼叫、可驗證的函式：

1. 在工作目錄寫入 `user_script.py`、`job.json`、`bootstrap.py`
2. 以封裝身分啟動 `blender -b --python <bootstrap>`（或直接模式）
3. bootstrap 把使用者腳本跑完後寫 `result.json`（含 ok／traceback／RESULT／artifacts）
4. 本模組輪詢 `result.json`，逾時則只終止「命令列含本工作目錄」的 blender 行程

對外 API：
    find_blender() -> dict                      # 安裝探測（direct / msix / missing）
    run_python(script, ...) -> dict             # 背景跑一段 Python（bpy）
    render(...) -> dict                          # 設定引擎→渲染→回傳成品路徑
    convert(...) -> dict                         # 3D 格式轉檔（obj/fbx/stl/gltf/usd/abc）

所有暫存檔一律落在 `<專案>/_temp/blender/<job>/`，不污染交付目錄。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:  # 專案路徑解析器（AGENTS.md §1.1：不得寫死絕對路徑）
    from tools import project_paths as pp  # type: ignore
    ROOT = Path(pp.ROOT)
    TEMP = Path(pp.TEMP)
except Exception:  # 被當成獨立模組載入時（MCP 直接跑本檔）仍可運作
    ROOT = Path(os.environ.get("CIVIL_AI_ROOT") or Path(__file__).resolve().parents[2]).resolve()
    TEMP = ROOT / "_temp"

JOBS_DIR = TEMP / "blender"
PACKAGE_MATCH = os.environ.get("CIVIL_AI_BLENDER_PACKAGE", "*Blender*")
APP_ID = os.environ.get("CIVIL_AI_BLENDER_APPID", "BLENDER")
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh") or "powershell"

BOOTSTRAP = r'''
# -*- coding: utf-8 -*-
"""Blender 背景工作 bootstrap：跑 user_script.py 並把結果寫成 result.json。"""
import bpy, io, json, os, sys, time, traceback

JOB_DIR = os.path.dirname(os.path.abspath(__file__))
USER = os.path.join(JOB_DIR, "user_script.py")
RESULT = os.path.join(JOB_DIR, "result.json")
LOG = os.path.join(JOB_DIR, "blender.log")
JOB = json.load(open(os.path.join(JOB_DIR, "job.json"), "r", encoding="utf-8"))

log = open(LOG, "a", encoding="utf-8", errors="replace")
real_out, real_err = sys.stdout, sys.stderr


class _Tee(io.TextIOBase):
    def __init__(self, stream):
        self.stream = stream

    def write(self, s):
        try:
            log.write(s)
            log.flush()
        except Exception:
            pass
        try:
            self.stream.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            log.flush()
        except Exception:
            pass
        try:
            self.stream.flush()
        except Exception:
            pass


sys.stdout, sys.stderr = _Tee(real_out), _Tee(real_err)
payload = {
    "ok": False,
    "job": JOB.get("job_name"),
    "blender": bpy.app.version_string,
    "python": sys.version.split()[0],
    "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "artifacts": [],
    "result": None,
    "error": None,
    "traceback": None,
}
t0 = time.time()
try:
    blend = JOB.get("blend_file")
    if blend:
        bpy.ops.wm.open_mainfile(filepath=blend)
    g = {"__name__": "__main__", "__file__": USER, "ARGS": JOB.get("args") or {},
         "JOB_DIR": JOB_DIR, "bpy": bpy}
    src = open(USER, "r", encoding="utf-8-sig").read()
    exec(compile(src, USER, "exec"), g)
    payload["ok"] = True
    value = g.get("RESULT")
    if value is not None:
        try:
            payload["result"] = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            payload["result"] = str(value)
    payload["artifacts"] = [str(p) for p in (g.get("ARTIFACTS") or [])]
except SystemExit as exc:
    payload["ok"] = int(getattr(exc, "code", 0) or 0) == 0
    payload["error"] = None if payload["ok"] else f"SystemExit({exc.code})"
except Exception:
    payload["error"] = traceback.format_exc(limit=6).strip().splitlines()[-1]
    payload["traceback"] = traceback.format_exc()
finally:
    payload["elapsed_s"] = round(time.time() - t0, 2)
    payload["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        log.close()
    except Exception:
        pass
    with open(RESULT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
'''


# ------------------------------------------------------------------ PowerShell
def _ps(command: str, timeout: int = 60) -> dict:
    # 非 Windows 沒有 Get-AppxPackage／MSIX，也常沒有 PowerShell：直接回空結果，讓呼叫端走 PATH／環境變數。
    if sys.platform != "win32":
        return {"exit_code": 127, "stdout": "", "stderr": "PowerShell 僅 Windows 使用"}
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=timeout,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace").strip(),
        "stderr": proc.stderr.decode("utf-8", "replace").strip(),
    }


def find_blender(refresh: bool = False) -> dict:
    """探測 Blender：環境變數 → MSIX 封裝 → PATH → 常見安裝目錄。"""
    info: dict = {"mode": "missing", "exe": None, "package_family": None, "app_id": APP_ID,
                  "version": None, "notes": []}

    explicit = os.environ.get("CIVIL_AI_BLENDER") or os.environ.get("BLENDER")
    if explicit and Path(explicit).exists():
        info.update(mode="direct", exe=str(Path(explicit)), notes=["來源：環境變數 CIVIL_AI_BLENDER／BLENDER"])
    else:
        res = _ps(
            "$p = Get-AppxPackage -Name '" + PACKAGE_MATCH + "' | Select-Object -First 1; "
            "if ($p) { $exe = Join-Path $p.InstallLocation 'Blender\\blender.exe'; "
            "$ok = Test-Path $exe; "
            "Write-Output ($p.PackageFamilyName + '|' + $p.Version + '|' + $exe + '|' + $ok) }"
        )
        line = (res.get("stdout") or "").strip().splitlines()
        if line and line[0].count("|") >= 3:
            pfn, ver, exe, ok = line[0].split("|", 3)
            if str(ok).strip().lower() == "true":
                info.update(mode="msix", package_family=pfn.strip(), version=ver.strip(),
                            exe=exe.strip(),
                            notes=["MSIX 封裝版：須經 Invoke-CommandInDesktopPackage 啟動"])

        if info["mode"] == "missing":
            on_path = shutil.which("blender")
            if on_path:
                info.update(mode="direct", exe=on_path, notes=["來源：PATH"])
            else:
                for pattern in (r"C:\Program Files\Blender Foundation\*\blender.exe",
                                r"D:\Program Files\Blender Foundation\*\blender.exe"):
                    hits = sorted(Path(p) for p in __import__("glob").glob(pattern))
                    if hits:
                        info.update(mode="direct", exe=str(hits[-1]), notes=["來源：常見安裝目錄"])
                        break

    if info["mode"] == "msix" and not info["version"]:
        info["version"] = None
    return info


def _version(blender: dict) -> str | None:
    if blender.get("version"):
        return blender["version"]
    return None


# --------------------------------------------------------------------- 工作目錄
def _slug(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_\-]+", "_", (text or "job").strip())[:40]
    return text or "job"


def new_job_dir(job_name: str | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = JOBS_DIR / f"{stamp}_{_slug(job_name or 'job')}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quote_ps(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _parse_args(pairs: list[str] | None) -> dict:
    """把 `--arg KEY=VALUE` 轉成腳本可見的 ARGS dict（值會自動轉數字）。"""
    out: dict = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--arg 需為 KEY=VALUE 形式，收到：{item}")
        key, raw = item.split("=", 1)
        key = key.strip()
        for cast in (int, float):
            try:
                out[key] = cast(raw)
                break
            except ValueError:
                continue
        else:
            out[key] = raw
    return out


def _blender_argv(blender: dict, job_dir: Path, blend_file: str | None,
                  extra_args: tuple[str, ...] | list[str] = ()) -> list[str]:
    argv = ["-b"]
    argv += [str(blend_file)] if blend_file else ["--factory-startup"]
    argv += ["--python", str(job_dir / "bootstrap.py")]
    argv += [str(a) for a in extra_args]
    return argv


def _kill_job_processes(job_dir: Path) -> dict:
    if sys.platform != "win32":  # 只終止命令列含本工作目錄的 blender
        r = subprocess.run(["pkill", "-f", str(job_dir)], capture_output=True, text=True)
        return {"killed_pids": [], "note": f"pkill exit={r.returncode}"}
    cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='blender.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -like "
        + _quote_ps("*" + str(job_dir) + "*")
        + " } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }"
    )
    res = _ps("try { " + cmd + " } catch { Write-Output ('ERR ' + $_.Exception.Message) }")
    killed = [ln.strip() for ln in (res.get("stdout") or "").splitlines() if ln.strip().isdigit()]
    return {"killed_pids": killed, "note": res.get("stderr") or None}


def _launch(blender: dict, job_dir: Path, blend_file: str | None,
            timeout_s: float, extra_args: tuple[str, ...] | list[str] = ()) -> dict:
    """啟動 Blender 並等待 result.json；回傳 launch 紀錄（不含腳本語意）。"""
    argv = _blender_argv(blender, job_dir, blend_file, extra_args)
    result_path = job_dir / "result.json"
    if result_path.exists():
        result_path.unlink()
    t0 = time.time()

    if blender["mode"] == "direct":
        launch = "direct"
        try:
            proc = subprocess.run(
                [blender["exe"], *argv],
                capture_output=True,
                timeout=timeout_s + 30,
                cwd=str(job_dir),
            )
            (job_dir / "stdout.txt").write_bytes(proc.stdout or b"")
            (job_dir / "stderr.txt").write_bytes(proc.stderr or b"")
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:  # 交給下方逾時流程回報，不要讓例外直接炸掉 MCP 呼叫
            exit_code = None
    elif blender["mode"] == "msix":
        args_str = " ".join(
            [a if a.startswith("-") else f'"{a}"' for a in argv]
        )
        command = (
            "Invoke-CommandInDesktopPackage -PackageFamilyName "
            + _quote_ps(blender["package_family"])
            + " -AppId " + _quote_ps(blender["app_id"])
            + " -Command " + _quote_ps(blender["exe"])
            + " -Args " + _quote_ps(args_str)
        )
        res = _ps(command, timeout=120)
        launch = "msix"
        exit_code = res.get("exit_code")
        if res.get("stderr"):
            (job_dir / "stderr.txt").write_text(res["stderr"], encoding="utf-8")
    else:
        raise RuntimeError("找不到 Blender（環境變數 CIVIL_AI_BLENDER 或 MSIX 封裝）")

    deadline = t0 + float(timeout_s)
    while time.time() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                return {"launched": launch, "timed_out": False, "exit_code": exit_code,
                        "wall_s": round(time.time() - t0, 2), "payload": data, "argv": argv}
            except json.JSONDecodeError:
                pass  # 檔案還在寫入
        time.sleep(0.25)

    kill = _kill_job_processes(job_dir)
    return {
        "launched": launch,
        "timed_out": True,
        "exit_code": exit_code,
        "wall_s": round(time.time() - t0, 2),
        "payload": None,
        "argv": argv,
        "kill": kill,
        "note": f"超過 {int(timeout_s)}s 未產生 result.json；已嘗試終止本工作行程",
    }


def _log_tail(job_dir: Path, lines: int = 40) -> str:
    for name in ("blender.log", "stderr.txt"):
        path = job_dir / name
        if path.exists() and path.stat().st_size:
            text = path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.strip().splitlines()[-lines:])
    return ""


def _finish(launch: dict, job_dir: Path, script_chars: int, lines: int) -> dict:
    payload = launch.get("payload") or {}
    artifacts = [a for a in payload.get("artifacts", []) if Path(a).exists()]
    out = {
        "ok": bool(payload.get("ok")) and not launch.get("timed_out"),
        "job_dir": str(job_dir),
        "blender": payload.get("blender"),
        "python": payload.get("python"),
        "elapsed_s": payload.get("elapsed_s"),
        "wall_s": launch.get("wall_s"),
        "script_chars": script_chars,
        "result": payload.get("result"),
        "artifacts": artifacts,
        "error": payload.get("error"),
        "traceback": payload.get("traceback"),
        "log_tail": _log_tail(job_dir, lines),
        "launched_via": launch.get("launched"),
        "timed_out": bool(launch.get("timed_out")),
    }
    if launch.get("timed_out"):
        out["error"] = launch.get("note")
        out["kill"] = launch.get("kill")
    return out


# ----------------------------------------------------------------- 對外主入口
def run_python(script: str, *, job_name: str | None = None, blend_file: str | None = None,
               args: dict | None = None, timeout_s: float = 300,
               extra_args: tuple[str, ...] | list[str] = (), log_lines: int = 40) -> dict:
    """在 Blender 背景行程執行一段 bpy Python，回傳結構化結果。"""
    blender = find_blender()
    if blender["mode"] == "missing":
        return {"ok": False, "error": "找不到 Blender 安裝", "blender": blender}

    job_dir = new_job_dir(job_name or "run_python")
    script = (script or "").lstrip("\ufeff")
    (job_dir / "user_script.py").write_text(script, encoding="utf-8")
    (job_dir / "bootstrap.py").write_text(BOOTSTRAP, encoding="utf-8")
    (job_dir / "job.json").write_text(
        json.dumps({"job_name": job_name, "blend_file": blend_file,
                    "args": args or {}, "timeout_s": timeout_s}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    launch = _launch(blender, job_dir, blend_file, timeout_s, extra_args)
    out = _finish(launch, job_dir, len(script), log_lines)
    out["blender_mode"] = blender["mode"]
    return out


RENDER_SCRIPT = r'''
# 由 blender_runner.render() 產生：先跑使用者腳本（可選），再套渲染設定並輸出。
import bpy, os, time
spec = ARGS
if not spec.get("keep_scene"):
    bpy.ops.wm.read_factory_settings(use_empty=True)

user_script = spec.get("user_script") or ""
if user_script.strip():
    exec(compile(user_script, os.path.join(JOB_DIR, "inline_render_setup.py"), "exec"), globals())

scene = bpy.context.scene
engine = spec.get("engine") or "CYCLES"
try:
    scene.render.engine = engine
except Exception:
    scene.render.engine = "CYCLES"
    engine = "CYCLES"
if engine == "CYCLES":
    scene.cycles.samples = int(spec.get("samples") or 64)
    scene.cycles.device = spec.get("device") or "CPU"
    scene.cycles.use_denoising = bool(spec.get("denoise", True))

w, h = (spec.get("resolution") or [1920, 1080])[:2]
scene.render.resolution_x = int(w)
scene.render.resolution_y = int(h)
scene.render.resolution_percentage = int(spec.get("resolution_percentage") or 100)
scene.render.film_transparent = bool(spec.get("transparent"))
scene.render.image_settings.file_format = (spec.get("format") or "PNG").upper()

camera = spec.get("camera")
if camera:
    obj = bpy.data.objects.get(camera)
    if obj is None:
        raise ValueError("找不到相機物件：" + camera)
    scene.camera = obj
if scene.camera is None:
    raise ValueError("場景沒有相機；請在腳本內建立相機或指定 camera=")

if spec.get("frame") is not None:
    scene.frame_set(int(spec["frame"]))

out = spec["output_path"]
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
scene.render.filepath = out
t0 = time.time()
bpy.ops.render.render(write_still=True)
RESULT = {
    "output": out,
    "exists": os.path.exists(out),
    "bytes": os.path.getsize(out) if os.path.exists(out) else -1,
    "engine": scene.render.engine,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "render_s": round(time.time() - t0, 2),
    "objects": len(bpy.data.objects),
}
ARTIFACTS = [out]
'''


def render(output_path: str, *, script: str | None = None, blend_file: str | None = None,
           engine: str = "CYCLES", samples: int = 64, resolution: tuple[int, int] | list[int] = (1920, 1080),
           camera: str | None = None, frame: int | None = None, transparent: bool = False,
           keep_scene: bool = False, timeout_s: float = 900,
           job_name: str | None = None) -> dict:
    """渲染一張靜態圖：可先跑 scene 建立腳本，再套用畫質設定輸出。"""
    out = Path(output_path)
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    args = {
        "output_path": str(out),
        "user_script": script or "",
        "engine": engine,
        "samples": int(samples),
        "resolution": [int(resolution[0]), int(resolution[1])],
        "camera": camera,
        "frame": frame,
        "transparent": bool(transparent),
        "keep_scene": bool(keep_scene) or bool(blend_file),
    }
    return run_python(RENDER_SCRIPT, job_name=job_name or "render", blend_file=blend_file,
                      args=args, timeout_s=timeout_s, log_lines=30)


CONVERT_SCRIPT = r'''
import bpy, os
spec = ARGS
src, dst = spec["input_path"], spec["output_path"]
ext = os.path.splitext(src)[1].lower()
bpy.ops.wm.read_factory_settings(use_empty=True)

importers = {
    ".obj": lambda: bpy.ops.wm.obj_import(filepath=src),
    ".fbx": lambda: bpy.ops.import_scene.fbx(filepath=src),
    ".stl": lambda: bpy.ops.wm.stl_import(filepath=src),
    ".ply": lambda: bpy.ops.wm.ply_import(filepath=src),
    ".gltf": lambda: bpy.ops.import_scene.gltf(filepath=src),
    ".glb": lambda: bpy.ops.import_scene.gltf(filepath=src),
    ".usd": lambda: bpy.ops.wm.usd_import(filepath=src),
    ".usda": lambda: bpy.ops.wm.usd_import(filepath=src),
    ".usdc": lambda: bpy.ops.wm.usd_import(filepath=src),
    ".abc": lambda: bpy.ops.wm.alembic_import(filepath=src),
}
if ext not in importers:
    raise ValueError("不支援的來源格式：" + ext)

importers[ext]()

dext = os.path.splitext(dst)[1].lower()
os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
if dext == ".obj":
    bpy.ops.wm.obj_export(filepath=dst, export_materials=True)
elif dext == ".fbx":
    bpy.ops.export_scene.fbx(filepath=dst)
elif dext == ".stl":
    bpy.ops.wm.stl_export(filepath=dst)
elif dext == ".ply":
    bpy.ops.wm.ply_export(filepath=dst)
elif dext in (".gltf", ".glb"):
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB" if dext == ".glb" else "GLTF_SEPARATE")
elif dext in (".usd", ".usda", ".usdc"):
    bpy.ops.wm.usd_export(filepath=dst)
elif dext == ".abc":
    bpy.ops.wm.alembic_export(filepath=dst)
else:
    raise ValueError("不支援的目標格式：" + dext)

RESULT = {
    "input": src,
    "output": dst,
    "exists": os.path.exists(dst),
    "bytes": os.path.getsize(dst) if os.path.exists(dst) else -1,
    "objects": len(bpy.data.objects),
    "triangles": sum(len(o.data.polygons) for o in bpy.data.objects if o.type == "MESH"),
}
ARTIFACTS = [dst]
'''


def convert(input_path: str, output_path: str, *, timeout_s: float = 300,
            job_name: str | None = None) -> dict:
    """3D 格式轉檔（obj/fbx/stl/ply/gltf/glb/usd/abc 互轉）。"""
    src = Path(input_path)
    if not src.is_absolute():
        src = (ROOT / src).resolve()
    dst = Path(output_path)
    if not dst.is_absolute():
        dst = (ROOT / dst).resolve()
    if not src.exists():
        return {"ok": False, "error": f"來源檔不存在：{src}"}
    args = {"input_path": str(src), "output_path": str(dst)}
    return run_python(CONVERT_SCRIPT, job_name=job_name or "convert", args=args,
                      timeout_s=timeout_s, log_lines=20)


def info(probe: bool = False) -> dict:
    """回傳 Blender 安裝資訊；probe=True 時另外啟動一次 Blender 讀版本與引擎清單。"""
    blender = find_blender()
    out = {"blender": blender, "jobs_dir": str(JOBS_DIR), "project_root": str(ROOT)}
    if blender["mode"] == "missing":
        out["ok"] = False
        out["hint"] = ("若為可攜版，設定環境變數 CIVIL_AI_BLENDER=<blender.exe 路徑>；"
                       "MSIX 版需存在 BlenderFoundation.* 封裝")
        return out
    out["ok"] = True
    if probe:
        res = run_python(
            "import bpy\n"
            "engines = [i.identifier for i in bpy.types.RenderSettings.bl_rna."
            "properties['engine'].enum_items]\n"
            "RESULT = {'version': bpy.app.version_string, 'binary': bpy.app.binary_path,"
            " 'engines': engines, 'addons': sorted(a.module for a in bpy.context.preferences.addons)}\n",
            job_name="info", timeout_s=120, log_lines=10,
        )
        out["probe_ok"] = res.get("ok")
        out["probe"] = res.get("result")
        out["probe_error"] = res.get("error")
    return out


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Blender 背景執行器（MSIX 相容）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="探測安裝與版本").add_argument("--probe", action="store_true")

    p_run = sub.add_parser("run", help="執行一支 Python 腳本")
    p_run.add_argument("script")
    p_run.add_argument("--blend")
    p_run.add_argument("--timeout", type=float, default=300)
    p_run.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE",
                       help="傳給腳本的全域 ARGS（可重複）。MSIX 啟動的 Blender 收不到呼叫端 $env:，"
                            "覆寫參數一律用這個。")

    p_render = sub.add_parser("render", help="渲染靜態圖")
    p_render.add_argument("output")
    p_render.add_argument("--script")
    p_render.add_argument("--blend")
    p_render.add_argument("--engine", default="CYCLES")
    p_render.add_argument("--samples", type=int, default=64)
    p_render.add_argument("--resolution", default="1920x1080")
    p_render.add_argument("--camera")
    p_render.add_argument("--frame", type=int)
    p_render.add_argument("--timeout", type=float, default=900)

    p_conv = sub.add_parser("convert", help="3D 格式轉檔")
    p_conv.add_argument("input")
    p_conv.add_argument("output")

    a = ap.parse_args()
    if a.cmd == "info":
        payload = info(probe=a.probe)
    elif a.cmd == "run":
        payload = run_python(Path(a.script).read_text(encoding="utf-8-sig"),
                            job_name=Path(a.script).stem, blend_file=a.blend, timeout_s=a.timeout,
                            args=_parse_args(a.arg))
    elif a.cmd == "render":
        w, h = (a.resolution.lower().split("x") + ["1080"])[:2]
        script = Path(a.script).read_text(encoding="utf-8-sig") if a.script else None
        payload = render(a.output, script=script, blend_file=a.blend, engine=a.engine,
                         samples=a.samples, resolution=(int(w), int(h)), camera=a.camera,
                         frame=a.frame, timeout_s=a.timeout)
    else:
        payload = convert(a.input, a.output)
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_cli())
