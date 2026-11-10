"""Stable JSON API for the civil-design calculation engines.

The individual engines remain independent command-line tools.  This module is
the common contract used by the workbench, agent integrations and tests.
It deliberately does not reimplement any formula: every calculation is
dispatched to the reviewed engine under ``tools/design``.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping


from catalog.wall import _BLOCK_WALL_SECTION_KEYS, _PASSIVE_RATIO_HINT  # noqa: F401  （外部仍以 design_api 取用）
from catalog.wall import (
    _example_retaining_wall,
    _wall_bar_choices,
    _passive_field_rules,
    _wall_field_rules,
    _block_wall_defaults,
    _example_block_wall,
    _block_wall_field_rules,
    _example_counterfort_wall,
    _counterfort_field_rules,
    _example_mse_wall,
    _mse_field_rules,
    _example_anchored_wall,
    _anchored_field_rules,
)
from catalog.box import (
    _example_box_culvert,
    _box_culvert_field_rules,
)
from catalog.water import (
    _example_channel,
    _example_channel_profile,
    _example_network,
    _example_basin,
    _channel_field_rules,
    _channel_profile_field_rules,
    _hydrology_field_rules,
    _sediment_field_rules,
    _network_field_rules,
)
from catalog.structure import (
    _example_building,
    _building_field_rules,
    _example_footing,
    _example_settlement_assessment,
    _foundation_type_choices,
    _foundation_type_rule,
    _foundation_field_rules,
    _settlement_field_rules,
    _example_channel_cover,
    _channel_cover_field_rules,
    _example_steel_column,
    _steel_column_field_rules,
)
from catalog.slope import (
    _slope_field_rules,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RUN_DIR = ROOT / "out" / "design_workbench" / "runs"


class DesignAPIError(ValueError):
    """Invalid calculator id or input payload."""
















































































CATALOG: list[dict[str, Any]] = [
    {
        "id": "wall_stability",
        "group": "擋土牆",
        "title": "擋土牆穩定與配筋（重力／半重力／懸臂）",
        "oral": ["擋土牆", "重力式", "懸臂式", "半重力式", "滑動", "傾倒", "配筋", "鋼筋"],
        "description": "重力式、懸臂式、半重力式的常時／地震穩定、合力位置與承載檢核；並依牆型分流完成配筋設計（懸臂式莖板＋底板撓曲、重力／半重力式名目構造鋼筋），輸出每延米鋼筋量。",
        "engine": "retaining_wall.py",
        "codes": ["水土保持技術規範 §119～121", "建築物基礎構造設計規範"],
        "limitations": "蛇籠、格籠、砌石、三明治式請用「疊式／砌石擋土牆」，扶壁式、加勁、錨定各有專用計算器；配筋為初步設計（未含施工詳圖、搭接位置與錨定長度詳算），土層參數須用鑽探值替換預設值。",
        "field_rules": _wall_field_rules(),
        "example": _example_retaining_wall(),
    },
    {
        "id": "block_wall",
        "group": "擋土牆",
        "title": "疊式／砌石擋土牆",
        "oral": ["蛇籠", "箱籠", "格籠", "砌石", "漿砌", "乾砌", "卵石牆", "疊式擋土牆"],
        "description": "蛇籠（箱籠）、格籠、漿砌／乾砌石擋土牆；逐層界面與基底的滑動、傾倒、合力位置，基底承載，以及 §118 有效高、每層高、牆面坡度與石材長徑限制。",
        "engine": "block_wall.py",
        "codes": ["水土保持技術規範 §118～121"],
        "limitations": "牆趾抵抗力是否計入依「計入牆趾被動土壓力」設定，只計入抗滑；背填黏著力未計；視為透水牆不計靜水壓；網線、格籠構件強度未檢核；整體傾斜蛇籠與牆背懸於填土上的幾何尚未支援。",
        "field_rules": _block_wall_field_rules(),
        "example": _example_block_wall(),
    },
    {
        "id": "counterfort_wall",
        "group": "擋土牆",
        "title": "扶壁式擋土牆",
        "oral": ["扶壁", "扶壁式", "高擋土牆", "counterfort"],
        "description": "扶壁式擋土牆常時／地震穩定、合力位置與承載；牆板與踵板以扶壁為支承之連續版、趾板懸臂、扶壁 T 梁拉力筋與箍筋、牆板／踵板繫筋；可依牆高反推斷面。",
        "engine": "counterfort_wall.py",
        "codes": ["水土保持技術規範 §118 五、§119～121", "混凝土結構設計規範（100.06.09 版）"],
        "limitations": "牆板／踵板採連續版係數與 Huntington 簡化，非雙向版精算；牆趾抵抗力是否計入依「計入牆趾被動土壓力」設定，只計入抗滑；黏著力與地下水未計；載重組合採 100 年版慣例。",
        "field_rules": _counterfort_field_rules(),
        "example": _example_counterfort_wall(),
    },
    {
        "id": "mse_wall",
        "group": "擋土牆",
        "title": "加勁擋土牆",
        "oral": ["加勁", "加勁擋土牆", "加勁土壤", "土工格網", "格網", "MSE", "鋼條帶"],
        "description": "加勁土壤構造物外部穩定（滑動、傾倒、偏心、Meyerhof 承載，含地震）與逐層內部穩定（拉斷、拉出、錨定長度，含地震）；FHWA 簡化法。",
        "engine": "mse_wall.py",
        "codes": ["水土保持技術規範 §118 六(三)、§119～120", "FHWA-NHI-10-024"],
        "limitations": "RC 面版僅做單向版初步配筋；面版－加勁材連接與局部承壓須輸入產品容量才檢核；吊裝、複合滑動與整體圓弧滑動未檢核；F*、α 為保守預設值；未計靜水壓。",
        "field_rules": _mse_field_rules(),
        "example": _example_mse_wall(),
    },
    {
        "id": "anchored_wall",
        "group": "擋土牆",
        "title": "錨定擋土牆",
        "oral": ["錨定", "錨定擋土牆", "地錨", "背拉", "地錨擋土牆", "岩錨", "anchor"],
        "description": "地錨背拉 RC 牆面：視土壓包絡或三角形土壓、牆面連續梁支點反力；每排地錨抗張材、錨碇段長、自由段長、鎖定荷重、承壓鈑壓應力與沖剪；基底滑動與承載；牆面雙向配筋。",
        "engine": "anchored_wall.py",
        "codes": ["水土保持技術規範 §118 八、§119～120", "公路邊坡工程設計規範（104.12）第六章",
                  "混凝土結構設計規範（100.06.09 版）", "FHWA GEC-4"],
        "limitations": "整體（深層）穩定未檢核，須另做邊坡穩定分析；握裹強度須證明試驗確認；牆面為連續梁＋p·sh²/10 近似；黏土包絡、地下水與黏著力未計。",
        "field_rules": _anchored_field_rules(),
        "example": _example_anchored_wall(),
    },
    {
        "id": "box_culvert",
        "group": "箱涵",
        "title": "單孔／雙孔／三孔箱涵",
        "oral": ["箱涵", "單孔", "雙孔", "三孔", "涵洞", "覆土", "出水高", "進口控制", "出口控制", "頭水"],
        "description": "參數化箱涵平面剛架、土水壓與 H-20／H-20 S-16／40T 拖車車載、內外側逐面配筋（正負彎矩包絡）、縱向分佈筋、裂縫與鋼筋量概估、撓曲／剪力／軸彎互制、浮力，以及附錄 N／O 進口／出口控制水理。",
        "engine": "box_culvert.py",
        "codes": ["公路排水設計規範", "公路橋梁設計規範", "水土保持技術規範 §87", "建築物混凝土結構設計規範"],
        "limitations": "翼牆與端牆只檢核有輸入的幾何值（§6.5），不檢核沖刷深度；低水頭出口控制未做迴水曲線；配筋已做內外側分層、縱向分佈筋與內角加腋處之角隅補強筋（X 形交叉斜筋，構造筋），但仍未計施工階段、開口補強、錨定／搭接長度細節與正式配筋詳圖；車載與其他載重共用 load_factor，未拆分靜載／活載因數。",
        "field_rules": _box_culvert_field_rules(),
        "example": _example_box_culvert(),
    },
    {
        "id": "channel_hydraulics",
        "group": "排水系統",
        "title": "排水溝水力檢核／選配",
        "oral": ["排水溝", "渠道", "曼寧", "流速", "出水高", "通水容量"],
        "description": "矩形明渠正常水深、容量、流速、福祿數、出水高與最小斷面選配。",
        "engine": "channel_hydraulics.py",
        "codes": ["水土保持技術規範 §78", "水土保持技術規範 §83～86"],
        "limitations": "穩定等速流；迴水、漸變水面線、跌水消能與連接井損失需另案分析。",
        "field_rules": _channel_field_rules(),
        "example": _example_channel(),
    },
    {
        "id": "channel_profile",
        "group": "排水系統",
        "title": "排水溝水面線（迴水）",
        "oral": ["水面線", "迴水", "漸變水面線", "標準步法", "M1", "M2", "S2", "出水高檢核"],
        "description": "矩形／梯形渠道標準步法水面線：自由出流或指定下游控制水深，逐段向上游演算水深、流速、福祿數與剖面型態，並檢核出水高與容許流速。",
        "engine": "channel_profile.py",
        "codes": ["水土保持技術規範 §84～86", "公路排水設計規範第四章"],
        "limitations": "一維緩變流；不處理水躍、橋涵束縮、側流入流、彎道二次流與分段糙度變化；超臨界段僅供參考。",
        "field_rules": _channel_profile_field_rules(),
        "example": _example_channel_profile(),
    },
    {
        "id": "channel_cover",
        "group": "排水系統",
        "title": "RC 路側溝加蓋（溝蓋版＋植筋）",
        "oral": [
            "溝蓋", "加蓋", "暗溝", "路側溝加蓋", "溝蓋板", "明溝加蓋", "植筋",
            "溝蓋配筋", "溝蓋載重",
        ],
        "description": (
            "既有 RC 明溝加蓋：HS20-44 後輪載重（可乘重型貨車係數 1.25）下，"
            "溝蓋版撓曲、剪力、裂縫、撓度，溝壁頂承壓，以及黏結式植筋拉力、"
            "剪力與拉剪互制。"
        ),
        "engine": "channel_cover.py",
        "codes": [
            "公路橋梁設計規範（98.12 初版；104.04.13／109.01.03 修訂）§3.7.6、§4.3、§7.1.5、§9",
            "建築物混凝土結構設計規範（112.08.10）§17.6.5、§17.7、§17.9、§22.9",
            "公路工程施工規範（112.02.22）§01525 施工縫及植筋",
        ],
        "limitations": (
            "只做簡支版正彎矩，不把 20 cm 溝壁當固接支承；植筋拉力需求採抗掀名義比例"
            "（非規範明文）。未檢核既有溝壁側向穩定、基礎承載、疲勞、溫度與地震；"
            "植筋膠須有黏結式錨栓評估準則（ACI 355.4）認證並以產品資料覆核。"
        ),
        "field_rules": _channel_cover_field_rules(),
        "example": _example_channel_cover(),
    },
    {
        "id": "drainage_network",
        "group": "排水系統",
        "title": "排水網路流量分配",
        "oral": ["排水系統", "排水網路", "匯流", "分流", "管渠", "容量"],
        "description": "節點—連線網路、指定或容量權重分流、渠道／圓管／箱涵／指定容量檢核。",
        "engine": "drainage_network.py",
        "codes": ["水土保持技術規範 §82～87", "公路排水設計規範", "下水道工程設施標準"],
        "limitations": "目前為穩定尖峰流量平衡；尚無儲蓄、時間延遲、迴水與漸變水面線。",
        "field_rules": _network_field_rules(),
        "example": _example_network(),
    },
    {
        "id": "detention_basin",
        "group": "滯洪池",
        "title": "滯洪池調洪演算",
        "oral": ["滯洪池", "滯洪", "調洪", "Modified Puls", "容許出流", "溢洪道"],
        "description": "水位—面積—蓄水曲線、孔口／堰出流、Modified Puls 演算、最高水位與出水高。",
        "engine": "detention_basin.py",
        "codes": ["水土保持技術規範 §94～97", "水土保持技術規範 §160、§166"],
        "limitations": "孔口以中心水頭計算，水位低於孔口中心時出流以 0 計；尚無多峰雨型、閘門操作、下游迴水、池堤穩定與緊急溢洪道完整設計。",
        "example": _example_basin(),
        "field_rules": {
            "outlet.orifice.invert_m": {
                "label": "孔底高程 (m)",
                "hint": "自池底起算；孔口中心取孔底＋孔徑/2，以中心水頭計算出流",
            },
        },
    },
    {
        "id": "building_frame",
        "group": "建築結構",
        "title": "建築 RC 平面剛架",
        "oral": ["樑", "柱", "樑柱", "建築構架", "樓層", "地震", "層間位移"],
        "description": "規則 2D RC 剛架、靜載／活載／等值靜力地震、內力包絡、樑柱初步配筋與層間位移。",
        "engine": "building_frame.py",
        "codes": ["建築技術規則建築構造編", "建築物耐震設計規範", "建築物混凝土結構設計規範"],
        "limitations": "代表性 2D 平面、單軸彎矩；未計 3D 扭轉、雙向彎矩、二階效應、接頭剪力與錨定。",
        "field_rules": _building_field_rules(),
        "example": _example_building(),
    },
    {
        "id": "foundation_isolated",
        "group": "建築基礎",
        "title": "獨立基腳",
        "oral": ["獨立基腳", "基腳", "基礎承載", "沖剪", "柱腳", "淺基礎"],
        "description": "矩形獨立基腳承載應力、全面受壓、滑動、單向剪力、沖剪、撓曲與可選分層沉陷檢核。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範 §4", "建築物混凝土結構設計規範"],
        "limitations": "沉陷須提供土層參數；可分層 2:1 法估算瞬時沉陷，選填 consolidation_layers 時可加算壓密與次壓縮。單一基腳不計算差異沉陷或角變量，請另用 settlement_assessment；液化與土壤—結構互制未計。",
        "field_rules": _foundation_field_rules(),
        "example": _example_footing("isolated"),
    },
    {
        "id": "foundation_combined",
        "group": "建築基礎",
        "title": "聯合基腳",
        "oral": ["聯合基腳", "兩柱基礎", "合併基腳", "條形基礎"],
        "description": "剛性聯合基腳線性基底反力、縱向撓曲、沖剪、柱載重分配與可選分層沉陷檢核。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範 §4", "建築物混凝土結構設計規範"],
        "limitations": "縱向條帶分析；沉陷須提供土層，可算分層瞬時、壓密與次壓縮總沉陷。橫向柱下局部分析、三維沖剪、差異沉陷與角變量須另用 settlement_assessment；土壤—結構互制未計。",
        "field_rules": _foundation_field_rules(),
        "example": _example_footing("combined"),
    },
    {
        "id": "foundation_pile",
        "group": "建築基礎",
        "title": "樁帽／樁群載重分配",
        "oral": ["樁帽", "樁群", "基樁", "樁基礎", "軸力分配"],
        "description": "等軸勁度與剛性樁帽假設下的樁群軸力分配、最大樁壓與拉力檢查。",
        "engine": "foundation_design.py",
        "codes": ["建築物基礎構造設計規範"],
        "limitations": "未做側向樁、群樁效率、沉陷、上浮與完整樁帽配筋。",
        "example": _example_footing("pile"),
    },
    {
        "id": "settlement_assessment",
        "group": "建築基礎",
        "title": "沉陷與角變量評估",
        "oral": [
            "沉陷",
            "壓密沉陷",
            "次壓縮",
            "差異沉陷",
            "角變量",
            "基礎變形",
            "相鄰柱沉陷",
        ],
        "description": "分層瞬時沉陷、單向度壓密、次壓縮、總沉陷，以及扣除剛體轉動後的多基礎差異沉陷與角變量。",
        "engine": "foundation_design.py",
        "codes": [
            "建築物基礎構造設計規範 §4.4.2～4.4.7",
            "建築物基礎構造設計規範 §4.5.3～4.5.4",
        ],
        "limitations": "地層採分層 2:1 應力擴散；差異沉陷為幾何篩檢，未做土壤—結構互制、筏基有限元、側向樁或三維勁度重分配。",
        "field_rules": _settlement_field_rules(),
        "example": _example_settlement_assessment(),
    },
    {
        "id": "hydrology",
        "group": "水文",
        "title": "集水區設計流量",
        "oral": ["水文", "降雨強度", "合理化公式", "逕流係數", "集流時間", "設計流量"],
        "description": "水土保持技術規範第 16～19 條降雨強度、逕流係數、集流時間與合理化公式。",
        "engine": "hydrology.py",
        "codes": ["水土保持技術規範 §16～19"],
        "limitations": "降雨與土地利用參數必須用當地資料；第 16 條公式推估值是下限。",
        "field_rules": _hydrology_field_rules(),
        "example": {
            "P_mm": 2000.0,
            "return_period_yr": 25.0,
            "area_ha": 2.0,
            "condition": "丘陵地或森林",
            "developed": False,
            "upper_c": False,
            "area_type": "集水區",
            "l_m": 100.0,
            "v_ms": 0.4,
            "L_km": 0.0,
            "H_km": 0.0,
        },
    },
    {
        "id": "sediment_basin",
        "group": "水保設施",
        "title": "沉砂池容量",
        "oral": ["沉砂池", "泥砂生產量", "USLE", "土壤流失", "沉砂"],
        "description": "USLE、泥砂生產量、容量下限、深度與可選池壁／出水口／溢流檢核。",
        "engine": "sediment_basin.py",
        "codes": ["水土保持技術規範 §35、§92～93", "下水道工程設施標準 §12"],
        "limitations": "結構與出水口為初步檢核；未計池外土壓、地震、滲流、阻塞與消能。",
        "field_rules": _sediment_field_rules(),
        "example": {
            "area_ha": 2.0,
            "excavated_ha": 1.2,
            "impervious_ha": 0.2,
            "kind": "temporary",
            "years": 1.0,
            "Am": 40.0,
            "depth_m": 2.0,
        },
    },
    {
        "id": "slope_stability",
        "group": "邊坡",
        "title": "邊坡穩定分析",
        "oral": ["邊坡", "坡角", "無限邊坡", "圓弧滑動", "安全係數"],
        "description": "無限邊坡法、Fellenius 坡趾圓與容許坡角反算，依永久／臨時與工況查最小 FS。",
        "engine": "slope_stability.py",
        "codes": ["水土保持技術規範 §72～73"],
        "limitations": "均質土層與坡趾圓家族；分層土、軟弱夾層與滲流網須另行分析。",
        "field_rules": _slope_field_rules(),
        "example": {
            "height_m": 5.0,
            "slope_angle_deg": 25.0,
            "cohesion_kpa": 0.0,
            "unit_weight_kn_m3": 18.0,
            "stage": "永久性",
            "condition": "平時",
            "friction_deg": 35.0,
        },
    },
    {
        "id": "rc_beam",
        "group": "RC 構材",
        "title": "RC 梁斷面配筋",
        "oral": ["梁配筋", "樑配筋", "撓曲", "剪力", "裂縫"],
        "description": "矩形梁撓曲、最小鋼筋、剪力與裂縫控制，輸出建議筋號與間距。",
        "engine": "rc_design.py",
        "codes": ["建築物混凝土結構設計規範"],
        "limitations": "單筋矩形梁、常重混凝土；未計扭力、疲勞、耐震塑鉸與接頭細節。",
        "example": {
            "Mu_kNm": 180.0,
            "Vu_kN": 120.0,
            "b_mm": 350.0,
            "h_mm": 750.0,
            "fc_mpa": 28.0,
            "fy_mpa": 420.0,
        },
    },
    {
        "id": "rc_column",
        "group": "RC 構材",
        "title": "RC 柱軸彎互制",
        "oral": ["柱配筋", "軸彎互制", "柱設計", "軸力", "彎矩"],
        "description": "矩形柱軸力—彎矩互制曲線與鋼筋配置初步選筋。",
        "engine": "rc_design.py",
        "codes": ["建築物混凝土結構設計規範"],
        "limitations": "單軸彎矩、對稱鋼筋配置；雙向彎矩、二階效應、剪力與耐震圍束須另做。",
        "example": {
            "Pu_kN": 1600.0,
            "Mu_kNm": 280.0,
            "b_mm": 450.0,
            "h_mm": 450.0,
            "fc_mpa": 28.0,
            "fy_mpa": 420.0,
        },
    },
    {
        "id": "steel_column",
        "group": "鋼結構",
        "title": "鋼構柱、柱腳基板與基礎螺栓",
        "oral": [
            "鋼柱",
            "柱腳",
            "基板",
            "基礎螺栓",
            "錨栓",
            "鋼構設計",
        ],
        "description": (
            "H 型鋼柱軸壓、撓曲與梁柱互制檢核，柱腳混凝土承壓、基板厚度、"
            "基礎錨栓群拉力、剪力傳遞與拉剪互制聯合檢核。"
        ),
        "engine": "steel_column.py",
        "codes": ["建築物鋼結構設計技術規範（99.09.16）"],
        "limitations": (
            "只做露出式柱腳與澆置前預埋錨栓；埋入式柱腳、後置錨栓與特殊預埋件不在本模組。"
            "基板厚度採簡化懸臂法，雙向彎矩採彈性錨栓群法，"
            "未做柱腹板剪力、焊道、灌漿與埋入式細部，須人工覆核。"
        ),
        "field_rules": _steel_column_field_rules(),
        "example": _example_steel_column(),
    },
]


def _catalog_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in CATALOG}


def list_calculators() -> list[dict[str, Any]]:
    """Return JSON-safe calculator metadata without implementation objects."""

    return [
        {
            "id": item["id"],
            "group": item["group"],
            "title": item["title"],
            "oral": item["oral"],
            "description": item["description"],
            "engine": item["engine"],
            "codes": item["codes"],
            "limitations": item["limitations"],
            "field_rules": item.get("field_rules", {}),
            "example": item["example"],
        }
        for item in CATALOG
    ]


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DesignAPIError(f"{name} 必須是 JSON 物件")
    return value


def _num(data: Mapping[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value in (None, ""):
        if default is None:
            raise DesignAPIError(f"缺少參數 {key}")
        return float(default)
    return float(value)


def _checks_from_common(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("checks")
    if isinstance(raw, list):
        checks = [dict(x) for x in raw if isinstance(x, Mapping)]
        for check in checks:
            if check.get("limit") is None and check.get("required") is not None:
                check["limit"] = check["required"]
                check["relation"] = "ge"
        return checks

    checks: list[dict[str, Any]] = []
    for design in result.get("designs") or []:
        if not isinstance(design, Mapping):
            continue
        if design.get("kind") == "beam":
            cap = (design.get("flexure") or {}).get("phiMn_kNm")
            item = "%s 梁撓曲" % design.get("member", "")
        else:
            cap = (design.get("chosen") or {}).get("phiMn_available_kNm")
            item = "%s 柱軸彎" % design.get("member", "")
        checks.append(
            {
                "item": item,
                "value": design.get("Mu_kNm"),
                "limit": cap,
                "ok": bool(design.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
    for drift in result.get("drift") or []:
        if isinstance(drift, Mapping):
            checks.append(
                {
                    "item": "第 %s 層層間位移比" % drift.get("storey", ""),
                    "value": drift.get("max_storey_drift_ratio"),
                    "limit": drift.get("limit"),
                    "ok": bool(drift.get("ok")),
                    "unit": "-",
                    "relation": "le",
                }
            )
    return checks


def _checks_from_rc(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    flex = value.get("flexure") or {}
    if flex:
        checks.append(
            {
                "item": "撓曲",
                "value": flex.get("Mu_kNm"),
                "limit": flex.get("phiMn_kNm"),
                "ok": bool(flex.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
    shear = value.get("shear") or {}
    if shear:
        checks.append(
            {
                "item": (
                    "剪力（含箍筋）"
                    if shear.get("stirrup")
                    else "混凝土剪力"
                ),
                "value": shear.get("Vu_kN"),
                "limit": shear.get(
                    "phiVn_kN", shear.get("phiVc_kN")
                ),
                "ok": bool(shear.get("ok")),
                "unit": "kN",
                "relation": "le",
            }
        )
    crack = value.get("crack") or {}
    if crack and crack.get("w_mm") is not None:
        checks.append(
            {
                "item": "裂縫寬度",
                "value": crack.get("w_mm"),
                "limit": crack.get("limit_mm"),
                "ok": bool(crack.get("ok")),
                "unit": "mm",
                "relation": "le",
            }
        )
    chosen = value.get("chosen") or {}
    if chosen:
        checks.append(
            {
                "item": "柱軸彎互制",
                "value": value.get("Mu_kNm"),
                "limit": chosen.get("phiMn_available_kNm"),
                "ok": bool(chosen.get("ok")),
                "unit": "kN·m",
                "relation": "le",
            }
        )
        if chosen.get("spacing_ok") is not None:
            checks.append(
                {
                    "item": "柱縱向鋼筋淨間距",
                    "value": chosen.get("centre_spacing_mm"),
                    "limit": chosen.get("min_spacing_mm"),
                    "ok": bool(chosen.get("spacing_ok")),
                    "unit": "mm",
                    "relation": "ge",
                }
            )
    return checks


def _format_fallback(calculator: str, result: Mapping[str, Any]) -> str:
    if calculator == "rc_beam":
        flex = result.get("flexure") or {}
        shear = result.get("shear") or {}
        crack = result.get("crack") or {}
        stirrup = shear.get("stirrup") or {}
        return "\n".join(
            [
                "RC 梁斷面：%s × %s mm"
                % (flex.get("b_mm", "-"), flex.get("h_mm", "-")),
                "  [%s] 撓曲：%s@%s mm，φMn = %s kN·m（Mu = %s）"
                % (
                    "OK" if flex.get("ok") else "NG",
                    flex.get("bar", "-"),
                    flex.get("spacing_mm", "-"),
                    flex.get("phiMn_kNm", "-"),
                    flex.get("Mu_kNm", "-"),
                ),
                "  [%s] 剪力：%s@%s mm 兩肢箍，φVn = %s kN（Vu = %s）"
                % (
                    "OK" if shear.get("ok") else "NG",
                    stirrup.get("bar", "-"),
                    stirrup.get("spacing_mm", "-"),
                    shear.get("phiVn_kN", "-"),
                    shear.get("Vu_kN", "-"),
                ),
                "  [%s] 裂縫：%s mm（限 %s mm）"
                % (
                    "OK" if crack.get("ok") else "NG",
                    crack.get("w_mm", "-"),
                    crack.get("limit_mm", "-"),
                ),
                "依據《混凝土結構設計規範》100.06.09 版；仍須技師覆核。",
            ]
        )
    if calculator == "rc_column":
        chosen = result.get("chosen") or {}
        ties = result.get("ties") or {}
        return "\n".join(
            [
                "RC 柱：%s × %s mm，Pu = %s kN、Mu = %s kN·m"
                % (
                    result.get("b_mm", "-"),
                    result.get("h_mm", "-"),
                    result.get("Pu_kN", "-"),
                    result.get("Mu_kNm", "-"),
                ),
                "  [%s] 軸彎互制：%s 根 %s（As = %s mm²），"
                "φMn = %s kN·m"
                % (
                    "OK" if chosen.get("ok") else "NG",
                    chosen.get("bars_total", "-"),
                    chosen.get("bar", "-"),
                    chosen.get("As_mm2", "-"),
                    chosen.get("phiMn_available_kNm", "-"),
                ),
                "  柱箍筋初步：%s@%s mm"
                % (ties.get("bar", "-"), ties.get("spacing_mm", "-")),
                "依據《混凝土結構設計規範》100.06.09 版；"
                "耐震圍束與接頭另計，仍須技師覆核。",
            ]
        )
    lines = ["計算器：%s" % calculator]
    checks = _checks_from_common(result)
    for check in checks:
        lines.append(
            "  [%s] %s：%s（限 %s %s）"
            % (
                "OK" if check.get("ok") else "NG",
                check.get("item", ""),
                check.get("value"),
                check.get("limit"),
                check.get("unit", ""),
            )
        )
    return "\n".join(lines)


_WALL_REBAR_KEYS = (
    "stem_bar",
    "base_bar",
    "mass_wall_face_bar",
    "mass_wall_face_spacing_mm",
    "mass_wall_base_bar",
    "mass_wall_base_spacing_mm",
)


def _wall_concrete(payload: Mapping[str, Any]) -> dict[str, Any]:
    """把 UI 的混凝土／鋼筋設定轉成 rc_design 的 cc 覆寫值。"""
    cc: dict[str, Any] = {}
    nested = payload.get("concrete")
    if isinstance(nested, Mapping):
        for key in ("fc_mpa", "fy_mpa", "cover_mm"):
            if nested.get(key) not in (None, ""):
                cc[key] = float(nested[key])
    for key in ("fc_mpa", "fy_mpa", "cover_mm"):
        if payload.get(key) not in (None, ""):
            cc[key] = float(payload[key])
    return cc


def _rebar_check(item, value, limit, unit, ok, *, relation="ge", decimals=3):
    return {
        "item": item,
        "value": round(float(value), decimals),
        "limit": round(float(limit), decimals),
        "unit": unit,
        "ok": bool(ok),
        "relation": relation,
    }


def _wall_rebar_checks(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把配筋設計轉成工作台檢核列（item/value/limit/unit/ok）。"""
    wt = str(design.get("wall_type") or "")
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        rho = float(mass.get("temperature_ratio") or 0.0)
        lim = float(mass.get("temperature_min") or 0.002)
        return [_rebar_check("牆面構造鋼筋比（ρ ≥ 0.002）", rho, lim, "-",
                             rho >= lim - 1e-9, decimals=4)]

    checks: list[dict[str, Any]] = []

    def add(prefix, member):
        main = member.get("main") or {}
        shear = member.get("shear") or {}
        crack = member.get("crack") or {}
        if main.get("phiMn_kNm") is not None:
            checks.append(_rebar_check(
                prefix + " 撓曲（φMn ≥ Mu）",
                main["phiMn_kNm"], main.get("Mu_kNm") or 0.0,
                "kN·m/m", main.get("ok")))
        if shear.get("phiVc_kN") is not None:
            checks.append(_rebar_check(
                prefix + " 剪力（φVc ≥ Vu）",
                shear["phiVc_kN"], shear.get("Vu_kN") or 0.0,
                "kN/m", shear.get("ok")))
        if crack.get("w_mm") is not None:
            checks.append(_rebar_check(
                prefix + " 裂縫寬度 ≤ 0.3 mm",
                crack["w_mm"], crack.get("limit_mm") or 0.3,
                "mm", crack.get("ok"), relation="le"))

    structural = design.get("structural") or {}
    stem = structural.get("stem") or {}
    if stem:
        add("牆身", stem)
    base = structural.get("base") or {}
    for member in base.get("members") or []:
        add(member.get("member") or "底板", member)
    return checks


def _wall_rebar_lines(design: Mapping[str, Any]) -> list[str]:
    """配筋設計的人看文字（接在穩定分析 summary 後）。"""
    def sp(value):
        try:
            return "%g" % float(value)
        except (TypeError, ValueError):
            return str(value or "-")

    wt = str(design.get("wall_type") or "")
    total = float(design.get("total_kg_per_m") or 0.0)
    rate = float(design.get("lap_allowance") or 0.0)
    if rate <= 0:
        import rc_design as RC
        rate = RC.LAP_ALLOWANCE
    lines = ["", "配筋設計（含 %.0f%% 搭接、錨定與損耗）：%.2f kg/m"
              % (rate * 100.0, total)]
    if wt in ("gravity", "semigravity"):
        mass = design.get("mass") or {}
        lines.append(
            "  牆面 %s@%s 雙向＋底部縱筋 %s@%s；構造鋼筋比 %.4f（≥ %.4f）" % (
                mass.get("face_bar", "-"), sp(mass.get("face_spacing_mm")),
                mass.get("base_bar", "-"), sp(mass.get("base_spacing_mm")),
                float(mass.get("temperature_ratio") or 0.0),
                float(mass.get("temperature_min") or 0.002)))
        lines.append("  重力式／半重力式以自重穩定，牆身不設撓曲主筋")
        return lines

    structural = design.get("structural") or {}
    for label, member in (("牆身", structural.get("stem") or {}),):
        main = member.get("main") or {}
        if main.get("bar"):
            lines.append(
                "  [%s] %s撓曲：%s@%s mm（As=%.0f mm²/m）；φMn=%.1f ≥ Mu=%.1f kN·m/m" % (
                    "OK" if main.get("ok") else "NG", label,
                    main.get("bar"), sp(main.get("spacing_mm")),
                    main.get("As_prov_mm2") or 0.0,
                    main.get("phiMn_kNm") or 0.0, main.get("Mu_kNm") or 0.0))
        shear = member.get("shear") or {}
        if shear.get("phiVc_kN") is not None:
            lines.append(
                "  [%s] 牆身剪力：φVc=%.1f ≥ Vu=%.1f kN/m" % (
                    "OK" if shear.get("ok") else "NG",
                    shear["phiVc_kN"], shear.get("Vu_kN") or 0.0))
        crack = member.get("crack") or {}
        if crack.get("w_mm") is not None:
            lines.append(
                "  [%s] 牆身裂縫：w=%.3f mm（限 %.1f mm）" % (
                    "OK" if crack.get("ok") else "NG",
                    crack["w_mm"], crack.get("limit_mm") or 0.3))
    base = structural.get("base") or {}
    for member in base.get("members") or []:
        main = member.get("main") or {}
        if not main.get("bar"):
            continue
        lines.append(
            "  [%s] %s：%s@%s mm；φMn=%.1f ≥ Mu=%.1f kN·m/m" % (
                "OK" if member.get("ok") else "NG", member.get("member", "底板"),
                main.get("bar"), sp(main.get("spacing_mm")),
                main.get("phiMn_kNm") or 0.0, main.get("Mu_kNm") or 0.0))
    rows = (design.get("kg") or {}).get("rows") or []
    if rows:
        detail = "、".join("%s %.2f" % (r.get("item", ""), r.get("kg_per_m") or 0.0)
                          for r in rows)
        lines.append("  鋼筋量明細（kg/m）：" + detail)
    return lines


def _attach_wall_rebar(q, res, payload):
    """在穩定分析結果上附加配筋設計（重力／半重力／懸臂）。"""
    import rc_design as RC

    q2 = dict(q)
    for key in _WALL_REBAR_KEYS:
        if payload.get(key) not in (None, ""):
            q2[key] = payload[key]
    design = RC.design_wall_rebar(q2, res, _wall_concrete(payload))
    res["rebar"] = design
    res["rebar_summary"] = _wall_rebar_lines(design)
    res["checks"] = list(res.get("checks") or []) + _wall_rebar_checks(design)
    res["pass"] = bool(res.get("pass")) and bool(design.get("ok"))
    return res


def _run_wall(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import retaining_wall as RW

    q = payload.get("section") or payload.get("quantities", {}).get("values") or payload
    soil = payload.get("soil")
    seismic = payload.get("seismic")
    if payload.get("kh") is not None:
        seismic = {"kh": float(payload["kh"])}
    kh = float((seismic or {}).get("kh") or 0.0)
    if payload.get("size"):
        wall_type = str(q.get("wall_type") or "gravity").strip().lower()
        if wall_type not in ("gravity", "cantilever"):
            raise DesignAPIError("自動試算斷面目前支援重力式（gravity）或懸臂式（cantilever）；半重力式請手動微調斷面。")

        def _rebar_ok(cand, cand_res):
            import rc_design as RC
            q2 = dict(cand)
            for key in _WALL_REBAR_KEYS:
                if payload.get(key) not in (None, ""):
                    q2[key] = payload[key]
            return bool(RC.design_wall_rebar(q2, cand_res, _wall_concrete(payload)).get("ok"))

        best, tried = RW.size_section(
            float(q.get("height_m") or 3.0),
            soil=soil,
            wall_type=wall_type,
            kh=kh,
            toe_passive={
                k: q[k]
                for k in ("toe_soil_depth_m", "include_passive", "passive_ratio")
                if k in q
            },
            extra_check=_rebar_ok,
        )
        if best is None:
            raise DesignAPIError("搜尋 %d 組斷面仍無法全部通過，請檢查土壤承載力／摩擦角或降低牆高" % tried)
        res = dict(best["res"])
        res["sized_section"] = dict(best["q"])
        res["warnings"] = [
            "已依牆高自動反推合格最小斷面（搜尋 %d 組）：%s"
            % (tried, json.dumps(best["q"], ensure_ascii=False))
        ] + list(res.get("warnings") or [])
        return _attach_wall_rebar(best["q"], res, payload)
    res = RW.analyse(q, soil=soil, seismic=seismic)
    return _attach_wall_rebar(q, res, payload)


def _run_block_wall(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import block_wall as BW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh"}
    }
    seismic = payload.get("seismic")
    if payload.get("kh") is not None:
        seismic = {"kh": float(payload["kh"])}
    return BW.analyse(q, soil=payload.get("soil"), seismic=seismic)


def _run_counterfort(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import counterfort_wall as CW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh", "concrete", "size"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    if payload.get("size"):
        out = CW.size_section(
            float(q["height_m"]), payload.get("soil"), kh, payload.get("concrete"),
            front_soil_depth_m=float(q.get("front_soil_depth_m") or 0.0),
            counterfort_spacing_m=q.get("counterfort_spacing_m"),
            include_passive=q.get("include_passive"),
            passive_ratio=q.get("passive_ratio"),
        )
        if not out["found"]:
            raise DesignAPIError("搜尋 %d 組斷面仍無法全部通過，請檢查土壤參數或改用其他牆型" % out["tried"])
        res = dict(out["result"])
        res["sized_section"] = out["section"]
        res["warnings"] = ["已依牆高自動反推斷面（搜尋 %d 組）：%s"
                           % (out["tried"], json.dumps(out["section"], ensure_ascii=False))] + list(res["warnings"])
        return res
    return CW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh}, concrete=payload.get("concrete"))


def _run_mse(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import mse_wall as MW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    return MW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh})


def _run_anchored(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import anchored_wall as AW

    q = payload.get("section") or {
        k: v for k, v in payload.items() if k not in {"soil", "seismic", "kh", "concrete"}
    }
    kh = float(payload.get("kh") or (payload.get("seismic") or {}).get("kh") or 0.0)
    return AW.analyse(q, soil=payload.get("soil"), seismic={"kh": kh}, concrete=payload.get("concrete"))


def _run_box(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import box_culvert as BC

    section = payload.get("section") or payload
    params = payload.get("analysis") or {}
    section_params = section if isinstance(section, Mapping) else {}
    traffic_type = payload.get("traffic_type") or section_params.get("traffic_type")
    traffic_load_kpa = float(
        payload.get("traffic_load_kpa", section_params.get("traffic_load_kpa", 0.0))
        or 0.0
    )
    traffic_lanes = int(
        payload.get("traffic_lanes", section_params.get("traffic_lanes", 4)) or 4
    )
    impact_raw = payload.get(
        "traffic_impact_factor", section_params.get("traffic_impact_factor")
    )
    impact = (
        float(impact_raw)
        if impact_raw not in (None, "")
        else None
    )
    loss_raw = payload.get(
        "rebar_loss_rate", section_params.get("rebar_loss_rate")
    )
    rebar_loss_rate = float(loss_raw) if loss_raw not in (None, "") else BC.REBAR_LOSS_RATE
    return BC.analyse(
        section,
        design_flow_m3s=float(payload.get("design_flow_m3s", params.get("design_flow_m3s", 0.0)) or 0.0),
        slope=float(payload.get("slope", params.get("slope", 0.005)) or 0.005),
        manning_n=float(payload.get("manning_n", params.get("manning_n", 0.014)) or 0.014),
        soil_unit_weight_kn_m3=float(payload.get("soil_unit_weight_kn_m3", 18.0)),
        soil_phi_deg=float(payload.get("soil_phi_deg", 30.0)),
        surcharge_kpa=float(payload.get("surcharge_kpa", 0.0)),
        traffic_load_kpa=traffic_load_kpa,
        traffic_type=traffic_type,
        traffic_lanes=traffic_lanes,
        traffic_impact_factor=impact,
        groundwater_depth_m=payload.get("groundwater_depth_m"),
        internal_water_depth_m=float(payload.get("internal_water_depth_m", 0.0)),
        load_factor=float(payload.get("load_factor", 1.7)),
        seismic_kh=float(payload.get("seismic_kh", 0.0)),
        freeboard_min_m=float(payload.get("freeboard_min_m", 0.20)),
        allowable_bearing_kpa=payload.get("allowable_bearing_kpa"),
        inlet_type=payload.get("inlet_type") or None,
        tailwater_depth_m=float(payload.get("tailwater_depth_m", 0.0) or 0.0),
        allowable_headwater_m=payload.get("allowable_headwater_m"),
        entrance_loss_ke=payload.get("entrance_loss_ke"),
        hw_d_limit=float(payload.get("hw_d_limit", 1.5) or 1.5),
        outlet_velocity_limit_m_s=payload.get("outlet_velocity_limit_m_s"),
        cover_mm=payload.get("cover_mm"),
        crack_limit_mm=float(payload.get("crack_limit_mm", 0.3) or 0.3),
        bar_preference=str(payload.get("bar_preference", "auto") or "auto"),
        distribution_bar=str(payload.get("distribution_bar", "D13") or "D13"),
        rebar_loss_rate=rebar_loss_rate,
    )


def _run_channel(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_hydraulics as CH

    params = {
        "manning_n": _num(payload, "manning_n", 0.014),
        "freeboard_min_m": _num(payload, "freeboard_min_m", 0.20),
    }
    if payload.get("size"):
        best, tried = CH.size_channel(
            _num(payload, "design_flow_m3s"),
            _num(payload, "slope"),
            params,
        )
        if best is None:
            raise DesignAPIError("搜尋 %d 組 U 型溝斷面仍無法全部通過，請檢查設計流量或縱坡（流速限制 0.8~4.57 m/s）" % tried)
        res = dict(best["res"])
        sized = {"inner_width_m": best["b"], "depth_m": best["h"]}
        res["sized_section"] = sized
        res["warnings"] = [
            "已依設計流量自動反推最小合格斷面（搜尋 %d 組）：內寬 b=%.2f m、溝深 h=%.2f m"
            % (tried, best["b"], best["h"])
        ] + list(res.get("warnings") or [])
        return res
    return CH.analyse(
        _num(payload, "design_flow_m3s"),
        _num(payload, "inner_width_m"),
        _num(payload, "depth_m"),
        _num(payload, "slope"),
        params,
    )


def _run_channel_profile(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_profile as CP

    width = payload.get("bottom_width_m", payload.get("inner_width_m"))
    depth = payload.get("channel_depth_m", payload.get("depth_m"))
    return CP.analyse(
        design_flow_m3s=_num(payload, "design_flow_m3s"),
        bottom_width_m=float(width) if width not in (None, "") else _num(payload, "bottom_width_m"),
        side_slope_h_v=_num(payload, "side_slope_h_v", 0.0),
        slope=_num(payload, "slope"),
        manning_n=_num(payload, "manning_n", 0.014),
        reach_length_m=_num(payload, "reach_length_m"),
        step_m=_num(payload, "step_m", 10.0),
        control_depth_m=payload.get("control_depth_m"),
        channel_depth_m=depth if depth not in (None, "") else None,
        freeboard_min_m=_num(payload, "freeboard_min_m", 0.20),
        minor_loss_coefficient=_num(payload, "minor_loss_coefficient", 0.0),
        velocity_min_m_s=_num(payload, "velocity_min_m_s", 0.0),
        velocity_max_m_s=payload.get("velocity_max_m_s"),
    )


def _run_network(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import drainage_network as DN

    return DN.analyse(payload)


def _run_basin(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import detention_basin as DB

    return DB.analyse(payload)


def _run_building(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import building_frame as BF

    geometry = payload.get("geometry") or payload
    loads = payload.get("loads") or {}
    return BF.analyse(geometry, loads)


def _run_foundation(payload: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    import foundation_design as FD

    geometry = payload.get("geometry") or payload
    load = payload.get("load") or payload
    common = {
        "q_allow_kpa": float(payload.get("q_allow_kpa", 200.0)),
        "fc_mpa": float(payload.get("fc_mpa", 28.0)),
        "fy_mpa": float(payload.get("fy_mpa", 420.0)),
    }
    if kind == "isolated":
        return FD.analyse_isolated_footing(
            load,
            B_m=float(geometry.get("B_m")),
            L_m=float(geometry.get("L_m")),
            thickness_m=float(geometry.get("thickness_m")),
            column_b_m=float(geometry.get("column_b_m")),
            column_l_m=float(geometry.get("column_l_m")),
            cover_mm=float(payload.get("cover_mm", 75.0)),
            friction_coefficient=float(payload.get("friction_coefficient", 0.5)),
            settlement=payload.get("settlement"),
            **common,
        )
    if kind == "combined":
        return FD.analyse_combined_footing(
            payload.get("columns") or [],
            B_m=float(payload.get("B_m")),
            L_m=float(payload.get("L_m")),
            thickness_m=float(payload.get("thickness_m")),
            column_b_m=float(payload.get("column_b_m", 0.4)),
            column_l_m=float(payload.get("column_l_m", 0.4)),
            settlement=payload.get("settlement"),
            **common,
        )
    return FD.pile_group_check(
        payload.get("piles") or [],
        P_kN=float(payload.get("P_kN")),
        Mx_kNm=float(payload.get("Mx_kNm", 0.0)),
        My_kNm=float(payload.get("My_kNm", 0.0)),
        Q_allow_kN=float(payload.get("Q_allow_kN")),
    )


def _run_hydrology(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import hydrology as HY

    return HY.design_flow(
        _num(payload, "P_mm"),
        _num(payload, "return_period_yr"),
        _num(payload, "area_ha"),
        str(payload.get("condition", "丘陵地或森林")),
        developed=bool(payload.get("developed", False)),
        upper_c=bool(payload.get("upper_c", False)),
        l_m=_num(payload, "l_m", 100.0),
        v_ms=_num(payload, "v_ms", 0.4),
        L_km=_num(payload, "L_km", 0.0),
        H_km=_num(payload, "H_km", 0.0),
        area_type=str(payload.get("area_type", "集水區")),
        t_override_min=payload.get("t_override_min"),
    )


def _run_sediment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import sediment_basin as SB

    result = SB.analyse(
        _num(payload, "area_ha"),
        excavated_ha=_num(payload, "excavated_ha", 0.0),
        impervious_ha=_num(payload, "impervious_ha", 0.0),
        kind=str(payload.get("kind", "temporary")),
        years=_num(payload, "years", 1.0),
        depth=payload.get("depth_m"),
        side_ratio=_num(payload, "side_ratio", 1.5),
        Am=payload.get("Am"),
        Rm=payload.get("Rm"),
        Km=payload.get("Km"),
        LS=payload.get("LS"),
        C=payload.get("C"),
        P=payload.get("P"),
    )
    if payload.get("structure"):
        s = payload["structure"]
        result["structure"] = SB.structural_design(
            result,
            wall_t_m=float(s.get("wall_t_m", 0.25)),
            base_t_m=float(s.get("base_t_m", 0.25)),
            water_level_m=s.get("water_level_m"),
            groundwater_head_m=float(s.get("groundwater_head_m", 0.0)),
        )
    if payload.get("outlet"):
        o = payload["outlet"]
        result["outlet"] = SB.outlet_and_overflow_design(
            _num(o, "design_q_m3s"),
            _num(o, "outlet_head_m"),
            outlet_d_m=o.get("outlet_d_m"),
            overflow_head_m=o.get("overflow_head_m"),
            overflow_length_m=o.get("overflow_length_m"),
        )
    return result


def _run_slope(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import slope_stability as SS

    return SS.analyse(payload)


def _run_rc_beam(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import rc_design as RC

    return RC.beam_design(
        _num(payload, "Mu_kNm"),
        _num(payload, "Vu_kN"),
        b_mm=_num(payload, "b_mm", 300.0),
        h_mm=_num(payload, "h_mm", 600.0),
        M_service_kNm=payload.get("M_service_kNm"),
        fc_mpa=_num(payload, "fc_mpa", 28.0),
        fy_mpa=_num(payload, "fy_mpa", 420.0),
        cover_mm=_num(payload, "cover_mm", 40.0),
    )


def _run_rc_column(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import rc_design as RC

    return RC.column_design(
        _num(payload, "Pu_kN"),
        _num(payload, "Mu_kNm"),
        b_mm=_num(payload, "b_mm", 400.0),
        h_mm=_num(payload, "h_mm", 400.0),
        fc_mpa=_num(payload, "fc_mpa", 28.0),
        fy_mpa=_num(payload, "fy_mpa", 420.0),
        cover_mm=_num(payload, "cover_mm", 40.0),
    )


def _run_settlement_assessment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import foundation_design as FD

    return FD.settlement_assessment(payload)


def _run_steel_column(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import steel_column as SC

    return SC.analyse(payload)


def _run_channel_cover(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    import channel_cover as CC

    if payload.get("size"):
        p2 = dict(payload)
        geo = dict(payload.get("geometry") or {})
        geo["slab_thickness_mm"] = None
        p2["geometry"] = geo
        p2["slab"] = {"main_bar": "", "main_spacing_mm": 0.0, "dist_bar": "", "dist_spacing_mm": 0.0}
        res = dict(CC.analyse(p2))
        sized = {
            "geometry.slab_thickness_mm": (res.get("geometry") or {}).get("slab_thickness_mm", 250.0),
            "slab.main_bar": "",
            "slab.main_spacing_mm": 0.0,
            "slab.dist_bar": "",
            "slab.dist_spacing_mm": 0.0,
        }
        res["sized_section"] = sized
        res["warnings"] = [
            "已自動搜尋最小合格版厚與配筋：版厚 %.0f mm"
            % float(sized["geometry.slab_thickness_mm"] or 250.0)
        ] + list(res.get("warnings") or [])
        return res
    return CC.analyse(payload)


RUNNERS: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
    "wall_stability": _run_wall,
    "block_wall": _run_block_wall,
    "counterfort_wall": _run_counterfort,
    "mse_wall": _run_mse,
    "anchored_wall": _run_anchored,
    "box_culvert": _run_box,
    "channel_hydraulics": _run_channel,
    "channel_profile": _run_channel_profile,
    "drainage_network": _run_network,
    "detention_basin": _run_basin,
    "building_frame": _run_building,
    "foundation_isolated": lambda p: _run_foundation(p, "isolated"),
    "foundation_combined": lambda p: _run_foundation(p, "combined"),
    "foundation_pile": lambda p: _run_foundation(p, "pile"),
    "settlement_assessment": _run_settlement_assessment,
    "hydrology": _run_hydrology,
    "sediment_basin": _run_sediment,
    "slope_stability": _run_slope,
    "rc_beam": _run_rc_beam,
    "rc_column": _run_rc_column,
    "steel_column": _run_steel_column,
    "channel_cover": _run_channel_cover,
}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _format_report(calc_id: str, result: Mapping[str, Any]) -> str:
    # 引擎模組自帶 format_report 者直接使用（新計算器只要在 CATALOG 填 engine 即可）；
    # rc_design.format_report 是給擋土牆莖板用的，梁／柱走 fallback。
    calc = _catalog_map().get(calc_id) or {}
    engine = str(calc.get("engine") or "")
    if engine.endswith(".py") and calc_id not in {"rc_beam", "rc_column"}:
        try:
            import importlib

            module = importlib.import_module(Path(engine).stem)
            if callable(getattr(module, "format_report", None)):
                return str(module.format_report(result))
        except Exception:
            pass
    return _format_fallback(calc_id, result)


def _pick_checks(calc_id: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    if calc_id in {"rc_beam", "rc_column"}:
        return _checks_from_rc(result)
    return _checks_from_common(result)


def _verified_refs(calc_id):
    """Verified clause entries (tools/regs/verified) this calculator relies on; never breaks a run."""
    try:
        import sys
        regs = str(ROOT / "tools" / "regs")
        if regs not in sys.path:
            sys.path.insert(0, regs)
        import verified
        return verified.references_for(calc_id)
    except Exception:
        return []


def run_calculation(
    calc_id: str,
    payload: Mapping[str, Any] | None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Run one calculator and return the common workbench envelope."""

    calc = _catalog_map().get(calc_id)
    if calc is None:
        raise DesignAPIError("未知計算器：%s" % calc_id)
    data = _require_mapping(payload or {}, "payload")
    runner = RUNNERS.get(calc_id)
    if runner is None:
        raise DesignAPIError("計算器尚未接線：%s" % calc_id)

    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        result = runner(data)
    except Exception as exc:
        return {
            "schema": "civil-design-run/1",
            "calculator": calc_id,
            "title": calc["title"],
            "engine": calc["engine"],
            "ok": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "summary": "輸入或計算失敗，請修正參數後重跑。\n%s" % exc,
            "checks": [],
            "warnings": [calc.get("limitations", "")],
            "codes": calc.get("codes", []),
            "generated_at": generated,
            "result": None,
            "saved_to": None,
        }

    checks = _pick_checks(calc_id, result)
    explicit = result.get("pass", result.get("ok"))
    ok = bool(explicit) if explicit is not None else all(
        bool(c.get("ok")) for c in checks
        if c.get("severity") != "advisory"
    )
    warnings = []
    for key in ("warnings", "limitations", "notes"):
        value = result.get(key)
        if isinstance(value, list):
            warnings.extend(str(v) for v in value)
        elif value:
            warnings.append(str(value))
    if calc.get("limitations") and calc["limitations"] not in warnings:
        warnings.append(calc["limitations"])

    envelope = {
        "schema": "civil-design-run/1",
        "calculator": calc_id,
        "title": calc["title"],
        "engine": calc["engine"],
        "ok": ok,
        "summary": _format_report(calc_id, result),
        "checks": _json_safe(checks),
        "warnings": warnings,
        "codes": calc.get("codes", []),
        "references": _verified_refs(calc_id),
        "generated_at": generated,
        "result": _json_safe(result),
        "saved_to": None,
    }
    if persist:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = RUN_DIR / ("%s_%s.json" % (stamp, re.sub(r"[^A-Za-z0-9_-]+", "_", calc_id)))
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            envelope["saved_to"] = str(path.relative_to(ROOT))
        except ValueError:
            envelope["saved_to"] = str(path)
    return envelope

