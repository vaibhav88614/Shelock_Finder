import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During `npm run dev` the Vite server proxies /api and /health
// to the FastAPI server on 127.0.0.1:8000. Production builds are
// served by FastAPI itself from frontend/dist, so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
