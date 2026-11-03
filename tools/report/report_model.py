# -*- coding: utf-8 -*-
"""報告資料模型：載入案件 JSON、驗證必填、計算衍生量與一致性自查。

本模組**不涉及 Word 排版**，只負責把「案件 JSON ＋ templates/report 範本」整理成
可供 docx_build.py 排版的結構。資料缺漏不在這裡失敗，而是標記成 None，
由排版層轉成「需人工補」佔位符（少數真正無法繼續的必填項才拋 ReportDataError）。

執行環境（AGENTS.md §3）：Python 一律 `set PYTHONIOENCODING=utf-8`，讀寫中文檔
一律 `encoding="utf-8"`。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# <專案根目錄>\tools\report\report_model.py → parents[2] == <專案根目錄>
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_DIR = WORKSPACE_ROOT / "templates" / "report"

# 章節 applies_to 比對用的類別關鍵字（子字串比對，故「道路改善（A.C. 刨鋪）」可命中「道路」）
CATEGORY_ALIASES = {
    "道路": ["道路", "路面", "刨鋪", "鋪面", "AC", "巷弄", "農路"],
    "排水溝": ["排水", "溝", "渠道", "箱涵", "側溝"],
    "擋土牆": ["擋土", "重力式", "懸臂式", "護坡"],
    "邊坡": ["邊坡", "坡面", "崩塌", "地滑"],
}


class ReportDataError(Exception):
    """案件資料無法滿足產生報告的最低需求。"""


# 案件基本資料的「還沒填」特徵字：欄位含這些字一律視為未確認
# （使用者規範：報告書輸出前必須先向使用者確認案名與主辦機關）
PLACEHOLDER_TOKENS = ("待填", "待確認", "待補", "請填", "未定", "TBD", "TODO")


def is_unconfirmed(value: Any) -> bool:
    """空白或含「待填／請填」等特徵字 → True（視為尚未確認）。"""
    text = str(value or "").strip()
    return not text or any(tok in text for tok in PLACEHOLDER_TOKENS)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dig(data: Any, dotted: str, default: Any = None) -> Any:
    """以 'a.b.c' 取巢狀值；任一層缺漏即回 default。"""
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


@dataclass
class Placeholder:
    """一個「需人工補」佔位符。"""

    chapter_no: int | str
    chapter_title: str
    label: str
    hint: str = ""

    def as_dict(self) -> dict:
        return {
            "chapter_no": self.chapter_no,
            "chapter_title": self.chapter_title,
            "label": self.label,
            "hint": self.hint,
        }


@dataclass
class ChapterStatus:
    """單章資料狀態統計（附錄 A 資料來源）。"""

    no: int
    title: str
    status: str = "manual"  # auto / partial / manual / na
    auto_sections: int = 0
    missing_sections: int = 0
    placeholders: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "no": self.no,
            "title": self.title,
            "status": self.status,
            "auto_sections": self.auto_sections,
            "missing_sections": self.missing_sections,
            "placeholders": self.placeholders,
            "note": self.note,
        }


@dataclass
class ConsistencyCheck:
    """數量一致性自我檢核（附錄 C）。"""

    item: str
    claimed: str
    formula: str
    computed: str
    result: str  # 一致 / 不一致 / 無法複核

    def as_dict(self) -> dict:
        return {
            "item": self.item,
            "claimed": self.claimed,
            "formula": self.formula,
            "computed": self.computed,
            "result": self.result,
        }


@dataclass
class ReportModel:
    case_path: Path
    case: dict
    template_dir: Path
    style: dict
    template: dict
    regdb: dict
    boilerplate: dict
    project: dict = field(default_factory=dict)
    consistency: list[ConsistencyCheck] = field(default_factory=list)

    # ---- 載入 -----------------------------------------------------------------
    @classmethod
    def load(cls, case_path: str | Path, template_dir: str | Path | None = None) -> "ReportModel":
        case_path = Path(case_path).resolve()
        if not case_path.exists():
            raise ReportDataError(f"案件 JSON 不存在：{case_path}")
        tdir = Path(template_dir).resolve() if template_dir else DEFAULT_TEMPLATE_DIR
        for name in ("style.json", "chapters.json", "regulations.json", "boilerplate.json"):
            if not (tdir / name).exists():
                raise ReportDataError(f"範本檔缺少：{tdir / name}")

        model = cls(
            case_path=case_path,
            case=load_json(case_path),
            template_dir=tdir,
            style=load_json(tdir / "style.json"),
            template=load_json(tdir / "chapters.json"),
            regdb=load_json(tdir / "regulations.json"),
            boilerplate=load_json(tdir / "boilerplate.json"),
        )
        model.project = model._normalise_project()
        model.consistency = model._consistency_checks()
        return model

    # ---- 專案基本資料 ---------------------------------------------------------
    def _normalise_project(self) -> dict:
        p = self.case.get("project") or {}
        report = self.case.get("report") or {}
        name = (p.get("name") or "").strip()
        if not name:
            raise ReportDataError("案件 JSON 缺少 project.name（工程名稱），無法命名輸出檔。")
        full_name = (p.get("full_name") or name).strip()
        category = (p.get("category") or "").strip()

        loc = p.get("location") or {}
        if isinstance(loc, str):
            loc = {"desc": loc}
        location_text = loc.get("desc") or self._join_location(loc)

        crs = p.get("crs") or {}
        return {
            "name": name,
            "full_name": full_name,
            "code": (p.get("code") or "").strip() or None,
            "category": category or None,
            "report_title": (report.get("title") or "設計報告書").strip(),
            "report_subtitle": (report.get("subtitle") or "").strip() or None,
            "location": loc,
            "location_text": location_text or None,
            "crs": crs,
            "crs_text": self._crs_text(crs),
            "coords": p.get("coords") or [],
            # 主辦機關（業主；封面必填，見 make_report.py 的確認閘門）
            "agency": (p.get("agency") or "").strip() or None,
            "agency_confirmed": not is_unconfirmed(p.get("agency")),
            "client": (p.get("client") or "").strip() or None,
            "designer": (p.get("designer") or "").strip() or None,
            "reviewer": (p.get("reviewer") or "").strip() or None,
            "date": (p.get("date") or "").strip() or None,
            "version": (p.get("version") or "v1.0").strip(),
            "rocin_date": (p.get("rocin_date") or "").strip() or None,
            "raw": p,
        }

    @staticmethod
    def _join_location(loc: dict) -> str:
        parts = [loc.get(k) for k in ("county", "town", "village", "section", "lot")]
        return "".join(str(x) for x in parts if x)

    @staticmethod
    def _crs_text(crs: dict) -> str | None:
        if not crs:
            return None
        name = crs.get("name") or crs.get("crs")
        epsg = crs.get("epsg")
        unit = crs.get("unit") or "公尺"
        bits = [b for b in (name, epsg, unit) if b]
        return "／".join(str(b) for b in bits) if bits else None

    # ---- 章節適用性 -----------------------------------------------------------
    def chapter_applies(self, chapter: dict) -> bool:
        applies = chapter.get("applies_to") or ["*"]
        if "*" in applies:
            return True
        cat = self.project.get("category") or ""
        if not cat:
            # 未宣告類別時，寧可全部產出佔位符，也不要靜默丟章
            return True
        hay = cat.upper()
        for token in applies:
            if token in cat:
                return True
            for alias in CATEGORY_ALIASES.get(token, []):
                if alias.upper() in hay:
                    return True
        return False

    # ---- 資料存取 -------------------------------------------------------------
    def get(self, dotted: str | None, default: Any = None) -> Any:
        if not dotted:
            return default
        return dig(self.case, dotted, default)

    def has(self, dotted: str | None) -> bool:
        val = self.get(dotted, None)
        if val is None:
            return False
        if isinstance(val, (str, list, dict)) and len(val) == 0:
            return False
        return True

    def reg(self, reg_id: str) -> dict | None:
        return (self.regdb.get("regulations") or {}).get(reg_id)

    def boiler(self, ref: str) -> dict | None:
        return (self.boilerplate.get("boilerplate") or {}).get(ref)

    def label(self, key: str) -> str:
        """取 style.json 的狀態標籤（自動填入／部分自動／需人工補／不適用）。"""
        return (
            (self.style.get("placeholder") or {}).get("status_labels") or {}
        ).get(key, key)

    # ---- 數量一致性自查 -------------------------------------------------------
    def _consistency_checks(self) -> list[ConsistencyCheck]:
        q = self.case.get("quantities") or {}
        checks: list[ConsistencyCheck] = []

        def num(key: str) -> float | None:
            v = q.get(key)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        L, A, V = num("length_m"), num("area_m2"), num("volume_m3")
        W, t_cm = num("width_avg_m"), num("thickness_cm")

        if A and t_cm is not None:
            computed = A * t_cm / 100.0
            if V is not None:
                diff = abs(computed - V) / V * 100 if V else 0.0
                checks.append(
                    ConsistencyCheck(
                        item="A.C. 鋪裝體積 V",
                        claimed=f"{V:,.2f} m³",
                        formula=f"A × t = {A:,.1f} × {t_cm:g}/100",
                        computed=f"{computed:,.2f} m³",
                        result="一致" if diff <= 1.0 else f"不一致（差 {diff:.2f}%）",
                    )
                )
            else:
                checks.append(
                    ConsistencyCheck(
                        item="A.C. 鋪裝體積 V",
                        claimed="（未提供，已由程式推算）",
                        formula=f"A × t = {A:,.1f} × {t_cm:g}/100",
                        computed=f"{computed:,.2f} m³",
                        result="已推算",
                    )
                )
        elif V is not None:
            checks.append(
                ConsistencyCheck(
                    item="A.C. 鋪裝體積 V",
                    claimed=f"{V:,.2f} m³",
                    formula="需 A 與 t 方可複核",
                    computed="—",
                    result="無法複核",
                )
            )

        if L and W:
            computed = L * W
            if A is not None:
                diff = abs(computed - A) / A * 100 if A else 0.0
                checks.append(
                    ConsistencyCheck(
                        item="刨鋪面積 A",
                        claimed=f"{A:,.1f} m²",
                        formula=f"L × W = {L:,.2f} × {W:,.2f}",
                        computed=f"{computed:,.1f} m²",
                        result="一致" if diff <= 1.0 else f"不一致（差 {diff:.2f}%）",
                    )
                )
            else:
                checks.append(
                    ConsistencyCheck(
                        item="刨鋪面積 A",
                        claimed="（未提供，已由程式推算）",
                        formula=f"L × W = {L:,.2f} × {W:,.2f}",
                        computed=f"{computed:,.1f} m²",
                        result="已推算",
                    )
                )
        return checks

    # ---- 輸出檔名 -------------------------------------------------------------
    def output_stem(self) -> str:
        """輸出檔名主幹：<工程名稱>_設計報告（沿用案件資料夾之命名慣例）。"""
        safe = self.project["name"].replace("/", "_").replace("\\", "_")
        return f"{safe}_設計報告"

    def summary(self) -> dict:
        return {
            "case": str(self.case_path),
            "template_dir": str(self.template_dir),
            "project": {
                k: v for k, v in self.project.items() if k != "raw"
            },
            "consistency": [c.as_dict() for c in self.consistency],
        }
