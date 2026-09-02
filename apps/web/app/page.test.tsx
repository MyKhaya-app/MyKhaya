import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Welcome from "./page";

const { nativeState, authState, replace } = vi.hoisted(() => ({
  nativeState: { value: false },
  authState: {
    status: "signed_out" as "initializing" | "ready" | "offline" | "signed_out",
    initialSessionLoading: false,
    retryInitialSession: vi.fn(),
  },
  replace: vi.fn(),
}));

// The public marketing homepage — composition/navigation coverage. Pricing
// data/routing behaviour has its own dedicated test file
// (components/marketing/public-pricing.test.tsx); this file is about the
// page as a whole: every section present, in the right order, with working
// links, and no leftover admin/dashboard-style content.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
}));

vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => nativeState.value }));
vi.mock("@/components/auth-provider", () => ({ useAuth: () => authState }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      familyPricing: vi.fn(async () => ({
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
      })),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  nativeState.value = false;
  authState.status = "signed_out";
  authState.initialSessionLoading = false;
});

describe("Welcome (public marketing homepage)", () => {
  it("renders every section of the new page structure, in order", async () => {
    render(<Welcome />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    const headingText = headings.map((node) => node.textContent);
    // Order matters — Header, Hero, Benefits, Feature showcase, How it
    // works, Pricing, Final CTA, Footer, per the agreed page structure.
    const benefitsIndex = headingText.findIndex((text) =>
      text?.includes("Why families"),
    );
    const featuresIndex = headingText.findIndex((text) =>
      text?.includes("Made for how families"),
    );
    const howIndex = headingText.findIndex((text) =>
      text?.includes("Up and running"),
    );
    const pricingIndex = headingText.findIndex((text) =>
      text?.includes("Free, or the complete"),
    );
    const finalCtaIndex = headingText.findIndex((text) =>
      text?.includes("Ready to bring"),
    );
    expect(benefitsIndex).toBeGreaterThanOrEqual(0);
    expect(featuresIndex).toBeGreaterThan(benefitsIndex);
    expect(howIndex).toBeGreaterThan(featuresIndex);
    expect(pricingIndex).toBeGreaterThan(howIndex);
    expect(finalCtaIndex).toBeGreaterThan(pricingIndex);
  });

  it("leads with the plain-English hero headline and no technical language", async () => {
    render(<Welcome />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /your family\. one place\. everything organised\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /calendars, routines, lists, chores and the everyday things/i,
      ),
    ).toBeInTheDocument();
    // No jargon a visitor would have to understand before signing up.
    expect(
      screen.queryByText(/household member capability/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/\bhome\b.*\bentitlement\b/i),
    ).not.toBeInTheDocument();
  });

  it("gives the header exactly the two public actions — Sign in and Get started free", async () => {
    render(<Welcome />);

    const header = screen.getByRole("banner");
    expect(header.querySelector('a[href="/login"]')).toHaveTextContent(
      /sign in/i,
    );
    expect(header.querySelector('a[href="/register"]')).toHaveTextContent(
      /get started free/i,
    );
  });

  it("the hero's primary action goes to registration, not straight into pricing", async () => {
    render(<Welcome />);

    const heroLinks = screen.getAllByRole("link", {
      name: /get started free/i,
    });
    expect(
      heroLinks.some((link) => link.getAttribute("href") === "/register"),
    ).toBe(true);
  });

  it("footer only links to real, existing pages", async () => {
    render(<Welcome />);

    const footer = screen.getByRole("contentinfo");
    for (const link of footer.querySelectorAll("a")) {
      expect(["/login", "/register", "/service-status", "/"]).toContain(
        link.getAttribute("href"),
      );
    }
  });

  it("gates the native root while restoring and redirects to authenticated Home after restore", async () => {
    nativeState.value = true;
    authState.status = "initializing";
    authState.initialSessionLoading = true;
    const view = render(<Welcome />);

    expect(screen.getByText(/checking your mykhaya session/i)).toBeInTheDocument();
    expect(screen.queryByText(/your family\. one place/i)).not.toBeInTheDocument();

    authState.status = "ready";
    authState.initialSessionLoading = false;
    view.rerender(<Welcome />);

    expect(screen.queryByText(/your family\. one place/i)).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith("/home");
  });
});
