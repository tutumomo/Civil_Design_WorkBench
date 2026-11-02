# -*- coding: utf-8 -*-
r"""AutoCAD 出圖型式表（.ctb）讀取、比對與產生。

本項目規定（見 tools\drawing_rules.py）：monochrome.ctb 灰階出圖，
顏色 1~8 對應線粗 0.20／0.20／0.20／0.25／0.35／0.40／0.15／0.10 mm。

CTB 是 PIA 格式：ASCII 表頭 + 4 byte magic + 未壓縮長度 + 壓縮長度 + zlib 資料。
本模組只改每個顏色的 lineweight，不動其他欄位；產出的是新檔案，不會覆寫
AutoCAD 安裝目錄或使用者的 Plot Styles 資料夾。

用法：
  python ctb.py report <檔案.ctb>
  python ctb.py verify <檔案.ctb>              # 與規定表比對，不符退出碼 1
  python ctb.py build  <來源.ctb> <輸出.ctb>    # 依規定表重寫顏色 1~8 的線粗
"""
import argparse
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from drawing_rules import LINE_WEIGHT_BY_COLOR   # noqa: E402

MAGIC = b"\x9c\x91\x9b\xc7"
DEFAULT_OUT = os.path.join(HERE, "plot", "monochrome.ctb")


def load(path):
    """回傳 (prefix, text)；prefix 為 magic 之後、含兩個長度欄位的表頭"""
    raw = open(path, "rb").read()
    i = raw.find(b"pmzlibcodec")
    if i < 0:
        raise ValueError("不是 CTB／STB：找不到 pmzlibcodec")
    j = i + len(b"pmzlibcodec")
    if raw[j:j + 4] != MAGIC:
        raise ValueError("CTB 表頭格式不同（magic 不符）")
    text = zlib.decompress(raw[j + 12:]).decode("latin-1")
    raw_len = struct.unpack("<I", raw[j + 4:j + 8])[0]
    if raw_len != len(text.encode("latin-1")):
        raise ValueError("CTB 長度欄位與實際內容不符")
    return raw[:j + 12], text


def save(prefix, text, path):
    data = text.encode("latin-1")
    comp = zlib.compress(data, 9)
    out = prefix[:-8] + struct.pack("<II", len(data), len(comp)) + comp
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    open(path, "wb").write(out)
    return path


def parse(text):
    """回傳 (lineweight_list{索引: mm}, {顏色: {lineweight: 索引, block: 原文}})"""
    m = re.search(r"(?:custom_lineweight_table|lineweight_list)\{(.*?)\}", text, re.S)
    if not m:
        raise ValueError("CTB 找不到線粗對照表（custom_lineweight_table）")
    table = {int(k): float(v) for k, v in re.findall(r"(\d+)=([0-9.]+)", m.group(1))}
    colors = {}
    for r in re.finditer(r'(?ms)^\s*(\d+)\{\s*$.*?name="Color_(\d+).*?^\s*\}\s*$', text):
        block = r.group(0)
        lw = re.search(r"lineweight=(\d+)", block)
        colors[int(r.group(2))] = {"index": int(lw.group(1)) if lw else None, "block": block}
    return table, colors


def current(path):
    """回傳 {顏色: 線粗 mm}（只列 1~8）"""
    table, colors = parse(load(path)[1])
    return {c: table.get(v["index"]) for c, v in colors.items() if c <= 8}


def build(src, dst, table=None):
    table_spec = table or LINE_WEIGHT_BY_COLOR
    prefix, text = load(src)
    lw_table, colors = parse(text)
    for c, mm in sorted(table_spec.items()):
        if c not in colors:
            raise ValueError(f"來源 CTB 沒有 Color_{c}")
        idx = min(lw_table, key=lambda k: abs(lw_table[k] - mm))
        block = colors[c]["block"]
        new = re.sub(r"lineweight=\d+", "lineweight=%d" % idx, block, count=1)
        text = text.replace(block, new, 1)
    return save(prefix, text, dst)


def verify(path, table=None):
    """回傳 [(顏色, 規定 mm, 實際 mm)]"""
    table_spec = table or LINE_WEIGHT_BY_COLOR
    got = current(path)
    return [(c, mm, got.get(c)) for c, mm in sorted(table_spec.items())
            if got.get(c) is None or abs(got[c] - mm) > 0.001]


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("report")
    r.add_argument("ctb")
    v = sp.add_parser("verify")
    v.add_argument("ctb")
    b = sp.add_parser("build")
    b.add_argument("src")
    b.add_argument("dst", nargs="?", default=DEFAULT_OUT)
    a = ap.parse_args()

    if a.cmd == "report":
        got = current(a.ctb)
        for c in range(1, 9):
            want = LINE_WEIGHT_BY_COLOR[c]
            mark = "" if got.get(c) == want else "  <-- 規定 %.2f" % want
            print("  顏色 %d：%.2f mm%s" % (c, got.get(c) or -1, mark))
        return 0
    if a.cmd == "verify":
        bad = verify(a.ctb)
        if bad:
            print("✗ %d 個顏色不符規定：" % len(bad))
            for c, want, now in bad:
                print("   顏色 %d：規定 %.2f，實際 %s" % (c, want, "%.2f" % now if now else "無"))
            return 1
        print("✓ 顏色 1~8 線粗與規定相符")
        return 0
    out = build(a.src, a.dst)
    bad = verify(out)
    if bad:
        print("✗ 產出後比對失敗：%s" % bad)
        return 1
    print("✓ 已產出 %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
