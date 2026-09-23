import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SupportSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/control-centre/support/settings",
}));

describe("Support settings", () => {
  it("renders the existing Coming soon stub honestly, with no fabricated settings UI", async () => {
    render(<SupportSettingsPage />);
    expect(await screen.findByRole("heading", { name: "Support settings" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon.")).toBeInTheDocument();
    expect(
      screen.getByText("Configuration for the Support ticket system."),
    ).toBeInTheDocument();
  });
});
