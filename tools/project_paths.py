"""專案路徑與外部工具解析（跨平台、無絕對路徑）。

所有工具都應該從這裡取路徑，不要寫死磁碟絕對路徑（例如 Windows 的
`D:\\某資料夾`、`C:\\Python312\\python.exe`）。本模組的解析順序：

1. **環境變數**（優先）：`CIVIL_AI_ROOT`、`CIVIL_AI_REGS_DB`、`ARTCRAFT_HOME`、
   `CIVIL_AI_PYTHON`、`AUTOCAD_HOME`、`SOLIDCRAFT_CLI`、`INGETRAZO_HOME`、
   `INGETRAZO_MCP`
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
    "TextureCraft": "texturecraft-cli",
    "Craft Anything": "craft-anything-cli",
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
        norm_in = key.lower().replace(" ", "").replace("-", "").replace("_", "")
        for k, v in ARTCRAFT_APPS.items():
            norm_k = k.lower().replace(" ", "").replace("-", "").replace("_", "")
            if norm_k == norm_in:
                key = k
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
    # macOS／Linux：App 套件內沒有 headless `-cli`，改用本專案的控制通道殼層
    # （tools/artcraft_cli/bin/<stem>，走 JSON-lines 控制通道，見 docs/環境需求與自動配置.md §8）
    shim = TOOLS / "artcraft_cli" / "bin" / stem
    if shim.is_file():
        return str(shim)
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


def ingetrazo_home() -> Path | None:
    """IngeTrazo 安裝根目錄：`INGETRAZO_HOME` → 各平台預設位置。"""
    p = _env_path("INGETRAZO_HOME")
    if p and p.is_dir():
        return p
    cands = [
        Path(r"C:\Program Files\IngeTrazo"),
        Path(r"D:\Program Files\IngeTrazo"),
        Path.home() / "IngeTrazo",
        Path("/opt/IngeTrazo"),
        Path("/Applications/IngeTrazo.app/Contents/MacOS"),
    ]
    for c in cands:
        if c.is_dir():
            return c
    return None


def ingetrazo_mcp() -> str | None:
    """IngeTrazo 的 MCP 橋接伺服器：`INGETRAZO_MCP` → 安裝目錄 → PATH。

    這個執行檔只是 stdio → 本機 TCP（預設 `127.0.0.1:4763`）的橋。
    工具要真的能用，IngeTrazo GUI 必須開著、已開文件，並在
    「擴充功能 ▸ AI Bridge (MCP)」啟動橋接；否則 `tools/list` 仍可通，
    但每次工具呼叫都會回「請先啟動 AI Bridge」。
    """
    p = _env_path("INGETRAZO_MCP")
    if p:
        return str(p) if p.is_file() else None
    home = ingetrazo_home()
    if home:
        found = _first_existing([home / "ingetrazo-mcp.exe", home / "ingetrazo-mcp"])
        if found:
            return found
    return shutil.which("ingetrazo-mcp") or shutil.which("ingetrazo-mcp.exe")


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


def cadcraft_studio_exe() -> str | None:
    """CadCraft Studio 執行檔（GUI 視窗，供人類檢視／互動驗收）：`CADCRAFT_STUDIO_EXE` → 常見安裝位置 → PATH。

    注意：此為 WebView2/WebAssembly 視窗殼層，無 headless CLI，不可用於背景批次轉檔。
    AI 背景轉檔與出圖一律使用 `artcraft_cli("CADCraft")`（即 `cadcraft-cli.exe`）。
    詳細分工規範見 `docs/CadCraft與CadCraft_Studio分工規範.md`。
    """
    p = _env_path("CADCRAFT_STUDIO_EXE")
    if p:
        return str(p) if p.is_file() else None
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    found = _first_existing([
        Path(r"C:\Program\CadCraft Studio\CadCraft Studio.exe"),
        Path(r"C:\Program Files\CadCraft Studio\CadCraft Studio.exe"),
        local_app / "Programs" / "CadCraft Studio" / "CadCraft Studio.exe",
        Path.home() / "CadCraft Studio" / "CadCraft Studio.exe",
        Path("/Applications/CadCraft Studio.app/Contents/MacOS/CadCraft Studio"),
    ])
    return found or shutil.which("cadcraft-studio") or shutil.which("CadCraft Studio.exe")


_BLENDER_CACHE: dict[str, str | None] = {}


def blender_exe() -> str | None:
    r"""Blender 執行檔（選用）：環境變數 → **MSIX 套件** → PATH → 常見安裝位置。

    本機 Blender 是 Microsoft Store（MSIX）封裝，exe 位於
    `C:\Program Files\WindowsApps\...\Blender\blender.exe`，
    只掃 `Program Files\Blender Foundation` 會得到「未安裝」的**假陰性**，
    因此這裡改為優先呼叫 `blender_runner.find_blender()`（會查 Get-AppxPackage）。
    """
    if "v" in _BLENDER_CACHE:
        return _BLENDER_CACHE["v"]
    exe: str | None = None
    for key in ("BLENDER", "CIVIL_AI_BLENDER"):
        cand = os.environ.get(key)
        if cand and Path(cand).exists():
            exe = cand
            break
    if exe is None:
        try:  # MSIX：延遲載入，避免循環匯入
            try:
                from blender.blender_runner import find_blender  # type: ignore
            except ImportError:
                import sys as _sys
                _tools = str(Path(__file__).resolve().parent)
                if _tools not in _sys.path:
                    _sys.path.insert(0, _tools)
                from blender.blender_runner import find_blender  # type: ignore
            found = (find_blender() or {}).get("exe")
            if found and Path(found).exists():
                exe = found
        except Exception:
            exe = None
    if exe is None:
        cands = [Path("/Applications/Blender.app/Contents/MacOS/Blender"), Path("/usr/bin/blender")]
        for r in (Path(r"C:\Program Files\Blender Foundation"),
                  Path(r"D:\Program Files\Blender Foundation")):
            if r.is_dir():
                cands += sorted(r.glob("Blender */blender.exe"), reverse=True)
        exe = _first_existing(cands) or shutil.which("blender")
    _BLENDER_CACHE["v"] = exe
    return exe


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
    bldg_dir = DATA / "臺中市建物"
    bldg_archive = bldg_dir / "臺中市建物_114.7z"
    bldg_shps = list(bldg_dir.rglob("*.shp")) if bldg_dir.is_dir() else []
    return {
        "root": str(ROOT),
        "python": python_exe(),
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "platform": sys.platform,
        "regs_db": str(regs_db()),
        "regs_db_exists": regs_db().exists(),
        "verified_dir": str(verified_dir()),
        "verified_exists": verified_dir().is_dir(),
        "taichung_bldg_archive": str(bldg_archive) if bldg_archive.is_file() else None,
        "taichung_bldg_shp": str(bldg_shps[0]) if bldg_shps else None,
        "temp": str(TEMP),
        "out": str(OUT),
        "artcraft_home": str(art) if art else None,
        "artcraft": {a: artcraft_cli(a) for a in ARTCRAFT_APPS},
        "cadcraft_studio": cadcraft_studio_exe(),
        "accoreconsole": accoreconsole(),
        "solidcraft": solidcraft_cli(),
        "ingetrazo_home": str(ingetrazo_home()) if ingetrazo_home() else None,
        "ingetrazo_mcp": ingetrazo_mcp(),
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
    if info["taichung_bldg_shp"]:
        print(f"臺中建物SHP: {info['taichung_bldg_shp']}  [OK]")
    elif info["taichung_bldg_archive"]:
        print(f"臺中建物SHP: 待解壓！隨 repo 已附 {info['taichung_bldg_archive']}，請就地解壓縮至 data/臺中市建物/")
    else:
        print("臺中建物SHP: —（缺少 data/臺中市建物/臺中市建物_114.7z）")
    print(f"ArtCraft   : {info['artcraft_home'] or '（未安裝，或設定 ARTCRAFT_HOME）'}")
    for k, v in info["artcraft"].items():
        print(f"  {k:<12} {'OK  ' + v if v else '—'}")
    if info.get("cadcraft_studio"):
        print(f"CadCraftStudio: {info['cadcraft_studio']}  [OK]（人類可視化驗收視窗，無 headless CLI）")
    else:
        print("CadCraftStudio: —（未安裝或未設定 CADCRAFT_STUDIO_EXE）")
    acc_desc = info['accoreconsole']
    if not acc_desc:
        if info["artcraft"].get("CADCraft"):
            acc_desc = "—（未安裝 AutoCAD；已安裝 CADCraft，可相容>80%功能並產出 DWG 與出圖）"
        else:
            acc_desc = "—（未安裝 AutoCAD；沒有也能產 DXF，但缺少 DWG 轉檔工具）"
    print(f"accoreconsole: {acc_desc}")
    print(f"SolidCraft   : {info['solidcraft'] or '—（選用）'}")
    iz = info["ingetrazo_mcp"]
    print(f"IngeTrazo    : {info['ingetrazo_home'] or '—（選用；未安裝或設定 INGETRAZO_HOME）'}")
    print(f"  MCP 橋     : {iz or '—（找不到 ingetrazo-mcp；設定 INGETRAZO_MCP）'}")
    print(f"Blender      : {info['blender'] or '—（選用）'}")
    print(f"CAD 字體庫   : {info['cad_fonts'] or '—（TOMO 樣式的 gbenor.shx / CHINA1.SHX 找不到）'}")
    for k, v in info["cad_font_files"].items():
        print(f"  {k:<14} {v or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
