// Electron 主进程：确保后端可用（复用已在运行的实例，否则拉起）→ 轮询 /api/health → 打开窗口
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const DEV = !!process.env.VITE_DEV;
const PORT = Number(process.env.VIBEPCB_PORT || 8710);
const HOST = '127.0.0.1';
const BASE_URL = `http://${HOST}:${PORT}`;

let backendProc = null;

// 后端目录：开发时取仓库 ../backend；打包后取 resources/backend
function backendDir() {
  if (process.env.VIBEPCB_BACKEND_DIR) return process.env.VIBEPCB_BACKEND_DIR;
  const packaged = path.join(process.resourcesPath || '', 'backend');
  if (!DEV && fs.existsSync(path.join(packaged, 'app', 'main.py'))) return packaged;
  return path.join(__dirname, '..', '..', 'backend');
}

// 解释器优先级：VIBEPCB_PYTHON > 仓库 .venv > 系统 python。
// 修复：此前固定用系统 python，而本机 python 指向 Anaconda（没有 fastapi/skidl），
// 导致 Electron 拉起的后端必然启动失败，只能靠 start.ps1 另起的那个后端兜住。
function pythonPath() {
  if (process.env.VIBEPCB_PYTHON) return process.env.VIBEPCB_PYTHON;
  const root = path.join(__dirname, '..', '..');
  const win = process.platform === 'win32';
  const venvPython = win
    ? path.join(root, '.venv', 'Scripts', 'python.exe')
    : path.join(root, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  return win ? 'python' : 'python3';
}

function healthOnce(timeoutMs = 1500) {
  return new Promise(resolve => {
    const req = http.get(`${BASE_URL}/api/health`, res => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.setTimeout(timeoutMs, () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });
}

async function ensureBackend() {
  if (await healthOnce()) {
    console.log(`[backend] 复用已在运行的后端 ${BASE_URL}`);
    return;
  }
  const cwd = backendDir();
  const py = pythonPath();
  console.log(`[backend] 启动 ${py} (cwd=${cwd}, port=${PORT})`);
  try {
    backendProc = spawn(
      py,
      ['-m', 'uvicorn', 'app.main:app', '--host', HOST, '--port', String(PORT)],
      { cwd, env: { ...process.env }, stdio: ['ignore', 'pipe', 'pipe'] }
    );
  } catch (err) {
    console.error(`[backend] spawn 失败: ${err.message}`);
    return;
  }
  backendProc.stdout.on('data', d => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on('data', d => process.stderr.write(`[backend] ${d}`));
  backendProc.on('error', err => console.error(`[backend] spawn 失败: ${err.message}`));
  backendProc.on('exit', code => {
    console.error(`[backend] 退出 code=${code}`);
    backendProc = null;
  });
}

function waitReady(cb, tries = 60) {
  if (tries <= 0) {
    console.error('[backend] 60s 内未就绪，仍然打开窗口（页面会显示接口错误）');
    cb();
    return;
  }
  healthOnce().then(ok => (ok ? cb() : setTimeout(() => waitReady(cb, tries - 1), 1000)));
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
    },
  });
  if (DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
}

app.whenReady().then(async () => {
  await ensureBackend();
  waitReady(createWindow);
});

app.on('window-all-closed', () => {
  if (backendProc) {
    backendProc.kill();
    backendProc = null;
  }
  app.quit();
});
