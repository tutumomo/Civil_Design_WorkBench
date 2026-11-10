r"""檢查專案內是否又出現寫死的 Windows 絕對路徑。

`AGENTS.md` §3 規定路徑一律由 `tools/project_paths.py` 解析、文件指令要能在任何平台照抄。
這支守門腳本掃描版控中的 `.py`／`.md`，發現 `C:\Python312` 這類寫死路徑就失敗。

例外：`docs/已驗證環境快照.md` 是「當時那台機器」的追溯紀錄，其中的實際路徑不改。

用法：
    python tools/selftest/check_portable_paths.py          # 掃描並回報
    python tools/selftest/check_portable_paths.py --list   # 只列出命中位置
退出碼 0 = 沒有寫死路徑。
"""

import argparse
import subprocess
import sys

BAD = ["C:\\Python312", "C:/Python312"]
ALLOW = {"docs/已驗證環境快照.md"}


def tracked_files():
    # core.quotepath=false + -z：中文檔名才不會被 git 轉義成 "\345\276..."（否則整批文件漏掃）
    p = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-z", "*.py", "*.md"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit("需要在 git 工作區內執行（git ls-files 失敗）")
    return [f for f in p.stdout.split("\0") if f.strip()]


def scan():
    hits = []
    for f in tracked_files():
        if f in ALLOW:
            continue
        try:
            text = open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for bad in BAD:
                if bad in line:
                    hits.append((f, no, line.strip()[:120]))
                    break
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="掃描寫死的 Windows 絕對路徑。")
    ap.add_argument("--list", action="store_true", help="只列出命中位置（預設也會列）")
    ap.parse_args(argv)

    hits = scan()
    if not hits:
        print("✓ 沒有寫死的 C:\\Python312 路徑（已排除 %s）" % "、".join(sorted(ALLOW)))
        return 0
    print("✗ 發現 %d 處寫死路徑：" % len(hits))
    for f, no, line in hits:
        print("  %s:%d  %s" % (f, no, line))
    print("\n改用 `python`／`.venv/bin/python`，路徑用正斜線；必要時經 tools/project_paths.py 解析。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
