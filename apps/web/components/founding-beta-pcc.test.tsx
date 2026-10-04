import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FoundingBetaPcc } from "./founding-beta-pcc";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/control-centre/founding-beta",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("./platform-shell", () => ({
  PlatformShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;

const programme = {
  id: "programme-1",
  slug: "founding-beta",
  name: "Founding Beta",
  max_homes: 100,
  waitlist_enabled: true,
  show_remaining_publicly: true,
  invitation_ttl_days: 7,
  terms_version: "beta-1",
  status: "active",
};

const overview = {
  signup_mode: "beta_only",
  max_homes: 100,
  joined: 37,
  reserved: 4,
  waiting: 0,
  joinable: 59,
};

beforeEach(() => {
  window.history.replaceState({}, "", "/control-centre/founding-beta");
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/beta/overview") return Promise.resolve(overview);
    if (path === "/beta/programme") return Promise.resolve(programme);
    if (path.startsWith("/beta/waitlist")) return Promise.resolve({ items: [{ id: "w1", name: "Asha Naidoo", email: "asha@example.com", country: "ZA", household_size: 4, joined_at: "2026-01-01T00:00:00Z", status: "waiting" }], total: 1 });
    if (path === "/beta/invitations") return Promise.resolve({ items: [], total: 0 });
    throw new Error(`Unexpected GET ${path}`);
  });
  post.mockResolvedValue(undefined);
  patch.mockResolvedValue(programme);
});

describe("Founding Beta PCC", () => {
  it("shows mathematically correct capacity and Signup Mode context", async () => {
    render(<FoundingBetaPcc />);
    expect(await screen.findByText("Available capacity")).toBeInTheDocument();
    expect(screen.getByText("59")).toBeInTheDocument();
    expect(screen.getByText("Beta only")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage signup settings/i })).toHaveAttribute("href", "/settings");
  });

  it("shows waitlist priority and disables Invite at zero capacity", async () => {
    window.history.replaceState({}, "", "/control-centre/founding-beta?view=waitlist");
    get.mockImplementation((path: string) => {
      if (path === "/beta/overview") return Promise.resolve({ ...overview, joinable: 0, waiting: 1 });
      if (path === "/beta/programme") return Promise.resolve(programme);
      if (path.startsWith("/beta/waitlist")) return Promise.resolve({ items: [{ id: "w1", name: "Asha Naidoo", email: "asha@example.com", country: "ZA", household_size: 4, joined_at: "2026-01-01T00:00:00Z", status: "waiting" }], total: 1 });
      if (path === "/beta/invitations") return Promise.resolve({ items: [], total: 0 });
      throw new Error(`Unexpected GET ${path}`);
    });
    render(<FoundingBetaPcc />);
    expect(await screen.findByText(/waitlist has priority/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite" })).toBeDisabled();
  });

  it("submits programme settings with an explicit reason", async () => {
    const user = userEvent.setup();
    render(<FoundingBetaPcc />);
    await screen.findByDisplayValue("beta-1");
    const terms = screen.getByDisplayValue("beta-1");
    await user.clear(terms);
    await user.type(terms, "beta-2");
    await user.type(screen.getByLabelText("Reason for this change"), "Approved terms refresh");
    await user.click(screen.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/beta/programme", expect.objectContaining({ terms_version: "beta-2", reason: "Approved terms refresh" })));
  });
});
