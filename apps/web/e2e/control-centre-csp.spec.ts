import { expect, test } from "@playwright/test";

test("Control Centre renders with the nonce-bearing CSP", async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const response = await page.goto("/login");
  expect(response).not.toBeNull();
  const csp = response?.headers()["content-security-policy"] ?? "";
  const nonce = csp.match(/'nonce-([^']+)'/)?.[1];

  expect(csp).toContain("script-src 'self'");
  expect(nonce).toBeTruthy();
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).not.toContain("'unsafe-inline'");
  await expect(page.getByRole("heading", { name: "MyKhaya Platform Control Centre" })).toBeVisible();
  await expect(page.locator("body")).not.toHaveText("");

  const inlineScripts = await page.locator("script:not([src]):not([type='application/json'])").evaluateAll((scripts) =>
    scripts.map((script) => (script as HTMLScriptElement).nonce),
  );
  expect(inlineScripts.length).toBeGreaterThan(0);
  expect(inlineScripts.every((scriptNonce) => scriptNonce === nonce)).toBe(true);
  expect(consoleErrors.join("\n")).not.toMatch(/Executing inline script violates.*Content Security Policy/i);
  expect([...consoleErrors, ...pageErrors].join("\n")).not.toMatch(/Connection closed/i);
  expect(pageErrors.join("\n")).not.toMatch(/hydration|Content Security Policy/i);
});
