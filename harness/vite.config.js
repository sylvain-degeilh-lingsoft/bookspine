import { defineConfig } from "vite";

// No BookSpine proxy: it used to route /api/* to a locally running
// `bookspine serve`, but Vite's dev proxy hangs for tens of seconds on
// multi-MB responses (this harness's own paragraph lists can get that big) —
// a bug in the proxy itself, not in BookSpine. main.js now calls BookSpine
// directly, which works because its API sends permissive CORS headers.
export default defineConfig({});
