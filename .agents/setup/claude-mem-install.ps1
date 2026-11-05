<#
    claude-mem 安裝腳本（Windows）

    做的事：
      1. 前置檢查：Node.js ≥ 20、npm、Git for Windows（Git Bash）、Claude Code 版本
      2. 執行官方安裝器：npx claude-mem install --ide claude-code --provider claude
         （provider=claude → 用你自己的 Anthropic 方案，不需要 cmem.ai 帳號、不外傳到第三方）
      3. 關閉匿名遙測
      4. 掛 marketplace 與 plugin：claude plugin marketplace add thedotmack/claude-mem
                                 claude plugin install claude-mem@<marketplace 名稱>
      5. 驗證：npx claude-mem doctor、claude plugin list

    用法：
      powershell -ExecutionPolicy Bypass -File "D:\Civil_Design_WorkBench\.agents\setup\claude-mem-install.ps1"

    參數：
      -Provider claude|host|openrouter|gemini|codex   記憶摘要用的模型來源（預設 claude）
      -SkipPlugin                                    略過第 4 步（只做 npx 安裝）
      -KeepTelemetry                                 保留匿名遙測（預設是關閉）
      -NoPause                                       不在最後停頓

    注意：
      - 這支腳本會在「你的電腦」上執行，不是沙箱。
      - 第 2 步之後必須**重開 Claude Code**（或 `/reload-plugins`），plugin 才會生效。
#>
[CmdletBinding()]
param(
    [ValidateSet('claude', 'host', 'openrouter', 'gemini', 'codex')]
    [string]$Provider = 'claude',
    [switch]$SkipPlugin,
    [switch]$KeepTelemetry,
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
$MarketplaceRepo = 'thedotmack/claude-mem'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "== $Text" -ForegroundColor Cyan
}
function Write-Ok([string]$Text) { Write-Host "   [OK]   $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "   [注意] $Text" -ForegroundColor Yellow }
function Write-Err([string]$Text) { Write-Host "   [問題] $Text" -ForegroundColor Red }
function Write-Info([string]$Text) { Write-Host "   $Text" -ForegroundColor DarkGray }

function Get-CommandPath([string]$Name) {
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Get-NodeMajor {
    $node = Get-CommandPath 'node'
    if (-not $node) { return $null }
    try {
        $v = (& node -v 2>$null) -replace '^v', ''
        return [int]($v -split '\.')[0]
    } catch { return $null }
}

function Get-ClaudeVersion {
    $claude = Get-CommandPath 'claude'
    if (-not $claude) { return $null }
    try {
        $v = (& claude --version 2>$null | Select-Object -First 1)
        if ($v -match '(\d+)\.(\d+)\.(\d+)') {
            return [pscustomobject]@{ Text = $Matches[0]; Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Patch = [int]$Matches[3] }
        }
    } catch { }
    return $null
}

function Find-GitBash {
    $cands = @(
        (Join-Path $env:ProgramFiles 'Git\bin\bash.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\bin\bash.exe')
    )
    foreach ($p in $cands) { if ($p -and (Test-Path $p)) { return $p } }
    $onPath = Get-CommandPath 'bash'
    if ($onPath -and ($onPath -notlike '*\System32\bash.exe')) { return $onPath }
    return $null
}

Write-Host ''
Write-Host ('=' * 66) -ForegroundColor DarkCyan
Write-Host ' claude-mem 安裝（持久記憶）' -ForegroundColor Cyan
Write-Host " provider = $Provider ；來源 = $MarketplaceRepo" -ForegroundColor DarkGray
Write-Host ('=' * 66) -ForegroundColor DarkCyan

# ---------------------------------------------------------------- 1. 前置檢查
Write-Step '1/5 前置檢查'

$major = Get-NodeMajor
if ($null -eq $major) {
    Write-Err '找不到 node。請先安裝 Node.js 20 以上（nodejs.org），重開終端機再跑一次。'
    exit 1
}
if ($major -lt 20) {
    Write-Err "Node.js 版本過舊（v$major）。claude-mem 需要 Node 20 以上，請先升級。"
    exit 1
}
Write-Ok "Node.js v$major"
Write-Ok "npm $((& npm -v 2>$null))"

$cv = Get-ClaudeVersion
if ($null -eq $cv) {
    Write-Warn '找不到 claude CLI（或尚未登入）。plugin 仍可安裝，但要在 Claude Code 內驗證。'
} elseif ($cv.Major -lt 2 -or ($cv.Major -eq 2 -and ($cv.Minor -lt 1 -or ($cv.Minor -eq 1 -and $cv.Patch -lt 139)))) {
    Write-Warn "Claude Code $($cv.Text) 過舊。exec 型 hook 需要 2.1.139 以上，舊版會安靜地擷取不到資料；請執行 claude update。"
} else {
    Write-Ok "Claude Code $($cv.Text)"
}

$bash = Find-GitBash
if ($bash) {
    Write-Ok "Git Bash：$bash"
} else {
    Write-Warn '找不到 Git for Windows（Git Bash）。claude-mem 的 Setup hook 用 shell:bash，Windows 上缺它會報錯。'
    Write-Info '請安裝：https://git-scm.com/download/win'
}

$launcherDir = Join-Path $env:LOCALAPPDATA 'claude-mem\bin'
Write-Info "hook launcher 預設位置：$launcherDir"

# ---------------------------------------------------------------- 2. 官方安裝器
Write-Step '2/5 執行官方安裝器（npx claude-mem install）'
Write-Info '首次執行會下載套件並自動安裝 Bun / uv，可能要數分鐘。'

$installArgs = @('-y', 'claude-mem', 'install', '--ide', 'claude-code', '--provider', $Provider)
& npx @installArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "npx claude-mem install 回傳 $LASTEXITCODE"
    Write-Info '若是互動式選單卡住，請改用指令模式（同一支腳本重跑）：'
    Write-Info '  powershell -ExecutionPolicy Bypass -File "$PSCommandPath" -Provider claude'
    exit 1
}
Write-Ok '安裝器完成'

# 讓本次 session 也能用到 launcher（安裝器已寫入使用者 PATH，但目前視窗還沒繼承）
if (Test-Path $launcherDir) {
    $env:Path = "$launcherDir;$env:Path"
    Write-Ok "本視窗 PATH 已補上 $launcherDir"
}

# ---------------------------------------------------------------- 3. 遙測
Write-Step '3/5 匿名遙測'
if ($KeepTelemetry) {
    Write-Info '依你的指示保留匿名遙測。'
} else {
    & npx -y claude-mem telemetry disable 2>&1 | Out-Null
    Write-Ok '匿名遙測已關閉（可隨時用 npx claude-mem telemetry enable 開啟）'
}

# ---------------------------------------------------------------- 4. plugin 掛載
Write-Step '4/5 掛 marketplace 與 plugin'
if ($SkipPlugin) {
    Write-Info '已指定 -SkipPlugin，略過。'
} else {
    $claudePath = Get-CommandPath 'claude'
    if (-not $claudePath) {
        Write-Warn '找不到 claude CLI，無法自動掛 marketplace。請稍後在 Claude Code 內執行：'
        Write-Info '  /plugin marketplace add thedotmack/claude-mem'
        Write-Info '  /plugin install claude-mem@thedotmack'
    } else {
        $already = (& claude plugin marketplace list 2>&1 | Out-String)
        if ($already -match 'thedotmack') {
            Write-Ok 'marketplace thedotmack 已存在，略過新增'
        } else {
            & claude plugin marketplace add $MarketplaceRepo
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "已新增 marketplace：$MarketplaceRepo"
            } else {
                Write-Warn "marketplace add 回傳 $LASTEXITCODE；改用 npx 安裝器註冊的版本"
            }
        }

        # 從 marketplace list 取得實際名稱（可能是 thedotmack 或 thedotmack-claude-mem）
        $mktName = 'thedotmack'
        $list = (& claude plugin marketplace list 2>&1 | Out-String)
        if ($list -match '(thedotmack[\w-]*)') { $mktName = $Matches[1] }

        & claude plugin install "claude-mem@$mktName"
        if ($LASTEXITCODE -ne 0 -and $mktName -ne 'thedotmack') {
            Write-Info "再試一次 thedotmack 這個名稱"
            & claude plugin install 'claude-mem@thedotmack'
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "已安裝 plugin：claude-mem@$mktName"
        } else {
            Write-Warn 'plugin 安裝未回傳 0；請在 Claude Code 內以 /plugin 面板確認'
        }
    }
}

# ---------------------------------------------------------------- 5. 驗證
Write-Step '5/5 驗證'
& npx -y claude-mem doctor 2>&1 | ForEach-Object { Write-Info $_ }
if (Get-CommandPath 'claude') {
    Write-Info '--- claude plugin list ---'
    & claude plugin list 2>&1 | ForEach-Object { Write-Info $_ }
}

Write-Host ''
Write-Host ('=' * 66) -ForegroundColor DarkCyan
Write-Host ' 完成。接下來：' -ForegroundColor Cyan
Write-Host ('=' * 66) -ForegroundColor DarkCyan
Write-Host '  1) 完全重開 Claude Code（或在 session 內輸入 /reload-plugins）'
Write-Host '  2) 新開一個 session，確認記憶被注入'
Write-Host '  3) 驗收指令：'
Write-Host '       npx claude-mem status'
Write-Host '       npx claude-mem search "某個關鍵字"'
Write-Host '       npx claude-mem doctor'
Write-Host '  4) 網頁檢視：http://localhost:37777'
Write-Host ''
Write-Host '  資料位置：%APPDATA%\claude-mem（SQLite）；設定：%USERPROFILE%\.claude-mem\settings.json'
Write-Host '  記憶產生模式（可選，預設英文）：設定 CLAUDE_MEM_MODE=code--zh 會改成簡體中文。'
Write-Host '  本機資料庫在本機；provider=claude 代表摘要用你自己的 Anthropic 方案，不需要 cmem.ai 帳號。'
Write-Host '  備註：Claude 桌面版另有 claude-mem-cowork plugin，會把工具使用串流到 cmem.ai 雲端；'
Write-Host '        若你的案件資料涉密，請不要安裝那個。'

if (-not $NoPause) {
    Write-Host ''
    Read-Host '按 Enter 結束'
}
