import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    // Windows environments in this repo can time out when booting multiple Vitest workers.
    // Keep parallelism on non-Windows platforms.
    maxWorkers: process.platform === "win32" ? 1 : undefined,
    // On Windows (Git Bash / MINGW64), spawning a fresh worker_thread per test file is slow
    // enough to trigger "Timeout waiting for worker to respond" errors.  The forks pool
    // gives each test file a real child process for true module isolation, avoiding mock
    // contamination that occurs with vmThreads' shared module registry.
    pool: process.platform === "win32" ? "forks" : "threads",
    // Disable file-level parallelism on Windows (single worker) for deterministic execution.
    fileParallelism: process.platform === "win32" ? false : true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/**/*.d.ts"],
    },
  },
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
