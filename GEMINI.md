# Gemini / Antigravity 工作區入口規範

本工作區所有規範已依 Harness² 架構統一收斂至 [`AGENTS.md`](AGENTS.md)，請以該檔為唯一常駐主規範：

@AGENTS.md

> 本專案不寫死磁碟絕對路徑（可搬移到任何磁碟／作業系統）。根目錄由 `tools/project_paths.py`
> 以本檔位置上推兩層推導；下列路徑一律相對於專案根目錄。

## 按需載入觸發提醒（On-Demand Triggers）
- **When generating a site basemap, tracing roads/buildings, or laying out an A3 sheet**, load the `civil-site-basemap` skill (or read `docs/現況平面底圖作業流程.md`) and run `python tools/a3_sheet/check_delivery.py` before delivery.
- **When troubleshooting tool errors or modifying `tools/` scripts**, check `docs/經驗索引_INDEX.md` first (do NOT read the full `docs/踩坑紀錄.md` unless a specific section matches).
