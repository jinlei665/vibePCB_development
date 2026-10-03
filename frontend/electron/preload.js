// 预加载：把主进程解析出的后端地址注入渲染进程。
// client.js 会优先读取 window.__VIBEPCB_API_BASE__，因此改 VIBEPCB_PORT 后
// 无需重新构建前端（此前端口被 .env.desktop 构建期写死为 8710）。
const { contextBridge } = require('electron');

const port = Number(process.env.VIBEPCB_PORT || 8710);
contextBridge.exposeInMainWorld('__VIBEPCB_API_BASE__', `http://127.0.0.1:${port}`);
contextBridge.exposeInMainWorld('vibepcb', { version: '0.1.0', port });
