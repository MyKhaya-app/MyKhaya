import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
  useParams: () => ({ id: "home-1" }),
  usePathname: () => "/homes/home-1",
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const activeHome = {
  id: "home-1",
  name: "The Smiths",
  active: true,
  lifecycle: "active" as const,
  created_at: "2026-01-01T00:00:00Z",
  members: [{ user_id: "u1", display_name: "Jane Smith", email: "jane@example.com", role: "owner" }],
  pending_invitations: [{ id: "inv-1", email: "invitee@example.com", role: "member", expires_at: "2026-12-01T00:00:00Z" }],
  feature_overrides: [{ feature: "calendar", enabled: true }],
  modules: [
    {
      id: "calendar",
      name: "Calendar",
      platform_enabled: true,
      entitled: true,
      home_override: true,
      effective_enabled: true,
      blocked_by: null,
      toggleable: true,
    },
    {
      id: "nudges",
      name: "Nudges",
      platform_enabled: true,
      entitled: false,
      home_override: null,
      effective_enabled: false,
      blocked_by: "plan" as const,
      toggleable: true,
    },
    {
      id: "meals",
      name: "Meal Plans",
      platform_enabled: false,
      entitled: true,
      home_override: null,
      effective_enabled: false,
      blocked_by: "platform" as const,
      toggleable: true,
    },
    {
      id: "wish_lists",
      name: "Wishlists",
      platform_enabled: true,
      entitled: true,
      home_override: false,
      effective_enabled: false,
      blocked_by: "home" as const,
      toggleable: true,
    },
  ],
  notes: [{ id: "note-1", body: "Called about billing.", created_at: "2026-02-01T00:00:00Z" }],
};
const suspendedHome = { ...activeHome, active: false, lifecycle: "disabled" as const };
const archivedHome = { ...activeHome, active: false, lifecycle: "archived" as const };
const emptyHome = { ...activeHome, members: [], pending_invitations: [], notes: [] };

// Realistic module states as the backend would actually compute them for a
// Free vs Family Home (mykhaya.entitlements.PLAN_DEFINITIONS) — platform is
// on and no Home override exists for any of these in either fixture, so
// only entitlement varies.
function freeModules() {
  return [
    { id: "calendar", name: "Calendar", platform_enabled: true, entitled: true, home_override: null, effective_enabled: true, blocked_by: null, toggleable: true },
    { id: "shopping", name: "Lists", platform_enabled: true, entitled: true, home_override: null, effective_enabled: true, blocked_by: null, toggleable: true },
    { id: "nudges", name: "Nudges", platform_enabled: true, entitled: false, home_override: null, effective_enabled: false, blocked_by: "plan" as const, toggleable: true },
    { id: "meals", name: "Meal Plans", platform_enabled: true, entitled: false, home_override: null, effective_enabled: false, blocked_by: "plan" as const, toggleable: true },
    { id: "wish_lists", name: "Wishlists", platform_enabled: true, entitled: false, home_override: null, effective_enabled: false, blocked_by: "plan" as const, toggleable: true },
  ];
}

function familyModules() {
  return freeModules().map((module) => ({ ...module, entitled: true, effective_enabled: true, blocked_by: null }));
}

const freeHome = { ...activeHome, modules: freeModules() };
const familyHome = { ...activeHome, modules: familyModules() };

function findDialog(name: RegExp | string) {
  return screen.findByRole("dialog", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
  routerPush.mockClear();
  get.mockResolvedValue(activeHome);
  post.mockResolvedValue({ message: "ok" });
  put.mockResolvedValue({});
});

describe("Home detail", () => {
  it("renders home metadata and an Active status", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getByText("home-1")).toBeInTheDocument();
  });

  it("shows a Disabled status and a Reactivate action when the home is suspended", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Reactivate Home" })).toBeInTheDocument();
  });

  it("renders memberships, invitations and notes", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText(/jane@example.com/)).toBeInTheDocument();
    expect(screen.getByText("invitee@example.com")).toBeInTheDocument();
    expect(screen.getByText("Called about billing.")).toBeInTheDocument();
  });

  it("shows empty states when there are no members, invitations or notes", async () => {
    get.mockResolvedValue(emptyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("No members yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending invitations.")).toBeInTheDocument();
    expect(screen.getByText("No administrative notes yet.")).toBeInTheDocument();
  });

  it("requires a reason of at least 10 characters before suspending, and sends the exact payload", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    const confirmButton = within(dialog).getByRole("button", { name: "Suspend Home" });
    const reasonInput = within(dialog).getByLabelText(/reason for this administrative action/i);
    expect(reasonInput).toHaveAttribute("minLength", "10");
    expect(reasonInput).toHaveAttribute("maxLength", "500");
    expect(reasonInput).toBeRequired();

    await userEvent.type(reasonInput, "Suspending pending a billing dispute");
    await userEvent.click(confirmButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/suspend", {
        reason: "Suspending pending a billing dispute",
        confirmed: true,
      }),
    );
  });

  it("reactivates symmetrically", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reactivate Home" }));
    const dialog = await findDialog(/Reactivate Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reactivating per request");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reactivate Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/reactivate", {
        reason: "Reactivating per request",
        confirmed: true,
      }),
    );
  });

  it("requires confirmation and a reason to toggle a feature flag, and sends it to the exact endpoint", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    // Calendar is effectively enabled in the fixture, so its action is "Disable".
    const calendarRow = screen.getByText("Calendar").closest("article")!;
    await userEvent.click(within(calendarRow).getByRole("button", { name: "Disable" }));
    const dialog = await findDialog(/Disable Calendar/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Turning off calendar module");
    await userEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/homes/home-1/feature-flags/calendar", {
        enabled: false,
        reason: "Turning off calendar module",
        confirmed: true,
      }),
    );
  });

  // PCC Polish Phase 1: operators need to understand WHY a module resolves
  // the way it does, not just a flattened Enabled/Disabled — see
  // routers.platform.home_detail's modules field and
  // routers.features.module_state.
  it("shows a platform-blocked module's reason distinctly", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Meal Plans").closest("article")!;
    expect(within(row).getByText("Effective: Blocked by platform")).toBeInTheDocument();
    expect(within(row).getByText("Platform: Disabled")).toBeInTheDocument();
  });

  it("shows a plan-blocked module's reason distinctly", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Nudges").closest("article")!;
    expect(within(row).getByText("Effective: Not included in plan")).toBeInTheDocument();
    expect(within(row).getByText("Plan: Not included")).toBeInTheDocument();
  });

  it("shows a Home-disabled module distinctly from platform/plan blocked", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Wishlists").closest("article")!;
    expect(within(row).getByText("Effective: Disabled by Home")).toBeInTheDocument();
    expect(within(row).getByText("Platform: Enabled")).toBeInTheDocument();
    expect(within(row).getByText("Plan: Included")).toBeInTheDocument();
    expect(within(row).getByText("Home: Disabled")).toBeInTheDocument();
  });

  it("shows an enabled/inherited module truthfully", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Calendar").closest("article")!;
    expect(within(row).getByText("Effective: Enabled")).toBeInTheDocument();
    expect(within(row).getByText("Home: Enabled")).toBeInTheDocument();
  });

  it("never shows a platform-off module as effectively enabled even when the Home override is on", async () => {
    // Meal Plans: platform disabled, entitled true, no Home override — a
    // Home override can never bypass a platform-wide OFF (see
    // mykhaya.features.is_feature_enabled).
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Meal Plans").closest("article")!;
    expect(within(row).queryByText("Effective: Enabled")).not.toBeInTheDocument();
  });

  it("shows Nudges/Meal Plans/Wishlists as plan-blocked on a Free Home, and Calendar/Lists as included", async () => {
    get.mockResolvedValue(freeHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    for (const name of ["Nudges", "Meal Plans", "Wishlists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByText("Effective: Not included in plan")).toBeInTheDocument();
    }
    for (const name of ["Calendar", "Lists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByText("Effective: Enabled")).toBeInTheDocument();
      expect(within(row).getByText("Plan: Included")).toBeInTheDocument();
    }
  });

  it("shows every optional module as entitled and enabled on a Family Home", async () => {
    get.mockResolvedValue(familyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    for (const name of ["Calendar", "Lists", "Nudges", "Meal Plans", "Wishlists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByText("Effective: Enabled")).toBeInTheDocument();
      expect(within(row).getByText("Plan: Included")).toBeInTheDocument();
    }
  });

  // PCC Polish Phase 1 (correction): the Home enable/disable control must
  // never be clickable when the module is blocked by platform or plan — a
  // Home override can never make it effectively available from this layer
  // (see mykhaya.features.is_feature_enabled), so offering the control
  // there would let an operator attempt a meaningless override.
  it("disables the Home control for a platform-blocked module", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Meal Plans").closest("article")!;
    expect(within(row).getByRole("button", { name: "Enable" })).toBeDisabled();
    expect(within(row).getByText("Controlled by platform")).toBeInTheDocument();
  });

  it("disables the Home control for a plan-blocked module", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Nudges").closest("article")!;
    expect(within(row).getByRole("button", { name: "Enable" })).toBeDisabled();
    expect(within(row).getByText("Not included in this Home's plan")).toBeInTheDocument();
  });

  it("keeps the Home control actionable for a Home-disabled module, so it can still be enabled", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Wishlists").closest("article")!;
    const button = within(row).getByRole("button", { name: "Enable" });
    expect(button).not.toBeDisabled();
  });

  it("keeps the Home control actionable for an enabled module, so it can still be disabled", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Calendar").closest("article")!;
    const button = within(row).getByRole("button", { name: "Disable" });
    expect(button).not.toBeDisabled();
  });

  it("keeps Calendar/Lists actionable on a Free Home, since they're included", async () => {
    get.mockResolvedValue(freeHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    for (const name of ["Calendar", "Lists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByRole("button", { name: "Disable" })).not.toBeDisabled();
    }
  });

  it("disables Nudges/Meal Plans/Wishlists on a Free Home, since none are included in plan", async () => {
    get.mockResolvedValue(freeHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    for (const name of ["Nudges", "Meal Plans", "Wishlists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByRole("button", { name: "Enable" })).toBeDisabled();
    }
  });

  it("keeps every entitled module actionable on a Family Home", async () => {
    get.mockResolvedValue(familyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    for (const name of ["Calendar", "Lists", "Nudges", "Meal Plans", "Wishlists"]) {
      const row = screen.getByText(name).closest("article")!;
      expect(within(row).getByRole("button", { name: "Disable" })).not.toBeDisabled();
    }
  });

  it("disables a platform-blocked module even on a Family Home that is otherwise entitled", async () => {
    const platformBlockedFamilyHome = {
      ...familyHome,
      modules: familyHome.modules.map((module) =>
        module.id === "meals"
          ? { ...module, platform_enabled: false, effective_enabled: false, blocked_by: "platform" as const }
          : module,
      ),
    };
    get.mockResolvedValue(platformBlockedFamilyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const row = screen.getByText("Meal Plans").closest("article")!;
    expect(within(row).getByRole("button", { name: "Enable" })).toBeDisabled();
    expect(within(row).getByText("Effective: Blocked by platform")).toBeInTheDocument();
  });

  it("never shows Notifications, External sharing, Tasks or Plans as ordinary Home modules", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    // Scoped to the module-availability section specifically — PlatformShell's
    // own sidebar legitimately has an unrelated "Notifications" nav link.
    const section = screen.getByRole("heading", { name: "Module availability" }).closest("section")!;
    for (const nonModule of ["Notifications", "External sharing", "Tasks", "Plans"]) {
      expect(within(section).queryByText(nonModule)).not.toBeInTheDocument();
    }
  });

  it("adds a note without requiring a reason and reloads", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    await userEvent.type(screen.getByLabelText("New internal note"), "A fresh note");
    await userEvent.click(screen.getByRole("button", { name: "Add administrative note" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/homes/home-1/notes", { body: "A fresh note" }));
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/homes/home-1")).toHaveLength(2),
    );
  });

  it("shows the reauth modal on a 403 and retries suspend after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/homes/home-1/suspend") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({ message: "Home suspended." });
      }
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Home suspended.")).toBeInTheDocument());
    expect(post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend")).toHaveLength(2);
  });

  it("shows a safe error message when an action fails", async () => {
    post.mockRejectedValueOnce(new Error("Home not found"));
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));
    expect(await screen.findByText("Home not found")).toBeInTheDocument();
  });
});

describe("Home detail — Archive lifecycle", () => {
  it("offers both Suspend and Archive for an active Home", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByRole("button", { name: "Suspend Home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore Home" })).not.toBeInTheDocument();
  });

  it("offers Reactivate and Archive for a disabled Home", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByRole("button", { name: "Reactivate Home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend Home" })).not.toBeInTheDocument();
  });

  it("shows Archived status and only a Restore action for an archived Home", async () => {
    get.mockResolvedValue(archivedHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Restore Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reactivate Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive Home" })).not.toBeInTheDocument();
  });

  it("archives a Home with a reason and reloads", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive Home" }));
    const dialog = await findDialog(/Archive Home/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Duplicate test Home",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/archive", {
        reason: "Duplicate test Home",
        confirmed: true,
      }),
    );
  });

  it("restores an archived Home with a reason and reloads", async () => {
    get.mockResolvedValue(archivedHome);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore Home" }));
    const dialog = await findDialog(/Restore Home/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Restoring by request",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/restore", {
        reason: "Restoring by request",
        confirmed: true,
      }),
    );
  });

  it("shows a clear API error when restore is rejected (e.g. no Home Admin)", async () => {
    get.mockResolvedValue(archivedHome);
    post.mockRejectedValueOnce(
      new ApiError(409, "This Home has no Home Admin. Assign one before restoring it."),
    );
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore Home" }));
    const dialog = await findDialog(/Restore Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Restoring");
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore Home" }));
    expect(
      await screen.findByText("This Home has no Home Admin. Assign one before restoring it."),
    ).toBeInTheDocument();
  });
});

describe("Home detail — Move member", () => {
  beforeEach(() => {
    get.mockImplementation((path: string) => {
      if (path === "/homes/home-1") return Promise.resolve(activeHome);
      if (path.startsWith("/homes?")) {
        return Promise.resolve({
          items: [{ id: "home-2", name: "Carol's Home", active: true, member_count: 1 }],
        });
      }
      return Promise.resolve(activeHome);
    });
  });

  it("opens the Move member dialog from a member row, fixed to this Home as the source", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const memberRow = screen.getByText("Jane Smith").closest("article")!;
    await userEvent.click(within(memberRow).getByRole("button", { name: "Move" }));

    const dialog = await findDialog(/Move member/i);
    // Source Home is fixed to this Home — no "From Home" picker, since there
    // is only ever one source Home when opened from a Home's own member row.
    expect(within(dialog).queryByLabelText(/from home/i)).not.toBeInTheDocument();
    expect(within(dialog).getByText("The Smiths")).toBeInTheDocument();
    // Source panel is passed this Home's own member count and lifecycle
    // status, both cheaply available on the Home-detail page already.
    expect(within(dialog).getByText("Active")).toBeInTheDocument();
    expect(within(dialog).getByText("1")).toBeInTheDocument();
  });

  it("moves the member and reloads this Home afterwards", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/users/u1/move-home") return Promise.resolve({ source_disposition: "left_unchanged" });
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const memberRow = screen.getByText("Jane Smith").closest("article")!;
    await userEvent.click(within(memberRow).getByRole("button", { name: "Move" }));

    const dialog = await findDialog(/Move member/i);
    await userEvent.type(within(dialog).getByLabelText(/find destination home/i), "Carol's Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Search" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: /Carol's Home/ }));
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reconciling Homes");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move member" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/u1/move-home", {
        source_group_id: "home-1",
        destination_group_id: "home-2",
        destination_relationship: "partner",
        source_disposition: "leave",
        reason: "Reconciling Homes",
        confirmed: true,
      }),
    );
    expect(await screen.findByText(/moved to Carol's Home/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/homes/home-1")).toHaveLength(2),
    );
  });
});

describe("Home detail — Permanent delete", () => {
  function mockEligibility(blockers: string[]) {
    get.mockImplementation((path: string) => {
      if (path === "/homes/home-1") return Promise.resolve(archivedHome);
      if (path === "/homes/home-1/permanent-delete/eligibility") {
        return Promise.resolve({ eligible: blockers.length === 0, blockers });
      }
      return Promise.resolve(archivedHome);
    });
  }

  it("only offers Permanently delete Home for an archived Home, not active/disabled", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.queryByRole("button", { name: "Permanently delete Home" })).not.toBeInTheDocument();

    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await screen.findAllByText("The Smiths");
    expect(screen.queryByRole("button", { name: "Permanently delete Home" })).not.toBeInTheDocument();

    mockEligibility([]);
    render(<DetailPage />);
    await screen.findAllByText("The Smiths");
    expect(screen.getByRole("button", { name: "Permanently delete Home" })).toBeInTheDocument();
  });

  it("checks eligibility on open and blocks confirmation while a blocker is present", async () => {
    mockEligibility(["has_active_members"]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Permanently delete Home" }));
    const dialog = await findDialog(/Permanently delete Home/i);
    expect(await within(dialog).findByText(/cannot be permanently deleted yet/i)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/type this home.?s name/i), "The Smiths");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Accidental test Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Permanently delete Home" }));
    expect(post).not.toHaveBeenCalledWith("/homes/home-1/permanent-delete", expect.anything());
    expect(routerPush).not.toHaveBeenCalled();
  });

  it("submits the typed name confirmation and reason, then navigates back to Homes", async () => {
    mockEligibility([]);
    post.mockResolvedValue({ message: "Home permanently deleted." });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Permanently delete Home" }));
    const dialog = await findDialog(/Permanently delete Home/i);
    await within(dialog).findByLabelText(/type this home.?s name/i);
    await userEvent.type(within(dialog).getByLabelText(/type this home.?s name/i), "The Smiths");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Accidental test Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Permanently delete Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/permanent-delete", {
        reason: "Accidental test Home",
        confirmation_text: "The Smiths",
        confirmed: true,
      }),
    );
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/homes"));
  });
});
