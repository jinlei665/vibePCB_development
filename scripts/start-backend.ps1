# Start the VibePCB backend with predictable, immediately-visible output.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 files using the ANSI
# code page unless a BOM is present, so non-ASCII bytes in a script can be
# mis-decoded and break parsing (this bit us once already).
#
# Sets PYTHONUTF8 / PYTHONUNBUFFERED / PYTHONIOENCODING so the Chinese log lines
# are neither mojibaked nor held back by buffering.
$ErrorActionPreference = 'Stop'
Set-Location "$PSScriptRoot\.."

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "X venv python not found: $py" -ForegroundColor Red
    Write-Host "  Create it first - see the KiCad section of README.md." -ForegroundColor Red
    exit 1
}

$env:PYTHONUTF8       = '1'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

# The key is read from the environment only; without it the pipeline still runs
# on the rule-based fallback.
if (-not $env:DEEPSEEK_API_KEY) {
    $userKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    if ($userKey) {
        $env:DEEPSEEK_API_KEY = $userKey
        Write-Host "DeepSeek   : loaded from user environment"
    } else {
        Write-Host "DeepSeek   : not configured -> parse/components/firmware use rule-based fallback" -ForegroundColor Yellow
    }
}

# Do not start a second instance on the same port.
$already = $false
try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8710/api/health' -TimeoutSec 2
    $already = $true
} catch { }
if ($already) {
    Write-Host "Backend already running: $($h.app) v$($h.version) on http://127.0.0.1:8710" -ForegroundColor Green
    exit 0
}

$vibepcbPort = if ($env:VIBEPCB_PORT) { $env:VIBEPCB_PORT } else { '8710' }
Write-Host "Starting backend on http://127.0.0.1:$vibepcbPort ..." -ForegroundColor Cyan
Write-Host "(Ctrl+C to stop)"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $vibepcbPort --app-dir backend
