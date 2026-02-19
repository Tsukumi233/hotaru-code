import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/hotaru/webui/dist",
    emptyOutDir: true
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:4096",
      "/health": "http://127.0.0.1:4096",
      "/healthz": "http://127.0.0.1:4096"
    }
  }
});
