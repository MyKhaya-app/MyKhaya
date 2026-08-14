import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home } from "@mykhaya/shared-types";
import RoutineSettings from "./page";

// Locked-state coverage for the Free plan enforcement pass: the "Household"
// routine scope must be disabled (not just rejected on save) before a Free
// Home can select it — see docs/architecture/commercial-entitlements.md
// "Free plan enforcement pass".

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/routines",
}));

function freeHome(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["household.manage_routines"],
    member_count: 1,
    child_login_code: "1234",
  };
}

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
      routines: vi.fn().mockResolvedValue({ items: [] }),
      billingStatus: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
});

describe("Routine settings — Free plan locked states", () => {
  it("disables the Household option and shows the Family upsell on Free", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      household_routines_enabled: false,
      member_usage: { count: 1, limit: 1, over_limit: false },
      calendar_usage: { count: 1, limit: 1, over_limit: false },
      shared_events_enabled: false,
      external_invites_enabled: false,
    });

    render(<RoutineSettings />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /add a routine/i }));

    const householdOption = await screen.findByRole("option", {
      name: /household/i,
    });
    expect(householdOption).toBeDisabled();
    expect(screen.getByText("Household routines")).toBeInTheDocument();
    expect(screen.getByText(/available with myKhaya family/i)).toBeInTheDocument();
  });

  it("leaves the Household option selectable on Family", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      household_routines_enabled: true,
      member_usage: { count: 1, limit: null, over_limit: false },
      calendar_usage: { count: 1, limit: null, over_limit: false },
      shared_events_enabled: true,
      external_invites_enabled: true,
    });

    render(<RoutineSettings />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /add a routine/i }));

    const householdOption = await screen.findByRole("option", {
      name: /household/i,
    });
    await waitFor(() => expect(householdOption).not.toBeDisabled());
  });
});
