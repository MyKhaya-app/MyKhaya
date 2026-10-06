import { expect, test, type Page, type Route } from "@playwright/test";

// Guards the UNKNOWN → RESOLVING → RESOLVED → RENDER rule (see
// components/resolvable.ts): auth/authorisation/entitlement-sensitive UI must
// never render from a guessed default and then correct itself. API responses
// are mocked and artificially delayed so the unresolved window is wide enough
// to observe on any machine; a MutationObserver records every DOM state the
// page ever commits (not just the one a screenshot would catch).

const DELAY_MS = 1200;

async function installProbe(page: Page, forbidden: Record<string, string>) {
  await page.addInitScript((selectors) => {
    const w = window as unknown as { __flicker: Record<string, boolean> };
    w.__flicker = {};
    const check = () => {
      for (const [name, selector] of Object.entries(selectors)) {
        if (document.querySelector(selector)) w.__flicker[name] = true;
      }
    };
    new MutationObserver(check).observe(document, { childList: true, subtree: true, attributes: true });
    document.addEventListener("DOMContentLoaded", check);
  }, forbidden);
}

async function seen(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Object.keys((window as unknown as { __flicker: Record<string, boolean> }).__flicker ?? {}),
  );
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const later = (ms = DELAY_MS) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------- PCC

const PCC_PRIVILEGED = {
  shell: ".platform-shell",
  sidebar: ".tailadmin-sidebar",
  nav: 'nav[aria-label="Control Centre navigation"]',
  operator: ".operator-identity",
  overview: ".platform-overview",
};

function adminUrl(baseURL: string | undefined, path: string) {
  const url = new URL(baseURL ?? "http://127.0.0.1:8089");
  url.hostname = "admin.localhost";
  return `${url.origin}${path}`;
}

// The edge (middleware) redirects a PCC request that carries no session cookie
// to /login before anything renders. Tests of the *client* gate therefore
// present a session cookie, the way a browser with a (possibly expired)
// session would.
async function withSessionCookie(page: Page, baseURL: string | undefined) {
  await page.context().addCookies([
    { name: "mk_admin_session", value: "test-session", url: adminUrl(baseURL, "/") },
  ]);
}

const OPERATOR = {
  id: "op-1",
  email: "op@example.com",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full",
};

test.describe("PCC first paint", () => {
  test("a fresh, cookie-less browser is redirected at the edge: no PCC HTML is ever served", async ({ baseURL, playwright }) => {
    const request = await playwright.request.newContext({ extraHTTPHeaders: { "sec-fetch-site": "none" } });
    for (const path of ["/", "/users", "/homes/abc"]) {
      const response = await request.get(adminUrl(baseURL, path), { maxRedirects: 0 });
      expect(response.status(), path).toBe(307);
      expect(response.headers()["location"]).toMatch(/^https?:\/\/admin\.localhost(:\d+)?\/login$/);
      expect(await response.text()).not.toMatch(/platform-shell|tailadmin-sidebar|Control Centre navigation/);
    }
    await request.dispose();
  });

  test("a fresh browser context (no cookies/storage) lands on login and paints no PCC UI, with /auth/me held for 4s", async ({ browser, baseURL }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await installProbe(page, PCC_PRIVILEGED);
    let authMeCalls = 0;
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      authMeCalls += 1;
      await later(4000);
      await json(route, { detail: "Not authenticated" }, 401);
    });
    await page.goto(adminUrl(baseURL, "/"));
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "MyKhaya Platform Control Centre" })).toBeVisible();
    await page.waitForTimeout(500);
    expect(await seen(page)).toEqual([]);
    expect(authMeCalls).toBe(0);
    await context.close();
  });

  test("with a session cookie, the server HTML is only the neutral gate — no PCC markup before JavaScript", async ({ baseURL, playwright }) => {
    const request = await playwright.request.newContext({
      extraHTTPHeaders: { "sec-fetch-site": "none", cookie: "mk_admin_session=test-session" },
    });
    for (const path of ["/", "/users", "/homes/abc"]) {
      const html = await (await request.get(adminUrl(baseURL, path), { maxRedirects: 0 })).text();
      expect(html, path).toContain("pcc-session-gate");
      expect(html, path).not.toMatch(
        /platform-shell|tailadmin-sidebar|Control Centre navigation|Privileged system|operator-identity|Loading operator|Loading platform state/,
      );
    }
    await request.dispose();
  });

  test("with JavaScript disabled, a session-cookie visit shows no PCC UI at all", async ({ browser, baseURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    await context.addCookies([{ name: "mk_admin_session", value: "x", url: adminUrl(baseURL, "/") }]);
    const page = await context.newPage();
    await page.goto(adminUrl(baseURL, "/"));
    for (const selector of Object.values(PCC_PRIVILEGED)) await expect(page.locator(selector)).toHaveCount(0);
    await context.close();
  });

  test("an expired session (cookie present, API says 401) shows only the gate for the whole 4s check, then login", async ({ page, baseURL }) => {
    await withSessionCookie(page, baseURL);
    await installProbe(page, PCC_PRIVILEGED);
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later(4000);
      await json(route, { detail: "Session expired" }, 401);
    });
    await page.goto(adminUrl(baseURL, "/users"));
    await expect(page.locator(".pcc-session-gate")).toBeVisible();
    await page.screenshot({ path: "test-results/pcc-gate-during-auth-check.png" });
    await page.waitForTimeout(2000);
    await expect(page.locator(".platform-shell")).toHaveCount(0);
    await expect(page).toHaveURL(/\/login$/, { timeout: 8000 });
    expect(await seen(page)).toEqual([]);
  });

  test("a refresh while authenticated shows the gate, then the shell — never the login page", async ({ page, baseURL }) => {
    await withSessionCookie(page, baseURL);
    await installProbe(page, { login: ".platform-login" });
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later(2000);
      await json(route, OPERATOR);
    });
    await page.route("**/api/v1/platform/overview", (route) => json(route, { detail: "n/a" }, 500));
    await page.goto(adminUrl(baseURL, "/"));
    await expect(page.locator(".pcc-session-gate")).toBeVisible();
    await expect(page.locator(".platform-shell")).toHaveCount(0);
    await expect(page.locator(".operator-identity")).toContainText("Operator One");
    expect(page.url()).not.toMatch(/\/login/);
    expect(await seen(page)).toEqual([]);
  });

  test("authenticated navigation between PCC pages does not re-show the gate", async ({ page, baseURL }) => {
    await withSessionCookie(page, baseURL);
    await installProbe(page, {});
    await page.route("**/api/v1/platform/auth/me", (route) => json(route, OPERATOR));
    await page.route("**/api/v1/platform/**", (route) =>
      route.request().url().includes("/auth/me") ? route.fallback() : json(route, { detail: "n/a" }, 500),
    );
    await page.goto(adminUrl(baseURL, "/"));
    await expect(page.locator(".operator-identity")).toBeVisible();
    await page.evaluate(() => {
      const w = window as unknown as { __gateAgain: boolean };
      w.__gateAgain = false;
      new MutationObserver(() => {
        if (document.querySelector(".pcc-session-gate")) w.__gateAgain = true;
      }).observe(document, { childList: true, subtree: true });
    });
    await page.locator('a.menu-item[href="/control-centre/health"], a.menu-item[href="/health"]').first().click();
    await expect(page.locator(".operator-identity")).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __gateAgain: boolean }).__gateAgain)).toBe(false);
  });

  test("a failed session check is 'could not verify', not a flash of PCC and not a silent redirect", async ({ page, baseURL }) => {
    await withSessionCookie(page, baseURL);
    await installProbe(page, PCC_PRIVILEGED);
    await page.route("**/api/v1/platform/auth/me", (route) => route.abort());
    await page.goto(adminUrl(baseURL, "/"));
    await expect(page.getByText("The Control Centre could not verify your session.")).toBeVisible();
    expect(page.url()).not.toMatch(/\/login/);
    expect(await seen(page)).toEqual([]);
  });
});

// ---------------------------------------------------------------- MyKhaya

type Plan = "free" | "family" | "ultimate";

const USER = {
  id: "u1",
  email: "megan@example.com",
  display_name: "Megan",
  email_verified: true,
  birth_month: null,
  birth_day: null,
  birth_year: null,
  avatar_version: null,
  principal_type: "adult",
};
const HOME = {
  id: "home-1",
  name: "Hales Home",
  role: "owner",
  relationship: "home_admin",
  permission_profile: "full",
  capabilities: ["members.invite"],
  member_count: 1,
  child_login_code: "ABC123",
};
const MODULES = ["calendar", "nudges", "shopping", "meals", "wish_lists", "driveway", "budget"];
const usage = { count: 1, limit: null, over_limit: false };

function billingFor(plan: Plan) {
  const family = plan !== "free";
  const ultimate = plan === "ultimate";
  return {
    stored_plan: plan,
    effective_plan: plan,
    family_access: family,
    can_manage_billing: true,
    calendar_usage: usage,
    category_usage: usage,
    member_usage: usage,
    nudges_enabled: family,
    meals_enabled: family,
    wishlists_enabled: family,
    lists_enabled: true,
    budget_enabled: ultimate,
    driveway_enabled: ultimate,
  };
}

async function mockMyKhaya(page: Page, plan: Plan, delay = DELAY_MS) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/users/me") return json(route, USER);
    if (path === "/legal/status") return json(route, { action_required: false, documents: [], children: [], child_self: null });
    if (path === "/groups") return json(route, [HOME]);
    // Plan/feature state is the slow, authoritative part.
    if (path === "/groups/home-1/billing") {
      await later(delay);
      return json(route, billingFor(plan));
    }
    if (path === "/features/home-1") {
      await later(delay / 3);
      return json(route, { features: MODULES.map((feature) => ({ feature, enabled: true })) });
    }
    if (path === "/notifications/unread-count") return json(route, { unread_count: 0 });
    return json(route, {});
  });
}

// Rows whose lock state must be correct from their very first render.
const row = (href: string) => `a.more-row[href="${href}"]`;
const FAMILY_ROWS = ["/settings/routines-reminders", "/meal-plans", "/wish-lists"];
const ULTIMATE_ROWS = ["/budget", "/driveway"];

function unlockedProbe(hrefs: string[]) {
  return Object.fromEntries(hrefs.map((href) => [`unlocked ${href}`, `${row(href)}:not(.more-row-locked)`]));
}
function lockedProbe(hrefs: string[]) {
  return Object.fromEntries(hrefs.map((href) => [`locked ${href}`, `${row(href)}.more-row-locked`]));
}

test.describe("MyKhaya entitlement state", () => {
  test("Free: premium modules are never shown as available on More", async ({ page }) => {
    await installProbe(page, {
      ...unlockedProbe([...FAMILY_ROWS, ...ULTIMATE_ROWS]),
      familyTab: ".bottom-nav a[href='/people']:not(.nav-pending), .desktop-nav a[href='/people']:not(.nav-pending)",
    });
    await mockMyKhaya(page, "free");
    await page.goto("/settings");
    await expect(page.locator(`${row("/meal-plans")}.more-row-locked`)).toBeVisible();
    await expect(page.locator(`${row("/driveway")}.more-row-locked`)).toBeVisible();
    // Lists is included on Free and is the one module that is never locked.
    await expect(page.locator(`${row("/lists")}:not(.more-row-locked)`)).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });

  test("Family: family modules are never shown locked, Ultimate-only ones are locked from first render", async ({ page }) => {
    await installProbe(page, {
      ...lockedProbe([...FAMILY_ROWS, "/lists"]),
      ...unlockedProbe(ULTIMATE_ROWS),
    });
    await mockMyKhaya(page, "family");
    await page.goto("/settings");
    await expect(page.locator(`${row("/meal-plans")}:not(.more-row-locked)`)).toBeVisible();
    await expect(page.locator(`${row("/budget")}.more-row-locked`)).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });

  test("Ultimate (and complimentary Ultimate): nothing is ever shown locked", async ({ page }) => {
    await installProbe(page, lockedProbe([...FAMILY_ROWS, ...ULTIMATE_ROWS, "/lists"]));
    await mockMyKhaya(page, "ultimate");
    await page.goto("/settings");
    await expect(page.locator(`${row("/driveway")}:not(.more-row-locked)`)).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });

  test("a refresh of an authenticated session never shows the signed-out interstitial", async ({ page }) => {
    await installProbe(page, { signedOut: "main.app-bootstrap-state:has-text('Taking you to sign in')" });
    await mockMyKhaya(page, "family", 600);
    await page.goto("/settings");
    await expect(page.locator(`${row("/meal-plans")}`)).toBeVisible();
    await page.reload();
    await expect(page.locator(`${row("/meal-plans")}`)).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });

  test("navigating within a session reuses resolved plan state (no placeholders on return to More)", async ({ page }) => {
    await installProbe(page, {});
    await mockMyKhaya(page, "family");
    await page.goto("/settings");
    await expect(page.locator(`${row("/meal-plans")}`)).toBeVisible();
    await page.getByRole("link", { name: "Calendar", exact: true }).first().click();
    await page.getByRole("link", { name: "More", exact: true }).first().click();
    // Immediately resolved — rows present without waiting for the (delayed) API.
    await expect(page.locator(`${row("/meal-plans")}`)).toBeVisible({ timeout: 500 });
    await expect(page.locator(".more-row-skeleton")).toHaveCount(0);
  });

  test("a failed entitlement request fails closed: module rows hidden, no placeholders left behind", async ({ page }) => {
    await installProbe(page, unlockedProbe([...FAMILY_ROWS, ...ULTIMATE_ROWS]));
    await mockMyKhaya(page, "ultimate", 300);
    await page.route("**/api/v1/groups/home-1/billing", (route) => route.abort());
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Help & Support" })).toBeVisible();
    await expect(page.locator(".more-row-skeleton")).toHaveCount(0);
    await expect(page.locator(row("/meal-plans"))).toHaveCount(0);
    expect(await seen(page)).toEqual([]);
  });

  test("direct navigation to a premium route on Free shows no premium content before the lock", async ({ page }) => {
    await installProbe(page, { vehicleForm: "[aria-label='Add vehicle'], .driveway-vehicle-list" });
    await mockMyKhaya(page, "free");
    await page.route("**/api/v1/groups/home-1/vehicles**", (route) => json(route, { items: [] }));
    await page.goto("/driveway");
    await expect(page.getByRole("link", { name: /Plan|Upgrade|Billing/i }).first()).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });
});
