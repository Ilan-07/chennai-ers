// The console is served by the FastAPI app in production (`ui/dist` is mounted
// at `/`), so asset paths must be relative to the mount point rather than to the
// filesystem root. In development Vite serves the UI and proxies every /api call
// to uvicorn, which keeps the front end talking to the REAL service instead of a
// fixture -- a console that only works against mocked data is how the static
// build and the reports drifted apart in the first place.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
