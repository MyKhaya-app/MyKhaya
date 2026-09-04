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
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  activeHomeValue = { id: "home-1", name: "Hales Home", relationship: "home_admin" };
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  global.fetch = vi.fn().mockRejectedValue(new Error("no build info in tests"));
});

// name -> [subtitle, href] for every row the approved mockup specifies —
// asserted verbatim so a future edit can't silently drift the copy.
const MOCKUP_ROWS: Record<string, [string, string]> = {
  "Home settings": ["Name, details, region and ownership", "/settings/home"],
  "Members and roles": ["Relationships, invitations and access", "/people"],
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
  it("still reaches Profile, Notifications, Routines & Reminders, Lists, Meal Plans and Plan & Billing", async () => {
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Home settings" });

    const expectations: [string, string][] = [
      ["Profile", "/settings/profile"],
      ["Notifications", "/settings/notifications"],
      ["Routines & Reminders", "/settings/routines-reminders"],
      ["Lists", "/lists"],
      ["Meal Plans", "/meal-plans"],
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
