import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir:"./e2e",
  fullyParallel:false,
  workers:1,
  retries:0,
  timeout:90_000,
  expect:{timeout:20_000},
  use:{baseURL:process.env.PLAYWRIGHT_BASE_URL??"http://localhost:3100",trace:"retain-on-failure",screenshot:"only-on-failure"},
  reporter:[["list"]],
});
