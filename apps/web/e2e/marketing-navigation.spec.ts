import { expect, test, type Page, type Route } from "@playwright/test";

// Back/Forward and in-app navigation across the public marketing pages.
//
// Regression for the "blank page after Back" defect: once /login had been
// visited in the tab, its stylesheet stayed loaded (Next.js keeps a route's
// global CSS after an in-app navigation away), and its bare ".signin" rule
// matched the marketing header's Sign in link. The link became a full-height
// block, so the sticky header covered the page: blank content, the nav
// floating mid-screen, "Sign in" alone at the top, clicks landing on the
// header. A full reload hid it, so only in-app navigation reproduces it.
//
// Every check runs after repeated Back/Forward cycles, not a single
// transition. API responses are mocked, so no account or data is needed.
// Run against a production build (`next build && next start`), not the
// development server.

const MARKETING_ROUTES = ["/", "/founding-beta", "/legal/terms", "/support", "/signup-choice"] as const;
const CYCLES = 3;

// Each page's own static heading. /legal/terms renders its title from the
// API response, so only its layout is checked here: under Playwright's
// request interception, WebKit can leave that fetch pending after a history
// navigation, which is a test-harness effect, not what this spec covers.
const HEADINGS: Record<string, string | null> = {
  "/": "Bring your family together.",
  "/founding-beta": "Help shape a calmer home.",
  "/legal/terms": null,
  "/support": "We’re here to help.",
  "/signup-choice": "How would you like to join MyKhaya?",
};

const SIGNUP_STATE = {
  signup_mode: "mixed",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: true,
  beta_joining_available: true,
  waitlist_available: true,
  joinable_count: 12,
  beta_terms_version: "1.1",
};

const TERMS = {
  key: "terms",
  display_name: "Terms & Conditions",
  audience: "adult",
  scope: "global",
  action_verb: "accept",
  acceptance_required: true,
  current_version: "1.0",
  current_version_id: "v-terms",
  effective_date: "2026-09-01",
};

/**
 * Mocks the API so no account or data is needed. Not in WebKit: Playwright's
 * request interception there can leave requests pending after a history
 * navigation (the page then waits for data that never arrives), which tests
 * the harness rather than the app. Without interception WebKit renders
 * these pages normally; their layout and static headings do not depend on
 * the API, which against a server without one simply answers with errors.
 */
async function mockApi(page: Page, browserName: string) {
  if (browserName === "webkit") return;
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/public/signup-state") return json(200, SIGNUP_STATE);
    if (path === "/legal/documents") return json(200, [TERMS]);
    if (path.startsWith("/legal/documents/")) {
      return json(200, { ...TERMS, version: "1.0", body_markdown: "# Terms & Conditions\n\nThe terms." });
    }
    if (path === "/auth/providers") return json(200, { providers: [] });
    // Signed out: the public pages must not depend on a session.
    if (path === "/users/me" || path === "/auth/renew") return json(401, { detail: "Not authenticated" });
    // Pricing is optional on the homepage and has its own failure state.
    if (path === "/billing/pricing") return json(503, { detail: "Unavailable" });
    return json(200, {});
  });
}

/** The page is laid out as itself: header at its normal height, its own
 *  heading visible, and the middle of the screen not covered by the header. */
async function expectIntactMarketingPage(page: Page, path: string, context: string) {
  await expect(page, context).toHaveURL((url) => url.pathname === path);
  const header = page.locator("header.nav");
  await expect(header, context).toBeVisible();
  await expect(page.locator("main").first(), context).toBeAttached();
  const heading = HEADINGS[path];
  if (heading) await expect(page.getByRole("heading", { level: 1, name: heading }), context).toBeVisible();
  const layout = await page.evaluate(() => {
    const headerBox = document.querySelector("header.nav")!.getBoundingClientRect();
    const middle = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    const signin = document.querySelector("header.nav .nav-cta a[href='/login']");
    return {
      headerHeight: Math.round(headerBox.height),
      middleIsHeader: Boolean(middle?.closest("header.nav")),
      signinHeight: signin ? Math.round(signin.getBoundingClientRect().height) : 0,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });
  expect(layout.headerHeight, `${context}: header height`).toBeLessThan(120);
  expect(layout.signinHeight, `${context}: header Sign in link height`).toBeLessThan(80);
  expect(layout.middleIsHeader, `${context}: the header covers the page`).toBe(false);
  expect(layout.horizontalOverflow, `${context}: horizontal overflow`).toBe(false);
}

/** The Sign in link a visitor can actually see: in the header on wide
 *  screens, in the footer on phones (the header link is hidden there). */
async function clickVisibleSignIn(page: Page) {
  const link = page.locator('a[href="/login"]:visible').first();
  await link.scrollIntoViewIfNeeded();
  await link.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
}

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

// The project's own viewport (desktop, Desktop Safari, iPhone 13), plus a
// tablet in both orientations: the header collapses into the menu at 920px
// and below, so portrait and landscape exercise different header layouts.
const TABLET_VIEWPORTS = [
  { label: "tablet portrait", viewport: { width: 820, height: 1180 } },
  { label: "tablet landscape", viewport: { width: 1024, height: 768 } },
] as const;

for (const { label, viewport } of [{ label: "project viewport", viewport: null }, ...TABLET_VIEWPORTS]) {
  test.describe(label, () => {
    if (viewport) test.use({ viewport });

    for (const route of MARKETING_ROUTES) {
      test(`${route}: Sign in, then Back and Forward ${CYCLES} times`, async ({ page, browserName }) => {
        const errors = collectPageErrors(page);
        await mockApi(page, browserName);
        await page.goto(route);
        await expectIntactMarketingPage(page, route, "fresh load");

        await clickVisibleSignIn(page);
        for (let cycle = 1; cycle <= CYCLES; cycle += 1) {
          await page.goBack();
          await expectIntactMarketingPage(page, route, `Back, cycle ${cycle}`);
          await page.goForward();
          await expect(page).toHaveURL(/\/login$/);
          await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
        }
        await page.goBack();
        await expectIntactMarketingPage(page, route, "Back after the last cycle");
        // Still interactive: an in-app link on the restored page works.
        const next = route === "/support" ? { name: "Terms", path: "/legal/terms" } : { name: "Support", path: "/support" };
        const link = page.locator("footer").getByRole("link", { name: next.name, exact: true });
        await link.scrollIntoViewIfNeeded();
        await link.click();
        await expectIntactMarketingPage(page, next.path, `in-app link after Back (${next.path})`);
        expect(errors).toEqual([]);
      });
    }

    test("arriving in-app from /login at the marketing pages, then Back and Forward through them all", async ({
      page,
      browserName,
    }) => {
      const errors = collectPageErrors(page);
      await mockApi(page, browserName);
      await page.goto("/login");
      await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();

      // Each step is an in-app (next/link) navigation, so /login's
      // stylesheet stays loaded the whole way.
      const visited: string[] = [];
      await page.locator("a.signin-brand").click();
      await expectIntactMarketingPage(page, "/", "in-app from /login");
      visited.push("/");
      for (const [name, path] of [
        ["Support", "/support"],
        ["Terms", "/legal/terms"],
      ] as const) {
        const link = page.locator("footer").getByRole("link", { name, exact: true });
        await link.scrollIntoViewIfNeeded();
        await link.click();
        await expectIntactMarketingPage(page, path, `in-app to ${path}`);
        visited.push(path);
      }
      // The join CTA reaches /signup-choice (and from there /founding-beta)
      // when the mocked signup state is "mixed"; without mocks (WebKit) the
      // CTA leads to /register instead, so the chain stops at /legal/terms.
      if (browserName !== "webkit") {
        const join = page.locator('a[href="/signup-choice"]:visible').first();
        await join.click();
        await expectIntactMarketingPage(page, "/signup-choice", "in-app to /signup-choice");
        visited.push("/signup-choice");
        await page.getByRole("link", { name: "Explore the Beta" }).click();
        await expectIntactMarketingPage(page, "/founding-beta", "in-app to /founding-beta");
        visited.push("/founding-beta");
      }

      // Walk the whole history back to /login and forward again, twice.
      for (let cycle = 1; cycle <= 2; cycle += 1) {
        for (let index = visited.length - 2; index >= 0; index -= 1) {
          await page.goBack();
          await expectIntactMarketingPage(page, visited[index]!, `Back to ${visited[index]}, cycle ${cycle}`);
        }
        await page.goBack();
        await expect(page).toHaveURL(/\/login$/);
        for (let index = 0; index < visited.length; index += 1) {
          await page.goForward();
          await expectIntactMarketingPage(page, visited[index]!, `Forward to ${visited[index]}, cycle ${cycle}`);
        }
      }
      expect(errors).toEqual([]);
    });
  });
}
