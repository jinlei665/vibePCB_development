import React, { useState } from 'react';
import { api } from '../api/client.js';
export default function PromptPage({ onCreated }) {
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    if (!prompt.trim()) return;
    setBusy(true); setErr('');
    try { const p = await api.createProject(name, prompt); onCreated(p); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };
  return (
    <div>
      <h2>描述你要做的设备</h2>
      <input style={{ width: '60%', padding: 8, marginRight: 8 }} placeholder="项目名（可选）" value={name} onChange={e => setName(e.target.value)} />
      <textarea style={{ width: '100%', height: 120, padding: 8, marginTop: 8 }} placeholder="例如：做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT"
        value={prompt} onChange={e => setPrompt(e.target.value)} />
      {err && <p style={{ color: 'red' }}>{err}</p>}
      <button disabled={busy || !prompt.trim()} onClick={go} style={{ marginTop: 8, padding: '8px 24px' }}>
        {busy ? '创建中…' : '开始生成'}
      </button>
    </div>
  );
}
