import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BillingStatus, Home, Member } from "@mykhaya/shared-types";
import ManageMembers from "./page";

let activeHomeOverride: Home | undefined;

// Locked-state coverage for the Free plan enforcement pass: "Add member"
// must not render as a normal action on a Free Home at its member limit,
// and Extended Family/Friend must show the Family-only treatment — see
// docs/architecture/commercial-entitlements.md "Free plan enforcement
// pass".

// A stable router object matters here: AppShell's bootstrap() effect depends
// on `router` (via useCallback), so a mock returning a fresh object identity
// on every call would re-trigger that effect (and its "Checking your
// MyKhaya session…" loading state) on every unrelated re-render.
const mockRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/settings/members",
}));

// A mutable indirection so individual tests can swap in a Family Home with
// invite/manage capabilities (see setActiveHomeForTest below) without
// re-declaring the whole vi.mock factory per test.
function currentActiveHome(): Home {
  return activeHomeOverride ?? freeHome();
}
function setActiveHomeForTest(home: Home | undefined) {
  activeHomeOverride = home;
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: currentActiveHome(),
    activeHomeId: "home-1",
    homes: [currentActiveHome()],
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
      me: vi.fn().mockResolvedValue({ id: "u1", display_name: "Owner" }),
      members: vi.fn().mockResolvedValue([ownerMember()]),
      listInvitations: vi.fn().mockResolvedValue([]),
      billingStatus: vi.fn().mockResolvedValue(freeBillingStatus()),
      post: vi.fn().mockResolvedValue({}),
      patch: vi.fn().mockResolvedValue({}),
      uploadMemberAvatar: vi.fn(),
      removeMemberAvatar: vi.fn(),
      getHomeJoinCode: vi.fn().mockResolvedValue({ code: null, generated_at: null }),
      regenerateHomeJoinCode: vi.fn(),
      listHomeJoinRequests: vi.fn().mockResolvedValue([]),
      approveHomeJoinRequest: vi.fn(),
      declineHomeJoinRequest: vi.fn(),
      grantFamilySponsorship: vi.fn(),
      revokeFamilySponsorship: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function freeHome(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["members.invite", "members.manage_relationships"],
    member_count: 1,
    child_login_code: "1234",
  };
}

function ownerMember(): Member {
  return {
    membership_id: "m1",
    user_id: "u1",
    display_name: "Owner",
    email: "owner@example.com",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    permission_overrides: {},
    shared_resources: [],
    colour: "teal",
    avatar_version: null,
  };
}

function freeBillingStatus(overrides: Partial<BillingStatus> = {}): BillingStatus {
  return {
    stored_plan: "free",
    provider: "free",
    status: "active",
    effective_plan: "free",
    effective_status_reason: null,
    billing_interval: null,
    price: null,
    current_period_end: null,
    cancel_at_period_end: false,
    complimentary_expires_at: null,
    can_manage_billing: true,
    has_stripe_customer: false,
    stripe_billing_available: true,
    family_access: false,
    calendar_usage: { count: 1, limit: 1, over_limit: false },
    category_usage: { count: 1, limit: 1, over_limit: false },
    member_usage: { count: 1, limit: 1, over_limit: false },
    household_routines_enabled: false,
    shared_events_enabled: false,
    external_invites_enabled: false,
    meals_enabled: false,
    lists_enabled: true,
    list_usage: { count: 0, limit: 2, over_limit: false },
    wishlists_enabled: false,
    nudges_enabled: false,
    ...overrides,
  };
}

function familyHomeWithGrowthRoom(): Home {
  return {
    ...freeHome(),
    capabilities: ["members.invite", "members.manage_relationships"],
  };
}

function familyBillingStatus(): BillingStatus {
  return freeBillingStatus({
    family_access: true,
    member_usage: { count: 1, limit: null, over_limit: false },
    external_invites_enabled: true,
  });
}

function partnerMember(): Member {
  return {
    membership_id: "m2",
    user_id: "u2",
    display_name: "Partner Person",
    email: "partner@example.com",
    role: "adult_member",
    relationship: "partner",
    permission_profile: "standard_partner",
    permission_overrides: {},
    shared_resources: [],
    colour: "sage",
    avatar_version: null,
  };
}

function childMember(): Member {
  return {
    membership_id: "m3",
    user_id: "u3",
    display_name: "Young Person",
    email: null,
    role: "member",
    relationship: "child",
    permission_profile: "child_restricted",
    permission_overrides: {},
    shared_resources: [],
    colour: "mustard",
    avatar_version: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setActiveHomeForTest(undefined);
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember()]);
  (api.listInvitations as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.getHomeJoinCode as ReturnType<typeof vi.fn>).mockResolvedValue({
    code: null,
    generated_at: null,
  });
  (api.listHomeJoinRequests as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Manage members page — Free plan locked states", () => {
  it("hides Add member and shows the Family upsell when the Home is at its member limit", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember()]);
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(freeBillingStatus());

    render(<ManageMembers />);

    await waitFor(() => {
      expect(screen.getByText("Owner")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /add member/i })).not.toBeInTheDocument();
    expect(screen.getByText(/invite household members/i)).toBeInTheDocument();
    expect(screen.getByText(/view family plan/i)).toBeInTheDocument();
  });

  it("shows Add member once the plan allows growing membership", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember()]);
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      freeBillingStatus({ member_usage: { count: 1, limit: null, over_limit: false } }),
    );

    render(<ManageMembers />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add member/i })).toBeInTheDocument();
    });
  });
});

// Coverage for the new Adult relationship (see docs task "Add member —
// Adult relationship"): it must appear in the Add-member picker between
// Partner and Child, follow the normal adult invite flow (no managed-Child
// account behaviour), and be counted under the Family screen's "Adults"
// filter alongside Home Admin/Partner — without changing how Partner or
// Child themselves behave.
describe("Manage members page — Adult relationship", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  async function openAddMemberSheet() {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, they live here/i }));
    return screen.getByLabelText("Relationship");
  }

  it("lists Adult between Partner and Child in the Add-member relationship options", async () => {
    const select = await openAddMemberSheet();
    const optionLabels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent);
    const partnerIndex = optionLabels.indexOf("Partner");
    const adultIndex = optionLabels.indexOf("Adult");
    const childIndex = optionLabels.indexOf("Child");

    expect(partnerIndex).toBeGreaterThanOrEqual(0);
    expect(adultIndex).toBe(partnerIndex + 1);
    expect(childIndex).toBe(adultIndex + 1);
  });

  it("follows the normal adult invite flow for Adult — no managed-Child callout, email field shown", async () => {
    const select = await openAddMemberSheet();
    const user = userEvent.setup();
    await user.selectOptions(select, "adult");

    expect(screen.queryByText(/managed profile/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no adult invitation will be sent/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("submits an Adult invitation with the relationship field set to 'adult'", async () => {
    const select = await openAddMemberSheet();
    const user = userEvent.setup();
    await user.selectOptions(select, "adult");
    await user.type(screen.getByLabelText("Email"), "housemate@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/invitations",
        expect.objectContaining({ relationship: "adult" }),
      ),
    );
  });

  it("counts Adult members under the Adults filter alongside Home Admin and Partner", async () => {
    const adultMember: Member = {
      membership_id: "m4",
      user_id: "u4",
      display_name: "Housemate Adult",
      email: "housemate@example.com",
      role: "adult_member",
      relationship: "adult",
      permission_profile: "standard_partner",
      permission_overrides: {},
      shared_resources: [],
      colour: "coral",
      avatar_version: null,
    };
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      ownerMember(),
      partnerMember(),
      adultMember,
      childMember(),
    ]);

    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());

    const adultsButton = screen.getByRole("button", { name: /^adults \d+$/i });
    expect(within(adultsButton).getByText("3")).toBeInTheDocument();

    await userEvent.setup().click(adultsButton);
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Partner Person")).toBeInTheDocument();
    expect(screen.getByText("Housemate Adult")).toBeInTheDocument();
    expect(screen.queryByText("Young Person")).not.toBeInTheDocument();
  });

  it("still shows the Adult relationship label on that member's card", async () => {
    const adultMember: Member = {
      membership_id: "m4",
      user_id: "u4",
      display_name: "Housemate Adult",
      email: "housemate@example.com",
      role: "adult_member",
      relationship: "adult",
      permission_profile: "standard_partner",
      permission_overrides: {},
      shared_resources: [],
      colour: "coral",
      avatar_version: null,
    };
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), adultMember]);

    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Housemate Adult")).toBeInTheDocument());
    expect(screen.getByText("Adult", { selector: ".role-badge" })).toBeInTheDocument();
  });

  it("leaves Partner members working unchanged (label, filter, no child callout)", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), partnerMember()]);

    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Partner Person")).toBeInTheDocument());
    expect(screen.getByText("Partner", { selector: ".role-badge" })).toBeInTheDocument();

    const adultsButton = screen.getByRole("button", { name: /^adults \d+$/i });
    expect(within(adultsButton).getByText("2")).toBeInTheDocument();
  });

  it("leaves Child members working unchanged (label, filter, manage-privacy link instead of a relationship selector)", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), childMember()]);

    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Young Person")).toBeInTheDocument());
    expect(screen.getByText("Child", { selector: ".role-badge" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage child privacy/i })).toBeInTheDocument();

    const childrenButton = screen.getByRole("button", { name: /^children \d+$/i });
    expect(within(childrenButton).getByText("1")).toBeInTheDocument();
  });

  it("offers managed-child photo actions and updates the member avatar from the canonical response", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), childMember()]);
    (api.uploadMemberAvatar as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...childMember(),
      avatar_version: "child-photo.webp",
    });

    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Young Person")).toBeInTheDocument());

    const picker = screen.getByLabelText(/add young person's photo/i);
    fireEvent.change(picker, {
      target: { files: [new File(["photo"], "child.jpg", { type: "image/jpeg" })] },
    });

    await waitFor(() =>
      expect(api.uploadMemberAvatar).toHaveBeenCalledWith(
        "home-1",
        "u3",
        expect.any(File),
      ),
    );
    expect(await screen.findByRole("button", { name: /remove young person's photo/i })).toBeInTheDocument();
  });
});

// External Calendar Sharing replaces Extended Family/Friend as a Home-member
// relationship (see mykhaya.routers.calendar_sharing) — new invitations must
// ask "does this person live in your household?" first, route "no" to
// calendar sharing instead of sending an invitation, and never offer
// Extended Family/Friend as a fresh Add-member option any more.
describe("Manage members page — external sharing replaces Extended Family/Friend", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  async function openAddMemberSheet() {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
  }

  it("asks whether the person lives in the household before showing any relationship picker", async () => {
    await openAddMemberSheet();
    expect(
      screen.getByText(/does this person live in your household/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Relationship")).not.toBeInTheDocument();
  });

  it("routes 'outside the household' to calendar sharing instead of sending an invitation", async () => {
    await openAddMemberSheet();
    fireEvent.click(screen.getByRole("button", { name: /no, they.?re outside the household/i }));

    expect(screen.queryByLabelText("Relationship")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /share a calendar/i }),
    ).toHaveAttribute("href", "/calendar/calendars");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("never offers Extended Family or Friend as a new relationship option", async () => {
    await openAddMemberSheet();
    fireEvent.click(screen.getByRole("button", { name: /yes, they live here/i }));

    const select = screen.getByLabelText("Relationship");
    const optionLabels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(optionLabels).not.toContain("Extended Family");
    expect(optionLabels).not.toContain("Friend");
  });
});

describe("Manage members page — explicit Family sponsorship", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  it("shows the explicit sponsorship choice on an adult email invitation", async () => {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, they live here/i }));
    await userEvent.setup().selectOptions(screen.getByLabelText("Relationship"), "adult");

    expect(screen.getByText(/yes, give them family access/i)).toBeInTheDocument();
    expect(screen.getByText(/personal home is not upgraded/i)).toBeInTheDocument();
  });

  it("sends the checked sponsorship choice with an invitation", async () => {
    const user = userEvent.setup();
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /add member/i }));
    await user.click(screen.getByRole("button", { name: /yes, they live here/i }));
    await user.selectOptions(screen.getByLabelText("Relationship"), "adult");
    await user.type(screen.getByLabelText("Email"), "sponsored@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/invitations",
        expect.objectContaining({ family_sponsorship: true }),
      ),
    );
  });

  it("renders member sponsorship state and exposes a revoke action", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      ownerMember(),
      { ...partnerMember(), family_sponsored: true, family_access: true },
    ]);
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Partner Person")).toBeInTheDocument());

    expect(screen.getByText(/family access shared from this home/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop sharing family/i })).toBeInTheDocument();
  });

  it("shows Home Admin access as Home-derived and never offers self-sponsorship controls", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...ownerMember(), family_sponsored: true, family_access: true },
      { ...partnerMember(), family_sponsored: true, family_access: true },
    ]);
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());

    expect(screen.getByText("Provided by this Home’s Family plan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop sharing family/i })).toBeInTheDocument();
    const ownerCard = screen.getByText("Owner").closest("article") ?? screen.getByText("Owner").parentElement;
    expect(within(ownerCard as HTMLElement).queryByRole("button", { name: /stop sharing family/i })).not.toBeInTheDocument();
  });
});

describe("Manage members page — Home join codes", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  async function openJoinCodePanel() {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, they live here/i }));
    fireEvent.click(screen.getByRole("button", { name: "Share join code" }));
  }

  it("offers a method choice between inviting by email and sharing a join code", async () => {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, they live here/i }));

    expect(screen.getByRole("button", { name: "Invite by email" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Share join code" })).toBeInTheDocument();
    // Email remains the default — existing behaviour is unchanged unless
    // "Share join code" is explicitly chosen.
    expect(screen.getByLabelText("Relationship")).toBeInTheDocument();
  });

  it("offers to generate a code when none exists yet", async () => {
    await openJoinCodePanel();
    await waitFor(() => expect(api.getHomeJoinCode).toHaveBeenCalledWith("home-1"));
    expect(screen.getByRole("button", { name: "Generate a join code" })).toBeInTheDocument();
  });

  it("generating a code displays it with Copy and Generate new code actions", async () => {
    const user = userEvent.setup();
    (api.regenerateHomeJoinCode as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: "K7P4-X2RM",
      generated_at: "2026-01-01T00:00:00Z",
    });
    await openJoinCodePanel();
    await user.click(screen.getByRole("button", { name: "Generate a join code" }));

    await waitFor(() => expect(api.regenerateHomeJoinCode).toHaveBeenCalledWith("home-1"));
    expect(await screen.findByText("K7P4-X2RM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate new code" })).toBeInTheDocument();
  });

  it("shows the existing code without needing to regenerate", async () => {
    (api.getHomeJoinCode as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: "M3NP-77QW",
      generated_at: "2026-01-01T00:00:00Z",
    });
    await openJoinCodePanel();
    expect(await screen.findByText("M3NP-77QW")).toBeInTheDocument();
    expect(api.regenerateHomeJoinCode).not.toHaveBeenCalled();
  });

  it("non-admin members do not see the Add member / join-code controls", async () => {
    setActiveHomeForTest({
      ...familyHomeWithGrowthRoom(),
      capabilities: [],
    });
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /add member/i })).not.toBeInTheDocument();
  });
});

describe("Manage members page — pending join requests", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  function pendingRequest() {
    return {
      id: "req-1",
      user_id: "u9",
      display_name: "Sarah Smith",
      email: "sarah@example.com",
      status: "pending" as const,
      method: "join_code",
      created_at: "2026-01-01T00:00:00Z",
    };
  }

  it("shows pending join requests with the requester's identity and method", async () => {
    (api.listHomeJoinRequests as ReturnType<typeof vi.fn>).mockResolvedValue([pendingRequest()]);
    render(<ManageMembers />);

    expect(await screen.findByText("Join requests (1)")).toBeInTheDocument();
    expect(screen.getByText("Sarah Smith")).toBeInTheDocument();
    expect(screen.getByText(/Requested using Home code/)).toBeInTheDocument();
  });

  it("requires the Home Admin to choose a relationship before approving", async () => {
    const user = userEvent.setup();
    (api.listHomeJoinRequests as ReturnType<typeof vi.fn>).mockResolvedValue([pendingRequest()]);
    (api.approveHomeJoinRequest as ReturnType<typeof vi.fn>).mockResolvedValue({});
    render(<ManageMembers />);
    await screen.findByText("Sarah Smith");

    await user.selectOptions(
      screen.getByLabelText("Relationship for Sarah Smith"),
      "adult",
    );
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(api.approveHomeJoinRequest).toHaveBeenCalledWith("home-1", "req-1", {
        relationship: "adult",
        confirmed: true,
      }),
    );
  });

  it("declining a request does not approve or create membership", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.listHomeJoinRequests as ReturnType<typeof vi.fn>).mockResolvedValue([pendingRequest()]);
    (api.declineHomeJoinRequest as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    render(<ManageMembers />);
    await screen.findByText("Sarah Smith");

    await user.click(screen.getByRole("button", { name: "Decline" }));

    await waitFor(() =>
      expect(api.declineHomeJoinRequest).toHaveBeenCalledWith("home-1", "req-1", {
        confirmed: true,
      }),
    );
    expect(api.approveHomeJoinRequest).not.toHaveBeenCalled();
  });

  it("does not show a Join requests section when there are none pending", async () => {
    render(<ManageMembers />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    expect(screen.queryByText(/Join requests/)).not.toBeInTheDocument();
  });
});
