import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import About from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/about",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
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
      publicLegalDocuments: vi.fn().mockResolvedValue([]),
      legalStatus: vi.fn().mockResolvedValue({
        documents: [],
        children: [],
        child_self: null,
        action_required: false,
      }),
    },
  };
});

const { isNativeShell, nativePlatform } = vi.hoisted(() => ({
  isNativeShell: vi.fn(() => false),
  nativePlatform: vi.fn(() => "ios" as "ios" | "android" | "web"),
}));
vi.mock("@/components/native-runtime", () => ({ isNativeShell, nativePlatform }));

const { getInfo } = vi.hoisted(() => ({ getInfo: vi.fn() }));
vi.mock("@capacitor/app", () => ({ App: { getInfo } }));

const nativePermission = vi.hoisted(() => ({
  status: "granted" as "not_requested" | "granted" | "denied" | "restricted" | "unsupported",
  loading: false,
  requestPermission: vi.fn(),
  openSettings: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("@/components/use-notification-permission", () => ({
  useNotificationPermission: () => nativePermission,
}));

const nativePushDiagnostics = vi.hoisted(() => vi.fn(() => ({ tokenPresent: false, registered: false })));
vi.mock("@/components/native-push", () => ({ nativePushDiagnostics }));

const { api } = await import("@mykhaya/api-client");

function mockBuild(payload: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(payload),
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
  isNativeShell.mockReturnValue(false);
  nativePlatform.mockReturnValue("ios");
  nativePermission.status = "granted";
  nativePushDiagnostics.mockReturnValue({ tokenPresent: false, registered: false });
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
});

describe("About — browser", () => {
  it("shows the Web version and no iOS app row", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0 (Web)");
    expect(screen.queryByText(/iOS app/i)).not.toBeInTheDocument();
    expect(getInfo).not.toHaveBeenCalled();
  });

  it("does not show an Environment row in production", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0 (Web)");
    expect(screen.queryByText("Environment")).not.toBeInTheDocument();
  });

  it("shows a Development environment row only on a development build", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "development", channel: "development" });

    render(<About />);

    await screen.findByText("Development");
  });

  it("shows a graceful fallback, never the raw word 'unknown', when the version can't be resolved", async () => {
    mockBuild({ version: "unknown", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    expect(await screen.findByText(/Version unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
  });
});

describe("About — native iOS", () => {
  beforeEach(() => {
    isNativeShell.mockReturnValue(true);
  });

  it("shows the iOS app version and build number alongside the Web version", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    getInfo.mockResolvedValue({ name: "MyKhaya", id: "app.mykhaya", build: "8", version: "0.1.0" });

    render(<About />);

    await waitFor(() => expect(screen.getByText(/0\.1\.0 \(Build 8\)/)).toBeInTheDocument());
    expect(screen.getByText("iOS app")).toBeInTheDocument();
    expect(screen.getByText("Web")).toBeInTheDocument();
  });

  it("omits the iOS app row rather than showing fake data when native metadata fails", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    getInfo.mockRejectedValue(new Error("unavailable"));

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText("iOS app")).not.toBeInTheDocument();
  });
});

describe("About — native Android", () => {
  beforeEach(() => {
    isNativeShell.mockReturnValue(true);
    nativePlatform.mockReturnValue("android");
  });

  it("shows the Android app version and build number, not iOS", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    getInfo.mockResolvedValue({ name: "MyKhaya", id: "app.mykhaya.mobile", build: "8", version: "0.1.0" });

    render(<About />);

    await waitFor(() => expect(screen.getByText(/0\.1\.0 \(Build 8\)/)).toBeInTheDocument());
    expect(screen.getByText("Android app")).toBeInTheDocument();
    expect(screen.queryByText("iOS app")).not.toBeInTheDocument();
  });

  it("shows Push provider as FCM, not APNs", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("Push provider");
    expect(screen.getByText("FCM")).toBeInTheDocument();
    expect(screen.queryByText("APNs")).not.toBeInTheDocument();
  });

  it("shows the same permission/registration diagnostics rows as iOS, unmodified", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePermission.status = "denied";
    nativePushDiagnostics.mockReturnValue({ tokenPresent: false, registered: false });

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.getByText("Off")).toBeInTheDocument();
    expect(screen.getByText("Not registered")).toBeInTheDocument();
  });
});

describe("About — native Notifications diagnostics", () => {
  beforeEach(() => {
    isNativeShell.mockReturnValue(true);
  });

  it("does not appear at all outside the native shell", async () => {
    isNativeShell.mockReturnValue(false);
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0 (Web)");
    expect(screen.queryByText("Notification permission")).not.toBeInTheDocument();
  });

  it("shows the live permission status independent of push-registration state", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePermission.status = "granted";
    nativePushDiagnostics.mockReturnValue({ tokenPresent: false, registered: false });

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.getByText("Granted")).toBeInTheDocument();
    expect(screen.getByText("Not registered")).toBeInTheDocument();
    expect(screen.getByText("Not present")).toBeInTheDocument();
  });

  it("shows Registered/Present when a device has registered", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Registered");
    expect(screen.getByText("Present")).toBeInTheDocument();
  });

  it("never shows the raw device token — only masked Present/Not present", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Present");
    expect(screen.queryByText("native-token")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{32,}/i);
  });

  it("shows Push provider as APNs", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("Push provider");
    expect(screen.getByText("APNs")).toBeInTheDocument();
  });

  it("omits the Last registration row rather than showing a fake value when never registered", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    window.localStorage.removeItem("mykhaya.native.push.last-registered-at");

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.queryByText("Last registration")).not.toBeInTheDocument();
  });

  it("shows a formatted Last registration timestamp when one is present", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    window.localStorage.setItem("mykhaya.native.push.last-registered-at", String(Date.UTC(2026, 0, 1)));

    render(<About />);

    await screen.findByText("Last registration");
    window.localStorage.removeItem("mykhaya.native.push.last-registered-at");
  });

  it("shows Off when notification permission is denied, distinct from push-registration status", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
    nativePermission.status = "denied";
    nativePushDiagnostics.mockReturnValue({ tokenPresent: true, registered: true });

    render(<About />);

    await screen.findByText("Notification permission");
    expect(screen.getByText("Off")).toBeInTheDocument();
    // Registration can still show "Registered" even though permission now
    // reads denied (e.g. revoked after a previous successful registration) —
    // the two are independent facts, neither overwrites the other.
    expect(screen.getByText("Registered")).toBeInTheDocument();
  });
});

describe("About — Service Status link", () => {
  it("links to the existing Service Status page", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toHaveAttribute("href", "/service-status");
  });
});

const termsDoc = {
  key: "terms",
  display_name: "Terms & Conditions",
  audience: "adult" as const,
  action_verb: "accept" as const,
  acceptance_required: true,
  current_version: "1.0",
  current_version_id: "v-terms-1",
  effective_date: "2026-09-01",
};
const privacyDoc = {
  ...termsDoc,
  key: "privacy",
  display_name: "Privacy Policy",
  action_verb: "acknowledge" as const,
  current_version_id: "v-privacy-1",
};
const childrenDoc = {
  ...termsDoc,
  key: "children_privacy",
  display_name: "Family & Children's Privacy",
  audience: "child" as const,
  current_version_id: "v-children-1",
};

function statusEntry(overrides: Record<string, unknown>) {
  return {
    document_key: "terms",
    display_name: "Terms & Conditions",
    audience: "adult",
    action_verb: "accept",
    current_version_id: "v-terms-1",
    current_version_label: "1.0",
    effective_date: "2026-09-01",
    required: true,
    satisfied: true,
    last_version_label: "1.0",
    last_version_id: "v-terms-1",
    last_accepted_at: "2026-09-29T14:32:00Z",
    is_test: false,
    ...overrides,
  };
}

describe("About — Legal & Compliance", () => {
  beforeEach(() => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });
  });

  it("shows a polished empty-state panel, not a loose line of text, when nothing is published", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    const heading = await screen.findByRole("heading", { name: "No legal documents published yet" });
    expect(heading.closest(".legal-empty-state")).not.toBeNull();
    expect(
      screen.getByText("Your current legal documents will appear here when they become available."),
    ).toBeInTheDocument();
    // "Keeping you informed" still renders underneath the empty state.
    expect(screen.getByText("Keeping you informed")).toBeInTheDocument();
  });

  it("shows each applicable document with its current version", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc, privacyDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [
        statusEntry({}),
        statusEntry({
          document_key: "privacy",
          action_verb: "acknowledge",
          current_version_id: "v-privacy-1",
          last_version_id: "v-privacy-1",
        }),
      ],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText("Terms & Conditions")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, element) => Boolean(element?.textContent?.startsWith("Version 1.0")))
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("Privacy Policy")).toBeInTheDocument();
  });

  it("shows Accepted with the recorded timestamp for Terms", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [statusEntry({})],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText(/Accepted$/)).toBeInTheDocument();
    expect(screen.getByText(/Accepted on/)).toBeInTheDocument();
  });

  it("shows Acknowledged, not Accepted, for a document with action_verb acknowledge", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([privacyDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [
        statusEntry({
          document_key: "privacy",
          action_verb: "acknowledge",
          current_version_id: "v-privacy-1",
          last_version_id: "v-privacy-1",
        }),
      ],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText(/Acknowledged$/)).toBeInTheDocument();
    expect(screen.getByText(/Acknowledged on/)).toBeInTheDocument();
    expect(screen.queryByText(/^Accepted$/)).not.toBeInTheDocument();
  });

  it("shows Authorised for the Family & Children's Privacy row when a guardian has authorised it", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([childrenDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [],
      children: [
        {
          child_membership_id: "child-1",
          document_key: "children_privacy",
          display_name: "Family & Children's Privacy",
          guardian_authorisation: statusEntry({
            document_key: "children_privacy",
            action_verb: null,
            current_version_id: "v-children-1",
            last_version_id: "v-children-1",
          }),
          child_acknowledgement: null,
        },
      ],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText(/Authorised$/)).toBeInTheDocument();
    expect(screen.getByText(/Authorised on/)).toBeInTheDocument();
  });

  it("shows Review required and no timestamp when re-acceptance is outstanding — never fabricates a date", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [
        statusEntry({
          satisfied: false,
          current_version_label: "2.0",
          last_version_label: "1.0",
          last_accepted_at: "2026-01-01T00:00:00Z",
        }),
      ],
      children: [],
      child_self: null,
      action_required: true,
    });

    render(<About />);

    expect(await screen.findByText("Review required")).toBeInTheDocument();
    expect(screen.queryByText(/Accepted on/)).not.toBeInTheDocument();
  });

  it("marks a TEST version distinctly, never as ordinary production history", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [statusEntry({ is_test: true })],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText("TEST")).toBeInTheDocument();
  });

  it("shows only the Family & Children's Privacy acknowledgement for a managed-child session, never adult Terms", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "c1",
      display_name: "Kiddo",
      principal_type: "managed_child",
    });
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc, childrenDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [],
      children: [],
      child_self: {
        child_membership_id: "child-1",
        document_key: "children_privacy",
        display_name: "Family & Children's Privacy",
        guardian_authorisation: null,
        child_acknowledgement: statusEntry({
          document_key: "children_privacy",
          action_verb: "acknowledge",
          current_version_id: "v-children-1",
          last_version_id: "v-children-1",
        }),
      },
      action_required: false,
    });

    render(<About />);

    expect(await screen.findByText("Family & Children's Privacy")).toBeInTheDocument();
    expect(screen.queryByText("Terms & Conditions")).not.toBeInTheDocument();
  });

  it("links each row to its own document reader", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([termsDoc]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [statusEntry({})],
      children: [],
      child_self: null,
      action_required: false,
    });

    render(<About />);

    const heading = await screen.findByRole("heading", { name: "Terms & Conditions" });
    expect(heading.closest("a")).toHaveAttribute("href", "/about/legal/terms");
  });
});
