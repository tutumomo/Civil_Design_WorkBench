import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from project_paths import (accoreconsole as _acc, artcraft_cli as _art,
                           opencadstudio_exe as _ocs)  # noqa: E402
ACC = _acc()
CADCRAFT = _art("CADCraft")
OCS = _ocs()
import os as _os
#: 後端選擇（環境變數 `CIVIL_AI_CAD_BACKEND`）。
#: `ocs`（預設，`auto` 同義）＝OpenCADStudio；找不到執行檔時自動退回下列傳統路徑。
#: `cadcraft`  ＝強制走傳統路徑（有 accoreconsole 用 accoreconsole，否則 cadcraft-cli），
#:               供 OCS 異常時的退路與跨後端比對。
#: 歷史：2026-11-08 舊版 OCS 在 Linux 出圖中文 SHX 亂碼，預設曾改回 `cadcraft`；
#: 2026-11-10 重編譯版（Windows）實測中文正確、線寬符合規定，預設切回 `ocs`。
#: Linux／macOS 尚未以新版重測，因此 OCS 開檔若回報 `missing_fonts` 會在 stderr 警告
#: （見 `_ocs_open`），務必目視 PDF 中文。細節：docs/CAD引擎選型_OpenCADStudio與CADCraft.md §13。
BACKEND = (_os.environ.get("CIVIL_AI_CAD_BACKEND") or "ocs").strip().lower()
"""AutoCAD 核心主控台 (accoreconsole) 封裝：DWT/DWG→DXF、DXF→DWG+PDF。
已處理的坑（docs\\踩坑紀錄.md L 節）：中文路徑→複製到英文暫存區；.scr 用 cp950 且 newline=""；
腳本必給完整路徑；卡在提示時逾時強制結束；中文版圖紙名「…公釐」。不碰使用者開著的 AutoCAD 視窗。
用法：
  python acc.py todxf  <來源.dwt|.dwg> <輸出.dxf>
  python acc.py publish <圖.dxf> [--pdf] [--paper "ISO full bleed A3 (420.00 x 297.00 公釐)"] [--ctb monochrome.ctb]
出圖型式預設用本專案的 tools\\acad\\plot\\monochrome.ctb（顏色 1~8 對應規定的線粗）；
該檔不存在時才退回 AutoCAD 的 monochrome.ctb。
"""
import os, sys, glob, shutil, subprocess, uuid, argparse, json

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

# ---------------------------------------------------------------- OpenCADStudio 後端
# 為什麼用「按需拉起」而不是常駐服務：本專案是單機工具鏈，常駐一個 GUI 級程序
# 換來的是開機負擔與連線埠衝突風險；而 OCS 服務實測 0.5 秒就緒，隨用隨起即可。

import contextlib, socket, tempfile, time, urllib.request, urllib.error


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ocs_wanted() -> bool:
    """是否應該走 OpenCADStudio 後端。"""
    if not OCS:
        return False
    if BACKEND == "cadcraft":
        return False
    return True


def _kill_tree(proc, grace=10.0):
    """殺掉整個 process group（AppImage 外殼 ＋ 它 spawn 的 opencadstudio 子進程）。"""
    import signal
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=grace)
        except Exception:
            proc.kill()
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        proc.terminate()
        pgid = None
    try:
        proc.wait(timeout=grace)
    except Exception:
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass
    time.sleep(0.2)


@contextlib.contextmanager
def ocs_service(timeout=30.0):
    """按需啟動 OpenCADStudio REST 服務，離開時結束它。

    產出 (base_url, token)。token 由 OCS_API_TOKEN 指定，避免解析啟動訊息。
    若本機已有服務在跑（同埠可連通）則直接沿用，不重啟。
    """
    if not OCS:
        raise SystemExit("找不到 opencadstudio；跑 python tools/project_paths.py --install 補裝")

    token = uuid.uuid4().hex
    port = _free_port()
    env = dict(os.environ, OCS_API_TOKEN=token)
    # AppImage 直接執行即可；若設定指向 squashfs-root/AppRun 也相容
    proc = subprocess.Popen([OCS, "--http", str(port), "--new"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=env, start_new_session=True)
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(base + "/ready",
                                             headers={"Authorization": "Bearer " + token})
                with urllib.request.urlopen(req, timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise SystemExit(f"OpenCADStudio 服務 {timeout}s 內未就緒（port {port}）")
        yield base, token
    finally:
        # Windows：opencadstudio 是 .cmd 包裝時，terminate() 只殺到 cmd.exe，
        # 真正的 OpenCADStudio.exe 會變孤兒（實測跑一次回歸殘留 17 個 --http 實例、約 2.9 GB），
        # 因此一律用 taskkill /T 連子行程一起殺。
        # Linux／macOS：AppImage 的 AppRun 也是外殼，只 terminate 外殼同樣留孤兒
        # （2026-11-08 實測殘留 6 個 --http 實例）；且孤兒結束時會把記憶體裡的舊設定
        # 回寫 settings.json，把已設好的 fonts_folder 蓋回 null。
        # 因此用 start_new_session 開獨立 process group，結束時整組殺。
        _kill_tree(proc)


def _bak_of(path):
    return os.path.splitext(path)[0] + ".bak"


def _rm_ocs_locks(*paths, bak_before=()):
    """清掉 OCS 的殘留，成品資料夾不得留雜物：
    · 被強殺後留下的 `.<檔名>.ocs.lock` 隱藏檔；
    · 覆寫既有檔時 OCS 自留的 `<檔名>.bak`——只刪「這次才出現」的（`bak_before` 為執行前已存在者，不動）。
    """
    for p in paths:
        lock = os.path.join(os.path.dirname(p), "." + os.path.basename(p) + ".ocs.lock")
        for f in (lock, _bak_of(p) if _bak_of(p) not in bak_before else None):
            if f:
                try:
                    os.remove(f)
                except OSError:
                    pass


def _ocs_post(base, token, path, payload, timeout=180):
    """POST 一個 JSON 到 OCS 並回傳解析後的 dict。

    失敗時把 OCS 的錯誤碼與訊息一併帶出（只印 HTTP 400 無法判斷是
    `destination_exists`、`audit_failed` 還是檔案被 GUI 佔用）。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:600]
        except Exception:
            detail = ""
        raise SystemExit("OCS %s 失敗（HTTP %s）：%s" % (path, e.code, detail))


def _ocs_open(base, token, path):
    """開檔並檢查。字型缺失時警告：缺 SHX 會讓 PDF 中文變亂碼或消失，而閘門抓不到。"""
    r = _ocs_post(base, token, "/open", {"path": path})
    if not r.get("ok"):
        raise SystemExit("OCS 開檔失敗：" + str(r.get("error")))
    missing = (r.get("state") or {}).get("missing_fonts") or []
    if missing:
        print("⚠ OCS 缺字型 %s（%s）：PDF 中文可能亂碼，請檢查 settings.fonts_folder 並目視 PDF；"
              "可設 CIVIL_AI_CAD_BACKEND=cadcraft 退回傳統路徑"
              % (os.path.basename(path), "、".join(map(str, missing))), file=sys.stderr)
    return r


def _ocs_save(base, token, target, document_id=None):
    """存檔並回傳 OCS 回應。

    上游 v2026.47 起，`/save` 對「已存在且內容不同」的目標固定回 400
    `destination_exists`（實測帶 `overwrite=true` 也無效，只有 `/save_verified` 接受），
    因此 DWG／DXF 一律走 `/save_verified`：存檔後重開並比對語意 manifest，
    正好接上本專案「完稿重開驗證」的規定。`/save_verified` 不支援 `.dwt` 等格式，
    該類目標改走 `/save`，並以「先改名為 `.prev`、失敗還原、成功刪除」避免同樣的 400。
    """
    ext = os.path.splitext(target)[1].lower()
    if ext in (".dwg", ".dxf"):
        body = {"path": target, "overwrite": True}
        if document_id:
            body["document_id"] = document_id
        return _ocs_post(base, token, "/save_verified", body)

    prev = target + ".prev"
    had_prev = os.path.exists(target)
    if had_prev:
        os.replace(target, prev)
    try:
        r = _ocs_post(base, token, "/save", {"path": target})
    except Exception:
        if had_prev and not os.path.exists(target):
            os.replace(prev, target)
        raise
    if r.get("ok") and os.path.exists(target):
        if had_prev:
            try:
                os.remove(prev)
            except OSError:
                pass
        return r
    if had_prev and not os.path.exists(target):
        os.replace(prev, target)
    return r


def ocs_publish(dxf, pdf=True):
    """用 OpenCADStudio 產 DWG（+PDF）。回傳 {'.dwg':…, '.pdf':…}。

    實測要點（docs/CAD引擎選型_OpenCADStudio與CADCraft.md §12）：
      · `layout` 必須給「圖紙名稱」或 `Model`，給 `all` 會把空的 Layout1 也輸出成空白頁
      · `plot_style` 指定 monochrome.ctb 才有正確的黑白出圖
      · 回應 `status: "waiting_input"` 是待命正常態，判成功看 `ok` 與 `result.pages`
      · 上游 v2026.47 的 `/save` 不接受覆寫既有檔，DWG 改走 `/save_verified`（見 `_ocs_save`）
    """
    dxf = os.path.abspath(str(dxf))
    base_path = os.path.splitext(dxf)[0]
    dwg = base_path + ".dwg"
    res = {}
    bak_before = tuple(b for b in (_bak_of(dxf), _bak_of(dwg)) if os.path.exists(b))
    with ocs_service() as (base, token):
        opened = _ocs_open(base, token, dxf)
        doc_id = (opened.get("state") or {}).get("document_id")
        r = _ocs_save(base, token, dwg, document_id=doc_id)
        if not r.get("ok") or not os.path.exists(dwg):
            raise SystemExit("OCS 存 DWG 失敗：" + str(r.get("error")))
        res[".dwg"] = dwg
        if pdf:
            pdf_path = base_path + ".pdf"
            # 必須傳專案 CTB 的絕對路徑：只給名稱時 OCS 會去 plot_styles_folder／
            # %APPDATA%\OpenCADStudio\plotstyles 找同名檔（內容與本專案規定不同），
            # 線寬整組偏移（0.09／0.30 mm…）且 check_delivery 抓不到（2026-11-10 實測）。
            ctb = PROJECT_CTB if os.path.exists(PROJECT_CTB) else "monochrome.ctb"
            body = {"path": pdf_path,
                    "layout": _paper_layout(dxf),
                    "plot_style": ctb}
            r = _ocs_post(base, token, "/plot", body)
            if not r.get("ok") or not os.path.exists(pdf_path):
                raise SystemExit("OCS 出圖失敗：" + str(r.get("error")))
            pages = (r.get("result") or {}).get("pages")
            res[".pdf"] = pdf_path
            res["pages"] = pages
    _rm_ocs_locks(dxf, dwg, bak_before=bak_before)
    return res


def ocs_todxf(src, dst):
    """用 OpenCADStudio 轉檔；輸出格式由 `dst` 副檔名決定（.dxf／.dwg／.dwt 皆可）。"""
    src, dst = os.path.abspath(str(src)), os.path.abspath(str(dst))
    bak_before = tuple(b for b in (_bak_of(src), _bak_of(dst)) if os.path.exists(b))
    with ocs_service() as (base, token):
        opened = _ocs_open(base, token, src)
        doc_id = (opened.get("state") or {}).get("document_id")
        r = _ocs_save(base, token, dst, document_id=doc_id)
        if not r.get("ok") or not os.path.exists(dst):
            raise SystemExit("OCS 存檔失敗（%s）：%s" % (os.path.basename(dst), r.get("error")))
    _rm_ocs_locks(src, dst, bak_before=bak_before)
    return dst


def _paper_layout(dxf, default="Layout1"):
    """CADCraft 出圖要指定配置名稱；各工具建的配置叫「斷面圖」「全區工程位置圖」等，
    不能寫死。以 ezdxf 讀第一個非 Model 的配置；讀不到才退回預設值。"""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf))
        names = [l.name for l in doc.layouts if l.name.lower() != "model"]
        return names[0] if names else default
    except Exception:
        return default


def to_dxf(src, dst):
    if _ocs_wanted():
        return ocs_todxf(src, dst)
    if not ACC and CADCRAFT:
        p = subprocess.run([CADCRAFT, "convert", str(src), str(dst)], capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(dst):
            raise SystemExit("CADCraft convert 失敗：\n" + p.stderr)
        return dst
    work, log = run(src, [r'_DXFOUT "{W}\out.dxf" _V 2018 16'])
    out = os.path.join(work, "out.dxf")
    if not os.path.exists(out): raise SystemExit("DXFOUT 失敗：\n" + log[-1500:])
    shutil.copy2(out, dst); return dst

def to_dwg(src, dst):
    """DXF→DWG（AutoCAD 2018）轉檔，不出 PDF。後端選擇同 `to_dxf`。"""
    if _ocs_wanted():
        return ocs_todxf(src, dst)
    if not ACC and CADCRAFT:
        p = subprocess.run([CADCRAFT, "convert", str(src), str(dst)], capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(dst):
            raise SystemExit("CADCraft convert 失敗：\n" + p.stderr)
        return dst
    work, log = run(src, [r'_SAVEAS 2018 "{W}\out.dwg"'])
    out = os.path.join(work, "out.dwg")
    if not os.path.exists(out): raise SystemExit("SAVEAS 失敗：\n" + log[-1500:])
    shutil.copy2(out, dst); return dst

def publish(dxf, pdf=True, paper="ISO full bleed A3 (420.00 x 297.00 公釐)", ctb=None,
            pc3="DWG To PDF.pc3", orient="_L", layout=""):
    """DXF → 同名 DWG(2018)；pdf=True 時以目前配置(CTAB)出 PDF，配置範圍 1:1。

    後端由 `CIVIL_AI_CAD_BACKEND` 決定（預設 ocs；cadcraft 為傳統退路），見檔頭說明。
    """
    if _ocs_wanted():
        r = ocs_publish(dxf, pdf=pdf)
        r.pop("pages", None)
        return r
    if not ACC and CADCRAFT:
        base = os.path.splitext(dxf)[0]
        dwg = base + ".dwg"
        p = subprocess.run([CADCRAFT, "convert", str(dxf), str(dwg)], capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(dwg):
            raise SystemExit("CADCraft 轉 DWG 失敗：\n" + p.stderr)
        res = {".dwg": dwg}
        if pdf:
            pdf_path = base + ".pdf"
            plot_args = {
                "path": str(pdf_path),
                "layout": _paper_layout(dxf),
                "landscape": True,
                "plotArea": "layout",
                "fit": False,
                "scale": 1.0
            }
            cmd = "plot " + json.dumps(plot_args, ensure_ascii=False)
            p_pdf = subprocess.run([CADCRAFT, "run", str(dxf), "--cmd", cmd], capture_output=True, text=True)
            if not os.path.exists(pdf_path):
                cmd_fallback = "plot " + json.dumps({"path": str(pdf_path), "fit": True}, ensure_ascii=False)
                subprocess.run([CADCRAFT, "run", str(dxf), "--cmd", cmd_fallback], capture_output=True, text=True)
            if not os.path.exists(pdf_path):
                raise SystemExit("CADCraft 出圖 PDF 失敗：\n" + p_pdf.stderr)
            res[".pdf"] = pdf_path
        return res
    ctb = ctb or (PROJECT_CTB if os.path.exists(PROJECT_CTB) else "monochrome.ctb")
    copies = []
    if os.path.isabs(ctb) or os.sep in ctb or "/" in ctb:
        copies = [ctb]
        ctb = "{W}\\" + os.path.basename(ctb)          # 複製到英文暫存區再指定
    L = [r'_SAVEAS 2018 "{W}\out.dwg"']
    if pdf:
        L += ["_-PLOT", "_Y", layout, pc3, paper, "_M", orient, "_N", "_L", "1:1", "0,0",
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
    b.add_argument("--layout", default="", help="圖紙空間名稱；省略則用目前配置(CTAB)")
    A = ap.parse_args()
    print(to_dxf(A.src, A.dst) if A.cmd == "todxf" else publish(A.dxf, A.pdf, A.paper, A.ctb, layout=A.layout))
