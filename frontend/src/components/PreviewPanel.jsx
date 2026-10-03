import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';

// 实时预览面板：显示由后端 kicad-cli 渲染出的原理图 / PCB SVG。
// refreshKey 变化时自动重新拉图 —— PipelinePage 把各阶段状态拼成 key 传进来，
// 于是每跑完一个阶段画面就跟着更新，实现「生成过程中实时看见」。
const KINDS = [
  { key: 'schematic', label: '原理图' },
  { key: 'pcb', label: 'PCB 布局布线' },
];

export default function PreviewPanel({ project, refreshKey = 0, height = 520, onOpenKiCad }) {
  const [kind, setKind] = useState('schematic');
  const [url, setUrl] = useState('');
  const [bust, setBust] = useState(() => Date.now());
  const [err, setErr] = useState('');
  const [pending, setPending] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => { setBust(Date.now()); }, [refreshKey, kind]);

  useEffect(() => {
    if (!project) return undefined;
    let cancelled = false;
    setLoading(true); setErr(''); setPending('');

    api.renderBlob(project.project_id, kind, bust)
      .then((b) => {
        if (cancelled) return;
        setUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(b); });
      })
      .catch((e) => {
        if (cancelled) return;
        setUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return ''; });
        if (e.notReady) setPending(e.message); else setErr(String(e.message || e));
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [project, kind, bust]);

  const open = async () => {
    setMsg('');
    if (onOpenKiCad) { onOpenKiCad(kind); }
    try {
      const r = await api.openInKiCad(project.project_id, kind);
      setMsg(`已用 KiCad 打开 ${r.file}`);
    } catch (e) {
      setMsg(`打开失败：${e.message || e}`);
    }
  };

  return (
    <div style={{ border: '1px solid #ddd', borderRadius: 6, marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: 8, borderBottom: '1px solid #eee', flexWrap: 'wrap' }}>
        {KINDS.map(k => (
          <button key={k.key} onClick={() => setKind(k.key)}
            style={{ fontWeight: kind === k.key ? 'bold' : 'normal' }}>{k.label}</button>
        ))}
        <button onClick={() => setBust(Date.now())} disabled={loading}>
          {loading ? '渲染中…' : '⟳ 刷新'}
        </button>
        <span style={{ flex: 1 }} />
        <button onClick={open} title="把当前产物交给 KiCad 做重度编辑（需本机装有 KiCad）">
          在 KiCad 中打开（精修）
        </button>
      </div>

      {err && <p style={{ color: '#c00', padding: 8, margin: 0, fontSize: 13 }}>{err}</p>}
      {pending && <p style={{ color: '#888', padding: 8, margin: 0, fontSize: 13 }}>{pending}（该阶段跑完会自动出现）</p>}
      {msg && <p style={{ color: '#0a0', padding: 8, margin: 0, fontSize: 12 }}>{msg}</p>}

      <div style={{ height, overflow: 'auto', background: '#fafafa', textAlign: 'center' }}>
        {url
          ? <img src={url} alt={`${kind} 预览`} style={{ maxWidth: '100%', display: 'block', margin: '0 auto' }} />
          : (!err && !pending && (
              <p style={{ color: '#999', paddingTop: 40 }}>{loading ? '正在渲染…' : '暂无预览'}</p>
          ))}
      </div>
    </div>
  );
}
