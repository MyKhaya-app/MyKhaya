import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 1,
  use: {
    // Local API CSRF/origin policy allow-lists localhost; using 127.0.0.1
    // causes authenticated mutating requests to fail before login handling.
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8089",
    extraHTTPHeaders: process.env.PLAYWRIGHT_HOST_HEADER
      ? { Host: process.env.PLAYWRIGHT_HOST_HEADER }
      : undefined,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"] } },
  ],
});
