import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PublicPricing } from "./public-pricing";

// The public pricing surface has three plans: Free, Family and Ultimate.
// Prices must always come from the live pricing API (never a hard-coded
// figure baked into the component), and every CTA must route through the
// same resolveCtaDestination logic the rest of the commercial journey uses.
// Family and Ultimate each own an independent Monthly/Annual selector.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      homes: vi.fn(),
      familyPricing: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

const familyPrices = {
  month: "£9.99",
  year: "£99.99",
};
const ultimatePrices = {
  month: "£14.99",
  year: "£149.99",
};

function pricingResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    plan: "family",
    options: [
      {
        interval: "month",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 999,
        formatted_amount: familyPrices.month,
      },
      {
        interval: "year",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 9999,
        formatted_amount: familyPrices.year,
      },
    ],
    annual_saving_formatted: "£19.89",
    annual_is_best_value: true,
    acquisition_enabled: true,
    ultimate_options: [
      {
        interval: "month",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 1499,
        formatted_amount: ultimatePrices.month,
      },
      {
        interval: "year",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 14999,
        formatted_amount: ultimatePrices.year,
      },
    ],
    ultimate_annual_saving_formatted: "£29.89",
    ultimate_acquisition_enabled: true,
    ...overrides,
  };
}

function mockPricing(overrides: Partial<Record<string, unknown>> = {}) {
  (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
    pricingResponse(overrides),
  );
}

function card(name: "free" | "family" | "ultimate"): HTMLElement {
  return document.querySelector(`.mk-plan-${name}`) as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockRejectedValue(
    new Error("not signed in"),
  );
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("PublicPricing — layout and copy", () => {
  it("renders the approved heading and supporting text", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Simple plans for modern family life",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /start free and upgrade when you’re ready\. all plans include a full set of core tools, with more for growing households\./i,
      ),
    ).toBeInTheDocument();
  });

  it("renders exactly three plan cards: Free, Family and Ultimate", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(
      screen.getByRole("heading", { level: 3, name: "Free" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Family" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Ultimate" }),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(3);
    expect(document.querySelectorAll(".mk-pricing-grid > article")).toHaveLength(
      3,
    );
  });

  it("shows the exact Free plan feature list, tagline and price", async () => {
    mockPricing();
    render(<PublicPricing />);

    const free = within(card("free"));
    for (const point of [
      "Calendar",
      "Events",
      "Notes",
      "1 calendar tag",
      "Up to 3 personal routines",
      "1 person",
    ]) {
      expect(free.getByText(point)).toBeInTheDocument();
    }
    expect(free.getByText("For individuals getting organised")).toBeInTheDocument();
    expect(free.getByText("£0")).toBeInTheDocument();
    expect(free.getByText(/\/ forever/)).toBeInTheDocument();
    expect(
      free.getByRole("button", { name: "Get started free" }),
    ).toBeInTheDocument();
  });

  it("shows the exact Family plan feature list, tagline and CTA", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    const family = within(card("family"));
    for (const point of [
      "Everything in Free",
      "Whole household",
      "Unlimited calendar tags",
      "Unlimited routines",
      "Household routines",
      "Shared family events",
      "Lists",
      "Gift wishlists",
      "Invite household members",
      "Invite external family/friends",
    ]) {
      expect(family.getByText(point)).toBeInTheDocument();
    }
    expect(family.getByText("For the whole household")).toBeInTheDocument();
    expect(
      family.getByRole("button", { name: "Start Family" }),
    ).toBeInTheDocument();
  });

  it("shows Ultimate features including Budget, Driveway and future premium modules", async () => {
    mockPricing();
    render(<PublicPricing />);

    const ultimate = within(card("ultimate"));
    expect(ultimate.getByText("Everything in Family")).toBeInTheDocument();
    expect(ultimate.getByText("Budget")).toBeInTheDocument();
    expect(ultimate.getByText("Driveway")).toBeInTheDocument();
    expect(ultimate.getByText("Future premium modules")).toBeInTheDocument();
    expect(
      ultimate.getByText("For the full MyKhaya experience"),
    ).toBeInTheDocument();
    expect(
      await ultimate.findByRole("button", { name: "Start Ultimate" }),
    ).toBeInTheDocument();
  });

  it("never advertises Chores or Family Plans — neither is a real, released capability", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(screen.queryByText("Chores")).not.toBeInTheDocument();
    expect(screen.queryByText("Family Plans")).not.toBeInTheDocument();
  });

  it("renders the four 'More about our plans' reassurances", async () => {
    mockPricing();
    render(<PublicPricing />);

    const list = screen.getByRole("list", { name: "More about our plans" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    for (const [title, text] of [
      ["No hidden fees", "Simple, transparent pricing."],
      ["Cancel anytime", "You’re always in control."],
      ["Built for families", "Share, organise and do more together."],
      ["Your data, your home", "Private, secure and in your control."],
    ] as const) {
      expect(within(list).getByText(title)).toBeInTheDocument();
      expect(within(list).getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("More about our plans", { selector: "p" })).toBeInTheDocument();
  });

  it("keeps decorative icons out of the accessibility tree", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(document.querySelectorAll(".mk-plan-icon[aria-hidden='true']")).toHaveLength(
      3,
    );
    expect(
      document.querySelectorAll(".mk-assurance-icon[aria-hidden='true']"),
    ).toHaveLength(4);
    for (const tick of document.querySelectorAll(".mk-plan-tick")) {
      expect(tick).toHaveAttribute("aria-hidden", "true");
    }
  });
});

describe("PublicPricing — Family price always comes from the live pricing API", () => {
  it("never shows a price before the API responds, and shows exactly what the API returned", async () => {
    mockPricing({
      options: [
        {
          interval: "month",
          provider: "stripe",
          currency: "gbp",
          unit_amount: 1234,
          formatted_amount: "£12.34",
        },
        {
          interval: "year",
          provider: "stripe",
          currency: "gbp",
          unit_amount: 12340,
          formatted_amount: "£123.40",
        },
      ],
    });
    render(<PublicPricing />);

    // Scoped to the Family plan card: Ultimate has its own independent
    // "Loading pricing…" state that would otherwise also match.
    const family = card("family");
    expect(within(family).getByText(/loading pricing/i)).toBeInTheDocument();
    expect(screen.queryByText("£123.40")).not.toBeInTheDocument();

    await screen.findByText("£123.40");
    expect(within(family).queryByText(/loading pricing/i)).not.toBeInTheDocument();
  });

  it("is annual by default, with the API's saving hint on its own lines", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    const family = within(card("family"));
    expect(family.getByText(/billed annually until cancelled\./i)).toBeInTheDocument();
    expect(family.getByText(/save £19\.89 per year/i)).toBeInTheDocument();
    expect(family.getByText(/\/ yr/)).toBeInTheDocument();
  });

  it("shows Family as the recommended 'Most popular' choice, and only Family", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(within(card("family")).getByText(/most popular/i)).toBeInTheDocument();
    expect(within(card("free")).queryByText(/most popular/i)).not.toBeInTheDocument();
    expect(within(card("ultimate")).queryByText(/most popular/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/most popular/i)).toHaveLength(1);
  });

  it("degrades gracefully, keeping Free available, when pricing fails to load", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("network"),
    );
    render(<PublicPricing />);

    await screen.findByText(/family pricing is temporarily unavailable/i);
    expect(
      screen.getByRole("button", { name: /get started free/i }),
    ).toBeEnabled();
    // No live price to charge — the Family CTA stays visible (no layout
    // jump) but can't be actioned until pricing is back.
    expect(
      screen.getByRole("button", { name: /^start family/i }),
    ).toBeDisabled();
  });

  it("replaces the Family CTA with a paused notice when acquisition is disabled, without hiding the price", async () => {
    mockPricing({ acquisition_enabled: false });
    render(<PublicPricing />);

    await screen.findByText(familyPrices.year);
    const family = card("family");
    expect(within(family).getByText(/temporarily paused/i)).toBeInTheDocument();
    expect(
      within(family).queryByRole("button", { name: /^start family/i }),
    ).not.toBeInTheDocument();
    // Ultimate has its own independent kill switch and is unaffected.
    expect(
      within(card("ultimate")).getByRole("button", { name: "Start Ultimate" }),
    ).toBeInTheDocument();
  });
});

describe("PublicPricing — independent billing selectors", () => {
  it("gives Free no billing selector, and Family and Ultimate one each", async () => {
    mockPricing();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    expect(
      within(card("free")).queryByRole("group", { name: /billing/i }),
    ).not.toBeInTheDocument();
    expect(
      within(card("free")).queryByRole("button", { name: /monthly|annual/i }),
    ).not.toBeInTheDocument();
    expect(
      within(card("family")).getByRole("group", { name: "Family billing interval" }),
    ).toBeInTheDocument();
    expect(
      within(card("ultimate")).getByRole("group", { name: "Ultimate billing interval" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: /billing interval/i })).toHaveLength(2);
  });

  it("exposes the selected state of each selector to assistive technology", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    const family = within(card("family"));
    const ultimate = within(card("ultimate"));
    expect(family.getByRole("button", { name: "Annual" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(family.getByRole("button", { name: "Monthly" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(ultimate.getByRole("button", { name: "Monthly" }));
    expect(ultimate.getByRole("button", { name: "Monthly" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(ultimate.getByRole("button", { name: "Annual" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("changing Family updates only Family", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    await user.click(within(card("family")).getByRole("button", { name: "Monthly" }));

    const family = within(card("family"));
    const ultimate = within(card("ultimate"));
    expect(await family.findByText(familyPrices.month)).toBeInTheDocument();
    expect(family.getByText(/billed monthly until cancelled\./i)).toBeInTheDocument();
    expect(family.getByText(/\/ mo/)).toBeInTheDocument();
    expect(family.queryByText(/save £19\.89/i)).not.toBeInTheDocument();

    // Ultimate is untouched: still annual.
    expect(ultimate.getByText(ultimatePrices.year)).toBeInTheDocument();
    expect(ultimate.getByText(/billed annually until cancelled\./i)).toBeInTheDocument();
    expect(ultimate.getByText(/save £29\.89 per year/i)).toBeInTheDocument();
    expect(ultimate.getByRole("button", { name: "Annual" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("changing Ultimate updates only Ultimate", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    await user.click(within(card("ultimate")).getByRole("button", { name: "Monthly" }));

    const family = within(card("family"));
    const ultimate = within(card("ultimate"));
    expect(await ultimate.findByText(ultimatePrices.month)).toBeInTheDocument();
    expect(ultimate.getByText(/billed monthly until cancelled\./i)).toBeInTheDocument();
    expect(ultimate.queryByText(/save £29\.89/i)).not.toBeInTheDocument();

    // Family is untouched: still annual.
    expect(family.getByText(familyPrices.year)).toBeInTheDocument();
    expect(family.getByText(/save £19\.89 per year/i)).toBeInTheDocument();
    expect(family.getByRole("button", { name: "Annual" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("lets the two cards sit on opposite billing cycles at the same time", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    await user.click(within(card("family")).getByRole("button", { name: "Monthly" }));
    await user.click(within(card("family")).getByRole("button", { name: "Annual" }));
    await user.click(within(card("ultimate")).getByRole("button", { name: "Monthly" }));

    expect(within(card("family")).getByText(familyPrices.year)).toBeInTheDocument();
    expect(within(card("ultimate")).getByText(ultimatePrices.month)).toBeInTheDocument();
  });
});

describe("PublicPricing — CTA routing", () => {
  it("routes an anonymous visitor choosing Free to registration with the right plan intent", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);

    await user.click(screen.getByRole("button", { name: /get started free/i }));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=free&interval=month"),
    );
  });

  it("routes Family to registration with the interval selected on the Family card", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    await user.click(within(card("family")).getByRole("button", { name: "Start Family" }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=family&interval=year"),
    );

    push.mockClear();
    await user.click(within(card("family")).getByRole("button", { name: "Monthly" }));
    await user.click(within(card("family")).getByRole("button", { name: "Start Family" }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=family&interval=month"),
    );
  });

  it("routes Ultimate to registration with the interval selected on the Ultimate card only", async () => {
    mockPricing();
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    // Moving Family must not change what Ultimate sends.
    await user.click(within(card("family")).getByRole("button", { name: "Monthly" }));
    await user.click(
      within(card("ultimate")).getByRole("button", { name: "Start Ultimate" }),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=ultimate&interval=year"),
    );

    push.mockClear();
    await user.click(within(card("ultimate")).getByRole("button", { name: "Monthly" }));
    await user.click(
      within(card("ultimate")).getByRole("button", { name: "Start Ultimate" }),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=ultimate&interval=month"),
    );
  });

  it("routes an already-authenticated visitor with an existing Home straight to Settings, not registration", async () => {
    mockPricing();
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "user-1" });
    (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "home-1" },
    ]);
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText(familyPrices.year);

    await user.click(screen.getByRole("button", { name: /^start family/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/settings/billing"));
  });
});
