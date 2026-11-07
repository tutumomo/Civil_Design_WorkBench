"""開工前同步檢查：本地落後 GitHub 幾筆、有沒有未推送、工作區乾不乾淨、有沒有殘留 lock。

為什麼要有這支
--------------
本專案在多台電腦輪流作業（公司／家裡／筆電）。常態是「做完有 push，但換地點忘了先 pull」，
做一陣子之後本地與遠端分叉，`git pull` 就被擋住（尤其圖檔是二進位，一衝突就難解）。

這支腳本掛在 Claude Code 的 **SessionStart hook**，每次開新對話就先講清楚三件事：
  1. 遠端有沒有新提交（該不該先 pull）
  2. 本地有沒有做完沒 push 的（換地點前是否真的收工了）
  3. 工作區乾不乾淨（不乾淨就不能 ff-only；要 stash 或用 worktree）
  4. `.git/*.lock` 有沒有殘留（別台機器／別的 agent 中斷留下的，會讓所有 git 指令失敗）

它**只報告、不改動**工作區。要不要 pull、要不要放棄本地改動，由使用者決定。

用法：
    python tools/git/sync_check.py            # 人看的報告（hook 也用這個）
    python tools/git/sync_check.py --json     # 機器可讀
    python tools/git/sync_check.py --quiet    # 沒事時完全不出聲（只剩一行 OK）

離開碼：一律 0（hook 不得擋住開工）。真正的阻擋交給人判斷。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FETCH_TIMEOUT = 15  # 秒；離線／慢線不拖住開工


def git(*args, timeout=20):
    try:
        p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if p.returncode != 0:
        return None, (p.stderr or p.stdout or "").strip()
    return (p.stdout or "").strip(), None


def int_or_none(text):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def collect(fetch=True):
    rec = {"root": str(ROOT), "branch": None, "detached": False,
           "behind": None, "ahead": None, "dirty_tracked": None,
           "untracked": None, "stash": None, "locks": [], "fetch_error": None,
           "is_repo": True}

    top, err = git("rev-parse", "--show-toplevel")
    if err:
        rec["is_repo"] = False
        rec["fetch_error"] = err
        return rec

    branch, err = git("rev-parse", "--abbrev-ref", "HEAD")
    if err is None:
        rec["detached"] = branch == "HEAD"
        rec["branch"] = None if rec["detached"] else branch

    remote_ref = f"origin/{rec['branch']}" if rec["branch"] else "origin/HEAD"

    if fetch:
        _, ferr = git("fetch", "--quiet", "origin", timeout=FETCH_TIMEOUT)
        if ferr:
            rec["fetch_error"] = ferr.splitlines()[0][:200] if ferr else "fetch 失敗"

    behind, _ = git("rev-list", "--count", f"HEAD..{remote_ref}")
    ahead, _ = git("rev-list", "--count", f"{remote_ref}..HEAD")
    rec["behind"] = int_or_none(behind)
    rec["ahead"] = int_or_none(ahead)

    # 只看已追蹤的改動：未追蹤檔不影響 ff-only pull，但值得知道有幾個
    tracked, _ = git("status", "--porcelain", "-uno")
    rec["dirty_tracked"] = len([ln for ln in (tracked or "").splitlines() if ln.strip()])
    every, _ = git("status", "--porcelain")
    rec["untracked"] = max(0, len([ln for ln in (every or "").splitlines()
                                   if ln.strip()]) - rec["dirty_tracked"])

    stash, _ = git("stash", "list")
    rec["stash"] = len([ln for ln in (stash or "").splitlines() if ln.strip()])

    gitdir, _ = git("rev-parse", "--absolute-git-dir")
    if gitdir:
        rec["locks"] = sorted(p.name for p in Path(gitdir).glob("*.lock"))
    return rec


def report(rec):
    if not rec["is_repo"]:
        return ["[git-sync] 這裡不是 git 工作區，略過同步檢查。"]

    lines = []
    where = rec["branch"] or ("detached HEAD" if rec["detached"] else "?")
    lines.append(f"[git-sync] 分支 {where}　落後 {rec['behind']} 筆／未推送 {rec['ahead']} 筆"
                 f"　已追蹤改動 {rec['dirty_tracked']} 檔　未追蹤 {rec['untracked']} 檔"
                 f"　stash {rec['stash']} 筆")

    if rec["fetch_error"]:
        lines.append(f"  ⚠ 無法連 origin（{rec['fetch_error']}）：以下數字是上次 fetch 的結果。")

    if rec["locks"]:
        lines.append(f"  ✗ .git 有殘留 lock：{', '.join(rec['locks'])}"
                     " → 先確認沒有 git 程序在跑，再刪掉，否則所有 git 指令都會失敗。")

    if rec["behind"]:
        lines.append(f"  → 遠端有 {rec['behind']} 筆新提交，**開工前應先 pull**。")
        if rec["dirty_tracked"]:
            lines.append("    工作區有已追蹤改動，ff-only 會失敗。依序：")
            lines.append("      git stash push -u -m \"pre-pull-$(hostname)-$(date +%H%M)\"")
            lines.append("      git pull --ff-only origin <branch>")
            lines.append("      git stash apply <上面記下的 SHA>   # 用 apply 不用 pop，出事才救得回")
            lines.append("    或由使用者決定放棄本地改動（git checkout -- <檔案>）。")
        else:
            lines.append("    工作區乾淨，直接：git pull --ff-only")
    elif rec["behind"] == 0 and not rec["fetch_error"] and not rec["locks"]:
        lines.append("  ✓ 已與遠端同步，可直接開工。")

    if rec["ahead"]:
        lines.append(f"  → 本地有 {rec['ahead']} 筆未推送：換地點／收工前記得 push（見 docs/專案收工SOP.md §13）。")

    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="開工前 git 同步檢查（只報告，不改動）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="沒事時不出聲")
    ap.add_argument("--no-fetch", action="store_true", help="不連網，只看現有 origin ref")
    a = ap.parse_args()

    rec = collect(fetch=not a.no_fetch)
    clean = (rec.get("is_repo") and not rec.get("behind") and not rec.get("ahead")
             and not rec.get("locks") and not rec.get("fetch_error"))

    if a.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    if a.quiet and clean:
        print("[git-sync] 與遠端同步。")
        return 0
    print("\n".join(report(rec)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
