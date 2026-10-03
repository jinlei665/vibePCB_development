import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // 相对基址：Electron 用 file:// 加载 dist/index.html 时必须，否则资源
  // 会解析成 file:///assets/... 导致白屏；同源 Web 部署下同样可用。
  base: './',
  server: { port: 5173 },
});
