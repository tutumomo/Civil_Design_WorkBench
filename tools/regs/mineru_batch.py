"""One-command MinerU draft for a regulation that has a PDF (SOP step 3).

usage: python -E -P -X utf8 mineru_batch.py <src id> [<part pdf name>]

Copies the PDF to an ASCII-only path (MinerU's llama.cpp/Windows code page breaks on Chinese paths),
runs `mineru-kit parse --tier basic -f middle_json` from the venv in _temp/mineru_test, then calls
mineru_import.build() so the draft shows up in the web drawer. Drafts never enter the index.
Needs ~0.2 s/page on the RTX 4080; long runs write the log to _temp/mineru_out/<src>.log.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
KIT = ROOT / "_temp" / "mineru_test" / "venv" / "Scripts" / "mineru-kit.exe"
WORK = Path(os.environ.get("MINERU_WORK")
            or (Path(__file__).resolve().parents[2] / "_temp" / "mineru"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src, part = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    if not KIT.exists():
        sys.exit(f"找不到 MinerU 環境 {KIT}；見 docs/規範查詢台.md「MinerU 自動辨識草稿」")
    import page_assets as P
    import mineru_import
    con = sqlite3.connect(ROOT / "data" / "法規" / "_regs_index.sqlite")
    row = con.execute("SELECT file FROM src WHERE id=?", (src,)).fetchone()
    if not row:
        sys.exit(f"索引沒有規範代號 {src}")
    pdf = P.find_pdf(row[0], part)
    if not pdf:
        sys.exit("這份規範沒有 PDF（網頁來源），MinerU 不適用；請人工轉錄")
    (WORK / "in").mkdir(parents=True, exist_ok=True)
    tag = src + ("_" + str(abs(hash(part)) % 10000) if part else "")
    shutil.copy(pdf, WORK / "in" / f"{tag}.pdf")
    outd = WORK / "out" / tag
    log = ROOT / "_temp" / "mineru_out" / f"{tag}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1")
    with open(log, "w", encoding="utf-8") as lf:
        r = subprocess.run([str(KIT), "parse", f"in/{tag}.pdf", "-o", f"out/{tag}", "--tier", "basic", "-f", "middle_json"],
                           cwd=str(WORK), env=env, stdout=lf, stderr=subprocess.STDOUT)
    if r.returncode:
        sys.exit(f"MinerU 失敗（exit {r.returncode}），看 {log}")
    js = next(outd.rglob("*.json"))
    n, w = mineru_import.build(src, js, part)
    shutil.copytree(outd, ROOT / "_temp" / "mineru_out" / tag, dirs_exist_ok=True)
    print(f"{src}: {n} 頁草稿，其中 {w} 頁有數字無法核對 → tools/regs/auto/{src}.json")


if __name__ == "__main__":
    main()
