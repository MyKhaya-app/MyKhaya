import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { SettingsPage } from "./settings-page";

// Coverage for the grouped More menu (consolidating Home settings' old
// "Khaya Control Centre" entry and its standalone hub route — see
// components/khaya-control-shell.tsx and the deleted
// app/khaya-control-centre/page.tsx) into one flat set of section cards.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings",
}));

let activeHomeValue: { id: string; name: string; relationship: string } | null = {
  id: "home-1",
  name: "Hales Home",
  relationship: "home_admin",
};
vi.mock("./use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: activeHomeValue,
    activeHomeId: activeHomeValue?.id ?? null,
    homes: activeHomeValue ? [activeHomeValue] : [],
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
      me: vi.fn(),
      featureMatrix: vi.fn(),
      billingStatus: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

// Family Home, Wishlists module released and entitled — the "everything
// normal" default so every pre-existing test (none of which care about
// Wishlists specifically) sees it exactly as any other always-on row,
// same as Nudges/Lists/Meal Plans already behave for them.
function mockModuleState(overrides: { wishlistsFeatureOn?: boolean; wishlistsEntitled?: boolean } = {}) {
  const { wishlistsFeatureOn = true, wishlistsEntitled = true } = overrides;
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "wish_lists", enabled: wishlistsFeatureOn }],
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    wishlists_enabled: wishlistsEntitled,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  activeHomeValue = { id: "home-1", name: "Hales Home", relationship: "home_admin" };
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  mockModuleState();
  global.fetch = vi.fn().mockRejectedValue(new Error("no build info in tests"));
});

// name -> [subtitle, href] for every row the approved mockup specifies —
// asserted verbatim so a future edit can't silently drift the copy.
const MOCKUP_ROWS: Record<string, [string, string]> = {
  Wishlists: [
    "Gift ideas for birthdays and Christmas, shared without spoiling the surprise",
    "/wish-lists",
  ],
  "Home settings": ["Name, details, region and ownership", "/settings/home"],
  "Members and roles": ["Relationships, invitations and access", "/settings/members"],
  "Child permissions": ["Guardians, age bands and privacy", "/khaya-control-centre/children"],
  "Calendar tags": ["Colour and organise your events", "/settings/calendar-tags"],
  "Home calendars": ["Manage shared calendars and permissions", "/calendar/calendars"],
  "Module management": [
    "Choose which MyKhaya features are available in this home",
    "/khaya-control-centre/feature-management",
  ],
  Security: ["Review account and session protection", "/settings/security"],
  Devices: ["Manage your trusted devices", "/settings/security#devices"],
  "Help & Support": ["Knowledge base, support tickets and service status", "/help-support"],
  "About MyKhaya": ["Version information and useful links", "/about"],
};

describe("More — mockup-specified rows", () => {
  it.each(Object.entries(MOCKUP_ROWS))(
    "%s links to its canonical destination with the approved subtitle",
    async (name, [detail, href]) => {
      render(<SettingsPage />);
      const heading = await screen.findByRole("heading", { name });
      const row = heading.closest("a");
      expect(row).toHaveAttribute("href", href);
      expect(screen.getByText(detail)).toBeInTheDocument();
    },
  );

  it("groups every row into the approved sections, in order, mockup groups verbatim", async () => {
    const { container } = render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const groupLabels = Array.from(container.querySelectorAll(".more-group-label")).map(
      (el) => el.textContent,
    );
    expect(groupLabels).toEqual([
      "You",
      "Household tools",
      "Home & people",
      "Calendar",
      "Features",
      "Plan & billing",
      "Account & security",
      "Support",
    ]);
  });
});

describe("More — preserved existing destinations", () => {
  it("still reaches Profile, Notifications, Nudges, Lists, Meal Plans and Plan & Billing", async () => {
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const expectations: [string, string][] = [
      ["Profile", "/settings/profile"],
      ["Notifications", "/settings/notifications"],
      ["Nudges", "/settings/routines-reminders"],
      ["Lists", "/lists"],
      ["Meal Plans", "/meal-plans"],
      ["Wishlists", "/wish-lists"],
      ["Plan & Billing", "/settings/billing"],
    ];
    for (const [name, href] of expectations) {
      const heading = screen.getByRole("heading", { name });
      expect(heading.closest("a")).toHaveAttribute("href", href);
    }
  });
});

describe("More — no Control Centre duplication", () => {
  it("does not show Khaya Control Centre as its own destination, even for a Home Admin", async () => {
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Home settings" });
    expect(screen.queryByRole("heading", { name: "Khaya Control Centre" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /khaya control centre/i })).not.toBeInTheDocument();
  });

  it("does not render the inline version/debug footer", async () => {
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Home settings" });
    expect(screen.queryByText(/MyKhaya \d+\.\d+\.\d+/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SW: not active/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\(development\)/)).not.toBeInTheDocument();
  });

  it("does not introduce any duplicate destinations", async () => {
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const headings = await screen.findAllByRole("heading", { level: 2 });
    const hrefs = headings.map((heading) => heading.closest("a")?.getAttribute("href"));
    const definedHrefs = hrefs.filter((href): href is string => Boolean(href));
    expect(new Set(definedHrefs).size).toBe(definedHrefs.length);
  });
});

describe("More — permission gating", () => {
  it("hides Child permissions and Module management from an adult who isn't the Home Admin", async () => {
    activeHomeValue = { id: "home-1", name: "Hales Home", relationship: "partner" };
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Home settings" });
    expect(screen.queryByRole("heading", { name: "Child permissions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Module management" })).not.toBeInTheDocument();
    // Still available — being a manager, not the Home Admin, is enough.
    expect(screen.getByRole("heading", { name: "Home settings" })).toBeInTheDocument();
  });

  it("hides every adult-only row for a managed Child", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "child-1",
      display_name: "Riley",
      principal_type: "managed_child",
    });
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Help & Support" });
    for (const name of [
      "Home settings",
      "Members and roles",
      "Child permissions",
      "Module management",
      "Plan & Billing",
      "Security",
      "Devices",
    ]) {
      expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
    }
    // Not adult-gated — still available to a Child.
    expect(screen.getByRole("heading", { name: "Calendar tags" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Home calendars" })).toBeInTheDocument();
  });
});

describe("More — green hero header", () => {
  it("shows the More heading, subtitle and a decorative, assistive-technology-hidden flower", async () => {
    const { container } = render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const hero = container.querySelector(".more-hero");
    expect(hero).not.toBeNull();
    expect(within(hero as HTMLElement).getByRole("heading", { name: "More" })).toBeInTheDocument();
    expect(screen.getByText("Everything else for your home")).toBeInTheDocument();

    const flower = container.querySelector(".hero-flower");
    expect(flower).not.toBeNull();
    expect(flower).toHaveAttribute("aria-hidden", "true");
  });

  it("does not show the hero on a regular settings sub-page (children supplied)", async () => {
    const { container } = render(
      <SettingsPage title="Security">
        <p>content</p>
      </SettingsPage>,
    );
    expect(await screen.findByRole("heading", { name: "Security" })).toBeInTheDocument();
    expect(container.querySelector(".more-hero")).toBeNull();
  });

  // The static AppHeader (rendered by AppShell, above this component) already
  // shows the MyKhaya icon/home name/avatar — the hero must not repeat a
  // second logo/icon. See the "Simplify the green More header" fix.
  it("does not render a second MyKhaya logo/icon inside the hero", async () => {
    const { container } = render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const hero = container.querySelector(".more-hero") as HTMLElement;
    expect(hero.querySelector(".more-hero-icon")).toBeNull();
    expect(within(hero).queryByLabelText("MyKhaya")).not.toBeInTheDocument();
  });
});

// Product-consistency follow-up: Wishlists is a released optional Home
// module (see docs/architecture/commercial-entitlements.md) and must appear
// in More using the same featureMatrix/billingStatus-aware pattern the Home
// dashboard's quick actions already use for it (app/home/page.tsx) — never
// a hardcoded always-active link, and never fully hidden just because it's
// not entitled on the current plan.
describe("More — Wishlists module state", () => {
  it("appears in More as a normal, actionable row when the module is released and this Home's plan includes it", async () => {
    mockModuleState({ wishlistsFeatureOn: true, wishlistsEntitled: true });
    render(<SettingsPage />);
    const heading = await screen.findByRole("heading", { name: "Wishlists" });
    const row = heading.closest("a")!;
    expect(row).toHaveAttribute("href", "/wish-lists");
    expect(row.className).not.toContain("more-row-locked");
    expect(within(row).queryByText("Included with MyKhaya Family")).not.toBeInTheDocument();
    expect(
      screen.getByText("Gift ideas for birthdays and Christmas, shared without spoiling the surprise"),
    ).toBeInTheDocument();
  });

  it("shows Wishlists as locked/Family-only on Free, without presenting it as normally usable", async () => {
    mockModuleState({ wishlistsFeatureOn: true, wishlistsEntitled: false });
    render(<SettingsPage />);
    const heading = await screen.findByRole("heading", { name: "Wishlists" });
    const row = heading.closest("a")!;
    // Still visible and still a normal link to the canonical route — the
    // destination page's own FamilyUpsell gate handles the actual upgrade
    // experience, matching the Home dashboard quick action's convention.
    expect(row).toHaveAttribute("href", "/wish-lists");
    expect(row.className).toContain("more-row-locked");
    expect(within(row).getByText("Included with MyKhaya Family")).toBeInTheDocument();
    // The normal subtitle is replaced, not merely appended alongside a
    // "fully usable" presentation.
    expect(
      within(row).queryByText(
        "Gift ideas for birthdays and Christmas, shared without spoiling the surprise",
      ),
    ).not.toBeInTheDocument();
  });

  it("does not show Wishlists at all when the Home Admin has disabled the module for this Family Home", async () => {
    mockModuleState({ wishlistsFeatureOn: false, wishlistsEntitled: true });
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });
    expect(screen.queryByRole("heading", { name: "Wishlists" })).not.toBeInTheDocument();
  });

  it("does not show Wishlists at all when the platform flag is off", async () => {
    mockModuleState({ wishlistsFeatureOn: false, wishlistsEntitled: false });
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });
    expect(screen.queryByRole("heading", { name: "Wishlists" })).not.toBeInTheDocument();
  });

  it("leaves every other More row unaffected by the module-state fetch", async () => {
    mockModuleState({ wishlistsFeatureOn: false, wishlistsEntitled: false });
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });
    for (const name of ["Profile", "Notifications", "Nudges", "Lists", "Meal Plans", "Plan & Billing"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  });

  it("still does not show Notifications, External sharing, Tasks or Plans as ordinary modules", async () => {
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });
    // Notifications legitimately has its own settings row — this checks it
    // never grows a *second*, module-styled entry alongside it.
    expect(screen.getAllByRole("heading", { name: "Notifications" })).toHaveLength(1);
    for (const nonModule of ["External sharing", "External Sharing", "Tasks", "Plans"]) {
      expect(screen.queryByRole("heading", { name: nonModule })).not.toBeInTheDocument();
    }
  });
});
