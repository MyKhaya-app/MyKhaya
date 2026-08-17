import { expect, test } from "@playwright/test";

test("network failure keeps session bootstrap recoverable", async ({ page }) => {
  await page.route("**/api/v1/users/me", route => route.abort());

  await page.goto("/home");

  await expect(
    page.getByRole("heading", { name: "MyKhaya is temporarily unavailable" }),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/\/login$/);
});

test("definitive unauthenticated bootstrap reaches login", async ({ page }) => {
  await page.route("**/api/v1/users/me", route =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    }),
  );
  await page.route("**/api/v1/auth/renew", route =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    }),
  );

  await page.goto("/home");

  await expect(page).toHaveURL(/\/login$/);
});
