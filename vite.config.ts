/// <reference types="vitest/config" />
import { defineConfig } from "vite";

// Builds the page only (web/). The API server in server/ is Python and needs no build step.
export default defineConfig({
  root: "web",
  base: "./",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    // MapLibre (~1 MB) is its own lazily loaded chunk, fetched only when the Roads style is picked
    chunkSizeWarningLimit: 1100,
  },
  server: {
    port: 5173,
    host: "127.0.0.1",
    // In development the page and the API are separate processes; `npm run dev` starts both.
    proxy: { "/api/": { target: `http://127.0.0.1:${process.env.API_PORT ?? 8787}`, changeOrigin: false } },
  },
  test: { root: ".", include: ["web/**/*.test.ts"] },
});
