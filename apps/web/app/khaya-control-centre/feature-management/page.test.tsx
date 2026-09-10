import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, HouseholdModule } from "@mykhaya/shared-types";
import FeatureManagementPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

function home(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["features.manage"],
    member_count: 1,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: home(),
    activeHomeId: "home-1",
    homes: [home()],
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
      featureManagement: vi.fn(),
      updateHouseholdFeature: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function module_(overrides: Partial<HouseholdModule> = {}): HouseholdModule {
  return {
    id: "nudges",
    name: "Nudges",
    description: "Routines, reminders and to-dos.",
    category: "Family",
    release_state: "released",
    enabled: true,
    toggleable: true,
    introduced_version: "0.5.0",
    dependencies: [],
    permissions: [],
    route: "/settings/routines-reminders",
    entitled: true,
    blocked_by: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Module management — Free vs Family plan awareness", () => {
  it("shows an enabled toggle for an entitled, available module", async () => {
    (api.featureManagement as ReturnType<typeof vi.fn>).mockResolvedValue([module_()]);
    render(<FeatureManagementPage />);

    expect(await screen.findByText("Nudges")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable Nudges" })).toBeInTheDocument();
  });

  it("shows a Family-required note, not a toggle, for a plan-blocked module", async () => {
    (api.featureManagement as ReturnType<typeof vi.fn>).mockResolvedValue([
      module_({ enabled: false, entitled: false, blocked_by: "plan" }),
    ]);
    render(<FeatureManagementPage />);

    expect(await screen.findByText("Nudges")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText(/Included with MyKhaya Family/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Family plan" })).toHaveAttribute(
      "href",
      "/settings/billing",
    );
    expect(
      screen.queryByRole("button", { name: /Enable Nudges/ }),
    ).not.toBeInTheDocument();
  });

  it("shows a platform-unavailable note, not a toggle, when PCC has disabled the module", async () => {
    (api.featureManagement as ReturnType<typeof vi.fn>).mockResolvedValue([
      module_({ enabled: false, entitled: true, blocked_by: "platform" }),
    ]);
    render(<FeatureManagementPage />);

    expect(await screen.findByText("Nudges")).toBeInTheDocument();
    expect(screen.getByText("Currently unavailable platform-wide.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Enable Nudges/ }),
    ).not.toBeInTheDocument();
  });

  it("still lets a Family Home toggle an entitled, available module", async () => {
    (api.featureManagement as ReturnType<typeof vi.fn>).mockResolvedValue([
      module_({ enabled: false }),
    ]);
    (api.updateHouseholdFeature as ReturnType<typeof vi.fn>).mockResolvedValue(
      module_({ enabled: true }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<FeatureManagementPage />);

    const button = await screen.findByRole("button", { name: "Enable Nudges" });
    await userEvent.click(button);

    expect(api.updateHouseholdFeature).toHaveBeenCalledWith(
      "home-1",
      "nudges",
      expect.objectContaining({ enabled: true }),
    );
  });
});
