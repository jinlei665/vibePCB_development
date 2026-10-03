// API 基址可配置：
// - 默认 ''（同源相对路径）：Web 在线部署（前后端同域/反向代理）模式
// - 构建时注入 VITE_API_BASE（如 'http://127.0.0.1:8710'）：Electron 桌面
//   壳或前后端分域部署时使用，例如：
//     npm run build -- --mode desktop    （.env.desktop 里配 VITE_API_BASE）
//     VITE_API_BASE=http://127.0.0.1:8710 npx vite build
// - 运行时注入：window.__VIBEPCB_API_BASE__（Electron preload 注入，或挂到
//   index.html 的 script 里）。
// 优先级（高→低）：运行时注入 > 构建期 VITE_API_BASE > 同源相对路径。
// 运行时最高，这样 Electron 桌面壳改 VIBEPCB_PORT 后无需重新构建前端。
const RUNTIME_BASE = (typeof window !== 'undefined' && window.__VIBEPCB_API_BASE__)
  ? String(window.__VIBEPCB_API_BASE__).trim()
  : '';
const BUILD_BASE = (import.meta.env.VITE_API_BASE ?? '').trim();
const BASE = RUNTIME_BASE || BUILD_BASE;
// API Token（后端启用 VIBEPCB_API_TOKEN 时需要）：localStorage 或运行时注入。
// 同源反代部署推荐在反代层注入 X-API-Token 头，浏览器无需配置。
const API_TOKEN = (typeof window !== 'undefined'
  && (localStorage.getItem('vibepcb_token') || window.__VIBEPCB_API_TOKEN__)) || '';
function authHeaders() {
  return API_TOKEN ? { 'X-API-Token': API_TOKEN } : {};
}
async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() }, ...opts,
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
  // 后台模式（质检 D1）：立即返回 202，阶段在工作线程推进，配合 getProject 轮询看进度
  runPipelineBackground: (id) => req(`/api/projects/${id}/pipeline?background=1`, { method: 'POST', body: JSON.stringify({ stages: ['all'] }) }),
  artifacts: (id, stage) => req(`/api/projects/${id}/artifacts/${stage}`),
  artifactText: (id, stage, path) => fetch(`${BASE}/api/projects/${id}/artifacts/${stage}?path=${encodeURIComponent(path)}`, { headers: authHeaders() }).then(r => r.text()),
  downloadUrl: (id, stage, path) => `${BASE}/api/projects/${id}/artifacts/${stage}?path=${encodeURIComponent(path)}&download=1`,
};
