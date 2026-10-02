# VibePCB

自然语言 → 需求解析 → 原理图/网表 → PCB 布局布线 → ESP32 固件 → Gerber 制造文件，一键生成的桌面应用 MVP。

- **后端**：Python FastAPI（127.0.0.1:8710），六阶段流水线，skidl + kiutils 生成 KiCad 9 格式产物
- **前端**：React + Electron 桌面壳（输入 → 1 秒轮询进度 → 产物查看/下载）
- **AI**：DeepSeek（可选；未配置自动降级规则引擎）

## 快速开始

### 1. 复制文件

```bash
git clone https://github.com/jinlei665/vibePCB_development.git
cd vibePCB_development
```

### 2. 装依赖

后端（Python ≥ 3.10）：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt
```

前端（Node ≥ 18）：

```bash
cd frontend
npm install
```

### 3. 设环境变量

```bash
export DEEPSEEK_API_KEY=sk-xxxx        # 不设则自动降级规则引擎（见下）
# export VIBEPCB_PCB_ENGINE=auto       # auto | pcbnew | simulated，默认 auto
# export VIBEPCB_PORT=8710
```

参考 `.env.example`。**密钥只从环境变量读取，禁止写进任何文件。**

### 4. 启动

一键启动（推荐）：

```bash
scripts/start.sh          # Windows: scripts\start.ps1
```

或分开启动：

```bash
# 后端
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8710 --app-dir backend

# 前端（开发模式，另开终端）
cd frontend && npm run electron:dev
```

打开应用后：输入需求（如"做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT"）→ 点"开始生成" → 观察六阶段进度 → 查看/下载产物。

## 降级模式说明

| 环境 | 行为 | 响应标记 |
|-|-|-|
| 未设 `DEEPSEEK_API_KEY` | parse/components/firmware 走规则引擎与模板拼装，产物仍完整 | `degraded: true` |
| 未装 KiCad | PCB 走 kiutils 模拟引擎（内置封装快照+分区布局+曼哈顿布线）；Gerber 走自研 RS-274X 写入器 | `degraded: true` |
| 强制 `VIBEPCB_PCB_ENGINE=simulated` | 同上模拟引擎，但视为用户显式选择 | `degraded: false` |
| 装有 KiCad | PCB 走 kinet2pcb（pcbnew）真实引擎；Gerber 走 kicad-cli 导出；真实引擎失败自动回落模拟 | `degraded: false` |

各阶段响应均带 `engine` 与 `degraded` 字段，前端据此显示徽标。

## 流水线六阶段

```
parse → components → schematic → pcb → gerber
                              └→ firmware（依赖 parse+components，不依赖 pcb）
```

- `parse`：自然语言 → RequirementSpec（DeepSeek / 规则引擎）
- `components`：选型 → BOM（DeepSeek 提议 + footprint_map.json 校正）
- `schematic`：skidl 建电路 → ERC → KiCad 网表 + .kicad_sch 骨架
- `pcb`：网表 → .kicad_pcb（布局+曼哈顿布线+基础 DRC）
- `firmware`：Arduino main.ino（DeepSeek / 模板拼装）+ 静态自检
- `gerber`：RS-274X Gerber（F.Cu/B.Cu/Edge.Cuts）+ Excellon 钻孔 → zip

## REST API（摘要）

```
GET  /api/health                                    健康检查
GET  /api/capabilities                              引擎探测结果
POST /api/projects                                  创建项目 {"name", "prompt"}
GET  /api/projects/{id}                             状态全景（前端 1 秒轮询）
POST /api/projects/{id}/{stage}                     单阶段执行
POST /api/projects/{id}/pipeline                    一键 {"stages": ["all"]}
GET  /api/projects/{id}/artifacts/{stage}           产物清单
GET  .../artifacts/{stage}?path=...                 文本预览
GET  .../artifacts/{stage}?path=...&download=1      附件下载
```

## 产物目录（运行时生成，不在仓库内）

```
~/.vibepcb/projects/{project_id}/
├── project.json          # 状态机（前端轮询的就是它）
├── in/                   # prompt.txt / spec.json / bom.json
├── out/                  # project.net / project.kicad_sch / project.kicad_pcb
├── firmware/main/        # main.ino + README
└── gerber/               # *.gbr / *.drl / gerbers.zip
```

## 版本锁定与已知偏差

- skidl 2.2.1 / kiutils 1.4.8（按架构文档 6.4）
- kinet2pcb **1.1.4**（文档 6.4 写 1.1.3，但 skidl 2.2.1 依赖 kinet2pcb>=1.1.4，无法共装 1.1.3）
- 布线为 MVP 级确定性正交布线（曼哈顿），非商用自动布线；产出可在 KiCad 中打开精修

## License

MIT
