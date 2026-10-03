import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';

// 器件 / 封装库浏览与编辑（CAD 化增量 4）
//
// 左：可用器件目录（来自 footprint_map.json，也就是**选型阶段真正会用到的那份清单**）
// 右：内置封装快照库（*.pretty，真实 .kicad_mod）
// 下：换封装 / 改值 —— 直接写回 .kicad_pcb（走 /board/edits 的 set_footprint / set_value）
export default function LibraryPanel({ project }) {
  const [lib, setLib] = useState(null);
  const [board, setBoard] = useState(null);
  const [ref, setRef] = useState('');
  const [fpid, setFpid] = useState('');
  const [value, setValue] = useState('');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr('');
    try {
      setLib(await api.library());
      if (project) {
        try {
          const b = await api.board(project.project_id);
          setBoard(b);
          if (b.footprints.length && !ref) {
            setRef(b.footprints[0].ref);
            setFpid(b.footprints[0].fpid);
            setValue(b.footprints[0].value);
          }
        } catch (e) {
          setBoard(null);   // 还没生成到 PCB 阶段是正常的，不算错误
        }
      }
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, [project, ref]);

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const sel = board ? board.footprints.find((f) => f.ref === ref) : null;

  const pick = (r) => {
    setRef(r); setMsg('');
    const f = board && board.footprints.find((x) => x.ref === r);
    if (f) { setFpid(f.fpid); setValue(f.value); }
  };

  const apply = async () => {
    setBusy(true); setErr(''); setMsg('');
    const edits = [];
    if (fpid && sel && fpid !== sel.fpid) edits.push({ op: 'set_footprint', ref, footprint: fpid });
    if (value && sel && value !== sel.value) edits.push({ op: 'set_value', ref, value });
    if (!edits.length) { setBusy(false); setMsg('没有变化需要提交'); return; }
    try {
      const r = await api.boardEdits(project.project_id, edits);
      setBoard(r.board);
      setMsg(`已应用 ${r.applied} 项修改并写回 .kicad_pcb`);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const revert = async () => {
    setBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.boardRevert(project.project_id);
      setBoard(r.board); setMsg('已恢复到上次编辑前');
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  if (!lib) {
    return (
      <div style={{ border: '1px solid #ddd', borderRadius: 6, marginTop: 12, padding: 12 }}>
        <b>器件 / 封装库</b>
        {err ? <p style={{ color: '#c00' }}>{err}</p> : <p style={{ color: '#888' }}>加载中…</p>}
      </div>
    );
  }

  return (
    <div style={{ border: '1px solid #ddd', borderRadius: 6, marginTop: 12 }}>
      <div style={{ padding: 8, borderBottom: '1px solid #eee' }}>
        <b>器件 / 封装库</b>{' '}
        <small style={{ color: '#888' }}>
          {lib.parts.length} 个器件 · {lib.libs.length} 个封装库 · {lib.footprint_ids.length} 个封装快照
          （这是选型阶段真正可用的清单）
        </small>
      </div>

      {err && <p style={{ color: '#c00', padding: 8, margin: 0, fontSize: 13 }}>{err}</p>}
      {msg && <p style={{ color: '#0a0', padding: 8, margin: 0, fontSize: 12 }}>{msg}</p>}

      <div style={{ display: 'flex', gap: 12, padding: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px', maxHeight: 260, overflow: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#f6f6f6' }}>
                <th align="left" style={{ padding: 4 }}>器件</th>
                <th align="left" style={{ padding: 4 }}>符号</th>
                <th align="left" style={{ padding: 4 }}>默认封装</th>
                <th align="right" style={{ padding: 4 }}>脚</th>
              </tr>
            </thead>
            <tbody>
              {lib.parts.map((p) => (
                <tr key={p.key} style={{ borderBottom: '1px solid #f0f0f0' }} title={p.description}>
                  <td style={{ padding: 4 }}><b>{p.key}</b></td>
                  <td style={{ padding: 4, color: '#555' }}>{p.symbol}</td>
                  <td style={{ padding: 4, color: '#555' }}>{p.footprint}</td>
                  <td align="right" style={{ padding: 4 }}>{p.pin_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ flex: '1 1 260px', maxHeight: 260, overflow: 'auto', fontSize: 12 }}>
          {lib.libs.map((l) => (
            <div key={l.lib} style={{ marginBottom: 6 }}>
              <b>{l.lib}</b> <small style={{ color: '#888' }}>({l.count})</small>
              <div style={{ color: '#555' }}>{l.footprints.join('、')}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ borderTop: '1px solid #eee', padding: 8 }}>
        <b style={{ fontSize: 13 }}>换封装 / 改值</b>
        {!board ? (
          <p style={{ color: '#888', fontSize: 12, margin: '6px 0 0' }}>
            还没有可编辑的 PCB（先跑到 pcb 阶段）
          </p>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 6 }}>
            <select value={ref} onChange={(e) => pick(e.target.value)}>
              {board.footprints.map((f) => (
                <option key={f.ref} value={f.ref}>{f.ref}（{f.value}）</option>
              ))}
            </select>
            <span style={{ fontSize: 12, color: '#666' }}>当前封装：{sel ? sel.fpid : '-'}</span>
            <select value={fpid} onChange={(e) => setFpid(e.target.value)} style={{ minWidth: 260 }}>
              {lib.footprint_ids.map((i) => <option key={i} value={i}>{i}</option>)}
            </select>
            <input value={value} onChange={(e) => setValue(e.target.value)}
                   placeholder="值（如 10k）" style={{ width: 110 }} />
            <button onClick={apply} disabled={busy}>应用并写回</button>
            <button onClick={revert} disabled={busy}>撤销全部编辑</button>
          </div>
        )}
      </div>
    </div>
  );
}
