- **工具鏈整合**：既有 `sc_build.py`（一鍵交付：腳本→建構→匯出→量測→驗證→截圖→紀錄）
  為主工具；`sc.py` 為 Python API 封裝（供程式化呼叫）。整合時補上：
  ① `parameters.export` **必須併入建模腳本**（`exec` 開的是空白 session → 匯出空表）；
  ② 產品渲染走 CLI `render` 子命令並自動帶 `--overwrite`（檔案已存在時會失敗）；
  ③ `--expect-volume 0` 會 ZeroDivisionError → 已加 `> 0` 判斷。
- **回歸驗證**（`tools\solidcraft\_selftest\regression.py`，全數通過）：
  ① U 型溝（B=400）體積與外框皆通過；② RC 擋土牆通過；③ 沉頭孔平板通過；
  ④ **重開 `.solidcraft` 設計檔改參數重建**：H 由 3000 → 3500 mm，外框高即變 3500 mm，
  體積 2,228,528,158 mm³、面仍 11 → **參數化特徵樹完整保留**。
- **`solid.cylinder` 的 `base` 是「底面中心」不是「中心」**：`base` 落在牆身中線 + `axis:[0,1,0]`
  只會貫穿半厚（一側），排水孔做全貫穿要 `base` 給牆外（如 `-T/2`）、`height` 給 `T*3`。
- **理論體積公式要檢查有無重疊**：擋土牆趾板在牆身**下方**（Z −BT~0），兩者不重疊 →
  體積 = 牆身 + 趾板 − 排水孔；誤扣重疊會差 11%。
- **`run --in <design>` 的 `--json-out` 產出的是「量測物件本體」**（`bodies` 在頂層），
  不是陣列 → 解析時要先判斷 dict/list。
