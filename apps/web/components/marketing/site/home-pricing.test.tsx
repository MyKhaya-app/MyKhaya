import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FamilyPricing } from "@mykhaya/shared-types";
import type { PublicSignupState } from "@mykhaya/api-client";
import { HomePricing, type PricingState } from "./home-pricing";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { me: vi.fn(), homes: vi.fn() } };
});
const { api } = await import("@mykhaya/api-client");
const me = api.me as unknown as ReturnType<typeof vi.fn>;
const homes = api.homes as unknown as ReturnType<typeof vi.fn>;

const option = (interval: "month" | "year", formatted_amount: string) => ({
  interval,
  provider: "stripe",
  currency: "gbp",
  unit_amount: 0,
  formatted_amount,
});

function pricing(overrides: Partial<FamilyPricing> = {}): FamilyPricing {
  return {
    plan: "family",
    options: [option("month", "£4.99"), option("year", "£49.99")],
    annual_saving_formatted: "£9.89",
    annual_is_best_value: true,
    acquisition_enabled: true,
    ultimate_options: [option("month", "£7.99"), option("year", "£79.99")],
    ultimate_acquisition_enabled: false,
    ...overrides,
  } as unknown as FamilyPricing;
}

const NORMAL = { signup_mode: "normal", normal_signup_available: true } as unknown as PublicSignupState;

function renderPricing(state: PricingState, signupState: PublicSignupState | null | undefined = NORMAL) {
  return render(<HomePricing pricingState={state} signupState={signupState} />);
}

const card = (name: string) => screen.getByRole("heading", { level: 3, name }).closest(".plan") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  me.mockRejectedValue(new Error("401"));
  homes.mockResolvedValue([]);
});

describe("Homepage pricing", () => {
  it("shows the £— placeholder until real prices arrive, then the API's monthly prices", () => {
    const { rerender } = renderPricing({ pricing: null, error: false });
    expect(within(card("Family")).getByText("£—")).toBeInTheDocument();
    expect(within(card("Ultimate")).getByText("£—")).toBeInTheDocument();

    rerender(<HomePricing pricingState={{ pricing: pricing(), error: false }} signupState={NORMAL} />);
    expect(within(card("Family")).getByText("£4.99")).toBeInTheDocument();
    expect(within(card("Ultimate")).getByText("£7.99")).toBeInTheDocument();
    expect(within(card("Family")).getByText("/ month")).toBeInTheDocument();
    expect(within(card("Free")).getByText("£0")).toBeInTheDocument();
  });

  it("lists only real Free plan features (no Notes)", () => {
    renderPricing({ pricing: pricing(), error: false });
    expect(within(card("Free")).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Calendar",
      "Events",
      "1 calendar tag",
      "Up to 3 personal routines",
      "1 person",
    ]);
  });

  it("switches both paid plans between monthly and annual prices and labels", async () => {
    const user = userEvent.setup();
    renderPricing({ pricing: pricing(), error: false });
    const monthly = screen.getByRole("button", { name: "Monthly" });
    const annual = screen.getByRole("button", { name: "Annual" });
    expect(monthly).toHaveAttribute("aria-pressed", "true");

    await user.click(annual);
    expect(annual).toHaveAttribute("aria-pressed", "true");
    expect(monthly).toHaveAttribute("aria-pressed", "false");
    expect(within(card("Family")).getByText("£49.99")).toBeInTheDocument();
    expect(within(card("Ultimate")).getByText("£79.99")).toBeInTheDocument();
    expect(within(card("Family")).getByText("/ year")).toBeInTheDocument();
    expect(within(card("Family")).getByText("£49.99")).toHaveAttribute("data-monthly", "£4.99");

    await user.click(monthly);
    expect(within(card("Family")).getByText("£4.99")).toBeInTheDocument();
  });

  it("shows the Ultimate paused note only while the billing setting pauses Ultimate", () => {
    const { rerender } = renderPricing({ pricing: pricing({ ultimate_acquisition_enabled: false }), error: false });
    expect(within(card("Ultimate")).getByText("New Ultimate sign-ups are temporarily paused.")).toBeInTheDocument();
    expect(within(card("Ultimate")).getByRole("link", { name: "More about our plans" })).toHaveAttribute("href", "#faq");

    rerender(
      <HomePricing pricingState={{ pricing: pricing({ ultimate_acquisition_enabled: true }), error: false }} signupState={NORMAL} />,
    );
    expect(within(card("Ultimate")).queryByText(/temporarily paused/)).not.toBeInTheDocument();
    expect(within(card("Ultimate")).getByRole("link", { name: "Start Ultimate" })).toBeInTheDocument();
  });

  it("does not claim Ultimate is paused before pricing is known", () => {
    renderPricing({ pricing: null, error: false });
    expect(screen.queryByText(/temporarily paused/)).not.toBeInTheDocument();
  });

  it("replaces Start Family with a paused note when Family acquisition is disabled", () => {
    renderPricing({ pricing: pricing({ acquisition_enabled: false }), error: false });
    expect(within(card("Family")).getByText(/New Family sign-ups are temporarily paused/)).toBeInTheDocument();
    expect(within(card("Family")).queryByRole("link", { name: "Start Family" })).not.toBeInTheDocument();
    expect(within(card("Family")).getByText("£4.99")).toBeInTheDocument();
  });

  it("degrades gracefully when pricing fails, keeping Free available", () => {
    renderPricing({ pricing: null, error: true });
    expect(within(card("Family")).getByText(/Pricing is temporarily unavailable/)).toBeInTheDocument();
    expect(within(card("Free")).getByRole("link", { name: "Get started free" })).toBeInTheDocument();
  });

  it("routes a signed-out visitor to registration with the plan and selected interval", async () => {
    const user = userEvent.setup();
    renderPricing({ pricing: pricing(), error: false });
    const family = within(card("Family")).getByRole("link", { name: "Start Family" });
    expect(family).toHaveAttribute("href", "/register?plan=family&interval=month");

    await user.click(screen.getByRole("button", { name: "Annual" }));
    await user.click(within(card("Family")).getByRole("link", { name: "Start Family" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/register?plan=family&interval=year"));
  });

  it("sends a signed-in visitor with a Home to billing, never back through registration", async () => {
    const user = userEvent.setup();
    me.mockResolvedValue({ id: "u1" });
    homes.mockResolvedValue([{ id: "h1" }]);
    renderPricing({ pricing: pricing(), error: false });
    await user.click(within(card("Family")).getByRole("link", { name: "Start Family" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/settings/billing"));
  });

  it("points every plan action at the waitlist when sign-ups are closed", () => {
    renderPricing(
      { pricing: pricing(), error: false },
      { signup_mode: "closed", normal_signup_available: false, waitlist_available: true } as unknown as PublicSignupState,
    );
    for (const name of ["Free", "Family"]) {
      expect(within(card(name)).getByRole("link", { name: "Join the waitlist" })).toHaveAttribute("href", "/waitlist");
    }
  });
});
