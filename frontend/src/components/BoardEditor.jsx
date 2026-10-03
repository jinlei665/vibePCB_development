import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client.js';

// PCB 画布编辑器（CAD 化增量 3）
//
// 底图：后端用 kicad-cli 渲染的 SVG（可选开关）；叠加层：本组件用 Canvas 依据
// /api/projects/{id}/board 的**板模型**精确绘制，并支持拖拽编辑。
// 编辑通过 POST /board/edits 批量写回 .kicad_pcb —— 所以改完仍能用 KiCad 打开继续精修。
//
// 为什么叠加层不直接画在 SVG 上：SVG 的 viewBox 由 kicad-cli 决定（本机实测比板
// bbox 各方向小约 0.05mm），依赖它做坐标映射不够可靠；板模型坐标才是权威的。
// 底图仅作视觉参考，按同一个 bbox 做线性映射，误差 ~0.05mm（肉眼不可见）。

const PAD = 24;          // 画布内边距（px）
const HIT_PX = 6;        // 命中容差（px）
const DEFAULT_GRID = 1.27;

function snap(v, grid, on) {
  return on ? Math.round(v / grid) * grid : v;
}

export default function BoardEditor({ project }) {
  const [model, setModel] = useState(null);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [showUnderlay, setShowUnderlay] = useState(true);
  const [gridOn, setGridOn] = useState(true);
  const [gridSize, setGridSize] = useState(DEFAULT_GRID);
  const [mode, setMode] = useState('select');        // select | add_track
  const [layer, setLayer] = useState('F.Cu');
  const [net, setNet] = useState('');
  const [sel, setSel] = useState(null);              // {type, key}
  const [dirty, setDirty] = useState(0);             // 触发重绘

  const canvasRef = useRef(null);
  const dragRef = useRef(null);
  const pendingRef = useRef(null);                   // 加线的第一个点
  const sizeRef = useRef({ w: 800, h: 600, scale: 1, ox: 0, oy: 0 });

  const load = useCallback(async () => {
    setErr('');
    try {
      const m = await api.board(project.project_id);
      setModel(m);
      if (m.nets && m.nets.length && !m.nets.includes(net)) setNet(m.nets[0]);
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, [project.project_id, net]);

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project.project_id]);

  // ---------- 坐标映射 ----------
  const mapping = useMemo(() => {
    if (!model) return null;
    const [x0, y0, x1, y1] = model.bbox;
    const bw = Math.max(x1 - x0, 1e-6);
    const bh = Math.max(y1 - y0, 1e-6);
    const availW = 900 - PAD * 2;
    const availH = 520 - PAD * 2;
    const scale = Math.min(availW / bw, availH / bh);
    const w = Math.round(bw * scale) + PAD * 2;
    const h = Math.round(bh * scale) + PAD * 2;
    return { x0, y0, bw, bh, scale, w, h };
  }, [model]);

  const toPx = useCallback((x, y) => {
    const m = mapping;
    return [PAD + (x - m.x0) * m.scale, PAD + (y - m.y0) * m.scale];
  }, [mapping]);

  const toMm = useCallback((px, py) => {
    const m = mapping;
    return [(px - PAD) / m.scale + m.x0, (py - PAD) / m.scale + m.y0];
  }, [mapping]);

  // ---------- 绘制 ----------
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !model || !mapping) return;
    const ctx = cv.getContext('2d');
    const { w, h } = mapping;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#fafafa';
    ctx.fillRect(0, 0, w, h);

    // 板框
    ctx.strokeStyle = '#c9a227';
    ctx.lineWidth = 1.5;
    for (const s of model.outline) {
      const [ax, ay] = toPx(s.start[0], s.start[1]);
      const [bx, by] = toPx(s.end[0], s.end[1]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }

    // 走线（F.Cu 红 / B.Cu 蓝）
    for (const t of model.tracks) {
      const [ax, ay] = toPx(t.start[0], t.start[1]);
      const [bx, by] = toPx(t.end[0], t.end[1]);
      ctx.strokeStyle = t.layer === 'B.Cu' ? '#1d4ed8' : '#dc2626';
      ctx.lineWidth = Math.max(1, t.width * mapping.scale);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }

    // 过孔
    for (const v of model.vias) {
      const [vx, vy] = toPx(v.x, v.y);
      ctx.fillStyle = '#059669';
      ctx.beginPath(); ctx.arc(vx, vy, Math.max(2, (v.size / 2) * mapping.scale), 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fafafa';
      ctx.beginPath(); ctx.arc(vx, vy, Math.max(1, (v.drill / 2) * mapping.scale), 0, Math.PI * 2); ctx.fill();
    }

    // 器件：焊盘 + 外框 + 位号
    for (const f of model.footprints) {
      const isSel = sel && sel.type === 'footprint' && sel.key === f.ref;
      for (const p of f.pads) {
        const [px, py] = toPx(p.x, p.y);
        const w2 = Math.max(2, (p.w / 2) * mapping.scale);
        const h2 = Math.max(2, (p.h / 2) * mapping.scale);
        ctx.fillStyle = p.side === 'B' ? '#93c5fd' : '#fca5a5';
        if (p.shape === 0) { ctx.beginPath(); ctx.arc(px, py, Math.max(w2, h2), 0, Math.PI * 2); ctx.fill(); }
        else ctx.fillRect(px - w2, py - h2, w2 * 2, h2 * 2);
      }
      const [bx, by, bx2, by2] = f.bbox;
      const [ax, ay] = toPx(bx, by);
      const [cx, cy] = toPx(bx2, by2);
      ctx.strokeStyle = isSel ? '#7c3aed' : '#94a3b8';
      ctx.lineWidth = isSel ? 2.5 : 1;
      ctx.strokeRect(ax, ay, cx - ax, cy - ay);
      ctx.fillStyle = isSel ? '#5b21b6' : '#475569';
      ctx.font = '11px sans-serif';
      ctx.fillText(f.ref, ax, ay - 3);
    }

    // 待放置的走线起点
    if (pendingRef.current) {
      const [px, py] = toPx(pendingRef.current[0], pendingRef.current[1]);
      ctx.strokeStyle = '#7c3aed';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.stroke();
    }
  }, [model, mapping, sel, toPx, dirty]);

  // ---------- 命中测试 ----------
  const hitTest = (mx, my) => {
    const thr = HIT_PX;
    // 器件优先
    for (let i = model.footprints.length - 1; i >= 0; i -= 1) {
      const f = model.footprints[i];
      const [ax, ay] = toPx(f.bbox[0], f.bbox[1]);
      const [bx, by] = toPx(f.bbox[2], f.bbox[3]);
      if (mx >= Math.min(ax, bx) - 2 && mx <= Math.max(ax, bx) + 2
          && my >= Math.min(ay, by) - 2 && my <= Math.max(ay, by) + 2) {
        return { type: 'footprint', key: f.ref, obj: f };
      }
    }
    for (const t of model.tracks) {
      const [ax, ay] = toPx(t.start[0], t.start[1]);
      const [bx, by] = toPx(t.end[0], t.end[1]);
      const dx = bx - ax; const dy = by - ay;
      const len2 = dx * dx + dy * dy || 1;
      let u = ((mx - ax) * dx + (my - ay) * dy) / len2;
      u = Math.max(0, Math.min(1, u));
      const px = ax + u * dx; const py = ay + u * dy;
      if (Math.hypot(mx - px, my - py) <= thr) return { type: 'track', key: t.id, obj: t };
    }
    for (const v of model.vias) {
      const [vx, vy] = toPx(v.x, v.y);
      if (Math.hypot(mx - vx, my - vy) <= Math.max(thr, (v.size / 2) * mapping.scale)) {
        return { type: 'via', key: v.id, obj: v };
      }
    }
    return null;
  };

  const localXY = (ev) => {
    const r = canvasRef.current.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  };

  // ---------- 鼠标交互 ----------
  const onDown = (ev) => {
    if (!model || busy) return;
    const [mx, my] = localXY(ev);
    const [mmx, mmy] = toMm(mx, my);

    if (mode === 'add_track') {
      const p = [snap(mmx, gridSize, gridOn), snap(mmy, gridSize, gridOn)];
      if (!pendingRef.current) { pendingRef.current = p; setDirty((d) => d + 1); return; }
      const a = pendingRef.current; pendingRef.current = null;
      applyEdits([{ op: 'add_track', layer, start: a, end: p, width: 0.25, net }]);
      return;
    }

    const hit = hitTest(mx, my);
    setSel(hit ? { type: hit.type, key: hit.key } : null);
    if (hit && (hit.type === 'footprint' || hit.type === 'track' || hit.type === 'via')) {
      dragRef.current = { hit, mx, my, moved: false };
    }
  };

  const onMove = (ev) => {
    const d = dragRef.current;
    if (!d || !model) return;
    const [mx, my] = localXY(ev);
    const ddx = mx - d.mx; const ddy = my - d.my;
    if (Math.abs(ddx) < 2 && Math.abs(ddy) < 2) return;
    d.moved = true;

    // 实时预览：直接改本地模型（不落盘），松手才提交
    const dxmm = ddx / mapping.scale; const dymm = ddy / mapping.scale;
    setModel((prev) => {
      const next = { ...prev, footprints: prev.footprints.map((f) => ({ ...f })),
        tracks: prev.tracks.map((t) => ({ ...t })), vias: prev.vias.map((v) => ({ ...v })) };
      if (d.hit.type === 'footprint') {
        const f = next.footprints.find((x) => x.ref === d.hit.key);
        const base = d.orig || (d.orig = { x: f.x, y: f.y, bbox: f.bbox.slice(), pads: f.pads.map((p) => ({ ...p })) });
        f.x = base.x + (mx - d.mx) / mapping.scale;
        f.y = base.y + (my - d.my) / mapping.scale;
        if (gridOn) { f.x = snap(f.x, gridSize, true); f.y = snap(f.y, gridSize, true); }
        const sx = f.x - base.x; const sy = f.y - base.y;
        f.pads = base.pads.map((p) => ({ ...p, x: p.x + sx, y: p.y + sy }));
        f.bbox = [base.bbox[0] + sx, base.bbox[1] + sy, base.bbox[2] + sx, base.bbox[3] + sy];
      } else if (d.hit.type === 'track') {
        const t = next.tracks.find((x) => x.id === d.hit.key);
        const base = d.orig || (d.orig = { s: t.start.slice(), e: t.end.slice() });
        const dx = (mx - d.mx) / mapping.scale; const dy = (my - d.my) / mapping.scale;
        t.start = [base.s[0] + dx, base.s[1] + dy];
        t.end = [base.e[0] + dx, base.e[1] + dy];
      } else {
        const v = next.vias.find((x) => x.id === d.hit.key);
        const base = d.orig || (d.orig = { x: v.x, y: v.y });
        v.x = base.x + (mx - d.mx) / mapping.scale;
        v.y = base.y + (my - d.my) / mapping.scale;
        if (gridOn) { v.x = snap(v.x, gridSize, true); v.y = snap(v.y, gridSize, true); }
      }
      return next;
    });
  };

  const onUp = () => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d || !d.moved || !d.orig) return;
    const obj = model.footprints.find((f) => f.ref === d.hit.key)
      || model.tracks.find((t) => t.id === d.hit.key)
      || model.vias.find((v) => v.id === d.hit.key);
    if (!obj) return;
    if (d.hit.type === 'footprint') {
      applyEdits([{ op: 'move_footprint', ref: d.hit.key, x: round(obj.x), y: round(obj.y), rot: obj.rot }]);
    } else if (d.hit.type === 'track') {
      applyEdits([{ op: 'move_track', id: d.hit.key, start: round2(obj.start), end: round2(obj.end) }]);
    } else {
      // 过孔只能平移：后端按 dx/dy 处理（用 x/y 会被忽略）
      const o = d.orig || { x: obj.x, y: obj.y };
      applyEdits([{ op: 'move_track', id: d.hit.key,
                    dx: round(obj.x - o.x), dy: round(obj.y - o.y) }]);
    }
  };

  const round = (v) => Math.round(v * 1000) / 1000;
  const round2 = (a) => [round(a[0]), round(a[1])];

  const applyEdits = async (edits) => {
    setBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.boardEdits(project.project_id, edits);
      setModel(r.board);
      setMsg(`已应用 ${r.applied} 项编辑并写回 .kicad_pcb`);
    } catch (e) {
      setErr(String(e.message || e));
      await load();          // 失败则回到磁盘上的真实状态
    } finally {
      setBusy(false);
      setDirty((d) => d + 1);
    }
  };

  const onDelete = async () => {
    if (!sel || sel.type === 'footprint') return;
    await applyEdits([{ op: 'delete_item', id: sel.key }]);
    setSel(null);
  };

  const onRevert = async () => {
    setBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.boardRevert(project.project_id);
      setModel(r.board);
      setMsg('已恢复到上次编辑前的备份');
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  // 键盘删除
  useEffect(() => {
    const h = (e) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel && sel.type !== 'footprint') {
        e.preventDefault(); onDelete();
      }
      if (e.key === 'Escape') { setSel(null); pendingRef.current = null; setDirty((d) => d + 1); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [sel, model]);   // eslint-disable-line

  if (!model) {
    return (
      <div style={{ border: '1px solid #ddd', borderRadius: 6, padding: 12, marginTop: 12 }}>
        <b>PCB 编辑器</b>
        {err ? <p style={{ color: '#c00' }}>{err}</p> : <p style={{ color: '#888' }}>加载板模型…</p>}
        <button onClick={load}>重试</button>
      </div>
    );
  }

  const { w, h } = mapping;

  return (
    <div style={{ border: '1px solid #ddd', borderRadius: 6, marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
                    padding: 8, borderBottom: '1px solid #eee' }}>
        <b>PCB 编辑器</b>
        <button onClick={() => { setMode('select'); pendingRef.current = null; }}
          style={{ fontWeight: mode === 'select' ? 'bold' : 'normal' }}>选择/拖拽</button>
        <button onClick={() => { setMode('add_track'); pendingRef.current = null; }}
          style={{ fontWeight: mode === 'add_track' ? 'bold' : 'normal' }}>画线</button>
        {mode === 'add_track' && (
          <>
            <select value={layer} onChange={(e) => setLayer(e.target.value)}>
              <option value="F.Cu">F.Cu</option><option value="B.Cu">B.Cu</option>
            </select>
            <select value={net} onChange={(e) => setNet(e.target.value)}>
              {model.nets.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </>
        )}
        <label style={{ fontSize: 12 }}>
          <input type="checkbox" checked={gridOn} onChange={(e) => setGridOn(e.target.checked)} /> 栅格吸附
        </label>
        <input type="number" step="0.1" value={gridSize} style={{ width: 70 }}
          onChange={(e) => setGridSize(parseFloat(e.target.value) || DEFAULT_GRID)} />
        <label style={{ fontSize: 12 }}>
          <input type="checkbox" checked={showUnderlay} onChange={(e) => setShowUnderlay(e.target.checked)} /> 显示 KiCad 底图
        </label>
        <button onClick={() => setDirty((d) => d + 1)}>刷新</button>
        <button onClick={onDelete} disabled={!sel || sel.type === 'footprint' || busy}>删除所选</button>
        <button onClick={onRevert} disabled={busy}>撤销全部编辑</button>
      </div>

      {err && <p style={{ color: '#c00', padding: 8, margin: 0, fontSize: 13 }}>{err}</p>}
      {msg && <p style={{ color: '#0a0', padding: 8, margin: 0, fontSize: 12 }}>{msg}</p>}

      <div style={{ position: 'relative', width: w, height: h, margin: '8px auto' }}>
        {showUnderlay && (
          <img alt="kicad 底图"
            src={api.renderUrl(project.project_id, 'pcb', dirty + 1)}
            style={{ position: 'absolute', left: PAD, top: PAD,
                     width: mapping.bw * mapping.scale, height: mapping.bh * mapping.scale,
                     opacity: 0.55, pointerEvents: 'none' }} />
        )}
        <canvas ref={canvasRef} width={w} height={h}
          style={{ position: 'absolute', left: 0, top: 0, cursor: mode === 'add_track' ? 'crosshair' : 'move' }}
          onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp} />
      </div>

      <div style={{ padding: '0 8px 8px', fontSize: 12, color: '#666' }}>
        选中：{sel ? `${sel.type} ${sel.key}` : '无'} ·
        器件 {model.counts.footprints} · 走线 {model.counts.tracks} · 过孔 {model.counts.vias} ·
        拖拽器件/走线即可移动（松手写回）；「画线」模式下点两下画一根走线；Delete 删除所选
      </div>
    </div>
  );
}
