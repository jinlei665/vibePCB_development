import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, App as AntApp, Button, Card, Col, Divider, Empty, Form, Input, Row, Select,
  Space, Spin, Table, Tabs, Tag, Typography,
} from 'antd';
import { AppstoreOutlined, ReloadOutlined, SwapOutlined } from '@ant-design/icons';
import { api } from '../api/client.js';

const { Text, Paragraph } = Typography;

// 器件 / 封装库浏览与编辑（CAD 化增量 4）
//
// 数据源是 footprint_map.json 的 parts + 内置 .pretty 快照 —— 也就是**选型阶段真正
// 会用到的那份清单**，所以这里看到的器件/封装都是能真正生成出来的。
// 换封装走 /board/edits 的 set_footprint，后端会按焊盘编号把网络搬过去。
export default function LibraryPanel({ project }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm();
  const [lib, setLib] = useState(null);
  const [board, setBoard] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [ref, setRef] = useState('');
  const [loadingBoard, setLoadingBoard] = useState(true);

  const loadBoard = useCallback(async () => {
    if (!project) { setLoadingBoard(false); return; }
    setLoadingBoard(true);
    try {
      const b = await api.board(project.project_id);
      setBoard(b);
      if (b.footprints.length) setRef((r) => r || b.footprints[0].ref);
    } catch (e) {
      setBoard(null);   // 还没生成到 PCB 阶段是正常的，不算错误
    } finally {
      setLoadingBoard(false);
    }
  }, [project]);

  const load = useCallback(async () => {
    setErr('');
    try {
      setLib(await api.library());
    } catch (e) {
      setErr(String(e.message || e));
    }
    await loadBoard();
  }, [loadBoard]);

  useEffect(() => { load(); }, [load]);

  const sel = board ? board.footprints.find((f) => f.ref === ref) : null;

  useEffect(() => {
    if (sel) form.setFieldsValue({ fpid: sel.fpid, value: sel.value });
  }, [sel, form]);

  const apply = async () => {
    const v = form.getFieldsValue();
    const edits = [];
    if (v.fpid && sel && v.fpid !== sel.fpid) edits.push({ op: 'set_footprint', ref, footprint: v.fpid });
    if (v.value != null && sel && v.value !== sel.value) edits.push({ op: 'set_value', ref, value: v.value });
    if (!edits.length) { message.info('没有变化需要提交'); return; }
    setBusy(true); setErr('');
    try {
      const r = await api.boardEdits(project.project_id, edits);
      setBoard(r.board);
      message.success(`已应用 ${r.applied} 项修改并写回 .kicad_pcb`);
    } catch (e) {
      setErr(String(e.message || e));
      message.error(`应用失败：${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const revert = async () => {
    setBusy(true); setErr('');
    try {
      const r = await api.boardRevert(project.project_id);
      setBoard(r.board);
      message.success('已恢复到上次编辑前');
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  if (!lib) {
    return (
      <Space direction="vertical" align="center" style={{ width: '100%', padding: 40 }}>
        {err ? <Alert type="error" showIcon message={err} /> : <Spin />}
        <Text type="secondary" style={{ fontSize: 12 }}>正在加载器件库…</Text>
      </Space>
    );
  }

  const partColumns = [
    {
      title: '器件',
      dataIndex: 'key',
      width: 168,
      render: (v) => <Text strong style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '符号',
      dataIndex: 'symbol',
      render: (v) => <Text type="secondary" className="vp-mono" style={{ fontSize: 11 }}>{v}</Text>,
    },
    {
      title: '默认封装',
      dataIndex: 'footprint',
      render: (v) => <Text type="secondary" className="vp-mono" style={{ fontSize: 11 }}>{v}</Text>,
    },
    {
      title: '引脚',
      dataIndex: 'pin_count',
      width: 60,
      align: 'right',
      render: (v) => <Tag style={{ marginInlineEnd: 0 }}>{v}</Tag>,
    },
  ];

  return (
    <div>
      <Space size={8} wrap style={{ marginBottom: 10 }}>
        <Tag icon={<AppstoreOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>
          {lib.parts.length} 个器件
        </Tag>
        <Tag color="cyan" style={{ marginInlineEnd: 0 }}>{lib.libs.length} 个封装库</Tag>
        <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>{lib.footprint_ids.length} 个封装快照</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>这是选型阶段真正可用的清单</Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>

      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 10 }} />}

      <Tabs
        size="small"
        items={[
          {
            key: 'parts',
            label: '器件目录',
            children: (
              <Table
                rowKey="key"
                size="small"
                columns={partColumns}
                dataSource={lib.parts}
                pagination={false}
                scroll={{ y: 300 }}
                expandable={{
                  expandedRowRender: (r) => (
                    <Space direction="vertical" size={6} style={{ fontSize: 12 }}>
                      <Text type="secondary">{r.description || '（无描述）'}</Text>
                      <Space size={4} wrap>
                        {r.pins.map((p) => (
                          <Tag key={`${p.num}-${p.name}`} className="vp-mono" style={{ fontSize: 11 }}>
                            {p.num}:{p.name || '-'}
                          </Tag>
                        ))}
                      </Space>
                    </Space>
                  ),
                }}
              />
            ),
          },
          {
            key: 'libs',
            label: '封装快照库',
            children: (
              <Row gutter={[10, 10]}>
                {lib.libs.map((l) => (
                  <Col xs={24} md={12} key={l.lib}>
                    <Card size="small" styles={{ body: { padding: 10 } }}>
                      <Text strong className="vp-mono" style={{ fontSize: 12 }}>{l.lib}</Text>
                      <Tag style={{ marginInlineStart: 8 }}>{l.count}</Tag>
                      <div style={{ marginTop: 6 }}>
                        <Space size={4} wrap>
                          {l.footprints.map((f) => (
                            <Tag key={f} className="vp-mono" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                              {f}
                            </Tag>
                          ))}
                        </Space>
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
        ]}
      />

      <Divider style={{ margin: '14px 0 10px' }} orientation="left" plain>
        <Space size={6}><SwapOutlined /><Text style={{ fontSize: 12 }}>换封装 / 改值</Text></Space>
      </Divider>

      {loadingBoard ? (
        <Space><Spin size="small" /><Text type="secondary" style={{ fontSize: 12 }}>读取板文件…</Text></Space>
      ) : !board ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Text type="secondary" style={{ fontSize: 12 }}>还没有可编辑的 PCB（先跑到 pcb 阶段）</Text>}
        />
      ) : (
        <Form form={form} layout="inline" onFinish={apply}>
          {/* 器件选择由组件状态控制（不是表单字段），只有封装/值走 Form */}
          <Form.Item label="器件">
            <Select
              style={{ width: 190 }}
              value={ref}
              onChange={setRef}
              options={board.footprints.map((f) => ({
                value: f.ref,
                label: `${f.ref}（${f.value}）`,
              }))}
            />
          </Form.Item>
          <Form.Item label="目标封装" name="fpid" style={{ minWidth: 340 }}>
            <Select
              showSearch
              style={{ width: 340 }}
              options={lib.footprint_ids.map((i) => ({ value: i, label: i }))}
            />
          </Form.Item>
          <Form.Item label="值" name="value">
            <Input style={{ width: 120 }} placeholder="如 10k" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={busy}>应用并写回</Button>
              <Button onClick={revert} disabled={busy}>撤销全部编辑</Button>
            </Space>
          </Form.Item>
          {sel && (
            <div style={{ width: '100%', marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前：<Text code style={{ fontSize: 12 }}>{sel.fpid}</Text> · 值 {sel.value} ·
                焊盘 {sel.pads.length} 个
              </Text>
            </div>
          )}
        </Form>
      )}

      <div style={{ marginTop: 8 }}>
        <Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
          换封装时会按**焊盘编号**把原网络搬到新封装上，所以连接关系不会丢。
        </Paragraph>
      </div>
    </div>
  );
}
