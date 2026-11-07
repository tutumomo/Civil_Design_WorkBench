# ArtCraft 控制通道殼層（macOS／Linux 專用）

> **為什麼有這一層**：Windows 上 ArtCraft 會隨附 headless CLI（`cadcraft-cli.exe`、
> `gridcraft-cli.exe`、`wordcraft-cli.exe`）；**macOS 的 `/Applications/<App>.app` 內只有 GUI
> 可執行檔，沒有 `-cli`**。直接執行 `/Applications/CADCraft.app/Contents/MacOS/CADCraft convert a.dxf b.dwg`
> 會**開一個 GUI 視窗然後結束**，指令根本沒跑（踩坑紀錄 §AI.1）。

本目錄提供三支同名殼層，把 Windows CLI 的呼叫介面映射到 macOS 的 **JSON-lines 控制通道**：

| 殼層 | 對應 App | 提供的子指令 | 本專案誰在用 |
|---|---|---|---|
| `bin/cadcraft-cli` | CADCraft | `convert <src> <dst>`、`run <file> --cmd "<指令>"` | `tools/acad/acc.py`、`tools/a3_sheet/make_sheet.py` |
| `bin/gridcraft-cli` | GridCraft | `run --script <腳本.jsonl> [--quiet]`、`eval "<公式>" --in <xlsx>`、`check <xlsx>` | `tools/boq/boq_build.py` |
| `bin/wordcraft-cli` | WordCraft | `convert <src> <dst> [--update-fields]` | `tools/report/make_report.py` |

`tools/project_paths.py` 的 `artcraft_cli()` 解析順序為
**環境變數 → `ARTCRAFT_HOME` → `PATH` → 本目錄的殼層**，
所以 Windows 仍優先用真正的 `*-cli.exe`，macOS 才落到這裡（**不需要改任何呼叫端**）。

## 控制通道協定

App 以 `--control <port>` 啟動後，對 `127.0.0.1:<port>` 逐行送 JSON：

```
→ {"id":1,"method":"engine.execute","params":{"command":"file.new","params":{}}}
← {"id":1,"ok":true,"result":...}
```

三個 App 的認證方式**各不相同**（2026-11-07 實測）：

| App | 認證 | 憑證檔位置 |
|---|---|---|
| CADCraft | 每個請求 body 帶 `token` | `~/.cache/cadcraft-control-<port>.token` |
| GridCraft | 連線後先送一次 `{"id":0,"method":"auth","params":{"token":...}}` | `~/.cache/gridcraft/control-<port>.token` |
| WordCraft | 每個請求 body 帶 `key` | `~/Library/Application Support/WordCraft/control-key.local-<port>` |

`channel.py` 會自己找這些檔案；找不到就明確報錯，不會靜默失敗。

## 已知限制（macOS 與 Windows 的差異）

1. **PDF 文字不可搜尋**：CADCraft 出圖時中文以 TTF 替代字型轉成向量，PDF 取文字為空。
   視覺檢查正常，但**不能靠 PDF 抽文字做校對**，要校文字請讀 DXF。
2. **字型**：CADCraft 不讀 SHX（本專案 TOMO 是 `gbenor.shx`＋`CHINA1.SHX`），
   macOS 上由 CADCraft 內建替代字型處理，**外觀與 AutoCAD 不完全一致**；
   正式交件建議仍在 AutoCAD 機器上出圖。細節見 `docs/字型設定_CADCraft與AutoCAD.md`。
3. **App 是單例**：同一時間只能開一個實例；`channel.py` 會先找既有實例的 port 再接上去，
   避免第二個實例搶鎖失敗。
4. **每個殼層呼叫會啟動一次 App**（約 0.5～1 秒），結束時自動結束該實例，不留殘留行程。
5. **視窗會短暫出現**：macOS 的 ArtCraft 是 GUI App，控制通道運作時視窗會開啟（可見）。

## 自我檢查

```bash
python tools/project_paths.py            # CADCraft／GridCraft／WordCraft 應顯示殼層路徑
./tools/artcraft_cli/bin/cadcraft-cli convert <某圖.dxf> _temp/test.dwg   # 應產出 AC1032 (AutoCAD 2018)
```

## 相關文件

- `docs/環境需求與自動配置.md` §1／§8（macOS 環境配置）
- `docs/踩坑紀錄.md` §AI（macOS 環境與圖面缺陷）
