import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api and /health to the API container so the browser
// sees a single origin. In production the API serves web/dist itself, so the
// same relative paths keep working with no build-time configuration.
// `loadEnv` rather than `process.env`: reading process here required @types/node,
// which is a dependency added only to satisfy a type in a config file. Vite's own
// helper reads .env files and needs no extra types.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const target = env.VITE_API_URL || "http://localhost:8000";

  return {
    plugins: [react()],
    server: {
      port: 3000,
      host: "0.0.0.0",
      // Only used by `vite dev` when the API is on a different origin. Under
      // docker-compose the browser calls the API directly, and in production the
      // API serves this bundle itself, so neither path needs the proxy.
      proxy: {
        "/api": { target, changeOrigin: true },
        "/health": { target, changeOrigin: true },
      },
    },
    build: { outDir: "dist", sourcemap: false },
  };
});
