r"""全案回歸測試：一次跑完所有案件，並與基準值比對。

為什麼要這個模組
----------------
工具改一次，就得手動跑全案全軸（每案含出圖、預算、報告、對帳），而且要人眼確認
預算總計、斷面積、FS、鋼筋量有沒有偷偷變動。這種「靠人記得去跑」的驗證，
遲早會漏 —— 而漏掉的那一次，通常正好是改壞的那一次。

本模組把回歸變成**一條指令**：

    python tools\selftest\regression.py            # 跑全部案件，比對基準
    python tools\selftest\regression.py --update   # 重寫基準（改了設計才用）

基準檔：`tools\selftest\baseline.json`
  · 每案的三大軸是否通過
  · 預算總計
  · 圖／數對帳的關鍵數值（斷面積、刨鋪面積）
  · 設計計算的關鍵數值（FS、鋼筋量）

任一項不符 → 退出碼 1，並列出「基準 → 現在」的差異。
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
PKG = os.path.join(ROOT, "tools", "case_package", "case_package.py")
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def _run(cmd, log_path=None):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if log_path:
        open(log_path, "w", encoding="utf-8").write(out)
    return p.returncode, out


def _num(pattern, text, cast=float):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


def collect(case_dir):
    """跑該案全軸，回傳要納入基準的關鍵數值。"""
    name = os.path.basename(case_dir)
    case_json = os.path.join(case_dir, "case.json")
    # case_package 的預設交付位置是 out\<案名>\（AGENTS.md §1.1）；
    # 舊的 cases\<案名>\out 可能是上一個版本留下的狀態檔，不能拿來判斷本次成敗。
    out_dir = os.path.join(ROOT, "out", name)
    os.makedirs(out_dir, exist_ok=True)
    log = os.path.join(out_dir, "_log_regression.txt")
    # 示範案件的主辦機關多為「（待填）」；報告軸的確認閘門（make_report exit 4）在回歸時放行，
    # 否則基準會因資料未補而整批失敗 —— 閘門本身另由 selftest 的負面測試驗。
    code, txt = _run(
        [PY, PKG, case_json, "--out-dir", out_dir, "--allow-placeholder"], log
    )

    rec = {"exit": code, "axes": {}, "numbers": {}}

    # 三大軸
    for line in txt.splitlines():
        m = re.match(r"\s*\[(OK|FAIL)\s*\]\s*(\S+)", line)
        if m:
            rec["axes"][m.group(2)] = (m.group(1) == "OK")
    # 以本次執行的退出碼與當次軸狀態為準；不可讀舊的交付狀態檔覆蓋，
    # 否則工具已 FAIL、舊檔仍寫 ok=true 時會產生假通過。
    rec["ok"] = code == 0 and (not rec["axes"] or all(rec["axes"].values()))

    # 預算總計（來源以交付清單最可靠：預算軸的 log 不一定有總計）
    _md = os.path.join(out_dir, name + "_案件交付清單.md")
    _src = open(_md, encoding="utf-8").read() if os.path.exists(_md) else txt
    import re as _re
    _m = _re.search(r"總計\s*([0-9][0-9,]*)", _src)
    if _m:
        rec["numbers"]["預算總計"] = int(_m.group(1).replace(",", ""))

    # 圖／數對帳
    for fn in ("_log_section_takeoff.txt", "_log_drawing_takeoff.txt"):
        fp = os.path.join(out_dir, fn)
        if os.path.exists(fp):
            t = open(fp, encoding="utf-8", errors="replace").read()
            v = _num(r"圖面混凝土淨面積\s*[^\d]*([0-9.]+)", t)
            if v:
                rec["numbers"]["斷面淨面積"] = round(v, 4)
            v = _num(r"刨鋪面積.*圖面\s*([0-9.]+)", t)
            if v:
                rec["numbers"]["刨鋪面積"] = round(v, 2)

    # 配筋圖核算
    fp = os.path.join(out_dir, "_log_section_rebar_takeoff.txt")
    if os.path.exists(fp):
        t = open(fp, encoding="utf-8", errors="replace").read()
        m = re.search(r"圖面量到 \[([0-9, ]+)\] mm", t)
        if m:
            rec["numbers"]["配筋間距_mm"] = m.group(1).strip()

    # 設計計算（直接呼叫模組，避免只有 log 可解析）
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "case_package"))
        sys.path.insert(0, os.path.join(ROOT, "tools", "design"))
        import case_core as CC
        case = CC.load(case_json)
        model, q, _ = CC.quantity_context(case)
        rec["model"] = model
        if model == "wall":
            # 走牆型分流唯一入口：重力／半重力／懸臂＋扶壁／錨定／加勁。
            # 先前只呼叫 retaining_wall，進階三型直接拋錯，回歸因此只記到
            # design_error，完全沒有追蹤它們的 FS 與鋼筋量。
            import wall_system as WS
            r = WS.analyse(q, case)
            # analyse() 的檢核值在 checks 裡（item→value），沒有 FS_sliding 這種扁平鍵。
            # 用 unit 判別：FS 才是安全係數，kPa 是承載應力（錨定式用容許承載力）。
            for ch in (r.get("checks") or []):
                it = ch.get("item", "")
                unit = ch.get("unit")
                if "常時" not in it:
                    continue
                if unit == "FS" and "滑動" in it:
                    rec["numbers"].setdefault("滑動FS", round(ch["value"], 3))
                elif unit == "FS" and "傾倒" in it:
                    rec["numbers"].setdefault("傾倒FS", round(ch["value"], 3))
                elif unit == "FS" and "承載" in it:
                    rec["numbers"].setdefault("承載FS", round(ch["value"], 3))
                elif unit == "kPa" and "承載" in it:
                    rec["numbers"].setdefault("承載應力_kPa", round(ch["value"], 2))
            rec["numbers"]["全部檢核通過"] = bool(r.get("pass"))
            # 鋼筋量（設計值）—— 曾漏收此項，導致 §7.4.3 修正讓鋼筋量 +28% 而回歸仍顯示「全部相符」
            try:
                import rc_design as RC
                # 必須走牆型分流的唯一入口；先前對重力式也套懸臂公式，
                # 基準因此記成 95.54 kg/m（虛構值），真正的設計值只有 43.86。
                _wd = WS.rebar_design(q, r)
                rec["numbers"]["鋼筋量_kg_per_m"] = round(_wd["total_kg_per_m"], 2)
                rec["numbers"]["鋼筋總量_kg"] = round(
                    _wd["total_kg_per_m"] * float(q.get("length_m") or 0), 0)
                if _wd["wall_type"] in ("gravity", "semigravity"):
                    rec["numbers"]["分布筋間距_mm"] = int(
                        _wd["mass"]["face_spacing_mm"])
                elif _wd["wall_type"] == "cantilever":
                    rec["numbers"]["分布筋間距_mm"] = int(
                        _wd["structural"]["stem"].get("dist_spacing_mm") or 0)
            except Exception as _ex:
                rec["numbers"]["鋼筋量_error"] = str(_ex)
        elif model == "box_culvert":
            import box_culvert as BC
            # 參數一律走 case_core 的唯一來源；回歸自己再組一套預設值，
            # 就會出現「預算用 H-20、回歸用 custom」這種看似全綠的假象。
            r = BC.analyse(q, **CC._box_culvert_kwargs(case, q))
            rec["numbers"]["箱涵結構檢核"] = bool(r.get("pass"))
            rec["numbers"]["混凝土量_m3"] = round(
                float(r["quantities"]["concrete_volume_m3"]), 3)
            rec["numbers"]["混凝土面積_m2_per_m"] = round(
                float(r["quantities"]["concrete_area_m2_per_m"]), 4)
            rec["numbers"]["滿管容量_m3s"] = round(
                float(r["hydraulic"]["capacity_m3s"]), 4)
            rec["numbers"]["正常水深_m"] = round(
                float(r["hydraulic"]["normal_depth_m"]), 4)
            # 追蹤「實際進預算的那個量」，不是舊的含鋼量假設值（rebar_kg）。
            rec["numbers"]["預算鋼筋量_kg"] = round(
                float(q.get("rebar_kg_design") or 0.0), 1)
            # 引擎實算的配筋量（與案件假設的 rebar_kg 分開追蹤）
            rec["numbers"]["配筋設計鋼筋量_kg_per_m"] = round(
                float(r["quantities"]["rebar_kg_per_m"]), 2)
            rec["numbers"]["配筋設計鋼筋總量_kg"] = round(
                float(r["quantities"]["rebar_kg_total"]), 1)
            rec["numbers"]["模板_m2"] = round(float(q.get("formwork_m2") or 0.0), 2)
        elif model == "slope":
            import slope_stability as SS
            r = SS.analyse(q)
            rec["numbers"]["無限邊坡FS"] = round(r["infinite"]["FS"], 3)
            rec["numbers"]["圓弧FS"] = round(r["circular"]["FS"], 3)
        elif model == "channel":
            import channel_hydraulics as CH
            hy = case.get("hydraulics") or {}
            r = CH.analyse(float(hy.get("design_flow_m3s") or 0.5),
                           float(q["inner_width_m"]), float(q["depth_m"]),
                           float(hy.get("slope") or 0.005),
                           {"manning_n": float(hy.get("manning_n") or 0.014)})
            rec["numbers"]["通水容量"] = round(r["Q_cap_m3s"], 4)
            try:
                import rc_design as RC
                _cw = RC.design_channel_wall(q, r)
                _kc = RC.rebar_kg_per_m_channel(q, _cw)
                rec["numbers"]["鋼筋量_kg_per_m"] = round(_kc["total_kg_per_m"], 2)
                rec["numbers"]["鋼筋總量_kg"] = round(
                    _kc["total_kg_per_m"] * float(q.get("length_m") or 0), 0)
                rec["numbers"]["分布筋間距_mm"] = int(_cw.get("dist_spacing_mm") or 0)
            except Exception as _ex:
                rec["numbers"]["鋼筋量_error"] = str(_ex)
        if q.get("section_area_m2") is not None:
            rec["numbers"]["模型斷面積"] = round(float(q["section_area_m2"]), 4)
    except Exception as ex:
        rec["design_error"] = str(ex)
    return rec


def collect_all():
    base = os.path.join(ROOT, "cases")
    out = {}
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d)
        if not os.path.isdir(p) or not os.path.exists(os.path.join(p, "case.json")):
            continue
        out[d] = collect(p)
        print("  跑完 %-18s %s" % (d, "✓" if out[d]["ok"] else "✗"))
    return out


def compare(base, now, ignore_new=False):
    """回傳差異清單。"""
    diffs = []
    for name, b in base.items():
        n = now.get(name)
        if n is None:
            diffs.append("%s：案件已不存在" % name)
            continue
        if b.get("ok") != n.get("ok"):
            diffs.append("%s：整體 %s → %s" % (
                name, "通過" if b.get("ok") else "未通過",
                "通過" if n.get("ok") else "未通過"))
        for k, bv in (b.get("numbers") or {}).items():
            nv = (n.get("numbers") or {}).get(k)
            if nv is None:
                diffs.append("%s／%s：基準 %s → 現在（無值）" % (name, k, bv))
                continue
            if isinstance(bv, (int, float)) and isinstance(nv, (int, float)):
                if abs(bv - nv) > max(abs(bv) * 1e-6, 1e-6):
                    diffs.append("%s／%s：%s → %s" % (name, k, bv, nv))
            elif str(bv) != str(nv):
                diffs.append("%s／%s：%s → %s" % (name, k, bv, nv))
    for name in now:
        if name not in base:
            msg = "%s：新增案件（基準沒有，跑 --update 收錄）" % name
            if ignore_new:
                print("  ! 提示：" + msg + "（--ignore-new，不計入失敗）")
            else:
                diffs.append(msg)
            continue
        # 新增的追蹤項目：compare 只走 base 的鍵，若不提醒，「新加的檢查」會永遠不生效
        # （實例：加了鋼筋量追蹤，但基準沒有這個鍵 → 鋼筋量 +28% 仍顯示「全部相符」）
        for k in (now[name].get("numbers") or {}):
            if k not in (base[name].get("numbers") or {}):
                diffs.append("%s／%s：新增追蹤項目（基準沒有，跑 --update 收錄）" % (name, k))
    return diffs


def main():
    update = "--update" in sys.argv
    ignore_new = "--ignore-new" in sys.argv
    print("全案回歸：")
    now = collect_all()
    base = json.load(open(BASELINE, encoding="utf-8")) if os.path.exists(BASELINE) else {}
    _base_ids = set(base)
    # --ignore-new：別的行程剛新增、尚未納入基準的案件，不計入失敗（其自身三軸狀態仍會印✗）
    # 基準已記錄為「未通過」的案件（例如案件資料本身缺工項）不算回歸；否則整條回歸
    # 永遠紅燈，新發生的失敗就會被這顆固定的紅燈蓋掉。新變紅的案子仍會列入 failed。
    known_bad = {k for k, v in base.items() if not v.get("ok")}
    failed = [k for k, v in now.items()
              if not v["ok"] and k not in known_bad
              and not (ignore_new and k not in _base_ids)]

    if update or not os.path.exists(BASELINE):
        json.dump(now, open(BASELINE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n已寫入基準 %s（%d 案）" % (BASELINE, len(now)))
        if not update:
            print("（首次執行自動建立基準；之後再跑就會比對）")
        return 0 if not failed else 1

    diffs = compare(base, now, ignore_new)
    print()
    if not diffs:
        print("✓ 基準全部相符（%d 案）" % len(now))
        still_bad = sorted(k for k, v in now.items() if not v["ok"])
        if still_bad:
            print("既有未通過（不計入本次失敗，需補案件資料）：%s" % "、".join(still_bad))
        return 0 if not failed else 1
    print("✗ 與基準不符 %d 項：" % len(diffs))
    for d in diffs:
        print("   ·", d)
    if failed:
        print("\n本次新增未通過：%s" % "、".join(failed))
    still_bad = sorted(k for k, v in now.items() if not v["ok"] and k in known_bad)
    if still_bad:
        print("既有未通過（基準已記錄，需補案件資料）：%s" % "、".join(still_bad))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
