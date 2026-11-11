# -*- coding: utf-8 -*-
"""Word 排版引擎：把 report_model 的結構排成 .docx（python-docx）。

設計原則
--------
1. **版面參數全部來自 templates/report/style.json**，程式內不寫死字級／邊界。
2. **OOXML 子元素順序嚴格遵守 schema**：pPr / tcPr / trPr / tblPr 皆有既定順序，
   順序錯會讓 Word 判定檔案損壞（LibreOffice 較寬容但不可依賴）。本檔用
   `insert_ordered()` 依 canonical order 插入。
3. **表號／圖號由本文物件計數器自動編**，PDF 由 wordcraft-cli 轉檔（見 make_report.py）。
4. 缺資料不報錯，一律轉成 `【需人工補｜章名】項目` 佔位符（黃底），並記錄供附錄 B 彙整。

執行環境（AGENTS.md §3）：Python 前必設 PYTHONIOENCODING=utf-8；中文檔一律 UTF-8。
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from report_model import WORKSPACE_ROOT, ChapterStatus, Placeholder, ReportModel
# ---------------------------------------------------------------------------
# OOXML 子元素順序（Subset，涵蓋本產線會用到的元素）
# ---------------------------------------------------------------------------
P_ORDER = [
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
    "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
]
TC_ORDER = [
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders",
    "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText",
    "w:vAlign", "w:hideMark",
]
TR_ORDER = [
    "w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore",
    "w:wAfter", "w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing",
    "w:jc", "w:hidden",
]
TBL_ORDER = [
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual",
    "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
    "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
    "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription",
]
SECT_ORDER = [
    "w:footnotePr", "w:endnotePr", "w:type", "w:pgSz", "w:pgMar", "w:paperSrc",
    "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt",
    "w:vAlign", "w:noEndnote", "w:titlePg", "w:textDirection", "w:bidi",
    "w:rtlGutter", "w:docGrid", "w:printerSettings", "w:sectPrChange",
]


def _insert_ordered(parent, child, order: list[str]):
    """依 canonical order 把 child 插到 parent 的正確位置（同 tag 不可重複）。"""
    qnames = [qn(t) for t in order]
    tag = child.tag
    idx = qnames.index(tag) if tag in qnames else len(qnames)
    for existing in list(parent):
        etag = existing.tag
        eidx = qnames.index(etag) if etag in qnames else len(qnames)
        if eidx > idx:
            existing.addprevious(child)
            return child
    parent.append(child)
    return child


def _ensure(parent, tag: str, order: list[str]):
    """取得或建立 parent 下的單一子元素。"""
    qname = qn(tag)
    found = parent.find(qname)
    if found is not None:
        return found
    el = OxmlElement(tag)
    return _insert_ordered(parent, el, order)


# ---------------------------------------------------------------------------
# 文字工具
# ---------------------------------------------------------------------------
def set_run_font(run, east_asia: str, latin: str, size_pt: float,
                 bold: bool = False, italic: bool = False,
                 color: tuple[int, int, int] | None = None):
    """設定 run 的中英文字型（East Asian 一定要另外指定，否則中文會落到別的字型）。"""
    run.font.name = latin
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rFonts.attrib.pop(qn(attr), None)
    rFonts.set(qn("w:ascii"), latin)
    rFonts.set(qn("w:hAnsi"), latin)
    rFonts.set(qn("w:eastAsia"), east_asia)
    rFonts.set(qn("w:cs"), latin)


def add_field(paragraph, instr: str, placeholder: str,
              east_asia: str, latin: str, size_pt: float):
    """插入 Word 欄位（PAGE / NUMPAGES / TOC），並給佔位文字。"""
    run = paragraph.add_run()
    set_run_font(run, east_asia, latin, size_pt)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    text_el = OxmlElement("w:t")
    text_el.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr_el, sep, text_el, end):
        run._element.append(el)
    return run


class DocxReport:
    """一份設計報告的 Word 文件建構器。"""

    def __init__(self, model: ReportModel):
        self.model = model
        self.style = model.style
        self.fonts = self.style["fonts"]
        self.sizes = self.style["sizes_pt"]
        self.spacing = self.style["spacing"]
        self.num = self.style["numbering"]
        self.cover_cfg = self.style.get("cover") or {}
        self.cap = self.style["captions"]
        self.tbl_cfg = self.style["table"]
        self.ph_cfg = self.style["placeholder"]

        self.doc = Document()
        self.table_no = 0
        self.figure_no = 0
        self.placeholders: list[Placeholder] = []
        self.chapter_status: list[ChapterStatus] = []
        self._cur: ChapterStatus | None = None
        self._sec_index = [0, 0]  # 目前章之節號、小節號計數

    # ==================================================================
    # 版面與樣式
    # ==================================================================
    def setup(self):
        page = self.style["page"]
        sec = self.doc.sections[0]
        sec.page_width = Cm(page["width_cm"])
        sec.page_height = Cm(page["height_cm"])
        m = page["margin_cm"]
        sec.top_margin = Cm(m["top"])
        sec.bottom_margin = Cm(m["bottom"])
        sec.left_margin = Cm(m["left"])
        sec.right_margin = Cm(m["right"])
        sec.header_distance = Cm(page["header_distance_cm"])
        sec.footer_distance = Cm(page["footer_distance_cm"])
        sec.different_first_page_header_footer = bool(page.get("different_first_page", True))

        # 章節起始頁碼：封面為第 1 頁且不顯示頁首頁尾（titlePg），故不必重設起始頁碼。
        self._setup_styles()
        self._setup_header_footer(sec)
        self._setup_core_properties()

    def _set_style_font(self, style_obj, font: dict, size_pt: float, bold: bool = False):
        style_obj.font.name = font["latin"]
        style_obj.font.size = Pt(size_pt)
        style_obj.font.bold = bold
        style_obj.font.color.rgb = RGBColor(0, 0, 0)
        rPr = style_obj.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.insert(0, rFonts)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            rFonts.attrib.pop(qn(attr), None)
        rFonts.set(qn("w:ascii"), font["latin"])
        rFonts.set(qn("w:hAnsi"), font["latin"])
        rFonts.set(qn("w:eastAsia"), font["east_asia"])
        rFonts.set(qn("w:cs"), font["latin"])

    def _setup_styles(self):
        styles = self.doc.styles
        normal = styles["Normal"]
        self._set_style_font(normal, self.fonts["body"], self.sizes["body"])
        pf = normal.paragraph_format
        pf.line_spacing = self.spacing["body_line_spacing"]
        pf.space_before = Pt(self.spacing["body_before_pt"])
        pf.space_after = Pt(self.spacing["body_after_pt"])
        # 東亞語系（避免簡繁轉換與字型替代）
        rPr = normal.element.get_or_add_rPr()
        lang = _ensure(rPr, "w:lang", ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs",
                                       "w:caps", "w:smallCaps", "w:strike", "w:dstrike",
                                       "w:outline", "w:shadow", "w:emboss", "w:imprint",
                                       "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden",
                                       "w:color", "w:spacing", "w:w", "w:kern", "w:position",
                                       "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
                                       "w:bdr", "w:shd", "w:fitText", "w:vertAlign",
                                       "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout"])
        lang.set(qn("w:val"), "en-US")
        lang.set(qn("w:eastAsia"), "zh-TW")

        for style_name, key, size_key, bold in (
            ("Heading 1", "heading1", "heading1", True),
            ("Heading 2", "heading2", "heading2", True),
            ("Heading 3", "heading3", "heading3", True),
        ):
            st = styles[style_name]
            self._set_style_font(st, self.fonts[key], self.sizes[size_key], bold=bold)
            spf = st.paragraph_format
            spf.space_before = Pt(self.spacing[f"{size_key}_before_pt"])
            spf.space_after = Pt(self.spacing[f"{size_key}_after_pt"])
            spf.keep_with_next = True
            spf.line_spacing = 1.2

        # 目錄樣式：TOC 欄位展開時轉檔器會套用 TOC 1／TOC 2 樣式，
        # 若未預先定義，中文會落回轉檔器內建的日文字型（實測為 ShipporiMincho）。
        for level in (1, 2, 3):
            name = f"TOC {level}"
            try:
                st = styles[name]
            except KeyError:
                st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
                st.base_style = styles["Normal"]
                st.quick_style = False
            self._set_style_font(st, self.fonts["body"], self.sizes["body"], bold=False)
            spf = st.paragraph_format
            spf.space_before = Pt(0)
            spf.space_after = Pt(3)
            spf.line_spacing = 1.15

    def _setup_header_footer(self, sec):
        hf_font = self.fonts["header_footer"]
        hf_size = self.sizes["header_footer"]
        project = self.model.project

        header = sec.header
        header.is_linked_to_previous = False
        hp = header.paragraphs[0]
        hp.text = ""
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        text = self.style["header"]["pattern"].format(
            project=project["full_name"], report_title=project["report_title"]
        )
        run = hp.add_run(text)
        set_run_font(run, hf_font["east_asia"], hf_font["latin"], hf_size)
        if self.style["header"].get("border_bottom", True):
            pPr = hp._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), "808080")
            pBdr.append(bottom)
            _insert_ordered(pPr, pBdr, P_ORDER)

        footer = sec.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0]
        fp.text = ""
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pattern = self.style["footer"]["pattern"]
        pre, _, post = pattern.partition("{page}")
        mid, _, tail = post.partition("{pages}")
        if pre:
            set_run_font(fp.add_run(pre), hf_font["east_asia"], hf_font["latin"], hf_size)
        add_field(fp, " PAGE ", "1", hf_font["east_asia"], hf_font["latin"], hf_size)
        if mid:
            set_run_font(fp.add_run(mid), hf_font["east_asia"], hf_font["latin"], hf_size)
        add_field(fp, " NUMPAGES ", "1", hf_font["east_asia"], hf_font["latin"], hf_size)
        if tail:
            set_run_font(fp.add_run(tail), hf_font["east_asia"], hf_font["latin"], hf_size)

        # 封面（第 1 頁）不顯示頁首頁尾
        first_header = sec.first_page_header
        first_header.is_linked_to_previous = False
        first_header.paragraphs[0].text = ""
        first_footer = sec.first_page_footer
        first_footer.is_linked_to_previous = False
        first_footer.paragraphs[0].text = ""

    def _setup_core_properties(self):
        project = self.model.project
        cp = self.doc.core_properties
        cp.title = f"{project['full_name']}　{project['report_title']}"
        cp.subject = project.get("category") or "土木工程設計"
        cp.author = project.get("designer") or "本工作區設計報告產線（tools/report）"
        cp.last_modified_by = "tools/report"
        cp.comments = "本文件為設計輔助文件，非技師簽證文件；正式施工前須由合格技師依實際地勘覆核簽證。"
        cp.keywords = "設計報告;土木工程;設計輔助"
        cp.category = project["report_title"]

    # ==================================================================
    # 基礎積木
    # ==================================================================
    def _para(self, align=None, first_line_chars=None, left_chars=None,
              hanging_chars=None, before=None, after=None, line=None,
              keep_with_next=False, outline_level=None):
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        if align is not None:
            pf.alignment = align
        if before is not None:
            pf.space_before = Pt(before)
        if after is not None:
            pf.space_after = Pt(after)
        if line is not None:
            pf.line_spacing = line
        if keep_with_next:
            pf.keep_with_next = True
        if outline_level is not None:
            pPr = p._p.get_or_add_pPr()
            lvl = OxmlElement("w:outlineLvl")
            lvl.set(qn("w:val"), str(outline_level))
            _insert_ordered(pPr, lvl, P_ORDER)

        ind = 0.0
        if first_line_chars is not None:
            ind = self.sizes["body"] * first_line_chars
        if left_chars is not None:
            ind = self.sizes["body"] * left_chars
        if first_line_chars is not None or left_chars is not None or hanging_chars is not None:
            pPr = p._p.get_or_add_pPr()
            ind_el = _ensure(pPr, "w:ind", P_ORDER)
            if left_chars is not None:
                ind_el.set(qn("w:leftChars"), str(int(left_chars * 100)))
                ind_el.set(qn("w:left"), str(int(self.sizes["body"] * left_chars * 20)))
            if first_line_chars is not None:
                ind_el.set(qn("w:firstLineChars"), str(int(first_line_chars * 100)))
                ind_el.set(qn("w:firstLine"), str(int(ind * 20)))
            if hanging_chars is not None:
                ind_el.set(qn("w:hangingChars"), str(int(hanging_chars * 100)))
                ind_el.set(qn("w:hanging"), str(int(self.sizes["body"] * hanging_chars * 20)))
        return p

    def para(self, text: str, indent: bool = True, size_key: str = "body",
             bold: bool = False, align=None, italic: bool = False):
        p = self._para(align=align,
                       first_line_chars=self.style["indent"]["body_first_line_chars"] if indent else None)
        run = p.add_run(text)
        f = self.fonts["body"]
        set_run_font(run, f["east_asia"], f["latin"], self.sizes[size_key],
                     bold=bold, italic=italic)
        return p

    def note(self, text: str):
        """表格／圖片下方的小字說明。"""
        p = self._para(after=8)
        f = self.fonts["note"]
        run = p.add_run(text)
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["note"], italic=False)
        return p

    def chapter_title(self, no: int, title: str, page_break: bool = True):
        text = self.num["chapter"].format(n=no, title=title)
        p = self.doc.add_paragraph(style="Heading 1")
        if page_break:
            p.paragraph_format.page_break_before = True
        run = p.add_run(text)
        f = self.fonts["heading1"]
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["heading1"], bold=True)
        self._sec_index = [0, 0]
        return p

    def section_title(self, chapter_no: int, title: str):
        self._sec_index[0] += 1
        self._sec_index[1] = 0
        text = self.num["section"].format(c=chapter_no, s=self._sec_index[0], title=title)
        p = self.doc.add_paragraph(style="Heading 2")
        run = p.add_run(text)
        f = self.fonts["heading2"]
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["heading2"], bold=True)
        return p

    def subsection_title(self, chapter_no: int, title: str):
        self._sec_index[1] += 1
        text = self.num["subsection"].format(
            c=chapter_no, s=self._sec_index[0] or 1, t=self._sec_index[1], title=title
        )
        p = self.doc.add_paragraph(style="Heading 3")
        run = p.add_run(text)
        f = self.fonts["heading3"]
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["heading3"], bold=True)
        return p

    def bullets(self, items: list[str]):
        for i, item in enumerate(items, 1):
            prefix = self.num["bullet_prefix"].format(i=i)
            p = self._para(left_chars=3, hanging_chars=1.5, after=3)
            run = p.add_run(prefix + str(item))
            f = self.fonts["body"]
            set_run_font(run, f["east_asia"], f["latin"], self.sizes["body"])

    def blank(self, count: int = 1, line_pt: float | None = None):
        """空白行。line_pt 給定時用「固定行高」，讓封面間隙可精算（不隨字型行距飘）。"""
        for _ in range(count):
            p = self.doc.add_paragraph()
            if line_pt is not None:
                pf = p.paragraph_format
                pf.line_spacing = Pt(line_pt)
                pf.space_before = Pt(0)
                pf.space_after = Pt(0)

    # ==================================================================
    # 表格
    # ==================================================================
    def caption(self, kind: str, text: str) -> str:
        """回傳完整題註文字（表 1　數量表）並記錄編號。"""
        prefix, sep = self.cap["table_prefix"], self.cap["separator"]
        if kind == "figure":
            self.figure_no += 1
            no = self.figure_no
            prefix = self.cap["figure_prefix"]
        else:
            self.table_no += 1
            no = self.table_no
        label = f"{prefix} {no}{sep}{text}" if text else f"{prefix} {no}"
        return label

    def _caption_paragraph(self, label: str):
        p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER,
                       before=self.spacing["caption_before_pt"],
                       after=self.spacing["caption_after_pt"], keep_with_next=True)
        f = self.fonts["caption"]
        run = p.add_run(label)
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["caption"], bold=True)
        return p

    def _set_cell_shading(self, cell, fill: str):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        _insert_ordered(tcPr, shd, TC_ORDER)

    def _set_cell_valign(self, cell, val: str = "center"):
        tcPr = cell._tc.get_or_add_tcPr()
        vAlign = OxmlElement("w:vAlign")
        vAlign.set(qn("w:val"), val)
        _insert_ordered(tcPr, vAlign, TC_ORDER)

    def _set_cell_text(self, cell, text: str, bold: bool = False,
                       align: str = "left", size_key: str = "table"):
        cell.text = ""
        p = cell.paragraphs[0]
        pf = p.paragraph_format
        pf.space_before = Pt(1)
        pf.space_after = Pt(1)
        pf.line_spacing = self.spacing["table_line_spacing"]
        pf.alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
        }.get(align, WD_ALIGN_PARAGRAPH.LEFT)
        f = self.fonts["table"]
        size = self.sizes[size_key]
        segments = str(text).split("\n")
        for i, seg in enumerate(segments):
            if i > 0:
                p = cell.add_paragraph()
                pf2 = p.paragraph_format
                pf2.space_before = Pt(0)
                pf2.space_after = Pt(1)
                pf2.line_spacing = self.spacing["table_line_spacing"]
                pf2.alignment = pf.alignment
            run = p.add_run(seg)
            set_run_font(run, f["east_asia"], f["latin"], size, bold=bold)
        self._set_cell_valign(cell, "center")

    def _norm_columns(self, columns: list, total_width_cm: float):
        names, aligns, widths = [], [], []
        for col in columns:
            if isinstance(col, str):
                names.append(col)
                aligns.append(None)
                widths.append(None)
            else:
                names.append(str(col.get("name", "")))
                aligns.append(col.get("align"))
                widths.append(col.get("width_cm"))
        fixed = sum(w for w in widths if w)
        missing = [i for i, w in enumerate(widths) if not w]
        if missing:
            each = max((total_width_cm - fixed) / len(missing), 1.6)
            for i in missing:
                widths[i] = each
        scale = total_width_cm / sum(widths) if sum(widths) else 1.0
        widths = [w * scale for w in widths]
        final_aligns = []
        for i, a in enumerate(aligns):
            if a:
                final_aligns.append(a)
            else:
                final_aligns.append("left" if i == 0 else "center")
        return names, final_aligns, widths

    def table(self, spec: dict, default_caption: str | None = None) -> bool:
        """排一個表格。回傳 False 表示資料不足（由呼叫端決定要不要出佔位符）。"""
        if not spec:
            return False
        columns = spec.get("columns") or []
        rows = spec.get("rows") or []
        if not columns:
            return False
        total_w = spec.get("width_cm") or self.tbl_cfg["width_cm"]
        names, aligns, widths = self._norm_columns(columns, total_w)

        label = self.caption("table", spec.get("caption") or default_caption or "")
        self._caption_paragraph(label)

        n_rows = 1 + len(rows)
        table = self.doc.add_table(rows=n_rows, cols=len(names))
        table.style = self.tbl_cfg.get("border", "Table Grid")
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False

        tbl = table._tbl
        tblPr = tbl.tblPr
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        _insert_ordered(tblPr, layout, TBL_ORDER)
        tblW = tblPr.find(qn("w:tblW"))
        if tblW is None:
            tblW = OxmlElement("w:tblW")
            _insert_ordered(tblPr, tblW, TBL_ORDER)
        tblW.set(qn("w:type"), "dxa")
        tblW.set(qn("w:w"), str(int(total_w * 567)))

        for i, w in enumerate(widths):
            table.columns[i].width = Cm(w)

        for j, name in enumerate(names):
            cell = table.cell(0, j)
            cell.width = Cm(widths[j])
            self._set_cell_text(cell, name, bold=self.tbl_cfg.get("header_bold", True),
                                align="center")
            self._set_cell_shading(cell, self.tbl_cfg["header_fill"])

        # 表頭跨頁重複
        if self.tbl_cfg.get("repeat_header_row", True):
            trPr = table.rows[0]._tr.get_or_add_trPr()
            hdr = OxmlElement("w:tblHeader")
            _insert_ordered(trPr, hdr, TR_ORDER)

        for i, row in enumerate(rows, start=1):
            for j in range(len(names)):
                value = row[j] if j < len(row) else ""
                cell = table.cell(i, j)
                cell.width = Cm(widths[j])
                self._set_cell_text(cell, value, align=aligns[j])
        if spec.get("note"):
            self.note(spec["note"])
        return True

    def tables(self, specs: Any, default_caption: str | None = None) -> int:
        """排一或多個表格，回傳成功排版數。"""
        if not specs:
            return 0
        if isinstance(specs, dict):
            specs = [specs]
        done = 0
        for spec in specs:
            if isinstance(spec, dict) and self.table(spec, default_caption):
                done += 1
        return done

    def checks_table(self, items: list[dict], caption: str) -> bool:
        """檢核判定表：項目／要求／實際值／判定（可自訂欄名）。"""
        if not items:
            return False
        spec = {
            "caption": caption,
            "columns": [
                {"name": "檢核項目", "width_cm": 4.2, "align": "left"},
                {"name": "規範或設計要求", "width_cm": 4.2, "align": "left"},
                {"name": "計算或實測值", "width_cm": 4.2, "align": "left"},
                {"name": "判定", "width_cm": 2.9, "align": "center"},
            ],
            "rows": [
                [
                    it.get("item", ""),
                    it.get("requirement", ""),
                    it.get("value", ""),
                    it.get("verdict", "待確認"),
                ]
                for it in items
            ],
        }
        return self.table(spec)

    # ==================================================================
    # 圖
    # ==================================================================
    def figures(self, items: list[dict]) -> int:
        if not items:
            return 0
        done = 0
        for it in items:
            path = it.get("path")
            title = it.get("title") or ""
            resolved = self._resolve_path(path)
            if not resolved or not resolved.exists():
                self.placeholder(self._cur, f"圖檔：{title or path}", 
                                 f"找不到圖檔 {path}。請先以 tools/a3_sheet 產出 PNG／PDF 後填入 drawings.figures。")
                continue
            p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER, before=6, after=2,
                           keep_with_next=True)
            run = p.add_run()
            width_cm = it.get("width_cm") or 15.0
            run.add_picture(str(resolved), width=Cm(width_cm))
            label = self.caption("figure", title)
            self._caption_paragraph(label)
            if it.get("note"):
                self.note(it["note"])
            done += 1
        return done

    def _resolve_path(self, path: str | None) -> Path | None:
        """圖檔路徑解析：絕對路徑 → 案件 JSON 同層 → 上一層 → 工作區根目錄。"""
        if not path:
            return None
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        bases = [self.model.case_path.parent, self.model.case_path.parents[1], WORKSPACE_ROOT]
        for base in bases:
            if (base / candidate).exists():
                return base / candidate
        return candidate

    # ==================================================================
    # 法規引用
    # ==================================================================
    def regulations(self, ids: list[str]) -> int:
        if not ids:
            return 0
        regs = [self.model.reg(str(i)) for i in ids]
        regs = [r for r in regs if r]
        if not regs:
            return 0
        status = self.model.regdb.get("status_labels") or {}
        spec = {
            "caption": "引用法規一覽表",
            "columns": [
                {"name": "法規名稱", "width_cm": 4.6, "align": "left"},
                {"name": "主管機關", "width_cm": 2.4, "align": "center"},
                {"name": "版本", "width_cm": 3.2, "align": "center"},
                {"name": "引用條文", "width_cm": 2.8, "align": "center"},
                {"name": "查證狀態", "width_cm": 2.5, "align": "center"},
            ],
            "rows": [
                [
                    r.get("law", ""),
                    r.get("authority", ""),
                    r.get("version", ""),
                    r.get("article", ""),
                    status.get("verified" if r.get("verified") else "unverified", ""),
                ]
                for r in regs
            ],
        }
        self.table(spec)

        f_caption = self.fonts["caption"]
        f_body = self.fonts["body"]
        for r in regs:
            p = self._para(before=6, after=2, keep_with_next=True)
            head = self.model.regdb.get("citation_format", "{law}（{version}）{article}").format(**r)
            if r.get("article_title"):
                head = f"{head}　{r['article_title']}"
            set_run_font(p.add_run(head), f_caption["east_asia"], f_caption["latin"],
                         self.sizes["caption"], bold=True)
            q = self._para(left_chars=2, after=2)
            set_run_font(q.add_run(r.get("text", "")), f_body["east_asia"], f_body["latin"],
                         self.sizes["table"])
            if r.get("use_note"):
                n = self._para(left_chars=2, after=8)
                set_run_font(n.add_run("適用說明：" + r["use_note"]), f_body["east_asia"],
                             f_body["latin"], self.sizes["note"])

        if any(not r.get("verified") for r in regs):
            self.boilerplate_block("reg_unverified")
        return len(regs)

    # ==================================================================
    # 固定聲明稿
    # ==================================================================
    def boilerplate_block(self, ref: str):
        item = self.model.boiler(ref)
        if not item:
            return
        p = self._para(first_line_chars=None, before=8, after=8)
        if item.get("boxes"):
            # 聲明框不得跨頁斷開（斷開時框線會在頁尾／頁首各出現半個）
            p.paragraph_format.keep_together = True
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            for edge in ("top", "left", "bottom", "right"):
                el = OxmlElement(f"w:{edge}")
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), "6")
                el.set(qn("w:space"), "6")
                el.set(qn("w:color"), "808080")
                pBdr.append(el)
            _insert_ordered(pPr, pBdr, P_ORDER)
        f = self.fonts["body"]
        set_run_font(p.add_run(item.get("text", "")), f["east_asia"], f["latin"],
                     self.sizes["table"] if item.get("boxes") else self.sizes["body"],
                     bold=False)
        return p

    # ==================================================================
    # 佔位符
    # ==================================================================
    def placeholder(self, chapter: ChapterStatus | None, label: str, hint: str = "",
                    chapter_no: int | str | None = None,
                    chapter_title: str | None = None):
        """插入一個『需人工補』佔位符（黃底粗體），並記錄到清單。"""
        if chapter is not None:
            no, title = chapter.no, chapter.title
            chapter.placeholders += 1
        else:
            no = chapter_no if chapter_no is not None else "—"
            title = chapter_title or "一般"
        self.placeholders.append(Placeholder(no, title, label, hint))

        text = self.ph_cfg["prefix"].format(chapter=title) + label
        p = self._para(before=4, after=2)
        f = self.fonts["body"]
        run = p.add_run(text)
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["body"], bold=True)
        pPr = p._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), self.ph_cfg["fill"])
        _insert_ordered(pPr, shd, P_ORDER)
        if hint:
            hp = self._para(left_chars=2, after=8)
            set_run_font(hp.add_run(self.ph_cfg["hint_prefix"] + hint), f["east_asia"],
                         f["latin"], self.sizes["note"])

    # ==================================================================
    # 章節狀態
    # ==================================================================
    def begin_chapter(self, chapter: dict) -> ChapterStatus:
        status = ChapterStatus(no=int(chapter.get("no", 0)), title=chapter.get("title", ""))
        self.chapter_status.append(status)
        self._cur = status
        return status

    def mark_auto(self):
        if self._cur:
            self._cur.auto_sections += 1

    def end_chapter(self):
        cur = self._cur
        if not cur:
            return
        if cur.status == "na":
            self._cur = None
            return
        if cur.auto_sections == 0:
            cur.status = "manual"
        elif cur.placeholders > 0:
            cur.status = "partial"
        else:
            cur.status = "auto"
        self._cur = None

    # ==================================================================
    # 封面 / 目錄
    # ==================================================================
    def cover(self):
        """封面（版式參考 `完整案例(參考用)/報告書 封面 v01.docx`）。

        版式：案名 36pt 大字居中 → 「設 計 報 告 書」→ 下半主辦單位／設計監造單位
        → 底端「中 華 民 國 YY 年 M 月」。全部參數來自 style.json 的 `cover` 段。
        """
        project = self.model.project
        cfg = self.cover_cfg
        font = cfg.get("font") or self.fonts["title"]
        cover_status = ChapterStatus(no=0, title="封面")
        self.chapter_status.append(cover_status)

        spacer = cfg.get("spacer_line_pt")
        self.blank(int(cfg.get("spacers_top", 2)), spacer)

        # ── 案名（大字居中；太長時自動降字級，避免折行折得很醜）──
        title_pt = self._fit_title_size(project["full_name"], cfg.get("title_size_pt", 36))
        p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER,
                       before=cfg.get("title_space_before_pt", 18), after=0)
        set_run_font(p.add_run(project["full_name"]), font["east_asia"], font["latin"],
                     title_pt, bold=True)

        # ── 「設 計 報 告 書」──
        if cfg.get("show_report_title", True):
            self.blank(int(cfg.get("spacers_after_title", 1)), spacer)
            p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
            set_run_font(p.add_run(cfg.get("report_title_text") or project["report_title"]),
                         font["east_asia"], font["latin"],
                         cfg.get("report_title_size_pt", 24), bold=True)

        self.blank(int(cfg.get("spacers_before_info", 7)), spacer)

        # ── 主辦單位／設計監造單位（左起，20pt）──
        info_pt = cfg.get("info_size_pt", 20)
        before_pt = cfg.get("info_space_before_pt", 6)
        after_pt = cfg.get("info_space_after_pt", 6)
        agency = (project.get("agency") or "").strip()
        if not project.get("agency_confirmed", True):
            agency = ""
        p = self._para(align=WD_ALIGN_PARAGRAPH.LEFT, before=before_pt, after=after_pt)
        set_run_font(p.add_run(cfg.get("agency_label", "主辦單位：")),
                     font["east_asia"], font["latin"], info_pt, bold=True)
        if agency:
            set_run_font(p.add_run(agency), font["east_asia"], font["latin"],
                         info_pt, bold=True)
        else:
            cover_status.placeholders += 1
            self.placeholders.append(Placeholder(0, "封面", "主辦機關",
                                                 "請填入主辦機關全銜（封面必填）。"))
            set_run_font(p.add_run("【需人工補｜封面】主辦機關"), font["east_asia"],
                         font["latin"], info_pt, bold=True,
                         color=self._ph_color())

        p = self._para(align=WD_ALIGN_PARAGRAPH.LEFT, before=0, after=after_pt)
        set_run_font(p.add_run(cfg.get("design_unit_label", "設計監造單位：")),
                     font["east_asia"], font["latin"], info_pt, bold=True)
        set_run_font(p.add_run(cfg.get("design_unit", "")), font["east_asia"],
                     font["latin"], info_pt, bold=True)

        # ── 日期 ──
        self.blank(int(cfg.get("spacers_before_date", 2)), spacer)
        p = self._para(align=WD_ALIGN_PARAGRAPH.LEFT, after=0)
        date_text = self._cover_date_text()
        set_run_font(p.add_run(date_text), font["east_asia"], font["latin"],
                     cfg.get("date_size_pt", 18), bold=True)

        cover_status.status = "partial" if cover_status.placeholders else "auto"

    def _ph_color(self) -> tuple[int, int, int]:
        """佔位符文字颜色（跟 placeholder.fill 同調，用深色字才看得清）。"""
        return (191, 64, 0)

    def _cover_text_width_cm(self) -> float:
        page = self.style["page"]
        m = page["margin_cm"]
        return page["width_cm"] - m["left"] - m["right"]

    @staticmethod
    def _display_units(text: str) -> float:
        """字寬估算：全形字 1 em、半形 0.5 em（只用来決定字級，不追求精確排版）。"""
        total = 0.0
        for ch in text:
            total += 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5
        return max(total, 1.0)

    def _fit_title_size(self, text: str, size_pt: float,
                        max_lines: int = 2, floor_pt: float = 24) -> float:
        """案名過長時逐級降字，直到可用寬度内不超過 max_lines 行。"""
        width_cm = self._cover_text_width_cm()
        units = self._display_units(text)
        pt = float(size_pt)
        while pt > floor_pt:
            per_line = width_cm / (pt * 0.03528)
            if per_line > 0 and -(-units // per_line) <= max_lines:
                return pt
            pt -= 2
        return float(floor_pt)

    def _cover_date_text(self) -> str:
        """封面日期：優先用 project.date（YYYY-MM-DD）轉民國年月；沒有就用今天。"""
        cfg = self.cover_cfg
        pat = cfg.get("date_pattern", "中 華 民 國 {year} 年 {month} 月")
        raw = (self.model.project.get("rocin_date") or "").strip()
        if raw and ("年" in raw):
            return raw
        src = (self.model.project.get("date") or "").strip()
        year = month = None
        for cand in (src, _dt.date.today().isoformat()):
            m = re.match(r"(\d{4})[-/](\d{1,2})", cand or "")
            if m:
                year, month = int(m.group(1)), int(m.group(2))
                break
        if year is None:
            return pat.format(year="　", month="　")
        return pat.format(year=year - 1911, month=month)

    def toc(self):
        self.doc.add_page_break()
        p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER, after=14, outline_level=None)
        f = self.fonts["heading1"]
        set_run_font(p.add_run("目　錄"), f["east_asia"], f["latin"],
                     self.sizes["heading1"], bold=True)
        p_toc = self._para(after=0)
        add_field(p_toc, ' TOC \\o "1-2" \\h \\z \\u ',
                  "（目錄將於產製 PDF 時自動展開）",
                  self.fonts["body"]["east_asia"], self.fonts["body"]["latin"],
                  self.sizes["body"])
        # 文件性質聲明（封面只留案名／單位／日期，聲明移到目錄頁下方）
        self.boilerplate_block("disclaimer_short")

    # ==================================================================
    # 附錄
    # ==================================================================
    def appendix_title(self, letter: str, title: str):
        text = self.num["appendix"].format(letter=letter, title=title)
        p = self.doc.add_paragraph(style="Heading 1")
        p.paragraph_format.page_break_before = True
        run = p.add_run(text)
        f = self.fonts["heading1"]
        set_run_font(run, f["east_asia"], f["latin"], self.sizes["heading1"], bold=True)
        self._sec_index = [0, 0]

    def appendix_status_table(self):
        labels = self.ph_cfg["status_labels"]
        spec = {
            "caption": "章節資料狀態表",
            "columns": [
                {"name": "章次", "width_cm": 1.8, "align": "center"},
                {"name": "章節名稱", "width_cm": 5.4, "align": "left"},
                {"name": "狀態", "width_cm": 2.6, "align": "center"},
                {"name": "自動填入區塊", "width_cm": 2.4, "align": "center"},
                {"name": "需人工補項目", "width_cm": 2.6, "align": "center"},
            ],
            "rows": [
                [
                    "封面" if st.no == 0 else f"第 {st.no} 章",
                    st.title,
                    labels.get(st.status, st.status),
                    str(st.auto_sections) if (st.status != "na" and st.no != 0) else "—",
                    str(st.placeholders) if st.status != "na" else "—",
                ]
                for st in self.chapter_status
            ],
        }
        self.table(spec)

    def appendix_todo_table(self):
        if not self.placeholders:
            self.para("本次產製之案件資料完整，無「需人工補」項目。")
            return
        spec = {
            "caption": "待補資料清單",
            "columns": [
                {"name": "序號", "width_cm": 1.6, "align": "center"},
                {"name": "所屬章節", "width_cm": 3.6, "align": "left"},
                {"name": "待補項目", "width_cm": 4.6, "align": "left"},
                {"name": "補件說明／建議處理方式", "width_cm": 5.7, "align": "left"},
            ],
            "rows": [
                [
                    str(i),
                    ("封面" if p.chapter_no == 0 else f"第 {p.chapter_no} 章 {p.chapter_title}"),
                    p.label,
                    p.hint or "—",
                ]
                for i, p in enumerate(self.placeholders, 1)
            ],
        }
        self.table(spec)

    def appendix_meta(self, extra: dict | None = None):
        project = self.model.project
        rows = [
            ["工程名稱", project["full_name"]],
            ["報告名稱", project["report_title"]],
            ["案件類別", project.get("category") or "（未宣告）"],
            ["報告版次", project.get("version") or "—"],
            ["產製日期", project.get("date") or "—"],
            ["產製工具", "tools/report/make_report.py（python-docx 排版 → WordCraft 轉檔）"],
            ["案件資料檔", self.model.case_path.name],
            ["範本目錄", "templates/report/（style.json／chapters.json／regulations.json／boilerplate.json）"],
            ["自動填入區塊總數", str(sum(st.auto_sections for st in self.chapter_status))],
            ["需人工補項目總數", str(len(self.placeholders))],
        ]
        if extra:
            for k, v in extra.items():
                rows.append([k, v])
        self.table({"caption": "產製與版本資訊", "columns": ["項目", "內容"], "rows": rows})

        if self.model.consistency:
            self.table({
                "caption": "數量一致性自我檢核",
                "columns": [
                    {"name": "檢核項目", "width_cm": 3.4, "align": "left"},
                    {"name": "資料採用值", "width_cm": 3.0, "align": "center"},
                    {"name": "複核公式", "width_cm": 4.4, "align": "left"},
                    {"name": "複核值", "width_cm": 2.7, "align": "center"},
                    {"name": "結果", "width_cm": 2.0, "align": "center"},
                ],
                "rows": [
                    [c.item, c.claimed, c.formula, c.computed, c.result]
                    for c in self.model.consistency
                ],
                "note": "複核結果由產生器以案件 JSON 內數據重新計算比對，容許差異 1%；"
                        "不一致者須回頭檢查原始數據來源。",
            })
        self.boilerplate_block("data_basis")
        self.boilerplate_block("generator_note")
        self.boilerplate_block("disclaimer_long")

    def appendix_crosscheck_table(self, rows: list, meta: dict | None = None):
        """附錄 D：OCSS 交叉驗算紀錄（本專案引擎 vs 開放計算環境）。"""
        meta = meta or {}
        labels = {"pass": "一致", "handled": "已處置", "fail": "未處置差異"}
        disp_labels = {"engine_fixed": "已修正引擎", "template_issue": "模板問題",
                       "explained": "已說明差異"}
        body = []
        for r in rows:
            ours = r.get("ours")
            theirs = r.get("ocss")
            rel = r.get("rel")
            body.append([
                r.get("case") or "—",
                r.get("item") or "—",
                ("%g" % ours) if isinstance(ours, (int, float)) else "—",
                ("%g" % theirs) if isinstance(theirs, (int, float)) else "—",
                (r.get("unit") or "—"),
                ("%.4g%%" % (rel * 100.0)) if isinstance(rel, (int, float)) else "—",
                labels.get(r.get("status"), r.get("status") or "—"),
                disp_labels.get(r.get("disposition"), "") if r.get("disposition") else "",
            ])
        self.table({
            "caption": "計算交叉驗算紀錄（本專案引擎 vs Open CalcSheet Studio）",
            "columns": [
                {"name": "對照案例", "width_cm": 3.4, "align": "left"},
                {"name": "比對項目", "width_cm": 3.0, "align": "left"},
                {"name": "本專案", "width_cm": 2.0, "align": "right"},
                {"name": "OCSS", "width_cm": 2.0, "align": "right"},
                {"name": "單位", "width_cm": 1.3, "align": "center"},
                {"name": "相對差異", "width_cm": 1.5, "align": "right"},
                {"name": "結果", "width_cm": 1.4, "align": "center"},
                {"name": "處置", "width_cm": 1.6, "align": "center"},
            ],
            "rows": body,
            "note": "「一致」指差值在案例容差內；「已處置」指差異經查明並有處置說明"
                    "（引擎已修正／模板問題／已說明差異）；「未處置差異」不得隨交付"
                    "（須先修正引擎或另案說明）。相對差異以 OCSS 值為分母。",
        })
        extra = []
        if meta.get("project_file"):
            extra.append(["逐式計算書專案檔", meta["project_file"]])
        if meta.get("case_count") is not None:
            extra.append(["對照案例數", str(meta.get("case_count"))])
        if meta.get("item_count") is not None:
            extra.append(["比對項數", str(meta.get("item_count"))])
        if meta.get("failed") is not None:
            extra.append(["未處置差異數", str(meta.get("failed"))])
        if meta.get("handled") is not None:
            extra.append(["已處置差異數", str(meta.get("handled"))])
        if meta.get("note"):
            extra.append(["產出說明", meta["note"]])
        if extra:
            self.table({"caption": "交叉驗算產製資訊",
                        "columns": ["項目", "內容"], "rows": extra})

    def end_mark(self):
        p = self._para(align=WD_ALIGN_PARAGRAPH.CENTER, before=18, after=6)
        f = self.fonts["caption"]
        set_run_font(p.add_run("— 本報告結束 —"), f["east_asia"], f["latin"],
                     self.sizes["caption"], bold=False)

    # ==================================================================
    # 存檔
    # ==================================================================
    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        return path

    def stats(self) -> dict:
        return {
            "tables": self.table_no,
            "figures": self.figure_no,
            "placeholders": len(self.placeholders),
            "chapters": len([s for s in self.chapter_status if s.no > 0]),
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
