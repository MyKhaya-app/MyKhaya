import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

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
});
vi.mock("@/components/auth-provider", () => ({ useAuth: defaultAuthContext }));
vi.mock("./components/auth-provider", () => ({ useAuth: defaultAuthContext }));

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
