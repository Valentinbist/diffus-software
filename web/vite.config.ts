import { defineConfig } from "vite";

// Builds straight into the shared presentation package's static dir so
// FastAPI can serve it from /static without copying anything around; the
// manifest lets shared/presentation/assets.py resolve hashed filenames.
export default defineConfig({
  base: "/static/dist/",
  build: {
    outDir: "../src/diffus/shared/presentation/static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: "src/main.ts",
    },
  },
});
