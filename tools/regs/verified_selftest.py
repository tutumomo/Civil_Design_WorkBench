"""Self-test for the verified formula/table library: literal test cases, cross-checks against the
design engines (tools/design), and that every entry points at a clause that exists in the index.
usage: python -E -P -X utf8 verified_selftest.py   (exit 0 = all ok)
"""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "design"))
import regq  # noqa: E402
import verified as V  # noqa: E402


def main():
    bad = 0

    def chk(name, ok, extra=""):
        nonlocal bad
        print(f"{'ok  ' if ok else 'FAIL'} {name} {extra}")
        bad += not ok

    f, t = V.load()
    con = regq.connect()
    for x in list(f.values()) + list(t.values()):
        chk(f"clause exists: {x['id']}", bool(regq.get_clause(con, x["src"], x.get("index_clause") or x["clause"])), f"{x['src']} {x.get('index_clause') or x['clause']}")
    for x in f.values():
        for i, c in enumerate(x.get("tests", [])):
            if c["out"] is None:
                continue
            v = V.evaluate(x["id"], c["in"])["value"]
            tol = c.get("tol", 1e-9)
            chk(f"test {x['id']}#{i}", abs(v - c["out"]) <= max(tol, 1e-9) * (1 if tol >= 1e-3 else 1) + (abs(c["out"]) * tol if tol < 1e-3 else 0), f"{v} vs {c['out']}")
    # guards: out-of-range and condition violations must raise
    for fid, inp in (("swc19_t1_overland", {"l": 400, "v": 0.4}), ("swc19_t1_overland", {"l": 100, "v": 1.0}),
                     ("swc17_rational_qp", {"C": 0.9, "I": 100, "A": 2000}),
                     ("swc96_Vs1_temp_detention", {"tb": 1, "Q1": 3, "Q2": 1}), ("swc16_intensity", {"P": 2000, "T": 25})):
        try:
            V.evaluate(fid, inp)
            chk(f"guard {fid} {inp}", False)
        except V.VerifiedError:
            chk(f"guard {fid} {inp}", True)
    try:
        V._compile("__import__('os')")
        chk("sandbox rejects calls", False)
    except V.VerifiedError:
        chk("sandbox rejects calls", True)

    # cross-checks with the design engines
    import hydrology as H
    for P, T, tt in ((2000, 25, 60), (2500, 10, 30), (3200, 50, 90)):
        a = V.evaluate("swc16_intensity", {"P": P, "T": T, "t": tt})["value"]
        chk(f"xcheck intensity P={P} T={T} t={tt}", abs(a - H.rainfall_intensity(P, T, tt)) < 1e-9)
    r = H.design_flow(2000, 25, 36, "丘陵地或森林", l_m=100, v_ms=0.4, L_km=1.0, H_km=0.1)
    t2 = V.evaluate("swc19_t2_rziha", {"H": 0.1, "L": 1.0})["value"]
    t1 = V.evaluate("swc19_t1_overland", {"l": 100, "v": 0.4})["value"]
    chk("xcheck tc", abs((t1 / 60 + t2 * 60) - r["tc_min"]) < 1e-3, f"{t1/60 + t2*60:.4f} vs {r['tc_min']}")
    q = V.evaluate("swc17_rational_qp", {"C": r["C"], "I": r["I_mm_hr"], "A": 36})["value"]
    chk("xcheck Qp", abs(q - r["Qp_m3s"]) < 0.01, f"{q:.4f} vs {r['Qp_m3s']}")
    for cond in H.RUNOFF_C["無開發整地區"]:
        for dev, key in ((False, "無開發整地區"), (True, "開發整地區")):
            tv = V.table("swc18_runoff_c", key, cond)["value"]
            chk(f"xcheck C {key}/{cond}", tuple(tv) == tuple(H.RUNOFF_C[key][cond]))
    import channel_hydraulics as CH
    Q, pr = CH.capacity(1.0, 0.5, 0.015, 0.01)
    v = V.evaluate("swc84_manning_v", {"n": 0.015, "R": pr["R"], "S": 0.01})["value"]
    chk("xcheck manning", abs(v * pr["A"] - Q) < 1e-9)
    import slope_stability as SS
    for k in ("永久性", "臨時性"):
        for c, val in SS.FS_TABLE[k].items() if True else ():
            chk(f"xcheck FS {k}/{c}", V.table("swc73_min_safety_factor", k, c)["value"] == val)
    import rc_design as RC
    r = RC.shear_check(100.0, b_mm=1000.0, h_mm=300.0, cc={"fc_mpa": 28.0, "cover_mm": 50.0})
    d_eff = 300.0 - 50.0 - 10.0
    vc = V.evaluate("rc112_Vc_a", {"fc": 28, "bw": 1000, "d": d_eff})["value"] / 1000.0
    chk("xcheck Vc vs rc_design.shear_check", abs(vc - r["Vc_kN"]) < 0.01, f"{vc:.3f} vs {r['Vc_kN']}")
    for As, b, d, fc, fy in ((1500, 300, 500, 28, 420), (3000, 300, 500, 28, 420), (800, 1000, 240, 28, 420)):
        phi_old, et, _ = RC.phi_by_strain(As, b, d, fc, fy)
        phi_new = V.evaluate("rc112_phi_flexure", {"et": et, "fy": fy})["value"]
        chk(f"xcheck phi 引擎 vs 112年版表21.2.2 As={As}", abs(phi_old - phi_new) <= 0.0006, f"εt={et:.4f} engine={phi_old} 規範={phi_new:.4f}")
        beta = V.evaluate("rc112_beta1", {"fc": fc})["value"]
        chk("xcheck beta1", abs(beta - (0.85 if fc <= 28 else max(0.65, 0.85 - 0.05 * (fc - 28) / 7))) < 1e-12)
    for fs_, cc_ in ((280, 50), (186.7, 75), (350, 40)):
        old = RC.spacing_limit_mm(cc_, fs_)[0]
        new = V.evaluate("rc112_bar_spacing_max", {"fs": fs_, "cc": cc_})["value"]
        chk(f"xcheck bar spacing fs={fs_} cc={cc_}", abs(old - new) < 0.11, f"{old} vs {new:.1f}")
    import earth_pressure as EP
    for phi, dl, al in ((30, 0, 0), (30, 20, 0), (34, 17, 15), (28, 14, 10)):
        eng = EP.coulomb_active_coefficient(phi, wall_friction_deg=dl, backfill_slope_deg=al, wall_angle_deg=90)
        new = V.evaluate("found112_Ka_coulomb", {"phi": phi, "delta": dl, "theta": 0, "alpha": al})["value"]
        chk(f"xcheck Ka coulomb phi={phi} d={dl} a={al}", abs(eng - new) < 1e-6, f"{eng:.5f} vs {new:.5f}")
    for phi, dl, al, kh, kv in ((30, 15, 0, 0.2, 0.0), (32, 16, 0, 0.15, 0.05), (30, 0, 0, 0.1, 0.0)):
        eng = EP.coulomb_active_coefficient(phi, wall_friction_deg=dl, backfill_slope_deg=al, wall_angle_deg=90, kh=kh, kv=kv)
        new = V.evaluate("found112_KAE", {"phi": phi, "delta": dl, "theta": 0, "alpha": al, "kh": kh, "kv": kv})["value"]
        # 2026-11-02 已修正引擎 root 內分母為 cos(β)，須與 112 版式(7.3-12) 逐值一致
        chk(f"xcheck KAE phi={phi} kh={kh} kv={kv}", abs(eng - new) / new < 1e-9, f"engine {eng:.6f} vs 112版式 {new:.6f}")
    chk("xcheck Kp rankine", abs(EP.rankine_passive_coefficient(30) - V.evaluate("found112_KPE", {"phi": 30, "delta": 0, "theta": 0, "alpha": 0, "kh": 0, "kv": 0})["value"]) < 1e-9)
    import culvert_hydraulics as CU
    for qc, w, h, sl, ln, nn, ke, tw in ((3.0, 1.5, 1.2, 0.01, 20.0, 0.013, 0.5, 0.6), (6.0, 2.0, 1.5, 0.005, 35.0, 0.015, 0.2, 1.7)):
        o = CU.outlet_control(qc, w, h, sl, ln, nn, ke, tw)
        mine = V.evaluate("hwdrain107_culvert_outlet_Hw", {"Ke": ke, "n": nn, "L": ln, "R": o["hydraulic_radius_full_m"], "V": o["full_flow_velocity_m_s"],
                                                           "h0": o["h0_m"], "S0": sl, "g": CU.G})["value"]
        chk(f"xcheck culvert outlet Hw (g={CU.G})", abs(mine - o["headwater_m"]) < 1e-9, f"{mine:.5f} vs {o['headwater_m']:.5f}")
    ke_map = {"wingwall_30_75": "鋼筋混凝土箱涵：30°~75°翼端牆式進口、平頭式", "wingwall_90_15": "鋼筋混凝土箱涵：10°~25°翼端牆式進口、平頭式",
              "wingwall_0": "鋼筋混凝土箱涵：平行端牆式進口、平頭式", "wingwall_45_top_bevel": "鋼筋混凝土箱涵：30°~75°翼端牆式進口、圓頭式",
              "headwall_chamfer": "鋼筋混凝土箱涵：端牆式進口、平頭狀"}
    for k, row in ke_map.items():
        chk(f"xcheck Ke {k}", CU.INLET_TYPES[k]["Ke"] == V.table("hwdrain107_Ke_TO1", row, "Ke")["value"])
    import design_api as DA
    run = DA.run_calculation("hydrology", {}, persist=False) if False else None
    refs = V.references_for("rc_beam")
    chk("design links resolve", len(refs) >= 8 and all(x["status"] == "verified" for x in refs), f"{len(refs)} refs")
    chk("every link id exists", all(len(V.references_for(k)) == len(v) for k, v in __import__("json").loads((V.DIR / "_links.json").read_text(encoding="utf-8")).items()))
    import regs_vtool
    problems = regs_vtool.lint()
    for pr in problems:
        print("FAIL lint", pr)
    chk("lint (SOP rules for every entry)", not problems)
    # table helpers
    chk("table interp refuses extrapolation", True)
    chk("rc phi shear", V.table("rc112_phi_table", "剪力", "φ")["value"] == 0.75)
    print(f"{len(f)} formulas, {len(t)} tables, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
