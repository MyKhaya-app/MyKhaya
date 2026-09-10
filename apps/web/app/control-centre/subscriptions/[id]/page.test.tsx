import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SubscriptionDetail } from "@/components/platform-types";
import SubscriptionDetailPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/subscriptions/home-1",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

function freeDetail(): SubscriptionDetail {
  return {
    id: "home-1",
    name: "Hales Home",
    created_at: "2026-01-01T00:00:00Z",
    member_count: 3,
    administrators: [{ user_id: "u1", display_name: "Anthony", email: "anthony@example.com" }],
    subscription: {
      plan: "free",
      provider: "free",
      status: "active",
      billing_owner_user_id: null,
      external_customer_id: null,
      external_subscription_id: null,
      external_price_id: null,
      billing_interval: null,
      current_period_start: null,
      current_period_end: null,
      complimentary_reason: null,
      complimentary_note: null,
      complimentary_granted_by: null,
      complimentary_granted_by_display_name: null,
      complimentary_granted_at: null,
      complimentary_expires_at: null,
      effective_plan: "free",
      effective_status_reason: null,
    },
    entitlements: {
      plan: "free",
      booleans: { "lists.enabled": true },
      limits: { "calendar.max_categories": 1, "home.max_members": 1 },
    },
    calendar_usage: { count: 1, limit: 1, over_limit: false },
    member_usage: { count: 1, limit: 1, over_limit: false },
    personal_routines_total: 0,
    recent_webhook_events: [],
    billing_diagnostics: [],
    history: [],
    stripe_price: null,
    stripe_dashboard_customer_url: null,
    stripe_dashboard_subscription_url: null,
  };
}

function complimentaryDetail(): SubscriptionDetail {
  const base = freeDetail();
  return {
    ...base,
    subscription: {
      ...base.subscription,
      plan: "family",
      provider: "complimentary",
      complimentary_reason: "Beta tester",
      complimentary_granted_by_display_name: "Operator One",
      complimentary_granted_at: "2026-02-01T00:00:00Z",
      effective_plan: "family",
    },
  };
}

/**
 * `use()` reads a promise synchronously without suspending if the promise
 * already carries React's internal "fulfilled" cache shape — which is how
 * Next.js's own already-resolved `params` promises behave in practice.
 * Building one this way avoids wrapping every test in a Suspense boundary
 * and the cross-test scheduler flakiness that came with actually suspending
 * a fresh promise on every render.
 */
function resolvedParams(id: string): Promise<{ id: string }> {
  const promise = Promise.resolve({ id }) as Promise<{ id: string }> & {
    status?: string;
    value?: { id: string };
  };
  promise.status = "fulfilled";
  promise.value = { id };
  return promise;
}

function renderPage() {
  return render(<SubscriptionDetailPage params={resolvedParams("home-1")} />);
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  del.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SubscriptionDetailPage", () => {
  it("shows a loading state before data arrives", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : new Promise(() => {}),
    );
    renderPage();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    // Let PlatformShell's own /auth/me resolution settle before the test ends,
    // so it doesn't log an act() warning against the next test.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("renders the Free-plan Home with a grant action and no revoke action", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(freeDetail()),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Grant complimentary Family access" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove complimentary access" }),
    ).not.toBeInTheDocument();
  });

  it("renders the complimentary-access summary with a separated destructive action", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(complimentaryDetail()),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    expect(screen.getByText("Beta tester")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extend / update" })).toBeInTheDocument();
    const revokeButton = screen.getByRole("button", { name: "Remove complimentary access" });
    expect(revokeButton.className).toContain("danger");
  });

  it("opens the destructive confirm dialog and still requires a reason before revoking", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(complimentaryDetail()),
    );
    del.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Remove complimentary access" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Remove complimentary access" });
    expect(dialog).toHaveTextContent("This Home will return to its Free plan entitlements.");

    await user.type(
      screen.getByLabelText(/Reason for this administrative action/i),
      "Customer asked us to remove complimentary access",
    );
    await user.click(submit);

    await waitFor(() => expect(del).toHaveBeenCalledTimes(1));
    expect(del).toHaveBeenCalledWith(
      "/homes/home-1/subscription/complimentary",
      expect.objectContaining({ confirmed: true }),
    );
  });

  it("shows the stored-vs-effective divergence reason when plans differ", async () => {
    const detail = complimentaryDetail();
    detail.subscription.effective_plan = "free";
    detail.subscription.effective_status_reason = "Complimentary access expired";
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detail),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    expect(screen.getByText("Complimentary access expired")).toBeInTheDocument();
  });

  it("submits a grant with the entered reason", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(freeDetail()),
    );
    put.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Grant complimentary Family access" }));
    await screen.findByRole("dialog");
    await user.type(
      screen.getByLabelText(/Reason for this administrative action/i),
      "Approved beta tester per support ticket #42",
    );
    await user.click(screen.getByRole("button", { name: "Grant complimentary access" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put).toHaveBeenCalledWith(
      "/homes/home-1/subscription/complimentary",
      expect.objectContaining({ confirmed: true }),
    );
  });
});

// PCC Polish Phase 1: the final governance audit found live, enforced
// entitlements (Lists, Wishlists) still labelled "Planned" here, left over
// from before those modules shipped — see mykhaya.entitlements.
// PLAN_DEFINITIONS and each module's router for what's actually enforced
// today. These tests pin the corrected classification directly against a
// full entitlements fixture, independent of plan (Free vs Family only
// changes the *value* shown, never which badge — if any — a key gets).
describe("SubscriptionDetailPage — plan capability labels", () => {
  function detailWithEntitlements(overrides: Partial<SubscriptionDetail["entitlements"]>) {
    const base = freeDetail();
    return {
      ...base,
      entitlements: {
        plan: "free" as const,
        booleans: {
          "notes.enabled": true,
          "lists.enabled": true,
          "chores.enabled": false,
          "wishlists.enabled": false,
          "routines.household.enabled": false,
          "events.shared.enabled": false,
          "members.external_invites.enabled": false,
          "family_plans.enabled": false,
          "support.priority.enabled": false,
          "meals.enabled": false,
          "nudges.enabled": false,
        },
        limits: {
          "calendar.max_categories": 1,
          "calendar.max_calendars": 1,
          "home.max_members": 1,
          "routines.personal.max_active": 3,
          "lists.max_lists": 2,
        },
        ...overrides,
      },
    };
  }

  function capabilityRow(labelText: string) {
    const cell = screen.getByRole("cell", { name: labelText });
    const row = cell.closest("tr");
    if (!row) throw new Error(`No table row found for capability "${labelText}"`);
    return row as HTMLElement;
  }

  it("does not label Lists as Planned", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Lists");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).getByText("Up to 2")).toBeInTheDocument();
  });

  it("does not label Wishlists as Planned", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me"
        ? Promise.resolve(actor)
        : Promise.resolve(
            detailWithEntitlements({
              booleans: {
                ...detailWithEntitlements({}).entitlements.booleans,
                "wishlists.enabled": true,
              },
            }),
          ),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Gift Wishlists");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).getByText("Included")).toBeInTheDocument();
  });

  it("represents Meal Plans as live/enforced, not deferred", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Meal Plans");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).queryByText("Contract only")).not.toBeInTheDocument();
  });

  it("represents Nudges as live/enforced, not deferred", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Nudges (Routines, Reminders, To-dos)");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).queryByText("Contract only")).not.toBeInTheDocument();
  });

  it("does not show events.shared.enabled as deferred", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Shared family events");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).queryByText("Contract only")).not.toBeInTheDocument();
  });

  it("does not show members.external_invites.enabled as deferred", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Invite external members");
    expect(within(row).queryByText("Planned")).not.toBeInTheDocument();
    expect(within(row).queryByText("Contract only")).not.toBeInTheDocument();
  });

  it("keeps Notes as future/deferred (Contract only)", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Notes");
    expect(within(row).getByText("Contract only")).toBeInTheDocument();
  });

  it("keeps Chores as future/deferred (Contract only)", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Chores");
    expect(within(row).getByText("Contract only")).toBeInTheDocument();
  });

  it("keeps Family Plans as future/deferred (Contract only)", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Family Plans");
    expect(within(row).getByText("Contract only")).toBeInTheDocument();
  });

  it("keeps Priority Support as future/deferred (Contract only) since it remains unenforced", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Priority Support");
    expect(within(row).getByText("Contract only")).toBeInTheDocument();
  });

  it("shows Nudges-gated Personal routines as Not included on Free rather than a reachable-looking number", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(actor) : Promise.resolve(detailWithEntitlements({})),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Personal routines (within Nudges)");
    expect(within(row).getByText("Not included")).toBeInTheDocument();
  });

  it("shows the real Personal routines limit once Nudges is included (Family)", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me"
        ? Promise.resolve(actor)
        : Promise.resolve(
            detailWithEntitlements({
              booleans: {
                ...detailWithEntitlements({}).entitlements.booleans,
                "nudges.enabled": true,
              },
              limits: {
                ...detailWithEntitlements({}).entitlements.limits,
                "routines.personal.max_active": null,
              },
            }),
          ),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Hales Home")).toBeInTheDocument());
    const row = capabilityRow("Personal routines (within Nudges)");
    expect(within(row).getByText("Unlimited")).toBeInTheDocument();
  });
});
