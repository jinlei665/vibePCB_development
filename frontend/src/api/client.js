const BASE = 'http://127.0.0.1:8710';
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
