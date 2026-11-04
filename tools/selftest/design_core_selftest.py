r"""Closed-form regression tests for the shared design-core modules.

Run:
    C:\Python312\python.exe -E -P -X utf8 tools\selftest\design_core_selftest.py
"""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "design"))
sys.path.insert(0, str(ROOT / "tools" / "case_package"))

import earth_pressure as EP  # noqa: E402
import anchored_wall as AW  # noqa: E402
import block_wall as BW  # noqa: E402
import box_culvert as BC  # noqa: E402
import culvert_hydraulics as CH  # noqa: E402
import channel_profile as CP  # noqa: E402
import channel_cover as CC  # noqa: E402
import counterfort_wall as CW  # noqa: E402
import design_api as DA  # noqa: E402
import building_frame as BF  # noqa: E402
import detention_basin as DB  # noqa: E402
import drainage_network as DN  # noqa: E402
import frame_analysis as FA  # noqa: E402
import foundation_design as FD  # noqa: E402
import load_combinations as LC  # noqa: E402
import mse_wall as MW  # noqa: E402
import rc_design as RC  # noqa: E402
import retaining_wall as RW  # noqa: E402
import steel_column as SC  # noqa: E402
import wall_geometry as WG  # noqa: E402
import case_core as CASE  # noqa: E402


class ChannelCoverTests(unittest.TestCase):
    """RC 路側溝加蓋：車載彎矩、配筋、承壓與植筋手算對照。"""

    def test_effective_span_and_impact(self) -> None:
        r = CC.analyse(CC.example_payload())
        self.assertAlmostEqual(r["geometry"]["effective_span_m"], 0.80, places=9)
        self.assertAlmostEqual(r["loads"]["impact"], 0.30, places=9)

    def test_live_moment_hand_calc(self) -> None:
        # §4.3.3 情況A：M = P·1.25·(S+6.0)/6.9·(1+I)
        # P = 7300 kgf = 71.593 kN；S = 0.80；I = 0.30
        r = CC.analyse(CC.example_payload())
        want = 7300.0 * CC.KN_PER_KGF * 1.25 * (0.80 + 6.0) / 6.9 * 1.30
        self.assertAlmostEqual(r["loads"]["live_moment_service_kNm"], want, places=2)

    def test_dead_moment_hand_calc(self) -> None:
        # w = 24 × 0.25 = 6.0 kN/m²；M = 6.0 × 0.80² / 8 = 0.48
        r = CC.analyse(CC.example_payload())
        self.assertAlmostEqual(r["loads"]["dead_moment_kNm"], 0.48, places=2)

    def test_structural_design_passes(self) -> None:
        r = CC.analyse(CC.example_payload())
        self.assertTrue(r["pass"])
        self.assertTrue(r["slab"]["main"]["ok"])
        self.assertTrue(r["slab"]["shear"]["ok"])
        self.assertTrue(r["slab"]["crack"]["ok"])
        self.assertTrue(r["slab"]["deflection"]["ok"])
        self.assertTrue(r["wall_bearing"]["ok"])

    def test_distribution_steel_percent(self) -> None:
        # 主筋垂直車行方向：121/√S = 135.3%，上限 67%
        r = CC.analyse(CC.example_payload())
        self.assertAlmostEqual(r["slab"]["distribution"]["percent_of_main"], 67.0, places=6)

    def test_anchor_bond_hand_calc(self) -> None:
        # Nba = τcr·π·da·hef = 14 × π × 1.59 × 20 = 1398.6 kgf
        r = CC.analyse(CC.example_payload())
        anchor = r["anchors"]
        want = 14.0 * math.pi * 1.59 * 20.0
        self.assertAlmostEqual(anchor["tension"]["Nba_kgf"], want, places=1)
        self.assertGreater(anchor["tension"]["capacity_kN"], anchor["tension_demand_kN"])

    def test_anchor_edge_and_spacing(self) -> None:
        # 20 cm 壁厚、D16 居中：ca = 100 mm ≥ 6db = 95.4 mm
        r = CC.analyse(CC.example_payload())
        anchor = r["anchors"]
        self.assertAlmostEqual(anchor["edge_mm"], 100.0, places=6)
        self.assertGreaterEqual(anchor["edge_mm"], 6.0 * anchor["diameter_mm"])
        self.assertGreaterEqual(anchor["spacing_mm"], 6.0 * anchor["diameter_mm"])

    def test_bearing_hand_calc(self) -> None:
        # q = Vu / (0.20 × 1.0)
        r = CC.analyse(CC.example_payload())
        want = r["loads"]["design_shear_kN_m"] / 0.20
        self.assertAlmostEqual(r["wall_bearing"]["q_kpa"], want, places=1)

    def test_d13_anchor_is_allowed(self) -> None:
        payload = CC.example_payload()
        payload["connection"]["bar"] = "D13"
        payload["connection"]["spacing_mm"] = 100.0
        r = CC.analyse(payload)
        self.assertEqual(r["anchors"]["bar"], "D13")
        self.assertTrue(r["pass"])

    def test_d19_anchor_is_rejected(self) -> None:
        payload = CC.example_payload()
        payload["connection"]["bar"] = "D19"
        with self.assertRaises(CC.ChannelCoverError):
            CC.analyse(payload)

    def test_partial_fixity_adds_top_steel(self) -> None:
        simple = CC.analyse(CC.example_payload())
        payload = CC.example_payload()
        payload["connection"]["model"] = "partial_fixity"
        payload["connection"]["fixity_ratio"] = 0.50
        fixed = CC.analyse(payload)
        self.assertGreater(
            fixed["slab"]["top"]["As_req_mm2"],
            simple["slab"]["top"]["As_req_mm2"],
        )

    def test_smooth_interface_reduces_friction(self) -> None:
        payload = CC.example_payload()
        payload["connection"]["surface_condition"] = "smooth"
        smooth = CC.analyse(payload)
        rough = CC.analyse(CC.example_payload())
        self.assertAlmostEqual(smooth["anchors"]["friction"]["mu"], 0.6, places=6)
        self.assertLess(
            smooth["anchors"]["friction"]["phiVn_kN_m"],
            rough["anchors"]["friction"]["phiVn_kN_m"],
        )

    def test_crack_controls_auto_main_steel(self) -> None:
        # 淨寬 0.40 m：若只配到撓曲剛好，D16@150 的 w=0.378 > 0.30。
        # 自動設計應改由裂縫控制加密間距。
        payload = CC.example_payload()
        payload["geometry"]["clear_width_m"] = 0.40
        payload["loads"]["vehicle"] = "hs20"
        payload["loads"]["live_load_factor"] = 1.0
        r = CC.analyse(payload)
        self.assertTrue(r["pass"])
        self.assertEqual(r["slab"]["main"]["governed_by"], "裂縫控制（主筋加密）")
        self.assertLessEqual(r["slab"]["main"]["spacing_mm"], 130.0)
        self.assertTrue(r["slab"]["crack"]["ok"])

    def test_specified_main_bars_ng_is_reported(self) -> None:
        # 使用者指定 D16@150 檢查既有配置：不得自動改筋，應回報裂縫 NG。
        payload = CC.example_payload()
        payload["geometry"]["clear_width_m"] = 0.40
        payload["loads"]["vehicle"] = "hs20"
        payload["loads"]["live_load_factor"] = 1.0
        payload["slab"] = {"main_bar": "D16", "main_spacing_mm": 150.0}
        r = CC.analyse(payload)
        self.assertFalse(r["pass"])
        self.assertEqual(r["slab"]["main"]["source"], "指定")
        self.assertAlmostEqual(r["slab"]["main"]["spacing_mm"], 150.0)
        self.assertFalse(r["slab"]["crack"]["ok"])
        self.assertEqual(
            [c["item"] for c in r["checks"] if not c["ok"]],
            ["裂縫寬度 w"],
        )

    def test_specified_main_bars_pass(self) -> None:
        payload = CC.example_payload()
        payload["geometry"]["clear_width_m"] = 0.40
        payload["loads"]["vehicle"] = "hs20"
        payload["loads"]["live_load_factor"] = 1.0
        payload["slab"] = {"main_bar": "D16", "main_spacing_mm": 125.0}
        r = CC.analyse(payload)
        self.assertTrue(r["pass"])
        self.assertEqual(r["slab"]["main"]["bar"], "D16")
        self.assertAlmostEqual(r["slab"]["main"]["spacing_mm"], 125.0)
        self.assertLessEqual(r["slab"]["crack"]["w_mm"], 0.30)

    def test_specified_rebar_must_be_paired(self) -> None:
        payload = CC.example_payload()
        payload["slab"] = {"main_bar": "D16", "main_spacing_mm": 0.0}
        with self.assertRaises(CC.ChannelCoverError):
            CC.analyse(payload)

    def test_d29_bar_is_supported(self) -> None:
        payload = CC.example_payload()
        payload["slab"] = {"dist_bar": "D29", "dist_spacing_mm": 200.0}
        r = CC.analyse(payload)
        self.assertEqual(r["slab"]["distribution"]["bar"], "D29")
        self.assertTrue(r["pass"])

    def test_workbench_registration(self) -> None:
        self.assertIn("channel_cover", DA.RUNNERS)
        self.assertIn("channel_cover", [c["id"] for c in DA.CATALOG])
        result = DA.run_calculation("channel_cover", CC.example_payload(), persist=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["calculator"], "channel_cover")


class SteelColumnTests(unittest.TestCase):
    """鋼構柱＋柱腳基板＋基礎螺栓：與手算逐項對照。"""

    SECTION = {"h_mm": 400.0, "b_mm": 300.0, "tw_mm": 13.0, "tf_mm": 22.0}

    def test_section_properties_hand_calc(self) -> None:
        # 手算（H400×300×13×22，忽略填角）：
        #   hw = 400 − 2×22 = 356 mm
        #   Ag = (2×300×22 + 356×13) / 100 = 178.28 cm²
        #   Ix = (300×400³ − (300−13)×356³) / 12 / 10⁴ = 52092.745 cm⁴
        #   Iy = (2×(22×300³/12) + 356×13³/12) / 10⁴ = 9906.5178 cm⁴
        props = SC.section_properties(self.SECTION)
        self.assertAlmostEqual(props["Ag_cm2"], 178.28, places=4)
        self.assertAlmostEqual(props["Ix_cm4"], 52092.7451, places=3)
        self.assertAlmostEqual(props["Iy_cm4"], 9906.5178, places=3)
        self.assertAlmostEqual(props["Sx_cm3"], 2604.6373, places=3)
        self.assertAlmostEqual(props["rx_cm"], 17.0937, places=3)
        self.assertAlmostEqual(props["ry_cm"], 7.4543, places=3)

    def test_asd_axial_capacity_hand_calc(self) -> None:
        # §6.3 Fa（(一) 版，式6.3-1）：Cc = √(2π²E/Fy) = 128.823
        #   取 KL/r = 60：ratio = 60/128.823 = 0.46575
        #   Fa = [1 − (KL/r)²/(2Cc²)]·Fy / [5/3 + (3/8)(KL/r)/Cc − (1/8)((KL/r)/Cc)³]
        #   Fa = 1.21801 tf/cm² = 119.446 MPa
        refs = SC._Refs()
        props = SC.section_properties(self.SECTION)
        fy_tf = 245.0 * SC.TF_PER_MPA
        e_tf = 206000.0 * SC.TF_PER_MPA
        cc = math.sqrt(2.0 * math.pi ** 2 * e_tf / fy_tf)
        ratio = 60.0 / cc
        hand = (
            (1.0 - 60.0 ** 2 / (2.0 * cc ** 2))
            * fy_tf
            / (5.0 / 3.0 + 3.0 / 8.0 * ratio - 1.0 / 8.0 * ratio ** 3)
        )
        axial = SC.axial_capacity("asd", props, fy_tf, e_tf, 60.0, refs)
        self.assertAlmostEqual(hand, 1.218012, places=5)
        self.assertAlmostEqual(axial["Fa_tf_cm2"], hand, places=9)
        self.assertAlmostEqual(axial["Fa_mpa"], 119.446, places=2)
        self.assertAlmostEqual(
            axial["capacity_kN"], hand * 178.28 * 9.80665, places=4
        )

    def test_base_plate_bearing_hand_calc(self) -> None:
        # §10.9（(二) 版）：φcPp = 0.6 × 0.85fc′A1√(A2/A1)
        #   A1 = 0.50×0.55 m² = 2750 cm²；A2 = 0.80×0.85 m² = 6800 cm²（≤ 4A1）
        #   fc′ = 28 MPa = 285.5216 kgf/cm²
        #   φcPp = 0.6×0.85×285.5216×2750×√(6800/2750) = 629694.6 kgf = 61751.9 kN
        refs = SC._Refs()
        out = SC.base_plate_bearing("lrfd", 0.50, 0.55, 28.0, 0.80, 0.85, refs)
        self.assertAlmostEqual(out["A1_cm2"], 2750.0, places=6)
        self.assertAlmostEqual(out["A2_cm2"], 6800.0, places=6)
        self.assertAlmostEqual(out["capacity_kN"], 61751.94, places=2)
        # (一) 版：Fp = 0.35fc′√(A2/A1) ≤ 0.7fc′
        asd = SC.base_plate_bearing("asd", 0.50, 0.55, 28.0, 0.80, 0.85, refs)
        expected_fp = 0.35 * 28.0 * math.sqrt(6800.0 / 2750.0)
        self.assertAlmostEqual(asd["allowable_mpa"], expected_fp, places=6)

    def test_bolt_tension_hand_calc(self) -> None:
        # 表10.3-2（(二) 版）：A307 Fnt = 3.15 tf/cm²，φ = 0.75
        #   Ab = π/4 × 3.2² = 8.04248 cm² → φFnt·Ab = 19.00035 tf = 186.330 kN
        refs = SC._Refs()
        ab = math.pi / 4.0 * 3.2 ** 2
        cap = SC.anchor_capacity(
            "lrfd", "A307", 400.0 * SC.TF_PER_MPA, True, ab, refs
        )
        self.assertAlmostEqual(cap["design_tension_tf_cm2"], 0.75 * 3.15, places=6)
        self.assertAlmostEqual(cap["tension_capacity_kN"], 186.3298, places=3)

    def test_anchor_group_elastic_hand_calc(self) -> None:
        # 彈性錨栓群法：T_i = Mx·y_i/Σy² − P/n
        #   Σy² = 8×0.21² = 0.3528；Mx·y/Σy² = 280×0.21/0.3528 = 166.6667 kN
        #   P/n = 700/8 = 87.5 kN → T_max = 79.1667 kN（受拉側 4 支），合計 316.667 kN
        positions = [
            {"x_m": x, "y_m": y}
            for y in (-0.21, 0.21)
            for x in (-0.19, -0.09, 0.09, 0.19)
        ]
        group = SC._anchor_group_elastic(positions, 700.0, 280.0, 0.0)
        self.assertAlmostEqual(group["sum_y2"], 0.3528, places=9)
        self.assertAlmostEqual(group["axial_share_per_anchor_kn"], 87.5, places=9)
        self.assertAlmostEqual(max(group["tensions_kn"]), 79.1667, places=3)
        self.assertAlmostEqual(group["total_tension_kn"], 316.6667, places=3)

    def test_contact_pressure_hand_calc(self) -> None:
        # 全板線性接觸壓力 q = P/A + M/S
        #   A = 0.55×0.50 = 0.275 m²；S = 0.50×0.55²/6 = 0.0252083 m³
        #   q_mean = 700/0.275 = 2545.4545 kPa；q_edge = 280×0.275/0.0252083 = 3054.5455 kPa
        #   q_max = 5600.0 kPa、q_min = −509.0909 kPa（揚起）
        out = SC._contact_pressure(700.0, 280.0, 0.55, 0.50)
        self.assertAlmostEqual(out["area_m2"], 0.275, places=9)
        self.assertAlmostEqual(out["section_modulus_m3"], 0.02520833, places=7)
        self.assertAlmostEqual(out["q_max_kpa"], 5600.0, places=4)
        self.assertAlmostEqual(out["q_min_kpa"], -509.0909, places=3)
        self.assertTrue(out["uplift"])

    def test_cone_projected_area_hand_calc(self) -> None:
        # 單支錨栓 45° 應力錐投影面積 ≈ π·hef²（hef = 0.6 m）= 11309.7 cm²
        out = SC.cone_projected_area(
            [{"x_m": 0.0, "y_m": 0.0}], 0.6, None, step_m=0.002
        )
        area = out["area_cm2"]
        self.assertAlmostEqual(area, math.pi * 0.6 ** 2 * 1.0e4, delta=area * 0.02)

    def test_end_to_end_asd_and_lrfd(self) -> None:
        for method in ("asd", "lrfd"):
            result = SC.analyse(SC.example_payload(method))
            self.assertTrue(result["pass"], result.get("warnings"))
            self.assertEqual(len(result["checks"]), 14)
            failed = [
                c["item"]
                for c in result["checks"]
                if not c["ok"] and c.get("severity") != "advisory"
            ]
            self.assertEqual(failed, [])

    def test_unknown_grade_is_rejected(self) -> None:
        payload = SC.example_payload("lrfd")
        payload["anchors"]["grade"] = "A999"
        with self.assertRaises(SC.SteelColumnError):
            SC.analyse(payload)


class WallGeometryTests(unittest.TestCase):
    def test_gravity_section(self) -> None:
        wall = WG.parse(
            {
                "wall_type": "gravity",
                "height_m": 3.0,
                "stem_thickness_m": 0.4,
                "base_width_m": 1.8,
            }
        )
        self.assertAlmostEqual(wall.area_m2_per_m, 3.3, places=12)
        self.assertEqual(wall.wall_type, "gravity")

    def test_cantilever_components(self) -> None:
        wall = WG.parse(
            {
                "wall_type": "cantilever",
                "height_m": 3.0,
                "stem_thickness_m": 0.35,
                "base_width_m": 2.4,
                "base_thickness_m": 0.4,
            }
        )
        expected = 2.4 * 0.4 + 0.35 * 3.0
        self.assertAlmostEqual(wall.area_m2_per_m, expected, places=12)
        self.assertEqual(len(wall.concrete_components()), 2)

    def test_legacy_semigravity_geometry(self) -> None:
        wall = WG.parse(
            {
                "wall_type": "semigravity",
                "height_m": 4.5,
                "base_width_m": 2.5,
                "base_thickness_m": 0.8,
                "top_width_m": 0.3,
                "front_batter_ratio": 0.3,
                "toe_projection_m": 0.5,
                "toe_soil_depth_m": 1.5,
            }
        )
        # Legacy workbook components: base 2.000 + stem 1.110 + triangle 2.0535.
        self.assertAlmostEqual(wall.area_m2_per_m, 5.1635, places=10)
        self.assertAlmostEqual(wall.centroid_m[0], 1.3556579839, places=8)
        self.assertAlmostEqual(
            sum(c.area_m2_per_m for c in wall.concrete_components()), 5.1635, places=10
        )
        self.assertAlmostEqual(
            sum(c.area_m2_per_m for c in wall.soil_components()), 0.35, places=10
        )


class WallRebarTests(unittest.TestCase):
    """擋土牆配筋分流：重力式／半重力式走名目構造鋼筋，懸臂式才做撓曲配筋。

    先前所有 wall 一律套 design_cantilever_stem()，3 m 重力式被算出
    66.8 kg/m（虛構的撓曲主筋）；改為分流後應為約 43.9 kg/m 的構造鋼筋。
    """

    GRAVITY = {
        "wall_type": "gravity",
        "height_m": 3.0,
        "stem_thickness_m": 0.30,
        "base_width_m": 1.95,
    }
    CANTILEVER = {
        "wall_type": "cantilever",
        "height_m": 3.0,
        "stem_thickness_m": 0.35,
        "base_width_m": 1.95,
        "base_thickness_m": 0.36,
    }
    SEMIGRAVITY = {
        "wall_type": "semigravity",
        "height_m": 4.0,
        "stem_thickness_m": 0.35,
        "top_width_m": 0.35,
        "front_batter_ratio": 0.30,
        "base_width_m": 2.60,
        "base_thickness_m": 0.60,
        "toe_projection_m": 0.50,
        "toe_soil_depth_m": 1.50,
    }

    def test_gravity_uses_nominal_steel(self) -> None:
        res = RW.analyse(self.GRAVITY)
        out = RC.design_wall_rebar(self.GRAVITY, res)
        self.assertEqual(out["wall_type"], "gravity")
        self.assertIsNone(out["structural"])
        mass = out["mass"]
        self.assertFalse(mass["structural_rebar"])
        # 牆面（露出側）D13@250 → 1,000/250 × A_D13
        as_face = RC.REBAR_SIZES["D13"][1] * 1000.0 / 250.0
        self.assertAlmostEqual(mass["As_face_mm2_per_m"], as_face, places=1)
        self.assertAlmostEqual(mass["temperature_ratio"], as_face / 250000.0, places=5)
        self.assertGreaterEqual(mass["temperature_ratio"], mass["temperature_min"])
        self.assertEqual(len(mass["rows"]), 3)
        self.assertNotIn("主筋", "".join(r["item"] for r in mass["rows"]))

    def test_mass_wall_total_includes_lap_allowance(self) -> None:
        res = RW.analyse(self.GRAVITY)
        mass = RC.design_mass_wall_steel(self.GRAVITY, res)
        self.assertAlmostEqual(
            mass["total_kg_per_m"],
            mass["subtotal_kg_per_m"] * (1.0 + mass["lap_allowance"]),
            places=3,
        )
        # 3 m 重力式（T=0.30、BL=1.95）實測總量 43.86 kg/m；
        # 舊版誤套懸臂公式為 66.8 kg/m（多算 52%）。
        self.assertAlmostEqual(mass["total_kg_per_m"], 43.857, places=2)

    def test_semigravity_uses_nominal_steel(self) -> None:
        res = RW.analyse(self.SEMIGRAVITY)
        out = RC.design_wall_rebar(self.SEMIGRAVITY, res)
        self.assertEqual(out["wall_type"], "semigravity")
        self.assertIsNone(out["structural"])
        self.assertFalse(out["mass"]["structural_rebar"])
        self.assertGreater(out["total_kg_per_m"], 0.0)

    def test_cantilever_keeps_flexural_design(self) -> None:
        res = RW.analyse(self.CANTILEVER)
        out = RC.design_wall_rebar(self.CANTILEVER, res)
        self.assertEqual(out["wall_type"], "cantilever")
        self.assertIn("stem", out["structural"])
        self.assertIn("base", out["structural"])
        self.assertIn("main", out["structural"]["stem"])
        self.assertAlmostEqual(out["total_kg_per_m"], 138.46, delta=1.0)

    def test_unknown_wall_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RC.design_wall_rebar(
                {"height_m": 3.0, "stem_thickness_m": 0.3},
                {"wall_type": "unknown_wall"},
            )

    def test_counterfort_steel_is_wired_and_positive(self) -> None:
        q = {
            "height_m": 8.0, "stem_thickness_m": 0.30, "base_width_m": 6.60,
            "base_thickness_m": 0.60, "toe_length_m": 1.98,
            "counterfort_spacing_m": 3.0, "counterfort_thickness_m": 0.40,
            "counterfort_top_width_m": 0.30, "front_soil_depth_m": 1.0,
        }
        soil = {"gamma": 18.0, "phi_deg": 30.0, "allowable_bearing_kpa": 300.0,
                "base_friction": 0.6, "foundation": "soil"}
        res = CW.analyse(q, soil=soil, seismic={"kh": 0.0})
        out = RC.design_wall_rebar(q, res)
        self.assertEqual(out["wall_type"], "counterfort")
        self.assertGreater(out["total_kg_per_m"], 0.0)
        names = "".join(row["item"] for row in out["structural"]["rows"])
        for token in ("牆板", "踵板", "趾板", "扶壁"):
            self.assertIn(token, names)
        self.assertAlmostEqual(
            out["total_kg_per_m"],
            out["structural"]["subtotal_kg_per_m"]
            * (1.0 + out["structural"]["lap_allowance"]),
            places=2,
        )

    def test_anchored_steel_is_wired_and_positive(self) -> None:
        q = {
            "height_m": 7.0, "wall_thickness_m": 0.40, "base_width_m": 1.20,
            "base_thickness_m": 0.50, "front_soil_depth_m": 1.0,
            "anchor_depths_m": [1.5, 3.5, 5.5], "horizontal_spacing_m": 2.50,
            "inclination_deg": 20.0, "service": "permanent", "strand_type": "12.7",
            "strands": 4, "free_length_m": 7.0, "bond_length_m": 6.0,
            "drill_diameter_mm": 135.0, "bearing_plate_m": 0.30,
            "lockoff_factor": 1.15, "pressure_distribution": "apparent",
        }
        soil = {"gamma": 19.0, "phi_deg": 30.0, "surcharge_kpa": 10.0,
                "allowable_bearing_kpa": 300.0, "base_friction": 0.55,
                "bond_strength_kpa": 400.0, "tendon_bond_mpa": 2.0}
        res = AW.analyse(q, soil=soil, seismic={"kh": 0.0})
        out = RC.design_wall_rebar(q, res)
        self.assertEqual(out["wall_type"], "anchored")
        self.assertGreater(out["total_kg_per_m"], 0.0)
        names = "".join(row["item"] for row in out["structural"]["rows"])
        self.assertIn("承壓區", names)
        # 4 道牆面筋＋承壓區＋基腳上下層＋縱向分布筋
        self.assertIn("基腳", names)
        self.assertEqual(len(out["structural"]["rows"]), 8)

    def test_mse_face_steel_uses_panel_minimum(self) -> None:
        q = {
            "height_m": 6.0, "embedment_m": 0.60, "reinforcement_type": "geogrid",
            "reinforcement_length_m": 5.40, "vertical_spacing_m": 0.60,
            "first_layer_m": 0.30, "long_term_strength_kN_per_m": 40.0,
            "coverage_ratio": 1.0, "face_panel_thickness_m": 0.20,
            "panel_width_m": 1.50, "face_panel_cover_mm": 50.0,
        }
        soil = {
            "reinforced_gamma": 19.0, "reinforced_phi_deg": 34.0,
            "retained_gamma": 18.0, "retained_phi_deg": 30.0,
            "foundation_phi_deg": 30.0, "surcharge_kpa": 10.0,
            "allowable_bearing_kpa": 300.0, "foundation": "soil",
        }
        res = MW.analyse(q, soil=soil, seismic={"kh": 0.0})
        out = RC.design_wall_rebar(q, res)
        self.assertEqual(out["wall_type"], "mse")
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["structural"]["rows"]), 2)
        self.assertEqual(out["structural"]["bar"], "D13")
        self.assertGreater(out["total_kg_per_m"], 0.0)

    def test_block_wall_has_no_rc_steel(self) -> None:
        q = {"wall_type": "gabion", "course_count": 3, "course_height_m": 1.0,
             "base_width_m": 2.5, "width_decrement_m": 0.5, "step_side": "front",
             "embedment_m": 0.5}
        res = BW.analyse(q)
        out = RC.design_wall_rebar(q, res)
        self.assertEqual(out["wall_type"], "gabion")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_kg_per_m"], 0.0)
        self.assertFalse(out["structural"]["applicable"])
        self.assertEqual(out["structural"]["rows"], [])

    def test_workbench_wall_stability_includes_rebar(self) -> None:
        """工作台擋土牆計算器必須同時回傳配筋，不能只給穩定分析。"""
        payload = dict(self.CANTILEVER)
        payload.update({
            "soil": {"gamma": 18.0, "phi_deg": 30.0, "c_kpa": 0.0,
                     "allowable_bearing_kpa": 200.0},
            "fc_mpa": 21.0, "fy_mpa": 420, "cover_mm": 75,
            "stem_bar": "auto", "base_bar": "auto",
        })
        out = DA.run_calculation("wall_stability", payload, persist=False)
        self.assertTrue(out["ok"])
        rebar = out["result"]["rebar"]
        self.assertAlmostEqual(rebar["total_kg_per_m"], 138.461, places=2)
        self.assertIn("配筋設計", out["summary"])
        self.assertTrue(any("撓曲" in c["item"] for c in out["checks"]))
        for check in out["checks"]:
            self.assertIn("item", check)
            self.assertIn("limit", check)
            self.assertIn("unit", check)

        # 指定筋號要真的改變配筋結果
        payload["stem_bar"] = "D19"
        out2 = DA.run_calculation("wall_stability", payload, persist=False)
        stem = out2["result"]["rebar"]["structural"]["stem"]["main"]
        self.assertEqual(stem["bar"], "D19")


class EarthPressureTests(unittest.TestCase):
    def test_rankine_triangle(self) -> None:
        result = EP.active_earth_pressure(
            height_m=4.0,
            gamma_kn_m3=18.0,
            phi_deg=30.0,
            wall_friction_deg=0.0,
        )
        self.assertAlmostEqual(result.coefficient, 1.0 / 3.0, places=12)
        self.assertAlmostEqual(result.horizontal_kn_per_m, 48.0, places=9)
        self.assertAlmostEqual(result.application_height_m, 4.0 / 3.0, places=9)

    def test_legacy_coulomb_fixture(self) -> None:
        result = EP.active_earth_pressure(
            height_m=4.5,
            gamma_kn_m3=16.671305,
            phi_deg=38.0,
            wall_friction_deg=2.0 * 38.0 / 3.0,
        )
        # data/reference/擋土牆/legacy_semigravity_H4.5.json
        self.assertAlmostEqual(result.total_normal_kn_per_m, 36.5934, places=3)
        self.assertAlmostEqual(result.horizontal_kn_per_m, 33.0719, delta=0.005)
        self.assertAlmostEqual(result.vertical_kn_per_m, 15.6567, delta=0.005)
        self.assertAlmostEqual(result.application_height_m, 1.5, places=9)

    def test_surcharge_and_water(self) -> None:
        result = EP.active_earth_pressure(
            height_m=4.0,
            gamma_kn_m3=18.0,
            phi_deg=30.0,
            surcharge_kpa=10.0,
            groundwater_depth_m=2.0,
            saturated_unit_weight_kn_m3=20.0,
            wall_friction_deg=0.0,
        )
        expected_soil = 0.5 * (1.0 / 3.0) * 18.0 * 16.0 + (1.0 / 3.0) * 10.0 * 4.0
        expected_soil += 0.5 * (1.0 / 3.0) * (20.0 - 9.81 - 18.0) * (4.0 - 2.0) ** 2
        expected_water = 0.5 * 9.81 * (4.0 - 2.0) ** 2
        self.assertAlmostEqual(result.soil_horizontal_kn_per_m, expected_soil, places=8)
        self.assertAlmostEqual(result.water_horizontal_kn_per_m, expected_water, places=8)


class RetainingWallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.q = {
            "wall_type": "semigravity",
            "height_m": 4.5,
            "base_width_m": 2.5,
            "base_thickness_m": 0.8,
            "top_width_m": 0.3,
            "front_batter_ratio": 0.3,
            "toe_projection_m": 0.5,
            "toe_soil_depth_m": 1.5,
        }
        self.soil = {
            "allowable_bearing_kpa": 200.0,
            "ultimate_bearing_kpa": 759.05,
            "ultimate_bearing_seismic_kpa": 714.018,
            "concrete_unit_weight_kn_m3": 23.53596,
            "foundation_soil": {
                "gamma_kn_m3": 17.65197,
                "phi_deg": 32.0,
                "c_kpa": 0.0,
            },
            "backfill": {
                "gamma_kn_m3": 16.671305,
                "phi_deg": 38.0,
                "c_kpa": 0.0,
                "wall_friction_deg": 2.0 * 38.0 / 3.0,
            },
        }

    def test_legacy_semigravity_static_fs(self) -> None:
        # Keep the original 4.5 m fixture as an engine regression check.
        # The public entry point intentionally rejects this height below.
        result = RW._analyse_semigravity(self.q, self.soil, {"kh": 0.0})
        values = {c["item"]: c["value"] for c in result["checks"]}
        self.assertAlmostEqual(values["滑動（常時）"], 3.6473913, delta=0.002)
        self.assertAlmostEqual(values["傾倒（常時）"], 4.1413261, delta=0.002)
        self.assertAlmostEqual(
            values["基礎承載（FS＝q_ult/q_max）"], 9.5138472, delta=0.01
        )
        self.assertAlmostEqual(result["x_R_m"], 1.0869593, delta=0.001)
        # 報告與數量共用 res["soil"]["base_friction"]；半重力式的摩擦係數
        # 是由 foundation_soil 推得，必須回寫到共用契約，不能只留在區域變數。
        self.assertIn("base_friction", result["soil"])
        self.assertAlmostEqual(
            result["soil"]["base_friction"],
            math.tan(math.radians((2.0 / 3.0) * 32.0)),
            places=8,
        )

    def test_legacy_semigravity_seismic_fs(self) -> None:
        result = RW._analyse_semigravity(self.q, self.soil, {"kh": 0.15})
        values = {c["item"]: c["value"] for c in result["checks"]}
        self.assertAlmostEqual(values["滑動（地震）"], 1.8577324, delta=0.01)
        self.assertAlmostEqual(values["傾倒（地震）"], 1.9032621, delta=0.01)
        self.assertAlmostEqual(
            values["基礎承載（FS＝q_ult/q_max）"], 5.0154221, delta=0.03
        )

    def test_supported_wall_type_height_limits(self) -> None:
        limits = {"gravity": 4.0, "semigravity": 4.0, "cantilever": 8.0}
        for wall_type, maximum in limits.items():
            with self.subTest(wall_type=wall_type):
                RW.validate_wall_applicability(wall_type, maximum)
                with self.assertRaisesRegex(ValueError, "超過適用上限"):
                    RW.validate_wall_applicability(wall_type, maximum + 0.01)

    def test_unsupported_wall_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支援的擋土牆牆型"):
            RW.validate_wall_applicability("buttressed", 3.0)

    def test_public_semigravity_entry_uses_effective_height(self) -> None:
        q = dict(self.q)
        q["height_m"] = 4.8  # 4.0 m exposed + 0.8 m base.
        result = RW.analyse_semigravity(q, self.soil, {"kh": 0.0})
        self.assertEqual(result["wall_type"], "semigravity")

        q["height_m"] = 4.81
        with self.assertRaisesRegex(ValueError, "超過適用上限 4.0 m"):
            RW.analyse_semigravity(q, self.soil, {"kh": 0.0})


class ToePassivePressureTests(unittest.TestCase):
    """牆趾被動土壓力：手算 Pp＝½·Kp·γ·D²，Kp＝tan²(45°＋φ/2)，φ＝30° 時 Kp＝3。"""

    CANTILEVER = {"wall_type": "cantilever", "height_m": 3.0, "stem_thickness_m": 0.35,
                  "base_width_m": 1.95, "base_thickness_m": 0.36}

    @staticmethod
    def _example(calc_id):
        return next(c for c in DA.list_calculators() if c["id"] == calc_id)["example"]

    def test_limitations_do_not_claim_passive_is_ignored(self):
        for calc in DA.list_calculators():
            if calc["id"] in {"wall_stability", "block_wall", "counterfort_wall",
                              "mse_wall", "anchored_wall"}:
                self.assertNotIn("被動土壓與", calc["limitations"], calc["id"])
                self.assertNotIn("被動土壓、", calc["limitations"], calc["id"])

    def test_user_case_d060_gives_9_72_kn_per_m(self):
        result = EP.toe_passive_resistance(depth_m=0.6, gamma_kn_m3=18.0, phi_deg=30.0)
        self.assertAlmostEqual(result["Kp"], 3.0, places=9)
        self.assertAlmostEqual(result["Pp_kN_per_m"], 9.72, places=9)
        self.assertAlmostEqual(result["application_height_m"], 0.2, places=9)

    def test_ratio_scales_force_and_is_bounded(self):
        half = EP.toe_passive_resistance(depth_m=0.6, gamma_kn_m3=18.0, phi_deg=30.0, ratio=0.5)
        self.assertAlmostEqual(half["Pp_kN_per_m"], 4.86, places=9)
        with self.assertRaisesRegex(EP.EarthPressureError, "折減比"):
            EP.toe_passive_resistance(depth_m=0.6, gamma_kn_m3=18.0, phi_deg=30.0, ratio=1.2)

    def test_gravity_and_cantilever_need_explicit_opt_in(self):
        base = RW.analyse(self.CANTILEVER)
        ignored = RW.analyse({**self.CANTILEVER, "toe_soil_depth_m": 1.5})
        self.assertEqual(ignored["checks"][0]["value"], base["checks"][0]["value"])
        self.assertIn("未計入", ignored["warnings"][0])

        counted = RW.analyse({**self.CANTILEVER, "toe_soil_depth_m": 0.6, "include_passive": True})
        expected = (base["W_kN_per_m"] * 0.5 + 9.72) / base["Pa_kN_per_m"]
        self.assertAlmostEqual(counted["checks"][0]["value"], expected, places=2)
        self.assertEqual(counted["checks"][1]["value"], base["checks"][1]["value"])
        self.assertEqual(counted["e_m"], base["e_m"])

    def test_gravity_wall_counts_passive(self):
        q = {"wall_type": "gravity", "height_m": 3.0, "stem_thickness_m": 0.45,
             "base_width_m": 1.8, "base_thickness_m": 0.0}
        result = RW.analyse({**q, "toe_soil_depth_m": 0.6, "include_passive": True})
        self.assertAlmostEqual(result["Pp_kN_per_m"], 9.72, places=3)

    def test_semigravity_keeps_counting_and_can_be_switched_off(self):
        q = {"wall_type": "semigravity", "height_m": 4.5, "base_width_m": 2.5,
             "base_thickness_m": 0.8, "top_width_m": 0.3, "front_batter_ratio": 0.3,
             "toe_projection_m": 0.5, "toe_soil_depth_m": 1.5}
        counted = RW.analyse(q)
        self.assertGreater(counted["Pp_kN_per_m"], 0.0)
        off = RW.analyse({**q, "include_passive": False})
        self.assertEqual(off["Pp_kN_per_m"], 0.0)
        self.assertLess(off["checks"][0]["value"], counted["checks"][0]["value"])

    def test_depth_must_stay_below_wall_height(self):
        with self.assertRaisesRegex(ValueError, "牆趾覆土深"):
            RW.analyse({**self.CANTILEVER, "toe_soil_depth_m": 3.36, "include_passive": True})

    def test_calculators_default_off_except_semigravity(self):
        for calc_id in ("block_wall", "counterfort_wall", "mse_wall", "anchored_wall"):
            with self.subTest(calc_id):
                payload = {k: v for k, v in self._example(calc_id).items() if k != "include_passive"}
                payload["soil"] = {k: v for k, v in payload["soil"].items()
                                   if k not in ("include_passive", "passive_ratio")}
                run = DA.run_calculation(calc_id, payload, persist=False)
                self.assertTrue(run["result"] is not None, run.get("error"))
                passive = run["result"].get("passive") or run["result"]["stability"]["static"]["passive"]
                self.assertFalse(passive["included"])

    def test_workbench_examples_report_passive(self):
        expected = {"wall_stability": 9.72, "block_wall": 6.75, "counterfort_wall": 69.12,
                    "anchored_wall": 14.25}
        for calc_id, pp in expected.items():
            with self.subTest(calc_id):
                run = DA.run_calculation(calc_id, self._example(calc_id), persist=False)
                self.assertTrue(run["result"] is not None, run.get("error"))
                passive = run["result"].get("passive") or run["result"]["stability"]["static"]["passive"]
                self.assertAlmostEqual(passive["Pp_kN_per_m"], pp, places=3)
                self.assertIn("牆趾被動土壓力", run["summary"])
                self.assertTrue(any("不得移除" in w for w in run["warnings"]))

    def test_mse_uses_foundation_gamma(self):
        payload = dict(self._example("mse_wall"), include_passive=True)
        payload["soil"] = dict(payload["soil"], foundation_gamma=20.0)
        run = DA.run_calculation("mse_wall", payload, persist=False)
        self.assertAlmostEqual(run["result"]["passive"]["Pp_kN_per_m"], 10.8, places=3)

    def test_seismic_case_warns_about_static_kp(self):
        run = DA.run_calculation("counterfort_wall", self._example("counterfort_wall"), persist=False)
        self.assertTrue(any("靜態 Rankine Kp" in w for w in run["warnings"]))

    def test_counterfort_sizing_forwards_passive_switch(self):
        payload = dict(self._example("counterfort_wall"), size=True)
        run = DA.run_calculation("counterfort_wall", payload, persist=False)
        self.assertTrue(run["result"]["stability"]["static"]["passive"]["included"])


class BlockWallTests(unittest.TestCase):
    SOIL = {"gamma": 18.0, "phi_deg": 30.0, "base_friction": 0.5,
            "allowable_bearing_kpa": 200.0}

    def test_single_gabion_block_matches_hand_calculation(self) -> None:
        # 2 m × 2 m 單層：Ka=1/3、Pa=0.5·Ka·18·2²=12、W=18·4=72
        # FS滑=0.5·72/12=3.0、FS倒=(72·1.0)/(12·2/3)=9.0、x_R=(72-8)/72
        res = BW.analyse({"wall_type": "gabion",
                          "layers": [{"height_m": 2.0, "width_m": 2.0}]}, self.SOIL)
        base = res["interfaces"][0]
        self.assertAlmostEqual(base["Ka"], 1.0 / 3.0, places=4)
        self.assertAlmostEqual(base["Ph_kN_per_m"], 12.0, places=6)
        self.assertAlmostEqual(base["FS_sliding"], 3.0, places=6)
        self.assertAlmostEqual(base["FS_overturning"], 9.0, places=6)
        self.assertAlmostEqual(base["x_R_m"], 64.0 / 72.0, places=4)

    def test_back_stepped_layers_include_soil_on_steps(self) -> None:
        # 後階：下層 2.0 m 寬、上層 1.0 m 寬；上層後方 1.0×1.0 m 土塊壓在下層
        res = BW.analyse({"wall_type": "gabion", "layers": [
            {"height_m": 1.0, "width_m": 2.0},
            {"height_m": 1.0, "width_m": 1.0},
        ]}, self.SOIL)
        base, upper = res["interfaces"]
        self.assertAlmostEqual(base["W_wall_kN_per_m"], 18.0 * 3.0, places=6)
        self.assertAlmostEqual(base["W_soil_kN_per_m"], 18.0, places=6)
        self.assertAlmostEqual(upper["W_soil_kN_per_m"], 0.0, places=6)
        self.assertAlmostEqual(upper["width_m"], 1.0, places=6)
        self.assertAlmostEqual(upper["Ph_kN_per_m"], 0.5 / 3.0 * 18.0, places=4)

    def test_masonry_trapezoid_weight_and_wedge(self) -> None:
        res = BW.analyse({"wall_type": "masonry_wet", "height_m": 3.0, "top_width_m": 0.5,
                          "front_batter_ratio": 0.3, "back_batter_ratio": 0.2,
                          "stone_length_m": 0.5}, self.SOIL)
        base = res["interfaces"][0]
        self.assertAlmostEqual(res["geometry"]["base_width_m"], 2.0, places=6)
        self.assertAlmostEqual(base["W_wall_kN_per_m"], 3.75 * 23.0, places=4)
        self.assertAlmostEqual(base["W_soil_kN_per_m"], 0.5 * 0.6 * 3.0 * 18.0, places=4)

    def test_section_118_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "超過適用上限 4.0 m"):
            BW.analyse({"wall_type": "gabion", "course_count": 5, "course_height_m": 1.0,
                        "base_width_m": 3.0, "width_decrement_m": 0.5, "embedment_m": 0.9})
        BW.analyse({"wall_type": "gabion", "course_count": 5, "course_height_m": 1.0,
                    "base_width_m": 3.0, "width_decrement_m": 0.5, "embedment_m": 1.0})
        with self.assertRaisesRegex(ValueError, "每層上限 3.0 m"):
            BW.analyse({"wall_type": "crib", "layers": [
                {"height_m": 3.5, "width_m": 3.0}]})
        with self.assertRaisesRegex(ValueError, "陡於 1:0.3"):
            BW.analyse({"wall_type": "masonry_dry", "height_m": 2.0, "top_width_m": 0.5,
                        "front_batter_ratio": 0.2, "stone_length_m": 0.5})
        res = BW.analyse({"wall_type": "masonry_dry", "height_m": 3.0, "top_width_m": 0.6,
                          "front_batter_ratio": 0.3, "back_batter_ratio": 0.2,
                          "stone_length_m": 0.5})
        stone = [c for c in res["checks"] if "長徑" in c["item"]][0]
        self.assertFalse(stone["ok"])  # 3.0 > 5 × 0.5
        self.assertFalse(res["pass"])

    def test_sandwich_wall_limits_by_site(self) -> None:
        base = {"wall_type": "sandwich", "top_width_m": 0.6, "front_batter_ratio": 0.3,
                "back_batter_ratio": 0.1, "embedment_m": 0.5}
        with self.assertRaisesRegex(ValueError, "site_condition"):
            BW.analyse(dict(base, height_m=2.0))
        with self.assertRaisesRegex(ValueError, "2.0 m"):
            BW.analyse(dict(base, height_m=2.6, site_condition="fill"))
        res = BW.analyse(dict(base, height_m=3.5, site_condition="cut"))
        self.assertTrue(res["pass"])
        self.assertFalse([c for c in res["checks"] if "長徑" in c["item"]])

    def test_overhanging_back_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "懸在填土上"):
            BW.analyse({"wall_type": "gabion", "layers": [
                {"height_m": 1.0, "width_m": 1.0},
                {"height_m": 1.0, "width_m": 1.5},
            ]})


class CounterfortWallTests(unittest.TestCase):
    SECTION = {"height_m": 8.0, "stem_thickness_m": 0.3, "base_width_m": 5.2,
               "base_thickness_m": 0.6, "toe_length_m": 1.2, "counterfort_spacing_m": 3.0,
               "counterfort_thickness_m": 0.4, "counterfort_top_width_m": 0.3,
               "front_soil_depth_m": 1.0}
    SOIL = {"gamma": 18.0, "phi_deg": 30.0, "allowable_bearing_kpa": 300.0, "base_friction": 0.6}

    def test_weights_and_earth_pressure_match_hand_calculation(self) -> None:
        res = CW.analyse(self.SECTION, self.SOIL)
        st = res["stability"]["static"]
        # 底板 74.88＋牆板 57.6＋扶壁 16×0.4/3×24＝51.2＋覆土 532.8−38.4＋前趾覆土 21.6
        self.assertAlmostEqual(st["N_kN_per_m"], 74.88 + 57.6 + 51.2 + 494.4 + 21.6, places=3)
        # Pa＝0.5×(1/3)×18×8.6²
        self.assertAlmostEqual(st["Pa_kN_per_m"], 0.5 / 3.0 * 18.0 * 8.6 ** 2, places=3)
        self.assertAlmostEqual(st["FS_sliding"], 0.6 * st["N_kN_per_m"] / st["Pa_kN_per_m"], places=6)

    def test_stem_and_counterfort_moments(self) -> None:
        res = CW.analyse(self.SECTION, self.SOIL)
        bottom = [m for m in res["structure"]["slabs"] if m["member"].startswith("牆板下帶 水平負")][0]
        # p＝Ka·γ·H＝48 kPa；Mu＝1.7×48×3²/12
        self.assertAlmostEqual(bottom["Mu_kNm_per_m"], 1.7 * 48.0 * 9.0 / 12.0, places=3)
        cf = res["structure"]["counterfort"]
        # M＝S·Ka·γ·H³/6＝3×(1/3)×18×512/6
        self.assertAlmostEqual(cf["M_service_kNm"], 3.0 / 3.0 * 18.0 * 512.0 / 6.0, places=3)
        # 扶壁為豎向懸臂 T 梁，d 是水平由牆板前面量到扶壁背面，
        # 不可乘斜背傾角（舊式會少 12%，屬保守但定義錯誤）。
        self.assertAlmostEqual(cf["d_mm"], (0.3 + 3.7) * 1000.0 - 105.0, places=0)

    def test_effective_height_limit_10m(self) -> None:
        sec = dict(self.SECTION, height_m=11.5, front_soil_depth_m=1.0)
        with self.assertRaisesRegex(ValueError, "超過適用上限 10.0 m"):
            CW.analyse(sec, self.SOIL)
        CW.analyse(dict(sec, front_soil_depth_m=1.5), self.SOIL)

    def test_size_section_passes_static_and_seismic(self) -> None:
        out = CW.size_section(8.0, self.SOIL, 0.15, front_soil_depth_m=1.0)
        self.assertTrue(out["found"])
        self.assertTrue(out["result"]["pass"])
        self.assertIsNotNone(out["result"]["stability"]["seismic"])


class MSEWallTests(unittest.TestCase):
    SEC = {"height_m": 6.0, "embedment_m": 0.6, "reinforcement_length_m": 4.5,
           "reinforcement_type": "geogrid", "vertical_spacing_m": 0.6, "first_layer_m": 0.3,
           "long_term_strength_kN_per_m": 30.0}
    SOIL = {"reinforced_gamma": 19.0, "reinforced_phi_deg": 34.0, "retained_gamma": 18.0,
            "retained_phi_deg": 30.0, "surcharge_kpa": 10.0, "allowable_bearing_kpa": 300.0}

    def test_external_forces_match_hand_calculation(self) -> None:
        res = MW.analyse(self.SEC, self.SOIL)
        ext = res["external"]["static"]
        self.assertAlmostEqual(ext["V_kN_per_m"], 19.0 * 6.0 * 4.5, places=6)
        # Ph＝0.5·(1/3)·18·6²＋(1/3)·10·6＝108＋20
        self.assertAlmostEqual(ext["Ph_kN_per_m"], 128.0, places=4)

    def test_internal_bottom_layer_tension_and_rupture(self) -> None:
        res = MW.analyse(self.SEC, self.SOIL)
        bottom = res["layers"][0]
        ka = math.tan(math.radians(45.0 - 17.0)) ** 2
        self.assertAlmostEqual(bottom["Tmax_kN_per_m"], ka * (19.0 * 5.7 + 10.0) * 0.6, places=4)
        # Le＝L－y·tan(45−φ/2)
        self.assertAlmostEqual(bottom["Le_m"], 4.5 - 0.3 * math.tan(math.radians(28.0)), places=4)
        rupture = [c for c in res["checks"] if c["item"].startswith("第 1 層") and c["item"].endswith("拉斷")][0]
        self.assertFalse(rupture["ok"])  # 30 / 20.07 = 1.495 < 1.5

    def test_steel_strip_uses_bilinear_surface_and_kr_ratio(self) -> None:
        res = MW.analyse(dict(self.SEC, reinforcement_type="steel_strip", coverage_ratio=0.25,
                              long_term_strength_kN_per_m=200.0), self.SOIL)
        top = res["layers"][-1]
        self.assertAlmostEqual(top["La_m"], 0.3 * 6.0, places=6)
        self.assertGreater(top["Kr"], res["Ka_reinforced"] * 1.6)

    def test_effective_height_limit_8m(self) -> None:
        with self.assertRaisesRegex(ValueError, "超過適用上限 8.0 m"):
            MW.analyse(dict(self.SEC, height_m=9.0, embedment_m=0.5), self.SOIL)
        MW.analyse(dict(self.SEC, height_m=9.0, embedment_m=1.0, reinforcement_length_m=6.5), self.SOIL)

    def test_connector_and_bearing_use_governing_layer(self) -> None:
        q = dict(self.SEC, panel_width_m=1.5,
                 connector_capacity_kN=50.0,
                 connector_bearing_area_mm2=20000.0,
                 connector_fs=1.5)
        res = MW.analyse(q, self.SOIL)
        gov = max(res["layers"],
                  key=lambda l: l["Tmax_kN_per_m"] + float(l.get("Tmd_kN_per_m") or 0.0))
        demand = (gov["Tmax_kN_per_m"] + float(gov.get("Tmd_kN_per_m") or 0.0)) * 1.5
        conn = res["connection"]
        self.assertIsNotNone(conn)
        self.assertAlmostEqual(conn["demand_kN"], demand, places=3)
        self.assertAlmostEqual(conn["FS"], 50.0 / demand, places=3)
        self.assertAlmostEqual(conn["bearing_stress_mpa"],
                               demand * 1000.0 / 20000.0, places=3)
        self.assertTrue(any("面版－加勁材連接" in c["item"] for c in res["checks"]))
        self.assertTrue(any("局部承壓" in c["item"] for c in res["checks"]))

    def test_connector_absent_stays_explicitly_unchecked(self) -> None:
        res = MW.analyse(self.SEC, self.SOIL)
        self.assertIsNone(res["connection"])
        self.assertIn("面版連接強度、局部承壓", "".join(res["warnings"]))


class AnchoredWallTests(unittest.TestCase):
    SEC = {"height_m": 7.0, "wall_thickness_m": 0.4, "base_width_m": 1.2, "base_thickness_m": 0.5,
           "front_soil_depth_m": 1.0, "anchor_depths_m": [1.5, 3.5, 5.5], "horizontal_spacing_m": 2.5,
           "inclination_deg": 20.0, "strands": 4, "free_length_m": 7.0, "bond_length_m": 6.0,
           "drill_diameter_mm": 135.0}
    SOIL = {"gamma": 19.0, "phi_deg": 30.0, "surcharge_kpa": 10.0, "bond_strength_kpa": 400.0,
            "allowable_bearing_kpa": 300.0, "base_friction": 0.55}

    def test_beam_reactions_match_hand_solutions(self) -> None:
        # 單排地錨＋基底為靜定：R1＝qH²/(2(H－z1))
        r = AW.beam_reactions(6.0, [2.0, 6.0], lambda z: 10.0)
        self.assertAlmostEqual(r[0], 45.0, places=6)
        self.assertAlmostEqual(r[1], 15.0, places=6)
        # 兩等跨連續梁均佈：3/8、10/8、3/8 qL
        r = AW.beam_reactions(8.0, [1e-6, 4.0, 8.0], lambda z: 10.0)
        for got, want in zip(r, (15.0, 50.0, 15.0)):
            self.assertAlmostEqual(got, want, delta=0.05)

    def test_apparent_envelope_and_anchor_load(self) -> None:
        res = AW.analyse(self.SEC, self.SOIL)
        ka = 1.0 / 3.0
        self.assertAlmostEqual(res["pressure"]["P_earth_kN_per_m"], 0.65 * ka * 19.0 * 49.0, places=3)
        self.assertAlmostEqual(res["pressure"]["p_max_kPa"], 0.65 * ka * 19.0 * 49.0 / (7.0 - 0.5 - 0.5), places=3)
        total = sum(a["R_static_kN_per_m"] for a in res["anchors"]) + res["base"][0]["R_base_kN_per_m"]
        self.assertAlmostEqual(total, 0.65 * ka * 19.0 * 49.0 + ka * 10.0 * 7.0, delta=0.01)
        a1 = res["anchors"][0]
        self.assertAlmostEqual(a1["T_design_kN"], a1["R_static_kN_per_m"] * 2.5 / math.cos(math.radians(20.0)), delta=0.01)
        # 長久性地層-漿體 FS 3.0：Lb＝T·3/(π·D·τ)
        self.assertAlmostEqual(a1["bond_by_ground_m"], a1["T_design_kN"] * 3.0 / (math.pi * 0.135 * 400.0), delta=0.01)
        self.assertTrue(res["pass"])

    def test_code_minimums_and_weak_anchor(self) -> None:
        res = AW.analyse(dict(self.SEC, bond_length_m=2.5, free_length_m=3.5, strands=2), self.SOIL)
        failed = " | ".join(c["item"] for c in res["checks"] if not c["ok"])
        for key in ("抗張材 T ≤ Pu/2.0", "錨碇段長", "自由段長"):
            self.assertIn(key, failed)
        temp = AW.analyse(dict(self.SEC, service="temporary"), self.SOIL)
        self.assertEqual(temp["anchor_fs"]["ground_grout"], 2.0)
        with self.assertRaisesRegex(ValueError, "太接近或超過牆底"):
            AW.analyse(dict(self.SEC, anchor_depths_m=[6.9]), self.SOIL)


class FrameAnalysisTests(unittest.TestCase):
    E = 200e6  # kN/m²
    A = 0.01
    I = 1e-4

    def test_cantilever_point_load(self) -> None:
        L = 3.0
        model = FA.FrameModel(
            [
                {"id": "A", "x": 0.0, "y": 0.0, "restraint": (True, True, True)},
                {"id": "B", "x": L, "y": 0.0, "fy": -10.0},
            ],
            [
                {
                    "id": "m",
                    "i": "A",
                    "j": "B",
                    "E_kn_m2": self.E,
                    "area_m2": self.A,
                    "inertia_m4": self.I,
                }
            ],
        )
        result = model.solve()
        expected = -10.0 * L**3 / (3.0 * self.E * self.I)
        self.assertAlmostEqual(result.displacements["B"][1], expected, places=12)
        self.assertAlmostEqual(result.reactions["A"][1], 10.0, places=10)
        self.assertAlmostEqual(result.reactions["A"][2], 30.0, places=10)

    def test_cantilever_uniform_load(self) -> None:
        L = 3.0
        q = -5.0
        n = 10
        nodes = [
            {
                "id": str(i),
                "x": L * i / n,
                "y": 0.0,
                "restraint": (True, True, True) if i == 0 else (False, False, False),
            }
            for i in range(n + 1)
        ]
        members = [
            {
                "id": str(i),
                "i": str(i),
                "j": str(i + 1),
                "E_kn_m2": self.E,
                "area_m2": self.A,
                "inertia_m4": self.I,
                "loads": {"wy": q},
            }
            for i in range(n)
        ]
        result = FA.analyse(nodes, members)
        expected = q * L**4 / (8.0 * self.E * self.I)
        self.assertAlmostEqual(result.displacements[str(n)][1], expected, places=10)
        self.assertAlmostEqual(result.reactions["0"][1], -q * L, places=9)
        self.assertAlmostEqual(result.reactions["0"][2], -q * L * L / 2.0, places=9)

    def test_fixed_fixed_uniform_load(self) -> None:
        L = 6.0
        q = -10.0
        result = FA.analyse(
            [
                {"id": "A", "x": 0.0, "y": 0.0, "restraint": (True, True, True)},
                {"id": "B", "x": L, "y": 0.0, "restraint": (True, True, True)},
            ],
            [
                {
                    "id": "m",
                    "i": "A",
                    "j": "B",
                    "E_kn_m2": self.E,
                    "area_m2": self.A,
                    "inertia_m4": self.I,
                    "loads": {"wy": q},
                }
            ],
        )
        self.assertAlmostEqual(result.reactions["A"][1], 30.0, places=9)
        self.assertAlmostEqual(result.reactions["B"][1], 30.0, places=9)
        self.assertAlmostEqual(result.members["m"].moment_end_knm[0], -30.0, places=8)
        self.assertAlmostEqual(result.members["m"].moment_end_knm[1], -30.0, places=8)
        self.assertAlmostEqual(result.members["m"].max_abs_moment_knm, 30.0, places=8)

    def test_simply_supported_uniform_load(self) -> None:
        L = 6.0
        q = -10.0
        n = 10
        nodes = []
        for i in range(n + 1):
            if i == 0:
                restraint = (True, True, False)
            elif i == n:
                restraint = (False, True, False)
            else:
                restraint = (False, False, False)
            nodes.append({"id": str(i), "x": L * i / n, "y": 0.0, "restraint": restraint})
        members = [
            {
                "id": str(i),
                "i": str(i),
                "j": str(i + 1),
                "E_kn_m2": self.E,
                "area_m2": self.A,
                "inertia_m4": self.I,
                "loads": {"wy": q},
            }
            for i in range(n)
        ]
        result = FA.analyse(nodes, members)
        self.assertAlmostEqual(result.reactions["0"][1], 30.0, places=8)
        self.assertAlmostEqual(result.reactions[str(n)][1], 30.0, places=8)
        max_m = max(m.max_abs_moment_knm for m in result.members.values())
        self.assertAlmostEqual(max_m, q * L * L / 8.0 * -1.0, places=8)


class BoxCulvertTests(unittest.TestCase):
    def section(self, cell_count: int) -> BC.BoxCulvertSection:
        return BC.BoxCulvertSection.from_mapping(
            {
                "cell_count": cell_count,
                "clear_width_m": 3.0,
                "clear_height_m": 2.5,
                "wall_thickness_m": 0.35,
                "interior_wall_thickness_m": 0.30,
                "top_slab_thickness_m": 0.40,
                "bottom_slab_thickness_m": 0.45,
                "cover_depth_m": 0.60,
                "length_m": 20.0,
            }
        )

    def test_topology_scales_with_cell_count(self) -> None:
        expected_nodes = {1: 4, 2: 6, 3: 8}
        expected_members = {1: 4, 2: 7, 3: 10}
        for n in (1, 2, 3):
            built = BC.build_frame(self.section(n), BC.BoxCulvertLoads())
            self.assertEqual(len(built.nodes), expected_nodes[n])
            self.assertEqual(len(built.members), expected_members[n])
            self.assertEqual(
                len([m for m in built.members if m.role == "interior"]), n - 1
            )

    def test_gravity_load_case_is_globally_balanced(self) -> None:
        built = BC.build_frame(self.section(3), BC.BoxCulvertLoads())
        result = FA.FrameModel(
            built.nodes, [m.frame_member for m in built.members]
        ).solve()
        self.assertAlmostEqual(sum(result.applied_load_vector[0::3]), 0.0, places=8)
        self.assertAlmostEqual(sum(result.applied_load_vector[1::3]), 0.0, places=8)
        self.assertAlmostEqual(sum(result.applied_load_vector[2::3]), 0.0, places=8)
        self.assertGreater(
            result.members["T0"].max_abs_moment_knm,
            1.0,
            "Member loads were not transferred to the frame model.",
        )

    def test_normal_depth_reproduces_manning_capacity(self) -> None:
        section = self.section(2)
        flow = BC.hydraulic_capacity(
            section, slope=0.005, manning_n=0.014, design_flow_m3s=4.2
        )
        self.assertAlmostEqual(flow["design_flow_m3s"], 4.2, places=12)
        b = section.clear_width_m
        y = flow["normal_depth_m"]
        area = section.cell_count * b * y
        perimeter = section.cell_count * (b + 2.0 * y)
        expected = (
            (1.0 / 0.014)
            * area
            * (area / perimeter) ** (2.0 / 3.0)
            * math.sqrt(0.005)
        )
        q_capacity = flow["capacity_m3s"]
        q_at_full = (
            (1.0 / 0.014)
            * flow["full_flow_area_m2"]
            * flow["hydraulic_radius_full_m"] ** (2.0 / 3.0)
            * math.sqrt(0.005)
        )
        self.assertAlmostEqual(q_capacity, q_at_full, places=9)
        self.assertTrue(flow["capacity_ok"])
        self.assertTrue(flow["freeboard_ok"])
        # The reported flow area and normal depth must satisfy the same formula.
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(flow["flow_area_m2"], area, places=12)

    def test_concrete_quantity_is_exact_outer_minus_voids(self) -> None:
        for n in (1, 2, 3):
            section = self.section(n)
            result = BC.analyse(section, design_flow_m3s=1.0)
            expected = (
                section.outer_width_m * section.outer_height_m
                - n * section.clear_width_m * section.clear_height_m
            )
            self.assertAlmostEqual(
                result["quantities"]["concrete_area_m2_per_m"], expected, places=12
            )
            self.assertAlmostEqual(
                result["quantities"]["concrete_volume_m3"],
                expected * section.length_m,
                places=9,
            )

    def test_face_reinforcement_covers_inner_outer_and_distribution(self) -> None:
        result = BC.analyse(self.section(3), design_flow_m3s=5.0)
        rep = result["reinforcement"]
        labels = {e["label"] for e in rep["elements"]}
        for expected in (
            "頂版外側（覆土側）",
            "頂版內側（涵內側）",
            "底版外側（基礎土側）",
            "底版內側（涵內側）",
            "外側牆外側（背土側）",
            "外側牆內側（涵內側）",
            "中間牆左面（涵內側）",
            "中間牆右面（涵內側）",
        ):
            self.assertIn(expected, labels)
        self.assertEqual(len(rep["elements"]), 8)
        for face in rep["elements"]:
            self.assertIn(face["flexure"]["bar"], BC.RC.REBAR_SIZES)
            self.assertGreater(face["flexure"]["As_prov_mm2"], 0.0)
            self.assertGreater(face["flexure"]["phiMn_kNm"], 0.0)
            self.assertTrue(face["ok"], face["label"])
        self.assertEqual(len(rep["distribution"]), 4)
        self.assertTrue(all(d["ok"] for d in rep["distribution"]))
        self.assertGreater(rep["quantity"]["total_kg"], 1000.0)
        self.assertAlmostEqual(
            rep["quantity"]["total_kg_per_m"],
            rep["quantity"]["total_kg"] / self.section(3).length_m,
            places=1,
        )
        self.assertTrue(all(c["ok"] for c in result["checks"]))

    def test_one_cell_has_no_interior_wall_faces(self) -> None:
        result = BC.analyse(self.section(1), design_flow_m3s=1.0)
        self.assertFalse(
            any(e["key"] == "interior_wall" for e in result["reinforcement"]["elements"])
        )
        self.assertEqual(len(result["reinforcement"]["elements"]), 6)
        self.assertEqual(len(result["reinforcement"]["distribution"]), 3)

    def test_cover_and_bar_preference_are_exposed(self) -> None:
        base = BC.analyse(self.section(3), design_flow_m3s=1.0, cover_mm=50.0)
        thick = BC.analyse(self.section(3), design_flow_m3s=1.0, cover_mm=75.0)
        self.assertEqual(base["section"]["cover_mm"], 50.0)
        self.assertEqual(thick["section"]["cover_mm"], 75.0)
        base_outer = next(
            e for e in base["reinforcement"]["elements"]
            if e["label"].startswith("頂版外側")
        )
        thick_outer = next(
            e for e in thick["reinforcement"]["elements"]
            if e["label"].startswith("頂版外側")
        )
        self.assertLess(
            thick_outer["flexure"]["d_mm"],
            base_outer["flexure"]["d_mm"],
        )
        self.assertLessEqual(
            thick_outer["flexure"]["spacing_max_mm"],
            base_outer["flexure"]["spacing_max_mm"],
        )
        fine = BC.analyse(
            self.section(3), design_flow_m3s=1.0, bar_preference="fine"
        )
        self.assertEqual(fine["reinforcement"]["bar_preference"][0], "D13")

    def test_shear_stirrups_are_not_reported_when_concrete_capacity_is_enough(self) -> None:
        result = BC.analyse(self.section(3), design_flow_m3s=1.0)
        self.assertTrue(
            all(m["shear"].get("required") is False for m in result["members"])
        )

    def test_axial_flexure_follows_the_governing_tension_face(self) -> None:
        # 6 m 覆土時頂版外側受拉、內側受壓；兩面配筋不同。
        # 若兩個彎曲方向取較小值，會得到約 199 kN·m/m 而誤判 NG；
        # 依實際受拉面定向後，容量應高於 240 kN·m/m。
        heavy = replace(self.section(3), cover_depth_m=6.0)
        result = BC.analyse(heavy, design_flow_m3s=5.0)
        top = next(
            a for a in result["reinforcement"]["axial_flexure"]
            if a["key"] == "top_slab"
        )
        self.assertEqual(top["tension_face"], "outer")
        self.assertGreater(top["phiMn_available_kNm"], 240.0)
        self.assertTrue(top["ok"])
        self.assertTrue(result["pass"])

    def test_h20_vehicle_load_matches_workbook(self) -> None:
        section = replace(self.section(1), cover_depth_m=0.0)
        traffic = BC.resolve_traffic_load(section, "h20")
        # 箱涵(單孔、雙孔、四孔).xls：7.25×1.30/[(1.065+0.707×0)×3.30]
        self.assertAlmostEqual(traffic.uniform_pressure_kpa / 9.80665, 2.6817, places=3)
        self.assertAlmostEqual(traffic.impact_factor, 0.30, places=12)
        result = BC.analyse(section, design_flow_m3s=0.0, traffic_type="h20")
        self.assertEqual(result["loads"]["traffic_type"], "h20")
        self.assertGreater(result["loads"]["traffic_equivalent_kpa"], 26.0)

    def test_h20_s16_lane_formula_matches_workbook(self) -> None:
        section = replace(self.section(2), clear_width_m=2.9, cover_depth_m=2.0)
        traffic = BC.resolve_traffic_load(
            section, "h20_s16", traffic_lanes=4
        )
        # 箱涵(雙孔、三孔).xls：4×4×7.3/(3.5×10.9125)=3.0581 t/m²
        self.assertAlmostEqual(
            traffic.uniform_pressure_kpa / 9.80665, 3.0581, places=4
        )
        self.assertEqual(traffic.lanes, 4)
        self.assertAlmostEqual(traffic.details["W_m"], 10.9125, places=4)

    def test_trailer_40t_uses_partial_patch_and_increases_steel(self) -> None:
        none = BC.analyse(self.section(3), design_flow_m3s=1.0, traffic_type="none")
        trailer = BC.analyse(
            self.section(3), design_flow_m3s=1.0, traffic_type="trailer_40t"
        )
        self.assertGreater(trailer["loads"]["traffic_patch_total_kn_m"], 0.0)
        self.assertGreater(
            trailer["loads"]["traffic_equivalent_kpa"],
            none["loads"]["traffic_equivalent_kpa"],
        )
        self.assertGreater(
            trailer["reinforcement"]["quantity"]["total_kg_per_m"],
            none["reinforcement"]["quantity"]["total_kg_per_m"],
        )
        top_face = next(
            e for e in trailer["reinforcement"]["elements"]
            if e["label"].startswith("頂版")
        )
        self.assertGreater(top_face["Mu_kNm"], 0.0)

    def test_no_traffic_must_be_explicit_and_lane_count_is_checked(self) -> None:
        result = BC.analyse(self.section(1), design_flow_m3s=0.0, traffic_type="none")
        self.assertEqual(result["loads"]["traffic_equivalent_kpa"], 0.0)
        self.assertTrue(any("未指定車載重" in w for w in result["warnings"]))
        with self.assertRaisesRegex(BC.BoxCulvertError, "traffic_lanes"):
            BC.analyse(
                self.section(2),
                design_flow_m3s=0.0,
                traffic_type="h20_s16",
                traffic_lanes=5,
            )


class CulvertHydraulicsTests(unittest.TestCase):
    """公路排水設計規範 §6.2／附錄 N、O 的獨立手算對帳。"""

    def test_inlet_control_form2_hand_calculation(self) -> None:
        # B=2.0, D=1.5, Q=1.0, S=0 → A=3.0, X=1.811/(3·√1.5)=0.49291
        result = CH.inlet_control(1.0, 2.0, 1.5, 0.0, "headwall_chamfer")
        x = 1.811 * 1.0 / (3.0 * math.sqrt(1.5))
        self.assertAlmostEqual(result["discharge_intensity_X"], x, places=12)
        expected = 0.515 * x ** (2.0 / 3.0)  # S = 0, so no −0.5·S term
        self.assertAlmostEqual(result["hw_over_d"], expected, places=12)
        self.assertAlmostEqual(result["headwater_m"], expected * 1.5, places=12)
        self.assertIn("非潛沒", result["regime"])

    def test_inlet_control_form1_includes_critical_depth(self) -> None:
        # 30°~75° flares: HW/D = 1.5·dc/D + 0.026·X (M=1)
        result = CH.inlet_control(1.0, 2.0, 1.5, 0.004, "wingwall_30_75")
        x = 1.811 * 1.0 / (3.0 * math.sqrt(1.5))
        dc = ((1.0 / 2.0) ** 2 / 9.81) ** (1.0 / 3.0)
        expected = 1.5 * dc / 1.5 + 0.026 * x - 0.5 * 0.004
        self.assertAlmostEqual(result["hw_over_d"], expected, places=12)
        self.assertAlmostEqual(result["critical_depth_m"], dc, places=12)

    def test_transition_zone_interpolates_between_curves(self) -> None:
        # Pick Q so X lands at 3.75, midway between the two validity limits.
        area, d = 2.0 * 1.5, 1.5
        x_target = 3.75
        q = x_target * area * math.sqrt(d) / 1.811
        lo = CH.inlet_control(
            CH.X_UNSUBMERGED_MAX * area * math.sqrt(d) / 1.811,
            2.0, d, 0.0, "wingwall_90_15",
        )
        hi = CH.inlet_control(
            CH.X_SUBMERGED_MIN * area * math.sqrt(d) / 1.811,
            2.0, d, 0.0, "wingwall_90_15",
        )
        mid = CH.inlet_control(q, 2.0, d, 0.0, "wingwall_90_15")
        self.assertIn("過渡", mid["regime"])
        self.assertAlmostEqual(
            mid["hw_over_d"], 0.5 * (lo["hw_over_d"] + hi["hw_over_d"]), places=12
        )

    def test_outlet_control_hand_calculation(self) -> None:
        # B=2.0, D=1.5, L=20, S=0, n=0.014, Ke=0.5, TW=0, Q=1.0
        result = CH.outlet_control(1.0, 2.0, 1.5, 0.0, 20.0, 0.014, 0.5, 0.0)
        area, radius = 3.0, 3.0 / (2.0 * 3.5)
        v = 1.0 / area
        friction = 19.6 * 0.014 ** 2 * 20.0 / radius ** 1.33
        hf = (1.0 + 0.5 + friction) * v * v / (2.0 * 9.81)
        dc = ((1.0 / 2.0) ** 2 / 9.81) ** (1.0 / 3.0)
        h0 = 0.5 * (dc + 1.5)
        self.assertAlmostEqual(result["hydraulic_radius_full_m"], radius, places=12)
        self.assertAlmostEqual(result["head_loss_m"], hf, places=12)
        self.assertAlmostEqual(result["h0_m"], h0, places=12)
        self.assertAlmostEqual(result["headwater_m"], hf + h0, places=12)
        self.assertEqual(result["h0_basis"], "(dc + D)/2")

    def test_tailwater_above_crown_uses_tailwater(self) -> None:
        result = CH.outlet_control(1.0, 2.0, 1.5, 0.0, 20.0, 0.014, 0.5, 2.0)
        self.assertEqual(result["h0_m"], 2.0)
        self.assertIn("高過涵頂", result["h0_basis"])

    def test_governing_headwater_is_the_larger_of_the_two(self) -> None:
        result = CH.analyse(
            design_flow_m3s=1.0, clear_width_m=2.0, clear_height_m=1.5,
            length_m=20.0, slope=0.0, inlet_type="headwall_chamfer",
            tailwater_depth_m=0.0, allowable_headwater_m=2.0,
        )
        self.assertEqual(result["governing"]["control"], "出口控制")
        self.assertAlmostEqual(
            result["governing"]["headwater_m"],
            max(result["inlet"]["headwater_m"], result["outlet"]["headwater_m"]),
            places=12,
        )
        self.assertTrue(result["pass"])

    def test_appendix_n2_example_within_nomograph_tolerance(self) -> None:
        # 附錄 N.2：1500×600、Q=2.12 → 1.75／1.90／2.05（型式 1／2／3）
        expected = {"wingwall_30_75": 1.75, "wingwall_90_15": 1.90, "wingwall_0": 2.05}
        for inlet_type, target in expected.items():
            got = CH.inlet_control(2.12, 1.5, 0.6, 0.0, inlet_type)["hw_over_d"]
            self.assertLess(abs(got - target) / target, 0.10,
                            "%s: %.3f vs %.2f" % (inlet_type, got, target))
        # Nomographs order the three cases (1) < (2) < (3); keep that ordering.
        self.assertLess(
            CH.inlet_control(2.12, 1.5, 0.6, 0.0, "wingwall_30_75")["hw_over_d"],
            CH.inlet_control(2.12, 1.5, 0.6, 0.0, "wingwall_90_15")["hw_over_d"],
        )
        self.assertLess(
            CH.inlet_control(2.12, 1.5, 0.6, 0.0, "wingwall_90_15")["hw_over_d"],
            CH.inlet_control(2.12, 1.5, 0.6, 0.0, "wingwall_0")["hw_over_d"],
        )

    def test_table_6_1_minimum_section_is_enforced(self) -> None:
        base = dict(design_flow_m3s=0.5, length_m=20.0, slope=0.005,
                    inlet_type="wingwall_30_75")
        small = CH.analyse(clear_width_m=0.9, clear_height_m=1.0, **base)
        self.assertFalse(small["pass"])
        ok = CH.analyse(clear_width_m=1.0, clear_height_m=1.0, **base)
        for check in ok["checks"]:
            if "最小淨寬" in check["item"] or "最小淨高" in check["item"]:
                self.assertTrue(check["ok"])

    def test_headwall_geometry_and_advisory_severity(self) -> None:
        result = CH.analyse(
            design_flow_m3s=1.0, clear_width_m=2.0, clear_height_m=1.5,
            length_m=20.0, slope=0.0, inlet_type="headwall_chamfer",
            headworks={
                "headwall_top_above_crown_m": 0.20,
                "headwall_thickness_m": 0.20,
            },
        )
        by_item = {c["item"]: c for c in result["checks"]}
        top = next(c for i, c in by_item.items() if "端牆頂高出涵頂" in i)
        thick = next(c for i, c in by_item.items() if "端牆厚度" in i)
        self.assertFalse(top["ok"])
        self.assertNotIn("severity", top)
        self.assertFalse(thick["ok"])
        self.assertEqual(thick["severity"], "advisory")
        self.assertFalse(result["pass"], "mandatory headwall rule must block")

    def test_box_culvert_reports_control_when_inlet_type_given(self) -> None:
        section = BoxCulvertTests().section(3)
        plain = BC.analyse(section, design_flow_m3s=0.0)
        self.assertIsNone(plain["control"])
        result = BC.analyse(
            section, design_flow_m3s=1.2, slope=0.005,
            inlet_type="wingwall_30_75", tailwater_depth_m=0.5,
            allowable_headwater_m=2.0,
        )
        self.assertIsNotNone(result["control"])
        self.assertEqual(result["control"]["engine"], "culvert_hydraulics")
        items = [c["item"] for c in result["checks"]]
        self.assertTrue(any("最高容許上游水深" in i for i in items))
        self.assertEqual(result["version"], "0.5")


class ChannelProfileTests(unittest.TestCase):
    """標準步法：臨界水深、均勻流不變性、M1 迴水與能量平衡。"""

    def test_critical_depth_closed_form(self) -> None:
        q, b = 0.4, 0.5
        expected = ((q / b) ** 2 / 9.81) ** (1.0 / 3.0)
        got = CP.critical_depth(q, b, 0.0, 1.0)
        self.assertAlmostEqual(got, expected, places=9)

    def test_uniform_flow_stays_at_normal_depth(self) -> None:
        q, b, s0, n = 0.3937, 0.4, 0.005, 0.014
        yn = CP.normal_depth(q, b, 0.0, s0, n, 1.2)
        result = CP.analyse(
            design_flow_m3s=q, bottom_width_m=b, slope=s0, manning_n=n,
            reach_length_m=200.0, step_m=20.0, control_depth_m=yn,
            channel_depth_m=1.2,
        )
        for st in result["stations"]:
            self.assertAlmostEqual(st["depth_m"], yn, places=6)
            self.assertAlmostEqual(st["friction_slope"], s0, places=6)

    def test_m1_backwater_falls_toward_normal_depth(self) -> None:
        q, b, s0, n = 2.0, 2.0, 0.002, 0.025
        m = 1.5
        yn = CP.normal_depth(q, b, m, s0, n, 2.0)
        result = CP.analyse(
            design_flow_m3s=q, bottom_width_m=b, side_slope_h_v=m, slope=s0,
            manning_n=n, reach_length_m=300.0, step_m=30.0,
            control_depth_m=0.9, channel_depth_m=2.0,
        )
        depths = [st["depth_m"] for st in result["stations"]]
        self.assertEqual(result["slope_class"], "緩坡（M）")
        self.assertTrue(all(d["profile"] == "M1" for d in result["stations"]))
        self.assertGreater(depths[0], depths[-1])
        self.assertGreater(depths[-1], yn - 1e-9)
        self.assertLess(depths[-1] - yn, depths[0] - yn)
        # Monotonic decay upstream is what an M1 curve must show.
        for a, b_ in zip(depths, depths[1:]):
            self.assertLessEqual(b_, a + 1e-9)

    def test_energy_balance_closes_between_stations(self) -> None:
        q, b, s0, n = 1.2, 0.8, 0.003, 0.015
        result = CP.analyse(
            design_flow_m3s=q, bottom_width_m=b, slope=s0, manning_n=n,
            reach_length_m=120.0, step_m=15.0, control_depth_m=0.75,
            channel_depth_m=1.5,
        )
        st = result["stations"]
        self.assertGreater(len(st), 4)
        for down, up in zip(st, st[1:]):
            dx = up["chainage_m"] - down["chainage_m"]
            hf = 0.5 * dx * (up["friction_slope"] + down["friction_slope"])
            h_up = up["bed_elevation_m"] + up["specific_energy_m"]
            h_down = down["bed_elevation_m"] + down["specific_energy_m"]
            self.assertAlmostEqual(h_up - h_down, hf, places=6)

    def test_free_outfall_uses_critical_depth(self) -> None:
        result = CP.analyse(
            design_flow_m3s=0.3937, bottom_width_m=0.4, slope=0.005,
            reach_length_m=40.0, step_m=10.0, channel_depth_m=1.2,
        )
        self.assertAlmostEqual(
            result["stations"][0]["depth_m"], result["critical_depth_m"], places=9
        )
        self.assertIn("自由出流", result["control_basis"])

    def test_freeboard_failure_is_reported(self) -> None:
        result = CP.analyse(
            design_flow_m3s=0.3937, bottom_width_m=0.4, slope=0.005,
            reach_length_m=40.0, step_m=10.0, channel_depth_m=0.62,
            freeboard_min_m=0.20,
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["checks"][0]["ok"])


class LoadCombinationTests(unittest.TestCase):
    def test_only_applicable_combinations_are_returned(self) -> None:
        gravity = LC.combinations(["D", "L"])
        self._ids = [c.id for c in gravity]
        self.assertEqual(self._ids, ["U1", "U2"])
        with self.assertRaises(LC.LoadCombinationError):
            LC.combinations([])

    def test_scalar_combination(self) -> None:
        c = next(c for c in LC.combinations(["D", "L"]) if c.id == "U2")
        value = LC.combined_scalar({"D": 100.0, "L": 40.0}, c)
        self.assertAlmostEqual(value, 184.0, places=12)

    def test_envelope_selects_combination(self) -> None:
        env = LC.envelope(
            {"U1": [10.0, -20.0], "U2": [12.0, -14.0], "U3": [-8.0, 18.0]}
        )
        self.assertEqual(env["0"]["combination"], "U2")
        self.assertEqual(env["0"]["value"], 12.0)
        self.assertEqual(env["1"]["combination"], "U3")
        self.assertEqual(env["1"]["value"], 18.0)


class ColumnDesignTests(unittest.TestCase):
    def test_section_axial_capacity_closed_form(self) -> None:
        fc, fy = 28.0, 420.0
        layers = [(796.0, 59.0), (796.0, 341.0)]
        curve = RC.column_interaction_curve(
            400.0,
            400.0,
            layer_areas=layers,
            fc_mpa=fc,
            fy_mpa=fy,
        )
        Ag = 400.0 * 400.0
        As = 1592.0
        P0 = (0.85 * fc * (Ag - As) + fy * As) / 1000.0
        self.assertAlmostEqual(curve["P0_kN"], P0, delta=0.001)
        self.assertAlmostEqual(curve["phiP0_kN"], 0.65 * P0, delta=0.001)

    def test_column_design_enforces_reinforcement_limits(self) -> None:
        result = RC.column_design(1000.0, 120.0, 400.0, 400.0)
        self.assertTrue(result["ok"])
        chosen = result["chosen"]
        self.assertGreaterEqual(chosen["ratio"], 0.01)
        self.assertLessEqual(chosen["ratio"], 0.08)
        self.assertGreaterEqual(
            chosen["phiMn_available_kNm"], 120.0
        )

    def test_column_axial_capacity_exceeded_is_rejected(self) -> None:
        result = RC.column_interaction_capacity(
            5000.0,
            400.0,
            400.0,
            layer_areas=[(796.0, 59.0), (796.0, 341.0)],
            fc_mpa=28.0,
            fy_mpa=420.0,
        )
        self.assertFalse(result["ok"])
        self.assertIn("軸力", result["reason"])


class BeamDesignTests(unittest.TestCase):
    def test_stirrup_design_satisfies_equilibrium_and_spacing(self) -> None:
        result = RC.beam_shear_design(
            400.0,
            b_mm=350.0,
            h_mm=750.0,
            main_bar="D16",
        )
        self.assertTrue(result["ok"])
        stirrup = result["stirrup"]
        self.assertIsNotNone(stirrup["spacing_mm"])
        av = result["Av_mm2"]
        d = result["d_mm"]
        vs = av * result["fyt_mpa"] * d / stirrup["spacing_mm"] / 1000.0
        self.assertAlmostEqual(result["Vs_prov_kN"], vs, delta=0.2)
        self.assertAlmostEqual(
            result["phiVn_kN"],
            result["phi_shear"] * (result["Vc_kN"] + result["Vs_prov_kN"]),
            delta=0.2,
        )
        self.assertLessEqual(
            stirrup["spacing_mm"], result["max_spacing_mm"] + 1e-9
        )
        self.assertTrue(result["minimum_ok"])
        self.assertTrue(result["section_ok"])

    def test_beam_design_combines_flexure_shear_and_crack(self) -> None:
        result = RC.beam_design(180.0, 120.0, b_mm=300.0, h_mm=600.0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["flexure"]["ok"])
        self.assertTrue(result["shear"]["ok"])
        self.assertTrue(result["crack"]["ok"])
        self.assertIn("bar", result["shear"]["stirrup"])
        self.assertGreaterEqual(result["flexure"]["As_prov_mm2"], result["flexure"]["As_req_mm2"])

    def test_shear_section_limit_is_enforced(self) -> None:
        result = RC.beam_shear_design(
            1200.0,
            b_mm=350.0,
            h_mm=750.0,
            main_bar="D16",
        )
        self.assertFalse(result["ok"])
        self.assertIn("斷面不足", result.get("error", ""))


class BuildingFrameTests(unittest.TestCase):
    def geometry(self) -> BF.BuildingGeometry:
        return BF.BuildingGeometry.from_mapping(
            {
                "x_grid_m": [0.0, 6.0],
                "storey_heights_m": [3.5],
                "beam_width_mm": 300.0,
                "beam_depth_mm": 600.0,
                "column_width_mm": 400.0,
                "column_depth_mm": 400.0,
            }
        )

    def test_generated_topology(self) -> None:
        built = BF.generate_frame(self.geometry(), BF.BuildingLoads())
        self.assertEqual(len(built["nodes"]), 4)
        self.assertEqual(len(built["members"]), 3)
        self.assertEqual(len([m for m in built["members"] if m["kind"] == "beam"]), 1)
        self.assertEqual(len([m for m in built["members"] if m["kind"] == "column"]), 2)

    def test_dead_load_reaction_equilibrium(self) -> None:
        geometry = self.geometry()
        loads = BF.BuildingLoads(dead_area_kn_m2=5.0, live_area_kn_m2=2.0)
        built = BF.generate_frame(geometry, loads)
        nodes, members = BF._compose_case(
            built["nodes"],
            built["members"],
            built["nodal_load_cases"],
            built["member_load_cases"],
            {"D": 1.0},
        )
        result = FA.FrameModel(nodes, members).solve()
        reaction_y = sum(r[1] for r in result.reactions.values())
        expected = (
            built["beam_dead_line_load_kn_m"] * geometry.plan_width_m
            + 2.0
            * (
                24.0
                * 0.4
                * 0.4
                * geometry.storey_heights_m[0]
            )
        )
        self.assertAlmostEqual(reaction_y, expected, places=7)

    def test_complete_lateral_analysis_returns_envelopes(self) -> None:
        result = BF.analyse(
            {
                "x_grid_m": [0.0, 6.0],
                "storey_heights_m": [3.5, 3.5],
                "beam_depth_mm": 650.0,
                "column_width_mm": 450.0,
                "column_depth_mm": 450.0,
            },
            {
                "dead_area_kn_m2": 5.0,
                "live_area_kn_m2": 2.0,
                "base_shear_coefficient": 0.12,
            },
        )
        ids = {c["id"] for c in result["combinations"]}
        self.assertIn("U3", ids)
        self.assertIn("S1", ids)
        self.assertEqual(len(result["designs"]), 6)
        self.assertTrue(result["drift"])
        self.assertIsInstance(result["pass"], bool)
        beam_checks = [
            c for c in result["checks"] if "梁剪力（含箍筋）" in c["item"]
        ]
        self.assertTrue(beam_checks)
        self.assertTrue(all(c["limit"] is not None for c in beam_checks))


class FoundationTests(unittest.TestCase):
    def test_uniform_pressure_closed_form(self) -> None:
        p = FD.pressure_distribution(1000.0, 0.0, 0.0, 2.0, 2.0)
        self.assertAlmostEqual(p["q_average_kpa"], 250.0, places=12)
        self.assertAlmostEqual(p["q_max_kpa"], 250.0, places=12)
        self.assertAlmostEqual(p["q_min_kpa"], 250.0, places=12)
        self.assertTrue(p["contact_full"])

    def test_combined_footing_eccentricity_acts_along_length(self) -> None:
        # L < B 時舊寫法用 Sy 會低估：手算 M=200、Sx=4×3²/6=6、q=100±33.33 kPa
        result = FD.analyse_combined_footing(
            [{"x_m": 0.5, "P_kN": 500.0}, {"x_m": 2.5, "P_kN": 700.0}],
            B_m=4.0,
            L_m=3.0,
            thickness_m=0.7,
        )
        self.assertAlmostEqual(result["pressure"]["q_max_kpa"], 400.0 / 3.0, places=9)
        self.assertAlmostEqual(result["pressure"]["q_min_kpa"], 200.0 / 3.0, places=9)
        self.assertAlmostEqual(
            result["pressure"]["q_max_kpa"], result["internal"]["q_right_kpa"], places=2
        )

    def test_layered_settlement_matches_square_closed_form(self) -> None:
        result = FD.settlement_by_layers(
            100.0,
            2.0,
            2.0,
            [{"thickness_m": 4.0, "constrained_modulus_kpa": 10000.0}],
            subdivisions=1000,
        )
        # Integral q B H / (M (B + H)) for a square 2:1 stress spread.
        expected_mm = (
            100.0 * 2.0 * 4.0 / (10000.0 * (2.0 + 4.0)) * 1000.0
        )
        self.assertAlmostEqual(
            result["total_settlement_mm"], expected_mm, delta=0.002
        )
        self.assertEqual(result["allowable_total_mm"], 100.0)
        self.assertTrue(result["ok"])

    def test_isotropic_modulus_converts_to_constrained_modulus(self) -> None:
        E = 15000.0
        nu = 0.30
        expected = E * (1.0 - nu) / ((1.0 + nu) * (1.0 - 2.0 * nu))
        self.assertAlmostEqual(
            FD.constrained_modulus_from_elastic(E, nu), expected, places=9
        )
        with self.assertRaises(FD.FoundationError):
            FD.constrained_modulus_from_elastic(E, 0.50)

    def test_isolated_footing_checks_are_complete(self) -> None:
        r = FD.analyse_isolated_footing(
            {"P_kN": 1000.0, "Mx_kNm": 100.0, "My_kNm": 50.0},
            B_m=2.5,
            L_m=2.5,
            thickness_m=0.6,
            column_b_m=0.45,
            column_l_m=0.45,
            q_allow_kpa=300.0,
        )
        labels = {c["item"] for c in r["checks"]}
        self.assertIn("沖剪", labels)
        self.assertIn("單向剪力", labels)
        self.assertIn("基腳撓曲", labels)

    def test_isolated_footing_with_settlement_adds_gate(self) -> None:
        r = FD.analyse_isolated_footing(
            {"P_kN": 1000.0},
            B_m=2.5,
            L_m=2.5,
            thickness_m=0.6,
            column_b_m=0.45,
            column_l_m=0.45,
            q_allow_kpa=300.0,
            settlement={
                "foundation_type": "rc_isolated_or_combined",
                "layers": [
                    {
                        "thickness_m": 2.0,
                        "elastic_modulus_kpa": 12000.0,
                        "poisson_ratio": 0.30,
                    },
                    {
                        "thickness_m": 4.0,
                        "constrained_modulus_kpa": 18000.0,
                    },
                ],
            },
        )
        labels = {c["item"] for c in r["checks"]}
        self.assertIn("總沉陷量（分層 2:1 法）", labels)
        self.assertEqual(len(r["settlement"]["layers"]), 2)
        self.assertTrue(r["settlement"]["ok"])

    def test_isolated_footing_combines_consolidation_with_immediate(self) -> None:
        r = FD.analyse_isolated_footing(
            {"P_kN": 1000.0},
            B_m=2.5,
            L_m=2.5,
            thickness_m=0.6,
            column_b_m=0.45,
            column_l_m=0.45,
            q_allow_kpa=300.0,
            settlement={
                "foundation_type": "rc_isolated_or_combined",
                "layers": [
                    {
                        "thickness_m": 2.0,
                        "constrained_modulus_kpa": 15000.0,
                    }
                ],
                "consolidation_layers": [
                    {
                        "thickness_m": 3.0,
                        "initial_effective_stress_kpa": 80.0,
                        "compression_index": 0.24,
                        "recompression_index": 0.05,
                        "preconsolidation_stress_kpa": 140.0,
                        "void_ratio": 0.90,
                    }
                ],
            },
        )
        settlement = r["settlement"]
        self.assertGreater(settlement["immediate_settlement_mm"], 0.0)
        self.assertGreater(settlement["primary_consolidation_mm"], 0.0)
        self.assertAlmostEqual(
            settlement["total_settlement_mm"],
            settlement["immediate_settlement_mm"]
            + settlement["primary_consolidation_mm"]
            + settlement["secondary_compression_mm"],
            places=4,
        )

    def test_normal_consolidation_closed_form(self) -> None:
        result = FD.consolidation_by_layers(
            100.0,
            2.0,
            2.0,
            [
                {
                    "thickness_m": 4.0,
                    "initial_effective_stress_kpa": 50.0,
                    "compression_index": 0.30,
                    "void_ratio": 0.90,
                }
            ],
        )
        expected_mm = (
            0.30 * 4.0 / 1.90 * math.log10(75.0 / 50.0) * 1000.0
        )
        self.assertAlmostEqual(
            result["primary_consolidation_mm"], expected_mm, delta=0.002
        )
        self.assertEqual(
            result["layers"][0]["consolidation_state"],
            "normally_consolidated",
        )

    def test_overconsolidated_below_preconsolidation_stress(self) -> None:
        result = FD.consolidation_by_layers(
            100.0,
            2.0,
            2.0,
            [
                {
                    "thickness_m": 4.0,
                    "initial_effective_stress_kpa": 50.0,
                    "compression_index": 0.30,
                    "recompression_index": 0.06,
                    "preconsolidation_stress_kpa": 100.0,
                    "void_ratio": 0.90,
                }
            ],
        )
        expected_mm = (
            0.06 * 4.0 / 1.90 * math.log10(75.0 / 50.0) * 1000.0
        )
        self.assertAlmostEqual(
            result["primary_consolidation_mm"], expected_mm, delta=0.002
        )

    def test_overconsolidated_crossing_preconsolidation_stress(self) -> None:
        result = FD.consolidation_by_layers(
            100.0,
            2.0,
            2.0,
            [
                {
                    "thickness_m": 4.0,
                    "initial_effective_stress_kpa": 50.0,
                    "compression_index": 0.30,
                    "recompression_index": 0.06,
                    "preconsolidation_stress_kpa": 60.0,
                    "void_ratio": 0.90,
                }
            ],
        )
        expected_mm = (
            0.06 * 4.0 / 1.90 * math.log10(60.0 / 50.0)
            + 0.30 * 4.0 / 1.90 * math.log10(75.0 / 60.0)
        ) * 1000.0
        self.assertAlmostEqual(
            result["primary_consolidation_mm"], expected_mm, delta=0.002
        )

    def test_underconsolidated_layer_is_rejected(self) -> None:
        with self.assertRaises(FD.FoundationError):
            FD.consolidation_by_layers(
                100.0,
                2.0,
                2.0,
                [
                    {
                        "thickness_m": 4.0,
                        "initial_effective_stress_kpa": 50.0,
                        "compression_index": 0.30,
                        "preconsolidation_stress_kpa": 40.0,
                        "void_ratio": 0.90,
                    }
                ],
            )

    def test_secondary_compression_closed_form(self) -> None:
        result = FD.consolidation_by_layers(
            100.0,
            2.0,
            2.0,
            [
                {
                    "thickness_m": 4.0,
                    "initial_effective_stress_kpa": 50.0,
                    "compression_index": 0.30,
                    "void_ratio": 0.90,
                    "secondary_compression_index": 0.005,
                    "consolidation_start_year": 1.0,
                    "assessment_end_year": 30.0,
                }
            ],
        )
        expected_mm = 0.005 * 4.0 * math.log10(30.0) * 1000.0
        self.assertAlmostEqual(
            result["secondary_compression_mm"], expected_mm, delta=0.002
        )

    def test_angular_distortion_deducts_rigid_body_plane(self) -> None:
        result = FD.angular_distortion(
            [
                {"id": "A", "x_m": 0.0, "y_m": 0.0, "settlement_mm": 10.0},
                {"id": "B", "x_m": 6.0, "y_m": 0.0, "settlement_mm": 12.0},
                {"id": "C", "x_m": 0.0, "y_m": 6.0, "settlement_mm": 13.0},
                {"id": "D", "x_m": 6.0, "y_m": 6.0, "settlement_mm": 15.0},
            ],
            limit=1.0 / 500.0,
        )
        self.assertEqual(result["rigid_body_model"], "plane")
        self.assertTrue(result["evaluated"])
        self.assertAlmostEqual(result["max_angular_distortion"], 0.0, places=10)
        self.assertTrue(result["ok"])

    def test_angular_distortion_rejects_non_planar_excess(self) -> None:
        result = FD.angular_distortion(
            [
                {"id": "A", "x_m": 0.0, "y_m": 0.0, "settlement_mm": 10.0},
                {"id": "B", "x_m": 6.0, "y_m": 0.0, "settlement_mm": 12.0},
                {"id": "C", "x_m": 0.0, "y_m": 6.0, "settlement_mm": 13.0},
                {"id": "D", "x_m": 6.0, "y_m": 6.0, "settlement_mm": 40.0},
            ],
            limit=1.0 / 500.0,
        )
        self.assertTrue(result["evaluated"])
        self.assertGreater(result["max_angular_distortion"], 1.0 / 500.0)
        self.assertFalse(result["ok"])

    def test_two_points_cannot_separate_rigid_rotation(self) -> None:
        result = FD.angular_distortion(
            [
                {"id": "A", "x_m": 0.0, "y_m": 0.0, "settlement_mm": 10.0},
                {"id": "B", "x_m": 6.0, "y_m": 0.0, "settlement_mm": 16.0},
            ]
        )
        self.assertFalse(result["evaluated"])
        self.assertFalse(result["ok"])
        self.assertIsNone(result["max_angular_distortion"])
        self.assertAlmostEqual(
            result["pairs"][0]["difference_over_distance"],
            0.001,
            places=12,
        )

    def test_settlement_assessment_combines_all_components(self) -> None:
        layer = [
            {
                "thickness_m": 2.0,
                "constrained_modulus_kpa": 15000.0,
            }
        ]
        consolidation = [
            {
                "thickness_m": 3.0,
                "initial_effective_stress_kpa": 80.0,
                "compression_index": 0.24,
                "recompression_index": 0.05,
                "preconsolidation_stress_kpa": 140.0,
                "void_ratio": 0.90,
                "secondary_compression_index": 0.002,
                "consolidation_start_year": 1.0,
                "assessment_end_year": 30.0,
            }
        ]
        result = FD.settlement_assessment(
            {
                "footings": [
                    {
                        "id": "F1",
                        "x_m": 0.0,
                        "y_m": 0.0,
                        "q_kpa": 100.0,
                        "B_m": 2.0,
                        "L_m": 2.0,
                        "immediate_layers": layer,
                        "consolidation_layers": consolidation,
                    },
                    {
                        "id": "F2",
                        "x_m": 5.0,
                        "y_m": 0.0,
                        "q_kpa": 100.0,
                        "B_m": 2.0,
                        "L_m": 2.0,
                        "immediate_layers": layer,
                        "consolidation_layers": consolidation,
                    },
                    {
                        "id": "F3",
                        "x_m": 0.0,
                        "y_m": 5.0,
                        "q_kpa": 100.0,
                        "B_m": 2.0,
                        "L_m": 2.0,
                        "immediate_layers": layer,
                        "consolidation_layers": consolidation,
                    },
                ]
            }
        )
        row = result["footings"][0]
        self.assertGreater(row["immediate_settlement_mm"], 0.0)
        self.assertGreater(row["primary_consolidation_mm"], 0.0)
        self.assertGreater(row["secondary_compression_mm"], 0.0)
        self.assertAlmostEqual(
            row["total_settlement_mm"],
            row["immediate_settlement_mm"]
            + row["primary_consolidation_mm"]
            + row["secondary_compression_mm"],
            places=4,
        )
        self.assertTrue(result["pass"])

    def test_pile_group_symmetric(self) -> None:
        piles = [
            {"x_m": -1.0, "y_m": -1.0},
            {"x_m": 1.0, "y_m": -1.0},
            {"x_m": -1.0, "y_m": 1.0},
            {"x_m": 1.0, "y_m": 1.0},
        ]
        r = FD.pile_group_check(piles, P_kN=2000.0, Q_allow_kN=600.0)
        self.assertAlmostEqual(r["max_pile_load_kN"], 500.0, places=6)
        self.assertAlmostEqual(r["min_pile_load_kN"], 500.0, places=6)
        self.assertTrue(r["pass"])


class DetentionBasinTests(unittest.TestCase):
    @staticmethod
    def _orifice_rate(stage_m: float, **orifice: float) -> float:
        return DB._outlet_rate(stage_m, (), {"orifice": {"diameter_m": 0.2, **orifice}})

    def test_orifice_invert_adds_half_diameter_to_center(self) -> None:
        area = math.pi * 0.2**2 / 4.0
        self.assertAlmostEqual(
            self._orifice_rate(1.1, invert_m=0.0, discharge_coefficient=0.5),
            0.5 * area * math.sqrt(2.0 * 9.81 * 1.0),
            places=12,
        )

    def test_orifice_canonical_and_alias_fields_agree(self) -> None:
        self.assertAlmostEqual(
            self._orifice_rate(1.0, center_m=0.1, Cd=0.7),
            self._orifice_rate(1.0, invert_m=0.0, discharge_coefficient=0.7),
            places=12,
        )

    def test_orifice_duplicate_fields_are_rejected(self) -> None:
        with self.assertRaises(DB.DetentionBasinError):
            self._orifice_rate(1.0, center_m=0.1, invert_m=0.0)
        with self.assertRaises(DB.DetentionBasinError):
            self._orifice_rate(1.0, Cd=0.6, discharge_coefficient=0.7)

    def test_vertical_side_storage(self) -> None:
        table = DB.stage_storage_from_area([0.0, 10.0], [100.0, 100.0])
        self.assertAlmostEqual(table[-1]["storage_m3"], 1000.0, places=12)

    def test_sloping_basin_storage_integral(self) -> None:
        table = DB.trapezoidal_basin_table(
            bottom_length_m=10.0,
            bottom_width_m=10.0,
            side_slope_h_v=2.0,
            max_stage_m=1.0,
            step_m=0.5,
        )
        # V = B L y + (B+L) z y^2 + (4/3) z^2 y^3
        expected = 100.0 * 1.0 + 2.0 * 20.0 * 1.0**2 + (4.0 / 3.0) * 4.0
        self.assertAlmostEqual(table[-1]["storage_m3"], expected, places=9)

    def test_orifice_and_weir_closed_form(self) -> None:
        area = math.pi * 0.2**2 / 4.0
        q_orifice = DB.orifice_flow(1.0, area_m2=area, discharge_coefficient=0.62)
        self.assertAlmostEqual(
            q_orifice, 0.62 * area * math.sqrt(2.0 * 9.81), places=12
        )
        q_weir = DB.weir_flow(0.5, length_m=3.0, coefficient=1.84)
        self.assertAlmostEqual(q_weir, 1.84 * 3.0 * 0.5**1.5, places=12)

    def test_modified_puls_mass_balance_without_outlet(self) -> None:
        result = DB.analyse(
            {
                "basin": {
                    "stage_area_table": [
                        {"stage_m": 0.0, "area_m2": 100.0},
                        {"stage_m": 10.0, "area_m2": 100.0},
                    ],
                    "dam_crest_m": 10.0,
                    "freeboard_min_m": 1.0,
                },
                "outlet": {},
                "inflow": {
                    "peak_m3s": 1.0,
                    "time_to_peak_min": 5.0,
                    "duration_min": 10.0,
                    "time_step_min": 1.0,
                },
                "allowable_outflow_m3s": 1.0,
            }
        )
        # No outlet: stored volume equals integrated triangular inflow.
        self.assertAlmostEqual(result["inflow_volume_m3"], 300.0, places=6)
        self.assertAlmostEqual(result["max_storage_m3"], 300.0, places=6)
        self.assertAlmostEqual(result["max_stage_m"], 3.0, places=6)
        self.assertAlmostEqual(result["peak_outflow_m3s"], 0.0, places=9)

    def test_routing_above_stage_table_is_rejected(self) -> None:
        with self.assertRaises(DB.DetentionBasinError):
            DB.analyse(
                {
                    "basin": {
                        "stage_area_table": [
                            {"stage_m": 0.0, "area_m2": 100.0},
                            {"stage_m": 0.1, "area_m2": 100.0},
                        ]
                    },
                    "outlet": {},
                    "inflow": {
                        "peak_m3s": 5.0,
                        "time_to_peak_min": 1.0,
                        "duration_min": 2.0,
                        "time_step_min": 0.5,
                    },
                }
            )


class DrainageNetworkTests(unittest.TestCase):
    def test_single_link_and_flow_balance(self) -> None:
        result = DN.analyse(
            {
                "nodes": [
                    {"id": "A", "inflow_m3s": 1.0},
                    {"id": "B"},
                ],
                "links": [
                    {
                        "id": "L1",
                        "from": "A",
                        "to": "B",
                        "type": "fixed",
                        "capacity_m3s": 2.0,
                    }
                ],
            }
        )
        self.assertAlmostEqual(result["links"][0]["flow_m3s"], 1.0, places=6)
        self.assertAlmostEqual(result["terminal_outflow_m3s"], 1.0, places=6)
        self.assertAlmostEqual(result["flow_balance_error_m3s"], 0.0, places=9)
        self.assertTrue(result["pass"])

    def test_specified_branch_split(self) -> None:
        result = DN.analyse(
            {
                "nodes": [
                    {"id": "A", "inflow_m3s": 5.0},
                    {"id": "B"},
                    {"id": "C"},
                ],
                "links": [
                    {
                        "id": "AB",
                        "from": "A",
                        "to": "B",
                        "type": "fixed",
                        "capacity_m3s": 10.0,
                        "split_fraction": 0.4,
                    },
                    {
                        "id": "AC",
                        "from": "A",
                        "to": "C",
                        "type": "fixed",
                        "capacity_m3s": 10.0,
                        "split_fraction": 0.6,
                    },
                ],
            }
        )
        flows = {row["id"]: row["flow_m3s"] for row in result["links"]}
        self.assertAlmostEqual(flows["AB"], 2.0, places=6)
        self.assertAlmostEqual(flows["AC"], 3.0, places=6)
        self.assertAlmostEqual(result["flow_balance_error_m3s"], 0.0, places=9)

    def test_capacity_weighted_branch_split(self) -> None:
        result = DN.analyse(
            {
                "nodes": [
                    {"id": "A", "inflow_m3s": 5.0},
                    {"id": "B"},
                    {"id": "C"},
                ],
                "links": [
                    {
                        "id": "AB",
                        "from": "A",
                        "to": "B",
                        "type": "fixed",
                        "capacity_m3s": 2.0,
                    },
                    {
                        "id": "AC",
                        "from": "A",
                        "to": "C",
                        "type": "fixed",
                        "capacity_m3s": 8.0,
                    },
                ],
            }
        )
        flows = {row["id"]: row["flow_m3s"] for row in result["links"]}
        self.assertAlmostEqual(flows["AB"], 1.0, places=6)
        self.assertAlmostEqual(flows["AC"], 4.0, places=6)

    def test_cycle_is_rejected(self) -> None:
        with self.assertRaises(DN.DrainageNetworkError):
            DN.analyse(
                {
                    "nodes": [{"id": "A"}, {"id": "B"}],
                    "links": [
                        {
                            "id": "AB",
                            "from": "A",
                            "to": "B",
                            "type": "fixed",
                            "capacity_m3s": 1.0,
                        },
                        {
                            "id": "BA",
                            "from": "B",
                            "to": "A",
                            "type": "fixed",
                            "capacity_m3s": 1.0,
                        },
                    ],
                }
            )

    def test_capacity_failure_is_reported(self) -> None:
        result = DN.analyse(
            {
                "nodes": [
                    {"id": "A", "inflow_m3s": 1.0},
                    {"id": "B"},
                ],
                "links": [
                    {
                        "id": "L1",
                        "from": "A",
                        "to": "B",
                        "type": "fixed",
                        "capacity_m3s": 0.5,
                    }
                ],
            }
        )
        self.assertFalse(result["links"][0]["ok"])
        self.assertFalse(result["pass"])


class WallCasePipelineTests(unittest.TestCase):
    """案件端到端：數量、預算、報告必須共用同一份牆型分流配筋量。"""

    def _case(self, values):
        return {
            "schema": "civil-case/1",
            "project": {"name": "測試案", "category": "擋土牆"},
            "quantities": {"model": "wall", "values": values},
        }

    def test_semigravity_quantity_uses_nominal_steel(self) -> None:
        case = self._case({
            "wall_type": "semigravity",
            "length_m": 20.0,
            "height_m": 4.0,
            "stem_thickness_m": 0.35,
            "top_width_m": 0.35,
            "front_batter_ratio": 0.30,
            "back_batter_ratio": 0.0,
            "base_width_m": 2.60,
            "base_thickness_m": 0.60,
            "toe_projection_m": 0.50,
            "toe_soil_depth_m": 1.50,
            "weep_diameter_m": 0.05,
            "backfill_thickness_m": 0.30,
            "excavation_work_m": 0.30,
            "excavation_depth_m": 0.10,
        })
        model, q, issues = CASE.quantity_context(case)
        self.assertEqual(model, "wall")
        self.assertFalse([i for i in issues if i["level"] == "error"])
        self.assertAlmostEqual(q["rebar_kg_per_m_design"], 58.48, delta=0.05)
        self.assertAlmostEqual(q["rebar_kg_design"], 1169.5, delta=1.0)

        sections = CASE._design_sections("wall", q, case)
        notes = "".join(sections["comparison"]["notes"])
        self.assertIn("半重力式", notes)
        self.assertNotIn("懸臂式（薄牆", notes)
        self.assertIn("已含 12% 搭接損耗", "".join(
            sections["reinforcement"]["notes"]))

    def test_unknown_wall_type_does_not_fall_back_to_cantilever(self) -> None:
        case = self._case({
            "wall_type": "buttress_unknown",
            "length_m": 20.0,
            "height_m": 8.0,
            "stem_thickness_m": 0.30,
            "base_width_m": 6.60,
            "base_thickness_m": 0.60,
        })
        _model, _q, issues = CASE.quantity_context(case)
        errors = [i["msg"] for i in issues if i["level"] == "error"]
        self.assertTrue(errors)
        self.assertIn("尚未支援", "".join(errors))
        self.assertNotIn("rebar_kg_design", _q)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)

