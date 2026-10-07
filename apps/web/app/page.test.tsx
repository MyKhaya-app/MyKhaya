import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HomePage from "./page";

const { nativeState, authState, replace } = vi.hoisted(() => ({
  nativeState: { value: false, platform: "ios" as "ios" | "android" | "web" },
  authState: {
    status: "signed_out" as "initializing" | "ready" | "offline" | "signed_out" | "locked" | "legal_check_error" | "legal_action_required",
    initialSessionLoading: false,
    retryInitialSession: vi.fn(),
    legalStatusError: null as string | null,
    retryLegalStatus: vi.fn(),
  },
  replace: vi.fn(),
}));
const { signupState } = vi.hoisted(() => ({
  signupState: {
    value: {
      signup_mode: "normal",
      registration_open: true,
      invitation_required: false,
      normal_signup_available: true,
      beta_joining_available: false,
      waitlist_available: false,
      joinable_count: null,
    } as Record<string, unknown>,
  },
}));
const NORMAL = { ...signupState.value };

// The public marketing homepage — composition/navigation coverage. Pricing
// data/routing behaviour has its own dedicated test file
// (components/marketing/site/home-pricing.test.tsx); this file is about the
// page as a whole: every section present, in order, with working links and
// anchors, signup-mode-aware actions, and the native root gate.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeState.value,
  nativePlatform: () => nativeState.platform,
}));
vi.mock("@/components/auth-provider", () => ({ useAuth: () => authState }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      publicSignupState: vi.fn(async () => signupState.value),
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
  nativeState.platform = "ios";
  authState.status = "signed_out";
  authState.initialSessionLoading = false;
  authState.legalStatusError = null;
  signupState.value = { ...NORMAL };
});

describe("Welcome (public marketing homepage)", () => {
  it("renders every section of the design, in order", async () => {
    render(<HomePage />);

    const main = await screen.findByRole("main");
    const headings = (await within(main).findAllByRole("heading", { level: 2 })).map((node) => node.textContent);
    expect(headings).toEqual([
      "Less organising. More being together.",
      "Made for how families actually run.",
      "From breakfast to bedtime.",
      "Up and running in minutes.",
      "Built for families. Built to be trusted.",
      "Every kind of home.",
      "Simple plans for modern family life.",
      "Good to know.",
      "Ready to bring your family together?",
    ]);
    expect(screen.getByRole("heading", { level: 1, name: /bring your family together\./i })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent)).toEqual(
      expect.arrayContaining([
        "Your whole day on one screen.",
        "One calendar, everyone in it.",
        "Dinner, decided.",
        "Keep track without keeping it all in your head.",
        "What's happening with your people.",
      ]),
    );
    // Family chat stays as the "coming soon" card on the Family tour row.
    expect(screen.getByText("Private to your family. Coming soon.")).toBeInTheDocument();
  });

  it("has no stats band and no 'Also in your home' block", async () => {
    render(<HomePage />);
    await screen.findByRole("heading", { name: "Good to know." });
    expect(screen.queryByLabelText("MyKhaya at a glance")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Also in your home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Going further with Ultimate" })).not.toBeInTheDocument();
    // The story section follows the hero directly, with the reduced top gap.
    const story = screen.getByRole("heading", { name: "Less organising. More being together." }).closest("section");
    expect(story).toHaveClass("after-hero");
  });

  it("never advertises Notes, which is not a real feature", async () => {
    const { container } = render(<HomePage />);
    await screen.findByRole("heading", { name: "Good to know." });
    // Only the story's "lost notes" (paper notes, not a feature) may remain.
    const text = (container.textContent ?? "").replace("lost notes", "");
    expect(text).not.toMatch(/\bnotes?\b/i);
  });

  it.each([
    ["App Store + Play listing", "https://apps.apple.com/gb/app/mykhaya/id1", "https://play.google.com/store/apps/details?id=app.mykhaya", true, true],
    ["TestFlight + Play testing", "https://testflight.apple.com/join/AbCdEf12", "https://play.google.com/apps/testing/app.mykhaya", false, false],
    ["empty", null, "https://downloads.mykhaya.app/android/beta.apk", false, false],
  ])("wires the PCC app links (%s) from signup-state into the hero badges", async (_label, ios, android, appleLinked, googleLinked) => {
    signupState.value = { ...NORMAL, ios_app_url: ios, android_app_url: android };
    render(<HomePage />);
    const badges = screen.getByRole("group", { name: "Get the app" });
    await waitFor(() =>
      expect(within(badges).getByAltText("Download on the App Store").closest("a")?.getAttribute("href") ?? null).toBe(
        appleLinked ? ios : null,
      ),
    );
    const google = within(badges).getByAltText(googleLinked ? "Get it on Google Play" : "Get it on Google Play, coming soon");
    expect(google.closest("a")?.getAttribute("href") ?? null).toBe(googleLinked ? android : null);
  });

  it("shows the App Store and Google Play badges under the hero ticks, as artwork only for now", async () => {
    render(<HomePage />);
    const badges = screen.getByRole("group", { name: "Get the app" });
    const apple = within(badges).getByAltText("Download on the App Store");
    const google = within(badges).getByAltText("Get it on Google Play, coming soon");
    expect(apple).toHaveAttribute("height", "40");
    expect(google).toHaveAttribute("height", "40");
    // No listing URLs yet: not links, and Google Play carries the pill.
    expect(within(badges).queryAllByRole("link")).toHaveLength(0);
    expect(within(badges).getByText("Coming soon")).toHaveClass("mk-applink-pill");
    // Sits after the ticks within the hero copy.
    const ticks = screen.getByText("Set up in minutes").closest("ul")!;
    expect(ticks.compareDocumentPosition(badges) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has a section for every in-page anchor used by the nav, menu and footer", async () => {
    const { container } = render(<HomePage />);
    await screen.findByRole("heading", { name: "Good to know." });
    const anchors = new Set(
      Array.from(container.querySelectorAll('a[href^="#"]')).map((link) => link.getAttribute("href")!.slice(1)),
    );
    expect([...anchors].sort()).toEqual(["day", "faq", "features", "how", "pricing"]);
    for (const id of anchors) expect(container.querySelector(`#${id}`), id).not.toBeNull();
  });

  it("only links to real public pages (or in-page anchors and the status page)", async () => {
    const { container } = render(<HomePage />);
    await screen.findByRole("heading", { name: "Good to know." });
    const allowed = new Set([
      "/",
      "/login",
      "/register",
      "/register?plan=free&interval=month",
      "/register?plan=family&interval=month",
      "/support",
      "/legal/terms",
      "/legal/privacy",
      "/legal/children",
      "/legal/cookies",
      "https://status.mykhaya.app/",
    ]);
    for (const link of container.querySelectorAll("a")) {
      const href = link.getAttribute("href")!;
      if (href.startsWith("#")) continue;
      expect(allowed, href).toContain(href);
    }
    // The in-app Help & Support needs sign-in, so it is never linked from here.
    expect(container.querySelector('a[href="/help-support"]')).toBeNull();
  });

  it("follows the normal signup mode: Sign in plus Get started free, with the free promise", async () => {
    render(<HomePage />);
    const header = screen.getByRole("banner");
    await waitFor(() =>
      expect(within(header).getByRole("link", { name: "Get started free" })).toHaveAttribute("href", "/register"),
    );
    expect(within(header).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.getByText("No card required").closest("ul")).toBeVisible();
  });

  it("follows Beta-only mode: Join the Beta everywhere and a Founding Beta offer in place of plans", async () => {
    signupState.value = {
      ...NORMAL,
      signup_mode: "beta_only",
      normal_signup_available: false,
      beta_joining_available: true,
      joinable_count: 7,
    };
    render(<HomePage />);
    const ctas = await screen.findAllByRole("link", { name: /^Join the Beta/ });
    expect(ctas.length).toBeGreaterThanOrEqual(3);
    for (const link of ctas) expect(link).toHaveAttribute("href", "/founding-beta");
    expect(screen.queryByRole("link", { name: /Get started free/ })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Join MyKhaya at no cost during our Founding Beta/ })).toBeInTheDocument();
    expect(screen.getByText("7 places currently available")).toBeInTheDocument();
    // Beta is free with no card, so the hero promise still holds.
    expect(screen.getByText("No card required")).toBeInTheDocument();
  });

  it("drops the free/no-card promise when sign-ups are closed (waitlist mode)", async () => {
    signupState.value = {
      ...NORMAL,
      signup_mode: "closed",
      registration_open: false,
      normal_signup_available: false,
      waitlist_available: true,
    };
    render(<HomePage />);
    expect((await screen.findAllByRole("link", { name: /Join the waitlist/ }))[0]).toHaveAttribute("href", "/waitlist");
    expect(screen.queryByText("No card required")).not.toBeInTheDocument();
    expect(screen.queryByText(/Free to start\. No card required/)).not.toBeInTheDocument();
    expect(screen.getByText("New sign-ups are currently closed.")).toBeInTheDocument();
  });

  it("does not show a duplicate Sign in when sign-ups are closed without a waitlist", async () => {
    signupState.value = {
      ...NORMAL,
      signup_mode: "closed",
      registration_open: false,
      normal_signup_available: false,
      waitlist_available: false,
    };
    render(<HomePage />);
    const header = screen.getByRole("banner");
    await waitFor(() => expect(within(header).getAllByRole("link", { name: /^Sign in/ })).toHaveLength(1));
  });

  it("holds the signup-mode wording invisibly until the mode is known", () => {
    render(<HomePage />);
    const header = screen.getByRole("banner");
    // First render, before publicSignupState resolves.
    const cta = header.querySelector(".nav-cta .btn") as HTMLElement;
    expect(cta.style.visibility).toBe("hidden");
    expect(cta).toHaveAttribute("aria-hidden", "true");
  });

  it("opens and closes the mobile menu", async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    const toggle = screen.getByRole("button", { name: "Open menu" });
    const menu = document.getElementById("mobile-menu")!;
    expect(menu).not.toBeVisible();
    await user.click(toggle);
    expect(menu).toBeVisible();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(within(menu).getByRole("link", { name: "Pricing" }));
    expect(menu).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
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
    const source = readFileSync(join(process.cwd(), "components", "marketing", "site", "welcome.tsx"), "utf8");
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
    const view = render(<HomePage />);

    expect(screen.getByText(/checking your mykhaya session/i)).toBeInTheDocument();
    expect(screen.queryByText(/your family\. one place/i)).not.toBeInTheDocument();

    authState.status = "ready";
    authState.initialSessionLoading = false;
    view.rerender(<HomePage />);

    expect(screen.queryByText(/your family\. one place/i)).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith("/home");
  });

  it("locked-state unlock copy names Face ID and Touch ID by name on iOS", async () => {
    nativeState.value = true;
    nativeState.platform = "ios";
    authState.status = "locked";
    render(<HomePage />);

    expect(await screen.findByText(/face id/i)).toBeInTheDocument();
    expect(screen.getByText(/touch id/i)).toBeInTheDocument();
  });

  it("locked-state unlock copy never claims a specific named modality on Android", async () => {
    nativeState.value = true;
    nativeState.platform = "android";
    authState.status = "locked";
    render(<HomePage />);

    await screen.findByRole("heading", { name: /unlock mykhaya/i });
    expect(screen.queryByText(/face id|touch id/i)).not.toBeInTheDocument();
  });

  it("shows a recoverable legal-check error at the native root", async () => {
    nativeState.value = true;
    authState.status = "legal_check_error";
    authState.legalStatusError = "Legal service unavailable";
    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: /could not check your legal documents/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalledWith("/login");
  });
});
