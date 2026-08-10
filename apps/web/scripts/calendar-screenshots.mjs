// Visual verification for the calendar density rework. Not a permanent test —
// captures screenshots for manual review against the TimeTree reference.
//
// Usage: node scripts/calendar-screenshots.mjs [baseUrl]
// Requires the dev stack running (default http://localhost:8080).

import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:8080";
const stamp = Date.now();
const email = `cal-shot-${stamp}@example.com`;
const password = "Correct-Horse-Battery-Staple-9";

const browser = await chromium.launch();
const page = await browser.newPage();

async function api(method, path, body) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1];
      const headers = { Accept: "application/json" };
      if (body) headers["Content-Type"] = "application/json";
      if (csrf && method !== "GET") headers["X-CSRF-Token"] = decodeURIComponent(csrf);
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        credentials: "include",
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await response.text();
      let parsed = null;
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

await page.goto(`${BASE}/register`);
await page.waitForLoadState("networkidle");
await page.fill('input[name="name"]', "Cal Shot");
await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.fill('input[name="confirm"]', password);
await page.click("button");
await page.waitForURL(/\/(login|verify-email)/, { timeout: 10000 });

if (page.url().includes("/verify-email")) {
  console.log("This dev stack has email verification enabled; run against a stack with it off, or verify manually.");
  await browser.close();
  process.exit(1);
}

await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.click("button");
await page.waitForURL(/\/(onboarding|home)/, { timeout: 10000 });
if (page.url().includes("/onboarding")) {
  await page.fill('input[name="name"]', "Hales Household");
  await page.click("button");
  await page.waitForURL(/\/home/, { timeout: 10000 });
}

const homes = (await api("GET", "/groups")).body;
const homeId = homes[0].id;
await api("PUT", `/features/${homeId}/calendar/household`, {
  enabled: true,
  confirmed: true,
});

const members = (await api("GET", `/groups/${homeId}/members`)).body;
const adminMembershipId = members[0].membership_id;
await api("POST", `/groups/${homeId}/children`, {
  display_name: "Alyssa Hales",
  age_band: "under_13",
  guardian_membership_ids: [adminMembershipId],
});

const labels = {};
for (const [name, color] of [
  ["Sport", "#3B82C4"],
  ["School", "#6FAA5E"],
  ["Family", "#E9B44C"],
  ["Work", "#9B6BC9"],
]) {
  const created = await api("POST", `/homes/${homeId}/event-labels`, { name, color });
  labels[name] = created.body.id;
}

// Fixed month: August 2026, matching the TimeTree reference. Deliberately busy:
// multiple events on many days, several long titles, a same-week multi-day span, a
// cross-week multi-day span (a "holiday"), a cross-month span, recurring-looking
// repeats, and enough events on one day to force the overflow indicator.
function iso(y, m, d, h, min = 0) {
  return new Date(Date.UTC(y, m - 1, d, h, min)).toISOString();
}

const events = [
  ["Anthony · On call this week", iso(2026, 8, 3, 8), iso(2026, 8, 3, 9), "Work", null],
  ["Megan · Dentist appointment downtown", iso(2026, 8, 3, 14), iso(2026, 8, 3, 15), "Family", null],
  ["Alyssa · Swimming lesson", iso(2026, 8, 4, 16), iso(2026, 8, 4, 17), "Sport", null],
  ["Alyssa · Eye check-up", iso(2026, 8, 4, 10), iso(2026, 8, 4, 11), "Family", null],
  ["Family dinner at Grandma's", iso(2026, 8, 4, 18), iso(2026, 8, 4, 20), "Family", null],
  ["Anthony · Team offsite", iso(2026, 8, 5, 9), iso(2026, 8, 5, 17), "Work", null],
  ["Megan · Yoga class", iso(2026, 8, 5, 7), iso(2026, 8, 5, 8), "Sport", null],
  ["Alyssa · School photo day", iso(2026, 8, 6, 9), iso(2026, 8, 6, 10), "School", null],
  ["Parents' evening", iso(2026, 8, 6, 17), iso(2026, 8, 6, 18), "School", null],
  ["Football match away fixture", iso(2026, 8, 6, 10), iso(2026, 8, 6, 11), "Sport", null],
  ["Anthony · Long call with the Berlin office", iso(2026, 8, 7, 8), iso(2026, 8, 7, 9), "Work", null],
  // A same-week multi-day span.
  ["Summer holiday", iso(2026, 8, 10, 0), iso(2026, 8, 13, 0), "Family", "allday"],
  // A cross-week multi-day span.
  ["School half-term camp", iso(2026, 8, 12, 0), iso(2026, 8, 19, 0), "School", "allday"],
  // A cross-month span.
  ["Extended family visiting", iso(2026, 8, 29, 0), iso(2026, 9, 3, 0), "Family", "allday"],
  // A very busy single day to force the "+N more" overflow indicator.
  ["Anthony · Standup", iso(2026, 8, 17, 9), iso(2026, 8, 17, 9), "Work", null],
  ["Megan · Physio", iso(2026, 8, 17, 10), iso(2026, 8, 17, 11), "Family", null],
  ["Alyssa · Piano lesson", iso(2026, 8, 17, 15), iso(2026, 8, 17, 16), "School", null],
  ["Family · Dinner reservation", iso(2026, 8, 17, 19), iso(2026, 8, 17, 20), "Family", null],
  ["Anthony · Gym", iso(2026, 8, 17, 6), iso(2026, 8, 17, 7), "Sport", null],
  ["Bins out", iso(2026, 8, 17, 7), iso(2026, 8, 17, 7), "Family", null],
];

for (const [title, start, end, label, allDay] of events) {
  await api("POST", `/homes/${homeId}/events`, {
    title,
    start_at: start,
    end_at: end,
    timezone: "Europe/London",
    is_all_day: Boolean(allDay),
    label_id: labels[label] ?? null,
    location_text: null,
    member_ids: [],
  });
}

console.log(`Seeded busy August 2026 calendar for ${email}`);

async function goToAugust() {
  await page.goto(`${BASE}/calendar`);
  await page.waitForTimeout(400);
  // Navigate to August 2026 specifically regardless of "today".
  for (let i = 0; i < 24; i += 1) {
    const heading = await page.locator(".calendar-period").textContent();
    if (heading?.includes("August 2026")) return;
    await page.getByRole("button", { name: "Next period" }).click();
    await page.waitForTimeout(150);
  }
}

const shots = "test-results/evidence";

// 390px month view.
await page.setViewportSize({ width: 390, height: 844 });
await goToAugust();
await page.screenshot({ path: `${shots}/calendar-month-390.png`, fullPage: true });

// 390px day sheet (a busy day).
await page.locator(".calendar-day:not(.outside)").filter({ hasText: "17" }).first().locator(".day-number").click();
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/calendar-day-sheet-390.png` });
await page.keyboard.press("Escape");
await page.waitForTimeout(200);

// 390px event editor (add).
await page.locator(".calendar-fab").click();
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/calendar-editor-390.png` });

// 390px editor with keyboard open (focus the title field to simulate keyboard).
await page.locator('.bottom-sheet input[name="title"]').click();
await page.locator('.bottom-sheet input[name="title"]').fill("Test event while keyboard is open");
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/calendar-editor-keyboard-390.png` });
await page.keyboard.press("Escape");
await page.waitForTimeout(200);

// 768px tablet.
await page.setViewportSize({ width: 768, height: 1024 });
await goToAugust();
await page.screenshot({ path: `${shots}/calendar-month-768.png`, fullPage: true });

// 1440px desktop.
await page.setViewportSize({ width: 1440, height: 960 });
await goToAugust();
await page.screenshot({ path: `${shots}/calendar-month-1440.png`, fullPage: true });

// Overflow measurement at all 5 required widths.
for (const width of [320, 375, 390, 393, 430]) {
  await page.setViewportSize({ width, height: 844 });
  await goToAugust();
  const overflow = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  console.log(`${width}px: clientWidth=${overflow.clientWidth} scrollWidth=${overflow.scrollWidth} overflow=${overflow.scrollWidth - overflow.clientWidth}`);
}

console.log("Screenshots written to", shots);
await browser.close();
