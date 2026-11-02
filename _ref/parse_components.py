from pathlib import Path
# -*- coding: utf-8 -*-
"""解析「公司土木工程常用元件」已轉出的 DXF，抽出可用於盤點的結構化資訊。

輸出：_ref/components_index.json
每筆含：檔名、層數、單位、模型範圍、圖元數、文字樣本、偵測到的比例、尺寸線索、圖紙版面。
設計原則：
  * 全程 try/except，單檔失敗不影響整體（並記錄 error）
  * 文字只取前 N 筆，避免巨型圖拖慢
  * 不做任何寫入原檔的動作（G: 為唯讀參考）
"""
import json, os, re, sys, traceback

R = str(Path(__file__).resolve().parents[1])
DXF_DIR = os.path.join(R, "_ref", "components_dxf")
manifest = json.load(open(os.path.join(R, "_ref", "manifest.json"), encoding="utf-8"))

SCALE_RE = re.compile(r"1\s*[:：]\s*(\d{1,4})")
UNIT_WORDS = re.compile(r"[（(](?:單位\s*[:：]?\s*)?(cm|CM|公分|M|m|公尺)[）)]")
INSUNITS = {0: "未指定", 1: "inch", 2: "foot", 4: "mm", 5: "cm", 6: "m", 7: "km"}

out = []
for rec in manifest:
    key = rec["key"]
    path = os.path.join(DXF_DIR, key + ".dxf")
    item = {"key": key, "file": rec["file"], "size_kb": round(rec.get("size", 0) / 1024)}
    try:
        import ezdxf
        from ezdxf import bbox
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        item["insunits"] = INSUNITS.get(doc.header.get("$INSUNITS", 0), str(doc.header.get("$INSUNITS")))
        item["layers"] = len([l for l in doc.layers])
        item["layer_names"] = [l.dxf.name for l in doc.layers][:40]
        item["layouts"] = [l.name for l in doc.layouts][:8]
        item["entities"] = len(msp)
        try:
            ext = bbox.extents(msp, fast=True)
            if ext.has_data:
                item["extent"] = [round(ext.size.x, 2), round(ext.size.y, 2)]
        except Exception:
            pass
        texts = []
        for e in msp.query("TEXT MTEXT"):
            try:
                t = e.dxf.text if e.dxftype() == "TEXT" else e.text
                t = re.sub(r"\\[A-Za-z][^;]*;", "", t or "").strip()
                if t:
                    texts.append(t)
            except Exception:
                pass
            if len(texts) >= 400:
                break
        item["n_text"] = len(texts)
        item["texts_sample"] = texts[:25]
        joined = " | ".join(texts)
        scales = sorted({int(m) for m in SCALE_RE.findall(joined)})
        item["scales"] = scales[:6]
        # 單位線索：檔名或文字裡出現 (單位M)／(單位cm)／(cm作圖)／(M作圖)
        item["unit_hint"] = sorted(set(UNIT_WORDS.findall(rec["file"] + " " + joined)))[:3]
        # 尺寸線索：H= / B= / 寬 / 高
        dims = []
        for pat in (r"H\s*[=＝]\s*([0-9.]+)", r"B\s*[=＝]\s*([0-9.]+)",
                    r"[Ww]\s*[=＝]\s*([0-9.]+)"):
            dims += re.findall(pat, joined)
        item["dims"] = sorted(set(dims))[:8]
        item["status"] = "ok"
    except BaseException as ex:
        item["status"] = "error"
        item["error"] = "%s: %s" % (type(ex).__name__, str(ex)[:160])
    out.append(item)
    print("%s %-6s %-52s 層%-3s 圖元%-6s 文字%-4s 比例%s" % (
        key, item.get("status"), rec["file"][:52], item.get("layers"),
        item.get("entities"), item.get("n_text"), item.get("scales")), flush=True)

json.dump(out, open(os.path.join(R, "_ref", "components_index.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("DONE", len(out), "ok=", sum(1 for x in out if x.get("status") == "ok"))
