import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // 相对基址：Electron 用 file:// 加载 dist/index.html 时必须，否则资源
  // 会解析成 file:///assets/... 导致白屏；同源 Web 部署下同样可用。
  base: './',
  server: {
    port: 5173,
    // 开发代理：client.js 默认走同源相对路径（/api/...），没有这条代理时
    // 浏览器直接开 http://localhost:5173 会让请求打到 Vite 自己身上并 404。
    // 有了它，`npm run dev` + 浏览器即可免 Electron 调界面。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8710',
        changeOrigin: true,
      },
    },
  },
});
