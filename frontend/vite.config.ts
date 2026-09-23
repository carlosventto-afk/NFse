import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  // Mesmo proxy do dev server: sem isso, `vite preview` (usado pelos testes
  // Playwright, ver CLAUDE.md) nao encaminha /api pro backend e todo fetch
  // do frontend buildado cai em 404 contra o proprio preview server.
  preview: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
