import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The dev server origin is the value the backend must allow through CORS.
// Backend CORS is empty by default and is not weakened for development; set
// ACADEMIOUS_CORS_ALLOWED_ORIGINS=http://localhost:5173 instead. See README.md.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // The first test in each file pays for module transform and jsdom start-up,
    // which on a loaded machine exceeds the 5 s default and reads as a flaky
    // timeout rather than as the fixed cost it is.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
