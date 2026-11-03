"""案件交付包：一份案件主檔 → 三軸（設計圖／預算書／設計報告）一次跑完並產交付清單。

設計原則
--------
1. **不重新實作**：三軸各自呼叫既有的確定性工具（`boq_build.py`、`make_report.py`、`check_delivery.py`），
   本檔只負責「串接、收集退出碼、產交付清單」。工具改了不會有兩份邏輯打架。
2. **主檔是超集**：`boq` 段直接放 `boq_build.py` 的案件 JSON，`report` 段直接放 `make_report.py` 的案件 JSON，
   本檔原樣落地到 `<out>/_case/` 再呼叫工具 —— 因此各產線的 schema 升級時本檔不必跟著改。
3. **退出碼說話**：只有「啟用的每一軸都通過自己的驗證」才回 0。任何一軸失敗，交付清單會標原因。

主檔格式（`案件主檔.json`）
--------------------------
    {
      "title": "案名（用於輸出檔名與清單標題）",
      "out_dir": "輸出資料夾",
      "boq":    { ... }  或 "boq_path": "相對/絕對路徑.json"      // 選用
      "report": { ... }  或 "report_path": "…/AC刨鋪5cm工程.json" // 選用
      "drawing": {                                                 // 選用
        "dxf": "…\\<案名>_現況平面圖_A3.dxf",
        "scale": 700,
        "require_dwg": true,
        "require_layers": ["10_道路邊線_現況", "20_建物"]
      }
    }

用法
----
    set PYTHONIOENCODING=utf-8
    python <專案根目錄>\\tools\\case_package\\case_package.py ^
        <案件主檔.json> [--out-dir DIR] [--only boq,report,drawing] [--no-pdf] [--allow-placeholder]

產出
----
    <out>\\<title>_案件交付清單.md      逐項交付狀態、檔案大小、驗證結果、待補事項
    <out>\\<title>_交付狀態.json        同上（機器可讀，供後續自動化）
    <out>\\_case\\*.json               各軸實際使用的輸入（可追溯到當次執行）
    <out>\\_log_<軸>.txt               各軸完整輸出（失敗時第一手證據）
"""

import argparse
import sys as _sys
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from project_paths import python_exe  # noqa: E402
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # <專案根目錄>
PY = python_exe()

TOOLS = {
    "boq": os.path.join(ROOT, "tools", "boq", "boq_build.py"),
    "report": os.path.join(ROOT, "tools", "report", "make_report.py"),
    "check": os.path.join(ROOT, "tools", "a3_sheet", "check_delivery.py"),
    "section": os.path.join(ROOT, "tools", "wall_section", "make_wall_section.py"),
    "takeoff": os.path.join(ROOT, "tools", "takeoff", "dxf_takeoff.py"),
    "paving": os.path.join(ROOT, "tools", "takeoff", "paving_extent.py"),
    "price_audit": os.path.join(ROOT, "tools", "boq", "price_audit.py"),
}

AXIS_NAMES = {"boq": "預算書", "report": "設計報告",
              "drawing": "設計圖（現況平面圖）", "section": "設計圖（擋土牆斷面圖）"}


def _run(cmd, log_path):
    """執行並把完整輸出落到 log；回傳 (exit_code, tail)。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    ms = (time.time() - t0) * 1000
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("CMD: " + " ".join(cmd) + "\n")
        f.write(f"EXIT: {r.returncode}  ({ms:.0f} ms)\n")
        f.write("-" * 70 + "\nSTDOUT\n" + "-" * 70 + "\n" + (r.stdout or ""))
        f.write("\n" + "-" * 70 + "\nSTDERR\n" + "-" * 70 + "\n" + (r.stderr or ""))
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode, "\n".join(tail[-12:])


def _files(paths):
    out = []
    for p in paths:
        if p and os.path.exists(p):
            out.append({"path": p, "bytes": os.path.getsize(p)})
    return out


# --------------------------------------------------------------------------- #
# 各軸
# --------------------------------------------------------------------------- #
def run_boq(master, out_dir, no_pdf):
    case = master.get("boq")
    if case is None and master.get("boq_path"):
        case = json.load(open(os.path.join(ROOT, master["boq_path"])
                              if not os.path.isabs(master["boq_path"]) else master["boq_path"],
                              encoding="utf-8"))
    if case is None:
        return None

    case_dir = os.path.join(out_dir, "_case")
    os.makedirs(case_dir, exist_ok=True)
    case_path = os.path.join(case_dir, "boq_case.json")
    json.dump(case, open(case_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    sub = os.path.join(out_dir, "預算書")
    cmd = [PY, TOOLS["boq"], case_path, "--out-dir", sub]
    if no_pdf:
        cmd.append("--no-pdf")
    code, tail = _run(cmd, os.path.join(out_dir, "_log_boq.txt"))

    name = case.get("project", master.get("title", "未命名"))
    base = os.path.join(sub, f"{name}_預算書")
    files = _files([base + ".xlsx", base + ".pdf", base + "_計算書.json"])
    ok = code == 0 and any(f["path"].endswith(".xlsx") for f in files)
    return {"axis": "boq", "name": AXIS_NAMES["boq"], "ok": ok, "returncode": code,
            "files": files, "log": tail,
            "note": "xlsx 回讀總計已與計算值比對；gridcraft-cli check round-trip 已驗" if ok else "失敗"}


def run_report(master, out_dir, no_pdf, allow_placeholder=False):
    case = master.get("report")
    if case is None and master.get("report_path"):
        p = master["report_path"]
        p = p if os.path.isabs(p) else os.path.join(ROOT, p)
        case = json.load(open(p, encoding="utf-8"))
    if case is None:
        return None

    case_dir = os.path.join(out_dir, "_case")
    os.makedirs(case_dir, exist_ok=True)
    case_path = os.path.join(case_dir, "report_case.json")
    json.dump(case, open(case_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    sub = os.path.join(out_dir, "設計報告")
    cmd = [PY, TOOLS["report"], "--case", case_path, "--out-dir", sub]
    if no_pdf:
        cmd.append("--no-pdf")
    if allow_placeholder:
        # 案名／主辦機關未確認時，報告工具預設 exit 4（使用者規範）。回歸測試與
        # 示範案件需要「先產得出來」，才由呼叫端明確放行。
        cmd.append("--allow-placeholder")
    code, tail = _run(cmd, os.path.join(out_dir, "_log_report.txt"))

    # 設計段落注入失敗（case_core._design_sections 拋錯）會讓第 6/7/8/9/11 章整批消失，
    # 而報告工具照樣 exit 0 → 必須在這裡變成 axis 失敗。
    # 實例：一句 `%d` 收到 None，把四個章節整批洗掉，全軸仍顯示「全部通過」。
    if os.path.exists(case_path):
        try:
            _d = json.load(open(case_path, encoding="utf-8"))
            _err = (_d.get("_derived") or {}).get("design_sections_error")
            if _err:
                code = 1
                tail = (tail or "") + "\n[設計段落注入失敗] %s\n" % _err
        except Exception:
            pass

    # 報告工具以「案件 full_name 或 title」命名；用實際檔案掃描避免猜錯
    files = []
    if os.path.isdir(sub):
        for fn in sorted(os.listdir(sub)):
            if fn.lower().endswith((".docx", ".pdf")):
                files.append({"path": os.path.join(sub, fn),
                              "bytes": os.path.getsize(os.path.join(sub, fn))})
    ok = code == 0 and any(f["path"].lower().endswith(".docx") for f in files)
    return {"axis": "report", "name": AXIS_NAMES["report"], "ok": ok, "returncode": code,
            "files": files, "log": tail,
            "note": "docx 已產出；章節內容完整度須人工複核（標示「需人工補」者）" if ok else "失敗"}


def run_drawing(master, out_dir):
    d = master.get("drawing")
    if not d:
        return None
    dxf = d.get("dxf")
    if not dxf:
        return {"axis": "drawing", "name": AXIS_NAMES["drawing"], "ok": False,
                "returncode": None, "files": [], "note": "主檔未指定 drawing.dxf", "log": ""}
    dxf = dxf if os.path.isabs(dxf) else os.path.join(ROOT, dxf)

    cmd = [PY, TOOLS["check"], dxf, "--scale", str(d.get("scale", 600))]
    if d.get("require_dwg", True):
        cmd.append("--require-dwg")
    for lay in d.get("require_layers", []):
        cmd += ["--require-layer", lay]
    code, tail = _run(cmd, os.path.join(out_dir, "_log_drawing.txt"))

    files = _files([dxf, os.path.splitext(dxf)[0] + ".dwg",
                    os.path.splitext(dxf)[0] + ".pdf",
                    os.path.splitext(dxf)[0] + ".png"])

    # ---- 道路案：圖／數對帳 ----
    # 平面圖只畫「現況」，刨鋪範圍要用 paving_extent.py 由實測邊線產生後才量得到。
    # 產生後以 `15_刨鋪範圍` 圖層的多邊形面積對 `area_m2`（面積才是決定 AC 體積的量）。
    extra_note = ""
    try:
        _mdl_d = CC.quantity_context(master)[0]
    except Exception:
        _mdl_d = (master.get("quantities") or {}).get("model") or "road"
    if _mdl_d == "road":
        # 案件主檔一律用 _case_path；out_dir 現在是 out\<案名>，dirname(out_dir) 不再是案件資料夾。
        case_json = master.get("_case_path") or os.path.join(ROOT, "cases",
                                                             master.get("name") or "", "case.json")
        # 不可寫死某個案名：預設找「該案自己的 model\road_edges_meta.json」。
        meta = d.get("road_edges_meta") or os.path.join(
            os.path.dirname(case_json), "model", "road_edges_meta.json")
        meta = meta if os.path.isabs(meta) else os.path.join(ROOT, meta)
        pav_dxf = os.path.join(os.path.dirname(dxf),
                               os.path.basename(dxf).replace("_現況平面圖_A3", "_刨鋪範圍_TWD97"))
        takeoff = None
        if os.path.exists(meta):
            pcmd = [PY, TOOLS["paving"], meta, "--out", pav_dxf,
                    "--case", case_json]
            pcode, plog = _run(pcmd, os.path.join(out_dir, "_log_drawing_paving.txt"))
            tail = tail + "\n[刨鋪範圍產生]\n" + plog
            if pcode != 0:
                code = pcode
            files += _files([pav_dxf])
            if pcode == 0:
                takeoff = "刨鋪範圍"
        elif os.path.exists(pav_dxf):
            # 實測邊線檔（road_edges_meta.json）可能已被清掉，但刨鋪範圍圖還在。
            # 這時不能直接跳過量測 —— 面積是 AC 體積的唯一來源，跳過等於放行未對帳的數量。
            files += _files([pav_dxf])
            takeoff = "刨鋪範圍（沿用既有 DXF，無 road_edges_meta.json）"
        else:
            code = 1
            extra_note = "；⚠ 找不到 road_edges_meta.json，也沒有既有刨鋪範圍 DXF，無法對帳"
        if takeoff:
            tcmd = [PY, TOOLS["takeoff"], pav_dxf, "--case", case_json, "--tol", "1.0"]
            tcode, tlog = _run(tcmd, os.path.join(out_dir, "_log_drawing_takeoff.txt"))
            tail = tail + "\n[圖／數對帳 %s]\n" % takeoff + tlog
            if tcode != 0:
                code = tcode
            extra_note = "；%s；圖／數對帳%s" % (
                takeoff, "相符" if tcode == 0 else "未通過")

    return {"axis": "drawing", "name": AXIS_NAMES["drawing"], "ok": code == 0,
            "returncode": code, "files": files, "log": tail,
            "note": ("check_delivery.py E1~E18 通過" + extra_note) if code == 0
                    else "品管檢核或圖／數對帳未通過"}


def run_section(master, out_dir, no_pdf):
    """擋土牆斷面圖軸：需要 master["section"]（scale／out）或 quantities.model == wall。"""
    case_path = master.get("_case_path")
    sec = master.get("section")
    if not sec:
        return None
    if not case_path:
        return {"axis": "section", "name": AXIS_NAMES["section"], "ok": False,
                "returncode": None, "files": [],
                "note": "section 軸只支援 civil-case/1 統一案件檔", "log": ""}

    # scale 可為整數（1:N）或 "auto"（由 make_wall_section 依斷面外廓自動挑標準比例）。
    # 預設 auto：右欄保留 183 mm 後，原本寫死 1:20 的 4 m 牆會超寬，不能再當預設。
    _sc = sec.get("scale", "auto")
    scale = "auto" if str(_sc).lower() == "auto" else int(_sc)
    out = sec.get("out") or os.path.join(out_dir, "S-01_擋土牆標準斷面圖.dxf")
    out = out if os.path.isabs(out) else os.path.join(ROOT, out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    cmd = [PY, TOOLS["section"], case_path, "--scale", str(scale), "--out", out]
    if sec.get("project"):
        cmd += ["--project", sec["project"]]
    if not no_pdf:
        cmd.append("--publish")
    code, tail = _run(cmd, os.path.join(out_dir, "_log_section.txt"))

    # --scale auto 時，實際採用的比例寫在出圖輸出（"自動比例：…→ 採 1:25"）。
    # check_delivery 只吃整數，所以要把解析出來的比例傳給它，不能傳 "auto"。
    if scale == "auto":
        import re as _re2
        _m2 = _re2.search(r"採 1:(\d+)", tail or "")
        if _m2:
            scale = int(_m2.group(1))
        else:
            scale = 20

    # 另產配筋圖（鋼筋依配筋設計配置、右欄為配筋表）：擋土牆 S-02、排水溝 D-02
    rebar_out = None
    _mdl = (master.get("quantities") or {}).get("model")
    if _mdl in ("wall", "channel", "slope") and _mdl != "slope":
        rebar_out = os.path.join(
            os.path.dirname(out),
            "S-02_擋土牆配筋圖.dxf" if _mdl == "wall" else "D-02_排水溝配筋圖.dxf")
        rcmd = [PY, TOOLS["section"], case_path, "--scale", str(scale),
                "--rebar", "--out", rebar_out]
        if not no_pdf:
            rcmd.append("--publish")
        rcode, rtail = _run(rcmd, os.path.join(out_dir, "_log_section_rebar.txt"))
        tail = tail + "\n[配筋圖 S-02]\n" + rtail
        if rcode != 0:
            code = rcode

    base = os.path.splitext(out)[0]
    files = _files([out, base + ".dwg", base + ".pdf", base + "_pdf.png"])
    if rebar_out:
        rb = os.path.splitext(rebar_out)[0]
        files += _files([rebar_out, rb + ".dwg", rb + ".pdf", rb + "_pdf.png"])
    ok = code == 0 and any(f["path"].endswith(".dxf") for f in files)

    # 用既有品管器驗這張斷面圖（E1~E18 全套；建物/剖面線圖層換成擋土牆的）
    check_log = ""
    if ok:
        pass
    if ok and rebar_out:
        rbc = [PY, TOOLS["check"], rebar_out, "--scale", str(scale), "--layout", "斷面圖",
               "--building-layer", "30_擋土牆混凝土", "--hatch-layer", "31_擋土牆剖面線"]
        _rbl = (("30_擋土牆混凝土", "40_鋼筋", "41_排水孔", "42_尺寸") if _mdl == "wall"
                else ("30_擋土牆混凝土", "40_鋼筋", "34_溝內腔", "42_尺寸"))
        for lay in _rbl:
            rbc += ["--require-layer", lay]
        rcode2, rlog2 = _run(rbc, os.path.join(out_dir, "_log_section_check_rebar.txt"))
        check_log += "\n[S-02 配筋圖品管]\n" + rlog2
        ok = ok and (rcode2 == 0)
    if ok:
        # 必要圖層依模型不同：擋土牆有排水孔，排水溝沒有（有溝內腔）
        try:
            _model = (master.get("quantities") or {}).get("model") or "road"
        except Exception:
            _model = "road"
        if _model == "channel":
            req_layers = ("30_擋土牆混凝土", "34_溝內腔", "40_鋼筋", "42_尺寸")
            _bld, _htc = "30_擋土牆混凝土", "31_擋土牆剖面線"
        elif _model == "slope":
            # 邊坡沒有混凝土／鋼筋／排水孔 —— 必要圖層是坡面線、坡體、尺寸
            req_layers = ("35_坡面線", "36_坡體", "42_尺寸")
            _bld, _htc = "36_坡體", "36_坡體"
        else:
            req_layers = ("30_擋土牆混凝土", "40_鋼筋", "41_排水孔", "42_尺寸")
            _bld, _htc = "30_擋土牆混凝土", "31_擋土牆剖面線"

        ccmd = [PY, TOOLS["check"], out, "--scale", str(scale), "--layout", "斷面圖",
                "--building-layer", _bld, "--hatch-layer", _htc]
        for lay in req_layers:
            ccmd += ["--require-layer", lay]
        ccode, check_log = _run(ccmd, os.path.join(out_dir, "_log_section_check.txt"))
        ok = (ccode == 0)
        code = ccode
        tail = tail + "\n[品管 check_delivery E1~E18]\n" + check_log

    # ---- 圖／數對帳：圖上量到的混凝土淨面積必須等於數量模型的斷面積 ----
    # 這一步抓的是 E1~E18 抓不到的東西：圖形正確但數量畫錯（例如內腔多邊形重複、
    # 外框含內腔沒扣）。實測排水溝曾因內腔畫兩次而淨面積差 96%，品管完全看不出來。
    takeoff_log = ""
    if ok and _mdl != "slope":
        tcmd = [PY, TOOLS["takeoff"], out, "--case", case_path, "--tol", "0.5"]
        tcode, tlog = _run(tcmd, os.path.join(out_dir, "_log_section_takeoff.txt"))
        takeoff_log = tlog
        tail = tail + "\n[圖／數對帳 " + os.path.basename(out) + "]\n" + tlog
        if tcode != 0:
            ok = False
            code = tcode
        if rebar_out:
            t2 = [PY, TOOLS["takeoff"], rebar_out, "--case", case_path, "--tol", "0.5"]
            t2code, t2log = _run(t2, os.path.join(out_dir, "_log_section_takeoff_rebar.txt"))
            tail = tail + "\n[圖／數對帳 " + os.path.basename(rebar_out) + "]\n" + t2log
            if t2code != 0:
                ok = False
                code = t2code

    # ---- 配筋圖核算：量圖上鋼筋圓點的實際間距，對配筋設計的間距 ----
    # 這是第四道閘門：前一道驗「面積」，這一道驗「鋼筋排法」。
    # 實測：牆身 0.30 m 的設計（間距 270）配上 0.35 m 的舊圖（220）→ 不符、exit 1。
    if ok and rebar_out:
        rbcmd = [PY, TOOLS["takeoff"], rebar_out, "--rebar", "--case", case_path]
        rbcode, rblog = _run(rbcmd, os.path.join(out_dir, "_log_section_rebar_takeoff.txt"))
        tail = tail + "\n[配筋圖核算 " + os.path.basename(rebar_out) + "]\n" + rblog
        if rbcode != 0:
            ok = False
            code = rbcode

    return {"axis": "section", "name": AXIS_NAMES["section"], "ok": ok,
            "returncode": code, "files": files, "log": tail,
            "note": ("斷面圖已產出、E1~E18 通過、圖／數對帳相符、配筋圖間距相符" if ok
                     else "斷面圖產出、品管、圖／數對帳或配筋圖核算未通過")}


# --------------------------------------------------------------------------- #
# 交付清單
# --------------------------------------------------------------------------- #
def write_manifest(master, out_dir, results):
    title = master.get("title", "未命名案件")
    enabled = [r for r in results if r]
    ok_all = all(r["ok"] for r in enabled)

    lines = [f"# {title}　案件交付清單", "",
             f"- 產製時間：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 主檔：`{master.get('_master_path', '')}`",
             f"- 整體狀態：**{'全部通過' if ok_all else '有未通過項目'}**", "",
             "## 一、交付狀態", "",
             "| 軸 | 狀態 | 退出碼 | 說明 |",
             "|---|---|---|---|"]
    for r in enabled:
        mark = "✅ 通過" if r["ok"] else "❌ 未通過"
        lines.append(f"| {r['name']} | {mark} | {r['returncode']} | {r['note']} |")

    # 單價來源稽核（若有）
    _pa = master.get("_price_audit") or {}
    import re as _re
    _m = _re.search(r"查證覆蓋率\s*([0-9.]+)%[^0-9（]*（(\d+)／(\d+) 項取自營建物價，(\d+) 項為假設值）",
                    (_pa.get("log") or ""))
    if _m:
        lines += ["", "## 一之二、單價查證覆蓋率", "",
                  "- **%s%%**（%s／%s 項取自營建物價 11405，%s 項為假設值）"
                  % (_m.group(1), _m.group(2), _m.group(3), _m.group(4)),
                  "- 逐項稽核：`%s`" % os.path.basename(_pa.get("path", "")),
                  "- 假設值不必然錯，但它**沒有查證**；正式預算前應逐項詢價或補進 `tools\\boq\\prices\\`。"]

    lines += ["", "## 二、產出檔案", ""]
    for r in enabled:
        if not r["files"]:
            lines.append(f"- {r['name']}：（無檔案）")
            continue
        for f in r["files"]:
            rel = os.path.relpath(f["path"], out_dir) if f["path"].startswith(out_dir) else f["path"]
            lines.append(f"- {r['name']}：`{rel}`　{f['bytes']:,} B")

    lines += ["", "## 三、各軸執行記錄（失敗時看這裡）", ""]
    for r in enabled:
        lines += [f"### {r['name']}（exit {r['returncode']}）", "```",
                  r["log"] or "（無輸出）", "```", ""]

    lines += ["## 四、交件前人工必檢（工具做不到的）", "",
              "0. 報告書：**案名與主辦機關須先向使用者確認**（`case.json` 的 `project.full_name`／"
              "`project.agency`）。未確認時報告軸以 exit 4 中止、不產檔，這是刻意設計；"
              "`--allow-placeholder` 只供內部測試。",
              "1. 圖面：開 PDF 目視比例尺、指北針、標題欄填值、技師圖記區未被壓（E9 已機器檢，仍建議看一眼）",
              "2. 預算書：工項名稱錯字、數量對得回圖面、單價是否當期行情（`note` 欄標「假設值，須詢價」者必須換掉）",
              "3. 設計報告：所有標「需人工補」的章節（委託單位、業主、版次待核的法規）",
              "4. 三軸數字一致性：圖面數量（L／A／V）＝ 預算書數量 ＝ 報告數量表",
              "5. 業主／設計／繪圖／日期四欄由人工填寫並核章", ""]

    md = os.path.join(out_dir, f"{title}_案件交付清單.md")
    open(md, "w", encoding="utf-8").write("\n".join(lines))

    js = os.path.join(out_dir, f"{title}_交付狀態.json")
    json.dump({"title": title, "ok": ok_all, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
               "axes": [{k: r[k] for k in ("axis", "name", "ok", "returncode", "note")}
                        for r in enabled]},
              open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return md, js, ok_all


def main():
    ap = argparse.ArgumentParser(description="案件交付包：三軸一次跑完")
    ap.add_argument("master", help="案件主檔 JSON")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--only", default=None, help="只跑指定軸，逗號分隔：boq,report,drawing")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--allow-placeholder", action="store_true",
                    help="允許案名／主辦機關未確認就產報告書（內部測試用；交件前不得使用）")
    a = ap.parse_args()

    mp = a.master if os.path.isabs(a.master) else os.path.abspath(a.master)
    master = json.load(open(mp, encoding="utf-8"))
    master["_master_path"] = mp

    # ---- 統一案件檔（civil-case/1）：先檢查一致性，再派生兩軸輸入 ----
    if master.get("schema") == "civil-case/1":
        sys.path.insert(0, HERE)
        import case_core
        issues = case_core.consistency(master)
        errors = [i for i in issues if i["level"] == "error"]
        warns = [i for i in issues if i["level"] == "warn"]
        print(f"統一案件檔：{os.path.basename(mp)}　一致性 {len(errors)} error / {len(warns)} warn")
        for i in errors:
            print(f"  [ERROR] {i['msg']}")
        if errors:
            sys.exit("一致性檢查未通過，已中止（不產出任何交付物）")
        master["_case_path"] = mp
        master["boq"] = case_core.derive_boq(master)
        master["report"] = case_core.derive_report(master)
        proj = master.get("project") or {}
        master.setdefault("title", proj.get("name") or "未命名案件")
        if not master.get("drawing"):
            print("  （主檔無 drawing 段 → 設計圖軸跳過；"
                  "既有 A3 需先用 check_delivery 驗證後再補上）")

    if a.out_dir or master.get("out_dir"):
        out_dir = a.out_dir or master["out_dir"]
    else:
        # AGENTS.md 1.1：交付物一律 out\<案名>\（不再寫到 cases\<案名>\out）
        _cname = os.path.basename(os.path.dirname(os.path.abspath(mp))) or "未命名案件"
        out_dir = os.path.join(ROOT, "out", _cname)
    out_dir = out_dir if os.path.isabs(out_dir) else os.path.join(ROOT, out_dir)
    os.makedirs(out_dir, exist_ok=True)

    want = set((a.only or "boq,report,drawing,section").split(","))
    print(f"案件：{master.get('title', '')}")
    print(f"輸出：{out_dir}")

    results = []
    if "drawing" in want:
        results.append(run_drawing(master, out_dir))
    if "boq" in want:
        results.append(run_boq(master, out_dir, a.no_pdf))
    if "boq" in want:
        _stem = os.path.basename(os.path.dirname(os.path.abspath(mp)))
        _md = os.path.join(out_dir, _stem + "_單價來源稽核.md")
        _pcode, _plog = _run([PY, TOOLS["price_audit"], mp, "--out", _md],
                             os.path.join(out_dir, "_log_price_audit.txt"))
        master["_price_audit"] = {"ok": _pcode == 0, "path": _md, "log": _plog}

    if "section" in want:
        results.append(run_section(master, out_dir, a.no_pdf))
    if "report" in want:
        results.append(run_report(master, out_dir, a.no_pdf, a.allow_placeholder))

    for r in results:
        if r:
            print(f"  [{('OK ' if r['ok'] else 'FAIL')}] {r['name']}  exit={r['returncode']}  "
                  f"{len(r['files'])} 個檔案")

    md, js, ok = write_manifest(master, out_dir, results)
    print(f"\n交付清單：{md}")
    print(f"交付狀態：{js}")
    print("整體：" + ("全部通過 ✓" if ok else "有未通過項目 ✗"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
