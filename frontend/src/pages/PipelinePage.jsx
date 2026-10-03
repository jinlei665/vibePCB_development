import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, App as AntApp, Button, Card, Col, Progress, Row, Space, Steps, Tag, Tooltip, Typography,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, FileTextOutlined, LoadingOutlined,
  ReloadOutlined, RocketOutlined, SyncOutlined,
} from '@ant-design/icons';
import { api } from '../api/client.js';
import PreviewPanel from '../components/PreviewPanel.jsx';

const { Text, Paragraph } = Typography;

const STAGES = ['parse', 'components', 'schematic', 'pcb', 'gerber', 'firmware'];
const LABELS = {
  parse: '需求解析',
  components: '元器件选型',
  schematic: '原理图 / 网表',
  pcb: 'PCB 布局布线',
  gerber: 'Gerber 导出',
  firmware: '固件生成',
};
const HINTS = {
  parse: '自然语言 → 结构化规格',
  components: '匹配器件库与封装',
  schematic: 'skidl 网表 + .kicad_sch',
  pcb: 'pcbnew 建板布线',
  gerber: 'kicad-cli 出生产文件',
  firmware: '按引脚映射生成固件',
};
// 流水线真实执行顺序（firmware 在 gerber 之后），Steps 按这个顺序展示更贴近实际
const ORDER = ['parse', 'components', 'schematic', 'pcb', 'firmware', 'gerber'];
const POLL_MS = 1000;
const MAX_POLLS = 900; // 15 分钟上限，防止后台线程异常时无限轮询

function statusOf(st) {
  if (!st) return 'pending';
  return st.status || 'pending';
}

export default function PipelinePage({ project, onDone, onBack, onOpenArtifacts }) {
  const { message } = AntApp.useApp();
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
        if (d.overall === 'done') {
          message.success('全部阶段已完成');
          onDone(d);
        } else {
          message.error('流水线执行失败，请查看阶段详情');
        }
      } else if (polls.current >= MAX_POLLS) {
        stopPolling();
        setRunning(false);
        setErr(`超过 ${Math.round(MAX_POLLS * POLL_MS / 60000)} 分钟仍未结束，已停止轮询`);
      }
    }, POLL_MS);
  };

  // 手动刷一次状态（不进入轮询）：只在用户点按钮时打一次后端，
  // 不会像定时刷新那样每秒重拉一次预览 SVG。
  const refreshOnce = async () => {
    try {
      setDetail(await api.getProject(project.project_id));
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  const run = async () => {
    setRunning(true); setErr('');
    // 关键（质检 D1）：先起轮询，再触发后台流水线。原实现是 await 同步长请求、
    // 跑完才开始轮询，导致进度条全程不动、结束时一次性全变 done。
    startPolling();
    try {
      await api.runPipelineBackground(project.project_id);
    } catch (e) {
      // 启动失败（例如 409 PROJECT_BUSY）：保留轮询以观察正在进行的进度
      setErr(String(e.message || e));
    }
  };

  const stages = detail.stages || {};
  // 各阶段状态的指纹：任一阶段从 pending→running→done 变化都会让预览自动重渲染
  const stageSig = useMemo(
    () => STAGES.map((s) => `${s}:${statusOf(stages[s])}`).join('|'),
    [stages],
  );

  const doneCount = ORDER.filter((s) => statusOf(stages[s]) === 'done').length;
  const runningStage = ORDER.find((s) => statusOf(stages[s]) === 'running');
  const failedStage = ORDER.find((s) => statusOf(stages[s]) === 'failed');
  const currentIndex = runningStage
    ? ORDER.indexOf(runningStage)
    : Math.min(doneCount, ORDER.length - 1);

  const items = ORDER.map((s) => {
    const st = stages[s] || {};
    const status = statusOf(st);
    return {
      title: (
        <Space size={8}>
          <span>{LABELS[s]}</span>
          {status === 'done' && <Tag color="success" style={{ marginInlineEnd: 0 }}>done</Tag>}
          {status === 'running' && <Tag color="processing" style={{ marginInlineEnd: 0 }}>running</Tag>}
          {status === 'failed' && <Tag color="error" style={{ marginInlineEnd: 0 }}>failed</Tag>}
          {st.degraded && (
            <Tooltip title="该阶段使用了降级实现，产物可用但精度受限">
              <Tag color="warning" style={{ marginInlineEnd: 0 }}>degraded</Tag>
            </Tooltip>
          )}
        </Space>
      ),
      icon: status === 'failed' ? <CloseCircleOutlined />
        : status === 'done' ? <CheckCircleOutlined />
          : status === 'running' ? <LoadingOutlined /> : undefined,
      status: status === 'done' ? 'finish' : status === 'failed' ? 'error'
        : status === 'running' ? 'process' : 'wait',
      description: (
        <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
          <Text type="secondary">{HINTS[s]}</Text>
          {st.engine && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              engine: <Text code style={{ fontSize: 11 }}>{st.engine}</Text>
            </Text>
          )}
          {st.error && <Text type="danger" style={{ fontSize: 12 }}>{st.error}</Text>}
        </Space>
      ),
    };
  });

  return (
    <Row gutter={[20, 20]}>
      <Col xs={24} xl={10}>
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card
            variant="borderless"
            style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
            title={
              <Space>
                <RocketOutlined />
                <span>一键生成</span>
                <Tag
                  color={detail.overall === 'done' ? 'success' : detail.overall === 'failed' ? 'error' : 'default'}
                  style={{ marginInlineEnd: 0 }}
                >
                  {detail.overall || 'created'}
                </Tag>
              </Space>
            }
            extra={<Text type="secondary" style={{ fontSize: 11 }}>{detail.project_id}</Text>}
          >
            <Paragraph
              type="secondary"
              ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
              style={{ marginBottom: 14, fontSize: 12 }}
            >
              {detail.prompt}
            </Paragraph>

            <Progress
              percent={Math.round((doneCount / ORDER.length) * 100)}
              status={failedStage ? 'exception' : runningStage ? 'active' : 'normal'}
              strokeColor={failedStage ? undefined : { from: '#1677ff', to: '#13c2c2' }}
              size="small"
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {doneCount} / {ORDER.length} 阶段完成
              {runningStage ? ` · 正在执行「${LABELS[runningStage]}」` : ''}
              {running ? ' · 轮询中' : ''}
            </Text>

            <div style={{ marginTop: 14 }}>
              <Space wrap>
                <Button
                  type="primary"
                  icon={running ? <SyncOutlined spin /> : <RocketOutlined />}
                  loading={running}
                  onClick={run}
                  disabled={running}
                >
                  {running ? '生成中…' : detail.overall === 'done' ? '重新生成' : '开始生成'}
                </Button>
                <Button icon={<ReloadOutlined />} onClick={refreshOnce} disabled={running}>
                  刷新状态
                </Button>
                {detail.overall !== 'created' && (
                  <Button icon={<FileTextOutlined />} onClick={onOpenArtifacts}>
                    查看产物
                  </Button>
                )}
                <Button type="text" onClick={onBack}>返回</Button>
              </Space>
            </div>

            {err && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 14 }}
                message={err}
              />
            )}
          </Card>

          <Card
            variant="borderless"
            title="阶段进度"
            style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
          >
            <Steps
              direction="vertical"
              size="small"
              current={currentIndex}
              status={failedStage ? 'error' : runningStage ? 'process' : 'finish'}
              items={items}
            />
          </Card>
        </Space>
      </Col>

      <Col xs={24} xl={14}>
        {/* 实时预览：refreshKey 由各阶段状态拼成，任何阶段状态一变就自动重渲染，
            于是「生成过程中」就能逐步看到原理图与 PCB 成形 */}
        <PreviewPanel project={detail} refreshKey={stageSig} height={620} />
      </Col>
    </Row>
  );
}
