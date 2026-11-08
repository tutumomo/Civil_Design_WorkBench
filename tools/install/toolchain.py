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


def download(url: str, dest: Path, quiet: bool = False) -> Path:
    """下載到 dest；有 Content-Length 就印進度百分比。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "CivilDesignWorkBench-Toolchain/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and not quiet:
                pct = got * 100 // total
                print(f"\r    下載 {pct:3d}%  {got/1048576:8.1f} / {total/1048576:.1f} MB",
                      end="", flush=True)
    if not quiet:
        print()
    return dest


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


#: OpenCADStudio 資產命名（實測 v2026.44）：
#:   OpenCADStudio-v2026.44-linux-aarch64.AppImage
#:   OpenCADStudio-v2026.44-linux-x86_64.AppImage
#:   OpenCADStudio-v2026.44-macos-arm64.dmg
#:   OpenCADStudio-v2026.44-windows-x86_64-portable.exe（另有 -installer.msi，不用它）
#:
#: Windows 一律取 **portable exe**，不取 MSI：
#:   - MSI 靜默安裝要管理員，實測 `msiexec /i ... /qn` 回 1603，等於什麼都沒裝成；
#:   - 取 MSI 時產出的 `~/.local/bin/opencadstudio.cmd` 只會變成「執行那個 .msi」，
#:     而 `acc.py` 的 `--http` 服務模式根本不會起來；
#:   - portable exe 是單檔可直接執行，`taskkill /T` 也殺得到本體（MSI 走殼層會留孤兒）。
TOOLS: list[Tool] = [
    Tool(
        key="OpenCADStudio",
        repo="HakanSeven12/OpenCADStudio",
        asset_patterns={
            ("linux", "aarch64"): [r"linux-aarch64\.AppImage$"],
            ("linux", "x86_64"): [r"linux-x86_64\.AppImage$"],
            ("macos", "aarch64"): [r"macos-arm64\.dmg$"],
            ("macos", "x86_64"): [r"macos-x86_64\.dmg$"],
            ("windows", "x86_64"): [r"windows-x86_64-portable\.exe$"],
            ("windows", "aarch64"): [r"windows-arm64-portable\.exe$"],
        },
        kind="appimage",
        bin_stem="opencadstudio",
        note="AutoCAD 開源平替；DWG/DXF 原生讀寫、CTB 出圖、MCP 介面",
        verify_argv=["--version"],
        verify_must_contain="OpenCADStudio",
    ),
    Tool(
        key="Blender",
        repo="blender/blender",
        asset_patterns={},   # Blender 官方 release 不在 GitHub releases，見 manual_hint
        kind="manual",
        bin_stem="blender",
        required=False,
        note="3D 景觀模擬與擬真算輪",
        manual_hint="Blender 由 blender.org 發行，GitHub repo 不含 release 資產；"
                    "請至 https://www.blender.org/download/ 下載，或系統套件管理器安裝",
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
    # 3. ~/.local/opt/<stem>-*/ 內找執行檔
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


def install_tool(tool: Tool, dry: bool = False, quiet: bool = False) -> dict:
    """安裝單一工具。回傳 {ok, action, detail, pending}。"""
    res = {"key": tool.key, "ok": False, "action": "", "detail": "", "pending": []}

    existing = _tool_installed(tool)
    if existing:
        res.update(ok=True, action="skip", detail=f"已安裝：{existing}")
        if not quiet:
            print(f"  {tool.key:<14} 已安裝  {existing}")
        return res

    if tool.kind == "manual":
        res.update(action="manual", detail=tool.manual_hint)
        if not quiet:
            print(f"  {tool.key:<14} 需手動安裝")
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
        return res
    asset_name, url = picked

    ver = tag.lstrip("vV")
    stem = tool.bin_stem or tool.key.lower()
    dest_dir = local_opt_dir() / f"{stem}-{ver}"
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

    target: Path | None = None
    try:
        if tool.kind == "appimage":
            target = dest_dir / asset_name
            shutil.move(str(tmp), target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        elif tool.kind == "zip":
            shutil.unpack_archive(str(tmp), str(dest_dir))
            target = next((p for p in dest_dir.rglob(stem) if p.is_file()), None)
        elif tool.kind == "tar":
            shutil.unpack_archive(str(tmp), str(dest_dir))
            target = next((p for p in dest_dir.rglob(stem) if p.is_file()), None)
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
            if not r["ok"] and r["action"] not in ("manual",):
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
