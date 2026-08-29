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
      // Stateful API routes must reach FastAPI too. Without these, Vite returns
      // the SPA HTML fallback with HTTP 200: tracking looks successful only in
      // React memory, then disappears on refresh because SQLite was never touched.
      "/tracked": "http://127.0.0.1:8000",
      "/portfolio": "http://127.0.0.1:8000",
      "/portfolios": "http://127.0.0.1:8000",
      "/sync": "http://127.0.0.1:8000",
      "/config": "http://127.0.0.1:8000",
    },
  },
});
