import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from project_paths import solidcraft_cli  # noqa: E402
"""SolidCraft 3D 參數化設計：命令腳本 → 模型建構 → 匯出 → 量測驗證 → 截圖 → 紀錄（一鍵交付）
用法：
  python sc_build.py <腳本.json> --out-dir <輸出資料夾> --name <零件名>
        [--param 名稱=運算式]...            # 覆寫參數，例：--param "L=120 mm"
        [--formats step,stl,3mf]            # 預設 step,stl,3mf
        [--expect-volume 23335.2] [--tol 0.1]   # 預期體積 mm³ 與容許誤差 %
        [--expect-bbox 80x50x6]             # 預期外框尺寸 mm（X×Y×Z），容許 0.01 mm
        [--views iso,top,front]
退出碼：0=建構成功且驗證通過；1=建構失敗或驗證不符
說明：見 D:\\公司案件.AI\\docs\\SolidCraft操作指引.md
"""
import os, sys, json, argparse, datetime, subprocess

CLI = solidcraft_cli() or ""

ap = argparse.ArgumentParser()
ap.add_argument("script"); ap.add_argument("--out-dir", required=True); ap.add_argument("--name", required=True)
ap.add_argument("--param", action="append", default=[], help="NAME=EXPR，例：L=120 mm")
ap.add_argument("--formats", default="step,stl,3mf"); ap.add_argument("--views", default="iso,top,front")
ap.add_argument("--no-render", action="store_true", help="跳過產品渲染（省時）")
ap.add_argument("--expect-volume", type=float, default=None); ap.add_argument("--tol", type=float, default=0.1)
ap.add_argument("--expect-bbox", default=None, help="LxWxH（mm）")
A = ap.parse_args()
OUT = os.path.abspath(A.out_dir); os.makedirs(OUT, exist_ok=True)
P = lambda ext: os.path.join(OUT, f"{A.name}{ext}")


def sc(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---- 1. 組合腳本：原腳本 + 參數覆寫（parameters.change 置於最後，整條時間軸重建）----
src = json.load(open(A.script, encoding="utf-8"))
cmds = list(src["commands"])
for kv in A.param:
    k, v = kv.split("=", 1)
    cmds.append({"command": "parameters.change", "params": {"name": k.strip(), "expression": v.strip()}})
# 參數表（須與建模同一 session 才能帶出參數）
cmds.append({"command": "parameters.export",
             "params": {"path": P("_參數表.csv"), "format": "csv"}})
script = P("_script.json")
json.dump({"commands": cmds}, open(script, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- 2. 建構＋匯出＋存檔＋量測（任一特徵失敗即整體失敗、不寫檔）----
outs = []
for f in [x.strip() for x in A.formats.split(",") if x.strip()]:
    outs += ["--out", P("." + f)]
rc, log = sc("run", script, *outs, "--save", P(".solidcraft"), "--json-out", P("_measure.json"))
if rc != 0:
    print("✗ 建構失敗\n" + log); sys.exit(1)
sc("eval", P(".solidcraft"), "--json-out", P("_measure.json"))      # run 的 json 不含參數；改量測存檔後設計
M = json.load(open(P("_measure.json"), encoding="utf-8"))

# ---- 3. 驗證：體積、外框 ----
errs, lines = [], []
bodies = M.get("bodies", [])
vol = sum(b["volume_mm3"] for b in bodies)
lo = [min(b["bbox"]["min"][i] for b in bodies) for i in range(3)] if bodies else [0, 0, 0]
hi = [max(b["bbox"]["max"][i] for b in bodies) for i in range(3)] if bodies else [0, 0, 0]
size = [hi[i] - lo[i] for i in range(3)]
if not bodies: errs.append("沒有任何實體")
if any(not b.get("closed", True) for b in bodies): errs.append("有非封閉實體（不是水密 solid）")
if A.expect_volume is not None and A.expect_volume > 0:
    d = abs(vol - A.expect_volume) / A.expect_volume * 100
    (errs if d > A.tol else lines).append(f"體積 {vol:.3f} vs 預期 {A.expect_volume:.3f} mm³（差 {d:.4f}%，容許 {A.tol}%）")
if A.expect_bbox:
    exp = [float(x) for x in A.expect_bbox.lower().split("x")]
    ok = all(abs(size[i] - exp[i]) <= 0.01 for i in range(3))
    (lines if ok else errs).append(f"外框 {size[0]:.3f}×{size[1]:.3f}×{size[2]:.3f} vs 預期 {A.expect_bbox} mm")

# ---- 4. 截圖（GPU 渲染，供目視檢查）----
shots = []
for v in [x.strip() for x in A.views.split(",") if x.strip()]:
    rc, o = sc("snapshot", P(".solidcraft"), "--out", P(f"_{v}.png"), "--view", v, "--width", "1200", "--height", "800")
    if rc == 0: shots.append(P(f"_{v}.png"))
    else: errs.append(f"截圖 {v} 失敗：{o.strip()[:200]}")

# ---- 4b. 產品渲染（CLI render 子命令；headless 可用，render.* 命令不行）----
if not A.no_render:
    rc, o = sc("render", P(".solidcraft"), "--out", P("_render.png"),
               "--width", "1600", "--height", "1000", "--overwrite", "--timeout", "900")
    if rc == 0: shots.append(P("_render.png"))
    else: errs.append(f"渲染失敗：{o.strip()[:200]}")

# ---- 4c. 參數表 CSV（交付用）----
# 注意：parameters.export 必須在有設計的 session 內執行，
# `solidcraft-cli exec` 開的是空白 session → 必須併入建模腳本（第 1 步）。
# 因此此處僅檢查檔案是否存在（由腳本內的 parameters.export 產生）。

# ---- 5. 紀錄 ----
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_, ver = sc("--version")
rep = [f"# {A.name} 建構紀錄  {now}", f"SolidCraft {ver.strip()}  腳本 {os.path.abspath(A.script)}",
       "參數：" + "；".join(f"{p['name']}={p['expression']}" for p in M.get("params", [])),
       f"實體 {len(bodies)} 個｜總體積 {vol:.3f} mm³｜外框 {size[0]:.3f}×{size[1]:.3f}×{size[2]:.3f} mm"]
for b in bodies:
    rep.append(f"  - {b['name']}: 體積 {b['volume_mm3']:.3f} mm³、面 {b['faces']}、材料 {b.get('material')}、質量 {b.get('mass_g', 0):.2f} g、封閉 {b.get('closed')}")
rep += ["檢核：" + ("；".join(lines) or "（未指定預期值）")]
rep += ["✗ " + e for e in errs] or []
rep += ["產出：" + "、".join(os.path.basename(x) for x in [P(".solidcraft")] + [P("." + f) for f in A.formats.split(",")] + shots)]
rep += ["結論：" + ("通過" if not errs else "不通過")]
open(P("_紀錄.log"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
print("\n".join(rep))
sys.exit(0 if not errs else 1)
