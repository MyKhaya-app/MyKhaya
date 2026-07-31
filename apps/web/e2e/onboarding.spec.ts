import { expect, test } from "@playwright/test";

test("public entry, registration, and responsive identity", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("Your family’s", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Create account" }).first(),
  ).toHaveAttribute("href", "/register");
  await page.goto("/register");
  await page.getByLabel("Your name").fill("Anthony Test");
  await page.getByLabel("Email").fill(`anthony-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: false })
    .first()
    .fill("Correct horse battery staple!");
  await page
    .getByLabel("Confirm password")
    .fill("Correct horse battery staple!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(
    page.getByRole("heading", { name: "Check your inbox" }),
  ).toBeVisible();
});
