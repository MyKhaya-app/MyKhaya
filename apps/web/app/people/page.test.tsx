import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BillingStatus, Home, Member } from "@mykhaya/shared-types";
import People from "./page";

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
  usePathname: () => "/people",
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
    calendar_usage: { count: 1, limit: 1, over_limit: false },
    category_usage: { count: 1, limit: 1, over_limit: false },
    member_usage: { count: 1, limit: 1, over_limit: false },
    household_routines_enabled: false,
    shared_events_enabled: false,
    external_invites_enabled: false,
    meals_enabled: false,
    lists_enabled: false,
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
});

describe("People page — Free plan locked states", () => {
  it("hides Add member and shows the Family upsell when the Home is at its member limit", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember()]);
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(freeBillingStatus());

    render(<People />);

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

    render(<People />);

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
describe("People page — Adult relationship", () => {
  beforeEach(() => {
    setActiveHomeForTest(familyHomeWithGrowthRoom());
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(familyBillingStatus());
  });

  async function openAddMemberSheet() {
    render(<People />);
    await waitFor(() => expect(screen.getByText("Owner")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));
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

    render(<People />);
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

    render(<People />);
    await waitFor(() => expect(screen.getByText("Housemate Adult")).toBeInTheDocument());
    expect(screen.getByText("Adult", { selector: ".role-badge" })).toBeInTheDocument();
  });

  it("leaves Partner members working unchanged (label, filter, no child callout)", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), partnerMember()]);

    render(<People />);
    await waitFor(() => expect(screen.getByText("Partner Person")).toBeInTheDocument());
    expect(screen.getByText("Partner", { selector: ".role-badge" })).toBeInTheDocument();

    const adultsButton = screen.getByRole("button", { name: /^adults \d+$/i });
    expect(within(adultsButton).getByText("2")).toBeInTheDocument();
  });

  it("leaves Child members working unchanged (label, filter, manage-privacy link instead of a relationship selector)", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([ownerMember(), childMember()]);

    render(<People />);
    await waitFor(() => expect(screen.getByText("Young Person")).toBeInTheDocument());
    expect(screen.getByText("Child", { selector: ".role-badge" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage child privacy/i })).toBeInTheDocument();

    const childrenButton = screen.getByRole("button", { name: /^children \d+$/i });
    expect(within(childrenButton).getByText("1")).toBeInTheDocument();
  });
});
