// Electron 主进程：spawn 后端子进程 → 轮询 /api/health 就绪 → 打开窗口
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let backendProc = null;
const DEV = !!process.env.VITE_DEV;
const BACKEND = path.join(__dirname, '..', 'backend');

function startBackend() {
  const isWin = process.platform === 'win32';
  backendProc = spawn(isWin ? 'python' : 'python3',
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8710'],
    { cwd: BACKEND, env: { ...process.env } });
  backendProc.stdout.on('data', d => console.log(`[backend] ${d}`));
  backendProc.stderr.on('data', d => console.error(`[backend] ${d}`));
}

function waitReady(cb, tries = 60) {
  if (tries <= 0) { console.error('backend not ready'); return; }
  http.get('http://127.0.0.1:8710/api/health', res => { if (res.statusCode === 200) cb(); else setTimeout(() => waitReady(cb, tries - 1), 1000); })
    .on('error', () => setTimeout(() => waitReady(cb, tries - 1), 1000));
}

function createWindow() {
  const win = new BrowserWindow({ width: 1200, height: 800 });
  if (DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
}

app.whenReady().then(() => {
  startBackend();
  waitReady(createWindow);
});
app.on('window-all-closed', () => { if (backendProc) backendProc.kill(); app.quit(); });
