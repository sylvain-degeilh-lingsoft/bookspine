import { defineConfig } from "vite";

// Proxies /api/* to a locally running `bookspine serve` so the harness page
// never has to deal with cross-origin fetches (or BookSpine needing CORS
// headers at all) — it's a same-origin request from the browser's point of
// view, just like Thorium Web's own publication-server setup.
export default defineConfig({
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
