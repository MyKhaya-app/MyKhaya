import { chromium, expect, test, type TestInfo } from "@playwright/test";

test("network failure keeps session bootstrap recoverable", async ({ page }) => {
  await page.route("**/api/v1/users/me", route => route.abort());

  await page.goto("/home");

  await expect(
    page.getByRole("heading", { name: "MyKhaya is temporarily unavailable" }),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/\/login$/);
});

test("definitive unauthenticated bootstrap reaches login", async ({ page }) => {
  await page.route("**/api/v1/users/me", route =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    }),
  );
  await page.route("**/api/v1/auth/renew", route =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    }),
  );

  await page.goto("/home");

  await expect(page).toHaveURL(/\/login$/);
});

test("trusted-device cookie survives a fresh browser process and renews silently", async ({
  baseURL,
}, testInfo: TestInfo) => {
  if (!baseURL) throw new Error("Playwright baseURL is required");
  const userDataDir = testInfo.outputPath("cold-start-profile");
  const deviceToken = "persisted-device-token";
  const deviceCsrf = "persisted-device-csrf";
  const deviceExpiry = Math.floor(Date.now() / 1000) + 90 * 24 * 60 * 60;
  const user = {
    id: "00000000-0000-0000-0000-000000000001",
    email: "cold-start@example.com",
    display_name: "Cold Start User",
    email_verified: true,
    birth_month: null,
    birth_day: null,
    birth_year: null,
    avatar_version: null,
    principal_type: "adult",
  };

  async function launchAndVerify() {
    const context = await chromium.launchPersistentContext(userDataDir, {
      headless: true,
    });
    const page = await context.newPage();
    let renewalSeen = false;
    await page.route("**/api/v1/users/me", (route) =>
      route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Expired" }) }),
    );
    await page.route("**/api/v1/auth/renew", async (route) => {
      renewalSeen = true;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(user) });
    });
    await page.route("**/api/v1/groups", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.goto(`${baseURL}/home`);
    await expect(page).not.toHaveURL(/\/login$/);
    await expect(page.getByText("Checking your MyKhaya session…")).not.toBeVisible();
    expect(renewalSeen).toBe(true);
    return context;
  }

  const firstContext = await chromium.launchPersistentContext(userDataDir, { headless: true });
  await firstContext.addCookies([
    {
      name: "mk_device",
      value: deviceToken,
      url: baseURL,
      httpOnly: true,
      sameSite: "Lax",
      expires: deviceExpiry,
    },
    { name: "mk_device_csrf", value: deviceCsrf, url: baseURL, sameSite: "Lax", expires: deviceExpiry },
  ]);
  await firstContext.close();

  const secondContext = await launchAndVerify();
  const persistedCookies = await secondContext.cookies(baseURL);
  expect(persistedCookies.find((cookie) => cookie.name === "mk_device")?.value).toBe(deviceToken);
  expect(persistedCookies.find((cookie) => cookie.name === "mk_device_csrf")?.value).toBe(deviceCsrf);
  await secondContext.close();
});
