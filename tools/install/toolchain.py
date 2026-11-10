"""工具鏈偵測與免 root 自動安裝（跨 Windows／Linux／macOS）。

為什麼要這個模組
----------------
專案 clone 到新電腦後，`tools/project_paths.py` 只會「回報」缺什麼，不會安裝。
使用者必須自己去找 GitHub Releases、自己解包、自己建 symlink，才知道怎麼補。
本模組把這一步變成可執行：

    python tools/project_paths.py --install            # 補齊所有缺漏
    python tools/project_paths.py --install --dry-run  # 只看計畫，不下載
    python tools/project_paths.py --install --only OpenCADStudio

安裝規範（沿用 2026-11-03 使用者約定）
--------------------------------------
1. **免 root**：成品一律放 `~/.local/opt/<name>-<ver>/`（Windows 為 `%LOCALAPPDATA%\\<name>-<ver>`）
2. **symlink 暴露命令**：`~/.local/bin/<name>`（Windows 為 `~/.local/bin/<name>.cmd`）
3. **衝突不直接覆蓋**：偵測到既有 symlink 時，改建成 `<name>-new`，並印出
   `mv` 備份替換指令交由使用者確認（2026-11-08 定案）
4. **跨裝置保守**：安裝路徑落在 Windows 分割區／UNC／WSL 掛載／網路共享時，
   不直接寫 symlink，改產出 `_install_links.sh`（或 `.ps1`）交由使用者執行
5. **下載來源**：官方 GitHub Releases（2026-11-08 定案，不依賴內網 NAS）

設計原則
--------
* 只用標準函式庫（urllib／platform／shutil／zipfile／tarfile），不新增 pip 依賴。
* 每個工具都是「偵測函式 + 資產樣式」兩段式，新增工具只要加一筆 manifest。
* 下載到 `_temp/install/` 再搬進 `~/.local/opt/`，中途失敗不會留下半套。
* 全部步驟印中文，失敗給可執行的補救指令，不靜默跳過。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 基本環境

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

MACHINE = platform.machine().lower()
# 統一的架構代號：aarch64 / x86_64
if MACHINE in ("arm64", "aarch64", "armv8l"):
    ARCH = "aarch64"
elif MACHINE in ("x86_64", "amd64", "x64"):
    ARCH = "x86_64"
else:
    ARCH = MACHINE  # 其他架構照實回報，讓 manifest 判斷沒有資產可下載


def local_opt_dir() -> Path:
    """免 root 安裝根目錄。Linux／macOS 依使用者約定用 `~/.local/opt`。"""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "opencad-toolchain"
    return Path.home() / ".local" / "opt"


def local_bin_dir() -> Path:
    """命令暴露目錄。"""
    if IS_WIN:
        return Path.home() / ".local" / "bin"
    return Path.home() / ".local" / "bin"


def _temp_install_dir() -> Path:
    """下載暫存區。放在系統 temp，避免污染專案 `_temp/`。"""
    d = Path(tempfile.gettempdir()) / "civil-toolchain"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- 網路工具


def _http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CivilDesignWorkBench-Toolchain/1.0",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release_tag(repo: str) -> str | None:
    """取得最新 release tag，三條路徑依序嘗試。

    1. `gh release view`（有登入時最穩，不受匿名速率限制）
    2. GitHub API `/releases/latest`
    3. 追蹤 `/releases/latest` 的 302 轉址，從 Location 取 tag
    """
    gh = shutil.which("gh")
    if gh:
        try:
            p = subprocess.run([gh, "release", "list", "-R", repo, "--limit", "1",
                                "--json", "tagName", "--jq", ".[0].tagName"],
                               capture_output=True, text=True, timeout=40)
            tag = (p.stdout or "").strip()
            if p.returncode == 0 and tag:
                return tag
        except Exception:
            pass
    try:
        d = _http_json(f"https://api.github.com/repos/{repo}/releases/latest")
        if d.get("tag_name"):
            return d["tag_name"]
    except Exception:
        pass
    try:
        req = urllib.request.Request(f"https://github.com/{repo}/releases/latest",
                                     headers={"User-Agent": "CivilDesignWorkBench-Toolchain/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            m = re.search(r"/releases/tag/([^/?#]+)", r.geturl())
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def download(url: str, dest: Path, quiet: bool = False, retries: int = 6) -> Path:
    """下載到 dest；有 Content-Length 就印進度百分比。

    GitHub 的 CDN 偶爾會讓連線停住不回資料（實測卡在 40.9/68.5 MB 不動），
    所以每次讀取都有 30 秒逾時；逾時或斷線就用 HTTP Range 從已下載處續傳，最多重試 `retries` 次。
    伺服器不支援 Range（回 200 而非 206）時，該次重新從頭下載。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)          # 只在本次呼叫內續傳，不沿用舊的殘檔
    got, total, last_err = 0, 0, None
    for attempt in range(1, retries + 1):
        headers = {"User-Agent": "CivilDesignWorkBench-Toolchain/1.0"}
        if got:
            headers["Range"] = f"bytes={got}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                if got and r.status != 206:      # 不支援續傳 → 重來
                    got = 0
                length = int(r.headers.get("Content-Length") or 0)
                if length:
                    total = got + length
                with open(dest, "ab" if got else "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if total and not quiet:
                            print(f"\r    下載 {got * 100 // total:3d}%  "
                                  f"{got/1048576:8.1f} / {total/1048576:.1f} MB",
                                  end="", flush=True)
            if total and got < total:
                raise OSError(f"連線提前結束（{got}/{total} bytes）")
            if not quiet:
                print()
            return dest
        except (OSError, urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if not quiet:
                print(f"\n    ! 下載中斷（{type(e).__name__}: {e}），第 {attempt}/{retries} 次，"
                      f"從 {got/1048576:.1f} MB 續傳…")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"下載失敗（重試 {retries} 次仍中斷）：{last_err}")


# ---------------------------------------------------------------- 工具清單


@dataclass
class Tool:
    """一個可安裝的工具。"""
    key: str                      # 顯示名稱，也是命令名
    repo: str                     # GitHub owner/repo
    asset_patterns: dict          # {(os, arch): [regex, ...]}；regex 對 release 資產檔名比對
    kind: str                     # appimage / zip / tar / dmg / msi / exe
    bin_stem: str | None = None   # 安裝後的執行檔名（預設同 key 小寫）
    note: str = ""
    required: bool = True
    manual_hint: str = ""         # 無法自動安裝時的指引
    verify_argv: list[str] = field(default_factory=list)  # 驗證用參數，如 ["--version"]
    verify_must_contain: str = ""                          # 輸出須包含的字串
    # 自訂偵測函式：回傳執行檔路徑或 None。給「安裝版路徑帶空格、不在 PATH」的工具用，
    # 例如 OCSS 由 project_paths.opencalcsheet_exe() 解析（嚴禁在此寫死安裝路徑）。
    detect: Callable[[], str | None] | None = None
    # 同一 release 內的校驗檔名（內容為 `<sha256>  <檔名>` 逐行）；有設就下載後比對，不符即中止。
    checksum_asset: str = ""
    # macOS 專用：dmg 內 .app 複製到 /Applications 時要用的名稱（例如 "Open CAD Studio TW.app"）。
    # 為什麼：fork 的 dmg 內 app 仍叫 OpenCADStudio.app，解析器（project_paths）只認名稱含 TW 的 .app，
    # 不改名就會被當成「未安裝」；改名後也不會覆蓋上游同名 app。空字串＝沿用 dmg 內名稱。
    macos_app_name: str = ""


#: OpenCADStudio 資產命名（實測 v2026.44）：
#:   OpenCADStudio-v2026.44-linux-aarch64.AppImage
#:   OpenCADStudio-v2026.44-linux-x86_64.AppImage
#:   OpenCADStudio-v2026.44-macos-arm64.dmg
#:   OpenCADStudio-v2026.44-windows-x86_64-portable.exe（另有 -installer.msi，不用它）
#:
#: **2026-11-10 起 Windows 改取 fork 的 MSI**（不再取 portable exe）：
#:   - fork 自 v2026.45.2 起 MSI 安裝為「Open CAD Studio.TW」（`OpenCADStudio.TW.exe`，獨立 UpgradeCode），
#:     與上游並行共存；本專案只綁這個本地化版，portable exe 檔名與上游無從分辨，故不用。
#:   - 舊紀錄：`msiexec /i ... /qn` 非管理員回 1603。因此改用 `/passive`（基本 UI，可跳 UAC 請使用者核准）。
#:   - 偵測走 project_paths.opencadstudio_exe()（只認 TW 版），直接啟動 exe，`taskkill /T` 殺得到本體。
#: Linux 仍取 AppImage，裝到 `~/.local/opt/opencadstudio-tw-<ver>/`、命令 `~/.local/bin/opencadstudio-tw`，
#: 與舊的上游 `opencadstudio-*` 區隔。
#: macOS：取 fork 的 `*-macos-arm64.dmg`（v2026.45.3 起確認有發行），其內 app 叫 `OpenCADStudio.app`，
#: 安裝時改名為 `/Applications/Open CAD Studio TW.app`（見 Tool.macos_app_name），解析器才認得；
#: 命令為 `~/.local/bin/opencadstudio-tw`，指向 app 內可獨立執行的 `OpenCADStudio-App`。
def _tools_on_path() -> None:
    tools_dir = Path(__file__).resolve().parent.parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))


def _detect_opencalcsheet() -> str | None:
    """OCSS 偵測：交給 project_paths.opencalcsheet_exe()（只認 TW 版；不跑 --version，會卡住）。"""
    _tools_on_path()
    from project_paths import opencalcsheet_exe
    return opencalcsheet_exe()


def _detect_artcraft_launcher() -> str | None:
    """ArtCraft Launcher 偵測：交給 project_paths.artcraft_launcher_exe()（不跑 --version，GUI 程式）。"""
    _tools_on_path()
    from project_paths import artcraft_launcher_exe
    return artcraft_launcher_exe()


def _detect_blender() -> str | None:
    """Blender 偵測：交給 project_paths.blender_exe()。

    MSIX（Microsoft Store）版的 exe 在 `WindowsApps` 底下，只掃
    `Program Files\\Blender Foundation` 會假陰性，所以必須走這條（含
    Get-AppxPackage 查詢）。不跑 `--version`，只看檔案是否存在。
    """
    _tools_on_path()
    from project_paths import blender_exe
    return blender_exe()


def _detect_opencadstudio() -> str | None:
    """OCS 偵測：交給 project_paths.opencadstudio_exe()（只認 TW 版）。"""
    _tools_on_path()
    from project_paths import opencadstudio_exe
    return opencadstudio_exe()


#: Open CalcSheet Studio TW 資產命名（實測 v2026.45.2-tw.4）：
#:   Open.CalcSheet.Studio.TW_2026.45.2_x64-setup.exe   Windows NSIS 安裝程式 → 「Open CalcSheet Studio TW」
#:   Open.CalcSheet.Studio.TW_2026.45.2_aarch64.dmg     macOS（Apple Silicon）
#:   Open.CalcSheet.Studio.TW_2026.45.2_amd64.deb／_arm64.deb  Linux
#:   SHA256SUMS.txt                                     校驗檔（檔名以空格表示，資產名以點表示）
#: 樣式刻意要求檔名含 `.TW_`，舊版（未改識別碼、會覆蓋上游）的 release 一律不取。
#:
#: 安裝策略（依資產副檔名分流，tool.kind="installer"）：
#:   · Windows：下載 → SHA256 校驗 → `setup.exe /S` 靜默安裝 → 以 opencalcsheet_exe() 驗證。
#:     不執行 `--version`／`--help`（實測會卡住）。若安裝程式要求 UAC，請使用者核准。
#:   · macOS：沿用 dmg 流程（掛載 → 複製 .app → symlink）。**尚未在 macOS 實測**。
#:   · Linux：.deb 試 `sudo -n apt-get install`（免密碼 sudo 才成功），否則印指令；裝好後補防黑屏啟動腳本與選單項目。
#: 已安裝則略過，不自動升級。
TOOLS: list[Tool] = [
    Tool(
        key="OpenCalcSheet",
        repo="tutumomo/Open-CalcSheet-Studio",
        asset_patterns={
            ("windows", "x86_64"): [r"\.TW_.*x64-setup\.exe$"],
            ("macos", "aarch64"): [r"\.TW_.*aarch64\.dmg$"],
            ("linux", "x86_64"): [r"\.TW_.*amd64\.deb$"],
            ("linux", "aarch64"): [r"\.TW_.*arm64\.deb$"],
        },
        kind="installer",
        bin_stem="open-calcsheet-studio-tw",
        note="開放計算環境／台灣版結構計算書；第二套獨立算法，供交叉驗算（tools/crosscheck/）",
        manual_hint="請至 https://github.com/tutumomo/Open-CalcSheet-Studio/releases 下載對應平台安裝檔，"
                    "裝好後可用環境變數 OCSS_EXE 指定執行檔",
        detect=_detect_opencalcsheet,
        checksum_asset="SHA256SUMS.txt",
    ),
    Tool(
        key="OpenCADStudio",
        repo="tutumomo/OpenCADStudio",   # 2026-11-10 起改用 fork（Big5 SHX 大字體修正，中文才不亂碼）；上游 HakanSeven12/OpenCADStudio
        asset_patterns={
            ("linux", "aarch64"): [r"linux-aarch64\.AppImage$"],
            ("linux", "x86_64"): [r"linux-x86_64\.AppImage$"],
            ("macos", "aarch64"): [r"macos-arm64\.dmg$"],
            ("macos", "x86_64"): [r"macos-x86_64\.dmg$"],
            ("windows", "x86_64"): [r"windows-x86_64-installer\.msi$"],
            ("windows", "aarch64"): [r"windows-arm64-installer\.msi$"],
        },
        kind="appimage",
        bin_stem="opencadstudio-tw",
        note="AutoCAD 開源平替（TW 版，Big5 SHX 修正）；DWG/DXF 原生讀寫、CTB 出圖、MCP 介面",
        manual_hint="請至 https://github.com/tutumomo/OpenCADStudio/releases 下載 fork 版"
                    "（Windows 取 *-installer.msi，裝到「Open CAD Studio.TW」），"
                    "或以環境變數 OPENCADSTUDIO_EXE 指定 TW 版執行檔",
        verify_argv=["--version"],
        verify_must_contain="OpenCADStudio",
        detect=_detect_opencadstudio,
        macos_app_name="Open CAD Studio TW.app",
    ),
    # ArtCraft Launcher：Craft App Suite（約 17 套開源軟體，可平替 Adobe／Office／CAD）的安裝、更新、開啟入口。
    # 它是 GUI，沒有 headless 安裝子命令，各 App 要在它的視窗裡按「Install」；因此本身也不自動安裝（kind=manual），
    # 只偵測並印取得指引。偵測交給 project_paths.artcraft_launcher_exe()。
    Tool(
        key="ArtCraft Launcher",
        repo="storytold/craft-launcher",
        asset_patterns={},
        kind="manual",
        bin_stem="artcraft-launcher",
        required=True,
        note="Craft App Suite 啟動器：安裝／更新 CADCraft、GridCraft、WordCraft、PdfCraft 等約 17 套開源軟體（必備）",
        manual_hint="請至 https://github.com/storytold/craft-launcher/releases/latest 下載對應平台版本"
                    "（Windows 取 *-windows-x64.msi；macOS 取 *-macos-universal.dmg；"
                    "Linux 取 *-linux-<x86_64|aarch64>.AppImage 或 .deb／.rpm），"
                    "裝好後開啟，在視窗內安裝各 App（至少 GridCraft、WordCraft）。"
                    "已裝在非標準位置時以環境變數 ARTCRAFT_LAUNCHER_EXE 指定",
        detect=lambda: _detect_artcraft_launcher(),
    ),
    # TextureCraft CLI：版本更新頻繁（0.4→0.5 僅隔三天），所以**不釘版本**：
    # 永遠取 repo 的最新 release（latest_release_tag），資產樣式也不含版號。
    # 呼叫端一律走 `~/.local/bin/texturecraft-cli`（artcraft_cli("TextureCraft")），不寫死任何版本路徑。
    # 已安裝則略過；要升級請先刪 `~/.local/bin/texturecraft-cli` 再跑 --install --only texturecraft-cli。
    # 目前只登記 macOS（universal zip）；其他平台資產名未實測，會走「選用工具、略過」。
    Tool(
        key="TextureCraft",
        repo="storytold/texturecraft",
        asset_patterns={
            ("macos", "aarch64"): [r"^texturecraft-cli-[\d.]+-macos-universal\.zip$"],
            ("macos", "x86_64"): [r"^texturecraft-cli-[\d.]+-macos-universal\.zip$"],
        },
        kind="zip",
        bin_stem="texturecraft-cli",
        required=False,
        note="3D 模型 PBR 材質貼圖、AO/Normal 烘焙與光追渲染（選用）",
        manual_hint="請至 https://github.com/storytold/texturecraft/releases 下載對應平台版本",
        checksum_asset="SHA256SUMS.txt",
    ),
    # Craft Anything CLI：同 TextureCraft，不釘版本、取最新 release；呼叫端走 `~/.local/bin/craft-anything-cli`。
    Tool(
        key="Craft Anything",
        repo="storytold/craft-anything",
        asset_patterns={
            ("macos", "aarch64"): [r"^craft-anything-cli-[\d.]+-macos-universal\.zip$"],
            ("macos", "x86_64"): [r"^craft-anything-cli-[\d.]+-macos-universal\.zip$"],
        },
        kind="zip",
        bin_stem="craft-anything-cli",
        required=False,
        note="ArtCraft 套裝的通用創作工具（選用）",
        manual_hint="請至 https://github.com/storytold/craft-anything/releases 下載對應平台版本",
        checksum_asset="SHA256SUMS.txt",
    ),
    Tool(
        key="Blender",
        repo="blender/blender",
        asset_patterns={},   # Blender 官方 release 不在 GitHub releases，見 manual_hint
        kind="manual",
        bin_stem="blender",
        detect=lambda: _detect_blender(),
        required=True,
        note="3D 景觀模擬與擬真算輪（必備）",
        manual_hint="Blender 由 blender.org 發行，GitHub repo 不含 release 資產；"
                    "請至 https://www.blender.org/download/ 下載（Windows 可用 Microsoft Store／winget，"
                    "macOS 可用 brew install --cask blender，Linux 可用套件管理器或 snap／flatpak），"
                    "已裝在非標準位置時以環境變數 BLENDER 指定",
    ),
    Tool(
        key="IngeTrazo",
        repo="",
        asset_patterns={},
        kind="manual",
        bin_stem="ingetrazo",
        required=False,
        note="道路橋樑 3D 設計（SketchUp 開源平替）",
        manual_hint="IngeTrazo 非 GitHub 發行；請依 docs/IngeTrazo操作指引.md 手動取得並設定 INGETRAZO_HOME",
    ),
]


# ---------------------------------------------------------------- 偵測


def _verify(path: str, tool: Tool) -> bool:
    """跑一次工具的版本指令，確認它真的是那個工具（不是同名冒牌貨）。

    沒有設定 verify_argv 的工具直接視為通過——驗證是加分，不是必要條件。
    """
    if not tool.verify_argv:
        return True
    try:
        p = subprocess.run([path] + tool.verify_argv, capture_output=True,
                           text=True, timeout=25)
        out = (p.stdout or "") + (p.stderr or "")
        if tool.verify_must_contain:
            return tool.verify_must_contain.lower() in out.lower()
        return p.returncode == 0
    except Exception:
        return False


def _tool_installed(tool: Tool) -> str | None:
    """回傳已安裝（且通過版本驗證）的執行檔路徑；未安裝回傳 None。"""
    if tool.detect is not None:
        # 自訂偵測（路徑嚴格比對，只認 TW 版）＋ 有設 verify_argv 時再做版本驗證
        try:
            p = tool.detect()
        except Exception:
            return None
        return p if p and _verify(p, tool) else None
    stem = tool.bin_stem or tool.key.lower()
    # 1. PATH
    for name in ([f"{stem}.cmd", f"{stem}.exe"] if IS_WIN else [stem]):
        w = shutil.which(name)
        if w and _verify(w, tool):
            return w
    # 2. ~/.local/bin
    lb = local_bin_dir()
    for name in ([f"{stem}.cmd", f"{stem}.exe"] if IS_WIN else [stem]):
        p = lb / name
        if p.exists() and _verify(str(p), tool):
            return str(p)
    # 3. macOS：/Applications/<Stem>.app（挑可獨立執行的那個，launcher stub 不行）
    if IS_MAC:
        app = Path("/Applications") / f"{tool.key}.app"
        if app.is_dir():
            exe = _macos_app_cli_exe(app, tool)
            if exe.is_file() and _verify(str(exe), tool):
                return str(exe)
    # 4. ~/.local/opt/<stem>-*/ 內找執行檔
    opt = local_opt_dir()
    if opt.is_dir():
        for d in sorted(opt.glob(f"{stem}-*"), reverse=True):
            for cand in d.rglob("*"):
                if cand.is_file() and cand.name.lower().startswith(stem):
                    if _verify(str(cand), tool):
                        return str(cand)
    return None


def detect_all() -> dict[str, str | None]:
    return {t.key: _tool_installed(t) for t in TOOLS}


# ---------------------------------------------------------------- 安裝動作


def _asset_urls(tool: Tool, tag: str) -> list[tuple[str, str]]:
    """取得該 release 的 (檔名, 下載 URL) 清單，四條路徑依序嘗試。

    為何要四條：GitHub API 匿名呼叫每小時只有 60 次，很容易 403；
    `gh` CLI 需已登入；`expanded_assets` 是網頁用的 HTML 片段端點，
    不需 API token 也不吃 API 配額，是最可靠的匿名路徑。
    """
    # 1. gh CLI（已登入時最穩）
    gh = shutil.which("gh")
    if gh:
        try:
            p = subprocess.run([gh, "release", "view", tag, "-R", tool.repo,
                                "--json", "assets", "--jq",
                                '.assets[] | [.name, .url] | @tsv'],
                               capture_output=True, text=True, timeout=60)
            if p.returncode == 0 and p.stdout.strip():
                out = []
                for line in p.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) == 2:
                        # gh 的 .url 是 API url，換成瀏覽器下載 url
                        name = parts[0]
                        out.append((name,
                                    f"https://github.com/{tool.repo}/releases/download/{tag}/{name}"))
                if out:
                    return out
        except Exception:
            pass

    # 2. GitHub API
    try:
        d = _http_json(f"https://api.github.com/repos/{tool.repo}/releases/tags/{tag}")
        out = [(a.get("name") or "", a.get("browser_download_url") or "")
               for a in (d.get("assets") or [])]
        out = [(n, u) for n, u in out if n and u]
        if out:
            return out
    except Exception:
        pass

    # 3. expanded_assets HTML 片段（不吃 API 配額）
    try:
        url = f"https://github.com/{tool.repo}/releases/expanded_assets/{tag}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "CivilDesignWorkBench-Toolchain/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
        hrefs = re.findall(r'href="(/[^"]*/releases/download/[^"]+)"', html)
        out = []
        for h in hrefs:
            name = h.rsplit("/", 1)[-1]
            out.append((name, "https://github.com" + h))
        if out:
            return out
    except Exception:
        pass

    # 4. 猜檔名（最後手段：直接試 manifest 的樣式，不列資產）
    return []


def _pick_asset(tool: Tool, tag: str, quiet: bool) -> tuple[str, str] | None:
    """從該 release 的資產清單挑出符合本機平台的檔案，回傳 (名稱, 下載 URL)。"""
    os_key = "windows" if IS_WIN else ("macos" if IS_MAC else "linux")
    pats = tool.asset_patterns.get((os_key, ARCH)) or []
    if not pats:
        if not quiet:
            print(f"    ✗ 此平台（{os_key}/{ARCH}）沒有登記對應資產樣式")
        return None

    assets = _asset_urls(tool, tag)
    if not assets:
        if not quiet:
            print("    ✗ 取不到 release 資產清單（API 配額、gh 未登入、網頁端點皆失敗）")
        return None

    for name, url in assets:
        for pat in pats:
            if re.search(pat, name):
                return name, url
    if not quiet:
        names = [n for n, _ in assets][:8]
        print(f"    ✗ 資產樣式 {pats} 沒對上；實際資產前幾筆：{names}")
    return None


def _place_symlink(tool: Tool, target: Path, dry: bool) -> list[str]:
    """建立命令暴露點，回傳「需要使用者確認的指令」清單。

    衝突策略（2026-11-08 定案）：
      · 目標不存在 → 直接建立
      · 目標已存在 → 建 <name>-new，並回傳 mv 備份替換指令
      · 安裝根在非 POSIX 檔案系統（UNC／Windows 分割區／WSL 掛載）→ 不寫 symlink，
        回傳「請執行 _install_links.sh」提示
    """
    pending: list[str] = []
    stem = tool.bin_stem or tool.key.lower()
    lb = local_bin_dir()
    lb.mkdir(parents=True, exist_ok=True)

    if IS_WIN:
        link = lb / f"{stem}.cmd"
        body = f'@echo off\r\n"{target}" %*\r\n'
        if dry:
            print(f"    （dry-run）將寫入 {link}")
            return pending
        if link.exists():
            new = lb / f"{stem}-new.cmd"
            new.write_text(body, encoding="utf-8")
            pending.append(f'move /Y "{link}" "{link}.bak" && move /Y "{new}" "{link}"')
            print(f"    ! {link} 已存在 → 已寫入 {new.name}（待你確認後替換）")
        else:
            link.write_text(body, encoding="utf-8")
            print(f"    ✓ 已建立 {link}")
        return pending

    link = lb / stem
    # 判斷是否落在非同檔案系統（跨裝置／網路共享）
    try:
        same_dev = os.stat(lb).st_dev == os.stat(target.parent).st_dev
    except Exception:
        same_dev = True

    if not same_dev:
        script = lb / "_install_links.sh"
        line = f'ln -sfn "{target}" "{link}"\n'
        if dry:
            print(f"    （dry-run）跨裝置：將追加到 {script}")
        else:
            with open(script, "a", encoding="utf-8") as f:
                f.write(line)
            script.chmod(0o755)
            pending.append(f"bash {script}")
            print(f"    ! 安裝根在不同檔案系統，已寫入 {script}（請自行執行）")
        return pending

    if dry:
        print(f"    （dry-run）將建立 symlink {link} → {target}")
        return pending

    if link.exists() or link.is_symlink():
        new = lb / f"{stem}-new"
        if new.exists() or new.is_symlink():
            new.unlink()
        new.symlink_to(target)
        pending.append(f'mv -f "{link}" "{link}.bak" && mv -f "{new}" "{link}"')
        print(f"    ! {link} 已存在 → 已建立 {new.name}（待你確認後替換）")
    else:
        link.symlink_to(target)
        print(f"    ✓ 已建立 {link} → {target}")
    return pending


def opencadstudio_config_dir() -> Path:
    """OpenCADStudio 的設定目錄（跨平台）。

    Linux  : ~/.config/OpenCADStudio
    Windows: %APPDATA%/OpenCADStudio
    macOS  : ~/Library/Application Support/OpenCADStudio
    可用 OCS_CONFIG_DIR 覆寫（OCS 本身也認這個變數）。
    """
    env = os.environ.get("OCS_CONFIG_DIR")
    if env:
        return Path(env)
    if IS_WIN:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "OpenCADStudio"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "OpenCADStudio"
    return Path.home() / ".config" / "OpenCADStudio"


def _sync_shx_fonts(src: Path, dst: Path) -> tuple[list[str], list[str]]:
    """把 `src` 內的 *.shx 複製到 `dst`（檔名不分大小寫比對）。回傳 (有複製的檔名, 已是最新的檔名)。

    目的檔存在且內容不同：舊檔先另存 `<檔名>.bak` 再覆蓋；內容相同則不動。
    """
    dst.mkdir(parents=True, exist_ok=True)
    existing = {f.name.lower(): f for f in dst.iterdir() if f.is_file()}
    copied: list[str] = []
    kept: list[str] = []
    for f in sorted(src.iterdir()):
        if not (f.is_file() and f.suffix.lower() == ".shx"):
            continue
        cur = existing.get(f.name.lower())
        if cur is not None:
            if cur.read_bytes() == f.read_bytes():
                kept.append(f.name)
                continue
            shutil.copy2(cur, cur.with_name(cur.name + ".bak"))
            cur.unlink()
        shutil.copy2(f, dst / f.name)
        copied.append(f.name)
    return copied, kept


def configure_opencadstudio(quiet: bool = False) -> bool:
    """把 TOMO 字型**複製**進 OpenCADStudio 自己的字型夾，並設好 CTB 出圖樣式夾。

    為什麼要這一步：OCS 的 `settings.fonts_folder` 預設是 null，開 TOMO 圖面會警告
    `Missing fonts: CHINA1.SHX, gbenor.shx`；`plot_styles_folder` 預設 null 則無法套
    monochrome.ctb（設定可即時生效、無須重啟）。

    字型：把專案 `CAD_FONTS/` 的 `*.shx` 複製到 OCS 設定目錄下的 `fonts/`，`fonts_folder`
    指向該夾（一勞永逸：之後搬動或刪除專案資料夾，OCS 仍找得到字型）。目的檔已存在且內容
    不同時，先把舊檔另存 `<檔名>.bak` 再覆蓋；內容相同則略過。複製失敗才退回直接指向 `CAD_FONTS/`。
    出圖樣式：指向專案 `tools/acad/plot`（不複製，避免蓋掉 OCS 自帶的同名 monochrome.ctb）。

    只覆蓋這兩個鍵，其餘設定原樣保留；原檔先備份為 settings.json.bak。
    """
    try:
        here = Path(__file__).resolve().parent
        tools_dir = here.parent
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from project_paths import ROOT, cad_fonts_dir

        fonts_dir = cad_fonts_dir() or (ROOT / "CAD_FONTS")
        plot_dir = ROOT / "tools" / "acad" / "plot"

        if not fonts_dir.is_dir():
            if not quiet:
                print(f"    ! 找不到字型夾 {fonts_dir}，略過 OpenCADStudio 設定")
            return False

        cfg_dir = opencadstudio_config_dir()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = cfg_dir / "settings.json"

        d = {}
        if cfg_file.is_file():
            try:
                d = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                d = {}
            # 破壞性操作前先整檔備份（使用者約定 2026-11-02）
            shutil.copy2(cfg_file, cfg_file.with_suffix(".json.bak"))

        if not isinstance(d.get("settings"), dict):
            d["settings"] = {}

        # 字型：複製進 OCS 自己的 fonts/，再把 fonts_folder 指過去
        ocs_fonts = cfg_dir / "fonts"
        try:
            copied, kept = _sync_shx_fonts(fonts_dir, ocs_fonts)
            fonts_target = ocs_fonts
        except OSError as e:
            if not quiet:
                print(f"    ! 複製字型失敗（{e}），退回直接指向 {fonts_dir}")
            copied, kept, fonts_target = [], [], fonts_dir

        d["settings"]["fonts_folder"] = str(fonts_target.resolve())
        d["settings"]["plot_styles_folder"] = str(plot_dir.resolve())

        cfg_file.write_text(json.dumps(d, ensure_ascii=False, indent=4) + "\n",
                            encoding="utf-8")
        if not quiet:
            print(f"    ✓ 字型夾   → {fonts_target.resolve()}"
                  f"（新複製 {len(copied)} 個、已是最新 {len(kept)} 個）")
            print(f"    ✓ 出圖樣式 → {plot_dir.resolve()}")
            print(f"    ✓ 已寫入 {cfg_file}")
        return True
    except Exception as e:
        if not quiet:
            print(f"    ! 設定 OpenCADStudio 失敗：{e}")
        return False



def _macos_app_cli_exe(app_dir: Path, tool: Tool) -> Path:
    """回傳 .app 內「可獨立執行」的 CLI 執行檔。

    為什麼不能直接用 `Contents/MacOS/<CFBundleExecutable>`：OpenCADStudio 的
    `Contents/MacOS/OpenCADStudio` 只是 **launcher stub**，它會去 .app 套件內部
    找資源；一旦被 symlink 到別處執行，就噴
    `OpenCADStudio launcher: failed to execute the application`。
    真正可獨立執行的是同目錄下的 `OpenCADStudio-App`（112 MB 的主程式）。

    通用作法：優先挑名字帶 `-App`／`-app` 後綴的較大檔案；沒有就退回第一個。
    """
    macos_dir = app_dir / "Contents" / "MacOS"
    cands = [c for c in sorted(macos_dir.glob("*")) if c.is_file()]
    if not cands:
        return app_dir
    stem = (tool.bin_stem or tool.key.lower()).lower()
    preferred = [c for c in cands if c.stem.lower() in (f"{stem}-app", f"{stem}-app-bin")]
    if preferred:
        return max(preferred, key=lambda p: p.stat().st_size)
    # 退回：挑最大的（launcher stub 通常只有幾百 KB）
    return max(cands, key=lambda p: p.stat().st_size)


def _install_macos_dmg(tool: Tool, dmg: Path, dest_dir: Path, asset_name: str,
                       quiet: bool = False) -> Path | None:
    """macOS：掛載 .dmg → 複製 .app 到 /Applications → 卸載 → 回傳 app 內執行檔路徑。

    為什麼需要這個：`.dmg` 是磁碟映像，不是可執行檔。先前直接把它搬到
    `~/.local/opt/` 再 symlink 出去，會得到一個「command not found」的假安裝。
    """
    mount_pt = None
    try:
        p = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", str(dmg)],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            if not quiet:
                print(f"    ✗ 掛載 DMG 失敗：{(p.stderr or '').strip()[:200]}")
            return None
        for line in (p.stdout or "").splitlines():
            # hdiutil 輸出格式：`/dev/disk8s1  <uuid>  /Volumes/Open CAD Studio`
            # 掛載點在**最後一欄**（以 tab 分隔），不是行首。
            parts = [c.strip() for c in line.split("\t") if c.strip()]
            for c in reversed(parts):
                if c.startswith("/Volumes/"):
                    mount_pt = Path(c)
                    break
            if mount_pt is not None:
                break
        if mount_pt is None or not mount_pt.is_dir():
            if not quiet:
                print("    ✗ 找不到 DMG 掛載點")
            return None

        app = next((c for c in mount_pt.glob("*.app") if c.is_dir()), None)
        if app is None:
            if not quiet:
                print("    ✗ DMG 內找不到 .app")
            return None

        dest = Path("/Applications") / (tool.macos_app_name or app.name)
        if dest.exists():
            if not quiet:
                print(f"    · {dest} 已存在，改用 ~/.local/opt 內的獨立副本")
            dest = dest_dir / (tool.macos_app_name or app.name)
        shutil.copytree(app, dest, symlinks=True, dirs_exist_ok=True)
        if not quiet:
            print(f"    ✓ 已安裝 {dest}")

        exe = _macos_app_cli_exe(dest, tool)
        return exe
    except Exception as e:
        if not quiet:
            print(f"    ✗ DMG 安裝失敗：{e}")
        return None
    finally:
        if mount_pt is not None:
            subprocess.run(["hdiutil", "detach", str(mount_pt), "-quiet"],
                           capture_output=True, timeout=120)


def _verify_checksum(tool: Tool, tag: str, asset_name: str, path: Path,
                     quiet: bool = False) -> bool | None:
    """用 release 內的校驗檔核對下載檔。True＝相符；False＝不符；None＝查不到校驗值。

    校驗檔的檔名欄以空格書寫（`Open CalcSheet Studio_…`），GitHub 資產名則把空格換成點，
    因此兩邊都先正規化再比對。
    """
    sums = next(((n, u) for n, u in _asset_urls(tool, tag) if n == tool.checksum_asset), None)
    if not sums:
        return None
    try:
        req = urllib.request.Request(sums[1], headers={"User-Agent": "CivilDesignWorkBench-Toolchain/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    def norm(n: str) -> str:
        return re.sub(r"^[./*]+", "", n.strip()).replace(" ", ".")

    want = None
    for line in text.splitlines():
        m = re.match(r"([0-9a-fA-F]{64})\s+\*?(.+)$", line.strip())
        if m and norm(m.group(2)) == norm(asset_name):
            want = m.group(1).lower()
            break
    if want is None:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if not quiet:
        print(f"    SHA256 {'相符' if got == want else '不符！'}  {got[:16]}…")
    return got == want


#: Linux 啟動包裝腳本的識別字串：只覆寫自己產生的包裝腳本或 symlink，不動使用者手寫的檔案
_WRAPPER_MARK = "# civil-toolchain wrapper"

#: WebKitGTK（Tauri）在部分 Linux GPU（實測 NVIDIA GB10／aarch64）建 DMA-BUF 緩衝區無權限，
#: 視窗全黑、日誌一直 `KMS: DRM_IOCTL_MODE_CREATE_DUMB failed`；強制軟體渲染即可（EXP-J4）。
_OCSS_WEBKIT_ENV = {"WEBKIT_DISABLE_DMABUF_RENDERER": "1", "WEBKIT_DISABLE_COMPOSITING_MODE": "1"}


def _write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _linux_desktop_integration(tool: Tool, exe: str, quiet: bool = False) -> None:
    """Linux：補「選單看得到、開了不黑屏」兩件事（2026-11-10 aarch64 實測）。

    * OpenCalcSheet（.deb 裝到 /usr/bin/open-calcsheet-studio）：
      寫包裝腳本 `~/.local/bin/open-calcsheet-studio-tw`（帶 WebKit 軟體渲染環境變數），
      並在 `~/.local/share/applications/` 放**同名** `Open CalcSheet Studio TW.desktop`
      蓋過系統那份（XDG 規則：使用者目錄同 desktop ID 優先），Exec 指向包裝腳本。
    * OpenCADStudio（AppImage）：AppImage 不會自建選單項目，補 `Open CAD Studio TW.desktop`，
      圖示用 `--appimage-extract` 取出。檔名比對鍵＝`opencadstudiotw`，與上游
      `io.github.HakanSeven12.OpenCadStudio.desktop` 區隔。
    失敗只印警告，不影響安裝結果。
    """
    if IS_WIN or IS_MAC:
        return
    apps = Path.home() / ".local" / "share" / "applications"
    changed = False
    try:
        if tool.key == "OpenCalcSheet":
            real = Path(exe).resolve()
            wrapper = local_bin_dir() / (tool.bin_stem or "open-calcsheet-studio-tw")
            if real == wrapper.resolve() and wrapper.is_file():
                # 偵測已回傳包裝腳本本身：取出它包裝的真正執行檔
                for line in wrapper.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("exec "):
                        real = Path(line.split('"')[1]) if '"' in line else real
            ours = (not wrapper.exists() or wrapper.is_symlink()
                    or _WRAPPER_MARK in wrapper.read_text(encoding="utf-8", errors="replace"))
            if ours and real.is_file() and real != wrapper:
                env = " ".join(f"{k}={v}" for k, v in _OCSS_WEBKIT_ENV.items())
                text = ("#!/bin/sh\n"
                        f"{_WRAPPER_MARK}（tools/install/toolchain.py 產生；EXP-J4）\n"
                        "# Open CalcSheet Studio TW：WebKitGTK GPU 緩衝區無權限會全黑 → 強制軟體渲染\n"
                        f"export {env}\n"
                        f'exec "{real}" "$@"\n')
                if wrapper.is_symlink():
                    wrapper.unlink()
                if _write_if_changed(wrapper, text):
                    wrapper.chmod(0o755)
                    changed = True
                    if not quiet:
                        print(f"    ✓ 啟動腳本 {wrapper}（WebKit 軟體渲染，避免黑屏）")
            sys_desk = Path("/usr/share/applications/Open CalcSheet Studio TW.desktop")
            if sys_desk.is_file() and wrapper.is_file():
                lines = [(f"Exec={wrapper}" if ln.startswith("Exec=") else ln)
                         for ln in sys_desk.read_text(encoding="utf-8", errors="replace").splitlines()]
                if _write_if_changed(apps / sys_desk.name, "\n".join(lines) + "\n"):
                    changed = True
                    if not quiet:
                        print(f"    ✓ 選單項目 {apps / sys_desk.name}（Exec → 啟動腳本）")

        elif tool.key == "OpenCADStudio":
            appimage = Path(exe).resolve()
            if not (appimage.is_file() and appimage.suffix.lower() == ".appimage"):
                return
            icon = next(iter(sorted((appimage.parent / "squashfs-root").glob("*.png"))), None)
            if icon is None:
                subprocess.run([str(appimage), "--appimage-extract", "*.png"], cwd=appimage.parent,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                icon = next(iter(sorted((appimage.parent / "squashfs-root").glob("*.png"))), None)
            text = "\n".join([
                "[Desktop Entry]",
                "Name=Open CAD Studio TW",
                "Name[zh_TW]=Open CAD Studio TW（Big5 SHX 修正版）",
                "Comment=OpenCADStudio TW fork - DWG/DXF 2D/3D CAD",
                f"Exec={local_bin_dir() / (tool.bin_stem or 'opencadstudio-tw')} %F",
                f"Icon={icon}" if icon else "Icon=io.github.HakanSeven12.OpenCadStudio",
                "Terminal=false",
                "Type=Application",
                "Categories=Graphics;Engineering;",
                "MimeType=image/vnd.dwg;image/vnd.dxf;",
                "StartupWMClass=OpenCADStudio",
            ]) + "\n"
            if _write_if_changed(apps / "Open CAD Studio TW.desktop", text):
                changed = True
                if not quiet:
                    print(f"    ✓ 選單項目 {apps / 'Open CAD Studio TW.desktop'}")
        if changed and shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(apps)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except Exception as e:  # noqa: BLE001 — 選單整合是加值，不該讓安裝失敗
        if not quiet:
            print(f"    ! Linux 選單整合失敗（不影響安裝）：{e}")


def _install_deb(tool: Tool, target: Path, res: dict, quiet: bool = False) -> dict:
    """Linux .deb：先試 `sudo -n apt-get install`（免密碼 sudo／已快取憑證才會成功，**絕不詢問或代填密碼**）；
    不行就印出 `sudo apt install` 指令請使用者自行執行。"""
    hint = f'sudo apt install "{target}"'
    if shutil.which("sudo") and shutil.which("apt-get"):
        try:
            p = subprocess.run(["sudo", "-n", "apt-get", "install", "-y", str(target)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900)
            if p.returncode == 0:
                exe = _tool_installed(tool)
                if exe:
                    res.update(ok=True, action="installed", detail=exe)
                    if not quiet:
                        print(f"    ✓ 已以 apt 安裝 {exe}")
                    return res
        except Exception:  # noqa: BLE001
            pass
    res.update(action="downloaded",
               detail=f"已下載到 {target}（.deb 需 root；sudo 需密碼，不代裝），請執行：{hint}")
    if not quiet:
        print(f"    ✓ 已下載 {target}")
        print(f"    .deb 需 root，請你自行執行：{hint}，再重跑 --install 補選單與啟動腳本")
    return res


def _run_installer(tool: Tool, tmp: Path, asset_name: str, ver: str, res: dict,
                   quiet: bool = False) -> dict:
    """處理「安裝程式型」資產（tool.kind == "installer" 且非 dmg）。

    Windows .exe：NSIS 靜默安裝（/S），完成後以 detect 驗證；失敗保留安裝檔供手動執行。
    Windows .msi：`msiexec /i <msi> /passive /norestart`（基本 UI 才能跳 UAC；`/qn` 非管理員實測回 1603）。
    Linux .deb：放到 ~/.local/opt，試 `sudo -n apt-get install`（不問密碼），不行才印 sudo apt install 指令。
    """
    low = asset_name.lower()
    if low.endswith((".exe", ".msi")) and IS_WIN:
        is_msi = low.endswith(".msi")
        argv = (["msiexec", "/i", str(tmp), "/passive", "/norestart"] if is_msi
                else [str(tmp), "/S"])
        if not quiet:
            print(f"    執行安裝（{'msiexec /passive' if is_msi else '/S'}）；若跳出 UAC 請核准……")
        try:
            p = subprocess.run(argv, timeout=900)
            # msiexec：0＝成功、3010＝成功但需重開機；其他（如 1602 使用者取消、1603 權限）視為失敗
            if is_msi and p.returncode not in (0, 3010):
                raise RuntimeError(f"msiexec 回傳 {p.returncode}")
        except Exception as e:
            res.update(action="fail", detail=f"執行安裝程式失敗：{e}（安裝檔保留在 {tmp}）")
            if not quiet:
                print(f"    ✗ 執行安裝程式失敗：{e}\n    可手動執行：\"{tmp}\"")
            return res
        # NSIS 靜默安裝偶爾在主行程結束後仍有收尾，輪詢最多 60 秒
        exe = None
        for _ in range(30):
            exe = _tool_installed(tool)
            if exe:
                break
            time.sleep(2)
        if not exe:
            res.update(action="fail",
                       detail=f"安裝程式已執行但找不到執行檔（安裝檔保留在 {tmp}，可手動執行）")
            if not quiet:
                print(f"    ✗ 安裝後仍偵測不到；可手動執行：\"{tmp}\"")
            return res
        try:
            tmp.unlink()
        except OSError:
            pass
        res.update(ok=True, action="installed", detail=exe)
        if not quiet:
            print(f"    ✓ 已安裝 {exe}")
        return res

    if low.endswith(".deb"):
        dest_dir = local_opt_dir() / f"{tool.bin_stem or tool.key.lower()}-{ver}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / asset_name
        shutil.move(str(tmp), target)
        res = _install_deb(tool, target, res, quiet=quiet)
        if res.get("ok"):
            _linux_desktop_integration(tool, res["detail"], quiet=quiet)
        return res

    res.update(action="fail", detail=f"不支援的安裝檔型態：{asset_name}")
    return res


def install_tool(tool: Tool, dry: bool = False, quiet: bool = False) -> dict:
    """安裝單一工具。回傳 {ok, action, detail, pending}。"""
    res = {"key": tool.key, "ok": False, "action": "", "detail": "", "pending": [],
           "required": tool.required}

    existing = _tool_installed(tool)
    if existing:
        res.update(ok=True, action="skip", detail=f"已安裝：{existing}")
        if not quiet:
            print(f"  {tool.key:<14} 已安裝  {existing}")
        # Linux：補選單項目與 OCSS 防黑屏啟動腳本（會在 ~/.local/bin/<stem> 放包裝腳本，須先於下方 symlink）
        _linux_desktop_integration(tool, existing, quiet=quiet)
        # 已安裝也要補命令暴露點：~/.local/bin/<stem> 可能不存在（macOS 走 /Applications）
        if not IS_WIN:
            stem = tool.bin_stem or tool.key.lower()
            lb = local_bin_dir()
            link = lb / stem
            if not (link.exists() or link.is_symlink()):
                try:
                    lb.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(existing)
                    if not quiet:
                        print(f"    ✓ 已建立 {link} → {existing}")
                except Exception as e:
                    if not quiet:
                        print(f"    ! 建立命令連結失敗：{e}")
        # 已安裝也要補設定：老機器先前裝過，settings.json 仍是 null
        if tool.key == "OpenCADStudio":
            configure_opencadstudio(quiet=quiet)
        return res

    if tool.kind == "manual":
        res.update(action="manual", detail=tool.manual_hint)
        if not quiet:
            print(f"  {tool.key:<14} 需手動安裝")
            print(f"    {tool.manual_hint}")
        return res

    # 選用工具若本平台沒登記資產樣式：不算失敗（否則會讓整個 --install 退出碼變 1），改印手動指引
    plat = ("windows" if IS_WIN else ("macos" if IS_MAC else "linux"), ARCH)
    if not tool.required and not tool.asset_patterns.get(plat):
        res.update(ok=False, action="manual", detail=tool.manual_hint)
        if not quiet:
            print(f"  {tool.key:<14} 選用，本平台（{plat[0]}/{plat[1]}）尚無自動安裝")
            print(f"    {tool.manual_hint}")
        return res

    if not quiet:
        print(f"  {tool.key:<14} 未安裝 → 開始取得")

    if dry:
        res.update(ok=False, action="plan",
                   detail=f"將從 {tool.repo} 下載最新 release 並安裝到 {local_opt_dir()}")
        if not quiet:
            print(f"    （dry-run）來源 {tool.repo}／平台 "
                  f"{'windows' if IS_WIN else ('macos' if IS_MAC else 'linux')}/{ARCH}")
            if tool.key == "OpenCADStudio" and IS_WIN:
                print("    （dry-run）下載 fork 的 *-installer.msi，以 msiexec /passive 安裝到「Open CAD Studio.TW」（可能跳 UAC）")
            elif tool.kind == "installer":
                how = ("下載後以 SHA256SUMS 校驗，再執行 setup.exe /S 靜默安裝" if IS_WIN
                       else "macOS：掛載 dmg 複製 .app" if IS_MAC
                       else "Linux：只下載 .deb 並印出 sudo apt install 指令（需 root，不代裝）")
                print(f"    （dry-run）{how}")
            else:
                print(f"    （dry-run）目標 {local_opt_dir()}/{(tool.bin_stem or tool.key.lower())}-<ver>")
        return res

    tag = latest_release_tag(tool.repo)
    if not tag:
        res.update(action="fail", detail="取不到最新 release tag（網路或速率限制）")
        if not quiet:
            print("    ✗ 取不到最新 release tag（可能被 GitHub 匿名速率限制；裝 gh 後重試）")
        return res
    if not quiet:
        print(f"    最新版本 {tag}")

    picked = _pick_asset(tool, tag, quiet)
    if not picked:
        res.update(action="fail", detail=f"{tag} 找不到本平台資產")
        if tool.manual_hint and not quiet:
            print(f"    {tool.manual_hint}")
        return res
    asset_name, url = picked

    ver = tag.lstrip("vV")
    stem = tool.bin_stem or tool.key.lower()
    dest_dir = local_opt_dir() / f"{stem}-{ver}"
    # 安裝程式型資產（setup.exe／.msi／.deb）交給系統安裝程式，不預建目錄，避免留下空資料夾
    is_pkg = (asset_name.lower().endswith((".msi", ".deb"))
              or (tool.kind == "installer" and not asset_name.lower().endswith(".dmg")))
    if not is_pkg:
        dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = _temp_install_dir() / asset_name

    try:
        if not quiet:
            print(f"    資產 {asset_name}")
        download(url, tmp, quiet=quiet)
    except Exception as e:
        res.update(action="fail", detail=f"下載失敗：{e}")
        if not quiet:
            print(f"    ✗ 下載失敗：{e}")
        return res

    if tool.checksum_asset:
        ck = _verify_checksum(tool, tag, asset_name, tmp, quiet=quiet)
        if ck is False:
            tmp.unlink(missing_ok=True)
            res.update(action="fail", detail="SHA256 校驗不符，已刪除下載檔並中止安裝")
            if not quiet:
                print("    ✗ SHA256 校驗不符，已刪除下載檔並中止安裝")
            return res
        if ck is None and not quiet:
            print("    ! 查不到校驗值，略過 SHA256 校驗")

    target: Path | None = None
    try:
        if is_pkg:
            res = _run_installer(tool, tmp, asset_name, ver, res, quiet=quiet)
            if res.get("ok") and tool.key == "OpenCADStudio":
                configure_opencadstudio(quiet=quiet)
            return res
        if asset_name.lower().endswith(".dmg"):
            # macOS DMG：掛載 → 取出 .app → 複製到 /Applications → 卸載。
            # （不可直接把 .dmg 當執行檔 symlink 出去，那會得到壞掉的命令。）
            target = _install_macos_dmg(tool, tmp, dest_dir, asset_name, quiet=quiet)
        elif tool.kind == "appimage":
            target = dest_dir / asset_name
            shutil.move(str(tmp), target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        elif tool.kind in ("zip", "tar"):
            shutil.unpack_archive(str(tmp), str(dest_dir))
            target = next((p for p in dest_dir.rglob(stem) if p.is_file()), None)
            if target is not None and not IS_WIN:
                # shutil.unpack_archive 解 zip 不保留執行權限，不補的話 symlink 出去是「Permission denied」
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        elif tool.kind in ("msi", "dmg"):
            # Windows MSI／macOS DMG 需使用者互動安裝，只下載不代裝
            target = dest_dir / asset_name
            shutil.move(str(tmp), target)
            hint = (f'msiexec /i "{target}"' if tool.kind == "msi"
                    else f'open "{target}"   # 拖曳 .app 到 /Applications')
            res.update(action="downloaded",
                       detail=f"已下載到 {target}，請執行：{hint}")
            if not quiet:
                print(f"    ✓ 已下載 {target}")
                print(f"    請執行：{hint}")
            return res
    except Exception as e:
        res.update(action="fail", detail=f"解包失敗：{e}")
        if not quiet:
            print(f"    ✗ 解包失敗：{e}")
        return res

    if not target or not target.is_file():
        res.update(action="fail", detail="解包後找不到執行檔")
        if not quiet:
            print("    ✗ 解包後找不到執行檔")
        return res

    res["pending"] = _place_symlink(tool, target, dry=False)
    res.update(ok=True, action="installed", detail=str(target))
    _linux_desktop_integration(tool, str(target), quiet=quiet)
    if tool.key == "OpenCADStudio":
        configure_opencadstudio(quiet=quiet)
    return res


# ---------------------------------------------------------------- 對外入口


def check_and_install(dry: bool = False, only: str | None = None,
                      quiet: bool = False) -> int:
    """主流程：偵測 → 安裝缺漏 → 印總結。回傳退出碼（0 全備妥／1 有缺漏）。"""
    if not quiet:
        osname = "Windows" if IS_WIN else ("macOS" if IS_MAC else "Linux")
        print(f"工具鏈檢查（{osname}／{ARCH}）")
        print(f"  安裝根 : {local_opt_dir()}")
        print(f"  命令夾 : {local_bin_dir()}")
        print(f"  來源   : 官方 GitHub Releases（免 root）")
        print()

    wanted = [t for t in TOOLS if not only or t.key.lower() == only.lower()
              or (t.bin_stem or "").lower() == only.lower()]
    if only and not wanted:
        print(f"✗ 沒有名為 {only!r} 的工具；可用：{', '.join(t.key for t in TOOLS)}")
        return 2

    results = [install_tool(t, dry=dry, quiet=quiet) for t in wanted]

    if not quiet:
        print()
        print("總結")
        missing, pending = [], []
        for r in results:
            mark = "✓" if r["ok"] else ("·" if r["action"] == "manual" else "✗")
            print(f"  {mark} {r['key']:<14} {r['detail'] or r['action']}")
            # 手動安裝的「選用」工具缺了不算失敗；「必備」的手動工具（Blender、ArtCraft Launcher）缺了要算
            if not r["ok"] and (r["action"] != "manual" or r.get("required")):
                missing.append(r["key"])
            pending.extend(r["pending"])

        if pending:
            print()
            print("以下指令需要你確認後自行執行（本腳本不代為替換既有命令）：")
            for c in pending:
                print(f"    {c}")

        if dry:
            print()
            print("（dry-run：未實際下載或安裝）")
            return 0

        if missing:
            print()
            print(f"✗ 仍有 {len(missing)} 項未備妥：{'、'.join(missing)}")
            return 1
        print()
        print("全部備妥。")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="工具鏈偵測與免 root 安裝")
    ap.add_argument("--dry-run", action="store_true", help="只印計畫，不下載")
    ap.add_argument("--only", help="只處理某一個工具")
    raise SystemExit(check_and_install(dry=ap.parse_args().dry_run, only=ap.parse_args().only))
