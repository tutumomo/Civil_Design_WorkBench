import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from project_paths import accoreconsole as _acc  # noqa: E402
ACC = _acc()
"""AutoCAD 核心主控台 (accoreconsole) 封裝：DWT/DWG→DXF、DXF→DWG+PDF。
已處理的坑（docs\\踩坑紀錄.md L 節）：中文路徑→複製到英文暫存區；.scr 用 cp950 且 newline=""；
腳本必給完整路徑；卡在提示時逾時強制結束；中文版圖紙名「…公釐」。不碰使用者開著的 AutoCAD 視窗。
用法：
  python acc.py todxf  <來源.dwt|.dwg> <輸出.dxf>
  python acc.py publish <圖.dxf> [--pdf] [--paper "ISO full bleed A3 (420.00 x 297.00 公釐)"] [--ctb monochrome.ctb]
出圖型式預設用本專案的 tools\\acad\\plot\\monochrome.ctb（顏色 1~8 對應規定的線粗）；
該檔不存在時才退回 AutoCAD 的 monochrome.ctb。
"""
import os, sys, glob, shutil, subprocess, uuid, argparse

def find_acc():
    c = [ACC] if ACC else []
    if not c: raise SystemExit("找不到 accoreconsole.exe")
    return c[-1]

TMP_ROOT = os.path.join(os.path.expanduser("~"), "ArtCraft-Work", "acc_tmp")   # 純英文路徑
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_CTB = os.path.join(HERE, "plot", "monochrome.ctb")   # 本專案出圖型式（顏色→線粗）

def run(infile, lines, timeout=240, copies=()):
    """在英文暫存區執行腳本；回傳 (暫存資料夾, log 文字)"""
    work = os.path.join(TMP_ROOT, uuid.uuid4().hex[:8]); os.makedirs(work)
    ext = os.path.splitext(infile)[1].lower()
    src = os.path.join(work, "in" + ext); shutil.copy2(infile, src)
    for f in glob.glob(os.path.join(os.path.dirname(infile), "*.jpg")) + glob.glob(os.path.join(os.path.dirname(infile), "*.png")):
        shutil.copy2(f, work)                                  # DXF 影像為相對路徑外部參考
    for f in copies:
        if f and os.path.exists(f):
            shutil.copy2(f, os.path.join(work, os.path.basename(f)))   # 出圖型式表跟著進暫存區
    scr = os.path.join(work, "run.scr")
    body = ["FILEDIA 0", "CMDDIA 0"] + [l.replace("{W}", work) for l in lines] + ["_QUIT _Y", ""]
    open(scr, "w", encoding="cp950", newline="").write("\r\n".join(body))
    try:
        p = subprocess.run([find_acc(), "/i", src, "/s", scr], capture_output=True, timeout=timeout)
        log = p.stdout.decode("utf-16-le", errors="replace")
    except subprocess.TimeoutExpired:
        log = "TIMEOUT：腳本可能卡在提示，已強制結束"
    open(os.path.join(work, "acc_log.txt"), "w", encoding="utf-8").write(log)
    return work, log

def to_dxf(src, dst):
    work, log = run(src, [r'_DXFOUT "{W}\out.dxf" _V 2018 16'])
    out = os.path.join(work, "out.dxf")
    if not os.path.exists(out): raise SystemExit("DXFOUT 失敗：\n" + log[-1500:])
    shutil.copy2(out, dst); return dst

def publish(dxf, pdf=True, paper="ISO full bleed A3 (420.00 x 297.00 公釐)", ctb=None,
            pc3="DWG To PDF.pc3", orient="_L"):
    """DXF → 同名 DWG(2018)；pdf=True 時以目前配置(CTAB)出 PDF，配置範圍 1:1。"""
    ctb = ctb or (PROJECT_CTB if os.path.exists(PROJECT_CTB) else "monochrome.ctb")
    copies = []
    if os.path.isabs(ctb) or os.sep in ctb or "/" in ctb:
        copies = [ctb]
        ctb = "{W}\\" + os.path.basename(ctb)          # 複製到英文暫存區再指定
    L = [r'_SAVEAS 2018 "{W}\out.dwg"']
    if pdf:
        L += ["_-PLOT", "_Y", "", pc3, paper, "_M", orient, "_N", "_L", "1:1", "0,0",
              "_Y", ctb, "_Y", "_N", "_N", "_N", r'"{W}\out.pdf"', "_N", "_Y"]
    work, log = run(dxf, L, copies=copies)
    base = os.path.splitext(dxf)[0]; res = {}
    for ext in (".dwg", ".pdf") if pdf else (".dwg",):
        f = os.path.join(work, "out" + ext)
        if not os.path.exists(f): raise SystemExit(f"{ext} 未產生（檢查圖紙名稱/配置），log 尾段：\n" + log[-2000:])
        shutil.copy2(f, base + ext); res[ext] = base + ext
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("todxf"); a.add_argument("src"); a.add_argument("dst")
    b = sp.add_parser("publish"); b.add_argument("dxf"); b.add_argument("--pdf", action="store_true")
    b.add_argument("--paper", default="ISO full bleed A3 (420.00 x 297.00 公釐)"); b.add_argument("--ctb", default=None)
    A = ap.parse_args()
    print(to_dxf(A.src, A.dst) if A.cmd == "todxf" else publish(A.dxf, A.pdf, A.paper, A.ctb))
