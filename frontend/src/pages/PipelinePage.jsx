import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
const STAGES = ['parse', 'components', 'schematic', 'pcb', 'gerber', 'firmware'];
const LABELS = { parse: '需求解析', components: '元器件选型', schematic: '原理图/网表', pcb: 'PCB 布局布线', gerber: 'Gerber 导出', firmware: '固件生成' };

export default function PipelinePage({ project, onDone, onBack }) {
  const [detail, setDetail] = useState(project);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef(null);

  useEffect(() => () => clearInterval(timer.current), []);

  const run = async () => {
    setRunning(true); setErr('');
    try { await api.runPipeline(project.project_id); } catch (e) { setErr(String(e.message || e)); }
    // 1 秒轮询直至终态
    timer.current = setInterval(async () => {
      const d = await api.getProject(project.project_id);
      setDetail(d);
      if (d.overall === 'done' || d.overall === 'failed') {
        clearInterval(timer.current); setRunning(false);
        if (d.overall === 'done') onDone(d);
      }
    }, 1000);
  };

  const stages = detail.stages || {};
  return (
    <div>
      <h2>流水线 · {detail.name} <small style={{ fontSize: 12, color: '#888' }}>{detail.project_id}</small></h2>
      <p style={{ background: '#f6f6f6', padding: 8, borderRadius: 4 }}>{detail.prompt}</p>
      {STAGES.map(s => {
        const st = stages[s] || {};
        const color = st.status === 'done' ? '#0a0' : st.status === 'running' ? '#08c' : st.status === 'failed' ? '#c00' : '#999';
        return (
          <div key={s} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #eee' }}>
            <span style={{ width: 16, color }}>{st.status === 'done' ? '✔' : st.status === 'running' ? '⟳' : st.status === 'failed' ? '✘' : '·'}</span>
            <b style={{ width: 130 }}>{LABELS[s]}</b>
            <span style={{ color }}>{st.status || 'pending'}</span>
            {st.engine && <span style={{ color: '#666' }}>engine: {st.engine}</span>}
            {st.degraded && <span style={{ background: '#b45309', color: '#fff', borderRadius: 4, padding: '1px 6px', fontSize: 12 }}>degraded</span>}
            {st.error && <span style={{ color: '#c00', fontSize: 12 }}>{st.error}</span>}
          </div>
        );
      })}
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <div style={{ marginTop: 12 }}>
        <button onClick={onBack}>← 返回</button>{' '}
        <button disabled={running} onClick={run}>{running ? `运行中（${detail.overall}）…` : '▶ 一键生成'}</button>
      </div>
    </div>
  );
}
