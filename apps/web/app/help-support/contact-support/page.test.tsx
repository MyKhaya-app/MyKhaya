import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ContactSupport from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/contact-support",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, me: vi.fn() } };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  global.fetch = vi.fn().mockRejectedValue(new Error("no build info in tests"));
});

describe("Contact support (Phase 2C placeholder)", () => {
  it("truthfully shows Coming soon with no form, no mailto:, and no submit action", async () => {
    render(<ContactSupport />);
    await screen.findByRole("heading", { name: "Contact support" });
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    expect(document.querySelector('a[href^="mailto:"]')).toBeNull();
  });
});
