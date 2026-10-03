import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import PreviewPanel from '../components/PreviewPanel.jsx';
import BoardEditor from '../components/BoardEditor.jsx';
import LibraryPanel from '../components/LibraryPanel.jsx';

export default function ArtifactsPage({ project, onBack }) {
  const [stage, setStage] = useState('schematic');
  const [arts, setArts] = useState([]);
  const [text, setText] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
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
      {/* 预览随 tab 切换联动：看 pcb 产物时显示 PCB，看 schematic 时显示原理图 */}
      <PreviewPanel project={project} refreshKey={stage} height={460} />

      <div style={{ marginTop: 12 }}>
        <button onClick={() => setShowEditor((v) => !v)}>
          {showEditor ? '收起 PCB 编辑器' : '✎ 打开 PCB 编辑器（手动调整）'}
        </button>
        <button style={{ marginLeft: 8 }} onClick={() => setShowLibrary((v) => !v)}>
          {showLibrary ? '收起器件库' : '⚙ 器件 / 封装库'}
        </button>
        <button style={{ marginLeft: 8 }} onClick={onBack}>← 返回流水线</button>
      </div>
      {showEditor && <BoardEditor project={project} />}
      {showLibrary && <LibraryPanel project={project} />}
    </div>
  );
}
