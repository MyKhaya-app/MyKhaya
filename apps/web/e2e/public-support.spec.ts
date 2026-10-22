import { expect, test, type Page, type Route } from "@playwright/test";

// Public Support page (/support): the App Store / Google Play support URL.
// Signed out (no session; /users/me answers 401), it must render without a
// sign-in redirect, keep the marketing nav and footer, link to the Support Hub
// and the support mailbox, and never scroll sideways at any supported width.
// API responses are mocked, so no account or seeded data is needed.

const WIDTHS = [320, 375, 390, 768, 1024, 1440];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockSignedOut(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/public/signup-state") return json(route, { signup_mode: "normal" });
    return json(route, { detail: "Not authenticated" }, 401);
  });
}

for (const width of WIDTHS) {
  test(`public Support page works signed out at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await mockSignedOut(page);
    await page.goto("/support");
    await expect(page.getByRole("heading", { level: 1, name: "We’re here to help." })).toBeVisible();
    await expect(page).toHaveURL(/\/support$/);

    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Support" })).toHaveAttribute("href", "/support");
    await expect(page.getByRole("link", { name: "Open Support Hub" })).toHaveAttribute("href", "/help-support");
    await expect(page.getByRole("link", { name: "Email Support" })).toHaveAttribute("href", "mailto:support@mykhaya.app");
    await expect(page.getByText("support@mykhaya.app", { exact: true })).toBeVisible();

    const { clientWidth, scrollWidth } = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(scrollWidth, `/support must not overflow at ${width}px`).toBeLessThanOrEqual(clientWidth);

    // Both actions stay comfortably tappable.
    for (const name of ["Open Support Hub", "Email Support"]) {
      const box = await page.getByRole("link", { name }).boundingBox();
      expect(box?.height ?? 0, `${name} height at ${width}px`).toBeGreaterThanOrEqual(44);
    }
  });
}

test("Open Support Hub sends a signed-out visitor to sign in, then back to the hub", async ({ page }) => {
  await mockSignedOut(page);
  await page.goto("/support");
  await page.getByRole("link", { name: "Open Support Hub" }).click();
  await expect(page).toHaveURL(/\/login\?next=%2Fhelp-support$/);
});
