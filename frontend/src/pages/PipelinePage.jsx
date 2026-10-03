import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
const STAGES = ['parse', 'components', 'schematic', 'pcb', 'gerber', 'firmware'];
const LABELS = { parse: '需求解析', components: '元器件选型', schematic: '原理图/网表', pcb: 'PCB 布局布线', gerber: 'Gerber 导出', firmware: '固件生成' };
const POLL_MS = 1000;
const MAX_POLLS = 900; // 15 分钟上限，防止后台线程异常时无限轮询

export default function PipelinePage({ project, onDone, onBack }) {
  const [detail, setDetail] = useState(project);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef(null);
  const polls = useRef(0);

  useEffect(() => () => clearInterval(timer.current), []);

  const stopPolling = () => { clearInterval(timer.current); timer.current = null; };

  const startPolling = () => {
    stopPolling();
    polls.current = 0;
    timer.current = setInterval(async () => {
      polls.current += 1;
      let d;
      try {
        d = await api.getProject(project.project_id);
      } catch (e) {
        // 单次轮询失败不立即终止（后端可能正在重启）；累计超时后再放弃
        if (polls.current >= MAX_POLLS) { stopPolling(); setRunning(false); setErr(String(e.message || e)); }
        return;
      }
      setDetail(d);
      if (d.overall === 'done' || d.overall === 'failed') {
        stopPolling();
        setRunning(false);
        if (d.overall === 'done') onDone(d);
      } else if (polls.current >= MAX_POLLS) {
        stopPolling();
        setRunning(false);
        setErr(`超过 ${Math.round(MAX_POLLS * POLL_MS / 60000)} 分钟仍未结束，已停止轮询`);
      }
    }, POLL_MS);
  };

  const run = async () => {
    setRunning(true); setErr('');
    // 关键（质检 D1）：先起轮询，再触发后台流水线。原实现是 await 同步的
    // 长请求、跑完才开始轮询，导致进度条全程不动、结束时一次性全变 done。
    startPolling();
    try {
      await api.runPipelineBackground(project.project_id);
    } catch (e) {
      // 启动失败（例如 409 PROJECT_BUSY）：保留轮询以观察正在进行的进度
      setErr(String(e.message || e));
    }
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
        <button disabled={running} onClick={run}>{running ? `运行中（${detail.overall}）…` : '▶ 一键生成'}</button>{' '}
        {!running && detail.overall !== 'done' && detail.overall !== 'created' && (
          <button onClick={() => onDone(detail)}>查看已有产物 →</button>
        )}
      </div>
    </div>
  );
}
