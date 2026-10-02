#!/usr/bin/env bash
# VibePCB 一键启动（开发模式）
set -e
cd "$(dirname "$0")/.."
# 后端
if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; fi
(.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8710 --app-dir backend &) 
# 前端
cd frontend
[ -d node_modules ] || npm install
npm run electron:dev
