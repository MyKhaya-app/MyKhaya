import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PublicPricing } from "./public-pricing";

// Two plans only — Free and Family, no manufactured third tier. Family's
// price must always come from the live pricing API (never a hard-coded
// figure baked into the component), and every CTA must route through the
// same resolveCtaDestination logic the rest of the commercial journey uses.

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

function pricingResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    plan: "family",
    options: [
      {
        interval: "month",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 999,
        formatted_amount: "£9.99",
      },
      {
        interval: "year",
        provider: "stripe",
        currency: "gbp",
        unit_amount: 9999,
        formatted_amount: "£99.99",
      },
    ],
    annual_saving_formatted: "£19.89",
    annual_is_best_value: true,
    acquisition_enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockRejectedValue(
    new Error("not signed in"),
  );
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("PublicPricing — two plans, no manufactured third tier", () => {
  it("renders exactly two plan cards: Free and Family", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    render(<PublicPricing />);

    await screen.findByText("£9.99");
    expect(
      screen.getByRole("heading", { level: 3, name: "Free" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Family" }),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(2);
  });

  it("shows the exact Free plan feature list and price", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    render(<PublicPricing />);

    for (const point of [
      "Calendar",
      "Events",
      "Notes",
      "1 event category",
      "Up to 3 personal routines",
      "1 person",
    ]) {
      expect(screen.getByText(point)).toBeInTheDocument();
    }
    expect(screen.getByText("£0")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /get started free/i }),
    ).toBeInTheDocument();
  });

  it("shows the exact Family plan feature list", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    render(<PublicPricing />);
    await screen.findByText("£9.99");

    for (const point of [
      "Everything in Free",
      "Whole household",
      "Unlimited event categories",
      "Unlimited routines",
      "Household routines",
      "Shared family events",
      "Lists",
      "Chores",
      "Gift wishlists",
      "Family Plans",
      "Invite household members",
      "Invite external family/friends",
    ]) {
      expect(screen.getByText(point)).toBeInTheDocument();
    }
    expect(
      screen.getByRole("button", { name: /^start family/i }),
    ).toBeInTheDocument();
  });
});

describe("PublicPricing — Family price always comes from the live pricing API", () => {
  it("never shows a price before the API responds, and shows exactly what the API returned", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse({
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
      }),
    );
    render(<PublicPricing />);

    expect(screen.getByText(/loading pricing/i)).toBeInTheDocument();
    expect(screen.queryByText("£12.34")).not.toBeInTheDocument();

    await screen.findByText("£12.34");
    expect(screen.queryByText(/loading pricing/i)).not.toBeInTheDocument();
  });

  it("switches to the annual price and shows the best-value badge only when the API says so", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText("£9.99");

    expect(screen.queryByText(/best value/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /annual/i }));

    expect(await screen.findByText("£99.99")).toBeInTheDocument();
    expect(screen.getByText(/best value/i)).toBeInTheDocument();
    expect(screen.getByText(/save £19\.89 per year/i)).toBeInTheDocument();
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
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse({ acquisition_enabled: false }),
    );
    render(<PublicPricing />);

    await screen.findByText("£9.99");
    expect(screen.getByText(/temporarily paused/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^start family/i }),
    ).not.toBeInTheDocument();
  });
});

describe("PublicPricing — CTA routing", () => {
  it("routes an anonymous visitor choosing Free to registration with the right plan intent", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    const user = userEvent.setup();
    render(<PublicPricing />);

    await user.click(screen.getByRole("button", { name: /get started free/i }));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=free&interval=month"),
    );
  });

  it("routes an anonymous visitor choosing Family to registration with the selected interval", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText("£9.99");

    await user.click(screen.getByRole("button", { name: /annual/i }));
    await user.click(screen.getByRole("button", { name: /^start family/i }));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/register?plan=family&interval=year"),
    );
  });

  it("routes an already-authenticated visitor with an existing Home straight to Settings, not registration", async () => {
    (api.familyPricing as ReturnType<typeof vi.fn>).mockResolvedValue(
      pricingResponse(),
    );
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "user-1" });
    (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "home-1" },
    ]);
    const user = userEvent.setup();
    render(<PublicPricing />);
    await screen.findByText("£9.99");

    await user.click(screen.getByRole("button", { name: /^start family/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/settings/billing"));
  });
});
