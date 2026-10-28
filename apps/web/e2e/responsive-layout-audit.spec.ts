import { expect, test } from "@playwright/test";

// This is deliberately opt-in: it uses only a dedicated E2E account supplied
// by the test environment and never creates or mutates household data.
const consumerRoutes = [
  "/",
  "/about",
  "/login",
  "/login/child",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/signup-choice",
  "/verify-email",
  "/offline",
  "/support",
  "/home",
  "/people",
  "/calendar",
  "/calendar/calendars",
  "/calendar/shared",
  "/meal-plans",
  "/lists",
  "/wish-lists",
  "/driveway",
  "/budget",
  "/help-support",
  "/me/notifications",
  "/settings",
  "/settings/profile",
  "/settings/home",
  "/settings/members",
  "/settings/security",
  "/settings/notifications",
  "/settings/reminders",
  "/settings/routines",
  "/settings/routines-reminders",
  "/settings/calendar",
  "/settings/calendar-tags",
] as const;

const viewports = [
  { name: "small-mobile", width: 320, height: 568 },
  { name: "iphone", width: 393, height: 852 },
  { name: "large-iphone", width: 430, height: 932 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

async function signIn(page: import("@playwright/test").Page, email: string) {
  const password = process.env.E2E_PASSWORD ?? "Correct horse battery staple!";
  await page.goto("/login");
  await page.getByRole("button", { name: "Not now" }).click({ timeout: 1500 }).catch(() => {});
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(home|onboarding)(?:$|\?)/, { timeout: 15000 });
}

test.describe("consumer responsive layout audit", () => {
  test("consumer routes have no document-level horizontal overflow", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    test.skip(!email, "E2E_EMAIL is required for the authenticated responsive audit");
    await signIn(page, email!);
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      for (const route of consumerRoutes) {
        await page.goto(route);
        await page.waitForLoadState("domcontentloaded");
        await expect(page.locator("body")).toBeVisible();
        const metrics = await page.evaluate(() => ({
          width: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
        }));
        expect(
          metrics.scrollWidth,
          `${route} at ${viewport.name} has document overflow: ${JSON.stringify(metrics)}`,
        ).toBeLessThanOrEqual(metrics.width + 1);
        expect(
          metrics.bodyScrollWidth,
          `${route} at ${viewport.name} has body overflow: ${JSON.stringify(metrics)}`,
        ).toBeLessThanOrEqual(metrics.width + 1);
      }
    }
  });

  test("open bottom sheets keep their primary controls reachable", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    test.skip(!email, "E2E_EMAIL is required for the authenticated responsive audit");
    await signIn(page, email!);
    await page.setViewportSize({ width: 393, height: 852 });
    await page.goto("/calendar");
    const add = page.getByRole("button", { name: /add event|new event/i }).first();
    if (await add.count()) {
      await add.click();
      const sheet = page.locator(".bottom-sheet").last();
      await expect(sheet).toBeVisible();
      const content = sheet.locator(".sheet-content");
      const bounds = await content.evaluate((node) => {
        const element = node as HTMLElement;
        return {
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight,
          hasOverflow: element.scrollHeight > element.clientHeight,
        };
      });
      expect(bounds.clientHeight).toBeGreaterThan(0);
      expect(await sheet.getByRole("button", { name: /save|create|add event/i }).count()).toBeGreaterThan(0);
    }
  });
});
