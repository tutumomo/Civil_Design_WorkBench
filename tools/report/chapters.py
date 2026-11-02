# -*- coding: utf-8 -*-
"""章節裝配：把 templates/report/chapters.json 的 14 章骨架，依案件 JSON 的資料逐章排出。

責任分工
--------
* `docx_build.py`：只管「怎麼排」（字級、框線、表號圖號）
* `chapters.py`（本檔）：只管「排什麼」（哪一章要哪些區塊、缺資料時怎麼標註）
* `make_report.py`：只管「流程」（產檔、轉檔、產製報告）

章節順序與編號固定（來源：docs/擋土牆改版_作業計畫.md §6 的 14 章），
內容則完全由案件 JSON 驅動；JSON 沒填的區塊一律轉成「需人工補」佔位符，
不會靜默消失，也不會讓整份報告失敗。
"""
from __future__ import annotations

from typing import Any

from docx_build import DocxReport
from report_model import ChapterStatus, ReportModel


def _as_list(value: Any) -> list:
    """把字串／清單／單一 dict 一律轉成清單。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in (None, "")]
    if isinstance(value, dict):
        return [value]
    return [value]


def _heading(builder: DocxReport, chapter_no: int, sec: dict):
    heading = sec.get("heading")
    if heading:
        builder.section_title(chapter_no, heading)


def _render_section(builder: DocxReport, model: ReportModel, chapter_no: int,
                    sec: dict, status: ChapterStatus) -> bool:
    """排一個資料區塊；有資料回 True，缺資料回 False（由呼叫端出佔位符）。"""
    kind = (sec.get("kind") or "").strip()
    src = sec.get("from")

    if kind == "boilerplate":
        builder.boilerplate_block(sec.get("ref", ""))
        return True

    data = model.get(src, None)

    if kind == "paragraphs":
        items = _as_list(data)
        if not items:
            return False
        _heading(builder, chapter_no, sec)
        for text in items:
            builder.para(str(text))
        return True

    if kind == "bullets":
        items = _as_list(data)
        if not items:
            return False
        _heading(builder, chapter_no, sec)
        builder.bullets([str(i) for i in items])
        return True

    if kind == "tables":
        specs = _as_list(data)
        if not specs:
            return False
        _heading(builder, chapter_no, sec)
        done = builder.tables(specs, default_caption=sec.get("label"))
        return done > 0

    if kind == "checks":
        items = _as_list(data)
        if not items:
            return False
        _heading(builder, chapter_no, sec)
        caption = sec.get("caption") or sec.get("label") or "檢核結果表"
        return builder.checks_table(items, caption)

    if kind == "figures":
        items = _as_list(data)
        if not items:
            return False
        _heading(builder, chapter_no, sec)
        return builder.figures(items) > 0

    if kind == "regulations":
        ids = _as_list(data)
        if not ids:
            return False
        _heading(builder, chapter_no, sec)
        return builder.regulations([str(i) for i in ids]) > 0

    # 未知 kind：當成缺資料處理（並在 hint 中提示範本設定錯誤）
    sec.setdefault("hint", f"範本 chapters.json 的 kind「{kind}」未被支援。")
    return False


def _present(model, path: str) -> bool:
    """檢查案件 JSON 的某個路徑是否有內容（用於決定是否還需「需人工補」）。"""
    cur = model.case if hasattr(model, "case") else getattr(model, "data", None)
    if cur is None:
        try:
            cur = model.get(path.split(".")[0])
        except Exception:
            return False
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return False
    if isinstance(cur, (list, dict, str)):
        return len(cur) > 0
    return cur is not None


def render_chapters(builder: DocxReport, model: ReportModel) -> list[ChapterStatus]:
    """排 14 章本文（不含封面、目錄、附錄）。回傳各章狀態。"""
    for chapter in model.template.get("chapters", []):
        no = int(chapter.get("no", 0))
        title = chapter.get("title", "")
        status = builder.begin_chapter(chapter)
        applies = model.chapter_applies(chapter)

        # 不適用之章節不另起新頁（避免出現一整頁只有一行字的空白頁）
        builder.chapter_title(no, title, page_break=applies)

        if not applies:
            status.status = "na"
            status.note = "本工程類別無此項目"
            builder.para(
                "本章（{}）不適用於本工程類別（{}）。本報告之章節架構固定為 14 章，"
                "為維持報告結構完整而保留本章；本工程無此類構造物，故無設計內容。"
                "如後續變更設計涉及此類構造，須另行補充本章內容、計算書與圖說，"
                "並重新發行報告版次。".format(title, model.project.get("category") or "（未宣告）")
            )
            builder.end_chapter()
            continue

        if chapter.get("intro"):
            builder.para(chapter["intro"])

        for sec in chapter.get("sections", []):
            ok = _render_section(builder, model, no, sec, status)
            if ok:
                builder.mark_auto()
            else:
                status.missing_sections += 1
                label = sec.get("label") or sec.get("heading") or sec.get("kind") or "資料區塊"
                builder.placeholder(status, label, sec.get("hint", ""))

        for man in chapter.get("manual", []) or []:
            # skip_if：若該章對應的資料區塊已由案件（或設計計算）自動填入，
            # 這筆「需人工補」就不再成立 —— 例如擋土牆穩定檢核已自動算出，
            # 就不該還要求人工補一份「安全係數計算書」。
            cond = man.get("skip_if")
            if cond and model.get(cond.replace(".", ".__dict__."), None) is not None:
                continue
            if cond and _present(model, cond):
                continue
            builder.placeholder(status, man.get("label", ""), man.get("hint", ""))

        builder.end_chapter()

    return builder.chapter_status


def render_appendices(builder: DocxReport, model: ReportModel, extra_meta: dict | None = None):
    """排附錄 A（章節狀態）、B（待補清單）、C（產製資訊）。"""
    for app in model.template.get("appendices", []):
        builder.appendix_title(app.get("letter", ""), app.get("title", ""))
        if app.get("note"):
            builder.note(app["note"])
        aid = app.get("id")
        if aid == "status":
            builder.appendix_status_table()
        elif aid == "todo":
            builder.appendix_todo_table()
        elif aid == "meta":
            builder.appendix_meta(extra_meta)
    builder.end_mark()
