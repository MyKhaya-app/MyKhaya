// Dev-only demo data seed for visual QA of the household product surface.
//
// Creates one household, its home admin, three child members and a set of
// calendar events (today, upcoming, a birthday, a shared household event)
// entirely through the real registration/login/API flow — never by writing
// directly to the database and never by hardcoding fixture JSON into any
// frontend component. Never run this against a shared or production
// environment: it creates a real account and real data.
//
// Usage: node scripts/seed-demo-data.mjs [baseUrl]
// Requires the dev stack to be running (default http://localhost:8080).

import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:8080";
const stamp = Date.now();
const email = `demo-${stamp}@example.com`;
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
await page.fill('input[name="name"]', "Anthony Hales");
await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.fill('input[name="confirm"]', password);
await page.click("button");
await page.waitForURL(/\/login/, { timeout: 10000 });

await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.click("button");
await page.waitForURL(/\/(onboarding|home)/, { timeout: 10000 });

if (page.url().includes("/onboarding")) {
  await page.fill('input[name="name"]', "Hales Home");
  await page.click("button");
  await page.waitForURL(/\/home/, { timeout: 10000 });
}

const homes = (await api("GET", "/groups")).body;
const homeId = homes[0].id;

// Calendar is opt-in per household — turn it on so the seeded events show.
const featureResult = await api("PUT", `/features/${homeId}/calendar/household`, {
  enabled: true,
  reason: "Demo data seed for visual QA",
  confirmed: true,
});
if (featureResult.status >= 400) {
  console.error("Feature toggle failed", featureResult.status, featureResult.body);
  process.exit(1);
}

const members = (await api("GET", `/groups/${homeId}/members`)).body;
const adminMembershipId = members[0].membership_id;

const children = [
  { display_name: "Alyssa Hales", age_band: "under_13" },
  { display_name: "Joshua Hales", age_band: "under_13" },
];
for (const child of children) {
  await api("POST", `/groups/${homeId}/children`, {
    ...child,
    guardian_membership_ids: [adminMembershipId],
  });
}

const labels = {};
for (const [name, color] of [
  ["Sport", "#3B82C4"],
  ["School", "#6FAA5E"],
  ["Family", "#E9B44C"],
]) {
  const created = await api("POST", `/homes/${homeId}/event-labels`, { name, color });
  labels[name] = created.body.id;
}

function iso(daysFromNow, hour, minute = 0) {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + daysFromNow);
  date.setUTCHours(hour, minute, 0, 0);
  return date.toISOString();
}

const events = [
  { title: "Alyssa – Swimming", start: iso(0, 9, 30), end: iso(0, 10, 30), label: "Sport", location: "Sports Centre" },
  { title: "Megan – Yoga", start: iso(0, 15, 30), end: iso(0, 16, 30), label: "Sport", location: "Kings Lynn" },
  { title: "Family Dinner", start: iso(0, 18, 0), end: iso(0, 19, 0), label: "Family", location: "At home" },
  { title: "Football Match", start: iso(1, 10, 0), end: iso(1, 11, 30), label: "Sport", location: "Away" },
  { title: "Parents' Evening", start: iso(2, 17, 0), end: iso(2, 18, 0), label: "School", location: "School hall" },
  { title: "Alyssa's Birthday", start: iso(3, 0, 0), end: iso(4, 0, 0), label: "Family", location: null, allDay: true },
];

for (const event of events) {
  await api("POST", `/homes/${homeId}/events`, {
    title: event.title,
    start_at: event.start,
    end_at: event.end,
    timezone: "Europe/London",
    is_all_day: Boolean(event.allDay),
    label_id: labels[event.label] ?? null,
    location_text: event.location,
    member_ids: [],
  });
}

console.log("Seeded demo household for", email);
console.log("Password:", password);
await browser.close();
