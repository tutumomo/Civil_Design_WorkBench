from pathlib import Path
# -*- coding: utf-8 -*-
"""把 components_index.json 分類成「單元標準圖」盤點表。

分類規則：以檔名關鍵字為主（公司命名有規律），DXF 解析資料為輔（圖元數、比例、單位）。
輸出：
  _ref/components_catalog.json   機讀目錄（含分類、系列、變體旗標）
  docs/常用元件標準圖盤點.md      人看的分類清單
"""
import json, os, re, collections

R = str(Path(__file__).resolve().parents[1])
idx = json.load(open(os.path.join(R, "_ref", "components_index.json"), encoding="utf-8"))

# 分類：順序即優先序（先比對到的勝）
RULES = [
    ("圖框與樣板", ["空白框", "視埠", "LOGO", "loge", "公司LOGO"]),
    ("擋土牆", ["擋土牆", "護岸", "擋水牆", "封牆"]),
    ("排水溝渠", ["L溝", "排水明溝", "加蓋溝", "截水溝", "暗溝", "拍漿溝", "坡面溝",
                 "排水溝", "明溝", "碎石排水袋", "既有溝"]),
    ("集水井與消能", ["集水井", "集水器", "消能", "跌水"]),
    ("箱涵與管涵", ["箱涵", "管涵", "RCP"]),
    ("護欄", ["護欄", "欄杆", "防撞桿", "紐澤西"]),
    ("路面與地坪", ["路面", "A.C.", "AC(", "瀝青", "地坪", "路基", "PC路面", "P.C."]),
    ("標誌標線與交安", ["告示牌", "標線", "導標", "減速墊", "交通安全", "防減災", "工區平面"]),
    ("植生與護坡", ["植生", "砌卵石", "石籠", "型框", "噴漿", "山溝"]),
    ("邊坡防護", ["防落石柵"]),
    ("附屬詳圖", ["洩水管", "格柵蓋板", "蓋板各部尺寸"]),
    ("其他構造物", ["候車亭", "防水", "地坪", "河道", "箱型", "乾砌大塊石", "紙模"]),
]


def classify(name):
    for cat, keys in RULES:
        if any(k in name for k in keys):
            return cat
    return "未分類"


def family(name):
    """去掉括號內容與版本尾綴，找出系列名（例如「重力式擋土牆」）。"""
    base = re.sub(r"[（(][^）)]*[）)]", "", name)
    base = re.sub(r"\.(dwg|DWG)$", "", base).strip()
    base = re.sub(r"\s*(v\d+|\d+|-?\d+\.\d+\.\d+)$", "", base)
    return base.strip()


rows = []
for x in idx:
    name = x["file"]
    cat = classify(name)
    flags = []
    if "誤用" in name:
        flags.append("⚠ 檔名標示「誤用」")
    if "待確認" in name:
        flags.append("⚠ 檔名標示「待確認」")
    if "OLD" in name.upper():
        flags.append("舊版")
    if re.search(r"\.dwg$", name) == False:
        flags.append("副檔名為大寫")
    if x.get("insunits") == "m":
        flags.append("圖面單位＝m")
    if re.search(r"\s*\(1\)", name):
        flags.append("疑似重複下載（(1) 尾綴）")
    rows.append({
        "key": x["key"], "file": name, "category": cat, "family": family(name),
        "flags": flags, "units": x.get("insunits"),
        "scales": x.get("scales") or [], "entities": x.get("entities"),
        "layers": x.get("layers"), "n_text": x.get("n_text"),
        "dims": x.get("dims") or [], "size_kb": x.get("size_kb"),
        "unit_guess": x.get("_unit_guess"), "extent": x.get("extent"),
        "unit_name_hint": (re.search(r"單位\s*[:：]?\s*(M|cm|公分|公尺)|[（(](M|cm)作圖[）)]",
                                      name) or [None])[0],
        "texts_sample": x.get("texts_sample") or [],
    })

by_cat = collections.OrderedDict()
for r in sorted(rows, key=lambda y: (y["category"], y["file"])):
    by_cat.setdefault(r["category"], []).append(r)

json.dump(rows, open(os.path.join(R, "_ref", "components_catalog.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---- 產生 Markdown ----
L = []
L.append("# 公司土木工程常用元件：單元標準圖盤點")
L.append("")
L.append("> 來源：`G:\\我的雲端硬碟\\Detail Manager\\00-圖面相關\\公司土木工程常用元件\\`")
L.append("> 盤點日期：2026-10-28｜**只讀取本資料夾，未觸及 Detail Manager 其他歷年案件**")
L.append("")
L.append("## 〇、怎麼用這份表（給接手的人）")
L.append("")
L.append("| 想做的事 | 看哪裡 |")
L.append("|---|---|")
L.append("| 找某類構造物的標準圖 | 下面各分類表 |")
L.append("| 要改一張圖套用到新案 | 先確認**圖面單位是 m 還是 mm**（見 §二）、再確認比例 |")
L.append("| 要重建這份盤點 | `python _ref\\convert_batch.py` → `python _ref\\parse_components.py` → `python _ref\\build_inventory.py` |")
L.append("| 要機讀資料 | `_ref\\components_catalog.json`（含每張圖的圖層數、圖元數、比例、文字樣本）|")
L.append("| 已轉好的 DXF | `_ref\\components_dxf\\C001.dxf ~ C166.dxf`（對照 `_ref\\manifest.json`）|")
L.append("")
L.append("## 一、總覽")
L.append("")
L.append("| 分類 | 張數 |")
L.append("|---|---|")
for cat, items in by_cat.items():
    L.append("| %s | %d |" % (cat, len(items)))
L.append("| **合計** | **%d** |" % len(rows))
L.append("")
L.append("## 二、⚠ 先注意三件事")
L.append("")
L.append("**① 圖面單位無法靠解析自動判定 —— 引用前必須確認**")
L.append("")
L.append("| 判定方式 | 結果 | 可信度 |")
L.append("|---|---|---|")
L.append("| `INSUNITS` 表頭 | 162 張寫 mm、4 張寫 m | **不可信**（多為樣板殘留，同一構造物的 m 版與 cm 版都寫 mm）|")
L.append("| 檔名標註（單位M／單位cm／M作圖／cm作圖）| 22 張有明確標註 | 高（人工寫的）|")
L.append("| 模型範圍量級（<50→m、50~2000→cm、>2000→mm）| m 88／cm 55／mm 19／無法判定 4 | 中（可初篩，有例外）|")
L.append("")
L.append("**實證**（同名兩版對比）：")
L.append("")
L.append("| 檔名 | INSUNITS | 模型範圍 | 實際內容單位 |")
L.append("|---|---|---|---|")
L.append("| `重力式擋土牆(H=2.0m)(上邊坡,單位M).dwg` | mm | 6.64 × 3.72 | **m** |")
L.append("| `重力式擋土牆(H=2.0m)(上邊坡,單位cm).dwg` | mm | 431.14 × 531.17 | **cm** |")
L.append("")
L.append("→ 兩張 INSUNITS 都寫 mm，卻相差 65 倍。**表頭是樣板殘留，不能信。**")
L.append("")
conflicts = [r for r in rows if r["unit_name_hint"] and r["unit_guess"] and
             (("cm" in r["unit_name_hint"] and r["unit_guess"] != "cm") or
              (("M" in r["unit_name_hint"] or "公尺" in r["unit_name_hint"]) and r["unit_guess"] != "m"))]
if conflicts:
    L.append("**檔名標註與範圍推測衝突者（須優先人工確認）**：")
    L.append("")
    for r in conflicts:
        L.append("- `%s` —— 檔名說 %s，範圍 %s 推測為 %s" % (
            r["file"], r["unit_name_hint"], r["extent"], r["unit_guess"]))
    L.append("")
L.append("**引用規則**：以檔名標註為準；沒有標註的，用模型範圍初篩後**再目視確認一次**。"
         "在 m 製圖的新案裡用 mm 或 cm 的圖塊，須分別縮放 1/1000 或 1/100。")
L.append("")
flagged = [r for r in rows if r["flags"]]
L.append("**② 有 %d 張帶警示標記**" % len(flagged))
L.append("")
for r in flagged:
    L.append("- `%s`：%s" % (r["file"], "、".join(r["flags"])))
L.append("")
L.append("**③ 比例以 1:20 與 1:50 為大宗**（符合出圖規定的標準比例），"
         "但仍有 23 張未偵測到比例文字 —— 引用前要人工確認。")
L.append("")
L.append("## 三、各分類明細")
L.append("")
for cat, items in by_cat.items():
    L.append("### %s（%d 張）" % (cat, len(items)))
    L.append("")
    L.append("| # | 檔名 | 比例 | 單位判定 | 圖元 | 層 | 備註 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in items:
        sc = "、".join("1:%d" % s for s in r["scales"]) if r["scales"] else "—"
        note = "、".join(r["flags"]) or "—"
        if r["unit_name_hint"]:
            u = "%s（檔名）" % r["unit_name_hint"]
        elif r["unit_guess"] and r["unit_guess"] != "?":
            u = "%s？（範圍推測）" % r["unit_guess"]
        else:
            u = "**待確認**"
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["key"], r["file"], sc, u, r["entities"], r["layers"], note))
    L.append("")
L.append("## 四、系列圖（同一構造物的不同尺寸版本）")
L.append("")
fam = collections.defaultdict(list)
for r in rows:
    fam[r["family"]].append(r)
multi = {k: v for k, v in fam.items() if len(v) > 1}
for k in sorted(multi, key=lambda y: -len(multi[y])):
    L.append("- **%s**：%d 張 → %s" % (
        k, len(multi[k]), "、".join("`%s`" % x["file"] for x in multi[k])))
L.append("")
L.append("> 同一系列優先挑「最新／無警示」的那張；標「誤用」的**不要當範本**。")
L.append("")
L.append("疑似重複下載（檔名帶 `(1)`）—— 內容多半與無尾綴者相同，比對後可刪其一：")
L.append("")
for r in rows:
    if any("疑似重複" in f for f in r["flags"]):
        L.append("- `%s`" % r["file"])
L.append("")
L.append("## 五、與本工作區工具鏈的對應")
L.append("")
L.append("| 本工作區產出的圖 | 可對照／沿用的標準圖 |")
L.append("|---|---|")
L.append("| 擋土牆 S-01／S-02（`make_wall_section.py`）| 「擋土牆」類 38 張：重力式 H=0.6~5.0m、半重力式 H=4m、懸臂式 H=3~7.4m |")
L.append("| 排水溝 D-01／D-02 | 「排水溝渠」類 30 張：L 溝、排水明溝、加蓋溝、截水溝、暗溝、拍漿溝、坡面溝 |")
L.append("| 邊坡 E-01 | 「植生與護坡」6 張 ＋「邊坡防護」4 張（防落石柵）|")
L.append("| 道路刨鋪範圍／現況平面圖 | 「路面與地坪」12 張（AC 加封標準圖、PC 路面、紙模地坪）＋「標誌標線與交安」10 張 |")
L.append("| 預算書工項 | 「集水井與消能」20 張、「箱涵與管涵」11 張、「護欄」11 張可補目前缺的工項單價依據 |")
L.append("")
L.append("### 引用這些圖的三個規矩")
L.append("")
L.append("1. **單位**：162 張是 mm 製圖。要在 m 製圖的新案裡用，須縮放 1/1000，或整張重畫。")
L.append("2. **比例**：只挑標準比例（1:20、1:50、1:100 為大宗）。出圖前用 `check_delivery.py` 驗 E16。")
L.append("3. **字型**：舊圖多為 `Standard` 或其他樣式；沿用前先套 `TOMO`（`gbenor.shx`＋`CHINA1.SHX`），"
         "否則出圖會缺字。")
L.append("")
open(os.path.join(R, "docs", "常用元件標準圖盤點.md"), "w", encoding="utf-8").write("\n".join(L))
print("  已產出 docs\\常用元件標準圖盤點.md")
for cat, items in by_cat.items():
    print("   %-12s %d" % (cat, len(items)))
