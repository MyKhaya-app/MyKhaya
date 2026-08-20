import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { BillingStatus, Home, Member } from "@mykhaya/shared-types";
import People from "./page";

// Locked-state coverage for the Free plan enforcement pass: "Add member"
// must not render as a normal action on a Free Home at its member limit,
// and Extended Family/Friend must show the Family-only treatment — see
// docs/architecture/commercial-entitlements.md "Free plan enforcement
// pass".

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/people",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: freeHome(),
    activeHomeId: "home-1",
    homes: [freeHome()],
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
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
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
