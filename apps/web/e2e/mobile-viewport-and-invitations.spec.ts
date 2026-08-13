import { expect, test } from "@playwright/test";

const WIDTHS = [320, 375, 390, 393, 430];

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

// The heuristics behind Anthony's original bug report: any element whose bounding
// box extends past the right edge or before the left edge of the viewport, or that
// scrolls internally when it shouldn't. Mirrors scripts/diagnose-overflow.mjs.
// Evaluated in-page, so it must not reference anything outside its own body.
function measureOverflow() {
  const vw = window.innerWidth;
  const offenders: string[] = [];
  for (const el of document.querySelectorAll("body *")) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    if (rect.right > vw + 0.5 || rect.left < -0.5 || el.scrollWidth > el.clientWidth + 1) {
      const cls =
        typeof el.className === "string" && el.className
          ? `.${el.className.trim().split(/\s+/).join(".")}`
          : "";
      offenders.push(`${el.tagName.toLowerCase()}${cls}`);
    }
  }
  return {
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    offenders,
  };
}

test.describe("no horizontal overflow at supported mobile widths", () => {
  test("Home, Family, Notifications and child-profile creation", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/home$/);

    const routes = ["/home", "/people", "/settings/notifications", "/khaya-control-centre/children"];

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      for (const route of routes) {
        await page.goto(route);
        await page.waitForTimeout(300);
        const { clientWidth, scrollWidth, offenders } = await page.evaluate(measureOverflow);
        expect(
          scrollWidth,
          `${route} at ${width}px must not overflow (offending elements: ${offenders.join(", ")})`,
        ).toBeLessThanOrEqual(clientWidth);
      }
    }
  });
});

test.describe("invitation status is mutually exclusive", () => {
  test("a failed attempt never leaves a stale success banner, and vice versa", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/home$/);

    const homeName = `Invite Status Test ${Date.now()}`;
    const created = await api(page, "POST", "/groups", { name: homeName });
    expect(created.status).toBe(201);

    await page.goto("/people");
    await expect(page.getByRole("heading", { name: "Family" })).toBeVisible();

    const inviteEmail = `dup-${Date.now()}@example.com`;

    async function sendInvite() {
      await page.getByRole("button", { name: "Add member" }).click();
      await page.getByLabel("Email").fill(inviteEmail);
      await page.getByRole("button", { name: "Send invitation" }).click();
    }

    // First send: succeeds.
    await sendInvite();
    await expect(page.locator(".notice.success")).toBeVisible();
    await expect(page.locator(".notice.error")).toHaveCount(0);

    // Second send to the same address: the backend rejects it as a duplicate active
    // invitation (409) — the UI must show only the error, not the previous success
    // banner lingering alongside it.
    await sendInvite();
    await expect(page.locator(".notice.error")).toBeVisible();
    await expect(page.locator(".notice.success")).toHaveCount(0);
  });
});
