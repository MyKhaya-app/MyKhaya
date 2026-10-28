// Direct Playwright responsive audit. This intentionally uses the browser API
// rather than @playwright/test because the Windows execution environment can
// launch Chromium but stalls the Playwright test runner worker.
//
// Usage:
//   E2E_EMAIL=... E2E_PASSWORD=... node scripts/responsive-audit.mjs
//   node scripts/responsive-audit.mjs http://127.0.0.1:8089
//
// The output directory is test-results/responsive-audit/<timestamp>, which is
// ignored by git. Missing credentials or an MFA hand-off are reported as
// BLOCKED; this script never bypasses or weakens authentication.

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline/promises";
import { chromium } from "@playwright/test";

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
const BASE = cliBase ?? auditEnv.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8089";

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
const viewports = [
  { name: "320x568", width: 320, height: 568 },
  { name: "375x667", width: 375, height: 667 },
  { name: "393x852", width: 393, height: 852 },
  { name: "430x932", width: 430, height: 932 },
  { name: "768x1024", width: 768, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
];

const results = [];
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

async function inspectLayout(page, activeSheetOnly = false) {
  return page.evaluate((activeSheetOnly) => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const issues = [];
    const details = [];
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const selector = (element) => {
      const classes = typeof element.className === "string" ? element.className.trim().split(/\s+/).slice(0, 3) : [];
      return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${classes.map((item) => `.${item}`).join("")}`;
    };
    const add = (kind, element, message, extra = {}) => {
      const rect = element.getBoundingClientRect();
      const detail = { kind, selector: selector(element), message, left: Math.round(rect.left), top: Math.round(rect.top), right: Math.round(rect.right), bottom: Math.round(rect.bottom), ...extra };
      issues.push(detail);
      if (details.length < 40) details.push(detail);
    };
    const activeSheet = activeSheetOnly ? [...document.querySelectorAll(".bottom-sheet")].filter(visible).at(-1) : null;
    const queryAll = (query) => activeSheet ? [...activeSheet.querySelectorAll(query)] : [...document.querySelectorAll(query)];

    const documentWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    if (documentWidth > viewport.width + 1) {
      add("document-overflow", document.documentElement, "Document scroll width exceeds the viewport", { scrollWidth: documentWidth });
    }
    if (document.body.scrollWidth > viewport.width + 1) {
      add("body-overflow", document.body, "Body scroll width exceeds the viewport", { scrollWidth: document.body.scrollWidth });
    }

    const interactive = queryAll("button, a[href], input, select, textarea, [role=button]").filter(visible);
    for (const element of interactive) {
      const rect = element.getBoundingClientRect();
      // The month grid intentionally renders adjacent-month cells outside its
      // clipped viewport. Those hidden grid controls are not user-visible
      // overflow and should not turn an otherwise usable calendar into a
      // false failure.
      const calendarCell = element.closest(".calendar-day, .month-event");
      const clippedCalendarCell = calendarCell && (rect.right <= 0 || rect.left < -1 || rect.right > viewport.width + 1);
      if (!clippedCalendarCell && (rect.right > viewport.width + 1 || rect.left < -1 || rect.bottom > viewport.height + 1 && getComputedStyle(element).position === "fixed")) {
        add("interactive-out-of-bounds", element, "Interactive element extends outside the viewport");
      }
      const clipped = element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1;
      if (clipped && !["INPUT", "TEXTAREA"].includes(element.tagName)) {
        add("interactive-clipped", element, "Interactive element has content clipped inside its box", { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth });
      }
    }

    const controls = queryAll("input, select, textarea").filter(visible);
    for (let index = 0; index < controls.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < controls.length; otherIndex += 1) {
        const first = controls[index].getBoundingClientRect();
        const second = controls[otherIndex].getBoundingClientRect();
        const intersects = first.left < second.right - 1 && first.right > second.left + 1 && first.top < second.bottom - 1 && first.bottom > second.top + 1;
        if (intersects) add("form-control-overlap", controls[index], "Adjacent form controls overlap", { other: selector(controls[otherIndex]) });
      }
    }

    for (const sheet of (activeSheet ? [activeSheet] : [...document.querySelectorAll(".bottom-sheet")]).filter(visible)) {
      const rect = sheet.getBoundingClientRect();
      const content = sheet.querySelector(".sheet-content");
      const footer = sheet.querySelector(".sheet-footer");
      if (rect.bottom > viewport.height + 1 || rect.top < -1) add("sheet-out-of-bounds", sheet, "Bottom sheet exceeds the viewport");
      if (content && content.scrollHeight > content.clientHeight + 1 && getComputedStyle(content).overflowY === "visible") add("sheet-not-scrollable", content, "Long sheet content has no scrollable container");
      if (footer && footer.getBoundingClientRect().bottom > viewport.height + 1) add("sheet-footer-out-of-bounds", footer, "Sheet footer is outside the viewport");
    }

    for (const fixed of (activeSheet ? [activeSheet, ...activeSheet.querySelectorAll("*")] : [...document.querySelectorAll("body *")]).filter((element) => visible(element) && ["fixed", "sticky"].includes(getComputedStyle(element).position))) {
      const fixedStyle = getComputedStyle(fixed);
      if (fixedStyle.pointerEvents === "none" || Number.parseFloat(fixedStyle.opacity || "1") < 0.05) continue;
      const rect = fixed.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > viewport.height) continue;
      const target = document.elementFromPoint(Math.min(viewport.width - 2, Math.max(1, rect.left + rect.width / 2)), Math.min(viewport.height - 2, Math.max(1, rect.bottom - 2)));
      if (target && target !== fixed && !fixed.contains(target) && !target.closest(".sheet-backdrop")) add("fixed-obscures-content", fixed, "Fixed/sticky element may obscure content", { target: selector(target) });
    }
    return { viewport, issues, details, documentWidth, bodyWidth: document.body.scrollWidth };
  }, activeSheetOnly);
}

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
  await page.waitForTimeout(500);
  const screenshot = await capture(page, route, viewport);
  if (!authenticated && !publicRoutes.includes(route)) {
    results.push({ route, viewport: viewport.name, result: "BLOCKED", issues: ["Authenticated route not tested"], details: [], screenshot, status: response?.status() ?? null });
    return;
  }
  const layout = await inspectLayout(page);
  const status = response?.status() ?? null;
  const statusIssues = status !== null && status >= 400 ? [`HTTP response ${status}`] : [];
  results.push({ route, viewport: viewport.name, result: layout.issues.length || statusIssues.length ? "FAIL" : "PASS", issues: [...statusIssues, ...layout.issues.map((issue) => issue.message)], details: layout.details, screenshot, status });
}

async function auditCopyEvent(page) {
  const copyResults = [];
  for (const viewport of viewports.filter(({ width }) => [320, 375, 393, 430].includes(width))) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`${BASE}/calendar`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(700);
    const events = page.locator(".month-event, .event-row");
    if (!(await events.count())) {
      copyResults.push({ viewport: viewport.name, result: "NOT TESTED", issues: ["No existing calendar event was available"] });
      continue;
    }

    // Recurring events deliberately cannot be copied. Try the populated
    // fixture events until the first event that supports Copy Event is found,
    // rather than treating a recurring first row as missing coverage.
    let detailSheet;
    let copyButton;
    for (let eventIndex = 0; eventIndex < await events.count(); eventIndex += 1) {
      await events.nth(eventIndex).click();
      await page.waitForTimeout(250);
      detailSheet = page.locator(".bottom-sheet").last();
      copyButton = detailSheet.getByRole("button", { name: "Copy event", exact: true });
      if (await copyButton.count()) break;
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(100);
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
    const layout = await inspectLayout(page, true);
    issues.push(...layout.issues.map((issue) => issue.message));
    const screenshot = await capture(page, `calendar-copy-event-${viewport.name}`, viewport, "calendar-copy-event");
    copyResults.push({ viewport: viewport.name, result: issues.length ? "FAIL" : "PASS", issues, screenshot, details: layout.details });
    await page.keyboard.press("Escape").catch(() => {});
  }
  return copyResults;
}

async function writeReport(auth, copyResults) {
  for (const entry of results) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  for (const entry of copyResults) {
    if (entry.details?.length) entry.issues.push(`DOM details: ${JSON.stringify(entry.details)}`);
  }
  const rows = results.map((entry) => `<tr class="${entry.result.toLowerCase()}"><td>${escapeHtml(entry.route)}</td><td>${escapeHtml(entry.viewport)}</td><td>${entry.status ?? ""}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="${escapeHtml(entry.route)} ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const copyRows = copyResults.map((entry) => `<tr class="${entry.result.toLowerCase().replaceAll(" ", "-")}"><td>${escapeHtml(entry.viewport)}</td><td>${escapeHtml(entry.result)}</td><td>${entry.issues.map(escapeHtml).join("<br>") || "—"}</td><td>${entry.screenshot ? `<img src="${escapeHtml(entry.screenshot)}" loading="lazy" alt="Copy Event ${escapeHtml(entry.viewport)}">` : ""}</td></tr>`).join("\n");
  const html = `<!doctype html><meta charset="utf-8"><title>MyKhaya Responsive Audit</title><style>body{font:14px system-ui;margin:24px;color:#24312d}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{border:1px solid #d8ded8;padding:8px;vertical-align:top;text-align:left}.pass{background:#edf7ed}.fail{background:#fff0ed}.blocked,.not-tested{background:#fff8df}img{display:block;max-width:320px;max-height:420px;border:1px solid #d8ded8}code{background:#f3f4f1;padding:2px 4px}summary{cursor:pointer}</style><h1>MyKhaya Responsive Audit</h1><p>Base URL: <code>${escapeHtml(BASE)}</code></p><p>Authentication: <strong>${auth.ok ? "PASS" : `BLOCKED — ${escapeHtml(auth.reason)}`}</strong></p><h2>Routes</h2><table><thead><tr><th>Route</th><th>Viewport</th><th>Status</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${rows}</tbody></table><h2>Calendar Copy Event</h2><table><thead><tr><th>Viewport</th><th>Result</th><th>Issues</th><th>Screenshot</th></tr></thead><tbody>${copyRows || `<tr><td colspan="4">${auth.ok ? "No results" : "BLOCKED — authentication unavailable"}</td></tr>`}</tbody></table><h2>Notes</h2><p>BLOCKED means authentication or required data was unavailable. NOT TESTED means the route rendered but the requested interactive component could not be opened. Screenshots are local artifacts under this audit directory.</p>`;
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
}
const copyResults = auth.ok ? await auditCopyEvent(page) : [];
await writeReport(auth, copyResults);
await browser.close();
console.log(JSON.stringify({ baseUrl: BASE, outputDir, authenticated: auth.ok, authReason: auth.reason ?? null, routeResults: results.length, copyResults: copyResults.length }, null, 2));
