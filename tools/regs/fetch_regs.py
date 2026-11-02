"""Download Taiwan design codes / regulations into data\\法規 and extract searchable text.

Each source is downloaded into a fresh staging folder, its file type is checked by magic
bytes, text is extracted (PDF via PyMuPDF, law.moj / law.moa pages by stripping HTML),
and only validated files are copied to data\\法規 as <名稱_版次>.<ext> plus _全文.txt and
_全文_NFKC.txt. A manifest (data\\法規\\_regs_manifest.json) records sha256, pages, size,
source URL and fetch time for the catalogue doc.

usage: python -I -X utf8 fetch_regs.py [--only ID ...] [--stage DIR]
"""
import argparse
import datetime
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import os
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(os.environ.get("CIVIL_AI_ROOT") or Path(__file__).resolve().parents[2])
OUT = ROOT / "data" / "法規"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
MOTC = "https://www.motc.gov.tw/ch/app/data/doc?id=740&module=divpubreg&type=s&preview=&aplistdn="
LAWMOJ = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode="
GLRS = "https://glrs.moi.gov.tw/LawContent.aspx?id="

# id, file stem (名稱_版次), kind, url, authority, version note
SOURCES = [
    # ---- 內政部國土管理署（建築） ----
    ("rc112", "建築物混凝土結構設計規範_1120810", "file",
     "https://www.nlma.gov.tw/filesys/file/EMMA/c1130219-1.pdf",
     "內政部", "112.08.10 台內營字第1120809921號令修正，113.01.01 生效"),
    ("found112", "建築物基礎構造設計規範_1120620", "file",
     "https://www.nlma.gov.tw/uploads/files/53651dae74223e6599e20838bb8c4f2a.pdf",
     "內政部", "112.06.20 台內營字第1120807974號令修正，113.01.01 生效"),
    ("seis111", "建築物耐震設計規範及解說_111年版", "file",
     "https://seaport.ncree.org/static/pdf/sederes/20220614_111年版建築物耐震設計規範及解說.pdf",
     "內政部（國震中心轉載）", "111 年版全文（已被 113.03.01 版取代，留作對照）"),
    ("seis113", "建築物耐震設計規範及解說_1130301", "glrs", GLRS + "GL000180",
     "內政部", "113.03.01 台內國字第1130801422號令修正"),
    ("wind103", "建築物耐風設計規範及解說_1031203", "glrs", GLRS + "GL000670",
     "內政部", "103.12.03 修正，104.01.01 生效"),
    ("wind103full", "建築物耐風設計規範及解說_1031203_全文", "file",
     "https://windexpert.ce.tku.edu.tw/newcode/Dfiles/New_wind_code.pdf",
     "內政部（淡江大學風工程研究中心轉載）", "103.12.03 修正版全文（glrs 附件僅 6 頁公告）"),
    ("steel99", "鋼構造建築物鋼結構設計技術規範_990916", "glrs_all", GLRS + "GL000143",
     "內政部", "96.06 發布，99.09.16 修正第十三．二點（含容許應力法與極限設計法兩冊）"),
    ("urbanroad113", "市區道路及附屬工程設計規範_1130912", "file",
     "https://www.nlma.gov.tw/filesys/file/chinese/law/c1130912-1.pdf",
     "內政部", "113.09.12 修正"),
    # ---- 交通部部頒規範（公路） ----
    ("hwroute115", "公路路線設計規範_11507版", "file",
     MOTC + "&serno=447&detailNo=1534440204138450944",
     "交通部", "115.07.28 交綜(一)字第11586004125號"),
    ("hwdrain107", "公路排水設計規範_1070206", "file",
     MOTC + "&serno=414&detailNo=2", "交通部", "107.02.06 修正版（附件標示）"),
    ("hwslope104", "公路邊坡工程設計規範_10412", "file",
     MOTC + "&serno=405&detailNo=1", "交通部", "104.12 版全文"),
    ("hwslope111", "公路邊坡工程設計規範_1110427_修正總說明及對照表", "file",
     MOTC + "&serno=405&detailNo=2", "交通部", "111.04.27 修正條文對照表"),
    ("flexpave91", "柔性鋪面設計規範_910131", "file",
     MOTC + "&serno=353&detailNo=1194539920614494208", "交通部", "91.01.31 版"),
    ("traffic114", "交通工程規範_11407", "file",
     MOTC + "&serno=434&detailNo=1417794078568878080", "交通部", "114.07 部分條文修正"),
    ("hwconst112", "公路工程施工規範_1120222", "file",
     MOTC + "&serno=439&detailNo=1077840993601982464", "交通部", "112.02.22"),
    ("hwbridge", "公路橋梁設計規範_全文", "file",
     MOTC + "&serno=424&detailNo=1", "交通部", "本文（版次見封面）"),
    ("hwbridge104", "公路橋梁設計規範_1040413_修訂", "file",
     MOTC + "&serno=424&detailNo=2", "交通部", "104.04.13 規範修訂"),
    ("hwbridge109", "公路橋梁設計規範_1090103_修訂總說明及對照表", "file",
     MOTC + "&serno=424&detailNo=3", "交通部", "109.01.03 修訂總說明及對照表"),
    # ---- 法規命令（全國法規資料庫） ----
    ("btr_general", "建築技術規則總則編", "lawmoj", LAWMOJ + "D0070114", "內政部", ""),
    ("btr_design", "建築技術規則建築設計施工編", "lawmoj", LAWMOJ + "D0070115", "內政部", ""),
    ("btr_struct", "建築技術規則建築構造編", "lawmoj", LAWMOJ + "D0070116", "內政部", ""),
    ("btr_equip", "建築技術規則建築設備編", "lawmoj", LAWMOJ + "D0070117", "內政部", ""),
    ("swc_act", "水土保持法", "lawmoj", LAWMOJ + "M0110001", "農業部", ""),
    ("swc_rule", "水土保持法施行細則", "lawmoj", LAWMOJ + "M0110002", "農業部", ""),
    ("swc_review", "水土保持計畫審核監督辦法", "lawmoj", LAWMOJ + "M0110012", "農業部", ""),
    ("slopeland_act", "山坡地保育利用條例", "lawmoj", LAWMOJ + "M0110006", "農業部", ""),
    ("slopeland_rule", "山坡地保育利用條例施行細則", "lawmoj", LAWMOJ + "M0110007", "農業部", ""),
    ("urbanroad_act", "市區道路條例", "lawmoj", LAWMOJ + "D0070007", "內政部", ""),
    ("sewer_std", "下水道工程設施標準", "lawmoj", LAWMOJ + "D0070071", "內政部", ""),
    ("traffic_sign", "道路交通標誌標線號誌設置規則", "lawmoj", LAWMOJ + "K0040014", "交通部、內政部", ""),
    # ---- 主管機關法規共用系統（主文＋附表／附圖） ----
    ("farmroad108", "農路設計規範_1081028", "moa_all",
     "https://law.moa.gov.tw/LawContent.aspx?id=GL000744",
     "農業部", "108.10.28 農授水保字第1081861522A號令修正"),
    ("airconst110", "營建工程空氣污染防制設施管理辦法_1101018", "moenv_all",
     "https://oaout.moenv.gov.tw/law/LawContent.aspx?id=FL024889",
     "環境部", "110.10.18 環署空字第1101141194號令修正"),
]


def curl(url, dest, referer=None):
    cmd = ["curl.exe", "-4", "-sS", "-L", "--retry", "2", "-m", "600", "-A", UA,
           "-D", str(dest) + ".hdr", "-o", str(dest)]
    if referer:
        cmd += ["-e", referer]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"curl exit {r.returncode}: {r.stderr.decode('utf-8', 'replace')[:200]}")


def glrs_file_url(page_url, tmp):
    """Resolve the full-text attachment (Download.ashx) on a glrs.moi.gov.tw law page."""
    curl(page_url, tmp)
    t = tmp.read_bytes().decode("utf-8", "replace")
    m = re.search(r'href="(Download\.ashx\?FileID=\d+[^"]*type=LAW[^"]*)"', t)
    if not m:
        raise RuntimeError("no Download.ashx attachment on glrs page")
    d = re.search(r"日期：.*?民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", re.sub(r"<[^>]+>", " ", t), re.S)
    return "https://glrs.moi.gov.tw/" + html.unescape(m.group(1)), \
        (f"{int(d.group(1))}.{d.group(2)}.{d.group(3)}" if d else "")


def glrs_all(page_url, stage, sid, outdir):
    """Download every attachment on a glrs page (multi-chapter codes) and collect them."""
    page = stage / (sid + "_page.html")
    curl(page_url, page)
    t = page.read_bytes().decode("utf-8", "replace")
    links = re.findall(r'href="(Download\.ashx\?FileID=\d+[^"]*type=LAW[^"]*)"[^>]*>(.*?)</a>', t, re.S)
    if not links:
        raise RuntimeError("no Download.ashx attachments on glrs page")
    xdir = stage / (sid + "_x")
    if xdir.exists():
        shutil.rmtree(xdir)  # our own staging folder from a previous run
    xdir.mkdir(parents=True)
    for i, (h, label) in enumerate(links, 1):
        name = re.sub(r'[\\/:*?"<>|\s]+', "_", html.unescape(re.sub(r"<[^>]+>", "", label)).strip())
        dest = xdir / f"{i:02d}_{name}"
        curl("https://glrs.moi.gov.tw/" + html.unescape(h), dest)
        typ = sniff(dest)
        if typ not in ("pdf", "doc", "zip"):
            raise RuntimeError(f"attachment {name} is {typ}")
        want = ".pdf" if typ == "pdf" else (".doc" if typ == "doc" else ".docx")
        if dest.suffix.lower() != want:
            dest.rename(dest.with_name(dest.stem + want) if dest.suffix.lower() in (".pdf", ".doc", ".docx")
                        else dest.with_name(dest.name + want))
    return collect(xdir, outdir, flatten=False), len(links)


def portal_law_text(raw):
    """Extract a law.moa / oaout.moenv LawContent page (title, date, body)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    node = soup.select_one(".law-reg-content.law-article")
    if node is None:
        raise RuntimeError("no .law-reg-content.law-article on portal page")

    title = ""
    amended = ""
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td:
            continue
        key = " ".join(th.get_text(" ", strip=True).split())
        val = " ".join(td.get_text(" ", strip=True).split())
        if key.startswith("法規名稱"):
            title = re.sub(r"\s*英$", "", val).strip()
        elif key.startswith("修正日期"):
            amended = val

    body = BeautifulSoup(str(node), "html.parser")
    for br in body.find_all("br"):
        br.replace_with("\n")
    for block in body.find_all(["div", "p", "pre", "tr", "li"]):
        block.append("\n")
    text = body.get_text("\n")
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        raw_title = re.sub(r"<[^>]+>", "", m.group(1)) if m else ""
        title = re.split(r"-法規內容-|法規內容-|－", raw_title)[-1].strip()
    if not amended:
        amended = "（頁面未標示）"
    header = f"{title}\n修正日期：{amended}\n\n"
    return {"title": title, "amended": amended}, header + text


def odt_text(p):
    """Read visible text from an ODT attachment without requiring LibreOffice."""
    import zipfile
    from bs4 import BeautifulSoup

    with zipfile.ZipFile(p) as z:
        raw = z.read("content.xml").decode("utf-8", "replace")
    soup = BeautifulSoup(raw, "xml")
    for br in soup.find_all("text:line-break"):
        br.replace_with("\n")
    for tab in soup.find_all("text:tab"):
        tab.replace_with("\t")
    for block in soup.find_all(["text:p", "text:h", "table:table-row"]):
        block.append("\n")
    text = soup.get_text("\n")
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def portal_all(page_url, stage, sid, outdir):
    """Fetch a portal law's main text and all selected attachments into one folder."""
    page = stage / (sid + "_page.html")
    curl(page_url, page)
    raw_page = page.read_text(encoding="utf-8", errors="replace")
    meta, main_text = portal_law_text(raw_page)

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw_page, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "Download.ashx" not in href:
            continue
        label = " ".join(a.get_text(" ", strip=True).split())
        if sid == "airconst110" and not label.startswith("附表"):
            continue
        links.append((label or Path(href).stem, urljoin(page_url, href)))
    if not links:
        raise RuntimeError("portal page has no selected Download.ashx attachments")

    if outdir.exists():
        shutil.rmtree(outdir)  # derived folder owned by this fetcher
    outdir.mkdir(parents=True)
    main_html = outdir / "main.html"
    main_html.write_bytes(raw_page.encode("utf-8"))

    parts, all_bytes = [], [raw_page.encode("utf-8")]
    total_pages = 0
    for i, (label, url) in enumerate(links, 1):
        label_path = Path(label)
        ext = label_path.suffix.lower()
        if ext not in (".pdf", ".odt", ".doc", ".docx"):
            raise RuntimeError(f"unknown attachment extension in label: {label}")
        clean = re.sub(r'[\\/:*?"<>|\s]+', "_", label_path.stem).strip("_") + ext
        dest = outdir / f"{i:02d}_{clean}"
        curl(url, dest, referer=page_url)
        Path(str(dest) + ".hdr").unlink(missing_ok=True)
        typ = sniff(dest)
        if typ == "pdf":
            n, text = pdf_text(dest)
            total_pages += n
            page_note = f"{n} 頁"
        elif typ == "zip" and dest.suffix.lower() == ".odt":
            text = odt_text(dest)
            n = None
            page_note = "ODT"
        else:
            raise RuntimeError(f"unsupported attachment {label}: {typ}")
        if len(text.strip()) < 20:
            raise RuntimeError(f"attachment has too little text: {label}")
        all_bytes.append(dest.read_bytes())
        parts.append({"file": dest.name, "pages": n, "text_chars": len(text), "label": label})
        main_text += f"\n\n##### {label}\n{text}"

    rec = {
        "type": "multi", "kind": "law", "attachments": len(links), "page": page_url,
        "bytes": sum(len(x) for x in all_bytes),
        "sha256": hashlib.sha256(b"".join(all_bytes)).hexdigest(),
        "pages": total_pages or None, "parts": parts,
    }
    rec.update(meta)
    return rec, main_text, {"folder": outdir.name}


def sniff(p):
    head = p.read_bytes()[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    if head.startswith(b"Rar!") or head.startswith(b"7z\xbc\xaf"):
        return "archive"
    if head.startswith(b"PK"):
        import zipfile
        names = zipfile.ZipFile(p).namelist()
        if "word/document.xml" in names or "content.xml" in names:
            return "zip"  # docx / odt
        return "archive"
    return "html"


def header_filename(hdr):
    m = re.findall(r"filename\*?=(?:UTF-8'')?\"?([^\";\r\n]+)", hdr, re.I)
    if not m:
        return ""
    from urllib.parse import unquote
    return unquote(m[-1])


def pdf_text(p):
    import fitz
    with fitz.open(p) as d:
        return d.page_count, "\n".join(f"\n=== p.{i + 1} ===\n" + pg.get_text() for i, pg in enumerate(d))


def docx_text(p):
    import docx
    d = docx.Document(p)
    return "\n".join(par.text for par in d.paragraphs)


def word_to_pdf(src, dst):
    """Convert .doc/.docx/.odt to PDF with a private, invisible Word instance."""
    import win32com.client
    w = win32com.client.DispatchEx("Word.Application")
    w.Visible = False
    w.DisplayAlerts = 0
    try:
        d = w.Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False)
        d.SaveAs2(str(dst), FileFormat=17)  # wdFormatPDF
        d.Close(False)
    finally:
        w.Quit()


def unpack(raw, xdir, outdir):
    """Extract an archive, keep document files only, return [(Path in outdir, pages, text)].

    A .doc/.docx/.odt whose sibling PDF exists is skipped; otherwise Word converts it to PDF.
    """
    if xdir.exists():
        shutil.rmtree(xdir)  # our own staging folder from a previous run
    xdir.mkdir(parents=True)
    r = subprocess.run(["7z", "x", "-y", f"-o{xdir}", str(raw)], capture_output=True)
    if r.returncode:
        raise RuntimeError("7z failed: " + r.stdout.decode("utf-8", "replace")[-300:])
    return collect(xdir, outdir)


def collect(xdir, outdir, flatten=True):
    """Copy document files from a staging folder to outdir as PDFs, return [(Path, pages, text)]."""
    docs = sorted(p for p in xdir.rglob("*") if p.suffix.lower() in (".pdf", ".doc", ".docx", ".odt"))
    pdf_stems = {p.with_suffix("").as_posix().lower() for p in docs if p.suffix.lower() == ".pdf"}
    keep = []
    for p in docs:
        if p.suffix.lower() == ".pdf":
            keep.append(p)
        elif p.with_suffix("").as_posix().lower() not in pdf_stems:
            conv = p.with_suffix(".pdf")
            word_to_pdf(p, conv)
            keep.append(conv)
    if not keep:
        raise RuntimeError("archive has no document files")
    # flatten a single top-level folder so files sit directly in outdir
    base = xdir
    tops = [c for c in xdir.iterdir()]
    if flatten and len(tops) == 1 and tops[0].is_dir():
        base = tops[0]
    if outdir.exists():
        shutil.rmtree(outdir)  # only ever a folder this script created
    res = []
    for p in keep:
        dest = outdir / p.relative_to(base)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        if sniff(dest) != "pdf":
            raise RuntimeError(f"not a PDF after extraction: {dest.name}")
        n, t = pdf_text(dest)
        res.append((dest, n, t))
    return res


def law_text(raw):
    t = raw
    i = t.find('class="law-reg-content"')
    body = t[t.find(">", i) + 1:] if i >= 0 else t
    name = re.search(r'id="hlLawName"[^>]*>(.*?)<', t, re.S)
    date = re.search(r'id="trLNNDate".*?<td[^>]*>(.*?)</td>', t, re.S)
    hist = re.search(r'id="trLNNHis".*?<td[^>]*>(.*?)</td>', t, re.S) or \
        re.search(r'id="trLNODate".*?<td[^>]*>(.*?)</td>', t, re.S)
    body = re.split(r'<div class="law-moj-content">|id="ftr"|<footer', body)[0]
    body = re.sub(r"(?i)<br\s*/?>|</div>|</p>|</tr>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body)
    body = "\n".join(ln.strip() for ln in body.splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    clean = lambda m: re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else ""
    meta = {"title": clean(name), "amended": clean(date), "history": clean(hist)[:300]}
    hdr = f"{meta['title']}\n修正日期：{meta['amended']}\n"
    return meta, hdr + "\n" + body


def fetch_doc(raw, stem, kind):
    """Classify a downloaded file and store it under data\\法規. Returns (rec_update, text, files, stem_v)."""
    typ = sniff(raw)
    rec = {}
    if kind == "lawmoj":
        if typ != "html":
            raise RuntimeError(f"expected html, got {typ}")
        meta, text = law_text(raw.read_bytes().decode("utf-8", "replace"))
        if len(text) < 2000 or not meta["title"]:
            raise RuntimeError(f"law page too short / no title ({len(text)} chars)")
        rec.update(meta, type="html", kind="law")
        stem_v = stem + "_" + re.sub(r"\D", "", meta["amended"].replace("民國", ""))[:7]
        rec["name"] = stem_v
        return rec, text, {}, stem_v
    if typ == "html":
        raise RuntimeError("got HTML instead of a document: "
                           + raw.read_bytes()[:200].decode("utf-8", "replace"))
    if typ == "archive":
        outdir = OUT / stem
        parts = unpack(raw, raw.with_name(raw.name + "_x"), outdir)
        rec["type"] = "archive"
        rec["pages"] = sum(n for _, n, _ in parts)
        rec["parts"] = [{"file": d.relative_to(OUT).as_posix(), "pages": n} for d, n, _ in parts]
        text = "\n".join(f"\n##### {d.name}\n" + t for d, _, t in parts)
        return rec, text, {"folder": outdir.name}, stem
    ext = {"pdf": ".pdf", "doc": ".doc"}.get(typ)
    if typ == "zip":
        hdr = Path(str(raw) + ".hdr").read_text(encoding="latin-1")
        ext = ".odt" if header_filename(hdr).lower().endswith(".odt") else ".docx"
    rec["type"] = ext.lstrip(".")
    dest = OUT / (stem + ext)
    shutil.copyfile(raw, dest)
    files = {"original": dest.name}
    if typ != "pdf":  # Word documents -> PDF copy for page count and text
        pdf = OUT / (stem + ".pdf")
        word_to_pdf(dest, pdf)
        files["pdf"] = pdf.name
        rec["pages"], text = pdf_text(pdf)
    else:
        rec["pages"], text = pdf_text(raw)
    return rec, text, files, stem


def write_text(rec, text, files, stem_v):
    if text:
        txt = OUT / (stem_v + "_全文.txt")
        txt.write_text(text, encoding="utf-8")
        (OUT / (stem_v + "_全文_NFKC.txt")).write_text(
            unicodedata.normalize("NFKC", text), encoding="utf-8")
        files["text"] = txt.name
        rec["text_chars"] = len(text)
        # scanned PDFs yield almost no text -> flag for OCR
        if rec.get("pages") and len(text) / rec["pages"] < 200:
            rec["warning"] = "文字量過少，可能為掃描影像，需 OCR"
    rec["files"] = files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--stage", default=str(OUT / "_dl_20261029" / "raw"))
    a = ap.parse_args()
    stage = Path(a.stage)
    stage.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "_regs_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    bad = 0
    for sid, stem, kind, url, auth, note in SOURCES:
        if a.only and sid not in a.only:
            continue
        raw = stage / sid
        rec = {"id": sid, "name": stem, "authority": auth, "version": note, "url": url, "fetched": now}
        try:
            if kind == "glrs_all":
                outdir = OUT / stem
                parts, nlinks = glrs_all(url, stage, sid, outdir)
                pdfs = [d for d, _, _ in parts]
                rec.update(type="multi", attachments=nlinks,
                           bytes=sum(d.stat().st_size for d in pdfs),
                           sha256=hashlib.sha256(b"".join(d.read_bytes() for d in pdfs)).hexdigest(),
                           pages=sum(n for _, n, _ in parts),
                           parts=[{"file": d.relative_to(OUT).as_posix(), "pages": n} for d, n, _ in parts])
                text = "\n".join(f"\n##### {d.name}\n" + t for d, _, t in parts)
                files, stem_v = {"folder": outdir.name}, stem
            elif kind in ("moa_all", "moenv_all"):
                outdir = OUT / stem
                upd, text, files = portal_all(url, stage, sid, outdir)
                rec.update(upd)
                if sid == "farmroad108":
                    rec.update(kind="law_point", splitter="point")
                stem_v = stem
            else:
                if kind == "glrs":
                    rec["page"] = url
                    url, rec["amended"] = glrs_file_url(url, stage / (sid + "_page.html"))
                    rec["url"] = url
                curl(url, raw)
                hdr = Path(str(raw) + ".hdr").read_text(encoding="latin-1")
                rec.update(bytes=raw.stat().st_size, sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                           server_filename=header_filename(hdr))
                upd, text, files, stem_v = fetch_doc(raw, stem, kind)
                rec.update(upd)
            write_text(rec, text, files, stem_v)
            manifest[sid] = rec
            print(f"OK  {sid:14s} {rec['name']}  {rec['type']}  {rec['bytes']:,}B  "
                  f"pages={rec.get('pages', '-')}  chars={rec.get('text_chars', 0):,}  {rec.get('warning', '')}")
        except Exception as e:  # keep going; report failures at the end
            bad += 1
            manifest.setdefault(sid, {}).update({"id": sid, "name": stem, "url": url,
                                                 "error": str(e)[:300], "fetched": now})
            print(f"ERR {sid:14s} {stem}: {e}")
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done, {bad} failed -> {man_path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
