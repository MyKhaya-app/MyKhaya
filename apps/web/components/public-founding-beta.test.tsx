import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PublicFoundingBeta } from "./public-founding-beta";

const router = { push: vi.fn(), replace: vi.fn() };
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/founding-beta",
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: { publicSignupState: vi.fn(), publicBetaInvitation: vi.fn(), me: vi.fn() },
  };
});
const { api, ApiError } = await import("@mykhaya/api-client");
const signupState = api.publicSignupState as unknown as ReturnType<typeof vi.fn>;
const me = api.me as unknown as ReturnType<typeof vi.fn>;
const invitationLookup = api.publicBetaInvitation as unknown as ReturnType<typeof vi.fn>;

function state(overrides: Record<string, unknown> = {}) {
  return {
    signup_mode: "beta_only",
    beta_joining_available: true,
    waitlist_available: false,
    joinable_count: 12,
    beta_terms_version: "2026-09",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  search = "";
  signupState.mockResolvedValue(state());
});

describe("Founding Beta page", () => {
  it("renders the approved hero, benefits card and terms line", async () => {
    render(<PublicFoundingBeta />);
    expect(screen.getByText("Founding Beta")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Help shape a calmer home." })).toBeInTheDocument();
    expect(screen.getByText("Join a small group of households testing and improving MyKhaya.")).toBeInTheDocument();

    const card = screen.getByRole("region", { name: "What you get" });
    const rows = within(card).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Complimentary Ultimate for lifeFull access to all features.",
      "No payment card requiredJoin without any payment details.",
      "Limited places while we testA small number of households.",
    ]);

    expect(await screen.findByRole("button", { name: /Join the Beta/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Beta Terms" })).toHaveAttribute("href", "/legal/founding-beta-terms");
    // No consent checkbox here: acceptance stays in registration/enrolment.
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("sends a signed-in visitor to Beta onboarding and a signed-out one to Beta registration", async () => {
    const user = userEvent.setup();
    me.mockResolvedValueOnce({ id: "u1" });
    render(<PublicFoundingBeta />);
    await user.click(await screen.findByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/onboarding?beta=1"));

    me.mockRejectedValueOnce(new ApiError(401, "Not authenticated"));
    await user.click(screen.getByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/register?beta=1"));
  });

  it("carries a Beta invitation through and keeps its reservation notice", async () => {
    search = "invitation=tok-1";
    invitationLookup.mockResolvedValue({ valid: true, expires_at: "2026-10-10T12:00:00Z" });
    signupState.mockResolvedValue(state({ beta_joining_available: false }));
    const user = userEvent.setup();
    me.mockRejectedValueOnce(new ApiError(401, "Not authenticated"));
    render(<PublicFoundingBeta />);
    expect(await screen.findByText(/This place is reserved for you until/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/register?beta=1&beta_invitation=tok-1"));
  });

  it("offers the waitlist instead when places go to the waitlist first", async () => {
    signupState.mockResolvedValue(state({ beta_joining_available: false, waitlist_available: true }));
    render(<PublicFoundingBeta />);
    expect(await screen.findByRole("link", { name: /Join the waitlist/ })).toHaveAttribute("href", "/waitlist");
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
  });

  it("says joining is unavailable when neither path is open", async () => {
    signupState.mockResolvedValue(state({ beta_joining_available: false, waitlist_available: false }));
    render(<PublicFoundingBeta />);
    expect(await screen.findByText(/Founding Beta joining is currently unavailable/)).toBeInTheDocument();
  });

  it("sits inside the shared marketing nav and footer, pinned to the light theme", async () => {
    const { container } = render(<PublicFoundingBeta />);
    const scopes = container.querySelectorAll(".mks.mks-scope");
    expect(scopes).toHaveLength(2);
    for (const scope of scopes) expect(scope).toHaveAttribute("data-theme", "light");
    // The page content itself is not inside the marketing scope.
    expect(screen.getByRole("heading", { level: 1 }).closest(".mks")).toBeNull();
    // The nav's sign-up action follows the page's own signup state (Beta).
    const header = screen.getByRole("banner");
    await waitFor(() =>
      expect(within(header).getByRole("link", { name: "Join the Beta" })).toHaveAttribute("href", "/founding-beta"),
    );
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Support" })).toHaveAttribute("href", "/support");
  });
});
