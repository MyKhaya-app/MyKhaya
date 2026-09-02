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
    },
  };
});

const { isNativeShell } = vi.hoisted(() => ({ isNativeShell: vi.fn(() => false) }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell }));

const { getInfo } = vi.hoisted(() => ({ getInfo: vi.fn() }));
vi.mock("@capacitor/app", () => ({ App: { getInfo } }));

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

    await screen.findByText("0.1.0");
    expect(screen.queryByText(/iOS app/i)).not.toBeInTheDocument();
    expect(getInfo).not.toHaveBeenCalled();
  });

  it("does not show an Environment row in production", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    await screen.findByText("0.1.0");
    expect(screen.queryByText("Environment")).not.toBeInTheDocument();
  });

  it("shows a Development environment row only on a development build", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "development", channel: "development" });

    render(<About />);

    await screen.findByText("Development");
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

describe("About — Service Status link", () => {
  it("links to the existing Service Status page", async () => {
    mockBuild({ version: "0.1.0", commit: "abc", build_time: "now", environment: "production", channel: "stable" });

    render(<About />);

    const heading = await screen.findByRole("heading", { name: "Service Status" });
    expect(heading.closest("a")).toHaveAttribute("href", "/service-status");
  });
});
