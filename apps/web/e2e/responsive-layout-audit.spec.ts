import { expect, test } from "@playwright/test";
// Shared with scripts/responsive-audit.mjs and scripts/form-layout-harness.mjs.
import { ACCEPTED_CONTAINMENT_EXCEPTIONS, inspectLayoutInPage, INTENDED_HORIZONTAL_SCROLLERS } from "../scripts/layout-inspector.mjs";

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
  // Document scroll width alone missed overflow inside clipped, independently
  // scrolling containers such as bottom sheets, so every route is measured
  // element by element (scripts/layout-inspector.mjs).
  test("consumer routes contain every element within its parent and the viewport", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    test.skip(!email, "E2E_EMAIL is required for the authenticated responsive audit");
    await signIn(page, email!);
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      for (const route of consumerRoutes) {
        await page.goto(route);
        await page.waitForLoadState("domcontentloaded");
        await expect(page.locator("body")).toBeVisible();
        const report = await page.evaluate(inspectLayoutInPage, {
          intendedScrollers: INTENDED_HORIZONTAL_SCROLLERS,
          acceptedOverflow: ACCEPTED_CONTAINMENT_EXCEPTIONS,
        });
        expect(
          report.issues.map((issue) => `${issue.kind}: ${issue.element}`),
          `${route} at ${viewport.name} has layout defects`,
        ).toEqual([]);
      }
    }
  });

  test("open bottom sheets keep their primary controls reachable", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    test.skip(!email, "E2E_EMAIL is required for the authenticated responsive audit");
    await signIn(page, email!);
    await page.setViewportSize({ width: 393, height: 852 });
    await page.goto("/calendar");
    // The previous pattern (/add event|new event/) never matched the FAB's
    // name, "Add calendar event", so this test passed without opening a
    // sheet. A missing control is now a failure, not a skip.
    const add = page.getByRole("button", { name: "Add calendar event" });
    await expect(add).toBeVisible();
    await add.click();
    const sheet = page.locator(".bottom-sheet").last();
    await expect(sheet).toBeVisible();
    const report = await page.evaluate(inspectLayoutInPage, {
      rootSelector: ".bottom-sheet",
      checkReachability: true,
      intendedScrollers: INTENDED_HORIZONTAL_SCROLLERS,
    });
    expect(report.issues.map((issue) => `${issue.kind}: ${issue.element}`)).toEqual([]);
    await expect(sheet.getByRole("button", { name: /save event/i })).toBeVisible();
  });
});
