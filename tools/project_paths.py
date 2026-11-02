"""專案路徑與外部工具解析（跨平台、無絕對路徑）。

所有工具都應該從這裡取路徑，不要在個別檔案裡寫死 `D:\\公司案件.AI` 或
`C:\\Python312\\python.exe`。本模組的解析順序：

1. **環境變數**（優先）：`CIVIL_AI_ROOT`、`CIVIL_AI_REGS_DB`、`ARTCRAFT_HOME`、
   `CIVIL_AI_PYTHON`、`AUTOCAD_HOME`、`SOLIDCRAFT_CLI`
2. **專案根目錄**：由本檔位置往上推（`tools/project_paths.py` → 上兩層），
   因此整個資料夾搬到任何磁碟、任何作業系統都成立
3. **外部程式**：先找環境變數，再找各平台的常見安裝位置，最後找 `PATH`

用法::

    from project_paths import ROOT, regs_db, artcraft_cli, python_exe

    print(ROOT)                       # 專案根目錄（Path）
    print(regs_db())                  # data/法規/_regs_index.sqlite
    print(artcraft_cli("GridCraft"))  # 找不到時回傳 None（不丟錯，讓呼叫端自行決定）

命令列檢查環境::

    python tools/project_paths.py            # 印出所有解析結果
    python tools/project_paths.py --json     # 給安裝腳本吃的 JSON
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------- 專案根目錄

HERE = Path(__file__).resolve().parent          # <root>/tools
ROOT = Path(os.environ.get("CIVIL_AI_ROOT") or HERE.parent).resolve()

DATA = ROOT / "data"
REGS_DIR = DATA / "法規"
OUT = ROOT / "out"
TEMP = ROOT / "_temp"
CASES = ROOT / "cases"
DOCS = ROOT / "docs"
TOOLS = ROOT / "tools"
TEMPLATES = ROOT / "templates"
SKILLS = ROOT / ".agents" / "skills"


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else None


def regs_db() -> Path:
    """規範索引 SQLite（預設 data/法規/_regs_index.sqlite）。"""
    return _env_path("CIVIL_AI_REGS_DB") or (REGS_DIR / "_regs_index.sqlite")


def verified_dir() -> Path:
    """已驗證公式／圖表庫目錄（tools/regs/verified）。"""
    return TOOLS / "regs" / "verified"


def temp_dir(*parts: str, create: bool = True) -> Path:
    """暫存目錄（_temp 下）。AGENTS.md §1.1：機械產物一律放這裡。"""
    p = TEMP.joinpath(*parts) if parts else TEMP
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir(*parts: str, create: bool = True) -> Path:
    """交付物目錄（out 下）。"""
    p = OUT.joinpath(*parts) if parts else OUT
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 外部程式

def python_exe() -> str:
    """執行 Python 的直譯器：`CIVIL_AI_PYTHON` → 目前執行中的解譯器。"""
    return os.environ.get("CIVIL_AI_PYTHON") or sys.executable


def _first_existing(cands) -> str | None:
    for c in cands:
        if not c:
            continue
        p = Path(os.path.expandvars(os.path.expanduser(str(c))))
        if p.is_file():
            return str(p)
    return None


#: ArtCraft 各 App 的 CLI 檔名（Windows 為 <app>-cli.exe，其他平台為 <app>-cli）
ARTCRAFT_APPS = {
    "CADCraft": "cadcraft-cli",
    "GridCraft": "gridcraft-cli",
    "WordCraft": "wordcraft-cli",
    "DeckCraft": "deckcraft-cli",
    "PdfCraft": "pdfcraft-cli",
    "PhotoCraft": "photocraft-cli",
    "LightCraft": "lightcraft-cli",
    "VectorCraft": "vectorcraft-cli",
    "DesignCraft": "designcraft-cli",
    "FigCraft": "figcraft-cli",
    "FilmCraft": "filmcraft-cli",
    "EffectCraft": "effectcraft-cli",
    "SoundCraft": "soundcraft-cli",
}


def artcraft_home() -> Path | None:
    """ArtCraft 安裝根目錄：`ARTCRAFT_HOME` → 各平台預設位置。"""
    p = _env_path("ARTCRAFT_HOME")
    if p and p.is_dir():
        return p
    cands = [
        Path(r"C:\Program\ArtCraft"),
        Path.home() / "ArtCraft",
        Path("/opt/ArtCraft"),
        Path("/Applications/ArtCraft"),
    ]
    for c in cands:
        if c.is_dir():
            return c
    return None


def artcraft_cli(app: str) -> str | None:
    """回傳某個 ArtCraft App 的 CLI 路徑；找不到回傳 None。

    `app` 可為 `"GridCraft"` 或 `"gridcraft"`（大小寫與 -cli 後綴皆可省略）。
    """
    key = app[:-4] if app.lower().endswith("-cli") else app
    stem = ARTCRAFT_APPS.get(key)
    if stem is None:
        for k, v in ARTCRAFT_APPS.items():
            if k.lower() == key.lower():
                stem = v
                break
    if stem is None:
        stem = f"{key.lower()}-cli"

    env_name = f"{stem.upper().replace('-', '_')}_CLI"
    p = _env_path(env_name)
    if p:
        return str(p)

    home = artcraft_home()
    if home:
        found = _first_existing([
            home / key / f"{stem}.exe",
            home / key / stem,
            home / key.capitalize() / f"{stem}.exe",
            home / key.capitalize() / stem,
        ])
        if found:
            return found
    for name in (f"{stem}.exe", stem):
        w = shutil.which(name)
        if w:
            return w
    return None


def accoreconsole() -> str | None:
    """AutoCAD 無介面核心（僅 Windows 需要，用於 DXF→DWG／PDF）。

    解析順序：`AUTOCAD_HOME` → 各版本安裝目錄 → PATH。
    """
    p = _env_path("AUTOCAD_HOME")
    if p:
        found = _first_existing([p / "accoreconsole.exe", p])
        if found:
            return found
    roots = [Path(r"C:\Program Files\Autodesk"), Path(r"C:\Program Files (x86)\Autodesk")]
    cands = []
    for r in roots:
        if r.is_dir():
            cands += sorted(r.glob("AutoCAD */accoreconsole.exe"), reverse=True)
    found = _first_existing(cands)
    return found or shutil.which("accoreconsole")


def solidcraft_cli() -> str | None:
    """SolidCraft CLI：`SOLIDCRAFT_CLI` → 常見安裝位置 → PATH。"""
    p = _env_path("SOLIDCRAFT_CLI")
    if p:
        return str(p)
    found = _first_existing([
        Path(r"C:\Program Files\SolidCraft\solidcraft-cli.exe"),
        Path(r"C:\Program\SolidCraft\solidcraft-cli.exe"),
        Path.home() / "SolidCraft" / "solidcraft-cli",
        Path("/opt/SolidCraft/solidcraft-cli"),
        Path("/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli"),
    ])
    return found or shutil.which("solidcraft-cli")


def blender_exe() -> str | None:
    """Blender 執行檔（選用）：`BLENDER` 環境變數 → PATH → 常見安裝位置。"""
    p = os.environ.get("BLENDER")
    if p:
        return p
    cands = [Path("/Applications/Blender.app/Contents/MacOS/Blender"), Path("/usr/bin/blender")]
    for r in (Path(r"C:\Program Files\Blender Foundation"),):
        if r.is_dir():
            cands += sorted(r.glob("Blender */blender.exe"), reverse=True)
    return _first_existing(cands) or shutil.which("blender")


def cad_fonts_dir() -> Path | None:
    """CAD 字體庫（TOMO 樣式用 gbenor.shx + CHINA1.SHX）。

    解析順序：`CAD_FONTS` 環境變數 → **專案內 `CAD_FONTS/`（已隨 repo 附）** →
    AutoCAD 安裝目錄的 Fonts 子目錄 → 舊的 `c:\\CadFont[S]`。

    注意：DXF 內只記字型**檔名**（`font="gbenor.shx"`），AutoCAD 開圖時是到自己的
    字型搜尋路徑找檔；所以把字型放在專案裡不會自動讓 AutoCAD 找到，
    仍需把兩個 .shx 複製到 AutoCAD 的字型目錄（見 `tools/install_cad_fonts.py`）。
    """
    p = _env_path("CAD_FONTS")
    if p and p.is_dir():
        return p
    in_repo = ROOT / "CAD_FONTS"
    if in_repo.is_dir() and any(in_repo.glob("*.shx")):
        return in_repo
    for c in (Path(r"C:\CadFont[S]"), Path(r"C:\Program Files\Autodesk")):
        if c.is_dir():
            for sub in sorted(c.rglob("Fonts")):
                if sub.is_dir() and any(sub.glob("gbenor.shx")):
                    return sub
    return None


def cad_font(name: str) -> Path | None:
    """回傳指定 SHX 字型檔的路徑（找不到回傳 None）。"""
    d = cad_fonts_dir()
    if not d:
        return None
    p = d / name
    return p if p.is_file() else None


# ---------------------------------------------------------------- 自我檢查

def report() -> dict:
    """把解析結果整理成 dict（給 `--json` 與安裝檢查腳本用）。"""
    art = artcraft_home()
    return {
        "root": str(ROOT),
        "python": python_exe(),
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "platform": sys.platform,
        "regs_db": str(regs_db()),
        "regs_db_exists": regs_db().exists(),
        "verified_dir": str(verified_dir()),
        "verified_exists": verified_dir().is_dir(),
        "temp": str(TEMP),
        "out": str(OUT),
        "artcraft_home": str(art) if art else None,
        "artcraft": {a: artcraft_cli(a) for a in ARTCRAFT_APPS},
        "accoreconsole": accoreconsole(),
        "solidcraft": solidcraft_cli(),
        "blender": blender_exe(),
        "cad_fonts": str(cad_fonts_dir()) if cad_fonts_dir() else None,
        "cad_font_files": {n: (str(cad_font(n)) if cad_font(n) else None)
                           for n in ("gbenor.shx", "CHINA1.SHX")},
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="印出專案路徑與外部工具的解析結果（跨平台、無絕對路徑寫死）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（給安裝腳本用）")
    a = ap.parse_args(argv)
    info = report()
    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0
    print(f"專案根目錄 : {info['root']}")
    print(f"Python     : {info['python']}  ({info['python_version']}, {info['platform']})")
    print(f"規範索引   : {info['regs_db']}  [{'OK' if info['regs_db_exists'] else '缺少，請先跑 tools/regs/build_index.py'}]")
    print(f"已驗證庫   : {info['verified_dir']}  [{'OK' if info['verified_exists'] else '缺少'}]")
    print(f"ArtCraft   : {info['artcraft_home'] or '（未安裝，或設定 ARTCRAFT_HOME）'}")
    for k, v in info["artcraft"].items():
        print(f"  {k:<12} {'OK  ' + v if v else '—'}")
    print(f"accoreconsole: {info['accoreconsole'] or '—（AutoCAD 僅 Windows；沒有也能產 DXF，只是不能轉 DWG）'}")
    print(f"SolidCraft   : {info['solidcraft'] or '—（選用）'}")
    print(f"Blender      : {info['blender'] or '—（選用）'}")
    print(f"CAD 字體庫   : {info['cad_fonts'] or '—（TOMO 樣式的 gbenor.shx / CHINA1.SHX 找不到）'}")
    for k, v in info["cad_font_files"].items():
        print(f"  {k:<14} {v or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
