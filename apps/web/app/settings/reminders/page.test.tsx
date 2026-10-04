import { describe, expect, it, vi } from "vitest";

// Routines and Reminders were consolidated into one "Routines & Reminders"
// module — see app/settings/routines-reminders/page.test.tsx for coverage
// of Reminder create/edit/complete/delete behaviour. This route now only
// needs to prove it redirects rather than 404s, so old bookmarks/deep links
// keep working.

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (url: string): void => {
    redirectMock(url);
  },
}));

describe("Reminders route — backward compatible redirect", () => {
  it("redirects to the combined Routines & Reminders module, pre-selecting the Reminders tab", async () => {
    const { default: RemindersRedirect } = await import("./page");
    RemindersRedirect();
    expect(redirectMock).toHaveBeenCalledWith("/settings/routines-reminders?type=reminders");
  });
});
