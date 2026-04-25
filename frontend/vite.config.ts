import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Avoid fs.realpathSync.native() which fails with EPERM on corporate Windows
    preserveSymlinks: true,
  },
  optimizeDeps: {
    // Force include deps so Vite doesn't need to scan index.html
    include: ["react", "react-dom", "react-router-dom", "recharts", "axios", "zustand"],
    esbuildOptions: {
      preserveSymlinks: true,
    },
  },
  server: {
    port: 5177,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8002",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
