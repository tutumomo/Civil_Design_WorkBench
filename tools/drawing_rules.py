"""本項目出圖規定（依 <專案根目錄>\\本項目的出圖規定(不定期新增).md）之共用常數與檢查函式。
規定有新增時，先改 .md，再同步本檔；make_sheet.py、site_basemap.py、check_delivery.py 皆引用本檔。

三項規定：
  1. 圖紙字高  本文 3／附註 4／標題 5 mm（模型空間乘 比例/1000）
  2. 標準比例尺
  3. AutoCAD 出圖樣式：monochrome.ctb；顏色 1~8 對應固定線粗（三級：0.10／0.15~0.20／0.35~0.40 mm）
"""

# ---- 規定 1：圖紙上顯示字高（mm）；模型空間文字須乘以比例係數 K = 比例分母 / 1000 ----
H_BODY = 3.0     # 本文
H_NOTE = 4.0     # 附註
H_TITLE = 5.0    # 標題
TEXT_HEIGHTS = (H_BODY, H_NOTE, H_TITLE)
MIN_TEXT_H = H_BODY

# ---- 規定 2：標準比例尺 ----
# 一般圖（平面／配置）：1/100~1/600 系列，含 1/250、1/1000 及其 10 倍數
_BASE = (100, 200, 250, 300, 400, 500, 600)
_PLAN_SCALES = {b * m for b in _BASE for m in (1, 10, 100)} | {50}

# 細部圖（斷面／配筋／大樣）：三角比例尺上的細部刻度
# 2026-10-28 追加：原本只有 1/100 以上，導致 1:20 斷面圖被 E16 誤擋。
# 1:10／1:20／1:25／1:30／1:40／1:75 都是台灣工程圖常用細部比例，屬標準比例尺。
# 2026-11-04 追加 1:60：工作台「設計圖」比例下拉依使用者指定清單
# （1/10、1/20、1/30、1/40、1/50、1/60、1/100…），1:60 為台灣常用細部比例。
_DETAIL_SCALES = {10, 20, 25, 30, 40, 60, 75}

STANDARD_SCALES = tuple(sorted(_PLAN_SCALES | _DETAIL_SCALES))


def is_standard_scale(n):
    return int(n) in STANDARD_SCALES


def require_standard_scale(n):
    """非標準比例直接中止，避免產出不合規圖面"""
    if not is_standard_scale(n):
        near = sorted(STANDARD_SCALES, key=lambda s: abs(s - n))[:3]
        raise SystemExit(f"比例 1/{n} 不是標準比例尺；可用：{', '.join('1/%d' % s for s in near)} 等")
    return int(n)


def model_h(paper_mm, scale):
    """圖紙字高（mm）→ 模型空間字高（公尺）"""
    return paper_mm * scale / 1000.0

# ---- 規定 3：AutoCAD 出圖樣式（2026-10-29 新增）----
# 線粗依重要性分三級：不重要 0.10、一般 0.15~0.20、重要 0.35~0.40 mm。
# 圖面元件依重要性使用不同顏色，並放在不同圖層；出圖型式 monochrome.ctb（灰階）。
PLOT_STYLE_SHEET = "monochrome.ctb"
PLOT_STYLE_TAG = "TOMO_PLOTSTYLE"          # 寫入 DXF 標頭，讓品管器確認出圖型式

# ACI 色號 → 出圖線粗（mm），完全依 .md 的對應表
LINE_WEIGHT_BY_COLOR = {1: 0.20, 2: 0.20, 3: 0.20, 4: 0.25,
                        5: 0.35, 6: 0.40, 7: 0.15, 8: 0.10}
PLOT_COLORS = tuple(sorted(LINE_WEIGHT_BY_COLOR))

# 重要性 → 預設顏色（避免用 2 黃色：舊規定禁用，出圖偏淡）
IMPORTANCE_COLOR = {"minor": 8, "normal": 7, "line": 1, "mid": 4,
                    "major": 5, "heavy": 6}
FORBIDDEN_TEXT_COLOR = 2

# 現況平面圖標準圖層配色（site_basemap 產出；apply_plot_style 也共用此表）
PLAN_LAYER_COLORS = {
    "00_正射影像_NLSC": 8, "01_公有地地籍影像": 8, "02_電子地圖影像": 8,
    "10_道路邊線_現況": 5, "11_道路用地界_地籍": 1, "12_公有地地籍界線": 8,
    "13_道路中心線_OSM": 1, "14_道路名稱": 7, "20_建物": 4,
    "21_建物_HATCH": 8, "22_水道": 5, "22_水道_HATCH": 8,
    "90_圖框": 7, "91_指北針": 7, "92_比例尺": 7, "93_說明": 7,
}
# 底圖與地籍界預設關閉（負色值＝關閉），套色時要保留這個狀態
PLAN_LAYERS_OFF = ("00_正射影像_NLSC", "01_公有地地籍影像", "02_電子地圖影像", "12_公有地地籍界線")

_DXF_LW = None


def _dxf_lineweights():
    """DXF 370 只接受固定值（見 ezdxf validator）；快取避免重複匯入"""
    global _DXF_LW
    if _DXF_LW is None:
        from ezdxf.lldxf import validator
        _DXF_LW = tuple(v for v in sorted(set(validator.VALID_DXF_LINEWEIGHTS)) if v > 0)
    return _DXF_LW


def dxf_lineweight(mm):
    """規定線粗（mm）→ DXF lineweight 值。
    DXF 沒有 0.10 這個值，取最近可用值（0.10 → 0.09），其餘完全相符。"""
    target = int(round(mm * 100))
    return min(_dxf_lineweights(), key=lambda v: (abs(v - target), v))


def lineweight_for_color(color):
    """ACI 色號 → 規定線粗（mm）；1~8 以外回 None"""
    return LINE_WEIGHT_BY_COLOR.get(int(color))


def plot_color(importance="normal"):
    return IMPORTANCE_COLOR[importance]


def set_layer_plot(layer, color=None, importance=None):
    """把既有圖層設成規定的顏色與線粗（顏色優先於重要性）"""
    c = int(color if color is not None else plot_color(importance or "normal"))
    if c not in LINE_WEIGHT_BY_COLOR:
        raise ValueError(f"顏色 ACI {c} 不在出圖色表 1~8")
    layer.dxf.color = c
    layer.dxf.lineweight = dxf_lineweight(LINE_WEIGHT_BY_COLOR[c])
    return layer


def add_plot_layer(doc, name, color=None, importance=None):
    """建立（或修正）符合出圖樣式的圖層"""
    if name in doc.layers:
        return set_layer_plot(doc.layers.get(name), color, importance)
    c = int(color if color is not None else plot_color(importance or "normal"))
    if c not in LINE_WEIGHT_BY_COLOR:
        raise ValueError(f"顏色 ACI {c} 不在出圖色表 1~8")
    lay = doc.layers.add(name, color=c)
    return set_layer_plot(lay, c)


def tag_plot_style(doc, style=PLOT_STYLE_SHEET):
    """在 DXF 標頭記錄出圖型式，供 check_delivery E18 檢查"""
    cv = doc.header.custom_vars
    if cv.has_tag(PLOT_STYLE_TAG):
        cv.replace(PLOT_STYLE_TAG, style)
    else:
        cv.append(PLOT_STYLE_TAG, style)
    return style


def plot_style_issues(doc, skip=()):
    """檢查顏色→線粗是否相符；回傳 (errors, warnings)。
    只檢查有圖元的圖層；skip 通常放樣板圖層（圖框、Defpoints…）。"""
    from collections import Counter
    used = Counter()
    for l in doc.layouts:
        for e in l:
            used[e.dxf.layer] += 1
    errs, warns = [], []
    for name in sorted(used):
        if name in skip or name not in doc.layers:
            continue
        lay = doc.layers.get(name)
        color = abs(lay.dxf.color)      # 負值＝圖層關閉，顏色仍取絕對值
        if color not in LINE_WEIGHT_BY_COLOR:
            errs.append(f"{name}：顏色 ACI {color} 不在 1~8，沒有對應線粗")
            continue
        want = dxf_lineweight(LINE_WEIGHT_BY_COLOR[color])
        got = lay.dxf.get("lineweight", -3)
        if got != want:
            errs.append(f"{name}：顏色 {color} 應配 {LINE_WEIGHT_BY_COLOR[color]:.2f} mm"
                        f"（DXF {want}），實為 {got}")
    over = []
    for l in doc.layouts:
        for e in l:
            if e.dxf.layer in skip or e.dxf.layer not in doc.layers:
                continue
            lay = doc.layers.get(e.dxf.layer)
            c = e.dxf.get("color", 256)
            lw = e.dxf.get("lineweight", -1)
            bad_c = c not in (256, 0) and c != lay.dxf.color
            bad_lw = lw not in (-1, -2, -3) and lw != lay.dxf.lineweight
            if bad_c or bad_lw:
                over.append(f"{e.dxftype()}@{e.dxf.layer}")
    if over:
        warns.append("圖元自帶顏色／線粗會蓋掉圖層設定：%s%s"
                     % ("、".join(sorted(set(over))[:5]), " …" if len(over) > 5 else ""))
    return errs, warns
