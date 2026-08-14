import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
  esbuild: {
    jsx: "automatic",
  },
  test: {
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // Lets @testing-library/react auto-register its afterEach(cleanup) hook,
    // which otherwise requires a global `afterEach` to detect.
    globals: true,
  },
});
