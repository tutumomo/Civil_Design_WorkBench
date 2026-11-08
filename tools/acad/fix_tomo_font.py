"""把 DXF／DWG 的 TOMO 文字樣式統一改為 gbenor.shx + bigfont=CHINESE.SHX（繁體中文相容）。

用法::

    python tools/acad/fix_tomo_font.py <檔案.dxf|.dwg>            # 預演
    python tools/acad/fix_tomo_font.py <檔案> --apply             # 就地改（先備份 .bak）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_paths import artcraft_cli

TARGET_FONT = "gbenor.shx"
TARGET_BIGFONT = "CHINESE.SHX"
TARGET_STYLES = ("TOMO",)


def _to_dxf(src: Path, dst: Path) -> Path:
    cc = artcraft_cli("CADCraft")
    if not cc:
        raise SystemExit("找不到 cadcraft-cli，無法轉 DWG→DXF")
    p = subprocess.run([cc, "convert", str(src), str(dst)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not dst.exists():
        raise SystemExit("cadcraft convert（DWG→DXF）失敗：\n" + (p.stderr or "")[-800:])
    return dst


def _to_dwg(src: Path, dst: Path) -> Path:
    cc = artcraft_cli("CADCraft")
    if not cc:
        raise SystemExit("找不到 cadcraft-cli，無法轉 DXF→DWG")
    p = subprocess.run([cc, "convert", str(src), str(dst)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not dst.exists():
        raise SystemExit("cadcraft convert（DXF→DWG）失敗：\n" + (p.stderr or "")[-800:])
    return dst


def patch_dxf(dxf: Path, apply: bool) -> dict:
    import ezdxf
    doc = ezdxf.readfile(str(dxf))
    changed = []
    for st in doc.styles:
        name = st.dxf.name
        if name not in TARGET_STYLES:
            continue
        old_font = st.dxf.get("font", "")
        old_big = st.dxf.get("bigfont", "")
        changed.append({"style": name, "old_font": old_font, "old_bigfont": old_big,
                        "new_font": TARGET_FONT, "new_bigfont": TARGET_BIGFONT})
        if apply:
            st.dxf.font = TARGET_FONT
            st.dxf.bigfont = TARGET_BIGFONT
    if apply and changed:
        doc.saveas(str(dxf))
    return {"file": str(dxf), "styles": changed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="把 TOMO 文字樣式由 CHINA1.SHX 改成 CHINESE.SHX")
    ap.add_argument("path", help="要處理的 .dxf 或 .dwg")
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設只預演）")
    a = ap.parse_args(argv)

    src = Path(a.path).expanduser().resolve()
    if not src.is_file():
        print(f"找不到檔案：{src}")
        return 1

    is_dwg = src.suffix.lower() == ".dwg"
    work = src.parent
    tmp_dxf = work / (src.stem + ".__totofont.dxf")

    try:
        if is_dwg:
            print(f"[1/3] DWG → DXF  {src.name}")
            _to_dxf(src, tmp_dxf)
            target_dxf = tmp_dxf
        else:
            target_dxf = src

        print(f"[2/3] 檢查 TOMO 樣式  {target_dxf.name}")
        rep = patch_dxf(target_dxf, apply=a.apply)
        if not rep["styles"]:
            print(f"  找不到樣式 {'／'.join(TARGET_STYLES)}，未變更")
            return 0
        for s in rep["styles"]:
            print(f"  {s['style']}: {s['old_font']} + bigfont={s['old_bigfont']}")
            print(f"    → {s['new_font']} + bigfont={s['new_bigfont']}")

        if is_dwg:
            if not a.apply:
                print("\n（預演）要真的寫回 DWG 請加 --apply")
                return 0
            bak = src.with_suffix(src.suffix + ".bak")
            shutil.copy2(src, bak)
            print(f"[3/3] DXF → DWG  備份原檔 → {bak.name}")
            _to_dwg(tmp_dxf, src)
            print(f"  已寫回 {src}")
        else:
            if a.apply:
                bak = src.with_suffix(src.suffix + ".bak")
                shutil.copy2(src, bak)
                print(f"  已備份 → {bak.name}")
            else:
                print("\n（預演）要真的寫入請加 --apply")
    finally:
        if tmp_dxf.exists() and tmp_dxf != src:
            try:
                tmp_dxf.unlink()
            except Exception:
                pass

    if a.apply:
        print("\n完成。已將 TOMO 樣式更新為 gbenor.shx + CHINESE.SHX。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
