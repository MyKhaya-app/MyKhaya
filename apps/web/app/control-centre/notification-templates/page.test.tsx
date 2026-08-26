import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect }));

describe("legacy /control-centre/notification-templates route", () => {
  it("redirects to the new Notifications module's Templates page", async () => {
    const { default: Page } = await import("./page");
    Page();
    expect(redirect).toHaveBeenCalledWith("/control-centre/notifications/templates");
  });
});
