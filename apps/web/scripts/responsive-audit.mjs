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

async function auditCopyEvent(page) {
  const copyResults = [];
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`${BASE}/calendar`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await applyInsets(page, viewport);
    await page.waitForTimeout(700);
    const events = page.locator(".month-event, .event-row");
    if (!(await events.count())) {
      copyResults.push({ viewport: viewport.name, result: "NOT TESTED", issues: ["No existing calendar event was available"] });
      continue;
    }

    // Recurring events deliberately cannot be copied. Try the populated
    // fixture events until the first event that supports Copy Event is found,
    // rather than treating a recurring first row as missing coverage. In the
    // wide layout a month-grid event focuses its day, and the day's events
    // are then opened from the side pane's event list.
    let copyButton = page.locator(".bottom-sheet").last().getByRole("button", { name: "Copy event", exact: true });
    const closeSheets = async () => {
      for (let attempt = 0; attempt < 3 && await page.locator(".bottom-sheet").count(); attempt += 1) {
        await page.keyboard.press("Escape").catch(() => {});
        await page.waitForTimeout(100);
      }
    };
    // A click may open the event itself, or (wide layouts) a day sheet or
    // side pane listing that day's events, which are tried in turn.
    const tryOpen = async (target, nested = false) => {
      if (!(await target.isVisible())) return false;
      await target.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(250);
      copyButton = page.locator(".bottom-sheet").last().getByRole("button", { name: "Copy event", exact: true });
      if (await copyButton.count()) return true;
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
      if (await tryOpen(events.nth(eventIndex))) break;
    }
    if (!(await copyButton.count())) {
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

async function writeReport(auth, copyResults) {
  for (const entry of results) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  for (const entry of [...copyResults, ...sheetResults]) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  const rows = results.map((entry) => `<tr class="${entry.result.toLowerCase()}"><td>${escapeHtml(entry.route)}</td><td>${escapeHtml(entry.viewport)}</td><td>${entry.status ?? ""}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.route)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const copyRows = copyResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="Copy Event ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const sheetRows = sheetResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.route)}</td><td>${escapeHtml(entry.title ?? "")}</td><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="">` : ""}</td></tr>`).join("\n");
  const html = `<!doctype html><meta charset="utf-8"><title>MyKhaya Responsive Audit</title><style>body{font:14px system-ui;margin:24px;color:#24312d}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{border:1px solid #d8ded8;padding:8px;vertical-align:top;text-align:left}.pass{background:#edf7ed}.fail{background:#fff0ed}.blocked,.not-tested{background:#fff8df}img{display:block;max-width:320px;max-height:420px;border:1px solid #d8ded8}code{background:#f3f4f1;padding:2px 4px}summary{cursor:pointer}</style><h1>MyKhaya Responsive Audit</h1><p>Base URL: <code>${escapeHtml(BASE)}</code></p><p>Authentication: <strong>${auth.ok ? "PASS" : `BLOCKED — ${escapeHtml(auth.reason)}`}</strong></p><h2>Routes</h2><table><thead><tr><th>Route</th><th>Viewport</th><th>Status</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${rows}</tbody></table><h2>Create sheets</h2><table><thead><tr><th>Route</th><th>Sheet</th><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${sheetRows || `<tr><td colspan="6">No create sheets opened</td></tr>`}</tbody></table><h2>Calendar Copy Event</h2><table><thead><tr><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${copyRows || `<tr><td colspan="4">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Notes</h2><p>Chromium only. Safe areas are simulated through the --safe-* properties; this is not native WKWebView or physical-device evidence.</p><p>BLOCKED means authentication or required data was unavailable. NOT TESTED means the route rendered but the requested interactive component could not be opened. Screenshots are local artifacts under this audit directory.</p>`;
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
await writeReport(auth, copyResults);
await browser.close();
const tally = (entries) => entries.reduce((counts, entry) => ({ ...counts, [entry.result]: (counts[entry.result] ?? 0) + 1 }), {});
console.log(JSON.stringify({ baseUrl: BASE, outputDir, authenticated: auth.ok, authReason: auth.reason ?? null, routes: tally(results), createSheets: tally(sheetResults), copyEvent: tally(copyResults) }, null, 2));
process.exitCode = [...results, ...sheetResults, ...copyResults].some((entry) => entry.result === "FAIL") || !auth.ok ? 1 : 0;
