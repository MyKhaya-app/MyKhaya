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

function iso(y: number, m: number, d: number, h: number) {
  return new Date(Date.UTC(y, m - 1, d, h)).toISOString();
}

async function gotoAugust2026(page: import("@playwright/test").Page) {
  await page.goto("/calendar");
  await page.waitForTimeout(300);
  for (let i = 0; i < 24; i += 1) {
    const heading = await page.locator(".calendar-period").textContent();
    if (heading?.includes("August 2026")) return;
    await page.getByRole("button", { name: "Next period" }).click();
    await page.waitForTimeout(100);
  }
  throw new Error("could not navigate to August 2026");
}

test.describe("calendar month view density", () => {
  test("empty weeks stay compact, busy weeks show events and overflow, multi-day events span, no horizontal overflow", async ({
    page,
  }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    // The install-PWA banner can overlap the sign-in button on this viewport.
    await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/(home|onboarding)$/);
    if (page.url().includes("/onboarding")) {
      await page.fill('input[name="name"]', "Density Test Home");
      await page.click("button");
      await expect(page).toHaveURL(/\/home$/);
    }

    const homes = (await api(page, "GET", "/groups")).body as { id: string }[];
    const homeId = homes[0]!.id;
    await api(page, "PUT", `/features/${homeId}/calendar/household`, { enabled: true, confirmed: true });

    // A busy first week of August 2026, several genuinely empty weeks, and a
    // multi-day event spanning a week boundary (12th-19th).
    for (const [title, day, hour] of [
      ["Busy one", 3, 8],
      ["Busy two", 3, 14],
      ["Busy three", 3, 16],
      ["Busy four", 3, 18],
      ["Busy five", 3, 20],
    ] as const) {
      await api(page, "POST", `/homes/${homeId}/events`, {
        title,
        start_at: iso(2026, 8, day, hour),
        end_at: iso(2026, 8, day, hour + 1),
        timezone: "Europe/London",
        is_all_day: false,
        label_id: null,
        location_text: null,
        member_ids: [],
      });
    }
    await api(page, "POST", `/homes/${homeId}/events`, {
      title: "Spans a week boundary",
      start_at: iso(2026, 8, 12, 0),
      end_at: iso(2026, 8, 19, 0),
      timezone: "Europe/London",
      is_all_day: true,
      label_id: null,
      location_text: null,
      member_ids: [],
    });

    await gotoAugust2026(page);

    // No horizontal overflow with this data.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    const weekHeights = await page.$$eval(".calendar-week", (weeks) =>
      weeks.map((week) => week.getBoundingClientRect().height),
    );
    // A week with 5 events reserves visibly more height than a week with none — this
    // is the core fix: rows are no longer a fixed block every week gets regardless
    // of content.
    const busiestWeek = Math.max(...weekHeights);
    const quietestWeek = Math.min(...weekHeights);
    expect(busiestWeek).toBeGreaterThan(quietestWeek);

    // The busy day shows an overflow indicator (5 events > MONTH_VISIBLE_ROW_CAP).
    await expect(page.locator(".overflow-events").first()).toBeVisible();

    // The multi-day event renders as a single spanning bar, not five separate items.
    const spanningBars = await page.locator(".month-event", { hasText: "Spans a week boundary" }).count();
    expect(spanningBars).toBeGreaterThanOrEqual(1);
    // Tapping the overflow indicator opens the day sheet.
    await page.locator(".overflow-events").first().click();
    await expect(page.locator(".bottom-sheet")).toBeVisible();
  });
});
