# One-shot launcher for VibePCB (Windows PowerShell).
# ASCII-only on purpose - see scripts/start-backend.ps1 for the reason.
$ErrorActionPreference = 'Stop'
Set-Location "$PSScriptRoot\.."

# ---- backend venv ----------------------------------------------------------
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "X No .venv found." -ForegroundColor Red
    Write-Host "  Do NOT create it with the system python: pcbnew requires KiCad's own"
    Write-Host "  Python so the MSVC toolchain matches. See README.md -> KiCad section:" -ForegroundColor Red
    Write-Host '      & "<KiCad>\bin\python.exe" -m venv .venv'
    Write-Host '      .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    Write-Host '      .\.venv\Scripts\python.exe scripts\setup_kicad_path.py'
    exit 1
}

# ---- backend process -------------------------------------------------------
$env:PYTHONUTF8       = '1'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:DEEPSEEK_API_KEY) {
    $userKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    if ($userKey) { $env:DEEPSEEK_API_KEY = $userKey }
}

$running = $false
try { Invoke-RestMethod -Uri 'http://127.0.0.1:8710/api/health' -TimeoutSec 2 | Out-Null; $running = $true } catch { }

if ($running) {
    Write-Host "Backend already running on 8710, reusing it." -ForegroundColor Green
} else {
    Write-Host "Starting backend on http://127.0.0.1:8710 ..." -ForegroundColor Cyan
    Start-Process -NoNewWindow -FilePath $py -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', '8710', '--app-dir', 'backend'
    )
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 700
        try { Invoke-RestMethod -Uri 'http://127.0.0.1:8710/api/health' -TimeoutSec 2 | Out-Null; $running = $true; break } catch { }
    }
    if (-not $running) {
        Write-Host "X Backend did not become ready in time." -ForegroundColor Red
        exit 1
    }
    Write-Host "Backend is up." -ForegroundColor Green
}

# ---- frontend --------------------------------------------------------------
Set-Location frontend
if (-not (Test-Path node_modules)) { npm ci }
npm run electron:dev
