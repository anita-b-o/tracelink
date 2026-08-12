import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  reporter: [["list"]],
  projects: [
    { name: "auth-setup", testMatch: /auth\.setup\.ts/ },
    { name: "auth", testMatch: /auth\.spec\.ts/ },
    {
      name: "workspace",
      testIgnore: [/auth\.setup\.ts/, /auth\.spec\.ts/],
      dependencies: ["auth-setup"],
      use: { storageState: "test-results/.auth/user.json" },
    },
  ],
});
