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

    python tools/project_paths.py                    # 印出所有解析結果
    python tools/project_paths.py --versions         # 即時查詢各 CLI 版本（僅供追溯）
    python tools/project_paths.py --json             # 給安裝腳本吃的 JSON
    python tools/project_paths.py --install          # 自動補齊缺漏的第三方工具（免 root）
    python tools/project_paths.py --install --dry-run # 只看安裝計畫，不下載
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def _norm_app(s: str) -> str:
    """應用程式資料夾／檔名的比對鍵：去空格、點、連字號、底線並轉小寫。

    「Open CAD Studio.TW」→ `opencadstudiotw`；「Open CalcSheet Studio TW」→ `opencalcsheetstudiotw`。
    """
    return re.sub(r"[ ._\-]", "", s).lower()


def _win_program_roots() -> list[Path]:
    """Windows 安裝根目錄（只取環境變數所指，不寫死磁碟代號）。"""
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots += [local, str(Path(local) / "Programs")]
    out, seen = [], set()
    for r in roots:
        if r and r not in seen and Path(r).is_dir():
            seen.add(r)
            out.append(Path(r))
    return out


def _win_app_dirs(key: str) -> list[Path]:
    """Windows 下比對鍵**完全等於** key 的安裝資料夾（不用 startswith，避免上游／TW 互相誤認）。"""
    hits = []
    for root in _win_program_roots():
        try:
            for d in sorted(root.iterdir()):
                if d.is_dir() and _norm_app(d.name) == key:
                    hits.append(d)
        except OSError:
            continue
    return hits


def _linux_desktop_exec(key: str) -> str | None:
    """Linux：從 .desktop 檔（檔名比對鍵＝key）取 Exec 指向的執行檔。

    Tauri／deb 以 productName 命名 desktop 檔（如 `Open CalcSheet Studio TW.desktop`），
    但二進位檔名沿用 Cargo 套件名，與上游**同名**；只能靠 desktop 檔分辨是哪一版。
    """
    for base in (Path("/usr/share/applications"), Path.home() / ".local" / "share" / "applications"):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*.desktop")):
            if _norm_app(f.stem) != key:
                continue
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("Exec="):
                        exe = line[5:].strip().split()[0].strip('"')
                        w = exe if Path(exe).is_file() else shutil.which(exe)
                        if w:
                            return str(w)
            except OSError:
                continue
    return None


#: 本專案只綁定使用者 fork 的「本地化版」應用程式（2026-11-10 定案）。
#: 上游版與 TW 版在本機並行安裝，差別是安裝資料夾／識別碼，**一律不得退回上游版**。
OCS_TW_KEY = "opencadstudiotw"            # 資料夾「Open CAD Studio.TW」、執行檔 OpenCADStudio.TW.exe
OCS_UPSTREAM_KEY = "opencadstudio"        # 上游「Open CAD Studio」（只用來提示，不採用）
OCSS_TW_KEY = "opencalcsheetstudiotw"     # 資料夾「Open CalcSheet Studio TW」
OCSS_UPSTREAM_KEY = "opencalcsheetstudio"
OCSS_TW_APP_ID = "tw.opencalcsheet.studio"            # TW 版 Tauri identifier
OCSS_UPSTREAM_APP_ID = "studio.openstructuralcalculation.app"


def opencadstudio_exe() -> str | None:
    """OpenCADStudio **TW 版**（fork `tutumomo/OpenCADStudio`，Big5 SHX 修正）執行檔。

    只認本地化版，不退回上游版：
      1. `OPENCADSTUDIO_EXE`（明確指定時照用，責任在設定者）
      2. Windows：`ProgramFiles` 等根目錄下比對鍵＝`opencadstudiotw` 的資料夾
         （實際為「Open CAD Studio.TW」）內的 `OpenCADStudio.TW.exe`
      3. macOS：`/Applications`、`~/Applications` 下比對鍵＝`opencadstudiotw` 的 .app
      4. Linux／其他：`--install` 產的 `~/.local/bin/opencadstudio-tw`、
         `~/.local/opt/opencadstudio-tw-*/` 內的 AppImage，再找 PATH 的 `opencadstudio-tw`
    未安裝回傳 None；補裝用 `python tools/project_paths.py --install`。
    設定檔夾與上游共用 `%APPDATA%/OpenCADStudio`（fork 未改 `config_dir()`）。
    """
    p = _env_path("OPENCADSTUDIO_EXE")
    if p and p.is_file():
        return str(p)

    if os.name == "nt":
        for d in _win_app_dirs(OCS_TW_KEY):
            for c in sorted(d.glob("*.exe")):
                if _norm_app(c.stem) == OCS_TW_KEY:
                    return str(c)

    # macOS：`Contents/MacOS/<App>` 可能只是 launcher stub，被 symlink 到別處執行會噴
    # "failed to execute the application"；優先挑名字帶 -App 的主程式，否則取最大檔。
    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            if not root.is_dir():
                continue
            for app in sorted(root.glob("*.app")):
                if _norm_app(app.stem) != OCS_TW_KEY:
                    continue
                cands = [c for c in (app / "Contents" / "MacOS").glob("*") if c.is_file()]
                app_bin = [c for c in cands if c.stem.lower().endswith("-app")]
                if app_bin or cands:
                    return str(max(app_bin or cands, key=lambda q: q.stat().st_size))

    home = Path.home()
    if os.name != "nt":
        c = home / ".local" / "bin" / "opencadstudio-tw"
        if c.exists():
            return str(c)
        opt = home / ".local" / "opt"
        if opt.is_dir():
            for d in sorted(opt.glob("opencadstudio-tw-*"), reverse=True):
                for pat in ("**/AppRun", "**/*.AppImage"):
                    for c in sorted(d.glob(pat)):
                        if c.is_file():
                            return str(c)
        w = shutil.which("opencadstudio-tw")
        if w:
            return str(w)
    return None


def upstream_only_hint(tool: str) -> str | None:
    """若本機只有上游版（沒有 TW 版），回傳一句提示；否則 None。只用於回報，不影響解析。"""
    if os.name != "nt":
        return None
    if (opencadstudio_exe() if tool == "opencadstudio" else opencalcsheet_exe()):
        return None
    if tool == "opencadstudio":
        up =[d for d in _win_app_dirs(OCS_UPSTREAM_KEY) if (d / "OpenCADStudio.exe").is_file()]
    else:
        up = [d for d in _win_app_dirs(OCSS_UPSTREAM_KEY) if (d / "open-calcsheet-studio.exe").is_file()]
    if up:
        return f"偵測到上游版 {up[0]}，本專案不採用（只綁 TW 版）"
    return None


def opencalcsheet_exe() -> str | None:
    """Open CalcSheet Studio **TW 版**（fork `tutumomo/Open-CalcSheet-Studio`）執行檔。

    只認本地化版，不退回上游版（兩者執行檔同名 `open-calcsheet-studio`，只能靠
    安裝資料夾／.app／desktop 檔名分辨）：
      1. `OCSS_EXE`（明確指定時照用）
      2. Windows：比對鍵＝`opencalcsheetstudiotw` 的資料夾（實際為「Open CalcSheet Studio TW」）
         內的 `open-calcsheet-studio.exe`（排除 uninstall.exe）
      3. macOS：比對鍵相同的 .app（「Open CalcSheet Studio TW.app」，尚未實測）
      4. Linux：比對鍵相同的 .desktop 檔的 Exec → `~/.local/bin/open-calcsheet-studio-tw`
         → PATH 的 `open-calcsheet-studio-tw`（尚未以 TW 版實測）
    未安裝回傳 None。**不得執行它的 `--version`／`--help`（會卡住）。**
    """
    p = _env_path("OCSS_EXE")
    if p and p.is_file():
        return str(p)

    if os.name == "nt":
        for d in _win_app_dirs(OCSS_TW_KEY):
            for c in sorted(d.glob("*.exe")):
                if _norm_app(c.stem) == "opencalcsheetstudio":
                    return str(c)

    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            if not root.is_dir():
                continue
            for d in sorted(root.glob("*.app")):
                if _norm_app(d.stem) != OCSS_TW_KEY:
                    continue
                for c in sorted((d / "Contents" / "MacOS").glob("*")):
                    if c.is_file():
                        return str(c)

    if sys.platform.startswith("linux"):
        exe = _linux_desktop_exec(OCSS_TW_KEY)
        if exe:
            return exe
        # 無 root 用 `dpkg-deb -x` 解壓時，請把執行檔連結成 `open-calcsheet-studio-tw`（與上游區隔）
        c = Path.home() / ".local" / "bin" / "open-calcsheet-studio-tw"
        if c.exists():
            return str(c)
        w = shutil.which("open-calcsheet-studio-tw")
        if w:
            return str(w)
    return None


def ocss_settings_dir() -> Path:
    """Open CalcSheet Studio **TW 版**的使用者資料夾（preferences.json 所在）。

    TW 版 Tauri identifier 為 `tw.opencalcsheet.studio`（上游為
    `studio.openstructuralcalculation.app`，兩版 token 不同，不可混用）。各平台慣例路徑：
    Windows `%APPDATA%`、macOS `~/Library/Application Support`、Linux `~/.local/share`（Tauri app_data_dir）。
    可用 `OCSS_SETTINGS_DIR` 覆寫。資料夾不存在時仍回傳路徑（呼叫端自行判斷）。
    """
    p = _env_path("OCSS_SETTINGS_DIR")
    if p:
        return p
    app_id = OCSS_TW_APP_ID
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / app_id


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
        "opencadstudio": opencadstudio_exe(),
        "opencalcsheet": opencalcsheet_exe(),
        "ocss_settings": str(ocss_settings_dir()),
        "ingetrazo_home": str(ingetrazo_home()) if ingetrazo_home() else None,
        "ingetrazo_mcp": ingetrazo_mcp(),
        "blender": blender_exe(),
        "cad_fonts": str(cad_fonts_dir()) if cad_fonts_dir() else None,
        "cad_font_files": {n: (str(cad_font(n)) if cad_font(n) else None)
                           for n in ("gbenor.shx", "CHINA1.SHX")},
    }



def cli_version(cmd: str | None, timeout: float = 8.0) -> str:
    """即時查詢外部 CLI 的版本字串；找不到或執行失敗回空字串（不丟錯）。

    各套 `--version` 形式不一（有的只認 `version`），因此兩種都試。
    """
    if not cmd:
        return ""
    for argv in ([cmd, "--version"], [cmd, "version"]):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except Exception:
            continue
        lines = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        if lines:
            return lines[0].strip()
    return ""


def _auto_installable_missing(info: dict) -> list[str]:
    """回傳目前缺少、但可由 toolchain 自動下載安裝的工具名稱清單。"""
    missing = []
    # OpenCADStudio
    if not info.get("opencadstudio"):
        missing.append("OpenCADStudio")
    # Open CalcSheet Studio（2026-11-10 起列為必備工具）
    if not info.get("opencalcsheet"):
        missing.append("OpenCalcSheet")
    return missing

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="印出專案路徑與外部工具的解析結果；加 --install 可自動補裝缺漏工具")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（給安裝腳本用）")
    ap.add_argument("--install", action="store_true",
                    help="偵測並自動安裝缺漏的第三方工具（免 root，來源為官方 GitHub Releases）")
    ap.add_argument("--dry-run", action="store_true", help="搭配 --install：只印計畫，不下載")
    ap.add_argument("--only", metavar="NAME", help="搭配 --install：只處理某一個工具")
    ap.add_argument("--configure", action="store_true",
                    help="只寫入工具設定（如 OpenCADStudio 的 TOMO 字型夾與 CTB 樣式夾），不下載")
    ap.add_argument("--versions", action="store_true",
                    help="即時查詢各 CLI 版本（僅供追溯，不作相容性檢核）")
    a = ap.parse_args(argv)

    if a.install:
        sys.path.insert(0, str(TOOLS / "install"))
        from toolchain import check_and_install
        return check_and_install(dry=a.dry_run, only=a.only)

    if a.configure:
        sys.path.insert(0, str(TOOLS / "install"))
        from toolchain import configure_opencadstudio
        ok = configure_opencadstudio(quiet=False)
        return 0 if ok else 1

    if a.versions:
        info = report()
        print("工具版本（即時查詢；僅供追溯，不作相容性檢核）")
        print("ArtCraft")
        for name, path in info["artcraft"].items():
            ver = cli_version(path) or "—"
            print(f"  {name:<14} {ver:<28} {path or '（未安裝）'}")
        print("其他")
        for name, key in (("SolidCraft", "solidcraft"),
                          ("OpenCADStudio", "opencadstudio"),
                          ("Blender", "blender")):
            path = info[key]
            ver = cli_version(path) or "—"
            print(f"  {name:<14} {ver:<28} {path or '（未安裝）'}")
        print("（版本號會隨 app 更新變動；固定基準見 docs/已驗證環境快照.md）")
        return 0

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
    if info.get("opencadstudio"):
        print(f"OpenCADStudio: {info['opencadstudio']}  [OK]（TW 版；DWG/DXF、CTB 出圖、MCP）")
    else:
        print("OpenCADStudio: —（必備；TW 版未安裝。跑 python tools/project_paths.py --install 自動補齊）")
    h = upstream_only_hint("opencadstudio")
    if h:
        print(f"  · {h}")
    if info.get("opencalcsheet"):
        print(f"OpenCalcSheet: {info['opencalcsheet']}  [OK]（TW 版；須開啟程式才有 API 3879）")
    else:
        print("OpenCalcSheet: —（必備；TW 版未安裝。跑 python tools/project_paths.py --install 自動補齊，或設定 OCSS_EXE）")
    h = upstream_only_hint("opencalcsheet")
    if h:
        print(f"  · {h}")
    print(f"SolidCraft   : {info['solidcraft'] or '—（選用）'}")
    iz = info["ingetrazo_mcp"]
    print(f"IngeTrazo    : {info['ingetrazo_home'] or '—（選用；未安裝或設定 INGETRAZO_HOME）'}")
    print(f"  MCP 橋     : {iz or '—（找不到 ingetrazo-mcp；設定 INGETRAZO_MCP）'}")
    print(f"Blender      : {info['blender'] or '—（選用）'}")
    print(f"CAD 字體庫   : {info['cad_fonts'] or '—（TOMO 樣式的 gbenor.shx / CHINA1.SHX 找不到）'}")
    for k, v in info["cad_font_files"].items():
        print(f"  {k:<14} {v or '—'}")

    missing_apps = _auto_installable_missing(info)
    if missing_apps:
        print()
        print(f"檢測到缺少可自動安裝的工具：{'、'.join(missing_apps)}")
        # 判斷是否為互動式終端機或非互動環境
        auto_yes = os.environ.get("CIVIL_AI_AUTO_INSTALL", "").lower() in ("1", "true", "yes")
        should_install = False
        if auto_yes:
            print("（偵測到 CIVIL_AI_AUTO_INSTALL=1，自動同意安裝）")
            should_install = True
        else:
            try:
                ans = input(f"是否立即幫您自動下載並安裝 {'、'.join(missing_apps)}？[y/N] ").strip().lower()
                should_install = (ans in ("y", "yes"))
            except (EOFError, KeyboardInterrupt):
                print()
                print("提示：在命令列執行 `python tools/project_paths.py --install` 即可一鍵補齊。")
                should_install = False

        if should_install:
            print()
            print("開始自動安裝...")
            sys.path.insert(0, str(TOOLS / "install"))
            from toolchain import check_and_install
            rc = check_and_install()
            return rc
        else:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
