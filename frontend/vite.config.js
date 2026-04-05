import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    /** 5173 被占用时自动递增端口，避免启动失败 */
    strictPort: false,
  },
  preview: {
    port: 5173,
    strictPort: false,
  },
});
