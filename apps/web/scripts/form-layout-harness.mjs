// Rendered-geometry harness for the shared form layout and bottom sheet.
//
// Bundles scripts/form-layout-fixtures.tsx (real components), loads it with
// the real design tokens and app/styles.css in Chromium, drives each fixture
// into its interactive states (extra destination rows, validation messages,
// a keyboard-reduced viewport) and measures every state with
// scripts/layout-inspector.mjs across phone, Duo-class, tablet and desktop
// viewports. Needs no running stack and no account.
//
// Usage: pnpm --filter @mykhaya/web test:layout [-- --out <dir>] [--styles <file>]
// --styles measures an alternative stylesheet in place of app/styles.css, for
// proving the harness fails when a defect is reintroduced.
// Exits 1 if any state has a layout or functional failure.
//
// Safe areas cannot be produced by Chromium (env() is always 0), so profiles
// set the shared --safe-* custom properties directly. The iPhone Duo values
// are the physical measurements recorded in
// docs/engineering/ios-engineering-standards.md §4 (right inset ~93pt,
// status column ~165pt folded / ~106pt unfolded). The Duo viewport sizes are
// representative of the native-layout class ranges, not measured devices.
// None of this replaces physical-device review.

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { chromium } from "@playwright/test";
import { inspectLayoutInPage, INTENDED_HORIZONTAL_SCROLLERS } from "./layout-inspector.mjs";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outArg = process.argv.indexOf("--out");
const outputDir = path.resolve(
  outArg > -1 ? process.argv[outArg + 1] : path.join(webDir, "test-results", "form-layout-harness", new Date().toISOString().replace(/[:.]/g, "-")),
);

const iphoneHome = { top: 20, bottom: 0 };
const iphoneNotch = { top: 59, bottom: 34 };
const notchLandscape = { left: 59, right: 59, bottom: 21 };
export const PROFILES = [
  { name: "320x568", width: 320, height: 568, insets: iphoneHome },
  { name: "375x667", width: 375, height: 667, insets: iphoneHome },
  { name: "393x852", width: 393, height: 852, insets: iphoneNotch },
  { name: "430x932", width: 430, height: 932, insets: iphoneNotch },
  { name: "667x375-landscape", width: 667, height: 375, insets: {} },
  { name: "852x393-landscape-notch", width: 852, height: 393, insets: notchLandscape },
  { name: "duo-outer-450x720", width: 450, height: 720, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 165 } },
  { name: "duo-outer-512x740", width: 512, height: 740, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 165 } },
  { name: "duo-inner-900x740", width: 900, height: 740, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 106 } },
  { name: "768x1024", width: 768, height: 1024, insets: {} },
  { name: "1024x768", width: 1024, height: 768, insets: {} },
  { name: "1280x800", width: 1280, height: 800, insets: {} },
  { name: "1440x900", width: 1440, height: 900, insets: {} },
  { name: "393x852-keyboard", width: 393, height: 852, insets: iphoneNotch, keyboard: 336 },
  { name: "320x568-keyboard", width: 320, height: 568, insets: iphoneHome, keyboard: 253 },
  { name: "duo-outer-512x740-keyboard", width: 512, height: 740, insets: { top: 20, right: 93 }, overlay: { right: 93, top: 165 }, keyboard: 300 },
];

async function bundle() {
  await fs.mkdir(outputDir, { recursive: true });
  await build({
    entryPoints: [path.join(webDir, "scripts", "form-layout-fixtures.tsx")],
    bundle: true,
    format: "iife",
    platform: "browser",
    jsx: "automatic",
    outfile: path.join(outputDir, "fixtures.js"),
    alias: { "@": webDir },
    define: { "process.env.NODE_ENV": '"production"' },
    logLevel: "warning",
  });
  const tokens = await fs.readFile(path.resolve(webDir, "..", "..", "packages", "design-tokens", "src", "tokens.css"), "utf8");
  const stylesArg = process.argv.indexOf("--styles");
  const styles = await fs.readFile(stylesArg > -1 ? path.resolve(process.argv[stylesArg + 1]) : path.join(webDir, "app", "styles.css"), "utf8");
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><style>${tokens}</style><style>${styles}</style><style id="insets"></style></head><body><div id="root"></div><script src="fixtures.js"></script></body></html>`;
  const page = path.join(outputDir, "fixtures.html");
  await fs.writeFile(page, html, "utf8");
  return pathToFileURL(page).href;
}

function insetCss(insets) {
  const value = (side) => `${insets[side] ?? 0}px`;
  return `:root{--safe-top:${value("top")};--safe-right:${value("right")};--safe-bottom:${value("bottom")};--safe-left:${value("left")};}`;
}

async function inspect(page, profile, extra = {}) {
  return page.evaluate(inspectLayoutInPage, {
    rootSelector: ".bottom-sheet",
    checkReachability: true,
    overlay: profile.overlay ?? null,
    intendedScrollers: INTENDED_HORIZONTAL_SCROLLERS,
    visibleHeight: profile.keyboard ? profile.height - profile.keyboard : null,
    ...extra,
  });
}

// Each scenario returns the states to measure; `checks` are functional
// assertions about the interactive state itself.
const SCENARIOS = [
  {
    fixture: "copy-event",
    async run(page, measure) {
      const sheet = page.locator(".bottom-sheet");
      const checks = [];
      const dates = sheet.locator('input[type="date"]');
      if (await dates.count() !== 1) checks.push("Expected exactly one destination row initially");
      if (await dates.first().inputValue()) checks.push("Initial destination date was preselected");
      if (!(await sheet.getByRole("button", { name: "Copy event", exact: true }).isDisabled())) checks.push("Copy event was enabled before a date was chosen");
      await measure("1-row", checks);
      const add = sheet.getByRole("button", { name: "Add another date" });
      await add.click();
      await add.click();
      const rowChecks = [];
      if (await dates.count() !== 3) rowChecks.push("Add another date did not create independent rows");
      if (await sheet.locator('input[type="time"]').count() !== 6) rowChecks.push("Each row needs its own start and end time");
      await dates.nth(0).fill("2030-11-05");
      await dates.nth(1).fill("2030-11-06");
      await dates.nth(2).fill("2030-11-07");
      if (!(await sheet.getByRole("button", { name: "Copy event (3)" }).isEnabled())) rowChecks.push("Copy event (3) was not enabled for three valid rows");
      await measure("3-rows", rowChecks, { scrollToEnd: true });
      await dates.nth(1).fill("2030-11-05");
      await sheet.locator('input[type="time"]').nth(1).fill("08:00");
      const errorChecks = [];
      if (await sheet.getByRole("alert").count() !== 2) errorChecks.push("Expected duplicate-date and invalid-time messages");
      await measure("3-rows-errors", errorChecks, { scrollToEnd: true });
    },
  },
  {
    fixture: "copy-event-all-day",
    async run(page, measure) {
      const checks = [];
      if (await page.locator('.bottom-sheet input[type="time"]').count() !== 0) checks.push("All-day copy should not offer times");
      await measure("1-row", checks);
    },
  },
  { fixture: "copy-event-error", async run(page, measure) { await measure("error", []); } },
  { fixture: "primitives", async run(page, measure) { await measure("primitives", [], { scrollToEnd: true }); } },
  { fixture: "legacy-sheet", async run(page, measure) { await measure("no-footer", []); } },
];

const url = await bundle();
const browser = await chromium.launch();
const results = [];
for (const profile of PROFILES) {
  for (const scenario of SCENARIOS) {
    const page = await browser.newPage({ viewport: { width: profile.width, height: profile.height } });
    await page.goto(`${url}#${scenario.fixture}`);
    await page.locator("#insets").evaluate((style, css) => { style.textContent = css; }, insetCss(profile.insets));
    await page.locator(".bottom-sheet").waitFor();
    const measure = async (state, checks, { scrollToEnd = false } = {}) => {
      if (profile.keyboard) {
        await page.evaluate((height) => window.simulateKeyboard(height), profile.keyboard);
        const followed = await page.locator(".sheet-backdrop.sheet-follows-visual-viewport").count();
        if (!followed) checks = [...checks, "Sheet did not follow the keyboard-reduced visual viewport"];
      }
      const layout = await inspect(page, profile);
      if (scrollToEnd) await page.locator(".sheet-content").evaluate((element) => { element.scrollTop = element.scrollHeight; });
      const screenshot = `${scenario.fixture}-${state}-${profile.name}.png`;
      await page.screenshot({ path: path.join(outputDir, screenshot) });
      results.push({ fixture: scenario.fixture, state, profile: profile.name, checks, issues: layout.issues, advisories: layout.advisories, metrics: layout.metrics, screenshot });
    };
    await scenario.run(page, measure);
    await page.close();
  }
}
// Inspector self-tests: small static pages with a known answer, proving the
// input-adornment allowance is narrow. A marked adornment may overlap only
// its own input, and only when it is contained, padded for, keyboard
// reachable and correctly named; every other overlap must still fail.
const field = (inputAttributes, buttonAttributes, { padding = 52, buttonStyle = "" } = {}) => `
  <div class="wrap" style="position:relative;width:300px">
    <input ${inputAttributes} style="box-sizing:border-box;width:300px;height:50px;padding:0 ${padding}px 0 12px;border:1px solid #999;font:16px sans-serif">
    <button type="button" ${buttonAttributes} style="position:absolute;right:3px;top:3px;width:44px;height:44px;padding:0;border:0;${buttonStyle}">·</button>
  </div>`;
const ADORNED = 'data-input-adornment="password-visibility" aria-controls="pw"';
const INSPECTOR_SELF_TESTS = [
  { name: "marked password toggle over its own padded input passes", html: field('id="pw" type="password"', `${ADORNED} aria-label="Show password"`), expect: [] },
  { name: "the same toggle shown as Hide password while the password is visible passes", html: field('id="pw" type="text"', `${ADORNED} aria-label="Hide password"`), expect: [] },
  { name: "the same overlap without the marker still fails", html: field('id="pw" type="password"', 'aria-label="Show password"'), expect: ["control-overlap"] },
  { name: "a marker naming a different input still fails", html: `${field('id="pw" type="password"', 'data-input-adornment="password-visibility" aria-controls="other" aria-label="Show password"')}<input id="other" style="margin-top:80px">`, expect: ["control-overlap"] },
  { name: "a marked toggle that also overlaps an unrelated control still fails", html: field('id="pw" type="password"', `${ADORNED} aria-label="Show password"`).replace("</div>", '<button type="button" style="position:absolute;right:20px;top:10px;width:60px;height:30px">Other</button></div>'), expect: ["control-overlap"] },
  { name: "text that can run under the toggle fails", html: field('id="pw" type="password"', `${ADORNED} aria-label="Show password"`, { padding: 12 }), expect: ["input-adornment"] },
  { name: "a toggle outside its input's wrapper fails", html: field('id="pw" type="password"', `${ADORNED} aria-label="Show password"`, { buttonStyle: "right:-30px;" }), expect: ["input-adornment"] },
  { name: "a toggle removed from the keyboard order fails", html: field('id="pw" type="password"', `${ADORNED} tabindex="-1" aria-label="Show password"`), expect: ["input-adornment"] },
  { name: "a toggle whose name does not match the field's state fails", html: field('id="pw" type="password"', `${ADORNED} aria-label="Hide password"`), expect: ["input-adornment"] },
  { name: "two plain overlapping inputs still fail", html: '<div style="position:relative"><input style="position:absolute;left:0;top:0;width:200px;height:40px"><input style="position:absolute;left:100px;top:10px;width:200px;height:40px"></div>', expect: ["control-overlap"] },
];
const selfTestResults = [];
const selfTestPage = await browser.newPage({ viewport: { width: 400, height: 300 } });
for (const test of INSPECTOR_SELF_TESTS) {
  await selfTestPage.setContent(`<!doctype html><html><body style="margin:20px">${test.html}</body></html>`);
  const report = await selfTestPage.evaluate(inspectLayoutInPage, {});
  const kinds = [...new Set(report.issues.map((issue) => issue.kind))].sort();
  const passed = JSON.stringify(kinds) === JSON.stringify([...test.expect].sort());
  selfTestResults.push({ name: test.name, passed, expected: test.expect, actual: kinds, issues: report.issues });
}
await browser.close();
const selfTestFailures = selfTestResults.filter((test) => !test.passed);
await fs.writeFile(path.join(outputDir, "inspector-self-tests.json"), JSON.stringify(selfTestResults, null, 2));

const failures = results.filter((result) => result.checks.length || result.issues.length);
await fs.writeFile(path.join(outputDir, "results.json"), JSON.stringify(results, null, 2));
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;");
const rows = results.map((result) => `<tr class="${result.checks.length || result.issues.length ? "fail" : "pass"}"><td>${escape(result.fixture)}</td><td>${escape(result.state)}</td><td>${escape(result.profile)}</td><td>${[...result.checks, ...result.issues.map((issue) => `${issue.kind}: ${issue.element} ${issue.message}`)].map(escape).join("<br>") || "PASS"}</td><td><img src="${result.screenshot}" loading="lazy"></td></tr>`).join("");
await fs.writeFile(path.join(outputDir, "index.html"), `<!doctype html><meta charset="utf-8"><title>Form layout harness</title><style>body{font:14px system-ui;margin:24px}td{border:1px solid #ccc;padding:6px;vertical-align:top}.pass{background:#edf7ed}.fail{background:#fff0ed}img{max-width:280px;max-height:420px}</style><h1>Form layout harness</h1><p>${results.length} states, ${failures.length} failing. Chromium only; safe areas simulated; not device evidence.</p><table>${rows}</table>`);

const summary = new Map();
for (const result of results) {
  const key = `${result.fixture}/${result.state}`;
  const entry = summary.get(key) ?? { pass: 0, fail: [] };
  if (result.checks.length || result.issues.length) entry.fail.push(`${result.profile} (${[...result.checks, ...new Set(result.issues.map((issue) => issue.kind))].join(", ")})`);
  else entry.pass += 1;
  summary.set(key, entry);
}
for (const [key, entry] of summary) console.log(`${key.padEnd(34)} pass ${entry.pass}/${entry.pass + entry.fail.length}${entry.fail.length ? `  FAIL: ${entry.fail.join("; ")}` : ""}`);
for (const test of selfTestFailures) console.log(`inspector self-test FAIL: ${test.name} (expected ${JSON.stringify(test.expected)}, got ${JSON.stringify(test.actual)})`);
console.log(`\n${results.length} states, ${failures.length} failing. Report: ${path.join(outputDir, "index.html")}`);
console.log(`${selfTestResults.length} inspector self-tests, ${selfTestFailures.length} failing.`);
process.exitCode = failures.length || selfTestFailures.length ? 1 : 0;
