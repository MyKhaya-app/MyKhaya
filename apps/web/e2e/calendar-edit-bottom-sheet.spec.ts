import { expect, test } from "@playwright/test";

async function api(
  page: import("@playwright/test").Page,
  method: string,
  path: string,
  body?: unknown,
) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie.match(/(?:^|; )mk_csrf=([^;]+)/)?.[1];
      const headers: Record<string, string> = { Accept: "application/json" };
      if (body) headers["Content-Type"] = "application/json";
      if (csrf && method !== "GET") headers["X-CSRF-Token"] = decodeURIComponent(csrf);
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        credentials: "include",
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await response.text();
      let parsed: unknown = null;
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

test("Edit does not submit the newly mounted event form", async ({ page }) => {
  const email = process.env.E2E_EMAIL;
  if (!email) {
    test.skip(true, "E2E_EMAIL is required for the authenticated browser flow");
    return;
  }

  await page.goto("/login");
  await page.getByRole("button", { name: "Not now" }).click({ timeout: 2000 }).catch(() => {});
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("Correct horse battery staple!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  const homes = (await api(page, "GET", "/groups")).body as { id: string }[];
  const homeId = homes[0]!.id;
  await api(page, "PUT", `/features/${homeId}/calendar/household`, {
    enabled: true,
    confirmed: true,
  });
  const calendars = (await api(page, "GET", `/homes/${homeId}/calendars`)).body as {
    items: { id: string; timezone: string; is_primary: boolean }[];
  };
  const primary = calendars.items.find((calendar) => calendar.is_primary) ?? calendars.items[0];
  const start = new Date(Date.now() + 2 * 60 * 60 * 1000);
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  const title = `Edit activation regression ${Date.now()}`;
  const created = await api(page, "POST", `/homes/${homeId}/events`, {
    title,
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    timezone: primary?.timezone ?? "UTC",
    is_all_day: false,
    label_id: null,
    location_text: null,
    member_ids: [],
    reminder_minutes: null,
    recurrence: "none",
    recurrence_interval: 1,
    recurrence_until: null,
    recurrence_end_date: null,
    recurrence_count: null,
    description: null,
    calendar_id: primary?.id ?? null,
  });
  expect(created.status).toBe(201);

  let updateRequests = 0;
  page.on("request", (request) => {
    if (request.method() === "PATCH" && request.url().includes(`/homes/${homeId}/events/`)) {
      updateRequests += 1;
    }
  });

  await page.goto("/calendar?calendarDebug=1");
  const eventChip = page.getByText(title, { exact: true }).first();
  await expect(eventChip).toBeVisible();
  await eventChip.click();

  const dayDialog = page.getByRole("dialog").first();
  await expect(dayDialog.getByRole("button", { name: title })).toBeVisible();
  await dayDialog.getByRole("button", { name: title }).click();

  const viewDialog = page.getByRole("dialog", { name: title });
  await expect(viewDialog.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(viewDialog.getByRole("button", { name: "Close" })).toBeVisible();

  await viewDialog.getByRole("button", { name: "Edit" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit event" });
  await expect(editDialog).toBeVisible();
  await page.waitForTimeout(100);
  await expect(editDialog.getByRole("button", { name: "Save changes" })).toBeVisible();
  await expect(editDialog.getByRole("button", { name: "Cancel" })).toBeVisible();
  expect(updateRequests).toBe(0);

  await editDialog.getByRole("button", { name: "Save changes" }).click();
  await expect.poll(() => updateRequests).toBe(1);
  await expect(editDialog).toHaveCount(0);
});
