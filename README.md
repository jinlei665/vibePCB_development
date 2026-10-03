# VibePCB

自然语言 → 需求解析 → 原理图/网表 → PCB 布局布线 → ESP32 固件 → Gerber 制造文件，一键生成的桌面应用 MVP。

- **后端**：Python FastAPI（127.0.0.1:8710），六阶段流水线，skidl + kiutils 生成 KiCad 格式产物
- **前端**：React + Electron 桌面壳（输入 → 1 秒轮询进度 → 产物查看/下载）
- **AI**：DeepSeek（可选；未配置自动降级规则引擎）

## 当前状态（本机实测）

> 2026-10-03 于 Windows + Python 3.11.5 完成端到端验证。

| 项目 | 状态 |
|-|-|
| 六阶段流水线（无 KiCad、无 API Key 的降级路径） | ✅ `overall=done`，约 2–3 秒跑完 |
| 回归脚本 `scripts/verify_fixes.py` | ✅ 29/29 通过（退出码 0） |
| MVP 五步验收 `scripts/verify_mvp.py` | ✅ 40/40 通过（退出码 0） |
| 中文需求端到端编码 | ✅ UTF-8 无损（`prompt.txt` 与 spec 逐字一致，关键词命中正常） |
| DeepSeek 真实 AI 链路 | ✅ parse / components / firmware 均实测 `engine=deepseek`、`degraded=false` |
| KiCad 真实 PCB 引擎（pcbnew） | ✅ 实测 `engine=pcbnew`、`degraded=false`（20 器件、112 走线、66 过孔、DRC 零错误） |
| KiCad 真实 Gerber（kicad-cli） | ✅ 实测 7 层 `.gbr`（含 Edge.Cuts）+ `.drl` + `.gbrjob` |

### 已修复的关键缺陷

| 编号 | 问题 | 影响 |
|-|-|-|
| **D8** | skidl 在多盘符 Windows 下把 `script_dir` 解析到**基础解释器**所在盘（本机 `D:\Anaconda`），随后 `os.path.relpath(源文件在 F:, script_dir 在 D:)` 抛 `ValueError: path is on mount 'F:', start on mount 'D:'` | **schematic 阶段直接 500，整条流水线走不下去** |
| D1 | 前端先 `await` 同步的 `/pipeline` 长请求、等跑完才开始轮询 | 进度条全程不动，结束时一次性全变 done |
| D2 | `in/spec.json` / `in/bom.json` 只写盘不登记，且 artifacts 路由把 parse/components 的 kind 过滤成空集 | 前两步产物在前端既看不到也下不了 |
| D3 | `pcb.py` 真实引擎硬编码 `python3`，而 Windows 上该名字常是 Microsoft Store 的 0 字节别名占位 | 装了 KiCad 也永远静默回落模拟引擎 |
| D4 | 真实引擎只调 kinet2pcb 做「网表→摆放」，返回的 segments/vias 是 0 占位 | 真实引擎下产出无走线的裸板 |
| D5 | Electron 壳 spawn 系统 `python`（本机指向 Anaconda，没有 fastapi/skidl），与 `start.ps1` 建的 `.venv` 不一致 | 单独跑 `npm run electron:dev` 后端起不来；`start.ps1` 会起两个后端抢 8710 |
| D6 | `vite.config.js` 缺 `base: './'`；`package.json` 无 electron-builder 配置 | Electron 以 `file://` 加载 dist 时资源 404 → 白屏 |
| **D10** | `gerber.py` 把 `-o` 当文件名模板传 `%f-%i.gbr`，而 KiCad 10 的 `-o` 是**目录** → 建了个同名目录，`glob("*.gbr")` 又恰好把它匹配上 | **「报告成功却零 Gerber」，静默空结果，直接打样会出事** |
| D11 | `basic_drc` 用 kiutils 回读板文件，而 kiutils 1.4.8 无法解析 KiCad 10 的板格式（`Net.from_sexpr` 对 `(net <code>)` 抛 `IndexError`） | 真实引擎下 pcb 阶段 500（已按引擎选择回读方式并兜底） |
| D12 | `requirements.txt` 含 UTF-8 中文注释；Windows 上 locale 非 UTF-8（本机 GBK）的 Python 跑 `pip install -r` 报 `UnicodeDecodeError` | README 里的安装命令在 stock Windows 上是坏的 |
| D13 | `vite.config.js` 没有 `/api` 开发代理，而 `client.js` 默认用同源相对路径 | `npm run dev` + 浏览器时请求打到 Vite 自己身上并 404，浏览器工作流实际不可用（现已加代理） |

## CAD 化路线图（进行中）

目标：让 VibePCB 具备「实时看见 + 手动调整」的 CAD 式体验。定位是**双轨**——本应用负责
AI 生成 + 实时预览 + 轻量编辑，重度编辑一键交给 KiCad（`pcbnew` / `eeschema`）。

| 阶段 | 内容 | 状态 |
|-|-|-|
| 1 | 实时预览：kicad-cli 渲染原理图/PCB 为 SVG，随阶段推进自动刷新；一键在 KiCad 中打开精修 | ✅ 已完成 |
| 2 | 原理图真实连线：梳形总线布线（引脚→短桩→通道 lane→总线），实测 162 wire / 65 junction；**连接关系与 skidl 权威网表逐引脚一致**（kicad-cli 导出比对） | ✅ 已完成 |
| 3 | 交互式 PCB 编辑：Canvas 叠加层拖拽器件/走线、平移与删除过孔、两点画线、栅格吸附，批量写回 `.kicad_pcb` | ✅ 已完成 |
| 4 | 器件/封装库浏览与编辑：15 个器件 + 9 个封装库/14 个封装快照；换封装时**按焊盘编号搬运网络**，不丢连接 | ✅ 已完成 |

设计约束（已定）：

- 渲染走 **kicad-cli 出底图 + Canvas 叠加可拖拽图层** 的混合方案；
- 所有编辑必须**写回 KiCad 原生文件**（`.kicad_pcb` / `.kicad_sch`），不引入私有格式；
- 每个阶段都要有回归护栏（见 `scripts/verify_mvp.py` 的 ⑥）；
- 预览端点：`GET /api/projects/{id}/render/{kind}`（kind = `pcb` / `schematic`），
  `POST /api/projects/{id}/open/{tool}`（仅限本机，否则 403）；
- 板编辑端点：`GET /api/projects/{id}/board`、`POST .../board/edits`、`POST .../board/revert`
  （整批原子：先全部校验再落盘；写盘前留 `.board_backup.kicad_pcb`）；
- 库端点：`GET /api/library`、`GET /api/library/footprints`。

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

**推荐：后端用脚本启动。** 它会设置 `PYTHONUTF8` / `PYTHONUNBUFFERED`（中文日志不再乱码、
也不会被缓冲吞掉），并在端口已被占用时复用已有实例而不是抢端口：

```powershell
# 若提示"禁止运行脚本"，先在本窗口放开：
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-backend.ps1
```

就绪判据：终端出现 `Uvicorn running on http://127.0.0.1:8710`。

前端二选一：

```powershell
cd frontend

# A) 浏览器开发（免 Electron，最快）。vite 已把 /api 代理到 127.0.0.1:8710
npm run dev            # 然后打开 http://localhost:5173

# B) Electron 桌面壳（首次会下载约 100MB 的 Electron 二进制）
npm run electron:dev
```

> `npm run dev` 依赖 `vite.config.js` 里的 `/api` 开发代理；没有它，浏览器会把
> `/api/...` 打到 Vite 自己身上并 404。

一键启动（后端 + Electron 壳）：

```powershell
.\scripts\start.ps1
```

打开应用后：输入需求（如"做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT"）→ 点"开始生成" → 观察六阶段进度 → 查看/下载产物。

> 仓库里的 `.ps1` 脚本与 `requirements.txt` 一律**只用 ASCII**：Windows PowerShell 5.1
> 在无 BOM 时按 ANSI 代码页读取 `.ps1`，pip 也可能用系统 locale 读取 requirements，
> 非 ASCII 字节会导致脚本解析失败或 `UnicodeDecodeError`（见 D12）。中文注释放在
> `.md` 文档里。

### 启动排障

| 现象 | 原因与处理 |
|-|-|
| `Electron failed to install correctly` | Electron 二进制没下完（`node_modules/electron` 里缺 `path.txt`/`dist`）。重跑 `node node_modules\electron\install.js`。GitHub 可能极慢（本机实测 0 B/s），先设国内镜像再重试：`$env:ELECTRON_MIRROR='https://npmmirror.com/mirrors/electron/'`（实测 9.8 MB/s，14 秒装完） |
| Electron 报 `Cannot read properties of undefined (reading 'whenReady')` | 环境里被设了 `ELECTRON_RUN_AS_NODE=1`，Electron 会退化为纯 Node，`require('electron')` 拿到的只是 npm 包导出的路径字符串（于是 `app` 为 undefined）。执行 `Remove-Item Env:ELECTRON_RUN_AS_NODE` 后重试 |
| 后端命令"没有任何输出" | 多是控制台编码/缓冲导致的假象。用 `.\scripts\start-backend.ps1`，它设置了 `PYTHONUTF8` / `PYTHONUNBUFFERED` / `PYTHONIOENCODING` |
| 浏览器打开 5173 但接口 404 | 确认后端在 8710；`vite.config.js` 的 `/api` 代理负责转发（见 D13） |
| `禁止运行脚本` / `UnauthorizedAccess` | 执行策略受限，先 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force` |

## Web 在线部署模式（免 Electron）

前端 API 基址**可配置**，默认同源相对路径——这意味着可以脱离 Electron 桌面壳，把前端构建产物当普通静态站点部署，与后端同域（或经反向代理同源）即可在线使用。

### 前端 API 基址的三种配置方式

| 方式 | 写法 | 适用 |
|-|-|-|
| 同源相对路径（默认） | 不做任何配置，`npm run build` | Web 在线部署：前后端同域/反代 |
| 构建参数注入 | `VITE_API_BASE=http://host:8710 npx vite build`，或 `npm run build:desktop`（读 `frontend/.env.desktop`） | Electron 桌面壳（file:// 加载，必须绝对地址）、前后端分域 |
| 运行时注入 | 在 `index.html` 加 `<script>window.__VIBEPCB_API_BASE__='http://host:8710'</script>`，或由 Electron preload 自动注入 | 同一份静态产物指向不同后端（**优先级最高**，高于构建期参数） |

### 在线部署步骤（同源反代示例，nginx）

```bash
# 1. 构建前端（同源模式，产物在 frontend/dist/）
cd frontend && npm run build

# 2. 启动后端（0.0.0.0 才能被反代/外网访问；密钥走环境变量）
DEEPSEEK_API_KEY=sk-xxxx VIBEPCB_API_TOKEN=<随机长token> \
  ../.venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8710 --app-dir backend

# 3. nginx 把 / 走静态产物、/api 转发后端（关键：同源，前端用相对路径即可）
```

```nginx
server {
  listen 80;
  root /path/to/vibepcb/frontend/dist;
  location / { try_files $uri /index.html; }
  location /api/ {
    # 推荐姿势：token 在反代层注入，浏览器端零配置
    proxy_set_header X-API-Token <与后端一致的token>;
    proxy_pass http://127.0.0.1:8710;
  }
}
```

### 公网部署安全配置（重要）

| 环境变量 | 作用 | 说明 |
|-|-|-|
| `VIBEPCB_API_TOKEN` | API 鉴权 | 非空时所有 `/api` 路由（`/api/health` 除外）要求 `Authorization: Bearer <token>` 或 `X-API-Token: <token>` 头；不设置则为本机模式（Electron/本地开发不受影响）。**公网部署必须设置**，否则任何人可无凭据创建项目烧你的 DeepSeek 配额 |
| `VIBEPCB_CORS_ORIGINS` | CORS 白名单 | 逗号分隔 origin 列表。默认 `http://localhost:5173,http://127.0.0.1:5173,null`（本机 vite dev + Electron file://）；同源反代部署天然无跨域无需改；分域部署时显式配前端 origin |

浏览器直连后端（分域）且后端启用了 token 时，在前端页面控制台执行一次
`localStorage.setItem('vibepcb_token','<token>')` 后刷新即可（token 保存在浏览器本地）。
推荐仍是同源反代 + 反代层注入 `X-API-Token`，浏览器端零配置。

后端 CORS 已按上述环境变量收敛（不再通配 `*`）；分域直连（`VITE_API_BASE` 指向后端地址）在配置好 CORS 后同样可用。

## KiCad 真实引擎（可选，推荐）

不装 KiCad 也能跑完整流程（PCB 走内置模拟引擎 + 自研 RS-274X Gerber 写入器）。
装上 KiCad 10 后，两个阶段会切到真实链路：

| 阶段 | 真实引擎 | 产物 |
|-|-|-|
| `pcb` | `pcbnew` | pcbnew 原生 API：`FootprintLoad` 摆放 + 曼哈顿自动布线 + `SaveBoard` |
| `gerber` | `kicad-cli` | 7 层 Gerber（F/B Cu、F/B Mask、F/B SilkS、Edge.Cuts）+ Excellon 钻孔 + `.gbrjob` |

### 关键：venv 必须用 KiCad 自带的 Python 创建

`pcbnew` 是 KiCad 自带的 CPython 扩展，不在 PyPI 上。**仅仅让 Python 小版本相同是不够的
——MSVC 工具链也必须一致。** 本机实测：系统 Python 是 Anaconda 的 `MSC v.1916`，KiCad 自带
Python 是 `MSC v.1944`，两者都是 3.11.5，但用 Anaconda 建的 venv 里 `import pcbnew` 报：

```
ImportError: DLL load failed while importing _pcbnew: 动态链接库(DLL)初始化例程失败。
```

所以请这样建 venv：

```powershell
# 1. 安装 KiCad 10.0.x
#    官方安装包（推荐，浏览器/下载工具可断点续传）：
#    https://downloads.kicad.org/kicad/windows/explore/stable
winget install --id KiCad.KiCad -e

# 2. 用 KiCad 自带的 Python 建 venv（不要用系统 python）
Remove-Item -Recurse -Force .venv
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. 写路径钩子（pcbnew 模块目录 + DLL 目录）并自检
#    装在非默认位置时用 --root 指定，例如本机是 F:\_kicad_dl\KiCad\10.0
.\.venv\Scripts\python.exe scripts\setup_kicad_path.py

# 4. 自检
curl http://127.0.0.1:8710/api/capabilities
```

判据：`pcb_engine_selected` 为 `"pcbnew"`、`pcbnew_available` 与 `kicad_cli_available`
均为 `true`；pcb 阶段 `engine == "pcbnew"` 且 `degraded == false`。

`setup_kicad_path.py` 会比对 MSVC 工具链，不一致时直接给出重建 venv 的命令。由于 venv 基于
KiCad 的 Python，`sys.base_prefix` 就是 KiCad 的 `bin`，因此
`backend/app/core/engines.py` 能自动定位 `kicad-cli`，**无需改系统 PATH**。

### 关于 kinet2pcb

早期实现用 kinet2pcb 做「网表→板」，但它 1.1.4 的 Windows 发现逻辑写死了

```python
for kicad_version in ("9.0", "8.0", "7.0", "6.0", "5.0"):
    ki_pth = os.path.join("C:\\Program Files\\KiCad", kicad_version)
```

既固定安装路径、又完全不认识 KiCad 10 → `import kinet2pcb` 必然抛
"Could not find KiCad installation to import pcbnew module"。本仓库因此改为**直接用
pcbnew 原生 API 建板**（`backend/app/services/pcb.py::_run_pcbnew`），不再依赖它；
`requirements.txt` 仍保留 kinet2pcb，以免破坏 skidl 声明的依赖关系。

> **多盘符提示**：若 `.venv` 与其基础 Python 不在同一盘符，skidl 会把 `script_dir`
> 解析到基础解释器所在盘并触发跨盘符 `relpath` 异常。本仓库已在
> `backend/app/services/schematic.py` 用 skidl 官方的 `track_abs_path=True` 规避
> （见上文 D8），无需额外处理。

> **多盘符提示**：若 `.venv` 与其基础 Python 不在同一盘符，skidl 会把 `script_dir`
> 解析到基础解释器所在盘并触发跨盘符 `relpath` 异常。本仓库已在
> `backend/app/services/schematic.py` 用 skidl 官方的 `track_abs_path=True` 规避
> （见上文 D8），无需额外处理。

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
POST /api/projects/{id}/pipeline                    一键 {"stages": ["all"]}（同步，返回最终全景 + pipeline_results）
POST /api/projects/{id}/pipeline?background=1       同上，但立即返回 202，进度靠轮询（前端使用此模式）
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
- skidl 会在**进程 CWD** 写 side-effect 文件（`*.erc` / `*.log` / `*_sklib.py`）。
  常驻服务里这些文件名取自 skidl 对「最外层脚本」的误判（本机为 `threading`），
  属纯噪音，不影响任何产物；仓库已在 `.gitignore` 忽略这些模式。根治需要上游修复
  `skidl/scriptinfo.py` 的栈遍历（循环缺少 `break`，见 D8）
- **KiCad 10 的 `PCB_VIA::GetWidth()` 不带图层参数会触发 C++ assert 并直接 abort 整个
  Python 进程**（`pcb_track.cpp:387`），Python 侧 try/except **抓不到**。读写板文件时
  必须用 `GetFrontWidth()` / `GetDrillValue()`。同理过孔宽度不要直接 `SetWidth`，
  走「删除 + 新增」。见 `backend/app/services/board_edit.py`
- KiCad 的 `.kicad_sch` 解析器不接受 `lib_symbols` 内 pin 上的 `(uuid ...)`（见 D14）

## License

MIT
