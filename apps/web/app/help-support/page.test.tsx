import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HelpSupport from "./page";

const { openExternalUrl } = vi.hoisted(() => ({ openExternalUrl: vi.fn() }));
vi.mock("@/components/open-external-url", () => ({ openExternalUrl }));

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
    expect(
      screen.getByRole("heading", { name: "Knowledge Base" }).closest(".card-stack"),
    ).not.toBeNull();
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

  it("opens the configured service_status_url as an external destination, never /service-status", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ service_status_url: "https://status.dev.mykhaya.app/" }),
    }) as unknown as typeof fetch;
    const user = userEvent.setup();

    render(<HelpSupport />);

    await screen.findByRole("heading", { name: "Service Status" });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Service Status" }).closest("a")).not.toBeNull(),
    );
    const link = screen.getByRole("heading", { name: "Service Status" }).closest("a");
    expect(link).not.toHaveAttribute("href", "/service-status");
    expect(link).toHaveAttribute("href", "https://status.dev.mykhaya.app/");

    await user.click(link!);
    expect(openExternalUrl).toHaveBeenCalledWith("https://status.dev.mykhaya.app/");
  });

  it("has no hard-coded dev/prod status URL anywhere in the component", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ service_status_url: "https://status.example.com/" }),
    }) as unknown as typeof fetch;

    render(<HelpSupport />);

    await screen.findByRole("heading", { name: "Service Status" });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Service Status" }).closest("a")).toHaveAttribute(
        "href",
        "https://status.example.com/",
      ),
    );
  });

  it("degrades gracefully with no crash and no clickable action when the URL is missing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ service_status_url: null }),
    }) as unknown as typeof fetch;

    render(<HelpSupport />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toBeNull();
    expect(screen.getByText("Not available right now")).toBeInTheDocument();
  });

  it("degrades gracefully when the config fetch fails", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    render(<HelpSupport />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toBeNull();
  });
});
