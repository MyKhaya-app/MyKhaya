import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportTicketsPage from "./page";

const replace = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParams,
  usePathname: () => "/control-centre/support/tickets",
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const tickets = [
  {
    id: "t1",
    reference: "MK-1001",
    type: "bug",
    status: "open",
    priority: "elevated",
    subject: "Calendar save fails",
    source: "ios",
    app_area: "calendar",
    requester_display_name: "Megan Hales",
    requester_email: "megan@example.com",
    group_id: "home-1",
    group_name: "Hales Home",
    assigned_admin_id: null,
    assigned_admin_display_name: null,
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
  },
];

function mockList(
  overrides: { items?: typeof tickets; next_page?: number | null } = {},
) {
  get.mockImplementation((path: string) => {
    if (path === "/administrators") return Promise.resolve([{ id: "a1", display_name: "Ada Admin" }]);
    if (path.startsWith("/support/tickets")) {
      return Promise.resolve({
        items: overrides.items ?? tickets,
        next_page: overrides.next_page ?? null,
      });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  searchParams = new URLSearchParams();
  mockList();
});

describe("Support tickets queue", () => {
  it("renders the table with expected columns and row content", async () => {
    render(<SupportTicketsPage />);
    expect(await screen.findByText("MK-1001")).toBeInTheDocument();
    expect(screen.getByText("Calendar save fails")).toBeInTheDocument();
    expect(screen.getByText("Megan Hales")).toBeInTheDocument();
    expect(screen.getByText("Hales Home")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Reference" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Priority" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "User" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "App area" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Platform" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Assigned" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MK-1001" })).toHaveAttribute("href", "/support/tickets/t1");
  });

  it("shows a loading state before the first response resolves", () => {
    get.mockImplementation(() => new Promise(() => {}));
    render(<SupportTicketsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("MK-1001")).not.toBeInTheDocument();
  });

  it("shows a safe error message, not a raw exception, when the queue fails to load", async () => {
    get.mockImplementation((path: string) =>
      path === "/administrators"
        ? Promise.resolve([])
        : Promise.reject(new ApiError(500, "Could not load support tickets.")),
    );
    render(<SupportTicketsPage />);
    expect(await screen.findByText(/Unable to load tickets/)).toBeInTheDocument();
  });

  it("submits the search query into the URL", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.type(screen.getByLabelText("Search"), "battery");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        expect.stringContaining("query=battery"),
        expect.anything(),
      ),
    );
    expect(replace).toHaveBeenCalledWith(expect.stringContaining("page=1"), expect.anything());
  });

  it("updates the URL when the status filter changes", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.selectOptions(screen.getByLabelText("Status"), "resolved");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("status=resolved"), expect.anything()),
    );
  });

  it("updates the URL when the type filter changes", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.selectOptions(screen.getByLabelText("Type"), "feedback");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("type=feedback"), expect.anything()),
    );
  });

  it("updates the URL when the priority filter changes", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.selectOptions(screen.getByLabelText("Priority"), "blocking");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("priority=blocking"), expect.anything()),
    );
  });

  it("updates the URL when the platform filter changes", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.selectOptions(screen.getByLabelText("Platform"), "android");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("source=android"), expect.anything()),
    );
  });

  it("updates the URL when the app-area filter changes", async () => {
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    await user.selectOptions(screen.getByLabelText("App area"), "budget");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("app_area=budget"), expect.anything()),
    );
  });

  it("shows pagination controls and requests the next page from the URL", async () => {
    mockList({ next_page: 2 });
    const user = userEvent.setup();
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(next);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("page=2"), expect.anything()),
    );
  });

  it("carries the current page from the URL into the ticket list request", async () => {
    searchParams = new URLSearchParams({ page: "3", status: "open" });
    render(<SupportTicketsPage />);
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(expect.stringContaining("page=3")),
    );
    expect(get).toHaveBeenCalledWith(expect.stringContaining("status=open"));
  });

  it("shows an empty state, not a broken table, when no tickets match", async () => {
    mockList({ items: [] });
    render(<SupportTicketsPage />);
    expect(await screen.findByText("No tickets match these filters.")).toBeInTheDocument();
  });

  it("hides the Clear action when no search or filter is active", async () => {
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });

  it("shows Clear once a filter is active, and resets search/filters/page when clicked", async () => {
    searchParams = new URLSearchParams({ status: "open", query: "battery" });
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    const clearButton = screen.getByRole("button", { name: "Clear" });

    await userEvent.click(clearButton);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("page=1"), expect.anything()),
    );
    const clearedCall = replace.mock.calls.find(([target]) =>
      (target as string).includes("/support/tickets"),
    );
    expect(clearedCall).toBeDefined();
    const [target] = clearedCall as [string, unknown];
    expect(target).not.toContain("status=");
    expect(target).not.toContain("query=");
  });

  it("keeps every filter control's accessible name in the compact toolbar layout", async () => {
    render(<SupportTicketsPage />);
    await screen.findByText("MK-1001");
    expect(screen.getByLabelText("Search")).toHaveAttribute("placeholder", "Reference, subject, requester…");
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Type")).toBeInTheDocument();
    expect(screen.getByLabelText("Priority")).toBeInTheDocument();
    expect(screen.getByLabelText("Platform")).toBeInTheDocument();
    expect(screen.getByLabelText("App area")).toBeInTheDocument();
    expect(screen.getByLabelText("Assigned to")).toBeInTheDocument();
  });
});
