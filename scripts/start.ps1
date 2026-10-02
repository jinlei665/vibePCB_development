# VibePCB 一键启动（Windows PowerShell）
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."
if (-not (Test-Path .venv)) { python -m venv .venv; .venv\Scripts\pip install -r requirements.txt }
Start-Process -NoNewWindow .venv\Scripts\python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8710","--app-dir","backend"
Set-Location frontend
if (-not (Test-Path node_modules)) { npm install }
npm run electron:dev
