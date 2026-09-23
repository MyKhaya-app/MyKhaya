import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReportBug from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/report-bug",
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
  return { ...actual, api: { ...actual.api, me: vi.fn(), createSupportTicket: vi.fn(), uploadSupportAttachment: vi.fn() } };
});

vi.mock("@/components/use-notification-permission", () => ({
  useNotificationPermission: () => ({ status: "granted", loading: false }),
}));

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
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: "1.0.0", build_time: "1", commit: "x", environment: "test", channel: "test" }) });
  }) as unknown as typeof fetch;
});

describe("Report a bug", () => {
  it("renders the accessible form when support is enabled", async () => {
    render(<ReportBug />);
    await screen.findByRole("heading", { name: "Report a bug" });
    expect(screen.getByLabelText("What went wrong?")).toBeInTheDocument();
    expect(screen.getByLabelText("What happened?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Minor/i })).toBeChecked();
  });

  it("submits diagnostics and shows the server reference", async () => {
    const user = userEvent.setup();
    const createTicket = api.createSupportTicket as unknown as ReturnType<typeof vi.fn>;
    createTicket.mockResolvedValue({ id: "t1", reference: "MK-1001" });
    render(<ReportBug />);
    await user.type(await screen.findByLabelText("What went wrong?"), "Calendar save fails");
    await user.type(screen.getByLabelText("What happened?"), "The event disappears after saving.");
    await user.click(screen.getByRole("button", { name: /send report/i }));
    await waitFor(() => expect(createTicket).toHaveBeenCalled());
    expect(await screen.findByText("MK-1001")).toBeInTheDocument();
  });
});
