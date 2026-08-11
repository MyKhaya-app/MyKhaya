import { expect, test } from "@playwright/test";

const widths = [320, 375, 390, 430, 768, 1024, 1440];

test("mobile-first Calendar, relationships and feature management", async ({
  page,
}) => {
  const email = process.env.E2E_EMAIL;
  if (!email) throw new Error("E2E_EMAIL is required");

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("Correct horse battery staple!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  for (const width of widths) {
    await page.setViewportSize({ width, height: width <= 430 ? 844 : 900 });
    await page.goto("/home");
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(
      overflow,
      `home must not overflow at ${width}px`,
    ).toBeLessThanOrEqual(0);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/calendar");
  await expect(page.getByLabel("Calendar view")).toBeVisible();
  await page.getByLabel("Calendar view").selectOption("month");
  await expect(page.getByLabel("Month view")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Add calendar event" }).click();
  const editor = page.getByRole("dialog", { name: "Add event" });
  await expect(editor).toBeVisible();
  await expect(editor.getByLabel("Title")).toBeFocused();
  await expect(
    editor.getByRole("group", { name: "Household members" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(editor).toBeHidden();
  await page.screenshot({
    path: "test-results/evidence/calendar-mobile-390.png",
    fullPage: true,
  });

  await page.goto("/people");
  await expect(page.getByRole("heading", { name: "Household" })).toBeVisible();
  await page.getByRole("button", { name: "Invite someone" }).click();
  await expect(
    page.locator(".invite-card").getByLabel("Relationship").locator("option"),
  ).toHaveText(["Home Admin", "Partner", "Child", "Extended Family", "Friend"]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(0);

  await page.goto("/khaya-control-centre/feature-management");
  await expect(
    page.getByRole("heading", { name: "Feature Management" }),
  ).toBeVisible();
  await expect(page.getByText("Calendar", { exact: true })).toBeVisible();
  await expect(page.getByText("Tasks", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Shopping lists", { exact: true })).toHaveCount(
    0,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(0);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.screenshot({
    path: "test-results/evidence/feature-management-desktop-1440.png",
    fullPage: true,
  });
});
