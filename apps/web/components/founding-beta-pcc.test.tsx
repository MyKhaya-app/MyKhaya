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

  it("offers site-wide iPhone and Android app link fields with their hints", async () => {
    render(<FoundingBetaPcc />);
    const ios = await screen.findByLabelText("iPhone app link");
    const android = screen.getByLabelText("Android app link");
    expect(screen.getByText("Used site-wide: on the public homepage and the Founding Beta page.")).toBeInTheDocument();
    expect(ios).toHaveAccessibleDescription(
      "Paste a TestFlight link during the beta, or the App Store link once the app is live. Leave empty to hide.",
    );
    expect(android).toHaveAccessibleDescription(/Google Play testing link during the beta/);
    expect(ios).toHaveValue("");
    expect(screen.getAllByText("Not set")).toHaveLength(2);
  });

  it("saves only the editable settings (no id/slug/name/status), including the app links", async () => {
    const user = userEvent.setup();
    render(<FoundingBetaPcc />);
    await user.type(await screen.findByLabelText("iPhone app link"), "https://testflight.apple.com/join/AbCdEf12");
    await user.type(screen.getByLabelText("Android app link"), " https://play.google.com/apps/testing/app.mykhaya ");
    await user.type(screen.getByLabelText("Reason for this change"), "Publish the beta app links");
    await user.click(screen.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0]![1]).toEqual({
      max_homes: 100,
      waitlist_enabled: true,
      show_remaining_publicly: true,
      invitation_ttl_days: 7,
      terms_version: "beta-1",
      ios_app_url: "https://testflight.apple.com/join/AbCdEf12",
      android_app_url: "https://play.google.com/apps/testing/app.mykhaya",
      reason: "Publish the beta app links",
    });
  });

  it("sends empty links as empty strings so clearing a field hides the link", async () => {
    const user = userEvent.setup();
    get.mockImplementation((path: string) => {
      if (path === "/beta/overview") return Promise.resolve(overview);
      if (path === "/beta/programme") return Promise.resolve({ ...programme, ios_app_url: "https://apps.apple.com/app/id1", android_app_url: null });
      throw new Error(`Unexpected GET ${path}`);
    });
    render(<FoundingBetaPcc />);
    await user.clear(await screen.findByLabelText("iPhone app link"));
    await user.type(screen.getByLabelText("Reason for this change"), "Hide the iPhone link");
    await user.click(screen.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0]![1]).toMatchObject({ ios_app_url: "", android_app_url: "" });
  });

  it("shows the API's validation error for an invalid link", async () => {
    const user = userEvent.setup();
    patch.mockRejectedValueOnce(new Error("Use a testflight.apple.com or apps.apple.com link."));
    render(<FoundingBetaPcc />);
    await user.type(await screen.findByLabelText("iPhone app link"), "https://example.com/app");
    await user.type(screen.getByLabelText("Reason for this change"), "Try a wrong link");
    await user.click(screen.getByRole("button", { name: /save changes/i }));
    expect(await screen.findByText("Use a testflight.apple.com or apps.apple.com link.")).toBeInTheDocument();
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
