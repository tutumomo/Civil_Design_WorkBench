# -*- coding: utf-8 -*-
r"""X5　逐式計算書：把交叉驗算案例做成 OCSS 專案檔（`.ifccalculation`）。

用途
----
技師要能**逐式核對**本專案的數字。OCSS 是唯一能「展開每一行公式」的環境，
所以把 `tools/crosscheck/checks/*.json` 的每個案例做成一張工作表：
公式鏈原樣寫在表上、輸入值直接內嵌在該行，技師在 App 裡看得到每一行怎麼算出來，
並可自行按「Rapport」輸出 PDF（**API 不能產 PDF**，見整合文件限制 2）。

產出
----
* `out/<案名>/<案名>_逐式計算書.ifccalculation` — OCSS 專案檔（可開啟、可列印）
* `out/<案名>/<案名>_交叉驗算結果.json` — 逐項比對結果（本專案 / OCSS / 差異 / 處置），
  供 `make_report.py` 的「計算附錄」引用（見 `--crosscheck`）

用法
----
    python tools/crosscheck/ocss_calcbook.py build --out out/<案名> [--only 關鍵字]
    python tools/crosscheck/ocss_calcbook.py summary --out out/<案名>

注意（改動 OCSS 專案狀態）
--------------------------
本工具會在 OCSS 開**新空白專案**並加入工作表，再另存新檔。OCSS 端若有未儲存變更，
`project_new` 會回 CONFLICT 而中止（**不會**強制丟棄使用者的專案）；
遇到这种情況請先在 App 裡存檔或開新專案再重跑。

需 OCSS 桌面程式開著（無 headless 模式）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT / "tools" / "design"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CHECKS_DIR = HERE / "checks"


class CalcbookError(RuntimeError):
    pass


# --------------------------------------------------------------- 輸入值內嵌
def bake_inputs(src: str, inv: dict, inputs: dict) -> str:
    """把模板輸入值直接寫進算式的那一行，回傳可獨立計算的 source。

    * literal 型（`B_chan = 0.60'm`）：改寫那一行的數值。
    * prompt 型（`S_DS = ?{0.80}'` 或 `fc_in = ?{28}*(MPa)`）：把 `?{預設}` 整段換成實際值。
    * choice 型（`@select support_type` 選單）：在該選單區塊的 `@end` 之後補一行
      `support_type = 1` 覆蓋選單值（選單本身留在表上，技師看得到選項）。

    為什麼不靠工作表輸入欄位：literal 型在工作表裡沒有輸入欄位
    （`sheet_set_input` 會回 "has no input"），而且逐式計算書要的是
    「值與式子並排可看」，內嵌最直白。
    """
    import ocss_template_check as TC

    src, values = TC.apply_inputs(src, inv, inputs)     # literal 已改寫；prompt 在 values
    kinds = {i["name"]: i.get("kind") for i in inv.get("inputs", [])}
    for name, val in (values or {}).items():
        if kinds.get(name) == "choice":
            # 選單型：在該 @select 區塊之後補一行賦值
            pat = re.compile(r"(@select\s+%s\b.*?@end\b)" % re.escape(name), re.S)
            src, n = pat.subn(lambda m: m.group(1) + "\n%s = %s" % (name, repr(float(val))),
                              src, count=1)
            if n != 1:
                raise CalcbookError("找不到選單區塊 @select %s" % name)
            continue
        # prompt 寫法是 `名 = ?{預設}` 或 `名 = ?{預設}*(單位)`；兩種都整段換掉，
        # 留著 `{預設}` 會讓 OCSS 解析成 `28.0{28}*(MPa)` 而報語法錯。
        pat = re.compile(r"^(%s\s*=\s*)\?\{[^}]*\}(\*\(.*?\))?" % re.escape(name), re.M)
        src, n = pat.subn(lambda m: m.group(1) + repr(float(val)) + (m.group(2) or ""),
                          src, count=1)
        if n != 1:
            raise CalcbookError("無法把輸入 %s 內嵌到算式" % name)
    return src


def _case_source(chk: dict) -> tuple[str, str]:
    """回傳（source, 來源標籤）。"""
    import ocss_template_check as TC

    if chk.get("type") == "formula":
        src = chk.get("source")
        if isinstance(src, list):
            src = "\n".join(src) + "\n"
        if not src:
            raise CalcbookError("formula 型案例缺 source")
        return src, "手寫公式鏈"
    tpl = chk["template"]
    src, inv = TC.load_template(tpl)
    return bake_inputs(src, inv, chk.get("ocss_inputs") or {}), tpl


def _sheet_name(chk: dict, idx: int, total: int) -> str:
    base = chk.get("name") or chk.get("template") or "公式"
    return "%02d %s" % (idx, base[:60])


# --------------------------------------------------------------- 建置
def build(client, out_dir: Path, only: str | None = None,
          project_name: str = "逐式計算書", compare: bool = True,
          calculator: str | None = None) -> dict:
    """建立 OCSS 專案（工作表＝交叉驗算案例），另存 `.ifccalculation`。

    `compare=False` 只做工作表、不跑逐項比對（自測用假客戶端時用）。
    `calculator` 只挑該計算器的案例（逐案交付時用）。
    """
    import ocss_template_check as TC

    files = sorted(CHECKS_DIR.glob("*.json"))
    if not files:
        raise CalcbookError("%s 內沒有對照案例" % CHECKS_DIR)

    cases: list[dict] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for chk in data.get("checks", []):
            if chk.get("type") not in ("template", "formula"):
                continue
            name = chk.get("name") or f.stem
            if only and only not in name:
                continue
            if calculator and chk.get("calculator") != calculator:
                continue
            cases.append({"file": f.name, "check": chk, "name": name})
    if not cases:
        raise CalcbookError("沒有符合條件的案例（--only %s）" % only)

    # 先在無狀態環境算一次，確定每張表都能算（source 有錯就不該存進專案）
    prepared = []
    for i, c in enumerate(cases, 1):
        src, origin = _case_source(c["check"])
        ev = client.evaluate(src)
        if ev.get("errorLines"):
            raise CalcbookError("案例「%s」算式有錯誤行（%s）"
                                % (c["name"], ev.get("errorLines")))
        prepared.append({
            "idx": i, "name": c["name"], "file": c["file"],
            "source": src, "origin": origin,
            "check": c["check"],
        })

    # ---- 動 OCSS 專案（新空白專案 → 加表 → 另存新檔）----
    # 使用者的未儲存內容不能丟：
    #   有檔案路徑 → 先存檔（內容留在磁碟，不會遺失），再開新專案。
    #   沒有檔案路徑（純記憶體內的新專案）且有未儲存變更 → 停下來問。
    cur = client.project()
    if cur.get("unsaved"):
        if not cur.get("filePath"):
            raise CalcbookError(
                "OCSS 目前專案有未儲存變更且沒有檔案路徑，開新專案會遺失內容。"
                "請先在 OCSS App 裡存檔（或另開空白專案），再重跑。")
        client.project_save()          # 先存檔：內容留在磁碟，開新專案不會遺失
    try:
        client.project_new(force=True)
    except Exception as e:                      # 其他錯誤（例如唯讀模式）
        raise CalcbookError("無法在 OCSS 開新專案：%s" % e) from None
    client.project_set_name(project_name)
    try:
        for p in prepared:
            res = client.sheet_add_source(p["source"],
                                          name=_sheet_name(p["check"], p["idx"], len(prepared)))
            p["sheet_id"] = res.get("id")
        for p in prepared:
            ev = client.sheet_evaluate(p["sheet_id"])
            p["uc"] = ev.get("uc")
            p["verdict"] = ev.get("passes")
        out_dir.mkdir(parents=True, exist_ok=True)
        ifc_path = (out_dir / ("%s_逐式計算書.ifccalculation" % project_name)).resolve()
        client.project_save_as(str(ifc_path))
    except Exception:
        # 失敗就清掉自己加的工作表，不留半套東西在 OCSS 裡擋住下次執行
        for p in prepared:
            sid = p.get("sheet_id")
            if not sid:
                continue
            try:
                client.sheet_remove(sid)
            except Exception:
                pass
        raise

    # ---- 逐項比對（用同一批 source，但走無狀態 evaluate，不動專案）----
    results = []
    total = failed = handled = 0
    if compare:
        for p in prepared:
            r = TC.run_case(client, p["check"], emit=lambda *a, **k: None)
            total += r["total"]
            failed += r["failed"]
            handled += r["handled"]
            results.append({
                "file": p["file"],
                "name": p["name"],
                "origin": p["origin"],
                "template": p["check"].get("template"),
                "type": p["check"].get("type"),
                "sheet": _sheet_name(p["check"], p["idx"], len(prepared)),
                "uc": p["uc"], "verdict": p["verdict"],
                "items": r.get("items") or [],
            })
    else:
        for p in prepared:
            results.append({
                "file": p["file"], "name": p["name"], "origin": p["origin"],
                "template": p["check"].get("template"), "type": p["check"].get("type"),
                "sheet": _sheet_name(p["check"], p["idx"], len(prepared)),
                "uc": p["uc"], "verdict": p["verdict"], "items": [],
            })
    summary = {
        "schema": "civil-ocss-calcbook/1",
        "project_file": str(ifc_path),
        "case_count": len(prepared),
        "item_count": total,
        "failed": failed,
        "handled": handled,
        "note": "PDF 需由使用者在 OCSS App 內按「Rapport」輸出（API 不產 PDF）。",
        "results": results,
    }
    js = out_dir / ("%s_交叉驗算結果.json" % project_name)
    js.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def print_summary(summary: dict) -> None:
    print("專案檔：%s" % summary["project_file"])
    print("案例 %d 個、比對項 %d 個（未處置差異 %d、已處置 %d）"
          % (summary["case_count"], summary["item_count"],
             summary["failed"], summary["handled"]))
    for r in summary["results"]:
        bad = [i for i in r["items"] if i["status"] != "pass"]
        print("  %-50s %s" % (r["sheet"], "全過" if not bad else
                              "／".join("%s(%s)" % (i["name"], i["status"]) for i in bad)))
    print("提醒：%s" % summary["note"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="逐式計算書（OCSS 專案檔）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="建立專案檔")
    p.add_argument("--out", required=True, help="輸出目錄（out/<案名>）")
    p.add_argument("--only", help="只做名稱含此關鍵字的案例")
    p.add_argument("--name", default="逐式計算書", help="檔名前綴（預設「逐式計算書」）")
    p.add_argument("--calculator", help="只做該計算器的案例（如 wall_stability）")
    p.add_argument("--summary", help="順便把摘要寫到這個 JSON")
    p2 = sub.add_parser("summary", help="讀既有結果檔並印摘要")
    p2.add_argument("--out", required=True)
    p2.add_argument("--name", default="逐式計算書")
    args = ap.parse_args(argv)

    if args.cmd == "summary":
        js = Path(args.out) / ("%s_交叉驗算結果.json" % args.name)
        if not js.is_file():
            raise SystemExit("找不到 %s（先跑 build）" % js)
        print_summary(json.loads(js.read_text(encoding="utf-8")))
        return 0

    from ocss_client import OcssClient
    client = OcssClient()
    client.require()
    try:
        summary = build(client, Path(args.out), only=args.only, project_name=args.name,
                        calculator=args.calculator)
    except CalcbookError as e:
        print("✗ %s" % e)
        return 2
    if args.summary:
        Path(args.summary).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
