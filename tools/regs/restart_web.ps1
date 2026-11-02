# 重啟規範查詢台／工程設計工作台的本機服務（Windows PowerShell）
#
# 用途：改過 tools/regs/regs_server.py 或資料後，把 8765／8766 兩個 port 的服務停掉重開。
# 特色：只殺「命令列含 regs_server.py --web」的行程，不會誤殺其他 Python／MCP 行程。
# 路徑全部相對：以本檔所在位置（tools/regs/）往上兩層當專案根目錄。
#
# 用法： powershell -ExecutionPolicy Bypass -File tools\regs\restart_web.ps1
#        powershell -ExecutionPolicy Bypass -File tools\regs\restart_web.ps1 -Ports 8765

param(
    [int[]]$Ports = @(8765, 8766)
)

$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Server = Join-Path $Root 'tools\regs\regs_server.py'
$LogDir = Join-Path $Root '_temp'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$env:PYTHONIOENCODING = 'utf-8'

# 只用 PATH 上的 python；找不到就退而用 py -3
$PyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
$PyArgs = @()
if (-not $PyExe) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Error '找不到 Python。請安裝 Python 3.10+ 並加入 PATH，或先啟用虛擬環境。'
        exit 1
    }
    $PyExe = $py.Source
    $PyArgs = @('-3')
}

Write-Host "專案根目錄：$Root"
Write-Host "Python    ：$PyExe $($PyArgs -join ' ')"

# 1) 停掉舊的 web 服務（只針對 regs_server.py --web）
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'regs_server\.py.*--web' } |
    ForEach-Object {
        Write-Host "  停止 PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

# 2) 逐一啟動
$first = $true
foreach ($p in $Ports) {
    $extra = @()
    if (-not $first) { $extra = @('--port', "$p") }
    $first = $false
    $out = Join-Path $LogDir "web$p.log"
    $err = Join-Path $LogDir "web$p.err"
    Start-Process -FilePath $PyExe `
        -ArgumentList ($PyArgs + @('-E', '-P', '-X', 'utf8', $Server, '--web') + $extra) `
        -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err
    Write-Host "  啟動 port $p（日誌：$out）"
}
Start-Sleep -Seconds 4

# 3) 回報 listening 狀態
Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalPort, OwningProcess | Format-Table

Write-Host "查詢台： http://127.0.0.1:$($Ports[0])/"
Write-Host "工作台： http://127.0.0.1:$($Ports[0])/design"
