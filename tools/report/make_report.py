# -*- coding: utf-8 -*-
"""設計報告產線主程式：案件 JSON → .docx ＋ .pdf。

用法（在 D:\\公司案件.AI 下執行；**執行前必設 PYTHONIOENCODING=utf-8**）：

    set PYTHONIOENCODING=utf-8
    C:\\Python312\\python.exe tools\\report\\make_report.py ^
        --case tools\\report\\examples\\AC刨鋪5cm工程.json ^
        --out-dir _report_test

產出
----
* `<工程名稱>_設計報告.docx`  目錄與頁碼已展開（由 wordcraft-cli --update-fields 烘焙）
* `<工程名稱>_設計報告.pdf`   A4 版面，中文字型已嵌入
* `<工程名稱>_設計報告_產製報告.json`  表號圖號數、章節狀態、待補清單、指令與耗時

退出碼：0 成功｜1 產製或轉檔失敗｜2 案件資料不足｜3 找不到轉檔工具
        4 案名／主辦機關未確認（依使用者規範，輸出前必須先確認；`--allow-placeholder` 可略過）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_paths import artcraft_cli  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chapters import render_appendices, render_chapters  # noqa: E402
from docx_build import DocxReport  # noqa: E402
from report_model import ReportDataError, ReportModel, is_unconfirmed  # noqa: E402

DEFAULT_WORDCRAFT = artcraft_cli("WordCraft") or ""
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

def project_info_missing(project: dict) -> list[tuple[str, str]]:
    """檢查封面兩個必填欄位：案名（full_name）、主辦機關（agency）。

    使用者規範（專案記憶 `project_report_word_requirements`）：報告書輸出前必須先向
    使用者確認案名與主辦機關，所以這兩個欄位不得是空白或「待填」。
    """
    missing = []
    for key, label in (("full_name", "案名"), ("agency", "主辦機關")):
        val = str(project.get(key) or "").strip()
        if is_unconfirmed(val):
            missing.append((label, val or "（空白）"))
    return missing


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def log(msg: str):
    print(msg, flush=True)


def run_cli(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    """執行外部 CLI；一律用 Python subprocess + UTF-8 抓輸出（見 SolidCraft 踩坑 #9）。"""
    log("  $ " + " ".join(str(c) for c in cmd))
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, f"找不到執行檔：{exc}"
    except subprocess.TimeoutExpired:
        return 124, f"逾時（>{timeout}s）"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        for line in out.splitlines():
            log("    " + line)
    return proc.returncode, out


def find_wordcraft(explicit: str | None) -> Path | None:
    for cand in (explicit, os.environ.get("WORDCRAFT_CLI"), DEFAULT_WORDCRAFT):
        if not cand:
            continue
        p = Path(cand)
        if p.exists():
            return p
    which = shutil.which("wordcraft-cli")
    return Path(which) if which else None


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n:,} B"
    for unit, div in (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < div * 1024:
            return f"{n / div:,.1f} {unit}"
    return f"{n / 1024 ** 3:,.1f} GB"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(args) -> int:
    t0 = time.perf_counter()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log("[1/5] 載入案件資料與範本 …")
    try:
        model = ReportModel.load(args.case, args.template_dir)
    except ReportDataError as exc:
        log(f"  ✗ 案件資料不足：{exc}")
        return 2
    except json.JSONDecodeError as exc:
        log(f"  ✗ 案件 JSON 格式錯誤：{exc}")
        return 2

    project = model.project
    log(f"  工程名稱：{project['full_name']}")
    log(f"  主辦機關：{project.get('agency') or '（未填）'}")
    log(f"  設計單位：{(model.style.get('cover') or {}).get('design_unit') or project.get('designer') or '（未填）'}")
    log(f"  案件類別：{project.get('category') or '（未宣告）'}")
    log(f"  範本目錄：{model.template_dir}")

    # ---- 確認閘門：案名／主辦機關（使用者規範，見專案記憶）----
    missing = project_info_missing(project)
    if missing and not args.allow_placeholder:
        log("")
        log("  ✗ 報告書輸出前必須先向使用者確認案名與主辦機關（公司規範）：")
        for label, val in missing:
            log(f"      · {label}：{val}")
        log("    請填入案件 JSON 的 project.full_name／project.agency 後重跑；")
        log("    若只是內部測試、確定不交件，可加 --allow-placeholder（封面會顯示黃字佔位符）。")
        return 4
    info_warnings: list[str] = []
    if missing:
        info_warnings.append("案名／主辦機關尚未確認（--allow-placeholder）："
                             + "、".join(label for label, _ in missing)
                             + "；此檔不得直接交件。")

    log("[2/5] 排版 Word（python-docx）…")
    builder = DocxReport(model)
    builder.setup()
    builder.cover()
    builder.toc()
    render_chapters(builder, model)
    render_appendices(builder, model, extra_meta={
        "案件資料路徑": str(model.case_path),
        "輸出目錄": str(out_dir),
    })

    stem = model.output_stem()
    raw_path = out_dir / f"{stem}_raw.docx"
    docx_path = out_dir / f"{stem}.docx"
    pdf_path = out_dir / f"{stem}.pdf"
    builder.save(raw_path)
    log(f"  ✓ 初稿：{raw_path.name}（{human_size(raw_path.stat().st_size)}）")

    wordcraft = None if args.no_wrapper else find_wordcraft(args.wordcraft)
    steps: list[dict] = []
    warnings: list[str] = list(info_warnings)

    if wordcraft:
        log("[3/5] 展開目錄與頁碼（wordcraft-cli convert --update-fields）…")
        code, out = run_cli([wordcraft, "convert", raw_path, docx_path, "--update-fields"])
        steps.append({"step": "docx_update_fields", "cmd": f'{wordcraft} convert "{raw_path}" "{docx_path}" --update-fields',
                      "exit_code": code, "output": out[-500:]})
        toc_baked = code == 0 and docx_path.exists()
        if not toc_baked:
            warnings.append(f"目錄展開失敗（exit {code}），改以初稿交付；目錄需在 Word 內按 F9 更新。")
            shutil.copyfile(raw_path, docx_path)
    else:
        warnings.append("找不到 wordcraft-cli，直接交付初稿 .docx（目錄需按 F9 更新）且不產 PDF。")
        shutil.copyfile(raw_path, docx_path)
        toc_baked = False

    pdf_ok = False
    if not args.no_pdf and wordcraft:
        log("[4/5] 轉 PDF（wordcraft-cli convert）…")
        code, out = run_cli([wordcraft, "convert", docx_path, pdf_path, "--update-fields"])
        steps.append({"step": "pdf", "cmd": f'{wordcraft} convert "{docx_path}" "{pdf_path}" --update-fields',
                      "exit_code": code, "output": out[-500:]})
        pdf_ok = code == 0 and pdf_path.exists() and pdf_path.stat().st_size > 0
        if not pdf_ok:
            warnings.append(f"PDF 轉檔失敗（exit {code}）。")
    elif args.no_pdf:
        warnings.append("指定 --no-pdf，未產出 PDF。")

    if not args.keep_raw:
        try:
            raw_path.unlink()
        except OSError:
            pass

    log("[5/5] 產製報告 …")
    elapsed = round(time.perf_counter() - t0, 2)
    report = {
        "case": str(model.case_path),
        "template_dir": str(model.template_dir),
        "outputs": {
            "docx": {"path": str(docx_path), "exists": docx_path.exists(),
                     "bytes": docx_path.stat().st_size if docx_path.exists() else 0,
                     "toc_baked": bool(toc_baked)},
            "pdf": {"path": str(pdf_path), "exists": pdf_ok,
                    "bytes": pdf_path.stat().st_size if pdf_ok else 0},
        },
        "stats": builder.stats(),
        "project": {k: v for k, v in project.items() if k != "raw"},
        "project_info": {"missing": [label for label, _ in missing],
                         "confirmed": not missing},
        "chapter_status": [s.as_dict() for s in builder.chapter_status],
        "placeholders": [p.as_dict() for p in builder.placeholders],
        "consistency": [c.as_dict() for c in model.consistency],
        "steps": steps,
        "warnings": warnings,
        "elapsed_sec": elapsed,
        "python": sys.version.split()[0],
    }
    report_path = out_dir / f"{stem}_產製報告.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    # ---- 主控台摘要 ----
    log("")
    log("=" * 72)
    log("產製完成")
    log("=" * 72)
    log(f"  DOCX：{docx_path}  ({human_size(report['outputs']['docx']['bytes']) if docx_path.exists() else '—'})")
    log(f"  PDF ：{pdf_path}  ({human_size(report['outputs']['pdf']['bytes']) if pdf_ok else '（未產出）'})")
    log(f"  產製報告：{report_path}")
    log(f"  表 {builder.table_no} 張／圖 {builder.figure_no} 張／耗時 {elapsed}s")
    log("")
    labels = model.style["placeholder"]["status_labels"]
    log("  章節資料狀態：")
    for st in builder.chapter_status:
        log(f"    {'封面' if st.no == 0 else f'第 {st.no} 章':>7}  {st.title:<14}  "
            f"{labels.get(st.status, st.status)}（自動 {st.auto_sections}／待補 {st.placeholders}）")
    if builder.placeholders:
        log("")
        log(f"  需人工補項目 {len(builder.placeholders)} 項：")
        for i, p in enumerate(builder.placeholders, 1):
            where = "封面" if p.chapter_no == 0 else f"第 {p.chapter_no} 章"
            log(f"    {i:>2}. [{where}] {p.label}")
    if warnings:
        log("")
        for w in warnings:
            log(f"  ⚠ {w}")
    log("")
    log(f"  下一步：C:\\Python312\\python.exe tools\\report\\verify_report.py \"{docx_path}\""
        + (f" --pdf \"{pdf_path}\"" if pdf_ok else ""))

    if args.fail_on_placeholder and builder.placeholders:
        log("  ✗ 指定 --fail-on-placeholder，仍有待補項目 → 退出碼 1")
        return 1
    if not docx_path.exists():
        return 1
    if not args.no_pdf and not pdf_ok:
        return 1
    if not wordcraft:
        return 3
    return 0


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="設計報告產線：案件 JSON → .docx ＋ .pdf（A4、14 章、表號圖號自動編）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="範例：\n"
               "  C:\\Python312\\python.exe tools\\report\\make_report.py "
               "--case tools\\report\\examples\\AC刨鋪5cm工程.json --out-dir _report_test\n",
    )
    ap.add_argument("--case", required=True, help="案件資料 JSON 路徑")
    ap.add_argument("--out-dir", default="_report_test", help="輸出目錄（預設 _report_test）")
    ap.add_argument("--template-dir", default=None, help="範本目錄（預設 templates/report）")
    ap.add_argument("--wordcraft", default=None, help="wordcraft-cli 路徑（預設自動偵測）")
    ap.add_argument("--no-pdf", action="store_true", help="只產 .docx，不轉 PDF")
    ap.add_argument("--no-wrapper", action="store_true", help="不做目錄展開、不呼叫外部轉檔（只用 python-docx 初稿）")
    ap.add_argument("--keep-raw", action="store_true", help="保留未展開目錄的初稿 _raw.docx")
    ap.add_argument("--fail-on-placeholder", action="store_true",
                    help="仍有『需人工補』項目時以退出碼 1 結束（CI／交件門檻用）")
    ap.add_argument("--allow-placeholder", action="store_true",
                    help="允許案名／主辦機關未確認（內部測試用；交件前不得使用）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("PYTHONIOENCODING", "").lower() not in ("utf-8", "utf8"):
        log("  ⚠ 建議先 set PYTHONIOENCODING=utf-8（AGENTS.md §3），否則中文輸出可能亂碼。")
    args = parse_args(argv)
    try:
        return build(args)
    except KeyboardInterrupt:
        log("  ✗ 使用者中止")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
