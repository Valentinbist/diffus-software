import { defineConfig } from "vite";

// Builds straight into the shared presentation package's static dir so
// FastAPI can serve it from /static without copying anything around; the
// manifest lets shared/presentation/assets.py resolve hashed filenames.
//
// Two entries: src/main.ts (the page script, hashed as usual) and src/sw.ts,
// the service worker, which has to keep one fixed name — app.py serves
// dist/sw.js at /sw.js — so entryFileNames keeps it out of assets/. The
// files in public/ (web app manifest, icons, offline page) are copied into
// dist/ as they are.
//
// __BUILD_ID__ makes each build's sw.js byte-different from the last, which
// is what tells browsers to install it and drop the previous build's cache.
// It is fixed for the lifetime of one `vite build --watch`, so in the dev
// stack the worker (and the offline page it precaches) refreshes when the
// web service restarts, not on every save.
export default defineConfig({
  base: "/static/dist/",
  define: {
    __BUILD_ID__: JSON.stringify(Date.now().toString(36)),
  },
  build: {
    outDir: "../src/diffus/shared/presentation/static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: { main: "src/main.ts", sw: "src/sw.ts" },
      output: {
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
      },
    },
  },
});
