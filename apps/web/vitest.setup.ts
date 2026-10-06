import { afterEach, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// The default 1000ms waitFor/findBy* timeout is occasionally too tight for
// this suite's size (2000+ tests) under CPU contention in CI's parallel
// worker pool — a handful of findBy*/waitFor assertions would intermittently
// time out purely from scheduling delay, not because the awaited condition
// was ever false (every affected test passes reliably standalone or in a
// small group; see docs/security/MYKHAYA_SECURITY_AUDIT_2026-10.md's test-
// baseline section for the investigation). This only changes how long a
// query waits before giving up — it does not change what is asserted or
// relax any assertion.
configure({ asyncUtilTimeout: 8000 });

// Global default for components/auth-provider.tsx's useAuth() — AppShell
// (and therefore every settings/authenticated page's SettingsPage/AppShell
// wrapper) now reads the signed-in user/auth status from AuthProvider's
// context instead of calling api.me() itself, and useAuth() throws outside
// an <AuthProvider>. Most page tests render a page directly (no
// AuthProvider in the tree) and don't care about auth state at all — they
// only need *some* authenticated adult user so the page's own content
// renders — so this default keeps them working without every one of them
// needing its own auth-provider mock.
//
// A test file that actually exercises auth behaviour itself (login pages,
// components/app-shell.test.tsx, the native-vs-browser Security page
// split) should declare its own `vi.mock("@/components/auth-provider", ...)`
// (or a relative "./auth-provider"/"../../components/auth-provider" import,
// whichever it already uses to reach the module) — a test file's own
// vi.mock call for the same resolved module overrides this default for
// that file, exactly like overriding any other setupFiles-registered mock.
// Registered under both the "@/..." alias and the plain relative path so it
// applies regardless of which form an individual test file's own imports
// use to reach the same apps/web/components/auth-provider.tsx module.
const defaultAuthContext = () => ({
  user: {
    id: "test-user",
    display_name: "Test User",
    email: "test-user@example.com",
    email_verified: true,
    birth_month: null,
    birth_day: null,
    birth_year: null,
    avatar_version: null,
    principal_type: "adult",
  },
  status: "ready",
  initialSessionLoading: false,
  sessionRefreshing: false,
  retryInitialSession: vi.fn(),
  refreshSession: vi.fn(),
  setAuthenticatedUser: vi.fn(),
  clearSession: vi.fn(),
});
vi.mock("@/components/auth-provider", () => ({ useAuth: defaultAuthContext }));
vi.mock("./components/auth-provider", () => ({ useAuth: defaultAuthContext }));

// Same idea for PCC: every Control Centre page renders inside PlatformShell,
// which now renders nothing until the administrator session resolves as
// authenticated (see components/platform-session.ts). Page tests don't care
// about auth, so default to a resolved, fully-authenticated administrator; a
// test of the session/gate itself opts out with vi.unmock(...) and drives the
// real module.
const defaultPlatformSession = () => ({
  usePlatformSession: () => ({
    state: "authenticated" as const,
    actor: {
      id: "test-operator",
      email: "operator@example.com",
      display_name: "Test Operator",
      role: "platform_owner",
      mfa_enrolled: true,
      session_status: "full" as const,
    },
    retry: vi.fn(),
  }),
  clearPlatformSession: vi.fn(),
  resetPlatformSessionForTests: vi.fn(),
});
vi.mock("@/components/platform-session", () => defaultPlatformSession());
vi.mock("./components/platform-session", () => defaultPlatformSession());

// jsdom doesn't implement matchMedia — standard polyfill so components that
// feature-detect display-mode (e.g. AppShell's auth diagnostics) don't throw
// in every test that renders through it. Always reports "no match"; no test
// in this repo currently depends on a specific media query result.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// jsdom doesn't implement scrollTo — components/bottom-sheet.tsx calls it to
// restore the background page's scroll position after releasing its
// scroll-lock on close. No test depends on an actual scroll happening; this
// just stops jsdom's "Not implemented" console error on every sheet close.
if (typeof window !== "undefined") {
  window.scrollTo = vi.fn();
}

// PCC's resolved administrator session is module-scoped (shared across pages);
// never let one test's session leak into the next.
// Imported lazily so it resolves through the current test file's own module
// mocks (e.g. a mocked @mykhaya/api-client), not the setup file's.
afterEach(async () => {
  (await import("./components/platform-session")).resetPlatformSessionForTests();
});
