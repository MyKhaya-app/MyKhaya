// Targeted screenshot capture for the calendar density review requested after the
// TimeTree rework. Not a permanent test.
//
// Usage: node scripts/calendar-review-screenshots.mjs [baseUrl]

import { randomUUID } from "node:crypto";
import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:8089";
const stamp = Date.now();
const email = `cal-review-${stamp}@example.com`;
// Freshly random per run — this account is thrown away immediately after,
// so there's no reason to reuse a fixed password across runs.
const password = `Demo-${randomUUID()}`;

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
await page.fill('input[name="name"]', "Cal Review");
await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.fill('input[name="confirm"]', password);
await page.click("button");
await page.waitForURL(/\/(login|verify-email)/, { timeout: 10000 });
if (page.url().includes("/verify-email")) {
  console.log("Email verification is enabled on this stack; run with it disabled.");
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
await api("PUT", `/features/${homeId}/calendar/household`, { enabled: true, confirmed: true });

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
  ["Summer holiday", iso(2026, 8, 10, 0), iso(2026, 8, 13, 0), "Family", "allday"],
  ["School half-term camp", iso(2026, 8, 12, 0), iso(2026, 8, 19, 0), "School", "allday"],
  ["Extended family visiting", iso(2026, 8, 29, 0), iso(2026, 9, 3, 0), "Family", "allday"],
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
  for (let i = 0; i < 24; i += 1) {
    const heading = await page.locator(".calendar-month-label").textContent();
    if (heading?.includes("August 2026")) return;
    await page.getByRole("button", { name: "Next period" }).click();
    await page.waitForTimeout(150);
  }
}

const shots = "test-results/evidence";

// 375px month view.
await page.setViewportSize({ width: 375, height: 812 });
await goToAugust();
await page.screenshot({ path: `${shots}/review-month-375.png`, fullPage: true });

// 390px month view (full page).
await page.setViewportSize({ width: 390, height: 844 });
await goToAugust();
await page.screenshot({ path: `${shots}/review-month-390.png`, fullPage: true });

// 390px: bottom of the viewport (NOT full page) — bottom nav + FAB as actually seen.
await page.screenshot({ path: `${shots}/review-month-390-viewport-bottom.png` });

// 430px month view.
await page.setViewportSize({ width: 430, height: 932 });
await goToAugust();
await page.screenshot({ path: `${shots}/review-month-430.png`, fullPage: true });

// Back to 390 for the interaction shots.
await page.setViewportSize({ width: 390, height: 844 });
await goToAugust();

// 390px busy day sheet.
await page.locator(".calendar-day:not(.outside)").filter({ hasText: "17" }).first().locator(".day-number").click();
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/review-day-sheet-390.png` });
await page.keyboard.press("Escape");
await page.waitForTimeout(250);

// 390px event editor immediately after opening (no field focused, no zoom).
await page.locator(".calendar-fab").click();
await page.waitForTimeout(300);
const scaleAfterOpen = await page.evaluate(() => window.visualViewport?.scale ?? 1);
await page.screenshot({ path: `${shots}/review-editor-open-390.png` });

// 390px event editor with keyboard "active" (title field focused + typing).
await page.locator('.bottom-sheet input[name="title"]').click();
await page.locator('.bottom-sheet input[name="title"]').fill("Test event while keyboard is open");
await page.waitForTimeout(300);
const scaleWithKeyboard = await page.evaluate(() => window.visualViewport?.scale ?? 1);
await page.screenshot({ path: `${shots}/review-editor-keyboard-390.png` });
await page.keyboard.press("Escape");
await page.waitForTimeout(200);

console.log(`visualViewport.scale on open: ${scaleAfterOpen}, with field focused: ${scaleWithKeyboard}`);
console.log("Screenshots written to", shots);
await browser.close();
