import { expect, test } from "@playwright/test";

async function api(page: import("@playwright/test").Page, method: string, path: string, body?: unknown) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1];
      const headers: Record<string, string> = { Accept: "application/json" };
      if (body) headers["Content-Type"] = "application/json";
      if (csrf && method !== "GET") headers["X-CSRF-Token"] = decodeURIComponent(csrf);
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        credentials: "include",
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = text;
      }
      return { status: response.status, body: parsed };
    },
    { method, path, body },
  );
}

async function loginAsAdult(page: import("@playwright/test").Page) {
  const email = process.env.E2E_EMAIL;
  if (!email) throw new Error("E2E_EMAIL is required");
  await page.goto("/login");
  await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("Correct horse battery staple!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(home|onboarding)$/);
  if (page.url().includes("/onboarding")) {
    await page.fill('input[name="name"]', "Child Login Test Home");
    await page.click("button");
    await expect(page).toHaveURL(/\/home$/);
  }
}

test.describe("managed Child sign-in", () => {
  test("adult can enable it from the Child profile screen, and the child can sign in and is restricted", async ({
    page,
  }) => {
    await loginAsAdult(page);

    const homes = (await api(page, "GET", "/groups")).body as {
      id: string;
      child_login_code: string;
    }[];
    const home = homes[0]!;

    const childName = `Login Test Child ${Date.now()}`;
    await page.goto("/khaya-control-centre/children");
    await page.getByLabel("Display name").fill(childName);
    await page.locator('input[name="guardians"]').first().check();
    await page.getByRole("button", { name: "Create Child profile" }).click();
    await expect(page.getByRole("heading", { name: childName }).first()).toBeVisible();

    const card = page.locator(".child-card", { hasText: childName });
    await card.locator("summary", { hasText: "Child sign-in" }).click();
    await expect(card.getByText("Disabled")).toBeVisible();

    const username = `loginkid${Date.now()}`;
    await card.locator('input[name="login_username"]').fill(username);
    await card.locator('input[name="login_pin"]').fill("4321");
    await card.getByRole("button", { name: "Enable sign-in" }).click();
    await expect(card.getByText("Enabled")).toBeVisible();

    // Log the adult out and sign in as the Child from a clean, unauthenticated
    // state — mirrors "another browser/PWA with no adult logged in".
    await page.context().clearCookies();
    await page.goto("/login");
    await page.getByRole("link", { name: "Child sign in" }).click();
    await expect(page).toHaveURL(/\/login\/child$/);

    await page.getByLabel("Home code").fill(home.child_login_code);
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("PIN").fill("4321");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/home$/);

    // A managed Child session must not see the Family (invite/membership) nav item.
    await expect(page.locator(".bottom-nav")).not.toContainText("Family");

    const me = await api(page, "GET", "/users/me");
    expect((me.body as { principal_type: string }).principal_type).toBe(
      "managed_child",
    );

    // Server-side enforcement, not just hidden UI: creating a Home must be refused.
    const createHome = await api(page, "POST", "/groups", { name: "Nope" });
    expect(createHome.status).toBe(403);

    // Normal logout returns to the ordinary sign-in screen with Child sign-in
    // choosable again, no adult-only options exposed.
    await api(page, "POST", "/auth/logout");
    await page.goto("/login");
    await expect(page.getByRole("link", { name: "Child sign in" })).toBeVisible();
  });

  test("the Child sign-in form fits a small mobile viewport without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/login/child");
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);

    const pin = page.getByLabel("PIN");
    await expect(pin).toHaveAttribute("inputmode", "numeric");
  });
});
