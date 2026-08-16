import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built straight into the API package so one uvicorn process serves everything.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../api/screener/static/ui", emptyOutDir: true },
  server: {
    proxy: {
      "/dashboard.json": "http://127.0.0.1:8000",
      "/fundamentals": "http://127.0.0.1:8000",
      "/screen": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
