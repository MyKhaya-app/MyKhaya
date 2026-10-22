import { expect, test, type Page, type Route } from "@playwright/test";

// Legal pages at phone widths: rendered legal Markdown (long URLs, lists,
// tables, code) must stay inside its padded card, never scroll the page
// sideways, and finish above the fixed bottom navigation. Covers the in-app
// Legal & Privacy overview and reader, About's reader, the public /legal
// page and the legal-action-required gate. API responses are mocked, so no
// account or seeded data is needed.

const PHONE_WIDTHS = [320, 375, 390, 430];
const WIDE_WIDTHS = [768, 1440];
const LONG_URL = "https://mykhaya.app/legal/privacy/supercalifragilisticexpialidocious-unbroken-path-segment-0123456789";
const FINAL = "FINAL-PARAGRAPH of the legal document.";

const MARKDOWN = [
  "# Privacy Notice",
  "Contact privacy-and-data-protection-enquiries@mykhaya.app with any questions.",
  "## 1. Who we are",
  "We are the controller of your data. ".repeat(8),
  `See ${LONG_URL} and [our subprocessors](${LONG_URL}).`,
  "- Account information\n  - Nested item with Antidisestablishmentarianism-style-compound-wording",
  "1. First\n2. Second",
  "> A quoted paragraph that wraps inside the card.",
  "| Purpose | Lawful basis | Retention |\n| --- | --- | --- |\n| Providing the service | Contract | Life of account plus 30 days |",
  "```\ncode with a-very-long-unbroken-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n```",
  "## 2. Final section",
  FINAL,
].join("\n\n");

const DOCUMENTS = [
  { key: "terms", display_name: "Terms & Conditions", audience: "adult", action_verb: "accept", acceptance_required: true, current_version: "1.0", effective_date: "2026-09-01" },
  { key: "privacy", display_name: "Privacy Notice", audience: "adult", action_verb: "acknowledge", acceptance_required: true, current_version: "2.1", effective_date: "2026-09-01" },
  { key: "children_privacy", display_name: "Family & Children's Privacy Notice", audience: "child", action_verb: "acknowledge", acceptance_required: true, current_version: "1.0", effective_date: "2026-09-01" },
  { key: "cookies", display_name: "Cookie Policy", audience: "adult", action_verb: "acknowledge", acceptance_required: false, current_version: "1.0", effective_date: "2026-09-01" },
];

function statusEntry(key: string, verb: string, satisfied: boolean, isTest = false) {
  return {
    document_key: key, display_name: DOCUMENTS.find((d) => d.key === key)?.display_name ?? key, audience: "adult",
    action_verb: verb, current_version_id: `v-${key}`, current_version_label: "1.0", effective_date: "2026-09-01",
    required: true, satisfied, last_version_label: satisfied ? "1.0" : null, last_version_id: satisfied ? `v-${key}` : null,
    last_accepted_at: satisfied ? "2026-09-29T14:32:00Z" : null, is_test: isTest,
  };
}

const USER = { id: "u1", email: "megan@example.com", display_name: "Megan", principal_type: "adult", email_verified: true, is_active: true };

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

function content(key: string) {
  const doc = DOCUMENTS.find((d) => d.key === key);
  return { key, display_name: doc?.display_name ?? key, version: doc?.current_version ?? "1.0", effective_date: "2026-09-01", published_at: "2026-08-20T00:00:00Z", change_summary: null, content_markdown: MARKDOWN };
}

async function mockApi(page: Page, { actionRequired = false } = {}) {
  const acceptances: unknown[] = [];
  let pending = actionRequired;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/users/me") return json(route, USER);
    if (path === "/legal/documents") return json(route, DOCUMENTS);
    if (path === "/legal/status") {
      return json(route, {
        documents: [statusEntry("terms", "accept", !pending, true), statusEntry("privacy", "acknowledge", true), statusEntry("cookies", "acknowledge", false)],
        children: [], child_self: null, action_required: pending,
      });
    }
    if (path.startsWith("/legal/documents/")) return json(route, content(decodeURIComponent(path.split("/").pop() ?? "")));
    if (path.startsWith("/legal/versions/")) return json(route, content("terms"));
    if (path === "/legal/acceptances" && route.request().method() === "POST") {
      acceptances.push(route.request().postDataJSON());
      pending = false;
      return json(route, statusEntry("terms", "accept", true, true));
    }
    if (path.includes("build")) return json(route, { version: "0.42.0", commit: "abc1234", build_time: "now", environment: "development", channel: "dev" });
    return json(route, { detail: "not mocked" }, 404);
  });
  return acceptances;
}

// Evaluated in-page. `cardSelector` is the padded container the rendered
// legal content must stay inside, with at least `minPadding` px each side.
function measure([cardSelector, minPadding]: [string, number]) {
  const box = (el: Element) => el.getBoundingClientRect();
  const problems: string[] = [];
  for (const card of document.querySelectorAll(cardSelector)) {
    const style = getComputedStyle(card);
    const outer = box(card);
    const left = outer.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft) - 0.5;
    const right = outer.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight) + 0.5;
    if (parseFloat(style.paddingLeft) < minPadding || parseFloat(style.paddingRight) < minPadding) problems.push(`${cardSelector} padding ${style.paddingLeft}/${style.paddingRight}`);
    for (const el of card.querySelectorAll("*")) {
      // A table scrolls within its own box; only that box must fit.
      if (el.closest("table") && el.tagName !== "TABLE") continue;
      const b = box(el);
      if (b.width === 0 && b.height === 0) continue;
      if (b.left < left || b.right > right) problems.push(`${el.tagName.toLowerCase()} outside the padding box (${b.left.toFixed(1)}–${b.right.toFixed(1)} vs ${left.toFixed(1)}–${right.toFixed(1)})`);
    }
  }
  return {
    found: document.querySelectorAll(cardSelector).length,
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    problems,
  };
}

async function scrollToEnd(page: Page) {
  await page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    for (const el of document.querySelectorAll("*")) {
      if (el.scrollHeight > el.clientHeight + 2 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
    }
  });
}

async function expectContained(page: Page, cardSelector: string, label: string, minPadding = 12) {
  const m = await page.evaluate(measure, [cardSelector, minPadding] as [string, number]);
  expect(m.found, `${cardSelector} rendered at ${label}`).toBeGreaterThan(0);
  expect(m.pageOverflow, `horizontal scroll at ${label}`).toBeLessThanOrEqual(0);
  expect(m.problems, `content outside ${cardSelector} at ${label}`).toEqual([]);
}

async function expectFinalAboveBottomNav(page: Page, label: string) {
  await scrollToEnd(page);
  const final = page.getByText(FINAL);
  await expect(final, `final paragraph at ${label}`).toBeInViewport();
  const nav = page.locator(".bottom-nav");
  if (await nav.isVisible()) {
    const [finalBox, navBox] = [await final.boundingBox(), await nav.boundingBox()];
    expect(finalBox!.y + finalBox!.height, `final paragraph under the bottom nav at ${label}`).toBeLessThanOrEqual(navBox!.y);
  }
}

test.describe("legal document layout", () => {
  for (const width of [...PHONE_WIDTHS, ...WIDE_WIDTHS]) {
    const label = `${width}px`;

    test(`in-app readers and overview fit at ${label}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await mockApi(page);

      for (const path of ["/settings/legal?document=privacy", "/about/legal/privacy"]) {
        await page.goto(path);
        await page.locator(".legal-document-card .legal-prose").waitFor();
        await expect(page.locator(".legal-document-card .legal-meta")).toContainText("Version 2.1");
        await expectContained(page, ".legal-document-card", `${label} ${path}`);
        if (width < 768) await expectFinalAboveBottomNav(page, `${label} ${path}`);
      }

      await page.goto("/settings/legal");
      await page.locator(".legal-document-row").first().waitFor();
      await expectContained(page, ".legal-document-row", `${label} overview`, 8);
      const insets = await page.evaluate(() => {
        const rows = document.querySelector(".legal-document-rows")!.getBoundingClientRect();
        return [...document.querySelectorAll(".legal-document-row")].map((row) => ({
          icon: row.querySelector(".more-icon-tile")!.getBoundingClientRect().left - rows.left,
          chevron: rows.right - row.querySelector(":scope > svg")!.getBoundingClientRect().right,
        }));
      });
      for (const inset of insets) {
        expect(inset.icon, `icon touches the row border at ${label}`).toBeGreaterThanOrEqual(8);
        expect(inset.chevron, `chevron touches the row border at ${label}`).toBeGreaterThanOrEqual(8);
      }
    });

    test(`public legal page fits at ${label}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await mockApi(page);
      await page.goto("/legal/privacy");
      await page.locator(".legal-document-page .legal-prose").waitFor();
      // No card here: the prose sits directly in the page's own gutter.
      await expectContained(page, ".legal-document-page", `${label} public page`, 8);
    });
  }

  for (const width of PHONE_WIDTHS) {
    test(`legal gate reader fits and still records the acceptance at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const acceptances = await mockApi(page, { actionRequired: true });
      await page.goto("/settings/legal");
      const terms = page.locator(".legal-gate-document", { hasText: "Terms & Conditions" });
      await terms.getByRole("button", { name: "Review document" }).click();
      await terms.locator(".legal-document-reader .legal-prose").waitFor();
      await expectContained(page, ".legal-gate-card", `${width}px gate`);
      await expectContained(page, ".legal-document-reader", `${width}px gate reader`);

      await terms.getByRole("button", { name: "Accept and continue" }).click();
      await expect.poll(() => acceptances.length).toBe(1);
      expect(acceptances[0]).toMatchObject({ document_key: "terms", document_version_id: "v-terms" });
    });
  }

  test("About no longer links to Service Status", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page);
    await page.goto("/about");
    await expect(page.locator(".about-version-card")).toContainText("0.42.0");
    await expect(page.getByText("Service Status")).toHaveCount(0);
    await expect(page.locator('a[href="/service-status"]')).toHaveCount(0);
  });
});
