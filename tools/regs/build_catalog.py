"""Build docs\\法規庫總目錄.md from data\\法規\\_regs_manifest.json plus hand-kept status notes.

usage: python -E -P -X utf8 build_catalog.py
"""
import datetime
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CIVIL_AI_ROOT") or Path(__file__).resolve().parents[2])
REG = ROOT / "data" / "法規"
DOC = ROOT / "docs" / "法規庫總目錄.md"

CUR, OLD, CHK = "現行", "已被取代（留作對照）", "需再核版次"

# id -> (類別, 狀態, 備註)；版次已於 2026-10-29 逐份開封面核對
META = {
    "swc_tech": ("水保", CUR, "農農保字第1142667525號；公報 PDF 僅 1 頁，全文以文字檔為準（第 1~211 條）；"
                 "本工作區水保設計計算之主依據"),
    "swc_act": ("水保", CUR, ""),
    "swc_rule": ("水保", CUR, ""),
    "swc_review": ("水保", CUR, "水土保持計畫／簡易水保審查程序"),
    "slopeland_act": ("水保", CUR, ""),
    "slopeland_rule": ("水保", CUR, ""),
    "rc112": ("建築結構", CUR, "含 113.02.19 勘誤；條文架構改依 ACI 318-19，條號與 100 年版不同"),
    "rc100": ("建築結構", OLD, "原「混凝土結構設計規範」；tools\\design\\rc_design.py 目前引用此版條號"),
    "found112": ("建築結構", CUR, "擋土牆、基礎承載、土壓力"),
    "seis113": ("建築結構", CUR, "glrs 公告全文"),
    "seis111": ("建築結構", OLD, "國震中心轉載之 111 年版，已被 113.03.01 版取代"),
    "wind103full": ("建築結構", CUR, "封面：103.6.12 台內營字第1030805400號令修正，104.01.01 生效；未見更新版公告"),
    "wind103": ("建築結構", CUR, "glrs 附件僅 6 頁（公告本文），完整內容請用上一列"),
    "steel99": ("建築結構", CUR, "41 個附件合併（容許應力法、極限設計法兩冊＋13.2 點修正）；"
                "建研所 110 年已完成新版草案，尚未見正式公告"),
    "btr_general": ("建築法規", CUR, ""),
    "btr_design": ("建築法規", CUR, ""),
    "btr_struct": ("建築法規", CUR, "擋土牆、基礎、山坡地建築相關條文"),
    "btr_equip": ("建築法規", CUR, ""),
    "urbanroad113": ("道路", CUR, "市區道路、人行道、側溝之設計依據"),
    "urbanroad_act": ("道路", CUR, ""),
    "hwroute115": ("道路", CUR, "交綜(一)字第11586004125號"),
    "farmroad108": ("農路", CUR, "點次式規範；含附表一～四與附圖，依第 75 條第 2 項訂定"),
    "hwdrain107": ("道路排水", CUR, "107.02.06 修正版；2026-11-01 查核交通部部頒規範頁面（serno=414）仍為最新版"),
    "sewer_std": ("道路排水", CUR, "雨水下水道設施標準"),
    "hwslope104": ("邊坡", CUR, "須搭配 111.04.27 修正對照表"),
    "hwslope111": ("邊坡", CUR, "104 版之修正條文"),
    "flexpave91": ("鋪面", CUR, "91.01.31 部頒版；2026-11-01 查核交通部部頒清單（serno=353）仍為最新版，引用時註明版次"),
    "traffic114": ("交通工程", CUR, "標誌標線、護欄"),
    "traffic_sign": ("交通工程", CUR, ""),
    "hwconst112": ("施工規範", CUR, "封面標示 111.12"),
    "airconst110": ("環境保護", CUR, "附表一～五；第 6 條圍籬、第 10 條洗車台／沉砂池、第 18 條監測"),
    "hwbridge": ("橋梁／箱涵", CUR, "本文為 98.12 初版；須搭配 104.04.13 與 109.01.03 兩次修訂"),
    "hwbridge104": ("橋梁／箱涵", CUR, "第 7、12 章（保護層、耐久性）修訂對照表"),
    "hwbridge109": ("橋梁／箱涵", CUR, "第 1 章（特殊性橋梁、維護管理）修訂"),
}

# files that predate fetch_regs.py
EXTRA = {
    "swc_tech": {"name": "水土保持技術規範_1140507", "authority": "農業部",
                 "version": "114.05.07 修正", "files": {"original": "水土保持技術規範_1140507_公報.pdf",
                                                       "text": "水土保持技術規範_1140507_全文.txt"}},
    "rc100": {"name": "混凝土結構設計規範_1000609", "authority": "內政部",
              "version": "100.06.09 修正", "files": {"original": "混凝土結構設計規範_1000609.pdf",
                                                    "text": "混凝土結構設計規範_1000609_全文.txt"}},
}

NOT_GOT = [
    ("水土保持手冊（2017 年版，總論／調查分析／農藝／工程／土石流／植生）", "農業部農村發展及水土保持署",
     "下載頁為互動式電子書平台，無法直接下載，請人工下載後放入 data\\法規\\",
     "https://learning.ardswc.gov.tw/pages/Advanced_Filter_Books_Introduction.html?bookId=SWCB_00022"),
    ("水土保持工程設計參考圖冊", "農業部農村發展及水土保持署", "屬圖冊非規範，未下載",
     "https://www.ardswc.gov.tw/home/Download/download_more?id=8ff5a0bf9fb9456e8b883c0b9f220a5d"),
    ("雨水下水道設計指南", "內政部國土管理署", "屬指南非法定規範，未下載；法定部分已由「下水道工程設施標準」涵蓋", ""),
    ("公路橋梁耐震設計規範", "交通部", "小型工程較少用到，未下載（如需箱涵耐震可補）",
     "https://www.motc.gov.tw/ch/app/divpubreg_list/view?module=divpubreg&id=740&serno=419"),
]

ORDER = ["水保", "道路", "農路", "道路排水", "邊坡", "鋪面", "交通工程", "施工規範", "環境保護",
         "橋梁／箱涵", "建築結構", "建築法規"]


def local(r):
    f = r.get("files", {})
    main = f.get("folder") and f["folder"] + "\\" or f.get("pdf") or f.get("original") or ""
    return main, f.get("text", "")


def version(r):
    v = r.get("version") or ""
    if r.get("amended") and r["amended"] not in v:
        v = (v + "；" if v else "修正日期：") + r["amended"]
    return v.replace("|", "／")


def main():
    man = json.loads((REG / "_regs_manifest.json").read_text(encoding="utf-8"))
    recs = dict(man)
    recs.update({k: dict(v, id=k) for k, v in EXTRA.items()})
    import fitz
    for k in EXTRA:
        with fitz.open(REG / recs[k]["files"]["original"]) as d:
            recs[k]["pages"] = d.page_count
    missing = [k for k in recs if k not in META]
    if missing:
        raise SystemExit(f"no META for {missing}")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [
        "# 法規庫總目錄（台灣土木／水保／建築設計規範）",
        "",
        f"> 由 `tools\\regs\\build_catalog.py` 依 `data\\法規\\_regs_manifest.json` 產生（{now}）。",
        "> 下載／更新：`C:\\Python312\\python.exe -E -P -X utf8 tools\\regs\\fetch_regs.py [--only ID ...]`；"
        "改完再跑本腳本重建目錄。",
        "",
        "## 使用規則",
        "",
        "1. **引用任何條文前先查本表**，確認用的是「現行」版；「已被取代」只供對照，不得作為設計依據。",
        "2. 全文搜尋請用 `_全文_NFKC.txt`（規範 PDF 常用相容表意字，未正規化會搜不到）。",
        "   快速查詢：`python -E -P -X utf8 tools\\regs\\verify_regs.py <ID> --grep <關鍵字>`。",
        "3. 法規命令（law.moj 來源）的版次取自全國法規資料庫「修正日期」，抓取當日為現行。",
        "4. 「需再核版次」：主管機關仍列為現行但年代久遠，引用時於報告註明版次。",
        "",
    ]
    for cat in ORDER:
        rows = [(k, r) for k, r in recs.items() if META[k][0] == cat]
        if not rows:
            continue
        out += [f"## {cat}", "",
                "| ID | 名稱 | 主管機關 | 版次／文號 | 頁數 | 狀態 | 本機檔案 | 全文文字檔 | 備註 |",
                "|---|---|---|---|---|---|---|---|---|"]
        for k, r in rows:
            _, status, note = META[k]
            f, t = local(r)
            f = f"`{f}`" if f else "（僅文字檔）"
            pages = r.get("pages") or ("—" if r.get("type") == "html" else "")
            out.append(f"| `{k}` | {r['name']} | {r.get('authority', '')} | {version(r)} | {pages} | "
                       f"{status} | {f} | `{t}` | {note} |")
        out.append("")
    out += ["## 來源網址與抓取紀錄", "", "| ID | 來源 | 抓取時間 | sha256（前 12 碼） |", "|---|---|---|---|"]
    for k, r in recs.items():
        out.append(f"| `{k}` | {r.get('page') or r.get('url', '（既有檔）')} | {r.get('fetched', '')} | "
                   f"{r.get('sha256', '')[:12]} |")
    out += ["", "## 尚未收錄", "", "| 名稱 | 主管機關 | 原因 | 網址 |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in NOT_GOT]
    out += ["", "## 待辦（只標記，未改程式）", "",
            "- `tools\\design\\rc_design.py` 與 `docs\\混凝土結構設計規範_取得與條文庫.md` 引用 100 年版條號"
            "（§2.3.2、§3.4.4、§3.6.1、§4.4.1.1、§7.2.2、§7.4.x）。112 年版已改名並依 ACI 318-19 重編，"
            "條號與部分數值可能變動，需逐條建立新舊對照後再決定是否改程式；改程式後必跑 "
            "`tools\\selftest\\regression.py`。",
            "- 已抽查一項：112 年版表 21.2.2 拉力控制界限改為 **εt ≥ εty＋0.003**（100 年版 §3.4.4 為 0.005）。"
            "fy＝420 MPa 時 εty＝0.002，兩者同為 0.005，**現有計算結果不變**；若改用 SD280 等其他鋼筋等級，"
            "`rc_design.py` 寫死的 0.005 就會不符新版。", ""]
    DOC.write_text("\n".join(out), encoding="utf-8")
    print("wrote", DOC, len(recs), "entries")


if __name__ == "__main__":
    main()
