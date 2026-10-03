import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, App as AntApp, Button, Checkbox, Divider, Empty, InputNumber, Segmented,
  Select, Space, Spin, Tag, Tooltip, Typography,
} from 'antd';
import {
  ClearOutlined, DeleteOutlined, ReloadOutlined, RollbackOutlined, SelectOutlined,
} from '@ant-design/icons';
import { api } from '../api/client.js';

const { Text } = Typography;

// PCB 画布编辑器（CAD 化增量 3）
//
// 底图：后端用 kicad-cli 渲染的 SVG（可选开关）；叠加层：本组件用 Canvas 依据
// /api/projects/{id}/board 的**板模型**精确绘制，并支持拖拽编辑。
// 编辑通过 POST /board/edits 批量写回 .kicad_pcb —— 所以改完仍能用 KiCad 打开继续精修。
//
// 为什么叠加层不直接画在 SVG 上：SVG 的 viewBox 由 kicad-cli 决定（本机实测比板
// bbox 各方向小约 0.05mm），依赖它做坐标映射不够可靠；板模型坐标才是权威的。

const PAD = 24;          // 画布内边距（px）
const HIT_PX = 6;        // 命中容差（px）
const DEFAULT_GRID = 1.27;

const snap = (v, grid, on) => (on ? Math.round(v / grid) * grid : v);
const round3 = (v) => Math.round(v * 1000) / 1000;
const round2 = (a) => [round3(a[0]), round3(a[1])];

function Legend() {
  return (
    <Space size={12} wrap>
      <Space size={4}><span style={{ width: 10, height: 3, background: '#dc2626', display: 'inline-block' }} /><Text type="secondary" style={{ fontSize: 11 }}>F.Cu</Text></Space>
      <Space size={4}><span style={{ width: 10, height: 3, background: '#1d4ed8', display: 'inline-block' }} /><Text type="secondary" style={{ fontSize: 11 }}>B.Cu</Text></Space>
      <Space size={4}><span style={{ width: 8, height: 8, borderRadius: 4, background: '#059669', display: 'inline-block' }} /><Text type="secondary" style={{ fontSize: 11 }}>过孔</Text></Space>
      <Space size={4}><span style={{ width: 10, height: 10, background: '#fca5a5', display: 'inline-block' }} /><Text type="secondary" style={{ fontSize: 11 }}>正面焊盘</Text></Space>
      <Space size={4}><span style={{ width: 10, height: 10, background: '#93c5fd', display: 'inline-block' }} /><Text type="secondary" style={{ fontSize: 11 }}>背面焊盘</Text></Space>
    </Space>
  );
}

export default function BoardEditor({ project }) {
  const { message } = AntApp.useApp();
  const [model, setModel] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [showUnderlay, setShowUnderlay] = useState(true);
  const [gridOn, setGridOn] = useState(true);
  const [gridSize, setGridSize] = useState(DEFAULT_GRID);
  const [mode, setMode] = useState('select');
  const [layer, setLayer] = useState('F.Cu');
  const [net, setNet] = useState('');
  const [sel, setSel] = useState(null);
  const [dirty, setDirty] = useState(0);

  const canvasRef = useRef(null);
  const dragRef = useRef(null);
  const pendingRef = useRef(null);

  const load = useCallback(async () => {
    setErr('');
    try {
      const m = await api.board(project.project_id);
      setModel(m);
      setNet((prev) => (m.nets && m.nets.length && !m.nets.includes(prev) ? m.nets[0] : prev));
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, [project.project_id]);

  useEffect(() => { load(); }, [load]);

  const mapping = useMemo(() => {
    if (!model) return null;
    const [x0, y0, x1, y1] = model.bbox;
    const bw = Math.max(x1 - x0, 1e-6);
    const bh = Math.max(y1 - y0, 1e-6);
    const scale = Math.min((940 - PAD * 2) / bw, (600 - PAD * 2) / bh);
    return { x0, y0, bw, bh, scale, w: Math.round(bw * scale) + PAD * 2, h: Math.round(bh * scale) + PAD * 2 };
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
    const { w, h, scale } = mapping;

    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = '#c9a227';
    ctx.lineWidth = 1.5;
    for (const s of model.outline) {
      const [ax, ay] = toPx(s.start[0], s.start[1]);
      const [bx, by] = toPx(s.end[0], s.end[1]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }

    for (const t of model.tracks) {
      const [ax, ay] = toPx(t.start[0], t.start[1]);
      const [bx, by] = toPx(t.end[0], t.end[1]);
      ctx.strokeStyle = t.layer === 'B.Cu' ? '#1d4ed8' : '#dc2626';
      ctx.lineWidth = Math.max(1, t.width * scale);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }

    for (const v of model.vias) {
      const [vx, vy] = toPx(v.x, v.y);
      ctx.fillStyle = '#059669';
      ctx.beginPath(); ctx.arc(vx, vy, Math.max(2, (v.size / 2) * scale), 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath(); ctx.arc(vx, vy, Math.max(1, (v.drill / 2) * scale), 0, Math.PI * 2); ctx.fill();
    }

    for (const f of model.footprints) {
      const isSel = sel && sel.type === 'footprint' && sel.key === f.ref;
      for (const p of f.pads) {
        const [px, py] = toPx(p.x, p.y);
        const w2 = Math.max(2, (p.w / 2) * scale);
        const h2 = Math.max(2, (p.h / 2) * scale);
        ctx.fillStyle = p.side === 'B' ? '#93c5fd' : '#fca5a5';
        if (p.shape === 0) { ctx.beginPath(); ctx.arc(px, py, Math.max(w2, h2), 0, Math.PI * 2); ctx.fill(); }
        else ctx.fillRect(px - w2, py - h2, w2 * 2, h2 * 2);
      }
      const [ax, ay] = toPx(f.bbox[0], f.bbox[1]);
      const [cx, cy] = toPx(f.bbox[2], f.bbox[3]);
      ctx.strokeStyle = isSel ? '#7c3aed' : '#94a3b8';
      ctx.lineWidth = isSel ? 2.5 : 1;
      ctx.strokeRect(ax, ay, cx - ax, cy - ay);
      ctx.fillStyle = isSel ? '#5b21b6' : '#475569';
      ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
      ctx.fillText(f.ref, ax, ay - 3);
    }

    if (pendingRef.current) {
      const [px, py] = toPx(pendingRef.current[0], pendingRef.current[1]);
      ctx.strokeStyle = '#7c3aed';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.stroke();
    }
  }, [model, mapping, sel, toPx, dirty]);

  // ---------- 命中测试 ----------
  const hitTest = (mx, my) => {
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
      if (Math.hypot(mx - (ax + u * dx), my - (ay + u * dy)) <= HIT_PX) {
        return { type: 'track', key: t.id, obj: t };
      }
    }
    for (const v of model.vias) {
      const [vx, vy] = toPx(v.x, v.y);
      if (Math.hypot(mx - vx, my - vy) <= Math.max(HIT_PX, (v.size / 2) * mapping.scale)) {
        return { type: 'via', key: v.id, obj: v };
      }
    }
    return null;
  };

  const localXY = (ev) => {
    const r = canvasRef.current.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  };

  // ---------- 编辑提交 ----------
  const applyEdits = useCallback(async (edits) => {
    setBusy(true); setErr('');
    try {
      const r = await api.boardEdits(project.project_id, edits);
      setModel(r.board);
      message.success(`已应用 ${r.applied} 项编辑并写回 .kicad_pcb`);
    } catch (e) {
      setErr(String(e.message || e));
      message.error(`编辑失败：${e.message || e}`);
      await load();          // 失败则回到磁盘上的真实状态
    } finally {
      setBusy(false);
      setDirty((d) => d + 1);
    }
  }, [project.project_id, message, load]);

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
    if (hit) dragRef.current = { hit, mx, my, moved: false };
  };

  const onMove = (ev) => {
    const d = dragRef.current;
    if (!d || !model) return;
    const [mx, my] = localXY(ev);
    if (Math.abs(mx - d.mx) < 2 && Math.abs(my - d.my) < 2) return;
    d.moved = true;

    // 实时预览：直接改本地模型（不落盘），松手才提交
    setModel((prev) => {
      const next = {
        ...prev,
        footprints: prev.footprints.map((f) => ({ ...f })),
        tracks: prev.tracks.map((t) => ({ ...t })),
        vias: prev.vias.map((v) => ({ ...v })),
      };
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
      applyEdits([{ op: 'move_footprint', ref: d.hit.key, x: round3(obj.x), y: round3(obj.y), rot: obj.rot }]);
    } else if (d.hit.type === 'track') {
      applyEdits([{ op: 'move_track', id: d.hit.key, start: round2(obj.start), end: round2(obj.end) }]);
    } else {
      // 过孔只能平移：后端按 dx/dy 处理（用 x/y 会被忽略）
      const o = d.orig || { x: obj.x, y: obj.y };
      applyEdits([{ op: 'move_track', id: d.hit.key, dx: round3(obj.x - o.x), dy: round3(obj.y - o.y) }]);
    }
  };

  const onDelete = async () => {
    if (!sel || sel.type === 'footprint') return;
    await applyEdits([{ op: 'delete_item', id: sel.key }]);
    setSel(null);
  };

  const onRevert = async () => {
    setBusy(true); setErr('');
    try {
      const r = await api.boardRevert(project.project_id);
      setModel(r.board);
      setSel(null);
      message.success('已恢复到上次编辑前的备份');
    } catch (e) {
      setErr(String(e.message || e));
      message.error(`撤销失败：${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const h = (e) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel && sel.type !== 'footprint') {
        e.preventDefault(); onDelete();
      }
      if (e.key === 'Escape') { setSel(null); pendingRef.current = null; setDirty((d) => d + 1); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  });   // 每次渲染重新绑定，读到的 sel/model 都是最新的

  if (!model) {
    return (
      <Space direction="vertical" align="center" style={{ width: '100%', padding: 40 }}>
        {err ? <Alert type="error" showIcon message={err} /> : <Spin />}
        <Text type="secondary" style={{ fontSize: 12 }}>
          {err ? '请先完成 PCB 阶段' : '正在加载板模型…'}
        </Text>
        <Button size="small" onClick={load}>重试</Button>
      </Space>
    );
  }

  const { w, h } = mapping;
  const stats = [
    { k: '器件', v: model.counts.footprints },
    { k: '走线', v: model.counts.tracks },
    { k: '过孔', v: model.counts.vias },
  ];

  return (
    <div>
      <Space wrap size={8} style={{ marginBottom: 10 }}>
        <Segmented
          size="small"
          value={mode}
          onChange={(v) => { setMode(v); pendingRef.current = null; setDirty((d) => d + 1); }}
          options={[
            { value: 'select', label: '选择 / 拖拽', icon: <SelectOutlined /> },
            { value: 'add_track', label: '画线', icon: <ClearOutlined /> },
          ]}
        />
        {mode === 'add_track' && (
          <>
            <Select
              size="small" value={layer} onChange={setLayer} style={{ width: 92 }}
              options={[{ value: 'F.Cu' }, { value: 'B.Cu' }]}
            />
            <Select
              size="small" value={net} onChange={setNet} style={{ width: 150 }}
              options={model.nets.map((n) => ({ value: n }))}
            />
          </>
        )}
        <Divider type="vertical" style={{ margin: 0 }} />
        <Checkbox checked={gridOn} onChange={(e) => setGridOn(e.target.checked)}>
          <Text style={{ fontSize: 12 }}>栅格吸附</Text>
        </Checkbox>
        <InputNumber
          size="small" min={0.01} step={0.1} value={gridSize} style={{ width: 84 }}
          onChange={(v) => setGridSize(v || DEFAULT_GRID)} suffix="mm"
        />
        <Checkbox checked={showUnderlay} onChange={(e) => setShowUnderlay(e.target.checked)}>
          <Text style={{ fontSize: 12 }}>KiCad 底图</Text>
        </Checkbox>
        <Divider type="vertical" style={{ margin: 0 }} />
        <Button size="small" icon={<ReloadOutlined />} onClick={load} disabled={busy}>刷新</Button>
        <Button
          size="small" danger icon={<DeleteOutlined />} onClick={onDelete}
          disabled={!sel || sel.type === 'footprint' || busy}
        >
          删除所选
        </Button>
        <Button size="small" icon={<RollbackOutlined />} onClick={onRevert} disabled={busy}>
          撤销全部编辑
        </Button>
      </Space>

      <div style={{ marginBottom: 8 }}>
        <Legend />
      </div>

      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 10 }} />}

      <div
        className="vp-scroll"
        style={{
          position: 'relative', width: w, height: h, margin: '0 auto',
          border: '1px solid var(--vp-border)', borderRadius: 8, overflow: 'hidden',
          background: '#fafafa',
        }}
      >
        {showUnderlay && (
          <img
            alt="kicad 底图"
            src={api.renderUrl(project.project_id, 'pcb', dirty + 1)}
            style={{
              position: 'absolute', left: PAD, top: PAD,
              width: mapping.bw * mapping.scale, height: mapping.bh * mapping.scale,
              opacity: 0.5, pointerEvents: 'none',
            }}
          />
        )}
        <canvas
          ref={canvasRef}
          width={w}
          height={h}
          style={{
            position: 'absolute', left: 0, top: 0,
            cursor: mode === 'add_track' ? 'crosshair' : 'move',
          }}
          onMouseDown={onDown}
          onMouseMove={onMove}
          onMouseUp={onUp}
          onMouseLeave={onUp}
        />
      </div>

      <Space size={16} wrap style={{ marginTop: 10 }}>
        {stats.map((s) => (
          <Text key={s.k} type="secondary" style={{ fontSize: 12 }}>
            {s.k} <Text strong style={{ fontSize: 12 }}>{s.v}</Text>
          </Text>
        ))}
        <Divider type="vertical" style={{ margin: 0 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          选中：{sel ? <Tag color="purple" style={{ marginInlineEnd: 0 }}>{sel.type} {sel.key}</Tag> : '无'}
        </Text>
      </Space>

      <div style={{ marginTop: 6 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          拖拽器件 / 走线即可移动（松手才写回）；「画线」模式下点两下画一根走线；Delete 删除所选；Esc 取消选择。
        </Text>
      </div>
    </div>
  );
}
