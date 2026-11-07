"""IngeTrazo 自動更新：抓 origin/main → 必要時重裝依賴 → 自檢。

為什麼要有這支
--------------
IngeTrazo 在本機是**原始碼建置**（aarch64 沒有官方 AppImage／flatpak），
所以「更新」＝ git 取新版 ＋ 必要時重跑 pip。手動做很容易漏掉第二步，
然後卡在「程式起不來」而看不出是缺套件。

用法：
    python tools/ingetrazo/ingetrazo_update.py            # 檢查並更新（預設）
    python tools/ingetrazo/ingetrazo_update.py --check    # 只看有沒有新版，不動手
    python tools/ingetrazo/ingetrazo_update.py --force    # 蓋掉本地改動（會先備份 patch）
    python tools/ingetrazo/ingetrazo_update.py --json     # 機器可讀輸出

行為：
  1. 找安裝目錄（`INGETRAZO_HOME` → `~/IngeTrazo` …，由 `project_paths` 解析）
  2. `git fetch --depth 1 origin main`，比對本地 HEAD
  3. 已是最新 → 直接自檢後結束（不碰 pip）
  4. 有新版 → 確認工作區乾淨（`--force` 才允許覆蓋，覆蓋前存 patch 到 `_temp/ingetrazo/`）
  5. `requirements.txt` 有變 → 重裝依賴；沒變 → 跳過（省下幾分鐘）
  6. 跑 `main.py --check`，把版本與自檢結果印出來

安全限制：
  · GUI 開著時不動檔案（改到一半的原始碼會讓 Qt 載入半套模組）；先關掉或加 `--force`
  · 只走 `origin/main`，不合併、不 rebase、不碰分支
  · 安裝目錄不是 git repo（例如官方 tarball 版）→ 明確報錯，不猜

離開碼：0＝已最新或更新成功且自檢 OK｜1＝更新失敗或自檢失敗｜2＝有新版但未套用（--check）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from project_paths import ROOT, ingetrazo_home  # noqa: E402

REQUIREMENTS = "requirements.txt"


def temp_dir() -> Path:
    p = ROOT / "_temp" / "ingetrazo"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run(cmd, cwd: Path, timeout: int = 1800):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def gui_running(home: Path) -> bool:
    """GUI 是否開著（比對 main.py 的完整路徑，避免誤抓別的 python）。"""
    if shutil.which("pgrep") is None:
        return False
    code, out, _ = run(["pgrep", "-af", str(home / "main.py")], Path("/"))
    return code == 0 and bool(out.strip())


def local_head(home: Path):
    code, out, _ = run(["git", "rev-parse", "HEAD"], home)
    return out.strip() if code == 0 else None


def version_of(home: Path) -> str | None:
    """版本號取自 main.py --check 的第一行（IngeTrazo 0.6.0）。"""
    code, out, err = run([str(home / "venv" / "bin" / "python"), "main.py", "--check"], home, timeout=300)
    m = re.search(r"IngeTrazo\s+([0-9][\w.\-]*)", out or err or "")
    return m.group(1) if m else None


def check_only(home: Path) -> dict:
    run(["git", "fetch", "--depth", "1", "origin", "main"], home, timeout=600)
    code, out, _ = run(["git", "rev-parse", "FETCH_HEAD"], home)
    remote = out.strip() if code == 0 else None
    local = local_head(home)
    return {"local": local, "remote": remote, "behind": bool(local and remote and local != remote)}


def main() -> int:
    ap = argparse.ArgumentParser(description="IngeTrazo 自動更新（原始碼建置版）")
    ap.add_argument("--check", action="store_true", help="只檢查，不更新")
    ap.add_argument("--force", action="store_true", help="GUI 開著或工作區有改動時仍強制更新（先存 patch）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args()

    def emit(payload, human):
        if a.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
        else:
            print(human)
        return payload

    home = ingetrazo_home()
    if not home:
        emit({"ok": False, "error": "not_installed"},
             "✗ 找不到 IngeTrazo 安裝目錄（設 INGETRAZO_HOME 或裝到 ~/IngeTrazo）")
        return 1
    home = Path(home)
    if not (home / ".git").is_dir():
        emit({"ok": False, "error": "not_a_git_checkout", "home": str(home)},
             f"✗ {home} 不是 git 工作區；官方 tarball／AppImage 版沒有自動更新，請重新下載發行版")
        return 1
    if not (home / "venv" / "bin" / "python").exists():
        emit({"ok": False, "error": "venv_missing", "home": str(home)},
             f"✗ {home}/venv 不存在；先照 docs/IngeTrazo操作指引.md 建 venv 並安裝 requirements.txt")
        return 1

    before_ver = version_of(home)
    st = check_only(home)
    if not st["remote"]:
        emit({"ok": False, "error": "fetch_failed", "home": str(home)},
             "✗ git fetch 失敗（網路或遠端不可用）")
        return 1

    if not st["behind"]:
        emit({"ok": True, "updated": False, "version": before_ver, "home": str(home),
              "head": st["local"]},
             f"✓ 已是最新（v{before_ver or '?'}，{st['local'][:8]}）")
        return 0

    if a.check:
        emit({"ok": True, "updated": False, "behind": True, "version": before_ver,
              "local": st["local"], "remote": st["remote"], "home": str(home)},
             f"↑ 有新版：{st['local'][:8]} → {st['remote'][:8]}（目前 v{before_ver or '?'}）；"
             f"執行不帶 --check 即可更新")
        return 2

    if gui_running(home) and not a.force:
        emit({"ok": False, "error": "gui_running", "home": str(home)},
             "✗ IngeTrazo 正在執行；先關掉 GUI 再更新（或加 --force，不建議）")
        return 1

    # 工作區是否乾淨：只看「已納入版控」的改動（-uno 略過未追蹤）。
    # 安裝目錄裡的 ingetrazo／ingetrazo-mcp 啟動器是本專案自己放的未追蹤檔，
    # reset --hard 不會碰它們，不該被當成衝突。
    code, out, _ = run(["git", "status", "--porcelain", "-uno"], home)
    dirty = [ln for ln in out.splitlines() if ln.strip()]
    if dirty and not a.force:
        emit({"ok": False, "error": "dirty_tree", "files": dirty[:20], "home": str(home)},
             "✗ 安裝目錄有本地改動，更新會蓋掉：\n   " + "\n   ".join(dirty[:20]) +
             "\n   （要覆蓋請加 --force，會先存 patch 到 _temp/ingetrazo/）")
        return 1
    patch_path = None
    if dirty and a.force:
        _, diff, _ = run(["git", "diff"], home)
        patch_path = temp_dir() / f"local_{datetime.now():%Y%m%d_%H%M}.patch"
        patch_path.write_text(diff, encoding="utf-8")

    code, out, err = run(["git", "reset", "--hard", "FETCH_HEAD"], home, timeout=600)
    if code != 0:
        emit({"ok": False, "error": "reset_failed", "detail": (err or out)[-500:]},
             "✗ git reset --hard FETCH_HEAD 失敗：\n" + (err or out)[-500:])
        return 1

    # requirements.txt 有變才重裝
    _, changed, _ = run(["git", "diff", "--name-only", st["local"], "FETCH_HEAD"], home)
    need_pip = REQUIREMENTS in changed.split()
    pip_note = "requirements.txt 未變，跳過依賴安裝"
    if need_pip:
        pip_note = "requirements.txt 有變，重裝依賴中…"
        code, out, err = run([str(home / "venv" / "bin" / "python"), "-m", "pip",
                              "install", "-r", REQUIREMENTS], home, timeout=3600)
        (temp_dir() / "pip_update.log").write_text(out + "\n" + err, encoding="utf-8")
        if code != 0:
            emit({"ok": False, "error": "pip_failed", "detail": (err or out)[-800:]},
                 "✗ 依賴安裝失敗（詳見 _temp/ingetrazo/pip_update.log）：\n" + (err or out)[-800:])
            return 1

    after_ver = version_of(home)
    code, out, err = run([str(home / "venv" / "bin" / "python"), "main.py", "--check"], home, timeout=300)
    ok = code == 0 and "\nOK" in (out or "") + (err or "")
    payload = {"ok": ok, "updated": True, "before": before_ver, "after": after_ver,
               "home": str(home), "head": st["remote"], "pip": need_pip,
               "patch": str(patch_path) if patch_path else None}
    human = (f"{'✓' if ok else '✗'} 更新 {'完成' if ok else '後自檢失敗'}："
             f"v{before_ver or '?'} → v{after_ver or '?'}（{st['remote'][:8]}）\n"
             f"  {pip_note}" + (f"\n  本地改動已存：{patch_path}" if patch_path else ""))
    if not ok:
        human += "\n  自檢輸出：\n" + ((out or "") + (err or ""))[-800:]
    emit(payload, human)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
