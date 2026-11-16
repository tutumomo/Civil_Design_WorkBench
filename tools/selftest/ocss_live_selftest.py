r"""工作台即時交叉驗算自測：不需要 OCSS 桌面程式（以假客戶端取代）。

驗證：
* 三態能力表（supported／offline_only／none）
* 三個計算器的參數對應（取自引擎實際採用的值，含預設值）
* 預先防護（不合範圍的參數在送給 OCSS 之前就擋下，附具體原因）
* 略過規則（不可比的項目標 skipped，不算吻合也不算差異）
* 逐項比對與結論（match／diff／nothing_compared）
* 不信任前端結果：伺服器端用同一組參數重跑引擎

Run:
    .venv/bin/python tools/selftest/ocss_live_selftest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("tools/crosscheck", "tools/design", "tools/regs"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import design_api as D  # noqa: E402
import ocss_live as L  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ((" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def example(calc_id: str) -> dict:
    """計算器範例參數的**副本**（catalog 的 example 是共用物件，不可就地改）。"""
    return json.loads(json.dumps(
        next(c["example"] for c in D.list_calculators() if c["id"] == calc_id)))


def deep_patch(dst: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_patch(dst[k], v)
        else:
            dst[k] = v
    return dst


def fresh(calc_id: str, patch: dict | None = None) -> tuple[dict, dict]:
    """改參數後**重跑引擎**再回傳（payload, result）。"""
    p = example(calc_id)
    if patch:
        deep_patch(p, patch)
    return p, D.run_calculation(calc_id, p, persist=False)["result"]


class FakeClient:
    """假的 OCSS 客戶端：回傳固定的變數值，不連桌面程式。"""

    def __init__(self, values: dict, unit: str = ""):
        self.values = values
        self.unit = unit
        self.calls: list[dict] = []

    def require(self):
        return {"version": "0.0.0-fake", "edition": "tw"}

    def evaluate(self, source, values=None):
        self.calls.append({"source": source, "values": values})
        lines = [{"type": "assignment", "name": k, "value": v, "unit": self.unit}
                 for k, v in self.values.items()]
        return {"lines": lines, "ucValues": {}, "uc": 0.5, "passes": True,
                "errorLines": 0, "warnings": [], "notConverged": False,
                "truncated": False, "uncheckedLines": [], "title": "fake"}


class FakeSheetClient(FakeClient):
    """假的專案／工作表客戶端，記錄動過哪些操作。"""

    def __init__(self, project_state: dict | None = None, fail_at: str | None = None,
                 sheet_source: str | None = None):
        super().__init__({})
        self.state = dict(project_state or {"filePath": "C:/tmp/prev.ifccalculation",
                                            "unsaved": False})
        self.fail_at = fail_at
        self.ops: list[str] = []
        self.source = None
        self.sheet_source = sheet_source     # 假裝 App 上實際存的文字（驗證用）
        self.saved_as = None
        self.opened = None

    def _maybe_fail(self, op):
        if self.fail_at == op:
            from ocss_client import OcssError
            raise OcssError("-", "假錯誤：%s" % op)

    def project(self):
        self.ops.append("project")
        return dict(self.state)

    def project_save(self, path=None):
        self.ops.append("project_save")
        self._maybe_fail("project_save")
        return {}

    def project_new(self, force=False):
        self.ops.append("project_new")
        self._maybe_fail("project_new")
        return {}

    def project_set_name(self, name):
        self.ops.append("project_set_name")
        return {}

    def sheet_add_source(self, source, name=None):
        self.ops.append("sheet_add_source")
        self._maybe_fail("sheet_add_source")
        self.source = source
        self.sheet_name = name
        return {"id": "sheet-1"}

    def sheet_evaluate(self, sheet_id, names=None):
        self.ops.append("sheet_evaluate")
        self._maybe_fail("sheet_evaluate")
        return {"uc": 0.5, "passes": True, "errorLines": 0,
                "lines": [{"type": "assignment", "name": "x", "value": 1.0}] * 3}

    def sheet_select(self, sheet_id):
        self.ops.append("sheet_select")
        self._maybe_fail("sheet_select")
        return {}

    def view_set(self, view):
        self.ops.append("view_set:%s" % view)
        self._maybe_fail("view_set")
        return {}

    def sheet(self, sheet_id, evaluate=False):
        """讀回剛寫進去的表（驗證「值真的有寫進去」用）。"""
        self.ops.append("sheet")
        self._maybe_fail("sheet")
        return {"id": sheet_id,
                "source": self.source if self.sheet_source is None else self.sheet_source}

    def project_save_as(self, path):
        self.ops.append("project_save_as")
        self._maybe_fail("project_save_as")
        self.saved_as = path
        return {}

    def project_open(self, path):
        self.ops.append("project_open")
        self.opened = path
        return {}


def main() -> int:
    print("[1] 三態能力表")
    caps = L.capability_map([c["id"] for c in D.list_calculators()])
    check("排水溝為 supported", caps["channel_hydraulics"]["status"] == "supported")
    check("獨立基腳為 supported", caps["foundation_isolated"]["status"] == "supported")
    check("鋼柱為 supported", caps["steel_column"]["status"] == "supported")
    check("懸臂牆為 offline_only（有批次對照案例）",
          caps["wall_stability"]["status"] == "offline_only"
          and caps["wall_stability"]["offline_cases"] >= 1)
    check("無對照者為 none", caps["detention_basin"]["status"] == "none")
    check("offline_only 不可即時驗算", caps["wall_stability"]["supported"] is False)

    print("[2] 參數對應（值取自引擎實際採用的結果）")
    res = D.run_calculation("channel_hydraulics", example("channel_hydraulics"),
                             persist=False)["result"]
    inputs, notes = L._channel_inputs(example("channel_hydraulics"), res)
    check("流量取自引擎的 Q_design",
          abs(float(inputs["Q_direct"]) - float(res["Q_design"])) < 1e-9, str(inputs))
    check("內寬溝深取自引擎結果",
          abs(float(inputs["B_chan"]) - float(res["b"])) < 1e-9
          and abs(float(inputs["H_chan"]) - float(res["h_total"])) < 1e-9)
    check("有對齊說明", len(notes) >= 1)
    check("literal 值不是科學記號", "e" not in inputs["Q_direct"].lower(), inputs["Q_direct"])

    fres = D.run_calculation("foundation_isolated", example("foundation_isolated"),
                              persist=False)["result"]
    finputs, fnotes = L._footing_inputs(example("foundation_isolated"), fres)
    check("基腳尺寸換算成 mm",
          abs(finputs["B_f"] - float(fres["geometry"]["B_m"]) * 1000) < 1e-6)
    check("自重與覆土歸零", finputs["gamma_c"] == 0 and finputs["gamma_s"] == 0
          and finputs["D_f"] == 0)
    check("載重取絕對值", finputs["Mx_serv"] >= 0 and finputs["My_serv"] >= 0)
    check("有對齊說明", len(fnotes) >= 1)

    sres = D.run_calculation("steel_column", example("steel_column"),
                             persist=False)["result"]
    sinputs, snotes = L._steel_inputs(example("steel_column"), sres)
    check("混凝土強度換算成 kgf/cm²（取 2 位小數）",
          abs(sinputs["fc_in"] - float(sres["base_plate"]["fc_mpa"]) * 10.1972) < 0.005,
          str(sinputs["fc_in"]))
    check("基板尺寸換算成 mm",
          abs(sinputs["B_p"] - float(sres["base_plate"]["plate_B_m"]) * 1000) < 1e-6)
    check("剪力取合力", abs(sinputs["V_u"] - 30.0) < 1e-6, str(sinputs["V_u"]))
    check("選到的型鋼斷面小於基板", sinputs["section_id"] in L._OCSS_H_SECTIONS)
    check("有對齊說明", len(snotes) >= 1)

    print("[3] 預先防護（送 OCSS 之前就擋下）")
    # 防護讀的是引擎**實際採用的**尺寸與工法，所以測資要先重跑引擎
    p_thin, r_thin = fresh("foundation_isolated", {"geometry": {"thickness_m": 0.15}})
    try:
        L._footing_inputs(p_thin, r_thin)
        check("基腳厚度過薄擋下", False)
    except L.NotApplicable as e:
        check("基腳厚度過薄擋下", "200 mm" in str(e), str(e))
    p_asd, r_asd = fresh("steel_column", {"design_method": "asd"})
    try:
        L._steel_inputs(p_asd, r_asd)
        check("ASD 擋下", False)
    except L.NotApplicable as e:
        check("ASD 擋下", "ASD" in str(e), str(e))
    p_ten, r_ten = fresh("steel_column", {"column": {"axial_P_kN": -300.0}})
    try:
        L._steel_inputs(p_ten, r_ten)
        check("受拉柱擋下", False)
    except L.NotApplicable as e:
        check("受拉柱擋下", "受拉" in str(e) or "受壓" in str(e), str(e))
    try:
        L._channel_inputs({"freeboard_min_m": 0.2}, {"Q_design": 0.0, "b": 1.0,
                                                      "h_total": 1.0, "S": 0.01,
                                                      "manning_n": 0.014})
        check("流量為 0 擋下", False)
    except L.NotApplicable as e:
        check("流量為 0 擋下", "大於 0" in str(e), str(e))

    print("[4] 逐項比對與結論")
    ex = example("channel_hydraulics")
    res = D.run_calculation("channel_hydraulics", ex, persist=False)
    ours = res["result"]
    fr = next(c["value"] for c in ours["checks"] if "福祿數" in str(c.get("item", "")))
    client = FakeClient({
        "Q_cap": float(ours["Q_cap_m3s"]), "V_full": float(ours["V_full_ms"]),
        "d_n": float(ours["h_normal_m"]), "V_design": float(ours["V_design_ms"]),
        "Fr_num": float(fr), "fb_req": float(ours["freeboard_required_m"]),
        "Q_design": float(ours["Q_design"]),
    }, unit="m")
    r = L.run("channel_hydraulics", ex, client=client)
    check("狀態 ok", r["status"] == "ok", r["message"])
    check("結論 match", r["verdict"] == "match", json.dumps(r["counts"]))
    check("六項都比到了", r["counts"]["total"] == 6 and r["counts"]["passed"] == 6,
          json.dumps(r["counts"]))
    check("回傳 OCSS 輸入供稽核", bool(r["ocss_inputs"]))
    check("不回傳 token", "token" not in json.dumps(r, ensure_ascii=False).lower()
          or "ocss_inputs" in r)

    print("[5] 溢流時水深不可比")
    ex2 = deep_patch(example("channel_hydraulics"), {"design_flow_m3s": 1.5})
    res2 = D.run_calculation("channel_hydraulics", ex2, persist=False)["result"]
    client2 = FakeClient({
        "Q_cap": float(res2["Q_cap_m3s"]), "V_full": float(res2["V_full_ms"]),
        "d_n": 1.05 * float(res2["h_total"]), "V_design": 1.0, "Fr_num": 0.5,
        "fb_req": 0.2, "Q_design": float(res2["Q_design"]),
    }, unit="m")
    r2 = L.run("channel_hydraulics", ex2, client=client2)
    skipped = [i for i in r2["items"] if i["status"] == "skipped"]
    check("溢流時水深等四項標為不比", len(skipped) == 4, json.dumps(r2["counts"]))
    check("不比項目不計為差異", r2["counts"]["failed"] == 0)
    check("仍比得了滿流通水量", r2["counts"]["passed"] == 2, json.dumps(r2["counts"]))
    check("不比有寫原因", all(i.get("reason") for i in skipped))

    print("[6] 數值有差異時判為 diff（不得放寬容差掩蓋）")
    client3 = FakeClient({
        "Q_cap": float(ours["Q_cap_m3s"]) * 1.5, "V_full": float(ours["V_full_ms"]),
        "d_n": float(ours["h_normal_m"]), "V_design": float(ours["V_design_ms"]),
        "Fr_num": 0.5, "fb_req": float(ours["freeboard_required_m"]),
        "Q_design": float(ours["Q_design"]),
    }, unit="m")
    r3 = L.run("channel_hydraulics", ex, client=client3)
    check("差異被標為 failed", r3["counts"]["failed"] >= 1, json.dumps(r3["counts"]))
    check("結論 diff", r3["verdict"] == "diff")

    print("[7] OCSS 沒有產生結果時不適用")
    r4 = L.run("channel_hydraulics", ex, client=FakeClient({}, unit="m"))
    check("模板無輸出時狀態 not_applicable", r4["status"] == "not_applicable", r4["message"])
    check("附帶適用範圍", len(r4["limits"]) >= 1)

    print("[8] 不支援的計算器")
    r5 = L.run("detention_basin", {})
    check("狀態 not_supported", r5["status"] == "not_supported")

    print("[9] 引擎算不出來時回報 engine_error")
    r6 = L.run("channel_hydraulics", {"design_flow_m3s": "abc"})
    check("狀態 engine_error 或 error",
          r6["status"] in ("engine_error", "error"), r6["status"])

    print("[10] 4 支對稱錨栓時 T 可比")
    sex = deep_patch(example("steel_column"), {"anchors": {"positions": [
        {"x_m": -0.15, "y_m": -0.19}, {"x_m": 0.15, "y_m": -0.19},
        {"x_m": -0.15, "y_m": 0.19}, {"x_m": 0.15, "y_m": 0.19}]}})
    sres2 = D.run_calculation("steel_column", sex, persist=False)["result"]
    sclient = FakeClient({
        "A1": float(sres2["base_plate"]["bearing"]["A1_cm2"]),
        "A2": float(sres2["base_plate"]["bearing"]["A2_cm2"]),
        "phiP_p": float(sres2["base_plate"]["bearing"]["capacity_kN"]),
        "q_max": 1.0, "q_min": -1.0,
        "T_bolt": float(sres2["anchors"]["max_tension_kn"]),
        "phiRn_t": float(sres2["anchors"]["capacity"]["tension_capacity_kN"]),
    }, unit="kN")
    r7 = L.run("steel_column", sex, client=sclient)
    names = [i["name"] for i in r7["items"]]
    check("T 項不被略過",
          "單支錨栓最大拉力 T" in names
          and [i for i in r7["items"] if i["name"] == "單支錨栓最大拉力 T"][0]["status"]
          != "skipped", json.dumps(r7["counts"]))

    print("[11] 8 支錨栓時 T 略過")
    r8 = L.run("steel_column", example("steel_column"), client=sclient)
    skipped8 = [i for i in r8["items"]
                if i["name"] == "單支錨栓最大拉力 T" and i["status"] == "skipped"]
    check("T 項被略過並寫原因",
          len(skipped8) == 1 and "8 支" in skipped8[0]["reason"])

    print("[12] 在 OCSS 開啟計算表（假客戶端，不動真實專案）")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ocss_sheet_")

    # 12a 未儲存且沒有檔案路徑 → 停下來，不動專案
    c1 = FakeSheetClient({"filePath": None, "unsaved": True})
    r1 = L.open_sheet("channel_hydraulics", ex, client=c1, out_dir=tmp)
    check("未儲存且無檔名時停下", r1["status"] == "error" and "未儲存" in r1["message"], r1["message"])
    check("此時不動任何專案操作", "project_new" not in c1.ops, str(c1.ops))

    # 12b 未儲存但有檔案路徑 → 先存檔再換專案
    c2 = FakeSheetClient({"filePath": "C:/tmp/prev.ifccalculation", "unsaved": True})
    r2 = L.open_sheet("channel_hydraulics", ex, client=c2, out_dir=tmp)
    check("先存檔再開新專案",
          c2.ops[:3] == ["project", "project_save", "project_new"], str(c2.ops[:4]))
    check("回報已幫使用者存檔", r2["saved_previous"] is True)
    check("狀態 ok", r2["status"] == "ok", r2["message"])
    check("另存成 .ifccalculation", (r2["project_file"] or "").endswith(".ifccalculation"))
    check("有切到該工作表", "sheet_select" in c2.ops)
    check("切到「算式＋結果」檢視，且在存檔之後（存檔會重設檢視）",
          "view_set:code-output" in c2.ops
          and c2.ops.index("project_save_as") < c2.ops.index("view_set:code-output"),
          str(c2.ops))
    check("有讀回 App 手上的表做驗證", "sheet" in c2.ops, str(c2.ops))
    check("select 在 save_as 之前", c2.ops.index("sheet_select") < c2.ops.index("project_save_as"))
    check("工作表名稱帶計算器", bool(r2["sheet"]) and "排水溝" in r2["sheet"], str(r2.get("sheet")))
    check("回報行數與 UC", r2["line_count"] > 0 and r2["uc"] == 0.5, str(r2["line_count"]))
    check("表格最上面有說明橫幅、且註明模板 UC 不代表本專案",
          (c2.source or "").startswith("'<div")
          and "不代表本專案結果" in (c2.source or ""))
    check("計算文字已內嵌輸入值（不是 ?{ 預設）",
          "?{" not in (c2.source or "") and "1e-05" not in (c2.source or ""),
          (c2.source or "")[:120])
    check("橫幅列出寫進這張表的輸入值", "寫進這張表的輸入值" in (c2.source or ""))
    check("讀回驗證通過（每個輸入值都在算式那一行）", r2["verified"] is True,
          json.dumps(r2["verification"], ensure_ascii=False)[:200])
    check("回報畫面上的輸入值清單",
          any(row["name"] == "B_chan" for row in r2["input_rows"]), str(r2["input_rows"])[:200])
    check("回報收到的參數（payload_echo）", r2["payload_echo"].get("inner_width_m") == 0.4,
          str(r2["payload_echo"])[:120])

    # 12c 中途失敗 → 把原本專案開回來
    c3 = FakeSheetClient({"filePath": "C:/tmp/prev.ifccalculation", "unsaved": False},
                         fail_at="sheet_evaluate")
    r3 = L.open_sheet("channel_hydraulics", ex, client=c3, out_dir=tmp)
    check("失敗時回報 error", r3["status"] == "error", r3["status"])
    check("失敗時把原本的專案開回來", c3.opened == "C:/tmp/prev.ifccalculation", str(c3.opened))

    # 12d 參數不適用 → 不碰專案
    c4 = FakeSheetClient()
    p_bad = example("foundation_isolated")
    deep_patch(p_bad, {"geometry": {"thickness_m": 0.15}})
    r4 = L.open_sheet("foundation_isolated", p_bad, client=c4, out_dir=tmp)
    check("參數不適用時不碰專案", r4["status"] == "not_applicable" and c4.ops == [],
          str(c4.ops))

    # 12e 讀回的值與送出不符（App 手上是舊的預設值）→ 一定要叫出來，不能報成功
    p5 = deep_patch(example("channel_hydraulics"),
                    {"inner_width_m": 0.55, "depth_m": 1.0})
    c0 = FakeSheetClient()
    r0 = L.open_sheet("channel_hydraulics", p5, client=c0, out_dir=tmp)
    good = c0.source or ""
    check("寫入的文字本身讀回驗證通過", r0["verified"] is True,
          json.dumps(r0["verification"], ensure_ascii=False)[:300])
    c5 = FakeSheetClient(sheet_source=good.replace("B_chan = 0.55", "B_chan = 0.4"))
    r5 = L.open_sheet("channel_hydraulics", p5, client=c5, out_dir=tmp)
    check("讀回的值與送出不符時回報 error", r5["status"] == "error", r5["status"])
    check("訊息點名是哪一項不符", "B_chan" in r5["message"], r5["message"][:160])
    check("不符時 verified 為 False", r5["verified"] is False)
    # 12f 同樣的參數，App 手上是對的內容 → verified 為 True
    c6 = FakeSheetClient(sheet_source=good)
    r6 = L.open_sheet("channel_hydraulics", p5, client=c6, out_dir=tmp)
    check("讀回相符時 verified 為 True", r6["verified"] is True,
          json.dumps(r6["verification"], ensure_ascii=False)[:200])
    check("相符時狀態 ok", r6["status"] == "ok", r6["status"])

    print()
    if FAILS:
        print("✗ 失敗 %d 項：%s" % (len(FAILS), "；".join(FAILS)))
        return 1
    print("✓ 工作台即時交叉驗算自測全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
