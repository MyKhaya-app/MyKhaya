import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import HelpSupport from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support",
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
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
    },
  };
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

describe("Help & Support", () => {
  it("renders a Knowledge Base foundation with a coming-soon state and no fake link", async () => {
    render(<HelpSupport />);

    await screen.findByRole("heading", { name: "Knowledge Base" });
    expect(screen.getByText("Find answers and guidance for using MyKhaya.")).toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: "Knowledge Base" });
    expect(heading.closest("a")).toBeNull();
  });

  it("renders a Contact Support foundation with a coming-soon state and no fake backend", async () => {
    render(<HelpSupport />);

    await screen.findByRole("heading", { name: "Contact Support" });
    expect(screen.getByText("Get help from the MyKhaya support team.")).toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: "Contact Support" });
    expect(heading.closest("a")).toBeNull();
  });

  it("links to the existing Service Status page", async () => {
    render(<HelpSupport />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toHaveAttribute("href", "/service-status");
  });
});
