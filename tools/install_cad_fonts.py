"""把 TOMO 樣式用的 SHX 字型安裝到 AutoCAD 的字型搜尋路徑。

為什麼需要這個：DXF 內只記字型**檔名**（`font="gbenor.shx"`、`bigfont="CHINESE.SHX"`），
AutoCAD 開圖時是到自己的字型目錄去找檔案。專案裡的 `CAD_FONTS/` 只是「隨附一份、
免依賴 AutoCAD 安裝」，要讓 AutoCAD 真的找得到，仍得複製過去。

用法::

    python tools/install_cad_fonts.py            # 列出將安裝到哪，先不動
    python tools/install_cad_fonts.py --apply    # 實際複製
    python tools/install_cad_fonts.py --apply --target "D:\\某字型目錄"

AutoCAD 的字型搜尋路徑（依安裝版本而異，常見者）：
  C:\\Program Files\\Autodesk\\AutoCAD <版本>\\Fonts
  %APPDATA%\\Autodesk\\AutoCAD <版本>\\... （部分設定）
若都找不到，本工具會提示用 `--target` 指定，或手動複製。

已存在同名檔案時不覆蓋（除非加 --force），避免蓋掉使用者自己的版本。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_paths import cad_font, cad_fonts_dir  # noqa: E402

FONTS = ["gbenor.shx", "CHINESE.SHX"]


def candidate_dirs() -> list[Path]:
    """AutoCAD 常見字型目錄（存在且含既有字型者優先）。"""
    cands: list[Path] = []
    for root in (Path(r"C:\Program Files\Autodesk"), Path(r"C:\Program Files (x86)\Autodesk")):
        if root.is_dir():
            for d in sorted(root.rglob("Fonts")):
                if d.is_dir():
                    cands.append(d)
    appdata = Path.home() / "AppData" / "Roaming" / "Autodesk"
    if appdata.is_dir():
        for d in sorted(appdata.rglob("Fonts")):
            if d.is_dir():
                cands.append(d)
    return cands


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把 TOMO 用 SHX 字型安裝到 AutoCAD 字型目錄")
    ap.add_argument("--apply", action="store_true", help="實際複製（預設只列出）")
    ap.add_argument("--target", help="指定目標目錄（覆蓋自動偵測）")
    ap.add_argument("--force", action="store_true", help="覆蓋同名既有檔案")
    a = ap.parse_args(argv)

    src_dir = cad_fonts_dir()
    if not src_dir:
        print("找不到字型來源。請確認專案根目錄下的 CAD_FONTS/ 存在，"
              "或設定環境變數 CAD_FONTS 指向字型資料夾。")
        return 1
    print(f"字型來源：{src_dir}")
    missing = [n for n in FONTS if not (src_dir / n).is_file()]
    if missing:
        print(f"來源缺檔：{missing}")
        return 1

    if a.target:
        targets = [Path(a.target)]
    else:
        targets = candidate_dirs()
        if not targets:
            print("\n找不到 AutoCAD 字型目錄。請手動指定：")
            print('  python tools/install_cad_fonts.py --apply --target "<某字型目錄>"')
            return 1
        print(f"\n偵測到 {len(targets)} 個候選字型目錄：")
        for t in targets[:8]:
            print(f"  {t}")
        if len(targets) > 8:
            print(f"  …另有 {len(targets) - 8} 個")

    tgt = targets[0]
    print(f"\n目標目錄：{tgt}")
    for n in FONTS:
        s = src_dir / n
        d = tgt / n
        if d.exists() and not a.force:
            same = d.read_bytes() == s.read_bytes()
            print(f"  {n:<14} 已存在（{'內容相同' if same else '內容不同，保留原檔'}）→ 略過"
                  + ("（要覆蓋請加 --force）" if not same else ""))
        else:
            print(f"  {n:<14} {'將覆蓋' if d.exists() else '將複製'}  {s.stat().st_size:,} bytes")

    if not a.apply:
        print("\n（預演）加 --apply 才會真的複製。")
        return 0

    tgt.mkdir(parents=True, exist_ok=True)
    done = 0
    denied = False
    for n in FONTS:
        s, d = src_dir / n, tgt / n
        if d.exists() and not a.force:
            continue
        try:
            shutil.copy2(s, d)
            print(f"  已複製 {n}")
            done += 1
        except PermissionError:
            denied = True
            print(f"  權限不足：{n}（{tgt} 受系統保護，需以系統管理員身分執行）")
        except Exception as e:
            print(f"  複製失敗 {n}: {e}")

    if denied:
        print("\n" + "─" * 60)
        print("目標在 Program Files 下，需要系統管理員權限。兩種做法：")
        print("  1) 以系統管理員身分重跑本指令")
        print('     python tools/install_cad_fonts.py --apply')
        print("  2) 手動複製（當滑鼠右鍵 → 以系統管理員身分執行 cmd）：")
        for n in FONTS:
            print(f'     copy /Y "{src_dir / n}" "{tgt / n}"')
        print("  3) 不安裝也可：AutoCAD → OPTIONS → 檔案 → 字型檔名，")
        print("     把本專案的 CAD_FONTS 資料夾加入字型搜尋路徑即可。")
    print(f"\n完成：{done} 個字型 → {tgt}")
    if done:
        print("若 AutoCAD 已開啟，需重啟才會重新載入字型。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
