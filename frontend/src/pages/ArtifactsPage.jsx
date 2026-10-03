import React, { useEffect, useState } from 'react';
import {
  App as AntApp, Button, Card, Col, Drawer, Empty, Row, Space, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import {
  CodeOutlined, DownloadOutlined, EyeOutlined, FileTextOutlined, ReloadOutlined,
  RocketOutlined, TableOutlined, ToolOutlined,
} from '@ant-design/icons';
import { api } from '../api/client.js';
import PreviewPanel from '../components/PreviewPanel.jsx';
import BoardEditor from '../components/BoardEditor.jsx';
import LibraryPanel from '../components/LibraryPanel.jsx';

const { Text, Paragraph } = Typography;

const STAGE_TABS = [
  { key: 'schematic', label: '原理图' },
  { key: 'pcb', label: 'PCB' },
  { key: 'firmware', label: '固件' },
  { key: 'gerber', label: 'Gerber' },
  { key: 'parse', label: '规格' },
  { key: 'components', label: 'BOM' },
];

function fmtSize(n) {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export default function ArtifactsPage({ project, onBack, onOpenPipeline }) {
  const { message } = AntApp.useApp();
  const [stage, setStage] = useState('schematic');
  const [arts, setArts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [current, setCurrent] = useState('');
  const [editorTab, setEditorTab] = useState('board');

  const load = async () => {
    setLoading(true);
    try {
      const d = await api.artifacts(project.project_id, stage);
      setArts(d.artifacts || []);
    } catch (e) {
      setArts([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [stage, project.project_id]);

  const view = async (path) => {
    setCurrent(path);
    setText('加载中…');
    setOpen(true);
    try {
      setText(await api.artifactText(project.project_id, stage, path));
    } catch (e) {
      setText(`读取失败：${e.message || e}`);
    }
  };

  const columns = [
    {
      title: '文件',
      dataIndex: 'path',
      render: (p) => (
        <Space size={8}>
          <FileTextOutlined style={{ opacity: 0.55 }} />
          <Text className="vp-mono" style={{ fontSize: 12 }}>{p}</Text>
        </Space>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      width: 96,
      align: 'right',
      render: (n) => <Text type="secondary" style={{ fontSize: 12 }}>{fmtSize(n)}</Text>,
    },
    {
      title: '操作',
      width: 132,
      align: 'right',
      render: (_, a) => (
        <Space size={4}>
          <Tooltip title="在线查看">
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => view(a.path)} />
          </Tooltip>
          <Tooltip title="下载">
            <Button
              size="small"
              type="text"
              icon={<DownloadOutlined />}
              href={api.downloadUrl(project.project_id, stage, a.path)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Row gutter={[20, 20]}>
        <Col xs={24} xl={13}>
          <Card
            variant="borderless"
            style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
            title={<Space><TableOutlined /><span>阶段产物</span></Space>}
            extra={
              <Space>
                <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
                  刷新
                </Button>
                <Button size="small" icon={<RocketOutlined />} onClick={onOpenPipeline}>
                  回到流水线
                </Button>
              </Space>
            }
          >
            <Tabs
              size="small"
              activeKey={stage}
              onChange={(k) => { setStage(k); setText(''); }}
              items={STAGE_TABS.map((t) => ({ key: t.key, label: t.label }))}
            />
            <Table
              rowKey="path"
              size="small"
              loading={loading}
              columns={columns}
              dataSource={arts}
              pagination={false}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={<Text type="secondary">该阶段还没有产物</Text>}
                  />
                ),
              }}
            />
          </Card>
        </Col>

        <Col xs={24} xl={11}>
          {/* 预览随 tab 联动：看 pcb 产物时显示 PCB，看 schematic 时显示原理图 */}
          <PreviewPanel project={project} refreshKey={stage} height={430} />
        </Col>
      </Row>

      <Card
        variant="borderless"
        style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
        title={<Space><ToolOutlined /><span>手动调整</span></Space>}
        extra={<Button size="small" type="text" onClick={onBack}>返回</Button>}
      >
        <Tabs
          activeKey={editorTab}
          onChange={setEditorTab}
          items={[
            {
              key: 'board',
              label: <Space><CodeOutlined />PCB 编辑器</Space>,
              children: <BoardEditor project={project} />,
            },
            {
              key: 'library',
              label: <Space><FileTextOutlined />器件 / 封装库</Space>,
              children: <LibraryPanel project={project} />,
            },
          ]}
        />
      </Card>

      <Drawer
        title={<Space><Text className="vp-mono" style={{ fontSize: 12 }}>{current}</Text></Space>}
        width={720}
        open={open}
        onClose={() => setOpen(false)}
        extra={
          <Button
            size="small"
            icon={<DownloadOutlined />}
            href={api.downloadUrl(project.project_id, stage, current)}
          >
            下载
          </Button>
        }
      >
        <Paragraph>
          <pre
            className="vp-mono vp-scroll"
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.55,
              background: 'rgba(128,128,128,0.08)',
              padding: 12,
              borderRadius: 8,
              maxHeight: 'calc(100vh - 180px)',
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {text}
          </pre>
        </Paragraph>
      </Drawer>
    </Space>
  );
}
