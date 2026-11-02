"""清理專案內臨時檔／暫存檔／無用檔（2026-11-02 使用者指示）。

原則：
1. `_temp/` 依 AGENTS.md §1.1 定義為「可無條件整批刪除」→ 整批清掉（工作台工具已移到 tools/regs/）。
2. 根目錄散落的一次性腳本、測試輸出、日誌 → 刪除。
3. `_cad_assess/`、`_boq_assess/`（能力評估測試產物）→ 刪除。
4. **不動**：完整案例(參考用)/、cases/、data/、標準圖圖庫/、_ref/components_dxf/、out/、tools.excel/、SolidCraft範例/、A3圖框.dwt。
5. 每項都印出大小，最後印回收空間。

用法：python _temp/clean_project.py --dry-run   # 先看會刪什麼
      python _temp/clean_project.py --apply     # 實際刪除
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- 要刪的目錄（相對路徑）----
DIRS = [
    "_temp",            # 整批暫存（AGENTS.md §1.1）
    "_cad_assess",      # CAD 能力評估測試產物
    "_boq_assess",      # 預算能力評估測試產物
]

# ---- 要刪的檔案樣式（根目錄）----
FILE_GLOBS = [
    "_temp*.py", "_tmp*.py",           # 散落的一次性腳本
    "temp.txt",
    "*.log",                            # plot.log、_regs_server_*.log
    "_regs_server_*.log",
    "描圖測試*",                         # 底圖測試輸出
    "osm_daya_v2.dxf",
    "TOMO_style_test.*",                # 字型樣式測試輸出
    "test_*.dxf", "test_*.png",
]

KEEP_NOTE = """
保留（不刪）：
  完整案例(參考用)/   使用者參考案例
  cases/              案件主檔
  data/               法規與圖資（現已入版控）
  標準圖圖庫/         166 張公司標準圖
  _ref/components_dxf/ 已轉好的 DXF（入版控）
  out/                交付物唯一落點
  tools.excel/        使用者既有 Excel 設計表
  SolidCraft範例/     範例
  A3圖框.dwt          出圖樣板（make_sheet 需要）
"""


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for q in p.rglob("*"):
        if q.is_file():
            try:
                total += q.stat().st_size
            except OSError:
                pass
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="清理專案內臨時檔／暫存檔／無用檔")
    ap.add_argument("--apply", action="store_true", help="實際刪除（預設只列出）")
    ap.add_argument("--dry-run", action="store_true", help="只列出（預設行為）")
    a = ap.parse_args(argv)
    do = a.apply and not a.dry_run

    targets: list[Path] = []
    for d in DIRS:
        p = ROOT / d
        if p.exists():
            targets.append(p)
    for g in FILE_GLOBS:
        targets += [p for p in sorted(ROOT.glob(g)) if p.is_file()]

    # 去重
    seen, uniq = set(), []
    for p in targets:
        if str(p) in seen:
            continue
        seen.add(str(p))
        uniq.append(p)

    total = sum(size_of(p) for p in uniq)
    print(f"{'實際刪除' if do else '（試跑）'} 共 {len(uniq)} 項，合計 {total / 1048576:.0f} MB\n")
    for p in sorted(uniq, key=lambda x: -size_of(x)):
        print(f"  {size_of(p) / 1048576:9.1f} MB  {p.relative_to(ROOT)}")

    if not do:
        print(KEEP_NOTE)
        print("加 --apply 才會真的刪除。")
        return 0

    freed = 0
    for p in uniq:
        sz = size_of(p)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            freed += sz
        except Exception as e:
            print(f"  刪除失敗 {p}: {e}", file=sys.stderr)
    print(f"\n已刪除 {len(uniq)} 項，回收 {freed / 1048576:.0f} MB")
    print(KEEP_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
