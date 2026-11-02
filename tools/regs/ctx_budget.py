"""Context-budget watchdog for long regulation-entry sessions (see docs/對話上下文預算.md).

動機：讀原頁圖（B 類）時，圖片會一直累積在對話裡；每輪送出都是「全部重貼」。
2026-11-01 撞牆實例：某 session 累積 211 張圖 = 約 48 MB base64，下一輪請求直接被
上游以 `413 Failed to buffer the request body: length limit exceeded` 拒絕，
而且因為 token 數遠低於壓縮門檻（1M context），自動壓縮永遠不會觸發 → 整條產線卡死。

用法：
  ctx_budget.py                     列出最近 10 個 session（本專案的排前面）
  ctx_budget.py --all               列出全部 session
  ctx_budget.py --session <path>    只算指定 session jsonl
  ctx_budget.py --json              機器可讀輸出
  ctx_budget.py --gate 25           只要有一個 session 超過 25 MB 就 exit 1（給閘門用）

判讀：
  圖片張數 > 200        → 多數供應商直接擋（MiniMax: num of image is larger than the limit: 200）
  估計 body > 10 MB     → 開始注意，準備 compact／換對話
  估計 body > 25 MB     → 危險，下一批做完就換對話
  估計 body > 40 MB     → 已在懸崖邊，隨時 413
"""
import argparse
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DIRS = [
    Path(os.environ.get("CINDY_SESSIONS_DIR", "")) if os.environ.get("CINDY_SESSIONS_DIR") else None,
    Path(os.environ.get("APPDATA", "")) / "CindyGlobal" / "pi-agent-home" / "sessions" if os.environ.get("APPDATA") else None,
    Path.home() / ".pi" / "sessions",
    Path.home() / ".local" / "share" / "cindy" / "pi-agent-home" / "sessions",
]

IMAGE_LIMIT = 200
WARN_MB = 10.0
OVER_MB = 25.0
FATAL_MB = 40.0


def session_dirs():
    out = []
    for d in DEFAULT_DIRS:
        if d and d.is_dir() and d not in out:
            out.append(d)
    return out


def scan(path):
    """回傳這個 session jsonl 的圖片張數、圖片 base64 位元組、其他文字量。"""
    images = 0
    image_bytes = 0
    text_bytes = 0
    first_cwd = None
    last_ts = None
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            size = len(line)
            if first_cwd is None and '"cwd"' in line:
                try:
                    first_cwd = json.loads(line).get("cwd")
                except Exception:
                    pass
            has_image = '"image"' in line
            if has_image:
                try:
                    obj = json.loads(line)
                except Exception:
                    text_bytes += size
                    continue
                line_images = 0
                stack = [obj]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        if node.get("type") == "image":
                            data = (node.get("source") or {}).get("data") or node.get("data") or ""
                            images += 1
                            image_bytes += len(data)
                            line_images += len(data)
                            continue
                        stack.extend(node.values())
                    elif isinstance(node, list):
                        stack.extend(node)
                text_bytes += max(0, size - line_images)
            else:
                text_bytes += size
            if '"timestamp"' in line:
                ts = line.find('"timestamp":"')
                if ts != -1:
                    last_ts = line[ts + 13:ts + 33]
    return {
        "path": str(path),
        "mtime": path.stat().st_mtime,
        "cwd": first_cwd,
        "images": images,
        "image_mb": round(image_bytes / 1e6, 2),
        "text_mb": round(text_bytes / 1e6, 2),
        "body_mb": round((image_bytes + text_bytes) / 1e6, 2),
        "last_ts": last_ts,
    }


def verdict(row):
    if row["images"] > IMAGE_LIMIT or row["body_mb"] >= FATAL_MB:
        return "FATAL"
    if row["body_mb"] >= OVER_MB:
        return "OVER"
    if row["body_mb"] >= WARN_MB or row["images"] > IMAGE_LIMIT * 0.6:
        return "WARN"
    return "OK"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="指定 session jsonl")
    ap.add_argument("--dir", action="append", default=[], help="額外/指定 session 目錄")
    ap.add_argument("--all", action="store_true", help="列出全部，不只最近 10 個")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", type=float, default=None, help="任一 session 超過此 MB 就 exit 1")
    args = ap.parse_args()

    if args.session:
        files = [Path(args.session)]
    else:
        dirs = [Path(d) for d in args.dir] or session_dirs()
        files = []
        for d in dirs:
            if d.is_dir():
                files.extend(sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True))
        if not files:
            print("找不到 session 檔；用 --dir 指定 pi-agent-home/sessions 目錄", file=sys.stderr)
            return 2
        if not args.all:
            files = files[:10]

    rows = [scan(p) for p in files if p.is_file()]
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    for r in rows:
        r["verdict"] = verdict(r)
        r["this_project"] = bool(r["cwd"]) and Path(r["cwd"]).resolve() == ROOT.resolve()

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"門檻：WARN {WARN_MB} MB／OVER {OVER_MB} MB／FATAL {FATAL_MB} MB；圖片上限 {IMAGE_LIMIT} 張")
        print(f"{'判定':6} {'圖':>4} {'圖MB':>7} {'文MB':>7} {'bodyMB':>7}  cwd／session")
        for r in rows:
            cwd = r["cwd"] or "-"
            mark = "*" if r["this_project"] else " "
            print(f"{r['verdict']:6} {r['images']:>4} {r['image_mb']:>7.2f} {r['text_mb']:>7.2f} {r['body_mb']:>7.2f} {mark}{cwd}")
            print(f"{'':6} {'':>4} {'':>7} {'':>7} {'':>7}  └ {Path(r['path']).name}")
        worst = rows[0] if rows else None
        if worst:
            print()
            if worst["verdict"] in ("OVER", "FATAL"):
                print(f"建議：立刻換新對話（或在該對話 /compact），並改用子代理讀圖（見 docs\\對話上下文預算.md）")
            elif worst["verdict"] == "WARN":
                print("建議：本批做完就 compact 或換對話；讀圖走子代理，別把圖留在主對話")
            else:
                print("狀態健康。維持每批（建議 20 條）換一次對話的節奏。")

    if args.gate is not None:
        over = [r for r in rows if r["body_mb"] >= args.gate]
        if over:
            print(f"GATE FAIL：{len(over)} 個 session 超過 {args.gate} MB", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
