import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: Vite on 127.0.0.1:5173 proxies /api to the backend on 127.0.0.1:8741 (backend runs with
// IIP_ENV=dev IIP_DEV_ORIGINS=http://127.0.0.1:5173). allowedHosts is left at its safe default (threat-model C-18).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8741", changeOrigin: true } },
  },
  build: { sourcemap: false, cssCodeSplit: true, assetsInlineLimit: 0 },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: false },
});
