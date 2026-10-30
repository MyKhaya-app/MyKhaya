// Direct Playwright responsive audit. This intentionally uses the browser API
// rather than @playwright/test because the Windows execution environment can
// launch Chromium but stalls the Playwright test runner worker.
//
// Usage:
//   E2E_EMAIL=... E2E_PASSWORD=... node scripts/responsive-audit.mjs
//   node scripts/responsive-audit.mjs http://localhost:8089
//
// The output directory is test-results/responsive-audit/<timestamp>, which is
// ignored by git. Missing credentials or an MFA hand-off are reported as
// BLOCKED; this script never bypasses or weakens authentication.

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline/promises";
import { chromium } from "@playwright/test";
import { ACCEPTED_CONTAINMENT_EXCEPTIONS, inspectLayoutInPage, INTENDED_HORIZONTAL_SCROLLERS } from "./layout-inspector.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const localEnvPath = path.resolve(scriptDir, "..", ".env.responsive-audit.local");

async function loadLocalEnv() {
  try {
    const contents = await fs.readFile(localEnvPath, "utf8");
    return Object.fromEntries(
      contents
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith("#") && line.includes("="))
        .map((line) => {
          const separator = line.indexOf("=");
          return [line.slice(0, separator).trim(), line.slice(separator + 1).trim()];
        })
        .filter(([key]) => ["E2E_EMAIL", "E2E_PASSWORD", "E2E_MFA_METHOD"].includes(key)),
    );
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

const localEnv = await loadLocalEnv();
const auditEnv = { ...localEnv, ...process.env };
const cliBase = process.argv.slice(2).find((argument) => argument !== "--" && !argument.startsWith("-"));
const checkConfig = process.argv.includes("--check-config");
// localhost, not 127.0.0.1: the local API's trusted origins name localhost,
// and sign-in from any other origin fails with "Request origin is not allowed".
const BASE = cliBase ?? auditEnv.PLAYWRIGHT_BASE_URL ?? "http://localhost:8089";

if (checkConfig) {
  const emailConfigured = Boolean(auditEnv.E2E_EMAIL?.trim());
  const passwordConfigured = Boolean(auditEnv.E2E_PASSWORD);
  const method = auditEnv.E2E_MFA_METHOD?.trim() || "preferred account method";
  if (!["preferred account method", "email", "totp"].includes(method)) {
    console.error("Responsive audit configuration invalid: E2E_MFA_METHOD must be email or totp.");
    process.exitCode = 1;
  } else {
    console.log(`Responsive audit configuration: file=${localEnvPath} email=${emailConfigured ? "SET" : "UNSET"} password=${passwordConfigured ? "SET" : "UNSET"} mfa=${method}`);
  }
  process.exit();
}
const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const outputDir = path.resolve(
  process.env.RESPONSIVE_AUDIT_OUTPUT_DIR ?? path.join("test-results", "responsive-audit"),
  timestamp,
);
const publicRoutes = [
  "/",
  "/about",
  "/login",
  "/login/child",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/signup-choice",
  "/verify-email",
  "/offline",
  "/support",
];
// Service status is no longer a consumer route: About removed its internal
// link and Help & Support uses the configured external status URL. The source
// page remains legacy code, but it is not part of the current route inventory.
const consumerRoutes = [
  "/home",
  "/people",
  "/calendar",
  "/calendar/calendars",
  "/calendar/shared",
  "/meal-plans",
  "/lists",
  "/wish-lists",
  "/driveway",
  "/driveway/add",
  "/budget",
  "/help-support",
  "/me/notifications",
  "/settings",
  "/settings/profile",
  "/settings/home",
  "/settings/members",
  "/settings/security",
  "/settings/notifications",
  "/settings/reminders",
  "/settings/routines",
  "/settings/routines-reminders",
  "/settings/calendar",
  "/settings/calendar-tags",
];
// Safe areas cannot be produced by Chromium (env() is always 0), so each
// profile sets the shared --safe-* custom properties. The Duo insets and
// status overlay zone are the physical measurements in
// docs/engineering/ios-engineering-standards.md section 4; the Duo viewport
// sizes are representative of its native-layout class ranges, not measured.
const viewports = [
  { name: "320x568", width: 320, height: 568, insets: { top: 20 } },
  { name: "375x667", width: 375, height: 667, insets: { top: 20 } },
  { name: "393x852", width: 393, height: 852, insets: { top: 59, bottom: 34 } },
  { name: "430x932", width: 430, height: 932, insets: { top: 59, bottom: 34 } },
  { name: "852x393-landscape", width: 852, height: 393, insets: { left: 59, right: 59, bottom: 21 } },
  { name: "duo-outer-512x740", width: 512, height: 740, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 165 } },
  { name: "duo-inner-900x740", width: 900, height: 740, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 106 } },
  { name: "768x1024", width: 768, height: 1024, insets: {} },
  { name: "1024x768", width: 1024, height: 768, insets: {} },
  { name: "1280x800", width: 1280, height: 800, insets: {} },
  { name: "1440x900", width: 1440, height: 900, insets: {} },
];

const results = [];
const sheetResults = [];
const screenshots = [];

function safeName(value) {
  return value.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "root";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function capture(page, route, viewport, label = route) {
  const filename = `${safeName(label)}-${viewport.name}.png`;
  const filePath = path.join(outputDir, filename);
  await page.screenshot({ path: filePath, fullPage: false });
  screenshots.push({ filename, route: label, viewport: viewport.name });
  return filename;
}

async function applyInsets(page, viewport) {
  const value = (side) => `${viewport.insets?.[side] ?? 0}px`;
  await page.addStyleTag({ content: `:root{--safe-top:${value("top")} !important;--safe-right:${value("right")} !important;--safe-bottom:${value("bottom")} !important;--safe-left:${value("left")} !important}` });
}

// Measures real bounding boxes with scripts/layout-inspector.mjs: children
// against their parents, internal and clipped horizontal overflow, overlap,
// native date/time appearance and, for an open sheet, scroll-to-reveal
// reachability of every control and the header close button against the
// simulated system overlay. Document scroll width alone missed overflow
// inside the clipped, independently scrolling bottom sheet.
async function inspectLayout(page, viewport, activeSheetOnly = false) {
  return page.evaluate(inspectLayoutInPage, {
    rootSelector: activeSheetOnly ? ".bottom-sheet" : null,
    checkReachability: activeSheetOnly,
    overlay: viewport.overlay ?? null,
    intendedScrollers: INTENDED_HORIZONTAL_SCROLLERS,
    acceptedOverflow: ACCEPTED_CONTAINMENT_EXCEPTIONS,
  });
}

const issueText = (issue) => `${issue.kind}: ${issue.element} — ${issue.message}`;

async function promptForMfaCode() {
  if (!process.stdin.isTTY || !process.stdout.isTTY) return null;
  const prompt = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const code = await prompt.question("Enter the current six-digit MFA code (not saved): ");
    return code.trim();
  } finally {
    prompt.close();
  }
}

async function authenticate(page) {
  const email = auditEnv.E2E_EMAIL;
  const password = auditEnv.E2E_PASSWORD;
  if (!email || !password) return { ok: false, reason: "E2E_EMAIL and E2E_PASSWORD are not configured" };
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForTimeout(1200);
  if (page.url().includes("/mfa")) {
    const mfaCode = process.env.E2E_MFA_CODE ?? await promptForMfaCode();
    if (!mfaCode) return { ok: false, reason: "MFA challenge required; provide E2E_MFA_CODE or use an interactive terminal" };
    const requestedMethod = auditEnv.E2E_MFA_METHOD;
    if (requestedMethod === "email" || requestedMethod === "totp") {
      const methodName = requestedMethod === "email" ? "Email code" : "Authenticator app";
      const methodButton = page.getByRole("button", { name: methodName, exact: true });
      if (await methodButton.count()) await methodButton.click();
    }
    await page.getByLabel("Verification code").fill(mfaCode);
    await page.getByRole("button", { name: "Verify", exact: true }).click();
    await page.waitForURL(/\/(home|onboarding)(?:$|\?)/, { timeout: 30000 });
  }
  if (page.url().includes("/onboarding")) return { ok: false, reason: "Account requires onboarding" };
  if (!page.url().match(/\/home(?:$|\?)/)) return { ok: false, reason: "Sign-in did not reach /home" };
  return { ok: true };
}

async function auditRoute(page, route, viewport, authenticated) {
  if (authenticated && route.startsWith("/driveway")) {
    drivewayRouteOwners ??= await drivewayFixtureOwners(page);
    if (drivewayRouteOwners) {
      await routeDriveway(page.context(), { enabled: true, ...drivewayRouteOwners });
      try {
        return await auditRouteOnce(page, route, viewport, authenticated);
      } finally {
        await unrouteDriveway(page.context());
      }
    }
    // Without the fixtures the page shows Driveway's unavailable screen,
    // which is not coverage of Driveway.
    results.push({ route, viewport: viewport.name, result: "NOT TESTED", issues: ["Driveway fixtures unavailable: the account's Home could not be read"], details: [], status: null });
    return;
  }
  return auditRouteOnce(page, route, viewport, authenticated);
}

let drivewayRouteOwners = null;

async function auditRouteOnce(page, route, viewport, authenticated) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const response = await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await applyInsets(page, viewport);
  await page.waitForTimeout(500);
  const screenshot = await capture(page, route, viewport);
  if (!authenticated && !publicRoutes.includes(route)) {
    results.push({ route, viewport: viewport.name, result: "BLOCKED", issues: ["Authenticated route not tested"], details: [], screenshot, status: response?.status() ?? null });
    return;
  }
  const layout = await inspectLayout(page, viewport);
  const status = response?.status() ?? null;
  const statusIssues = status !== null && status >= 400 ? [`HTTP response ${status}`] : [];
  results.push({ route, viewport: viewport.name, result: layout.issues.length || statusIssues.length ? "FAIL" : "PASS", issues: [...statusIssues, ...layout.issues.map(issueText)], details: layout.issues.slice(0, 40), screenshot, status });

  // The route's primary create sheet, opened in this viewport and measured in
  // its interactive state. Nothing is submitted.
  if (!authenticated || publicRoutes.includes(route)) return;
  const trigger = page.locator("button.rr-fab, button.calendar-fab").first();
  if (!(await trigger.count()) || !(await trigger.isVisible())) return;
  await trigger.click({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(350);
  const sheet = page.locator(".bottom-sheet").last();
  if (!(await sheet.count()) || !(await sheet.isVisible())) {
    sheetResults.push({ route, viewport: viewport.name, result: "NOT TESTED", issues: ["Create action did not open a sheet"] });
    return;
  }
  const sheetLayout = await inspectLayout(page, viewport, true);
  const sheetScreenshot = await capture(page, route, viewport, `${route}-create-sheet`);
  const title = (await sheet.locator("#sheet-title").textContent().catch(() => "")) ?? "";
  sheetResults.push({ route, viewport: viewport.name, title, result: sheetLayout.issues.length ? "FAIL" : "PASS", issues: sheetLayout.issues.map(issueText), details: sheetLayout.issues.slice(0, 40), screenshot: sheetScreenshot });
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(150);
}

// Opens existing calendar events in turn until one's sheet offers an enabled
// `action` button (Copy event, Edit). Recurring or shared events may not, so
// a first row without it is not missing coverage. In the wide layout a
// month-grid event focuses its day, and the day's events are then opened
// from the day sheet or side pane. Returns the button, null when no event
// offers it, or undefined when the calendar has no events at all.
async function openEventWithAction(page, action) {
  const events = page.locator(".month-event, .event-row");
  // Events load after the page; a fixed pause alone can miss them on a busy
  // machine and misreport an empty calendar.
  await events.first().waitFor({ state: "attached", timeout: 5000 }).catch(() => {});
  if (!(await events.count())) return undefined;
  const actionButton = () => page.locator(".bottom-sheet").last().getByRole("button", { name: action, exact: true });
  const closeSheets = async () => {
    for (let attempt = 0; attempt < 3 && await page.locator(".bottom-sheet").count(); attempt += 1) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(100);
    }
  };
  const tryOpen = async (target, nested = false) => {
    if (!(await target.isVisible())) return false;
    await target.click({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(250);
    if (await actionButton().count() && !(await actionButton().isDisabled())) return true;
    if (!nested) {
      const dayRows = page.locator(".bottom-sheet .event-row, .calendar-expanded-agenda-section .event-row");
      const rowCount = await dayRows.count();
      for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
        if (await tryOpen(dayRows.nth(rowIndex), true)) return true;
      }
    }
    if (!nested) await closeSheets();
    return false;
  };
  for (let eventIndex = 0; eventIndex < await events.count(); eventIndex += 1) {
    if (await tryOpen(events.nth(eventIndex))) return actionButton();
  }
  return null;
}

// The Calendar event editor in its longest states, measured with
// scroll-to-reveal reachability: Add event with multi-day, the advanced
// disclosure open and a recurrence ending on a date; then Edit on an existing
// event. Nothing is submitted: Add is dismissed and Edit is cancelled.
async function auditEventEditor(page) {
  const editorResults = [];
  for (const viewport of viewports) {
    for (const state of ["add", "edit"]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`${BASE}/calendar`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await applyInsets(page, viewport);
      await page.waitForTimeout(700);
      const issues = [];
      if (state === "add") {
        const add = page.locator("button.calendar-fab:visible, button.calendar-add-desktop:visible").first();
        if (!(await add.count())) {
          editorResults.push({ viewport: viewport.name, state, result: "NOT TESTED", issues: ["No visible Add event action"] });
          continue;
        }
        await add.click({ timeout: 3000 }).catch(() => {});
      } else {
        const edit = await openEventWithAction(page, "Edit");
        if (!edit) {
          editorResults.push({ viewport: viewport.name, state, result: "NOT TESTED", issues: ["No existing event offered Edit"] });
          continue;
        }
        await edit.click();
      }
      await page.waitForTimeout(350);
      const sheet = page.locator(".bottom-sheet").last();
      const form = sheet.locator("form.calendar-event-form");
      if (!(await form.count())) {
        editorResults.push({ viewport: viewport.name, state, result: "FAIL", issues: ["The event editor did not open on the shared form layout"] });
        await page.keyboard.press("Escape").catch(() => {});
        continue;
      }
      await sheet.locator(".event-advanced summary").click();
      if (state === "add") {
        await sheet.getByRole("button", { name: "Ends on another day" }).click();
        await sheet.getByLabel("Repeat", { exact: true }).selectOption("weekly");
        await sheet.locator("select[name=recurrence_end_mode]").selectOption("on_date");
        for (const label of ["Title", "Starts", "Ends", "Start time", "End time", "Calendar", "Location", "Reminder", "End date", "Notes"]) {
          if (!(await sheet.getByLabel(label, { exact: true }).count())) issues.push(`No field labelled "${label}"`);
        }
      }
      await page.waitForTimeout(150);
      const layout = await inspectLayout(page, viewport, true);
      issues.push(...layout.issues.map(issueText));
      const screenshot = await capture(page, `calendar-event-editor-${state}-${viewport.name}`, viewport, `calendar-event-editor-${state}`);
      editorResults.push({ viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
      const cancel = sheet.getByRole("button", { name: "Cancel", exact: true });
      if (await cancel.count()) await cancel.click().catch(() => {});
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(150);
    }
  }
  return editorResults;
}

const LONG_TEXT = "Bring the green recycling box and the garden waste bin to the kerb, then check the side gate is latched so the collection crew can get through without ringing the bell.";

// The Routines & Reminders editors and the Settings forms on the shared form
// primitives, each in a meaningful filled state, plus a failed save. The
// failed save is answered by an intercepted request, so it never reaches the
// API; every other editor is cancelled, so nothing is saved.
async function auditNudgeForms(page) {
  const nudgeResults = [];
  const openEditor = async (kind) => {
    await page.locator("button.rr-fab").click({ timeout: 3000 });
    await page.getByRole("button", { name: `New ${kind}`, exact: true }).click({ timeout: 3000 });
    await page.waitForTimeout(350);
  };
  const requireLabels = async (scope, labels, issues) => {
    for (const label of labels) {
      if (!(await scope.getByLabel(label, { exact: true }).count())) issues.push(`No field labelled "${label}"`);
    }
  };
  const states = [
    ["routine", async (sheet, issues) => {
      await openEditor("Routine");
      await sheet().getByLabel("Description (optional)", { exact: true }).fill(LONG_TEXT);
      await sheet().getByRole("button", { name: "Weekly", exact: true }).click();
      await sheet().getByLabel("Every", { exact: true }).selectOption("2");
      await requireLabels(sheet(), ["Title", "Who this is for", "Category (optional)", "Every", "Anchor date", "Remind", "Starts", "Ends (optional)"], issues);
      return true;
    }],
    ["reminder", async (sheet, issues) => {
      await openEditor("Reminder");
      await sheet().getByLabel("Notes (optional)", { exact: true }).fill(LONG_TEXT);
      await sheet().getByLabel("Scope", { exact: true }).selectOption("household");
      await sheet().getByLabel("Repeat", { exact: true }).selectOption("weekly");
      await sheet().getByLabel("Remind", { exact: true }).selectOption("hourly");
      await requireLabels(sheet(), ["Title", "Scope", "Assign to (household only)", "Category (optional)", "Due date", "Due time", "Repeat", "Remind"], issues);
      return true;
    }],
    ["to-do", async (sheet, issues) => {
      await openEditor("To-do");
      await sheet().getByLabel("Notes (optional)", { exact: true }).fill(LONG_TEXT);
      await sheet().getByLabel("Scope", { exact: true }).selectOption("household");
      await requireLabels(sheet(), ["Title", "Due date", "Scope", "Category (optional)", "Assign to (household only)"], issues);
      return true;
    }],
    ["reminder save error", async (sheet, issues) => {
      await page.route("**/api/v1/homes/*/reminders", (route) => route.request().method() === "POST"
        ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: `The audit rejected this save on purpose. ${LONG_TEXT}` }) })
        : route.continue());
      await openEditor("Reminder");
      await sheet().getByLabel("Title", { exact: true }).fill("Responsive audit reminder");
      await sheet().getByRole("button", { name: "Save", exact: true }).click();
      const error = sheet().locator(".notice.error");
      await error.waitFor({ state: "visible", timeout: 5000 }).catch(() => issues.push("The failed save did not show its error inside the sheet"));
      if (await sheet().getByRole("button", { name: "Save", exact: true }).isDisabled()) issues.push("Save stayed disabled after the failed save");
      if (await sheet().getByRole("button", { name: "Cancel", exact: true }).isDisabled()) issues.push("Cancel stayed disabled after the failed save");
      await error.scrollIntoViewIfNeeded().catch(() => {});
      return true;
    }],
    ["edit", async (sheet, issues) => {
      const edit = page.locator("button.rr-card-action:visible", { hasText: "Edit" }).first();
      if (!(await edit.count())) return false;
      await edit.click({ timeout: 3000 });
      await page.waitForTimeout(350);
      if (!/^Edit /.test((await sheet().locator("#sheet-title").textContent().catch(() => "")) ?? "")) issues.push("Edit did not open an edit sheet");
      return true;
    }],
  ];
  for (const viewport of viewports) {
    for (const [state, prepare] of states) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`${BASE}/settings/routines-reminders`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await applyInsets(page, viewport);
      await page.locator("button.rr-fab").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(500);
      const issues = [];
      const sheet = () => page.locator(".bottom-sheet").last();
      let opened = false;
      try {
        opened = await prepare(sheet, issues);
      } catch (error) {
        issues.push(`Could not prepare the state: ${error.message.split("\n")[0]}`);
      }
      if (!opened) {
        nudgeResults.push({ form: "Routines & Reminders", viewport: viewport.name, state, result: "NOT TESTED", issues: ["No existing item offered Edit"] });
        continue;
      }
      if (!(await sheet().locator("form.rr-form").count())) issues.push("The editor did not open on the shared form layout");
      await page.waitForTimeout(150);
      const layout = await inspectLayout(page, viewport, true);
      issues.push(...layout.issues.map(issueText));
      const screenshot = await capture(page, `nudges-${state}`, viewport, `nudges-${state}`);
      nudgeResults.push({ form: "Routines & Reminders", viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
      const cancel = sheet().getByRole("button", { name: "Cancel", exact: true });
      if (await cancel.count()) await cancel.click().catch(() => {});
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await page.waitForTimeout(150);
    }

    // Settings pages: measured as pages, in their expanded states.
    const pageStates = [
      ["/settings/notifications", "notification preferences (custom times)", async (issues) => {
        await page.getByRole("checkbox", { name: "Send me a daily Nudge summary" }).waitFor({ timeout: 5000 });
        if (!(await page.getByRole("checkbox", { name: "Send me a daily Nudge summary" }).isChecked())) await page.getByRole("checkbox", { name: "Send me a daily Nudge summary" }).check();
        for (const select of await page.getByRole("combobox", { name: "Delivery time", exact: true }).all()) await select.selectOption("custom");
        await requireLabels(page, ["Evening Clean-up time", "Days", "Lock-screen preview", "Start", "End"], issues);
        if ((await page.getByLabel("Custom time", { exact: true }).count()) !== 2) issues.push("Both Custom time fields should be shown");
      }],
      ["/settings/profile", "profile birthday editor", async (issues) => {
        await page.locator(".profile-detail-value").getByRole("button", { name: "Edit" }).click({ timeout: 5000 });
        await requireLabels(page, ["Month", "Day"], issues);
      }],
    ];
    for (const [route, state, prepare] of pageStates) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await applyInsets(page, viewport);
      const issues = [];
      try {
        await prepare(issues);
      } catch (error) {
        issues.push(`Could not prepare the state: ${error.message.split("\n")[0]}`);
      }
      if (!(await page.locator("form.form-layout").count())) issues.push("The form is not on the shared form layout");
      await page.waitForTimeout(150);
      const layout = await inspectLayout(page, viewport);
      issues.push(...layout.issues.map(issueText));
      const screenshot = await capture(page, `${route}-${state}`, viewport, `${route}-${state}`);
      nudgeResults.push({ form: route, viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
    }
  }
  return nudgeResults;
}

// Same-origin API call from the signed-in page, with the CSRF header the API
// requires for writes. Used only to create and remove the audit's own
// disposable fixtures.
function apiCall(page, method, apiPath, body) {
  return page.evaluate(async ({ method, apiPath, body }) => {
    const csrf = document.cookie.split("; ").find((cookie) => cookie.startsWith("mk_csrf="))?.slice(8);
    const headers = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}) };
    const response = await fetch(`/api/v1${apiPath}`, { method, credentials: "include", headers, body: body === undefined ? undefined : JSON.stringify(body) });
    let json = null;
    try { json = await response.json(); } catch { json = null; }
    return { status: response.status, body: json };
  }, { method, apiPath, body });
}

// Driveway is measured against fixtures served in the audit's own browser
// context, so the result does not depend on how the account's Home or the
// platform feature flag is configured, and nothing is written to the API or
// its database. routeDriveway answers the feature matrix's Driveway row, the
// billing entitlement and every /homes/{id}/vehicles request; everything else
// still goes to the real API. With enabled: false it serves Driveway exactly
// as the API does when the feature is off (a 404 for every vehicle request).
const DRIVEWAY_ROUTES = {
  features: /\/api\/v1\/features\/[^/?]+(\?.*)?$/,
  billing: /\/api\/v1\/groups\/[^/]+\/billing(\?.*)?$/,
  vehicles: /\/api\/v1\/homes\/[^/]+\/vehicles(\/[^?]*)?(\?.*)?$/,
};
const AUDIT_VEHICLE_ID = "0aa0d17e-0000-4000-8000-000000000001";

function drivewayFixtureVehicles(homeId, ownerId, otherOwnerId) {
  const vehicle = (overrides) => ({
    group_id: homeId, owner_user_id: ownerId, colour: null, year: null, fuel_type: null, engine_size: null,
    first_registration_date: null, vin: null, lookup_provider: null, lookup_status: null, last_successful_lookup: null,
    tax_status: null, tax_due_date: null, inspection_status: null, inspection_due_date: null, photo_version: null,
    archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  });
  return [
    vehicle({
      id: AUDIT_VEHICLE_ID, nickname: "Responsive audit vehicle", make: "Volkswagen", model: "Golf Estate R-Line Edition",
      colour: "Silver", year: 2019, fuel_type: "Plug-in hybrid", engine_size: "1.4 TSI", country_code: "GB", registration: "AU19 DVW",
      first_registration_date: "2019-03-01", inspection_status: "valid", inspection_due_date: "2026-11-20",
    }),
    // A long make and model, owned by another member when the Home has one.
    vehicle({
      id: "0aa0d17e-0000-4000-8000-000000000002", owner_user_id: otherOwnerId ?? ownerId, nickname: "Family estate",
      make: "Mercedes-Benz", model: "GLE 350 de 4MATIC AMG Line Premium Plus", colour: "Obsidian Black", year: 2021,
      fuel_type: "Plug-in hybrid", country_code: "GB", registration: "LN71 XYZ", inspection_status: "expired", inspection_due_date: "2026-09-01",
    }),
    vehicle({
      id: "0aa0d17e-0000-4000-8000-000000000003", nickname: "Holiday car", make: "Toyota", model: "Yaris", year: 2015,
      fuel_type: "Hybrid", country_code: "IE", registration: "191-D-12345",
    }),
  ];
}

function drivewayFixtureMot(vehicle) {
  const eligible = vehicle.country_code === "GB";
  return {
    eligible, provider_available: false, has_registration: Boolean(vehicle.registration),
    summary: {
      status: eligible ? vehicle.inspection_status : null, due_date: eligible ? vehicle.inspection_due_date : null,
      expiry_date: eligible ? vehicle.inspection_due_date : null, first_mot_due_date: null, last_test_date: null, last_result: null,
      source: null, refreshed_at: null, stale: false, last_attempt_at: null, last_attempt_outcome: null,
    },
    tests: [],
  };
}

async function routeDriveway(context, { enabled, homeId, ownerId, otherOwnerId }) {
  const vehicles = drivewayFixtureVehicles(homeId, ownerId, otherOwnerId);
  const plans = new Map();
  const json = (route, status, body) => route.fulfill({ status, contentType: "application/json", body: body === undefined ? "" : JSON.stringify(body) });
  await context.route(DRIVEWAY_ROUTES.features, async (route) => {
    const response = await route.fetch();
    const matrix = await response.json();
    const existing = matrix.features?.find((row) => row.feature === "driveway") ?? { feature: "driveway" };
    matrix.features = [...(matrix.features ?? []).filter((row) => row.feature !== "driveway"), { ...existing, enabled }];
    await route.fulfill({ response, json: matrix });
  });
  await context.route(DRIVEWAY_ROUTES.billing, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const billing = await response.json();
    await route.fulfill({ response, json: { ...billing, driveway_enabled: true } });
  });
  await context.route(DRIVEWAY_ROUTES.vehicles, async (route) => {
    if (!enabled) return json(route, 404, { detail: "Not found" });
    const request = route.request();
    const method = request.method();
    const [, rest = ""] = new URL(request.url()).pathname.match(/\/vehicles(\/.*)?$/) ?? [];
    const [vehicleId, ...tail] = rest.split("/").filter(Boolean);
    const sub = tail.join("/");
    if (!vehicleId) return method === "GET" ? json(route, 200, { items: vehicles }) : json(route, 201, { ...vehicles[0], ...JSON.parse(request.postData() ?? "{}") });
    if (vehicleId === "lookup") return json(route, 200, { found: false, manual_entry_required: true, provider: null, registration: null, make: null, model: null, colour: null, year: null, fuel_type: null, engine_size: null, first_registration_date: null, tax_status: null, tax_due_date: null, inspection_status: null, inspection_due_date: null, capabilities: [], message: "Lookups are not available in the responsive audit." });
    const vehicle = vehicles.find((item) => item.id === vehicleId);
    if (!vehicle) return json(route, 404, { detail: "That vehicle could not be found" });
    if (!sub) {
      if (method === "GET") return json(route, 200, vehicle);
      if (method === "PATCH") return json(route, 200, { ...vehicle, ...JSON.parse(request.postData() ?? "{}") });
      return json(route, 204);
    }
    if (sub === "mot" || sub === "mot/refresh") return json(route, 200, drivewayFixtureMot(vehicle));
    if (sub === "mot/nudges") {
      if (method === "PUT") {
        const plan = { ...JSON.parse(request.postData() ?? "{}"), scheduled: [] };
        plans.set(vehicleId, plan);
        return json(route, 200, { plan });
      }
      if (method === "DELETE") {
        plans.delete(vehicleId);
        return json(route, 204);
      }
      return json(route, 200, { plan: plans.get(vehicleId) ?? null });
    }
    if (sub === "reminders") return method === "GET" ? json(route, 200, { items: [] }) : json(route, 422, { detail: "Reminders are not created in the responsive audit." });
    return json(route, 404, { detail: "Not found" });
  });
}

async function unrouteDriveway(context) {
  for (const pattern of Object.values(DRIVEWAY_ROUTES)) await context.unroute(pattern);
}

// The account's Home and people, for the fixtures' owners.
async function drivewayFixtureOwners(page) {
  await page.waitForFunction(() => localStorage.getItem("mykhaya.activeHomeId"), null, { timeout: 10000 }).catch(() => {});
  const homeId = await page.evaluate(() => localStorage.getItem("mykhaya.activeHomeId"));
  const me = (await apiCall(page, "GET", "/users/me")).body;
  const members = homeId ? (await apiCall(page, "GET", `/groups/${homeId}/members`)).body : null;
  const otherOwnerId = Array.isArray(members) ? members.find((member) => member.user_id !== me?.id)?.user_id ?? null : null;
  return homeId && me?.id ? { homeId, ownerId: me.id, otherOwnerId } : null;
}

// Driveway's vehicle forms on the shared form primitives, in filled,
// validation-error and failed-save states, on the fixture vehicle. Failed
// saves are answered by intercepted requests; nothing is saved.
async function auditDrivewayForms(page) {
  const drivewayResults = [];
  const states = [
    "vehicle detail page",
    "edit details",
    "edit details validation",
    "edit details failed save",
    "add vehicle validation",
    "MOT nudge validation",
    "MOT nudge failed save",
    "add reminder sheet validation",
    "add reminder sheet failed save",
  ];
  await page.goto(`${BASE}/driveway`, { waitUntil: "domcontentloaded", timeout: 30000 });
  const owners = await drivewayFixtureOwners(page);
  if (!owners) {
    for (const viewport of viewports) for (const state of states) drivewayResults.push({ viewport: viewport.name, state, result: "NOT TESTED", issues: ["The account's Home could not be read for the fixtures"] });
    return drivewayResults;
  }
  await routeDriveway(page.context(), { enabled: true, ...owners });
  const vehicleId = AUDIT_VEHICLE_ID;
  const registration = "AU19 DVW";
  // Page-level routes run before the fixtures; fallback() hands every other
  // request on to them.
  const rejectWith = (method, pattern, message) => page.route(pattern, (route) => route.request().method() === method
    ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: message }) })
    : route.fallback());
  const requireLabels = async (scope, labels, issues) => {
    for (const label of labels) {
      if (!(await scope.getByLabel(label, { exact: true }).count())) issues.push(`No field labelled "${label}"`);
    }
  };
  const requireInvalid = async (scope, labels, issues) => {
    for (const label of labels) {
      const field = scope.getByLabel(label, { exact: true });
      if ((await field.getAttribute("aria-invalid").catch(() => null)) !== "true") issues.push(`"${label}" is not marked invalid`);
    }
  };
  const failedSaveMessage = `The audit rejected this save on purpose. ${LONG_TEXT}`;
  const prepare = {
    "vehicle detail page": async () => ({ url: `/driveway/${vehicleId}`, sheet: false, run: async (issues) => {
      // The detail page names the vehicle by make and model, with its plate.
      await page.getByText(registration, { exact: true }).first().waitFor({ timeout: 8000 }).catch(() => issues.push("The vehicle did not load"));
    } }),
    "edit details": async () => ({ url: `/driveway/${vehicleId}/details`, sheet: false, run: async (issues) => {
      await page.getByRole("button", { name: "Save changes" }).waitFor({ timeout: 8000 });
      await page.getByLabel("Nickname", { exact: true }).fill(`Responsive audit vehicle with a much longer nickname than usual`);
      await requireLabels(page, ["Country / region", "Registration / licence plate", "Owner", "Nickname", "Make", "Model", "Year", "Fuel type", "Colour", "Engine size", "First registration date", "VIN / chassis number"], issues);
    } }),
    "edit details validation": async () => ({ url: `/driveway/${vehicleId}/details`, sheet: false, run: async (issues) => {
      await page.getByRole("button", { name: "Save changes" }).waitFor({ timeout: 8000 });
      await page.getByLabel("Nickname", { exact: true }).fill("");
      await page.getByLabel("Registration / licence plate", { exact: true }).fill("");
      await page.getByLabel("Year", { exact: true }).fill("1800");
      await page.getByRole("button", { name: "Save changes" }).click();
      await requireInvalid(page, ["Registration / licence plate", "Nickname", "Year"], issues);
    } }),
    "edit details failed save": async () => ({ url: `/driveway/${vehicleId}/details`, sheet: false, run: async (issues) => {
      await rejectWith("PATCH", "**/api/v1/homes/*/vehicles/*", failedSaveMessage);
      await page.getByRole("button", { name: "Save changes" }).waitFor({ timeout: 8000 });
      await page.getByRole("button", { name: "Save changes" }).click();
      const alert = page.locator(".notice.error", { hasText: "The audit rejected this save on purpose." });
      await alert.waitFor({ timeout: 5000 }).catch(() => issues.push("The failed save was not shown"));
      if (await page.getByRole("button", { name: "Save changes" }).isDisabled()) issues.push("Save changes stayed disabled");
      await alert.scrollIntoViewIfNeeded().catch(() => {});
    } }),
    "add vehicle validation": async () => ({ url: "/driveway/add", sheet: false, run: async (issues) => {
      await page.getByRole("button", { name: "Add manually" }).click({ timeout: 8000 });
      await page.getByLabel("Year", { exact: true }).fill("1800");
      await page.getByRole("button", { name: "Add vehicle" }).click();
      await requireInvalid(page, ["Registration / licence plate", "Year"], issues);
    } }),
    "MOT nudge validation": async () => ({ url: `/driveway/${vehicleId}/mot/reminder`, sheet: false, run: async (issues) => {
      await page.getByRole("button", { name: "Save nudge" }).waitFor({ timeout: 8000 });
      await page.getByLabel("Reminder", { exact: true }).fill("");
      await page.getByLabel("MOT expires", { exact: true }).fill("");
      for (const name of ["30 days before", "7 days before"]) {
        const chip = page.getByRole("button", { name, exact: true });
        if ((await chip.getAttribute("aria-pressed")) === "true") await chip.click();
      }
      await page.getByRole("button", { name: "Save nudge" }).click();
      await requireInvalid(page, ["Reminder", "MOT expires"], issues);
      if (!(await page.getByText("Choose at least one time to be nudged.").count())) issues.push("No error for the Nudge me times");
    } }),
    "MOT nudge failed save": async () => ({ url: `/driveway/${vehicleId}/mot/reminder`, sheet: false, run: async (issues) => {
      await rejectWith("PUT", "**/api/v1/homes/*/vehicles/*/mot/nudges", failedSaveMessage);
      await page.getByRole("button", { name: "Save nudge" }).waitFor({ timeout: 8000 });
      await page.getByLabel("MOT expires", { exact: true }).fill("2027-08-25");
      await page.getByRole("button", { name: "Save nudge" }).click();
      const alert = page.locator(".notice.error", { hasText: "The audit rejected this save on purpose." });
      await alert.waitFor({ timeout: 5000 }).catch(() => issues.push("The failed save was not shown"));
      await alert.scrollIntoViewIfNeeded().catch(() => {});
    } }),
    "add reminder sheet validation": async () => ({ url: `/driveway/${vehicleId}/reminders`, sheet: true, run: async (issues) => {
      await page.getByRole("button", { name: /add reminder/i }).first().click({ timeout: 8000 });
      await page.waitForTimeout(350);
      const sheet = page.locator(".bottom-sheet").last();
      await sheet.getByRole("button", { name: "Add reminder", exact: true }).click();
      await requireInvalid(sheet, ["Title", "Due date"], issues);
    } }),
    "add reminder sheet failed save": async () => ({ url: `/driveway/${vehicleId}/reminders`, sheet: true, run: async (issues) => {
      await rejectWith("POST", "**/api/v1/homes/*/vehicles/*/reminders", failedSaveMessage);
      await page.getByRole("button", { name: /add reminder/i }).first().click({ timeout: 8000 });
      await page.waitForTimeout(350);
      const sheet = page.locator(".bottom-sheet").last();
      await sheet.getByLabel("Title", { exact: true }).fill("Responsive audit reminder");
      await sheet.getByLabel("Due date", { exact: true }).fill("2027-01-15");
      await sheet.getByRole("button", { name: "Add reminder", exact: true }).click();
      await sheet.locator(".notice.error").waitFor({ timeout: 5000 }).catch(() => issues.push("The failed save was not shown inside the sheet"));
      if (await sheet.getByRole("button", { name: "Cancel", exact: true }).isDisabled()) issues.push("Cancel stayed disabled after the failed save");
      if ((await sheet.getByLabel("Title", { exact: true }).inputValue()) !== "Responsive audit reminder") issues.push("The draft was not kept");
    } }),
  };
  try {
    for (const viewport of viewports) {
      for (const state of states) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        const { url, sheet, run } = await prepare[state]();
        await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
        await applyInsets(page, viewport);
        await page.waitForTimeout(500);
        const issues = [];
        try {
          await run(issues);
        } catch (error) {
          issues.push(`Could not prepare the state: ${error.message.split("\n")[0]}`);
        }
        await page.waitForTimeout(200);
        const layout = await inspectLayout(page, viewport, sheet);
        issues.push(...layout.issues.map(issueText));
        const screenshot = await capture(page, `driveway-${state}`, viewport, `driveway-${state}`);
        drivewayResults.push({ viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
        await page.unrouteAll({ behavior: "ignoreErrors" });
        if (sheet) {
          const cancel = page.locator(".bottom-sheet").last().getByRole("button", { name: "Cancel", exact: true });
          if (await cancel.count()) await cancel.click().catch(() => {});
        }
      }
    }
  } finally {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await unrouteDriveway(page.context());
  }
  return drivewayResults;
}

// Driveway turned off for the Home: the overview shows that it is not
// available, and a vehicle's pages offer no form. These states pass only when
// the unavailable screen is what renders; they are never counted as coverage
// of the forms above.
async function auditDrivewayDisabled(page) {
  const disabledResults = [];
  await page.goto(`${BASE}/driveway`, { waitUntil: "domcontentloaded", timeout: 30000 });
  const owners = await drivewayFixtureOwners(page);
  const states = ["overview unavailable", "vehicle details unavailable"];
  if (!owners) {
    for (const viewport of viewports) for (const state of states) disabledResults.push({ viewport: viewport.name, state, result: "NOT TESTED", issues: ["The account's Home could not be read for the fixtures"] });
    return disabledResults;
  }
  await routeDriveway(page.context(), { enabled: false, ...owners });
  try {
    for (const viewport of viewports) {
      for (const state of states) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        const url = state === "overview unavailable" ? "/driveway" : `/driveway/${AUDIT_VEHICLE_ID}/details`;
        await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
        await applyInsets(page, viewport);
        const issues = [];
        const expected = state === "overview unavailable" ? /Driveway isn.t available for this Home/ : /That vehicle could not be found/;
        await page.getByText(expected).first().waitFor({ timeout: 8000 }).catch(() => issues.push("The unavailable message was not shown"));
        if (await page.locator(".drv-cards, form.vehicle-form").count()) issues.push("Vehicles or a form were shown while Driveway is off");
        await page.waitForTimeout(150);
        const layout = await inspectLayout(page, viewport);
        issues.push(...layout.issues.map(issueText));
        const screenshot = await capture(page, `driveway-disabled-${state}`, viewport, `driveway-disabled-${state}`);
        disabledResults.push({ viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
      }
    }
  } finally {
    await unrouteDriveway(page.context());
  }
  return disabledResults;
}

// The sign-in screen's states, each in a fresh signed-out browser context so
// the state is set up deliberately rather than inherited from the host:
// whether /login shows the remembered-account screen depends on a local
// sign-in hint and on the browser reporting a platform authenticator, which
// headless Chromium does or does not depending on the machine. The
// remembered-account state uses a mocked hint and a virtual WebAuthn
// authenticator; no real account, passkey or credential is involved.
async function auditSignInStates(browser) {
  const signInResults = [];
  const states = ["password sign-in", "password shown", "remembered account"];
  for (const viewport of viewports) {
    for (const state of states) {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
      const page = await context.newPage();
      const issues = [];
      try {
        if (state === "remembered account") {
          try {
            const cdp = await context.newCDPSession(page);
            await cdp.send("WebAuthn.enable");
            await cdp.send("WebAuthn.addVirtualAuthenticator", {
              options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true },
            });
          } catch (error) {
            // The state cannot be set up in this browser: not tested, not passed.
            signInResults.push({ viewport: viewport.name, state, result: "NOT TESTED", issues: [`No virtual authenticator: ${error.message.split("\n")[0]}`] });
            continue;
          }
          await context.addInitScript(() => {
            window.localStorage.setItem("mk_biometric_hint", JSON.stringify({ userId: "00000000-0000-0000-0000-000000000000", displayName: "Audit Example", avatarVersion: null }));
          });
        }
        await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 30000 });
        await applyInsets(page, viewport);
        if (state === "remembered account") {
          await page.getByRole("button", { name: "Sign in another way" }).waitFor({ timeout: 8000 });
          if (!(await page.getByText("Audit Example").count())) issues.push("The remembered account was not shown");
          if (await page.locator("#signin-password").count()) issues.push("The password form showed instead of the remembered account");
        } else {
          const password = page.locator("#signin-password");
          await password.waitFor({ timeout: 8000 });
          const toggle = page.getByRole("button", { name: "Show password" });
          if (!(await toggle.count())) issues.push('No "Show password" control');
          if (state === "password shown") {
            await password.fill("not-a-real-password");
            await toggle.click();
            if ((await password.getAttribute("type")) !== "text") issues.push("Show password did not reveal the password");
            if (!(await page.getByRole("button", { name: "Hide password" }).count())) issues.push('The control was not renamed "Hide password"');
          }
        }
        await page.waitForTimeout(150);
        const layout = await inspectLayout(page, viewport);
        issues.push(...layout.issues.map(issueText));
        const screenshot = await capture(page, `signin-${state}`, viewport, `signin-${state}`);
        signInResults.push({ viewport: viewport.name, state, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
      } catch (error) {
        // Set up deliberately, so a state that does not appear is a failure.
        signInResults.push({ viewport: viewport.name, state, result: "FAIL", issues: [`The state did not appear: ${error.message.split("\n")[0]}`] });
      } finally {
        await context.close();
      }
    }
  }
  return signInResults;
}

async function auditCopyEvent(page) {
  const copyResults = [];
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`${BASE}/calendar`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await applyInsets(page, viewport);
    await page.waitForTimeout(700);
    const copyButton = await openEventWithAction(page, "Copy event");
    if (copyButton === undefined) {
      copyResults.push({ viewport: viewport.name, result: "NOT TESTED", issues: ["No existing calendar event was available"] });
      continue;
    }
    if (!copyButton) {
      copyResults.push({ viewport: viewport.name, result: "NOT TESTED", issues: ["No populated non-recurring event exposed Copy event"] });
      continue;
    }
    await copyButton.click();
    await page.waitForTimeout(250);
    const copySheet = page.locator(".bottom-sheet").last();
    const dateInputs = copySheet.locator('input[type="date"]');
    const addDate = copySheet.getByRole("button", { name: /Add another date/i });
    const issues = [];
    if (await dateInputs.count() !== 1) issues.push("Expected one empty initial destination row");
    if (await dateInputs.count() && await dateInputs.nth(0).inputValue()) issues.push("Initial destination date was preselected");
    const initialCopyButton = copySheet.getByRole("button", { name: "Copy event", exact: true });
    if (await initialCopyButton.count() && !(await initialCopyButton.isDisabled())) issues.push("Copy action was enabled before a destination date was selected");
    if (await dateInputs.count() && await addDate.count()) {
      await dateInputs.nth(0).fill("2030-11-07");
      if (await dateInputs.nth(0).inputValue() !== "2030-11-07") issues.push("Changing the primary destination date did not replace its value");
      await dateInputs.nth(0).fill("2030-11-05");
      const firstTimes = copySheet.locator('input[type="time"]');
      if (await firstTimes.count() === 2) {
        await firstTimes.nth(0).fill("15:00");
        await firstTimes.nth(1).fill("23:00");
      }
      await addDate.click();
      await page.waitForTimeout(100);
      const rowsAfterAdd = copySheet.locator('input[type="date"]');
      if (await rowsAfterAdd.count() !== 2) issues.push("Add another date did not create an independent row");
      if (await rowsAfterAdd.count() >= 2) await rowsAfterAdd.nth(1).fill("2030-11-07");
      const secondTimes = copySheet.locator('input[type="time"]');
      if (await secondTimes.count() === 4) {
        await secondTimes.nth(2).fill("16:00");
        await secondTimes.nth(3).fill("22:00");
      }
      const remove = copySheet.getByRole("button", { name: /Remove destination/i });
      if (await remove.count()) {
        await remove.last().click();
        await page.waitForTimeout(100);
        if (await copySheet.locator('input[type="date"]').count() !== 1) issues.push("Removing a destination did not preserve the primary row");
        await addDate.click();
        await copySheet.locator('input[type="date"]').nth(1).fill("2030-11-07");
        const restoredTimes = copySheet.locator('input[type="time"]');
        if (await restoredTimes.count() === 4) {
          await restoredTimes.nth(2).fill("16:00");
          await restoredTimes.nth(3).fill("22:00");
        }
      }
    }
    const timeInputs = copySheet.locator('input[type="time"]');
    if (await timeInputs.count() !== 4) issues.push("Expected independent start/end inputs for both destination rows");
    if (!(await copySheet.getByRole("button", { name: /Copy event \(2\)/i }).count())) issues.push("Multiple destination action was not enabled");
    // A third row exercises sheet scrolling and footer clearance.
    if (await addDate.count()) await addDate.click();
    const layout = await inspectLayout(page, viewport, true);
    issues.push(...layout.issues.map(issueText));
    const screenshot = await capture(page, `calendar-copy-event-${viewport.name}`, viewport, "calendar-copy-event");
    copyResults.push({ viewport: viewport.name, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.issues.slice(0, 40) });
    await page.keyboard.press("Escape").catch(() => {});
  }
  return copyResults;
}

async function writeReport(auth, copyResults, editorResults, nudgeResults, drivewayResults, drivewayDisabledResults, signInResults) {
  for (const entry of results) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  for (const entry of [...copyResults, ...editorResults, ...nudgeResults, ...drivewayResults, ...drivewayDisabledResults, ...signInResults, ...sheetResults]) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  const rows = results.map((entry) => `<tr class="${entry.result.toLowerCase()}"><td>${escapeHtml(entry.route)}</td><td>${escapeHtml(entry.viewport)}</td><td>${entry.status ?? ""}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.route)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const copyRows = copyResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="Copy Event ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const editorRows = editorResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.state)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="Event editor ${escapeHtml(entry.state)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const nudgeRows = nudgeResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.form)}</td><td>${escapeHtml(entry.state)}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.state)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const drivewayRows = drivewayResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.state)}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.state)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const drivewayDisabledRows = drivewayDisabledResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.state)}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.state)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const signInRows = signInResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.state)}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.state)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const sheetRows = sheetResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.route)}</td><td>${escapeHtml(entry.title ?? "")}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="">` : ""}</td></tr>`).join("\n");
  const html = `<!doctype html><meta charset="utf-8"><title>MyKhaya Responsive Audit</title><style>body{font:14px system-ui;margin:24px;color:#24312d}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{border:1px solid #d8ded8;padding:8px;vertical-align:top;text-align:left}.pass{background:#edf7ed}.fail{background:#fff0ed}.blocked,.not-tested{background:#fff8df}img{display:block;max-width:320px;max-height:420px;border:1px solid #d8ded8}code{background:#f3f4f1;padding:2px 4px}summary{cursor:pointer}</style><h1>MyKhaya Responsive Audit</h1><p>Base URL: <code>${escapeHtml(BASE)}</code></p><p>Authentication: <strong>${auth.ok ? "PASS" : `BLOCKED — ${escapeHtml(auth.reason)}`}</strong></p><h2>Routes</h2><table><thead><tr><th>Route</th><th>Viewport</th><th>Status</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${rows}</tbody></table><h2>Create sheets</h2><table><thead><tr><th>Route</th><th>Sheet</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${sheetRows || `<tr><td colspan="6">No create sheets opened</td></tr>`}</tbody></table><h2>Calendar Copy Event</h2><table><thead><tr><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${copyRows || `<tr><td colspan="4">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Calendar event editor</h2><table><thead><tr><th>Viewport</th><th>State</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${editorRows || `<tr><td colspan="5">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Routines, Reminders and Settings forms</h2><table><thead><tr><th>Form</th><th>State</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${nudgeRows || `<tr><td colspan="6">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Driveway forms</h2><table><thead><tr><th>State</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${drivewayRows || `<tr><td colspan="5">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Driveway turned off</h2><table><thead><tr><th>State</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${drivewayDisabledRows || `<tr><td colspan="5">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Sign-in states</h2><table><thead><tr><th>State</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${signInRows || `<tr><td colspan="5">No results</td></tr>`}</tbody></table><h2>Notes</h2><p>Chromium only. Safe areas are simulated through the --safe-* properties; this is not native WKWebView or physical-device evidence.</p><p>BLOCKED means authentication or required data was unavailable. NOT TESTED means the route rendered but the requested interactive component could not be opened. Screenshots are local artifacts under this audit directory.</p>`;
  await fs.writeFile(path.join(outputDir, "index.html"), html, "utf8");
}

await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
const auth = await authenticate(page).catch((error) => ({ ok: false, reason: `Authentication error: ${error.message}` }));
const routes = [...publicRoutes, ...consumerRoutes.filter((route) => !publicRoutes.includes(route))];
for (const viewport of viewports) {
  for (const route of routes) await auditRoute(page, route, viewport, auth.ok);
  // Kept current after every viewport, so an interrupted run still leaves
  // its measurements behind.
  await fs.writeFile(path.join(outputDir, "results.partial.json"), JSON.stringify({ results, sheetResults }, null, 2));
}
const copyResults = auth.ok ? await auditCopyEvent(page) : [];
const editorResults = auth.ok ? await auditEventEditor(page) : [];
const nudgeResults = auth.ok ? await auditNudgeForms(page) : [];
const drivewayResults = auth.ok ? await auditDrivewayForms(page) : [];
const drivewayDisabledResults = auth.ok ? await auditDrivewayDisabled(page) : [];
const signInResults = await auditSignInStates(browser);
await writeReport(auth, copyResults, editorResults, nudgeResults, drivewayResults, drivewayDisabledResults, signInResults);
await browser.close();
const tally = (entries) => entries.reduce((counts, entry) => ({ ...counts, [entry.result]: (counts[entry.result] ?? 0) + 1 }), {});
console.log(JSON.stringify({ baseUrl: BASE, outputDir, authenticated: auth.ok, authReason: auth.reason ?? null, routes: tally(results), createSheets: tally(sheetResults), copyEvent: tally(copyResults), eventEditor: tally(editorResults), nudgeForms: tally(nudgeResults), drivewayForms: tally(drivewayResults), drivewayDisabled: tally(drivewayDisabledResults), signIn: tally(signInResults) }, null, 2));
process.exitCode = [...results, ...sheetResults, ...copyResults, ...editorResults, ...nudgeResults, ...drivewayResults, ...drivewayDisabledResults, ...signInResults].some((entry) => entry.result === "FAIL") || !auth.ok ? 1 : 0;
