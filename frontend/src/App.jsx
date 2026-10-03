import React, { useCallback, useEffect, useState } from 'react';
import {
  App as AntApp, Badge, Button, ConfigProvider, Divider, Empty, Layout, Menu,
  Space, Tag, Tooltip, Typography,
} from 'antd';
import {
  ApiOutlined, AppstoreOutlined, BgColorsOutlined, ExperimentOutlined,
  FileTextOutlined, PlusCircleOutlined, RocketOutlined, ToolOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import { api } from './api/client.js';
import { buildTheme } from './theme.js';
import PromptPage from './pages/PromptPage.jsx';
import PipelinePage from './pages/PipelinePage.jsx';
import ArtifactsPage from './pages/ArtifactsPage.jsx';

const { Sider, Header, Content } = Layout;
const { Text, Title } = Typography;

const NAV = [
  { key: 'prompt', icon: <PlusCircleOutlined />, label: '新建项目' },
  { key: 'pipeline', icon: <RocketOutlined />, label: '生成流水线', needsProject: true },
  { key: 'artifacts', icon: <FileTextOutlined />, label: '产物与编辑', needsProject: true },
];

function EngineTag({ ok, label, tip }) {
  return (
    <Tooltip title={tip}>
      <Tag
        color={ok ? 'success' : 'default'}
        style={{ marginInlineEnd: 0 }}
        icon={<ApiOutlined />}
      >
        {label}
      </Tag>
    </Tooltip>
  );
}

function Shell({ dark, setDark }) {
  const { message } = AntApp.useApp();
  const [view, setView] = useState('prompt');
  const [project, setProject] = useState(null);
  const [caps, setCaps] = useState(null);
  const [projects, setProjects] = useState([]);
  const [healthy, setHealthy] = useState(null);

  const refreshProjects = useCallback(async () => {
    try {
      const d = await api.listProjects();
      setProjects(d.projects || []);
    } catch (e) {
      setProjects([]);
    }
  }, []);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => setCaps(null));
    api.health().then(() => setHealthy(true)).catch(() => setHealthy(false));
    refreshProjects();
  }, [refreshProjects]);

  const openProject = async (id) => {
    try {
      const d = await api.getProject(id);
      setProject(d);
      setView('pipeline');
    } catch (e) {
      message.error(`打开项目失败：${e.message || e}`);
    }
  };

  const onCreated = (p) => {
    setProject(p);
    setView('pipeline');
    refreshProjects();
  };

  const navItems = NAV.map((n) => ({
    key: n.key,
    icon: n.icon,
    label: n.label,
    disabled: n.needsProject && !project,
  }));

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={238}
        theme={dark ? 'dark' : 'light'}
        style={{ borderInlineEnd: '1px solid var(--vp-border, rgba(128,128,128,0.16))' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', position: 'sticky', top: 0 }}>
          {/* 品牌区 */}
          <div style={{ padding: '18px 20px 14px' }}>
            <Space align="center" size={10}>
              <span
                style={{
                  width: 30, height: 30, borderRadius: 8, display: 'grid', placeItems: 'center',
                  background: 'linear-gradient(135deg,#1677ff,#13c2c2)', color: '#fff', fontSize: 16,
                }}
              >
                <ThunderboltOutlined />
              </span>
              <div style={{ lineHeight: 1.15 }}>
                <div className="vp-brand" style={{ fontSize: 17 }}>VibePCB</div>
                <Text type="secondary" style={{ fontSize: 11 }}>自然语言 → 硬件</Text>
              </div>
            </Space>
          </div>

          <Menu
            mode="inline"
            theme={dark ? 'dark' : 'light'}
            selectedKeys={[view]}
            items={navItems}
            onClick={({ key }) => setView(key)}
            style={{ borderInlineEnd: 0 }}
          />

          <Divider style={{ margin: '10px 0 6px' }}>
            <Text type="secondary" style={{ fontSize: 11, fontWeight: 400 }}>最近项目</Text>
          </Divider>

          <div className="vp-scroll" style={{ flex: 1, overflowY: 'auto', padding: '0 8px 8px' }}>
            {projects.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={<Text type="secondary" style={{ fontSize: 12 }}>还没有项目</Text>}
                style={{ margin: '12px 0' }}
              />
            ) : (
              projects.slice(0, 30).map((p) => {
                const active = project && project.project_id === p.project_id;
                return (
                  <div
                    key={p.project_id}
                    onClick={() => openProject(p.project_id)}
                    title={p.prompt || p.project_id}
                    style={{
                      padding: '7px 10px',
                      borderRadius: 8,
                      cursor: 'pointer',
                      marginBottom: 2,
                      background: active ? 'rgba(22,119,255,0.12)' : 'transparent',
                      borderInlineStart: active ? '2px solid #1677ff' : '2px solid transparent',
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: active ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.name || p.project_id}
                    </div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {p.overall ? `${p.overall} · ` : ''}{p.project_id}
                    </Text>
                  </div>
                );
              })
            )}
          </div>

          <div style={{ padding: '10px 16px', borderTop: '1px solid var(--vp-border, rgba(128,128,128,0.16))' }}>
            <Space size={6}>
              <Badge status={healthy === false ? 'error' : healthy ? 'success' : 'processing'} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {healthy === false ? '后端离线' : healthy ? '后端已连接' : '连接中…'}
              </Text>
            </Space>
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>v{caps?.version || '0.1.0'}</Text>
            </div>
          </div>
        </div>
      </Sider>

      <Layout>
        <Header
          style={{
            display: 'flex', alignItems: 'center', gap: 12,
            borderBottom: '1px solid var(--vp-border, rgba(128,128,128,0.16))',
            position: 'sticky', top: 0, zIndex: 10,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            {project ? (
              <Space size={10} style={{ maxWidth: '100%' }}>
                <Title level={5} style={{ margin: 0, whiteSpace: 'nowrap' }}>
                  {project.name || project.project_id}
                </Title>
                <Text type="secondary" ellipsis style={{ maxWidth: 560, fontSize: 12 }}>
                  {project.prompt}
                </Text>
              </Space>
            ) : (
              <Title level={5} style={{ margin: 0 }}>新建项目</Title>
            )}
          </div>

          <Space size={6} wrap>
            <EngineTag
              ok={!!caps?.pcbnew_available}
              label={caps?.pcb_engine_selected ? `PCB:${caps.pcb_engine_selected}` : 'PCB:—'}
              tip={caps?.engines?.kicad_cli_path || '未检测到 KiCad'}
            />
            <EngineTag
              ok={!!caps?.kicad_cli_available}
              label={caps?.kicad_version ? `KiCad ${caps.kicad_version}` : 'KiCad —'}
              tip="kicad-cli 用于渲染 SVG 与导出 Gerber"
            />
            <Tooltip title={caps?.deepseek_configured ? `模型 ${caps.deepseek_model}` : '未配置 DEEPSEEK_API_KEY，将走降级模式'}>
              <Tag
                color={caps?.deepseek_configured ? 'blue' : 'warning'}
                style={{ marginInlineEnd: 0 }}
                icon={<ExperimentOutlined />}
              >
                {caps?.deepseek_configured ? 'DeepSeek' : '降级模式'}
              </Tag>
            </Tooltip>
            <Tooltip title={dark ? '切换到浅色' : '切换到深色'}>
              <Button
                type="text"
                icon={<BgColorsOutlined />}
                onClick={() => setDark((v) => !v)}
              />
            </Tooltip>
            <Tooltip title="刷新项目列表">
              <Button type="text" icon={<AppstoreOutlined />} onClick={refreshProjects} />
            </Tooltip>
          </Space>
        </Header>

        <Content className="vp-scroll" style={{ padding: 20, overflowY: 'auto' }}>
          <div style={{ maxWidth: 1480, margin: '0 auto' }}>
            {view === 'prompt' && <PromptPage onCreated={onCreated} caps={caps} />}
            {view === 'pipeline' && (
              project ? (
                <PipelinePage
                  project={project}
                  onDone={(p) => { setProject(p); setView('artifacts'); refreshProjects(); }}
                  onBack={() => setView('prompt')}
                  onOpenArtifacts={() => setView('artifacts')}
                />
              ) : (
                <Empty description="请先新建一个项目" />
              )
            )}
            {view === 'artifacts' && (
              project ? (
                <ArtifactsPage
                  project={project}
                  onBack={() => setView('pipeline')}
                  onOpenPipeline={() => setView('pipeline')}
                />
              ) : (
                <Empty description="请先新建一个项目" />
              )
            )}
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  // 主题状态提到最顶层：ConfigProvider 与顶栏开关共用同一份，不做重复状态同步。
  const [dark, setDark] = useState(() => localStorage.getItem('vibepcb_theme') === 'dark');

  useEffect(() => {
    localStorage.setItem('vibepcb_theme', dark ? 'dark' : 'light');
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, [dark]);

  return (
    <ConfigProvider locale={zhCN} theme={buildTheme(dark)}>
      <AntApp>
        <Shell dark={dark} setDark={setDark} />
      </AntApp>
    </ConfigProvider>
  );
}
