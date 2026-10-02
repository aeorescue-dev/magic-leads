import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    // O frontend so tem testes unitarios de logica pura por agora.
    // A cobertura de UI real (barra amarela no DOM) vem do Playwright E2E.
    environment: "node",
    include: ["lib/**/*.test.ts", "tests/unit/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});