import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RunDiagnostics from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/diagnostics",
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
  return { ...actual, api: { ...actual.api, me: vi.fn() } };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("config/public")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ support_enabled: true }) });
    if (url.includes("health/live")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "ok" }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: "1.0.0", build_time: "1" }) });
  }) as unknown as typeof fetch;
});

describe("Run diagnostics", () => {
  it("runs checks and exposes rerun/share actions", async () => {
    render(<RunDiagnostics />);
    await screen.findByRole("heading", { name: "Run diagnostics" });
    expect(await screen.findByText("MyKhaya service")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run again/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /report a bug with diagnostics/i })).toHaveAttribute("href", "/help-support/report-bug?diagnostics=1");
  });

  it("keeps every diagnostic row and the share card mounted while checks run", async () => {
    let resolveHealth!: (response: Response) => void;
    const health = new Promise<Response>((resolve) => { resolveHealth = resolve; });
    global.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("health/live")) return health;
      if (url.includes("config/public")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ support_enabled: true }) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: "1.0.0", build_time: "1" }) });
    }) as unknown as typeof fetch;

    render(<RunDiagnostics />);

    for (const label of ["MyKhaya service", "Internet connection", "Notifications", "Account sync", "App version", "Platform"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText(/Checking/).length).toBeGreaterThanOrEqual(8);
    expect(screen.getByRole("heading", { name: "Share diagnostics with support" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run again/i })).toBeDisabled();

    resolveHealth({ ok: true } as Response);
    await waitFor(() => expect(screen.getByText("Passed")).toBeInTheDocument());
    expect(screen.getByText("MyKhaya service")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Share diagnostics with support" })).toBeInTheDocument();
  });

  it("does not start a second run while the first run is active", async () => {
    let resolveHealth!: (response: Response) => void;
    const health = new Promise<Response>((resolve) => { resolveHealth = resolve; });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("health/live")) return health;
      if (url.includes("config/public")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ support_enabled: false }) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: "1.0.0", build_time: "1" }) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<RunDiagnostics />);
    const rerun = screen.getByRole("button", { name: /run again/i });
    fireEvent.click(rerun);
    expect(rerun).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([input]) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return url.includes("health/live");
    })).toHaveLength(1);
    expect(screen.getByText("Share diagnostics with support")).toBeInTheDocument();

    resolveHealth({ ok: true } as Response);
    await waitFor(() => expect(rerun).not.toBeDisabled());
    expect(screen.getByText("Support sharing is unavailable right now.")).toBeInTheDocument();
  });
});
