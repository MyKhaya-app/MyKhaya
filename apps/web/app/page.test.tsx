import { readFileSync } from "node:fs";
import { join } from "node:path";
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
    // Order matters — Header, Hero, Features, Lifestyle, Pricing, Final CTA,
    // Footer, per the approved mockup's section order.
    const featuresIndex = headingText.findIndex((text) =>
      text?.includes("Made for how families"),
    );
    const lifestyleIndex = headingText.findIndex((text) =>
      text?.includes("Less organising"),
    );
    const pricingIndex = headingText.findIndex((text) =>
      text?.includes("A plan for every family"),
    );
    const finalCtaIndex = headingText.findIndex((text) =>
      text?.includes("Ready to bring"),
    );
    expect(featuresIndex).toBeGreaterThanOrEqual(0);
    expect(lifestyleIndex).toBeGreaterThan(featuresIndex);
    expect(pricingIndex).toBeGreaterThan(lifestyleIndex);
    expect(finalCtaIndex).toBeGreaterThan(pricingIndex);
  });

  it("leads with the plain-English hero headline and no technical language", async () => {
    render(<Welcome />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /bring your family together\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /shared calendars, meals, lists and nudges — all in one place/i,
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
      expect([
        "/login",
        "/register",
        "/help-support",
        "https://status.dev.mykhaya.app/",
        "/",
      ]).toContain(link.getAttribute("href"));
    }
  });

  it("never calls isNativeShell() synchronously in Welcome's render body (SSR-hydration-safety contract)", () => {
    // Regression guard for Android Phase 2's finding: isNativeShell() reads
    // false during SSR (no window there) but can read true on the client's
    // very first render inside a native shell. Welcome() used to branch on
    // it directly in the render body, so the client's first render produced
    // a totally different tree (<NativeRootGate/>) than what was
    // server-rendered (<PublicWelcome/>) — a root-level React hydration
    // mismatch (error #418), reproduced on a real Android build. React
    // Testing Library's render() is act-wrapped and flushes the fix's
    // useEffect synchronously, so a DOM-content assertion can't distinguish
    // "checked after mount" from "checked during render" here — this
    // asserts the actual structural contract by inspecting the source
    // directly: the fix (`useState` + `useEffect`) must still be in place,
    // and Welcome's body must not call isNativeShell() outside that effect.
    const source = readFileSync(join(process.cwd(), "app", "page.tsx"), "utf8");
    const welcomeBody = source
      .slice(source.indexOf("export default function Welcome"))
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");
    const outsideEffect = welcomeBody.replace(/useEffect\(\s*\(\)\s*=>\s*\{[\s\S]*?\},\s*\[\]\);/, "");
    expect(outsideEffect).not.toMatch(/isNativeShell\(\)/);
    expect(welcomeBody).toMatch(/useState\(false\)/);
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
