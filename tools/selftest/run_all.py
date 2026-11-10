r"""統一測試入口：一次跑完專案的所有自測，回報每一支的結果與耗時。

為什麼要這個模組
----------------
專案的自測散在好幾處（`tools/selftest/`、`tools/boq/selftest/`、`tools/regs/`），
「改了哪裡該跑哪幾支」只寫在 `AGENTS.md` §5 的文字裡，靠人記得跑。本模組把它變成
一條指令，並在 CI 上當唯一入口。

用法
----
    python tools\selftest\run_all.py                 # 跑全部（回歸需要本機 CAD 後端）
    python tools\selftest\run_all.py --changed       # 只跑與 git 改動範圍相關的測試
    python tools\selftest\run_all.py --no-cad        # 跳過需要 OpenCADStudio 的回歸（CI 用）
    python tools\selftest\run_all.py --with-ocss     # 另外跑 OCSS 交叉驗算（需桌面程式）
    python tools\selftest\run_all.py --only design-core,regq
    python tools\selftest\run_all.py --skip regs-verified  # 排除已知缺口（例：尚未進索引的規範）
    python tools\selftest\run_all.py --list          # 列出測試 id

退出碼 0 = 選到的每一支都通過。任一失敗即 1，並印出該支輸出的最後幾行。
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable

# 對照表：AGENTS.md §5「改過工具後必跑」的程式版。改了路徑就同步改這裡與文件。
TESTS = [
    {
        "id": "design-core",
        "cmd": ["tools/selftest/design_core_selftest.py"],
        "globs": ["tools/design/", "tools/selftest/"],
        "what": "設計引擎手算對照（unittest）",
    },
    {
        "id": "design-workbench",
        "cmd": ["tools/selftest/design_workbench_selftest.py"],
        "globs": ["tools/design/", "tools/selftest/"],
        "what": "設計工作台 API／目錄規則",
    },
    {
        "id": "design-launch",
        "cmd": ["tools/selftest/design_launch_check.py", "--all"],
        "globs": ["tools/design/", "tools/selftest/"],
        "what": "計算器上架檢核 G0~G8",
    },
    {
        "id": "regq",
        "cmd": ["tools/regs/regq_selftest.py"],
        "globs": ["tools/regs/", "tools/selftest/"],
        "what": "規範查詢引擎與主題卡",
    },
    {
        "id": "regs-verified",
        "cmd": ["tools/regs/verified_selftest.py"],
        "globs": ["tools/regs/", "tools/selftest/"],
        "what": "已驗證公式／圖表庫",
    },
    {
        "id": "boq-rules",
        "cmd": ["tools/boq/selftest/selftest_rules.py"],
        "globs": ["tools/boq/", "tools/selftest/"],
        "what": "預算費率核心（對真實預算書）",
    },
    {
        "id": "regression",
        "cmd": ["tools/selftest/regression.py"],
        "globs": ["tools/"],  # AGENTS.md §3：改動 tools/ 任一處都必跑全案回歸
        "what": "全案回歸（需本機 CAD 後端與既有 out/ 產物）",
        "needs_cad": True,
    },
    {
        "id": "ocss-checks",
        "cmd": ["tools/crosscheck/ocss_crosscheck.py", "checks"],
        "globs": ["tools/crosscheck/"],
        "what": "OCSS 交叉驗算（需桌面程式開啟）",
        "needs_ocss": True,
    },
]


def _changed_paths():
    """git 的改動範圍（含未追蹤檔）。不在 git 工作區時回傳空集合。"""
    out = []
    for args in (["git", "diff", "--name-only", "HEAD"],):
        try:
            p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except OSError:
            return set()
        if p.returncode != 0:
            return set()
        out += [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    p = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode == 0:
        out += [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    return {p.replace("\\", "/") for p in out}


def select(args):
    skipped_ids = set()
    for chunk in (args.skip or []):
        skipped_ids |= {x.strip() for x in chunk.split(",") if x.strip()}
    tests = [t for t in TESTS
             if (not t.get("needs_ocss") or args.with_ocss)
             and (not t.get("needs_cad") or not args.no_cad)
             and t["id"] not in skipped_ids]
    if args.only:
        ids = []
        for chunk in args.only:
            ids += [x.strip() for x in chunk.split(",") if x.strip()]
        unknown = [i for i in ids if i not in {t["id"] for t in TESTS}]
        if unknown:
            print("找不到測試 id：%s（用 --list 查看）" % "、".join(unknown))
            return None
        tests = [t for t in tests if t["id"] in ids]
        return tests
    if args.changed:
        changed = _changed_paths()
        hit = [t for t in tests if any(c.startswith(g) for c in changed for g in t["globs"])]
        if not hit:
            print("改動（%d 檔）未對應任何自測，改跑全部。" % len(changed))
            return tests
        # 任一 tools/ 改動都命中回歸（globs 含 "tools/"），這是刻意照 AGENTS.md §3
        return hit
    return tests


def run_one(t, tail_lines=40):
    print("→ %-18s %s" % (t["id"], t["what"]), flush=True)
    started = time.time()
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    p = subprocess.run([PY] + [c.replace("/", os.sep) for c in t["cmd"]],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    secs = time.time() - started
    ok = p.returncode == 0
    print("  %s %-18s %5.1fs" % ("[ok  ]" if ok else "[FAIL]", t["id"], secs), flush=True)
    if not ok:
        out = ((p.stdout or "") + (p.stderr or "")).rstrip().splitlines()
        for ln in out[-tail_lines:]:
            print("    " + ln)
    return ok, secs


def main(argv=None):
    ap = argparse.ArgumentParser(description="統一測試入口：跑專案所有自測並彙總結果。")
    ap.add_argument("--changed", action="store_true", help="只跑與 git 改動範圍相關的測試")
    ap.add_argument("--no-cad", action="store_true", help="跳過需要本機 CAD 後端的全案回歸")
    ap.add_argument("--with-ocss", action="store_true", help="另外跑 OCSS 交叉驗算")
    ap.add_argument("--only", action="append", metavar="id", help="只跑指定測試，可重複或逗號分隔")
    ap.add_argument("--skip", action="append", metavar="id",
                    help="排除指定測試（例：已知缺口），可重複或逗號分隔")
    ap.add_argument("--list", action="store_true", help="列出測試 id 後結束")
    ap.add_argument("--tail", type=int, default=40, help="失敗時印出的最後幾行（預設 40）")
    args = ap.parse_args(argv)

    if args.list:
        for t in TESTS:
            flags = "".join((" [需CAD]" if t.get("needs_cad") else "",
                             " [需OCSS]" if t.get("needs_ocss") else ""))
            print("%-18s %s%s" % (t["id"], t["what"], flags))
        return 0

    tests = select(args)
    if tests is None:
        return 2
    if not tests:
        print("沒有選到任何測試。")
        return 0

    print("自測：%d 支" % len(tests))
    results = []
    for t in tests:
        ok, secs = run_one(t, args.tail)
        results.append((t["id"], ok, secs))

    failed = [r for r in results if not r[1]]
    print()
    if not failed:
        print("✓ 全部通過（%d 支，%.1fs）" % (len(results), sum(r[2] for r in results)))
        return 0
    print("✗ 失敗 %d 支：%s" % (len(failed), "、".join(r[0] for r in failed)))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
