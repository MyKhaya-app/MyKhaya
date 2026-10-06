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

test.describe("PCC session gate", () => {
  test("a logged-out visit never paints authenticated PCC content before the login redirect", async ({ page, baseURL }) => {
    await installProbe(page, PCC_PRIVILEGED);
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later();
      await json(route, { detail: "Not authenticated" }, 401);
    });
    await page.goto(adminUrl(baseURL, "/"));
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "MyKhaya Platform Control Centre" })).toBeVisible();
    expect(await seen(page)).toEqual([]);
  });

  test("a refresh while logged out behaves the same", async ({ page, baseURL }) => {
    await installProbe(page, PCC_PRIVILEGED);
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later();
      await json(route, { detail: "Not authenticated" }, 401);
    });
    await page.goto(adminUrl(baseURL, "/users"));
    await expect(page).toHaveURL(/\/login$/);
    await page.goto(adminUrl(baseURL, "/users"));
    await expect(page).toHaveURL(/\/login$/);
    expect(await seen(page)).toEqual([]);
  });

  test("an expired session is treated as logged out", async ({ page, baseURL }) => {
    await installProbe(page, PCC_PRIVILEGED);
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later(300);
      await json(route, { detail: "Session expired" }, 401);
    });
    await page.goto(adminUrl(baseURL, "/homes"));
    await expect(page).toHaveURL(/\/login$/);
    expect(await seen(page)).toEqual([]);
  });

  test("a refresh while authenticated shows a neutral gate, then the shell — never the login page", async ({ page, baseURL }) => {
    await installProbe(page, { login: ".platform-login" });
    await page.route("**/api/v1/platform/auth/me", async (route) => {
      await later();
      await json(route, {
        id: "op-1",
        email: "op@example.com",
        display_name: "Operator One",
        role: "platform_owner",
        mfa_enrolled: true,
        session_status: "full",
      });
    });
    await page.route("**/api/v1/platform/overview", (route) => json(route, { detail: "n/a" }, 500));
    await page.goto(adminUrl(baseURL, "/"));
    // While resolving: content-free gate only.
    await expect(page.locator(".pcc-session-gate")).toBeVisible();
    await expect(page.locator(".platform-shell")).toHaveCount(0);
    await expect(page.locator(".operator-identity")).toContainText("Operator One");
    expect(page.url()).not.toMatch(/\/login/);
    expect(await seen(page)).toEqual([]);
  });

  test("a failed session check is 'could not verify', not a flash of PCC and not a silent redirect", async ({ page, baseURL }) => {
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
