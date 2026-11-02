r"""Integration tests for the civil-design JSON API and web workbench.

Run:
    C:\Python312\python.exe -E -P -X utf8 tools\selftest\design_workbench_selftest.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "regs"))
sys.path.insert(0, str(ROOT / "tools" / "design"))

import design_api as API  # noqa: E402
import regs_server  # noqa: E402


# 列舉型參數一律要用下拉選單；自由文字只限識別碼、節點名稱與逗號分隔的清單。
# design_launch_check.py 會匯入同一份白名單，避免兩處守門各自漂移。
FREE_TEXT_FIELDS: dict[str, set[str]] = {
    "anchored_wall": {"anchor_depths_m"},
    "drainage_network": {"nodes[].id", "links[].id", "links[].from", "links[].to"},
    "settlement_assessment": {"footings[].id"},
    "building_frame": {"geometry.x_grid_m", "geometry.storey_heights_m"},
}


class Checks:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, condition: bool) -> None:
        print(("ok   " if condition else "FAIL ") + name)
        if not condition:
            self.failures += 1


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    checks = Checks()
    calculators = API.list_calculators()
    checks.check(
        "catalog has >= 17 calculators and every id is wired",
        len(calculators) >= 17
        and {row["id"] for row in calculators} == set(API.RUNNERS),
    )
    checks.check(
        "catalog ids are unique",
        len({row["id"] for row in calculators}) == len(calculators),
    )
    wall = next((row for row in calculators if row["id"] == "wall_stability"), None)
    wall_rules = (wall or {}).get("field_rules") or {}
    wall_type_rule = wall_rules.get("wall_type") or {}
    height_rule = wall_rules.get("height_m") or {}
    choice_rows = wall_type_rule.get("choices", [])
    choices = {choice.get("value") for choice in choice_rows}
    choice_defaults = {
        choice.get("value"): choice.get("defaults") or {} for choice in choice_rows
    }
    limits = height_rule.get("limits") or {}
    checks.check(
        "wall type is a select field",
        wall_type_rule.get("type") == "select"
        and choices == {"gravity", "semigravity", "cantilever"},
    )
    checks.check(
        "wall height max follows wall type",
        height_rule.get("max_by") == "wall_type"
        and limits.get("gravity", {}).get("max") == 4.0
        and limits.get("semigravity", {}).get("max") == 4.0
        and limits.get("cantilever", {}).get("max") == 8.0
        and limits.get("semigravity", {}).get("input_offset_by")
        == "base_thickness_m"
        and choice_defaults.get("semigravity", {}).get("top_width_m") == 0.30
        and choice_defaults.get("semigravity", {}).get("base_thickness_m") == 0.80,
    )
    settlement = next(
        (row for row in calculators if row["id"] == "settlement_assessment"),
        None,
    )
    block = next((row for row in calculators if row["id"] == "block_wall"), None)
    block_rules = (block or {}).get("field_rules") or {}
    block_choices = {
        c.get("value") for c in (block_rules.get("wall_type") or {}).get("choices", [])
    }
    block_height = (block_rules.get("height_m") or {}).get("limits") or {}
    block_course = (block_rules.get("course_height_m") or {}).get("limits") or {}
    checks.check(
        "block wall exposes gabion/crib/masonry select and section 118 limits",
        block_choices == {"gabion", "crib", "masonry_wet", "masonry_dry", "sandwich"}
        and block_height.get("masonry_wet", {}).get("max") == 4.0
        and (block_height.get("sandwich", {}).get("limits") or {}).get("fill", {}).get("max") == 2.0
        and (block_height.get("sandwich", {}).get("limits") or {}).get("cut", {}).get("max") == 4.0
        and (block_rules.get("site_condition") or {}).get("type") == "select"
        and block_height.get("masonry_dry", {}).get("input_offset_by") == "embedment_m"
        and block_course.get("crib", {}).get("max") == 3.0,
    )
    counterfort = next((row for row in calculators if row["id"] == "counterfort_wall"), None)
    cf_height = ((counterfort or {}).get("field_rules") or {}).get("height_m") or {}
    checks.check(
        "counterfort wall height limit is 10 m effective (minus front soil)",
        (cf_height.get("limit") or {}).get("max") == 10.0
        and (cf_height.get("limit") or {}).get("input_offset_by") == "front_soil_depth_m",
    )
    cf_size = dict((counterfort or {}).get("example") or {}, size=True, height_m=6.0, kh=0.0)
    cf_sized = API.run_calculation("counterfort_wall", cf_size, persist=False)
    checks.check(
        "counterfort wall sizing returns a passing section",
        cf_sized.get("ok") is True
        and (cf_sized.get("result") or {}).get("sized_section", {}).get("height_m") == 6.0,
    )
    cf_over = dict((counterfort or {}).get("example") or {}, height_m=11.5, front_soil_depth_m=1.0)
    cf_over_result = API.run_calculation("counterfort_wall", cf_over, persist=False)
    checks.check(
        "counterfort wall over 10 m effective height is rejected",
        cf_over_result.get("ok") is False and "10.0 m" in str(cf_over_result.get("error")),
    )
    mse = next((row for row in calculators if row["id"] == "mse_wall"), None)
    mse_height = ((mse or {}).get("field_rules") or {}).get("height_m") or {}
    checks.check(
        "mse wall height limit is 8 m effective (minus embedment)",
        (mse_height.get("limit") or {}).get("max") == 8.0
        and (mse_height.get("limit") or {}).get("input_offset_by") == "embedment_m",
    )
    mse_result = API.run_calculation("mse_wall", (mse or {}).get("example") or {}, persist=False)
    checks.check("mse wall example runs", mse_result.get("ok") is True)
    sw = dict((block or {}).get("example") or {})
    for key in API._BLOCK_WALL_SECTION_KEYS + ["embedment_m"]:
        sw.pop(key, None)
    sw.update(API._block_wall_defaults()["sandwich"], wall_type="sandwich", site_condition="fill", height_m=2.8)
    sw_over = API.run_calculation("block_wall", sw, persist=False)
    checks.check(
        "sandwich wall on fill slope over 2 m effective height is rejected",
        sw_over.get("ok") is False and "2.0 m" in str(sw_over.get("error")),
    )
    anchored = next((row for row in calculators if row["id"] == "anchored_wall"), None)
    aw_rules = (anchored or {}).get("field_rules") or {}
    checks.check(
        "anchored wall exposes service/strand selects and bond presets",
        (aw_rules.get("service") or {}).get("type") == "select"
        and (aw_rules.get("strand_type") or {}).get("type") == "select"
        and (aw_rules.get("bond_strength_kpa") or {}).get("type") == "number_with_presets",
    )
    aw_result = API.run_calculation("anchored_wall", (anchored or {}).get("example") or {}, persist=False)
    checks.check("anchored wall example runs and passes", aw_result.get("ok") is True)
    checks.check(
        "settlement assessment exposes foundation and angular rules",
        settlement is not None
        and (settlement.get("field_rules") or {})
        .get("default_foundation_type", {})
        .get("type")
        == "select"
        and (settlement.get("field_rules") or {})
        .get("angular_distortion_limit", {})
        .get("type")
        == "number",
    )
    channel = next(
        (row for row in calculators if row["id"] == "channel_hydraulics"),
        None,
    )
    manning_rule = ((channel or {}).get("field_rules") or {}).get("manning_n") or {}
    preset_values = {
        float(row.get("value"))
        for row in manning_rule.get("choices", [])
        if row.get("value") not in (None, "")
    }
    checks.check(
        "manning n exposes material presets and manual input",
        manning_rule.get("type") == "number_with_presets"
        and {0.014, 0.025, 0.035}.issubset(preset_values),
    )
    culvert = next(
        (row for row in calculators if row["id"] == "box_culvert"), None
    )
    inlet_rule = ((culvert or {}).get("field_rules") or {}).get("inlet_type") or {}
    checks.check(
        "box culvert exposes inlet-type select",
        inlet_rule.get("type") == "select"
        and {row.get("value") for row in inlet_rule.get("choices", [])}
        >= {"wingwall_30_75", "wingwall_90_15", "wingwall_0"},
    )
    culvert_result = API.run_calculation(
        "box_culvert",
        culvert["example"],
        persist=False,
    )
    checks.check(
        "box culvert example returns inlet/outlet control",
        (culvert_result.get("result") or {}).get("control", {}).get("engine")
        == "culvert_hydraulics"
        and any("最高容許上游水深" in c.get("item", "")
                for c in culvert_result.get("checks", [])),
    )
    steel = next((row for row in calculators if row["id"] == "steel_column"), None)
    checks.check(
        "steel column is listed on the workbench catalog",
        steel is not None
        and steel.get("group") == "鋼結構"
        and steel.get("engine") == "steel_column.py"
        and "steel_column" in API.RUNNERS,
    )
    steel_rules = (steel or {}).get("field_rules") or {}
    checks.check(
        "steel column exposes method/support/grade/shear-path selects",
        (steel_rules.get("design_method") or {}).get("type") == "select"
        and {c.get("value") for c in (steel_rules.get("design_method") or {}).get("choices", [])}
        == {"lrfd", "asd"}
        and (steel_rules.get("base_plate.support_condition") or {}).get("type") == "select"
        and (steel_rules.get("anchors.grade") or {}).get("type") == "select"
        and (steel_rules.get("anchors.shear_path") or {}).get("type") == "select",
    )
    steel_result = API.run_calculation("steel_column", (steel or {}).get("example") or {}, persist=False)
    checks.check(
        "steel column example runs and passes with 14 checks",
        steel_result.get("ok") is True
        and len(steel_result.get("checks", [])) == 14
        and "鋼構柱" in str(steel_result.get("summary", "")),
    )
    steel_asd = dict((steel or {}).get("example") or {})
    steel_asd["design_method"] = "asd"
    steel_asd_result = API.run_calculation("steel_column", steel_asd, persist=False)
    checks.check(
        "steel column switches to ASD without losing the calculation",
        steel_asd_result.get("ok") is True
        and len(steel_asd_result.get("checks", [])) == 14,
    )

    def _walk_example(node, prefix=""):
        rows = []
        if isinstance(node, dict):
            for key, value in node.items():
                rows += _walk_example(value, prefix + "." + key if prefix else key)
        elif isinstance(node, list):
            for value in node:
                rows += _walk_example(value, prefix + "[]")
        else:
            rows.append((prefix, node))
        return rows

    def _rule_for(rules, path):
        if path in rules:
            return rules[path]
        return rules.get(path.split(".")[-1])

    uncovered = []
    for row in calculators:
        rules = row.get("field_rules") or {}
        allowed = FREE_TEXT_FIELDS.get(row["id"], set())
        for path, value in _walk_example(row.get("example") or {}):
            if not isinstance(value, str) or path in allowed:
                continue
            rule = _rule_for(rules, path)
            if (rule or {}).get("type") != "select":
                uncovered.append("%s:%s" % (row["id"], path))
    checks.check(
        "every string-valued example field is a select or allow-listed free text",
        not uncovered,
    )
    if uncovered:
        print("     free text left: " + ", ".join(uncovered))

    def _rule(calc_id, path):
        calc = next((row for row in calculators if row["id"] == calc_id), None)
        return ((calc or {}).get("field_rules") or {}).get(path) or {}

    hydrology_condition = _rule("hydrology", "condition")
    checks.check(
        "hydrology surface condition is the five section 18 classes",
        hydrology_condition.get("type") == "select"
        and [c.get("value") for c in hydrology_condition.get("choices", [])]
        == ["陡峻山地", "山嶺區", "丘陵地或森林", "平坦耕地", "非農業使用"],
    )
    checks.check(
        "hydrology overland-flow range is a select",
        _rule("hydrology", "area_type").get("type") == "select",
    )
    checks.check(
        "sediment basin kind is a select",
        _rule("sediment_basin", "kind").get("type") == "select",
    )
    checks.check(
        "slope stage and condition are selects",
        _rule("slope_stability", "stage").get("type") == "select"
        and _rule("slope_stability", "condition").get("type") == "select",
    )
    cell_rule = _rule("box_culvert", "cell_count")
    checks.check(
        "box culvert cell count is a numeric select",
        cell_rule.get("type") == "select"
        and [c.get("value") for c in cell_rule.get("choices", [])] == [1, 2, 3],
    )
    checks.check(
        "settlement foundation type is a select",
        _rule("settlement_assessment", "default_foundation_type").get("type") == "select"
        and _rule("foundation_isolated", "settlement.foundation_type").get("type") == "select",
    )
    checks.check(
        "drainage network link type and cell count are selects",
        _rule("drainage_network", "links[].type").get("type") == "select"
        and _rule("drainage_network", "links[].cell_count").get("type") == "select",
    )
    support_rule = _rule("building_frame", "geometry.support")
    checks.check(
        "building frame support condition is a select",
        support_rule.get("type") == "select"
        and {c.get("value") for c in support_rule.get("choices", [])}
        == {"fixed", "pinned"},
    )
    for wall_id in ("block_wall", "counterfort_wall", "mse_wall"):
        checks.check(
            "%s soil foundation is a select" % wall_id,
            _rule(wall_id, "foundation").get("type") == "select",
        )

    failed_examples = []
    for row in calculators:
        result = API.run_calculation(row["id"], row["example"], persist=False)
        required = {
            "schema",
            "calculator",
            "title",
            "engine",
            "ok",
            "summary",
            "checks",
            "warnings",
            "codes",
            "result",
            "saved_to",
        }
        if not required.issubset(result) or result.get("schema") != "civil-design-run/1":
            checks.check("%s schema" % row["id"], False)
        if not result.get("ok"):
            failed_examples.append(row["id"])
    checks.check(
        "all catalog examples pass",
        not failed_examples,
    )
    if failed_examples:
        print("     failed: " + ", ".join(failed_examples))

    try:
        API.run_calculation("not-a-calculator", {}, persist=False)
        unknown_ok = False
    except API.DesignAPIError:
        unknown_ok = True
    checks.check("unknown calculator is rejected", unknown_ok)

    missing = API.run_calculation("rc_beam", {}, persist=False)
    checks.check(
        "missing parameters return structured error",
        missing.get("ok") is False and bool(missing.get("error")),
    )
    custom_manning = dict(channel["example"])
    custom_manning["manning_n"] = 0.017
    custom_manning_result = API.run_calculation(
        "channel_hydraulics",
        custom_manning,
        persist=False,
    )
    checks.check(
        "custom Manning n reaches the hydraulic engine",
        custom_manning_result.get("error") is None
        and custom_manning_result.get("result", {}).get("manning_n") == 0.017,
    )

    page = (ROOT / "tools" / "design" / "workbench_web.html").read_text(
        encoding="utf-8"
    )
    checks.check(
        "workbench posts to design API",
        "/api/design/run" in page and "/api/design/catalog" in page,
    )
    checks.check("workbench displays advisory rows", 'c.severity === "advisory"' in page)
    checks.check(
        "workbench renders rule-driven selects",
        'rule?.type === "select"' in page
        and 'el.dataset.rule === "rerender"' in page
        and "input_offset_by" in page
        and "clear_on_change" in page
        and "choice?.defaults" in page
        and "validateFieldRules" in page,
    )
    checks.check(
        "workbench renders nested list editors",
        "isSimpleObjectArray" in page
        and "listEditorHtml" in page
        and "data-list-add" in page
        and "data-list-remove" in page
        and "normalizeRulePath" in page,
    )
    checks.check(
        "workbench renders editable Manning presets",
        "number_with_presets" in page
        and "data-preset-for" in page
        and "preset-row" in page
        and "presetSelections" in page
        and "data-label" in page,
    )
    checks.check(
        "workbench labels the steel column fields",
        "design_method:" in page
        and "base_plate:" in page
        and "anchors:" in page
        and "plate_t_mm:" in page
        and "embedment_mm:" in page,
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), regs_server.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % port
    try:
        with urlopen(base + "/design", timeout=10) as response:
            design_html = response.read().decode("utf-8")
        checks.check(
            "GET /design returns the workbench",
            "工程設計工作台" in design_html,
        )
        health = _request_json(base + "/api/design/health")
        checks.check(
            "GET /api/design/health",
            health.get("ok") is True
            and health.get("calculators") == len(calculators),
        )
        catalog = _request_json(base + "/api/design/catalog")
        checks.check(
            "GET /api/design/catalog",
            len(catalog.get("calculators") or []) == len(calculators),
        )
        rc_beam = _request_json(
            base + "/api/design/run",
            {
                "calculator": "rc_beam",
                "payload": {
                    "Mu_kNm": 180.0,
                    "Vu_kN": 120.0,
                    "b_mm": 350.0,
                    "h_mm": 750.0,
                },
                "persist": False,
            },
        )
        checks.check(
            "POST /api/design/run",
            rc_beam.get("ok") is True
            and any(
                item.get("item") == "剪力（含箍筋）"
                for item in rc_beam.get("checks", [])
            ),
        )
        over_limit = _request_json(
            base + "/api/design/run",
            {
                "calculator": "wall_stability",
                "payload": {
                    "wall_type": "semigravity",
                    "height_m": 4.81,
                    "base_width_m": 2.5,
                    "base_thickness_m": 0.8,
                    "top_width_m": 0.3,
                    "front_batter_ratio": 0.3,
                    "toe_projection_m": 0.5,
                    "toe_soil_depth_m": 1.5,
                },
                "persist": False,
            },
        )
        checks.check(
            "POST wall over height limit returns structured error",
            over_limit.get("ok") is False
            and "超過適用上限 4.0 m" in str(over_limit.get("error")),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print("\n%d failure(s)" % checks.failures)
    return 1 if checks.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
