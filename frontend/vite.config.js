import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 开发模式下将 /api 代理到本地 FastAPI（8000 端口），
// 前端统一使用相对路径请求，生产同源部署无需任何改动。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
