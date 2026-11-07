# Claude 入口

本工作區規範統一寫在 `AGENTS.md`，請先完整閱讀：

@AGENTS.md

- **When starting a session or switching machines**, run `python tools/git/sync_check.py` (or verify the SessionStart hook output) before editing code.
- **When generating a site basemap, tracing roads/buildings, or laying out an A3 sheet**, load `.agents/skills/civil-site-basemap/SKILL.md` (or read `docs\現況平面底圖作業流程.md`).
- **When troubleshooting or modifying `tools\`**, consult `docs\經驗索引_INDEX.md` first and open only the relevant section of `docs\踩坑紀錄.md` (do NOT read the full `docs\踩坑紀錄.md` up front).
