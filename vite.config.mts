import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: path.resolve(projectRoot, "electron/renderer"),
  base: "./",
  plugins: [react()],
  build: {
    outDir: path.resolve(projectRoot, "dist/renderer"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    root: projectRoot,
    include: ["tests-electron/**/*.test.ts"],
  },
});
