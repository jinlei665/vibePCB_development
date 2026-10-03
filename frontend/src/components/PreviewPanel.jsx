import React, { useEffect, useState } from 'react';
import {
  Alert, App as AntApp, Button, Card, Empty, Segmented, Space, Spin, Tooltip, Typography,
} from 'antd';
import {
  ExportOutlined, PictureOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { api } from '../api/client.js';

const { Text } = Typography;

// 实时预览面板：显示由后端 kicad-cli 渲染出的原理图 / PCB SVG。
// refreshKey 变化时自动重新拉图 —— PipelinePage 把各阶段状态拼成 key 传进来，
// 于是每跑完一个阶段画面就跟着更新，实现「生成过程中实时看见」。
const KINDS = [
  { key: 'schematic', label: '原理图' },
  { key: 'pcb', label: 'PCB 布局布线' },
];

export default function PreviewPanel({ project, refreshKey = 0, height = 520 }) {
  const { message } = AntApp.useApp();
  const [kind, setKind] = useState('schematic');
  const [url, setUrl] = useState('');
  const [bust, setBust] = useState(() => Date.now());
  const [err, setErr] = useState('');
  const [pending, setPending] = useState('');
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);

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
    setOpening(true);
    try {
      const r = await api.openInKiCad(project.project_id, kind);
      message.success(`已用 KiCad 打开 ${r.file}`);
    } catch (e) {
      message.error(`打开失败：${e.message || e}`);
    } finally {
      setOpening(false);
    }
  };

  return (
    <Card
      variant="borderless"
      style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
      title={
        <Space>
          <PictureOutlined />
          <span>实时预览</span>
        </Space>
      }
      extra={
        <Space size={8}>
          <Segmented
            size="small"
            value={kind}
            onChange={setKind}
            options={KINDS.map((k) => ({ value: k.key, label: k.label }))}
          />
          <Tooltip title="重新渲染（源文件变化时后端也会自动重渲染）">
            <Button
              size="small"
              icon={<ReloadOutlined spin={loading} />}
              onClick={() => setBust(Date.now())}
              disabled={loading}
            />
          </Tooltip>
          <Tooltip title="把当前产物交给 KiCad 做重度编辑（需本机装有 KiCad）">
            <Button size="small" icon={<ExportOutlined />} loading={opening} onClick={open}>
              在 KiCad 中打开
            </Button>
          </Tooltip>
        </Space>
      }
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      {pending && !err && (
        <Alert
          type="info"
          showIcon
          message={`${pending}（该阶段跑完会自动出现）`}
          style={{ marginBottom: 12 }}
        />
      )}

      <div
        className="vp-canvas-bg vp-scroll"
        style={{
          height,
          overflow: 'auto',
          borderRadius: 8,
          border: '1px solid var(--vp-border)',
          display: 'grid',
          placeItems: loading && !url ? 'center' : 'start center',
          position: 'relative',
        }}
      >
        {url ? (
          <img
            src={url}
            alt={`${kind} 预览`}
            style={{ maxWidth: '100%', display: 'block', margin: '0 auto' }}
          />
        ) : loading ? (
          <Space direction="vertical" align="center" style={{ padding: 48 }}>
            <Spin />
            <Text type="secondary" style={{ fontSize: 12 }}>正在渲染…</Text>
          </Space>
        ) : !err && !pending ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<Text type="secondary">暂无预览</Text>}
            style={{ padding: 48 }}
          />
        ) : null}
      </div>
    </Card>
  );
}
