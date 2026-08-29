import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  webServer: {
    command: "pnpm start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    env: {
      // Test-only Credentials provider (src/auth.ts) — never set outside e2e runs.
      AUTH_E2E_TEST_MODE: "1",
      AUTH_SECRET: process.env.AUTH_SECRET ?? "e2e-test-secret-not-for-real-use-0123456789",
      GITHUB_ID: process.env.GITHUB_ID ?? "e2e-dummy-client-id",
      GITHUB_SECRET: process.env.GITHUB_SECRET ?? "e2e-dummy-client-secret",
    },
  },
  use: {
    baseURL: "http://localhost:3000",
  },
});
