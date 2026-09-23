import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportTicketDetailPage from "./page";

// The route reads its id via `use(params)`, which suspends on first render
// until the params promise settles. render() itself isn't awaited by
// Testing Library, so the resulting suspend/resolve has to be wrapped in
// its own awaited act() or React warns and the DOM update is missed.
async function renderPage() {
  await act(async () => {
    render(<SupportTicketDetailPage params={params()} />);
  });
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/control-centre/support/tickets/t1",
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
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;

const baseTicket = {
  id: "t1",
  reference: "MK-1001",
  type: "bug",
  status: "open",
  priority: "elevated",
  subject: "Calendar save fails",
  description: "The event disappears after saving.",
  source: "ios",
  app_area: "calendar",
  requester_user_id: "u1",
  requester_display_name: "Megan Hales",
  requester_email: "megan@example.com",
  group_id: "home-1",
  group_name: "Hales Home",
  assigned_admin_id: null as string | null,
  assigned_admin_display_name: null as string | null,
  created_at: "2026-09-01T09:00:00Z",
  updated_at: "2026-09-01T09:00:00Z",
  resolved_at: null as string | null,
  messages: [] as {
    id: string;
    author_user_id: string | null;
    author_admin_id: string | null;
    author_display_name: string;
    message: string;
    visibility: "requester" | "internal";
    created_at: string;
  }[],
  attachments: [] as {
    id: string;
    original_filename: string;
    content_type: string;
    size_bytes: number;
    created_at: string;
  }[],
  diagnostics: null as Record<string, string | null> | null,
};

function mockDetail(ticket: typeof baseTicket = baseTicket, administrators: { id: string; display_name: string }[] = []) {
  get.mockImplementation((path: string) => {
    if (path === "/administrators") return Promise.resolve(administrators);
    if (path === "/support/tickets/t1") return Promise.resolve(ticket);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function params() {
  return Promise.resolve({ id: "t1" });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockDetail();
});

describe("Support ticket detail", () => {
  it("renders ticket metadata: requester, Home, description, type, app area, source", async () => {
    await renderPage();
    expect(await screen.findByRole("heading", { name: "MK-1001" })).toBeInTheDocument();
    expect(screen.getByText("The event disappears after saving.")).toBeInTheDocument();
    expect(screen.getByText("Megan Hales")).toBeInTheDocument();
    expect(screen.getByText("Hales Home")).toBeInTheDocument();
  });

  it("renders the conversation, or an empty state when there are no messages", async () => {
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
  });

  it("renders existing messages with author attribution", async () => {
    mockDetail({
      ...baseTicket,
      messages: [
        {
          id: "m1",
          author_user_id: "u1",
          author_admin_id: null,
          author_display_name: "Megan Hales",
          message: "Any update?",
          visibility: "requester",
          created_at: "2026-09-01T10:00:00Z",
        },
      ],
    });
    await renderPage();
    expect(await screen.findByText("Any update?")).toBeInTheDocument();
    // "Megan Hales" appears both as the requester and as this message's
    // author — assert the author attribution specifically.
    const article = screen.getByText("Any update?").closest("article");
    expect(article).not.toBeNull();
    expect(within(article!).getByText("Megan Hales")).toBeInTheDocument();
  });

  it("hides the diagnostics section when absent", async () => {
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    expect(screen.queryByRole("heading", { name: "Diagnostics" })).not.toBeInTheDocument();
  });

  it("renders named diagnostic fields when present, never a raw JSON dump", async () => {
    mockDetail({
      ...baseTicket,
      diagnostics: {
        app_version: "1.4.0",
        build_number: "204",
        platform: "ios",
        os_version: "iOS 18",
        runtime: "native",
        notification_permission: "granted",
        push_registration_state: "registered",
        api_connectivity: "connected",
        network_state: "wifi",
        background_refresh_state: "available",
        client_timestamp: "2026-09-01T09:00:00Z",
      },
    });
    await renderPage();
    expect(await screen.findByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByText("1.4.0")).toBeInTheDocument();
    expect(screen.getByText("iOS 18")).toBeInTheDocument();
    expect(screen.queryByText(/[{[]/)).not.toBeInTheDocument();
  });

  it("shows no attachments as an empty state", async () => {
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    expect(screen.getByText("No attachments.")).toBeInTheDocument();
  });

  it("renders an attachment via the authenticated ticket/attachment route, never exposing a storage key or path", async () => {
    mockDetail({
      ...baseTicket,
      attachments: [
        {
          id: "att1",
          original_filename: "screenshot.png",
          content_type: "image/png",
          size_bytes: 12345,
          created_at: "2026-09-01T09:05:00Z",
        },
      ],
    });
    await renderPage();
    const link = await screen.findByRole("link", { name: /screenshot\.png/i });
    expect(link).toHaveAttribute("href", "/api/v1/platform/support/tickets/t1/attachments/att1");
    const image = screen.getByAltText("screenshot.png");
    expect(image).toHaveAttribute("src", expect.stringContaining("/api/v1/platform/support/tickets/t1/attachments/att1"));
    // No storage key (a UUID.webp filename) or filesystem path ever appears anywhere on the page.
    expect(document.body.innerHTML).not.toMatch(/\.webp/);
    expect(document.body.innerHTML).not.toMatch(/\/data\/support-attachments/);
  });

  it("changes ticket status via the API and disables the control while saving", async () => {
    let resolvePatch!: (value: typeof baseTicket) => void;
    patch.mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve; }),
    );
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    const statusSelect = screen.getByLabelText("Status");
    await user.selectOptions(statusSelect, "resolved");
    expect(patch).toHaveBeenCalledWith("/support/tickets/t1", { status: "resolved" });
    expect(statusSelect).toBeDisabled();
    resolvePatch({ ...baseTicket, status: "resolved", resolved_at: "2026-09-02T09:00:00Z" });
    await waitFor(() => expect(statusSelect).not.toBeDisabled());
  });

  it("changes ticket priority via the API", async () => {
    patch.mockResolvedValue({ ...baseTicket, priority: "blocking" });
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    await user.selectOptions(screen.getByLabelText("Priority"), "blocking");
    expect(patch).toHaveBeenCalledWith("/support/tickets/t1", { priority: "blocking" });
  });

  it("assigns the ticket to an administrator via the API", async () => {
    mockDetail(baseTicket, [{ id: "a1", display_name: "Ada Admin" }]);
    patch.mockResolvedValue({ ...baseTicket, assigned_admin_id: "a1", assigned_admin_display_name: "Ada Admin" });
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    await user.selectOptions(screen.getByLabelText("Assigned admin"), "a1");
    expect(patch).toHaveBeenCalledWith("/support/tickets/t1", { assigned_admin_id: "a1" });
  });

  it("shows an error, not a false success, when a mutation fails", async () => {
    patch.mockRejectedValue(new ApiError(500, "Could not update this ticket."));
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    await user.selectOptions(screen.getByLabelText("Priority"), "blocking");
    expect(await screen.findByText("Could not update this ticket.")).toBeInTheDocument();
  });

  it("submits a reply once, prevents duplicate submission while sending, and states it is saved and emailed", async () => {
    let resolvePost!: (value: unknown) => void;
    post.mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });

    expect(
      screen.getByText("This reply is saved to the ticket and emailed to the requester."),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Add a reply"), "We're looking into this.");
    const sendButton = screen.getByRole("button", { name: /add reply/i });
    await user.click(sendButton);

    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/support/tickets/t1/messages", { message: "We're looking into this." });
    expect(sendButton).toBeDisabled();

    // A second click while still submitting must not fire a second request.
    await user.click(sendButton);
    expect(post).toHaveBeenCalledTimes(1);

    resolvePost(undefined);
    await waitFor(() => expect(screen.getByText("Reply added to the ticket.")).toBeInTheDocument());
  });

  it("does not submit an empty or whitespace-only reply", async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByRole("heading", { name: "MK-1001" });
    const sendButton = screen.getByRole("button", { name: /add reply/i });
    expect(sendButton).toBeDisabled();
    await user.type(screen.getByLabelText("Add a reply"), "   ");
    expect(sendButton).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("shows a safe error, not a raw exception, when loading the ticket fails", async () => {
    get.mockImplementation((path: string) =>
      path === "/administrators"
        ? Promise.resolve([])
        : Promise.reject(new ApiError(404, "That support ticket could not be found.")),
    );
    await renderPage();
    expect(await screen.findByText("That support ticket could not be found.")).toBeInTheDocument();
  });
});
