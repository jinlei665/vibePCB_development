// API 基址可配置：
// - 默认 ''（同源相对路径）：Web 在线部署（前后端同域/反向代理）模式
// - 构建时注入 VITE_API_BASE（如 'http://127.0.0.1:8710'）：Electron 桌面
//   壳或前后端分域部署时使用，例如：
//     npm run build -- --mode desktop    （.env.desktop 里配 VITE_API_BASE）
//     VITE_API_BASE=http://127.0.0.1:8710 npx vite build
// - 运行时兜底：window.__VIBEPCB_API_BASE__（挂到 index.html 的 script 里），
//   优先级低于构建参数，适合同一份静态产物指向不同后端
const BASE = (import.meta.env.VITE_API_BASE ?? '').trim()
  || (typeof window !== 'undefined' && window.__VIBEPCB_API_BASE__ ? String(window.__VIBEPCB_API_BASE__).trim() : '');
async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' }, ...opts,
  });
  if (!r.ok) {
    let detail = {};
    try { detail = await r.json(); } catch (e) {}
    throw new Error(detail?.error?.message || `HTTP ${r.status}`);
  }
  return r.json();
}
export const api = {
  health: () => req('/api/health'),
  capabilities: () => req('/api/capabilities'),
  createProject: (name, prompt) => req('/api/projects', { method: 'POST', body: JSON.stringify({ name, prompt }) }),
  getProject: (id) => req(`/api/projects/${id}`),
  runPipeline: (id) => req(`/api/projects/${id}/pipeline`, { method: 'POST', body: JSON.stringify({ stages: ['all'] }) }),
  artifacts: (id, stage) => req(`/api/projects/${id}/artifacts/${stage}`),
  artifactText: (id, stage, path) => fetch(`${BASE}/api/projects/${id}/artifacts/${stage}?path=${encodeURIComponent(path)}`).then(r => r.text()),
  downloadUrl: (id, stage, path) => `${BASE}/api/projects/${id}/artifacts/${stage}?path=${encodeURIComponent(path)}&download=1`,
};
