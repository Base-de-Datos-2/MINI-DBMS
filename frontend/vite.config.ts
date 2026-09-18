import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the API runs separately (`python -m api`); Vite forwards
// every /api request to it, so the browser only ever talks to one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
