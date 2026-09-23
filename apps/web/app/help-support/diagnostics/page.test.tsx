import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
});
