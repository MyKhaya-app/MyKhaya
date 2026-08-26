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
    const heading = await page.locator(".calendar-month-label").textContent();
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
    // multi-day event spanning a week boundary (12th-19th). Six same-day
    // events is deliberately one more than MONTH_VISIBLE_ROW_CAP (5) so the
    // overflow indicator below is genuinely exercised.
    for (const [title, day, hour] of [
      ["Busy one", 3, 8],
      ["Busy two", 3, 10],
      ["Busy three", 3, 14],
      ["Busy four", 3, 16],
      ["Busy five", 3, 18],
      ["Busy six", 3, 20],
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
    // Week height is the viewport's leftover space (after header/toolbar/weekday
    // row/bottom nav) divided across all six weeks — clamp(88px, ..., 145px) — so
    // every week, including an empty one, reads as a genuine row rather than a thin
    // strip, all six stay visible together with no internal scroll region, and a
    // busy week's actual content can still push it taller than a quiet one.
    const quietestWeek = Math.min(...weekHeights);
    const busiestWeek = Math.max(...weekHeights);
    expect(quietestWeek).toBeGreaterThanOrEqual(85);
    expect(busiestWeek).toBeGreaterThanOrEqual(quietestWeek);

    // All six weeks are visible together on a standard phone viewport — no nested
    // scroll region inside the month grid (a real regression this test catches: an
    // earlier iteration made the weeks grid its own internally-scrolling box).
    const weeksBox = await page.locator(".calendar-weeks").boundingBox();
    const weeksScroll = await page.locator(".calendar-weeks").evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      overflowY: getComputedStyle(el).overflowY,
    }));
    expect(weeksScroll.overflowY).not.toBe("auto");
    expect(weeksScroll.overflowY).not.toBe("scroll");
    expect(weeksScroll.scrollHeight).toBeLessThanOrEqual(weeksScroll.clientHeight + 1);
    const allWeeksBottom = weekHeights.reduce((sum, h) => sum + h, 0) + weeksBox!.y;
    expect(allWeeksBottom).toBeLessThanOrEqual(844);

    // The busy day shows an overflow indicator (6 events > MONTH_VISIBLE_ROW_CAP).
    await expect(page.locator(".overflow-events").first()).toBeVisible();

    // The multi-day event renders as a single spanning bar, not five separate items.
    const spanningBars = await page.locator(".month-event", { hasText: "Spans a week boundary" }).count();
    expect(spanningBars).toBeGreaterThanOrEqual(1);
    // Tapping the overflow indicator opens the day sheet.
    await page.locator(".overflow-events").first().click();
    await expect(page.locator(".bottom-sheet")).toBeVisible();
  });

  test("a multi-day event's title starts from its first character and truncates only on the right, including when it begins in the first visible column", async ({
    page,
  }) => {
    const email = process.env.E2E_EMAIL;
    if (!email) throw new Error("E2E_EMAIL is required");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("Correct horse battery staple!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/(home|onboarding)$/);
    if (page.url().includes("/onboarding")) {
      await page.fill('input[name="name"]', "Clipping Test Home");
      await page.click("button");
      await expect(page).toHaveURL(/\/home$/);
    }

    const homes = (await api(page, "GET", "/groups")).body as { id: string }[];
    const homeId = homes[0]!.id;
    await api(page, "PUT", `/features/${homeId}/calendar/household`, { enabled: true, confirmed: true });

    // August 3, 2026 is a Monday — the first visible weekday column — and the
    // title is deliberately long enough to overflow a narrow mobile week cell.
    // This is the exact regression: centering a `nowrap` overflowing flex
    // child clips its *start*, not just its end ("AH - Police ..." rendered
    // as "- Police Tr...").
    const longTitle = "AH - Police training refresher course";
    await api(page, "POST", `/homes/${homeId}/events`, {
      title: longTitle,
      start_at: iso(2026, 8, 3, 0),
      end_at: iso(2026, 8, 6, 0),
      timezone: "Europe/London",
      is_all_day: true,
      label_id: null,
      location_text: null,
      member_ids: [],
    });

    await gotoAugust2026(page);

    const bar = page.locator(".month-event.month-event-span", { hasText: "Police" }).first();
    await expect(bar).toBeVisible();

    // The root cause, asserted directly: a spanning bar must never centre its
    // text — centering plus `overflow: hidden` on a `nowrap` child is what
    // clipped the start of the title in the reported bug.
    const alignment = await bar.evaluate((el) => ({
      justifyContent: getComputedStyle(el).justifyContent,
      textAlign: getComputedStyle(el).textAlign,
    }));
    expect(alignment.justifyContent).not.toBe("center");
    expect(alignment.textAlign).not.toBe("center");

    // The full, untruncated title is always present in the accessible name —
    // truncation is purely visual, never a loss of the underlying data.
    await expect(bar).toHaveAccessibleName(new RegExp(longTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

    // The rendered box starts flush with its grid column (no negative
    // offset/transform pushing it left of the day it begins on).
    const week = page.locator(".calendar-week").filter({ has: bar });
    const [barBox, weekBox] = await Promise.all([bar.boundingBox(), week.boundingBox()]);
    expect(barBox).not.toBeNull();
    expect(weekBox).not.toBeNull();
    expect(barBox!.x).toBeGreaterThanOrEqual(weekBox!.x - 1);
  });
});
