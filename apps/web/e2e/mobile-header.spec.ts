import { expect, test } from "@playwright/test";

const WIDTHS = [320, 360, 375, 390, 393, 430];
const LONG_NAME = "The Parker-Montgomery Family Household";

// The Home name sits between the logo and the bell/avatar controls. It must
// never run under either side, the bell keeps its 44px touch target, and the
// header never scrolls the page sideways. Evaluated in-page.
function measureHeader() {
  const box = (selector: string) => document.querySelector(selector)?.getBoundingClientRect() ?? null;
  const home = box(".app-header-home");
  const logo = box(".app-header-logo");
  const actions = box(".app-header-actions");
  const bell = box(".app-header-notifications");
  const name = box(".app-header-home span");
  return {
    overlapsControls: home && actions ? home.right - actions.left : null,
    overlapsLogo: home && logo ? logo.right - home.left : null,
    bell: bell ? { width: bell.width, height: bell.height } : null,
    // A name too long for its button is clipped (ellipsis) inside it.
    nameSpills: name && home ? Math.max(name.right - home.right, home.left - name.left) : null,
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}

test.describe("mobile header", () => {
  test("the Home name never overlaps the logo or the bell", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(process.env.E2E_PASSWORD ?? "Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/home$/);

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/home");
      await page.locator(".app-header-notifications").waitFor();
      for (const longName of [false, true]) {
        if (longName) {
          // Display-only: the layout must cope with whatever name a Home has.
          await page.evaluate((text) => {
            const span = document.querySelector(".app-header-home span");
            if (span) span.textContent = text;
          }, LONG_NAME);
        }
        const label = `${width}px${longName ? " with a long Home name" : ""}`;
        const m = await page.evaluate(measureHeader);
        expect(m.overlapsControls, `name overlaps the bell/avatar at ${label}`).toBeLessThanOrEqual(0);
        expect(m.overlapsLogo, `name overlaps the logo at ${label}`).toBeLessThanOrEqual(0);
        expect(m.bell?.width, `bell touch target at ${label}`).toBeGreaterThanOrEqual(44);
        expect(m.bell?.height, `bell touch target at ${label}`).toBeGreaterThanOrEqual(44);
        expect(m.pageOverflow, `horizontal scroll at ${label}`).toBeLessThanOrEqual(0);
        expect(m.nameSpills, `name spills out of its button at ${label}`).toBeLessThanOrEqual(0);
      }
    }
  });
});
