"""一次性遷移：把舊 skip 狀態 no-content / deferred 拆成四類（2026-11-02）。

  covered       已由 verified 條目涵蓋（理由指向他條或重複單元）
  qualitative   確實無算式／數值表（定義、程序、目錄、計價…）
  out_of_scope  判斷非本工作區；原文有表／式但「未轉換、未驗證」
  unrecognized  有表／式但排版破碎或表身未擷取，辨識／轉錄失敗＝真缺口
                （理由含「非本工作區」者另標 relevance=out，轉錄時排在後面）

可重跑（已是新狀態者不動）。用法：python tools/regs/migrate_skip_status.py [--dry]
"""
import json, re, sys, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import regq  # noqa: E402

SKIPS = HERE / "verified" / "_skips.json"
COVERED = re.compile(r"已入庫|已併入|已與.{0,12}合併|已涵蓋|已由.{0,20}(涵蓋|入庫)|主式已|同型內容已|重複單元|不另立|已於.{0,24}入庫|已建立 skip|建立 skip 紀錄")
SCOPE = re.compile(r"非本工作區|本工作區未涉及|本工作區不含|本工作區.{0,6}未|非引用項|非範疇|不在本工作區|非設計引用|未涉及")
QUAL = re.compile(r"定性|名詞|定義|程序|沿革|目錄|封面|符號表|用詞|計價|文獻|範例|原則|說明|解說|流程圖|屬.{0,6}規定|品管|引用規定")
STRUCT = re.compile(r"[┌├│]|^\s*表\s*[A-Z0-9]|\(\s*[0-9A-Z]+[.\-][0-9A-Z.\-]+\s*\)\s*$", re.M)


def classify(item, text):
    st, reason = item.get("status"), item.get("reason") or ""
    if st in ("covered", "qualitative", "out_of_scope", "unrecognized"):
        return st, item.get("relevance")
    if st == "deferred":
        return "unrecognized", ("out" if SCOPE.search(reason) else "in")
    if COVERED.search(reason):
        return "covered", None
    if SCOPE.search(reason):
        return "out_of_scope", None
    if QUAL.search(reason):
        # 理由說是定性，但原文有框線表格 → 不能說「無表」，歸 out_of_scope（未轉換）
        return ("out_of_scope" if re.search(r"[┌├]", text) else "qualitative"), None
    return ("out_of_scope" if STRUCT.search(text) else "qualitative"), None


def main():
    dry = "--dry" in sys.argv
    con = regq.connect()
    d = json.loads(SKIPS.read_text(encoding="utf-8"))
    cnt = collections.Counter()
    for it in d["items"]:
        rows = con.execute("SELECT text FROM unit WHERE src=? AND clause=?", (it["src"], str(it["clause"]))).fetchall()
        text = "\n".join(r["text"] for r in rows)
        new, rel = classify(it, text)
        it["legacy_status"] = it.get("legacy_status") or (it["status"] if it["status"] in ("no-content", "deferred") else None)
        if it["legacy_status"] is None:
            it.pop("legacy_status")
        it["status"] = new
        if rel:
            it["relevance"] = rel
        cnt[new] += 1
    print(dict(cnt), "共", sum(cnt.values()))
    if not dry:
        SKIPS.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("written")


if __name__ == "__main__":
    main()
