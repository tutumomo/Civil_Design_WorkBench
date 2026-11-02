"""把 payload（新條目）安全併入既有 verified 分片。

用法：
    python tools/regs/merge_shard.py <payload.json> <shard.json>

規則（2026-11-01 事故後新增）：
1. **只增不覆寫**：目標分片已存在時一律讀入後 extend，絕不以新檔取代
   （曾因直接 write 目標分片，一次刪掉 5 條既有條目）。
2. 併入前檢查 id 重複；重複一律拒併並列出，避免同 id 兩份定義。
3. 併入後自動把目標分片備份到 `_temp/regs_pages/_backup_shards/<shard>.<ts>`，
   讓覆寫類事故可回溯。
4. 併入後立即寫回並印出「formulas / tables 前後數量」。
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "_temp" / "regs_pages" / "_backup_shards"


def load(path: Path) -> dict:
    if not path.exists():
        return {"formulas": [], "tables": []}
    d = json.loads(path.read_text(encoding="utf-8"))
    d.setdefault("formulas", [])
    d.setdefault("tables", [])
    return d


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    payload = Path(argv[1])
    shard = Path(argv[2])
    if not payload.exists():
        print(f"payload 不存在：{payload}")
        return 1

    new = json.loads(payload.read_text(encoding="utf-8"))
    if isinstance(new, list):
        new = {"formulas": [e for e in new if "rows" not in e],
               "tables": [e for e in new if "rows" in e]}
    new.setdefault("formulas", [])
    new.setdefault("tables", [])

    old = load(shard)
    have = {e["id"] for e in old["formulas"]} | {e["id"] for e in old["tables"]}
    dup = [e["id"] for e in new["formulas"] + new["tables"] if e["id"] in have]
    if dup:
        print("拒絕併入：id 已存在於目標分片 → " + ", ".join(sorted(set(dup))))
        print("（同一條文若要更新，請改既有條目，不要另立 id）")
        return 1

    if shard.exists():
        BACKUP.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(shard, BACKUP / f"{shard.name}.{stamp}")

    before = (len(old["formulas"]), len(old["tables"]))
    old["formulas"].extend(new["formulas"])
    old["tables"].extend(new["tables"])
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text(json.dumps(old, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"併入 {shard.name}：formulas {before[0]} → {len(old['formulas'])}、"
          f"tables {before[1]} → {len(old['tables'])}")
    if shard.exists():
        print(f"舊檔已備份至 _temp/regs_pages/_backup_shards/{shard.name}.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
