import React, { useEffect, useState } from 'react';
import PromptPage from './pages/PromptPage.jsx';
import PipelinePage from './pages/PipelinePage.jsx';
import ArtifactsPage from './pages/ArtifactsPage.jsx';
import { api } from './api/client.js';

export default function App() {
  const [view, setView] = useState('prompt');
  const [project, setProject] = useState(null);
  const [caps, setCaps] = useState(null);
  useEffect(() => { api.capabilities().then(setCaps).catch(() => {}); }, []);
  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 960, margin: '0 auto', padding: 24 }}>
      <h1>VibePCB <small style={{ fontSize: 14, color: '#888' }}>自然语言 → 原理图 → PCB → 固件 → Gerber</small></h1>
      {caps && <p style={{ color: '#666' }}>引擎：{caps.pcb_engine_selected} | DeepSeek：{caps.deepseek_configured ? '已配置' : '未配置（降级模式）'}</p>}
      {view === 'prompt' && <PromptPage onCreated={(p) => { setProject(p); setView('pipeline'); }} />}
      {view === 'pipeline' && project && <PipelinePage project={project} onDone={(p) => { setProject(p); setView('artifacts'); }} onBack={() => setView('prompt')} />}
      {view === 'artifacts' && project && <ArtifactsPage project={project} onBack={() => setView('pipeline')} />}
    </div>
  );
}
