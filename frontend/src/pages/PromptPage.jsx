import React, { useState } from 'react';
import {
  Alert, App as AntApp, Button, Card, Col, Form, Input, Row, Space, Tag, Typography,
} from 'antd';
import { BulbOutlined, RocketOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { api } from '../api/client.js';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const EXAMPLES = [
  {
    title: 'ESP32 温控器',
    desc: 'DS18B20 测温 + MOSFET 加热 + OLED 显示 + MQTT 上报',
    prompt: '做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT',
  },
  {
    title: 'ESP32 环境监测节点',
    desc: 'DHT22 温湿度 + OLED 显示 + 单总线传感器',
    prompt: '做一个ESP32环境监测节点：DHT22测温湿度，OLED显示，WiFi上报MQTT',
  },
  {
    title: 'ESP32 最小开发板',
    desc: 'USB-C 供电 + AMS1117 转 3.3V + 状态 LED',
    prompt: '做一个ESP32开发板：USB-C供电，AMS1117转3.3V，复位按键，状态指示灯',
  },
];

const STAGES = [
  { name: '需求解析', desc: '把自然语言变成结构化规格' },
  { name: '元器件选型', desc: '匹配内置器件库与封装' },
  { name: '原理图 / 网表', desc: 'skidl 建网表 + 生成可加载的 .kicad_sch' },
  { name: 'PCB 布局布线', desc: 'pcbnew 建板、布线、铺铜、DRC' },
  { name: '固件生成', desc: '按引脚映射产出可编译的 ESP32 固件' },
  { name: 'Gerber 导出', desc: 'kicad-cli 输出可打样文件' },
];

export default function PromptPage({ onCreated, caps }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch (e) {
      return;
    }
    setBusy(true);
    try {
      const p = await api.createProject(values.name || '', values.prompt);
      message.success('项目已创建，开始生成');
      onCreated(p);
    } catch (e) {
      message.error(`创建失败：${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Row gutter={[20, 20]}>
      <Col xs={24} xl={15}>
        <Card variant="borderless" style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}>
          <Space direction="vertical" size={2} style={{ marginBottom: 18 }}>
            <Title level={3} style={{ margin: 0 }}>
              描述你要做的硬件
            </Title>
            <Text type="secondary">
              一句话说明功能与器件，AI 会依次产出规格、选型、原理图、PCB、固件与 Gerber。
            </Text>
          </Space>

          {caps && !caps.deepseek_configured && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="未检测到 DeepSeek API Key"
              description="解析与固件阶段会走降级模式，产物可用但不如真实模型精准。设置 DEEPSEEK_API_KEY 后重启后端即可生效。"
            />
          )}

          <Form form={form} layout="vertical" requiredMark={false} onFinish={submit}>
            <Form.Item
              name="name"
              label="项目名"
              extra="留空则由系统按时间生成"
            >
              <Input placeholder="例如：esp32-温控器" allowClear />
            </Form.Item>

            <Form.Item
              name="prompt"
              label="需求描述"
              rules={[{ required: true, message: '请描述你要做的设备' }]}
            >
              <TextArea
                rows={7}
                showCount
                maxLength={1000}
                placeholder="例如：做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT"
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Space>
                <Button
                  type="primary"
                  size="large"
                  icon={<RocketOutlined />}
                  loading={busy}
                  onClick={submit}
                >
                  开始生成
                </Button>
                <Button size="large" onClick={() => form.resetFields()} disabled={busy}>
                  清空
                </Button>
              </Space>
            </Form.Item>
          </Form>
        </Card>
      </Col>

      <Col xs={24} xl={9}>
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card
            variant="borderless"
            title={<Space><BulbOutlined /><span>示例需求</span></Space>}
            size="small"
            style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {EXAMPLES.map((ex) => (
                <Card
                  key={ex.title}
                  size="small"
                  className="vp-example"
                  onClick={() => form.setFieldsValue({
                    prompt: ex.prompt,
                    name: form.getFieldValue('name') || ex.title.replace(/\s+/g, '-'),
                  })}
                >
                  <Space direction="vertical" size={0} style={{ width: '100%' }}>
                    <Text strong style={{ fontSize: 13 }}>{ex.title}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{ex.desc}</Text>
                  </Space>
                </Card>
              ))}
            </Space>
          </Card>

          <Card
            variant="borderless"
            title={<Space><ThunderboltOutlined /><span>生成流程</span></Space>}
            size="small"
            style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}
          >
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              {STAGES.map((s, i) => (
                <div key={s.name} style={{ display: 'flex', gap: 10 }}>
                  <Tag
                    color="blue"
                    style={{ marginInlineEnd: 0, width: 22, textAlign: 'center', flex: '0 0 auto' }}
                  >
                    {i + 1}
                  </Tag>
                  <div style={{ lineHeight: 1.35 }}>
                    <div style={{ fontSize: 13 }}>{s.name}</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>{s.desc}</Text>
                  </div>
                </div>
              ))}
            </Space>
          </Card>

          <Card size="small" variant="borderless" style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.04)' }}>
            <Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
              产物全部是 KiCad 原生文件（<Text code>.kicad_sch</Text> / <Text code>.kicad_pcb</Text>），
              可以随时用 KiCad 打开继续精修，改完再回到这里预览。
            </Paragraph>
          </Card>
        </Space>
      </Col>
    </Row>
  );
}
