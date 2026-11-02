"""Add one design topic to the lookup: validate every clause, write the topic, add an exam, verify.

usage:
  add_topic.py --name 農塘 --aliases 農塘,蓄水池 --scope "農地蓄水" \
               --core "swc_tech:55=設置原則,swc_tech:56=開挖式農塘" --prereq "swc_tech:18" \
               --note "農塘容量依集水面積與逕流量估算" --route "挖一個農塘" --dry-run

  --core/--prereq  "src:clause=note,src:clause"   (note optional)
  --tools          "tools\\design\\hydrology.py,tools\\..."   (optional)
  --note           may be repeated
  --route          a spoken sentence that must open this topic (optional, recommended)

The script refuses when a clause is missing, a name/alias is already used, or the self-test fails;
on failure it restores both files. --topics/--exams let you try it on copies first.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("CIVIL_AI_REGS_DB")
           or (Path(__file__).resolve().parents[2] / "data" / "法規" / "_regs_index.sqlite"))
PY = sys.executable


def refs(spec):
    out = []
    for item in filter(None, (x.strip() for x in (spec or "").split(","))):
        clause_note = item.split("=", 1)
        src, _, clause = clause_note[0].partition(":")
        if not src or not clause:
            raise SystemExit(f"條文寫法應為 src:clause=說明，收到「{item}」")
        out.append({"src": src.strip(), "clause": clause.strip(),
                    "note": clause_note[1].strip() if len(clause_note) > 1 else ""})
    return out


def run_selftest(topics, exams):
    env = dict(os.environ, REGS_TOPICS=str(topics), REGS_EXAMS=str(exams), PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY, "-E", "-P", "-X", "utf8", str(HERE / "regq_selftest.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--aliases", default="", help="逗號分隔；同義詞不可與其他主題重複")
    ap.add_argument("--scope", default="")
    ap.add_argument("--core", required=True, help="src:clause=說明,src:clause …")
    ap.add_argument("--prereq", default="")
    ap.add_argument("--tools", default="")
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--route", default="", help="一句口語，必須開啟此主題")
    ap.add_argument("--exam-refs", default="", help="考題必須出現的條文（預設取 core 前兩條）")
    ap.add_argument("--update", action="store_true", help="主題已存在時覆寫")
    ap.add_argument("--topics", default=str(HERE / "topics.json"))
    ap.add_argument("--exams", default=str(HERE / "exams.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    topics_path, exams_path = Path(a.topics), Path(a.exams)
    lib = json.loads(topics_path.read_text(encoding="utf-8-sig"))
    exams = json.loads(exams_path.read_text(encoding="utf-8"))
    by_name = {t["name"]: t for t in lib["topics"]}

    aliases = list(dict.fromkeys(x.strip() for x in a.aliases.replace("，", ",").split(",") if x.strip()))
    if a.name in aliases:
        aliases.remove(a.name)
        print(f"（同義詞與主題名相同，已略過：{a.name}）")
    core, prereq = refs(a.core), refs(a.prereq)
    if not core:
        raise SystemExit("至少要有一條核心條文")

    # 1. names must be free (unless --update) and unique across topics
    owner = {}
    for t in lib["topics"]:
        for w in [t["name"]] + t.get("aliases", []):
            owner[w] = t["name"]
    clash = [w for w in [a.name] + aliases if w in owner and owner[w] != a.name]
    if clash:
        raise SystemExit("這些名稱／同義詞已被別的主題使用：" + "、".join(f"{w}（{owner[w]}）" for w in clash))
    if a.name in by_name and not a.update:
        raise SystemExit(f"主題「{a.name}」已存在；要改內容請加 --update")

    # 2. every clause must exist; show what it resolved to
    import sqlite3
    con = sqlite3.connect(DB)
    bad = []
    for ref in core + prereq:
        row = con.execute("SELECT title, (SELECT name FROM src WHERE id = unit.src) FROM unit "
                          "WHERE src = ? AND clause = ? LIMIT 1", (ref["src"], ref["clause"])).fetchone()
        if not row:
            bad.append(f'{ref["src"]}:{ref["clause"]}')
        else:
            print(f'  ✓ {ref["src"]}:{ref["clause"]}  {row[0] or ""}'.rstrip())
    if bad:
        raise SystemExit("索引裡找不到：" + "、".join(bad) + "\n（新規範要先 fetch_regs.py → build_index.py）")

    topic = {"name": a.name, "aliases": aliases, "scope": a.scope, "core": core, "prereq": prereq,
             "tools": [x.strip() for x in a.tools.split(",") if x.strip()], "notes": a.note}
    exam_refs = refs(a.exam_refs) or core[:2]
    exam = [a.name, "topic", [[r["src"], r["clause"]] for r in exam_refs], "新增主題自動考題"]
    route = [a.route, a.name] if a.route else None

    print(f"\n主題：{a.name}｜同義詞 {len(aliases)}｜核心 {len(core)}｜前置 {len(prereq)}"
          + (f"｜口語「{a.route}」" if route else ""))
    if a.dry_run:
        print("（試跑，未寫入）")
        return 0

    old_topics, old_exams = topics_path.read_bytes(), exams_path.read_bytes()
    lib["topics"] = [t for t in lib["topics"] if t["name"] != a.name] + [topic]
    exams["exam"] = [e for e in exams["exam"] if e[0] != a.name] + [exam]
    if route:
        exams["route"] = [r for r in exams["route"] if r[0] != a.route] + [route]
    topics_path.write_text(json.dumps(lib, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    exams_path.write_text(json.dumps(exams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    code, lines = run_selftest(topics_path, exams_path)
    if code:
        topics_path.write_bytes(old_topics)
        exams_path.write_bytes(old_exams)
        print("\n".join(lines[-12:]))
        raise SystemExit("自我測試沒過，已還原兩個檔")
    print(lines[-1])
    print(f"已加入「{a.name}」。網頁與 AI 服務不用重開，下一次查詢就會看到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
