import sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "tools" / "acad"))
import acc
import pathlib as _p
_H = _p.Path(__file__).resolve().parent
src = str(_H / "case.dwg")
dst = str(_H / "case.dxf")
acc.to_dxf(src, dst)
print("OK", os.path.getsize(dst))
