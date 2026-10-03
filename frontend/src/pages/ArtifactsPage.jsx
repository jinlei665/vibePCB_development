import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';

export default function ArtifactsPage({ project, onBack }) {
  const [stage, setStage] = useState('schematic');
  const [arts, setArts] = useState([]);
  const [text, setText] = useState('');
  useEffect(() => { api.artifacts(project.project_id, stage).then(d => setArts(d.artifacts || [])).catch(() => setArts([])); }, [stage, project.project_id]);
  const view = async (path) => { setText('加载中…'); setText(await api.artifactText(project.project_id, stage, path)); };
  return (
    <div>
      <h2>产物 · {project.name}</h2>
      <div style={{ margin: '8px 0' }}>
        {['parse', 'components', 'schematic', 'pcb', 'firmware', 'gerber'].map(s => (
          <button key={s} onClick={() => { setStage(s); setText(''); }} style={{ marginRight: 8, fontWeight: s === stage ? 'bold' : 'normal' }}>{s}</button>
        ))}
      </div>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <tbody>
          {arts.map(a => (
            <tr key={a.path} style={{ borderBottom: '1px solid #eee' }}>
              <td style={{ padding: 6 }}>{a.path}</td>
              <td style={{ padding: 6, color: '#888' }}>{a.size} B</td>
              <td style={{ padding: 6 }}>
                <a href="#" onClick={e => { e.preventDefault(); view(a.path); }}>查看</a>{' '}
                <a href={api.downloadUrl(project.project_id, stage, a.path)}>下载</a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {text && <pre style={{ background: '#f6f6f6', padding: 12, marginTop: 12, maxHeight: 400, overflow: 'auto', fontSize: 12 }}>{text}</pre>}
      <button style={{ marginTop: 12 }} onClick={onBack}>← 返回流水线</button>
    </div>
  );
}
