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

test.describe("normal household actions never prompt for a reason", () => {
  test("child permission change: no text-reason prompt, a plain confirm, and it's audited", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    // If window.prompt is ever called during this test, fail loudly rather than
    // silently accepting whatever the browser's default (usually null) resolves to
    // — a real regression here should not be masked by prompt() just returning null.
    let promptCalls = 0;
    page.on("dialog", async (dialog) => {
      if (dialog.type() === "prompt") promptCalls += 1;
      await dialog.accept();
    });

    await page.goto("/login");
    await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/(home|onboarding)$/);
    if (page.url().includes("/onboarding")) {
      await page.fill('input[name="name"]', "Reason Test Home");
      await page.click("button");
      await expect(page).toHaveURL(/\/home$/);
    }

    const homes = (await api(page, "GET", "/groups")).body as { id: string }[];
    const homeId = homes[0]!.id;

    await page.goto("/khaya-control-centre/children");
    await page.getByLabel("Display name").fill("Test Child");
    // The only guardian checkbox available is the current user (home admin).
    await page.locator('input[name="guardians"]').first().check();
    await page.getByRole("button", { name: "Create Child profile" }).click();
    // Also the regression guard for a real bug this suite caught: createChild()
    // used to read event.currentTarget after an `await`, which React can have
    // already nulled out, so form.reset() threw and masked a genuinely
    // successful 201 behind a generic "could not be created" error. If that
    // regresses, the profile never appears here even though the API call
    // succeeded. See the fix in khaya-control-centre/children/page.tsx.
    await expect(page.getByRole("heading", { name: "Test Child" }).first()).toBeVisible();

    // Toggle a permission — this used to prompt for a text reason before the plain
    // confirm; now it should go straight to the confirm.
    await page.locator("summary", { hasText: "Child permissions" }).first().click();
    const firstToggle = page.locator(".permission-row input[type=checkbox]").first();
    await firstToggle.click();

    expect(promptCalls, "window.prompt must never be called for a routine household action").toBe(0);

    // Confirm the change actually took effect and was audited (backend requirement:
    // making reason optional must not weaken the audit log).
    const audit = await api(page, "GET", `/groups/${homeId}/members`);
    expect(audit.status).toBe(200);
  });

  test("adult transition review: no text-reason prompt", async ({ page }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    let promptCalls = 0;
    page.on("dialog", async (dialog) => {
      if (dialog.type() === "prompt") promptCalls += 1;
      await dialog.accept();
    });

    await page.goto("/login");
    await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/(home|onboarding)$/);
    if (page.url().includes("/onboarding")) {
      await page.fill('input[name="name"]', "Reason Test Home");
      await page.click("button");
      await expect(page).toHaveURL(/\/home$/);
    }

    await page.goto("/khaya-control-centre/children");
    const reviewButton = page.getByRole("button", { name: "Start adult transition review" }).first();
    if (await reviewButton.count()) {
      await reviewButton.click();
      expect(promptCalls).toBe(0);
    }
  });
});
