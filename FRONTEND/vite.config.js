import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // the Python API (py -m copilot.server) listens on :8000; proxying keeps the browser same-origin (no CORS)
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, timeout: 200000, proxyTimeout: 200000 } },
  },
});
