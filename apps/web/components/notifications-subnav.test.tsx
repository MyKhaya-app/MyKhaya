import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NotificationsSubNav } from "./notifications-subnav";

let currentPath = "/notifications/templates";
vi.mock("next/navigation", () => ({ usePathname: () => currentPath }));

describe("NotificationsSubNav", () => {
  it("renders a link for every sub-section", () => {
    render(<NotificationsSubNav />);
    ["Overview", "Templates", "Channels", "Daily Briefing", "Test Centre", "Delivery Logs"].forEach(
      (label) => expect(screen.getByRole("link", { name: label })).toBeInTheDocument(),
    );
  });

  it("marks only the current section's link as active", () => {
    currentPath = "/notifications/channels";
    render(<NotificationsSubNav />);
    expect(screen.getByRole("link", { name: "Channels" })).toHaveClass("active");
    expect(screen.getByRole("link", { name: "Templates" })).not.toHaveClass("active");
  });

  it("links to the correct routes", () => {
    render(<NotificationsSubNav />);
    expect(screen.getByRole("link", { name: "Delivery Logs" })).toHaveAttribute(
      "href",
      "/notifications/delivery-logs",
    );
  });
});
