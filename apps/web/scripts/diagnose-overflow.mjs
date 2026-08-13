// Runtime DOM-overflow diagnostic. Not a permanent test — throwaway investigation
// tool for finding the actual offending element(s) at mobile widths.
//
// Usage: node scripts/diagnose-overflow.mjs [baseUrl]
// Requires the dev stack running (default http://localhost:8089).

import { execSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:8089";
const WIDTHS = [320, 375, 390, 393, 430];
const stamp = Date.now();
const email = `overflow-diag-${stamp}@example.com`;
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

page.on("console", (msg) => console.log("PAGE CONSOLE:", msg.type(), msg.text()));
page.on("pageerror", (err) => console.log("PAGE ERROR:", err.message));
page.on("requestfailed", (req) => console.log("REQUEST FAILED:", req.url(), req.failure()?.errorText));

// A deliberately long household name — this was the last known overflow trigger
// (the header truncation fix), kept in to confirm it's actually fixed and not the
// remaining cause.
await page.goto(`${BASE}/register`);
await page.waitForLoadState("networkidle");
await page.fill('input[name="name"]', "Anthony Hales");
await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.fill('input[name="confirm"]', password);
await page.click("button");
try {
  await page.waitForURL(/\/(login|verify-email)/, { timeout: 10000 });
} catch (cause) {
  console.log("DEBUG url:", page.url());
  console.log("DEBUG body:", (await page.textContent("body")).slice(0, 500));
  throw cause;
}

if (page.url().includes("/verify-email")) {
  // This dev stack has email verification enabled — pull the raw token straight out
  // of the api container's DB rather than driving Mailpit through the UI, purely to
  // unblock the layout diagnostic below.
  const script = `
import asyncio
from sqlalchemy import select
from mykhaya.db import SessionFactory
from mykhaya.models import ActionToken, TokenPurpose, User
from mykhaya.security import derived_token
from mykhaya.config import get_settings

async def main():
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == "${email}"))
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        raw = derived_token(token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value())
        print(raw)

asyncio.run(main())
`;
  const raw = execSync(
    `docker compose -f compose.yml -f compose.dev.yml -f compose.override.yml exec -T api python3 -c "${script.replace(/"/g, '\\"')}"`,
    { cwd: "../..", encoding: "utf-8" },
  ).trim();
  await page.goto(`${BASE}/verify-email?token=${encodeURIComponent(raw)}`);
  await page.waitForTimeout(500);
  await page.goto(`${BASE}/login`);
}

await page.fill('input[name="email"]', email);
await page.fill('input[name="password"]', password);
await page.click("button");
await page.waitForURL(/\/(onboarding|home)/, { timeout: 10000 });

if (page.url().includes("/onboarding")) {
  await page.fill('input[name="name"]', "The Extended Hales-Worthington Household");
  await page.click("button");
  await page.waitForURL(/\/home/, { timeout: 10000 });
}

const homes = (await api("GET", "/groups")).body;
const homeId = homes[0].id;

await api("PUT", `/features/${homeId}/calendar/household`, {
  enabled: true,
  reason: "Overflow diagnostic",
  confirmed: true,
});

const members = (await api("GET", `/groups/${homeId}/members`)).body;
const adminMembershipId = members[0].membership_id;

await api("POST", `/groups/${homeId}/children`, {
  display_name: "Alexandria Worthington-Hales",
  age_band: "under_13",
  guardian_membership_ids: [adminMembershipId],
});

// Birthday this month so the birthday card actually renders on Home.
const today = new Date();
await api("PUT", "/users/me/birthday", {
  birth_month: today.getUTCMonth() + 1,
  birth_day: Math.min(28, today.getUTCDate() + 3),
});

await api("POST", `/homes/${homeId}/events`, {
  title: "A Reasonably Long Family Calendar Event Title For Testing",
  start_at: new Date(Date.now() + 3600_000).toISOString(),
  end_at: new Date(Date.now() + 7200_000).toISOString(),
  timezone: "Europe/London",
  is_all_day: false,
  label_id: null,
  location_text: "Somewhere with a fairly long location name",
  member_ids: [],
});

console.log(`Seeded diagnostic account: ${email} / ${password} (home: ${homeId})`);

const routes = [
  ["Home", "/home"],
  ["Family", "/people"],
  ["Notifications", "/settings/notifications"],
  ["Child profile creation", "/khaya-control-centre/children"],
];

const overflowFinder = () => {
  const results = [];
  const vw = window.innerWidth;
  const docEl = document.documentElement;
  const summary = {
    innerWidth: window.innerWidth,
    clientWidth: docEl.clientWidth,
    scrollWidth: docEl.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    scrollX: window.scrollX,
  };
  const all = document.querySelectorAll("body *");
  for (const el of all) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const overflowsRight = rect.right > vw + 0.5;
    const overflowsLeft = rect.left < -0.5;
    const innerScroll = el.scrollWidth > el.clientWidth + 1;
    if (overflowsRight || overflowsLeft || innerScroll) {
      let selector = el.tagName.toLowerCase();
      if (el.id) selector += `#${el.id}`;
      if (el.className && typeof el.className === "string") {
        selector += `.${el.className.trim().split(/\s+/).join(".")}`;
      }
      // A short ancestor chain to localise it precisely.
      const chain = [];
      let node = el;
      for (let i = 0; i < 4 && node && node !== document.body; i += 1) {
        const cls =
          typeof node.className === "string" && node.className
            ? `.${node.className.trim().split(/\s+/).join(".")}`
            : "";
        chain.unshift(`${node.tagName.toLowerCase()}${cls}`);
        node = node.parentElement;
      }
      results.push({
        selector,
        chain: chain.join(" > "),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        overflowsRight,
        overflowsLeft,
        innerScroll,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        text: (el.textContent || "").trim().slice(0, 40),
      });
    }
  }
  return { summary, results };
};

for (const [label, path] of routes) {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`${BASE}${path}`);
    await page.waitForTimeout(600);
    const { summary, results } = await page.evaluate(overflowFinder);
    const overflowAmount = summary.scrollWidth - summary.clientWidth;
    console.log(`\n=== ${label} @ ${width}px ===`);
    console.log(JSON.stringify(summary));
    console.log(`document overflow (scrollWidth - clientWidth): ${overflowAmount}`);
    if (overflowAmount > 0 && results.length) {
      console.log(`offending elements (${results.length}):`);
      for (const r of results.slice(0, 15)) {
        console.log(
          `  [${r.overflowsRight ? "R" : ""}${r.overflowsLeft ? "L" : ""}${r.innerScroll ? "S" : ""}] ` +
            `left=${r.left} right=${r.right} width=${r.width} scrollWidth=${r.scrollWidth} clientWidth=${r.clientWidth}\n` +
            `      ${r.chain}\n      text="${r.text}"`,
        );
      }
      await page.screenshot({
        path: `test-results/evidence/overflow-${label.toLowerCase().replace(/\s+/g, "-")}-${width}.png`,
        fullPage: true,
      });
    } else if (overflowAmount > 0) {
      console.log("  (document overflows but no single element matched the heuristics)");
    }
  }
}

// Scroll-position preservation across client-side route navigation.
console.log("\n=== Scroll position across navigation ===");
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE}/home`);
await page.waitForTimeout(500);
await page.evaluate(() => window.scrollTo(500, 300)); // force an artificial horizontal offset
const beforeNav = await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY }));
await page.getByRole("link", { name: /family|household/i }).first().click().catch(() => {});
await page.waitForTimeout(500);
const afterNav = await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY, url: location.pathname }));
console.log("before nav (forced offset):", beforeNav);
console.log("after nav:", afterNav);

await browser.close();
